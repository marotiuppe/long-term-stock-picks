import json, os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import api_me
from modules.account import groww
from core.store import Store

U = {"TCS", "INFY", "RELIANCE", "TATSILV"}
KEY, SECRET = "key-ABCDEFGH-1234567890", "secret-ZYXWVUTS-0987654321"


@pytest.fixture(autouse=True)
def fresh_keys(tmp_path, monkeypatch):
    """Never write the real master key, and never hit the rate limit across tests."""
    monkeypatch.setattr(groww, "KEY_PATH", str(tmp_path / "groww.key"))
    monkeypatch.delenv("STOCKPICKS_SECRET_KEY", raising=False)
    groww._last.clear()


RESP = {"holdings": [
    {"isin": "X1", "trading_symbol": "TCS", "quantity": 10.0, "average_price": 3500, "pledge_quantity": 0},
    {"isin": "X2", "trading_symbol": "INFY", "quantity": 25, "average_price": 1450.5, "pledge_quantity": 5},
    {"isin": "X3", "trading_symbol": "ZZUNKNOWN", "quantity": 3, "average_price": 10, "pledge_quantity": 0},
    {"isin": "X4", "trading_symbol": "RELIANCE", "quantity": 0, "average_price": 2000},
    {"isin": "X5", "trading_symbol": "bad sym!", "quantity": 1, "average_price": 5},
]}


def fake_fetch(resp=RESP, seen=None):
    def f(key, secret):
        if seen is not None:
            seen.append((key, secret))
        return groww.normalize_holdings(resp)
    return f


def call(st, uid, method, path, body=None, fetch=None):
    ctx = {"groww_fetch": fetch} if fetch else None
    return api_me.handle(method, path, "", json.dumps(body).encode() if body is not None else b"", st, uid, {"stocks": []}, U, ctx=ctx)


# ---------- pure parts ----------
def test_normalize_skips_bad_rows_and_combines_duplicates():
    rows, skipped = groww.normalize_holdings({"holdings": RESP["holdings"] + [
        {"trading_symbol": "TCS", "quantity": 10, "average_price": 3700}]})
    tcs = next(r for r in rows if r["symbol"] == "TCS")
    assert tcs["qty"] == 20 and tcs["avg_price"] == 3600          # weighted average
    assert next(r for r in rows if r["symbol"] == "INFY")["pledged"] == 5
    reasons = {s["symbol"]: s["reason"] for s in skipped}
    assert reasons["RELIANCE"] == "Groww lists no net quantity"
    assert not any(r["symbol"] == "RELIANCE" for r in rows)
    with pytest.raises(groww.GrowwError):
        groww.normalize_holdings({"nope": 1})


def test_encryption_round_trip_and_hint():
    token = groww.encrypt(SECRET)
    assert SECRET not in token and groww.decrypt(token) == SECRET
    assert groww.hint(KEY).endswith(KEY[-4:]) and KEY[:-4] not in groww.hint(KEY)
    with pytest.raises(ValueError):
        groww.decrypt("not-a-token")


def test_clean_credentials_messages():
    assert groww.clean_credentials(" %s " % KEY, SECRET) == (KEY, SECRET)
    for k, s in (("", SECRET), (KEY, ""), ("short", SECRET), (KEY, "has space inside it!"), (KEY, "x" * 5000)):
        with pytest.raises(ValueError):
            groww.clean_credentials(k, s)


class _Exc(Exception):
    def __init__(self, code="", msg=""):
        self.code, self.msg = code, msg


def _sdk(error=None, resp=RESP):
    class API:
        def __init__(self, token): pass
        def get_holdings_for_user(self, timeout=None): return resp
        @staticmethod
        def get_access_token(api_key, totp=None, secret=None):
            if error:
                raise error
            return "tok"
    return type("sdk", (), {"GrowwAPI": API})


def test_fetch_maps_sdk_errors_to_kinds():
    class GrowwAPIAuthenticationException(_Exc): pass
    class GrowwAPIAuthorisationException(_Exc): pass
    class GrowwAPIRateLimitException(_Exc): pass
    class ReadTimeout(_Exc): pass
    cases = [(GrowwAPIAuthenticationException(), "rejected"), (GrowwAPIAuthorisationException(), "forbidden"),
             (GrowwAPIRateLimitException(), "rate"), (ReadTimeout(), "unreachable"),
             (_Exc("400", "Approval pending for %s" % SECRET), "rejected"), (RuntimeError("boom"), "unreachable")]
    for exc, kind in cases:
        with pytest.raises(groww.GrowwError) as e:
            groww.fetch_holdings(KEY, SECRET, sdk=_sdk(exc))
        assert e.value.kind == kind
        assert SECRET not in e.value.message and KEY not in e.value.message   # a message from Groww is scrubbed
    rows, _ = groww.fetch_holdings(KEY, SECRET, sdk=_sdk())
    assert {r["symbol"] for r in rows} == {"TCS", "INFY", "ZZUNKNOWN"}


# ---------- API ----------
def test_sync_with_new_key_saves_only_after_success_and_never_returns_it():
    st, seen = Store(":memory:"), []
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch(seen=seen))
    assert code == 200 and seen == [(KEY, SECRET)]
    assert out["added"] == 3 and out["updated"] == 0
    assert out["unscanned"] == ["ZZUNKNOWN"]                        # held per Groww, but not a stock the scan covers: kept, flagged
    assert not any(s["symbol"] == "ZZUNKNOWN" for s in out["skipped"])
    assert out["pledged"] == [{"symbol": "INFY", "qty": 5.0}]
    assert {h["symbol"] for h in st.list_holdings("u1")} == {"TCS", "INFY", "ZZUNKNOWN"}
    blob = json.dumps(out)
    assert SECRET not in blob and KEY not in blob and out["groww"]["saved"] and out["groww"]["hint"].endswith(KEY[-4:])
    raw = st.db.execute("SELECT key_enc, secret_enc FROM groww_creds").fetchone()
    assert KEY not in raw[0] and SECRET not in raw[1]                   # encrypted at rest
    assert SECRET not in json.dumps(st.export_user("u1")) and KEY not in json.dumps(st.export_user("u1"))
    assert SECRET not in json.dumps(call(st, "u1", "GET", "/api/groww")[1])


def test_second_sync_reuses_the_saved_key():
    st, seen = Store(":memory:"), []
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch(seen=seen))
    groww._last.clear()
    code, out = call(st, "u1", "POST", "/api/groww/sync", {}, fake_fetch(seen=seen))
    assert code == 200 and seen[-1] == (KEY, SECRET) and out["unchanged"] == 3 and out["added"] == 0


def test_rejected_key_is_not_saved_and_gives_a_clear_message():
    st = Store(":memory:")
    def bad(key, secret):
        raise groww.GrowwError("rejected", "Groww did not accept this key and secret.")
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, bad)
    assert code == 400 and out["kind"] == "rejected" and not st.groww_status("u1")["saved"]


def test_no_key_and_missing_field_errors():
    st = Store(":memory:")
    assert call(st, "u1", "POST", "/api/groww/sync", {}, fake_fetch())[1]["kind"] == "no_key"
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY}, fake_fetch())
    assert code == 400 and "both" in out["error"].lower()


def test_rate_limit_between_syncs():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    code, out = call(st, "u1", "POST", "/api/groww/sync", {}, fake_fetch())
    assert code == 429 and out["kind"] == "rate"


def test_users_are_isolated():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert call(st, "u2", "GET", "/api/groww")[1]["saved"] is False
    assert call(st, "u2", "POST", "/api/groww/sync", {}, fake_fetch())[1]["kind"] == "no_key"
    assert st.list_holdings("u2") == []


def test_forget_key_and_delete_my_data_remove_it():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert call(st, "u1", "DELETE", "/api/groww/credentials")[1]["saved"] is False
    assert st.get_groww("u1") is None
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    st.delete_user("u1")
    assert st.db.execute("SELECT COUNT(*) FROM groww_creds").fetchone()[0] == 0


def test_remember_false_does_not_save():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET, "remember": False}, fake_fetch())
    assert not st.groww_status("u1")["saved"] and len(st.list_holdings("u1")) == 3


def test_user_entered_transactions_are_never_overwritten():
    st = Store(":memory:")
    st.upsert_holding("u1", "TCS", 5, 3000)                                   # one opening lot: Groww may update it
    lots = {"symbol": "INFY", "side": "buy", "qty": 10, "price": 1400, "date": "2026-01-02", "fees": 0, "note": ""}
    st.add_lot("u1", lots); st.add_lot("u1", dict(lots, qty=5, date="2026-02-02"))   # two transactions: hands off
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert code == 200 and out["updated"] == 1 and out["added"] == 1      # TCS updated; ZZUNKNOWN is new
    held = {h["symbol"]: h for h in st.list_holdings("u1")}
    assert held["TCS"]["qty"] == 10 and held["TCS"]["avg_price"] == 3500
    assert held["INFY"]["qty"] == 15                                           # untouched
    assert any(s["symbol"] == "INFY" and "transactions" in s["reason"] for s in out["skipped"])


def test_symbols_not_in_groww_are_reported_not_removed():
    st = Store(":memory:")
    st.upsert_holding("u1", "TATSILV", 100, 20)
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert out["not_in_groww"] == ["TATSILV"] and any(h["symbol"] == "TATSILV" for h in st.list_holdings("u1"))


def test_synced_position_is_labelled():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert all(l["note"].startswith("Synced from Groww") for l in st.list_lots("u1"))


def test_master_key_file_created_once_and_reused(tmp_path):
    a = groww.encrypt("hello")
    assert os.path.exists(groww.KEY_PATH) and groww.decrypt(a) == "hello"
    b = groww.encrypt("hello")
    assert groww.decrypt(b) == "hello"           # same key on the second use


def test_zero_net_quantity_reports_what_groww_sent_instead_of_guessing():
    rows, skipped = groww.normalize_holdings({"holdings": [
        {"trading_symbol": "TCS", "quantity": 0, "average_price": 3500, "pledge_quantity": 10, "t1_quantity": 2, "demat_free_quantity": 0},
        "junk"]})
    assert rows == []
    why = {x["symbol"]: x["reason"] for x in skipped}
    assert why["TCS"] == "Groww lists no net quantity (but pledged 10, T+1 2)"
    assert why["?"].startswith("Groww sent an entry")


def test_sync_says_how_many_groww_returned_and_what_happened_to_each():
    st = Store(":memory:")
    code, out = call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    assert code == 200 and out["returned"] == 5                      # every entry Groww sent is counted, imported or not
    by = {d["symbol"]: d for d in out["details"]}
    assert len(out["details"]) == 5
    assert by["TCS"]["outcome"] == "new" and by["TCS"]["qty"] == 10 and by["TCS"]["avg_price"] == 3500
    assert by["INFY"]["outcome"] == "new" and by["INFY"]["pledged"] == 5
    assert by["ZZUNKNOWN"]["outcome"] == "new" and by["ZZUNKNOWN"]["unscanned"] is True and by["TCS"]["unscanned"] is False
    assert by["RELIANCE"]["outcome"] == "skipped" and "no net quantity" in by["RELIANCE"]["reason"]
    groww._last.clear()
    out2 = call(st, "u1", "POST", "/api/groww/sync", {}, fake_fetch())[1]
    assert {d["symbol"]: d["outcome"] for d in out2["details"]}["TCS"] == "unchanged"


def test_stocks_outside_the_scan_are_kept_and_counted_as_unpriced_in_the_portfolio():
    st = Store(":memory:")
    call(st, "u1", "POST", "/api/groww/sync", {"api_key": KEY, "api_secret": SECRET}, fake_fetch())
    me = api_me.me_payload(st, "u1", {"stocks": [{"symbol": "TCS", "price": 4000.0, "verdict": "WATCH"}, {"symbol": "INFY", "price": 1500.0, "verdict": "WATCH"}]})
    rows = {r["symbol"]: r for r in me["positions"]}
    assert set(rows) == {"TCS", "INFY", "ZZUNKNOWN"}
    assert rows["ZZUNKNOWN"]["price"] is None and rows["ZZUNKNOWN"]["value"] is None and rows["ZZUNKNOWN"]["invested"] == 30
    assert me["summary"]["unpriced"] == ["ZZUNKNOWN"] and me["summary"]["count"] == 3
    assert me["summary"]["value"] == 10 * 4000 + 25 * 1500                      # value counts only what has a price
