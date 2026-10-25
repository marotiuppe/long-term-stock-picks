"""Anonymous page-view counts: a number per page per day in the database, a token-protected read, nothing that identifies a visitor."""
import datetime, json, os, sys, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core.store import Store

TOKEN = "t" * 40
DAY = datetime.date.today()
TODAY = DAY.isoformat()


@pytest.fixture
def st(monkeypatch):
    s = Store(":memory:")
    monkeypatch.setattr(server, "get_store", lambda: s)
    return s


@pytest.fixture
def srv(st, monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setattr(server, "price_db", lambda: None)
    monkeypatch.setenv("STATS_TOKEN", TOKEN)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def get(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 (X11; Linux) Firefox/130"}, method=method)
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_views_add_up_per_page_and_day(st):
    st.views_add(TODAY, {"/": 2, "/index.html": 1})
    st.views_add(TODAY, {"/": 3})
    st.views_add((DAY - datetime.timedelta(days=1)).isoformat(), {"/": 4})
    s = st.views_summary(TODAY)
    assert s["total"] == 10 and s["today"] == 6
    assert s["byDay"] == [{"day": TODAY, "views": 6}, {"day": (DAY - datetime.timedelta(days=1)).isoformat(), "views": 4}]
    assert s["byPage"][0] == {"path": "/", "views": 9} and s["since"] == (DAY - datetime.timedelta(days=1)).isoformat()


def test_summary_window_limits_days_but_not_the_all_time_total(st):
    old = (DAY - datetime.timedelta(days=90)).isoformat()
    st.views_add(old, {"/": 5})
    st.views_add(TODAY, {"/": 1})
    s = st.views_summary(TODAY, days=30)
    assert s["total"] == 6 and [r["day"] for r in s["byDay"]] == [TODAY] and s["byPage"] == [{"path": "/", "views": 1}]


def test_empty_database_gives_zeros(st):
    assert st.views_summary(TODAY) == {"total": 0, "since": None, "today": 0, "days": 30, "byDay": [], "byPage": []}


def test_bots_and_health_checkers_are_not_counted():
    for ua in ("Googlebot/2.1", "UptimeRobot/2.0", "curl/8.4", "python-requests/2.31", "HeadlessChrome/120", "stockpicks-keepalive (monitor)", ""):
        server.count_view("/", ua) if ua else None
    assert server._views == {}
    server.count_view("/", "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36")
    assert server._views == {"/": 1}


def test_flush_writes_the_batch_and_keeps_it_if_the_database_fails(st, monkeypatch):
    server.count_view("/", "Mozilla/5.0")
    server.count_view("/", "Mozilla/5.0")
    server.count_view("/about.html", "Mozilla/5.0")
    assert server.flush_views(TODAY) == 2 and server._views == {}
    assert st.views_summary(TODAY)["total"] == 3
    server.count_view("/", "Mozilla/5.0")
    monkeypatch.setattr(Store, "views_add", lambda self, d, c: (_ for _ in ()).throw(OSError("db down")))
    assert server.flush_views(TODAY) == 0 and server._views == {"/": 1}          # not lost: tried again next time


def test_pages_are_counted_but_assets_api_head_and_missing_pages_are_not(srv):
    assert get(srv + "/")[0] == 200 and get(srv + "/index.html")[0] == 200 and get(srv + "/privacy.html")[0] == 200
    get(srv + "/assets/css/tokens.css"); get(srv + "/api/scan"); get(srv + "/health"); get(srv + "/nothing-here")
    get(srv + "/index.html", method="HEAD")
    get(srv + "/index.html", headers={"User-Agent": "Googlebot/2.1"})
    assert server._views == {"/": 1, "/index.html": 1, "/privacy.html": 1}


def test_stats_are_off_without_a_token_and_hidden_from_a_wrong_one(srv, monkeypatch):
    assert get(srv + "/api/stats")[0] == 404
    assert get(srv + "/api/stats", {"Authorization": "Bearer nope"})[0] == 404
    assert get(srv + "/api/stats", {"Authorization": TOKEN})[0] == 404                 # needs the Bearer word
    monkeypatch.delenv("STATS_TOKEN")
    assert get(srv + "/api/stats", {"Authorization": "Bearer " + TOKEN})[0] == 404     # switched off: even the right word does nothing
    assert get(srv + "/api/stats", {"Authorization": "Bearer "})[0] == 404
    assert get(srv + "/stats.html")[0] == 404


def test_stats_with_the_token_include_views_not_yet_written(srv):
    get(srv + "/"); get(srv + "/")
    code, body = get(srv + "/api/stats", {"Authorization": "Bearer " + TOKEN})
    d = json.loads(body)
    assert code == 200 and d["today"] == 2 and d["total"] == 2 and d["byPage"] == [{"path": "/", "views": 2}]


def test_stats_page_is_served_with_the_token_set_and_not_indexed(srv):
    code, body = get(srv + "/stats.html")
    t = body.decode()
    assert code == 200 and 'name="robots" content="noindex,nofollow"' in t and "/modules/stats/stats.js" in t
    for ref in ("/modules/stats/stats.js", "/modules/stats/stats.css"):
        assert get(srv + ref)[0] == 200


def test_the_privacy_policy_says_page_views_are_counted_anonymously(srv):
    t = get(srv + "/privacy.html")[1].decode()
    assert "counter for that page and that day" in t and "no IP address, cookie ID or anything about you" in t
    assert "Counting page views uses no cookie" in get(srv + "/cookies.html")[1].decode()
