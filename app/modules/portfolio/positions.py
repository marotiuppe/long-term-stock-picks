"""Pure lot maths for holdings tracking. No I/O.

A holding is a list of transactions ("lots"): buys and sales of one symbol. Cost basis is the AVERAGE COST method:
- a buy adds qty x price plus its charges to the cost of the position;
- a sale realises qty x (sale price - average cost at that moment) minus its charges, and removes qty x average cost
  from the position (the average cost of what is left does not change).
Transactions are replayed in date order (ties by id) so a back-dated edit gives the same answer as entering it in order.
"""
import datetime
import re

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
MAX_QTY = 10_000_000          # shares in one transaction
MAX_PRICE = 10_000_000.0      # rupees per share
MIN_DATE = datetime.date(1990, 1, 1)
MAX_FEE_SHARE = 0.25          # charges above 25% of the amount are almost certainly a typo


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _num(v, name):
    if isinstance(v, bool):
        raise ValueError("%s must be a number" % name)
    try:
        f = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("%s must be a number" % name)
    return f


def validate_lot(d, today=None, require_date=True):
    """Clean one transaction or raise ValueError with a message fit to show next to the field."""
    today = today or datetime.date.today()
    side = str(d.get("side", "buy")).strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    sym = str(d.get("symbol", "")).strip().upper()
    if sym.endswith(".NS"):
        sym = sym[:-3]
    if not SYMBOL_RE.match(sym):
        raise ValueError("Enter a valid symbol, for example TCS")
    qty = _num(d.get("qty"), "Quantity")
    if qty <= 0:
        raise ValueError("Quantity must be more than 0")
    if qty != int(qty):
        raise ValueError("Quantity must be a whole number of shares")
    if qty > MAX_QTY:
        raise ValueError("Quantity looks too large (limit %s shares)" % format(MAX_QTY, ","))
    price = _num(d.get("price"), "Price")
    if price <= 0:
        raise ValueError("Price must be more than 0")
    if price > MAX_PRICE:
        raise ValueError("Price looks too large (limit Rs %s)" % format(int(MAX_PRICE), ","))
    raw_date = d.get("date")
    if raw_date in (None, ""):
        if require_date:
            raise ValueError("Pick the date of the transaction")
        date = None
    else:
        pd = parse_date(raw_date)
        if pd is None or len(str(raw_date)) < 10:
            raise ValueError("Date must look like 2026-10-24")
        if pd > today:
            raise ValueError("Date cannot be in the future")
        if pd < MIN_DATE:
            raise ValueError("Date is too far in the past")
        date = pd.isoformat()
    fees = d.get("fees")
    fees = 0.0 if fees in (None, "") else _num(fees, "Charges")
    if fees < 0:
        raise ValueError("Charges cannot be negative")
    if fees > qty * price * MAX_FEE_SHARE:
        raise ValueError("Charges look too high for this amount. Check the figure")
    note = str(d.get("note") or "").strip()
    if len(note) > 200:
        raise ValueError("Note is too long (200 characters at most)")
    return {"symbol": sym, "side": side, "qty": int(qty), "price": round(price, 4), "date": date,
            "fees": round(fees, 2), "note": note}


def qty_from_amount(amount, price):
    """Whole shares an amount buys, and what is left over. (0, amount) when it buys none."""
    amount, price = float(amount), float(price)
    if amount <= 0 or price <= 0:
        return 0, max(amount, 0.0)
    q = int(amount // price)
    return q, round(amount - q * price, 2)


def _order(lots):
    return sorted(lots, key=lambda l: (l.get("date") or "0000-00-00", int(l.get("id") or 0)))


def _n(x):
    """A whole number of shares as an int, otherwise a float."""
    return int(round(x)) if abs(x - round(x)) < 1e-9 else x


def replay(lots):
    """Replay transactions in order. Raises ValueError when a sale is larger than what was held at that time.
    Returns the position and every transaction annotated with its amount (and realised P&L for sales)."""
    qty, cost, realized = 0, 0.0, 0.0
    bought_qty = bought_amt = sold_qty = sold_amt = 0.0
    first_buy = None
    out = []
    for l in _order(lots):
        q, p, fee = float(l["qty"]), float(l["price"]), float(l.get("fees") or 0)
        row = dict(l)
        if l["side"] == "buy":
            amt = q * p
            cost += amt + fee
            qty += q
            bought_qty += q
            bought_amt += amt
            row.update(amount=round(amt, 2), realized=None)
            if l.get("date") and (first_buy is None or l["date"] < first_buy):
                first_buy = l["date"]
        else:
            if q > qty:
                raise ValueError("Cannot sell %s shares of %s on %s: only %s held then"
                                 % (_n(q), l.get("symbol", ""), l.get("date") or "an unknown date", _n(qty)))
            avg = cost / qty
            gain = q * (p - avg) - fee
            cost -= q * avg
            qty -= q
            if qty < 1e-9:
                qty, cost = 0, 0.0
            realized += gain
            sold_qty += q
            sold_amt += q * p
            row.update(amount=round(q * p, 2), realized=round(gain, 2), basis=round(avg, 4))
        out.append(row)
    avg_cost = (cost / qty) if qty else None
    return {"qty": _n(qty), "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
            "invested": round(cost, 2), "realized": round(realized, 2),
            "bought_qty": _n(bought_qty), "bought_amount": round(bought_amt, 2),
            "sold_qty": _n(sold_qty), "sold_amount": round(sold_amt, 2),
            "first_buy": first_buy, "lots": out}


def valuation(pos, price, prev_close=None):
    """Add current value, unrealised P&L and day change to a position. price may be None (no data)."""
    out = dict(pos, price=None, value=None, unrealized=None, unrealized_pct=None, day_abs=None, day_pct=None)
    if price is None or not pos["qty"]:
        return out
    price = float(price)
    out["price"] = price
    out["value"] = round(pos["qty"] * price, 2)
    if pos["invested"] > 0:
        out["unrealized"] = round(out["value"] - pos["invested"], 2)
        out["unrealized_pct"] = round((out["value"] / pos["invested"] - 1) * 100, 2)
    if prev_close:
        out["day_abs"] = round(pos["qty"] * (price - float(prev_close)), 2)
        out["day_pct"] = round((price / float(prev_close) - 1) * 100, 2)
    return out


def summarize(rows):
    """Totals, weights, best and worst performers across valued positions (dicts from valuation()).
    Positions without a price are left out of value and weights and listed in 'unpriced'."""
    held = [r for r in rows if r["qty"]]
    priced = [r for r in held if r.get("value") is not None]
    value = sum(r["value"] for r in priced)
    invested_priced = sum(r["invested"] for r in priced)
    invested_all = sum(r["invested"] for r in held)
    for r in held:
        r["weight"] = round(r["value"] / value * 100, 2) if r.get("value") is not None and value > 0 else None
    pnl = value - invested_priced
    day_rows = [r for r in priced if r.get("day_abs") is not None]
    day_abs = sum(r["day_abs"] for r in day_rows)
    day_base = sum(r["value"] - r["day_abs"] for r in day_rows)
    ranked = sorted((r for r in priced if r.get("unrealized_pct") is not None), key=lambda r: r["unrealized_pct"])
    return {"invested": round(invested_all, 2), "invested_priced": round(invested_priced, 2), "value": round(value, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl / invested_priced * 100, 2) if invested_priced > 0 else None,
            "day_abs": round(day_abs, 2) if day_rows else None,
            "day_pct": round(day_abs / day_base * 100, 2) if day_rows and day_base > 0 else None,
            "realized": round(sum(r.get("realized") or 0 for r in rows), 2),
            "count": len(held), "unpriced": [r["symbol"] for r in held if r.get("value") is None],
            "best": [r["symbol"] for r in reversed(ranked[-3:])] if len(ranked) > 1 else [],
            "worst": [r["symbol"] for r in ranked[:3]] if len(ranked) > 1 else []}


def fmt_inr(v, d=0):
    """Rupees with Indian digit grouping: 1234567.5 -> '12,34,568' (lakh and crore commas)."""
    neg = v < 0
    s = "{:.{d}f}".format(abs(v), d=d)
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + "₹" + whole + ("." + frac if frac else "")
