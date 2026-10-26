"""The live check wired into the real scan: one scan saves the forecasts, the next scan (a day later) settles them against the new day's close."""
import datetime, os, random, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core import livecheck
from core.store import Store
from modules.stocks import bhavcopy, lists

DAY = datetime.timedelta(days=1)


def weekday_before(d):
    d -= DAY
    while d.weekday() >= 5:
        d -= DAY
    return d


D2 = weekday_before(datetime.date.today())        # the newest bar of the second scan: a finished day
D1 = weekday_before(D2)                           # the newest bar of the first scan
N_BARS, SYMBOLS = 420, ["S%02d" % i for i in range(30)]


def series(sym):
    """A reproducible price path of weekday bars ending on D2: [(date, close)], oldest first. The last step is a different size for each symbol."""
    rng = random.Random(sym)
    dates, d = [], D2
    while len(dates) < N_BARS:
        if d.weekday() < 5:
            dates.append(d)
        d -= DAY
    dates.reverse()
    px, out = 100.0 + rng.random() * 400, []
    for i, day in enumerate(dates):
        px *= 1 + (rng.gauss(0.0004, 0.012) if i < len(dates) - 1 else rng.gauss(0, 0.03))
        out.append((day, round(px, 2)))
    return out


def bars_until(sym, last):
    return [(d, c * 1.01, c * 0.99, c, c, 2_000_000) for d, c in series(sym) if d <= last]


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = Store(":memory:")
    monkeypatch.setattr(server, "_store", st)
    monkeypatch.setattr(server, "price_db", lambda: None)
    monkeypatch.setattr(server, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "is_td", lambda d: d.weekday() < 5)
    monkeypatch.setattr(server, "save_scan", lambda: None)
    monkeypatch.setattr(server, "news", lambda *a, **k: [])
    monkeypatch.setattr(server, "load_universe", lambda: {s: s + " Ltd" for s in SYMBOLS})
    monkeypatch.setattr(bhavcopy, "auto_lists", lambda *a, **k: {})
    monkeypatch.setattr(lists, "load", lambda: {})
    last = {"d": D1}

    def fake_fetch(sym, suffix=".NS", yahoo=None):
        return sym, bars_until("S00" if sym == "^NSEI" else sym, last["d"])
    monkeypatch.setattr(server, "fetch", fake_fetch)

    def scan(until):
        last["d"] = until
        server.STATE.update(running=False, error=None, data=None)
        server.run_scan("full")
        assert server.STATE["error"] is None, server.STATE["error"]
        return server.STATE["data"]
    return st, scan


def test_the_first_scan_saves_the_forecasts_and_nothing_is_checked_yet(world):
    st, scan = world
    data = scan(D1)
    n = len(data["stocks"])
    assert n >= 20
    rows = st._all("SELECT hz, target, asof FROM forecast_log")
    assert len(rows) == n * len(livecheck.TRACKED) and {r["asof"] for r in rows} == {D1.isoformat()}
    assert {r["hz"]: r["target"] for r in rows}["1d"] == D2.isoformat()                  # tomorrow's close is the next bar
    assert st.fc_stats() == [] and st.fc_counts() == {hz: n for hz in livecheck.TRACKED}


def test_the_next_scan_checks_yesterdays_forecast_against_the_new_close(world):
    st, scan = world
    first = scan(D1)
    saved = {r["symbol"]: r for r in st._all("SELECT symbol, price, p10, p90 FROM forecast_log WHERE asof=? AND hz='1d'", (D1.isoformat(),))}
    second = scan(D2)
    # worked out here from the same price paths, not from the code under test
    close2 = {s: dict(series(s))[D2] for s in saved}
    inside = sum(1 for s, r in saved.items() if r["price"] * (1 + r["p10"]) <= close2[s] <= r["price"] * (1 + r["p90"]))
    rose = sum(1 for s, r in saved.items() if close2[s] > r["price"])
    day = [r for r in st.fc_stats() if r["asof"] == D1.isoformat() and r["hz"] == "1d" and r["grp"] == "all"]
    assert len(day) == 1 and day[0]["n"] == len(saved) == len(first["stocks"])
    assert (day[0]["inside"], day[0]["rose"]) == (inside, rose)
    assert day[0]["sum_change"] == pytest.approx(sum(close2[s] / r["price"] - 1 for s, r in saved.items()))
    assert 0 <= inside <= day[0]["n"] and 0 < rose < day[0]["n"]                         # a real mix, not all or nothing
    # the longer periods are still waiting, and the second scan saved its own forecasts
    assert st.fc_counts()["5d"] == len(first["stocks"]) + len(second["stocks"]) and "1d" in st.fc_counts()
    page = livecheck.summarize(st.fc_stats(), st.fc_counts())["horizons"][0]
    assert page["n"] == len(saved) and page["days"] == 1 and page["note"].startswith("Too early to tell")


def test_a_scan_before_the_days_close_saves_nothing_and_a_broken_store_never_fails_the_scan(world, monkeypatch):
    st, scan = world
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    monkeypatch.setattr(livecheck, "bar_is_final", lambda asof, now: False)                # the bar might still be partial
    scan(D1)
    assert st._all("SELECT COUNT(*) AS n FROM forecast_log")[0]["n"] == 0
    monkeypatch.setattr(livecheck, "bar_is_final", lambda asof, now: True)
    monkeypatch.setattr(Store, "fc_record", lambda self, rows: (_ for _ in ()).throw(OSError("database down")))
    assert scan(D1)["stocks"]                                                              # the scan still finishes
    monkeypatch.setattr(Store, "fc_pending", lambda self, upto: (_ for _ in ()).throw(OSError("database down")))
    assert scan(D2)["stocks"]


def test_old_data_reused_after_a_failed_download_is_not_saved_as_a_forecast(world, monkeypatch):
    st, scan = world
    scan(D1)
    st._run("DELETE FROM forecast_log")
    monkeypatch.setattr(server, "fetch", lambda sym, *a, **k: (sym, None))                 # Yahoo is down: the scan falls back to the saved prices
    monkeypatch.setattr(server, "older_cache", lambda cpath: {s: bars_until(s if s != "^NSEI" else "S00", D1) for s in SYMBOLS + ["^NSEI"]})
    server.STATE.update(running=False, error=None, data=None)
    server.run_scan("full")
    assert server.STATE["data"] and st._all("SELECT COUNT(*) AS n FROM forecast_log")[0]["n"] == 0


def test_the_live_check_endpoint_serves_the_summary(world):
    import json, threading, urllib.request
    from http.server import ThreadingHTTPServer
    st, scan = world
    scan(D1); scan(D2)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{s.server_port}/api/live-check"))
    finally:
        s.shutdown()
    assert [h["hz"] for h in d["horizons"]] == list(livecheck.TRACKED) and d["horizons"][0]["n"] > 0 and d["expectedInside"] == 0.8
    assert d["horizons"][0]["daily"][0]["asof"] == D1.isoformat()
