"""Daily refresh for Windows Task Scheduler, no browser and no server needed:  pythonw refresh_job.py
Runs one full scan after the close, saves it to cache/scan-latest.pkl (the page loads it instantly) and appends
one line per run to data/refresh.log. Skips weekends and NSE holidays; retries if the new day's prices are not up yet."""
import datetime, os, sys, time

import server
from core.paths import DATA_DIR

LOG = os.path.join(DATA_DIR, "refresh.log")
TRIES, WAIT = 3, 600   # Yahoo can lag the close; try again 10 minutes later, up to 3 times


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def newest_bar():
    d = server.STATE["data"]
    return max((s["asof"] for s in d["stocks"]), default="") if d else ""


def main():
    server.refresh_holidays()
    today = datetime.date.today()
    if not server.is_td(today):
        log("skipped: not a trading day")
        return 0
    for attempt in range(1, TRIES + 1):
        server.STATE.update(running=True, error=None)
        t0 = time.time()
        server.run_scan(True)
        if server.STATE["error"]:
            log(f"try {attempt}: scan failed: {server.STATE['error']}")
        elif newest_bar() >= today.isoformat():
            n = len(server.STATE["data"]["stocks"])
            log(f"ok: {n} stocks, prices as of {newest_bar()}, {time.time() - t0:.0f}s")
            return 0
        else:
            log(f"try {attempt}: newest price is {newest_bar()}, today's is not published yet")
        if attempt < TRIES:
            time.sleep(WAIT)
    log("gave up: the page keeps showing the last good scan")
    return 1


if __name__ == "__main__":
    sys.exit(main())
