import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.portfolio import positions as P

TODAY = datetime.date(2026, 10, 24)


def lot(i, side, qty, price, date, fees=0, sym="TCS"):
    return {"id": i, "symbol": sym, "side": side, "qty": qty, "price": price, "date": date, "fees": fees}


# ---------- weighted average and invested ----------
def test_weighted_average_of_two_buys():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "buy", 10, 200, "2026-02-01")])
    assert p["qty"] == 20 and p["avg_cost"] == 150 and p["invested"] == 3000 and p["realized"] == 0
    assert p["first_buy"] == "2026-01-01" and p["bought_qty"] == 20


def test_unequal_lots():
    p = P.replay([lot(1, "buy", 30, 100, "2026-01-01"), lot(2, "buy", 10, 200, "2026-02-01")])
    assert p["avg_cost"] == pytest.approx(125) and p["invested"] == 5000


def test_charges_are_part_of_the_cost():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01", fees=50)])
    assert p["invested"] == 1050 and p["avg_cost"] == 105


def test_no_transactions():
    p = P.replay([])
    assert p["qty"] == 0 and p["avg_cost"] is None and p["invested"] == 0 and p["realized"] == 0 and p["lots"] == []


# ---------- sales and realised P&L ----------
def test_partial_sale_realises_against_average_cost_and_keeps_the_average():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "buy", 10, 200, "2026-02-01"), lot(3, "sell", 5, 200, "2026-03-01")])
    assert p["realized"] == 250                       # 5 x (200 - 150)
    assert p["qty"] == 15 and p["avg_cost"] == 150 and p["invested"] == 2250
    sale = p["lots"][-1]
    assert sale["realized"] == 250 and sale["basis"] == 150 and sale["amount"] == 1000


def test_sale_at_a_loss_and_with_charges():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "sell", 4, 90, "2026-02-01", fees=10)])
    assert p["realized"] == pytest.approx(4 * (90 - 100) - 10) and p["qty"] == 6 and p["invested"] == 600


def test_selling_everything_then_buying_again_starts_fresh():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "sell", 10, 130, "2026-02-01"), lot(3, "buy", 5, 50, "2026-03-01")])
    assert p["realized"] == 300 and p["qty"] == 5 and p["avg_cost"] == 50 and p["invested"] == 250


def test_fully_sold_position_is_empty_but_remembers_realised():
    p = P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "sell", 10, 120, "2026-02-01")])
    assert p["qty"] == 0 and p["avg_cost"] is None and p["invested"] == 0 and p["realized"] == 200


def test_cannot_sell_more_than_held():
    with pytest.raises(ValueError, match="Cannot sell 11 shares"):
        P.replay([lot(1, "buy", 10, 100, "2026-01-01"), lot(2, "sell", 11, 120, "2026-02-01")])


def test_transactions_replay_in_date_order_not_entry_order():
    # the sale was entered first but happened after the purchase
    p = P.replay([lot(1, "sell", 5, 120, "2026-02-01"), lot(2, "buy", 10, 100, "2026-01-01")])
    assert p["qty"] == 5 and p["realized"] == 100
    with pytest.raises(ValueError):   # back-dating the buy to after the sale breaks the history
        P.replay([lot(1, "sell", 5, 120, "2026-02-01"), lot(2, "buy", 10, 100, "2026-03-01")])


def test_undated_opening_position_comes_first():
    p = P.replay([lot(2, "sell", 3, 150, "2026-02-01"), lot(1, "buy", 10, 100, None)])
    assert p["qty"] == 7 and p["first_buy"] is None


# ---------- valuation and portfolio ----------
def test_valuation_unrealised_and_day_change():
    pos = P.replay([lot(1, "buy", 10, 100, "2026-01-01")])
    v = P.valuation({k: pos[k] for k in pos if k != "lots"}, 120, 118)
    assert v["value"] == 1200 and v["unrealized"] == 200 and v["unrealized_pct"] == 20
    assert v["day_abs"] == 20 and v["day_pct"] == pytest.approx(1.69, abs=0.01)


def test_valuation_without_a_price_stays_empty():
    pos = P.replay([lot(1, "buy", 10, 100, "2026-01-01")])
    v = P.valuation({k: pos[k] for k in pos if k != "lots"}, None)
    assert v["value"] is None and v["unrealized"] is None and v["day_abs"] is None


def _row(sym, qty, avg, price, prev=None):
    pos = P.replay([lot(1, "buy", qty, avg, "2026-01-01", sym=sym)])
    return dict(P.valuation({k: pos[k] for k in pos if k != "lots"}, price, prev), symbol=sym)


def test_weights_sum_to_100_and_totals():
    rows = [_row("A", 10, 100, 150, 140), _row("B", 20, 50, 40, 41), _row("C", 5, 10, 10)]
    s = P.summarize(rows)
    assert s["invested"] == 2050 and s["value"] == 1500 + 800 + 50
    assert sum(r["weight"] for r in rows) == pytest.approx(100, abs=0.05)
    assert s["pnl"] == 300 and s["pnl_pct"] == pytest.approx(14.63, abs=0.01)
    assert s["day_abs"] == 10 * 10 + 20 * -1       # C has no previous close and is left out
    assert s["best"][0] == "A" and s["worst"][0] == "B"


def test_summary_with_zero_holdings_has_no_division_errors():
    s = P.summarize([])
    assert s["value"] == 0 and s["pnl"] == 0 and s["pnl_pct"] is None and s["day_abs"] is None and s["count"] == 0
    assert s["best"] == [] and s["worst"] == []


def test_unpriced_positions_are_listed_and_excluded_from_value():
    rows = [_row("A", 10, 100, 120), _row("B", 5, 100, None)]
    s = P.summarize(rows)
    assert s["unpriced"] == ["B"] and s["value"] == 1200 and rows[1]["weight"] is None and rows[0]["weight"] == 100
    assert s["invested"] == 1500 and s["invested_priced"] == 1000   # pnl is computed on the priced part only


def test_single_holding_best_and_worst_are_empty():
    assert P.summarize([_row("A", 1, 10, 12)])["best"] == []


# ---------- validation ----------
def good(**kw):
    d = {"symbol": "tcs", "side": "buy", "qty": "10", "price": "3,500.50", "date": "2026-10-01", "fees": "20", "note": " first "}
    d.update(kw)
    return d


def test_validate_accepts_and_cleans():
    c = P.validate_lot(good(), TODAY)
    assert c == {"symbol": "TCS", "side": "buy", "qty": 10, "price": 3500.5, "date": "2026-10-01", "fees": 20.0, "note": "first"}


@pytest.mark.parametrize("kw,msg", [({"qty": 0}, "more than 0"), ({"qty": -3}, "more than 0"), ({"qty": 2.5}, "whole number"),
                                    ({"qty": "abc"}, "number"), ({"qty": 10 ** 8}, "too large"), ({"price": 0}, "more than 0"),
                                    ({"price": 10 ** 8}, "too large"), ({"price": float("nan")}, "number"), ({"price": True}, "number"),
                                    ({"date": "2026-10-25"}, "future"), ({"date": "24/10/2026"}, "look like"), ({"date": "1980-01-01"}, "past"),
                                    ({"date": ""}, "date"), ({"fees": -1}, "negative"), ({"fees": 99999}, "too high"),
                                    ({"symbol": "bad sym!"}, "valid symbol"), ({"symbol": ""}, "valid symbol"), ({"side": "hold"}, "buy or sell"),
                                    ({"note": "x" * 201}, "too long")])
def test_validate_rejects_with_a_message(kw, msg):
    with pytest.raises(ValueError, match=msg):
        P.validate_lot(good(**kw), TODAY)


def test_today_is_allowed_and_ns_suffix_is_stripped():
    assert P.validate_lot(good(date="2026-10-24", symbol="TCS.NS"), TODAY)["symbol"] == "TCS"


def test_date_optional_for_imports():
    assert P.validate_lot(good(date=None), TODAY, require_date=False)["date"] is None


def test_quantity_from_an_amount():
    assert P.qty_from_amount(10000, 3500) == (2, 3000.0)
    assert P.qty_from_amount(100, 3500) == (0, 100.0)
    assert P.qty_from_amount(0, 10) == (0, 0.0) and P.qty_from_amount(10, 0)[0] == 0


def test_indian_grouping():
    assert P.fmt_inr(999) == "₹999" and P.fmt_inr(1234567.5) == "₹12,34,568" and P.fmt_inr(12345678) == "₹1,23,45,678"
    assert P.fmt_inr(-1500.5, 2) == "-₹1,500.50" and P.fmt_inr(100000) == "₹1,00,000" and P.fmt_inr(0) == "₹0"
