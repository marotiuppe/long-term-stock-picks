import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.portfolio import rules as R

TODAY = datetime.date(2026, 10, 24)


# ---------- builders: real-looking Yahoo-shaped facts ----------
def quarters(rev, ni, oi=None, eps=None, start="2025-06-30"):
    ends = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
    i0 = ends.index(start)
    out = []
    for k, r in enumerate(rev):
        out.append({"end": ends[i0 + k], "revenue": r, "net_income": ni[k], "operating_income": (oi[k] if oi else ni[k] * 1.3),
                    "eps": (eps[k] if eps else ni[k] / 1e8)})
    return out


CR = 1e7


def closes_to(price_by_year):
    """Daily closes that hit the given price on each fiscal year-end (Mar 31), flat in between."""
    d, c = [], []
    day = datetime.date(2022, 1, 3)
    price = list(price_by_year.values())[0]
    while day <= TODAY:
        d.append(day.isoformat())
        c.append(price_by_year.get(day.isoformat(), price))
        day += datetime.timedelta(days=1)
    return {"d": d, "c": c}


def healthy(**kw):
    q = quarters([100 * CR, 105 * CR, 110 * CR, 115 * CR, 120 * CR], [10 * CR, 11 * CR, 12 * CR, 13 * CR, 14 * CR],
                 eps=[1.0, 1.1, 1.2, 1.3, 1.4])
    f = {"symbol": "X", "status": "ok", "fetched": "2026-10-24", "quarters": q, "annual": [], "debt": [], "dividends": [], "splits": [],
         "closes": {"d": [], "c": []}, "reason": None}
    f.update(kw)
    return f


def with_pe_history(f, price_now_pe_target=None):
    """Annual EPS 4, 5, 6, 7 at year-end prices that give P/E of 20, 20, 20, 20 (average 20)."""
    f = dict(f)
    f["annual"] = [{"end": "2023-03-31", "eps": 4.0}, {"end": "2024-03-31", "eps": 5.0}, {"end": "2025-03-31", "eps": 6.0}, {"end": "2026-03-31", "eps": 7.0}]
    f["closes"] = closes_to({"2023-03-31": 80.0, "2024-03-31": 100.0, "2025-03-31": 120.0, "2026-03-31": 140.0})
    return f


def holding(sym="TCS", price=100.0, avg=100.0, weight=10.0, facts=None, **kw):
    h = {"symbol": sym, "name": sym + " Ltd", "etf": False, "qty": 10, "avg_cost": avg, "price": price, "asof": "2026-10-23", "weight": weight,
         "target_weight": None, "review_price": None, "close": price, "s200": None, "facts": facts}
    h.update(kw)
    return h


def ev(holdings, settings=None, new_results=None):
    return R.evaluate(holdings, settings or {}, TODAY, new_results)


def rules_fired(res, sym=None):
    return {a["rule"] for a in res["alerts"] if sym in (None, a["symbol"])}


# ---------- settings ----------
def test_defaults_match_the_agreed_thresholds():
    S = R.normalize_settings({})
    assert S["add_drop"]["pct"] == 15 and S["trim_conc"]["pct"] == 20 and S["trim_gain_val"]["gain"] == 50
    assert all(v["on"] for v in S.values())


def test_settings_merge_and_validate():
    S = R.normalize_settings({"add_drop": {"pct": "25", "on": False}, "bogus": {"x": 1}, "trim_conc": "nope"})
    assert S["add_drop"] == {"on": False, "pct": 25} and S["trim_conc"]["pct"] == 20 and "bogus" not in S
    with pytest.raises(ValueError, match="between"):
        R.normalize_settings({"add_drop": {"pct": 0}})
    with pytest.raises(ValueError, match="between"):
        R.normalize_settings({"trim_conc": {"pct": 100}})
    with pytest.raises(ValueError, match="number"):
        R.normalize_settings({"add_drop": {"pct": "abc"}})


# ---------- signals ----------
def test_ttm_eps_needs_four_consecutive_quarters():
    assert R.ttm_eps(healthy()["quarters"]) == pytest.approx(1.1 + 1.2 + 1.3 + 1.4)
    assert R.ttm_eps(healthy()["quarters"][:3]) is None
    gappy = healthy()["quarters"]
    gappy[1]["eps"] = None
    assert R.ttm_eps(gappy) is None            # a missing quarter stretches the last four past a year: no TTM figure, not a guess


def test_pe_stats_builds_history_from_year_end_prices():
    f = with_pe_history(healthy())
    st, why = R.pe_stats(100.0, f)
    assert why is None and st["n"] == 4 and st["avg"] == pytest.approx(20.0)
    assert st["ttm_eps"] == pytest.approx(5.0) and st["now"] == pytest.approx(20.0)


@pytest.mark.parametrize("facts,needle", [(None, "No company results"), ({"status": "none", "reason": "ETFs have no results"}, "ETFs"),
                                          ({"status": "error", "reason": "Could not reach Yahoo"}, "Yahoo")])
def test_pe_unavailable_when_no_facts(facts, needle):
    st, why = R.pe_stats(100.0, facts)
    assert st is None and needle in why


def test_pe_unavailable_with_too_few_quarters_or_years():
    f = with_pe_history(healthy())
    f["quarters"] = f["quarters"][:3]
    assert R.pe_stats(100.0, f)[0] is None
    f = with_pe_history(healthy())
    f["annual"] = f["annual"][:2]
    st, why = R.pe_stats(100.0, f)
    assert st is None and "3 fiscal years" in why


def test_pe_not_meaningful_with_negative_eps():
    f = healthy()
    for q in f["quarters"]:
        q["eps"] = -1.0
    assert "not positive" in R.pe_stats(100.0, f)[1]


# ---------- fundamentals getting worse ----------
def test_revenue_falling_two_quarters_and_below_last_year_is_flagged():
    q = quarters([120 * CR, 110 * CR, 100 * CR, 95 * CR, 90 * CR], [10 * CR] * 5, start="2025-06-30")
    # quarters: Jun25 120, Sep25 110, Dec25 100, Mar26 95, Jun26 90 ; last three falling, Jun26 90 < Jun25 120
    conds, why = R.worsening(healthy(quarters=q))
    assert why is None and [c[0] for c in conds] == ["fund_revenue"]
    assert "₹90.0 cr" in conds[0][1] and "-25.0%" in conds[0][1]


def test_a_seasonal_dip_that_is_still_above_last_year_is_not_flagged():
    q = quarters([100 * CR, 120 * CR, 110 * CR, 105 * CR, 130 * CR], [10 * CR] * 5)
    q[2]["revenue"], q[3]["revenue"], q[4]["revenue"] = 118 * CR, 112 * CR, 108 * CR     # falling, but Jun26 108 > Jun25 100
    conds, _ = R.worsening(healthy(quarters=q))
    assert conds == []


def test_no_year_ago_quarter_means_no_flag_not_a_guess():
    q = quarters([100 * CR, 90 * CR, 80 * CR], [10 * CR] * 3, start="2025-12-31")
    conds, why = R.worsening(healthy(quarters=q))
    assert why is None and conds == []


def test_profit_and_margin_decline_are_reported_with_numbers():
    q = quarters([100 * CR, 100 * CR, 100 * CR, 100 * CR, 100 * CR], [20 * CR, 15 * CR, 12 * CR, 10 * CR, 8 * CR], oi=[30 * CR, 25 * CR, 20 * CR, 15 * CR, 12 * CR])
    conds, _ = R.worsening(healthy(quarters=q))
    ids = [c[0] for c in conds]
    assert "fund_profit" in ids and "fund_margin" in ids
    assert "Operating margin shrank" in dict(conds)["fund_margin"] and "12.0%" in dict(conds)["fund_margin"]


def test_rising_debt_needs_three_periods_and_skips_financials():
    f = healthy(debt=[{"end": "2025-03-31", "value": 100 * CR}, {"end": "2025-09-30", "value": 120 * CR}, {"end": "2026-03-31", "value": 150 * CR}])
    assert [c[0] for c in R.worsening(f)[0]] == ["fund_debt"]
    f2 = healthy(debt=f["debt"][:2])
    assert R.worsening(f2)[0] == []
    bank = healthy(debt=f["debt"])
    for q in bank["quarters"]:
        q["operating_income"] = None
    assert R.worsening(bank)[0] == []          # debt means something different for a bank


def test_too_little_data_to_judge():
    f = healthy()
    f["quarters"] = f["quarters"][:2]
    conds, why = R.worsening(f)
    assert conds == [] and "at least 3" in why
    assert R.worsening({"status": "none", "reason": "ETF"})[1] == "ETF"


# ---------- Consider adding ----------
def test_price_far_below_cost_with_intact_results_prompts_adding():
    res = ev([holding(price=80.0, avg=100.0, weight=10, facts=healthy())])
    a = next(x for x in res["alerts"] if x["rule"] == "add_drop")
    assert a["label"] == "Consider adding" and a["tone"] == "add"
    assert "20.0% below your average buy price" in a["reason"] and "₹80.00" in a["reason"] and "₹100.00" in a["reason"]
    assert "15%" in a["rule_text"] and a["as_of"] == "2026-10-23" and a["key"] == "TCS|add_drop"


def test_small_drop_does_not_fire_and_threshold_is_adjustable():
    h = holding(price=90.0, avg=100.0, facts=healthy())
    assert "add_drop" not in rules_fired(ev([h]))
    assert "add_drop" in rules_fired(ev([h], {"add_drop": {"pct": 8}}))
    assert "add_drop" not in rules_fired(ev([holding(price=80.0, facts=healthy())], {"add_drop": {"on": False}}))


def test_drop_with_worsening_results_does_not_prompt_adding():
    q = quarters([120 * CR, 110 * CR, 100 * CR, 95 * CR, 90 * CR], [10 * CR] * 5)
    res = ev([holding(price=80.0, facts=healthy(quarters=q))])
    assert "add_drop" not in rules_fired(res) and "trim_fund" in rules_fired(res)


def test_drop_with_no_company_data_is_reported_as_a_gap_not_fired():
    res = ev([holding(price=80.0, facts={"status": "none", "reason": "ETFs and funds have no company results"})])
    assert "add_drop" not in rules_fired(res)
    g = next(x for x in res["not_evaluated"] if x["rule"] == "add_drop")
    assert "cannot be judged" in g["why"] and "ETFs" in g["why"]


def test_pe_below_own_average_prompts_adding():
    f = with_pe_history(healthy())          # average year-end P/E 20; TTM EPS 5.0
    res = ev([holding(price=70.0, avg=70.0, facts=f)])     # P/E = 70 / 5.0 = 14, 30% below 20
    a = next(x for x in res["alerts"] if x["rule"] == "add_pe")
    assert "P/E is 14.0 now" in a["reason"] and "30% below its own average of 20.0" in a["reason"] and "2023" in a["reason"]
    assert "add_pe" not in rules_fired(ev([holding(price=95.0, avg=95.0, facts=f)]))   # 19 is within the 10% margin


def test_below_target_weight():
    res = ev([holding(weight=4.0, target_weight=10.0)])
    a = next(x for x in res["alerts"] if x["rule"] == "add_weight")
    assert "4.0% of your portfolio" in a["reason"] and "10.0% target" in a["reason"]
    assert "add_weight" not in rules_fired(ev([holding(weight=9.0, target_weight=10.0)]))     # inside the 2 point tolerance
    assert "add_weight" not in rules_fired(ev([holding(weight=4.0, target_weight=None)]))
    gap = ev([holding(weight=None, target_weight=10.0)])
    assert any(g["rule"] == "add_weight" for g in gap["not_evaluated"])


# ---------- Consider reviewing / trimming ----------
def test_concentration():
    res = ev([holding("A", weight=35.0), holding("B", weight=10.0)])
    a = next(x for x in res["alerts"] if x["rule"] == "trim_conc")
    assert a["symbol"] == "A" and a["label"] == "Consider reviewing" and "35.0%" in a["reason"] and "20%" in a["reason"]
    assert rules_fired(ev([holding("A", weight=19.9), holding("B", weight=10.0)])) == set()
    assert "trim_conc" in rules_fired(ev([holding("A", weight=19.9), holding("B", weight=10.0)], {"trim_conc": {"pct": 15}}))


def test_a_single_holding_is_not_a_concentration_problem():
    assert "trim_conc" not in rules_fired(ev([holding("A", weight=100.0)]))


def test_big_gain_with_a_high_pe():
    f = with_pe_history(healthy())
    res = ev([holding(price=200.0, avg=100.0, weight=10, facts=f)])     # +100%, P/E 40 vs 20
    a = next(x for x in res["alerts"] if x["rule"] == "trim_gain_val")
    assert "up 100.0%" in a["reason"] and "P/E is 40.0" in a["reason"] and "100% above" in a["reason"]
    assert "trim_gain_val" not in rules_fired(ev([holding(price=130.0, avg=100.0, facts=f)]))     # gain below 50%


def test_big_gain_without_pe_history_is_a_gap():
    res = ev([holding(price=200.0, avg=100.0, facts=healthy())])      # no annual history
    assert "trim_gain_val" not in rules_fired(res)
    assert any(g["rule"] == "trim_gain_val" and "P/E history cannot be built" in g["why"] for g in res["not_evaluated"])


def test_fundamentals_worse_alert_carries_the_numbers_and_the_data_date():
    q = quarters([100 * CR] * 5, [20 * CR, 15 * CR, 12 * CR, 10 * CR, 8 * CR])
    a = next(x for x in ev([holding(facts=healthy(quarters=q))])["alerts"] if x["rule"] == "trim_fund")
    assert "Net profit fell two quarters in a row" in a["reason"] and "₹12.0 cr" in a["reason"]
    assert a["as_of"] == "2026-06-30" and "2026-10-24" in a["rule_text"] and a["importance"] >= 80


def test_below_200_day_average_and_under_cost_is_a_loss_review():
    h = holding(price=70.0, avg=100.0, close=70.0, s200=95.0)
    a = next(x for x in ev([h])["alerts"] if x["rule"] == "trim_loss")
    assert "below its 200-day average of ₹95.00" in a["reason"] and "30.0% below" in a["reason"] and "not a sell signal" in a["reason"]
    assert "trim_loss" not in rules_fired(ev([holding(price=70.0, avg=100.0, close=70.0, s200=60.0)]))     # above its average
    assert "trim_loss" not in rules_fired(ev([holding(price=90.0, avg=100.0, close=90.0, s200=95.0)]))     # only 10% under cost
    gap = ev([holding(price=70.0, avg=100.0, close=None, s200=None)])
    assert any(g["rule"] == "trim_loss" for g in gap["not_evaluated"])


def test_review_level_reached():
    a = next(x for x in ev([holding(price=95.0, review_price=96.0)])["alerts"] if x["rule"] == "review_level")
    assert "₹95.00" in a["reason"] and "₹96.00" in a["reason"] and a["importance"] >= 90
    assert "review_level" not in rules_fired(ev([holding(price=97.0, review_price=96.0)]))
    assert "review_level" not in rules_fired(ev([holding(price=95.0, review_price=None)]))


# ---------- information ----------
def test_new_results_are_information_only():
    f = healthy()
    res = ev([holding(facts=f)], new_results={"TCS": {"end": "2026-06-30", "detected": "2026-10-20"}})
    a = next(x for x in res["alerts"] if x["rule"] == "info_results")
    assert a["label"] == "Info" and a["tone"] == "info" and "2026-06-30" in a["reason"] and "revenue ₹120.0 cr" in a["reason"]


def test_dividend_window():
    f = healthy(dividends=[{"date": "2026-10-14", "amount": 12.0}])
    a = next(x for x in ev([holding(facts=f)])["alerts"] if x["rule"] == "info_dividend")
    assert "ex-dividend on 2026-10-14" in a["reason"] and "₹12.00 per share" in a["reason"]
    old = healthy(dividends=[{"date": "2026-08-01", "amount": 12.0}])
    assert "info_dividend" not in rules_fired(ev([holding(facts=old)]))
    assert "info_dividend" in rules_fired(ev([holding(facts=old)], {"info_dividend": {"days": 90}}))
    future = healthy(dividends=[{"date": "2026-11-01", "amount": 12.0}])
    assert "info_dividend" not in rules_fired(ev([holding(facts=future)]))


def test_split_or_bonus():
    f = healthy(splits=[{"date": "2026-10-10", "text": "1:1"}])
    assert "info_corp" in rules_fired(ev([holding(facts=f)]))


# ---------- honesty and edge cases ----------
def test_alert_wording_never_gives_a_buy_or_sell_instruction():
    f = with_pe_history(healthy())
    q = quarters([100 * CR] * 5, [20 * CR, 15 * CR, 12 * CR, 10 * CR, 8 * CR])
    hs = [holding("A", price=70.0, avg=100.0, weight=35.0, facts=with_pe_history(healthy(quarters=q)), close=70.0, s200=95.0, review_price=75.0, target_weight=60.0),
          holding("B", price=200.0, avg=100.0, weight=10.0, facts=f)]
    res = ev(hs)
    assert len(res["alerts"]) >= 6
    for a in res["alerts"]:
        text = (a["reason"] + a["rule_text"] + a["title"] + a["label"]).lower()
        assert a["label"] in ("Consider adding", "Consider reviewing", "Info")
        assert "buy now" not in text and "sell now" not in text and "you should" not in text and "will rise" not in text and "will fall" not in text
        assert a["reason"] and a["rule_text"] and a["as_of"] and a["fingerprint"] and a["key"].startswith(a["symbol"] + "|")


def test_alerts_are_sorted_by_importance():
    q = quarters([100 * CR] * 5, [20 * CR, 15 * CR, 12 * CR, 10 * CR, 8 * CR])
    res = ev([holding("A", price=95.0, review_price=96.0, facts=healthy(quarters=q), weight=40.0), holding("B", weight=10.0)])
    imps = [a["importance"] for a in res["alerts"]]
    assert imps == sorted(imps, reverse=True) and res["alerts"][0]["rule"] == "review_level"


def test_zero_holdings_and_zero_quantity_rows():
    assert ev([]) == {"alerts": [], "not_evaluated": [], "checked": []}
    assert ev([holding(qty=0)])["alerts"] == []


def test_missing_price_never_crashes_or_fires_price_rules():
    res = ev([holding(price=None, weight=None, close=None, facts=healthy(), review_price=50.0, target_weight=10.0)])
    assert rules_fired(res) <= {"info_results", "info_dividend", "info_corp", "trim_fund"}


def test_all_rules_off_gives_nothing():
    off = {r: {"on": False} for r in R.DEFAULTS}
    q = quarters([100 * CR] * 5, [20 * CR, 15 * CR, 12 * CR, 10 * CR, 8 * CR])
    assert ev([holding(price=50.0, facts=healthy(quarters=q), review_price=60.0, weight=50.0), holding("B")], off)["alerts"] == []


# ---------- dismiss and snooze ----------
def alert(fp="10", key="TCS|add_drop"):
    return {"key": key, "fingerprint": fp, "symbol": "TCS", "rule": "add_drop"}


def test_dismissed_stays_hidden_until_the_condition_changes():
    st = {"TCS|add_drop": {"state": "dismissed", "until": None, "fingerprint": "10"}}
    assert R.apply_state([alert("10")], st, TODAY) == ([], 1)
    vis, hidden = R.apply_state([alert("15")], st, TODAY)
    assert len(vis) == 1 and hidden == 0


def test_snoozed_hides_until_the_date_or_a_change():
    st = {"TCS|add_drop": {"state": "snoozed", "until": "2026-10-31", "fingerprint": "10"}}
    assert R.apply_state([alert("10")], st, TODAY) == ([], 1)
    assert len(R.apply_state([alert("10")], st, datetime.date(2026, 10, 31))[0]) == 1      # the snooze has ended
    assert len(R.apply_state([alert("15")], st, TODAY)[0]) == 1                            # the condition changed
    assert R.apply_state([alert("10")], st, datetime.date(2026, 10, 31))[0][0]["snoozed_before"] is True


def test_other_alerts_are_not_hidden():
    st = {"TCS|add_drop": {"state": "dismissed", "until": None, "fingerprint": "10"}}
    vis, hidden = R.apply_state([alert("10"), alert("5", "TCS|trim_conc")], st, TODAY)
    assert [a["key"] for a in vis] == ["TCS|trim_conc"] and hidden == 1
