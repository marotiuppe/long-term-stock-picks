import json, os, shutil, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

APP = os.path.join(os.path.dirname(__file__), "..")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def yahoo(close, adj=None, opens=None):
    n = len(close)
    adj = adj or close
    return {"chart": {"result": [{"timestamp": [1760000000 + i * 86400 for i in range(n)],
                                  "indicators": {"quote": [{"open": opens or close,
                                                            "high": [None if c is None else c + 2 for c in close],
                                                            "low": [None if c is None else c - 2 for c in close], "close": close,
                                                            "volume": [1000 + i for i in range(n)]}],
                                                 "adjclose": [{"adjclose": adj}]}}]}}


# ---------- fetch_ohlc ----------
def test_ohlc_is_scaled_to_the_adjusted_close_and_skips_gaps(monkeypatch):
    close = [100.0, None, 200.0]
    payload = yahoo(close, adj=[50.0, None, 100.0], opens=[98.0, None, 190.0])
    payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"][2] = None
    monkeypatch.setattr(server, "get_json", lambda url: payload)
    out = server.fetch_ohlc("TCS")
    assert len(out["d"]) == 2                                   # the bar with no prices is skipped
    assert out["c"] == [50.0, 100.0] and out["o"] == [49.0, 95.0]   # open follows the same 0.5 factor as the close
    assert out["h"] == [51.0, 101.0] and out["l"] == [49.0, 99.0] and out["v"] == [1000, 0]


def test_ohlc_urls_use_daily_bars_over_the_whole_history(monkeypatch):
    urls = []
    monkeypatch.setattr(server, "get_json", lambda url: urls.append(url) or yahoo([10.0, 11.0]))
    server.fetch_ohlc("TCS")
    server.fetch_ohlc("539999", "BSE")
    server.fetch_ohlc("M&M")
    server.fetch_ohlc("^NSEI")
    paths = [u.split("/chart/")[1].split("?")[0] for u in urls]
    assert paths == ["TCS.NS", "539999.BO", "M%26M.NS", "%5ENSEI"]
    assert all("period1=0" in u and "interval=1d" in u and "range=" not in u for u in urls)   # range=max would go monthly


def test_ohlc_unknown_ticker_is_none_without_retry(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    monkeypatch.setattr(server, "get_json", fake)
    assert server.fetch_ohlc("NOPE") is None and len(calls) == 1


def test_chart_payload_caches_and_uses_the_scanned_exchange(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "fetch_ohlc", lambda s, ex="NSE": seen.append((s, ex)) or {"d": ["2026-10-23"], "c": [1.0]})
    monkeypatch.setattr(server, "_charts", {})
    server.STATE.update(data={"stocks": [{"symbol": "SMPLMILL", "exchange": "BSE"}, {"symbol": "TCS", "exchange": "NSE"}]})
    try:
        assert server.chart_payload("SMPLMILL")["c"] == [1.0]
        server.chart_payload("SMPLMILL")
        server.chart_payload("TCS")
        assert seen == [("SMPLMILL", "BSE"), ("TCS", "NSE")]    # second call served from memory
    finally:
        server.STATE.update(data=None)


def test_chart_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(server, "CHART_MAX", 3)
    monkeypatch.setattr(server, "_charts", {})
    monkeypatch.setattr(server, "fetch_ohlc", lambda s, ex="NSE": {"d": ["x"], "c": [1.0]})
    for s in "ABCDE":
        server.chart_payload(s)
        time.sleep(0.002)
    assert len(server._charts) == 3 and "E" in server._charts and "A" not in server._charts


# ---------- endpoint ----------
@pytest.fixture
def srv(monkeypatch):
    server.STATE.update(t=time.time(), running=False, error=None, data={"generated": "t", "stocks": [], "buyDate": "2026-10-26"})
    server.DETAIL.clear()
    server.DETAIL["TCS"] = {"why": []}
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    server.STATE.update(data=None, t=0, error=None)
    server.DETAIL.clear()


def status(url):
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_chart_endpoint_validates_and_is_not_an_open_proxy(srv, monkeypatch):
    asked = []
    monkeypatch.setattr(server, "chart_payload", lambda s: asked.append(s) or {"d": ["2026-10-23"], "o": [1], "h": [1], "l": [1], "c": [1], "v": [1]})
    assert status(srv + "/api/chart") == 400 and status(srv + "/api/chart?sym=a%20b") == 400
    assert status(srv + "/api/chart?sym=EVIL") == 404 and asked == []     # not a symbol the scan lists
    assert json.load(urllib.request.urlopen(srv + "/api/chart?sym=TCS"))["c"] == [1]
    assert status(srv + "/api/chart?sym=%5ENSEI") == 200 and asked == ["TCS", "^NSEI"]   # the benchmark is allowed


def test_chart_endpoint_502_when_yahoo_has_nothing(srv, monkeypatch):
    monkeypatch.setattr(server, "chart_payload", lambda s: None)
    assert status(srv + "/api/chart?sym=TCS") == 502


def test_chart_js_is_served_and_page_loads_it(srv):
    r = urllib.request.urlopen(srv + "/assets/js/chart.js")
    assert r.status == 200 and "javascript" in r.headers["Content-Type"] and b"PriceChart" in r.read()
    assert b'src="/assets/js/chart.js"' in urllib.request.urlopen(srv + "/index.html").read()


# ---------- chart.js helpers, run under node ----------
def node(expr):
    code = f"const C=require({json.dumps(os.path.join(APP, 'assets', 'js', 'chart.js'))})._t;process.stdout.write(JSON.stringify({expr}))"
    return json.loads(subprocess.run([NODE, "-e", code], capture_output=True, encoding="utf-8", check=True).stdout)


@needs_node
def test_sma_waits_for_a_full_window():
    assert node("C.sma([1,2,3,4,5],3)") == [None, None, 2, 3, 4]


@needs_node
def test_bollinger_collapses_on_a_flat_series_and_widens_with_noise():
    flat = node("C.bollinger(Array(30).fill(10),20,2)")
    assert flat["up"][25] == flat["lo"][25] == flat["mid"][25] == 10 and flat["up"][5] is None
    noisy = node("C.bollinger(Array.from({length:30},(_,i)=>i%2?12:8),20,2)")
    assert noisy["mid"][25] == 10 and noisy["up"][25] == pytest.approx(14) and noisy["lo"][25] == pytest.approx(6)





@needs_node
def test_align_carries_the_last_value_forward_and_is_null_before_the_first():
    assert node("C.align(['1','2','3','4'],{d:['2','4'],c:[20,40]})") == [None, 20, 20, 40]


@needs_node
def test_range_windows_and_chip_matching():
    assert node("C.rangeWindow('1M',1000)") == [979, 999] and node("C.rangeWindow('Max',1000)") == [0, 999]
    assert node("C.rangeWindow('1Y',100)") == [0, 99]                               # short history: everything
    assert node("C.matchRange([748,999],1000)") == "1Y" and node("C.matchRange([0,999],1000)") == "Max"
    assert node("C.matchRange([500,999],1000)") == "" and node("C.matchRange([748,900],1000)") == ""   # hand zoom, or not at the right edge
    assert node("C.matchRange([0,99],100)") == "Max"                               # ranges longer than the history are Max


@needs_node
def test_zoom_window_stays_inside_the_data_and_keeps_a_minimum():
    assert node("C.zoomWindow([0,99],1000,2)") == [0, 199] and node("C.zoomWindow([900,999],1000,2)") == [800, 999]
    z = node("C.zoomWindow([100,199],1000,.5)")
    assert z[1] - z[0] + 1 == 50 and 100 <= z[0] and z[1] <= 199
    assert node("C.zoomWindow([10,14],1000,.1)") == [10, 14]                       # never below 5 bars
    assert node("C.zoomWindow([0,9],10,2)") == [0, 9]


@needs_node
def test_52_week_window_uses_the_last_252_bars_only():
    r = node("C.window52([...Array(300).fill(10),50],[...Array(300).fill(5),1],252)")
    assert r["hi"] == 50 and r["lo"] == 1 and r["ihi"] == 300
    old = node("C.window52([99,...Array(260).fill(10)],[0,...Array(260).fill(5)],252)")   # the spike is older than 252 bars
    assert old["hi"] == 10 and old["lo"] == 5


@needs_node
def test_rebase_and_percent_since_start():
    assert node("C.rebase([null,50,100,75],0)") == [None, 100, 200, 150]           # base is the first value at or after the start
    assert node("C.rebase([50,100,75],1)") == [50, 100, 75]
    assert node("C.pctSince([100,110,90],1,0)") == pytest.approx(10) and node("C.pctSince([100,110,90],2,0)") == pytest.approx(-10)


@needs_node
def test_formatting_helpers():
    assert node("[C.vol(92243),C.vol(1443950),C.vol(25000000)]") == ["92,243", "14.4 lakh", "2.50 crore"]
    assert node("[C.compactVol(500),C.compactVol(25000),C.compactVol(250000),C.compactVol(25000000)]") == ["500", "25K", "2.5L", "2.5Cr"]
    assert node("[C.signed(1.5),C.signed(-1.5)]") == ["+1.50", "−1.50"]


MODEL = """(()=>{const n=300,d=Array.from({length:n},(_,i)=>'2025-'+String(1+Math.floor(i/28)).padStart(2,'0')+'-'+String(1+i%28).padStart(2,'0'));
const c=Array.from({length:n},(_,i)=>100+i%17+i*.1);
const D={d,o:c.map(x=>x-1),h:c.map(x=>x+2),l:c.map(x=>x-2),c,v:c.map((_,i)=>1000+i)};
const ind={sma50:C.sma(c,50),sma200:C.sma(c,200),bb:C.bollinger(c,20,2)};
const on=Object.assign({sma50:false,sma200:false,hl52:false,bb:false,vol:true,cmp:false},__ON__);
return {sym:'TCS',data:D,ind,win:[n-63,n-1],W:__W__,H:340,prefs:{type:__TYPE__,range:'3M',on},nal:__CMP__?C.align(d,{d,c:c.map(x=>x*2)}):null,my:__MY__}})()"""
COLORS = "{card:'#fff',tx:'#000',mu:'#666',bd:'#ddd',ac:'#0a8',up:'#080',dn:'#a00',amber:'#b60',s200:'#999',blue:'#668',font:'x'}"


def option(expr, on="{}", typ="area", cmp="false", my="null", w=800):
    model = (MODEL.replace("__ON__", on).replace("__TYPE__", json.dumps(typ)).replace("__CMP__", cmp)
             .replace("__MY__", my).replace("__W__", str(w)))
    return node(f"(()=>{{const m={model};const o=C.buildOption(m,{COLORS});return {expr}}})()")


@needs_node
def test_option_defaults_line_with_volume_and_two_zoom_controls():
    o = option("o")
    assert [s["id"] for s in o["series"]] == ["px", "vol"] and o["series"][0]["type"] == "line"
    assert len(o["grid"]) == 2 and len(o["xAxis"]) == 2
    assert [z["type"] for z in o["dataZoom"]] == ["inside", "slider"]
    assert all(z["startValue"] == 237 and z["endValue"] == 299 for z in o["dataZoom"])   # the 3M window
    assert o["series"][0]["sampling"] == "lttb" and o["series"][1]["large"] is True


@needs_node
def test_option_candles_are_hollow_when_up_and_filled_when_down():
    s = option("o.series[0]", typ="candle")
    assert s["type"] == "candlestick" and s["itemStyle"]["color"] == "#fff" and s["itemStyle"]["color0"] == "#a00"
    assert s["data"][0] == [99, 100, 98, 102]                                        # open, close, low, high


@needs_node
def test_option_overlays_toggle_series_and_marks():
    o = option("o", on="{sma50:true,sma200:true,bb:true,hl52:true,vol:false}")
    assert [s["id"] for s in o["series"]] == ["px", "sma200", "sma50", "bbu", "bbl"] and len(o["grid"]) == 1
    labels = [m["label"]["formatter"] for m in o["series"][0]["markLine"]["data"]]
    assert labels[0].startswith("52-week high") and labels[1].startswith("52-week low")


@needs_node
def test_option_comparison_rebases_to_100_and_replaces_candles():
    o = option("o", on="{cmp:true,hl52:true}", typ="candle", cmp="true")
    assert [s["id"] for s in o["series"]][:2] == ["px", "nifty"] and o["series"][0]["type"] == "line" and "markLine" not in o["series"][0]
    assert o["series"][0]["data"][237] == pytest.approx(100) and o["series"][1]["data"][237] == pytest.approx(100)


@needs_node
def test_option_draws_the_users_average_price_and_lots():
    my = "{avg:110,lots:[{date:'2025-03-05',side:'buy',qty:5,price:100},{date:'2025-04-05',side:'sell',qty:2,price:120},{date:'1999-01-01',side:'buy',qty:1,price:1}]}"
    s = option("o.series[0]", my=my)
    assert s["markLine"]["data"][0]["label"]["formatter"] == "Your average ₹110.00"
    assert [p["symbolRotate"] for p in s["markPoint"]["data"]] == [0, 180]           # buy up, sell down; the pre-history lot is skipped
    assert "markLine" not in option("o.series[0]", my=my, on="{cmp:true}", cmp="true")


@needs_node
def test_option_is_a_phone_layout_at_360px():
    o = option("o", w=360)
    assert o["grid"][0]["left"] <= 48 and o["dataZoom"][1]["height"] >= 30 and o["dataZoom"][1]["showDetail"] is False


@needs_node
def test_tooltip_and_readout_carry_ohlc_volume_and_signed_change():
    h = option("C.tipHtml(m,299)")
    for word in ("Open", "High", "Low", "Close", "Volume", "Since start of range"):
        assert word in h
    assert "▲" in h or "▼" in h
    assert "Nifty 50" in option("C.tipHtml(m,299)", on="{cmp:true}", cmp="true")
    r = option("C.readout(m,299)")
    assert "close" in r and "since the start of the range" in r


@needs_node
def test_zoom_events_give_a_window_from_values_or_percent():
    assert option("C.winFromEvent(m,{batch:[{startValue:10,endValue:50}]})") == [10, 50]
    assert option("C.winFromEvent(m,{start:0,end:100})") == [0, 299]
    assert option("C.winFromEvent(m,{})") is None


@needs_node
def test_chart_js_loads_under_node_with_stubbed_echarts_and_is_syntactically_valid():
    path = os.path.join(APP, "assets", "js", "chart.js")
    subprocess.run([NODE, "--check", path], check=True)
    code = (f"globalThis.echarts={{color:{{modifyAlpha:c=>c}},init(){{throw 1}}}};const P=require({json.dumps(path)});"
            "process.stdout.write(typeof P.mount+typeof P.redraw)")
    assert subprocess.run([NODE, "-e", code], capture_output=True, encoding="utf-8", check=True).stdout == "functionfunction"
