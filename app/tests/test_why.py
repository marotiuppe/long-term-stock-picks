import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.portfolio import rules
from modules.stock import why

TODAY = datetime.date(2026, 10, 24)


def chart(n=1400, start=100.0, step=0.001, vol=2e6, end=TODAY):
    ds, d = [], end
    while len(ds) < n:
        if d.weekday() < 5:
            ds.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    ds.reverse()
    cs = [round(start * (1 + step) ** i * (1 + (0.01 if i % 2 else -0.01) * 0.3), 2) for i in range(n)]
    return {"d": ds, "o": cs, "h": cs, "l": cs, "c": cs, "v": [int(vol)] * n}


def q(end, rev, oi, ni, eps):
    return {"end": end, "revenue": rev, "operating_income": oi, "net_income": ni, "eps": eps}


def facts(ch=None, **kw):
    ch = ch or chart()
    f = {"symbol": "ACME", "status": "ok", "fetched": "2026-10-24", "reason": None,
         "quarters": [q("2025-09-30", 1000e7, 200e7, 100e7, 2.0), q("2025-12-31", 1050e7, 215e7, 105e7, 2.1), q("2026-03-31", 1100e7, 230e7, 112e7, 2.2),
                      q("2026-06-30", 1150e7, 250e7, 120e7, 2.4), q("2026-09-30", 1200e7, 270e7, 130e7, 2.6)],
         "annual": [{"end": "%d-03-31" % y, "eps": e, "net_income": n * 1e7, "revenue": r * 1e7} for y, e, n, r in
                    ((2023, 6.0, 300, 3000), (2024, 7.0, 360, 3400), (2025, 8.0, 420, 3900), (2026, 9.0, 450, 4300))],
         "debt": [{"end": "2025-09-30", "value": 500e7}, {"end": "2026-03-31", "value": 480e7}, {"end": "2026-09-30", "value": 450e7}],
         "dividends": [{"date": "2022-06-10", "amount": 2.0}, {"date": "2023-06-10", "amount": 2.5}, {"date": "2024-06-10", "amount": 3.0},
                       {"date": "2025-06-10", "amount": 3.5}, {"date": "2026-06-10", "amount": 4.0}],
         "splits": [], "closes": {"d": ch["d"], "c": ch["c"]}}
    f.update(kw)
    return f


STOCK = {"symbol": "ACME", "name": "Acme", "price": 150.0, "verdict": "BUY", "sma20": 148.0, "etf": False, "exchange": "NSE", "newsNet": 0}


def card(r, cid):
    return next(c for c in r["cards"] if c["id"] == cid)


def labels(c):
    return {x["label"]: x for x in c["rows"]}


def test_healthy_stock_has_all_cards_and_json():
    r = why.build("ACME", STOCK, chart(), chart(start=1000, step=0.0004), facts(), TODAY)
    json.dumps(r)
    assert [c["id"] for c in r["cards"]] == ["quality", "valuation", "price", "stability", "momentum"]
    assert card(r, "quality")["status"]["label"] == "Healthy"
    assert r["summary"].endswith("This describes the past and is not a prediction.")
    assert r["disclaimer"] == "For research and education. Not investment advice."
    for c in r["cards"]:
        assert c["status"]["icon"] and c["status"]["label"] and c["source"]
    assert any("Yahoo" in s["label"] for s in r["sources"])


def test_rupee_sign_is_never_doubled():
    r = why.build("ACME", STOCK, chart(), chart(start=1000, step=0.0004), facts(), TODAY)
    assert "₹₹" not in json.dumps(r, ensure_ascii=False)


def test_not_available_rows_are_explicit():
    r = why.build("ACME", STOCK, chart(), chart(), facts(), TODAY)
    roe = [x for x in card(r, "quality")["rows"] if "ROE" in x["label"]][0]
    assert roe["value"] == "Not available" and roe["na"] and "No licensed data source" in roe["note"]
    v = labels(card(r, "valuation"))
    assert v["P/E vs sector or peers"]["na"] and v["Price to book (P/B)"]["na"]
    assert labels(card(r, "stability"))["Promoter holding"]["value"] == "Not available"
    assert r["risksNa"][0]["label"] == "Pledged promoter shares" and r["risksNa"][0]["value"] == "Not available"


def test_quality_growth_numbers_come_from_fixture():
    r = why.build("ACME", STOCK, chart(), chart(), facts(), TODAY)
    rows = labels(card(r, "quality"))
    assert "+20.0%" in rows["Revenue (latest quarter)"]["value"]       # 1200 vs 1000
    assert "+30.0%" in rows["Net profit (latest quarter)"]["value"]    # 130 vs 100
    assert "3 fiscal years" in rows["Annual revenue"]["value"]
    assert "rose from 6.00 to 9.00" in rows["Earnings per share"]["value"]
    assert "down from" in rows["Total debt"]["value"]


def test_valuation_rule_labels():
    f = facts()
    c = card(why.build("ACME", STOCK, chart(), None, f, TODAY), "valuation")
    assert c["status"]["label"].endswith("vs own history") and "15%" in c["note"]
    now = float(re.search(r"([\d.]+) \(price", labels(c)["P/E now"]["value"]).group(1))
    assert abs(now - chart()["c"][-1] / 9.3) < 0.2     # ttm eps 2.1+2.2+2.4+2.6 is 9.3
    st, _ = rules.pe_stats(chart()["c"][-1], f)
    got = [why._valuation(st["avg"] * st["ttm_eps"] * k, f)[0]["status"]["label"] for k in (0.7, 1.05, 1.4)]
    assert got == ["Cheap vs own history", "Fair vs own history", "Expensive vs own history"]


def test_expensive_pe_is_a_risk_and_no_why_now():
    ch = chart()
    ch["c"][-1] = ch["c"][-1] * 3
    r = why.build("ACME", STOCK, ch, None, facts(), TODAY)
    assert any(x["id"] == "pe_high" for x in r["risks"])
    assert r["whyNow"] == {"fired": False, "text": why.DEFAULT_WHY_NOW}


def test_falling_margins_flagged():
    f = facts(quarters=[q("2025-09-30", 1000e7, 300e7, 150e7, 3.0), q("2025-12-31", 1000e7, 280e7, 140e7, 2.8), q("2026-03-31", 990e7, 250e7, 120e7, 2.4),
                        q("2026-06-30", 980e7, 220e7, 100e7, 2.0), q("2026-09-30", 960e7, 190e7, 80e7, 1.6)])
    r = why.build("ACME", STOCK, chart(), None, f, TODAY)
    assert {"fund_margin", "fund_profit", "fund_revenue"} <= {x["id"] for x in r["risks"]}
    assert card(r, "quality")["status"]["key"] == "warn"
    assert r["noRisks"] is None


def test_debt_rising_and_high():
    f = facts(debt=[{"end": "2025-09-30", "value": 2000e7}, {"end": "2026-03-31", "value": 2500e7}, {"end": "2026-09-30", "value": 3000e7}])
    ids = {x["id"] for x in why.build("ACME", STOCK, chart(), None, f, TODAY)["risks"]}
    assert "fund_debt" in ids and "debt_high" in ids


def test_etf_state_is_price_only():
    ef = {"status": "none", "reason": "ETFs and funds have no company results.", "quarters": [], "annual": [], "debt": [], "dividends": [], "closes": {"d": [], "c": []}, "fetched": "2026-10-24"}
    r = why.build("GOLDBEES", dict(STOCK, etf=True), chart(), chart(), ef, TODAY)
    assert r["etf"] and [c["id"] for c in r["cards"]] == ["price", "momentum"]
    assert "ETF" in r["summary"]
    assert any("Company-based" in x for x in r["limits"])


def test_no_fundamentals_stock_shows_na_cards():
    r = why.build("ACME", STOCK, chart(), chart(), {"status": "error", "reason": "Could not reach Yahoo Finance (URLError)."}, TODAY)
    c = card(r, "quality")
    assert c["status"]["key"] == "na" and "Could not reach Yahoo" in c["headline"]
    assert card(r, "price")["status"]["key"] != "na"


def test_missing_nifty_and_short_history():
    r = why.build("ACME", STOCK, chart(), None, facts(), TODAY)
    assert "Nifty 50 comparison not available" in labels(card(r, "price"))["1-year return"]["note"]
    r = why.build("ACME", STOCK, chart(n=100), chart(n=100), facts(), TODAY)
    rows = labels(card(r, "price"))
    assert rows["1-year return"]["na"] and rows["5-year return"]["na"]
    m = card(r, "momentum")
    assert m["status"]["key"] == "na" and m["rows"][0]["value"] == "Not available"
    r = why.build("ACME", STOCK, chart(n=10), None, None, TODAY)
    assert card(r, "price")["status"]["key"] == "na"
    assert r["summary"].endswith("not a prediction.")


def test_returns_vs_nifty_exact():
    c, n = chart(), chart(start=1000, step=0.0004)
    row = labels(card(why.build("ACME", STOCK, c, n, facts(), TODAY), "price"))["1-year return"]
    assert "Nifty 50 over the same dates" in row["note"]
    a = [x for x in zip(c["d"], c["c"]) if x[0] <= why._ago(c["d"][-1], 1)][-1][1]
    assert row["value"] == why._p((c["c"][-1] / a - 1) * 100)


def test_risks_from_price_data():
    ch = chart()
    n = len(ch["c"])
    ch["c"] = [100.0 * (0.998 ** i) for i in range(n)]
    ch["v"] = [100] * n
    ids = {x["id"] for x in why.build("ACME", dict(STOCK, newsNet=-3), ch, None, None, TODAY)["risks"]}
    assert {"liquidity", "drawdown", "below200", "news"} <= ids


def test_no_risk_message_not_safe():
    ch = chart(step=0.0002)
    r = why.build("ACME", STOCK, ch, None, facts(ch), TODAY)
    assert r["risks"] == [] and "limited" in r["noRisks"] and "safe" not in r["noRisks"].lower()


def test_why_now_cases():
    r = why.build("ACME", dict(STOCK, verdict="WAIT", price=100.0, sma20=101.0), chart(), None, facts(), TODAY)
    assert r["whyNow"]["fired"] and "20-day average" in r["whyNow"]["text"]
    r = why.build("ACME", dict(STOCK, verdict="WAIT", price=100.0, sma20=130.0), chart(), None, None, TODAY)
    assert r["whyNow"]["text"] == why.DEFAULT_WHY_NOW
    ch = chart()
    ch["c"] = [200 - i * 0.05 for i in range(len(ch["c"]))]
    r = why.build("ACME", dict(STOCK, verdict="BUY"), ch, None, None, TODAY)
    assert "52-week low" in r["whyNow"]["text"]
    # the same near-the-low price on a Downtrend call is not offered as a reason to buy now
    r = why.build("ACME", dict(STOCK, verdict="DOWNTREND"), ch, None, None, TODAY)
    assert r["whyNow"]["text"] == why.DEFAULT_WHY_NOW and r["verdict"] == "DOWNTREND"


def test_stability_dividend_years():
    row = labels(card(why.build("ACME", STOCK, chart(), None, facts(), TODAY), "stability"))
    v = row["Dividend payments per year"]["value"]
    assert "2022: 1" in v and "2026: 1 (so far)" in v
    assert row["Latest dividend"]["value"].endswith("on 10 Jun 2026")
    assert row["Years of positive EPS"]["value"].startswith("4 of 4")


def test_numbers_in_strings_trace_to_fixture():
    """Every crore figure printed in the quality card must be one of the fixture's reported numbers."""
    f = facts()
    r = why.build("ACME", STOCK, chart(), None, f, TODAY)
    allowed = set()
    for x in f["quarters"]:
        for k in ("revenue", "operating_income", "net_income"):
            allowed.add(round(x[k] / 1e7))
    for x in f["annual"]:
        allowed.add(round(x["net_income"] / 1e7))
        allowed.add(round(x["revenue"] / 1e7))
    for x in f["debt"]:
        allowed.add(round(x["value"] / 1e7))
    txt = json.dumps(card(r, "quality")["rows"], ensure_ascii=False)
    found = re.findall(r"([\d,]+(?:\.\d)?) cr", txt)
    assert found
    for m in found:
        assert round(float(m.replace(",", ""))) in allowed, m


# ---------- /api/why ----------
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import server


@pytest.fixture
def srv():
    server.STATE.update(t=time.time(), running=False, error=None, data={"generated": "t", "stocks": [dict(STOCK)], "buyDate": "2026-10-26"})
    server.DETAIL.clear()
    server.DETAIL["ACME"] = {"why": []}
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1]
    s.shutdown()
    server.STATE.update(data=None, t=0, error=None)
    server.DETAIL.clear()


def _get(url):
    try:
        r = urllib.request.urlopen(url, timeout=5)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None


def test_api_why_route(srv, monkeypatch):
    monkeypatch.setattr(server, "chart_payload", lambda s: chart())
    monkeypatch.setattr(server.fundamentals, "get_facts", lambda *a, **k: facts())
    assert _get(srv + "/api/why")[0] == 400 and _get(srv + "/api/why?sym=a%20b")[0] == 400
    assert _get(srv + "/api/why?sym=%5ENSEI")[0] == 400
    assert _get(srv + "/api/why?sym=EVIL")[0] == 404
    code, j = _get(srv + "/api/why?sym=ACME")
    assert code == 200 and j["symbol"] == "ACME" and len(j["cards"]) == 5 and "priceError" not in j


def test_api_why_survives_missing_history(srv, monkeypatch):
    monkeypatch.setattr(server, "chart_payload", lambda s: None)
    monkeypatch.setattr(server.fundamentals, "get_facts", lambda *a, **k: {"status": "error", "reason": "Could not reach Yahoo Finance (URLError)."})
    code, j = _get(srv + "/api/why?sym=ACME")
    assert code == 200 and j["priceError"] and any(c["id"] == "price" and c["status"]["key"] == "na" for c in j["cards"])
