import json, os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import api_me
from modules.account import auth, groww
from core.store import Store

U = {"TCS", "INFY"}
KEY, SECRET = "key-ABCDEFGH-1234567890", "secret-ZYXWVUTS-0987654321"
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(groww, "KEY_PATH", str(tmp_path / "groww.key"))
    monkeypatch.delenv("STOCKPICKS_SECRET_KEY", raising=False)
    monkeypatch.setattr(auth, "SCRYPT", (2 ** 10, 8, 1))      # fast hashing for tests; the real setting is checked in test_scrypt_parameters
    auth.reset_limits()
    groww._last.clear()


class Browser:
    """A cookie jar that talks to api_me the way server.py does."""

    def __init__(self, st, ip="1.2.3.4", profile=None):
        self.st, self.ip, self.jar, self.profile, self.now = st, ip, {}, profile or {"vendor_user_id": "VU-1", "ucc": "UCC-1"}, 1_800_000_000.0

    def header(self):
        return "; ".join("%s=%s" % kv for kv in self.jar.items())

    def call(self, method, path, body=None):
        ident = api_me.identify(self.header(), self.st, self.now)
        ctx = {"ident": ident, "cookies": [], "ip": self.ip, "now": self.now, "groww_profile": lambda k, s: self.profile,
               "groww_fetch": lambda k, s: groww.normalize_holdings({"holdings": []})}
        code, obj = api_me.handle(method, path, "", json.dumps(body).encode() if body is not None else b"", self.st, ident.uid, {"stocks": []}, U, ctx=ctx)
        self.cookies = ident.cookies + ctx["cookies"]
        for c in self.cookies:
            name, _, rest = c.partition("=")
            value = rest.split(";")[0]
            if "Max-Age=0" in c:
                self.jar.pop(name, None)
            else:
                self.jar[name] = value
        return code, obj

    def uid(self):
        return api_me.identify(self.header(), self.st, self.now).uid


def signup(b, name="alice", pw=PW):
    return b.call("POST", "/api/auth/signup", {"username": name, "password": pw})


# ---------- pure helpers ----------
def test_password_hash_and_verify():
    h = auth.hash_password(PW)
    assert PW not in h and h.startswith("scrypt$") and auth.verify_password(PW, h)
    assert not auth.verify_password("wrong password!", h)
    assert auth.hash_password(PW) != h                           # random salt
    for bad in ("", "x", "scrypt$1$2", None):
        assert not auth.verify_password(PW, bad)


def test_scrypt_parameters_are_the_owasp_setting():
    import importlib
    real = importlib.reload(auth)
    assert real.SCRYPT == (2 ** 15, 8, 3)


def test_username_and_password_rules():
    assert auth.check_username(" Bob_1 ") == "Bob_1"
    for bad in ("ab", "x" * 33, "has space", "emoji☃", ""):
        with pytest.raises(ValueError):
            auth.check_username(bad)
    assert auth.check_password(PW, "bob")
    for pw, name in (("short", "bob"), ("x" * 201, "bob"), ("BOBBOBBOBBOB", "bobbobbobbob"), (123, "bob")):
        with pytest.raises(ValueError):
            auth.check_password(pw, name)


def test_limiter_window():
    l = auth.Limiter(3, 100)
    for t in (0, 1, 2):
        l.fail("k", t)
    assert l.wait("k", 3) > 0 and l.wait("other", 3) == 0
    assert l.wait("k", 150) == 0                                # old failures expire
    l.clear("k")
    assert l.wait("k", 3) == 0


def test_id_hash_is_keyed_and_stable():
    a, b = auth.id_hash("v", "X", b"k1"), auth.id_hash("v", "X", b"k2")
    assert a == auth.id_hash("v", "X", b"k1") and a != b and "X" not in a
    assert auth.id_hash("v", "X", b"k1") != auth.id_hash("u", "X", b"k1")


# ---------- guests, sign-up, sign-out ----------
def test_guest_gets_a_guest_cookie_and_is_not_signed_in():
    b = Browser(Store(":memory:"))
    code, me = b.call("GET", "/api/auth/me")
    assert code == 200 and me["signedIn"] is False and me["guest"] is True
    assert "uid" in b.jar and "sid" not in b.jar
    flags = [c for c in b.cookies if c.startswith("uid=")][0]
    assert "HttpOnly" in flags and "SameSite=Strict" in flags and "Secure" not in flags


def test_secure_flag_only_when_configured(monkeypatch):
    monkeypatch.setenv("STOCKPICKS_SECURE_COOKIES", "1")
    b = Browser(Store(":memory:"))
    b.call("GET", "/api/auth/me")
    assert all("Secure" in c for c in b.cookies)


def test_signup_keeps_the_guest_data_and_rotates_the_guest_cookie():
    st = Store(":memory:")
    b = Browser(st)
    b.call("GET", "/api/session")
    guest = b.uid()
    st.upsert_holding(guest, "TCS", 10, 3500)
    code, me = signup(b)
    assert code == 200 and me["signedIn"] and me["username"] == "alice" and me["hasPassword"] and me["via"] == "password"
    assert b.uid() == guest and st.is_account_id(guest)             # data owner is the former guest id
    assert b.jar["uid"] != guest                                    # the browser no longer holds the account id as a guest id
    assert [h["symbol"] for h in st.list_holdings(b.uid())] == ["TCS"]
    sid = b.jar["sid"]
    assert sid not in json.dumps(st.db.execute("SELECT * FROM sessions").fetchall() and [tuple(r) for r in st.db.execute("SELECT * FROM sessions")])   # only a hash is stored


def test_logout_does_not_leave_the_account_data_reachable():
    st = Store(":memory:")
    b = Browser(st)
    b.call("GET", "/api/session")
    owner = b.uid()
    st.upsert_holding(owner, "TCS", 10, 3500)
    signup(b)
    code, me = b.call("POST", "/api/auth/logout")
    assert code == 200 and me["signedIn"] is False and "sid" not in b.jar
    assert b.uid() != owner and st.list_holdings(b.uid()) == []
    b.jar["uid"] = owner                                            # even a stale guest cookie holding the account id is refused
    assert b.uid() != owner


def test_session_expires():
    st = Store(":memory:")
    b = Browser(st)
    signup(b)
    assert b.call("GET", "/api/auth/me")[1]["signedIn"]
    b.now += auth.SESSION_TTL + 5
    assert b.call("GET", "/api/auth/me")[1]["signedIn"] is False


def test_username_taken_case_insensitive_and_validation():
    st = Store(":memory:")
    assert signup(Browser(st), "Alice")[0] == 200
    code, out = signup(Browser(st), "alice")
    assert code == 409 and "taken" in out["error"]
    assert signup(Browser(st), "ab")[0] == 400
    assert signup(Browser(st), "bob", "short")[0] == 400
    b = Browser(st)
    signup(b, "carol")
    assert signup(b, "carol2")[0] == 400                           # already signed in


# ---------- sign-in ----------
def test_login_from_a_second_browser_sees_the_data():
    st = Store(":memory:")
    a = Browser(st)
    a.call("GET", "/api/session")
    st.upsert_holding(a.uid(), "INFY", 5, 1400)
    signup(a)
    b = Browser(st)
    code, me = b.call("POST", "/api/auth/login", {"username": "ALICE", "password": PW})
    assert code == 200 and me["signedIn"] and b.uid() == a.uid()
    assert [h["symbol"] for h in st.list_holdings(b.uid())] == ["INFY"]


def test_wrong_password_and_unknown_user_look_the_same():
    st = Store(":memory:")
    signup(Browser(st))
    b = Browser(st)
    c1, o1 = b.call("POST", "/api/auth/login", {"username": "alice", "password": "wrong wrong wrong"})
    c2, o2 = b.call("POST", "/api/auth/login", {"username": "nobody", "password": "wrong wrong wrong"})
    assert (c1, o1) == (c2, o2) == (401, {"error": "Wrong username or password."})
    assert b.call("POST", "/api/auth/login", {"username": "alice"})[0] == 401      # missing password


def test_lockout_after_repeated_failures_then_recovers():
    st = Store(":memory:")
    signup(Browser(st))
    b = Browser(st)
    for _ in range(5):
        assert b.call("POST", "/api/auth/login", {"username": "alice", "password": "wrong wrong wrong"})[0] == 401
    code, out = b.call("POST", "/api/auth/login", {"username": "alice", "password": PW})
    assert code == 429 and "minute" in out["error"]                 # even the right password waits
    b.now += 16 * 60
    assert b.call("POST", "/api/auth/login", {"username": "alice", "password": PW})[0] == 200


def test_password_account_data_is_isolated_between_users():
    st = Store(":memory:")
    a, b = Browser(st), Browser(st)
    a.call("GET", "/api/session"); st.upsert_holding(a.uid(), "TCS", 1, 10); signup(a, "alice")
    signup(b, "bobby")
    assert st.list_holdings(b.uid()) == [] and b.uid() != a.uid()


# ---------- Sign in with Groww ----------
def groww_signin(b, remember=True):
    return b.call("POST", "/api/auth/groww", {"api_key": KEY, "api_secret": SECRET, "remember": remember})


def test_groww_signin_creates_an_account_and_keeps_guest_data():
    st = Store(":memory:")
    b = Browser(st)
    b.call("GET", "/api/session"); guest = b.uid(); st.upsert_holding(guest, "TCS", 10, 3500)
    code, me = groww_signin(b)
    assert code == 200 and me["created"] is True and me["signedIn"] and me["via"] == "groww" and me["username"] is None
    assert me["hasPassword"] is False and me["growwLinked"] is True and me["canSetPasswordFreely"] is True
    assert b.uid() == guest and b.jar["uid"] != guest
    raw = json.dumps([tuple(r) for r in st.db.execute("SELECT * FROM groww_ids")])
    assert "VU-1" not in raw and "UCC-1" not in raw                # ids are stored only as keyed hashes
    assert st.groww_status(guest)["saved"] is True                  # remembered key belongs to the account


def test_groww_signin_again_finds_the_same_account_and_never_returns_key_material():
    st = Store(":memory:")
    a = Browser(st)
    _, first = groww_signin(a)
    owner = a.uid()
    a.call("POST", "/api/auth/logout")
    b = Browser(st)
    code, me = groww_signin(b)
    assert code == 200 and me["created"] is False and b.uid() == owner
    assert KEY not in json.dumps(me) and SECRET not in json.dumps(me)
    # Groww later adds a ucc to a profile that only had a vendor id: still the same account
    st2 = Store(":memory:")
    c = Browser(st2, profile={"vendor_user_id": "VU-9", "ucc": ""}); groww_signin(c); o = c.uid(); c.call("POST", "/api/auth/logout")
    d = Browser(st2, profile={"vendor_user_id": "VU-9", "ucc": "NEW-UCC"})
    assert groww_signin(d)[1]["created"] is False and d.uid() == o


def test_groww_errors_are_reported_and_count_against_the_limiter():
    st = Store(":memory:")
    b = Browser(st)
    def bad(k, s):
        raise groww.GrowwError("rejected", "Groww did not accept this key and secret.")
    ident = api_me.identify("", st)
    ctx = {"ident": ident, "cookies": [], "ip": "9.9.9.9", "groww_profile": bad}
    for _ in range(20):
        code, out = api_me.handle("POST", "/api/auth/groww", "", json.dumps({"api_key": KEY, "api_secret": SECRET}).encode(), st, ident.uid, {"stocks": []}, U, ctx=ctx)
        assert code == 400 and out["kind"] == "rejected"
    assert api_me.handle("POST", "/api/auth/groww", "", json.dumps({"api_key": KEY, "api_secret": SECRET}).encode(), st, ident.uid, {"stocks": []}, U, ctx=ctx)[0] == 429
    assert st.get_account(ident.uid) is None


def test_groww_signin_validates_fields_before_calling_groww():
    st = Store(":memory:")
    b = Browser(st)
    code, out = b.call("POST", "/api/auth/groww", {"api_key": "", "api_secret": SECRET})
    assert code == 400 and "both" in out["error"].lower()


def test_link_groww_to_a_password_account_and_block_stealing():
    st = Store(":memory:")
    a = Browser(st); signup(a, "alice")
    assert a.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET})[1]["growwLinked"] is True
    b = Browser(st); signup(b, "bobby")
    code, out = b.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET})
    assert code == 409 and "already linked" in out["error"]
    g = Browser(st)
    assert Browser(st).call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET})[0] == 401   # guests cannot link
    code, me = groww_signin(g)
    assert me["created"] is False and g.uid() == a.uid()            # signing in with that Groww id reaches alice's account


def test_unlink_needs_a_password():
    st = Store(":memory:")
    g = Browser(st); groww_signin(g)
    code, out = g.call("DELETE", "/api/auth/groww")
    assert code == 400 and "password" in out["error"].lower()
    a = Browser(st, profile={"vendor_user_id": "VU-2", "ucc": "UCC-2"}); signup(a)
    a.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET})
    code, me = a.call("DELETE", "/api/auth/groww")
    assert code == 200 and me["growwLinked"] is False


# ---------- passwords and recovery ----------
def test_change_password_needs_the_current_one_and_signs_other_devices_out():
    st = Store(":memory:")
    a = Browser(st); signup(a)
    other = Browser(st); other.call("POST", "/api/auth/login", {"username": "alice", "password": PW})
    assert a.call("POST", "/api/auth/password", {"current_password": "nope nope nope", "new_password": "a brand new password"})[0] == 401
    code, me = a.call("POST", "/api/auth/password", {"current_password": PW, "new_password": "a brand new password"})
    assert code == 200 and me["signedIn"]
    assert other.call("GET", "/api/auth/me")[1]["signedIn"] is False   # the other device was signed out
    assert a.call("GET", "/api/auth/me")[1]["signedIn"] is True        # this one stays
    c = Browser(st)
    assert c.call("POST", "/api/auth/login", {"username": "alice", "password": PW})[0] == 401
    assert c.call("POST", "/api/auth/login", {"username": "alice", "password": "a brand new password"})[0] == 200


def test_groww_only_account_sets_a_username_and_password():
    st = Store(":memory:")
    g = Browser(st); groww_signin(g)
    assert g.call("POST", "/api/auth/password", {"new_password": PW})[0] == 400      # needs a username
    code, me = g.call("POST", "/api/auth/password", {"username": "gina", "new_password": PW})
    assert code == 200 and me["username"] == "gina" and me["hasPassword"]
    assert Browser(st).call("POST", "/api/auth/login", {"username": "gina", "password": PW})[0] == 200


def test_forgotten_password_is_recovered_through_groww_but_only_for_a_short_time():
    st = Store(":memory:")
    a = Browser(st); signup(a, "alice"); a.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET}); owner = a.uid()
    b = Browser(st)                                              # forgot the password: signs in with Groww
    code, me = groww_signin(b)
    assert code == 200 and b.uid() == owner and me["hasPassword"] and me["canSetPasswordFreely"] is True
    code, me = b.call("POST", "/api/auth/password", {"new_password": "my recovered password"})
    assert code == 200
    assert a.call("GET", "/api/auth/me")[1]["signedIn"] is False   # the old session is gone
    assert Browser(st).call("POST", "/api/auth/login", {"username": "alice", "password": "my recovered password"})[0] == 200
    b.now += auth.RECENT_GROWW + 60                              # later, the Groww shortcut has lapsed
    assert b.call("GET", "/api/auth/me")[1]["canSetPasswordFreely"] is False
    assert b.call("POST", "/api/auth/password", {"new_password": "another password here"})[0] == 401


def test_password_endpoint_needs_a_session():
    st = Store(":memory:")
    assert Browser(st).call("POST", "/api/auth/password", {"new_password": PW})[0] == 401
    assert Browser(st).call("GET", "/api/auth/nope")[0] == 404


# ---------- privacy ----------
def test_export_and_database_hold_no_secrets():
    st = Store(":memory:")
    b = Browser(st); signup(b); groww_signin_b = Browser(st);
    b.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET})
    out = json.dumps(st.export_user(b.uid()))
    assert "scrypt$" not in out and "pw_hash" not in out and KEY not in out and SECRET not in out
    acct = st.export_user(b.uid())["account"]
    assert acct == {"is_account": True, "username": "alice", "has_password": True, "groww_linked": True}
    assert PW not in json.dumps([tuple(r) for r in st.db.execute("SELECT * FROM accounts")])


def test_delete_my_data_removes_the_account_sessions_and_links():
    st = Store(":memory:")
    b = Browser(st); signup(b); b.call("POST", "/api/auth/groww/link", {"api_key": KEY, "api_secret": SECRET}); uid = b.uid()
    code, out = b.call("DELETE", "/api/me")
    assert code == 200 and out["deleted"] and "sid" not in b.jar and b.uid() != uid
    for t in ("accounts", "groww_ids", "sessions", "groww_creds"):
        assert st.db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] == 0
    assert Browser(st).call("POST", "/api/auth/login", {"username": "alice", "password": PW})[0] == 401


def test_groww_sync_still_works_for_a_signed_in_account_with_a_remembered_key():
    st = Store(":memory:")
    b = Browser(st); groww_signin(b)
    code, out = b.call("POST", "/api/groww/sync", {})
    assert code == 200 and out["groww"]["saved"] is True            # reuses the key remembered at sign-in
