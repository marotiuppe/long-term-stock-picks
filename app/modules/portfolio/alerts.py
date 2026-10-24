"""End-of-day alert generation. Pure functions, no I/O.

Each alert: {key, kind, symbol, message, date}. Keys are deterministic so a
UNIQUE(user_id, key) constraint gives one alert per event.
"""
import datetime

NEAR_PCT = 1.5


def _num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _rs(v):
    return "₹{:,.2f}".format(v)


def _label(sym, st):
    name = st.get("name") if isinstance(st, dict) else None
    return "%s (%s)" % (name, sym) if name else sym


def _iso(d):
    return d.isoformat()


def _parse(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def next_calls(stocks):
    out = {}
    for sym, st in (stocks or {}).items():
        v = st.get("verdict") if isinstance(st, dict) else None
        if v:
            out[sym] = v
    return out


def generate_alerts(holdings, watchlist, stocks, last_calls, today, review_date=None):
    stocks = stocks or {}
    last_calls = last_calls or {}
    alerts = []
    held = []
    for h in holdings or []:
        sym = h.get("symbol") if isinstance(h, dict) else None
        if sym and sym not in held:
            held.append(sym)
    watch = [s for s in (watchlist or []) if s]
    d = _iso(today)

    def add(key, kind, sym, msg):
        alerts.append({"key": key, "kind": kind, "symbol": sym,
                       "message": msg, "date": d})

    for sym in held:
        st = stocks.get(sym)
        if not isinstance(st, dict):
            continue
        price, stop = _num(st.get("price")), _num(st.get("stop"))
        if price is not None and stop is not None and price <= stop:
            add("stop:%s:%s" % (sym, stop), "stop_breached", sym,
                "%s closed at %s, at or below its stop level of %s. "
                "Review whether your original reason for holding still applies."
                % (_label(sym, st), _rs(price), _rs(stop)))

    seen = set()
    for sym in held + watch:
        if sym in seen:
            continue
        seen.add(sym)
        st = stocks.get(sym)
        if not isinstance(st, dict) or st.get("verdict") != "WAIT":
            continue
        price, sma = _num(st.get("price")), _num(st.get("sma20"))
        stop = _num(st.get("stop"))
        if price is None or sma is None or sma <= 0:
            continue
        if stop is not None and price <= stop:
            continue
        if sma <= price <= sma * (1 + NEAR_PCT / 100.0):
            wk = tuple(today.isocalendar())[:2]
            add("near:%s:%s" % (sym, wk), "near_sma20", sym,
                "%s is at %s, within %s%% above its 20-day average of %s. "
                "It is still rated WAIT."
                % (_label(sym, st), _rs(price), NEAR_PCT, _rs(sma)))

    for sym in held + watch:
        st = stocks.get(sym)
        if not isinstance(st, dict):
            continue
        new, old = st.get("verdict"), last_calls.get(sym)
        if new and old and new != old:
            add("call:%s:%s>%s:%s" % (sym, old, new, d), "call_changed", sym,
                "%s call changed from %s to %s." % (_label(sym, st), old, new))

    rd = _parse(review_date) if review_date else None
    if rd and rd <= today:
        for sym in held:
            add("review:%s:%s" % (sym, review_date), "review_due", sym,
                "Your review date of %s for %s has arrived. "
                "Check whether you still want to hold it."
                % (_iso(rd), sym))
    return alerts


def price_alert_hit(kind, value, st):
    """True if the latest close meets the user's level. End-of-day data only; a missing price never fires."""
    if not isinstance(st, dict):
        return False
    price, v = _num(st.get("price")), _num(value)
    if price is None or v is None:
        return False
    if kind == "below":
        return price <= v
    if kind == "above":
        return price >= v
    if kind == "off_high":
        hi = _num(st.get("hi52"))
        return hi is not None and hi > 0 and price <= hi * (1 - v / 100.0)
    return False


def _level(v):
    return "{:,.2f}".format(v).rstrip("0").rstrip(".")


def price_alert_message(kind, value, sym, st):
    price = _num(st.get("price"))
    tail = " This is a reminder you asked for, not a recommendation."
    if kind in ("below", "above"):
        return "Price alert: %s closed at %s, at or %s your \u20b9%s level.%s" % (
            sym, _rs(price), "below" if kind == "below" else "above", _level(value), tail)
    return "Price alert: %s closed at %s, at least %s%% below its 52-week high of %s.%s" % (
        sym, _rs(price), "%g" % value, _rs(_num(st.get("hi52"))), tail)


def evaluate_price_alerts(rows, stocks, today):
    """rows: price alerts. -> [(alert_id, alert dict)] for active ones not yet reached whose condition holds on the latest
    scan. Key pa:<id>:<scan date> gives one inbox entry per scan date; a reached alert is not evaluated again until re-armed."""
    out = []
    for r in rows or []:
        if not r.get("active") or r.get("last_fired"):
            continue
        st = (stocks or {}).get(r["symbol"])
        if not price_alert_hit(r["kind"], r["value"], st):
            continue
        asof = (_parse(st.get("asof")) or today).isoformat()
        out.append((r["id"], {"key": "pa:%s:%s" % (r["id"], asof), "kind": "price_alert", "symbol": r["symbol"],
                              "message": price_alert_message(r["kind"], r["value"], r["symbol"], st), "date": asof}))
    return out
