/* "Needs your attention": rule-based review prompts for the stocks you hold, the bell count, and optional browser notifications.
   The server evaluates the rules (rules.py) from your transactions and real data; this file only shows the result.
   Every prompt carries the rule that fired and the numbers behind it. Nothing here says buy or sell as a certainty. */
(function () {
  'use strict';
  var state = { data: null, promise: null, all: false };
  var SHOWN = 4;
  var $ = function (id) { return document.getElementById(id); };
  function E(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function icon(n, c) { return window.Shell ? window.Shell.icon(n, c) : ''; }

  function load(force) {
    if (state.promise && !force) return state.promise;
    state.promise = Holdings.api('GET', '/api/attention').then(function (d) {
      state.data = d; Shell.setBell(d.unseen); maybeNotify(d); return d;
    }).catch(function (e) { state.promise = null; throw e; });
    return state.promise;
  }

  // ---------- optional browser notification: only if the user switched it on, silent, once per new alert ----------
  function notifyOn() { try { return localStorage.getItem('notify') === '1' && window.Notification && Notification.permission === 'granted'; } catch (e) { return false; } }
  function maybeNotify(d) {
    if (!notifyOn() || !d.unseen) return;
    try {
      var done = JSON.parse(localStorage.getItem('notified') || '[]'), fresh = d.alerts.filter(function (a) { return a.unseen && done.indexOf(a.key + '|' + a.fingerprint) < 0; });
      if (!fresh.length) return;
      new Notification('Stock picks: ' + fresh.length + (fresh.length === 1 ? ' holding needs' : ' holdings need') + ' a look', { body: fresh.slice(0, 3).map(function (a) { return a.symbol + ': ' + a.title; }).join('. ') + '. For research and education.', silent: true, tag: 'attention' });
      localStorage.setItem('notified', JSON.stringify(done.concat(fresh.map(function (a) { return a.key + '|' + a.fingerprint; })).slice(-200)));
    } catch (e) { /* notifications are optional */ }
  }
  function enableNotifications() {
    if (!window.Notification) return Promise.reject(new Error('This browser does not support notifications.'));
    return Notification.requestPermission().then(function (p) {
      if (p !== 'granted') throw new Error('Notifications were not allowed in the browser, so they stay off.');
      try { localStorage.setItem('notify', '1'); } catch (e) { /* ignore */ }
    });
  }
  function disableNotifications() { try { localStorage.setItem('notify', '0'); } catch (e) { /* ignore */ } }

  // ---------- the feed ----------
  var ICON = { add: 'circle-plus', review: 'eye', info: 'info' };
  function dateText(iso) { return iso ? Holdings.longDate(iso) : ''; }
  function alertHtml(a) {
    return '<li class="al al-' + a.tone + '" data-key="' + E(a.key) + '"><div class="al-rail"><a class="al-ic" href="/stock.html?symbol=' + encodeURIComponent(a.symbol) + '" title="View stock" aria-label="View stock ' + E(a.symbol) + '">' + icon('eye') + '</a>' +
      '<span class="al-q"><button type="button" class="ibtn sm" title="Add shares" aria-label="Add shares" data-add="' + E(a.symbol) + '">' + icon('plus', 'sm') + '</button>' +
      '<button type="button" class="ibtn sm" title="Snooze 7 days" aria-label="Snooze 7 days" data-snooze="' + E(a.key) + '" data-fp="' + E(a.fingerprint) + '">' + icon('clock', 'sm') + '</button>' +
      '<button type="button" class="ibtn sm" title="Dismiss" aria-label="Dismiss" data-dismiss="' + E(a.key) + '" data-fp="' + E(a.fingerprint) + '">' + icon('x', 'sm') + '</button></span></div><div class="al-b">' +
      '<div class="al-h"><span class="al-lab">' + E(a.label) + '</span><a class="al-sym" href="/stock.html?symbol=' + encodeURIComponent(a.symbol) + '">' + E(a.symbol) + '</a>' + (a.unseen ? '<span class="al-new">New</span>' : '') + '</div>' +
      '<div class="al-sub"><span class="al-name">' + E(a.name) + '</span><span class="al-date">As of ' + E(dateText(a.as_of)) + '</span></div>' +
      '<p class="al-t">' + E(a.title) + '</p><p class="al-r">' + E(a.reason) + '</p><details class="more al-rule"><summary>Why this alert</summary><p class="mu"><b>Rule that fired:</b> ' + E(a.rule_text) + '</p></details></div></li>';
  }
  function footHtml(d) {
    var cov = d.coverage.map(function (c) {
      var t = c.status === 'ok' ? 'Company results to the quarter ended ' + dateText(c.latest_quarter) + ' (' + c.quarters + ' quarters), looked up ' + dateText(c.fetched) + '.'
        : c.status === 'stale' ? (c.reason || 'Older copy of company results.')
        : 'Data unavailable: ' + (c.reason || 'no company results.') + (c.fetched ? ' Checked ' + dateText(c.fetched) + '.' : '');
      return '<li><b>' + E(c.symbol) + '</b> ' + E(t) + '</li>';
    }).join('');
    var gaps = d.not_evaluated.map(function (g) { return '<li><b>' + E(g.symbol) + '</b> ' + E(g.title) + ': ' + E(g.why) + '</li>'; }).join('');
    return '<div class="al-foot"><p class="al-disc">' + E(d.disclaimer) + ' These are prompts to look again, built from your own transactions and public data. They do not predict anything.</p>' +
      (d.hidden ? '<p class="al-hid">' + d.hidden + ' dismissed or snoozed alert' + (d.hidden === 1 ? ' is' : 's are') + ' hidden until the condition changes.</p>' : '') +
      '<details class="more"><summary>Data used and what could not be checked</summary>' + (cov ? '<h3 class="al-dh">Company data</h3><ul class="al-dl">' + cov + '</ul>' : '') +
      (gaps ? '<h3 class="al-dh">Not checked for lack of data</h3><ul class="al-dl">' + gaps + '</ul>' : '<p class="mu">Every enabled rule could be checked with the data available.</p>') +
      '<p class="mu">Company results come from Yahoo Finance and cover only about five quarters for most NSE and BSE stocks; ETFs and many banks have none. A rule that needs data that is missing does not fire.</p></details></div>';
  }

  /* Fills `el` (a .card) with the feed. */
  function mountFeed(el) {
    function shell(inner) {
      return '<div class="card-h"><div><h2 id="attn-h" tabindex="-1">Needs your attention</h2><p>Review prompts for the stocks you own, from the rules in Settings.</p></div><a class="btn sm" href="/settings.html">' + icon('settings', 'sm') + 'Rules</a></div><div class="card-b">' + inner + '</div>';
    }
    el.setAttribute('aria-labelledby', 'attn-h');
    el.innerHTML = shell('<div class="sk" style="width:60%;height:20px"></div><div class="sk" style="width:95%"></div><div class="sk" style="width:80%"></div>');
    function draw(d, focusKey) {
      if (!d.holdings) {
        el.innerHTML = '<div class="card-h attn-compact"><div><h2 id="attn-h" tabindex="-1">Needs your attention</h2><p>Add a holding and your rules in Settings will flag it here. ' + E(d.disclaimer) + '</p></div><button class="btn sm pri" type="button" data-addnew>' + icon('plus', 'sm') + 'Add a holding</button></div>';
      } else if (!d.alerts.length) {
        el.innerHTML = shell('<div class="empty"><div class="ico">' + icon('circle-check') + '</div><b>Nothing needs attention</b><span>Your holdings are within your rules.</span></div>') + footHtml(d);
      } else {
        var shown = state.all ? d.alerts : d.alerts.slice(0, SHOWN), more = d.alerts.length - shown.length;
        el.innerHTML = shell('<ul class="alist" aria-label="Alerts, most important first">' + shown.map(alertHtml).join('') + '</ul>' +
          (d.alerts.length > SHOWN ? '<button type="button" class="btn al-more" data-more aria-expanded="' + state.all + '">' + (state.all ? 'Show fewer' : 'Show ' + more + ' more alert' + (more === 1 ? '' : 's')) + '</button>' : '')) + footHtml(d);
      }
      if (focusKey) { var t = el.querySelector('#attn-h'); if (t) t.focus({ preventScroll: true }); }
      var seen = {}; d.alerts.forEach(function (a) { if (a.unseen) seen[a.key] = a.fingerprint; });
      if (Object.keys(seen).length) Holdings.api('POST', '/api/attention/seen', { seen: seen }).then(function () { Shell.setBell(0); }).catch(function () { /* the count just stays */ });
    }
    function fail(e) {
      el.innerHTML = shell('<div class="empty"><div class="ico">' + icon('triangle-alert') + '</div><b>Could not check your alerts</b><span>' + E(e.message) + '</span><button class="btn" type="button" data-retry>Try again</button></div>');
    }
    function run(force, fk) { return load(force).then(function (d) { draw(d, fk); }).catch(fail); }
    el.addEventListener('click', function (e) {
      // a click on the card itself (not a button, link or the rule disclosure) opens the stock
      var card = e.target.closest('li.al');
      if (card && !e.target.closest('a,button,details') && !(window.getSelection && String(window.getSelection()))) {
        var v = card.querySelector('a.al-ic'); if (v) { location.href = v.getAttribute('href'); return; }
      }
      var t =e.target.closest('[data-add],[data-dismiss],[data-snooze],[data-retry],[data-addnew],[data-more]'); if (!t) return;
      if (t.hasAttribute('data-more')) { state.all = !state.all; draw(state.data); var nb = el.querySelector('[data-more]'); if (nb) nb.focus(); return; }
      if (t.hasAttribute('data-retry')) { el.innerHTML = shell('<div class="sk" style="width:60%;height:20px"></div><div class="sk" style="width:90%"></div>'); return run(true); }
      if (t.hasAttribute('data-addnew')) return Holdings.openLotForm({ side: 'buy', onSaved: function () { run(true); document.dispatchEvent(new CustomEvent('mine:update')); } });
      if (t.dataset.add) { var a = state.data.alerts.find(function (x) { return x.symbol === t.dataset.add; }); return Holdings.openLotForm({ symbol: t.dataset.add, name: a && a.name, side: 'buy', onSaved: function () { run(true); } }); }
      var key = t.dataset.dismiss || t.dataset.snooze, act = t.dataset.dismiss ? 'dismiss' : 'snooze';
      t.disabled = true;
      Holdings.api('POST', '/api/attention/state', { key: key, fingerprint: t.dataset.fp, action: act, days: 7 }).then(function () {
        Holdings.say((act === 'dismiss' ? 'Dismissed ' : 'Snoozed for 7 days: ') + key.split('|')[0]); return run(true, true);
      }).catch(function (err) { t.disabled = false; Holdings.say(err.message); });
    });
    return run(false);
  }

  window.Attention = { load: load, mountFeed: mountFeed, state: state, enableNotifications: enableNotifications, disableNotifications: disableNotifications, notifyOn: notifyOn };
  document.addEventListener('DOMContentLoaded', function () { load().catch(function () { /* the bell just shows nothing */ }); });
  if (document.readyState !== 'loading') load().catch(function () { /* same */ });
})();
