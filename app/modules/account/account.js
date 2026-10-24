/* Account page: sign in, create an account, sign in with Groww, and manage the sign-in methods. Talks to /api/auth/*.
   Passwords and API secrets live only in their input fields: they are cleared after each request and never stored or logged. */
(function () {
  'use strict';

  // ---------- pure helpers (testable, mirror the server rules; the server stays authoritative) ----------
  var USER_RE = /^[A-Za-z0-9._-]+$/;
  function usernameError(u) {
    u = String(u == null ? '' : u);
    if (!u) return 'Enter a username.';
    if (u.length < 3) return 'Username must be at least 3 characters.';
    if (u.length > 32) return 'Username can be at most 32 characters.';
    if (!USER_RE.test(u)) return 'Username can only use letters, digits, dot, underscore and hyphen.';
    return '';
  }
  function passwordRules(p, u) {
    p = String(p == null ? '' : p); u = String(u == null ? '' : u);
    return { length: p.length >= 10 && p.length <= 200, notUsername: p !== '' && p !== u };
  }
  function passwordError(p, u) {
    p = String(p == null ? '' : p);
    if (!p) return 'Enter a password.';
    if (p.length < 10) return 'Password must be at least 10 characters.';
    if (p.length > 200) return 'Password can be at most 200 characters.';
    if (u && p === String(u)) return 'Password must not be the same as the username.';
    return '';
  }
  function confirmError(p, c) { return p === c ? '' : 'The two passwords do not match.'; }
  // Only same-origin paths: one leading slash, not "//" or "/\", no control characters.
  function safeNext(n) {
    if (typeof n !== 'string' || n.length > 500) return '';
    if (n.charAt(0) !== '/' || n.charAt(1) === '/' || n.charAt(1) === '\\' || /[\x00-\x1f\x7f\\]/.test(n)) return '';
    return n;
  }
  function viewModel(me) {
    var ok = me && typeof me === 'object' && me.signedIn === true;
    if (!ok) return { signedIn: false, guest: true, username: '', label: 'Guest', hasPassword: false, growwLinked: false, via: null, freePassword: false };
    var name = typeof me.username === 'string' ? me.username : '';
    return { signedIn: true, guest: false, username: name, label: name || 'Signed in with Groww (no username yet)',
      hasPassword: !!me.hasPassword, growwLinked: !!me.growwLinked, via: me.via === 'password' || me.via === 'groww' ? me.via : null,
      freePassword: !!me.canSetPasswordFreely };
  }

  var _t = { usernameError: usernameError, passwordRules: passwordRules, passwordError: passwordError, confirmError: confirmError, safeNext: safeNext, viewModel: viewModel };
  if (typeof module !== 'undefined' && module.exports) module.exports = { _t: _t };
  if (typeof document === 'undefined') return;

  // ---------- browser part ----------
  var DOCS = 'https://groww.in/trade-api/docs/python-sdk';
  var SAFETY = 'Read-only: this app only asks Groww for your holdings and never places or changes an order. Groww API keys may be allowed to trade, so keep yours private. ' +
    'They are stored encrypted on this computer.';
  var S = { me: null, vm: viewModel(null), tab: 'signin', loading: true, busy: false, failed: false };
  var app = document.getElementById('app');
  function E(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function $(id) { return document.getElementById(id); }
  function nextPath() { try { return safeNext(new URLSearchParams(location.search).get('next') || ''); } catch (e) { return ''; } }

  function api(method, url, body) {
    var opt = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return (window.Session ? window.Session.fetch(url, opt) : fetch(url, opt)).then(function (r) {
      if (!/json/i.test(r.headers.get('content-type') || '')) throw new Error('The service did not answer. Is the app still running?');
      return r.json().then(function (j) {
        if (!r.ok) { var e = new Error((j && j.error) || 'Request failed'); e.kind = j && j.kind; e.status = r.status; throw e; }
        return j;
      });
    });
  }

  function field(id, label, type, auto, extra) {
    return '<div class="lf-f"><label for="' + id + '">' + label + '</label>' +
      '<input class="lf-in" id="' + id + '" name="' + id + '" type="' + type + '" autocomplete="' + auto + '"' + (type === 'text' ? ' autocapitalize="none" autocorrect="off" spellcheck="false"' : '') + ' ' + (extra || '') + ' aria-describedby="' + id + '-e"><span class="lf-e" id="' + id + '-e"></span></div>';
  }
  function pwField(id, label, auto) {
    return '<div class="lf-f"><label for="' + id + '">' + label + '</label><div class="ac-pw"><input class="lf-in" id="' + id + '" name="' + id + '" type="password" autocomplete="' + auto + '" aria-describedby="' + id + '-e">' +
      '<button type="button" class="btn" data-show="' + id + '" aria-pressed="false" aria-label="Show ' + E(label.toLowerCase()) + '">Show</button></div><span class="lf-e" id="' + id + '-e"></span></div>';
  }
  function msgs(p) { return '<p class="lf-err" id="' + p + '-err" role="alert" tabindex="-1"></p><p class="lf-ok" id="' + p + '-ok" role="status"></p>'; }
  function rulesList(p) {
    return '<ul class="ac-rules" id="' + p + '-rules" aria-label="Password rules"><li data-r="length">10 to 200 characters</li><li data-r="notUsername">Not the same as the username</li></ul>';
  }
  function growwFields(p) {
    return '<p class="lf-n">' + E(SAFETY) + '</p>' +
      '<p class="lf-n">Create the key on the Groww Cloud API Keys page. With the key-and-secret method Groww asks you to approve it there each day, so approve it before you sign in. A paid Groww Trading API subscription is needed. <a href="' + DOCS + '" target="_blank" rel="noopener">How the Groww API works</a>.</p>' +
      field(p + '-key', 'Groww API key', 'password', 'off', 'spellcheck="false"') + field(p + '-sec', 'Groww API secret', 'password', 'off', 'spellcheck="false"') +
      '<label class="ac-chk"><input type="checkbox" id="' + p + '-rem" checked> Remember on this computer</label>';
  }

  // ---------- views ----------
  function card(title, sub, inner) {
    return '<section class="card"><div class="card-h"><div><h2>' + title + '</h2>' + (sub ? '<p>' + sub + '</p>' : '') + '</div></div><div class="card-b">' + inner + '</div></section>';
  }
  function head(sub) { return typeof ph === 'function' ? ph('Account', sub) : '<h1>Account</h1>'; }

  function guestView() {
    var t = S.tab, tabs = [['signin', 'Sign in'], ['signup', 'Create account'], ['groww', 'Sign in with Groww']];
    var panel;
    if (t === 'signin') {
      panel = '<form class="lf" id="f-signin" novalidate>' + field('si-user', 'Username', 'text', 'username') + pwField('si-pass', 'Password', 'current-password') + msgs('si') +
        '<div class="lf-act"><button type="submit" class="btn pri">Sign in</button></div>' +
        '<p class="lf-n">Forgot your password? There is no reset by email. If your account is linked to Groww, use Sign in with Groww and then set a new password.</p></form>';
    } else if (t === 'signup') {
      panel = '<form class="lf" id="f-signup" novalidate>' + field('su-user', 'Username', 'text', 'username', 'maxlength="32"') +
        '<p class="lf-n">3 to 32 characters: letters, digits, dot, underscore, hyphen. Not case-sensitive.</p>' +
        pwField('su-pass', 'Password', 'new-password') + rulesList('su') + pwField('su-conf', 'Confirm password', 'new-password') + msgs('su') +
        '<p class="ac-note">There is no password reset by email in this app. If you forget your password, the only way back in is Sign in with Groww, and only if you linked Groww to this account. Link Groww after you sign up, or keep your password somewhere safe.</p>' +
        '<div class="lf-act"><button type="submit" class="btn pri">Create account</button></div></form>';
    } else {
      panel = '<form class="lf" id="f-groww" novalidate>' +
        '<p class="ac-note">Signing in with Groww needs a paid Groww Trading API subscription. A username and password account does not.</p>' + growwFields('gw') + msgs('gw') +
        '<div class="lf-act"><button type="submit" class="btn pri">Sign in with Groww</button></div></form>';
    }
    return head('Sign in to keep your portfolio, notes and alerts across devices.') + '<div class="ac">' +
      card('You are using the app as a guest', '', '<p>You are using the app as a guest. Your portfolio, notes and alerts are stored in this browser only. Create an account to keep them and use them on other devices. Existing data in this browser is kept when you sign up.</p>') +
      '<section class="card"><div class="card-b lf"><div class="seg" role="group" aria-label="Choose how to sign in">' +
      tabs.map(function (x) { return '<button type="button" class="tab' + (x[0] === t ? ' on' : '') + '" data-tab="' + x[0] + '" aria-pressed="' + (x[0] === t) + '">' + x[1] + '</button>'; }).join('') +
      '</div>' + panel + '</div></section></div>';
  }

  function signedInView() {
    var v = S.vm, free = v.freePassword, hasPw = v.hasPassword;
    var pwTitle = hasPw ? 'Change password' : 'Set a password';
    var pwForm = '<form class="lf" id="f-pw" novalidate><h3 class="ac-sub">' + pwTitle + '</h3>' +
      (!v.username ? field('pw-user', 'Choose a username', 'text', 'username', 'maxlength="32"') + '<p class="lf-n">You need a username to sign in with a password later. Letters, digits, dot, underscore or hyphen, 3 to 32 characters.</p>' : '') +
      (hasPw && !free ? pwField('pw-cur', 'Current password', 'current-password') : '') +
      pwField('pw-new', 'New password', 'new-password') + rulesList('pw') + pwField('pw-conf', 'Confirm new password', 'new-password') + msgs('pw') +
      '<div class="lf-act"><button type="submit" class="btn pri">' + pwTitle + '</button></div></form>';
    var gw = v.growwLinked
      ? '<div class="ac-kv"><div><b>Groww</b><small>Linked. You can sign in with your Groww key and secret.</small></div><button type="button" class="btn" id="gw-unlink">Unlink Groww</button></div>' + msgs('ul')
      : '<div class="ac-kv"><div><b>Groww</b><small>Not linked. Linking lets you sign in with Groww if you forget your password.</small></div></div>' +
        '<form class="lf" id="f-link" novalidate><p class="lf-n">Linking needs a paid Groww Trading API subscription.</p>' + growwFields('lk') + msgs('lk') +
        '<div class="lf-act"><button type="submit" class="btn">Link Groww</button></div></form>' + msgs('ul');
    return head('Manage how you sign in.') + '<div class="ac">' +
      card('Your account', '', '<div class="ac-kv"><div><b>' + E(v.label) + '</b><small>' + (v.via === 'groww' ? 'Signed in with Groww' : v.via === 'password' ? 'Signed in with your password' : 'Signed in') + '</small></div></div>' +
        '<p class="lf-n">Your portfolio, notes and alerts are saved to this account.</p>') +
      card('Sign-in methods', '', '<div class="ac-kv"><div><b>Password</b><small>' + (hasPw ? 'Set' : 'Not set') + '</small></div></div>' + pwForm + '<h3 class="ac-sub">Groww</h3>' + gw +
        (!hasPw && v.growwLinked ? '<p class="lf-n">Set a password before you can unlink Groww, otherwise you would be locked out.</p>' : '')) +
      card('Session', '', '<div class="lf"><div class="lf-act" style="justify-content:flex-start"><button type="button" class="btn" id="signout">Sign out</button></div>' + msgs('so') + '</div>') +
      card('Your data', '', '<p><a class="ac-del" href="/portfolio.html">Delete my data and account</a></p><p class="lf-n">Opens the Portfolio page, where Delete my data under Your data removes your holdings, notes, alerts and settings. It asks you to confirm first.</p>') +
      '</div>';
  }

  function render(focusSel) {
    if (S.loading) { app.innerHTML = head('') + '<div class="ac" aria-busy="true"><div class="card"><div class="card-b"><div class="ac-sk"></div><div class="ac-sk"></div><div class="ac-sk"></div></div></div></div>'; return; }
    app.innerHTML = S.vm.signedIn ? signedInView() : guestView();
    if (S.failed) { var h = app.querySelector('.ac'); if (h) h.insertAdjacentHTML('afterbegin', '<p class="ac-note" role="status">Could not reach the account service, so you are shown as a guest. Signing in may not work right now.</p>'); }
    bind();
    var el = focusSel ? app.querySelector(focusSel) : app.querySelector('form input:not([type=checkbox])');
    if (el) el.focus();
  }

  // ---------- behaviour ----------
  function setMe(me) {
    S.me = me; S.vm = viewModel(me);
    if (window.Auth) {
      window.Auth.me = me;
      var c = $('acct'), lb = c && c.querySelector('.acl');
      if (lb) { lb.textContent = S.vm.signedIn ? (S.vm.username || 'Groww account') : 'Sign in'; c.classList.toggle('in', S.vm.signedIn); }
    }
  }
  function say(p, kind, text, focusEl) {
    var err = $(p + '-err'), ok = $(p + '-ok'); if (!err) return;
    err.textContent = kind === 'err' ? text : ''; ok.textContent = kind === 'ok' ? text : '';
    if (kind === 'err') { if (focusEl) focusEl.focus(); else err.focus(); }
  }
  function fieldErr(id, text) {
    var i = $(id), e = $(id + '-e'); if (!i) return;
    if (text) i.setAttribute('aria-invalid', 'true'); else i.removeAttribute('aria-invalid');
    if (e) e.textContent = text || '';
  }
  function clear(ids) { ids.forEach(function (id) { var i = $(id); if (i) { i.value = ''; if (i.type === 'text' && /pass|conf|cur|new/.test(id)) i.type = 'password'; } }); }
  function resetPwToggles(form) {
    form.querySelectorAll('[data-show]').forEach(function (b) { var i = $(b.dataset.show); if (i) i.type = 'password'; b.textContent = 'Show'; b.setAttribute('aria-pressed', 'false'); });
  }
  function busy(form, on) {
    S.busy = on; form.setAttribute('aria-busy', on ? 'true' : 'false');
    form.querySelectorAll('button,input').forEach(function (e) { e.disabled = on; });
  }
  // Runs a request with the form locked. fn() returns the promise; ok(me) runs on success; fail(err) shows the error.
  function submit(form, fn, ok, fail) {
    if (S.busy) return;
    busy(form, true);
    fn().then(function (me) { busy(form, false); ok(me); }, function (e) { busy(form, false); fail(e); });
  }
  function enter(me) {   // data owner changed: go back where the user came from, or reload
    var n = nextPath(); setMe(me);
    if (n) location.assign(n); else location.reload();
  }
  function updateRules(p, passId, userVal) {
    var r = passwordRules($(passId).value, userVal), ul = $(p + '-rules'); if (!ul) return;
    ul.querySelectorAll('li').forEach(function (li) { li.classList.toggle('ok', !!r[li.dataset.r]); });
  }
  function growwBody(p) { return { api_key: $(p + '-key').value.trim(), api_secret: $(p + '-sec').value.trim(), remember: $(p + '-rem').checked }; }

  function bind() {
    app.querySelectorAll('[data-show]').forEach(function (b) {
      b.onclick = function () {
        var i = $(b.dataset.show), show = i.type === 'password'; i.type = show ? 'text' : 'password';
        b.textContent = show ? 'Hide' : 'Show'; b.setAttribute('aria-pressed', String(show)); b.setAttribute('aria-label', (show ? 'Hide ' : 'Show ') + b.getAttribute('aria-label').replace(/^(Show|Hide) /, ''));
      };
    });
    var tabs = app.querySelectorAll('[data-tab]');
    tabs.forEach(function (b, k) {
      b.onclick = function () { if (S.busy) return; S.tab = b.dataset.tab; render(); };
      b.onkeydown = function (e) {
        var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (!d) return;
        e.preventDefault(); var n = tabs[(k + d + tabs.length) % tabs.length]; S.tab = n.dataset.tab; render('[data-tab="' + n.dataset.tab + '"]');
      };
    });

    var f = $('f-signin');
    if (f) f.onsubmit = function (e) {
      e.preventDefault(); var form = e.currentTarget;
      var u = $('si-user').value.trim(), p = $('si-pass').value; fieldErr('si-user', ''); fieldErr('si-pass', '');
      if (!u) { fieldErr('si-user', 'Enter your username.'); return say('si', 'err', 'Enter your username.', $('si-user')); }
      if (!p) { fieldErr('si-pass', 'Enter your password.'); return say('si', 'err', 'Enter your password.', $('si-pass')); }
      say('si', '', '');
      submit(form, function () { return api('POST', '/api/auth/login', { username: u, password: p }); },
        function (me) { clear(['si-pass']); enter(me); },
        function (er) { clear(['si-pass']); resetPwToggles(form); say('si', 'err', er.message, er.status === 401 ? $('si-pass') : null); });
    };

    f = $('f-signup');
    if (f) {
      var live = function () { updateRules('su', 'su-pass', $('su-user').value.trim()); };
      $('su-pass').oninput = live; $('su-user').oninput = live; live();
      f.onsubmit = function (e) {
        e.preventDefault(); var form = e.currentTarget;
        var u = $('su-user').value.trim(), p = $('su-pass').value, c = $('su-conf').value;
        ['su-user', 'su-pass', 'su-conf'].forEach(function (id) { fieldErr(id, ''); });
        var ue = usernameError(u), pe = ue ? '' : passwordError(p, u), ce = ue || pe ? '' : confirmError(p, c);
        if (ue) { fieldErr('su-user', ue); return say('su', 'err', ue, $('su-user')); }
        if (pe) { fieldErr('su-pass', pe); return say('su', 'err', pe, $('su-pass')); }
        if (ce) { fieldErr('su-conf', ce); return say('su', 'err', ce, $('su-conf')); }
        say('su', '', '');
        submit(form, function () { return api('POST', '/api/auth/signup', { username: u, password: p }); },
          function (me) { clear(['su-pass', 'su-conf']); enter(me); },
          function (er) { clear(['su-pass', 'su-conf']); resetPwToggles(form); live(); say('su', 'err', er.message, er.status === 409 ? $('su-user') : $('su-pass')); });
      };
    }

    f = $('f-groww');
    if (f) f.onsubmit = function (e) {
      e.preventDefault(); var form = e.currentTarget;
      var b = growwBody('gw');
      if (!b.api_key || !b.api_secret) return say('gw', 'err', 'Enter both the Groww API key and the API secret.', $(b.api_key ? 'gw-sec' : 'gw-key'));
      say('gw', '', '');
      submit(form, function () { return api('POST', '/api/auth/groww', b); },
        function (me) { clear(['gw-key', 'gw-sec']); enter(me); },
        function (er) { clear(['gw-key', 'gw-sec']); say('gw', 'err', er.message || 'Groww could not be reached.', $('gw-key')); });
    };

    f = $('f-link');
    if (f) f.onsubmit = function (e) {
      e.preventDefault(); var form = e.currentTarget;
      var b = growwBody('lk');
      if (!b.api_key || !b.api_secret) return say('lk', 'err', 'Enter both the Groww API key and the API secret.', $(b.api_key ? 'lk-sec' : 'lk-key'));
      say('lk', '', '');
      submit(form, function () { return api('POST', '/api/auth/groww/link', b); },
        function (me) { clear(['lk-key', 'lk-sec']); setMe(me); render(); say('ul', 'ok', 'Groww is now linked to your account.'); },
        function (er) { clear(['lk-key', 'lk-sec']); say('lk', 'err', er.message || 'Groww could not be reached.', $('lk-key')); });
    };

    var ul = $('gw-unlink');
    if (ul) ul.onclick = function () {
      if (S.busy) return;
      if (!window.confirm('Unlink Groww from this account? You will no longer be able to sign in with Groww.')) return;
      S.busy = true; ul.disabled = true;
      api('DELETE', '/api/auth/groww').then(function (me) { S.busy = false; setMe(me); render(); say('ul', 'ok', 'Groww was unlinked.'); },
        function (er) { S.busy = false; ul.disabled = false; say('ul', 'err', er.message); });
    };

    f = $('f-pw');
    if (f) {
      var vm = S.vm, live2 = function () { updateRules('pw', 'pw-new', vm.username); };
      $('pw-new').oninput = live2; live2();
      f.onsubmit = function (e) {
        e.preventDefault(); var form = e.currentTarget;
        var cur = $('pw-cur'), n = $('pw-new').value, c = $('pw-conf').value, un = $('pw-user'), uname = un ? un.value.trim() : vm.username;
        ['pw-user', 'pw-cur', 'pw-new', 'pw-conf'].forEach(function (id) { if ($(id)) fieldErr(id, ''); });
        if (un) { var uerr = usernameError(uname); if (uerr) { fieldErr('pw-user', uerr); return say('pw', 'err', uerr, un); } }
        if (cur && !cur.value) { fieldErr('pw-cur', 'Enter your current password.'); return say('pw', 'err', 'Enter your current password.', cur); }
        var pe = passwordError(n, uname), ce = pe ? '' : confirmError(n, c);
        if (pe) { fieldErr('pw-new', pe); return say('pw', 'err', pe, $('pw-new')); }
        if (ce) { fieldErr('pw-conf', ce); return say('pw', 'err', ce, $('pw-conf')); }
        say('pw', '', '');
        var body = { new_password: n }; if (cur) body.current_password = cur.value; if (un) body.username = uname;
        submit(form, function () { return api('POST', '/api/auth/password', body); },
          function (me) { clear(['pw-cur', 'pw-new', 'pw-conf']); setMe(me); render('#pw-new'); say('pw', 'ok', 'Your password was saved.'); },
          function (er) { clear(['pw-cur', 'pw-new', 'pw-conf']); resetPwToggles(form); live2(); say('pw', 'err', er.message, cur || $('pw-new')); });
      };
    }

    var so = $('signout');
    if (so) so.onclick = function () {
      if (S.busy) return; S.busy = true; so.disabled = true;
      api('POST', '/api/auth/logout').then(function (me) { S.busy = false; setMe(me); location.reload(); },
        function (er) { S.busy = false; so.disabled = false; say('so', 'err', er.message); });
    };
  }

  function boot() {
    render();
    var p = window.Auth ? window.Auth.load() : Promise.resolve(null);
    p.then(function (me) {
      S.loading = false; S.failed = !me; setMe(me);
      if (S.vm.signedIn && nextPath()) { location.replace(nextPath()); return; }   // already signed in: go straight on
      render();
    });
  }
  boot();
})();
