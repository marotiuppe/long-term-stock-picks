/* "Sync from Groww": each user enters their own Groww API key and secret once; later syncs reuse the saved key.
   Read-only: the server only asks Groww for holdings. The secret is sent to the server, stored encrypted, and never shown again.
   Needs holdings.js (Holdings.api, Mine) and shell.js (Shell.sheet). */
(function () {
  'use strict';
  function E(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var DOCS = 'https://groww.in/trade-api/docs/python-sdk';
  var SAFETY = 'Read-only: this app only asks Groww for your holdings and never places or changes an order. Groww API keys may be allowed to trade, so keep yours private. ' +
    'Your key and secret are stored encrypted on the computer that runs this app and are never shown again. You can forget them at any time.';

  function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

  // r: the /api/groww/sync answer -> [{tone, text}] lines for the result view (pure, tested under node)
  function summary(r) {
    var out = [], n = (r.added || 0) + (r.updated || 0) + (r.unchanged || 0), got = r.returned == null ? n + (r.skipped || []).length : r.returned;
    out.push({ tone: n ? 'ok' : 'warn', text: got ? 'Groww returned ' + plural(got, 'holding') + '. ' + (n ? 'Synced ' + n + ': ' + (r.added || 0) + ' new, ' + (r.updated || 0) + ' updated, ' + (r.unchanged || 0) + ' unchanged.' : 'None could be imported.') : 'Groww returned no holdings to import.' });
    (r.skipped || []).forEach(function (s) { out.push({ tone: 'warn', text: s.symbol + ' was skipped: ' + s.reason + '.' }); });
    if ((r.unscanned || []).length) out.push({ tone: 'info', text: plural(r.unscanned.length, 'holding') + ' (' + r.unscanned.join(', ') + ') ' + (r.unscanned.length === 1 ? 'is' : 'are') + ' not in this app\'s stock scan, for example small or special-series shares and some ETFs. ' + (r.unscanned.length === 1 ? 'It is' : 'They are') + ' kept in your portfolio and counted in the amount invested, but ' + (r.unscanned.length === 1 ? 'shows' : 'show') + ' no price, call or chart here.' });
    if ((r.pledged || []).length) out.push({ tone: 'info', text: 'Pledged shares at Groww: ' + r.pledged.map(function (p) { return p.symbol + ' (' + p.qty + ')'; }).join(', ') + '.' });
    if ((r.not_in_groww || []).length) out.push({ tone: 'info', text: 'Not in your Groww holdings, left as they were: ' + r.not_in_groww.join(', ') + '.' });
    return out;
  }

  function fmtDate(s) { return s || 'never'; }

  // every entry Groww sent and what became of it, so a stock that seems to be missing can be found
  function detailsTable(d) {
    if (!d || !d.length) return '';
    var num = function (v) { return v == null ? '' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: 4 }); };
    var res = { 'new': 'Added', updated: 'Updated', unchanged: 'Already up to date', skipped: 'Skipped' };
    return '<details class="more"><summary>See every stock Groww sent (' + d.length + ')</summary><div class="of"><table class="mini"><caption class="sr">Stocks returned by Groww and what happened to each</caption>' +
      '<tr><th scope="col">Stock</th><th scope="col">Shares</th><th scope="col">Avg price</th><th scope="col">Result</th></tr>' +
      d.map(function (x) {
        return '<tr><th scope="row">' + E(x.symbol) + '</th><td>' + num(x.qty) + (x.pledged ? ' <small>(' + num(x.pledged) + ' pledged)</small>' : '') + '</td><td>' + num(x.avg_price) + '</td><td>' +
          E(res[x.outcome] || x.outcome) + (x.reason ? ': ' + E(x.reason) : '') + (x.unscanned && x.outcome !== 'skipped' ? ' <small>(no price here)</small>' : '') + '</td></tr>';
      }).join('') + '</table></div></details>';
  }

  function open(after) {
    var api = window.Holdings.api;
    var body = '<div id="gw"><p class="lf-n">Loading…</p></div>';
    window.Shell.sheet({ title: 'Sync from Groww', html: body, onOpen: function (b, sheet) {
      var root = b.querySelector('#gw');
      function busy(btn, on, text) { btn.disabled = on; if (text) btn.textContent = text; }

      function showResult(r) {
        root.innerHTML = '<div class="lf" role="status">' + summary(r).map(function (l) { return '<p class="' + (l.tone === 'ok' ? 'lf-ok' : 'lf-n') + '">' + E(l.text) + '</p>'; }).join('') +
          detailsTable(r.details) +
          '<p class="lf-n">Groww describes this call as covering your long-term equity delivery stocks. If the Groww app shows more than this list, the rest may be of another kind (for example mutual funds) that the call does not return.</p>' +
          '<p class="lf-n">Average buy price comes from Groww and may be rounded by Groww. Compare it with the Groww app once.</p>' +
          '<div class="lf-act"><button type="button" class="btn pri" data-x>Done</button></div></div>';
        window.Mine.load(true).then(function () { if (after) after(); });
      }

      function run(payload, errEl, btn, label) {
        errEl.textContent = '';
        busy(btn, true, 'Syncing…');
        return api('POST', '/api/groww/sync', payload).then(showResult)
          .catch(function (e) { errEl.textContent = e.message; busy(btn, false, label); });
      }

      function form(saved) {
        root.innerHTML = '<form class="lf" id="gw-f" novalidate autocomplete="off">' +
          '<p class="lf-n">' + E(SAFETY) + '</p>' +
          '<p class="lf-n">Create the key on the Groww Cloud API Keys page. With the key-and-secret method Groww asks you to approve it there each day, so approve it before you sync. A Groww Trading API subscription is needed. <a href="' + DOCS + '" target="_blank" rel="noopener">How the Groww API works</a>.</p>' +
          '<div class="lf-f"><label for="gw-k">Groww API key</label><input id="gw-k" class="lf-in" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" required></div>' +
          '<div class="lf-f"><label for="gw-s">Groww API secret</label><input id="gw-s" class="lf-in" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" required></div>' +
          '<label class="lf-rad"><input type="checkbox" id="gw-r" checked> Remember them on this computer so I only enter them once</label>' +
          '<p class="lf-err" id="gw-e" role="alert"></p>' +
          '<div class="lf-act"><button type="button" class="btn" data-x>Cancel</button>' + (saved ? '<button type="button" class="btn" id="gw-back">Use the saved key</button>' : '') + '<button class="btn pri" type="submit" id="gw-go">Sync holdings</button></div></form>';
        var f = root.querySelector('#gw-f'), er = root.querySelector('#gw-e'), go = root.querySelector('#gw-go');
        var back = root.querySelector('#gw-back'); if (back) back.onclick = function () { saved_view(saved); };
        f.addEventListener('submit', function (e) {
          e.preventDefault();
          var k = root.querySelector('#gw-k').value.trim(), s = root.querySelector('#gw-s').value.trim();
          if (!k || !s) { er.textContent = 'Enter both the API key and the API secret.'; return; }
          run({ api_key: k, api_secret: s, remember: root.querySelector('#gw-r').checked }, er, go, 'Sync holdings').then(function () {
            var a = root.querySelector('#gw-k'), c = root.querySelector('#gw-s'); if (a) a.value = ''; if (c) c.value = '';   // never leave the secret sitting in the page
          });
        });
        var first = root.querySelector('#gw-k'); if (first) first.focus();
      }

      function saved_view(st) {
        root.innerHTML = '<div class="lf"><p>Using your saved Groww key <b>' + E(st.hint || 'saved') + '</b> (saved ' + E(fmtDate(st.saved_on)) + '). Last sync: ' + E(fmtDate(st.last_sync)) + '.</p>' +
          '<p class="lf-n">If Groww says the key was not accepted, approve it again on the Groww Cloud API Keys page and sync again.</p>' +
          '<p class="lf-err" id="gw-e" role="alert"></p>' +
          '<div class="lf-act"><button type="button" class="btn lf-del" id="gw-forget">Forget saved key</button><button type="button" class="btn" id="gw-new">Use a different key</button><button type="button" class="btn pri" id="gw-now">Sync now</button></div></div>';
        var er = root.querySelector('#gw-e'), now = root.querySelector('#gw-now');
        now.onclick = function () { run({}, er, now, 'Sync now'); };
        root.querySelector('#gw-new').onclick = function () { form(st); };
        root.querySelector('#gw-forget').onclick = function () {
          if (!window.confirm('Forget the saved Groww key and secret? Your holdings stay as they are.')) return;
          api('DELETE', '/api/groww/credentials').then(function () { form(null); }).catch(function (e) { er.textContent = e.message; });
        };
        now.focus();
      }

      api('GET', '/api/groww').then(function (st) { if (st.saved) saved_view(st); else form(null); })
        .catch(function (e) { root.innerHTML = '<p class="lf-err" role="alert">' + E(e.message) + '</p><div class="lf-act"><button type="button" class="btn" data-x>Close</button></div>'; });
    } });
  }

  (typeof window !== 'undefined' ? window : globalThis).GrowwSync = { open: open, summary: summary, detailsTable: detailsTable };
  if (typeof module !== 'undefined' && module.exports) module.exports = { summary: summary, detailsTable: detailsTable };
})();
