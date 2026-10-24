---
name: web-research
description: >-
  Responsible web research. Finds and fetches PUBLIC data for this project
  (BSE share list, NSE ETF list, exchange holiday lists, public fundamentals)
  the polite and legal-minded way: official download or API first, read
  robots.txt and the terms page, then fetch slowly with an honest User-Agent,
  a request cap and a disk cache, and stop on 403 or 429. Never logs in,
  never uses private APIs, never invents data. Use when the user says "get
  the BSE list", "find the ETF list", "fetch holidays", "scrape this site",
  "is it OK to use this data", "check the terms", or before adding any new
  external data source. Groww app or private API scraping is out of scope.
argument-hint: "<what data is needed> [url]"
---

# web-research

This skill decides whether and how to fetch public web data. The project plans
public users (ROADMAP.md, "Risks to settle before public users": data licence,
broker terms), so every source must be checked, not assumed. Read ROADMAP.md
and README.md first if you have not.

`${CLAUDE_SKILL_DIR}` is this skill's folder.

## Steps, in this order

1. **Official route first.** Look for an official download (CSV, XLSX), feed,
   RSS or documented API on the data owner's site. Use it if it exists. Prefer
   one file download over crawling many pages.
2. **Read the rules before fetching pages.** Run:
   `python ${CLAUDE_SKILL_DIR}/check_source.py <url>`
   It reads robots.txt only. Then open the site's terms or disclaimer page and
   find what it says on automated access and on redistribution. Quote the
   relevant line. If a page could not be read, write `not read`. Never guess,
   and never say "probably allowed".
3. **Only then fetch public pages**, within these limits:
   - Honest User-Agent that names the project and gives a contact, never a
     browser disguise.
   - At least 1 second between requests to the same host (use the robots
     crawl-delay if it is longer).
   - A per-run request cap (default 20). Stop at the cap and report.
   - Cache every response on disk (for example `data/cache/<host>/<hash>`).
     Do not fetch the same URL twice in one day.
   - On 403 or 429, stop that host for the run. Do not retry, rotate headers,
     use proxies or look for a workaround. Report it.
4. **Hard no list.** Never log in. Never use cookies from a user's account.
   Never call private or undocumented app APIs of a commercial site. Never
   bypass captchas, paywalls or rate limits. Disallowed in robots.txt means
   do not fetch.
   - **Groww:** scraping Groww's app or private API is out of scope. Point the
     user to their own holdings export file (import template, G2) or to
     Groww's official Trading API, and tell them its terms must be read first.
5. **Never invent data.** If a value was not fetched, leave it blank or say it
   is missing. Every figure carries: source URL, date fetched, terms status
   (`allowed`, `not allowed`, `unclear`, `not read`).
6. **Record the source.** Put the source record in your reply. Write it into
   ROADMAP.md only when the user asks.

## Checklist (copy into the reply)

- [ ] Official download, feed or API looked for (result: ...)
- [ ] robots.txt read (line quoted, or `not read`)
- [ ] Terms page read (line quoted on automation and redistribution, or `not read`)
- [ ] Path allowed for our User-Agent
- [ ] UA honest, delay >= 1 s, request cap set, cache on
- [ ] No login, no cookies, no private API, no captcha or paywall bypass
- [ ] Every figure has URL, date fetched, terms status
- [ ] Redistribution to app users checked separately from our own reading

## Source record template

```
Source name:
URL fetched:
Official download or API available: yes / no (link)
robots.txt: allowed / disallowed / not read  - quote:
Terms page URL:
Terms on automated access: quote, or not read
Terms on redistribution: quote, or not read
Terms status: allowed / not allowed / unclear / not read
Date checked:
Allowed use: personal only / app users with credit / needs licence / unknown
Requests made: N (cache hits: N)
Notes:
```

Reading data for the owner's own use is a different question from showing it
to public users. If the terms are silent or unclear on redistribution, mark
`unclear` and say so.

## Stop and ask the user when

- The terms forbid automated access or redistribution, or are unclear.
- robots.txt disallows the path, or could not be read.
- You hit 403, 429, a captcha, a login wall or a paywall.
- The only way to get the data is a private or undocumented API.
- The request would need more than the cap, or a user's account or cookies.
- A licence, fee or contact with the data owner looks needed.
- The data would be shown to other users or sold (ROADMAP P7).

This is a working checklist, not legal advice. For licensing doubts, ask the
user to check with a qualified professional.
