"""Pure portfolio helpers (G2): paste parser and holding review."""
import re

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
NUM_RE = re.compile(r"^(\d+|\d{1,3}(,\d{2,3})+)(\.\d+)?$")


def _num(tok):
    tok = tok.strip().lstrip("₹").strip()
    if tok.lower().startswith("rs."):
        tok = tok[3:]
    elif tok.lower().startswith("rs"):
        tok = tok[2:]
    tok = tok.strip()
    if not NUM_RE.match(tok):
        raise ValueError("not a number: %r" % tok)
    return float(tok.replace(",", ""))


def _split(line):
    line = line.replace("₹", " ")
    line = re.sub(r"\bRs\.?(?=\s|\d)", " ", line, flags=re.I)
    line = line.strip()
    if not re.search(r"\s", line):
        return [t for t in line.split(",")] if "," in line else [line]
    toks = line.split()
    # tolerate "TCS, 10, 3500": a comma after a token is a separator, not part of a number
    return [t[:-1] if t.endswith(",") else t for t in toks]


def parse_paste(text, universe):
    """Return (rows, errors). rows: [{symbol, qty, avg_price}], errors: [(line_no, message)]."""
    uni = set(universe or [])
    merged = {}
    order = []
    errors = []
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        toks = _split(line)
        if len(toks) != 3:
            errors.append((n, "expected 3 fields (SYMBOL qty avg_price), got %d" % len(toks)))
            continue
        sym = toks[0].strip().upper()
        if sym.endswith(".NS"):
            sym = sym[:-3]
        if not SYMBOL_RE.match(sym):
            errors.append((n, "invalid symbol %r" % toks[0]))
            continue
        if sym not in uni:
            errors.append((n, "%s is not in the NSE universe" % sym))
            continue
        try:
            qty = _num(toks[1])
            avg = _num(toks[2])
        except ValueError:
            errors.append((n, "qty and avg price must be positive numbers"))
            continue
        if qty <= 0 or avg <= 0:
            errors.append((n, "qty and avg price must be greater than 0"))
            continue
        if sym in merged:
            q0, a0 = merged[sym]
            merged[sym] = (q0 + qty, (q0 * a0 + qty * avg) / (q0 + qty))
        else:
            merged[sym] = (qty, avg)
            order.append(sym)
    rows = []
    for s in order:
        q, a = merged[s]
        rows.append({"symbol": s, "qty": int(q) if q == int(q) else q, "avg_price": round(a, 4)})
    return rows, errors


def review(holding, stock, hz=None, today=None, review_date=None):
    """Review one holding against the latest scan row. stock may be None (not scanned)."""
    qty = float(holding["qty"])
    avg = float(holding["avg_price"])
    invested = qty * avg
    out = {"symbol": holding.get("symbol"), "qty": holding["qty"], "avg_price": avg,
           "invested": round(invested, 2), "hz": hz, "today": today, "review_date": review_date,
           "price": None, "value": None, "pnl_abs": None, "pnl_pct": None, "stop": None,
           "distance_to_stop_pct": None, "stop_breached": False, "call": None,
           "downtrend_flag": False, "flags": []}
    price = (stock or {}).get("price")
    if not stock or price is None:
        out["flags"].append("no data")
        return out
    price = float(price)
    value = qty * price
    out["price"] = price
    out["value"] = round(value, 2)
    out["pnl_abs"] = round(value - invested, 2)
    out["pnl_pct"] = round((price / avg - 1) * 100, 2) if avg else None
    out["call"] = stock.get("verdict")
    out["downtrend_flag"] = bool(stock.get("downtrend"))
    stop = stock.get("stop")
    if stop is not None and price > 0:
        stop = float(stop)
        out["stop"] = stop
        out["distance_to_stop_pct"] = round((price - stop) / price * 100, 2)
        out["stop_breached"] = price <= stop
    if out["stop_breached"]:
        out["flags"].append("stop breached")
    if out["downtrend_flag"]:
        out["flags"].append("downtrend")
    return out
