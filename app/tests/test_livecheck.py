"""Live check: nightly forecasts are saved, settled against the real adjusted close, and summed up. Dates are computed, never typed in."""
import datetime, os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import livecheck
from core.store import Store

DAY = datetime.timedelta(days=1)
TODAY = datetime.date.today()
A = TODAY - 40 * DAY                  # a scan date well in the past, so its targets have passed
ASOF = A.isoformat()


def add_td(d, k):
    """Weekdays only: good enough for these tests."""
    while k > 0:
        d += DAY
        if d.weekday() < 5:
            k -= 1
    return d


DAYS = {"1d": 1, "5d": 5, "1m": 20}


def stock(sym, price=100.0, asof=ASOF, verdict="WATCH", p10=-0.04, p50=0.0, p90=0.05, pgain=0.5, horizons=("1d", "5d", "1m")):
    f = {"p10": p10, "p50": p50, "p90": p90, "pgain": pgain}
    return {"symbol": sym, "price": price, "asof": asof, "verdict": verdict, "forecast": {h: dict(f) for h in horizons}}


def bar(d, close, adj=None):
    return (d, close, close, close, close if adj is None else adj, 1000)


def row(asof=ASOF, sym="AAA", hz="1d", target=None, price=100.0, p10=-0.04, p50=0.0, p90=0.05, pgain=0.5, verdict="WATCH"):
    return (asof, sym, hz, target or add_td(datetime.date.fromisoformat(asof), DAYS[hz]).isoformat(), price, p10, p50, p90, pgain, verdict)


# ---------- what is saved ----------
def test_snapshot_has_one_row_per_stock_and_period_with_the_right_target_dates():
    rows = livecheck.snapshot_rows([stock("AAA", verdict="buy")], DAYS, add_td)
    assert [(r[1], r[2]) for r in rows] == [("AAA", "1d"), ("AAA", "5d"), ("AAA", "1m")]
    assert rows[0][3] == add_td(A, 1).isoformat() and rows[2][3] == add_td(A, 20).isoformat()
    assert rows[0][0] == ASOF and rows[0][4:] == (100.0, -0.04, 0.0, 0.05, 0.5, "BUY")


def test_only_stocks_priced_on_the_newest_bar_are_saved_and_odd_ones_are_skipped():
    older = (A - 3 * DAY).isoformat()
    rows = livecheck.snapshot_rows([stock("NEW"), stock("OLD", asof=older), dict(stock("NOFC"), forecast=None), stock("PART", horizons=("1d",))], DAYS, add_td)
    assert {r[1] for r in rows} == {"NEW", "PART"} and sum(1 for r in rows if r[1] == "PART") == 1
    assert livecheck.snapshot_rows([], DAYS, add_td) == []


def test_a_bar_is_final_after_the_close_or_on_a_later_day():
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    at = lambda d, h: datetime.datetime(d.year, d.month, d.day, h, 0, tzinfo=ist)
    assert livecheck.bar_is_final((TODAY - DAY).isoformat(), at(TODAY, 9))                       # yesterday's bar, this morning
    assert not livecheck.bar_is_final(TODAY.isoformat(), at(TODAY, livecheck.FINAL_HOUR - 1))     # today's bar while the market may still be open
    assert livecheck.bar_is_final(TODAY.isoformat(), at(TODAY, livecheck.FINAL_HOUR))


# ---------- settling against the real price ----------
def pend(hz="1d", price=100.0, asof=ASOF, sym="AAA"):
    r = row(asof=asof, sym=sym, hz=hz, price=price)
    return {"asof": r[0], "symbol": r[1], "hz": r[2], "target": r[3], "price": r[4]}


def history(start, n, close_of=lambda i: 100.0 + i, adj_of=None):
    out, d, i = [], start, 0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(bar(d, close_of(i), None if adj_of is None else adj_of(i)))
            i += 1
        d += DAY
    return out


def test_settle_finds_the_close_on_the_target_date():
    bars = history(A, 6, close_of=lambda i: 100.0 * (1 + 0.01 * i))        # +1% a day from the scan date
    (res,) = livecheck.settle([pend("1d")], bars)
    assert res[:3] == (ASOF, "AAA", "1d") and res[3] == pytest.approx(101.0)


def test_a_split_does_not_look_like_a_crash_because_the_adjusted_close_is_used():
    bars = history(A, 6, close_of=lambda i: 100.0 if i < 2 else 50.0, adj_of=lambda i: 50.0 + 0.5 * i)   # 2-for-1 split after day 1
    (res,) = livecheck.settle([pend("5d")], bars)
    assert res[3] == pytest.approx(100.0 * (50.0 + 0.5 * 5) / 50.0)          # the adjusted ratio, 1.05: not 50/100 = -50%


def test_a_target_on_a_non_trading_day_uses_the_next_bar():
    t = A + 4 * DAY
    while t.weekday() < 5:
        t += DAY                                                              # the next Saturday
    p = dict(pend("1d"), target=t.isoformat())
    bars = history(A, 12)
    (res,) = livecheck.settle([p], bars)
    nxt = next(b for b in bars if b[0] >= t)
    assert res[3] == pytest.approx(100.0 * nxt[4] / bars[0][4])


def test_a_forecast_whose_target_has_no_bar_yet_stays_pending():
    bars = history(A, 2)                                                      # only the scan date and the day after
    assert livecheck.settle([pend("5d")], bars) == []


def test_a_forecast_that_can_never_be_checked_is_dropped():
    bars = history(A, 1) + history(A + 30 * DAY, 3)                           # a bar on the scan date, then nothing near the target, then bars long after
    (res,) = livecheck.settle([pend("1d")], bars)
    assert res[3] is None
    near = history(A, 3)                                                       # a bar two days after the target is close enough to use
    assert livecheck.settle([pend("1d")], [b for b in near if b[0] != add_td(A, 1)])[0][3] == pytest.approx(102.0)
    assert livecheck.settle([pend("1d")], history(A + 2 * DAY, 4))[0][3] is None     # no price on the scan date at all
    assert livecheck.settle([pend()], []) == []


def test_wilson_interval_is_wide_for_few_forecasts_and_tight_for_many():
    assert livecheck.wilson(0, 0) == (None, None)
    lo, hi = livecheck.wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=0.002) and hi == pytest.approx(0.596, abs=0.002)
    lo2, hi2 = livecheck.wilson(5000, 10000)
    assert hi2 - lo2 < (hi - lo) / 5


# ---------- the database ----------
@pytest.fixture
def st():
    return Store(":memory:")


def test_saving_the_same_forecast_twice_keeps_the_first(st):
    assert st.fc_record([row(price=100.0)]) == 1
    st.fc_record([row(price=999.0)])
    assert st._all("SELECT price FROM forecast_log") == [{"price": 100.0}]
    assert st.fc_record([]) == 0


def test_pending_lists_only_due_unchecked_forecasts_by_symbol(st):
    st.fc_record([row(sym="AAA", hz="1d"), row(sym="AAA", hz="1m"), row(sym="BBB", hz="1d")])
    due = st.fc_pending(add_td(A, 1).isoformat())
    assert {s: [r["hz"] for r in v] for s, v in due.items()} == {"AAA": ["1d"], "BBB": ["1d"]}        # the 1-month one is not due yet
    assert st.fc_counts() == {"1d": 2, "1m": 1}


def test_settling_updates_the_forecast_and_sums_the_day_for_all_and_for_buy_calls(st):
    # price 100, range 96..105. actuals: 110 (outside, rose), 100 (inside), 90 (outside, fell), 104 (inside, rose)
    st.fc_record([row(sym="W1", verdict="WATCH"), row(sym="W2", verdict="WATCH"), row(sym="B1", verdict="BUY"), row(sym="B2", verdict="BUY")])
    st.fc_settle([(ASOF, "W1", "1d", 110.0), (ASOF, "W2", "1d", 100.0), (ASOF, "B1", "1d", 90.0), (ASOF, "B2", "1d", 104.0)], TODAY.isoformat())
    by = {r["grp"]: r for r in st.fc_stats()}
    assert (by["all"]["n"], by["all"]["inside"], by["all"]["rose"]) == (4, 2, 2)
    assert by["all"]["sum_change"] == pytest.approx(0.10 + 0.0 - 0.10 + 0.04) and by["all"]["sum_pgain"] == pytest.approx(2.0)
    assert (by["buy"]["n"], by["buy"]["inside"], by["buy"]["rose"]) == (2, 1, 1)
    assert st.fc_pending(TODAY.isoformat()) == {} and st.fc_counts() == {}


def test_the_range_edges_count_as_inside_and_a_void_forecast_is_removed(st):
    st.fc_record([row(sym="LO"), row(sym="HI"), row(sym="GONE")])
    st.fc_settle([(ASOF, "LO", "1d", 96.0), (ASOF, "HI", "1d", 105.0), (ASOF, "GONE", "1d", None)], TODAY.isoformat())
    assert st.fc_stats()[0]["n"] == 2 and st.fc_stats()[0]["inside"] == 2
    assert st._all("SELECT COUNT(*) AS n FROM forecast_log WHERE symbol='GONE'")[0]["n"] == 0


def test_settling_again_later_adds_the_stragglers_without_double_counting(st):
    st.fc_record([row(sym="A1"), row(sym="A2")])
    st.fc_settle([(ASOF, "A1", "1d", 101.0)], TODAY.isoformat())
    st.fc_settle([(ASOF, "A1", "1d", 50.0)], TODAY.isoformat())                  # already checked: not changed
    st.fc_settle([(ASOF, "A2", "1d", 99.0)], TODAY.isoformat())
    assert [(r["n"], r["rose"]) for r in st.fc_stats() if r["grp"] == "all"] == [(2, 1)]


def test_expiring_and_pruning(st):
    old = (TODAY - 100 * DAY).isoformat()
    st.fc_record([row(asof=old, sym="OLDDONE"), row(asof=old, sym="OLDOPEN"), row(sym="NEW")])
    st.fc_settle([(old, "OLDDONE", "1d", 101.0)], TODAY.isoformat())
    newest = TODAY.isoformat()
    assert st.fc_expire(newest) == 2                                              # unchecked and long past: both old-open and the 40-day-old open one
    assert st.fc_prune(newest) == 1                                               # the finished old row is forgotten
    assert any(r["asof"] == old for r in st.fc_stats())                           # but its daily total stays for good
    assert st._all("SELECT COUNT(*) AS n FROM forecast_log")[0]["n"] == 0


# ---------- the numbers on the page ----------
def stats_row(asof, hz="1d", grp="all", n=100, inside=80, rose=50, sp=50.0, sc=0.0, sm=0.0):
    return {"asof": asof, "hz": hz, "grp": grp, "n": n, "inside": inside, "rose": rose, "sum_pgain": sp, "sum_change": sc, "sum_mid": sm}


def test_empty_summary_explains_there_is_nothing_yet():
    s = livecheck.summarize([], {})
    assert [h["hz"] for h in s["horizons"]] == list(livecheck.TRACKED) and s["horizons"][0]["n"] == 0
    assert "Nothing has been checked yet" in s["horizons"][0]["note"]
    assert "waiting" in livecheck.summarize([], {"1d": 7})["horizons"][0]["note"]


def test_a_small_sample_is_called_too_early_to_tell():
    s = livecheck.summarize([stats_row(ASOF, n=200, inside=100)], {})["horizons"][0]
    assert s["n"] == 200 and s["days"] == 1 and s["note"].startswith("Too early to tell")


def days(count, **kw):
    return [stats_row((TODAY - i * DAY).isoformat(), **kw) for i in range(count)]


def test_a_large_sample_that_matches_the_promise_says_so():
    s = livecheck.summarize(days(10, n=200, inside=160, rose=100, sp=100.0), {})["horizons"][0]
    assert s["n"] == 2000 and s["inside"]["rate"] == pytest.approx(0.8) and s["rose"]["rate"] == pytest.approx(0.5)
    assert "held about as often as promised" in s["note"] and s["predictedRise"] == pytest.approx(0.5)
    assert len(s["daily"]) == 10 and s["daily"][0]["asof"] == TODAY.isoformat()


def test_ranges_that_are_too_narrow_or_too_wide_are_called_out():
    narrow = livecheck.summarize(days(10, n=200, inside=120), {})["horizons"][0]["note"]
    wide = livecheck.summarize(days(10, n=200, inside=190), {})["horizons"][0]["note"]
    assert "too narrow" in narrow and "too wide" in wide


def test_rises_versus_the_forecast_chance_and_buy_calls_versus_all_stocks():
    rows = days(10, n=200, inside=160, rose=130, sp=100.0) + days(10, grp="buy", n=100, rose=80)       # rose 65% when 50% was forecast; Buy rose 80%
    s = livecheck.summarize(rows, {})["horizons"][0]
    assert "rose more often than the forecasts said" in s["note"] and "Buy calls rose more often than all stocks" in s["note"]
    assert s["buy"]["n"] == 1000 and s["daily"][0]["buyRose"] == pytest.approx(0.8)
    worse = livecheck.summarize(days(10, n=200, inside=160, rose=100, sp=100.0) + days(10, grp="buy", n=100, rose=20), {})["horizons"][0]["note"]
    assert "Buy calls rose less often than all stocks" in worse
    same = livecheck.summarize(days(10, n=200, inside=160, rose=100, sp=100.0) + days(10, grp="buy", n=100, rose=50), {})["horizons"][0]["note"]
    assert "no clear difference" in same


def test_only_the_last_30_days_are_listed_but_every_day_counts_in_the_totals():
    s = livecheck.summarize(days(45, n=100, inside=80), {})["horizons"][0]
    assert len(s["daily"]) == 30 and s["days"] == 45 and s["n"] == 4500


def test_a_tiny_gap_is_not_called_out_even_when_thousands_of_forecasts_make_it_measurable():
    # 79% inside against 80% promised, 51% rose against 50% forecast: real but trivial, over 28,000 forecasts
    s = livecheck.summarize(days(20, n=1400, inside=1106, rose=714, sp=700.0), {})["horizons"][0]
    assert s["inside"]["hi"] < 0.8 and s["rose"]["lo"] > 0.5                       # the intervals do exclude the promise...
    assert "held about as often as promised" in s["note"] and "often than the forecasts said" not in s["note"]   # ...but it is not worth saying
    wide_gap = livecheck.summarize(days(20, n=1400, inside=1008), {})["horizons"][0]["note"]                      # 72% vs 80%: worth saying
    assert "too narrow" in wide_gap
    buy_edge = livecheck.summarize(days(20, n=1400, inside=1120, rose=700, sp=700.0) + days(20, grp="buy", n=100, rose=52), {})["horizons"][0]["note"]
    assert "no clear difference" in buy_edge                                       # 52% vs 50% is inside the 3-point margin
