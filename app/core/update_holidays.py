"""NSE trading-holiday list: load, validate and update app/holidays.json. Stdlib only.

python update_holidays.py          fetch NSE's cash-market list now and merge it in
The server also calls maybe_update() at start, so a missed scheduled run still happens."""
import datetime, http.cookiejar, json, os, urllib.request

from core.paths import APP_DIR as HERE   # the app folder, not this module's folder
PATH = os.path.join(HERE, "holidays.json")
HOME = "https://www.nseindia.com/"
URL = HOME + "api/holiday-master?type=trading"
MIN_ENTRIES = 10        # a real CM list has far more; fewer means a bad response
STALE_DAYS = 31         # catch-up on start if the last good fetch is older than this
ALERT_DAYS = 45         # warn the owner if no good fetch for this long
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"lastCheck": None, "years": {}}


def save(doc, path=PATH):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, path)


def holiday_set(doc):
    return {d for y in doc["years"].values() for d in y["dates"]}


def year_status(doc, year):
    """'official', 'provisional' or 'missing' for a calendar year."""
    return doc["years"].get(str(year), {}).get("status", "missing")


def parse_cm(payload):
    """NSE holiday-master JSON -> {year: sorted weekday ISO dates} from the CM (cash market) segment.
    Raises ValueError on anything malformed, so the caller can keep the last good file."""
    try:
        rows = payload["CM"]
        dates = {datetime.datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows}
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"unexpected NSE response: {e!r}")
    if len(dates) < MIN_ENTRIES:
        raise ValueError(f"only {len(dates)} holidays in response")
    out = {}
    for d in sorted(dates):
        if d.weekday() < 5:     # weekends are already skipped by is_td
            out.setdefault(d.year, []).append(d.isoformat())
    return out


def merge(doc, fetched, today):
    """Apply a parsed NSE list to doc in place. Returns warnings. Never removes a year NSE did not send."""
    warnings = []
    for year, dates in fetched.items():
        old = doc["years"].get(str(year))
        if old and len(dates) < len(old["dates"]):
            warnings.append(f"{year}: NSE sent {len(dates)} holidays, stored list has {len(old['dates'])}")
            if old["status"] == "official":
                continue    # keep the verified list
        doc["years"][str(year)] = {"status": "official", "source": URL, "checked": today.isoformat(), "dates": dates}
    doc["lastCheck"] = today.isoformat()
    return warnings


def fetch():
    """One request; if NSE refuses it, collect cookies from the home page and retry once."""
    headers = {"User-Agent": UA, "Referer": HOME + "resources/exchange-communication-holidays", "Accept": "application/json"}
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=20))
    except Exception:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.open(urllib.request.Request(HOME, headers={"User-Agent": UA}), timeout=20).read()
        return json.load(op.open(urllib.request.Request(URL, headers=headers), timeout=20))


def due(doc, today):
    """Monthly on the 1st, daily from 1 Dec to 31 Jan (NSE publishes in December), or overdue (catch-up)."""
    last = doc.get("lastCheck")
    if not last:
        return True
    last = datetime.date.fromisoformat(last)
    if last == today:
        return False
    return today.day == 1 or today.month in (12, 1) or (today - last).days >= STALE_DAYS


def stale_alert(doc, today):
    """Message if no good fetch for ALERT_DAYS, else None."""
    last = doc.get("lastCheck")
    if not last:
        return None
    days = (today - datetime.date.fromisoformat(last)).days
    return f"Holiday list not refreshed for {days} days" if days > ALERT_DAYS else None


def update(path=PATH, today=None, fetcher=fetch):
    """Fetch and merge. Returns (changed, messages). On any failure the stored file is untouched."""
    today = today or datetime.date.today()
    doc = load(path)
    try:
        fetched = parse_cm(fetcher())
    except Exception as e:
        return False, [f"holiday fetch failed, keeping stored list: {e}"]
    msgs = merge(doc, fetched, today)
    save(doc, path)
    return True, msgs + [f"holidays updated for {sorted(fetched)}"]


def maybe_update(path=PATH, today=None, fetcher=fetch):
    today = today or datetime.date.today()
    if not due(load(path), today):
        return False, []
    return update(path, today, fetcher)


if __name__ == "__main__":
    for line in update()[1]:
        print(line)
