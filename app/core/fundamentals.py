"""Company fundamentals for the stocks a user holds, from Yahoo Finance (same source and fields as the trader-analyst skill).

What Yahoo gives for NSE and BSE names is thin: about five quarters of revenue, operating income, net income and diluted EPS,
four fiscal years of annual EPS, a sparse total-debt series, and dividend and split events. ETFs and funds have no company
results and most banks have very little. This module never fills a gap: whatever is missing stays missing and the rules say so.

Everything is cached on disk for a day (a held stock is looked up at most once a day) and a failed lookup falls back to the
last good copy, labelled stale. Nothing here raises: callers get a dict with status 'ok', 'stale', 'none' or 'error'.
"""
import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from core.paths import APP_DIR as HERE   # the app folder, not this module's folder
from core import cachefs
from core.paths import CACHE_DIR
TTL_SECONDS = 20 * 3600
UA = "Mozilla/5.0 (compatible; stock-picks-local/1.0)"
TS_URL = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s?type=%s&period1=1400000000&period2=%d")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5y&interval=1d&events=div,split"
TYPES = {"quarterlyTotalRevenue": ("q", "revenue"), "quarterlyOperatingIncome": ("q", "operating_income"),
         "quarterlyNetIncome": ("q", "net_income"), "quarterlyDilutedEPS": ("q", "eps"),
         "quarterlyTotalDebt": ("d", "debt"), "annualDilutedEPS": ("a", "eps"),
         "annualNetIncome": ("a", "net_income"), "annualTotalRevenue": ("a", "revenue")}
SAFE = re.compile(r"^[A-Z0-9&-]{1,20}$")
_lock = threading.Lock()


def yahoo_symbol(symbol, exchange="NSE"):
    return "%s.%s" % (symbol, "BO" if exchange == "BSE" else "NS")


def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _iso(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date().isoformat()


def normalize(ts_doc, chart_doc, symbol):
    """Yahoo's two JSON documents -> one plain dict. Either document may be None (that part is then empty)."""
    q, a, debt = {}, {}, {}
    try:
        results = (ts_doc or {}).get("timeseries", {}).get("result") or []
    except AttributeError:
        results = []
    for r in results:
        t = (r.get("meta", {}).get("type") or [None])[0]
        kind = TYPES.get(t)
        if not kind:
            continue
        for v in r.get(t) or []:
            if not v:
                continue
            raw = (v.get("reportedValue") or {}).get("raw")
            end = v.get("asOfDate")
            if raw is None or not end:
                continue
            per = v.get("periodType")
            if kind[0] == "q" and per in (None, "3M"):
                q.setdefault(end, {})[kind[1]] = float(raw)
            elif kind[0] == "a" and per in (None, "12M"):
                a.setdefault(end, {})[kind[1]] = float(raw)
            elif kind[0] == "d":
                debt[end] = float(raw)
    quarters = [dict(end=e, revenue=v.get("revenue"), operating_income=v.get("operating_income"),
                     net_income=v.get("net_income"), eps=v.get("eps")) for e, v in sorted(q.items())]
    annual = [dict(end=e, eps=v.get("eps"), net_income=v.get("net_income"), revenue=v.get("revenue")) for e, v in sorted(a.items())]
    closes = {"d": [], "c": []}
    divs, splits = [], []
    try:
        res = (chart_doc or {})["chart"]["result"][0]
        ts = res.get("timestamp") or []
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for t, c in zip(ts, cl):
            if c is not None:
                closes["d"].append(_iso(t))
                closes["c"].append(round(float(c), 4))
        ev = res.get("events") or {}
        for d in (ev.get("dividends") or {}).values():
            if d.get("amount") is not None and d.get("date"):
                divs.append({"date": _iso(d["date"]), "amount": float(d["amount"])})
        for s in (ev.get("splits") or {}).values():
            if s.get("date"):
                splits.append({"date": _iso(s["date"]), "text": s.get("splitRatio") or "%s:%s" % (s.get("numerator"), s.get("denominator"))})
    except (KeyError, IndexError, TypeError):
        pass
    divs.sort(key=lambda x: x["date"])
    splits.sort(key=lambda x: x["date"])
    has_results = bool(quarters or annual)
    return {"symbol": symbol, "quarters": quarters, "annual": annual,
            "debt": [{"end": e, "value": v} for e, v in sorted(debt.items())],
            "dividends": divs, "splits": splits, "closes": closes,
            "status": "ok" if has_results else "none",
            "reason": None if has_results else "Yahoo has no company results for this symbol (an ETF or fund, a bank with a different statement layout, or a very new listing)."}


def _cache_path(symbol, cache_dir):
    return os.path.join(cache_dir, "fund-%s.json" % symbol)


def get_facts(symbol, exchange="NSE", is_etf=False, cache_dir=None, now=None, getter=None, ttl=TTL_SECONDS):
    """Facts for one held symbol. Never raises."""
    symbol = str(symbol).upper()
    today = (now or datetime.datetime.now()).date().isoformat()
    if is_etf:
        return {"symbol": symbol, "status": "none", "fetched": today, "quarters": [], "annual": [], "debt": [], "dividends": [],
                "splits": [], "closes": {"d": [], "c": []},
                "reason": "ETFs and funds have no company results, so there is no revenue, profit or P/E to read."}
    if not SAFE.match(symbol):
        return {"symbol": symbol, "status": "error", "fetched": today, "quarters": [], "annual": [], "debt": [], "dividends": [],
                "splits": [], "closes": {"d": [], "c": []}, "reason": "Unusual symbol, not looked up."}
    name = "fund-%s.json" % symbol
    old = None
    saved = cachefs.read(name, cache_dir, CACHE_DIR)
    if saved:
        try:
            old = json.loads(saved[0].decode("utf-8"))
        except ValueError:
            pass
    t = time.time() if now is None else now.timestamp()
    if old and t - old.get("t", 0) < ttl:
        return old["facts"]
    getter = getter or _http_json
    ys = urllib.parse.quote(yahoo_symbol(symbol, exchange))
    try:
        ts_doc = getter(TS_URL % (ys, ",".join(TYPES), int(t)))
        try:
            chart_doc = getter(CHART_URL % ys)
        except Exception:
            chart_doc = None
        facts = normalize(ts_doc, chart_doc, symbol)
        facts["fetched"] = today
        if chart_doc is None and old and old["facts"].get("closes", {}).get("d"):
            facts["closes"], facts["dividends"], facts["splits"] = old["facts"]["closes"], old["facts"]["dividends"], old["facts"]["splits"]
    except Exception as e:
        if old:
            facts = dict(old["facts"], status="stale" if old["facts"].get("status") == "ok" else old["facts"].get("status"),
                         reason="Could not refresh from Yahoo (%s). Showing the copy from %s." % (type(e).__name__, old["facts"].get("fetched")))
            return facts
        return {"symbol": symbol, "status": "error", "fetched": today, "quarters": [], "annual": [], "debt": [], "dividends": [],
                "splits": [], "closes": {"d": [], "c": []}, "reason": "Could not reach Yahoo Finance (%s)." % type(e).__name__}
    try:
        with _lock:
            cachefs.write(name, json.dumps({"t": t, "facts": facts}, separators=(",", ":")).encode("utf-8"), cache_dir, CACHE_DIR)
    except Exception:
        pass   # a cache that cannot be written (read-only disk, database down) must not fail the lookup
    return facts


def get_many(items, **kw):
    """items: [(symbol, exchange, is_etf)] -> {symbol: facts}. A few lookups in parallel, never more than 4."""
    if not items:
        return {}
    with ThreadPoolExecutor(max_workers=min(4, len(items))) as ex:
        res = list(ex.map(lambda it: get_facts(it[0], it[1], it[2], **kw), items))
    return {it[0]: r for it, r in zip(items, res)}
