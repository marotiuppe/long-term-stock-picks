/* Landing page: the theme toggle. Same storage key as the app (shell.js), so the choice carries over. Dark unless light was chosen. */
(function () {
  'use strict';
  var root = document.documentElement, btn = document.getElementById('theme');
  var SUN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></svg>';
  function dark() { return root.getAttribute('data-theme') !== 'light'; }
  function paint() {
    if (!btn) return;
    btn.innerHTML = dark() ? SUN : MOON;
    btn.setAttribute('aria-label', dark() ? 'Switch to light theme' : 'Switch to dark theme');
    var m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = dark() ? '#0F1419' : '#F8F9FB';
  }
  if (btn) btn.onclick = function () {
    var next = dark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) { /* storage blocked: the choice lasts for this visit only */ }
    paint();
  };
  paint();
})();
