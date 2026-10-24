# Indian market (NSE / BSE) support

These skills came from the upstream day-trader-skill pack, which is US-only. This copy adds India for
buying and holding stocks. An Indian ticker is a Yahoo-style symbol ending `.NS` (NSE) or `.BO` (BSE):
`RELIANCE.NS`, `TCS.NS`, `TATSILV.NS`, `500325.BO`. US tickers work exactly as before, and you can mix both.

| skill | India | what it does for an Indian ticker |
|---|---|---|
| `/trader-alerts` | yes | price alerts in rupees on the NSE clock (9:15 to 15:30 IST, NSE holidays); `clock --market IN` |
| `/trader-news` | yes | NSE corporate announcements (results, board meetings, deals) plus headlines (Yahoo, else Google News India); times in IST |
| `/trader-analyst` | partly | quarterly revenue, margins, EPS in Rs crore with India's April-March quarters, from Yahoo; thin coverage, no ETFs, weak for banks |
| `/trader-scanner` | partly | `universe --market IN` and `daily --market IN`: daily setups on about 2,300 NSE shares. The opening-range scan is US-only |
| `/trader-budget` | partly | `"currency": "INR"`; weights mode splits a rupee budget into whole shares. Day-trade sizing is US-only |
| `/trader-entry`, `/trader-exit`, `/trader-timemachine`, `/trader-risk`, `/trader-broker`, `/trader-pelosi` | no | US day-trading tools (NYSE session, Alpaca, US Congress). They say so rather than run |

## Typical flow for buying an Indian stock

1. `python3 scan.py universe --market IN`, then `python3 scan.py daily --market IN` (or skip: pick a stock yourself).
2. `/trader-analyst RELIANCE.NS` for the numbers, and confirm them on NSE/BSE.
3. `/trader-news RELIANCE.NS` for announcements and headlines.
4. `/trader-budget` in weights mode to turn a rupee budget into whole shares.
5. `/trader-alerts` to set price levels. Place the order yourself in your broker app.

## What to know

- ETFs and funds (TATSILV.NS) have no earnings: analyze them by expense ratio, tracking error, AUM, volume and the underlying price.
- Data is free, unofficial and delayed (Yahoo, NSE, Google News). The NSE holiday list covers 2026 only: check nseindia.com for 2027.
- No India broker connector is included. `trader-broker` and `trader-risk` are Alpaca / US only.
- Yahoo's latest NSE bar can lag for some stocks, and fundamentals can stop months back for some companies. The tools say when they notice.
- Nothing here is financial advice.
