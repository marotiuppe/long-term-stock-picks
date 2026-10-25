/* My portfolio section. Loaded before the main page script, which mounts it on /portfolio. Read-only: never places orders. */
(function () {
  'use strict';

  // ---------- pure helpers (testable) ----------
  function num(n) { return typeof n === 'number' && isFinite(n) ? n : null; }
  function fmt(n, d) {
    n = num(n); if (n === null) return '-';
    d = d === undefined ? 2 : d;
    return n.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function rupee(n, d) { n = num(n); return n === null ? '-' : '₹' + fmt(n, d); }
  function signedRupee(n) {
    n = num(n); if (n === null) return '-';
    return (n >= 0 ? '+' : '-') + '₹' + fmt(Math.abs(n), 0);
  }
  // pct values from server are fractions (0.05 = 5%) or percent? Contract: *_pct are percent numbers.
  function signedPct(n, d) {
    n = num(n); if (n === null) return '-';
    return (n >= 0 ? '+' : '-') + fmt(Math.abs(n), d === undefined ? 1 : d) + '%';
  }
  function tone(n) { n = num(n); return n === null || n === 0 ? '' : (n > 0 ? 'up' : 'dn'); }
  function warnings(h) {
    var w = [];
    if (h && h.stop_breached) w.push('Stop-loss breached');
    if (h && (h.downtrend_flag || /downtrend/i.test(String(h.call || '')))) w.push('Downtrend');
    return w;
  }
  function parseHoldingForm(sym, qty, avg) {
    sym = String(sym || '').trim().toUpperCase().replace(/\.NS$/, '');
    var q = Number(qty), a = Number(avg);
    if (!/^[A-Z0-9&-]{1,20}$/.test(sym)) return { error: 'Enter a valid symbol, e.g. TCS' };
    if (!isFinite(q) || q <= 0 || Math.floor(q) !== q) return { error: 'Quantity must be a whole number above 0' };
    if (!isFinite(a) || a <= 0) return { error: 'Average price must be above 0' };
    return { symbol: sym, qty: q, avg_price: a };
  }
  function totals(hs) {
    var inv = 0, val = 0;
    (hs || []).forEach(function (h) { inv += num(h.invested) || 0; val += num(h.value) || 0; });
    return { invested: inv, value: val, pnl: val - inv, pct: inv > 0 ? (val - inv) / inv * 100 : null };
  }
  function syncedLabel(iso) {
    if (!iso) return 'not yet';
    var d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso) : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { fmt: fmt, rupee: rupee, signedRupee: signedRupee, signedPct: signedPct, tone: tone,
      warnings: warnings, parseHoldingForm: parseHoldingForm, totals: totals, syncedLabel: syncedLabel };
  }
  if (typeof document === 'undefined') return;

  // ---------- DOM ----------
  var root, S = { me: null, unavailable: false, busy: false, editSym: null, sort: { key: 'value', dir: -1 }, by: 'stock' };
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function kid(p) { for (var i = 1; i < arguments.length; i++) if (arguments[i]) p.appendChild(arguments[i]); return p; }

  function api(method, url, body) {
    var opt = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return (window.Session ? window.Session.fetch(url, opt) : fetch(url, opt)).then(function (r) {
      var ct = r.headers.get('content-type') || '';
      if (!/json/i.test(ct)) throw new Error('unavailable');
      return r.json().then(function (j) { return { ok: r.ok, data: j }; });
    });
  }

  function setMsg(text, bad) {
    var m = $('pf-msg'); if (!m) return;
    m.textContent = text || ''; m.className = 'pf-msg' + (bad ? ' bad' : '');
  }

  function adopt(me) {
    if (me && Array.isArray(me.holdings)) { S.me = me; S.unavailable = false; return true; }
    return false;
  }

  function load() {
    return api('GET', '/api/me').then(function (r) {
      if (!r.ok || !adopt(r.data)) throw new Error('unavailable');
      render();
    }).catch(function () { S.unavailable = true; render(); });
  }

  function act(method, url, body, okMsg) {
    if (S.busy) return Promise.resolve();
    S.busy = true; setMsg('Working…');
    return api(method, url, body).then(function (r) {
      if (r.data && r.data.error) { setMsg(String(r.data.error), true); return r.data; }
      if (!r.ok) { setMsg('Request failed', true); return r.data; }
      var me = r.data && r.data.me ? r.data.me : r.data;
      if (!adopt(me)) return load().then(function () { return r.data; });
      render(); setMsg(okMsg || 'Saved');
      return r.data;
    }).catch(function () { setMsg('Portfolio is unavailable', true); })
      .then(function (x) { S.busy = false; return x; });
  }

  function btn(label, cls, fn, aria) {
    var b = el('button', { type: 'button', class: 'btn pf-btn ' + (cls || '') }, label);
    if (aria) b.setAttribute('aria-label', aria);
    b.addEventListener('click', fn);
    return b;
  }
  function field(id, label, attrs) {
    var w = el('div', { class: 'pf-field' });
    var l = el('label', { for: id }, label);
    var i = el('input', Object.assign({ id: id, class: 'pf-in' }, attrs || {}));
    return kid(w, l, i);
  }

  function ico(name, cls) { return window.Shell ? window.Shell.icon(name, cls) : ''; }
  function card(title, desc, cls) {
    var c = el('section', { class: 'card ' + (cls || '') });
    var h = el('div', { class: 'card-h' }), t = el('div');
    kid(t, el('h2', null, title)); if (desc) kid(t, el('p', null, desc));
    kid(h, t); kid(c, h);
    var b = el('div', { class: 'card-b' }); kid(c, b);
    c.body = b; c.heading = t.firstChild; return c;
  }
  function tile(icon, label, value, sub, cls) {
    var t = el('div', { class: 'card kpi' });
    var l = el('div', { class: 'kpi-l' }); l.innerHTML = ico(icon); l.appendChild(document.createTextNode(label));
    kid(t, l, el('div', { class: 'kpi-v ' + (cls || '') }, value), el('div', { class: 'kpi-s' }, sub || ''));
    return t;
  }

  // ---------- holdings table: sortable, with weights and day change ----------
  var WHY = { thin: 'price under the minimum or too little history', illiquid: 'low daily trading value', suspect: 'unusual price jumps' };
  var COLS = [['symbol', 'Stock'], ['qty', 'Shares'], ['avg_cost', 'Avg buy'], ['invested', 'Invested'], ['price', 'Price'], ['value', 'Value'],
    ['unrealized', 'P&L'], ['unrealized_pct', 'P&L %'], ['day_abs', 'Day'], ['weight', 'Weight']];
  function sorted(ps) {
    var k = S.sort.key, d = S.sort.dir;
    return ps.slice().sort(function (a, b) {
      if (k === 'symbol') return d * a.symbol.localeCompare(b.symbol);
      var x = a[k], y = b[k];
      if (x == null && y == null) return a.symbol.localeCompare(b.symbol);
      if (x == null) return 1; if (y == null) return -1;      // missing figures always go last
      return d * (x - y) || a.symbol.localeCompare(b.symbol);
    });
  }
  function pctHtml(n) { if (n == null) return '<span class="mu">-</span>'; var c = n > 0 ? 'up' : n < 0 ? 'dn' : 'mu'; return '<span class="chg ' + c + '">' + (n > 0 ? ico('arrow-up-right', 'sm') : n < 0 ? ico('arrow-down-right', 'sm') : '') + signedPct(n) + '</span>'; }
  function chgHtml(abs, pct, d) { return window.Holdings ? window.Holdings.chg(abs, pct, d) : (abs == null ? '-' : signedRupee(abs)); }

  function holdingsTable(ps) {
    if (!ps.length) {
      var e = el('div', { class: 'empty', style: 'padding:32px 16px' }); e.innerHTML = '<div class="ico">' + ico('inbox') + '</div>';
      var b = btn('Add a holding', 'pri', function () { addHolding(); });
      kid(e, el('b', null, 'No holdings yet'), el('span', null, 'Record what you bought and the app tracks your average price, profit or loss and share of the portfolio. You can also import a file or paste a list below.'), b);
      return e;
    }
    var wrap = el('div', { class: 'pf-scroll', role: 'region', 'aria-label': 'Holdings table', tabindex: '0' });
    var t = el('table', { class: 'pf-table' });
    var hr = el('tr');
    COLS.forEach(function (c, i) {
      var on = S.sort.key === c[0], th = el('th', { scope: 'col', class: i ? 'num' : '', 'aria-sort': on ? (S.sort.dir > 0 ? 'ascending' : 'descending') : 'none' });
      var b = el('button', { type: 'button', class: 'sb', 'data-k': c[0], title: 'Sort by ' + c[1].toLowerCase() }, c[1]);
      var ar = el('span', { class: 'ar' }); ar.innerHTML = ico(on ? (S.sort.dir > 0 ? 'arrow-up' : 'arrow-down') : 'chevrons-up-down'); b.appendChild(ar);
      b.addEventListener('click', function () { S.sort = on ? { key: c[0], dir: -S.sort.dir } : { key: c[0], dir: c[0] === 'symbol' ? 1 : -1 }; render(); var nb = document.querySelector('.pf-table th[aria-sort] .sb[data-k="' + c[0] + '"]'); if (nb) nb.focus(); });
      th.appendChild(b); hr.appendChild(th);
    });
    hr.appendChild(el('th', { scope: 'col' }, ''));
    kid(t, kid(el('thead'), hr));
    var tb = el('tbody');
    sorted(ps).forEach(function (p) {
      var tr = el('tr');
      var rh = el('th', { scope: 'row' }); rh.appendChild(el('a', { href: '/stock.html?symbol=' + encodeURIComponent(p.symbol) }, p.symbol));
      if (p.quote_only) rh.appendChild(el('span', { class: 'etf', title: 'Not in the stock scan (' + (WHY[p.why_not_scanned] || 'filtered out') + '). Valued at its last close, with no call, forecast or chart.' }, ' price only'));
      if (p.name) rh.appendChild(el('div', { class: 'pf-sub' }, p.name)); tr.appendChild(rh);
      function td(html, cls) { var c = el('td', { class: 'num' + (cls ? ' ' + cls : '') }); c.innerHTML = html; tr.appendChild(c); return c; }
      td(fmt(p.qty, 0));
      td(rupee(p.avg_cost));
      td(rupee(p.invested, p.invested < 1000 ? 2 : 0));       // small holdings need the paise to match the broker's figure
      td(p.price == null ? '<span class="mu">-</span>' : rupee(p.price));
      td(p.value == null ? '<span class="mu">-</span>' : rupee(p.value, p.value < 1000 ? 2 : 0));
      td(p.unrealized == null ? '-' : chgHtml(p.unrealized, null));
      td(pctHtml(p.unrealized_pct));
      td(p.day_abs == null ? '<span class="mu">-</span>' : chgHtml(p.day_abs, p.day_pct));
      td(p.weight == null ? '-' : fmt(p.weight, 1) + '%');
      var ac = el('td', { class: 'pf-acts' });
      var addb = btn('', 'sm', function () { addHolding(p); }, 'Add more shares of ' + p.symbol);
      addb.innerHTML = ico('plus', 'sm') + '<span class="lbl">Add shares</span>'; ac.appendChild(addb);
      tr.appendChild(ac);
      Array.prototype.forEach.call(tr.children, function (c, i) { var h = i === 0 ? null : (COLS[i] || [])[1]; if (h) c.setAttribute('data-label', h); });
      tb.appendChild(tr);
    });
    kid(t, tb); kid(wrap, t);
    return wrap;
  }

  function addHolding(p) {
    if (!window.Holdings) return;
    window.Holdings.openLotForm({ symbol: p && p.symbol, name: p && p.name, price: p && p.price, side: 'buy', onSaved: function () { load(); } });
  }

  // ---------- allocation: by stock or by the sector tags the user assigned ----------
  function allocationCard(ps) {
    var c = card('Allocation', 'Share of current value.');
    var seg = el('div', { class: 'seg', role: 'group', 'aria-label': 'Group allocation by' });
    ['stock', 'sector'].forEach(function (k) {
      var b = el('button', { type: 'button', class: 'tab' + (S.by === k ? ' on' : ''), 'aria-pressed': S.by === k ? 'true' : 'false' }, 'By ' + k);
      b.addEventListener('click', function () { S.by = k; draw(); }); seg.appendChild(b);
    });
    c.firstChild.appendChild(seg);
    function draw() {
      seg.querySelectorAll('.tab').forEach(function (b, i) { var on = (i === 0) === (S.by === 'stock'); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
      var rows, note = '';
      if (S.by === 'stock') rows = ps.map(function (p) { return { label: p.symbol, value: p.value || 0 }; });
      else {
        var g = {}; ps.forEach(function (p) { var k = p.sector || '__none'; g[k] = (g[k] || 0) + (p.value || 0); });
        rows = Object.keys(g).map(function (k) { return { label: k === '__none' ? 'No sector set' : k, value: g[k], none: k === '__none' }; });
        if (g.__none) note = '<p class="pf-note">' + (Object.keys(g).length === 1 ? 'No sector is set yet. ' : '') + 'Sector labels are your own: Yahoo Finance does not provide them without a login, so none are guessed. Set one for each stock in <a href="/settings.html">Settings</a>.</p>';
      }
      var tot = ps.reduce(function (a, p) { return a + (p.value || 0); }, 0);
      c.body.innerHTML = window.Allocation ? window.Allocation.html(rows, { by: S.by, centerTop: rupee(tot, 0), centerBottom: 'current value' }) + note : '';
      if (window.Allocation) window.Allocation.bind(c.body);
    }
    draw();
    return c;
  }

  function performersCard(ps) {
    var c = card('Best and worst', 'By profit or loss on what you invested.');
    var r = ps.filter(function (p) { return p.unrealized_pct != null; }).sort(function (a, b) { return b.unrealized_pct - a.unrealized_pct; });
    if (r.length < 2) { c.body.appendChild(el('p', { class: 'pf-empty' }, 'Needs at least two holdings with prices.')); return c; }
    function list(title, rows) {
      var h = el('h3', { class: 'pf-h2' }, title), ul = el('ul', { class: 'pf-perf' });
      rows.forEach(function (p) {
        var li = el('li'); li.appendChild(el('a', { href: '/stock.html?symbol=' + encodeURIComponent(p.symbol) }, p.symbol));
        var v = el('span', { class: 'pf-pv' }); v.innerHTML = chgHtml(p.unrealized, null) + ' ' + pctHtml(p.unrealized_pct); li.appendChild(v); ul.appendChild(li);
      });
      return kid(el('div'), h, ul);
    }
    kid(c.body, list('Best', r.slice(0, 3)), list('Worst', r.slice(-3).reverse()));
    if (S.me.summary && S.me.summary.realized) c.body.appendChild(el('p', { class: 'pf-note' }, 'Realised so far from sales: ' + signedRupee(S.me.summary.realized) + '.'));
    return c;
  }

  function startEdit(h) { /* kept for compatibility: edits now happen on the stock's page */ }

  function render() {
    if (!root) return;
    var body = $('pf-body'); if (!body) return;
    var keep = {};
    ['pf-paste', 'pf-wl'].forEach(function (id) { var e = $(id); if (e) keep[id] = e.value; });
    body.textContent = '';
    if (S.unavailable || !S.me) {
      var u = card('Portfolio is unavailable', 'The portfolio service did not answer. Your data is stored on the server and is not affected.');
      u.body.appendChild(el('p', { class: 'pf-empty', role: 'status' }, 'Portfolio is unavailable'));
      u.body.appendChild(btn('Retry', '', load));
      body.appendChild(u);
      return;
    }
    var me = S.me, ps = me.positions || [], sm = me.summary || {};

    // (a) KPI row: invested, current value, total P&L, today. Signs and arrows carry direction.
    if (ps.length) {
      var k = el('div', { class: 'kpis' });
      function big(abs) { return abs == null ? '-' : (abs > 0 ? '+' : abs < 0 ? '-' : '') + rupee(Math.abs(abs), 0); }
      var pnlTile = tile('trending-up', 'Total P&L', big(sm.pnl), (sm.pnl_pct == null ? '' : signedPct(sm.pnl_pct) + ' on invested') + (sm.realized ? ' · realised ' + big(sm.realized) : ''), tone(sm.pnl) === 'up' ? 'good' : tone(sm.pnl) === 'dn' ? 'bad' : '');
      var dayTile = tile('clock', 'Today’s change', big(sm.day_abs), sm.day_abs == null ? 'previous close not available' : signedPct(sm.day_pct) + ' since the last close', tone(sm.day_abs) === 'up' ? 'good' : tone(sm.day_abs) === 'dn' ? 'bad' : '');
      [pnlTile, dayTile].forEach(function (t, i) { var v = t.querySelector('.kpi-v'), n = i ? sm.day_abs : sm.pnl; if (n) v.insertAdjacentHTML('afterbegin', ico(n > 0 ? 'arrow-up-right' : 'arrow-down-right', 'sm')); });
      kid(k, tile('wallet', 'Total invested', rupee(sm.invested, 0), ps.length + (ps.length === 1 ? ' holding' : ' holdings')),
        tile('briefcase', 'Current value', rupee(sm.value, 0), sm.unpriced && sm.unpriced.length ? sm.unpriced.join(', ') + ' without a price' : 'at the latest close'), pnlTile, dayTile);
      body.appendChild(k);
    }

    var grid = el('div', { class: 'grid' });
    // (b) holdings
    var hc = card('Holdings', ps.length ? 'Select a column heading to sort. Select a symbol for its page.' : '');
    hc.body.className = 'card-b flush'; hc.body.appendChild(holdingsTable(ps));
    if (ps.length) hc.body.appendChild(el('p', { class: 'pf-note pf-pad' }, 'Average buy price includes brokerage you entered. Prices are the latest close; synced ' + syncedLabel(me.synced) + '.'));
    kid(grid, hc);
    // (c) allocation
    body.appendChild(grid);
    if (ps.length) {
      var gB = el('div', { class: 'grid' }), ac0 = allocationCard(ps), pf0 = performersCard(ps);
      ac0.classList.add('span-6'); pf0.classList.add('span-6'); kid(gB, ac0, pf0); body.appendChild(gB);
    }

    var g2 = el('div', { class: 'grid pf-g' });
    // (d) paste import, export, import
    var fc = card('Add, import and export', 'Your data is stored on the server under your account or browser cookie. Export a copy whenever you like.', 'span-6 pf-io');
    var row = el('div', { class: 'pf-data' });
    kid(row, el('a', { class: 'btn', href: '/api/export.csv', download: 'my-transactions.csv' }, 'Export transactions (CSV)'),
      el('a', { class: 'btn', href: '/api/export', download: 'my-portfolio.json' }, 'Export everything (JSON)'),
      btn('Import a file', '', function () { if (window.Holdings) window.Holdings.openImport(load); }),
      btn('Sync from Groww', 'pri', function () { if (window.GrowwSync) window.GrowwSync.open(load); }));
    fc.body.appendChild(row);
    var pw = el('div', { class: 'pf-block' });
    pw.appendChild(el('label', { for: 'pf-paste' }, 'Or paste a list: SYMBOL qty avg price, one per line'));
    pw.appendChild(el('textarea', { id: 'pf-paste', class: 'pf-in', rows: '4', placeholder: 'TCS 10 3500\nINFY 25 1450.5' }));
    pw.appendChild(el('p', { class: 'pf-mu' }, 'Each line becomes one opening purchase. A stock that already has several transactions is skipped, so nothing you recorded is overwritten.'));
    var errs = el('ul', { id: 'pf-errs', class: 'pf-errs', 'aria-live': 'polite' });
    pw.appendChild(btn('Import list', '', function () {
      var text = $('pf-paste').value;
      if (!text.trim()) { setMsg('Paste at least one line', true); return; }
      errs.textContent = '';
      act('POST', '/api/holdings/paste', { text: text }, null).then(function (d) {
        if (!d || d.error) return;
        var live = $('pf-errs') || errs;
        live.textContent = '';
        (d.errors || []).forEach(function (e) { live.appendChild(el('li', null, (e.line ? 'Line ' + e.line + ': ' : '') + e.message)); });
        setMsg((d.added || 0) + ' imported' + ((d.errors || []).length ? ', ' + d.errors.length + ' skipped' : ''), !!(d.errors || []).length && !d.added);
        if (!(d.errors || []).length) $('pf-paste').value = '';
      });
    }));
    pw.appendChild(errs);
    pw.appendChild(el('p', { id: 'pf-msg', class: 'pf-msg', role: 'status', 'aria-live': 'polite' }));
    fc.body.appendChild(pw);
    kid(g2, fc);

    // (e) watchlist and the older alerts inbox
    var wc = card('Watchlist', 'Names you are following but do not hold.', 'span-6');
    var wf = el('form', { class: 'pf-form', 'aria-label': 'Add to watchlist' });
    kid(wf, field('pf-wl', 'Symbol', { type: 'text', autocomplete: 'off', maxlength: '20', placeholder: 'RELIANCE' }),
      el('button', { type: 'submit', class: 'btn pf-btn' }, 'Add to watchlist'));
    wf.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var s = $('pf-wl').value.trim().toUpperCase().replace(/\.NS$/, '');
      if (!/^[A-Z0-9&-]{1,20}$/.test(s)) { setMsg('Enter a valid symbol', true); return; }
      act('POST', '/api/watchlist', { symbol: s }, s + ' added to watchlist');
    });
    wc.body.appendChild(wf);
    var wl = me.watchlist || [];
    if (!wl.length) wc.body.appendChild(el('p', { class: 'pf-empty' }, 'Watchlist is empty.'));
    else {
      var ul = el('ul', { class: 'pf-wl' });
      wl.forEach(function (w) {
        var li = el('li');
        var sg = el('strong'); sg.appendChild(el('a', { href: '/stock.html?symbol=' + encodeURIComponent(w.symbol) }, w.symbol)); li.appendChild(sg);
        li.appendChild(el('span', { class: 'pf-mu' }, ' ' + rupee(w.price)));
        if (w.call) li.appendChild(el('span', { class: 'pf-badge' }, w.call));
        li.appendChild(btn('Remove', 'sm', function () {
          act('DELETE', '/api/watchlist?sym=' + encodeURIComponent(w.symbol), undefined, w.symbol + ' removed from watchlist');
        }, 'Remove ' + w.symbol + ' from watchlist'));
        ul.appendChild(li);
      });
      wc.body.appendChild(ul);
    }
    kid(g2, wc);
    body.appendChild(g2);
    var g3 = el('div', { class: 'grid pf-g' });

    var unread = Number(me.unread) || 0;
    var alc = card('Scan alerts', 'Stop levels, call changes and review dates from the daily scan.', 'span-6');
    alc.heading.appendChild(document.createTextNode(' '));
    alc.heading.appendChild(el('span', { class: 'pf-count', 'aria-label': unread + ' unread' }, String(unread)));
    var al = me.alerts || [];
    if (!al.length) alc.body.appendChild(el('p', { class: 'pf-empty' }, 'No alerts.'));
    else {
      var au = el('ul', { class: 'pf-alerts', 'data-gloss-auto': '' });
      al.forEach(function (a) {
        var li = el('li', { class: a.read ? 'read' : 'unread' });
        li.appendChild(el('span', { class: 'pf-badge' }, a.kind || 'alert'));
        li.appendChild(el('strong', null, ' ' + (a.symbol || '') + ' '));
        li.appendChild(el('span', null, a.message || ''));
        li.appendChild(el('span', { class: 'pf-mu' }, ' ' + (a.date || '')));
        au.appendChild(li);
      });
      alc.body.appendChild(au);
      var mb = btn('Mark all read', '', function () { act('POST', '/api/alerts/read', {}, 'Alerts marked read'); });
      if (!unread) mb.disabled = true;
      var mw = el('div', { class: 'pf-block' }); mw.appendChild(mb); alc.body.appendChild(mw);
    }
    kid(g3, alc);

    // (f) delete
    var dc = card('Your data', 'Stored on the server, under your account or browser cookie. Read-only: this page never places orders and never asks for broker passwords.', 'span-6');
    var dw = el('div', { class: 'pf-data' });
    dw.appendChild(btn('Delete my data', 'danger', function () {
      if (!window.confirm('Delete all your holdings, transactions, watchlist, alerts and settings? This cannot be undone.')) return;
      S.busy = true;
      api('DELETE', '/api/me').then(function () { S.busy = false; if (window.Mine) window.Mine.load(true).catch(function () {}); return load(); })
        .then(function () { setMsg('Your data was deleted'); })
        .catch(function () { S.busy = false; setMsg('Portfolio is unavailable', true); });
    }));
    dc.body.appendChild(dw);
    kid(g3, dc);
    body.appendChild(g3);

    Object.keys(keep).forEach(function (id) { if ($(id) && keep[id]) $(id).value = keep[id]; });
  }

  // Mounts the portfolio view into a page container (the /portfolio page).
  function mount(host) {
    root = el('div', { id: 'pf', class: 'pf' });
    root.appendChild(el('div', { id: 'pf-body', class: 'pf-body' }, 'Loading…'));
    host.textContent = '';
    host.appendChild(root);
    load();
  }

  // Unread alert count, for the nav badge. Resolves to 0 when unavailable.
  function unread() {
    return api('GET', '/api/me').then(function (r) {
      if (r.ok && adopt(r.data)) return Number(r.data.unread) || 0;
      return 0;
    }).catch(function () { return 0; });
  }

  // a finished scan brings new prices: refresh the numbers on screen without a page reload
  document.addEventListener('scan:updated', function () { if (document.getElementById('pfhost')) load(); });
  window.PF = { mount: mount, unread: unread, reload: load, add: function () { addHolding(); } };
})();
