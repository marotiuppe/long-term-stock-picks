/* Holdings tracking, shared by the stock, list, dashboard, portfolio and settings pages.
   - pure helpers for the form's arithmetic and checks (also loaded by node for the tests),
   - Mine: the user's positions as the server computes them,
   - the add / add more / record a sale / edit form (a modal on desktop, a bottom sheet on a phone),
   - the "My position" card, position settings and transaction import.
   Needs common.js (f, dt, ic, esc, $) and shell.js (Shell.sheet). Amounts are rupees with Indian digit grouping. */
(function () {
  'use strict';

  // ---------- pure helpers ----------
  function num(v) {
    if (v === null || v === undefined || typeof v === 'boolean') return NaN;
    if (typeof v === 'number') return v;
    var s = String(v).replace(/[,\s₹]/g, '').replace(/^rs\.?/i, '');
    return s === '' ? NaN : Number(s);
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function isoToday(d) { d = d || new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function inr(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return '-';
    d = d === undefined ? 0 : d;
    var s = Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
    return (n < 0 ? '-' : '') + '₹' + s;
  }
  function signedInr(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return '-';
    return (n > 0 ? '+' : n < 0 ? '-' : '') + inr(Math.abs(n), d === undefined ? 0 : d);
  }
  function signedPct(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return '-';
    return (n > 0 ? '+' : n < 0 ? '-' : '') + Math.abs(n).toFixed(d === undefined ? 1 : d) + '%';
  }
  function qtyFromAmount(amount, price) {
    amount = num(amount); price = num(price);
    if (!(amount > 0) || !(price > 0)) return { qty: 0, left: amount > 0 ? amount : 0 };
    var q = Math.floor(amount / price + 1e-9);
    return { qty: q, left: Math.round((amount - q * price) * 100) / 100 };
  }
  var LIMITS = { qty: 10000000, price: 10000000, feeShare: 0.25 };

  // f: {side, mode ('qty'|'amount'), qty, amount, price, date, fees, note, symbol}; c: {today, held, avg}
  // -> {errors:{field:msg}, qty, price, fees, gross, total, realized, left}
  function checkLot(f, c) {
    var e = {}, side = f.side === 'sell' ? 'sell' : 'buy', out = { errors: e, side: side };
    var price = num(f.price), fees = (f.fees === '' || f.fees == null) ? 0 : num(f.fees), qty = NaN, left = 0;
    if (!/^[A-Za-z0-9&-]{1,20}$/.test(String(f.symbol || '').trim().replace(/\.NS$/i, ''))) e.symbol = 'Enter a valid symbol, for example TCS';
    if (!(price > 0)) e.price = isNaN(price) ? 'Enter the price per share' : 'Price must be more than 0';
    else if (price > LIMITS.price) e.price = 'Price looks too large (limit ₹1,00,00,000)';
    if (f.mode === 'amount' && side === 'buy') {
      var amt = num(f.amount);
      if (!(amt > 0)) e.amount = isNaN(amt) ? 'Enter the amount you invested' : 'Amount must be more than 0';
      else if (price > 0) {
        var r = qtyFromAmount(amt, price); qty = r.qty; left = r.left;
        if (qty < 1) e.amount = 'That amount is less than the price of one share (' + inr(price, 2) + ')';
      }
    } else {
      qty = num(f.qty);
      if (isNaN(qty)) e.qty = 'Enter the number of shares';
      else if (!(qty > 0)) e.qty = 'Quantity must be more than 0';
      else if (qty !== Math.floor(qty)) e.qty = 'Quantity must be a whole number of shares';
      else if (qty > LIMITS.qty) e.qty = 'Quantity looks too large (limit 1,00,00,000 shares)';
    }
    if (side === 'sell' && qty > 0 && c && c.held != null && qty > c.held) e.qty = 'You hold ' + c.held + ' share' + (c.held === 1 ? '' : 's') + ' of ' + (f.symbol || 'this stock') + ', so you cannot sell ' + qty;
    if (!f.date) e.date = 'Pick the date of the transaction';
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || isNaN(new Date(f.date + 'T00:00:00'))) e.date = 'Date must look like 2026-10-24';
    else if (c && f.date > c.today) e.date = 'Date cannot be in the future';
    else if (f.date < '1990-01-01') e.date = 'Date is too far in the past';
    if (isNaN(fees)) e.fees = 'Charges must be a number';
    else if (fees < 0) e.fees = 'Charges cannot be negative';
    else if (qty > 0 && price > 0 && fees > qty * price * LIMITS.feeShare) e.fees = 'Charges look too high for this amount. Check the figure';
    if (String(f.note || '').length > 200) e.note = 'Note is too long (200 characters at most)';
    out.qty = qty > 0 ? qty : 0; out.price = price > 0 ? price : 0; out.fees = fees > 0 ? fees : 0; out.left = left;
    out.gross = out.qty * out.price;
    if (side === 'buy') out.total = out.gross + out.fees;
    else {
      out.total = out.gross - out.fees;
      if (c && c.avg > 0 && out.qty > 0) out.realized = out.qty * (out.price - c.avg) - out.fees;
    }
    return out;
  }

  var pure = { num: num, inr: inr, signedInr: signedInr, signedPct: signedPct, qtyFromAmount: qtyFromAmount, checkLot: checkLot, isoToday: isoToday };
  if (typeof module !== 'undefined' && module.exports) { module.exports = pure; }
  if (typeof document === 'undefined') return;

  // ---------- state ----------
  var $ = function (id) { return document.getElementById(id); };
  var Mine = { me: null, pos: {}, summary: null, error: null, promise: null };
  function hapi(method, url, body) {
    var opt = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return (window.Session ? window.Session.fetch(url, opt) : fetch(url, opt)).then(function (r) {
      var ct = r.headers.get('content-type') || '';
      if (!/json/i.test(ct)) throw new Error('The service did not answer. Is the app still running?');
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || 'Request failed'); return j; });
    });
  }
  Mine.load = function (force) {
    if (Mine.promise && !force) return Mine.promise;
    Mine.promise = hapi('GET', '/api/me').then(function (me) {
      Mine.me = me; Mine.summary = me.summary; Mine.error = null; Mine.pos = {};
      (me.positions || []).forEach(function (p) { Mine.pos[p.symbol] = p; });
      document.dispatchEvent(new CustomEvent('mine:update'));
      return me;
    }).catch(function (e) { Mine.error = e.message; Mine.promise = null; document.dispatchEvent(new CustomEvent('mine:update')); throw e; });
    return Mine.promise;
  };
  Mine.has = function () { return !!(Mine.me && Mine.me.positions && Mine.me.positions.length); };

  // ---------- small UI helpers ----------
  function E(s) { return window.esc ? window.esc(s) : String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function icon(n, c) { return window.Shell ? window.Shell.icon(n, c) : ''; }
  function arrowFor(n) { return n > 0 ? icon('arrow-up-right', 'sm') : n < 0 ? icon('arrow-down-right', 'sm') : ''; }
  // a signed figure with an arrow, never colour alone
  function chg(abs, pct, d) {
    if (abs === null || abs === undefined) return '<span class="mu">-</span>';
    var cls = abs > 0 ? 'up' : abs < 0 ? 'dn' : 'mu';
    return '<span class="chg ' + cls + '">' + arrowFor(abs) + signedInr(abs, d === undefined ? 0 : d) + (pct === null || pct === undefined ? '' : ' <span class="chg-p">(' + signedPct(pct) + ')</span>') + '</span>';
  }
  function say(msg) { var l = $('hlive'); if (!l) { l = document.createElement('div'); l.id = 'hlive'; l.className = 'sr'; l.setAttribute('role', 'status'); l.setAttribute('aria-live', 'polite'); document.body.appendChild(l); } l.textContent = ''; setTimeout(function () { l.textContent = msg; }, 30); }
  function longDate(s) { if (!s) return 'date not recorded'; var d = new Date(s + 'T00:00:00'); return isNaN(d) ? s : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); }

  function confirmSheet(o) {
    Shell.sheet({ title: o.title, html: '<p class="cf-t">' + E(o.text) + '</p><div class="lf-act"><button type="button" class="btn" data-x>' + E(o.keep || 'Keep it') + '</button><button type="button" class="btn danger" id="cf-go">' + E(o.confirm || 'Delete') + '</button></div>',
      onOpen: function (b, api) { b.querySelector('#cf-go').onclick = function () { this.disabled = true; Promise.resolve(o.onConfirm()).then(function () { api.close(); }).catch(function (e) { b.querySelector('.cf-t').textContent = e.message; b.querySelector('#cf-go').disabled = false; }); }; } });
  }

  // ---------- the transaction form ----------
  /* o: {symbol, name, price, side ('buy'|'sell'), lot (to edit), onSaved(resp)} */
  function openLotForm(o) {
    o = o || {};
    var edit = !!o.lot, sym = o.symbol || (o.lot && o.lot.symbol) || '';
    var side = edit ? o.lot.side : (o.side || 'buy'), mode = 'qty', touched = {}, tried = false;
    var p = Mine.pos[sym], held = p ? p.qty : 0, avg = p ? p.avg_cost : null;
    if (edit && p) { held = p.qty; avg = p.avg_cost; }
    var price0 = o.price != null ? o.price : (p && p.price) || (window.D && D.stocks && (D.stocks.find(function (s) { return s.symbol === sym; }) || {}).price) || null;
    var title = edit ? 'Edit transaction' : side === 'sell' ? 'Record a sale' : (held ? 'Add more shares' : 'Add to my holdings');
    var known = (window.D && D.stocks) ? D.stocks.map(function (s) { return '<option value="' + E(s.symbol) + '">' + E(s.name || '') + '</option>'; }).join('') : '';
    var L = edit ? o.lot : {};
    var html =
      '<form class="lf" id="lf" novalidate>' +
      (edit ? '' : '<div class="seg" role="group" aria-label="Transaction type" id="lf-side"><button type="button" class="tab" data-s="buy">Buy</button><button type="button" class="tab" data-s="sell">Sell</button></div>') +
      '<div class="lf-f"><label for="lf-sym">Stock</label>' +
      (o.symbol || edit ? '<input id="lf-sym" class="lf-in" value="' + E(sym) + '" readonly aria-describedby="lf-sym-n"><p class="lf-n" id="lf-sym-n">' + E(o.name || '') + '</p>'
        : '<input id="lf-sym" class="lf-in" list="lf-syms" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="TCS" aria-describedby="lf-sym-e"><datalist id="lf-syms">' + known + '</datalist><p class="lf-e" id="lf-sym-e" role="alert"></p>') + '</div>' +
      '<div class="seg" role="group" aria-label="Enter by" id="lf-mode" hidden><button type="button" class="tab on" data-m="qty">Quantity</button><button type="button" class="tab" data-m="amount">Amount invested</button></div>' +
      '<div class="lf-row"><div class="lf-f" id="lf-qf"><label for="lf-qty">Quantity (shares)</label><input id="lf-qty" class="lf-in" inputmode="numeric" autocomplete="off" aria-describedby="lf-qty-e"><p class="lf-e" id="lf-qty-e" role="alert"></p></div>' +
      '<div class="lf-f" id="lf-af" hidden><label for="lf-amt">Amount invested (₹)</label><input id="lf-amt" class="lf-in" inputmode="decimal" autocomplete="off" aria-describedby="lf-amt-e"><p class="lf-e" id="lf-amt-e" role="alert"></p></div>' +
      '<div class="lf-f"><label for="lf-price" id="lf-pl">Buy price per share (₹)</label><input id="lf-price" class="lf-in" inputmode="decimal" autocomplete="off" aria-describedby="lf-price-e"><p class="lf-e" id="lf-price-e" role="alert"></p><button type="button" class="lf-use" id="lf-use" hidden></button></div></div>' +
      '<div class="lf-sum" id="lf-sum" aria-live="polite"></div>' +
      '<div class="lf-row"><div class="lf-f"><label for="lf-date">Date</label><input id="lf-date" class="lf-in" type="date" max="' + isoToday() + '" aria-describedby="lf-date-e"><p class="lf-e" id="lf-date-e" role="alert"></p></div>' +
      '<div class="lf-f"><label for="lf-fees">Brokerage and charges (₹, optional)</label><input id="lf-fees" class="lf-in" inputmode="decimal" autocomplete="off" aria-describedby="lf-fees-e"><p class="lf-e" id="lf-fees-e" role="alert"></p></div></div>' +
      '<div class="lf-f"><label for="lf-note">Note (optional)</label><input id="lf-note" class="lf-in" maxlength="200" autocomplete="off" aria-describedby="lf-note-e"><p class="lf-e" id="lf-note-e" role="alert"></p></div>' +
      '<p class="lf-err" id="lf-form-e" role="alert"></p>' +
      '<div class="lf-act">' + (edit ? '<button type="button" class="btn danger lf-del" id="lf-del">' + icon('trash', 'sm') + 'Delete</button>' : '') +
      '<button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn pri" id="lf-save">' + (edit ? 'Save changes' : 'Save') + '</button></div></form>';

    Shell.sheet({ title: title, html: html, onOpen: function (b, api) {
      var q = function (id) { return b.querySelector('#' + id); }, form = q('lf');
      function val() { return { symbol: q('lf-sym').value.trim().toUpperCase().replace(/\.NS$/, ''), side: side, mode: mode, qty: q('lf-qty').value, amount: q('lf-amt').value, price: q('lf-price').value, date: q('lf-date').value, fees: q('lf-fees').value, note: q('lf-note').value }; }
      function ctx() {
        var s = val().symbol, pp = Mine.pos[s];
        var h = pp ? pp.qty : 0;
        if (edit && L.side === 'buy' && L.symbol === s) h = (pp ? pp.qty : 0) - L.qty;    // editing a buy: what it adds is not yet "held"
        if (edit && L.side === 'sell' && L.symbol === s) h = (pp ? pp.qty : 0) + L.qty;
        return { today: isoToday(), held: side === 'sell' ? h : null, avg: pp ? pp.avg_cost : null };
      }
      function render() {
        var v = val(), c = ctx(), r = checkLot(v, c), sy = v.symbol;
        b.querySelectorAll('#lf-side .tab').forEach(function (t) { var on = t.dataset.s === side; t.classList.toggle('on', on); t.setAttribute('aria-pressed', on); });
        b.querySelectorAll('#lf-mode .tab').forEach(function (t) { var on = t.dataset.m === mode; t.classList.toggle('on', on); t.setAttribute('aria-pressed', on); });
        q('lf-mode').hidden = !(side === 'buy' && !edit);
        q('lf-qf').hidden = (side === 'buy' && mode === 'amount' && !edit); q('lf-af').hidden = !(side === 'buy' && mode === 'amount' && !edit);
        q('lf-pl').textContent = (side === 'sell' ? 'Sell' : 'Buy') + ' price per share (₹)';
        var cur = Mine.pos[sy] && Mine.pos[sy].price || (window.D && D.stocks && (D.stocks.find(function (s) { return s.symbol === sy; }) || {}).price) || price0;
        var use = q('lf-use'); if (cur && !edit) { use.hidden = false; use.textContent = 'Use today’s price ' + inr(cur, 2); use.dataset.p = cur; } else use.hidden = true;
        ['symbol', 'qty', 'amount', 'price', 'date', 'fees', 'note'].forEach(function (k) {
          var id = { symbol: 'lf-sym', amount: 'lf-amt' }[k] || 'lf-' + k, el = q(id), er = q(id + '-e');
          var show = (touched[k] || tried) && r.errors[k];
          if (er) er.textContent = show ? r.errors[k] : '';
          if (el) { el.setAttribute('aria-invalid', show ? 'true' : 'false'); }
        });
        var s = '';
        if (r.qty > 0 && r.price > 0) {
          if (side === 'buy') {
            s = '<div class="lf-big">Total invested <b>' + inr(r.total, 2) + '</b></div><div class="lf-sub">' + r.qty + ' share' + (r.qty === 1 ? '' : 's') + ' × ' + inr(r.price, 2) + (r.fees ? ' + ' + inr(r.fees, 2) + ' charges' : '') + (mode === 'amount' && r.left > 0 ? '. ' + inr(r.left, 2) + ' is left over, not enough for another share.' : '') + '</div>';
          } else {
            s = '<div class="lf-big">Sale proceeds <b>' + inr(r.total, 2) + '</b></div><div class="lf-sub">' + r.qty + ' share' + (r.qty === 1 ? '' : 's') + ' × ' + inr(r.price, 2) + (r.fees ? ' − ' + inr(r.fees, 2) + ' charges' : '') +
              (r.realized != null ? '. Realised P&amp;L against your average cost of ' + inr(c.avg, 2) + ': ' + chg(r.realized, null, 2) : '') + '</div>';
          }
        } else s = '<div class="lf-sub">The total appears here as you type.</div>';
        q('lf-sum').innerHTML = s;
        return r;
      }
      if (edit) {
        q('lf-qty').value = L.qty; q('lf-price').value = L.price; q('lf-date').value = L.date || ''; q('lf-fees').value = L.fees || ''; q('lf-note').value = L.note || '';
      } else {
        q('lf-date').value = isoToday();
        if (o.symbol) q('lf-sym').value = o.symbol;
        if (side === 'sell' && !held) { /* sell tab stays selectable, the form explains */ }
      }
      form.addEventListener('input', function (e) { var k = { 'lf-sym': 'symbol', 'lf-qty': 'qty', 'lf-amt': 'amount', 'lf-price': 'price', 'lf-date': 'date', 'lf-fees': 'fees', 'lf-note': 'note' }[e.target.id]; if (k) touched[k] = touched[k] || e.type === 'change'; render(); });
      form.addEventListener('focusout', function (e) { var k = { 'lf-sym': 'symbol', 'lf-qty': 'qty', 'lf-amt': 'amount', 'lf-price': 'price', 'lf-date': 'date', 'lf-fees': 'fees', 'lf-note': 'note' }[e.target.id]; if (k) { touched[k] = true; render(); } });
      b.querySelectorAll('#lf-side .tab').forEach(function (t) { t.onclick = function () { side = t.dataset.s; render(); }; });
      b.querySelectorAll('#lf-mode .tab').forEach(function (t) { t.onclick = function () { mode = t.dataset.m; render(); }; });
      q('lf-use').onclick = function () { q('lf-price').value = this.dataset.p; touched.price = true; render(); q('lf-price').focus(); };
      if (edit) q('lf-del').onclick = function () {
        confirmSheet({ title: 'Delete this transaction?', text: 'This removes the ' + L.side + ' of ' + L.qty + ' ' + L.symbol + ' on ' + longDate(L.date) + ' and changes your average price and invested amount.', confirm: 'Delete transaction', keep: 'Keep it',
          onConfirm: function () { return hapi('DELETE', '/api/lots?id=' + L.id).then(function (resp) { return Mine.load(true).then(function () { api.close(); say('Transaction deleted'); if (o.onSaved) o.onSaved(resp); }); }); } });
      };
      form.addEventListener('submit', function (e) {
        e.preventDefault(); tried = true;
        var r = render(), first = ['symbol', 'qty', 'amount', 'price', 'date', 'fees', 'note'].filter(function (k) { return r.errors[k]; })[0];   // top to bottom, as on screen
        if (first) { var id = { symbol: 'lf-sym', amount: 'lf-amt' }[first] || 'lf-' + first; q(id).focus(); return; }
        var body = { symbol: val().symbol, side: side, qty: r.qty, price: r.price, date: val().date, fees: r.fees, note: val().note.trim() };
        var btn = q('lf-save'); btn.disabled = true; btn.textContent = 'Saving…'; q('lf-form-e').textContent = '';
        hapi(edit ? 'PUT' : 'POST', '/api/lots' + (edit ? '?id=' + L.id : ''), body).then(function (resp) {
          return Mine.load(true).then(function () { api.close(); say((side === 'sell' ? 'Sale' : 'Purchase') + ' of ' + body.qty + ' ' + body.symbol + ' saved'); if (o.onSaved) o.onSaved(resp); });
        }).catch(function (err) { q('lf-form-e').textContent = err.message; btn.disabled = false; btn.textContent = edit ? 'Save changes' : 'Save'; });
      });
      render();
    } });
  }

  // ---------- position settings: target weight, review level, sector ----------
  function openPositionSettings(sym, name, after) {
    var st = (Mine.pos[sym] && { target_weight: Mine.pos[sym].target_weight, review_price: Mine.pos[sym].review_price, sector: Mine.pos[sym].sector }) || {};
    Shell.sheet({ title: sym + ' settings', html:
      '<form class="lf" id="ps" novalidate><p class="lf-n">' + E(name || '') + ' Used by the alert rules. All three are optional.</p>' +
      '<div class="lf-f"><label for="ps-w">Target weight in the portfolio (%)</label><input id="ps-w" class="lf-in" inputmode="decimal" value="' + (st.target_weight == null ? '' : st.target_weight) + '" placeholder="for example 10"></div>' +
      '<div class="lf-f"><label for="ps-r">Review level (₹)</label><input id="ps-r" class="lf-in" inputmode="decimal" value="' + (st.review_price == null ? '' : st.review_price) + '" placeholder="alert if the price reaches or falls below this"></div>' +
      '<div class="lf-f"><label for="ps-s">Sector (your own label)</label><input id="ps-s" class="lf-in" maxlength="40" value="' + E(st.sector || '') + '" placeholder="for example Banking" list="ps-sl"><datalist id="ps-sl">' + sectors().map(function (s) { return '<option value="' + E(s) + '">'; }).join('') + '</datalist></div>' +
      '<p class="lf-err" id="ps-e" role="alert"></p><div class="lf-act"><button type="button" class="btn" data-x>Cancel</button><button class="btn pri" type="submit">Save</button></div></form>',
      onOpen: function (b, api) {
        b.querySelector('#ps').addEventListener('submit', function (e) {
          e.preventDefault();
          var w = b.querySelector('#ps-w').value.trim(), r = b.querySelector('#ps-r').value.trim();
          hapi('PUT', '/api/rules', { stock: { symbol: sym, target_weight: w === '' ? null : num(w), review_price: r === '' ? null : num(r), sector: b.querySelector('#ps-s').value } })
            .then(function () { return Mine.load(true); }).then(function () { api.close(); say(sym + ' settings saved'); if (after) after(); })
            .catch(function (err) { b.querySelector('#ps-e').textContent = err.message; });
        });
      } });
  }
  function sectors() { var s = {}; (Mine.me && Mine.me.positions || []).forEach(function (p) { if (p.sector) s[p.sector] = 1; }); return Object.keys(s).sort(); }

  // ---------- the "My position" card ----------
  function statHtml(label, value, sub) { return '<div class="ps"><div class="ps-l">' + label + '</div><div class="ps-v">' + value + '</div>' + (sub ? '<div class="ps-s">' + sub + '</div>' : '') + '</div>'; }
  function positionHtml(p, sym) {
    if (!p || !p.lots || !p.lots.length) {
      return '<div class="card-h"><div><h2>My position</h2></div></div><div class="card-b"><div class="empty"><div class="ico">' + icon('briefcase') + '</div><b>You do not hold ' + E(sym) + ' yet</b><span>Record a purchase to track your shares, average price and profit or loss.</span>' +
        '<button class="btn pri" type="button" data-act="add">' + icon('plus', 'sm') + 'Add to my holdings</button></div></div>';
    }
    var open = p.qty > 0;
    var stats = '';
    if (open) {
      stats += statHtml('Shares held', Number(p.qty).toLocaleString('en-IN'));
      stats += statHtml('Average buy price', inr(p.avg_cost, 2), 'incl. charges');
      stats += statHtml('Invested', inr(p.invested, 0));
      stats += statHtml('Current value', p.value == null ? '<span class="mu">price not available</span>' : inr(p.value, 0), p.price == null ? '' : 'at ' + inr(p.price, 2));
      stats += statHtml('Unrealised P&amp;L', p.unrealized == null ? '-' : chg(p.unrealized, p.unrealized_pct));
      stats += statHtml('Day change', p.day_abs == null ? '<span class="mu">-</span>' : chg(p.day_abs, p.day_pct), p.day_abs == null ? 'no previous close' : '');
      stats += statHtml('Share of portfolio', p.weight == null ? '-' : p.weight.toFixed(1) + '%', p.target_weight != null ? 'target ' + p.target_weight + '%' : '');
    } else stats += statHtml('Shares held', '0', 'fully sold');
    if (p.sold_qty) stats += statHtml('Realised P&amp;L', chg(p.realized, null), p.sold_qty + ' share' + (p.sold_qty === 1 ? '' : 's') + ' sold');
    var rows = p.lots.slice().sort(function (a, b) { return (b.date || '') < (a.date || '') ? -1 : (b.date || '') > (a.date || '') ? 1 : b.id - a.id; }).map(function (l) {
      return '<li class="tx"><div class="tx-d">' + E(longDate(l.date)) + '</div><div class="tx-m"><span class="vd ' + (l.side === 'buy' ? 'BUY' : 'WATCH') + '">' + (l.side === 'buy' ? 'Bought' : 'Sold') + '</span> <b>' + l.qty + '</b> × ' + inr(l.price, 2) + '</div>' +
        '<div class="tx-a">' + inr(l.amount, 2) + (l.fees ? '<small>+ ' + inr(l.fees, 2) + ' charges</small>' : '') + (l.side === 'sell' && l.realized != null ? '<small>' + chg(l.realized, null, 2) + ' realised</small>' : '') + '</div>' +
        (l.note ? '<div class="tx-n">' + E(l.note) + '</div>' : '') +
        '<div class="tx-b"><button class="ibtn sm" type="button" data-edit="' + l.id + '" aria-label="Edit ' + l.side + ' of ' + l.qty + ' on ' + E(longDate(l.date)) + '">' + icon('pencil', 'sm') + '</button><button class="ibtn sm" type="button" data-del="' + l.id + '" aria-label="Delete ' + l.side + ' of ' + l.qty + ' on ' + E(longDate(l.date)) + '">' + icon('trash', 'sm') + '</button></div></li>';
    }).join('');
    return '<div class="card-h"><div><h2>My position</h2><p>' + (open ? 'Cost basis uses the average cost of all your purchases.' : 'No shares left. Your history is kept below.') + '</p></div>' +
      '<div class="ph-act"><button class="btn pri" type="button" data-act="add">' + icon('plus', 'sm') + 'Add more shares</button>' + (open ? '<button class="btn" type="button" data-act="sell">Record a sale</button>' : '') + '<button class="btn" type="button" data-act="settings">' + icon('sliders', 'sm') + 'Alert settings</button></div></div>' +
      '<div class="card-b"><div class="pstats">' + stats + '</div><h3 class="tx-h">Transactions (' + p.lots.length + ')</h3><ul class="txl">' + rows + '</ul></div>';
  }
  // Fills a card element and wires its buttons. reload() runs after any change.
  var posCache = {};
  function mountPosition(el, sym, name, price, reload) {
    if (posCache[sym]) paint(posCache[sym]);
    else el.innerHTML = '<div class="card-b"><div class="sk" style="width:35%;height:22px"></div><div class="sk" style="width:90%"></div><div class="sk" style="width:70%"></div></div>';
    function paint(p) { el.innerHTML = positionHtml(p, sym); }
    return hapi('GET', '/api/position?sym=' + encodeURIComponent(sym)).then(function (p) {
      posCache[sym] = p;
      paint(p);
      window.MY_POS = window.MY_POS || {};
      if (p.qty > 0 && p.avg_cost) window.MY_POS[sym] = { avg: p.avg_cost, lots: p.lots.filter(function (l) { return l.date; }).map(function (l) { return { date: l.date, side: l.side, qty: l.qty, price: l.price }; }) };
      else delete window.MY_POS[sym];
      var after = function () { mountPosition(el, sym, name, price, reload); if (reload) reload(); if (window.PriceChart && PriceChart.redraw) document.querySelectorAll('.pc[data-sym]').forEach(PriceChart.redraw); if (window.refreshForecastChart) window.refreshForecastChart(); };
      el.onclick = function (e) {
        var t = e.target.closest('[data-act],[data-edit],[data-del]'); if (!t) return;
        if (t.dataset.act === 'add') openLotForm({ symbol: sym, name: name, price: price, side: 'buy', onSaved: after });
        else if (t.dataset.act === 'sell') openLotForm({ symbol: sym, name: name, price: price, side: 'sell', onSaved: after });
        else if (t.dataset.act === 'settings') openPositionSettings(sym, name, after);
        else if (t.dataset.edit) openLotForm({ symbol: sym, name: name, price: price, lot: p.lots.find(function (l) { return String(l.id) === t.dataset.edit; }), onSaved: after });
        else if (t.dataset.del) {
          var l = p.lots.find(function (x) { return String(x.id) === t.dataset.del; });
          confirmSheet({ title: 'Delete this transaction?', text: 'This removes the ' + l.side + ' of ' + l.qty + ' ' + sym + ' on ' + longDate(l.date) + ' and changes your average price and invested amount.', confirm: 'Delete transaction',
            onConfirm: function () { return hapi('DELETE', '/api/lots?id=' + l.id).then(function () { return Mine.load(true); }).then(function () { say('Transaction deleted'); after(); }); } });
        }
      };
      return p;
    }).catch(function (e) {
      el.innerHTML = '<div class="card-b"><div class="empty"><div class="ico">' + icon('triangle-alert') + '</div><b>Could not load your position</b><span>' + E(e.message) + '</span><button class="btn" type="button" id="pos-retry">Try again</button></div></div>';
      var r = el.querySelector('#pos-retry'); if (r) r.onclick = function () { mountPosition(el, sym, name, price, reload); };
    });
  }

  // ---------- import and export ----------
  function openImport(after) {
    Shell.sheet({ title: 'Import transactions', html:
      '<form class="lf" id="im" novalidate><p class="lf-n">Use a file exported from this app (JSON or CSV), or a CSV with the columns symbol, qty, price and optionally side, date, fees and note. The file is read in your browser and nothing is saved unless every row is valid.</p>' +
      '<div class="lf-f"><label for="im-f">File</label><input id="im-f" class="lf-in" type="file" accept=".csv,.json,text/csv,application/json"></div>' +
      '<div class="lf-f"><label for="im-t">Or paste the text</label><textarea id="im-t" class="lf-in" rows="5" spellcheck="false" placeholder="symbol,side,qty,price,date\nTCS,buy,10,3500,2026-01-15"></textarea></div>' +
      '<fieldset class="lf-fs"><legend>If you already have transactions</legend><label class="lf-rad"><input type="radio" name="im-m" value="merge" checked> Add these to what I have (exact duplicates are skipped)</label><label class="lf-rad"><input type="radio" name="im-m" value="replace"> Replace everything with this file</label></fieldset>' +
      '<p class="lf-err" id="im-e" role="alert"></p><p class="lf-ok" id="im-ok" role="status"></p><div class="lf-act"><button type="button" class="btn" data-x>Close</button><button class="btn pri" type="submit" id="im-go">Import</button></div></form>',
      onOpen: function (b, api) {
        var file = null;
        b.querySelector('#im-f').onchange = function (e) { var fl = e.target.files[0]; if (!fl) return; if (fl.size > 90000) { b.querySelector('#im-e').textContent = 'That file is too large (90 KB at most).'; return; } var r = new FileReader(); r.onload = function () { b.querySelector('#im-t').value = r.result; }; r.readAsText(fl); };
        b.querySelector('#im').addEventListener('submit', function (e) {
          e.preventDefault();
          var text = b.querySelector('#im-t').value.trim(), er = b.querySelector('#im-e'), ok = b.querySelector('#im-ok');
          er.textContent = ok.textContent = '';
          if (!text) { er.textContent = 'Choose a file or paste some text first.'; return; }
          var isJson = text[0] === '{', mode = b.querySelector('input[name=im-m]:checked').value, go = b.querySelector('#im-go');
          if (mode === 'replace' && !window.confirm('Replace all your current transactions with this file?')) return;
          go.disabled = true;
          hapi('POST', '/api/transactions/import', { format: isJson ? 'json' : 'csv', data: isJson ? text : text, mode: mode }).then(function (r) {
            ok.textContent = 'Imported ' + r.added + ' transaction' + (r.added === 1 ? '' : 's') + (r.skipped ? ', skipped ' + r.skipped + ' duplicate' + (r.skipped === 1 ? '' : 's') : '') + '.';
            return Mine.load(true).then(function () { if (after) after(); });
          }).catch(function (err) { er.textContent = err.message; }).then(function () { go.disabled = false; });
        });
      } });
  }

  window.Mine = Mine;
  window.Holdings = { openLotForm: openLotForm, openImport: openImport, openPositionSettings: openPositionSettings, mountPosition: mountPosition, api: hapi,
    inr: inr, signedInr: signedInr, signedPct: signedPct, chg: chg, longDate: longDate, say: say, confirmSheet: confirmSheet, num: num };
})();
