"""Long-term stock picker (NSE): python server.py  ->  http://localhost:8765
The stock scan uses only the standard library (Sync from Groww and login add cryptography and growwapi, see requirements.txt). Buy-and-hold horizons of 10 days to 6 months, never intraday.

Method: 5 years of daily adjusted prices (Yahoo, free, delayed). Each stock gets a trend/momentum score.
The forecast for a score comes from what stocks with a similar score actually did over the next
10/20/60/126 trading days across the whole universe (volatility-scaled to the stock), so every number on
the page is an empirical odds figure, not a promise. The page also shows that method's own track record."""
import bisect, csv, datetime, glob, gzip, hmac, html, io, json, zlib, math, os, pickle, re, statistics, threading, time, webbrowser
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import api_me, cachefs, forecast_xlsx, fundamentals, livecheck, update_holidays
from modules.stocks import bhavcopy, lists
from modules.about import backtest
from modules.stock import why
from core.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", 8765))   # Render sets PORT
HOST = os.environ.get("HOST", "127.0.0.1")   # 0.0.0.0 on a server
CACHE_SECONDS = 30 * 60
HORIZONS = {"1d": 1, "2d": 2, "5d": 5, "10d": 10, "1m": 20, "3m": 60, "6m": 126}   # trading days
HZ_1M = list(HORIZONS).index("1m")   # the Buy call and the all-stock base rate are judged on the 1-month horizon
SCAN_HOUR = 23   # IST: the daily refresh runs at 11 pm, long after the 3:30 pm close, and data scanned earlier counts as stale
BUY_SCORE, WATCH_SCORE = 40, 20

FALLBACK = """RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC SBIN LT HINDUNILVR KOTAKBANK AXISBANK
BAJFINANCE MARUTI SUNPHARMA TITAN ULTRACEMCO ASIANPAINT NTPC POWERGRID ONGC M&M TATASTEEL""".split()
ETF_LIST = {"TATSILV": "Tata Silver ETF", "SILVERBEES": "Nippon Silver BeES ETF", "GOLDBEES": "Nippon Gold BeES ETF",
            "NIFTYBEES": "Nippon Nifty BeES ETF"}
ETFS = set(ETF_LIST)
from core.paths import CACHE_DIR, DATA_DIR
# Quality filter: below these, prices are too thin to trust or to exit at a stop-loss.
MIN_PRICE, MIN_AVG_VALUE, MIN_BARS, MAX_DAY_MOVE = 20.0, 1e7, 300, 0.35   # Rs, Rs traded per day (20d avg)
POOL_STEP = 10
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
SYM_RE = re.compile(r"^[A-Z0-9&.^-]{1,20}$")
FORCE_COOLDOWN = 60   # seconds between forced scans
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}


def load_universe():
    """All NSE equity-series shares from NSE's own EQUITY_L.csv (cached per day) plus a few ETFs."""
    saved = cachefs.read("EQUITY_L.csv", default_dir=CACHE_DIR)
    if not saved or time.time() - saved[1] > 86400:
        try:
            req = urllib.request.Request("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                                         headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=30).read()
            cachefs.write("EQUITY_L.csv", data, default_dir=CACHE_DIR)
            saved = (data, time.time())
        except Exception:
            pass   # keep the older copy if there is one
    names = dict(ETF_LIST)
    try:
        for r in csv.DictReader(io.StringIO(saved[0].decode("utf-8", errors="replace") if saved else "")):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if r.get("SERIES") == "EQ" and r.get("SYMBOL"):
                names[r["SYMBOL"]] = r.get("NAME OF COMPANY", r["SYMBOL"])
    except Exception:
        pass
    if len(names) < 100:
        names.update({x: x for x in FALLBACK})
    return names


HOLIDAY_DOC = update_holidays.load()   # holidays.json: per-year status (official/provisional), source, checked
NSE_HOLIDAYS = update_holidays.holiday_set(HOLIDAY_DOC)


def set_holidays(doc):
    global HOLIDAY_DOC, NSE_HOLIDAYS
    HOLIDAY_DOC, NSE_HOLIDAYS = doc, update_holidays.holiday_set(doc)


def holiday_warnings(dates):
    """{year: 'provisional'|'missing'} for every year the given ISO dates touch whose list is not official."""
    out = {}
    for y in sorted({d[:4] for d in dates}):
        st = update_holidays.year_status(HOLIDAY_DOC, y)
        if st != "official":
            out[y] = st
    return out


def refresh_holidays():
    changed, msgs = update_holidays.maybe_update()
    for m in msgs:
        print(m)
    if changed:
        set_holidays(update_holidays.load())


HOLIDAY_CHECK_EVERY = 6 * 3600


KEEPALIVE_EVERY = 300


def keepalive_url():
    """The address to call to stay awake: KEEPALIVE_URL, else the public address Render gives the service. None when neither is set (a local
    run). It must be the public address: a free Render service sleeps unless requests arrive through Render's proxy, and localhost does not."""
    base = (os.environ.get("KEEPALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    return base + "/health" if base.startswith(("http://", "https://")) else None


def keepalive(stop, url, every=KEEPALIVE_EVERY, opener=None):
    """Calls the service's own /health every few minutes so a free host does not put it to sleep. Never raises."""
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "stockpicks-keepalive"}), timeout=30).read())
    while not stop.wait(every):
        try:
            opener(url)
        except Exception as e:
            print("keep-alive failed:", type(e).__name__, e)


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_xlsx = {}   # (scan, horizon) -> (file name, bytes): built once per scan, not once per click


def forecast_xlsx_file(hz):
    """(file name, workbook bytes) for the forecast over horizon `hz` from the scan in memory, or None when there is no scan yet. The forecast is
    the close on the scan date against the close HORIZONS[hz] trading days later, so for "1d" it is tomorrow's close (the next trading day)."""
    load_scan()
    d = STATE["data"]
    if not d or not d.get("stocks"):
        return None
    key = (id(d), hz)
    if key not in _xlsx:
        asof = max(datetime.date.fromisoformat(s["asof"]) for s in d["stocks"])
        target = add_td(asof, HORIZONS[hz])
        if len(_xlsx) >= 8:
            _xlsx.pop(next(iter(_xlsx)))
        _xlsx[key] = ("forecast-%s-for-%s.xlsx" % (hz, target.isoformat()),
                      forecast_xlsx.build(d["stocks"], hz, HORIZONS[hz], target, d.get("generated", "")))
    return _xlsx[key]


SCAN_WATCH_EVERY = 300


def scan_watch(stop, every=SCAN_WATCH_EVERY):
    """Starts the daily refresh by itself once the latest cutoff (SCAN_HOUR, IST) has passed, so it happens at night even when nobody is on the
    site. Without it a host that has no scheduler would refresh only when the first visitor arrives, who would then wait on stale data. It shares
    the retry pause with page loads (AUTO_RETRY_SECONDS) so a failing scan is not hammered. Never raises."""
    while not stop.wait(every):
        try:
            load_scan()   # another process (refresh_job.py) may have saved a newer one
            if not STATE["running"] and not scan_up_to_date() and time.time() - _last_auto[0] > AUTO_RETRY_SECONDS:
                _last_auto[0] = time.time()
                start_scan()
        except Exception as e:
            print("scheduled refresh check failed:", type(e).__name__, e)


VIEW_FLUSH_EVERY = 30
BOT_RE = re.compile(r"bot|crawl|spider|slurp|monitor|uptime|pingdom|curl|wget|python-|go-http|headless|preview|facebookexternalhit", re.I)
_views, _views_lock = {}, threading.Lock()


def count_view(path, user_agent=""):
    """One more view of a page today. Kept in memory and written to the database in batches (a database write per page view is wasteful on a
    small host). Only the page path and the day are kept: no IP address, no cookie, nothing about the visitor. Obvious bots are not counted."""
    if BOT_RE.search(user_agent or ""):
        return
    with _views_lock:
        _views[path] = _views.get(path, 0) + 1


def today_ist():
    return datetime.datetime.now(IST).date().isoformat()


def flush_views(day=None):
    """Write the counted views to the database. Counts that could not be written are kept for the next try."""
    with _views_lock:
        batch = dict(_views)
        _views.clear()
    if not batch:
        return 0
    try:
        return get_store().views_add(day or today_ist(), batch)
    except Exception as e:
        with _views_lock:
            for p, n in batch.items():
                _views[p] = _views.get(p, 0) + n
        print("view count not saved:", type(e).__name__, e)
        return 0


def views_watch(stop, every=VIEW_FLUSH_EVERY):
    while not stop.wait(every):
        flush_views()
    flush_views()


def stats_allowed(headers):
    """The stats are shown only to someone who knows STATS_TOKEN (Authorization: Bearer <token>). With no token set they are off."""
    token = os.environ.get("STATS_TOKEN", "").strip()
    given = (headers.get("Authorization") or "")[7:].strip() if (headers.get("Authorization") or "").startswith("Bearer ") else ""
    return bool(token) and hmac.compare_digest(token.encode(), given.encode())


def holiday_watch(stop, every=HOLIDAY_CHECK_EVERY):
    """Keeps the NSE holiday list current while the server stays up. refresh_holidays only fetches when the list is due (monthly on the
    1st, daily from 1 Dec to 31 Jan, or overdue), so checking every few hours costs nothing on the other days. Never raises."""
    while not stop.wait(every):     # the first check happens at start-up, before the first scan
        try:
            refresh_holidays()
        except Exception as e:
            print("holiday check failed:", type(e).__name__, e)


def quote_row(rows, why):
    """Last close for a stock the scan filters out (price under the minimum, thin history or trading, odd price jumps). The portfolio uses it
    to value holdings the scan does not cover. These stocks still get no call, forecast or chart."""
    return {"price": round(rows[-1][3], 4), "prev": round(rows[-2][3], 4) if len(rows) > 1 else None, "asof": rows[-1][0].isoformat(), "why": why}


def slim(rows, today):
    """Full history only for stocks that pass the quality filter. The rest, about two thirds of the market, shrink to their last close
    plus the reason they are filtered out, which is all the scan and the portfolio use of them. Keeps memory and the cache file small."""
    if not rows or isinstance(rows, (dict, bool)):   # already slim, or True: the history is in the database
        return rows
    if (today - rows[-1][0]).days > 7:
        return quote_row(rows, "stale")
    why = passes_quality(rows)
    return quote_row(rows, why) if why else rows


def is_td(d):
    return d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS


def add_td(d, k):
    while k > 0:
        d += datetime.timedelta(days=1)
        if is_td(d):
            k -= 1
    return d


def first_td_from(d):
    while not is_td(d):
        d += datetime.timedelta(days=1)
    return d


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def fetch(sym, suffix=".NS", yahoo=None):
    """Daily prices from Yahoo. `sym` is the key the app uses; `yahoo` is the Yahoo ticker stem if it differs
    (BSE numeric codes) and `suffix` the exchange suffix (.NS default, .BO for imported BSE lists)."""
    s = "%5ENSEI" if sym == "^NSEI" else (yahoo or sym).replace("&", "%26") + suffix
    for _ in range(2):
        try:
            r = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=5y&interval=1d")["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
            rows = []
            for i, ts in enumerate(r["timestamp"]):
                if q["close"][i] is None or adj[i] is None or q["high"][i] is None or q["low"][i] is None:
                    continue
                d = datetime.datetime.fromtimestamp(ts, IST).date()
                rows.append((d, q["high"][i], q["low"][i], q["close"][i], adj[i], q["volume"][i] or 0))
            return sym, rows
        except urllib.error.HTTPError as e:
            if e.code == 404:   # Yahoo does not know this ticker: skip it, no retry
                break
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return sym, None


CHART_TTL = 30 * 60
CHART_MAX = 300   # symbols kept in memory
_charts = {}
_charts_lock = threading.Lock()


def fetch_ohlc(sym, exchange="NSE"):
    """Full daily history for the price chart: {d,o,h,l,c,v} oldest first, or None if Yahoo has nothing.
    Open, high and low are scaled by adjclose/close so candles line up with the adjusted close the app uses.
    Explicit period1/period2 keep daily bars: range=max silently falls back to monthly for long histories."""
    s = "%5ENSEI" if sym == "^NSEI" else urllib.parse.quote(sym, safe="") + (".BO" if exchange == "BSE" else ".NS")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=0&period2={int(time.time()) + 86400}&interval=1d"
    for _ in range(2):
        try:
            r = get_json(url)["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
            out = {"d": [], "o": [], "h": [], "l": [], "c": [], "v": []}
            for i, ts in enumerate(r["timestamp"]):
                o, h, lo, c, a = q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]
                if None in (o, h, lo, c, a) or not c:
                    continue
                k = a / c
                out["d"].append(datetime.datetime.fromtimestamp(ts, IST).date().isoformat())
                out["o"].append(round(o * k, 2))
                out["h"].append(round(h * k, 2))
                out["l"].append(round(lo * k, 2))
                out["c"].append(round(a, 2))
                out["v"].append(int(q["volume"][i] or 0))
            return out if out["d"] else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def chart_payload(sym):
    """Cached fetch_ohlc for a symbol the scan knows (or the Nifty 50 benchmark). None if unavailable."""
    now = time.time()
    with _charts_lock:
        hit = _charts.get(sym)
        if hit and now - hit[0] < CHART_TTL:
            return hit[1]
    exchange = next((s["exchange"] for s in (STATE["data"] or {}).get("stocks", []) if s["symbol"] == sym), "NSE")
    data = fetch_ohlc(sym, exchange)
    if data:
        with _charts_lock:
            if len(_charts) >= CHART_MAX:
                _charts.pop(min(_charts, key=lambda k: _charts[k][0]))
            _charts[sym] = (now, data)
    return data


def api_why(sym):
    """The 'why this stock was picked' payload. Missing data never fails the request: it comes back inside the payload."""
    s = next((x for x in (STATE["data"] or {}).get("stocks", []) if x["symbol"] == sym), None) or {}
    chart = chart_payload(sym)
    nifty = chart_payload("^NSEI") if chart else None
    facts = fundamentals.get_facts(sym, s.get("exchange", "NSE"), bool(s.get("etf")))
    out = why.build(sym, s, chart, nifty, facts, datetime.date.today())
    if not chart:
        out["priceError"] = "Price history could not be loaded from Yahoo Finance."
    return out


def clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def sma(pre, i, w):
    return (pre[i + 1] - pre[i + 1 - w]) / w


def score_at(c, pre, nif, i):
    p = c[i]
    s50, s200 = sma(pre, i, 50), sma(pre, i, 200)
    m126, m63 = c[i - 5] / c[i - 126] - 1, c[i - 5] / c[i - 63] - 1
    dist = p / max(c[i - 251:i + 1]) - 1
    rel = m126 - (nif[i - 5] / nif[i - 126] - 1) if nif else 0
    return (35 * clip(m126 / 0.4) + 20 * clip(m63 / 0.2) + 15 * (p > s200) + 10 * (s50 > s200)
            + 10 * clip(1 + dist / 0.25, 0, 1) + 10 * clip(rel / 0.2))


def sigma_at(c, i, w=60):
    r = [c[j] / c[j - 1] - 1 for j in range(i - w + 1, i + 1)]
    return statistics.pstdev(r) or 1e-4


def quantile(sorted_list, q):
    return sorted_list[min(len(sorted_list) - 1, int(q * len(sorted_list)))]


def prep(rows, nrows):
    c = [r[4] for r in rows]
    pre = [0.0]
    for x in c:
        pre.append(pre[-1] + x)
    nif = None
    if nrows:
        nd = [r[0] for r in nrows]
        nc = [r[4] for r in nrows]
        nif = [nc[max(0, bisect.bisect_right(nd, r[0]) - 1)] for r in rows]
    return c, pre, nif


def build_pool(data, nrows):
    """Every POOL_STEP-th day of history for every stock: (score, returns by horizon, vol-scaled moves, date)."""
    pool = []
    for rows in data.values():
        c, pre, nif = prep(rows, nrows)
        for i in range(252, len(c) - 1, POOL_STEP):
            sg = sigma_at(c, i)
            r = tuple(c[i + h] / c[i] - 1 if i + h < len(c) else None for h in HORIZONS.values())
            z = tuple(None if x is None else x / (sg * math.sqrt(h)) for x, h in zip(r, HORIZONS.values()))
            pool.append((score_at(c, pre, nif, i), r, z, rows[i][0]))
    pool.sort(key=lambda p: p[0])
    return pool, [p[0] for p in pool]


class Forecaster:
    """Odds for a score = what stocks with a similar score did next, volatility-scaled to this stock."""

    def __init__(self, pool, scores):
        self.pool, self.scores, self.cache = pool, scores, {}

    def zs(self, score, hi):
        band = 10
        mid = round(score / 5) * 5
        while True:
            key = (mid, band, hi)
            if key not in self.cache:
                lo_i = bisect.bisect_left(self.scores, mid - band)
                hi_i = bisect.bisect_right(self.scores, mid + band)
                self.cache[key] = sorted(p[2][hi] for p in self.pool[lo_i:hi_i] if p[2][hi] is not None)
            z = self.cache[key]
            if len(z) >= 150 or band > 80:
                return z
            band += 6

    def __call__(self, score, sigma):
        out = {}
        for hi, (k, h) in enumerate(HORIZONS.items()):
            z = self.zs(score, hi)
            if not z:
                continue
            sc = sigma * math.sqrt(h)
            out[k] = {"p10": quantile(z, .1) * sc, "p25": quantile(z, .25) * sc, "p50": quantile(z, .5) * sc,
                      "p75": quantile(z, .75) * sc, "p90": quantile(z, .9) * sc,
                      "pgain": sum(1 for x in z if x > 0) / len(z), "n": len(z)}
        return out


HELDOUT_FRAC = 0.25      # last 25% of distinct dates are held out of the track record
# Purge gap in calendar days: the longest horizon (126 trading days ~ 176 calendar days) plus a margin, so no
# forecast-pool window (row date + horizon) reaches into the held-out period.
PURGE_DAYS = 190
MIN_HELDOUT = 200        # held-out rows needed before its all-stock hit rate replaces the pool-wide base rate


def split_pool(pool):
    """(train, held-out, cutoff). train: dated before cutoff; held-out: dated at/after cutoff + PURGE_DAYS."""
    dates = sorted({p[3] for p in pool})
    if not dates:
        return [], [], None
    cutoff = dates[min(len(dates) - 1, int(len(dates) * (1 - HELDOUT_FRAC)))]
    start = cutoff + datetime.timedelta(days=PURGE_DAYS)
    return [p for p in pool if p[3] < cutoff], [p for p in pool if p[3] >= start], cutoff


def edge_interval(hit, n_top, all_hit, n_all):
    """95% interval for hit - all_hit, normal approximation; n_* are EFFECTIVE sample sizes."""
    se = math.sqrt(hit * (1 - hit) / max(n_top, 1) + all_hit * (1 - all_hit) / max(n_all, 1))
    e = hit - all_hit
    return e - 1.96 * se, e + 1.96 * se


def track_record(pool):
    """How did buy-grade scores do versus every stock-date, on HELD-OUT rows only (see split_pool)?
    Raw forward returns, equal-weighted. Samples every POOL_STEP days overlap when the horizon is longer, so
        effective_n = rows / overlap, overlap = max(1, horizon / POOL_STEP)
    (a rough fix: stocks on the same date also move together, so the true uncertainty is larger still)."""
    res = {}
    held = split_pool(pool)[1]
    for hi, (k, h) in enumerate(HORIZONS.items()):
        rows = [p for p in held if p[1][hi] is not None]
        allr = sorted(p[1][hi] for p in rows)
        top = sorted(p[1][hi] for p in rows if p[0] >= BUY_SCORE)
        weak = sorted(p[1][hi] for p in rows if p[0] < WATCH_SCORE)
        if not top or not weak:
            continue
        overlap = max(1.0, h / POOL_STEP)
        hit, all_hit = sum(1 for x in top if x > 0) / len(top), sum(1 for x in allr if x > 0) / len(allr)
        eff, all_eff = len(top) / overlap, len(allr) / overlap
        lo, hi_ = edge_interval(hit, eff, all_hit, all_eff)
        res[k] = {"n": len(top), "effective_n": eff, "all_effective_n": all_eff,
                  "start": min(p[3] for p in rows).isoformat(), "end": max(p[3] for p in rows).isoformat(),
                  "hit": hit, "median": statistics.median(top),
                  "all_n": len(allr), "all_hit": all_hit,
                  "all_median": statistics.median(allr), "worst10": quantile(top, .1),
                  "weak_hit": sum(1 for x in weak if x > 0) / len(weak), "weak_median": statistics.median(weak),
                  "edge": hit - all_hit, "edge_lo": lo, "edge_hi": hi_}
    return res


def base_rate(pool, track=None):
    """Base rate for the Buy call: the 1m hit rate of all stocks over the WHOLE pool. It deliberately ignores the
    held-out track record: the recent held-out window was a weak market (about 47% of stocks rose), and using it
    would lower the Buy bar and nearly triple the Buy list exactly when the market is weak. `track` is kept only
    so callers need not change."""
    allr = [p[1][HZ_1M] for p in pool if p[1][HZ_1M] is not None]
    return sum(1 for x in allr if x > 0) / len(allr) if allr else 0.5


POS = r"\b(?:upgrade|surge|record|beats|wins|order win|rises|jumps|soars|rally|gains|buy rating|raises target|strong)\b"
NEG = r"\b(?:downgrade|plunge|falls|slump|probe|fraud|penalty|ban|resign|loss|miss|cuts target|crash|tanks|raid|default|weak)\b"
TAGS = [("earnings", r"result|earnings|profit|q[1-4]|revenue|dividend"), ("deal", r"acqui|merger|deal|stake|order win|contract"),
        ("analyst", r"target|upgrade|downgrade|brokerage|rating"), ("regulatory", r"\bsebi\b|\brbi\b|probe|penalty|fraud|court|\bban\b"),
        ("management", r"ceo|md |chairman|resign|appoint")]
NAMES = {"M&M": "Mahindra", "ETERNAL": "Eternal Zomato", "TATSILV": "Tata Silver ETF", "SILVERBEES": "Silver BeES ETF",
         "GOLDBEES": "Gold BeES ETF", "NIFTYBEES": "Nifty BeES ETF", "BAJAJ-AUTO": "Bajaj Auto"}
_news = {}


def news_tone(title):
    """-1, 0 or 1. Whole words only, so 'bank' is not 'ban' and 'mission' is not 'miss'."""
    return clip(len(re.findall(POS, title, re.I)) - len(re.findall(NEG, title, re.I)), -1, 1)


def news(sym, name=None):
    hit = _news.get(sym)
    if hit and time.time() - hit[0] < 30 * 60:
        return hit[1]
    q = urllib.parse.quote(f"{name or NAMES.get(sym, sym)} NSE share when:14d")
    items = []
    try:
        req = urllib.request.Request(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en",
                                     headers={"User-Agent": "Mozilla/5.0"})
        for it in ET.fromstring(urllib.request.urlopen(req, timeout=15).read()).iter("item"):
            t = it.findtext("title", "")
            tag = next((n for n, rx in TAGS if re.search(rx, t, re.I)), "news")
            tone = news_tone(t)
            items.append({"title": t, "link": it.findtext("link"), "tag": tag, "tone": tone,
                          "ts": parsedate_to_datetime(it.findtext("pubDate")).timestamp()})
        items = sorted(items, key=lambda x: -x["ts"])[:6]
    except Exception:
        pass
    _news[sym] = (time.time(), items)
    return items


def rsi14(c):
    d = [c[i] - c[i - 1] for i in range(len(c) - 14, len(c))]
    g, l = sum(max(x, 0) for x in d), sum(max(-x, 0) for x in d)
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def analyse(sym, rows, nrows, fcst, name, info=None):
    c, pre, nif = prep(rows, nrows)
    i = len(c) - 1
    price = rows[-1][3]
    sc = score_at(c, pre, nif, i)
    s20, s50, s200 = sma(pre, i, 20), sma(pre, i, 50), sma(pre, i, 200)
    rsi = rsi14(c)
    trs = [max(rows[j][1] - rows[j][2], abs(rows[j][1] - rows[j - 1][3]), abs(rows[j][2] - rows[j - 1][3]))
           for j in range(len(rows) - 14, len(rows))]
    stop_pct = max(0.07, min(0.15, 2.5 * (sum(trs) / 14) / price))
    ext = c[i] / s20 - 1
    hi52 = max(c[-252:])
    m126 = c[i - 5] / c[i - 126] - 1
    why = [("up" if c[i] > s200 else "down", f"Price {'above' if c[i] > s200 else 'below'} its 200-day average (₹{s200:,.2f})"),
           ("up" if s50 > s200 else "down", f"50-day average {'above' if s50 > s200 else 'below'} 200-day: long trend {'up' if s50 > s200 else 'down'}"),
           ("up" if m126 > 0 else "down", f"6-month return {m126 * 100:+.1f}%"),
           ("up" if c[i] / hi52 > .9 else "flat", f"{(c[i] / hi52 - 1) * 100:.1f}% from the 52-week high")]
    if rsi > 75 or ext > 0.08:
        why.append(("down", f"Stretched short-term (RSI {rsi:.0f}, {ext * 100:+.1f}% vs 20-day average)"))
    info = info or {}
    extra = {k: info[k] for k in ("underlying", "issuer") if info.get(k)}
    return {
        **extra, "exchange": info.get("exchange", "NSE"),
        "symbol": sym, "name": name, "etf": sym in ETFS or bool(info.get("etf")), "price": round(price, 2), "asof": rows[-1][0].isoformat(),
        "score": round(sc, 1), "rsi": round(rsi, 1), "ext": round(ext, 4), "sma20": round(s20, 2),
        "stop": round(price * (1 - stop_pct), 2), "stopPct": round(stop_pct, 4),
        "forecast": fcst(sc, sigma_at(c, i)), "why": why, "hi52": round(hi52, 2),
        "series": {"d": [r[0].isoformat() for r in rows[-252:]], "c": [round(x, 2) for x in c[-252:]],
                   "s50": [round(sma(pre, j, 50), 2) for j in range(len(c) - 252, len(c))],
                   "s200": [round(sma(pre, j, 200), 2) for j in range(len(c) - 252, len(c))]},
    }


def decide(s, today, base):
    """Verdict and dates. News (top candidates only) can only make the call more cautious."""
    net = sum(n["tone"] for n in s.get("news", [])[:5])
    s["newsNet"] = net
    strong = s["score"] >= BUY_SCORE and s["forecast"].get("1m", {}).get("pgain", 0) >= base + 0.02   # beats the all-stock base rate
    extended = s["ext"] > 0.08 or s["rsi"] > 75
    if strong and net <= -2:
        v, note = "WAIT", "Setup is strong but recent headlines are negative: read the news before buying."
    elif strong and extended:
        v, note = "WAIT", f"Good trend but stretched. A better entry is near ₹{s['sma20']:,.2f} (20-day average)."
    elif strong:
        v, note = "BUY", "Trend and momentum are strong and the price is not stretched."
    elif s["score"] >= WATCH_SCORE:
        v, note = "WATCH", "Mixed picture: not enough edge yet."
    else:
        v, note = "DOWNTREND", "Price trend is down. History shows no reliable rebound signal either way, so this tool does not back a purchase."
    s["verdict"], s["note"] = v, note


STATE = {"data": None, "t": 0, "running": False, "done": 0, "total": 0, "phase": "", "error": None}
DETAIL = {}
_lock = threading.Lock()


def passes_quality(rows):
    if len(rows) < MIN_BARS or rows[-1][3] < MIN_PRICE:
        return "thin"
    if sum(r[3] * r[5] for r in rows[-20:]) / 20 < MIN_AVG_VALUE:
        return "illiquid"
    a = [r[4] for r in rows[-500:]]
    if any(abs(a[i] / a[i - 1] - 1) > MAX_DAY_MOVE for i in range(1, len(a))):
        return "suspect"
    return None


def last_cutoff(now=None):
    """The most recent SCAN_HOUR:00 IST on a trading day that has already passed. A scan made before it predates
    that day's close, so it is stale; one made after it is current until the next cutoff."""
    now = now or datetime.datetime.now(IST)
    d = now.date()
    if not (is_td(d) and now.hour >= SCAN_HOUR):
        d -= datetime.timedelta(days=1)
        while not is_td(d):
            d -= datetime.timedelta(days=1)
    return datetime.datetime(d.year, d.month, d.day, SCAN_HOUR, tzinfo=IST)


def scan_is_current(t, now=None):
    return t >= last_cutoff(now).timestamp()


SCAN_VERSION = 2   # bump when the saved scan gains fields (2: track report, last closes of filtered-out stocks): older saves are rebuilt once


def scan_up_to_date():
    """The scan in memory was made after the latest market close by this version of the code, so a refresh could not find anything newer."""
    d = STATE["data"]
    return bool(d) and d.get("v") == SCAN_VERSION and scan_is_current(STATE["t"])


def cache_outdated(cpath, force=False, now=None):
    """Whether today's saved price download must be thrown away and fetched again: it was made before the latest close (a partial bar), or the
    user asked for a full re-download. A plain refresh reuses a download made after the close: Yahoo has nothing newer until the next close."""
    return os.path.exists(cpath) and (force == "full" or os.path.getmtime(cpath) < last_cutoff(now).timestamp())


class LazyBars(dict):
    """symbol -> bars read from the database only when asked for, so scoring holds one history at a time instead of all of them.
    The dict keys are the symbols; items() and values() load each history as they are iterated and let it go afterwards."""

    def __init__(self, symbols, load):
        super().__init__(dict.fromkeys(symbols))
        self._load = load

    def __getitem__(self, sym):
        return self._load(sym)

    def items(self):
        for s in list(dict.keys(self)):
            rows = self._load(s)
            if rows:   # an unreadable row is skipped, and fetched again by the next scan
                yield s, rows

    def values(self):
        return (rows for _, rows in self.items())


def price_db():
    """The store that holds the price cache, or None to keep it in files (no DATABASE_URL)."""
    return get_store() if os.environ.get("DATABASE_URL", "").strip() else None


lists.db = price_db   # imported ETF and BSE lists live in the database too when there is one
cachefs.backend = price_db   # and so do the downloaded NSE/BSE files and company facts, which a restart would otherwise fetch again


def backfill_quotes(data):
    """A scan saved before last closes were kept has no 'quotes'. Build them from the newest saved price download so holdings the scan
    filters out are valued straight away, without waiting for a new scan."""
    if not data or "quotes" in data:
        return
    quotes = {}
    try:
        if price_db():
            raise OSError("price cache is in the database")   # a current scan always carries its quotes; nothing to rebuild from files
        files = sorted(glob.glob(os.path.join(CACHE_DIR, "rows-*.pkl")))
        res = pickle.load(open(files[-1], "rb")) if files else {}
        scanned, today = {s["symbol"] for s in data.get("stocks", [])}, datetime.date.today()
        for sym, rows in res.items():
            if sym == "^NSEI" or sym in scanned or not rows:
                continue
            if isinstance(rows, dict):
                if rows["why"] != "stale" and (today - datetime.date.fromisoformat(rows["asof"])).days <= 7:
                    quotes[sym] = rows
                continue
            if (today - rows[-1][0]).days > 7:
                continue
            why = passes_quality(rows)
            if why:
                quotes[sym] = quote_row(rows, why)
    except Exception:
        quotes = {}      # unreadable cache: the portfolio simply shows those holdings without a price until the next scan
    data["quotes"] = quotes


def scan_file():
    return os.path.join(CACHE_DIR, "scan-latest.pkl")


_seen_scan = [0.0]    # stamp (database save time, or file mtime) of the newest saved scan this process has already looked at
_scan_checked = [0.0]
SCAN_CHECK_SECONDS = 10   # with a database: look for a newer saved scan at most this often (each look is a round trip)


def save_scan():
    """Keep the finished scan on disk (or in the database) so a restart (or the page) never has to wait for a recompute."""
    pdb = price_db()
    if pdb:
        pdb.blob_put("scan-latest", {"t": STATE["t"], "data": STATE["data"], "detail": dict(DETAIL)})
        _seen_scan[0] = pdb.blob_saved("scan-latest") or 0.0   # this process just wrote it: no need to read it back
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = scan_file() + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump({"t": STATE["t"], "data": STATE["data"], "detail": dict(DETAIL)}, f)
    os.replace(tmp, scan_file())
    _seen_scan[0] = os.path.getmtime(scan_file())


_scan_lock = threading.Lock()


def load_scan():
    """Adopt the saved scan when it is newer than what is in memory (server start, or the daily job finished
    while the server was running). True if it was loaded. One caller at a time: at start-up the start-up thread and the first page load both
    come here, and the second must wait for the first to finish, not give up and see "no data" (that started a needless full scan)."""
    with _scan_lock:
        try:
            pdb = price_db()
            if pdb:
                if STATE["data"] is not None and time.time() - _scan_checked[0] < SCAN_CHECK_SECONDS:
                    return False   # already have a scan: look for a newer one only every few seconds, each look is a database round trip
                _scan_checked[0] = time.time()
                stamp = pdb.blob_saved("scan-latest")
            else:
                stamp = os.path.getmtime(scan_file()) if os.path.exists(scan_file()) else None
            # a saved scan is always stamped a moment after the time inside it, so comparing the stamp with STATE["t"] never settles:
            # remember the stamp of the version already looked at instead, and read a saved scan only when a newer one appears
            if stamp is None or stamp <= STATE["t"] or (STATE["data"] is not None and stamp <= _seen_scan[0]):   # with nothing in memory, always read
                return False
            saved = pdb.blob_get("scan-latest") if pdb else pickle.load(open(scan_file(), "rb"))
            _seen_scan[0] = stamp
            if not saved or not saved.get("data") or saved["t"] <= STATE["t"]:
                return False
        except Exception:
            _scan_checked[0] = 0.0   # the look failed: try again on the next call, not after the pause
            return False
        DETAIL.clear()
        DETAIL.update(saved["detail"])
        backfill_quotes(saved["data"])
        STATE.update(t=saved["t"], data=saved["data"], error=None)
        return True


def older_cache(current):
    """Rows from the newest earlier daily cache file, or {} if none can be read."""
    files = sorted(f for f in os.listdir(CACHE_DIR) if f.startswith("rows-") and f.endswith(".pkl"))
    for f in reversed(files):
        path = os.path.join(CACHE_DIR, f)
        if path != current:
            try:
                return pickle.load(open(path, "rb"))
            except Exception:
                continue
    return {}


def stale_since(asof, today):
    """Latest trading day before today if the newest price bar is older than it, else None."""
    d = today - datetime.timedelta(days=1)
    while not is_td(d):
        d -= datetime.timedelta(days=1)
    return d.isoformat() if asof < d else None


def run_scan(force):
    try:
        today = datetime.date.today()
        names, info, imp = lists.merge(load_universe(), lists.union(bhavcopy.auto_lists(), lists.load()))
        syms = list(names) + ["^NSEI"]
        symset = set(syms)
        core = [x for x in syms if info.get(x, {}).get("exchange") != "BSE"]   # the failure check ignores BSE rows
        cpath = os.path.join(CACHE_DIR, f"rows-{today.isoformat()}.pkl")
        pdb = price_db()   # prices live in the database when DATABASE_URL is set, in cache/rows-<date>.pkl otherwise
        if pdb:
            # a symbol fetched before today's close holds a partial bar, and a full re-download was asked for: fetch those again
            res = {} if force == "full" else pdb.price_index(last_cutoff().timestamp())
        else:
            if cache_outdated(cpath, force):
                os.remove(cpath)   # fetched before today's close (a partial bar), or a full re-download was asked for
            try:
                res = pickle.load(open(cpath, "rb")) if os.path.exists(cpath) else {}
            except Exception:
                res = {}   # truncated or unreadable cache: download again
        res = {k: (v if k == "^NSEI" else slim(v, today)) for k, v in res.items()}
        if pdb and "^NSEI" in res:
            res["^NSEI"] = pdb.price_one("^NSEI")   # the benchmark's bars are always held in memory
            if not res["^NSEI"]:
                del res["^NSEI"]
        todo = [x for x in syms if x not in res]
        fallback = False   # True when Yahoo was unreachable and an older saved scan's prices are being reused
        t0 = time.time()
        STATE.update(phase="Downloading 5 years of prices", done=len(syms) - len(todo), total=len(syms))
        with ThreadPoolExecutor(16) as ex:
            def submit(x):
                i = info.get(x, {})
                return ex.submit(fetch, x, i["suffix"], i["yahoo"]) if i.get("suffix") else ex.submit(fetch, x)
            queue, pending, unsaved = iter(todo), set(), {}
            while True:
                while len(pending) < 64:   # a bounded window: finished downloads are handled and freed, not queued up in memory
                    x = next(queue, None)
                    if x is None:
                        break
                    pending.add(submit(x))
                if not pending:
                    break
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in finished:
                    sym, rows = fut.result()
                    v = rows if sym == "^NSEI" else slim(rows, today)
                    if pdb and v:
                        unsaved[sym] = v   # saved in small batches (one commit each), so a restart resumes close to where it stopped
                        if len(unsaved) >= 25:
                            pdb.price_save(unsaved)
                            unsaved = {}
                        if isinstance(v, list) and sym != "^NSEI":
                            v = True   # the history stays in the database: scoring reads it back one symbol at a time
                    res[sym] = v
                    STATE["done"] += 1
            if pdb and unsaved:
                pdb.price_save(unsaved)
        if sum(1 for x in core if res.get(x)) < len(core) / 2:
            old = None
            if pdb:
                old = pdb.price_index()   # Yahoo unreachable: serve the newest saved scan data, flagged stale on the page
                bench = pdb.price_one("^NSEI")
                if bench:
                    old["^NSEI"] = bench
            else:
                old = older_cache(cpath)
            if not old:
                raise RuntimeError("Yahoo Finance is unreachable and there is no saved data yet")
            res, fallback = old, True
        elif not pdb:
            pickle.dump({k: v for k, v in res.items() if v}, open(cpath + ".tmp", "wb"))
            os.replace(cpath + ".tmp", cpath)
        res = {k: v for k, v in res.items() if k in symset}   # drop cached rows of lists that were cleared
        STATE.update(phase="Scoring and forecasting", done=0, total=1)
        nrows = res.pop("^NSEI", None)
        data, excl, quotes = (LazyBars((), pdb.price_one) if pdb else {}), {"nodata": 0, "thin": 0, "illiquid": 0, "suspect": 0, "stale": 0}, {}
        for sym, rows in res.items():
            if not rows:
                excl["nodata"] += 1
            elif rows is True:   # passes the filter; the history is in the database
                data[sym] = True
            elif isinstance(rows, dict):   # slimmed: filtered out already
                if rows["why"] == "stale":
                    excl["stale"] += 1
                else:
                    excl[rows["why"]] += 1
                    quotes[sym] = rows
            elif (today - rows[-1][0]).days > 7:
                excl["stale"] += 1
            else:
                why = passes_quality(rows)
                if why:
                    excl[why] += 1
                    quotes[sym] = quote_row(rows, why)
                else:
                    data[sym] = rows
        pool, scores = build_pool(data, nrows)
        fcst = Forecaster(pool, scores)
        newest_bar = nrows[-1][0].isoformat() if nrows else None
        pending, settled = live_check_pending(newest_bar), []
        stocks = sorted((analyse(s, r, nrows, fcst, names.get(s, s), info.get(s)) for s, r in settling(data.items(), pending, settled)),
                        key=lambda x: -x["score"])
        STATE.update(phase="Reading news", done=0, total=1)
        with ThreadPoolExecutor(8) as ex:
            for s, n in zip(stocks[:40], ex.map(lambda s: news(s["symbol"], s["name"]), stocks[:40])):
                s["news"] = n
        track = track_record(pool)
        train, held, cutoff = split_pool(pool)
        report = backtest.format_report(track, len(data), len(pool), len(train), len(held), cutoff, PURGE_DAYS, "scan of " + today.isoformat())
        for s in stocks:
            decide(s, today, base_rate(pool, track))
        if not stocks:
            raise RuntimeError("the scan found no usable stocks (%d symbols, filtered out: %s, unreadable or empty price rows: %d). "
                               "Yahoo may be blocking this host or returning partial data; check the logs and try Refresh data again"
                               % (len(syms) - 1, excl, len(data) - len(stocks)))
        last = max(datetime.date.fromisoformat(s["asof"]) for s in stocks)
        buy = first_td_from(max(today, last + datetime.timedelta(days=1)))
        DETAIL.clear()
        for s in stocks:
            DETAIL[s["symbol"]] = {k: s.pop(k, None) for k in ("series", "why", "news", "note")}
        sells = {k: add_td(buy, h).isoformat() for k, h in HORIZONS.items()}
        # Old prices are stamped just before the cutoff, so the scan stays "stale" and is retried instead of
        # being treated as today's data.
        STATE.update(t=last_cutoff().timestamp() - 1 if fallback else time.time(), data={
            "generated": time.strftime("%d %b %Y %H:%M"), "today": today.isoformat(), "stocks": stocks,
            "scanSeconds": round(time.time() - t0, 1), "baseline": baseline_from(stocks),
            "buyDate": buy.isoformat(), "sellDates": sells,
            "v": SCAN_VERSION, "track": track, "trackReport": report, "quotes": quotes, "poolSize": len(pool), "universe": len(syms) - 1 - imp["bse"], "imports": imp, "excluded": excl,
            "benchmark": bool(nrows), "holidayWarnings": holiday_warnings([buy.isoformat(), *sells.values()]),
            "holidaysChecked": HOLIDAY_DOC.get("lastCheck"),
            "holidayAlert": update_holidays.stale_alert(HOLIDAY_DOC, today),
            "minPrice": MIN_PRICE, "minValue": MIN_AVG_VALUE}, error=None)
        live_check_update(stocks, settled, newest_bar, fallback)
        try:
            save_scan()
        except Exception:
            pass   # a read-only disk must not fail the scan itself
    except Exception as e:
        STATE["error"] = f"{type(e).__name__}: {e}"
    finally:
        STATE["running"] = False


def live_check_pending(newest_bar):
    """Saved forecasts that are due to be checked, {symbol: [forecast]}. Never raises: the live check must not be able to fail a scan."""
    try:
        return get_store().fc_pending(newest_bar) if newest_bar else {}
    except Exception as e:
        print("live check: could not read saved forecasts:", type(e).__name__, e)
        return {}


def settling(items, pending, out):
    """Passes (symbol, price history) pairs through unchanged and, for each symbol with forecasts due, adds their results to `out`. The scan
    loads every history once anyway, so checking the forecasts costs next to nothing extra."""
    for sym, rows in items:
        due = pending.get(sym)
        if due:
            try:
                out.extend(livecheck.settle(due, rows))
            except Exception as e:
                print("live check: could not settle", sym, type(e).__name__, e)
        yield sym, rows


def live_check_update(stocks, settled, newest_bar, fallback):
    """After a scan: record the forecasts that have now been checked, drop the unfinishable and the old, and save tonight's forecasts to be checked
    later. Tonight's are saved only from a complete day's bar, and never from old data reused because Yahoo was unreachable."""
    try:
        st = get_store()
        if settled:
            st.fc_settle(settled, datetime.date.today().isoformat())
        if newest_bar:
            st.fc_expire(newest_bar)
            st.fc_prune(newest_bar)
        if not fallback and stocks and livecheck.bar_is_final(max(s["asof"] for s in stocks), datetime.datetime.now(IST)):
            st.fc_record(livecheck.snapshot_rows(stocks, {hz: HORIZONS[hz] for hz in livecheck.TRACKED}, add_td))
    except Exception as e:
        print("live check: not updated:", type(e).__name__, e)


def baseline_from(stocks):
    """NIFTYBEES forecast per horizon (only if it passed the quality filter and so is in stocks)."""
    for s in stocks:
        if s["symbol"] == "NIFTYBEES":
            return {k: {x: v[x] for x in ("p50", "p10", "p90", "pgain")} for k, v in s["forecast"].items()}
    return {}


_force_lock = threading.Lock()
_last_force = [0.0]


def force_allowed():
    """True at most once per FORCE_COOLDOWN seconds."""
    with _force_lock:
        now = time.monotonic()
        if _last_force[0] and now - _last_force[0] < FORCE_COOLDOWN:
            return False
        _last_force[0] = now
        return True


_store = None
_universe = None
# every screen lives in its own folder: app/modules/<screen>/<page>.html (see README, "Project layout")
_HOME, _STOCKS = "modules/home/index.html", "modules/stocks/"
PAGES = {"/": "modules/landing/landing.html", "/index.html": _HOME, "/stocks.html": _STOCKS + "stocks.html", "/etfs.html": _STOCKS + "etfs.html",
         "/bse.html": _STOCKS + "bse.html", "/portfolio.html": "modules/portfolio/portfolio.html", "/about.html": "modules/about/about.html",
         "/stock.html": "modules/stock/stock.html", "/livecheck.html": "modules/livecheck/livecheck.html", "/settings.html": "modules/settings/settings.html", "/account.html": "modules/account/account.html"}
LEGACY_PAGES = {"/stocks": "/stocks.html", "/etfs": "/etfs.html", "/portfolio": "/portfolio.html", "/bse": "/bse.html",
                "/about": "/about.html", "/livecheck": "/livecheck.html", "/settings": "/settings.html", "/account": "/account.html",
                "/privacy": "/privacy.html", "/cookies": "/cookies.html", "/terms": "/terms.html", "/disclaimer": "/disclaimer.html"}   # the old single-page URLs, kept so bookmarks still work
STOCK_PAGE_RE = re.compile(r"^/stock/([A-Za-z0-9&.^%-]{1,40})/?$")
ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml"}
ASSET_DIRS = {"css": {".css"}, "js": {".js"}, "icons": {".png", ".svg"}}
ASSET_RE = re.compile(r"^/assets/(css|js|icons)/[A-Za-z0-9._-]+$")
MODULE_RE = re.compile(r"^/modules/[a-z]+/[A-Za-z0-9._-]+$")   # a screen's own page JS and CSS; the same folder also holds Python, which is never served
MODULE_EXT = {".css", ".js"}


def asset_bytes(path):
    """Shared CSS, JS and icons from app/assets/, plus each screen's own CSS and JS from app/modules/<screen>/. Only those file types,
    so Python files, HTML sources and data on disk are not reachable."""
    ext = os.path.splitext(path)[1]
    m = ASSET_RE.match(path)
    if m:
        if ext not in ASSET_DIRS[m.group(1)]:
            return None
    elif not (MODULE_RE.match(path) and ext in MODULE_EXT):
        return None
    full = os.path.join(HERE, path[1:])
    if not os.path.isfile(full):
        return None
    return open(full, "rb").read(), ASSET_TYPES[ext]


_store_lock = threading.Lock()


def get_store():
    global _store
    if _store is None:
        with _store_lock:   # the start-up thread and the first page load both ask: build it once (two CREATE TABLEs at once collide in PostgreSQL)
            if _store is None:
                url = os.environ.get("DATABASE_URL", "").strip()   # PostgreSQL when set, otherwise SQLite under DATA_DIR
                if url:
                    _store = Store(url)
                else:
                    os.makedirs(DATA_DIR, exist_ok=True)
                    _store = Store(os.path.join(DATA_DIR, "users.db"))
    return _store


def get_universe():
    global _universe
    if _universe is None:
        _universe = set(load_universe())
    return _universe


def health():
    d = STATE["data"]
    asof = max((x["asof"] for x in d["stocks"]), default=None) if d else None
    return {"ok": True, "dataAsOf": asof, "scanAgeMinutes": int((time.time() - STATE["t"]) // 60) if d else None}


_page = {}
_page_lock = threading.Lock()


SOCIAL_IMAGE = "/assets/icons/og-image.png"   # 1200 x 630
SOCIAL_DESCRIPTION = ("Buy-and-hold picks for NSE shares and ETFs: a buy date, a review date, a stop-loss, a forecast range and the reasons "
                      "behind every pick. Free, no sign-up. Educational, not investment advice.")


def site_base(headers):
    """The public address of this site, for the absolute URLs link previews need: SITE_URL, else the address Render gives the service, else
    the Host header of the request (a local run)."""
    base = (os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if base.startswith(("http://", "https://")):
        return base
    host = re.sub(r"[^A-Za-z0-9.:-]", "", headers.get("Host") or "")[:100] or "localhost"
    return "http://" + host


def add_social_tags(page, path, base):
    """Open Graph and Twitter card tags in the page's head, so a shared link shows the title, a description and the logo card instead of a
    grey placeholder. Built from the page's own <title> and description; a page that already has them is left alone."""
    text = page.decode("utf-8")
    if 'property="og:title"' in text or "</head>" not in text:
        return page
    m = re.search(r"<title>(.*?)</title>", text, re.S)
    title = html.unescape(m.group(1).strip()) if m else "Long-Term Stock Picks"
    d = re.search(r'<meta name="description" content="([^"]*)"', text)
    desc = html.unescape(d.group(1)) if d else SOCIAL_DESCRIPTION
    q = lambda v: html.escape(v, quote=True)
    tags = "".join('<meta %s="%s" content="%s">' % (k, n, q(v)) for k, n, v in (
        ("property", "og:type", "website"), ("property", "og:site_name", "Long-Term Stock Picks"), ("property", "og:title", title),
        ("property", "og:description", desc), ("property", "og:url", base + ("" if path == "/" else path)),
        ("property", "og:image", base + SOCIAL_IMAGE), ("property", "og:image:type", "image/png"), ("property", "og:image:width", "1200"),
        ("property", "og:image:height", "630"), ("property", "og:image:alt", "Long-Term Stock Picks: long-term NSE stock picks, with the reasons shown"),
        ("name", "twitter:card", "summary_large_image"), ("name", "twitter:title", title), ("name", "twitter:description", desc),
        ("name", "twitter:image", base + SOCIAL_IMAGE)))
    if not d:
        tags = '<meta name="description" content="%s">' % q(desc) + tags
    return text.replace("</head>", tags + "</head>", 1).encode("utf-8")


LEGAL_UPDATED = "25 October 2026"
LEGAL_PAGES = {"/privacy.html": ("Privacy Policy", "privacy"), "/cookies.html": ("Cookie Policy", "cookies"),
               "/terms.html": ("Terms of Use", "terms"), "/disclaimer.html": ("Disclaimer", "disclaimer")}


def legal_bytes(path):
    """A legal page: modules/legal/layout.html around <name>.body.html, with the operator's details filled in. The details come from the
    environment (LEGAL_OPERATOR, LEGAL_EMAIL, LEGAL_ADDRESS, LEGAL_GRIEVANCE, LEGAL_JURISDICTION, LEGAL_SEBI_STATUS); an unset one shows a
    visible placeholder so nobody publishes the pages without them."""
    title, name = LEGAL_PAGES[path]
    env = lambda k, d: html.escape(os.environ.get(k, "").strip() or d)
    operator = env("LEGAL_OPERATOR", "the operator of this website")
    vals = {"title": html.escape(title), "updated": LEGAL_UPDATED, "operator": operator,
            "email": env("LEGAL_EMAIL", "[contact email not set: set LEGAL_EMAIL]"),
            "address": env("LEGAL_ADDRESS", ""),
            "grievance": env("LEGAL_GRIEVANCE", operator),
            "jurisdiction": env("LEGAL_JURISDICTION", "[city and state not set: set LEGAL_JURISDICTION]"),
            "sebi": env("LEGAL_SEBI_STATUS", "This service is not registered with SEBI as an investment adviser or a research analyst.")}
    body = page_bytes(f"modules/legal/{name}.body.html").decode("utf-8")
    page = page_bytes("modules/legal/layout.html").decode("utf-8").replace("{{body}}", body)
    return re.sub(r"\{\{(\w+)\}\}", lambda m: vals.get(m.group(1), m.group(0)), page).encode("utf-8")


def page_bytes(name="index.html"):
    path = os.path.join(HERE, name)
    m = os.path.getmtime(path)
    with _page_lock:
        if _page.get(name, (None,))[0] != m:
            _page[name] = (m, open(path, "rb").read())
        return _page[name][1]


def start_scan(force=False):
    with _lock:
        if STATE["running"]:
            return
        STATE.update(running=True, error=None)
    threading.Thread(target=run_scan, args=(force,), daemon=True).start()


_last_auto = [0.0]
AUTO_RETRY_SECONDS = 600   # a failed background refresh is retried at most this often


def api_scan(force):
    """force: False, True (Refresh data) or "full" (re-download everything). A plain refresh of data that is already from the latest close
    answers at once with upToDate instead of starting a scan that could only reproduce it."""
    load_scan()   # the daily job may have saved a newer scan than the one in memory
    stale = bool(STATE["data"]) and not scan_up_to_date()
    up_to_date = False
    if force is True and not STATE["running"] and scan_up_to_date():
        up_to_date, force = True, False
    else:
        asked = bool(force)                       # "full" is truthy too
        force = ("full" if force == "full" else True) if asked and force_allowed() else False
    auto = stale and time.time() - _last_auto[0] > AUTO_RETRY_SECONDS
    if force or auto or (not STATE["data"] and not STATE["running"] and not STATE["error"]):
        if auto:
            _last_auto[0] = time.time()
        start_scan(force)
    if STATE["data"]:
        asof = max((x["asof"] for x in STATE["data"]["stocks"]), default="")
        body = {k: v for k, v in STATE["data"].items() if k not in ("trackReport", "quotes")}   # the report has its own address, and quotes are for the portfolio only
        return dict(body, status="ready", refreshing=STATE["running"], upToDate=up_to_date,
                    progress={"phase": STATE["phase"], "done": STATE["done"], "total": STATE["total"]} if STATE["running"] else None,
                    refreshError=None if STATE["running"] else STATE["error"],
                    staleSince=stale_since(datetime.date.fromisoformat(asof), datetime.date.today()) if asof else None)
    return {"status": "error" if STATE["error"] else "loading", "error": STATE["error"], "phase": STATE["phase"],
            "done": STATE["done"], "total": STATE["total"]}


_gz_cache, _gz_lock = {}, threading.Lock()
GZIP_TYPES = ("text/", "application/json", "application/javascript", "application/manifest+json", "image/svg+xml")
GZIP_MIN = 1400


def gzipped(body):
    """gzip of body, kept for next time (the same page, script or scan is sent to every visitor); at most 48 entries."""
    key = (len(body), hash(body))
    with _gz_lock:
        if key in _gz_cache:
            return _gz_cache[key]
    out = gzip.compress(body, 6, mtime=0)
    with _gz_lock:
        if len(_gz_cache) >= 48:
            _gz_cache.pop(next(iter(_gz_cache)))
        _gz_cache[key] = out
    return out


_scan_body = [None, b""]   # [key, serialized /api/scan]


def scan_json(qs):
    """The /api/scan answer as JSON bytes. The scan is 2 to 3 MB of JSON, so it is serialized once and reused until something in the answer changes."""
    res = api_scan("full" if qs.get("force") == ["full"] else "force" in qs)
    if res.get("status") != "ready":
        return json.dumps(res).encode()
    key = (id(STATE["data"]), res["refreshing"], res["upToDate"], res["refreshError"], res["staleSince"], json.dumps(res["progress"]))
    if _scan_body[0] != key:
        _scan_body[1], _scan_body[0] = json.dumps(res).encode(), key
    return _scan_body[1]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    head_only = False

    def drain(self, n, cap=16 * 1024 * 1024):
        """Read and discard a refused body so the client can finish sending and see the 413, not a reset."""
        left = min(n, cap)
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)

    def drain_request(self):
        try:
            self.drain(int(self.headers.get("Content-Length") or 0))
        except ValueError:
            pass

    def do_HEAD(self):
        self.head_only = True
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/health":
            body, ctype = json.dumps(health()).encode(), "application/json"
        elif u.path == "/api/scan":
            qs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
            body, ctype = scan_json(qs), "application/json"
        elif u.path == "/api/live-check":
            st = get_store()
            body, ctype = json.dumps(livecheck.summarize(st.fc_stats(), st.fc_counts())).encode(), "application/json"
        elif u.path == "/api/forecast.xlsx":
            hz = urllib.parse.parse_qs(u.query).get("hz", ["1d"])[0]
            if hz not in HORIZONS:
                return self.reply(400, json.dumps({"error": "hz must be one of " + ", ".join(HORIZONS)}).encode(), "application/json")
            got = forecast_xlsx_file(hz)
            if not got:
                return self.reply(503, json.dumps({"error": "The scan is not ready yet. Try again in a few minutes."}).encode(), "application/json")
            return self.reply(200, got[1], XLSX_TYPE, {"Content-Disposition": 'attachment; filename="%s"' % got[0]})
        elif u.path == "/api/stock":
            sym = urllib.parse.parse_qs(u.query).get("sym", [""])[0]
            if not SYM_RE.fullmatch(sym):
                return self.reply(400, json.dumps({"error": "invalid symbol"}).encode(), "application/json")
            if sym not in DETAIL:
                return self.reply(404, json.dumps({"error": f"unknown symbol: {sym[:30]}"}).encode(), "application/json")
            body, ctype = json.dumps(DETAIL[sym]).encode(), "application/json"
        elif u.path == "/api/track-record":
            report = (STATE["data"] or {}).get("trackReport")
            if not report:
                return self.reply(404, b"No track record yet: the first scan of the day is still running.", "text/plain; charset=utf-8")
            body, ctype = report.encode("utf-8"), "text/plain; charset=utf-8"
        elif u.path == "/api/chart":
            sym = urllib.parse.parse_qs(u.query).get("sym", [""])[0]
            if not SYM_RE.fullmatch(sym):
                return self.reply(400, json.dumps({"error": "invalid symbol"}).encode(), "application/json")
            if sym != "^NSEI" and sym not in DETAIL:   # only symbols the scan lists: this is not an open Yahoo proxy
                return self.reply(404, json.dumps({"error": f"unknown symbol: {sym[:30]}"}).encode(), "application/json")
            data = chart_payload(sym)
            if not data:
                return self.reply(502, json.dumps({"error": "price history unavailable"}).encode(), "application/json")
            body, ctype = json.dumps(data, separators=(",", ":")).encode(), "application/json"
        elif u.path == "/api/why":
            sym = urllib.parse.parse_qs(u.query).get("sym", [""])[0]
            if not SYM_RE.fullmatch(sym) or sym == "^NSEI":
                return self.reply(400, json.dumps({"error": "invalid symbol"}).encode(), "application/json")
            if sym not in DETAIL:
                return self.reply(404, json.dumps({"error": f"unknown symbol: {sym[:30]}"}).encode(), "application/json")
            body, ctype = json.dumps(api_why(sym)).encode(), "application/json"
        elif u.path == "/api/bhav":
            sym = urllib.parse.parse_qs(u.query).get("sym", [""])[0]
            if not SYM_RE.fullmatch(sym):
                return self.reply(400, json.dumps({"error": "invalid symbol"}).encode(), "application/json")
            rows = bhavcopy.both(sym, {ex: bhavcopy.latest(ex) for ex in ("NSE", "BSE")})
            if not rows:
                return self.reply(404, json.dumps({"error": f"not in latest bhavcopy: {sym[:30]}"}).encode(), "application/json")
            body, ctype = json.dumps(rows).encode(), "application/json"
        elif u.path in PAGES:
            body, ctype = add_social_tags(page_bytes(PAGES[u.path]), u.path, site_base(self.headers)), "text/html; charset=utf-8"
            if not self.head_only:
                count_view(u.path, self.headers.get("User-Agent"))
        elif u.path in LEGAL_PAGES:
            body, ctype = add_social_tags(legal_bytes(u.path), u.path, site_base(self.headers)), "text/html; charset=utf-8"
            if not self.head_only:
                count_view(u.path, self.headers.get("User-Agent"))
        elif u.path == "/stats.html" and os.environ.get("STATS_TOKEN", "").strip():
            body, ctype = page_bytes("modules/stats/stats.html"), "text/html; charset=utf-8"
        elif u.path == "/api/stats":
            if not stats_allowed(self.headers):
                return self.reply(404, b"Not found", "text/plain")     # off, or the wrong token: it looks like any other missing page
            flush_views()
            body, ctype = json.dumps(get_store().views_summary(today_ist())).encode(), "application/json"
        elif u.path == "/manifest.webmanifest":
            body, ctype = open(os.path.join(HERE, "manifest.webmanifest"), "rb").read(), "application/manifest+json"
        elif u.path in LEGACY_PAGES or STOCK_PAGE_RE.match(u.path):
            m = STOCK_PAGE_RE.match(u.path)
            where = LEGACY_PAGES.get(u.path) or "/stock.html?symbol=" + m.group(1).rstrip("/")
            return self.reply(301, b"", "text/plain", {"Location": where})
        elif asset_bytes(u.path):
            body, ctype = asset_bytes(u.path)
        elif u.path in ("/api/me", "/api/export", "/api/export.csv", "/api/lots", "/api/position", "/api/rules", "/api/attention", "/api/session", "/api/notes", "/api/price-alerts", "/api/groww", "/api/auth/me"):
            return self.user_api("GET", u)
        elif u.path == "/api/import/list":
            return self.import_api("GET", u)
        else:
            return self.reply(404, b"Not found", "text/plain")
        self.reply(200, body, ctype)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        (self.import_api if u.path == "/api/import/list" else self.user_api)("POST", u)

    def do_PUT(self):
        self.user_api("PUT", urllib.parse.urlparse(self.path))

    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        (self.import_api if u.path == "/api/import/list" else self.user_api)("DELETE", u)

    new_cookies = ()

    def import_api(self, method, u):
        """Manual exchange-list import (personal use). Same-origin writes only, small bodies only."""
        j = "application/json"
        if method != "GET" and not api_me.same_origin(self.headers):
            self.drain_request()
            return self.reply(403, json.dumps({"error": "cross-site request refused"}).encode(), j)
        raw = b""
        if method == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                return self.reply(400, json.dumps({"error": "bad Content-Length"}).encode(), j)
            if n > lists.MAX_BODY:
                self.drain(n)
                return self.reply(413, json.dumps({"error": "request too large"}).encode(), j)
            raw = self.rfile.read(n) if n else b""
        code, obj = lists.handle(method, u.query, raw)
        if code == 200 and method != "GET":
            STATE["t"] = 0   # the next /api/scan sees the data as stale and re-scans (cached prices are reused)
        self.reply(code, json.dumps(obj).encode(), j)

    def user_api(self, method, u):
        if not u.path.startswith(("/api/me", "/api/export", "/api/holdings", "/api/watchlist", "/api/alerts", "/api/lots", "/api/position",
                                  "/api/rules", "/api/attention", "/api/transactions", "/api/session", "/api/notes", "/api/price-alerts", "/api/groww", "/api/auth")):
            return self.reply(404, b"Not found", "text/plain")
        if method != "GET" and not api_me.same_origin(self.headers):
            self.drain_request()
            return self.reply(403, json.dumps({"error": "cross-site request refused"}).encode(), "application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n > api_me.MAX_BODY:
            self.drain(n)
            return self.reply(413, json.dumps({"error": "request too large"}).encode(), "application/json")
        raw = self.rfile.read(n) if n else b""
        store = get_store()
        ident = api_me.identify(self.headers.get("Cookie"), store)   # a valid session means the signed-in account, otherwise a guest id
        ctx = {"detail": DETAIL, "facts": lambda items: fundamentals.get_many(items), "ident": ident, "cookies": [],
               "ip": self.client_address[0]}
        code, obj = api_me.handle(method, u.path, u.query, raw, store, ident.uid, STATE["data"], get_universe(), ctx=ctx)
        jar = {}
        for c in ident.cookies + ctx["cookies"]:    # one Set-Cookie per name, the last one wins (a sign-in replaces the guest cookie)
            jar[c.split("=", 1)[0]] = c
        self.new_cookies = list(jar.values())
        if isinstance(obj, dict) and "_csv" in obj:
            return self.reply(code, obj["_csv"].encode("utf-8"), "text/csv; charset=utf-8",
                              {"Content-Disposition": "attachment; filename=%s" % obj["_name"]})
        headers = {"Content-Disposition": "attachment; filename=my-stock-picks-data.json"} if u.path == "/api/export" else {}
        self.reply(code, json.dumps(obj).encode(), "application/json", headers)

    def reply(self, code, body, ctype, extra=None):
        etag = None
        if code == 200 and ctype != "application/json" and body and not extra:
            # pages, scripts and styles: a visitor whose copy is unchanged gets a tiny 304 instead of the whole file again
            etag = 'W/"%x-%x"' % (len(body), zlib.crc32(body))
            if etag in (self.headers.get("If-None-Match") or ""):
                code, body = 304, b""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        for c in self.new_cookies:
            self.send_header("Set-Cookie", c)
        self.send_header("Cache-Control", "no-store" if ctype == "application/json" else "no-cache")
        if etag:
            self.send_header("ETag", etag)
        if ctype.startswith(GZIP_TYPES) and len(body) >= GZIP_MIN and code == 200:
            self.send_header("Vary", "Accept-Encoding")
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body = gzipped(body)
                self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if not self.head_only:
            self.wfile.write(body)


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), H)   # listen first: a host (Render) wants an open port before the slow start-up work below

    def startup():
        try:
            refresh_holidays()
        except Exception as e:
            print("holiday check failed:", type(e).__name__, e)
        if not (load_scan() and scan_up_to_date()):   # a current saved scan opens instantly, no recompute
            _last_auto[0] = time.time()
            start_scan()
        holiday_watch(threading.Event())
    threading.Thread(target=startup, daemon=True, name="startup").start()
    threading.Thread(target=scan_watch, args=(threading.Event(),), daemon=True, name="scan-watch").start()
    threading.Thread(target=views_watch, args=(threading.Event(),), daemon=True, name="views-watch").start()
    if keepalive_url():
        threading.Thread(target=keepalive, args=(threading.Event(), keepalive_url()), daemon=True, name="keepalive").start()
    if HOST == "127.0.0.1":   # local run: open the browser; a server has none
        threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"Stock Picks running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    srv.serve_forever()
