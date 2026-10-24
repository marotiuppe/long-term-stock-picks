#!/usr/bin/env python3
"""Price alerts and the NYSE clock for trader-alerts. Standard library only.

    python3 alerts.py clock                          # is the NYSE open? next open / close
    python3 alerts.py quote TSLA --write             # quotes -> trader/prices.json
    python3 alerts.py quote --holdings --write       # every ticker in your portfolio and plan
    python3 alerts.py add --from-plan                # stop, target and flat-by-close from trader/plan.json
    python3 alerts.py add --symbol TSLA --stop 358.32
    python3 alerts.py add --symbol TSLA --target 370.04
    python3 alerts.py add --at 15:55 --label "flat by close" --before-close
    python3 alerts.py add --symbol KO --pct 3
    python3 alerts.py add --opening-bell
    python3 alerts.py check                          # rings what hit, once; exit 1 if nothing rang
    python3 alerts.py check --now "2026-10-19 15:55" --offline tests/fixtures/trader-alerts
    python3 alerts.py list
    python3 alerts.py reset tsla-plan-stop

Rule types:
  above / target  the price is at or above "price"
  below / stop    the price is at or below "price"
  pct_move        the price moved "pct" percent or more from the previous close
                  (or from "ref" if you give one); "direction": "up" or "down"
  opening_bell    the NYSE opened today (rings once per trading day)
  time            the New York clock passed "at" (HH:MM) on a trading day
                  (rings once per trading day); "before_close": true moves it
                  3 hours earlier on a 1:00 p.m. early close, so a 15:55
                  "flat by close" rings at 12:55 on those days

A rule with "date" is only watched on that New York date (rules from a plan
are for the plan's day only). An above / below alert rings ONCE and then stays
quiet until you reset it, unless the rule has "rearm": true (it re-arms when
the price crosses back). A pct_move alert rings at most once per day.

Quotes (free, delayed, unofficial; for alerts only, never for timing an order):
  yahoo   https://query2.finance.yahoo.com/v8/finance/chart/TSLA (falls back to
          query1 on a 429 or a 5xx; one retry with a pause on a 429; one
          request per ticker, half a second apart; the default)
  stooq   https://stooq.com/q/l/?s=tsla.us&f=sd2t2ohlcv&h&e=csv (Stooq's free
          CSV; it answered 404 on 2026-10-13, kept for when it is back)
  --offline DIR reads DIR/<source>-<TICKER>.json|csv (or .json.gz) instead.

NYSE calendar: the 2026 and 2027 holidays and 1:00 p.m. early closes as
published at https://www.nyse.com/markets/hours-calendars (read 2026-10-13).
Outside those years the clock says the holiday list is unknown.
"""

import argparse
import csv
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
PAUSE = 0.5    # seconds between requests: be polite to free endpoints
BACKOFF = 2.0  # seconds to wait before the one retry after a 429
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

NYSE_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
NYSE_EARLY_CLOSE = {  # 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
CALENDAR_YEARS = (2026, 2027)
OPEN = datetime.time(9, 30)
CLOSE = datetime.time(16, 0)
EARLY = datetime.time(13, 0)

# India: NSE / BSE equity trading holidays (weekday ones), from the NSE holiday master
# https://www.nseindia.com/api/holiday-master?type=trading (read 2026-10-24). 2027 is not published yet.
# Diwali Laxmi Pujan (2026-11-08, a Sunday) has a one-hour Muhurat session; the exchange announces its time.
NSE_HOLIDAYS = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
NSE_CALENDAR_YEARS = (2026,)
NSE_OPEN = datetime.time(9, 15)
NSE_CLOSE = datetime.time(15, 30)
IST_OFFSET = datetime.timedelta(hours=5, minutes=30)   # India has no daylight saving time

MARKETS = {
    "US": {"exchange": "NYSE", "zone": "New York", "currency": "$", "open": OPEN, "close": CLOSE,
           "holidays": NYSE_HOLIDAYS, "early": NYSE_EARLY_CLOSE, "years": CALENDAR_YEARS,
           "site": "nyse.com"},
    "IN": {"exchange": "NSE", "zone": "India (IST)", "currency": "₹", "open": NSE_OPEN, "close": NSE_CLOSE,
           "holidays": NSE_HOLIDAYS, "early": {}, "years": NSE_CALENDAR_YEARS, "site": "nseindia.com"},
}
INDIAN_SUFFIXES = (".NS", ".BO")


def market_of(sym):
    """'IN' for an NSE (.NS) or BSE (.BO) ticker such as TATSILV.NS, else 'US'."""
    return "IN" if str(sym or "").upper().endswith(INDIAN_SUFFIXES) else "US"


def money(market, x):
    """'$12.34' or '₹12.34'."""
    return "%s%.2f" % (MARKETS[market]["currency"], float(x))


class AlertError(Exception):
    pass


# ---------------------------------------------------------------- time

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def to_local(utc, market="US"):
    """UTC -> that market's wall-clock time (New York or India)."""
    if market == "IN":
        return utc.replace(tzinfo=None) + IST_OFFSET
    return to_eastern(utc)


def local_to_utc(local, market="US"):
    if market == "IN":
        return local - IST_OFFSET
    return eastern_to_utc(local)


def parse_now(text, market="US"):
    """ISO time -> naive UTC. A time without an offset is taken as the market's local time
    (New York for US, India for IN)."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise AlertError("--now wants a time like \"2026-10-19 10:15\" (market local time) or ...Z (UTC)")
    if dt.tzinfo is None:
        return local_to_utc(dt, market)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def trading_day(d, market="US"):
    """(is_trading_day, reason). Weekends and the exchange's holiday list."""
    if d.weekday() >= 5:
        return False, "weekend"
    m = MARKETS[market]
    name = m["holidays"].get(d.isoformat())
    if name:
        return False, "%s holiday: %s" % (m["exchange"], name)
    return True, ""


def session(d, market="US"):
    """(open_time, close_time) in the market's local time, or None if closed all day."""
    ok, _ = trading_day(d, market)
    if not ok:
        return None
    m = MARKETS[market]
    return m["open"], (EARLY if d.isoformat() in m["early"] else m["close"])


def market_status(now_utc, market="US"):
    m = MARKETS[market]
    local = to_local(now_utc, market)
    d = local.date()
    ok, reason = trading_day(d, market)
    st = {"market": market, "exchange": m["exchange"], "now_local": local.strftime("%Y-%m-%d %H:%M"),
          "date": d.isoformat(), "weekday": local.strftime("%A"), "calendar_known": d.year in m["years"],
          "open": False, "reason": reason, "early_close": m["early"].get(d.isoformat())}
    if market == "US":
        st["now_new_york"] = st["now_local"]
    s = session(d, market)
    if s:
        o, c = s
        st["opens"], st["closes"] = o.strftime("%H:%M"), c.strftime("%H:%M")
        if o <= local.time() < c:
            st["open"] = True
            st["reason"] = "regular session"
        elif local.time() < o:
            st["reason"] = "before the open"
        else:
            st["reason"] = "after the close"
    # next open
    nd = d if (s and local.time() < s[0]) else d + datetime.timedelta(days=1)
    for _ in range(15):
        ns = session(nd, market)
        if ns:
            st["next_open"] = "%s %s" % (nd.isoformat(), ns[0].strftime("%H:%M"))
            break
        nd += datetime.timedelta(days=1)
    return st


# ---------------------------------------------------------------- quotes

def stooq_url(sym):
    if market_of(sym) == "IN":
        raise AlertError("Stooq has no Indian stocks: use the default Yahoo source for %s" % sym)
    return "https://stooq.com/q/l/?s=%s.us&f=sd2t2ohlcv&h&e=csv" % sym.lower().replace(".", "-")


def yahoo_symbol(sym):
    """Yahoo's spelling: BRK.B -> BRK-B for US share classes; TATSILV.NS / 500325.BO keep their suffix."""
    sym = sym.upper()
    for suf in INDIAN_SUFFIXES:
        if sym.endswith(suf):
            return sym[:-len(suf)].replace(".", "-") + suf
    return sym.replace(".", "-")


def yahoo_url(sym, host=YAHOO_HOSTS[0]):
    return "https://%s/v8/finance/chart/%s?range=1d&interval=1d" % (host, yahoo_symbol(sym))


def parse_stooq(text, sym):
    """Symbol,Date,Time,Open,High,Low,Close,Volume -> quote. N/D means no data."""
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    if not rows:
        raise AlertError("Stooq returned no rows for %s" % sym)
    r = {k.strip().lower(): (v or "").strip() for k, v in rows[0].items() if k}
    close = r.get("close", "")
    if not close or close.upper() == "N/D":
        raise AlertError("Stooq has no data for %s (check the ticker)" % sym)

    def f(k):
        v = r.get(k, "")
        try:
            return float(v)
        except ValueError:
            return None
    return {"symbol": sym.upper(), "price": float(close), "open": f("open"), "high": f("high"),
            "low": f("low"), "prev_close": None, "time": ("%s %s" % (r.get("date", ""), r.get("time", ""))).strip(),
            "source": "stooq"}


def parse_yahoo(text, sym):
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise AlertError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise AlertError("Yahoo has no data for %s: %s" % (sym, err.get("description", "unknown ticker")))
    m = res[0].get("meta", {})
    price = m.get("regularMarketPrice")
    if price is None:
        raise AlertError("Yahoo has no price for %s" % sym)
    t = m.get("regularMarketTime")
    when = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t else "")
    q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
    opens = [x for x in (q.get("open") or []) if x is not None]
    return {"symbol": sym.upper(), "price": float(price), "open": opens[0] if opens else None,
            "high": m.get("regularMarketDayHigh"), "low": m.get("regularMarketDayLow"),
            "prev_close": m.get("previousClose") or m.get("chartPreviousClose"), "time": when,
            "currency": m.get("currency"), "source": "yahoo"}


_urlopen = urllib.request.urlopen   # tests swap these two
_sleep = time.sleep


def _get(url, timeout=20):
    """(HTTP status, body). A network failure is an AlertError."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with _urlopen(req, timeout=timeout) as r:
            return 200, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            try:
                e.close()
            except Exception:
                pass
        return e.code, body
    except urllib.error.URLError as e:
        raise AlertError("could not reach %s: %s" % (url.split("/")[2], e.reason))


def fetch(url, timeout=20):
    code, text = _get(url, timeout)
    if code != 200:
        raise AlertError("%s answered HTTP %d" % (url.split("?")[0], code))
    return text


def fetch_yahoo(sym, timeout=20):
    """query2 first. A 429 waits BACKOFF seconds and tries once more; a 429 or a 5xx
    after that moves on to query1. A 404 comes back as Yahoo's own error JSON."""
    last = None
    for host in YAHOO_HOSTS:
        url = yahoo_url(sym, host)
        code, text = _get(url, timeout)
        if code == 429:
            _sleep(BACKOFF)
            code, text = _get(url, timeout)
        if code == 200:
            return text
        if code == 404 and text.strip().startswith("{"):
            return text
        last = (url, code)
        if code != 429 and code < 500:
            break
    raise AlertError("%s answered HTTP %d" % (last[0].split("?")[0], last[1]))


def _offline_text(folder, source, sym):
    ext = "csv" if source == "stooq" else "json"
    base = os.path.join(folder, "%s-%s.%s" % (source, sym, ext))
    if os.path.exists(base):
        with open(base, encoding="utf-8") as fh:
            return fh.read()
    if os.path.exists(base + ".gz"):
        with gzip.open(base + ".gz", "rt", encoding="utf-8") as fh:
            return fh.read()
    raise AlertError("no offline quote file %s" % base)


def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE):
    """{SYM: quote} and [errors]. One request per ticker, with a pause between."""
    quotes, errors = {}, []
    for i, sym in enumerate(symbols):
        sym = sym.upper()
        try:
            if offline:
                text = _offline_text(offline, source, sym)
            else:
                if i and pause:
                    _sleep(pause)
                text = fetch(stooq_url(sym)) if source == "stooq" else fetch_yahoo(sym)
            quotes[sym] = parse_stooq(text, sym) if source == "stooq" else parse_yahoo(text, sym)
        except AlertError as e:
            errors.append(str(e))
    return quotes, errors


def write_prices(path, quotes, now_utc, source):
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        except (ValueError, OSError):
            old = {}
    prices = dict(old.get("prices", {}))
    detail = dict(old.get("detail", {}))
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    for s, q in quotes.items():
        prices[s] = q["price"]
        detail[s] = {"prev_close": q.get("prev_close"), "time": q.get("time"), "source": q.get("source"),
                     "fetched": stamp}
    doc = {"as_of": stamp, "source": source,
           "note": ("Delayed quotes for alerts and sizing checks. Your broker's price is the one that fills. "
                    "detail.fetched is when each price was read."),
           "prices": prices, "detail": detail}
    _write(path, doc)
    return doc


def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _read(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise AlertError("%s is not valid JSON: %s" % (path, e))


# ---------------------------------------------------------------- rules

PRICE_TYPES = {"above", "below", "stop", "target", "pct_move", "opening_bell", "time"}
NO_QUOTE = {"opening_bell", "time"}


def _hhmm(text):
    m = HHMM.match(str(text or "").strip())
    if not m:
        return None
    return datetime.time(int(m.group(1)), int(m.group(2)))


def validate(rule):
    t = rule.get("type")
    if t not in PRICE_TYPES:
        raise AlertError("rule %s: unknown type %r" % (rule.get("id"), t))
    if t not in NO_QUOTE and not rule.get("symbol"):
        raise AlertError("rule %s needs a symbol" % rule.get("id"))
    if t in ("above", "below", "stop", "target") and not isinstance(rule.get("price"), (int, float)):
        raise AlertError("rule %s needs a numeric price" % rule.get("id"))
    if t == "pct_move" and not isinstance(rule.get("pct"), (int, float)):
        raise AlertError("rule %s needs a numeric pct" % rule.get("id"))
    if t == "time" and _hhmm(rule.get("at")) is None:
        raise AlertError("rule %s needs \"at\" as a time like \"15:55\" (market local time: New York, or India for .NS/.BO)"
                         % rule.get("id"))
    if rule.get("market") and rule["market"] not in MARKETS:
        raise AlertError("rule %s: market must be US or IN" % rule.get("id"))
    if rule.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(rule["date"])):
        raise AlertError("rule %s: date must be YYYY-MM-DD" % rule.get("id"))


def rule_market(rule):
    """The market a rule belongs to: its "market" field, else the symbol's (.NS/.BO = IN), else US."""
    return rule.get("market") or market_of(rule.get("symbol"))


def active(rule, today):
    """A rule with a "date" is watched on that local date (New York or India) only."""
    return not rule.get("date") or str(rule["date"]) == today


def _rang_today(stamp, today, market="US"):
    """Did a rule that rang at this UTC stamp ring on this local date?"""
    if not stamp:
        return False
    try:
        utc = datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp[:10] == today
    return to_local(utc, market).date().isoformat() == today


def ring_time(rule, status):
    """The time a time rule rings today, moved 3 hours earlier on an early close if "before_close"."""
    at = _hhmm(rule.get("at"))
    if rule.get("before_close") and status.get("early_close"):
        at = (datetime.datetime.combine(datetime.date(2000, 1, 1), at) - datetime.timedelta(hours=3)).time()
    return at


def evaluate(rules, quotes, status, state, now_utc, statuses=None):
    """Pure function. Returns (rings, new_state). Each ring: {id, symbol, message}.
    `status` is the US market's; `statuses` ({"US": ..., "IN": ...}) adds other markets."""
    state = json.loads(json.dumps(state or {}))
    rung = state.setdefault("rung", {})
    statuses = dict(statuses or {})
    statuses.setdefault("US", status)
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    rings = []
    for r in rules:
        validate(r)
        mk = rule_market(r)
        status = statuses.get(mk) or market_status(now_utc, mk)
        m = MARKETS[mk]
        today = status["date"]
        local = to_local(now_utc, mk)
        rid = r.get("id") or "%s-%s" % (r.get("symbol", "market"), r["type"])
        if not active(r, today):
            continue
        typ = {"stop": "below", "target": "above"}.get(r["type"], r["type"])
        if typ == "opening_bell":
            if status["open"] and not _rang_today(rung.get(rid), today, mk):
                rings.append({"id": rid, "symbol": "", "message": "Opening bell: the %s is open (%s %s)%s."
                              % (m["exchange"], status["now_local"], m["zone"],
                                 (", early close at 1:00 p.m. today, " + status["early_close"])
                                 if status.get("early_close") else "")})
                rung[rid] = stamp
            continue
        if typ == "time":
            at = ring_time(r, status)
            if status.get("opens") and local.time() >= at and not _rang_today(rung.get(rid), today, mk):
                label = r.get("label") or "time alert"
                msg = "%s%s: it is %s %s (set for %s)" % (label[:1].upper(), label[1:], local.strftime("%H:%M"),
                                                           m["zone"], at.strftime("%H:%M"))
                msg += (", the market closes at %s." % status["closes"]) if status["open"] else \
                    ", the market has closed."
                sym = str(r.get("symbol") or "").upper()
                if sym:
                    msg += (" If %s is still open, close it: trader-broker flatten --symbol %s builds the sell "
                            "ticket, then trader-risk and your yes." % (sym, sym))
                rings.append({"id": rid, "symbol": sym, "message": msg})
                rung[rid] = stamp
            continue
        sym = r["symbol"].upper()
        q = quotes.get(sym)
        if not q:
            continue
        p = q["price"]
        if typ in ("above", "below"):
            hit = p >= r["price"] if typ == "above" else p <= r["price"]
            if hit and rid not in rung:
                word = "at or above" if typ == "above" else "at or below"
                label = {"stop": "stop", "target": "target"}.get(r["type"], "alert level")
                cur = m["currency"]
                rings.append({"id": rid, "symbol": sym, "message": "%s %s %s%.2f: %s your %s %s%s%s."
                              % (sym, "is" if status["open"] else "last", cur, p, word, label, cur, _n(r["price"]),
                                 (" (" + r["note"] + ")") if r.get("note") else "")})
                rung[rid] = stamp
            elif not hit and rid in rung and r.get("rearm"):
                del rung[rid]
        elif typ == "pct_move":
            ref = r.get("ref") or q.get("prev_close") or q.get("open")
            if not ref:
                continue
            move = 100.0 * (p / float(ref) - 1)
            want = r.get("direction")
            hit = abs(move) >= r["pct"] and (not want or (want == "up") == (move > 0))
            if hit and not _rang_today(rung.get(rid), today, mk):
                rings.append({"id": rid, "symbol": sym, "message": "%s moved %+.2f%% to %s (from %s)."
                              % (sym, move, money(mk, p), money(mk, ref))})
                rung[rid] = stamp
    state["last_check"] = stamp
    return rings, state


def _n(x):
    x = float(x)
    return str(int(x)) if x == int(x) else "%.2f" % x


def rules_from_plan(plan, cfg_flat_by=None):
    """trader/plan.json -> a stop alert, a target alert and a flat-by-close time alert, for the plan's day."""
    if not isinstance(plan, dict) or not plan.get("symbol"):
        raise AlertError("the plan has no symbol (run trader-exit first)")
    sym = str(plan["symbol"]).upper()
    out = []
    for key, typ, word in (("stop", "stop", "plan stop"), ("target", "target", "plan target")):
        v = plan.get(key)
        if not isinstance(v, (int, float)) or v <= 0:
            raise AlertError("the plan has no %s (run trader-exit)" % key)
        label = plan.get("%s_label" % key)
        out.append({"id": "%s-plan-%s" % (sym.lower(), key), "symbol": sym, "type": typ, "price": float(v),
                    "note": word + (": " + label if label else "")})
    flat = plan.get("flat_by") or cfg_flat_by or "15:55"
    if _hhmm(flat) is None:
        raise AlertError("the plan's flat_by %r is not a time like 15:55" % flat)
    out.append({"id": "%s-flat-by" % sym.lower(), "symbol": sym, "type": "time", "at": flat,
                "label": "flat by close", "before_close": True})
    if plan.get("date"):
        for r in out:
            r["date"] = str(plan["date"])
    return out


# ---------------------------------------------------------------- commands

def holdings(a):
    syms = []
    pf = _read(a.portfolio, {})
    for p in pf.get("positions", []) if isinstance(pf, dict) else []:
        syms.append(str(p.get("ticker") or p.get("symbol") or "").upper())
    plan = _read(a.plan, {})
    if isinstance(plan, dict) and plan.get("symbol"):
        syms.append(str(plan["symbol"]).upper())
    return [s for s in syms if s]


def _dedupe(items):
    out = []
    for s in items:
        if s and s not in out:
            out.append(s)
    return out


def _print_clock(st):
    m = MARKETS[st["market"]]
    print("%s %s (%s): %s %s, %s." % (m["zone"], st["now_local"], st["weekday"], m["exchange"],
                                     "OPEN" if st["open"] else "closed", st["reason"]))
    if st.get("opens"):
        print("Today's session: %s to %s%s." % (st["opens"], st["closes"],
                                                (" (early close: %s)" % st["early_close"]) if st.get("early_close") else ""))
    if not st["open"] and st.get("next_open"):
        print("Next open: %s %s." % (st["next_open"], m["zone"]))
    if not st["calendar_known"]:
        print("Holiday list covers %s only: check %s for this date." % (" and ".join(map(str, m["years"])), m["site"]))


def cmd_clock(a):
    markets = ["US", "IN"] if a.market == "both" else [a.market]
    sts = [market_status(parse_now(a.now, mk), mk) for mk in markets]
    if a.json:
        print(json.dumps(sts[0] if len(sts) == 1 else {st["market"]: st for st in sts}, indent=2))
    else:
        for st in sts:
            _print_clock(st)
    return 0 if any(st["open"] for st in sts) else 1


def cmd_quote(a):
    syms = _dedupe([s.upper() for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("which tickers? alerts.py quote TSLA KO, or --holdings")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, a.source, a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, a.source)
    if a.json:
        print(json.dumps({"quotes": quotes, "errors": errors}, indent=2))
    else:
        for s in syms:
            q = quotes.get(s)
            if q:
                chg = ""
                if q.get("prev_close"):
                    chg = " (%+.2f%% vs prev close %s)" % (100.0 * (q["price"] / q["prev_close"] - 1),
                                                          money(market_of(s), q["prev_close"]))
                print("%-6s %s%s  %s  [%s]" % (s, money(market_of(s), q["price"]), chg, q.get("time", ""), q["source"]))
        for e in errors:
            print("error: " + e)
        if a.write and quotes:
            print("Wrote %d price(s) to %s." % (len(quotes), a.write))
        print("Quotes are free, delayed and unofficial: for alerts only. Your broker's price is the one that fills.")
    return 0 if quotes else 1


def cmd_check(a):
    doc = _read(a.rules, None)
    if not doc or not doc.get("rules"):
        raise AlertError("no rules in %s: add some with alerts.py add --from-plan" % a.rules)
    rules = doc["rules"]
    now = parse_now(a.now, a.market)
    status = market_status(now)
    statuses = {mk: market_status(now, mk) for mk in MARKETS}
    watched = [r for r in rules if active(r, statuses[rule_market(r)]["date"])]
    syms = _dedupe([str(r.get("symbol", "")).upper() for r in watched if r.get("type") not in NO_QUOTE])
    quotes, errors = (get_quotes(syms, a.source, a.offline) if syms else ({}, []))
    state = _read(a.state, {})
    rings, state = evaluate(rules, quotes, status, state, now, statuses)
    if not a.no_write:
        _write(a.state, state)
        if quotes:
            write_prices(a.prices_out, quotes, now, a.source)
    if a.json:
        print(json.dumps({"market": status, "rings": rings, "errors": errors,
                          "quotes": {s: q["price"] for s, q in quotes.items()}}, indent=2))
    else:
        for mk in sorted({rule_market(r) for r in watched} or {"US"}):
            st, m = statuses[mk], MARKETS[mk]
            print("%s %s (%s %s, %s)." % (m["exchange"], "OPEN" if st["open"] else "closed", st["now_local"],
                                         m["zone"], st["reason"]))
        for r in rings:
            print("ALERT " + r["message"])
        if not rings:
            print("Nothing hit. %d rule(s) watched today%s." % (
                len(watched), (", " + ", ".join(money(market_of(s), quotes[s]["price"]).replace(
                    MARKETS[market_of(s)]["currency"], s + " " + MARKETS[market_of(s)]["currency"])
                    for s in syms if s in quotes)) if quotes else ""))
        for e in errors:
            print("error: " + e)
        if rings:
            print("An alert is information, not an order. A bracket's stop-loss and take-profit already sit at "
                  "the broker: check get_open_position and record any fill (ticket.py fill). To close a "
                  "position yourself: ticket.py flatten, then trader-risk and your yes.")
    return 0 if rings else 1


def cmd_add(a):
    doc = _read(a.rules, {"rules": []})
    doc.setdefault("rules", [])
    if a.from_plan:
        plan = _read(a.plan, None)
        if plan is None:
            raise AlertError("no plan at %s (run trader-exit first)" % a.plan)
        cfg = _read(a.config, {}) if a.config else {}
        new = rules_from_plan(plan, (cfg or {}).get("flat_by"))
        ids = {r["id"] for r in new}
        doc["rules"] = [r for r in doc["rules"] if r.get("id") not in ids] + new
        state = _read(a.state, {})
        if state.get("rung"):
            for i in ids:
                state["rung"].pop(i, None)
            _write(a.state, state)
        _write(a.rules, doc)
        for r in new:
            print("Added %s: %s" % (r["id"], json.dumps(r)))
        print("Run alerts.py check every few minutes while the trade is open (a scheduled task or /loop). "
              "Free quotes are delayed; the broker's bracket orders are what actually stop you out.")
        return 0
    if a.opening_bell:
        rule = {"id": a.id or ("opening-bell-in" if a.market == "IN" else "opening-bell"), "type": "opening_bell"}
        if a.market:
            rule["market"] = a.market
    elif a.at:
        if _hhmm(a.at) is None:
            raise AlertError("--at wants a market local time like 15:55 (New York, or India with --market IN)")
        rule = {"id": a.id or ("time-%s" % a.at.replace(":", "")), "type": "time", "at": a.at,
                "label": a.label or "time alert"}
        if a.symbol:
            rule["symbol"] = a.symbol.upper()
        if a.before_close:
            rule["before_close"] = True
        if a.market:
            rule["market"] = a.market
    else:
        if not a.symbol:
            raise AlertError("--symbol is required (or --from-plan, --at, --opening-bell)")
        sym = a.symbol.upper()
        if a.above is not None:
            rule = {"type": "above", "price": a.above}
        elif a.below is not None:
            rule = {"type": "below", "price": a.below}
        elif a.stop is not None:
            rule = {"type": "stop", "price": a.stop}
        elif a.target is not None:
            rule = {"type": "target", "price": a.target}
        elif a.pct is not None:
            rule = {"type": "pct_move", "pct": a.pct}
            if a.direction:
                rule["direction"] = a.direction
        else:
            raise AlertError("give one of --above, --below, --stop, --target or --pct")
        val = rule.get("price", rule.get("pct"))
        rule = dict({"id": a.id or ("%s-%s-%s" % (sym.lower(), rule["type"], _n(val)))}, symbol=sym, **rule)
        if a.rearm:
            rule["rearm"] = True
        if a.note:
            rule["note"] = a.note
    if a.date:
        rule["date"] = a.date
    validate(rule)
    if any(r.get("id") == rule["id"] for r in doc["rules"]):
        raise AlertError("a rule with id %s already exists" % rule["id"])
    doc["rules"].append(rule)
    _write(a.rules, doc)
    print("Added %s: %s" % (rule["id"], json.dumps(rule)))
    return 0


def cmd_list(a):
    doc = _read(a.rules, {"rules": []})
    state = _read(a.state, {})
    if not doc.get("rules"):
        print("No rules yet.")
        return 1
    for r in doc["rules"]:
        rid = r.get("id")
        rung = state.get("rung", {}).get(rid)
        print("%-24s %s%s" % (rid, json.dumps({k: v for k, v in r.items() if k != "id"}),
                              ("  (rang %s)" % rung) if rung else ""))
    return 0


def cmd_reset(a):
    state = _read(a.state, {})
    if a.id not in state.get("rung", {}):
        print("%s has not rung (nothing to reset)." % a.id)
        return 1
    del state["rung"][a.id]
    _write(a.state, state)
    print("Re-armed %s." % a.id)
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):   # the rupee sign must not crash a cp1252 Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Price alerts and the NYSE / NSE clocks (trader-alerts).")
    sub = ap.add_subparsers(dest="cmd")

    def net(p):
        p.add_argument("--source", default="yahoo", choices=["yahoo", "stooq"])
        p.add_argument("--offline", metavar="DIR", help="read <source>-<TICKER>.json|csv files, no network")
        p.add_argument("--now", help="pretend it is this time (no offset = New York time, or India with --market IN)")
        p.add_argument("--market", default="US", choices=["US", "IN"], help="zone for a --now without an offset")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("clock", help="is the NYSE / NSE open?")
    p.add_argument("--market", default="US", choices=["US", "IN", "both"], help="US (NYSE), IN (NSE) or both")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("quote", help="latest delayed quotes")
    net(p)
    p.add_argument("symbols", nargs="*")
    p.add_argument("--holdings", action="store_true", help="add tickers from your portfolio and plan")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--write", nargs="?", const="trader/prices.json", metavar="PATH",
                   help="save to prices.json (default trader/prices.json)")
    p = sub.add_parser("check", help="check every rule, ring what hit")
    net(p)
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--prices-out", default="trader/prices.json")
    p.add_argument("--no-write", action="store_true")
    p = sub.add_parser("add", help="add a rule")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--symbol")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--above", type=float)
    g.add_argument("--below", type=float)
    g.add_argument("--stop", type=float)
    g.add_argument("--target", type=float)
    g.add_argument("--pct", type=float)
    g.add_argument("--opening-bell", action="store_true")
    g.add_argument("--at", metavar="HH:MM", help="a time alert, New York time")
    g.add_argument("--from-plan", action="store_true", help="stop, target and flat-by-close from the plan")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json", help="flat_by when the plan has none")
    p.add_argument("--label", help="what a time alert says, e.g. \"flat by close\"")
    p.add_argument("--before-close", action="store_true",
                   help="a time alert that moves 3 hours earlier on a 1:00 p.m. early close")
    p.add_argument("--date", help="watch this rule on this New York date only (YYYY-MM-DD)")
    p.add_argument("--market", choices=["US", "IN"],
                   help="for --at / --opening-bell: which market's clock (default: the symbol's, else US)")
    p.add_argument("--direction", choices=["up", "down"])
    p.add_argument("--rearm", action="store_true")
    p.add_argument("--note")
    p.add_argument("--id")
    p = sub.add_parser("list", help="list the rules")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p = sub.add_parser("reset", help="re-arm a rule that rang")
    p.add_argument("id")
    p.add_argument("--state", default="trader/state/alerts.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"clock": cmd_clock, "quote": cmd_quote, "check": cmd_check, "add": cmd_add,
                "list": cmd_list, "reset": cmd_reset}[a.cmd](a)
    except AlertError as e:
        print("alerts.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
