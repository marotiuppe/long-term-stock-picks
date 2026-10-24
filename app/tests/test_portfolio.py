import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.portfolio.portfolio import parse_paste, review

UNI = {"TCS", "INFY", "RELIANCE", "M&M"}


def test_basic_separators():
    rows, errs = parse_paste("TCS 10 3500\nINFY\t5\t1500.5\nRELIANCE,2,2900\n", UNI)
    assert errs == []
    assert rows == [{"symbol": "TCS", "qty": 10, "avg_price": 3500.0},
                    {"symbol": "INFY", "qty": 5, "avg_price": 1500.5},
                    {"symbol": "RELIANCE", "qty": 2, "avg_price": 2900.0}]


def test_indian_numbers_and_rupee():
    rows, errs = parse_paste("TCS 1,000 ₹1,23,456.50\nINFY 5 ₹ 1500", UNI)
    assert errs == []
    assert rows[0]["qty"] == 1000 and rows[0]["avg_price"] == 123456.5
    assert rows[1]["avg_price"] == 1500.0


def test_comma_line_needs_exactly_three_fields():
    rows, errs = parse_paste("TCS,10,1,23,456", UNI)
    assert rows == [] and errs[0][0] == 1
    rows, errs = parse_paste("TCS, 10, 3500", UNI)
    assert errs == [] and rows[0]["qty"] == 10


def test_duplicates_weighted_average():
    rows, errs = parse_paste("TCS 10 100\nTCS 30 200", UNI)
    assert errs == [] and len(rows) == 1
    assert rows[0]["qty"] == 40 and rows[0]["avg_price"] == 175.0


def test_errors_and_skips():
    text = "# header\n\nFOO 1 1\nTCS -5 100\nTCS 0 100\nTCS abc 100\nTCS 1\nbad$sym 1 1\nINFY 1 100"
    rows, errs = parse_paste(text, UNI)
    assert [r["symbol"] for r in rows] == ["INFY"]
    assert [e[0] for e in errs] == [3, 4, 5, 6, 7, 8]
    assert "universe" in errs[0][1]


def test_lowercase_and_ns_suffix_and_ampersand():
    rows, errs = parse_paste("tcs.ns 1 10\nm&m 2 20", UNI)
    assert errs == [] and [r["symbol"] for r in rows] == ["TCS", "M&M"]


def test_review_pnl_maths():
    h = {"symbol": "TCS", "qty": 10, "avg_price": 100.0}
    s = {"price": 110.0, "stop": 99.0, "verdict": "BUY"}
    r = review(h, s, "3m", "2026-10-24", review_date="2027-01-20")
    assert r["invested"] == 1000 and r["value"] == 1100
    assert r["pnl_abs"] == 100 and r["pnl_pct"] == 10.0
    assert r["distance_to_stop_pct"] == 10.0 and r["stop_breached"] is False
    assert r["call"] == "BUY" and r["review_date"] == "2027-01-20"
    assert r["downtrend_flag"] is False and r["flags"] == []


def test_review_loss_and_stop_breached():
    h = {"symbol": "TCS", "qty": 4, "avg_price": 200.0}
    r = review(h, {"price": 90.0, "stop": 90.0, "verdict": "DOWNTREND", "downtrend": True}, "1m", "2026-10-24")
    assert r["pnl_abs"] == -440 and r["pnl_pct"] == -55.0
    assert r["stop_breached"] is True and r["distance_to_stop_pct"] == 0.0
    assert r["downtrend_flag"] is True
    assert "stop breached" in r["flags"]


def test_review_no_data():
    h = {"symbol": "ZZZ", "qty": 1, "avg_price": 50.0}
    for stock in (None, {}):
        r = review(h, stock, "3m", "2026-10-24")
        assert r["call"] is None and r["flags"] == ["no data"]
        assert r["pnl_abs"] is None and r["invested"] == 50
