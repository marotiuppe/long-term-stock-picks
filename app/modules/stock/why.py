"""'Why this stock was picked': a plain-English reading of what the app's real data shows, for the stock page.

build(sym, stock, chart, nifty, facts, today) -> JSON-ready dict. Pure: no network, no clock, no disk. Every number is computed from
the scan row, the adjusted daily history, the Nifty 50 history or Yahoo's company facts. A figure that cannot be computed is
shown as 'Not available' with the reason; nothing is guessed. This describes the past. It is not a prediction (the scan signal
has no proven predictive edge, see about.html)."""
import datetime
import statistics

from modules.portfolio import rules
from modules.portfolio.rules import _cr, _yoy, _margin

# ---- thresholds (each one is stated to the reader next to the figure it judges) ----
PE_FAIR_BAND = 0.15        # P/E within +/-15% of the stock's own fiscal-year average = fair
NEAR_HIGH = 0.10           # within 10% of the 52-week high
DEEP_DD = 0.30             # 30% or more below the 52-week high
LOW_LIQ = 5e7              # 20-day average traded value below Rs 5 crore a day (the scan's own floor is Rs 1 crore)
HIGH_VOL = 0.40            # annualised daily-return volatility over the last year above 40%
HIGH_DEBT_YEARS = 5.0      # total debt above 5 years of the latest fiscal year's net profit
NEG_NEWS = -2              # net headline tone at or below this (same line the scan uses)
NEAR_SMA20 = 0.03          # price within 3% of the 20-day average (the scan's "better entry" zone)
NEAR_LOW52 = 0.10          # within 10% of the 52-week low
MIN_BARS = 20
YEAR = 252
NA_NOTE = "No licensed data source yet."
DEFAULT_WHY_NOW = "For long-term buying, timing matters less than the quality of the business."
DISCLAIMER = "For research and education. Not investment advice."

ST = {"good": "circle-check", "neutral": "info", "warn": "triangle-alert", "na": "clock"}


def _dt(iso):
    d = rules.parse_date(iso)
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


def _p(v, d=1):
    return ("%+." + str(d) + "f%%") % v


def _rs(v):
    return rules.fmt_inr(v, 2)   # already carries the rupee sign


def _row(label, value, term=None, note=None):
    r = {"label": label, "value": value, "na": False}
    if term:
        r["term"] = term
    if note:
        r["note"] = note
    return r


def _na(label, why, term=None):
    r = {"label": label, "value": "Not available", "na": True, "note": why}
    if term:
        r["term"] = term
    return r


def _card(cid, icon, title, state, label, headline, rows, source, note=None):
    c = {"id": cid, "icon": icon, "title": title, "status": {"key": state, "label": label, "icon": ST[state]},
         "headline": headline, "rows": rows, "source": source}
    if note:
        c["note"] = note
    return c


def _unavailable(cid, icon, title, why, source):
    return _card(cid, icon, title, "na", "Not enough data", "Not available: " + why, [], source)


# ---------- price-derived measures ----------
def _stats(chart):
    """Plain measures from the adjusted history, or None when it is too short."""
    if not chart or len(chart.get("c", [])) < MIN_BARS:
        return None
    c, d, v = chart["c"], chart["d"], chart.get("v") or []
    n = len(c)
    w = c[-YEAR:]
    s = {"n": n, "last": c[-1], "date": d[-1], "first_date": d[0], "w": len(w), "hi": max(w), "lo": min(w)}
    s["below_hi"] = (1 - c[-1] / s["hi"]) * 100
    s["above_lo"] = (c[-1] / s["lo"] - 1) * 100
    peak, mdd = c[0], 0.0
    for x in c:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    s["max_dd"] = mdd * 100
    s["peak"] = max(c)
    s["below_peak"] = (1 - c[-1] / s["peak"]) * 100
    s["sma50"] = sum(c[-50:]) / 50 if n >= 50 else None
    s["sma200"] = sum(c[-200:]) / 200 if n >= 200 else None
    s["sma20"] = sum(c[-20:]) / 20
    if len(v) == n:
        s["tv20"] = sum(c[i] * v[i] for i in range(n - 20, n)) / 20
    else:
        s["tv20"] = None
    r = [c[i] / c[i - 1] - 1 for i in range(max(1, n - YEAR), n)]
    s["vol"] = statistics.pstdev(r) * (YEAR ** 0.5) * 100 if len(r) >= 60 else None
    return s


def _ago(iso, years):
    d = rules.parse_date(iso)
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:
        return d.replace(year=d.year - years, day=28).isoformat()


def _returns(chart, nifty):
    """-> rows for 1/3/5-year returns vs the Nifty 50 over the same dates; only periods the history covers."""
    rows, d0 = [], chart["d"][0]
    last = chart["d"][-1]
    cl = {"d": chart["d"], "c": chart["c"]}
    nl = {"d": nifty["d"], "c": nifty["c"]} if nifty and nifty.get("d") else None
    for y in (1, 3, 5):
        start = _ago(last, y)
        label = "%d-year return" % y
        if d0 > start:
            rows.append(_na(label, "History only starts %s, so this period is not covered." % _dt(d0)))
            continue
        a = rules.price_on(cl, start)
        if a is None:
            rows.append(_na(label, "No price near %s." % _dt(start)))
            continue
        ret = (chart["c"][-1] / a - 1) * 100
        n_ret = None
        if nl:
            na, nb = rules.price_on(nl, start), rules.price_on(nl, last)
            if na and nb:
                n_ret = (nb / na - 1) * 100
        if n_ret is None:
            rows.append(_row(label, _p(ret), note="%s to %s. Nifty 50 comparison not available (index history missing for these dates)." % (_dt(start), _dt(last))))
        else:
            gap = ret - n_ret
            rows.append(_row(label, _p(ret), note="Nifty 50 over the same dates: %s (%s %s points than the index). %s to %s." % (_p(n_ret), "%.1f" % abs(gap), "more" if gap >= 0 else "fewer", _dt(start), _dt(last))))
    return rows


# ---------- cards ----------
def _price_card(s, chart, nifty):
    src = "Yahoo Finance daily prices (adjusted for splits and dividends), as of %s" % _dt(s["date"])
    rows = [_row("52-week high", "%s (%.1f%% below it)" % (_rs(s["hi"]), s["below_hi"]), "hi52",
                 None if s["w"] >= YEAR else "Only %d trading days of history, so this is the high since listing in our data." % s["w"]),
            _row("52-week low", "%s (%.1f%% above it)" % (_rs(s["lo"]), s["above_lo"]), "hi52"),
            _row("Drawdown", "%.1f%% below the highest close in the history (%s); the worst peak-to-trough fall was %.1f%%" % (s["below_peak"], _rs(s["peak"]), s["max_dd"]), "drawdown",
                 "History covers %s to %s." % (_dt(s["first_date"]), _dt(s["date"])))]
    rows += _returns(chart, nifty)
    if s["below_hi"] >= DEEP_DD * 100:
        st, lab = "warn", "Watch out"
    elif s["below_hi"] <= NEAR_HIGH * 100:
        st, lab = "good", "Near its high"
    else:
        st, lab = "neutral", "Neutral"
    head = "%.1f%% below its 52-week high and %.1f%% above its 52-week low." % (s["below_hi"], s["above_lo"])
    return _card("price", "chart-pie", "Price context", st, lab, head, rows, src,
                 "Rule: within %d%% of the high is shown as near its high; %d%% or more below is flagged." % (NEAR_HIGH * 100, DEEP_DD * 100))


def _momentum_card(s):
    src = "Yahoo Finance daily prices, as of %s" % _dt(s["date"])
    if s["sma200"] is None:
        return _card("momentum", "trending-up", "Momentum and trend", "na", "Not enough data",
                     "Needs 200 trading days of prices; only %d available." % s["n"],
                     [_na("200-day average", "Only %d trading days of history." % s["n"], "sma200")], src,
                     "Context, not a prediction.")
    gap = (s["last"] / s["sma200"] - 1) * 100
    rows = [_row("Price vs 200-day average", "%s: %s vs %s" % (_p(gap), _rs(s["last"]), _rs(s["sma200"])), "sma200")]
    above50 = None
    if s["sma50"] is not None:
        above50 = s["sma50"] > s["sma200"]
        rows.append(_row("50-day vs 200-day average", "%s vs %s, so the 50-day is %s the 200-day" % (_rs(s["sma50"]), _rs(s["sma200"]), "above" if above50 else "below"), "sma50"))
    if gap > 0 and above50:
        st, lab = "good", "Positive trend"
    elif gap < 0:
        st, lab = "warn", "Weak trend"
    else:
        st, lab = "neutral", "Mixed"
    return _card("momentum", "trending-up", "Momentum and trend", st, lab,
                 "Price is %.1f%% %s its 200-day average." % (abs(gap), "above" if gap >= 0 else "below"), rows, src, "Context, not a prediction.")


def _fund_ok(facts):
    return bool(facts) and facts.get("status") in ("ok", "stale")


def _src_facts(facts):
    return "Yahoo Finance company results, fetched %s" % _dt(facts["fetched"]) if facts and facts.get("fetched") else "Yahoo Finance company results"


def _growth(v, py):
    if v is None or py is None:
        return None
    return (v / py - 1) * 100 if py > 0 and v >= 0 else None


def _quality_card(facts, pe_why_unused=None):
    src = _src_facts(facts)
    q = facts.get("quarters", [])
    a = facts.get("annual", [])
    rows, flags = [], {"neg": 0}
    if q:
        last = len(q) - 1
        L = q[last]
        for key, name in (("revenue", "Revenue"), ("net_income", "Net profit")):
            v, py = L.get(key), _yoy(q, last, key)
            if v is None:
                rows.append(_na(name + " growth", "Yahoo has no %s for the latest quarter." % name.lower()))
            elif py is None:
                rows.append(_row(name + " (latest quarter)", _cr(v), note="Quarter ended %s. No quarter a year earlier in Yahoo's data to compare." % L["end"]))
            else:
                g = _growth(v, py)
                val = "%s vs %s a year earlier (%s)" % (_cr(v), _cr(py), _p(g) if g is not None else "% change not meaningful with a loss or zero")
                rows.append(_row(name + " (latest quarter)", val, note="Quarter ended %s." % L["end"]))
                if (g is not None and g < 0) or (g is None and v < py):
                    flags["neg"] += 1
        m = _margin(L)
        pq, pr = _yoy(q, last, "operating_income"), _yoy(q, last, "revenue")
        pm = pq / pr * 100 if pq is not None and pr else None
        if m is None:
            rows.append(_na("Operating margin", "Banks and finance companies report no operating income in Yahoo's data.", "margin"))
        else:
            ms = [_margin(x) for x in q[-3:]]
            trail = ", ".join("%.1f%%" % x for x in ms if x is not None)
            rows.append(_row("Operating margin", "%.1f%% in the latest quarter%s" % (m, " vs %.1f%% a year earlier" % pm if pm is not None else ""), "margin", "Last quarters: %s." % trail))
    else:
        rows.append(_na("Quarterly results", "Yahoo has no quarterly results for this symbol."))
    ya = [x for x in a if x.get("revenue") is not None]
    if len(ya) >= 2:
        f0, f1 = ya[0], ya[-1]
        g = _growth(f1["revenue"], f0["revenue"])
        rows.append(_row("Annual revenue", "%s to %s over %d fiscal years (%s to %s)%s" % (_cr(f0["revenue"]), _cr(f1["revenue"]), len(ya) - 1, f0["end"][:4], f1["end"][:4], ", " + _p(g) if g is not None else "")))
    else:
        rows.append(_na("Annual revenue", "Yahoo has %d fiscal year(s) of revenue; at least 2 are needed." % len(ya)))
    yn = [x for x in a if x.get("net_income") is not None]
    if len(yn) >= 2:
        f0, f1 = yn[0], yn[-1]
        g = _growth(f1["net_income"], f0["net_income"])
        rows.append(_row("Annual net profit", "%s to %s over %d fiscal years (%s to %s)%s" % (_cr(f0["net_income"]), _cr(f1["net_income"]), len(yn) - 1, f0["end"][:4], f1["end"][:4], ", " + _p(g) if g is not None else "")))
    else:
        rows.append(_na("Annual net profit", "Yahoo has %d fiscal year(s) of profit; at least 2 are needed." % len(yn)))
    ye = [x for x in a if x.get("eps") is not None]
    eps_dir = None
    if len(ye) >= 2:
        e0, e1 = ye[0]["eps"], ye[-1]["eps"]
        eps_dir = "rose" if e1 > e0 else "fell" if e1 < e0 else "was flat"
        rows.append(_row("Earnings per share", "%s from %.2f to %.2f over %d fiscal years (%s to %s)" % (eps_dir, e0, e1, len(ye) - 1, ye[0]["end"][:4], ye[-1]["end"][:4]), "eps"))
    else:
        rows.append(_na("Earnings per share", "Yahoo has %d fiscal year(s) of EPS; at least 2 are needed." % len(ye), "eps"))
    debt = facts.get("debt", [])
    fin = bool(q) and not any(x.get("operating_income") is not None for x in q)
    if fin:
        rows.append(_na("Debt", "Not meaningful for banks and finance companies (debt is their raw material)."))
    elif len(debt) >= 2:
        d0, d1 = debt[-2], debt[-1]
        rows.append(_row("Total debt", "%s (as of %s), %s the %s before (%s)" % (_cr(d1["value"]), d1["end"], "up from" if d1["value"] > d0["value"] else "down from" if d1["value"] < d0["value"] else "unchanged from", _cr(d0["value"]), d0["end"]),
                         note="Yahoo's total debt includes lease obligations."))
    elif len(debt) == 1:
        rows.append(_row("Total debt", "%s (as of %s); one reading only, so no trend" % (_cr(debt[0]["value"]), debt[0]["end"])))
    else:
        rows.append(_na("Debt", "Yahoo has no total-debt reading for this symbol."))
    rows.append(_na("Return on equity and capital employed (ROE, ROCE)", NA_NOTE))
    conds, why = rules.worsening(facts)
    ok, _t = rules.intact(facts) if not why else (None, why)
    if conds or ok is False:
        st, lab = "warn", "Watch out"
        head = (conds[0][1] if conds else _t)
    elif ok and not flags["neg"]:
        st, lab = "good", "Healthy"
        head = _t
    elif ok is None:
        st, lab = "na", "Not enough data"
        head = "Cannot be judged: %s" % _t
    else:
        st, lab = "neutral", "Neutral"
        head = "No two-quarter decline, but the latest quarter is below the same quarter a year earlier on at least one measure."
    return _card("quality", "landmark", "Business quality", st, lab, head, rows, src,
                 "Rule: flagged only when revenue, profit or margin fell two quarters in a row and is below a year earlier, or debt rose in each of the last two periods.")


def _valuation(price, facts):
    """-> (card, stats or None)"""
    src = "Yahoo Finance company results, fetched %s; price as of the last close" % (_dt(facts["fetched"]) if facts.get("fetched") else "n/a")
    pe, why = rules.pe_stats(price, facts)
    na_rows = [_na("P/E vs sector or peers", "Sector averages: " + NA_NOTE), _na("Price to book (P/B)", NA_NOTE)]
    if not pe:
        return _card("valuation", "percent", "Valuation", "na", "Not enough data", "P/E vs its own history is not available: %s" % why,
                     [_na("P/E vs its own history", why, "pe-history")] + na_rows, src), None
    rel = pe["now"] / pe["avg"] - 1
    if rel > PE_FAIR_BAND:
        st, lab, word = "warn", "Expensive vs own history", "above"
    elif rel < -PE_FAIR_BAND:
        st, lab, word = "good", "Cheap vs own history", "below"
    else:
        st, lab, word = "neutral", "Fair vs own history", "near"
    pe["rel"] = rel * 100
    rows = [_row("P/E now", "%.1f (price %s / trailing 4-quarter EPS %.2f)" % (pe["now"], _rs(price), pe["ttm_eps"]), "pe"),
            _row("Own fiscal-year average P/E", "%.1f across %d fiscal years (%s)" % (pe["avg"], pe["n"], ", ".join("%s: %.1f" % (h["end"][:4], h["pe"]) for h in pe["history"])), "pe-history"),
            _row("Versus its own average", "%s (%s)" % (_p(rel * 100), word))] + na_rows
    return _card("valuation", "percent", "Valuation", st, lab,
                 "P/E %.1f is %s this stock's own %d-year average of %.1f." % (pe["now"], word, pe["n"], pe["avg"]), rows, src,
                 "Rule: within +/-%d%% of its own average = fair, above = expensive, below = cheap. This compares the stock only with itself, not with other companies." % (PE_FAIR_BAND * 100)), pe


def _stability_card(facts, today):
    src = _src_facts(facts)
    rows = []
    divs = facts.get("dividends", [])
    cd = facts.get("closes", {}).get("d", [])
    first = cd[0] if cd else None
    y0 = today.year
    cnt, full, parts = {}, 0, []
    for x in divs:
        cnt[int(x["date"][:4])] = cnt.get(int(x["date"][:4]), 0) + 1
    paid_full = 0
    for y in range(y0 - 4, y0 + 1):
        partial = y == y0 or (first is not None and first > "%d-01-10" % y)
        n = cnt.get(y, 0)
        parts.append("%d: %d%s" % (y, n, " (so far)" if y == y0 else " (partial window)" if partial else ""))
        if not partial:
            full += 1
            paid_full += 1 if n else 0
    if cd:
        rows.append(_row("Dividend payments per year", "; ".join(parts), "dividend", "Yahoo's dividend history covers about 5 years. Years marked partial are not counted below."))
        if divs:
            L = divs[-1]
            rows.append(_row("Latest dividend", "%s per share on %s" % (_rs(L["amount"]), _dt(L["date"])), "dividend"))
        rows.append(_row("Years with a dividend", "%d of %d full years" % (paid_full, full), "dividend", "Paying no dividend is not a fault: many companies reinvest instead."))
    else:
        rows.append(_na("Dividend history", "Yahoo returned no dividend history.", "dividend"))
    ye = [x for x in facts.get("annual", []) if x.get("eps") is not None]
    pos = sum(1 for x in ye if x["eps"] > 0)
    if ye:
        rows.append(_row("Years of positive EPS", "%d of %d fiscal years Yahoo has" % (pos, len(ye)), "eps"))
    else:
        rows.append(_na("Years of positive EPS", "Yahoo has no annual EPS.", "eps"))
    rows.append(_na("Promoter holding", NA_NOTE))
    if ye and pos < len(ye):
        st, lab, head = "warn", "Watch out", "EPS was positive in only %d of %d fiscal years." % (pos, len(ye))
    elif ye and len(ye) >= 3 and full and paid_full >= full - 1 and paid_full:
        st, lab, head = "good", "Steady", "Positive EPS in all %d fiscal years and a dividend in %d of %d full years." % (len(ye), paid_full, full)
    elif ye:
        st, lab, head = "neutral", "Neutral", "Positive EPS in all %d fiscal years Yahoo has; %d of %d full years paid a dividend." % (len(ye), paid_full, full)
    else:
        st, lab, head = "na", "Not enough data", "Not enough earnings history to judge."
    return _card("stability", "layers", "Stability", st, lab, head, rows, src)


# ---------- risks ----------
def _risks(stock, s, facts, pe, etf):
    out = []

    def add(rid, icon, title, text):
        out.append({"id": rid, "icon": icon, "title": title, "text": text})
    if not etf and _fund_ok(facts):
        conds, _w = rules.worsening(facts)
        names = {"fund_revenue": "Revenue falling", "fund_profit": "Profit falling", "fund_margin": "Margin shrinking", "fund_debt": "Debt rising"}
        for cid, text in conds:
            add(cid, "triangle-alert", names.get(cid, "Results worsening"), text)
        debt, ann = facts.get("debt", []), [x for x in facts.get("annual", []) if x.get("net_income") is not None]
        fin = bool(facts.get("quarters")) and not any(x.get("operating_income") is not None for x in facts["quarters"])
        if debt and ann and not fin:
            d, ni = debt[-1]["value"], ann[-1]["net_income"]
            if d > 0 and ni > 0 and d / ni > HIGH_DEBT_YEARS:
                add("debt_high", "triangle-alert", "High debt", "Total debt %s is %.1f times the net profit of the fiscal year ended %s (%s). Flag line: more than %g times. Yahoo's debt includes leases." % (_cr(d), d / ni, ann[-1]["end"], _cr(ni), HIGH_DEBT_YEARS))
            elif d > 0 and ni <= 0:
                add("debt_high", "triangle-alert", "Debt with no annual profit", "Total debt is %s while net profit for the fiscal year ended %s was %s." % (_cr(d), ann[-1]["end"], _cr(ni)))
    if pe and pe["rel"] > PE_FAIR_BAND * 100:
        add("pe_high", "percent", "Expensive against its own history", "P/E %.1f is %.0f%% above its own %d-year average of %.1f (flag line: more than %d%% above)." % (pe["now"], pe["rel"], pe["n"], pe["avg"], PE_FAIR_BAND * 100))
    if s:
        if s["tv20"] is not None and s["tv20"] < LOW_LIQ:
            add("liquidity", "wallet", "Thin trading", "Average traded value over the last 20 days is about Rs %.2f crore a day (price x volume). Flag line: under Rs %.0f crore. Thin trading can make buying or selling at a fair price harder." % (s["tv20"] / 1e7, LOW_LIQ / 1e7))
        if s["vol"] is not None and s["vol"] > HIGH_VOL * 100:
            add("volatility", "triangle-alert", "Large price swings", "Daily moves over the last year annualise to %.0f%% (flag line: above %d%%)." % (s["vol"], HIGH_VOL * 100))
        if s["below_hi"] >= DEEP_DD * 100:
            add("drawdown", "arrow-down-right", "Deep fall from the high", "Price is %.1f%% below its 52-week high (flag line: %d%% or more)." % (s["below_hi"], DEEP_DD * 100))
        if s["sma200"] is not None and s["last"] < s["sma200"]:
            add("below200", "arrow-down-right", "Below the 200-day average", "Price %s is %.1f%% below its 200-day average of %s." % (_rs(s["last"]), (1 - s["last"] / s["sma200"]) * 100, _rs(s["sma200"])))
    net = stock.get("newsNet") if stock else None
    if net is not None and net <= NEG_NEWS:
        add("news", "info", "Negative recent headlines", "Net headline tone is %d across the latest headlines (flag line: %d or lower). Read the news before buying." % (net, NEG_NEWS))
    return out


def _why_now(stock, s, pe):
    t = []
    if pe and pe["now"] < pe["avg"]:
        t.append("P/E %.1f is below this stock's own fiscal-year average of %.1f." % (pe["now"], pe["avg"]))
    if stock and stock.get("verdict") == "WAIT" and stock.get("sma20") and stock.get("price"):
        g = stock["price"] / stock["sma20"] - 1
        if abs(g) <= NEAR_SMA20:
            t.append("The scan calls this WAIT, and the price is within %d%% of its 20-day average (%s), the zone the scan treats as a better entry." % (NEAR_SMA20 * 100, _rs(stock["sma20"])))
    # near a 52-week low is only a "why now" when the scan is not already calling a downtrend (a falling stock sits near its lows)
    if s and s["above_lo"] <= NEAR_LOW52 * 100 and (stock or {}).get("verdict") != "DOWNTREND":
        t.append("Price is only %.1f%% above its 52-week low." % s["above_lo"])
    return {"fired": bool(t), "text": " ".join(t) if t else DEFAULT_WHY_NOW}


def _summary(sym, s, facts, pe, etf, q_card, stock):
    parts = []
    if s:
        sent = "%s closed at %s on %s, %.1f%% below its 52-week high" % (sym, _rs(s["last"]), _dt(s["date"]), s["below_hi"])
        if s["sma200"] is not None:
            sent += " and %.1f%% %s its 200-day average" % (abs(s["last"] / s["sma200"] - 1) * 100, "above" if s["last"] >= s["sma200"] else "below")
        parts.append(sent + ".")
    else:
        parts.append("%s: the price history is too short to describe." % sym)
    if etf:
        parts.append("This is an ETF or fund, so it has no company results and only the price-based facts are shown.")
    elif _fund_ok(facts):
        q = facts.get("quarters", [])
        bits = []
        if q:
            for key, name in (("revenue", "revenue"), ("net_income", "net profit")):
                g = _growth(q[-1].get(key), _yoy(q, len(q) - 1, key))
                if g is not None:
                    bits.append("%s %s" % (name, _p(g)))
        if bits:
            parts.append("In its latest reported quarter, %s against the same quarter a year earlier%s." % (" and ".join(bits), "; its P/E of %.1f is %s its own fiscal-year average of %.1f" % (pe["now"], "above" if pe["now"] > pe["avg"] else "below", pe["avg"]) if pe else ""))
        elif pe:
            parts.append("Its P/E of %.1f compares with its own fiscal-year average of %.1f." % (pe["now"], pe["avg"]))
        else:
            parts.append("Yahoo's company results are too thin to say more.")
    else:
        parts.append("Company results are not available for this symbol, so only price facts are shown.")
    parts.append("This describes the past and is not a prediction.")
    return " ".join(parts)


def build(sym, stock, chart, nifty, facts, today):
    """today: datetime.date. All inputs may be None except sym."""
    stock = stock or {}
    etf = bool(stock.get("etf"))
    s = _stats(chart)
    cards, na_cards = [], []
    pe = None
    asof = s["date"] if s else stock.get("asof")
    price = s["last"] if s else stock.get("price")
    if etf or not _fund_ok(facts):
        why = (facts or {}).get("reason") or "No company results available."
        if etf:
            why = "ETFs and funds have no company results, so there is no revenue, profit, debt or P/E to read."
        for cid, icon, title in (("quality", "landmark", "Business quality"), ("valuation", "percent", "Valuation"), ("stability", "layers", "Stability")):
            na_cards.append(_unavailable(cid, icon, title, why, "Yahoo Finance company results"))
        if etf:
            na_cards = []
    else:
        cards.append(_quality_card(facts))
        v, pe = _valuation(price, facts) if price else (None, None)
        if v:
            cards.append(v)
        cards.append(_stability_card(facts, today))
    if s:
        cards.append(_price_card(s, chart, nifty))
        cards.append(_momentum_card(s))
    else:
        cards.append(_unavailable("price", "chart-pie", "Price context", "price history is missing or too short (need at least %d trading days)." % MIN_BARS, "Yahoo Finance daily prices"))
    cards += na_cards
    order = ["quality", "valuation", "price", "stability", "momentum"]
    cards.sort(key=lambda c: order.index(c["id"]))
    risks = _risks(stock, s, facts, pe, etf)
    na_risks = [{"label": "Pledged promoter shares", "value": "Not available", "note": NA_NOTE}]
    limits = []
    if not s:
        limits.append("Price-based flags (liquidity, volatility, drawdown, trend) could not be checked: price history missing or short.")
    if etf or not _fund_ok(facts):
        limits.append("Company-based flags (debt, falling revenue or profit, expensive P/E) could not be checked: no company results.")
    sources = []
    if s:
        sources.append({"label": "Yahoo Finance daily prices (adjusted for splits and dividends)", "asof": s["date"]})
    if nifty and nifty.get("d"):
        sources.append({"label": "Yahoo Finance Nifty 50 daily prices", "asof": nifty["d"][-1]})
    if _fund_ok(facts) and facts.get("fetched"):
        sources.append({"label": "Yahoo Finance company results", "asof": facts["fetched"], "stale": facts.get("status") == "stale"})
    return {"symbol": sym, "etf": etf, "asof": asof, "summary": _summary(sym, s, facts, pe, etf, None, stock), "cards": cards,
            "risks": risks, "risksNa": na_risks, "noRisks": "No flags from the data we have, which is limited." if not risks else None,
            "limits": limits, "whyNow": _why_now(stock, s, pe), "sources": sources, "disclaimer": DISCLAIMER, "verdict": stock.get("verdict"),
            "factsStatus": (facts or {}).get("status"), "factsReason": (facts or {}).get("reason")}
