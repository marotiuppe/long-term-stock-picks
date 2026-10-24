# Long-Term Stock Picks: Roadmap

Single place for all planned work. No separate tracking folder. Update the status boxes and the Progress log as work lands.

Status: `[ ]` todo, `[~]` in progress, `[x]` done. Effort: S (hours), M (a day or two), L (a week or more). Effort figures are estimates.

## Context

- **Product:** NSE buy-and-hold stock picker (10 days to 6 months). Daily bars only, no intraday, no auto-trading. The score has no proven edge, so never promise profit.
- **Today:** one local Python script (`app/server.py`) and one page (`app/index.html`), single user, run via `Start Stock Picks.bat`.
- **Next:** deploy on Render, then move to our own server as usage grows.
- **New requirement:** more than one user. Each user needs their own portfolio, watchlist and settings.
- **Assumption:** "local bun" in the request is read as "local run". The app has no Bun or JavaScript backend today. Tell me if you meant to move to Bun.

## Key design rule for multi-user

Market data and the scan are the same for everyone, so **scan once and serve many**. Only holdings, watchlist, settings and alerts are per user. This keeps Yahoo load flat as users grow, and it is the main reason to split the app into a scan worker and a web server (P2).

## Suggested order

| Phase | Goal | Items |
|---|---|---|
| 1. Now, local, **before 1 Jan 2027** | Remove date bug and obvious defects, get a safety net | G1, Q2, Q3, Q4, Q5, G5 |
| 2. Local, multi-user ready | Portfolio and per-user data, with a clean split of scan and web | P1, P2, P7, G2 (manual and Groww file first), G3 |
| 3. Render deploy | Auth, database, background scan, monitoring, keep-alive, then broker APIs once terms are confirmed | P3, P4, P5, P8, G2 (Groww and Zerodha API), G4 spike |
| 4. Own server | Docker, backups, scaling | P6 |
| Ongoing | Trust and method quality | Q1, Q6, Q7, Q8, Q9, Q10 |

---

## Part A: Prioritised feature gaps

### Quick wins

- [x] **G1. Holiday list for 2026 to 2028** (S, high value, deadline 1 Jan 2027). Done 2026-10-24, see Progress log.
  - Problem: `NSE_HOLIDAYS` in `server.py:57` covers 2026 only, so buy and sell dates are wrong from January.
  - **What exists (checked 2026-10-24):**
    - **2026: official, verified.** The 16 weekday holidays already in the code match the list on [Angel One](https://www.angelone.in/nse-holidays) (the page shows no publication date).
    - **2027 and 2028: NSE has not published them.** NSE normally issues the next year's list by circular in December, so the earliest official 2027 list is expected in December 2026 and 2028 in December 2027. The lists below come from a commercial calendar site ([2027](https://www.calendarlabs.com/nse-market-holidays-2027/), [2028](https://www.calendarlabs.com/nse-market-holidays-2028/)), which does not say whether they are official or tentative. Treat them as **provisional**. Lunar and religious dates (Holi, Eid, Muharram, Diwali and similar) can move by a day.
  - Only weekdays are listed, because weekends are already skipped by `is_td`.

  | Year | Status | Weekday holidays |
  |---|---|---|
  | 2026 | Official | 01-15, 01-26, 03-03, 03-26, 03-31, 04-03, 04-14, 05-01, 05-28, 06-26, 09-14, 10-02, 10-20, 11-10, 11-24, 12-25 |
  | 2027 | Provisional | 01-26, 03-10, 03-22, 03-26, 04-14, 04-15, 04-19, 05-17, 06-15, 10-29 |
  | 2028 | Provisional | 01-26, 02-23, 04-04, 04-07, 04-14, 05-01, 05-05, 08-15, 08-23, 09-27, 10-02, 10-17, 10-18, 11-02, 12-25 |

  - Left out because they fall on a weekend: 2027 Mar 6, May 1, Aug 15, Sep 4, Oct 2, Oct 10, Nov 14, Dec 25. 2028 Feb 27, Mar 11, Jun 3. NSE can still list a weekend holiday separately, so this changes nothing for trading days.
  - Do:
    - Move holidays to `app/holidays.json`, one block per year with `status` (`official` or `provisional`), `source` and `checked` date.
    - Show a visible badge on any buy or sell date that falls in a provisional year, replacing the static `holidayNote`.
    - Show a stronger warning for any year with no entry.
    - Add two dated reminders to the Progress log: replace 2027 with NSE's circular in **December 2026**, and 2028 in **December 2027**.
  - **Automatic fetch (decided 2026-10-24).** NSE publishes its holiday list as JSON at `https://www.nseindia.com/api/holiday-master?type=trading`. I tested it on 2026-10-24 and it returned data for 2026 only, in segments including `CM` (cash market, the one we need). No 2027 or 2028 yet, which matches NSE publishing in December. It is an undocumented endpoint, and NSE's home page returned 403 to the same request, so it can break or block without notice. I have not read NSE's terms for it.
    - Add `app/update_holidays.py` (stdlib only). It fetches the `CM` list, keeps all years it contains, and marks each fetched year `official`. It sends a browser-like User-Agent and a Referer, and falls back to a first request that collects cookies if the direct call fails.
    - **Safety rules:** write only if the response parses, has at least 10 entries and every date is valid. Never remove a year that the response does not contain (so provisional 2027 and 2028 stay until replaced). Never replace a year with fewer entries than before without a warning. Write to a temporary file, then rename. Keep the last good file if anything fails.
    - **Schedule:** run on the 1st of every month, as you asked. Add a catch-up run on server start if the file was last checked more than 31 days ago, so a missed run on a laptop that was off still happens. Because NSE publishes in December, also run it **daily from 1 Dec to 31 Jan**: it is one request, and it gets the new list the day it appears instead of waiting up to a month.
    - **Where it runs:** locally, use Windows Task Scheduler or the start-up catch-up. On Render (P4), use a cron job. On our own server (P6), use cron or a systemd timer. Cloud servers may be blocked by NSE, so if the fetch fails there, the app keeps the stored list and shows the provisional badge.
    - Show on the page when the list was last checked, and send the owner an alert if the fetch has failed for more than 45 days.
    - If the fetch stays blocked, fall back to a manual step: download NSE's circular and paste the dates into `holidays.json`.
  - Done when: a test proves `add_td` skips a listed 2027 holiday, a plan crossing 2027 shows the "provisional" badge, and removing a year shows the warning. A test with a canned NSE response proves a good response updates one year, a malformed or empty response changes nothing, and a response with only 2026 leaves provisional 2027 and 2028 in place.

- [~] **G5. CSV export of the table and of the user's portfolio** (S, low to medium). Table export done 2026-10-24; portfolio export waits for G2.
  - Do: "Download CSV" button for the current filtered list (symbol, call, price, p10/p50/p90, stop, buy and sell dates). Build the CSV client-side.
  - Done when: the export matches the table for the chosen horizon and filter, and opens in Excel with ₹ and Indian number formats intact.

### Strategic bets

- [~] **G2. Portfolio / holdings: load, track, review** (M to L, high)
  - Why: you hold TATSILV, and a picker is more useful once it knows what you own.
  - Data model (per user): `holding(user_id, symbol, qty, avg_price, first_buy_date, source)`. Keep lots later if tax tracking is wanted (see Not now).
  - Show per holding: current price, P&L in ₹ and %, stop-loss and distance to it, review date for the chosen horizon, current call, and a flag when the stop is breached or the call turns Downtrend.
  - **Loading options, in build order:**

  | # | Method | What we know | Effort | Notes |
  |---|---|---|---|---|
  | 1 | Manual add or edit, plus paste of "SYMBOL qty avg" lines | Needs nothing external | S | Ship first. Validate symbols against the NSE universe. Handles ETFs like TATSILV. |
  | 2 | **Upload broker holdings file** (CSV or XLSX) with a column-mapping step. **Groww template first, then Zerodha.** | Zerodha Console exports holdings as XLSX (Portfolio, Holdings, Download XLSX): [support.zerodha.com](https://support.zerodha.com/category/console/portfolio/articles/holding-report). **Groww's holdings export format: unverified.** I did not find it. Get a real sample file from a Groww user before building the template. | M | Built-in templates per broker plus a generic mapper (pick symbol, quantity, average-price columns). Show a preview before saving. Parse in the browser so the file never leaves the user's machine, or on the server with the file deleted after parsing. Decide in P1. |
  | 3 | **Groww Trading API**, read-only holdings | Official page advertises ₹499 + taxes per month. A third-party guide says the free trial excludes live data and backtesting but still allows holdings, positions and margin, and lists a ₹4,999/year plan. Python SDK has `get_holdings_for_user`. Docs say OAuth 2.0 with tokens that **expire daily**. Holdings calls are limited to 20 per second, 500 per minute in the official docs. Sources: [Groww API docs](https://groww.in/trade-api/docs/curl), [Groww API page](https://groww.in/trade-api), [Chittorgarh review](https://www.chittorgarh.com/broker/groww/api-for-algo-trading-review/173/). Pricing differs between sources, so **confirm on Groww's pricing page**. | M to L | **Unverified and decisive:** whether our service may log other people in through Groww (a normal "connect your broker" flow), or whether each user must create their own API key and paste it into our app. If it is the second, we would hold user secrets, which raises the security bar (see Q8). Ask Groww or read their terms before building. |
  | 4 | **Zerodha Kite Connect API**, read-only holdings | Free "Personal" tier covers holdings and positions, per Zerodha's [charges page](https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/kite-api/articles/what-are-the-charges-for-kite-apis) and [forum](https://kite.trade/forum/discussion/comment/53027/). Pricing changed several times and third-party blogs disagree. **Check developers.kite.trade before building.** Whether one app may serve many users: **unverified**. | L | Needs per-user OAuth login, token storage and daily re-login. Only for Zerodha users. |
  | 5 | Upstox and other broker APIs | Search returned nothing usable. **Unverified.** | unknown | Add a broker only when real users ask for it. |
  | 6 | Depository statement (CAS PDF from CDSL or NSDL) | Search returned nothing on format or import. **Unverified.** | L | Covers all brokers in one file, but needs PDF parsing and password handling. Research later. |

  - **Design for several brokers.** Define one `BrokerConnector` interface (`connect`, `fetch_holdings`, `disconnect`) so Groww, Zerodha and others plug in without changing the portfolio screens. File upload is one connector, each API is another.
  - **Never** ask users for broker passwords or store API secrets or tokens unencrypted. Read-only access only. No order placement (rejected scope). Let a user disconnect and delete stored tokens at any time.
  - Because tokens expire daily, an API connection cannot refresh holdings overnight by itself. Plan for "reconnect" prompts, and keep the last imported holdings visible with a "last synced" time.
  - Done when: a user can load holdings by manual entry and by a Groww file, sees P&L and stop status, and another user cannot see them. API connectors follow once the Groww and Zerodha terms are confirmed.

- [x] **G3. Watchlist and local alerts, end-of-day only** (M, medium to high). Done 2026-10-24 (in-page inbox only; email later).
  - Alerts: stop breached, price near the 20-day average on a WAIT stock, call changed (Buy to Downtrend, etc.), review date reached.
  - Delivery: in-page inbox first. Email later (needs a sender service, a cost and a deliverability concern in P4). Nothing intraday.
  - Done when: after each scan, a user's holdings and watchlist produce alerts once per event, with no repeats.

- [~] **G4. Fundamentals filter** (M to L, high, data risk). Spike 2026-10-24: **no-go for now**, no lawful source found (see Data source terms). No coverage was measured.
  - Why: every comparable tool (Screener.in, Tickertape, Trendlyne) leads with fundamentals, and the price-only score has no proven edge.
  - Do: pull ROCE, debt/equity, revenue and profit growth, and a promoter-holding trend, from one source. Use them to demote weak businesses from Buy to Watch. Do not invent a new composite "score" (see Not recommended).
  - Risk: Yahoo fundamentals are thin for some NSE names and weak for banks and ETFs (see `.claude/skills/INDIA.md`). Spike first (S): measure coverage across the 2,300 shares before committing.
  - **Decision (owner delegated, 2026-10-24):** do the spike first and build only if coverage is good. Proposed bar: usable ROCE, debt and growth figures for at least 80% of the stocks that reach Buy or Wait, with banks handled separately or left out. This 80% bar is my suggestion, so change it if you want.
  - Done when: spike reports coverage, and the decision to proceed or drop is written in the Progress log.

### Nice-to-haves

- [x] **G6. Index baseline.** Done 2026-10-24. Show NIFTYBEES as the "just buy the index" comparison on each horizon (S to M).
- [ ] **G7. News for all stocks** instead of the top 40. Only after the scan moves to a background worker (S).

### Not recommended

- Intraday signals, Streak-style algo execution, broker order placement. You rejected day trading.
- A new single composite score in the style of Trendlyne's DVM. It would add another number with no proven edge.
- More "AI price prediction". The honest "no edge" message is the differentiator.

---

## Part B: Quality improvements to the existing app

- [x] **Q1. Out-of-sample track record** (M, high for trust). Done 2026-10-24. Held-out edge is not distinguishable from zero at 10d, 1m or 3m; 6m has no held-out rows yet. `python app/backtest.py` reproduces the numbers.
  - Problem: the track record and the forecast use the same history (`build_pool`, `track_record`). Windows overlap, since 10-day sampling is used with 126-day horizons, so hit rates look more certain than they are. Survivorship bias is disclosed but not fixed.
  - Do: train the pool on the earlier years and report the track record only on the later, held-out period. Report the effective sample count. Keep the survivorship caveat visible.
  - Done when: the page's "How this was tested" shows the held-out period and the edge number matches a script that anyone can re-run.

- [x] **Q2. News tone regex** (S, observed). Done 2026-10-24.
  - Problem: `NEG` in `server.py:208` has no word boundaries. `ban` matches "bank" and "Bandhan", `miss` matches "mission", `loss` matches "lossless". Bank stocks can be wrongly pushed to WAIT by `decide`.
  - Do: wrap each term in `\b...\b`, keep the cautious-only rule, and add tests with real headlines ("HDFC Bank ..." must score 0).
  - Done when: tests pass and no bank headline is penalised for the word "bank".

- [x] **Q3. Tests** (M). Done 2026-10-24. Holdings importer tests come with G2.
  - There are none. Start with pure functions: `add_td`, `first_td_from`, `score_at`, `decide`, `passes_quality`, the news tone, and the holdings importers once G2 exists.
  - Use fixed price fixtures, never live Yahoo calls. Add one smoke test that starts the server on a free port and reads `/api/scan` with a canned dataset.
  - Done when: `pytest` runs offline in under 10 seconds.

- [x] **Q4. README** (S). Done 2026-10-24, see `README.md`.
  - How to run, how the method works, what each call means, the "no proven edge" statement, data sources and their limits, how to update holidays.

- [x] **Q5. Error and stale-data handling** (S to M). Done 2026-10-24.
  - Show a clear banner when Yahoo is unreachable or data is older than the last trading day, and keep serving the last good scan instead of an empty page.
  - Return 404 for unknown paths and an explicit error for an unknown symbol in `/api/stock` (currently any path returns the index page and an unknown symbol returns `{}`).
  - Done when: with the network off, the page still shows the cached scan with a "data may be old" banner.

- [x] **Q6. Replace deprecated `utcfromtimestamp`** (S). Done 2026-10-24. Only matters if Python removes it. Use timezone-aware dates in `fetch`.
- [x] **Q7. Offline-safe fonts** (S, minor). Done 2026-10-24: font stylesheet no longer blocks rendering. Self-host or fall back to system fonts so the page does not wait on Google Fonts.
- [~] **Q8. Security basics before any public deploy** (M). Input validation, security headers and the forced-scan limit are done 2026-10-24; a full review is still needed before a public deploy. input validation on `sym`, response headers (CSP, `X-Content-Type-Options`), rate limits on `/api/scan?force`, no secrets in config or logs. Required for P3.
- [ ] **Q9. Accessibility regression check** (S). The chart table fallback and keyboard support exist. Add a check to the release steps whenever the UI changes.
- [~] **Q10. Performance** (S, suspected). Scan duration is now recorded and the page is cached in memory; measure with real users before more. The scan runs on one process and `index.html` is read from disk on every request. Measure scan time and memory with real users before optimising.

---

## Part C: Platform, multi-user and deployment

These are needed for "more than one user". They are not in your original gap list, so confirm the priority.

- [x] **P1. Architecture decision** (S). Defaults used 2026-10-24, not yet confirmed by the owner: stay on Python (stdlib server) with SQLite locally and Postgres on deploy; parse broker files in the browser (not built yet); login deferred to P3, so each browser is one user via a random cookie for now. Write the answer to each, as a short note in this file:
  - Stay on Python and add a small web framework, or rewrite? **Recommended default:** stay on Python (the scan logic is the product) and add a framework plus Postgres.
  - Parse uploaded files in the browser or on the server?
  - Which login method (email and password, Google, magic link)?
- [ ] **P2. Split scan worker from web server** (M). Not started. The worker downloads prices and builds the scan, then writes the result to storage (database or file store). The web server only reads it. This replaces the in-memory `STATE` and `DETAIL` in `server.py`, which cannot be shared across processes or restarts.
- [ ] **P3. Accounts and per-user data** (M to L). Auth, a database (users, holdings, watchlist, settings, alerts), per-user queries only, and moving the budget and max-loss values out of browser localStorage into the user's profile. Include account deletion and data export.
- [ ] **P4. Render deploy** (M). Confirm Render's current terms before choosing a plan, since I did not verify them. Check in particular: whether free web services spin down when idle, whether the filesystem is ephemeral, and the lifetime of free databases. Likely shape: one web service, one scheduled job for the scan, one Postgres. Configuration through environment variables, health check, log retention. Also confirm whether Yahoo throttles cloud IP addresses, since that works differently from your home connection.
- [ ] **P5. Monitoring and cost** (S). Scan success and duration, data freshness, error rate, and a daily "scan ran" check that alerts the owner.
- [~] **P7. Plans and feature flags, free for now** (S now, M later). The product is free today and may charge or limit features by plan once usage grows. Do the cheap part now: give every user a `plan` field (default `free`) and gate paid-capable features (for example broker API sync, alert email, extra horizons or watchlist size) behind one `can(user, feature)` check, so a plan change later needs no rewrite. Billing, invoices and tax (GST) wait until there is a decision to charge. Nothing is paywalled today.
- [~] **P8. `/health` endpoint and keep-alive pinger for Render's free tier** (S, medium; do together with P4). The `/health` endpoint is done 2026-10-24; the external pinger and Render health-check setting wait for P4.
  - **Why:** Render spins a Free web service down after 15 minutes with no inbound traffic, and the next request waits up to about a minute while it starts ([Render docs](https://render.com/docs/free), checked 2026-10-24). Here the wait is worse than usual, because the scan lives in memory (`STATE` in `server.py`) and a cold start means a multi-minute rescan. Until P2 moves the scan into storage, a sleeping server shows users a loading screen.
  - **`/health` endpoint:** add `GET /health` that returns HTTP 200 with a tiny JSON body, for example `{"ok": true, "dataAsOf": "...", "scanAgeMinutes": 12}`. It must be cheap: no scan, no price download, no database query beyond a trivial one, no authentication and no per-user data. Also answer `HEAD`. It must never start a scan. Keep the body minimal so it does not leak internals.
  - **Pinger:** use an **external** service that calls `https://<our-app>.onrender.com/health` every 5 minutes. It cannot be code inside the app, because a sleeping app cannot wake itself, and a call to `localhost` is not inbound traffic. Five minutes is inside the 15-minute window, so it keeps the instance awake.
  - **Options (confirm each one's terms before relying on it):**
    - UptimeRobot free plan: its [pricing page](https://uptimerobot.com/pricing/) lists 5-minute checks on the free plan. A competitor's blog says it banned commercial use in November 2024. **I did not verify that against UptimeRobot's own terms**, so read them first, especially once we charge (P7).
    - A scheduled GitHub Actions workflow or another free cron service. Scheduled runs can be delayed, so a 5-minute schedule may slip and miss the window.
  - **Limits you should know about:**
    - **Hours.** Render gives 750 free instance hours per workspace each month, and a service awake all month uses about 744. One always-on free service fits. A second free service would run out of hours and everything free would be suspended until next month ([Render docs](https://render.com/docs/free), [community thread](https://community.render.com/t/free-tier-queries/6555)). So the scan cannot be a second always-on free service. Run it inside the web service or as a scheduled job, and check whether scheduled jobs are free on Render (**unverified**).
    - **Restarts still lose memory.** Keep-alive stops idle sleep, but a deploy, crash or Render's own restart still empties `STATE`. P2 (storing the scan) is the real fix. Free instances also have no persistent disk and the `cache` folder is lost on restart (**check the current terms**).
    - **A workaround, not a plan.** Once users depend on the app, move to a paid Render instance, which does not sleep. I did not check the current price. The pinger is the cheap stop-gap until then.
    - **Real traffic only counts if it reaches the app.** A monitor that only tests the page from its own network, without calling our URL, does not help. The pinger must call our public URL.
  - **Also set Render's own health check path** to `/health` so deploys fail fast when the app does not start. This is separate from the keep-alive pinger and does not keep the app awake by itself.
  - **Alerting:** configure the pinger to notify the owner when `/health` fails twice in a row. Then it doubles as uptime monitoring (P5).
  - Done when: after 30 minutes with no human traffic the app still answers the first page load in under 2 seconds with the scan intact, the pinger shows 5-minute successful checks, and `/health` is verified to start no work.
- [ ] **P6. Own server** (M). Package as Docker with the same environment variables, database backups with a tested restore, HTTPS, and a basic upgrade routine. Keep Render-specific features out of the code so the move is only configuration.

### Risks to settle before public users (not legal advice)

- **Licensed data is a launch requirement (added 2026-10-24).** Every source checked forbids or does not clearly allow automated collection or redistribution. See "Data source terms" below. Before opening to other users, get a licensed or official feed for prices and exchange lists. For the owner's personal use on a local machine the risk is lower but not zero.

- **Data licence.** The app uses Yahoo Finance's free, unofficial feed and NSE's public list. Redistributing that data to many users, or running it commercially, may not be allowed. Check each source's terms, and plan a licensed feed if usage grows. **This risk rises the moment a fee or paid plan is added (P7).**
- **Regulation.** Telling other people which stocks to buy and sell may fall under India's SEBI rules for research analysts or investment advisers. Ask a qualified professional before opening this to the public, and again before charging. Until then, keep the educational framing and the "no proven edge" statements.
- **Broker terms.** Connecting to users' broker accounts (Groww, Zerodha) is governed by each broker's API terms, which I have not read. Confirm them before building any API connector.
- **Personal data.** Holdings are sensitive. Minimise what is stored, encrypt at rest on the server, and publish a short privacy note.

---

## Data source terms (read 2026-10-24; not legal advice)

| Source | What we use it for | What the terms say | Status |
|---|---|---|---|
| NSE website (Terms of Use, updated 29/10/2025, copy supplied by the owner) | Holiday list (`update_holidays.py`), `EQUITY_L.csv` universe | "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)". No copying or redistribution without written permission, "Unless the information or Content is available for download". No use of NSE data "for any gaming, virtual trading or simulation activities". | The holiday fetch conflicts with this. The `EQUITY_L.csv` download is a published download file, a grey area. Decision pending: make the holiday update manual. |
| BSE website policies (copy supplied by the owner) | Not used yet | "You should not conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our website without our express written consent." Site for "non-commercial purposes only". Copyright policy allows download "for personal, non-commercial or educational purpose" with acknowledgement. BSE `robots.txt` returns 403. | No automated BSE fetching. Manual download by the user for personal use is the only option without a licence. |
| Yahoo Finance (prices for all stocks) | Every price in the app | `query1.finance.yahoo.com/robots.txt` is `Disallow: /` (checked by us). Terms (quoted by a research agent, not read in full by us) ban "robots, spiders, scrapers" without permission and commercial use. | Acceptable only as a personal, local stopgap. Must be replaced before a public launch. |
| Screener.in | Fundamentals (not used) | "personal, non-commercial transitory viewing only"; no public API; export needs login. | Do not use. |
| AMFI NAV file | ETF names and NAV (not used yet) | The download page states no terms; footer terms not read. | Unverified. |
| NSE ETF list page | ETF list (not used yet) | Falls under the NSE terms above. | Manual download only. |

### GitHub repo review (2026-10-24, agents read READMEs and API metadata, no code run)

Topics reviewed: `bhavcopy`, `indian-stock-market`, `nse-stock-data`. **Result: use none of the repos and copy no code.**
- Almost all fetch from nseindia.com or bseindia.com automatically, often with browser-like headers or cookie warm-ups to get past blocking. This conflicts with both exchanges' terms and with our `web-research` skill.
- Several are GPL-3.0 (copying would force GPL on our code). Some have no licence. Two archive repos republish NSE data with no visible permission.
- The permissive ones (for example mftool, MIT) use Yahoo, AMFI or Screener.in, which does not make the data lawful for us.
- An open-source code licence does not grant any right to the exchange's data.
- Official broker APIs are the only lawful route found: Zerodha Kite Connect lists historical data at Rs 500 per month (page read 2026-10-24); Upstox, Groww and Angel were not fully read. All need the user's own trading account, and none obviously lets us serve prices to other users (data terms not read).
- No source found for: licensed price history, fundamentals, a holiday list, or an open dataset with a clear data licence. AMFI's NAV file is the only non-exchange source for ETF names, terms unread.
- File layouts found for the manual importer: old NSE bhavcopy (SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TIMESTAMP, ISIN), newer NSE UDiFF (TckrSymb, SctySrs, ClsPric and others), old BSE (SC_CODE, ISIN_CODE, SC_TYPE, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, date only in the filename). No newer BSE layout found: get a real sample from the owner.
- Next step before any public launch: ask NSE or BSE data sales or a vendor for terms and prices, and get legal advice (including on NSE's "virtual trading or simulation" clause).

## Decisions made

| Date | Decision |
|---|---|
| 2026-10-24 | Broker API connections are in scope, alongside file upload and manual entry (G2). |
| 2026-10-24 | Most first users have **Groww**, so the Groww import template and Groww API come before Zerodha. |
| 2026-10-24 | The product is **free for now**. Paid plans or feature limits may come later (P7). |
| 2026-10-24 | Fundamentals (G4): spike first, build only if coverage is good. |
| 2026-10-24 | Holidays 2026 to 2028 go into G1. 2027 and 2028 are provisional until NSE publishes them. |
| 2026-10-24 | **Owner decision, kept as is despite NSE's terms:** the NSE holiday auto-fetch stays on for now (personal local use). Revisit before any public launch. |
| 2026-10-24 | Holidays are fetched by script from NSE's holiday endpoint: monthly on the 1st, daily during Dec to Jan, plus a catch-up on start. Manual paste is the fallback. |

## Open questions

00. Holiday updater: switch to manual by default because of NSE's terms? Build manual-import BSE and ETF pages (user downloads the file, app reads it locally, personal use only)?
0. BSE stocks page: which data source may we use? BSE's `robots.txt` returned 403 and its terms are unread. ETFs page: confirm NSE's ETF list source and terms before adding the full list.
1. Can you get a real Groww holdings export (with personal data removed) so the import template matches the real columns?
2. Do you want to contact Groww about whether a third-party app can offer "connect your Groww account" login? This decides the shape of the Groww API connector.
3. Is 80% coverage the right bar for the fundamentals spike?

## Progress log

| Date | Change |
|---|---|
| 2026-10-24 | Roadmap created from the product gap analysis. No items started. |
| 2026-10-24 | G1 expanded with the 2026 to 2028 holiday table. 2026 checked against Angel One. 2027 and 2028 are provisional from calendarlabs.com. `server.py` not changed yet. |
| 2026-10-24 | G2 now includes Groww and Zerodha broker APIs. Added P7 (plans and feature flags). |
| 2026-10-24 | Added P8: `/health` endpoint plus an external 5-minute pinger to stop Render's free tier sleeping. Limits noted: 750 free hours, memory lost on restart. |
| 2026-10-24 | **G1 done.** `app/holidays.json` (per-year status, source, checked), `app/update_holidays.py` (fetch, validate, merge, schedule), `server.py` reads the file and runs the catch-up on start, page shows a "(provisional)" or "(no holiday list)" badge on affected dates plus a note with the last-checked date. 19 offline tests in `app/tests/test_holidays.py` pass. A live dry run against NSE returned 16 weekday holidays for 2026, identical to the stored list. Not done: the Windows Task Scheduler entry (start-up catch-up covers it while the app is used), and the 45-day failure alert is only shown on the page, not sent to the owner (needs P5). |
| 2026-10-24 | **Q2 done.** `POS` and `NEG` use whole-word matching and the regulatory tag uses `ban`, `sebi`, `rbi`. New `news_tone()` function. "HDFC Bank", "Bandhan", "mission" and "lossless" now score 0. 12 tests. |
| 2026-10-24 | **Q3 done.** 64 offline tests in `app/tests/` (holidays, news, scoring, `decide`, `passes_quality`, `add_td`, forecast, CSV, errors, server smoke test). Run in about 3 seconds. The CSV test runs the page's own code under Node and skips if Node is missing. |
| 2026-10-24 | **Q4 done.** `README.md` covers running, method, call meanings, the no-edge statement, data limits and the holiday updater. |
| 2026-10-24 | **Q5 done.** Unknown paths and unknown symbols return 404. If Yahoo is unreachable the scan falls back to the newest saved daily cache, and a failed refresh keeps the last scan. The page shows "Data may be old" (newest bar older than the last trading day) and "Last refresh failed". Not tested against a real network outage, only with simulated failures. |
| 2026-10-24 | **G5 table export done.** "Download CSV" exports the filtered list for the chosen horizon (all rows, not only the 150 shown), with a BOM so Excel shows ₹, plain numbers so Excel formats them, and a guard against formula injection from company names. Not opened in Excel by me. |
| 2026-10-24 | Phase 1 finished except the portfolio half of G5. Server restarted on the new code (found about ten old `server.py` processes from earlier sessions sharing port 8765 and serving old code, and stopped them). |
| 2026-10-24 | **Phase 2 first pass, built by four parallel agents and wired together.** New: `store.py` (SQLite, all rows scoped by user), `portfolio.py` (paste import, P&L and stop review), `plans.py` (`can(plan, feature)`, nothing paywalled), `alerts.py` (stop breached, near 20-day average, call changed, review due; one per event), `api_me.py` (per-user API with a random cookie, same-origin check, 100 KB body limit), `portfolio.js` and `portfolio.css` (the "My portfolio" section: manual add, paste import, watchlist, alerts inbox, export, delete my data). Also G6, Q6, Q7, Q8 basics, Q10 basics and `/health`. 118 tests pass in about 15 seconds (the Q3 target was under 10 seconds; some test files start real servers). Not done: Groww file upload and column mapping (needs a real sample file), broker APIs, P2 worker split, accounts and login (P3). Not verified: the portfolio screen in a real browser. |
| 2026-10-24 | **Separate pages built.** Shared sticky menu and pages at `/` (Home), `/stocks` (NSE), `/etfs`, `/portfolio`, `/stock/<SYMBOL>`, `/bse` ("coming soon", no data) and `/about`. 138 tests pass in about 25 seconds. Not verified in a browser: layout at 360px, dark mode, keyboard use. |
| 2026-10-24 | **`web-research` skill added** (`.claude/skills/web-research/`) with a `robots.txt` checker. Checks run: NSE `robots.txt` loads and allows `/` (terms page not read). BSE `robots.txt` returned HTTP 403, so BSE is **not read** and blocked until the owner decides (read BSE's terms, use another open source, or leave BSE as "coming soon"). Groww app or private API scraping is out of scope. |
| 2026-10-24 | **Q1 done** (agent). Held-out period from 2026-05-07, 25% held-out, 190-day purge gap. Hit-rate edge with 95% interval: 10d +0.5 pts (-0.9 to +2.0), 1m +1.2 pts (-1.0 to +3.4), 3m +2.1 pts (-2.9 to +7.2). All include zero. 6m has no held-out rows. |
| 2026-10-24 | **Q1 side effect fixed.** The Buy call's base rate had been switched to the held-out window, which was a weak market (47% of stocks rose in a month). That lowered the Buy bar and raised the Buy list from 154 to 460. Reverted: `base_rate` now uses the whole pool. A regression test locks this. Buy list is back to 154. |
| 2026-10-24 | **G4 spike: no-go for now.** No candidate passed the web-research gate, so no fundamentals were fetched and no coverage was measured. Options: licensed feed, paid vendor, or manual entry for a short list. |
| 2026-10-24 | **Exchange terms read** (BSE and NSE copies supplied by the owner). Both prohibit scripted collection. See Data source terms. The NSE holiday fetch (G1) conflicts with NSE's terms. |
| 2026-10-24 | **Browser QA (Playwright, Chromium) found 3 bugs, all fixed and re-checked in the browser:** (1) the CSV button on `/stocks` and `/etfs` emptied the table instead of downloading, because a `.chip` selector bound the filter handler to it; (2) Home showed an error because the server was still running pre-Q1 code (fixed by restart); (3) paste-import error lines were wiped by the re-render. Still open, low: the not-found page for an unknown stock shows no 404 status and a bare tab title, and horizon choice persists only in the URL hash. |
| **Due Dec 2026** | Confirm the fetch script picked up the official 2027 list and marked it `official`. If not, paste it from NSE's circular. |
| **Due Dec 2027** | Same for 2028. |
| 2026-10-24 | **Holdings tracking and "Needs your attention" alerts.** Transactions (lots) with average-cost P&L, sales with realised P&L, a My position card and chart markers, portfolio KPIs, allocation by stock or by your own sector tags, CSV/JSON export and import, a rules engine (11 rules, thresholds in Settings) fed by Yahoo company results, dismiss and snooze that clear when the condition changes. Schema version 2 migrates old holdings into opening lots (backup: `users.db.bak-v1`). Fixed a first-visit race where concurrent API calls could create several anonymous users (`/api/session`). Not available from Yahoo for NSE/BSE: sector, more than about five quarters, a P/E history longer than four fiscal years; ETFs and most banks have no company results, so those rules say "data unavailable". |
| 2026-10-24 | **Stock page: Why panel, ECharts chart and six quick wins** (built by five parallel agents, checked in Playwright at 360, 768 and 1280 px in light and dark: full screen and Esc, zoom, pan, reset, timeframes, no console errors, no horizontal scroll after one fix). New: `why.py` and `/api/why` (price facts plus Yahoo company results, fundamentals we lack show 'Not available', risks given equal weight, 'Why now' only when data supports it and never on a Downtrend call), one-line summary on list rows, chart rebuilt on Apache ECharts 5.6.0 (vendored in `assets/js/echarts.min.js`), glossary tooltips (53 terms), share link and print/PDF, saved notes per stock, price alerts (at or below, at or above, % below 52-week high; checked once a day), 'what if I had invested' lump-sum, SIP and compounding calculators. 405 tests pass. Not done: Medium and Big items from the audit (compare stocks, dividends view, valuation band, DCF, filings, email alerts) wait for approval. Not verified: iOS Safari full screen and landscape lock, real print preview, a screen reader.
| 2026-10-24 | **Sync from Groww** (G2, method 3 for your own account): each user enters their own Groww API key and secret in a dialog on Portfolio; saved encrypted (Fernet, master key in `app/data/groww.key` or env `STOCKPICKS_SECRET_KEY`) only after Groww accepts them, reused on later syncs, forgettable, never returned by the API or exported, removed by Delete my data. Read-only: only `get_access_token` and `get_holdings_for_user` are called. Stocks you entered with several transactions are never overwritten. 422 tests pass; dialog checked in a browser at 360 and 1280 px against a fake Groww client. **Not tested against the real Groww API** (no credentials used). Open: Groww's terms for an app that stores other people's keys are unconfirmed; `average_price` is typed as an integer in Groww's docs, so compare with the Groww app on the first sync; the key and master key sit on the same machine, so this protects a copied database, not a compromised computer.
| 2026-10-24 | **Login (P3, first version).** Guests still work. New: username and password accounts (scrypt, 30-day sessions stored as hashes, per-username and per-address throttling), **Sign in with Groww** (Groww has no OAuth for outside apps, so the key and secret are used once to call `get_user_profile`; the returned ids are stored only as keyed hashes), link and unlink Groww, password change that signs other devices out, and recovery by Groww sign-in. Guest data is kept when a guest signs up. A signed-out browser can never reach an account's data: the guest cookie is rotated on sign-up and a guest id that is an account id is refused. New `/account.html` and an account chip in the app bar. 452 tests pass; flows checked in a browser at 360 and 1280 px against a fake Groww profile (**not** against the real Groww API). Not done: email verification and email reset (no email service), two-step sign-in, merging a guest browser's data into an existing account at sign-in, a proxy-aware client address for the rate limiter, account deletion that is separate from Delete my data (they are the same action now).
| 2026-10-24 | **Project restructure: one folder per screen.** `app/modules/<screen>/` (home, stocks, stock, portfolio, settings, account, about) holds each screen's HTML, Python services and page-only JS/CSS; shared Python is in `app/core/`, shared JS/CSS stay in `app/assets/`. `server.py` and `refresh_job.py` stay at the app root so `Start Stock Picks.bat` and any Task Scheduler entry keep working. Moves only: URLs, APIs and behaviour are unchanged; imports updated everywhere, no forwarding files. New: `/modules/<screen>/*.js|css` route (Python and HTML sources there are never served, with tests). Command changes: `python -m core.update_holidays` and `python -m modules.about.backtest`, both from the `app` folder. Two existing bugs found and fixed on the way: list pages loaded `chart.js` without ECharts or `chart.css`, so a chart opened from a list row showed 'Price history could not be loaded' (ECharts now loads on first use). 476 tests pass; all 9 pages checked in a browser at 360 and 1280 px with no failed requests or console errors.
| 2026-10-24 | **Two manual commands made automatic.** (1) NSE holiday list: `server.py` only checked at start-up, so a server left running never re-checked (including the daily checks NSE's December publishing needs). A background thread now calls the existing due-based check every 6 hours; start-up still checks first, before the first scan. (2) Held-out track-record report: every scan now builds it (`backtest.format_report`, same numbers as the page), keeps it with the saved scan, and serves it at `/api/track-record` (linked from 'How this was tested' on Home; not sent with `/api/scan`). `python -m modules.about.backtest` stays as an optional offline re-print. A real scan from the price cache produced the report with the same figures as the command. Saved scans made before this change have no report until the next scan (daily job or Refresh data). 483 tests pass.
| 2026-10-24 | **Groww sync no longer drops stocks outside the scan.** First real sync: Groww returned 14 holdings, 6 imported, 8 skipped (ATVOENT, CROPSTER, DHARAN, OILIETF, OMNIAX, SBL, SPRAYKING, SPRIGHT) because the 'known stock' check only knows NSE EQ-series shares and a short ETF list. That check suits typed input, not holdings the broker reports. They are now imported, flagged `unscanned`, shown without price, call or chart, counted in Total invested and left out of value, weights and P&L (the portfolio already handled unpriced positions). The result also shows 'Groww returned N holdings' and a table of every stock with its outcome. Open: those stocks have no price here; pricing held stocks outside the scan (on-demand Yahoo lookup, cached, off the request thread) is the next step if wanted. 488 tests pass.
| 2026-10-24 | **Portfolio now values holdings the scan filters out.** Checked against the owner's Groww screenshot: all 14 holdings from the Groww API matched on quantity, average price and invested (13,641), but only 2 of 14 had a price because the portfolio priced only stocks the scan kept (it drops shares under Rs 20, thin trading or history). The price cache already held the last close for 13 of 14, equal to Groww's market price. Each scan now saves a compact last close for every filtered-out stock (`quotes`, about 2,700 entries, not sent with `/api/scan`); the portfolio values holdings with it and tags them 'price only' (no call, forecast or chart). Amounts under Rs 1,000 show paise. Verified with a real scan and the 14 holdings: all 13 priced stocks match Groww to the paisa for value and invested; total value 10,258.31 vs Groww 10,384 (the 126 gap is DHARAN, no Yahoo data). Open: DHARAN stays unpriced; Groww's last-price call (get_ltp, 50 stocks per call) could price it and any other stock Yahoo lacks. Saved scans made before this change have no quotes until the next scan. 493 tests pass.
| 2026-10-24 | **Refresh data is no longer slow and silent.** Found while checking the portfolio: the old saved scan had no last-close records, so the portfolio kept the old numbers until a scan finished, and 'Refresh data' deleted today's price cache and re-downloaded every stock (minutes) even on a Saturday when nothing newer exists. Now: (1) the scan has a version (`SCAN_VERSION`); a scan saved by older code is rebuilt once at start-up, reusing today's price download; (2) a saved scan with no `quotes` gets them rebuilt from the saved download at load time (0.1 s), so holdings are valued straight after a restart; (3) Refresh on data from the latest close answers at once with 'Already up to date' plus a 'Re-download anyway' button (`?force=full`); a plain refresh never re-downloads a download made after the close; (4) progress is shown while a scan runs; (5) the Portfolio page reloads itself when a scan finishes (`scan:updated`). Checked in a browser from the owner's real old scan: value correct at once (10,258.31), rebuild finished, page updated itself, Refresh answered in under 1 s. Not changed: a rebuild still takes a few minutes of computing (scoring and news), shown as progress. 500 tests pass.
