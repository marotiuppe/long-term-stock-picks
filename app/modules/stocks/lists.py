"""Manually imported exchange lists (ETFs, BSE scrips). Personal use only.

The owner downloads a list file from the exchange website in a browser, the page parses it locally and sends the
cleaned rows here. This module never contacts any exchange website: it only validates, stores and merges rows."""
import datetime, json, os, re, threading
import urllib.parse

from core.paths import APP_DIR as HERE   # the app folder, not this module's folder
from core.paths import DATA_DIR
PATH = os.path.join(DATA_DIR, "lists.json")
KINDS = ("etf", "bse")
MAX_ROWS = 5000
MAX_BODY = 1_500_000
SYM_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
CODE_RE = re.compile(r"^[0-9]{5,6}$")
CTRL_RE = re.compile("[\x00-\x1f\x7f-\x9f  ]")
_lock = threading.Lock()


def clean_text(v, n=120):
    """Plain string with control characters removed and spaces collapsed; non-text values become ''."""
    if v is None or isinstance(v, (dict, list, bool)):
        return ""
    return " ".join(CTRL_RE.sub(" ", str(v)).split())[:n]


def validate(kind, rows):
    """-> (clean rows, {reason: count}). Raises ValueError for a bad request or when nothing is usable."""
    if kind not in KINDS:
        raise ValueError("kind must be 'etf' or 'bse'")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"too many rows (max {MAX_ROWS})")
    out, skipped, seen = [], {}, set()

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    for r in rows:
        if not isinstance(r, dict):
            skip("bad_row")
            continue
        sym = clean_text(r.get("symbol"), 40).upper()
        code = clean_text(r.get("code"), 20) if kind == "bse" else ""
        if code and not CODE_RE.fullmatch(code):
            skip("bad_code")
            continue
        if not sym and code:
            sym = code
        if not SYM_RE.fullmatch(sym):
            skip("bad_symbol")
            continue
        key = code or sym
        if key in seen:
            skip("duplicate")
            continue
        seen.add(key)
        row = {"symbol": sym, "name": clean_text(r.get("name"))}
        if code:
            row["code"] = code
        for f in ("underlying", "issuer"):
            v = clean_text(r.get(f)) if kind == "etf" else ""
            if v:
                row[f] = v
        out.append(row)
    if not out:
        raise ValueError("no valid rows to save")
    return out, skipped


def _read():
    try:
        d = json.load(open(PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def load():
    """{kind: {rows, importedAt, count}} for every kind that has stored rows."""
    d = _read()
    return {k: d[k] for k in KINDS if isinstance(d.get(k), dict) and isinstance(d[k].get("rows"), list) and d[k]["rows"]}


def _write(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, PATH)


def save(kind, rows):
    with _lock:
        d = _read()
        d[kind] = {"rows": rows, "importedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "count": len(rows)}
        _write(d)
        return d[kind]


def clear(kind):
    with _lock:
        d = _read()
        d.pop(kind, None)
        _write(d)


def union(auto, manual):
    """Per kind, your imported rows first, then automatic rows whose symbol/code you did not import yourself."""
    out = {}
    for kind in KINDS:
        rows = list((manual.get(kind) or {}).get("rows", []))
        seen = {r.get("code") or r["symbol"] for r in rows} | {r["symbol"] for r in rows}
        rows += [r for r in (auto.get(kind) or {}).get("rows", []) if (r.get("code") or r["symbol"]) not in seen
                 and r["symbol"] not in seen]
        if rows:
            out[kind] = {"rows": rows, "count": len(rows)}
    return out


def merge(names, stored):
    """Add stored lists to the NSE universe.
    -> (names, info, stats). info[symbol] holds what the scan needs: etf/underlying/issuer for ETFs, and
    exchange 'BSE' with the Yahoo '.BO' suffix and symbol for BSE rows. BSE rows whose symbol is already known
    (NSE shares or ETFs) are left out, so nothing is listed twice."""
    names, info = dict(names), {}
    stats = {"etf": 0, "bse": 0, "bseDuplicate": 0}
    for r in (stored.get("etf") or {}).get("rows", []):
        s = r["symbol"]
        if s not in names:
            names[s] = r.get("name") or s
        info[s] = {"etf": True, "underlying": r.get("underlying"), "issuer": r.get("issuer")}
        stats["etf"] += 1
    for r in (stored.get("bse") or {}).get("rows", []):
        s = r["symbol"]
        if s in names:
            stats["bseDuplicate"] += 1
            continue
        names[s] = r.get("name") or s
        # Yahoo knows BSE short names (TCS.BO), not scrip codes; the code is only the fallback when no name exists
        info[s] = {"exchange": "BSE", "suffix": ".BO", "yahoo": s if not s.isdigit() else (r.get("code") or s)}
        stats["bse"] += 1
    return names, info, stats


def handle(method, query, raw):
    """-> (status, json-able) for /api/import/list. Same-origin and size checks are done by the server."""
    q = urllib.parse.parse_qs(query)
    try:
        if method == "GET":
            return 200, load()
        if method == "POST":
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                raise ValueError("body is not valid JSON")
            if not isinstance(d, dict):
                raise ValueError("body must be a JSON object")
            kind = d.get("kind")
            rows, skipped = validate(kind, d.get("rows"))
            saved = save(kind, rows)
            return 200, {"kind": kind, "count": saved["count"], "importedAt": saved["importedAt"], "skipped": skipped}
        if method == "DELETE":
            kind = q.get("kind", [""])[0]
            if kind not in KINDS:
                raise ValueError("kind must be 'etf' or 'bse'")
            clear(kind)
            return 200, {"kind": kind, "cleared": True}
        return 405, {"error": "method not allowed"}
    except (ValueError, TypeError) as e:
        return 400, {"error": str(e) or "invalid input"}
