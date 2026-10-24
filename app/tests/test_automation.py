"""Things that must happen by themselves while the app runs: the NSE holiday list stays current, and the track-record report is rebuilt."""
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from modules.about import backtest
from test_trackrecord import synth


# ---------- holiday list ----------
def test_holiday_watch_rechecks_while_the_server_stays_up(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "refresh_holidays", lambda: calls.append(time.time()))
    stop = threading.Event()
    t = threading.Thread(target=server.holiday_watch, args=(stop, 0.01), daemon=True)
    t.start()
    time.sleep(0.25)
    stop.set(); t.join(2)
    assert not t.is_alive() and len(calls) >= 3          # keeps checking, and stops when asked


def test_holiday_watch_survives_a_failed_check(monkeypatch):
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("network down")
    monkeypatch.setattr(server, "refresh_holidays", flaky)
    stop = threading.Event()
    t = threading.Thread(target=server.holiday_watch, args=(stop, 0.01), daemon=True)
    t.start(); time.sleep(0.2); stop.set(); t.join(2)
    assert len(calls) >= 2                               # one failure did not end the loop


def test_holiday_watch_does_not_check_before_the_first_wait(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "refresh_holidays", lambda: calls.append(1))
    stop = threading.Event()
    t = threading.Thread(target=server.holiday_watch, args=(stop, 3600), daemon=True)
    t.start(); time.sleep(0.1); stop.set(); t.join(2)
    assert calls == []                                    # start-up already did the first check, before the first scan


def test_server_main_starts_the_watcher():
    src = open(os.path.join(os.path.dirname(__file__), "..", "server.py"), encoding="utf-8").read()
    main = src[src.index('if __name__ == "__main__":'):]
    assert "refresh_holidays()" in main and "holiday_watch" in main and "daemon=True" in main


# ---------- track-record report ----------
def test_report_carries_the_same_numbers_as_the_track_record():
    pool = synth()
    track = server.track_record(pool)
    train, held, cutoff = server.split_pool(pool)
    rep = backtest.format_report(track, 10, len(pool), len(train), len(held), cutoff, server.PURGE_DAYS, "scan of 2026-10-24")
    assert rep.startswith("scan of 2026-10-24: 10 stocks") and "survivorship caveat" in rep and rep.endswith("\n")
    assert track
    for k, t in track.items():
        assert f"[{k}] held-out {t['start']} to {t['end']}" in rep
        assert f"hit rate buy {t['hit']*100:.1f}% vs all {t['all_hit']*100:.1f}%" in rep
        assert f"edge {t['edge']*100:+.1f} pts" in rep
    assert rep.count("not distinguishable from zero") == sum(1 for t in track.values() if t["edge_lo"] <= 0 <= t["edge_hi"])


def test_backtest_module_does_not_import_the_server_at_load():
    code = open(os.path.join(os.path.dirname(__file__), "..", "modules", "about", "backtest.py"), encoding="utf-8").read()
    head = code.split("def main")[0]
    assert "import server" not in head                  # server imports this module, so a top-level import would be circular


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setitem(server.STATE, "running", True)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown(); s.server_close()


def get(url):
    try:
        r = urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, r.headers, r.read()


def test_track_record_route_serves_the_report_and_scan_stays_light(base, monkeypatch):
    monkeypatch.setitem(server.STATE, "data", None)
    assert get(base + "/api/track-record")[0] == 404               # nothing scanned yet
    stock = {"symbol": "ZZ", "asof": "2026-10-23", "verdict": "WATCH", "score": 1, "forecast": {}}
    monkeypatch.setitem(server.STATE, "data", {"stocks": [stock], "trackReport": "scan of x: 1 stocks\n[1m] held-out a to b\n", "track": {}})
    monkeypatch.setitem(server.STATE, "t", time.time())
    st, h, body = get(base + "/api/track-record")
    assert st == 200 and h["Content-Type"].startswith("text/plain") and body.decode().startswith("scan of x")
    st, h, body = get(base + "/api/scan")
    assert st == 200 and b"trackReport" not in body and b'"track"' in body    # the page still gets the numbers, not the long text
