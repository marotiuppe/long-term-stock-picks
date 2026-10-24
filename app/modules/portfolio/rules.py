"""Rule-based review prompts for the stocks a user holds. Pure functions, no I/O.

These are prompts to look again, built only from the user's own transactions and real data (the scan's price, the app's 200-day
average, Yahoo's company results). They are not predictions and never say buy or sell. Each alert carries the exact rule that
fired, with the thresholds in force, and the numbers behind it. When the data a rule needs is missing the rule does not fire and
the gap is reported in 'not_evaluated', never guessed.
"""
import datetime

from modules.portfolio.positions import fmt_inr, parse_date

DEFAULTS = {
    "add_drop": {"on": True, "pct": 15},
    "add_pe": {"on": True, "margin": 10},
    "add_weight": {"on": True, "tol": 2},
    "trim_conc": {"on": True, "pct": 20},
    "trim_gain_val": {"on": True, "gain": 50, "premium": 30},
    "trim_fund": {"on": True},
    "trim_loss": {"on": True, "below_avg": 20},
    "review_level": {"on": True},
    "info_results": {"on": True},
    "info_dividend": {"on": True, "days": 30},
    "info_corp": {"on": True, "days": 30},
}
LIMITS = {("add_drop", "pct"): (1, 90), ("add_pe", "margin"): (1, 90), ("add_weight", "tol"): (0.5, 50),
          ("trim_conc", "pct"): (5, 95), ("trim_gain_val", "gain"): (5, 1000), ("trim_gain_val", "premium"): (5, 500),
          ("trim_loss", "below_avg"): (1, 90), ("info_dividend", "days"): (1, 365), ("info_corp", "days"): (1, 365)}
LABELS = {"add": "Consider adding", "review": "Consider reviewing", "info": "Info"}
META = {  # rule: (tone, base importance, title, one-line description shown in Settings)
    "review_level": ("review", 90, "Your review level reached", "A price you set for a stock has been reached."),
    "trim_fund": ("review", 80, "Fundamentals weakening", "Revenue, profit or operating margin fell two quarters in a row (and is below a year ago), or debt rose two periods in a row."),
    "trim_conc": ("review", 70, "Large share of the portfolio", "One stock is more than this share of your portfolio's current value."),
    "trim_gain_val": ("review", 65, "Big gain and a high P/E", "The gain is large and the P/E is far above that stock's own history."),
    "trim_loss": ("review", 60, "Below the 200-day average and under your cost", "A loss review: the price is under its 200-day average and well under your average buy price."),
    "add_drop": ("add", 50, "Below your cost, results intact", "Price is well below your average buy price while the latest results show no decline."),
    "add_weight": ("add", 45, "Below your target weight", "A stock's share of the portfolio is under the target you set for it."),
    "add_pe": ("add", 40, "P/E below its own average", "The P/E is below that stock's own average over recent fiscal years."),
    "info_results": ("info", 20, "New quarterly results", "A newer quarter of results appeared in the data."),
    "info_dividend": ("info", 15, "Dividend", "A stock went ex-dividend recently."),
    "info_corp": ("info", 25, "Split or bonus", "A stock split or bonus happened recently."),
}


def normalize_settings(raw):
    """Merge user settings over the defaults. Unknown keys are ignored; bad numbers raise ValueError."""
    out = {r: dict(v) for r, v in DEFAULTS.items()}
    for rule, vals in (raw or {}).items():
        if rule not in out or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k == "on":
                out[rule]["on"] = bool(v)
            elif k in out[rule]:
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    raise ValueError("%s: %s must be a number" % (META[rule][2], k))
                lo, hi = LIMITS[(rule, k)]
                if not lo <= f <= hi:
                    raise ValueError("%s: %s must be between %g and %g" % (META[rule][2], k, lo, hi))
                out[rule][k] = int(f) if f == int(f) else f
    return out


# ---------- signals from the data ----------
def _d(s):
    return parse_date(s)


def _cr(v):
    c = v / 1e7
    return fmt_inr(c, 0 if abs(c) >= 1000 else 1) + " cr"


def _pct(v):
    return "%+.1f%%" % v


def ttm_eps(quarters):
    """Sum of the last four quarters' diluted EPS, only when they are four consecutive-ish quarters. None otherwise."""
    q = [x for x in quarters if x.get("eps") is not None][-4:]
    if len(q) < 4:
        return None
    span = (_d(q[-1]["end"]) - _d(q[0]["end"])).days
    return round(sum(x["eps"] for x in q), 4) if 200 <= span <= 300 else None


def price_on(closes, iso, slack=10):
    """Last close on or before a date, if it is within 'slack' days of it."""
    end = _d(iso)
    best = None
    for d, c in zip(closes.get("d", []), closes.get("c", [])):
        dd = _d(d)
        if dd <= end:
            best = (dd, c)
        else:
            break
    return best[1] if best and (end - best[0]).days <= slack else None


def pe_stats(price, facts):
    """-> (stats, why). stats: now, ttm_eps, avg, n, history[{end, eps, price, pe}]. why explains a missing figure."""
    if not facts or facts.get("status") not in ("ok", "stale"):
        return None, (facts or {}).get("reason") or "No company results available."
    eps = ttm_eps(facts.get("quarters", []))
    if eps is None:
        return None, "Needs four recent quarters of EPS; Yahoo has fewer."
    if eps <= 0:
        return None, "Trailing 4-quarter EPS is not positive, so a P/E is not meaningful."
    hist = []
    for a in facts.get("annual", []):
        if a.get("eps") and a["eps"] > 0:
            p = price_on(facts.get("closes", {}), a["end"])
            if p:
                hist.append({"end": a["end"], "eps": a["eps"], "price": p, "pe": round(p / a["eps"], 2)})
    if len(hist) < 3:
        return None, "Needs at least 3 fiscal years of EPS and price history; found %d." % len(hist)
    avg = sum(h["pe"] for h in hist) / len(hist)
    return {"now": round(price / eps, 2), "ttm_eps": eps, "avg": round(avg, 2), "n": len(hist), "history": hist}, None


def _yoy(quarters, i, key):
    """The same metric one year before quarters[i], or None."""
    end = _d(quarters[i]["end"])
    for x in quarters[:i]:
        if abs((end - _d(x["end"])).days - 365) <= 20 and x.get(key) is not None:
            return x[key]
    return None


def _margin(x):
    return x["operating_income"] / x["revenue"] * 100 if x.get("operating_income") is not None and x.get("revenue") else None


def worsening(facts):
    """-> (conditions, why). conditions: [(id, text)] for each measure that got worse; why when it cannot be judged.
    Quarterly measures need 3 quarters in a row falling (two declines) AND the latest quarter below the same quarter a year
    earlier, so a normal seasonal dip is not flagged. Debt needs three reported periods, each higher than the last."""
    if not facts or facts.get("status") not in ("ok", "stale"):
        return [], (facts or {}).get("reason") or "No company results available."
    q = facts.get("quarters", [])
    if len(q) < 3:
        return [], "Only %d quarter(s) of results available; at least 3 are needed." % len(q)
    a, b, c = q[-3:]
    out = []
    last = len(q) - 1
    for key, name, wording in (("revenue", "Revenue", "revenue"), ("net_income", "Net profit", "profit")):
        vals = [a.get(key), b.get(key), c.get(key)]
        if None in vals:
            continue
        py = _yoy(q, last, key)
        if vals[2] < vals[1] < vals[0] and py is not None and vals[2] < py:
            out.append(("fund_" + wording, "%s fell two quarters in a row: %s, %s, %s (quarters ending %s, %s, %s), and is %s against the same quarter a year earlier (%s)."
                        % (name, _cr(vals[0]), _cr(vals[1]), _cr(vals[2]), a["end"], b["end"], c["end"], _pct((vals[2] / py - 1) * 100) if py > 0 else "lower", _cr(py))))
    m = [_margin(x) for x in (a, b, c)]
    if None not in m:
        py = _yoy(q, last, "operating_income")
        pr = _yoy(q, last, "revenue")
        pm = py / pr * 100 if py is not None and pr else None
        if m[2] < m[1] < m[0] and pm is not None and m[2] < pm:
            out.append(("fund_margin", "Operating margin shrank two quarters in a row: %.1f%%, %.1f%%, %.1f%%, and is below the same quarter a year earlier (%.1f%%)." % (m[0], m[1], m[2], pm)))
    debt = facts.get("debt", [])
    financial = not any(x.get("operating_income") is not None for x in q)
    if not financial and len(debt) >= 3:
        d3 = [x["value"] for x in debt[-3:]]
        if d3[0] < d3[1] < d3[2]:
            out.append(("fund_debt", "Total debt rose in each of the last two reported periods: %s, %s, %s (as of %s, %s, %s; Yahoo's total debt includes lease obligations)."
                        % (_cr(d3[0]), _cr(d3[1]), _cr(d3[2]), debt[-3]["end"], debt[-2]["end"], debt[-1]["end"])))
    return out, None


def intact(facts):
    """-> (True/False/None, text). None means it cannot be judged (data missing)."""
    conds, why = worsening(facts)
    if why:
        return None, why
    q = [x for x in facts["quarters"] if x.get("net_income") is not None and x.get("revenue") is not None]
    if len(q) < 3:
        return None, "Fewer than 3 quarters with both revenue and profit."
    if conds:
        return False, conds[0][1]
    last = q[-1]
    if last["net_income"] <= 0:
        return False, "The latest quarter's net profit was not positive."
    return True, "Net profit %s for the quarter ended %s, and revenue, profit and operating margin have not fallen two quarters in a row." % (_cr(last["net_income"]), last["end"])


# ---------- the rules ----------
def _alert(rule, h, reason, rule_text, fp, as_of, bump=0):
    tone, base, title, _ = META[rule]
    return {"key": "%s|%s" % (h["symbol"], rule), "rule": rule, "symbol": h["symbol"], "name": h.get("name") or h["symbol"],
            "tone": tone, "label": LABELS[tone], "title": title, "importance": base + max(0, min(9, int(bump))),
            "reason": reason, "rule_text": rule_text, "fingerprint": str(fp), "as_of": as_of}


def evaluate(holdings, settings, today, new_results=None):
    """holdings: dicts with symbol, name, etf, qty, avg_cost, price, asof, weight, target_weight, review_price, close, s200, facts.
    Returns {'alerts': [...sorted most important first], 'not_evaluated': [{symbol, rule, why}], 'checked': [keys]}.
    'checked' lists the keys whose condition could be judged (so a stored dismissal can be cleared once it no longer holds)."""
    S = normalize_settings(settings)
    new_results = new_results or {}
    alerts, gaps, checked = [], [], set()
    count = len([h for h in holdings if h.get("qty")])

    def gap(h, rule, why):
        gaps.append({"symbol": h["symbol"], "rule": rule, "title": META[rule][2], "why": why})

    for h in holdings:
        if not h.get("qty"):
            continue
        h = dict(h, name=h.get("name") or h["symbol"])
        sym, price, avg, facts = h["symbol"], h.get("price"), h.get("avg_cost"), h.get("facts")
        as_of = h.get("asof") or today.isoformat()
        key = lambda r: "%s|%s" % (sym, r)
        loss = (avg - price) / avg * 100 if price is not None and avg else None
        gain = -loss if loss is not None else None
        pe, pe_why = pe_stats(price, facts) if price is not None else (None, "No current price.")

        r = S["add_drop"]
        if r["on"] and loss is not None:
            if loss >= r["pct"]:
                ok, txt = intact(facts)
                if ok:
                    checked.add(key("add_drop"))
                    alerts.append(_alert("add_drop", h, "%s is at %s, %.1f%% below your average buy price of %s. %s" % (h["name"], fmt_inr(price, 2), loss, fmt_inr(avg, 2), txt),
                                         "Price at least %g%% below your average buy price, while the latest results show no decline (no two-quarter fall in revenue, profit or margin, and the latest quarter is profitable)." % r["pct"],
                                         int(loss // 5 * 5), as_of, loss / 10))
                elif ok is None:
                    gap(h, "add_drop", "The price is %.1f%% below your cost, but whether results are intact cannot be judged: %s" % (loss, txt))
                else:
                    checked.add(key("add_drop"))
            else:
                checked.add(key("add_drop"))

        r = S["add_pe"]
        if r["on"] and price is not None:
            if pe:
                checked.add(key("add_pe"))
                if pe["now"] < pe["avg"] * (1 - r["margin"] / 100):
                    disc = (1 - pe["now"] / pe["avg"]) * 100
                    hist = ", ".join("%s %.1f" % (x["end"][:4], x["pe"]) for x in pe["history"])
                    alerts.append(_alert("add_pe", h, "P/E is %.1f now (%s / trailing 4-quarter EPS %s), %.0f%% below its own average of %.1f over %d fiscal year-ends (%s)."
                                         % (pe["now"], fmt_inr(price, 2), fmt_inr(pe["ttm_eps"], 2), disc, pe["avg"], pe["n"], hist),
                                         "P/E at least %g%% below the stock's own average P/E at its last fiscal year-ends (price at year-end / that year's diluted EPS; needs 3 or more years)." % r["margin"],
                                         int(disc // 10 * 10), as_of, disc / 10))

        r = S["add_weight"]
        if r["on"] and h.get("target_weight") is not None:
            if h.get("weight") is None:
                gap(h, "add_weight", "Needs a current price to work out the weight.")
            else:
                checked.add(key("add_weight"))
                if h["weight"] < h["target_weight"] - r["tol"]:
                    gapv = h["target_weight"] - h["weight"]
                    alerts.append(_alert("add_weight", h, "%s is %.1f%% of your portfolio's current value, against the %.1f%% target you set." % (h["name"], h["weight"], h["target_weight"]),
                                         "Share of the portfolio more than %g points below the target weight you set for this stock." % r["tol"],
                                         int(gapv // 2 * 2), as_of, gapv / 5))

        r = S["trim_conc"]
        if r["on"] and h.get("weight") is not None and count >= 2:
            checked.add(key("trim_conc"))
            if h["weight"] >= r["pct"]:
                alerts.append(_alert("trim_conc", h, "%s is %.1f%% of your portfolio's current value (your limit: %g%%)." % (h["name"], h["weight"], r["pct"]),
                                     "One stock above %g%% of the portfolio's current value (checked only when you hold two or more stocks)." % r["pct"],
                                     int(h["weight"] // 5 * 5), as_of, (h["weight"] - r["pct"]) / 5))

        r = S["trim_gain_val"]
        if r["on"] and gain is not None and gain >= r["gain"]:
            if pe:
                checked.add(key("trim_gain_val"))
                if pe["now"] >= pe["avg"] * (1 + r["premium"] / 100):
                    prem = (pe["now"] / pe["avg"] - 1) * 100
                    alerts.append(_alert("trim_gain_val", h, "%s is up %.1f%% on your average buy price of %s, and its P/E is %.1f, %.0f%% above its own average of %.1f over %d fiscal year-ends."
                                         % (h["name"], gain, fmt_inr(avg, 2), pe["now"], prem, pe["avg"], pe["n"]),
                                         "Gain of at least %g%% on your average buy price and a P/E at least %g%% above the stock's own average at its last fiscal year-ends." % (r["gain"], r["premium"]),
                                         "%d:%d" % (int(gain // 10 * 10), int(prem // 10 * 10)), as_of, prem / 20))
            else:
                gap(h, "trim_gain_val", "The gain is %.1f%%, but the P/E history cannot be built: %s" % (gain, pe_why))
        elif r["on"] and gain is not None:
            checked.add(key("trim_gain_val"))

        r = S["trim_fund"]
        if r["on"] and facts is not None:
            conds, why = worsening(facts)
            if why:
                if facts.get("status") in ("ok", "stale"):
                    gap(h, "trim_fund", why)
            else:
                checked.add(key("trim_fund"))
                if conds:
                    q = facts["quarters"]
                    alerts.append(_alert("trim_fund", h, " ".join(c[1] for c in conds),
                                         "Revenue, net profit or operating margin falling two quarters in a row and below the same quarter a year earlier, or total debt rising two reported periods in a row (company results from Yahoo Finance, last fetched %s)." % facts.get("fetched"),
                                         q[-1]["end"] + ":" + ",".join(sorted(c[0] for c in conds)), q[-1]["end"], len(conds) * 2))
                    alerts[-1]["as_of"] = q[-1]["end"]

        r = S["trim_loss"]
        if r["on"] and loss is not None:
            c0, s200 = h.get("close"), h.get("s200")
            if c0 is None or s200 is None:
                if loss >= r["below_avg"]:
                    gap(h, "trim_loss", "The price is %.1f%% below your cost, but the 200-day average is not available (needs about 200 days of price history)." % loss)
            else:
                checked.add(key("trim_loss"))
                if c0 < s200 and loss >= r["below_avg"]:
                    alerts.append(_alert("trim_loss", h, "%s closed at %s, below its 200-day average of %s, and is %.1f%% below your average buy price of %s. A prompt to re-check why you hold it, not a sell signal."
                                         % (h["name"], fmt_inr(c0, 2), fmt_inr(s200, 2), loss, fmt_inr(avg, 2)),
                                         "Price below its 200-day average and at least %g%% below your average buy price." % r["below_avg"],
                                         int(loss // 5 * 5), as_of, loss / 10))

        r = S["review_level"]
        if r["on"] and h.get("review_price") is not None and price is not None:
            checked.add(key("review_level"))
            if price <= h["review_price"]:
                alerts.append(_alert("review_level", h, "%s is at %s, at or below the review level you set (%s)." % (h["name"], fmt_inr(price, 2), fmt_inr(h["review_price"], 2)),
                                     "Price at or below the review level you set for this stock.", h["review_price"], as_of, 5))

        r = S["info_results"]
        nr = new_results.get(sym)
        if r["on"] and nr and facts:
            x = next((q for q in facts.get("quarters", []) if q["end"] == nr["end"]), None)
            if x:
                bits = []
                if x.get("revenue") is not None:
                    bits.append("revenue %s" % _cr(x["revenue"]))
                if x.get("net_income") is not None:
                    bits.append("net profit %s" % _cr(x["net_income"]))
                if x.get("eps") is not None:
                    bits.append("diluted EPS %s" % fmt_inr(x["eps"], 2))
                alerts.append(_alert("info_results", h, "Results for the quarter ended %s appeared in the data (first seen %s): %s." % (x["end"], nr["detected"], ", ".join(bits) or "figures not listed"),
                                     "A newer quarter of company results appeared in Yahoo Finance's data since you last opened the app; shown for 30 days.", x["end"], x["end"]))

        r = S["info_dividend"]
        if r["on"] and facts:
            for dv in reversed(facts.get("dividends", [])):
                dd = _d(dv["date"])
                if dd and 0 <= (today - dd).days <= r["days"]:
                    alerts.append(_alert("info_dividend", h, "%s went ex-dividend on %s: %s per share. Yahoo lists the ex-dividend date; the declaration date is not available." % (h["name"], dv["date"], fmt_inr(dv["amount"], 2)),
                                         "A dividend whose ex-date was in the last %g days (from Yahoo Finance's dividend history)." % r["days"], dv["date"], dv["date"]))
                    break

        r = S["info_corp"]
        if r["on"] and facts:
            for sp in reversed(facts.get("splits", [])):
                dd = _d(sp["date"])
                if dd and 0 <= (today - dd).days <= r["days"]:
                    alerts.append(_alert("info_corp", h, "%s had a stock split or bonus on %s (ratio %s). Share counts and prices in old records may need adjusting." % (h["name"], sp["date"], sp["text"]),
                                         "A split or bonus whose date was in the last %g days (from Yahoo Finance)." % r["days"], sp["date"], sp["date"]))
                    break
    alerts.sort(key=lambda a: (-a["importance"], a["symbol"]))
    return {"alerts": alerts, "not_evaluated": gaps, "checked": sorted(checked)}


def apply_state(alerts, states, today):
    """Hide alerts the user dismissed or snoozed, until the condition changes (its fingerprint) or the snooze ends.
    -> (visible, hidden_count). states: {key: {state, until, fingerprint}}"""
    t = today.isoformat() if hasattr(today, "isoformat") else str(today)
    vis, hidden = [], 0
    for a in alerts:
        s = states.get(a["key"])
        if s and s.get("fingerprint") == a["fingerprint"] and (s["state"] == "dismissed" or (s["state"] == "snoozed" and (s.get("until") or "") > t)):
            hidden += 1
            continue
        vis.append(dict(a, snoozed_before=bool(s and s["state"] == "snoozed")))
    return vis, hidden
