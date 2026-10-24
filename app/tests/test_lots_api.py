import datetime
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import api_me
from core import fundamentals
from core.store import Store

TODAY = datetime.date(2026, 10, 24)
CR = 1e7


def scan(prices=None):
    prices = prices or {"TCS": 3000.0, "INFY": 1500.0, "NIFTYBEES": 250.0}
    return {"generated": "24 Oct 2026", "sellDates": {"1m": "2026-11-24"},
            "stocks": [{"symbol": s, "name": s + " Ltd", "price": p, "asof": "2026-10-23", "etf": s == "NIFTYBEES", "exchange": "NSE",
                        "verdict": "BUY", "stop": p * .9, "sma20": p} for s, p in prices.items()]}


def detail(sym, last=3000.0, prev=2970.0, s200=2900.0):
    c = [prev] * 5 + [last]
    return {sym: {"series": {"c": c, "s200": [s200] * len(c)}}}


@pytest.fixture
def st():
    s = Store(":memory:")
    yield s
    s.close()


def call(st, method, path, body=None, uid="u1", sc=None, ctx=None, query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    return api_me.handle(method, path, query, raw, st, uid, sc or scan(), {"TCS", "INFY", "NIFTYBEES"}, ctx=ctx, today=TODAY)


def buy(st, sym="TCS", qty=10, price=2800, date="2026-09-01", uid="u1", **kw):
    d = {"symbol": sym, "side": "buy", "qty": qty, "price": price, "date": date}
    d.update(kw)
    code, out = call(st, "POST", "/api/lots", d, uid=uid)
    assert code == 200, out
    return out


# ---------- adding, editing, deleting lots ----------
def test_two_buys_become_one_position_with_a_weighted_average(st):
    buy(st, qty=10, price=2800, date="2026-01-01")
    out = buy(st, qty=10, price=3200, date="2026-03-01")
    p = out["position"]
    assert p["qty"] == 20 and p["avg_cost"] == 3000 and p["invested"] == 60000 and len(p["lots"]) == 2
    assert p["value"] == 60000 and p["unrealized"] == 0 and p["weight"] == 100


def test_position_shows_unrealised_pnl_and_day_change_from_the_apps_own_prices(st):
    buy(st, qty=10, price=2800)
    ctx = {"detail": detail("TCS", last=3000.0, prev=2970.0)}
    code, p = call(st, "GET", "/api/position", query="sym=TCS", ctx=ctx)
    assert p["value"] == 30000 and p["unrealized"] == 2000 and p["unrealized_pct"] == pytest.approx(7.14, abs=0.01)
    assert p["day_abs"] == pytest.approx(300) and p["day_pct"] == pytest.approx(1.01, abs=0.01)


def test_sale_records_realised_pnl_and_reduces_the_position(st):
    buy(st, qty=10, price=2800)
    code, out = call(st, "POST", "/api/lots", {"symbol": "TCS", "side": "sell", "qty": 4, "price": 3000, "date": "2026-10-01", "fees": 15})
    assert code == 200
    p = out["position"]
    assert p["qty"] == 6 and p["realized"] == pytest.approx(4 * 200 - 15) and p["invested"] == pytest.approx(16800)


def test_cannot_sell_what_you_do_not_hold(st):
    buy(st, qty=10)
    code, out = call(st, "POST", "/api/lots", {"symbol": "TCS", "side": "sell", "qty": 11, "price": 3000, "date": "2026-10-01"})
    assert code == 400 and "Cannot sell 11 shares" in out["error"]
    assert len(call(st, "GET", "/api/lots")[1]["lots"]) == 1          # nothing was stored


def test_validation_errors_are_clear_and_store_nothing(st):
    for bad, msg in [({"qty": 0}, "more than 0"), ({"qty": 1.5}, "whole number"), ({"price": -5}, "more than 0"),
                     ({"date": "2026-12-01"}, "future"), ({"symbol": "ZZZZ"}, "not a stock or ETF"), ({"fees": 10 ** 6}, "too high")]:
        d = {"symbol": "TCS", "side": "buy", "qty": 1, "price": 100, "date": "2026-10-01"}
        d.update(bad)
        code, out = call(st, "POST", "/api/lots", d)
        assert code == 400 and msg in out["error"], (bad, out)
    assert call(st, "GET", "/api/lots")[1]["lots"] == []


def test_edit_a_transaction(st):
    lid = buy(st, qty=10, price=2800)["id"]
    code, out = call(st, "PUT", "/api/lots", {"symbol": "TCS", "side": "buy", "qty": 20, "price": 2500, "date": "2026-09-02", "note": "fixed"}, query="id=%d" % lid)
    assert code == 200 and out["position"]["qty"] == 20 and out["position"]["avg_cost"] == 2500 and out["position"]["lots"][0]["note"] == "fixed"
    assert call(st, "PUT", "/api/lots", {"symbol": "TCS", "qty": 1, "price": 1, "date": "2026-01-01"}, query="id=9999")[0] == 404


def test_editing_a_buy_cannot_strand_a_later_sale(st):
    lid = buy(st, qty=10, date="2026-01-01")["id"]
    call(st, "POST", "/api/lots", {"symbol": "TCS", "side": "sell", "qty": 8, "price": 3000, "date": "2026-02-01"})
    code, out = call(st, "PUT", "/api/lots", {"symbol": "TCS", "side": "buy", "qty": 5, "price": 2800, "date": "2026-01-01"}, query="id=%d" % lid)
    assert code == 400 and "Cannot sell" in out["error"]
    assert call(st, "GET", "/api/position", query="sym=TCS")[1]["qty"] == 2      # unchanged: 10 bought, 8 sold


def test_delete_a_transaction_and_protect_the_history(st):
    a = buy(st, qty=10, date="2026-01-01")["id"]
    b = buy(st, qty=5, date="2026-02-01")["id"]
    code, out = call(st, "DELETE", "/api/lots", query="id=%d" % b)
    assert code == 200 and out["position"]["qty"] == 10
    call(st, "POST", "/api/lots", {"symbol": "TCS", "side": "sell", "qty": 10, "price": 3000, "date": "2026-03-01"})
    code, out = call(st, "DELETE", "/api/lots", query="id=%d" % a)
    assert code == 400 and "Cannot sell" in out["error"]
    assert call(st, "DELETE", "/api/lots", query="id=424242")[0] == 404
    assert call(st, "DELETE", "/api/lots")[0] == 400


def test_users_cannot_touch_each_others_transactions(st):
    lid = buy(st, uid="u1")["id"]
    assert call(st, "DELETE", "/api/lots", query="id=%d" % lid, uid="u2")[0] == 404
    assert call(st, "PUT", "/api/lots", {"symbol": "TCS", "qty": 1, "price": 1, "date": "2026-01-01"}, query="id=%d" % lid, uid="u2")[0] == 404
    assert call(st, "GET", "/api/lots", uid="u2")[1]["lots"] == []


def test_no_holdings_gives_empty_summary(st):
    me = call(st, "GET", "/api/me")[1]
    assert me["positions"] == [] and me["summary"]["count"] == 0 and me["summary"]["value"] == 0 and me["summary"]["pnl_pct"] is None


def test_me_payload_summary_has_weights_and_totals(st):
    buy(st, "TCS", 10, 2800)
    buy(st, "INFY", 20, 1600)
    me = call(st, "GET", "/api/me")[1]
    s = me["summary"]
    assert s["invested"] == 28000 + 32000 and s["value"] == 30000 + 30000
    assert {p["symbol"]: p["weight"] for p in me["positions"]} == {"TCS": 50.0, "INFY": 50.0}
    assert s["pnl"] == 0 and s["count"] == 2        # +2,000 on TCS and -2,000 on INFY


def test_legacy_holdings_endpoint_still_sets_a_position(st):
    code, me = call(st, "POST", "/api/holdings", {"symbol": "TCS", "qty": 10, "avg_price": 2800})
    assert code == 200 and me["holdings"][0]["qty"] == 10 and me["holdings"][0]["avg_price"] == 2800
    assert call(st, "GET", "/api/position", query="sym=TCS")[1]["lots"][0]["note"].startswith("Position entered")


# ---------- export and import ----------
def test_csv_export_and_import_round_trip(st):
    buy(st, qty=10, price=2800, date="2026-01-01", fees=20, note="=cmd()")
    call(st, "POST", "/api/lots", {"symbol": "TCS", "side": "sell", "qty": 2, "price": 3000, "date": "2026-02-01"})
    code, out = call(st, "GET", "/api/export.csv")
    text = out["_csv"]
    assert code == 200 and text.startswith("﻿symbol,side,qty,price,date,fees,note,amount,realized") and "'=cmd()" in text
    st2 = Store(":memory:")
    code, res = call(st2, "POST", "/api/transactions/import", {"format": "csv", "data": text})
    assert code == 200 and res["added"] == 2
    p = call(st2, "GET", "/api/position", query="sym=TCS")[1]
    assert p["qty"] == 8 and p["lots"][0]["note"] == "=cmd()"
    st2.close()


def test_json_export_import_and_dedupe(st):
    buy(st, qty=10, price=2800, date="2026-01-01")
    call(st, "PUT", "/api/rules", {"rules": {"add_drop": {"pct": 25}}, "stock": {"symbol": "TCS", "target_weight": 12, "sector": "IT"}})
    exp = st.export_user("u1")
    assert exp["schema_version"] == 2 and exp["lots"] and exp["rules"]["add_drop"]["pct"] == 25 and exp["holding_settings"]["TCS"]["sector"] == "IT"
    st2 = Store(":memory:")
    code, res = call(st2, "POST", "/api/transactions/import", {"format": "json", "data": exp}, uid="u9")
    assert code == 200 and res["added"] == 1
    assert st2.get_rules("u9")["add_drop"]["pct"] == 25 and st2.get_hsettings("u9")["TCS"]["target_weight"] == 12
    code, again = call(st2, "POST", "/api/transactions/import", {"format": "json", "data": exp}, uid="u9")
    assert again["added"] == 0 and again["skipped"] == 1
    st2.close()


def test_import_is_all_or_nothing_and_names_the_bad_rows(st):
    csv_text = "symbol,side,qty,price,date\nTCS,buy,10,2800,2026-01-01\nTCS,buy,-5,2800,2026-01-02\nINFY,buy,2,abc,2026-01-03\n"
    code, out = call(st, "POST", "/api/transactions/import", {"format": "csv", "data": csv_text})
    assert code == 400 and "Row 3" in out["error"] and "Row 4" in out["error"]
    assert call(st, "GET", "/api/lots")[1]["lots"] == []
    code, out = call(st, "POST", "/api/transactions/import", {"format": "csv", "data": "foo,bar\n1,2\n"})
    assert code == 400 and "must name the columns" in out["error"]
    code, out = call(st, "POST", "/api/transactions/import", {"format": "csv", "data": "symbol,qty,price\nZZZZ,1,1\n"})
    assert code == 400 and "ZZZZ" in out["error"]
    code, out = call(st, "POST", "/api/transactions/import", {"format": "json", "data": {"nothing": 1}})
    assert code == 400


def test_import_that_oversells_is_refused_and_replace_mode_replaces(st):
    bad = "symbol,side,qty,price,date\nTCS,sell,5,3000,2026-01-01\n"
    assert call(st, "POST", "/api/transactions/import", {"format": "csv", "data": bad})[0] == 400
    buy(st, "INFY", 3, 1500)
    ok = "symbol,qty,price,date\nTCS,5,2800,2026-01-01\n"
    code, out = call(st, "POST", "/api/transactions/import", {"format": "csv", "data": ok, "mode": "replace"})
    assert code == 200 and [l["symbol"] for l in call(st, "GET", "/api/lots")[1]["lots"]] == ["TCS"]


# ---------- settings ----------
def test_rule_settings_validate_and_persist(st):
    code, out = call(st, "PUT", "/api/rules", {"rules": {"trim_conc": {"pct": 30, "on": False}}})
    assert code == 200 and out["rules"]["trim_conc"] == {"on": False, "pct": 30}
    assert call(st, "GET", "/api/rules")[1]["rules"]["trim_conc"]["pct"] == 30
    code, out = call(st, "PUT", "/api/rules", {"rules": {"trim_conc": {"pct": 500}}})
    assert code == 400 and "between" in out["error"]
    assert call(st, "GET", "/api/rules")[1]["rules"]["trim_conc"]["pct"] == 30


def test_per_stock_settings(st):
    code, out = call(st, "PUT", "/api/rules", {"stock": {"symbol": "TCS", "target_weight": 15, "review_price": 2500, "sector": " IT "}})
    assert out["stocks"]["TCS"] == {"target_weight": 15, "review_price": 2500, "sector": "IT"}
    assert call(st, "PUT", "/api/rules", {"stock": {"symbol": "TCS", "target_weight": 0}})[0] == 400
    assert call(st, "PUT", "/api/rules", {"stock": {"symbol": "TCS", "review_price": -1}})[0] == 400
    out = call(st, "PUT", "/api/rules", {"stock": {"symbol": "TCS", "target_weight": None, "review_price": None}})[1]
    assert out["stocks"]["TCS"]["target_weight"] is None and out["stocks"]["TCS"]["sector"] == "IT"


# ---------- the alerts feed end to end ----------
def healthy_facts(sym):
    q = [{"end": e, "revenue": r * CR, "net_income": n * CR, "operating_income": n * CR * 1.3, "eps": n / 10}
         for e, r, n in (("2025-06-30", 100, 10), ("2025-09-30", 105, 11), ("2025-12-31", 110, 12), ("2026-03-31", 115, 13), ("2026-06-30", 120, 14))]
    return {"symbol": sym, "status": "ok", "fetched": "2026-10-24", "quarters": q, "annual": [], "debt": [], "dividends": [], "splits": [],
            "closes": {"d": [], "c": []}, "reason": None}


def ctx_for(*syms, facts=None):
    d = {}
    for s in syms:
        d.update(detail(s))
    return {"detail": d, "facts": lambda items: {i[0]: (facts or healthy_facts)(i[0]) for i in items}}


def feed(st, ctx, uid="u1", sc=None):
    code, out = api_me.handle("GET", "/api/attention", "", b"", st, uid, sc or scan(), {"TCS", "INFY", "NIFTYBEES"}, ctx=ctx, today=TODAY)
    assert code == 200
    return out


def test_feed_is_empty_without_holdings(st):
    out = feed(st, ctx_for())
    assert out["alerts"] == [] and out["holdings"] == 0 and out["disclaimer"] == "For research and education. Not investment advice."


def test_a_drop_below_cost_with_intact_results_produces_a_consider_adding_alert(st):
    buy(st, "TCS", 10, 4000)             # price 3000 is 25% below cost
    out = feed(st, ctx_for("TCS"))
    a = next(x for x in out["alerts"] if x["rule"] == "add_drop")
    assert a["label"] == "Consider adding" and "25.0% below your average buy price" in a["reason"] and a["unseen"] is True
    assert out["unseen"] >= 1 and out["coverage"][0]["symbol"] == "TCS" and out["coverage"][0]["quarters"] == 5


def test_dismiss_hides_until_the_condition_changes(st):
    buy(st, "TCS", 10, 4000)
    a = next(x for x in feed(st, ctx_for("TCS"))["alerts"] if x["rule"] == "add_drop")
    code, _ = call(st, "POST", "/api/attention/state", {"key": a["key"], "fingerprint": a["fingerprint"], "action": "dismiss"})
    assert code == 200
    out = feed(st, ctx_for("TCS"))
    assert all(x["rule"] != "add_drop" for x in out["alerts"]) and out["hidden"] == 1
    # the price falls further: the condition changed, so it comes back
    deeper = scan({"TCS": 2400.0, "INFY": 1500.0, "NIFTYBEES": 250.0})
    out = feed(st, ctx_for("TCS"), sc=deeper)
    assert any(x["rule"] == "add_drop" for x in out["alerts"])


def test_dismissal_is_forgotten_once_the_condition_has_cleared(st):
    buy(st, "TCS", 10, 4000)
    a = next(x for x in feed(st, ctx_for("TCS"))["alerts"] if x["rule"] == "add_drop")
    call(st, "POST", "/api/attention/state", {"key": a["key"], "fingerprint": a["fingerprint"], "action": "dismiss"})
    recovered = scan({"TCS": 4200.0, "INFY": 1500.0, "NIFTYBEES": 250.0})
    feed(st, ctx_for("TCS"), sc=recovered)                              # condition is gone and was checked
    assert "TCS|add_drop" not in st.get_states("u1")
    assert any(x["rule"] == "add_drop" for x in feed(st, ctx_for("TCS"))["alerts"])     # a new drop shows again


def test_snooze_for_seven_days(st):
    buy(st, "TCS", 10, 4000)
    a = next(x for x in feed(st, ctx_for("TCS"))["alerts"] if x["rule"] == "add_drop")
    call(st, "POST", "/api/attention/state", {"key": a["key"], "fingerprint": a["fingerprint"], "action": "snooze", "days": 7})
    assert st.get_states("u1")["TCS|add_drop"]["until"] == "2026-10-31"
    assert all(x["rule"] != "add_drop" for x in feed(st, ctx_for("TCS"))["alerts"])
    code, out = call(st, "POST", "/api/attention/state", {"key": a["key"], "fingerprint": "x", "action": "snooze", "days": 0})
    assert code == 400


def test_marking_alerts_seen_clears_the_unseen_count(st):
    buy(st, "TCS", 10, 4000)
    out = feed(st, ctx_for("TCS"))
    seen = {a["key"]: a["fingerprint"] for a in out["alerts"]}
    call(st, "POST", "/api/attention/seen", {"seen": seen})
    again = feed(st, ctx_for("TCS"))
    assert again["unseen"] == 0 and len(again["alerts"]) == len(out["alerts"])


def test_unknown_alert_keys_and_actions_are_refused(st):
    assert call(st, "POST", "/api/attention/state", {"key": "../../etc", "fingerprint": "1", "action": "dismiss"})[0] == 400
    assert call(st, "POST", "/api/attention/state", {"key": "TCS|add_drop", "fingerprint": "1", "action": "explode"})[0] == 400


def test_etf_is_checked_on_price_rules_and_reports_missing_company_data(st):
    buy(st, "NIFTYBEES", 100, 400)
    ctx = {"detail": detail("NIFTYBEES", last=250.0, prev=249.0, s200=300.0),
           "facts": lambda items: {i[0]: fundamentals.get_facts(i[0], "NSE", True) for i in items}}
    out = feed(st, ctx)
    rules_ = {a["rule"] for a in out["alerts"]}
    assert "trim_loss" in rules_ and "add_drop" not in rules_
    assert any(g["rule"] == "add_drop" and "ETFs" in g["why"] for g in out["not_evaluated"])
    assert out["coverage"][0]["status"] == "none" and out["coverage"][0]["etf"] is True


def test_new_quarterly_results_appear_as_information_only_after_the_first_look(st):
    buy(st, "TCS", 10, 3000)
    feed(st, ctx_for("TCS"))                                           # first look: remembered silently
    assert st.get_seen("u1")["TCS"]["end"] == "2026-06-30"
    newer = healthy_facts("TCS")
    newer["quarters"].append({"end": "2026-09-30", "revenue": 125 * CR, "net_income": 15 * CR, "operating_income": 19 * CR, "eps": 1.5})
    out = feed(st, ctx_for("TCS", facts=lambda s: newer))
    a = next(x for x in out["alerts"] if x["rule"] == "info_results")
    assert a["label"] == "Info" and "2026-09-30" in a["reason"] and a["tone"] == "info"


def test_alert_failure_modes_do_not_break_the_feed(st):
    buy(st, "TCS", 10, 4000)
    broken = {"detail": {}, "facts": lambda items: {i[0]: {"symbol": i[0], "status": "error", "reason": "Could not reach Yahoo Finance (URLError).",
                                                              "quarters": [], "annual": [], "debt": [], "dividends": [], "splits": [], "closes": {"d": [], "c": []}, "fetched": "2026-10-24"} for i in items}}
    out = feed(st, broken)
    assert all(a["rule"] != "add_drop" for a in out["alerts"])
    assert any(g["rule"] == "add_drop" and "Yahoo" in g["why"] for g in out["not_evaluated"])
    assert out["coverage"][0]["status"] == "error"


def test_each_users_feed_is_their_own(st):
    buy(st, "TCS", 10, 4000, uid="u1")
    assert feed(st, ctx_for("TCS"), uid="u2")["alerts"] == []


# ---------- schema versions ----------
def test_migration_turns_old_holdings_into_opening_lots_and_keeps_a_backup(tmp_path):
    path = str(tmp_path / "users.db")
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE users(id TEXT PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'free', created TEXT);
      CREATE TABLE holdings(user_id TEXT NOT NULL, symbol TEXT NOT NULL, qty REAL NOT NULL, avg_price REAL NOT NULL, first_buy_date TEXT,
        source TEXT NOT NULL DEFAULT 'manual', PRIMARY KEY(user_id, symbol));
      INSERT INTO users VALUES('u1','free','2026-01-01');
      INSERT INTO holdings VALUES('u1','TCS',10,3500.5,'2026-01-02','manual');
      INSERT INTO holdings VALUES('u1','INFY',5,1450,NULL,'paste');""")
    db.commit()
    db.close()
    s = Store(path)
    h = {x["symbol"]: x for x in s.list_holdings("u1")}
    assert h["TCS"]["qty"] == 10 and h["TCS"]["avg_price"] == 3500.5 and h["TCS"]["first_buy_date"] == "2026-01-02"
    assert h["INFY"]["qty"] == 5 and h["INFY"]["first_buy_date"] is None
    assert os.path.exists(path + ".bak-v1")
    assert s.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert s.db.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == 0
    s.close()
    s2 = Store(path)                                                   # opening again must not duplicate anything
    assert len(s2.list_lots("u1")) == 2
    s2.close()
