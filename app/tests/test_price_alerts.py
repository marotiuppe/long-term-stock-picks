import datetime, json, os, shutil, subprocess, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.portfolio import alerts
from core import api_me
from core.store import Store, PRICE_ALERT_MAX

U = {"TCS", "INFY", "SBIN"}
TODAY = datetime.date(2026, 10, 24)


def scan(price=3200.5, hi52=4000.0, asof="2026-10-23"):
    return {"generated": "x", "stocks": [{"symbol": "TCS", "price": price, "hi52": hi52, "asof": asof, "verdict": "BUY"},
                                          {"symbol": "INFY", "price": None, "hi52": None, "asof": asof}]}


def h(st, uid, method, path, body=None, query="", sc=None):
    return api_me.handle(method, path, query, json.dumps(body).encode() if body is not None else b"", st, uid, sc or scan(), U, today=TODAY)


def pa_alerts(s, uid):
    return [a for a in s.list_alerts(uid) if a["kind"] == "price_alert"]


def test_store_crud_isolation_and_validation():
    s = Store(":memory:")
    a = s.add_price_alert("u1", "tcs", "below", 3300)
    s.add_price_alert("u2", "TCS", "below", 3300)       # same level, other user: fine
    assert [r["id"] for r in s.list_price_alerts("u1")] == [a]
    assert s.list_price_alerts("u1")[0]["active"] is True
    with pytest.raises(ValueError):
        s.add_price_alert("u1", "TCS", "below", 3300)   # duplicate
    for bad in [("TCS", "sideways", 5), ("TCS", "below", 0), ("TCS", "below", "abc"), ("TCS", "off_high", 0.5),
                ("TCS", "off_high", 91), ("bad sym", "below", 5), ("TCS", "below", -3)]:
        with pytest.raises(ValueError):
            s.add_price_alert("u1", *bad)
    assert not s.delete_price_alert("u2", a)             # not theirs
    assert not s.set_price_alert_active("u2", a, False)
    assert s.delete_price_alert("u1", a)


def test_limit_of_20_active():
    s = Store(":memory:")
    for i in range(PRICE_ALERT_MAX):
        s.add_price_alert("u", "TCS", "below", 100 + i)
    with pytest.raises(ValueError):
        s.add_price_alert("u", "TCS", "below", 999)
    s.add_price_alert("v", "TCS", "below", 999)


def test_export_and_delete_include_alerts():
    s = Store(":memory:")
    s.add_price_alert("u", "TCS", "above", 5000)
    assert s.export_user("u")["price_alerts"][0]["value"] == 5000
    s.delete_user("u")
    assert s.list_price_alerts("u") == []


def test_api_flow_and_unknown_symbol():
    s = Store(":memory:")
    code, r = h(s, "u", "POST", "/api/price-alerts", {"symbol": "TCS", "kind": "below", "value": 3300})
    assert code == 200 and r["alerts"][0]["status"] == "waiting" and r["alerts"][0]["price"] == 3200.5
    assert h(s, "u", "POST", "/api/price-alerts", {"symbol": "ZZZZ", "kind": "below", "value": 5})[0] == 400
    assert h(s, "u", "POST", "/api/price-alerts", {"symbol": "TCS", "kind": "below", "value": True})[0] == 400
    assert h(s, "u", "POST", "/api/price-alerts", {"symbol": "TCS", "kind": "below", "value": 3300})[0] == 400
    assert h(s, "u", "GET", "/api/price-alerts", query="sym=INFY")[1]["alerts"] == []
    assert h(s, "other", "GET", "/api/price-alerts")[1]["alerts"] == []
    aid = r["id"]
    assert h(s, "other", "DELETE", "/api/price-alerts", query="id=%d" % aid)[0] == 404
    assert h(s, "u", "PUT", "/api/price-alerts", {"id": aid, "active": "yes"})[0] == 400
    assert h(s, "u", "PUT", "/api/price-alerts", {"id": aid, "active": False})[1]["alerts"][0]["status"] == "paused"
    assert h(s, "u", "PUT", "/api/price-alerts", {"id": aid, "active": True})[1]["alerts"][0]["status"] == "waiting"
    assert h(s, "u", "DELETE", "/api/price-alerts")[0] == 400
    assert h(s, "u", "DELETE", "/api/price-alerts", query="id=%d" % aid)[1]["alerts"] == []


def test_fires_once_per_scan_date_then_rearm():
    s = Store(":memory:")
    aid = s.add_price_alert("u", "TCS", "below", 3300)
    api_me.me_payload(s, "u", scan(), today=TODAY)
    pa = pa_alerts(s, "u")
    assert len(pa) == 1 and pa[0]["key"] == "pa:%d:2026-10-23" % aid
    assert "₹3,200.50" in pa[0]["message"] and "₹3,300 level" in pa[0]["message"] and "not a recommendation" in pa[0]["message"]
    assert s.list_price_alerts("u")[0]["last_fired"] == "2026-10-23"
    api_me.me_payload(s, "u", scan(), today=TODAY)                       # same scan again: nothing new
    api_me.me_payload(s, "u", scan(asof="2026-10-24"), today=TODAY)       # later scan, still reached: stays fired until re-armed
    assert len(pa_alerts(s, "u")) == 1
    assert h(s, "u", "PUT", "/api/price-alerts", {"id": aid, "active": True})[1]["alerts"][0]["status"] == "waiting"
    api_me.me_payload(s, "u", scan(asof="2026-10-24"), today=TODAY)
    assert len(pa_alerts(s, "u")) == 2


def test_not_fired_for_missing_price_or_unmet_or_paused():
    s = Store(":memory:")
    s.add_price_alert("u", "INFY", "below", 100)            # price None
    s.add_price_alert("u", "SBIN", "below", 100)            # not in scan
    s.add_price_alert("u", "TCS", "above", 5000)            # not met
    pid = s.add_price_alert("u", "TCS", "below", 3300)
    s.set_price_alert_active("u", pid, False)               # paused
    s.add_price_alert("u", "TCS", "off_high", 30)           # 3200.5 vs 4000*.7=2800: not met
    api_me.me_payload(s, "u", scan(), today=TODAY)
    assert pa_alerts(s, "u") == []


def test_kinds_and_hit_rules():
    st = {"price": 3000.0, "hi52": 4000.0}
    assert alerts.price_alert_hit("below", 3000, st) and alerts.price_alert_hit("above", 3000, st)
    assert alerts.price_alert_hit("off_high", 25, st) and not alerts.price_alert_hit("off_high", 26, st)
    assert not alerts.price_alert_hit("off_high", 10, {"price": 3000.0})
    assert not alerts.price_alert_hit("below", 5000, None)
    rows = [{"id": 7, "symbol": "TCS", "kind": "off_high", "value": 25, "active": True, "last_fired": None}]
    (aid, a), = alerts.evaluate_price_alerts(rows, {"TCS": dict(st, asof="2026-10-23")}, TODAY)
    assert aid == 7 and "25% below its 52-week high of ₹4,000.00" in a["message"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_helpers():
    js = os.path.join(os.path.dirname(__file__), "..", "modules", "stock", "pricealerts.js").replace("\\", "/")
    code = ("const h=require(%s);console.log(JSON.stringify([h.validate('off_high','95'),h.validate('below','3,300'),h.validate('below',''),"
            "h.validate('x','1'),h.describe('above',3300),h.statusOf({status:'waiting'}).text,h.statusOf({status:'reached',last_fired:'2026-10-23'}).text]))" % json.dumps(js))
    out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert out == ["Enter a percentage from 1 to 90.", "", "Enter a number.", "Choose what to watch for.",
                   "Price at or above ₹3,300", "Waiting", "Reached on 2026-10-23"]
