"""Live check: save each night's forecasts, settle them against the real closing price, and say how they did.

The scan already measures a forecast as the close on the scan date against the close `days` trading days later. This module keeps the forecasts it
made, finds that later close once it exists, and keeps daily totals (store.fc_*). Pure functions only: the database calls live in core/store.py and
the scan hooks in server.py.
"""
import datetime
import math

TRACKED = ("1d", "5d", "1m")                      # the periods that are saved and checked
LABELS = {"1d": "Tomorrow", "5d": "5 days", "1m": "1 month"}
EXPECTED_INSIDE = 0.8                             # the low and high case are the 10th and 90th percentile: 8 in 10 should fall between them
MIN_FORECASTS = 500                               # below this, or fewer than MIN_DAYS days, there is too little to judge
MIN_DAYS = 5
MATERIAL = 0.03                                   # a gap smaller than 3 points is not worth calling out, however many forecasts show it
FINAL_HOUR = 16                                   # IST: after this the day's bar is the final close, not a partial one
VOID_AFTER_DAYS = 5                               # no price within this many days after the target date: the forecast cannot be checked


def bar_is_final(asof, now):
    """True when the bar dated `asof` (ISO) is a complete day. `now` is an IST datetime. A bar from today is only final after the close."""
    d = datetime.date.fromisoformat(asof)
    return d < now.date() or (d == now.date() and now.hour >= FINAL_HOUR)


def snapshot_rows(stocks, days_of, add_td, horizons=TRACKED):
    """Forecasts to save: one row per stock and period, for the stocks whose price is from the newest bar (an older one is a stale price).
    days_of: {hz: trading days}. add_td(date, k): the date k trading days later."""
    dated = [s["asof"] for s in stocks if s.get("asof")]
    if not dated:
        return []
    newest = max(dated)
    target = {hz: add_td(datetime.date.fromisoformat(newest), days_of[hz]).isoformat() for hz in horizons}
    out = []
    for s in stocks:
        if s.get("asof") != newest or not isinstance(s.get("forecast"), dict):
            continue
        for hz in horizons:
            f = s["forecast"].get(hz)
            if f and s.get("price"):
                out.append((newest, s["symbol"], hz, target[hz], float(s["price"]), float(f["p10"]), float(f["p50"]), float(f["p90"]),
                            float(f["pgain"]), (s.get("verdict") or "").upper()))
    return out


def settle(pending, bars):
    """Results for one symbol's due forecasts, from its price history. pending: the symbol's rows from store.fc_pending. bars: (date, high, low, close,
    adjusted close, volume), oldest first. Returns (asof, symbol, hz, actual): `actual` is the saved price moved by the change in the ADJUSTED close,
    so a split or a dividend between the two dates cannot look like a gain or a loss. actual is None when the forecast can never be checked.
    A forecast whose target date has no bar yet is left out (it stays pending)."""
    if not bars:
        return []
    by_date = {b[0]: b for b in bars}
    last = bars[-1][0]
    out = []
    for p in pending:
        start, target = datetime.date.fromisoformat(p["asof"]), datetime.date.fromisoformat(p["target"])
        base = by_date.get(start)
        end = next((b for b in bars if b[0] >= target and (b[0] - target).days <= VOID_AFTER_DAYS), None)
        if base is None or not base[4]:
            out.append((p["asof"], p["symbol"], p["hz"], None))        # no price on the scan date: nothing to measure from
        elif end is not None:
            out.append((p["asof"], p["symbol"], p["hz"], round(p["price"] * end[4] / base[4], 4)))
        elif (last - target).days > VOID_AFTER_DAYS:
            out.append((p["asof"], p["symbol"], p["hz"], None))        # it stopped trading
    return out


def wilson(k, n, z=1.96):
    """95% interval for a share k out of n (Wilson): (low, high). Wide when n is small, which is the point."""
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def _rate(k, n):
    lo, hi = wilson(k, n)
    return {"rate": k / n, "lo": lo, "hi": hi} if n else None


def _note(n, days, inside, rose, predicted, buy, buy_n):
    if n < MIN_FORECASTS or days < MIN_DAYS:
        return "Too early to tell: %d forecasts over %d day%s so far. Judge it after a few weeks, not a few days." % (n, days, "" if days == 1 else "s")
    parts = []
    # a gap is called out only when it is both clear (the interval excludes the promise) and material (at least MATERIAL points)
    if inside["hi"] < EXPECTED_INSIDE and EXPECTED_INSIDE - inside["rate"] >= MATERIAL:
        parts.append("The real price landed inside the range less often than the 80% promised, so the ranges look too narrow.")
    elif inside["lo"] > EXPECTED_INSIDE and inside["rate"] - EXPECTED_INSIDE >= MATERIAL:
        parts.append("The real price landed inside the range more often than the 80% promised, so the ranges look too wide.")
    else:
        parts.append("The range has held about as often as promised.")
    if predicted is not None and abs(rose["rate"] - predicted) >= MATERIAL and (rose["hi"] < predicted or rose["lo"] > predicted):
        parts.append("Prices rose %s often than the forecasts said." % ("less" if rose["hi"] < predicted else "more"))
    if buy and buy_n >= 100:
        if buy["lo"] > rose["rate"] and buy["rate"] - rose["rate"] >= MATERIAL:
            parts.append("Buy calls rose more often than all stocks so far.")
        elif buy["hi"] < rose["rate"] and rose["rate"] - buy["rate"] >= MATERIAL:
            parts.append("Buy calls rose less often than all stocks so far.")
        else:
            parts.append("Buy calls show no clear difference from all stocks yet.")
    parts.append("All stocks move with the market on a given day, so the number of days matters more than the number of forecasts.")
    return " ".join(parts)


def summarize(stats, pending=None, horizons=TRACKED):
    """The Live check page's data from store.fc_stats() rows (newest day first) and store.fc_counts()."""
    pending = pending or {}
    out = {"horizons": [], "expectedInside": EXPECTED_INSIDE, "pending": sum(pending.values())}
    for hz in horizons:
        mine = [r for r in stats if r["hz"] == hz]
        allr = [r for r in mine if r["grp"] == "all"]
        buyr = [r for r in mine if r["grp"] == "buy"]
        n = sum(r["n"] for r in allr)
        item = {"hz": hz, "label": LABELS.get(hz, hz), "n": n, "days": len(allr), "waiting": pending.get(hz, 0), "daily": []}
        if n:
            inside_k, rose_k = sum(r["inside"] for r in allr), sum(r["rose"] for r in allr)
            predicted = sum(r["sum_pgain"] for r in allr) / n
            bn, brose = sum(r["n"] for r in buyr), sum(r["rose"] for r in buyr)
            item.update(inside=_rate(inside_k, n), rose=_rate(rose_k, n), predictedRise=predicted,
                        avgChange=sum(r["sum_change"] for r in allr) / n, avgMiddle=sum(r["sum_mid"] for r in allr) / n,
                        buy=dict(_rate(brose, bn) or {}, n=bn) if bn else None)
            item["note"] = _note(n, len(allr), item["inside"], item["rose"], predicted, item["buy"] if bn else None, bn)
            buy_by_day = {r["asof"]: r for r in buyr}
            for r in allr[:30]:
                b = buy_by_day.get(r["asof"])
                item["daily"].append({"asof": r["asof"], "n": r["n"], "inside": r["inside"] / r["n"], "rose": r["rose"] / r["n"],
                                      "predictedRise": r["sum_pgain"] / r["n"], "avgChange": r["sum_change"] / r["n"],
                                      "buyN": b["n"] if b else 0, "buyRose": (b["rose"] / b["n"]) if b else None})
        else:
            item["note"] = ("Nothing has been checked yet. Tonight's forecasts are saved after each full scan and checked once their date has passed."
                            if not item["waiting"] else "%d forecasts are saved and waiting for their date to pass." % item["waiting"])
        out["horizons"].append(item)
    return out
