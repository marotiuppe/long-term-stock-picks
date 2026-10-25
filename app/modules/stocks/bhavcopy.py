"""Official end-of-day prices from the exchanges' own bhavcopy files (NSE and BSE). Stdlib only, personal use.
Both exchanges publish the same UDiFF CSV layout; the newest file is found by walking back from today."""
import csv, datetime, io, json, os, time, urllib.request, zipfile

from core.paths import APP_DIR as HERE   # the app folder, not this module's folder
from core import cachefs
from core.paths import CACHE_DIR
NSE_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
BSE_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d}_F_0000.CSV"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/"}
LOOKBACK_DAYS = 7          # covers weekends and exchange holidays
NSE_SERIES = {"EQ", "BE", "SM", "ST"}   # equity-like series; ETFs trade as EQ on NSE
BSE_SERIES = {"A", "B", "T", "X", "XT", "M", "MT", "F"}


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=30).read()


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse(text, exchange):
    """UDiFF csv text -> {symbol: {...}}. NSE keys by ticker; BSE keys by its numeric scrip code
    (BSE's ticker column is a short name, the code is what Yahoo's .BO uses)."""
    allowed = NSE_SERIES if exchange == "NSE" else BSE_SERIES
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("FinInstrmTp") != "STK" or r.get("SctySrs") not in allowed:
            continue
        close = _num(r.get("ClsPric"))
        if not close:
            continue
        key = r["TckrSymb"] if exchange == "NSE" else r["FinInstrmId"]
        out[key] = {"symbol": r["TckrSymb"], "code": r["FinInstrmId"], "name": r["FinInstrmNm"], "isin": r["ISIN"],
                    "exchange": exchange, "series": r["SctySrs"], "date": r["TradDt"], "open": _num(r["OpnPric"]),
                    "high": _num(r["HghPric"]), "low": _num(r["LwPric"]), "close": close,
                    "prev_close": _num(r["PrvsClsgPric"]), "volume": int(_num(r["TtlTradgVol"]) or 0),
                    "value": _num(r["TtlTrfVal"]) or 0.0}
    return out


def _download(exchange, day):
    d = day.strftime("%Y%m%d")
    raw = _get((NSE_URL if exchange == "NSE" else BSE_URL).format(d=d))
    if exchange == "NSE":
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    text = raw.decode("utf-8-sig")
    if not text.startswith("TradDt"):   # the exchange answers a missing day with an html page
        raise ValueError("not a bhavcopy file")
    return text


_miss = {}          # (exchange, day) -> when the exchange last had no file for it
MISS_SECONDS = 600  # NSE posts bhavcopy well after the close: do not ask again on every request until it is out


def latest(exchange, today=None, cache_dir=None):
    """Newest available bhavcopy for 'NSE' or 'BSE' as {symbol: row}; cached on disk per trading date.
    Returns {} when nothing could be fetched or read."""
    today = today or datetime.date.today()
    for back in range(LOOKBACK_DAYS):
        day = today - datetime.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        name = f"bhav-{exchange}-{day.isoformat()}.json"
        saved = cachefs.read(name, cache_dir, CACHE_DIR)
        if saved:
            try:
                return json.loads(saved[0].decode("utf-8"))
            except ValueError:
                pass
        if time.time() - _miss.get((exchange, day, cache_dir), 0) < MISS_SECONDS:
            continue
        try:
            rows = parse(_download(exchange, day), exchange)
        except Exception:
            _miss[(exchange, day, cache_dir)] = time.time()
            continue
        if rows:
            cachefs.write(name, json.dumps(rows).encode("utf-8"), cache_dir, CACHE_DIR)
            return rows
    return {}


ETF_LIST_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
BSE_EQUITY_GROUPS = {"A", "B", "T", "X", "XT"}   # shares only: bonds, debentures and funds sit in other groups


def nse_etfs(cache_dir=None):
    """NSE's official ETF list as rows for lists.merge ('etf' kind), cached for a day. [] when unavailable."""
    saved = cachefs.read("eq_etfseclist.csv", cache_dir, CACHE_DIR)
    if not saved or time.time() - saved[1] > 86400:
        try:
            data = _get(ETF_LIST_URL)
            cachefs.write("eq_etfseclist.csv", data, cache_dir, CACHE_DIR)
            saved = (data, time.time())
        except Exception:
            pass   # keep the older copy if there is one
    if not saved:
        return []
    text = saved[0].decode("utf-8-sig", errors="replace")
    return [{"symbol": r["Symbol"].strip(), "name": (r.get("SecurityName") or "").strip(),
             "underlying": (r.get("Underlying Asset") or "").strip()}
            for r in csv.DictReader(io.StringIO(text)) if (r.get("Symbol") or "").strip()]


def bse_only(nse, bse):
    """Share rows from the BSE file whose ISIN is not traded on NSE (those are already covered by the NSE list)."""
    on_nse = {r["isin"] for r in nse.values()}
    return [{"symbol": r["symbol"], "name": r["name"], "code": r["code"]}
            for r in bse.values() if r["series"] in BSE_EQUITY_GROUPS and r["isin"] not in on_nse]


def auto_lists(cache_dir=None):
    """Stored-list shaped dict ({'etf': {'rows': ...}, 'bse': {'rows': ...}}) built from the official files,
    for lists.merge. Anything that cannot be fetched or validated is simply left out."""
    from modules.stocks import lists
    nse, bse = latest("NSE", cache_dir=cache_dir), latest("BSE", cache_dir=cache_dir)
    out = {}
    etfs = nse_etfs(cache_dir)
    if nse:   # only ETFs that traded in the latest NSE file
        etfs = [e for e in etfs if e["symbol"] in nse]
    for kind, rows in (("etf", etfs), ("bse", bse_only(nse, bse) if nse and bse else [])):
        try:
            clean, _ = lists.validate(kind, rows[:lists.MAX_ROWS])
        except ValueError:
            continue
        out[kind] = {"rows": clean, "count": len(clean), "auto": True}
    return out


def both(sym, rows_by_exchange):
    """{'NSE': row, 'BSE': row} for one stock, pairing the two listings by ISIN. Missing exchanges are left out."""
    first = lookup(sym, rows_by_exchange)
    if not first:
        return {}
    out = {first["exchange"]: first}
    other = "BSE" if first["exchange"] == "NSE" else "NSE"
    for r in (rows_by_exchange.get(other) or {}).values():
        if r["isin"] == first["isin"]:
            out[other] = r
            break
    return out


def lookup(sym, rows_by_exchange):
    """Find one symbol across the exchanges: an NSE ticker, a BSE scrip code or a BSE short name."""
    for ex in ("NSE", "BSE"):
        rows = rows_by_exchange.get(ex) or {}
        if sym in rows:
            return rows[sym]
        for r in rows.values():
            if r["symbol"] == sym:
                return r
    return None
