/* Admin shell shared by every page: sidebar, top bar, status line and footer, built around the page's own <main id="app">.
   Load it in <head> (it applies the saved theme before first paint), then call Shell.mount() once the body has parsed.
   common.js does that as its first line; if no page script does, it mounts on DOMContentLoaded.
   The body says which page it is: <body data-page="stocks" data-title="NSE stocks">. */
(function () {
  'use strict';
  var root = document.documentElement, THEME = 'theme', SIDE = 'sidebar';
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked: keep going without it */ } }
  };

  // ---------- icons (Lucide, inline SVG, one set for the whole app) ----------
  var P = {
    trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    'circle-plus': '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/>',
    eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    upload: '<path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
    bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    ellipsis: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    house: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'trending-up': '<path d="M16 7h6v6"/><path d="m22 7-8.5 8.5-5-5L2 17"/>',
    layers: '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
    landmark: '<path d="M10 18v-7"/><path d="M11.12 2.198a2 2 0 0 1 1.76.006l7.866 3.847c.476.233.31.949-.22.949H3.474c-.53 0-.695-.716-.22-.949z"/><path d="M14 18v-7"/><path d="M18 18v-7"/><path d="M3 22h18"/><path d="M6 18v-7"/>',
    briefcase: '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    moon: '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
    'refresh-cw': '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    menu: '<path d="M4 12h16"/><path d="M4 6h16"/><path d="M4 18h16"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'chevron-left': '<path d="m15 18-6-6 6-6"/>',
    'chevron-right': '<path d="m9 18 6-6-6-6"/>',
    'chevrons-up-down': '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
    'arrow-up': '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    'arrow-down': '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    'arrow-up-right': '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    'arrow-down-right': '<path d="m7 7 10 10"/><path d="M17 7v10H7"/>',
    'arrow-left': '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    download: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
    'file-spreadsheet': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h2"/><path d="M14 13h2"/><path d="M8 17h2"/><path d="M14 17h2"/>',
    'panel-left': '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    wallet: '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    'chart-pie': '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z"/><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>',
    star: '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
    percent: '<line x1="19" x2="5" y1="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
    list: '<path d="M3 5h.01"/><path d="M3 12h.01"/><path d="M3 19h.01"/><path d="M8 5h13"/><path d="M8 12h13"/><path d="M8 19h13"/>',
    'circle-check': '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'
  };
  function icon(name, cls) {
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + (P[name] || '') + '</svg>';
  }

  // ---------- session ----------
  // Each browser is one anonymous user, identified by a cookie the server hands out on the first API call. If several calls
  // start at once with no cookie yet, each would be given a different identity and the last cookie would win, which could swap
  // a person to an empty account. So one call goes first (/api/session) and every API call after it waits for it.
  var sessionReady = fetch('/api/session', { credentials: 'same-origin' }).then(function () {}, function () {});
  window.Session = { ready: sessionReady, fetch: function (u, o) { return sessionReady.then(function () { return fetch(u, o); }); } };

  // ---------- signed-in state ----------
  // One GET /api/auth/me per page load, cached in window.Auth.me. Failure is silent and counts as a guest (chip says "Sign in").
  var authP = null, authSubs = [];
  function chipLabel(me) { return me && me.signedIn ? (me.username || 'Groww account') : 'Sign in'; }
  function paintChip() {
    var c = document.getElementById('acct'); if (!c) return;
    var me = window.Auth.me, label = chipLabel(me), on = !!(me && me.signedIn);
    c.querySelector('.acl').textContent = label; c.classList.toggle('in', on);
    c.setAttribute('aria-label', on ? 'Account, signed in as ' + label : 'Sign in or create an account'); c.title = on ? 'Signed in as ' + label : 'Sign in';
  }
  window.Auth = { me: null, load: function (force) {
    if (authP && !force) return authP;
    authP = window.Session.fetch('/api/auth/me', { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok || !/json/i.test(r.headers.get('content-type') || '')) return null;
      return r.json();
    }).catch(function () { return null; }).then(function (j) {
      window.Auth.me = j && typeof j === 'object' && 'signedIn' in j ? j : null; paintChip();
      authSubs.forEach(function (f) { try { f(window.Auth.me); } catch (e) { /* subscriber failed */ } });
      return window.Auth.me;
    });
    return authP;
  }, on: function (f) { authSubs.push(f); } };

  // ---------- theme ----------
  function effective() {
    var t = root.getAttribute('data-theme');
    return t === 'light' ? 'light' : 'dark';   // dark is the default; the system setting is not followed
  }
  function applySaved() {
    var t = store.get(THEME);
    root.setAttribute('data-theme', t === 'light' ? 'light' : 'dark');
  }
  function themeColor() {
    var dark = effective() === 'dark', phone = matchMedia('(max-width:768px)').matches;
    var m = document.querySelector('meta[name="theme-color"]');
    if (!m) { m = document.createElement('meta'); m.name = 'theme-color'; document.head.appendChild(m); }
    m.content = phone ? (dark ? '#1A2029' : '#FFFFFF') : (dark ? '#0F1419' : '#F8F9FB');
  }
  function paintToggle() {
    themeColor();
    var b = document.getElementById('theme'); if (!b) return;
    var dark = effective() === 'dark';
    b.innerHTML = icon(dark ? 'sun' : 'moon');
    b.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    b.title = dark ? 'Light theme' : 'Dark theme';
  }
  applySaved();   // before first paint
  themeColor();
  addEventListener('storage', function (e) { if (e.key === THEME) { applySaved(); paintToggle(); } });   // another tab changed it

  // ---------- shell ----------
  // Desktop and tablet: sidebar + top bar. Phone (768px and below): top app bar + bottom navigation, sheets for More, filters and the
  // account menu, and a full-screen search. Both are built from the same markup; CSS decides which one shows.
  var NAV = [['home', '/index.html', 'Home', 'house'], ['stocks', '/stocks.html', 'NSE stocks', 'trending-up'], ['etfs', '/etfs.html', 'ETFs', 'layers'], ['livecheck', '/livecheck.html', 'Live check', 'circle-check'],
    ['bse', '/bse.html', 'BSE stocks', 'landmark'], ['portfolio', '/portfolio.html', 'Portfolio', 'briefcase'],
    ['account', '/account.html', 'Account', 'user'], ['settings', '/settings.html', 'Settings', 'settings'], ['about', '/about.html', 'About', 'info']];
  var BN = { home: 'Home', stocks: 'Stocks', etfs: 'ETFs', portfolio: 'Portfolio' };   // bottom bar: four destinations plus More
  var MORE = ['livecheck', 'bse', 'account', 'settings', 'about'];
  var MQ = matchMedia('(max-width:768px)');
  var mounted = false, shell, titleText = '', pageId = '', searchSource = function () { return null; };

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function $(id) { return document.getElementById(id); }
  function navItem(p) { return NAV.filter(function (n) { return n[0] === p; })[0]; }

  function setActive(p, loose) {
    document.querySelectorAll('#links a, #bnav a').forEach(function (a) {
      if (a.dataset.p === p) a.setAttribute('aria-current', loose ? 'true' : 'page'); else a.removeAttribute('aria-current');
    });
    var more = $('more'); if (more) { if (MORE.indexOf(p) >= 0) more.setAttribute('aria-current', loose ? 'true' : 'page'); else more.removeAttribute('aria-current'); }
  }
  function paintTitle() {
    var el = $('ptitle'); if (el) el.textContent = (pageId === 'home' && MQ.matches) ? 'Stock picks' : titleText;
  }
  function setTitle(t) { titleText = t; paintTitle(); }
  function setBack(href) {   // inner pages show a back arrow instead of the logo on the phone
    var b = $('tb-back'); if (!b) return; if (href) { b.href = href; shell.classList.add('has-back'); } else shell.classList.remove('has-back');
  }
  function setBadge(p, n) {
    var name = navItem(p) ? navItem(p)[2] : p;
    document.querySelectorAll('#links a[data-p="' + p + '"], #bnav a[data-p="' + p + '"]').forEach(function (a) {
      var old = a.querySelector('.nbadge'); if (old) old.remove();
      if (n) { var b = document.createElement('span'); b.className = 'nbadge'; b.textContent = n; (a.querySelector('.pill') || a).appendChild(b); a.setAttribute('aria-label', name + ', ' + n + ' unread alerts'); }
      else a.removeAttribute('aria-label');
    });
  }
  // The bell counts holdings alerts you have not looked at yet ("Needs your attention" on the dashboard).
  function setBell(n) {
    var bell = $('bell'); if (!bell) return;
    var d = bell.querySelector('.nbadge'); if (d) d.remove();
    if (n) { var x = document.createElement('span'); x.className = 'nbadge'; x.textContent = n > 99 ? '99+' : n; bell.appendChild(x); }
    bell.setAttribute('aria-label', n ? 'Alerts needing attention, ' + n + ' new' : 'Alerts needing attention');
  }

  // ---------- body scroll lock, focus trap ----------
  var locks = 0;
  function lock(on) { locks = Math.max(0, locks + (on ? 1 : -1)); root.classList.toggle('noscroll', locks > 0); }
  var stack = [];
  function focusable(c) { return [].slice.call(c.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])')).filter(function (e) { return e.offsetParent !== null; }); }
  function trap(e, c) {
    if (e.key !== 'Tab') return;
    var f = focusable(c); if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // ---------- bottom sheet ----------
  // o: {title, html, onOpen(bodyEl, api)}. Closes on the scrim, the close button, Escape or a downward drag on the handle.
  function sheet(o) {
    var prev = document.activeElement, closed = false, me = {};
    stack.push(me);
    var wrap = document.createElement('div'); wrap.className = 'sheet-wrap';
    wrap.innerHTML = '<div class="sheet-scrim" data-x></div><div class="sheet" role="dialog" aria-modal="true" aria-label="' + esc(o.title) + '">' +
      '<div class="sheet-grab" data-grab><i></i></div><div class="sheet-h"><h2>' + esc(o.title) + '</h2><button type="button" class="ibtn" data-x aria-label="Close">' + icon('x') + '</button></div>' +
      '<div class="sheet-b">' + (o.html || '') + '</div></div>';
    document.body.appendChild(wrap); lock(true);
    var sh = wrap.querySelector('.sheet');
    function close() {
      if (closed) return; closed = true;
      stack.splice(stack.indexOf(me), 1);
      document.removeEventListener('keydown', onKey, true); wrap.classList.remove('open'); lock(false);
      setTimeout(function () { wrap.remove(); }, 200);
      if (prev && prev.focus) prev.focus();
      if (o.onClose) o.onClose();
    }
    function onKey(e) { if (stack[stack.length - 1] !== me) return; if (e.key === 'Escape') { e.stopPropagation(); close(); } else trap(e, sh); }
    document.addEventListener('keydown', onKey, true);
    wrap.addEventListener('click', function (e) { if (e.target.closest('[data-x]')) close(); });
    var y0 = null, grab = wrap.querySelector('[data-grab]');
    grab.addEventListener('pointerdown', function (e) { y0 = e.clientY; grab.setPointerCapture(e.pointerId); sh.style.transition = 'none'; });
    grab.addEventListener('pointermove', function (e) { if (y0 !== null) sh.style.transform = 'translateY(' + Math.max(0, e.clientY - y0) + 'px)'; });
    grab.addEventListener('pointerup', function (e) {
      if (y0 === null) return; var dy = e.clientY - y0; y0 = null; sh.style.transition = ''; sh.style.transform = '';
      if (dy > 80) close();
    });
    var api = { close: close, el: sh.querySelector('.sheet-b') };
    requestAnimationFrame(function () { wrap.classList.add('open'); var f = focusable(sh.querySelector('.sheet-b')); (f[0] || sh.querySelector('[data-x]')).focus(); });
    if (o.onOpen) o.onOpen(api.el, api);
    return api;
  }

  // ---------- search overlay ----------
  function recents() { try { return JSON.parse(store.get('recent') || '[]'); } catch (e) { return []; } }
  function addRecent(sym) { var r = recents().filter(function (x) { return x !== sym; }); r.unshift(sym); store.set('recent', JSON.stringify(r.slice(0, 6))); }
  var searchPrev = null;
  function row(s, ico) {
    var tag = s.etf ? '<span class="etf">ETF</span>' : s.exchange === 'BSE' ? '<span class="etf">BSE</span>' : '';
    return '<a class="srow" href="/stock.html?symbol=' + encodeURIComponent(s.symbol) + '" data-sym="' + esc(s.symbol) + '"><span class="si">' + icon(ico) + '</span>' +
      '<span class="sn"><b>' + esc(s.symbol) + '</b>' + tag + '<small>' + esc(s.name || '') + '</small></span>' +
      (s.price != null ? '<span class="sp">₹' + Number(s.price).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '</span>' : '') + '</a>';
  }
  function renderSearch() {
    var out = $('sres'), q = $('sq').value.trim().toUpperCase(), list = searchSource();
    if (!q) {
      var r = recents();
      if (!r.length) { out.innerHTML = '<p class="shint">Search by symbol or company name. Stocks you open show up here as recent searches.</p>'; return; }
      var byS = {}; (list || []).forEach(function (s) { byS[s.symbol] = s; });
      out.innerHTML = '<div class="sh-h"><h2>Recent searches</h2><button type="button" class="chip" id="sclr">Clear</button></div>' +
        r.map(function (sym) { return row(byS[sym] || { symbol: sym }, 'history'); }).join('');
      $('sclr').onclick = function () { store.set('recent', '[]'); renderSearch(); $('sq').focus(); };
      return;
    }
    if (!list) { out.innerHTML = '<p class="shint">The stock list is still loading. Try again in a moment.</p>'; return; }
    var hits = list.map(function (s) {
      var sy = s.symbol.toUpperCase(), nm = String(s.name || '').toUpperCase(), k = sy === q ? 0 : sy.indexOf(q) === 0 ? 1 : sy.indexOf(q) > 0 ? 2 : nm.indexOf(q) >= 0 ? 3 : 9;
      return { s: s, k: k };
    }).filter(function (x) { return x.k < 9; }).sort(function (a, b) { return a.k - b.k || a.s.symbol.localeCompare(b.s.symbol); }).slice(0, 30);
    out.innerHTML = hits.length ? hits.map(function (x) { return row(x.s, 'trending-up'); }).join('')
      : '<p class="shint">No stock or ETF matches "' + esc($('sq').value.trim()) + '". Only names that passed the quality checks are listed.</p>';
  }
  function openSearch() {
    var s = $('search'); if (!s || !s.hidden) return;
    searchPrev = document.activeElement; s.hidden = false; lock(true); $('sq').value = ''; renderSearch(); $('sq').focus();
  }
  function closeSearch() {
    var s = $('search'); if (!s || s.hidden) return;
    s.hidden = true; lock(false); if (searchPrev && searchPrev.focus) searchPrev.focus();
  }

  // ---------- actions shared by the desktop top bar, the account menu and the More sheet ----------
  function toggleTheme() {
    var next = effective() === 'dark' ? 'light' : 'dark';
    store.set(THEME, next); root.setAttribute('data-theme', next); paintToggle();
  }
  function refreshData() { var b = $('rf'); if (b) b.click(); }
  var popOpen = false;
  function closePop() { var p = $('pop'); if (!p || p.hidden) return; p.hidden = true; $('avatar').setAttribute('aria-expanded', 'false'); popOpen = false; }
  function openPop() {
    var p = $('pop'), dark = effective() === 'dark';
    p.innerHTML = '<a role="menuitem" href="/portfolio.html">' + icon('briefcase') + 'My portfolio</a>' +
      '<button type="button" role="menuitem" data-a="theme">' + icon(dark ? 'sun' : 'moon') + (dark ? 'Light theme' : 'Dark theme') + '</button>' +
      '<button type="button" role="menuitem" data-a="refresh">' + icon('refresh-cw') + 'Refresh data</button>' +
      '<a role="menuitem" href="/account.html">' + icon('user') + 'Account</a>' +
      '<a role="menuitem" href="/settings.html">' + icon('settings') + 'Settings</a>' +
      '<a role="menuitem" href="/about.html">' + icon('info') + 'About</a>';
    p.hidden = false; popOpen = true; $('avatar').setAttribute('aria-expanded', 'true');
    var f = focusable(p); if (f[0]) f[0].focus();
  }
  function openMore() {
    var dark = effective() === 'dark';
    sheet({ title: 'More', html:
      '<ul class="mlist">' + MORE.map(function (p) { var n = navItem(p); return '<li><a href="' + n[1] + '">' + icon(n[3]) + '<span>' + n[2] + '</span>' + icon('chevron-right', 'sm') + '</a></li>'; }).join('') +
      '<li><button type="button" data-a="theme" role="switch" aria-checked="' + dark + '">' + icon(dark ? 'moon' : 'sun') + '<span>Dark theme</span><i class="tgl"></i></button></li>' +
      '<li><button type="button" data-a="refresh">' + icon('refresh-cw') + '<span>Refresh data</span></button></li></ul>',
      onOpen: function (body, api) {
        body.addEventListener('click', function (e) {
          var b = e.target.closest('[data-a]'); if (!b) return;
          if (b.dataset.a === 'theme') { toggleTheme(); var d = effective() === 'dark'; b.setAttribute('aria-checked', d); b.firstChild.outerHTML = icon(d ? 'moon' : 'sun'); }
          else { api.close(); refreshData(); }
        });
      } });
  }

  function mount() {
    if (mounted || !document.body) return;
    mounted = true;
    var B = document.body, page = B.dataset.page || '', title = B.dataset.title || document.title, back = B.dataset.back || '';
    var app = $('app'); pageId = page;
    shell = document.createElement('div'); shell.className = 'shell' + (store.get(SIDE) === 'rail' ? ' rail' : '') + (back ? ' has-back' : ''); shell.id = 'shell';
    shell.innerHTML =
      '<aside class="side" id="side" aria-label="Sidebar">' +
        '<a class="brand" href="/index.html"><span class="logo">' + icon('trending-up') + '</span><span class="brand-name">Stock picks</span></a>' +
        '<nav aria-label="Main"><div class="links" id="links">' +
          NAV.map(function (n) { return '<a href="' + n[1] + '" data-p="' + n[0] + '" title="' + n[2] + '">' + icon(n[3]) + '<span class="lb">' + n[2] + '</span></a>'; }).join('') +
        '</div></nav>' +
        '<button type="button" class="sb-toggle" id="sbt" aria-expanded="' + !shell.classList.contains('rail') + '" aria-label="Collapse sidebar">' + icon('panel-left') + '<span>Collapse</span></button>' +
      '</aside>' +
      '<div class="col">' +
        '<header class="topbar">' +
          '<a class="logo tb-logo" href="/index.html" aria-label="Stock picks, home">' + icon('trending-up') + '</a>' +
          '<a class="ibtn tb-back" id="tb-back" href="' + esc(back || '/index.html') + '" aria-label="Back">' + icon('arrow-left') + '</a>' +
          '<p class="tb-title" id="ptitle"></p><span class="tb-sp"></span>' +
          '<button type="button" class="ibtn" id="sbtn" aria-label="Search stocks" title="Search">' + icon('search') + '</button>' +
          '<a class="ibtn tb-bell" id="bell" href="/index.html#attention" aria-label="Alerts needing attention">' + icon('bell') + '</a>' +
          '<button type="button" class="ibtn tb-d" id="rf" aria-label="Refresh data" title="Refresh data">' + icon('refresh-cw') + '<span class="txt">Refresh data</span></button>' +
          '<button type="button" class="ibtn tb-d" id="theme"></button>' +
          '<a class="acct-chip" id="acct" href="/account.html"' + (page === 'account' ? ' aria-current="page"' : '') + '>' + icon('user') + '<span class="acl">Sign in</span></a>' +
          '<button type="button" class="ibtn tb-avatar" id="avatar" aria-label="Account menu" aria-haspopup="menu" aria-expanded="false"><span>' + icon('user') + '</span></button>' +
          '<div class="pop" id="pop" role="menu" aria-label="Account" hidden></div>' +
        '</header>' +
        '<div class="w"><div class="status"><div class="load" id="meta" role="status" aria-live="polite"><i></i>Starting…</div></div>' +
          '<footer><div class="ft">For education only. Not investment advice and not a recommendation to buy or sell any stock or ETF; we are not responsible for your decisions. <a href="/disclaimer.html">Disclaimer</a> · <a href="/terms.html">Terms</a> · <a href="/privacy.html">Privacy</a> · <a href="/cookies.html">Cookies</a> · <a href="/about.html">Data and method</a></div></footer></div>' +
      '</div>' +
      '<nav class="bnav" id="bnav" aria-label="Main">' +
        Object.keys(BN).map(function (p) { var n = navItem(p); return '<a href="' + n[1] + '" data-p="' + p + '" aria-label="' + n[2] + '"><span class="pill">' + icon(n[3]) + '</span><span class="lb">' + BN[p] + '</span></a>'; }).join('') +
        '<button type="button" id="more" aria-haspopup="dialog" aria-label="More"><span class="pill">' + icon('ellipsis') + '</span><span class="lb">More</span></button>' +
      '</nav>' +
      '<div class="search" id="search" role="dialog" aria-modal="true" aria-label="Search stocks" hidden>' +
        '<div class="search-p"><div class="search-bar"><button type="button" class="ibtn" id="sx" aria-label="Close search">' + icon('arrow-left') + '</button>' +
          '<input id="sq" type="search" placeholder="Search symbol or company" autocomplete="off" autocapitalize="characters" spellcheck="false" aria-label="Search symbol or company"></div>' +
        '<div class="search-r" id="sres" aria-live="polite"></div></div></div>';
    B.insertBefore(shell, B.firstChild);
    var skip = document.createElement('a'); skip.className = 'skip'; skip.href = '#app'; skip.textContent = 'Skip to content'; B.insertBefore(skip, B.firstChild);
    var w = shell.querySelector('.w'); if (app) w.insertBefore(app, w.querySelector('footer'));
    setTitle(title); setActive(page); paintToggle(); paintChip(); window.Auth.load();

    $('theme').onclick = toggleTheme;
    $('sbt').onclick = function () {
      var rail = shell.classList.toggle('rail'); store.set(SIDE, rail ? 'rail' : 'full');
      this.setAttribute('aria-expanded', !rail); this.setAttribute('aria-label', rail ? 'Expand sidebar' : 'Collapse sidebar');
      this.title = rail ? 'Expand sidebar' : '';
    };
    $('more').onclick = openMore;
    $('sbtn').onclick = openSearch;
    $('sx').onclick = closeSearch;
    $('sq').oninput = renderSearch;
    $('sq').onkeydown = function (e) { if (e.key === 'Enter') { var a = $('sres').querySelector('.srow'); if (a) { addRecent(a.dataset.sym); location.href = a.href; } } };
    $('sres').addEventListener('click', function (e) { var a = e.target.closest('.srow'); if (a) addRecent(a.dataset.sym); });
    $('search').addEventListener('click', function (e) { if (e.target === e.currentTarget) closeSearch(); });
    $('search').addEventListener('keydown', function (e) { if (e.key === 'Escape') closeSearch(); else trap(e, $('search')); });
    $('avatar').onclick = function (e) { e.stopPropagation(); popOpen ? closePop() : openPop(); };
    $('pop').addEventListener('click', function (e) {
      var b = e.target.closest('[data-a]'); if (!b) return;
      closePop(); if (b.dataset.a === 'theme') toggleTheme(); else refreshData();
    });
    document.addEventListener('click', function (e) { if (popOpen && !e.target.closest('#pop')) closePop(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && popOpen) { closePop(); $('avatar').focus(); }
      if ((e.key === '/' || (e.key === 'k' && (e.ctrlKey || e.metaKey))) && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) { e.preventDefault(); openSearch(); }
    });
    var onMQ = function () { paintTitle(); themeColor(); closePop(); };
    try { MQ.addEventListener('change', onMQ); } catch (e) { /* old browser */ }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
  window.Shell = { mount: mount, icon: icon, setActive: setActive, setTitle: setTitle, setBack: setBack, setBadge: setBadge, setBell: setBell, theme: effective,
    sheet: sheet, openSearch: openSearch, setSearchSource: function (fn) { searchSource = fn; if ($('search') && !$('search').hidden) renderSearch(); },
    isMobile: function () { return MQ.matches; } };
})();
