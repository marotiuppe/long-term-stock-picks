# long-term-stock-picks

A buy-and-hold stock and ETF picker for the Indian market (NSE), with a portfolio tracker, alerts and a plain-language "why" for every pick. Python standard-library server, no framework, no day trading.

A local page that lists liquid NSE shares and ETFs to buy and hold for 10 days, 1 month, 3 months or 6 months. It shows a buy date, a sell or review date, a stop-loss, a forecast range and recent news. Daily prices only. No intraday signals and no order placement.

**It has no proven edge.** In our own back-test the buy-grade picks rose about 57% of the time at 1 month, against about 56% for any stock. Treat every number as a historical base rate, never as a promise of profit. This is an educational tool, not investment advice. Planned work is in [ROADMAP.md](ROADMAP.md).

## Run it

```
git clone https://github.com/marotiuppe/long-term-stock-picks.git
cd long-term-stock-picks
```

Needs Python 3 (tested on 3.14). Install the packages once: `pip install -r requirements.txt`.
The stock scan itself uses only what ships with Python; the packages are for **Sync from Groww** (`cryptography` and Groww's `growwapi`, which also installs `pandas` and others, so it is a large download).

- Windows: double-click `app/Start Stock Picks.bat`.
- Any system: `cd app` then `python server.py`, and open <http://localhost:8765>.

The first scan of the day downloads 5 years of prices for the whole market and takes a few minutes. Later loads use the cache in `app/cache/`.

**Refresh data** is instant when the prices are already from the latest market close: it says "Already up to date", because Yahoo has nothing newer until the next close. It starts a scan only when a close has passed since the last one (or the saved scan came from older code), shows the scan's progress while it runs, and the Portfolio page updates itself when the scan finishes. The "Re-download anyway" button next to that message forces a full re-download (`/api/scan?force=full`).

## How it works

1. **Universe.** NSE's own `EQUITY_L.csv` (equity series) plus a few ETFs (TATSILV, SILVERBEES, GOLDBEES, NIFTYBEES).
2. **Quality filter.** Skipped if the price is under ₹20, average daily traded value is under ₹1 crore, there are fewer than 300 days of history, or the data has a daily jump above 35%.
3. **Score (0 to 100).** Trend and momentum: 6-month and 3-month return, price against the 200-day average, 50-day against 200-day, distance from the 52-week high, and strength against the Nifty 50.
4. **Forecast.** For a given score, the page looks at what stocks with a similar score did over the next 10, 20, 60 and 126 trading days across the whole universe, scaled to the stock's own volatility. It shows the 10th, 50th and 90th percentile and the share of cases that gained.
5. **Stop-loss.** 2.5 times the 14-day average true range, limited to 7% to 15% below the price.
6. **News.** Google News headlines for the top 40 names. News can only make a call more cautious.

## What the calls mean

| Call | Meaning |
|---|---|
| Buy | Strong score, beats the all-stock base rate, price not stretched, no negative news |
| Wait | Strong score, but the price is stretched or headlines are negative. Wait for a dip near the 20-day average |
| Watch | Mixed picture, not enough edge |
| Downtrend | Price trend is down. The tool does not back a purchase, but history shows no reliable rebound or fall signal either |

## Data sources and limits

- **Prices:** Yahoo Finance, free, delayed and unofficial. It can change or block without notice. Redistribution to other people may not be allowed.
- **Survivorship bias:** today's listed names are used for the history test, so delisted stocks are missing and results look better than reality.
- **Holidays:** `app/holidays.json`. 2026 is official. 2027 and 2028 are **provisional** until NSE publishes them, and the page marks affected dates "(provisional)". BSE-only shares are not included.
- **If Yahoo is unreachable:** the page keeps showing the last scan and adds a "data may be old" notice.

## Sync holdings from Groww

On the Portfolio page, **Sync from Groww** loads your holdings with your own Groww API key and secret (Groww Trading API, subscription needed).
One-time setup: `pip install -r requirements.txt`. Create the key on the Groww Cloud API Keys page and approve it there each day (key-and-secret method).
The app only reads holdings and never places an order. Keys are stored encrypted in `app/data/users.db`; the master key is `app/data/groww.key`
(or set `STOCKPICKS_SECRET_KEY`). Back up both together, and never share either file. A stock you entered with several transactions is not overwritten.

## Configuration

All settings are environment variables. None is required to run locally.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8765` | Port to listen on (Render sets it) |
| `HOST` | `127.0.0.1` | Address to bind. Use `0.0.0.0` on a server. A local run opens your browser; any other host does not |
| `DATABASE_URL` | unset | `postgresql://...` URL. Unset means SQLite at `data/users.db` |
| `STOCKPICKS_DATA_DIR` | the `app` folder | Folder that holds `data/` (database, Groww key, lists) and `cache/` (prices). Point it at a persistent disk when hosting |
| `STOCKPICKS_SECURE_COOKIES` | unset | `1` sends cookies over HTTPS only |

## Deploy on Render

`render.yaml` in the repo root describes the service.

1. The code is at `marotiuppe/long-term-stock-picks` on GitHub (keep it private).
2. In Render choose **New, Blueprint**, pick the repo and apply it. It creates one web service (Python, `pip install -r requirements.txt`, start with `cd app && python server.py`) and a 2 GB disk mounted at `/var/data`.
3. When asked, enter `DATABASE_URL` (your PostgreSQL URL; on Render use the database's Internal URL).
4. Wait a few minutes after the first start: the first scan downloads 5 years of prices.

Notes: the scan needs about 1 GB of memory, so use the Standard plan (2 GB); the 512 MB Starter plan runs out of memory. The disk needs a paid plan and still holds the price cache and `groww.key` (the key that protects saved Groww credentials, so losing it means users must re-enter their Groww key). Run a single instance, because scan state and the sign-in rate limiter live in memory. Behind Render's proxy every visitor shares one address for rate limiting.

## Accounts and sign-in

Without signing in you are a guest: your data lives under a cookie in this browser. On **Account** you can:

- **Create an account** (username and password). The data already in this browser becomes the account, so nothing is lost.
- **Sign in with Groww** using your own Groww API key and secret (needs a paid Groww Trading API subscription). Groww has no outside-app login button, so the app asks Groww who owns the key and uses that as the identity. Only a keyed hash of the Groww id is stored.
- **Recover a forgotten password** by signing in with Groww (if you linked it): for 15 minutes after that sign-in you can set a new password without the old one. There is no email reset.

Passwords are hashed with scrypt, sessions last 30 days and only a hash of the session token is stored, and sign-in attempts are rate limited per username and per address (in memory, so a restart resets them). Set `DATABASE_URL` to a `postgresql://...` URL to keep accounts and portfolios in PostgreSQL instead of the SQLite file `app/data/users.db` (tables are created on first start; nothing is copied over from SQLite). Serving the app over HTTPS? Set `STOCKPICKS_SECURE_COOKIES=1` so cookies are sent only over HTTPS. The app does not trust proxy headers: behind a reverse proxy every visitor looks like one address to the rate limiter.

## Updating NSE holidays

The app does this by itself: it checks when it starts and again every 6 hours while it runs, and fetches only when the list is due (monthly on the 1st, daily from 1 Dec to 31 Jan, or overdue). The daily refresh job checks too. The fetch takes NSE's cash-market list and merges it into `holidays.json`. It only writes a valid response, never removes a year NSE did not send, and keeps an official year if the new list is shorter. The server also runs it at start when due (the 1st of each month, every day from December to January, or if the last good fetch is over 31 days old). NSE's endpoint is undocumented and may block it. If so, paste the dates from NSE's circular into `holidays.json` by hand and set that year's `status` to `official`.

## Tests

```
cd app
pip install -r requirements-dev.txt   # once
python -m pytest tests -q
```

Runs offline in a few seconds. One test group needs Node.js and skips itself without it.

## Project layout

Each screen has its own folder under `app/modules/` with its page, its Python services, and the JavaScript and CSS only that screen uses. Code several screens share lives in `app/core/` (Python) and `app/assets/` (JavaScript, CSS, icons).

```
app/
  server.py              web server, stock scan, scoring and forecast (start here: python server.py)
  refresh_job.py         daily refresh for Windows Task Scheduler (stays here so an existing scheduled task keeps working)
  core/                  shared Python: store.py (SQLite, or PostgreSQL through pgdb.py), api_me.py (the per-user API router), fundamentals.py,
                         update_holidays.py, plans.py, paths.py
  modules/
    home/                index.html, index.js
    stocks/              stocks.html, etfs.html, bse.html, lists.py (NSE/BSE/ETF lists), bhavcopy.py (official exchange close)
    stock/               stock.html (?symbol=TCS), why.py (the Why panel), notes, price alerts, what-if calculator, share and print
    portfolio/           portfolio.html, portfolio.py, positions.py, rules.py, alerts.py, Sync from Groww (groww.js)
    settings/            settings.html, settings.js
    account/             account.html, auth.py (passwords, sessions), groww.py (Groww API), account.css
    about/               about.html, backtest.py (the track-record report text)
  assets/                shared css (tokens, layout, components, chart), shared js (shell, common, chart, holdings, ...), icons
  tests/                 offline tests
  holidays.json, cache/, data/    data the app reads and writes (not code; cache/ and data/ are git-ignored)
```

Nothing here has to be run by hand. The daily scan rebuilds the held-out test report (read it at `/api/track-record`, linked from "How this was tested" on Home), and the app keeps the NSE holiday list current. `python -m modules.about.backtest` (from the `app` folder) is optional: it only reprints the same report from the saved price cache.

A page is served at its usual address (`/portfolio.html`, `/stock.html?symbol=TCS`, ...). A screen's own `.js` and `.css` are served from `/modules/<screen>/`; Python files and page sources in those folders are never served. Run the Python tools from the `app` folder, for example `python -m core.update_holidays`.

## Files

| File | Purpose |
|---|---|
| `app/server.py` | Scan, scoring, forecast, web server |
| `app/modules/<screen>/` | One folder per screen, see Project layout |
| `app/core/` | Shared Python services |
| `app/assets/css/` | `tokens.css` (Fresh Teal theme, light and dark), `layout.css` (shell, grid), `components.css`, `chart.css` |
| `app/assets/js/` | `shell.js` (sidebar, top bar, bottom nav, sheets, search, theme), `common.js`, `picks-table.js`, `chart.js` (loads `echarts.min.js` when a chart is first shown), `holdings.js`, `attention.js`, `allocation.js`, `glossary.js`, `why.js` |
| `app/manifest.webmanifest`, `app/assets/icons/` | Installable-app manifest and icons |
| `app/holidays.json` | NSE holiday list (updated by `core/update_holidays.py`) |
| `app/tests/` | Offline tests |
| `ROADMAP.md` | Planned work and progress log |
