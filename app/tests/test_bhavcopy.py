import datetime, io, json, os, sys, zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.stocks import bhavcopy

HEAD = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
        "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
        "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")


def line(tp, fid, sym, series, name, close, vol="100", val="5000"):
    return f"2026-10-23,2026-10-23,CM,X,{tp},{fid},INE0,{sym},{series},,,,,{name},1,2,1,{close},{close},1,,1,,,{vol},{val},3,F1,1,,,,,\n"


def test_parse_nse_keeps_equity_and_etf_by_ticker():
    text = HEAD + line("STK", "1", "TCS", "EQ", "TCS LTD", "3500") + line("STK", "2", "TATSILV", "EQ", "TATA SILVER", "11.5") \
        + line("STK", "3", "SGBJUN28", "GB", "GOLD BOND", "14000") + line("STK", "4", "ZERO", "EQ", "NO CLOSE", "")
    rows = bhavcopy.parse(text, "NSE")
    assert set(rows) == {"TCS", "TATSILV"} and rows["TCS"]["close"] == 3500.0 and rows["TCS"]["volume"] == 100


def test_parse_bse_keys_by_scrip_code():
    rows = bhavcopy.parse(HEAD + line("STK", "500002", "ABB", "A", "ABB INDIA", "6140"), "BSE")
    assert list(rows) == ["500002"] and rows["500002"]["symbol"] == "ABB" and rows["500002"]["exchange"] == "BSE"


def test_lookup_by_ticker_code_or_short_name():
    data = {"NSE": {"TCS": {"symbol": "TCS"}}, "BSE": {"500002": {"symbol": "ABB"}}}
    assert bhavcopy.lookup("TCS", data) == {"symbol": "TCS"}
    assert bhavcopy.lookup("500002", data)["symbol"] == "ABB"
    assert bhavcopy.lookup("ABB", data)["symbol"] == "ABB"
    assert bhavcopy.lookup("NOPE", data) is None


def test_both_pairs_nse_and_bse_by_isin():
    nse = {"TCS": {"symbol": "TCS", "exchange": "NSE", "isin": "INE467B01029"}}
    bse = {"532540": {"symbol": "TCS", "exchange": "BSE", "isin": "INE467B01029"},
           "500002": {"symbol": "ABB", "exchange": "BSE", "isin": "INE117A01022"}}
    data = {"NSE": nse, "BSE": bse}
    assert set(bhavcopy.both("TCS", data)) == {"NSE", "BSE"}
    assert set(bhavcopy.both("500002", data)) == {"BSE"}      # BSE-only stock
    assert bhavcopy.both("NOPE", data) == {}


ETF_CSV = ("Symbol,Underlying Asset,SecurityName,DateofListing,MarketLot,ISINNumber\n"
           "GOLDBEES,Gold,NIP IND ETF GOLD BEES,08-Jan-02,1,INF1\nGONE,Gold,DELISTED ETF,08-Jan-02,1,INF2\n")


def test_auto_lists_etfs_and_bse_only(monkeypatch, tmp_path):
    nse = bhavcopy.parse(HEAD + line("STK", "1", "TCS", "EQ", "TCS LTD", "3500", "1", "1").replace(",INE0,", ",INE-TCS,")
                         + line("STK", "2", "GOLDBEES", "EQ", "GOLD BEES", "115").replace(",INE0,", ",INF1,"), "NSE")
    bse = bhavcopy.parse(HEAD + line("STK", "532540", "TCS", "A", "TCS", "3490").replace(",INE0,", ",INE-TCS,")
                         + line("STK", "539999", "SMPLMILL", "B", "SAMPLE MILLS", "50").replace(",INE0,", ",INE-S,")
                         + line("STK", "900001", "BOND29", "F", "A BOND", "100").replace(",INE0,", ",INE-B,"), "BSE")
    monkeypatch.setattr(bhavcopy, "latest", lambda ex, **kw: nse if ex == "NSE" else bse)
    monkeypatch.setattr(bhavcopy, "_get", lambda url: ETF_CSV.encode())
    out = bhavcopy.auto_lists(str(tmp_path))
    assert [r["symbol"] for r in out["etf"]["rows"]] == ["GOLDBEES"]          # delisted ETF dropped, none that did not trade
    assert out["etf"]["rows"][0]["underlying"] == "Gold"
    assert out["bse"]["rows"] == [{"symbol": "SMPLMILL", "name": "SAMPLE MILLS", "code": "539999"}]   # no TCS (on NSE), no bond


def test_auto_lists_empty_when_exchange_files_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(bhavcopy, "latest", lambda ex, **kw: {})
    monkeypatch.setattr(bhavcopy, "_get", lambda url: (_ for _ in ()).throw(OSError("offline")))
    assert bhavcopy.auto_lists(str(tmp_path)) == {}


def test_union_prefers_your_imported_rows():
    from modules.stocks import lists
    manual = {"bse": {"rows": [{"symbol": "SMPLMILL", "name": "mine", "code": "539999"}]}}
    auto = {"bse": {"rows": [{"symbol": "SMPLMILL", "name": "auto", "code": "539999"},
                             {"symbol": "OTHER", "name": "o", "code": "500001"}]}, "etf": {"rows": [{"symbol": "GOLDBEES", "name": "g"}]}}
    u = lists.union(auto, manual)
    assert [(r["symbol"], r["name"]) for r in u["bse"]["rows"]] == [("SMPLMILL", "mine"), ("OTHER", "o")]
    assert u["etf"]["count"] == 1 and lists.union({}, {}) == {}


def test_latest_walks_back_over_missing_days_and_caches(monkeypatch, tmp_path):
    saturday_after = datetime.date(2026, 10, 24)            # Saturday: skipped, Friday 23rd is tried first
    asked = []

    def fake_download(exchange, day):
        asked.append(day)
        if day == datetime.date(2026, 10, 23):
            raise ValueError("not a bhavcopy file")        # e.g. a holiday: html page instead of a csv
        return HEAD + line("STK", "1", "TCS", "EQ", "TCS LTD", "3500")

    monkeypatch.setattr(bhavcopy, "_download", fake_download)
    rows = bhavcopy.latest("NSE", saturday_after, str(tmp_path))
    assert "TCS" in rows and asked == [datetime.date(2026, 10, 23), datetime.date(2026, 10, 22)]
    asked.clear()
    assert bhavcopy.latest("NSE", saturday_after, str(tmp_path)) == rows   # 22nd comes from cache, never re-downloaded
    assert asked == []     # and the 23rd, which was not out yet, is not asked for again for a few minutes


def test_download_rejects_html_and_unzips_nse(monkeypatch):
    monkeypatch.setattr(bhavcopy, "_get", lambda url: b"<html>not found</html>")
    try:
        bhavcopy._download("BSE", datetime.date(2026, 10, 23))
        assert False
    except ValueError:
        pass
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", HEAD + line("STK", "1", "TCS", "EQ", "TCS LTD", "3500"))
    monkeypatch.setattr(bhavcopy, "_get", lambda url: buf.getvalue())
    assert bhavcopy._download("NSE", datetime.date(2026, 10, 23)).startswith("TradDt")
