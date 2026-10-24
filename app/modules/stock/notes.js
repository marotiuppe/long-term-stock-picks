/* notes.js: "Your notes" card on the stock page. window.Notes.mount(host, symbol, {stock, horizon}).
   The stock page rebuilds its DOM on every horizon tab click and calls mount again, so the draft lives in module state
   (per symbol), not in the DOM: typing that has not been saved yet survives a re-mount and is still saved. */
(function () {
  var MAX = 5000, DELAY = 800;
  var states = {};   // symbol -> {text, saved, loaded, timer, saving, again, err}
  var ui = null;     // the DOM of the card currently on screen

  // pure helpers (also used by the node test)
  function fmtTime(d) { var p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getHours()) + ':' + p(d.getMinutes()); }
  function counter(n) { return n.toLocaleString('en-IN') + ' / ' + MAX.toLocaleString('en-IN'); }
  function statusText(s, now) {
    if (s.err) return 'Could not save, retry';
    if (s.saving || s.text !== s.saved) return 'Saving…';
    return s.savedAt ? 'Saved ' + fmtTime(s.savedAt) : '';
  }

  function st(sym) { return states[sym] || (states[sym] = { text: '', saved: '', loaded: false, timer: null, saving: false, again: false, err: false, savedAt: null }); }
  function api(method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }

  function paint(sym) {
    if (!ui || ui.sym !== sym) return;
    var s = st(sym);
    ui.count.textContent = counter(s.text.length);
    ui.count.classList.toggle('over', s.text.length > MAX);
    ui.status.textContent = statusText(s);
    ui.status.classList.toggle('bad', !!s.err);
    ui.retry.hidden = !s.err;
    ui.del.disabled = !s.text && !s.saved;
    ui.empty.hidden = !!(s.text || s.saved);
  }

  function save(sym) {
    var s = st(sym);
    clearTimeout(s.timer); s.timer = null;
    if (s.text === s.saved && !s.err) return;
    if (s.text.length > MAX) { s.err = true; paint(sym); return; }
    if (s.saving) { s.again = true; return; }
    var sent = s.text;
    s.saving = true; s.err = false; paint(sym);
    api('PUT', '/api/notes', { symbol: sym, text: sent }).then(function () {
      s.saved = sent; s.savedAt = new Date();   // whitespace-only text is deleted server-side, which equals "nothing to save"
    }).catch(function () { s.err = true; }).then(function () {
      s.saving = false; paint(sym);
      if (s.again) { s.again = false; save(sym); }
    });
  }

  function schedule(sym) {
    var s = st(sym);
    s.err = false; clearTimeout(s.timer);
    s.timer = setTimeout(function () { save(sym); }, DELAY);
    paint(sym);
  }

  function build(host, sym) {
    host.innerHTML = '<div class="card nt"><div class="card-h"><div><h2>Your notes</h2><p>Why you like it, what would change your mind, when to look again.</p></div></div>' +
      '<div class="card-b"><div class="nt-empty hint" data-e>No note yet. Write down your reasons while they are fresh. It helps you hold or review with a clear head.</div>' +
      '<label class="nt-l" for="nt-ta">Note for ' + sym.replace(/[^A-Z0-9&-]/g, '') + '</label>' +
      '<textarea id="nt-ta" class="nt-ta" rows="6" spellcheck="true" aria-describedby="nt-count nt-priv"></textarea>' +
      '<div class="nt-row"><span id="nt-count" class="nt-count hint" data-c></span>' +
      '<span class="nt-status hint" data-s role="status" aria-live="polite"></span>' +
      '<button type="button" class="btn" data-r hidden>Retry</button>' +
      '<button type="button" class="btn danger" data-d>Delete note</button></div>' +
      '<p id="nt-priv" class="hint">Notes are stored on this server for this browser only. For research and education. Not investment advice.</p></div></div>';
    var ta = host.querySelector('textarea');
    ui = { sym: sym, ta: ta, count: host.querySelector('[data-c]'), status: host.querySelector('[data-s]'), retry: host.querySelector('[data-r]'),
           del: host.querySelector('[data-d]'), empty: host.querySelector('[data-e]') };
    var s = st(sym);
    ta.value = s.text;
    ta.oninput = function () { s.text = ta.value; schedule(sym); };
    ta.onblur = function () { if (s.text !== s.saved) save(sym); };
    ui.retry.onclick = function () { s.err = false; save(sym); };
    ui.del.onclick = function () {
      if (!window.confirm('Delete your note for ' + sym + '? This cannot be undone.')) return;
      clearTimeout(s.timer);
      api('DELETE', '/api/notes?sym=' + encodeURIComponent(sym)).then(function () {
        s.text = s.saved = ''; s.err = false; s.savedAt = null; if (ui && ui.sym === sym) ui.ta.value = ''; paint(sym);
      }).catch(function () { s.err = true; paint(sym); });
    };
    paint(sym);
    return ta;
  }

  function mount(host, symbol) {
    var sym = String(symbol || '').toUpperCase();
    if (!host || !sym) return;
    var s = st(sym), ta = build(host, sym);
    if (s.loaded) return;
    s.loaded = true;
    ta.disabled = true;
    api('GET', '/api/notes?sym=' + encodeURIComponent(sym)).then(function (n) {
      if (!s.text) { s.text = s.saved = n.text || ''; }   // never overwrite something typed while loading
      else s.saved = n.text || '';
      if (n.updated) s.savedAt = new Date(n.updated);
    }).catch(function () { s.loaded = false; }).then(function () {
      if (ui && ui.sym === sym) { ui.ta.disabled = false; if (ui.ta.value !== s.text) ui.ta.value = s.text; }
      paint(sym);
    });
  }

  var helpers = { fmtTime: fmtTime, counter: counter, statusText: statusText, MAX: MAX };
  if (typeof window !== 'undefined') window.Notes = { mount: mount, _h: helpers };
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
})();
