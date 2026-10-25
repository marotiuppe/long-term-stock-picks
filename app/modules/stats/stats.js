/* Stats page: asks for the token, reads /api/stats with it and draws the numbers. The token is kept for this tab only (sessionStorage). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var KEY = 'stats-token';
  function saved() { try { return sessionStorage.getItem(KEY) || ''; } catch (e) { return ''; } }
  function keep(t) { try { sessionStorage.setItem(KEY, t); } catch (e) { /* this tab only; fine without it */ } }
  function forget() { try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ } }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fmt(n) { return Number(n).toLocaleString('en-IN'); }

  function draw(d) {
    var sum = d.byDay.reduce(function (a, r) { return a + r.views; }, 0);
    $('cards').innerHTML =
      '<div><b>' + fmt(d.total) + '</b><span>All time</span></div>' +
      '<div><b>' + fmt(d.today) + '</b><span>Today (IST)</span></div>' +
      '<div><b>' + fmt(sum) + '</b><span>Last ' + d.days + ' days</span></div>';
    $('nd').textContent = d.days;
    var max = d.byDay.reduce(function (m, r) { return Math.max(m, r.views); }, 1);
    $('days').innerHTML = d.byDay.length ? d.byDay.map(function (r) {
      return '<div class="drow"><span>' + esc(r.day) + '</span><span class="bar-bg"><span class="bar-fg" style="width:' + (100 * r.views / max).toFixed(1) +
        '%"></span></span><span class="n">' + fmt(r.views) + '</span></div>';
    }).join('') : '<p class="muted">No visits counted in this period.</p>';
    $('pages').innerHTML = d.byPage.map(function (r) {
      return '<tr><td>' + esc(r.path === '/' ? '/ (landing page)' : r.path) + '</td><td class="cnt">' + fmt(r.views) + '</td></tr>';
    }).join('') || '<tr><td colspan="2">Nothing yet.</td></tr>';
    $('since').textContent = d.since ? 'Counting since ' + d.since + '.' : '';
    $('out').hidden = false;
  }

  function load(token) {
    $('err').hidden = true;
    return fetch('/api/stats', { headers: { Authorization: 'Bearer ' + token }, cache: 'no-store' }).then(function (r) {
      if (r.status === 404) throw new Error('Wrong token, or the stats are switched off.');
      if (!r.ok) throw new Error('The server answered ' + r.status + '.');
      return r.json();
    }).then(function (d) { keep(token); $('gate').hidden = true; draw(d); }).catch(function (e) {
      forget(); $('out').hidden = true; $('gate').hidden = false;
      $('err').textContent = e.message || 'Could not load the stats.'; $('err').hidden = false;
    });
  }

  $('gate').addEventListener('submit', function (e) { e.preventDefault(); load($('tok').value.trim()); });
  var t = saved(); if (t) load(t);
})();
