import datetime
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

D0 = datetime.date(2020, 1, 1)


def row(day, score, r10=0.01, r1m=0.01, r3m=0.01, r6m=0.01):
    by = {"10d": r10, "1m": r1m, "3m": r3m, "6m": r6m}
    r = tuple(by.get(k, r10) for k in server.HORIZONS)   # 1d, 2d and 5d reuse the 10-day value
    return (score, r, r, D0 + datetime.timedelta(days=day))


def synth(n_days=1500, per_day=1):
    return [row(d, 50 if (d + k) % 2 else 10, r10=0.02 if d % 3 else -0.01)
            for d in range(0, n_days, 3) for k in range(per_day)]


def test_no_lookahead_gap():
    pool = synth()
    train, held, cutoff = server.split_pool(pool)
    assert train and held
    gap = datetime.timedelta(days=server.PURGE_DAYS)
    assert max(p[3] for p in train) < cutoff
    assert min(p[3] for p in held) >= max(p[3] for p in train) + gap
    # longest horizon (126 trading days ~ 176 calendar) fits inside the purge
    assert server.PURGE_DAYS >= 126 * 7 / 5
    assert len(train) + len(held) < len(pool)   # purge rows belong to neither


def test_heldout_fraction_roughly_quarter():
    pool = synth()
    _, held, _ = server.split_pool(pool)
    assert 0.05 < len(held) / len(pool) < 0.25


def test_effective_n_and_fields():
    pool = synth(per_day=4)
    t = server.track_record(pool)
    held = server.split_pool(pool)[1]
    for k, h in server.HORIZONS.items():
        overlap = max(1.0, h / server.POOL_STEP)
        assert math.isclose(t[k]["effective_n"], t[k]["n"] / overlap)
        assert math.isclose(t[k]["all_effective_n"], t[k]["all_n"] / overlap)
    assert t["10d"]["effective_n"] == t["10d"]["n"]   # overlap floor of 1
    assert t["6m"]["effective_n"] < t["6m"]["n"]
    assert t["10d"]["start"] >= min(p[3] for p in held).isoformat()
    assert t["10d"]["end"] == max(p[3] for p in held).isoformat()
    assert all(p[3].isoformat() >= t["10d"]["start"] for p in held)


def test_interval_math():
    lo, hi = server.edge_interval(0.6, 100, 0.5, 400)
    se = math.sqrt(0.6 * 0.4 / 100 + 0.5 * 0.5 / 400)
    assert math.isclose(lo, 0.1 - 1.96 * se) and math.isclose(hi, 0.1 + 1.96 * se)
    # more effective samples, tighter interval
    lo2, hi2 = server.edge_interval(0.6, 10000, 0.5, 40000)
    assert hi2 - lo2 < hi - lo


def test_track_record_edge_uses_interval():
    t = server.track_record(synth(per_day=4))["1m"]
    assert math.isclose(t["edge"], t["hit"] - t["all_hit"])
    assert t["edge_lo"] <= t["edge"] <= t["edge_hi"]


def test_base_rate_uses_whole_pool_never_the_heldout_window():
    # Regression: a weak held-out window (low all_hit) must not lower the Buy bar.
    pool = [row(d, 50, r1m=0.01 if (d // 10) % 2 else -0.01) for d in range(0, 600, 10)]
    weak_heldout = {"1m": {"all_n": server.MIN_HELDOUT * 10, "all_hit": 0.10}}
    assert math.isclose(server.base_rate(pool, weak_heldout), 0.5)
    assert math.isclose(server.base_rate(pool, {}), 0.5)
    assert server.base_rate([], {}) == 0.5


def test_empty_pool():
    assert server.track_record([]) == {}
    assert server.split_pool([]) == ([], [], None)
