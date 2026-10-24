import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import fundamentals as F

NOW = datetime.datetime(2026, 10, 24, 12, 0)


def ts_doc(**series):
    res = []
    for t, rows in series.items():
        res.append({"meta": {"type": [t]}, t: [{"asOfDate": e, "periodType": p, "reportedValue": {"raw": v}} for e, p, v in rows]})
    return {"timeseries": {"result": res}}


def chart_doc(closes, divs=(), splits=()):
    base = int(datetime.datetime(2026, 1, 1, 4, tzinfo=datetime.timezone.utc).timestamp())
    ts = [base + i * 86400 for i in range(len(closes))]
    ev = {}
    if divs:
        ev["dividends"] = {str(i): {"amount": a, "date": int(datetime.datetime.fromisoformat(d + "T04:00:00+00:00").timestamp())} for i, (d, a) in enumerate(divs)}
    if splits:
        ev["splits"] = {"1": {"date": int(datetime.datetime.fromisoformat(splits[0][0] + "T04:00:00+00:00").timestamp()), "splitRatio": splits[0][1]}}
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": closes}]}, "events": ev}]}}


GOOD = ts_doc(quarterlyTotalRevenue=[("2026-03-31", "3M", 1000.0), ("2025-12-31", "3M", 900.0), ("2026-06-30", "3M", 1100.0)],
              quarterlyNetIncome=[("2025-12-31", "3M", 90.0), ("2026-03-31", "3M", 100.0), ("2026-06-30", "3M", 110.0)],
              quarterlyDilutedEPS=[("2026-06-30", "3M", 1.1)], annualDilutedEPS=[("2025-03-31", "12M", 4.0), ("2026-03-31", "12M", 5.0)],
              quarterlyTotalDebt=[("2026-03-31", "3M", 50.0), ("2025-03-31", "3M", 40.0)])


def test_normalize_sorts_quarters_and_keeps_gaps_as_none():
    f = F.normalize(GOOD, chart_doc([10.0, None, 12.0], divs=[("2026-01-02", 6.0)], splits=[("2026-01-03", "2:1")]), "TCS")
    assert f["status"] == "ok" and [q["end"] for q in f["quarters"]] == ["2025-12-31", "2026-03-31", "2026-06-30"]
    assert f["quarters"][0]["eps"] is None and f["quarters"][2]["eps"] == 1.1 and f["quarters"][0]["operating_income"] is None
    assert [a["eps"] for a in f["annual"]] == [4.0, 5.0] and [d["value"] for d in f["debt"]] == [40.0, 50.0]
    assert f["closes"]["c"] == [10.0, 12.0] and len(f["closes"]["d"]) == 2           # a missing close is dropped, not invented
    assert f["dividends"] == [{"date": "2026-01-02", "amount": 6.0}] and f["splits"][0]["text"] == "2:1"


def test_normalize_with_nothing_is_none_with_a_reason():
    f = F.normalize({"timeseries": {"result": []}}, None, "TATSILV")
    assert f["status"] == "none" and "no company results" in f["reason"] and f["quarters"] == [] and f["closes"] == {"d": [], "c": []}
    assert F.normalize(None, None, "X")["status"] == "none"


def test_normalize_ignores_non_quarterly_periods_and_missing_values():
    doc = ts_doc(quarterlyNetIncome=[("2026-03-31", "12M", 5.0), ("2026-06-30", "3M", None)])
    assert F.normalize(doc, None, "X")["status"] == "none"


def test_yahoo_symbols():
    assert F.yahoo_symbol("TCS", "NSE") == "TCS.NS" and F.yahoo_symbol("ABC", "BSE") == "ABC.BO"


def fake_getter(calls, ts=GOOD, chart=None):
    def g(url):
        calls.append(url)
        return chart_doc([10.0, 11.0]) if "v8/finance/chart" in url and chart is None else (chart if "v8/finance/chart" in url else ts)
    return g


def test_get_facts_caches_for_a_day(tmp_path):
    calls = []
    a = F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW, getter=fake_getter(calls))
    assert a["status"] == "ok" and a["fetched"] == "2026-10-24" and len(calls) == 2
    assert os.path.exists(tmp_path / "fund-TCS.json")
    b = F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW + datetime.timedelta(hours=5), getter=fake_getter(calls))
    assert b == a and len(calls) == 2                                           # served from the cache
    F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW + datetime.timedelta(hours=30), getter=fake_getter(calls))
    assert len(calls) == 4                                                      # a day later it looks again


def test_a_failed_refresh_falls_back_to_the_last_good_copy_and_says_so(tmp_path):
    F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW, getter=fake_getter([]))

    def boom(url):
        raise OSError("offline")
    f = F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW + datetime.timedelta(days=2), getter=boom)
    assert f["status"] == "stale" and "Could not refresh" in f["reason"] and "2026-10-24" in f["reason"] and f["quarters"]


def test_a_failure_with_no_cache_is_an_error_not_an_invention(tmp_path):
    def boom(url):
        raise OSError("offline")
    f = F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW, getter=boom)
    assert f["status"] == "error" and f["quarters"] == [] and "Could not reach" in f["reason"]


def test_etfs_are_not_looked_up_at_all(tmp_path):
    calls = []
    f = F.get_facts("TATSILV", is_etf=True, cache_dir=str(tmp_path), now=NOW, getter=fake_getter(calls))
    assert f["status"] == "none" and "ETFs and funds" in f["reason"] and calls == []


def test_odd_symbols_are_refused_before_any_request(tmp_path):
    calls = []
    assert F.get_facts("../../x", cache_dir=str(tmp_path), now=NOW, getter=fake_getter(calls))["status"] == "error" and calls == []


def test_chart_failure_alone_keeps_the_results(tmp_path):
    def g(url):
        if "v8/finance/chart" in url:
            raise OSError("chart down")
        return GOOD
    f = F.get_facts("TCS", cache_dir=str(tmp_path), now=NOW, getter=g)
    assert f["status"] == "ok" and f["quarters"] and f["closes"]["d"] == []


def test_get_many_returns_one_entry_per_symbol(tmp_path):
    out = F.get_many([("TCS", "NSE", False), ("TATSILV", "NSE", True)], cache_dir=str(tmp_path), now=NOW, getter=fake_getter([]))
    assert set(out) == {"TCS", "TATSILV"} and out["TCS"]["status"] == "ok" and out["TATSILV"]["status"] == "none"
    assert F.get_many([]) == {}
