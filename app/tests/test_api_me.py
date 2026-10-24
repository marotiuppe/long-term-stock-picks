import json, os, sys, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core.store import Store

SCAN = {"generated": "24 Oct 2026 10:00", "sellDates": {"1m": "2026-11-24"}, "buyDate": "2026-10-26",
        "stocks": [{"symbol": "TCS", "price": 100.0, "stop": 90.0, "sma20": 99.0, "verdict": "BUY", "asof": "2026-10-23"},
                   {"symbol": "INFY", "price": 80.0, "stop": 85.0, "sma20": 79.0, "verdict": "DOWNTREND", "asof": "2026-10-23"}]}


@pytest.fixture
def base():
    server._store, server._universe = Store(":memory:"), {"TCS", "INFY", "SBIN"}
    server.STATE.update(t=time.time(), running=False, error=None, data=SCAN)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    server._store = server._universe = None
    server.STATE.update(data=None, t=0)


def call(base, method, path, body=None, cookie=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(base + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        r = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, json.loads(r.read() or b"{}"), r.headers


def new_user(base):
    _, _, h = call(base, "GET", "/api/me")
    return h["Set-Cookie"].split(";")[0]


def test_first_visit_sets_httponly_cookie(base):
    _, _, h = call(base, "GET", "/api/me")
    assert "uid=" in h["Set-Cookie"] and "HttpOnly" in h["Set-Cookie"] and "SameSite=Strict" in h["Set-Cookie"]


def test_add_holding_shows_pnl_and_stop(base):
    c = new_user(base)
    code, me, _ = call(base, "POST", "/api/holdings", {"symbol": "tcs", "qty": 10, "avg_price": 80}, c)
    h = me["holdings"][0]
    assert code == 200 and h["symbol"] == "TCS" and h["pnl_abs"] == 200 and h["pnl_pct"] == 25.0
    assert h["distance_to_stop_pct"] == 10.0 and h["call"] == "BUY" and h["review_date"] == "2026-11-24"


def test_users_cannot_see_each_others_data(base):
    a, b = new_user(base), new_user(base)
    call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": 5, "avg_price": 90}, a)
    call(base, "POST", "/api/watchlist", {"symbol": "SBIN"}, a)
    _, me_b, _ = call(base, "GET", "/api/me", cookie=b)
    assert me_b["holdings"] == [] and me_b["watchlist"] == []
    assert len(call(base, "GET", "/api/me", cookie=a)[1]["holdings"]) == 1
    assert call(base, "GET", "/api/export", cookie=b)[1]["holdings"] == []


def test_paste_import_reports_errors(base):
    c = new_user(base)
    code, d, _ = call(base, "POST", "/api/holdings/paste", {"text": "TCS 10 95\nNOSUCH 1 1\nINFY -3 50"}, c)
    assert code == 200 and d["added"] == 1 and len(d["errors"]) == 2
    assert d["me"]["holdings"][0]["symbol"] == "TCS"


def test_unknown_symbol_and_bad_numbers_rejected(base):
    c = new_user(base)
    assert call(base, "POST", "/api/holdings", {"symbol": "NOSUCH", "qty": 1, "avg_price": 1}, c)[0] == 400
    assert call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": -1, "avg_price": 1}, c)[0] == 400
    assert call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": "x", "avg_price": 1}, c)[0] == 400


def test_alerts_once_per_event_and_mark_read(base):
    c = new_user(base)
    call(base, "POST", "/api/holdings", {"symbol": "INFY", "qty": 1, "avg_price": 100}, c)   # price 80 <= stop 85
    first = call(base, "GET", "/api/me", cookie=c)[1]
    again = call(base, "GET", "/api/me", cookie=c)[1]
    assert [a["kind"] for a in first["alerts"]].count("stop_breached") == 1
    assert len(again["alerts"]) == len(first["alerts"]) and first["unread"] >= 1
    assert call(base, "POST", "/api/alerts/read", {}, c)[1]["unread"] == 0


def test_cross_site_write_refused(base):
    c = new_user(base)
    code, _, _ = call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": 1, "avg_price": 1}, c,
                      headers={"Origin": "https://evil.example"})
    assert code == 403


def test_delete_my_data(base):
    c = new_user(base)
    call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": 1, "avg_price": 1}, c)
    assert call(base, "DELETE", "/api/me", cookie=c)[1] == {"deleted": True}
    assert call(base, "GET", "/api/export", cookie=c)[1]["holdings"] == []


def test_remove_holding_and_watch(base):
    c = new_user(base)
    call(base, "POST", "/api/holdings", {"symbol": "TCS", "qty": 1, "avg_price": 1}, c)
    call(base, "POST", "/api/watchlist", {"symbol": "SBIN"}, c)
    me = call(base, "DELETE", "/api/holdings?sym=TCS", cookie=c)[1]
    assert me["holdings"] == [] and me["watchlist"][0]["symbol"] == "SBIN"
    assert call(base, "DELETE", "/api/watchlist?sym=SBIN", cookie=c)[1]["watchlist"] == []


def test_static_files_and_page_links(base):
    assert b"portfolio" in urllib.request.urlopen(base + "/modules/portfolio/portfolio.js").read().lower()
    assert urllib.request.urlopen(base + "/assets/css/components.css").status == 200
    assert b"/modules/portfolio/portfolio.js" in urllib.request.urlopen(base + "/portfolio.html").read()


def test_malformed_cookie_gets_fresh_user(base):
    code, me, h = call(base, "GET", "/api/me", cookie="uid=../../etc")
    assert code == 200 and "Set-Cookie" in h


def test_session_endpoint_hands_out_the_identity_cookie_once(base):
    code, obj, h = call(base, "GET", "/api/session")
    assert code == 200 and obj == {"ok": True} and "uid=" in h.get("Set-Cookie", "") and "HttpOnly" in h["Set-Cookie"]
    uid = h["Set-Cookie"].split(";")[0]
    code, obj, h2 = call(base, "GET", "/api/session", cookie=uid)
    assert code == 200 and "Set-Cookie" not in h2          # a browser that already has an identity keeps it
