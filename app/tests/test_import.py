import json, os, re, shutil, subprocess, sys, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from modules.stocks import lists

APP = os.path.join(os.path.dirname(__file__), "..")
HTML = os.path.join(APP, "assets", "js", "picks-table.js")
NODE = shutil.which("node")

# Canned fixtures in the shape of the files the owner downloads (invented rows, not real exchange data).
ETF_CSV = ('﻿Symbol,Security Name,Underlying,Issuer\r\n'
           'NIFTYBEES,"Nippon India ETF Nifty 50 BeES, Growth",Nifty 50,Nippon\r\n'
           'LIQUIDBEES,Nippon Liquid BeES,Overnight rate,Nippon\r\n'
           'LIQUIDBEES,Nippon Liquid BeES again,Overnight rate,Nippon\r\n'
           'bad sym!,Broken row,x,y\r\n')
BSE_SCRIP_CSV = ('Security Code,Issuer Name,Security Id,Security Name,Status,Group,Face Value,ISIN No,Industry,Instrument\n'
                 '500325,Reliance Industries Ltd,RELIANCE,RELIANCE INDUSTRIES LTD,Active,A,10,INE002A01018,Oil,Equity\n'
                 '539999,Sample Mills Ltd,SMPLMILL,"SAMPLE MILLS, LTD",Active,B,10,INE000000001,Textile,Equity\n'
                 '540001,Old Co,OLDCO,OLD CO LTD,Delisted,B,10,INE000000002,Misc,Equity\n'
                 '800001,Gilt,GSEC,GOVT SEC 2030,Active,G,100,IN0000000001,Debt,Debt\n'
                 '539999,Sample Mills Ltd,SMPLMILL,"SAMPLE MILLS, LTD",Active,B,10,INE000000001,Textile,Equity\n')
BHAV_CSV = ('SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE\n'
            '500325,RELIANCE INDS.,A,Q,2900,2950,2880,2940\n'
            '532540,TATA CONSULTANCY,A,Q,4000,4050,3990,4020\n'
            '700001,SOME DEBENTURE,F,B,1000,1000,1000,1000\n')


# ---------- CSV column detection, running the page's own code under node ----------
HARNESS = """
const input=JSON.parse(process.argv[1]);
%s
const t=parseCsv(input.text),h=findHeader(t,input.kind),map=detect(t[h],input.kind);
const R=buildRows(t,h,map,input.kind,input.all);
process.stdout.write(JSON.stringify({t,h,map,R}));
"""


def run_page(text, kind, all_rows=False):
    src = open(HTML, encoding="utf-8").read()
    code = src[src.index("/*imp*/"):src.index("/*endimp*/")]
    out = subprocess.run([NODE, "-e", HARNESS % code, json.dumps({"text": text, "kind": kind, "all": all_rows})],
                         capture_output=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


@needs_node
def test_etf_columns_quotes_bom_duplicates_and_bad_symbols():
    r = run_page(ETF_CSV, "etf")
    assert r["h"] == 0 and r["map"] == {"symbol": 0, "name": 1, "underlying": 2, "issuer": 3}
    assert r["t"][0][0] == "Symbol"                      # BOM stripped
    rows = r["R"]["rows"]
    assert [x["symbol"] for x in rows] == ["NIFTYBEES", "LIQUIDBEES"]
    assert rows[0]["name"] == "Nippon India ETF Nifty 50 BeES, Growth"   # quoted comma kept in one cell
    assert rows[0]["underlying"] == "Nifty 50" and rows[0]["issuer"] == "Nippon"
    assert r["R"]["skipped"] == {"duplicate": 1, "invalid symbol": 1} and r["R"]["total"] == 4


@needs_node
def test_bse_scrip_list_keeps_active_equity_only():
    r = run_page(BSE_SCRIP_CSV, "bse")
    assert r["map"]["code"] == 0 and r["map"]["symbol"] == 2 and r["map"]["name"] == 3
    assert r["map"]["status"] == 4 and r["map"]["group"] == 5 and r["map"]["type"] == 9
    assert [x["symbol"] for x in r["R"]["rows"]] == ["RELIANCE", "SMPLMILL"]
    assert r["R"]["rows"][1]["name"] == "SAMPLE MILLS, LTD" and r["R"]["rows"][1]["code"] == "539999"
    assert r["R"]["skipped"] == {"not active": 1, "not equity": 1, "duplicate": 1}


@needs_node
def test_bse_include_all_rows_keeps_everything_valid():
    r = run_page(BSE_SCRIP_CSV, "bse", all_rows=True)
    assert [x["symbol"] for x in r["R"]["rows"]] == ["RELIANCE", "SMPLMILL", "OLDCO", "GSEC"]
    assert r["R"]["skipped"] == {"duplicate": 1}


@needs_node
def test_bse_bhavcopy_style_uses_code_as_symbol_and_drops_non_equity():
    r = run_page(BHAV_CSV, "bse")
    assert r["map"]["code"] == 0 and r["map"]["symbol"] == -1 and r["map"]["name"] == 1
    assert r["map"]["group"] == 2 and r["map"]["type"] == 3
    assert [(x["symbol"], x["code"]) for x in r["R"]["rows"]] == [("500325", "500325"), ("532540", "532540")]
    assert r["R"]["skipped"] == {"not equity": 1}


@needs_node
def test_header_found_below_title_rows_and_tab_delimiter():
    r = run_page('Exchange traded funds\n\nSymbol\tName\nGOLDBEES\tGold BeES\n', "etf")
    assert r["h"] == 1 and [x["symbol"] for x in r["R"]["rows"]] == ["GOLDBEES"]


@needs_node
def test_page_import_blocks_are_syntactically_valid_and_markers_intact():
    src = open(HTML, encoding="utf-8").read()
    assert src.count("/*csv*/") == 1 and src.count("/*endcsv*/") == 1
    assert src.count("/*imp*/") == 1 and src.count("/*endimp*/") == 1
    scratch = os.environ.get("TEMP", ".")
    js = "".join(re.findall(r"<script>(.*?)</script>", src, re.S))
    path = os.path.join(scratch, "index_scripts_check.js")
    open(path, "w", encoding="utf-8").write(js)
    subprocess.run([NODE, "--check", path], check=True, capture_output=True)


# ---------- server API ----------
@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setitem(server.STATE, "running", True)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    s.server_close()


def call(base, method, path="/api/import/list", body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    try:
        r = urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=method, headers=h))
    except urllib.error.HTTPError as e:
        r = e
    return r.status, json.loads(r.read() or b"{}")


def test_post_get_delete_roundtrip_and_atomic_file(srv):
    rows = [{"symbol": "goldbees", "name": "Gold\x00 BeES\x07"}, {"symbol": "BAD SYM", "name": "x"},
            {"symbol": "GOLDBEES", "name": "dup"}, {"symbol": "LIQUIDBEES", "name": "Liquid", "underlying": "Overnight"}]
    st, j = call(srv, "POST", body={"kind": "etf", "rows": rows})
    assert st == 200 and j["count"] == 2 and j["skipped"] == {"bad_symbol": 1, "duplicate": 1}
    st, got = call(srv, "GET")
    assert got["etf"]["count"] == 2 and got["etf"]["rows"][0] == {"symbol": "GOLDBEES", "name": "Gold BeES"}
    assert got["etf"]["importedAt"]
    assert json.load(open(lists.PATH))["etf"]["count"] == 2 and not os.path.exists(lists.PATH + ".tmp")
    st, j = call(srv, "DELETE", "/api/import/list?kind=etf")
    assert st == 200 and call(srv, "GET")[1] == {}
    assert call(srv, "DELETE", "/api/import/list?kind=nope")[0] == 400


def test_bse_codes_must_be_numeric_and_symbol_defaults_to_code(srv):
    rows = [{"symbol": "RELIANCE", "name": "Reliance", "code": "500325"}, {"symbol": "X", "code": "12AB"},
            {"code": "532540", "name": "TCS"}, {"symbol": "ZZ", "code": "500325"}]
    st, j = call(srv, "POST", body={"kind": "bse", "rows": rows})
    assert st == 200 and j["count"] == 2 and j["skipped"] == {"bad_code": 1, "duplicate": 1}
    saved = call(srv, "GET")[1]["bse"]["rows"]
    assert saved[1] == {"symbol": "532540", "name": "TCS", "code": "532540"}


def test_rejections(srv):
    assert call(srv, "POST", body={"kind": "etf", "rows": [{"symbol": "A B"}]})[0] == 400     # nothing valid
    assert call(srv, "POST", body={"kind": "zzz", "rows": []})[0] == 400
    assert call(srv, "POST", raw=b"not json")[0] == 400
    assert call(srv, "POST", body={"kind": "etf", "rows": [{"symbol": "A"}] * 5001})[0] == 400
    assert call(srv, "GET")[1] == {}


def test_oversize_body_is_413(srv):
    big = {"kind": "etf", "rows": [{"symbol": "A", "name": "x" * 100}] * 20000}
    st, j = call(srv, "POST", body=big)
    assert st == 413 and call(srv, "GET")[1] == {}


def test_cross_origin_write_refused_but_same_origin_ok(srv):
    ok_body = {"kind": "etf", "rows": [{"symbol": "GOLDBEES", "name": "Gold"}]}
    assert call(srv, "POST", body=ok_body, headers={"Origin": "http://evil.example"})[0] == 403
    assert call(srv, "DELETE", "/api/import/list?kind=etf", headers={"Origin": "http://evil.example"})[0] == 403
    assert call(srv, "GET")[1] == {}
    assert call(srv, "POST", body=ok_body, headers={"Origin": srv})[0] == 200


def test_import_marks_scan_stale_so_next_request_rescans(srv, monkeypatch):
    monkeypatch.setitem(server.STATE, "t", 123456.0)
    call(srv, "POST", body={"kind": "etf", "rows": [{"symbol": "GOLDBEES", "name": "Gold"}]})
    assert server.STATE["t"] == 0


# ---------- universe merge and scan wiring ----------
def test_merge_adds_etfs_and_bse_and_excludes_nse_duplicates():
    nse = {"RELIANCE": "Reliance", "TCS": "Tata Consultancy", "NIFTYBEES": "Nippon Nifty BeES ETF"}
    stored = {"etf": {"rows": [{"symbol": "NIFTYBEES", "name": "x", "underlying": "Nifty 50"},
                               {"symbol": "LIQUIDBEES", "name": "Liquid", "underlying": "Overnight", "issuer": "Nippon"}]},
              "bse": {"rows": [{"symbol": "RELIANCE", "name": "dup of NSE", "code": "500325"},
                               {"symbol": "LIQUIDBEES", "name": "dup of ETF"},
                               {"symbol": "SMPLMILL", "name": "Sample Mills", "code": "539999"},
                               {"symbol": "532540", "name": "No id", "code": "532540"},
                               {"symbol": "ONLYSYM", "name": "No code"}]}}
    names, info, stats = lists.merge(nse, stored)
    assert names["NIFTYBEES"] == "Nippon Nifty BeES ETF"              # built-in name kept
    assert info["NIFTYBEES"] == {"etf": True, "underlying": "Nifty 50", "issuer": None}
    assert info["LIQUIDBEES"]["etf"] and names["LIQUIDBEES"] == "Liquid"
    assert "SMPLMILL" in names and info["SMPLMILL"] == {"exchange": "BSE", "suffix": ".BO", "yahoo": "SMPLMILL"}   # Yahoo knows names, not codes
    assert info["532540"]["yahoo"] == "532540" and info["ONLYSYM"]["yahoo"] == "ONLYSYM"
    assert names["RELIANCE"] == "Reliance" and "RELIANCE" not in info   # NSE row untouched, BSE copy dropped
    assert stats == {"etf": 2, "bse": 3, "bseDuplicate": 2}


def test_merge_with_no_imports_changes_nothing():
    nse = {"TCS": "Tata"}
    assert lists.merge(nse, lists.load()) == (nse, {}, {"etf": 0, "bse": 0, "bseDuplicate": 0})


class FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def chart_json():
    return json.dumps({"chart": {"result": [{"timestamp": [1700000000, 1700086400],
                                             "indicators": {"quote": [{"close": [10.0, 11.0], "high": [11, 12], "low": [9, 10],
                                                                       "volume": [100, 200]}], "adjclose": [{"adjclose": [10.0, 11.0]}]}}]}}).encode()


def test_fetch_urls_ns_default_bo_for_bse_and_only_yahoo_host(monkeypatch):
    urls = []

    def fake(req, timeout=None):
        urls.append(req.full_url)
        return FakeResp(chart_json())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert server.fetch("TCS")[1] is not None
    assert server.fetch("M&M")[0] == "M&M"
    assert server.fetch("SMPLMILL", ".BO", "539999")[1] is not None
    assert server.fetch("^NSEI")[0] == "^NSEI"
    paths = [u.split("/chart/")[1].split("?")[0] for u in urls]
    assert paths == ["TCS.NS", "M%26M.NS", "539999.BO", "%5ENSEI"]
    assert {u.split("/")[2] for u in urls} == {"query1.finance.yahoo.com"}


def test_failed_bo_fetch_returns_none_and_404_is_not_retried(monkeypatch):
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    assert server.fetch("NOPE", ".BO", "999999") == ("NOPE", None)
    assert len(calls) == 1


def test_no_exchange_website_requests_added(monkeypatch, tmp_path):
    """load_universe, merge and fetch contact only the hosts that already existed; none is bseindia.com."""
    hosts = []

    def fake(req, timeout=None):
        hosts.append(req.full_url.split("/")[2])
        if "nseindia" in req.full_url:
            raise OSError("offline")
        return FakeResp(chart_json())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(server, "CACHE_DIR", str(tmp_path))
    names = server.load_universe()
    lists.save("bse", [{"symbol": "SMPLMILL", "name": "S", "code": "539999"}])
    names, info, _ = lists.merge(names, lists.load())
    server.fetch("SMPLMILL", info["SMPLMILL"]["suffix"], info["SMPLMILL"]["yahoo"])
    assert set(hosts) <= {"nsearchives.nseindia.com", "query1.finance.yahoo.com"}
    assert hosts.count("nsearchives.nseindia.com") == 1      # the one pre-existing EQUITY_L.csv download


def test_sources_name_no_bse_host_and_only_known_hosts():
    for fn in ("server.py", "modules/stocks/lists.py", "modules/home/index.html", "assets/js/picks-table.js", "assets/js/common.js"):   # bseindia.com lives only in bhavcopy.py
        text = open(os.path.join(APP, fn), encoding="utf-8").read().lower()
        assert "bseindia" not in text, fn
    hosts = set(re.findall(r"https://([a-z0-9.-]+)", open(os.path.join(APP, "server.py"), encoding="utf-8").read()))
    assert hosts == {"nsearchives.nseindia.com", "query1.finance.yahoo.com", "news.google.com",
                     "fonts.googleapis.com", "fonts.gstatic.com"}
    assert "http" not in open(os.path.join(APP, "modules", "stocks", "lists.py"), encoding="utf-8").read().replace("http.server", "")


def test_analyse_flags_bse_and_etf_from_info():
    import datetime
    rows = [(datetime.date(2020, 1, 1) + datetime.timedelta(days=i), 101.0 + i * .01, 99.0 + i * .01, 100.0 + i * .01,
             100.0 + i * .01, 1000) for i in range(400)]
    fc = lambda score, sigma: {}
    b = server.analyse("SMPLMILL", rows, None, fc, "Sample", {"exchange": "BSE", "suffix": ".BO", "yahoo": "539999"})
    assert b["exchange"] == "BSE" and b["etf"] is False
    e = server.analyse("LIQUIDBEES", rows, None, fc, "Liquid", {"etf": True, "underlying": "Overnight"})
    assert e["etf"] is True and e["underlying"] == "Overnight" and e["exchange"] == "NSE"
    assert server.analyse("TCS", rows, None, fc, "Tata")["exchange"] == "NSE"
