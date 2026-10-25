import datetime, os, sys, time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import refresh_job, server

IST = server.IST
H = server.SCAN_HOUR          # the refresh hour comes from the code, so changing it needs no test edit


def last_friday(today=None):
    """The most recent Friday before today. The dates below are built from it, so nothing is a fixed calendar date; the weekday rules
    (weekends are skipped) only need known weekdays, and these are computed."""
    d = today or datetime.date.today()
    return d - datetime.timedelta(days=(d.weekday() - 4) % 7 or 7)


DAY = datetime.timedelta(days=1)
FRI = last_friday()
THU, SAT, MON = FRI - DAY, FRI + DAY, FRI + 3 * DAY
ASOF = FRI.isoformat()        # the date of the newest price bar in the canned scans


def at(day, h, mi=0):
    return datetime.datetime(day.year, day.month, day.day, h, mi, tzinfo=IST)


def cutoff(day):
    return at(day, H)


@pytest.fixture(autouse=True)
def weekdays_only(monkeypatch):
    monkeypatch.setattr(server, "is_td", lambda d: d.weekday() < 5)   # no holidays: keeps the dates below exact
    monkeypatch.setattr(server, "_last_auto", [0.0])


def test_cutoff_is_the_last_refresh_hour_of_a_trading_day():
    assert server.last_cutoff(cutoff(FRI)) == cutoff(FRI)                                    # Friday, right at the refresh time
    assert server.last_cutoff(cutoff(FRI) - datetime.timedelta(minutes=1)) == cutoff(THU)   # a minute before: yesterday's
    assert server.last_cutoff(at(SAT, 12)) == cutoff(FRI)                                    # Saturday: Friday's
    assert server.last_cutoff(cutoff(MON) - datetime.timedelta(minutes=1)) == cutoff(FRI)   # Monday, a minute before its refresh: still Friday's


@pytest.mark.parametrize("hour", range(24))
def test_cutoff_switches_exactly_at_the_refresh_hour(hour):
    expected = cutoff(FRI) if hour >= H else cutoff(THU)
    assert server.last_cutoff(at(FRI, hour, 30)) == expected


def test_holiday_moves_the_cutoff_back(monkeypatch):
    monkeypatch.setattr(server, "is_td", lambda d: d.weekday() < 5 and d != THU)
    assert server.last_cutoff(at(THU, H, 30)) == cutoff(THU - DAY)                          # Thursday is a holiday: Wednesday's


def test_scan_is_current_only_if_made_after_the_cutoff():
    now = cutoff(FRI) + datetime.timedelta(minutes=30)
    assert server.scan_is_current((cutoff(FRI) + datetime.timedelta(minutes=5)).timestamp(), now)
    assert not server.scan_is_current((cutoff(FRI) - datetime.timedelta(minutes=5)).timestamp(), now)   # made before the refresh time: stale


class Ticks:
    """A stop event whose wait() returns False for the first n calls (n scheduler ticks), then True."""
    def __init__(self, n):
        self.n = n

    def wait(self, _):
        self.n -= 1
        return self.n < 0


@pytest.fixture
def watch(monkeypatch):
    started = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: started.append(1))
    monkeypatch.setattr(server, "load_scan", lambda: False)
    server.STATE.update(running=False)
    return started


def test_scan_watch_starts_the_refresh_when_the_scan_is_stale(watch, monkeypatch):
    monkeypatch.setattr(server, "scan_up_to_date", lambda: False)
    server.scan_watch(Ticks(1))
    assert watch == [1]


def test_scan_watch_does_not_hammer_a_failing_scan(watch, monkeypatch):
    monkeypatch.setattr(server, "scan_up_to_date", lambda: False)
    server.scan_watch(Ticks(5))                                  # five ticks inside one retry pause: one start
    assert watch == [1]


def test_scan_watch_starts_nothing_when_up_to_date_or_already_running(watch, monkeypatch):
    monkeypatch.setattr(server, "scan_up_to_date", lambda: True)
    server.scan_watch(Ticks(3))
    monkeypatch.setattr(server, "scan_up_to_date", lambda: False)
    server.STATE.update(running=True)
    server.scan_watch(Ticks(3))
    server.STATE.update(running=False)
    assert watch == []


def test_scan_watch_survives_an_error(watch, monkeypatch):
    def boom():
        raise OSError("db down")
    monkeypatch.setattr(server, "load_scan", boom)
    server.scan_watch(Ticks(2))                                  # must not raise
    assert watch == []


def test_saved_scan_round_trips_and_older_memory_is_replaced(monkeypatch):
    data = {"generated": "x", "v": server.SCAN_VERSION, "quotes": {}, "stocks": [{"symbol": "TCS", "asof": ASOF}]}
    monkeypatch.setattr(server, "DETAIL", {"TCS": {"why": [["up", "ok"]]}})
    server.STATE.update(t=1000.0, data=data)
    server.save_scan()
    server.DETAIL.clear()
    server.STATE.update(t=0, data=None)
    assert server.load_scan()
    assert server.STATE["data"] == data and server.STATE["t"] == 1000.0 and server.DETAIL["TCS"]["why"]
    assert not server.load_scan()            # nothing newer on disk
    server.STATE.update(data=None, t=0)


def test_corrupt_saved_scan_is_ignored(tmp_path):
    open(server.scan_file(), "wb").write(b"not a pickle")
    server.STATE.update(t=0, data=None)
    assert not server.load_scan()


def test_api_scan_serves_a_current_saved_scan_without_rescanning(monkeypatch):
    started = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: started.append(force))
    data = {"generated": "x", "v": server.SCAN_VERSION, "stocks": [{"symbol": "TCS", "asof": ASOF}]}
    server.STATE.update(t=time.time(), data=data, running=False, error=None)
    monkeypatch.setattr(server, "scan_is_current", lambda t, now=None: True)
    assert server.api_scan(False)["status"] == "ready" and started == []
    server.STATE.update(data=None, t=0)


def test_stale_scan_is_shown_and_refreshed_once_then_backs_off(monkeypatch):
    started = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: started.append(force))
    data = {"generated": "x", "stocks": [{"symbol": "TCS", "asof": ASOF}]}
    server.STATE.update(t=1.0, data=data, running=False, error=None)
    monkeypatch.setattr(server, "scan_is_current", lambda t, now=None: False)
    assert server.api_scan(False)["status"] == "ready"      # old data is still shown straight away
    server.api_scan(False)
    assert started == [False]                               # a failing refresh is not hammered on every poll
    server.STATE.update(data=None, t=0)


def test_horizons_include_short_ones_and_one_month_index():
    assert list(server.HORIZONS)[:3] == ["1d", "2d", "5d"] and server.HORIZONS["3m"] == 60
    assert list(server.HORIZONS)[server.HZ_1M] == "1m"
    assert set(server.HORIZONS) == set(server.api_me.HZ_KEYS)


# ---------- the 4 pm job ----------
@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh_job, "LOG", str(tmp_path / "refresh.log"))
    monkeypatch.setattr(server, "refresh_holidays", lambda: None)
    monkeypatch.setattr(server, "is_td", lambda d: True)   # whatever day the suite runs on
    monkeypatch.setattr(refresh_job.time, "sleep", lambda s: None)
    calls = []

    def run(newest, error=None):
        def fake(force):
            calls.append(force)
            server.STATE.update(error=error, data={"stocks": [{"asof": newest}]})
        monkeypatch.setattr(server, "run_scan", fake)
        return calls
    return run, lambda: open(refresh_job.LOG, encoding="utf-8").read()


def test_job_skips_a_non_trading_day(job, monkeypatch):
    run, log = job
    calls = run(ASOF)
    monkeypatch.setattr(server, "is_td", lambda d: False)
    assert refresh_job.main() == 0 and calls == [] and "not a trading day" in log()


def test_job_forces_a_fresh_download_and_logs_success(job):
    run, log = job
    calls = run(datetime.date.today().isoformat())
    assert refresh_job.main() == 0 and calls == [True] and "ok:" in log()


def test_job_retries_until_todays_prices_exist_then_gives_up(job):
    run, log = job
    calls = run("2000-01-03")
    assert refresh_job.main() == 1 and calls == [True] * 3
    assert log().count("not published yet") == 3 and "gave up" in log()


def test_job_logs_a_failed_scan(job):
    run, log = job
    run("2000-01-03", error="URLError: down")
    assert refresh_job.main() == 1 and "scan failed: URLError: down" in log()


# ---------- Refresh data: instant when nothing newer can exist, explained, and rebuilt when the saved scan is from older code ----------
def _current(monkeypatch, v=None, **extra):
    started = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: started.append(force))
    monkeypatch.setattr(server, "scan_is_current", lambda t, now=None: True)
    monkeypatch.setattr(server, "force_allowed", lambda: True)
    data = {"generated": "x", "v": server.SCAN_VERSION if v is None else v, "stocks": [{"symbol": "TCS", "asof": ASOF}], "quotes": {}, **extra}
    server.STATE.update(t=time.time(), data=data, running=False, error=None, phase="", done=0, total=1)
    return started


def test_refresh_of_data_from_the_latest_close_answers_at_once_without_a_scan(monkeypatch):
    started = _current(monkeypatch)
    out = server.api_scan(True)
    assert out["status"] == "ready" and out["upToDate"] is True and out["refreshing"] is False and started == []
    assert server.api_scan(False)["upToDate"] is False             # a plain page load never claims it
    server.STATE.update(data=None, t=0)


def test_full_refresh_still_re_downloads_even_when_up_to_date(monkeypatch):
    started = _current(monkeypatch)
    out = server.api_scan("full")
    assert started == ["full"] and out["upToDate"] is False
    server.STATE.update(data=None, t=0)


def test_refresh_after_a_new_close_starts_a_scan(monkeypatch):
    started = _current(monkeypatch)
    monkeypatch.setattr(server, "scan_is_current", lambda t, now=None: False)     # a market close has passed since this scan
    assert server.api_scan(True)["upToDate"] is False and started == [True]
    server.STATE.update(data=None, t=0)


def test_scan_saved_by_older_code_is_rebuilt_once_and_never_called_up_to_date(monkeypatch):
    started = _current(monkeypatch, v=1)
    monkeypatch.setattr(server, "_last_auto", [0.0])
    out = server.api_scan(False)
    assert out["status"] == "ready" and started == [False]          # still served at once, rebuilt in the background
    started.clear()
    assert server.api_scan(True)["upToDate"] is False and started == [True]
    server.STATE.update(data=None, t=0)


def test_progress_is_reported_while_a_scan_runs(monkeypatch):
    _current(monkeypatch)
    server.STATE.update(running=True, phase="Downloading 5 years of prices", done=1240, total=2734)
    out = server.api_scan(False)
    assert out["refreshing"] is True and out["progress"] == {"phase": "Downloading 5 years of prices", "done": 1240, "total": 2734}
    assert server.api_scan(True)["upToDate"] is False              # a scan is already running: no "up to date" claim
    server.STATE.update(running=False, data=None, t=0)


def test_cache_is_reused_by_a_plain_refresh_and_dropped_only_when_outdated_or_full(tmp_path, monkeypatch):
    f = tmp_path / "rows.pkl"
    f.write_bytes(b"x")
    cutoff = datetime.datetime.fromtimestamp(os.path.getmtime(f) - 3600, server.IST)          # the latest close was an hour before the download
    monkeypatch.setattr(server, "last_cutoff", lambda now=None: cutoff)
    assert server.cache_outdated(str(f), False) is False and server.cache_outdated(str(f), True) is False
    assert server.cache_outdated(str(f), "full") is True
    monkeypatch.setattr(server, "last_cutoff", lambda now=None: cutoff + datetime.timedelta(hours=2))   # a close happened after the download
    assert server.cache_outdated(str(f), False) is True
    assert server.cache_outdated(str(tmp_path / "missing.pkl"), "full") is False


def test_quotes_are_rebuilt_from_the_saved_download_for_a_scan_that_lacks_them(tmp_path, monkeypatch):
    import pickle
    today = datetime.date.today()
    def rows(price, n=400, last=today):
        return [(last - datetime.timedelta(days=n - i), price, price, price, price, 1000) for i in range(n)]
    cache = tmp_path / "cache"
    cache.mkdir()
    pickle.dump({"^NSEI": rows(20000), "TCS": rows(4000), "SBL": rows(1.55, n=300), "OLD": rows(9, last=today - datetime.timedelta(days=30))},
                open(cache / f"rows-{today.isoformat()}.pkl", "wb"))
    monkeypatch.setattr(server, "CACHE_DIR", str(cache))
    data = {"stocks": [{"symbol": "TCS"}]}
    server.backfill_quotes(data)
    assert set(data["quotes"]) == {"SBL"}                           # TCS is scanned, OLD is stale, the index is not a stock
    assert data["quotes"]["SBL"]["price"] == 1.55 and data["quotes"]["SBL"]["why"] in ("thin", "illiquid")
    keep = {"SBL": {"price": 2.0}}
    d2 = {"stocks": [], "quotes": keep}
    server.backfill_quotes(d2)
    assert d2["quotes"] is keep                                      # a scan that already has quotes is left alone
    monkeypatch.setattr(server, "CACHE_DIR", str(tmp_path / "nothing"))
    d3 = {"stocks": []}
    server.backfill_quotes(d3)
    assert d3["quotes"] == {}                                        # no download saved: empty, never an error
