import datetime, json, os, sys, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server


@pytest.fixture
def srv(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: calls.append(force))
    monkeypatch.setitem(server.STATE, "data", None)
    monkeypatch.setitem(server.STATE, "running", True)   # no auto-scan path
    monkeypatch.setattr(server, "_last_force", [0.0])
    monkeypatch.setitem(server.DETAIL, "TCS", {"why": []})
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", calls
    s.shutdown()
    s.server_close()


def get(url, method="GET"):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method=method))
    except urllib.error.HTTPError as e:
        r = e
    return r.status, dict(r.headers), r.read()


def test_health_get_and_head_never_scan(srv):
    base, calls = srv
    st, h, body = get(base + "/health")
    assert st == 200 and json.loads(body) == {"ok": True, "dataAsOf": None, "scanAgeMinutes": None}
    st, h, body = get(base + "/health", "HEAD")
    assert st == 200 and body == b""
    assert calls == []


def test_health_reports_data_age(monkeypatch):
    monkeypatch.setitem(server.STATE, "data", {"stocks": [{"asof": "2026-10-22"}, {"asof": "2026-10-23"}]})
    monkeypatch.setitem(server.STATE, "t", time.time() - 600)
    assert server.health() == {"ok": True, "dataAsOf": "2026-10-23", "scanAgeMinutes": 10}


@pytest.mark.parametrize("sym", ["a b", "tcs", "X" * 21, "T;S", "%3Cscript%3E"])
def test_bad_sym_is_400(srv, sym):
    st, _, body = get(srv[0] + "/api/stock?sym=" + sym.replace(" ", "%20"))
    assert st == 400 and "error" in json.loads(body)


def test_good_sym_and_unknown(srv):
    assert get(srv[0] + "/api/stock?sym=TCS")[0] == 200
    assert get(srv[0] + "/api/stock?sym=NOPE")[0] == 404


def test_security_headers_on_every_response(srv):
    for path in ("/health", "/", "/api/stock?sym=bad!", "/nothing"):
        st, h, _ = get(srv[0] + path)
        assert h["X-Content-Type-Options"] == "nosniff" and h["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]


def test_head_page(srv):
    st, h, body = get(srv[0] + "/", "HEAD")
    assert st == 200 and body == b"" and int(h["Content-Length"]) > 1000


def test_force_scan_rate_limited(srv):
    base, calls = srv
    get(base + "/api/scan?force")
    get(base + "/api/scan?force")
    assert calls == [True]   # second forced request within 60s does not force


def test_baseline_from():
    fc = {"1m": {"p10": -.1, "p25": 0, "p50": .02, "p75": 0, "p90": .1, "pgain": .6, "n": 500}}
    assert server.baseline_from([{"symbol": "TCS", "forecast": fc}]) == {}
    out = server.baseline_from([{"symbol": "NIFTYBEES", "forecast": fc}])
    assert out == {"1m": {"p50": .02, "p10": -.1, "p90": .1, "pgain": .6}}


def test_fetch_date_is_ist(monkeypatch):
    # 2026-10-23 19:00 UTC is already 24 Oct in IST
    ts = int(datetime.datetime(2026, 10, 23, 19, 0, tzinfo=datetime.timezone.utc).timestamp())
    payload = {"chart": {"result": [{"timestamp": [ts], "indicators": {
        "quote": [{"close": [1.0], "high": [1.0], "low": [1.0], "volume": [5]}], "adjclose": [{"adjclose": [1.0]}]}}]}}
    monkeypatch.setattr(server, "get_json", lambda url: payload)
    assert server.fetch("TCS")[1][0][0] == datetime.date(2026, 10, 24)
