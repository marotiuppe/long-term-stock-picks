/* pricealerts.js: "Price alerts" card on the stock page. window.PriceAlerts.mount(host, symbol, {stock, horizon}).
   The page rebuilds its DOM on horizon tab clicks and calls mount again; the half-filled form is kept in module state. */
(function () {
  var KINDS = { below: 'Price at or below', above: 'Price at or above', off_high: 'Falls this % below the 52-week high' };
  var draft = {};   // symbol -> {kind, value}

  // pure helpers (also used by the node test)
  function validate(kind, raw) {
    if (!KINDS[kind]) return 'Choose what to watch for.';
    var t = String(raw == null ? '' : raw).replace(/,/g, '').trim();
    if (!t) return 'Enter a number.';
    var v = Number(t);
    if (!isFinite(v)) return 'Enter a number, for example 3300.';
    if (kind === 'off_high') return v >= 1 && v <= 90 ? '' : 'Enter a percentage from 1 to 90.';
    return v > 0 ? '' : 'The price must be more than 0.';
  }
  function num(v) { return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }); }
  function describe(kind, value) {
    if (kind === 'below') return 'Price at or below ₹' + num(value);
    if (kind === 'above') return 'Price at or above ₹' + num(value);
    return 'Falls ' + num(value) + '% or more below the 52-week high';
  }
  function statusOf(a) {
    if (a.status === 'paused') return { cls: 'paused', text: 'Paused' };
    if (a.last_fired || a.status === 'reached') return { cls: 'reached', text: 'Reached on ' + (a.last_fired || '') };
    return { cls: 'waiting', text: 'Waiting' };
  }

  function api(method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  var ICO = {
    waiting: '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    paused: '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M9 6v12M15 6v12"/></svg>'
  };

  function mount(host, symbol, opts) {
    var sym = String(symbol || '').toUpperCase();
    if (!host || !sym) return;
    var stock = (opts && opts.stock) || {}, d = draft[sym] || (draft[sym] = { kind: 'below', value: '' });
    host.innerHTML = '<div class="card pa"><div class="card-h"><div><h2>Price alerts</h2><p>A reminder to look at this stock again when a price you set has been reached.</p></div></div><div class="card-b"></div></div>';
    var body = host.querySelector('.card-b');
    var cur = el('p', 'pa-cur');
    cur.appendChild(document.createTextNode('Latest close: '));
    var b = el('b', null, stock.price != null ? '₹' + num(stock.price) : 'not available');
    cur.appendChild(b);
    if (stock.hi52 != null) cur.appendChild(document.createTextNode(' · 52-week high ₹' + num(stock.hi52)));
    body.appendChild(cur);

    var form = el('form', 'pa-form'); form.noValidate = true;
    form.innerHTML = '<div class="pa-f"><label for="pa-kind">Alert me when</label><select id="pa-kind"></select></div>' +
      '<div class="pa-f"><label for="pa-val">Level</label><div class="pa-in"><span class="pa-pre" aria-hidden="true">₹</span>' +
      '<input id="pa-val" type="text" inputmode="decimal" autocomplete="off" aria-describedby="pa-err"><span class="pa-suf" aria-hidden="true">%</span></div></div>' +
      '<button type="submit" class="btn pri">Add alert</button>';
    var sel = form.querySelector('select'), inp = form.querySelector('input'), pre = form.querySelector('.pa-pre'), suf = form.querySelector('.pa-suf');
    Object.keys(KINDS).forEach(function (k) { var o = el('option', null, KINDS[k]); o.value = k; sel.appendChild(o); });
    sel.value = d.kind; inp.value = d.value;
    var err = el('div', 'pa-err'); err.id = 'pa-err'; err.setAttribute('role', 'alert');
    var wrap = form.querySelector('.pa-in');
    function sync() { var oh = sel.value === 'off_high'; pre.hidden = oh; suf.hidden = !oh; wrap.classList.toggle('pct', oh); inp.placeholder = oh ? 'e.g. 20' : 'e.g. 3300'; }
    sel.onchange = function () { d.kind = sel.value; err.textContent = ''; sync(); };
    inp.oninput = function () { d.value = inp.value; err.textContent = ''; };
    sync();
    body.appendChild(form); body.appendChild(err);

    var list = el('div', 'pa-list'); list.setAttribute('aria-live', 'polite');
    body.appendChild(list);
    body.appendChild(el('p', 'hint', 'Alerts are checked once a day, after the end-of-day scan, never during the trading day. A reached alert appears in the Portfolio alerts inbox and the alert badge in the navigation. For research and education. Not investment advice.'));

    function render(alerts) {
      list.textContent = '';
      if (!alerts.length) {
        list.innerHTML = '<div class="empty"><div class="ico"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg></div><b>No price alerts for this stock</b><span>Set a level above and you will get a reminder after the scan that closes there.</span></div>';
        return;
      }
      var ul = el('ul', 'pa-ul');
      alerts.forEach(function (a) {
        var s = statusOf(a), li = el('li', 'pa-item');
        var main = el('div', 'pa-main'); main.appendChild(el('span', 'pa-desc', describe(a.kind, a.value)));
        var chip = el('span', 'pa-chip ' + s.cls);
        chip.innerHTML = s.cls === 'reached' ? (window.Shell ? window.Shell.icon('circle-check') : '') : ICO[s.cls];
        chip.appendChild(document.createTextNode(s.text));
        main.appendChild(chip); li.appendChild(main);
        var act = el('div', 'pa-act');
        if (a.status !== 'waiting') {
          var re = el('button', 'btn', a.status === 'paused' ? 'Resume' : 'Re-arm'); re.type = 'button';
          re.onclick = function () { run(api('PUT', '/api/price-alerts', { id: a.id, active: true })); };
          act.appendChild(re);
        }
        var del = el('button', 'btn danger', 'Delete'); del.type = 'button';
        del.setAttribute('aria-label', 'Delete alert: ' + describe(a.kind, a.value));
        del.onclick = function () { run(api('DELETE', '/api/price-alerts?id=' + encodeURIComponent(a.id))); };
        act.appendChild(del); li.appendChild(act); ul.appendChild(li);
      });
      list.appendChild(ul);
    }
    function run(p) {
      return p.then(function (j) { err.textContent = ''; render(j.alerts || []); return true; })
        .catch(function (e) { err.textContent = e.message || 'Could not update the alert.'; return false; });
    }
    form.onsubmit = function (ev) {
      ev.preventDefault();
      var m = validate(sel.value, inp.value);
      if (m) { err.textContent = m; inp.focus(); return; }
      run(api('POST', '/api/price-alerts', { symbol: sym, kind: sel.value, value: Number(inp.value.replace(/,/g, '')) })).then(function (ok) {
        if (ok) { d.value = inp.value = ''; }
      });
    };
    api('GET', '/api/price-alerts?sym=' + encodeURIComponent(sym)).then(function (j) { render(j.alerts || []); })
      .catch(function () { list.textContent = ''; list.appendChild(el('p', 'hint', 'Could not load your alerts. Reload the page to try again.')); });
  }

  var helpers = { validate: validate, describe: describe, statusOf: statusOf, KINDS: KINDS };
  if (typeof window !== 'undefined') window.PriceAlerts = { mount: mount, _h: helpers };
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
})();
