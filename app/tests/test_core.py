import datetime, json, os, sys, threading, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

D = datetime.date


def make_rows(n=400, start=100.0, daily=0.001, volume=1_000_000, end=D(2026, 10, 23)):
    """Fixed synthetic price history, oldest first: (date, high, low, close, adjclose, volume)."""
    rows, p = [], start
    d = end - datetime.timedelta(days=n * 2)
    while len(rows) < n:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            p *= 1 + daily
            rows.append((d, p * 1.01, p * 0.99, p, p, volume))
    return rows


def test_first_td_from_skips_weekend():
    assert server.first_td_from(D(2026, 10, 24)) == D(2026, 10, 26)   # Saturday -> Monday


def test_first_td_from_trading_day_is_unchanged():
    assert server.first_td_from(D(2026, 10, 23)) == D(2026, 10, 23)


def test_add_td_ten_days_counts_only_trading_days():
    assert server.add_td(D(2026, 10, 23), 10) == D(2026, 11, 6)   # two full weeks, no holiday in between


def test_add_td_skips_diwali_holiday():
    assert server.add_td(D(2026, 11, 9), 1) == D(2026, 11, 11)   # 10 Nov is a listed holiday


def test_passes_quality_ok():
    assert server.passes_quality(make_rows()) is None


def test_passes_quality_too_little_history():
    assert server.passes_quality(make_rows(n=100)) == "thin"


def test_passes_quality_too_cheap():
    assert server.passes_quality(make_rows(start=5.0, daily=0)) == "thin"


def test_passes_quality_illiquid():
    assert server.passes_quality(make_rows(volume=10)) == "illiquid"


def test_passes_quality_suspect_jump():
    rows = make_rows()
    r = rows[-100]
    rows[-100] = r[:4] + (r[4] * 1.5,) + r[5:]
    assert server.passes_quality(rows) == "suspect"


def test_score_rises_with_trend():
    def score(daily):
        c, pre, nif = server.prep(make_rows(daily=daily), None)
        return server.score_at(c, pre, nif, len(c) - 1)
    assert score(0.002) > score(0.0) > score(-0.002)


def test_score_is_bounded():
    c, pre, nif = server.prep(make_rows(daily=0.01), None)
    assert 0 <= server.score_at(c, pre, nif, len(c) - 1) <= 100


def stock(score, ext=0.0, rsi=50, pgain=0.7, net=0):
    return {"score": score, "ext": ext, "rsi": rsi, "sma20": 100.0, "forecast": {"1m": {"pgain": pgain}},
            "news": [{"tone": net}]}


def verdict(s):
    server.decide(s, D(2026, 10, 24), 0.56)
    return s["verdict"]


def test_decide_buy():
    assert verdict(stock(60)) == "BUY"


def test_decide_wait_when_stretched():
    assert verdict(stock(60, ext=0.1)) == "WAIT"
    assert verdict(stock(60, rsi=80)) == "WAIT"


def test_decide_wait_on_bad_news():
    assert verdict(stock(60, net=-2)) == "WAIT"


def test_decide_good_news_cannot_upgrade():
    assert verdict(stock(30, net=3)) == "WATCH"


def test_decide_needs_to_beat_base_rate():
    assert verdict(stock(60, pgain=0.57)) == "WATCH"   # 0.57 < base 0.56 + 0.02


def test_decide_downtrend():
    assert verdict(stock(5)) == "DOWNTREND"


def test_forecast_quantiles_ordered():
    data = {"A": make_rows(daily=0.001), "B": make_rows(daily=-0.0005, start=200)}
    pool, scores = server.build_pool(data, None)
    out = server.Forecaster(pool, scores)(50, 0.02)
    for h in out.values():
        assert h["p10"] <= h["p25"] <= h["p50"] <= h["p75"] <= h["p90"]
        assert 0 <= h["pgain"] <= 1


@pytest.fixture
def live_server():
    server.STATE.update(t=time_now(), running=False, error=None, data={"generated": "test", "stocks": [], "buyDate": "2026-10-26"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    server.STATE.update(data=None, t=0)


def time_now():
    import time
    return time.time()


def test_smoke_api_scan_serves_canned_data(live_server):
    d = json.load(urllib.request.urlopen(live_server + "/api/scan", timeout=5))
    assert d["status"] == "ready" and d["buyDate"] == "2026-10-26"


def test_smoke_index_page(live_server):
    body = urllib.request.urlopen(live_server + "/", timeout=5).read()
    assert b"<html" in body.lower()
