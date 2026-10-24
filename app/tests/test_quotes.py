"""Holdings the scan filters out (under Rs 20, thin trading or history) are still valued at their last close."""
import datetime, json, os, sys, threading, time, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core import api_me
from core.store import Store


def bars(*closes):
    d0 = datetime.date(2026, 10, 20)
    return [(d0 + datetime.timedelta(days=i), c, c, c, c, 1000) for i, c in enumerate(closes)]


def test_quote_row_keeps_last_and_previous_close():
    q = server.quote_row(bars(1.60, 1.55), "thin")
    assert q == {"price": 1.55, "prev": 1.6, "asof": "2026-10-21", "why": "thin"}
    assert server.quote_row(bars(5.0), "illiquid")["prev"] is None


SCAN = {"stocks": [{"symbol": "SUZLON", "name": "Suzlon Energy Limited", "price": 37.40, "asof": "2026-10-23", "verdict": "WATCH", "score": 1, "stop": 30.0}],
        "quotes": {"SBL": {"price": 1.55, "prev": 1.69, "asof": "2026-10-23", "why": "thin"},
                   "TATSILV": {"price": 18.69, "prev": 19.31, "asof": "2026-10-23", "why": "thin"},
                   "IDEA": {"price": 11.36, "prev": 11.53, "asof": "2026-10-23", "why": "thin"},
                   "SUZLON": {"price": 99.0, "prev": 99.0, "asof": "2026-10-01", "why": "thin"}}}   # a scanned stock is never replaced by a quote


def test_stocks_view_adds_quote_only_entries_without_overriding_scanned_ones():
    s = api_me._stocks(SCAN)
    assert s["SUZLON"]["price"] == 37.40 and not s["SUZLON"].get("quoteOnly")
    assert s["SBL"]["quoteOnly"] is True and s["SBL"]["price"] == 1.55 and s["SBL"]["verdict"] is None and s["SBL"]["whyNotScanned"] == "thin"


def test_values_match_the_brokers_figures_for_unscanned_holdings():
    """Quantities, average prices and market prices taken from the Groww screenshot: current values 661.85, 4336.08 and 863.36."""
    st = Store(":memory:")
    for sym, q, avg in (("SBL", 427, 2.32), ("TATSILV", 232, 23.55), ("IDEA", 76, 13.51), ("SUZLON", 1, 58.47), ("DHARAN", 1050, 0.19)):
        st.upsert_holding("u", sym, q, avg, source="groww")
    me = api_me.me_payload(st, "u", SCAN)
    rows = {r["symbol"]: r for r in me["positions"]}
    assert rows["SBL"]["value"] == 661.85 and rows["TATSILV"]["value"] == 4336.08 and rows["IDEA"]["value"] == 863.36
    assert rows["SBL"]["invested"] == 990.64 and rows["SBL"]["unrealized"] == pytest.approx(-328.79, abs=0.01)
    assert rows["SBL"]["quote_only"] is True and rows["SBL"]["why_not_scanned"] == "thin" and rows["SUZLON"]["quote_only"] is False
    assert rows["SBL"]["day_abs"] == pytest.approx(427 * (1.55 - 1.69), abs=0.01) and rows["SBL"]["call"] is None
    assert rows["DHARAN"]["price"] is None and me["summary"]["unpriced"] == ["DHARAN"]       # no price anywhere: stays unpriced, never guessed
    assert me["summary"]["value"] == pytest.approx(661.85 + 4336.08 + 863.36 + 37.40, abs=0.01)


def test_alerts_and_watchlist_cope_with_quote_only_stocks():
    st = Store(":memory:")
    st.upsert_holding("u", "SBL", 427, 2.32)
    st.add_watch("u", "IDEA")
    me = api_me.me_payload(st, "u", SCAN)
    assert me["watchlist"] == [{"symbol": "IDEA", "price": 11.36, "call": None}]
    assert [h["symbol"] for h in me["holdings"]] == ["SBL"] and me["holdings"][0]["value"] == 661.85
    assert me["holdings"][0]["stop"] is None and "no data" not in me["holdings"][0]["flags"]
    assert api_me.me_payload(st, "u", SCAN)["unread"] == 0         # running it twice raises no alert from a stock with no call


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setitem(server.STATE, "running", True)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown(); s.server_close()


def test_scan_api_does_not_send_the_quotes(base, monkeypatch):
    stock = {"symbol": "ZZ", "asof": "2026-10-23", "verdict": "WATCH", "score": 1, "forecast": {}}
    monkeypatch.setitem(server.STATE, "data", {"stocks": [stock], "quotes": {"SBL": {"price": 1.55}}, "trackReport": "x", "track": {}})
    monkeypatch.setitem(server.STATE, "t", time.time())
    body = urllib.request.urlopen(base + "/api/scan", timeout=5).read()
    assert b"quotes" not in body and b"SBL" not in body and b'"ZZ"' in body
