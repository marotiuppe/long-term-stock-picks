"""Per-user API (holdings, watchlist, alerts, export, delete, login). A visitor is a guest (a random cookie, one browser is one user)
until they sign up or sign in; then a session cookie maps the browser to the account's user id. All data is scoped by user id in
Store, so one user can never read another's rows."""
import csv, datetime, io, json, os, re, secrets, time
import urllib.parse

from modules.portfolio import alerts, portfolio, positions, rules
from modules.account import auth, groww
from core.store import Store

COOKIE = "uid"
UID_RE = re.compile(r"[0-9a-f]{32}")
MAX_BODY = 100_000
HZ_KEYS = ("1d", "2d", "5d", "10d", "1m", "3m", "6m")


def user_from_cookie(cookie_header):
    """(uid, Set-Cookie value or None). A missing or malformed cookie gets a new random id."""
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and UID_RE.fullmatch(v):
            return v, None
    uid = secrets.token_hex(16)
    return uid, f"{COOKIE}={uid}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"


SID = "sid"
GUEST_MAX_AGE = 31536000


def _cookie(name, value, max_age):
    # Secure only when the app is served over HTTPS (set STOCKPICKS_SECURE_COOKIES=1 there); a Secure cookie is dropped on plain http
    return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (name, value, max_age, "; Secure" if os.environ.get("STOCKPICKS_SECURE_COOKIES") == "1" else "")


class Ident:
    """Who a request belongs to: uid owns the data. signed_in is True only for a valid session."""

    def __init__(self, uid, signed_in=False, via=None, sess_hash=None, sess_created=0, cookies=None):
        self.uid, self.signed_in, self.via, self.sess_hash, self.sess_created, self.cookies = uid, signed_in, via, sess_hash, sess_created, cookies or []


def identify(cookie_header, store, now=None):
    """Session cookie first; else the guest cookie. A guest cookie that is an account's own user id is refused (it would give a signed-out
    browser the account's data), so a fresh guest id is issued. -> Ident, whose .cookies are the Set-Cookie values to send."""
    now = time.time() if now is None else now
    jar = {}
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k and k not in jar:
            jar[k] = v
    cookies = []
    sid = jar.get(SID)
    if sid and auth.SID_RE.match(sid):
        h = auth.token_hash(sid)
        sess = store.get_session(h, now)
        if sess:
            return Ident(sess["user_id"], True, sess["via"], h, sess["created"], cookies)
    if sid:
        cookies.append(_cookie(SID, "", 0))      # expired or unknown session: drop the cookie
    guest = jar.get(COOKIE, "")
    if not UID_RE.fullmatch(guest) or store.is_account_id(guest):
        guest = secrets.token_hex(16)
        cookies.append(_cookie(COOKIE, guest, GUEST_MAX_AGE))
    return Ident(guest, False, cookies=cookies)


def same_origin(headers):
    """Reject cross-site writes: if Origin is sent it must match Host."""
    origin = headers.get("Origin")
    return not origin or urllib.parse.urlparse(origin).netloc == headers.get("Host")


def _stocks(scan):
    out = {}
    for s in (scan or {}).get("stocks", []):
        out[s["symbol"]] = dict(s, downtrend=s.get("verdict") == "DOWNTREND")
    # shares the scan filters out still have a last close: enough to value a holding, but no call, stop or forecast
    for sym, q in ((scan or {}).get("quotes") or {}).items():
        if sym not in out and q.get("price") is not None:
            out[sym] = {"symbol": sym, "price": q["price"], "prev": q.get("prev"), "asof": q.get("asof"), "verdict": None,
                        "quoteOnly": True, "whyNotScanned": q.get("why")}
    return out


def me_payload(store, uid, scan, today=None, hz="1m", ctx=None):
    """Everything the page shows for one user. Also records any new alerts (once per event)."""
    today = today or datetime.date.today()
    hz = hz if hz in HZ_KEYS else "1m"
    stocks = _stocks(scan)
    review_date = ((scan or {}).get("sellDates") or {}).get(hz)
    holdings = store.list_holdings(uid)
    watch = store.list_watchlist(uid)
    if stocks:
        for a in alerts.generate_alerts(holdings, watch, stocks, store.get_last_calls(uid), today, review_date):
            store.add_alert(uid, a["key"], a["kind"], a["symbol"], a["message"], a["date"])
        # only the stocks this user holds or watches can raise a "call changed" alert, so only those are remembered (not the whole market)
        mine = {h.get("symbol") for h in holdings} | set(watch)
        store.set_last_calls(uid, {s: v for s, v in alerts.next_calls(stocks).items() if s in mine})
        # price alerts the user set, any symbol; end-of-day scan data only
        for aid, a in alerts.evaluate_price_alerts(store.list_price_alerts(uid), stocks, today):
            store.add_alert(uid, a["key"], a["kind"], a["symbol"], a["message"], a["date"])
            store.mark_price_alert_fired(uid, aid, a["date"])
    rows = []
    for h in holdings:
        r = portfolio.review(h, stocks.get(h["symbol"]), hz, today.isoformat(), review_date)
        r.update(first_buy_date=h.get("first_buy_date"), source=h.get("source"))
        rows.append(r)
    al = store.list_alerts(uid)
    pos, summary = valued_positions(store, uid, stocks, (ctx or {}).get("detail") or {})
    return {"holdings": rows, "positions": pos, "summary": summary,
            "watchlist": [{"symbol": w, "price": stocks.get(w, {}).get("price"), "call": stocks.get(w, {}).get("verdict")}
                          for w in watch],
            "alerts": al, "unread": sum(1 for a in al if not a["read"]),
            "settings": store.get_settings(uid), "synced": (scan or {}).get("generated") or None}


def _tid(q):
    try:
        return int(q.get("id", [""])[0])
    except ValueError:
        raise ValueError("transaction id is required")


def _aid(v):
    try:
        if isinstance(v, bool):
            raise ValueError
        return int(v)
    except (TypeError, ValueError):
        raise ValueError("price alert id is required")


def price_alerts_payload(store, uid, stocks, sym=None):
    """Alerts with the latest close (from the scan) and a status: waiting, reached or paused."""
    out = []
    for r in store.list_price_alerts(uid, sym):
        st = stocks.get(r["symbol"]) or {}
        r["price"], r["hi52"], r["asof"] = st.get("price"), st.get("hi52"), st.get("asof")
        r["status"] = "paused" if not r["active"] else ("reached" if r["last_fired"] else "waiting")
        out.append(r)
    return {"alerts": out, "max": 20, "disclaimer": DISCLAIMER}


def _json_body(raw):
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        raise ValueError("body is not valid JSON")
    if not isinstance(d, dict):
        raise ValueError("body must be a JSON object")
    return d


def handle(method, path, query, raw, store, uid, scan, universe, ctx=None, today=None):
    """-> (status, json-able). Raises nothing: bad input becomes a 4xx with {"error": ...}."""
    q = urllib.parse.parse_qs(query)
    hz = q.get("hz", ["1m"])[0]
    today = today or datetime.date.today()
    stocks = _stocks(scan)
    detail = (ctx or {}).get("detail") or {}
    known = lambda sym: bool(sym) and ((not universe) or sym in universe or sym in stocks)
    try:
        if path.startswith("/api/auth/"):
            return auth_handle(method, path, raw, store, uid, ctx, today)
        if path == "/api/session" and method == "GET":
            return 200, {"ok": True}    # only here so the first request of a visit can set the identity cookie
        if path == "/api/lots":
            if method == "GET":
                return 200, {"lots": store.list_lots(uid, q.get("sym", [""])[0] or None)}
            if method in ("POST", "PUT"):
                d = _json_body(raw)
                lot = positions.validate_lot(d, today)
                if not known(lot["symbol"]):
                    return 400, {"error": "%s is not a stock or ETF this app knows" % lot["symbol"]}
                if method == "POST":
                    lid = store.add_lot(uid, lot)
                else:
                    lid = _tid(q)
                    try:
                        store.update_lot(uid, lid, lot)
                    except KeyError:
                        return 404, {"error": "no such transaction"}
                return 200, {"id": lid, "position": position_payload(store, uid, lot["symbol"], stocks, detail)}
            if method == "DELETE":
                lid = _tid(q)
                row = [l for l in store.list_lots(uid) if l["id"] == lid]
                if not store.delete_lot(uid, lid):
                    return 404, {"error": "no such transaction"}
                return 200, {"deleted": lid, "position": position_payload(store, uid, row[0]["symbol"], stocks, detail)}
        elif path == "/api/position" and method == "GET":
            return 200, position_payload(store, uid, q.get("sym", [""])[0], stocks, detail)
        elif path == "/api/export.csv" and method == "GET":
            return 200, {"_csv": lots_csv(store, uid), "_name": "my-transactions.csv"}
        elif path == "/api/transactions/import" and method == "POST":
            d = _json_body(raw)
            fmt = "json" if d.get("format") == "json" else "csv"
            lots, rl, hs = parse_import(fmt, d.get("data"), today)
            bad = [l["symbol"] for l in lots if not known(l["symbol"])]
            if bad:
                return 400, {"error": "Not a stock or ETF this app knows: %s" % ", ".join(sorted(set(bad))[:8])}
            added, skipped = store.import_lots(uid, lots, replace=d.get("mode") == "replace")
            if rl:
                store.set_rules(uid, rl)
            for sym, h in (hs or {}).items() if isinstance(hs, dict) else []:
                if isinstance(h, dict):
                    store.set_hsetting(uid, sym, **{k: h.get(k) for k in ("target_weight", "review_price", "sector") if k in h})
            return 200, {"added": added, "skipped": skipped, "me": me_payload(store, uid, scan, hz=hz, ctx=ctx)}
        elif path == "/api/rules":
            if method == "GET":
                return 200, {"rules": store.get_rules(uid), "defaults": rules.DEFAULTS,
                             "meta": {k: {"tone": v[0], "title": v[2], "text": v[3]} for k, v in rules.META.items()},
                             "stocks": store.get_hsettings(uid), "held": [h["symbol"] for h in store.list_holdings(uid)], "disclaimer": DISCLAIMER}
            if method in ("POST", "PUT"):
                d = _json_body(raw)
                if "rules" in d:
                    store.set_rules(uid, d["rules"])
                if isinstance(d.get("stock"), dict):
                    st = d["stock"]
                    store.set_hsetting(uid, st.get("symbol"), **{k: st[k] for k in ("target_weight", "review_price", "sector") if k in st})
                return 200, {"rules": store.get_rules(uid), "stocks": store.get_hsettings(uid)}
        elif path == "/api/attention" and method == "GET":
            return 200, attention_payload(store, uid, scan, ctx, today)
        elif path == "/api/attention/state" and method == "POST":
            d = _json_body(raw)
            key, fp, act = str(d.get("key", "")), str(d.get("fingerprint", "")), d.get("action")
            if not re.fullmatch(r"[A-Z0-9&-]{1,20}\|[a-z_]{3,20}", key):
                return 400, {"error": "unknown alert"}
            if act == "dismiss":
                store.set_state(uid, key, "dismissed", fp)
            elif act == "snooze":
                days = int(d.get("days", 7))
                if not 1 <= days <= 90:
                    return 400, {"error": "snooze must be 1 to 90 days"}
                store.set_state(uid, key, "snoozed", fp, (today + datetime.timedelta(days=days)).isoformat())
            elif act == "restore":
                store.clear_states(uid, [key])
            else:
                return 400, {"error": "action must be dismiss, snooze or restore"}
            return 200, {"ok": True}
        elif path == "/api/attention/seen" and method == "POST":
            for k, fp in (_json_body(raw).get("seen") or {}).items():
                if re.fullmatch(r"[A-Z0-9&-]{1,20}\|[a-z_]{3,20}", str(k)):
                    store.set_state(uid, "seen:" + k, "seen", str(fp))
            return 200, {"ok": True}
        elif path == "/api/me":
            if method == "GET":
                return 200, me_payload(store, uid, scan, hz=hz, ctx=ctx)
            if method == "DELETE":
                store.delete_user(uid)
                if ctx is not None:     # the account and its sessions are gone: sign the browser out and give it a fresh guest id
                    ctx.setdefault("cookies", []).extend([_cookie(SID, "", 0), _cookie(COOKIE, secrets.token_hex(16), GUEST_MAX_AGE)])
                return 200, {"deleted": True}
        elif path == "/api/export" and method == "GET":
            return 200, store.export_user(uid)
        elif path == "/api/holdings":
            if method == "DELETE":
                store.delete_holding(uid, q.get("sym", [""])[0].upper())
                return 200, me_payload(store, uid, scan, hz=hz)
            if method == "POST":
                d = _json_body(raw)
                sym = str(d.get("symbol", "")).strip().upper()
                if universe and sym not in universe:
                    return 400, {"error": f"{sym or 'symbol'} is not an NSE share this app knows"}
                p = store.list_positions(uid).get(sym)
                if p and (len(p["lots"]) > 1 or p["sold_qty"]):
                    return 400, {"error": "%s already has %d transactions. Edit them on its page" % (sym, len(p["lots"]))}
                store.upsert_holding(uid, sym, float(d.get("qty")), float(d.get("avg_price")))
                return 200, me_payload(store, uid, scan, hz=hz, ctx=ctx)
        elif path == "/api/holdings/paste" and method == "POST":
            rows, errs = portfolio.parse_paste(str(_json_body(raw).get("text", "")), universe)
            errs = list(errs)
            mine = store.list_positions(uid)
            ok_rows = []
            for r in rows:
                p = mine.get(r["symbol"])
                if p and (len(p["lots"]) > 1 or p["sold_qty"]):
                    errs.append((0, "%s already has %d transactions. Edit them on its page instead of pasting over them" % (r["symbol"], len(p["lots"]))))
                    continue
                ok_rows.append(r)
            rows = ok_rows
            for r in rows:
                store.upsert_holding(uid, r["symbol"], r["qty"], r["avg_price"], source="paste")
            return 200, {"added": len(rows), "errors": [{"line": n, "message": m} for n, m in errs],
                         "me": me_payload(store, uid, scan, hz=hz)}
        elif path == "/api/watchlist":
            if method == "DELETE":
                store.remove_watch(uid, q.get("sym", [""])[0].upper())
                return 200, me_payload(store, uid, scan, hz=hz)
            if method == "POST":
                sym = str(_json_body(raw).get("symbol", "")).strip().upper()
                if universe and sym not in universe:
                    return 400, {"error": f"{sym or 'symbol'} is not an NSE share this app knows"}
                store.add_watch(uid, sym)
                return 200, me_payload(store, uid, scan, hz=hz)
        elif path == "/api/notes":
            sym = q.get("sym", [""])[0]
            if method == "GET":
                if sym:
                    return 200, store.get_note(uid, sym)
                return 200, {"notes": store.list_notes(uid)}
            if method in ("POST", "PUT"):
                d = _json_body(raw)
                return 200, store.set_note(uid, d.get("symbol"), d.get("text", ""))
            if method == "DELETE":
                return 200, {"deleted": store.delete_note(uid, sym)}
        elif path == "/api/price-alerts":
            if method == "GET":
                return 200, price_alerts_payload(store, uid, stocks, q.get("sym", [""])[0] or None)
            if method == "POST":
                d = _json_body(raw)
                sym = str(d.get("symbol", "")).strip().upper()
                if not known(sym):
                    return 400, {"error": "%s is not a stock or ETF this app knows" % (sym or "symbol")}
                if isinstance(d.get("value"), bool):
                    return 400, {"error": "value must be a number"}
                aid = store.add_price_alert(uid, sym, d.get("kind"), d.get("value"))
                return 200, dict(price_alerts_payload(store, uid, stocks, sym), id=aid)
            if method == "PUT":
                d = _json_body(raw)
                if not isinstance(d.get("active"), bool):
                    return 400, {"error": "active must be true or false"}
                aid = _aid(d.get("id"))
                row = [r for r in store.list_price_alerts(uid) if r["id"] == aid]
                if not row or not store.set_price_alert_active(uid, aid, d["active"]):
                    return 404, {"error": "no such price alert"}
                return 200, price_alerts_payload(store, uid, stocks, row[0]["symbol"])
            if method == "DELETE":
                aid = _aid(q.get("id", [""])[0])
                row = [r for r in store.list_price_alerts(uid) if r["id"] == aid]
                if not row or not store.delete_price_alert(uid, aid):
                    return 404, {"error": "no such price alert"}
                return 200, price_alerts_payload(store, uid, stocks, row[0]["symbol"])
        elif path == "/api/alerts/read" and method == "POST":
            store.mark_alerts_read(uid)
            return 200, me_payload(store, uid, scan, hz=hz)
        elif path == "/api/groww" and method == "GET":
            return 200, groww_payload(store, uid)
        elif path == "/api/groww/credentials" and method == "DELETE":
            store.delete_groww(uid)
            return 200, groww_payload(store, uid)
        elif path == "/api/groww/sync" and method == "POST":
            return groww_sync(store, uid, _json_body(raw), scan, universe, stocks, ctx, hz, today)
        else:
            return 404, {"error": "not found"}
        return 405, {"error": "method not allowed"}
    except (ValueError, TypeError) as e:
        return 400, {"error": str(e) or "invalid input"}


# ---------- login: password accounts and Sign in with Groww ----------
def auth_me(store, ident, now=None):
    now = time.time() if now is None else now
    if not ident.signed_in:
        return {"signedIn": False, "guest": True, "username": None, "hasPassword": False, "growwLinked": False, "via": None, "canSetPasswordFreely": False}
    a = store.get_account(ident.uid) or {}
    has_pw = bool(a.get("pw_hash"))
    free = (not has_pw) or (ident.via == "groww" and now - ident.sess_created <= auth.RECENT_GROWW)
    return {"signedIn": True, "guest": False, "username": a.get("username"), "hasPassword": has_pw, "growwLinked": store.groww_linked(ident.uid),
            "via": ident.via, "canSetPasswordFreely": free}


def _start_session(store, uid, via, ctx, now, rotate_guest):
    tok = auth.new_token()
    store.create_session(uid, auth.token_hash(tok), via, now, auth.SESSION_TTL)
    store.touch_login(uid)
    ctx["cookies"].append(_cookie(SID, tok, auth.SESSION_TTL))
    if rotate_guest:    # the guest id became the account id: the browser must not keep it as a guest id
        ctx["cookies"].append(_cookie(COOKIE, secrets.token_hex(16), GUEST_MAX_AGE))
    return Ident(uid, True, via, auth.token_hash(tok), now)


def _groww_hashes(profile):
    key = groww.master_secret()
    return [auth.id_hash(k, profile[f], key) for k, f in (("v", "vendor_user_id"), ("u", "ucc")) if profile.get(f)]


def _remember_groww(store, uid, d, key, secret):
    if d.get("remember", True):
        store.set_groww(uid, groww.encrypt(key), groww.encrypt(secret), groww.hint(key))


def auth_handle(method, path, raw, store, uid, ctx, today):
    ctx = ctx if ctx is not None else {}
    ctx.setdefault("cookies", [])
    ident = ctx.get("ident") or Ident(uid)
    ip = str(ctx.get("ip") or "unknown")
    now = ctx.get("now") or time.time()
    sub = path[len("/api/auth/"):]
    if sub == "me" and method == "GET":
        return 200, auth_me(store, ident, now)
    if sub == "logout" and method == "POST":
        if ident.sess_hash:
            store.delete_session(ident.sess_hash)
        ctx["cookies"].append(_cookie(SID, "", 0))
        return 200, auth_me(store, Ident(uid), now)

    if sub == "signup" and method == "POST":
        if ident.signed_in:
            return 400, {"error": "You are already signed in."}
        wait = auth.SIGNUP_IP.wait(ip, now)
        if wait:
            return 429, {"error": auth.wait_message(wait)}
        d = _json_body(raw)
        name = auth.check_username(d.get("username"))
        pw = auth.check_password(d.get("password"), name)
        try:
            store.create_account(uid, name, auth.hash_password(pw))     # the guest id becomes the account: browser data is kept
        except ValueError as e:
            if "taken" in str(e):
                return 409, {"error": "That username is taken. Choose another."}
            return 400, {"error": "This browser already has an account. Sign in instead."}
        auth.SIGNUP_IP.fail(ip, now)
        ident = _start_session(store, uid, "password", ctx, now, rotate_guest=True)
        return 200, auth_me(store, ident, now)

    if sub == "login" and method == "POST":
        if ident.signed_in:
            return 400, {"error": "You are already signed in. Sign out first to use another account."}
        d = _json_body(raw)
        name = str(d.get("username") or "").strip()
        pw = d.get("password")
        wait = max(auth.LOGIN_IP.wait(ip, now), auth.LOGIN_USER.wait(name.lower(), now))
        if wait:
            return 429, {"error": auth.wait_message(wait)}
        acct = store.account_by_username(name) if name and isinstance(pw, str) else None
        if acct and acct["pw_hash"] and auth.verify_password(pw, acct["pw_hash"]):
            auth.LOGIN_USER.clear(name.lower())
            return 200, auth_me(store, _start_session(store, acct["user_id"], "password", ctx, now, rotate_guest=False), now)
        if not acct or not acct["pw_hash"]:
            auth.burn_time(pw if isinstance(pw, str) else "")
        auth.LOGIN_USER.fail(name.lower(), now)
        auth.LOGIN_IP.fail(ip, now)
        return 401, {"error": "Wrong username or password."}

    if sub in ("groww", "groww/link") and method == "POST":
        linking = sub == "groww/link"
        if linking and not ident.signed_in:
            return 401, {"error": "Sign in first, then link Groww."}
        if not linking and ident.signed_in:
            return 400, {"error": "You are already signed in. Use Link Groww in your account instead."}
        wait = auth.LOGIN_IP.wait(ip, now)
        if wait:
            return 429, {"error": auth.wait_message(wait)}
        d = _json_body(raw)
        key, secret = groww.clean_credentials(d.get("api_key"), d.get("api_secret"))
        try:
            profile = (ctx.get("groww_profile") or groww.fetch_profile)(key, secret)
        except groww.GrowwError as e:
            auth.LOGIN_IP.fail(ip, now)
            return e.status, {"error": e.message, "kind": e.kind}
        hashes = _groww_hashes(profile)
        owner, conflict = store.user_for_groww(hashes)
        if conflict:
            return 409, {"error": "This Groww account matches two different accounts here. Contact the person who runs this app."}
        if linking:
            if owner and owner != ident.uid:
                return 409, {"error": "This Groww account is already linked to another account here."}
            store.link_groww_ids(ident.uid, hashes)
            _remember_groww(store, ident.uid, d, key, secret)
            return 200, auth_me(store, ident, now)
        created = owner is None
        if created:     # first time: the guest id becomes the account, so this browser's data is kept
            try:
                store.create_account(uid)
                store.link_groww_ids(uid, hashes)
            except ValueError:
                return 400, {"error": "This browser already has an account. Sign in with your username instead."}
            owner = uid
        else:
            store.link_groww_ids(owner, hashes)     # remember any id Groww added since the last sign-in
        _remember_groww(store, owner, d, key, secret)
        ident = _start_session(store, owner, "groww", ctx, now, rotate_guest=created)
        return 200, dict(auth_me(store, ident, now), created=created)

    return _auth_account(sub, method, raw, store, ident, now)


def _auth_account(sub, method, raw, store, ident, now):
    if sub not in ("password", "groww"):
        return 404, {"error": "not found"}
    if not ident.signed_in:
        return 401, {"error": "Sign in first."}
    a = store.get_account(ident.uid) or {}
    has_pw = bool(a.get("pw_hash"))
    if sub == "groww" and method == "DELETE":
        if not has_pw:
            return 400, {"error": "Set a password first. Without one, unlinking Groww would lock you out of this account."}
        store.unlink_groww_ids(ident.uid)
        return 200, auth_me(store, ident, now)
    if sub == "password" and method == "POST":
        d = _json_body(raw)
        free = auth_me(store, ident, now)["canSetPasswordFreely"]
        if has_pw and not free:
            wait = auth.LOGIN_USER.wait("pw:" + ident.uid, now)
            if wait:
                return 429, {"error": auth.wait_message(wait)}
            cur = d.get("current_password")
            if not isinstance(cur, str) or not auth.verify_password(cur, a["pw_hash"]):
                auth.LOGIN_USER.fail("pw:" + ident.uid, now)
                return 401, {"error": "The current password is wrong."}
            auth.LOGIN_USER.clear("pw:" + ident.uid)
        name, new_name = a.get("username"), None
        if not name:        # a Groww-only account picks a username when it first sets a password
            new_name = name = auth.check_username(d.get("username"))
        new = auth.check_password(d.get("new_password"), name)
        try:
            store.set_credentials(ident.uid, auth.hash_password(new), new_name)
        except ValueError:
            return 409, {"error": "That username is taken. Choose another."}
        store.delete_other_sessions(ident.uid, ident.sess_hash)     # a changed password signs every other device out
        return 200, auth_me(store, ident, now)
    return 405, {"error": "method not allowed"}


# ---------- Groww sync: the user's own API key and secret, read-only ----------
GROWW_NOTE = ("Read-only: this app only reads your holdings and never places or changes an order. Your key and secret are stored "
              "encrypted on the computer running this app and are never shown again.")


def groww_payload(store, uid):
    return dict(store.groww_status(uid), note=GROWW_NOTE)


def _groww_apply(store, uid, rows, known):
    """Write Groww's holdings as one opening position per stock. A stock whose transactions the user entered themselves
    (several, or any sale) is left alone and reported. A stock the app's scan does not cover (small or special-series shares, some ETFs)
    is still kept, because the broker says it is held: it shows without a price and is counted in the invested amount only."""
    added = updated = unchanged = 0
    skipped, outcome = [], {}
    mine = store.list_positions(uid)
    for r in rows:
        sym = r["symbol"]
        p = mine.get(sym)
        if p and (len(p["lots"]) > 1 or p["sold_qty"]):
            skipped.append({"symbol": sym, "reason": "You entered %d transactions for it, so it was not changed" % len(p["lots"])})
            continue
        if p and p["qty"] and abs(p["qty"] - r["qty"]) < 1e-9 and abs(p["avg_cost"] - r["avg_price"]) < 0.005:
            unchanged += 1
            outcome[sym] = "unchanged"
            continue
        store.upsert_holding(uid, sym, r["qty"], r["avg_price"], source="groww")
        if p and p["qty"]:
            updated += 1
            outcome[sym] = "updated"
        else:
            added += 1
            outcome[sym] = "new"
    return added, updated, unchanged, skipped, outcome


def groww_sync(store, uid, d, scan, universe, stocks, ctx, hz, today):
    """New credentials in the body are used first and saved only after Groww accepts them; otherwise the saved ones are used."""
    given = bool(str(d.get("api_key") or "").strip() or str(d.get("api_secret") or "").strip())
    if given:
        key, secret = groww.clean_credentials(d.get("api_key"), d.get("api_secret"))
    else:
        saved = store.get_groww(uid)
        if not saved:
            return 400, {"error": "Enter your Groww API key and secret to sync.", "kind": "no_key"}
        try:
            key, secret = groww.decrypt(saved["key_enc"]), groww.decrypt(saved["secret_enc"])
        except ValueError as e:
            return 400, {"error": str(e), "kind": "key_unreadable"}
    if not groww.rate_ok(uid):
        return 429, {"error": "A sync just ran. Wait %d seconds and try again." % groww.MIN_GAP, "kind": "rate"}
    fetch = (ctx or {}).get("groww_fetch") or groww.fetch_holdings
    try:
        rows, skipped = fetch(key, secret)
    except groww.GrowwError as e:
        return e.status, {"error": e.message, "kind": e.kind}
    if given and d.get("remember", True):
        store.set_groww(uid, groww.encrypt(key), groww.encrypt(secret), groww.hint(key))
    known = lambda sym: (not universe) or sym in universe or sym in stocks
    added, updated, unchanged, more, outcome = _groww_apply(store, uid, rows, known)
    store.mark_groww_sync(uid, len(rows) - len(more))
    seen = {r["symbol"] for r in rows}
    # one line per entry Groww sent, so a missing stock can be found: what Groww said and what this app did with it
    details = [{"symbol": r["symbol"], "qty": r["qty"], "avg_price": r["avg_price"], "pledged": r["pledged"],
                "outcome": outcome.get(r["symbol"]) or "skipped", "unscanned": not known(r["symbol"])} for r in rows]         + [dict(symbol=s["symbol"], outcome="skipped", reason=s["reason"]) for s in skipped]
    for d in details:
        if d["outcome"] == "skipped" and "reason" not in d:
            d["reason"] = next((m["reason"] for m in more if m["symbol"] == d["symbol"]), "")
    return 200, {"returned": len(rows) + len(skipped), "details": details, "unscanned": [d["symbol"] for d in details if d.get("unscanned") and d["outcome"] != "skipped"],
                 "added": added, "updated": updated, "unchanged": unchanged, "skipped": skipped + more,
                 "pledged": [{"symbol": r["symbol"], "qty": r["pledged"]} for r in rows if r["pledged"] > 0],
                 "not_in_groww": [h["symbol"] for h in store.list_holdings(uid) if h["symbol"] not in seen],
                 "groww": groww_payload(store, uid), "me": me_payload(store, uid, scan, hz=hz, ctx=ctx)}


# ---------- holdings tracking: valued positions, lots, import and export ----------
def _price_and_prev(stock, series):
    """Latest price from the scan; previous close derived from the app's own daily series (same basis as the price)."""
    price = stock.get("price") if stock else None
    prev = None
    c = (series or {}).get("c") or []
    if price is not None and len(c) >= 2 and c[-1] and c[-2]:
        prev = float(price) * c[-2] / c[-1]
    elif price is not None and stock and stock.get("prev"):     # a quote-only stock has no series: use its saved previous close
        prev = float(stock["prev"])
    return price, prev


def valued_positions(store, uid, stocks, detail, include_closed=False):
    """-> (list of valued positions, summary). Positions are open ones (and, if asked, fully sold ones)."""
    hs = store.get_hsettings(uid)
    rows = []
    for sym, p in sorted(store.list_positions(uid).items()):
        if not p["qty"] and not include_closed:
            continue
        st = stocks.get(sym)
        price, prev = _price_and_prev(st, (detail.get(sym) or {}).get("series"))
        v = positions.valuation({k: p[k] for k in p if k != "lots"}, price, prev)
        h = hs.get(sym) or {}
        v.update(symbol=sym, name=(st or {}).get("name"), etf=bool((st or {}).get("etf")), exchange=(st or {}).get("exchange"),
                 asof=(st or {}).get("asof"), call=(st or {}).get("verdict"), lots_count=len(p["lots"]),
                 quote_only=bool(st and st.get("quoteOnly")), why_not_scanned=(st or {}).get("whyNotScanned"),
                 target_weight=h.get("target_weight"), review_price=h.get("review_price"), sector=h.get("sector"))
        rows.append(v)
    summary = positions.summarize(rows)
    for r in rows:
        r.setdefault("weight", None)
    return rows, summary


def position_payload(store, uid, sym, stocks, detail):
    sym = str(sym).strip().upper()
    p = store.list_positions(uid).get(sym)
    if p is None:
        p = positions.replay([])
        p["lots"] = []
    rows, summary = valued_positions(store, uid, stocks, detail, include_closed=True)
    v = next((r for r in rows if r["symbol"] == sym), None)
    if v is None:
        st = stocks.get(sym)
        price, prev = _price_and_prev(st, (detail.get(sym) or {}).get("series"))
        v = positions.valuation(dict({k: p[k] for k in p if k != "lots"}), price, prev)
        v.update(symbol=sym, weight=None)
    out = dict(v, lots=p["lots"])
    out["settings"] = store.get_hsettings(uid).get(sym) or {"target_weight": None, "review_price": None, "sector": None}
    out["portfolio"] = {"value": summary["value"], "count": summary["count"]}
    return out


def _csv_num(v):
    """1600.0 -> 1600, 3068.3333 -> 3068.3333: no trailing .0 in an exported file."""
    return str(int(v)) if v == int(v) else ("%.4f" % v).rstrip("0").rstrip(".")


CSV_COLUMNS = ("symbol", "side", "qty", "price", "date", "fees", "note", "amount", "realized")


def lots_csv(store, uid):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for sym, p in sorted(store.list_positions(uid).items()):
        for l in p["lots"]:
            row = [_csv_num(l.get(c)) if isinstance(l.get(c), (int, float)) and not isinstance(l.get(c), bool) else (l.get(c) if l.get(c) is not None else "") for c in CSV_COLUMNS]
            # a note that starts with = + - @ would be run as a formula by a spreadsheet
            row[6] = ("'" + row[6]) if row[6][:1] in ("=", "+", "-", "@") else row[6]
            w.writerow(row)
    return "\ufeff" + buf.getvalue()


_ALIASES = {"symbol": ("symbol", "ticker", "scrip"), "side": ("side", "type", "action"), "qty": ("qty", "quantity", "shares"),
            "price": ("price", "rate", "buy price", "sell price"), "date": ("date", "trade date"),
            "fees": ("fees", "charges", "brokerage"), "note": ("note", "notes", "remarks")}


def parse_import(fmt, data, today):
    """-> (clean lots, rules or None, holding_settings or None). Raises ValueError listing every bad row."""
    raw_rows, extra_rules, extra_hs = [], None, None
    if fmt == "json":
        d = json.loads(data) if isinstance(data, str) else data
        if not isinstance(d, dict) or not isinstance(d.get("lots"), list):
            raise ValueError("This JSON file has no transactions. Import a file exported from this app.")
        raw_rows = [(i + 1, x) for i, x in enumerate(d["lots"]) if isinstance(x, dict)]
        extra_rules, extra_hs = d.get("rules"), d.get("holding_settings")
    else:
        text = str(data or "").lstrip("\ufeff")
        rd = csv.reader(io.StringIO(text))
        header = None
        for n, row in enumerate(rd, 1):
            if not any(c.strip() for c in row):
                continue
            if header is None:
                names = [c.strip().lower() for c in row]
                header = {k: next((names.index(a) for a in al if a in names), None) for k, al in _ALIASES.items()}
                if header["symbol"] is None or header["qty"] is None or header["price"] is None:
                    raise ValueError("The first row must name the columns: symbol, qty (or quantity) and price are required; side, date, fees and note are optional.")
                continue
            raw_rows.append((n, {k: (row[i].strip() if i is not None and i < len(row) else "") for k, i in header.items()}))
    clean, errs = [], []
    for n, r in raw_rows:
        try:
            r = dict(r)
            if not str(r.get("side") or "").strip():
                r["side"] = "buy"
            if str(r.get("note") or "").startswith("'") and str(r["note"])[1:2] in ("=", "+", "-", "@"):
                r["note"] = r["note"][1:]
            clean.append(positions.validate_lot(r, today, require_date=False))
        except ValueError as e:
            errs.append("Row %d: %s" % (n, e))
    if errs:
        raise ValueError("; ".join(errs[:8]) + (" (and %d more)" % (len(errs) - 8) if len(errs) > 8 else ""))
    if not clean:
        raise ValueError("No transactions found in the file.")
    return clean, extra_rules, extra_hs


# ---------- alerts ("Needs your attention") ----------
DISCLAIMER = "For research and education. Not investment advice."


def attention_payload(store, uid, scan, ctx, today=None):
    """Evaluate the rules for the stocks this user holds, then apply what they dismissed or snoozed."""
    today = today or datetime.date.today()
    stocks = _stocks(scan)
    detail = (ctx or {}).get("detail") or {}
    rows, summary = valued_positions(store, uid, stocks, detail)
    holdings = []
    if rows:
        facts_fn = (ctx or {}).get("facts")
        items = [(r["symbol"], r.get("exchange") or "NSE", r.get("etf", False)) for r in rows]
        facts = facts_fn(items) if facts_fn else {}
        hs = store.get_hsettings(uid)
        seen = store.get_seen(uid)
        new_results = {}
        for r in rows:
            f = facts.get(r["symbol"])
            if f and f.get("status") in ("ok", "stale") and f.get("quarters"):
                end = f["quarters"][-1]["end"]
                row = seen.get(r["symbol"])
                if row is None:
                    store.set_seen(uid, r["symbol"], end, None)
                elif end > row["end"]:
                    store.set_seen(uid, r["symbol"], end, today.isoformat())
                    row = {"end": end, "detected": today.isoformat()}
                if row and row.get("detected") and row["end"] == end:
                    d = positions.parse_date(row["detected"])
                    if d and 0 <= (today - d).days <= 30:
                        new_results[r["symbol"]] = {"end": end, "detected": row["detected"]}
            series = (detail.get(r["symbol"]) or {}).get("series") or {}
            c, s200 = series.get("c") or [], series.get("s200") or []
            holdings.append(dict(r, avg_cost=r["avg_cost"], close=c[-1] if c else None, s200=s200[-1] if s200 else None,
                                 facts=facts.get(r["symbol"])))
        res = rules.evaluate(holdings, store.get_rules(uid), today, new_results)
    else:
        res = {"alerts": [], "not_evaluated": [], "checked": []}
    states = store.get_states(uid)
    rule_states = {k: v for k, v in states.items() if not k.startswith("seen:")}
    firing = {a["key"] for a in res["alerts"]}
    stale = [k for k in rule_states if k in set(res["checked"]) and k not in firing]
    stale += [k for k in states if k.startswith("seen:") and k[5:] not in firing and k[5:] in set(res["checked"])]
    if stale:
        store.clear_states(uid, stale)
        states = {k: v for k, v in states.items() if k not in stale}
        rule_states = {k: v for k, v in rule_states.items() if k not in stale}
    visible, hidden = rules.apply_state(res["alerts"], rule_states, today)
    for a in visible:
        sv = states.get("seen:" + a["key"])
        a["unseen"] = not (sv and sv["fingerprint"] == a["fingerprint"])
    coverage = []
    for h in holdings:
        f = h.get("facts") or {}
        q = f.get("quarters") or []
        coverage.append({"symbol": h["symbol"], "status": f.get("status") or "none", "reason": f.get("reason"), "fetched": f.get("fetched"),
                         "latest_quarter": q[-1]["end"] if q else None, "quarters": len(q), "etf": h.get("etf", False)})
    return {"alerts": visible, "hidden": hidden, "unseen": sum(1 for a in visible if a["unseen"]), "not_evaluated": res["not_evaluated"],
            "coverage": coverage, "disclaimer": DISCLAIMER, "holdings": len(rows), "generated": today.isoformat(),
            "rules": store.get_rules(uid)}
