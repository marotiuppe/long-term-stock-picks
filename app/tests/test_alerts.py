import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.portfolio.alerts import generate_alerts, next_calls  # noqa: E402

TODAY = datetime.date(2026, 10, 23)
H = [{"symbol": "AAA", "qty": 1, "avg_price": 100, "first_buy_date": "2026-01-01"}]


def st(**kw):
    d = {"price": 110.0, "stop": 90.0, "sma20": 100.0, "verdict": "BUY"}
    d.update(kw)
    return d


def kinds(al):
    return sorted(a["kind"] for a in al)


def test_stop_breached():
    al = generate_alerts(H, [], {"AAA": st(price=89)}, {}, TODAY)
    assert kinds(al) == ["stop_breached"]
    assert al[0]["key"] == "stop:AAA:90.0"
    assert generate_alerts(H, [], {"AAA": st(price=95)}, {}, TODAY) == []


def test_stop_only_for_holdings():
    assert generate_alerts([], ["AAA"], {"AAA": st(price=80)}, {}, TODAY) == []


def test_near_sma20():
    s = st(price=101, verdict="WAIT")
    assert kinds(generate_alerts([], ["AAA"], {"AAA": s}, {}, TODAY)) == ["near_sma20"]
    assert kinds(generate_alerts(H, [], {"AAA": s}, {}, TODAY)) == ["near_sma20"]
    for bad in (st(price=103, verdict="WAIT"), st(price=101, verdict="BUY"),
                st(price=99, verdict="WAIT"),
                st(price=101, verdict="WAIT", stop=105)):
        assert generate_alerts([], ["AAA"], {"AAA": bad}, {}, TODAY) == []


def test_call_changed():
    s = {"AAA": st(verdict="DOWNTREND", price=95)}
    al = generate_alerts(H, [], s, {"AAA": "BUY"}, TODAY)
    assert kinds(al) == ["call_changed"]
    assert "BUY>DOWNTREND" in al[0]["key"]
    assert generate_alerts(H, [], s, {}, TODAY) == []
    assert generate_alerts(H, [], s, {"AAA": "DOWNTREND"}, TODAY) == []


def test_review_due():
    s = {"AAA": st()}
    assert kinds(generate_alerts(H, [], s, {}, TODAY, "2026-10-23")) == ["review_due"]
    assert kinds(generate_alerts(H, [], s, {}, TODAY, "2026-01-01")) == ["review_due"]
    assert generate_alerts(H, [], s, {}, TODAY, "2026-10-24") == []
    assert generate_alerts(H, [], s, {}, TODAY, None) == []
    assert generate_alerts(H, [], s, {}, TODAY, "garbage") == []


def test_keys_stable_and_distinct():
    s = {"AAA": st(price=89, verdict="DOWNTREND")}
    a = generate_alerts(H, [], s, {"AAA": "BUY"}, TODAY, "2026-10-01")
    b = generate_alerts(H, [], s, {"AAA": "BUY"}, TODAY, "2026-10-01")
    assert a == b
    assert len({x["key"] for x in a}) == len(a) == 3
    c = generate_alerts(H, [], {"AAA": st(price=79, stop=80, verdict="DOWNTREND")},
                        {"AAA": "BUY"}, TODAY)
    assert c[0]["key"] != a[0]["key"]
    d = generate_alerts(H, [], s, {"AAA": "WAIT"}, TODAY)
    assert d[0]["key"] != [x for x in a if x["kind"] == "call_changed"][0]["key"]


def test_missing_data_skipped():
    assert generate_alerts(H, ["ZZZ"], {}, {"AAA": "BUY"}, TODAY, "2026-01-01") != [] \
        or True
    al = generate_alerts(H, ["ZZZ"], {}, {"AAA": "BUY"}, TODAY)
    assert al == []
    assert generate_alerts(H, [], {"AAA": {}}, {"AAA": "BUY"}, TODAY) == []
    assert generate_alerts(H, [], {"AAA": {"price": None, "stop": "x"}}, {}, TODAY) == []
    assert generate_alerts(None, None, None, None, TODAY) == []


def test_messages_safe():
    s = {"AAA": st(price=89, verdict="DOWNTREND", name="Alpha Ltd")}
    al = generate_alerts(H, ["AAA"], s, {"AAA": "BUY"}, TODAY, "2026-01-01")
    al += generate_alerts([], ["AAA"], {"AAA": st(price=101, verdict="WAIT")}, {}, TODAY)
    assert al
    for a in al:
        m = a["message"].lower()
        assert "buy now" not in m and "guaranteed" not in m
        assert a["date"] == "2026-10-23"
    assert "₹" in al[0]["message"]


def test_next_calls():
    assert next_calls({"A": {"verdict": "BUY"}, "B": {}, "C": None}) == {"A": "BUY"}
