import datetime, json, os, pickle, sys, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

D = datetime.date


def canned(asof):
    return {"generated": "test", "stocks": [{"asof": asof}], "buyDate": "2026-10-26"}


@pytest.fixture
def srv():
    server.STATE.update(t=time.time(), running=False, error=None, data=canned("2026-10-23"))
    server.DETAIL.clear()
    server.DETAIL["TCS"] = {"why": []}
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    server.STATE.update(data=None, t=0, error=None)
    server.DETAIL.clear()


def status(url):
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_unknown_path_is_404(srv):
    assert status(srv + "/nope") == 404
    assert status(srv + "/../server.py") == 404


def test_unknown_symbol_is_404_with_error(srv):
    assert status(srv + "/api/stock?sym=NOSUCH") == 404
    assert status(srv + "/api/stock") == 400   # missing sym fails validation (Q8)


def test_known_symbol_ok(srv):
    assert json.load(urllib.request.urlopen(srv + "/api/stock?sym=TCS")) == {"why": []}


def test_stale_since_flags_old_bars():
    today = D(2026, 10, 28)                                  # Wednesday
    assert server.stale_since(D(2026, 10, 27), today) is None   # yesterday's bar is current
    assert server.stale_since(D(2026, 10, 26), today) == "2026-10-27"


def test_stale_since_monday_accepts_friday_bar():
    assert server.stale_since(D(2026, 10, 23), D(2026, 10, 26)) is None


def test_stale_since_skips_holiday():
    # Tue 10 Nov 2026 is a holiday, so on Wed 11 Nov the last session was Mon 9 Nov
    assert server.stale_since(D(2026, 11, 9), D(2026, 11, 11)) is None


def test_failed_refresh_keeps_serving_last_scan(srv):
    server.STATE.update(error="URLError: network down", data=canned("2020-01-01"))
    d = json.load(urllib.request.urlopen(srv + "/api/scan"))
    assert d["status"] == "ready" and d["buyDate"] == "2026-10-26"
    assert d["refreshError"] == "URLError: network down"
    assert d["staleSince"]


def test_older_cache_picks_newest_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CACHE_DIR", str(tmp_path))
    for name, val in (("rows-2026-10-20.pkl", {"A": 1}), ("rows-2026-10-22.pkl", {"B": 2})):
        (tmp_path / name).write_bytes(pickle.dumps(val))
    (tmp_path / "rows-2026-10-23.pkl").write_bytes(b"truncated")
    assert server.older_cache(str(tmp_path / "rows-2026-10-24.pkl")) == {"B": 2}


def test_older_cache_empty_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CACHE_DIR", str(tmp_path))
    assert server.older_cache("x") == {}
