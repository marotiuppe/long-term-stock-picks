# Replica Skill: How It Works

Eleven Claude Code skills that take you from "I want my own version of app X" to a live, rebranded product. Source: https://github.com/Jakeschincariol/replica-skill (MIT license).

Installed globally at `C:\Users\91986\.claude\skills\replica-*`. Restart Claude Code after installing so the commands appear.

## Core idea

- It rebuilds **what an app does** (features, flows), never **what it owns** (code, logo, copy, content). Every skill is written around this clean-room rule.
- The skills form a pipeline. Each one reads what the previous one wrote into a `replica/` folder in your current project, so run them in order and from the same folder.
- No API keys or accounts are needed for the skills themselves. The Python helper tools need Python 3.8+ and nothing to pip install.

```
recon -> architect -> design -> build -> backend -> test -> diff -> entrepreneur -> brand -> launch -> deploy
```

## Before you start

1. Make a **new empty folder** for each clone. Do not run it inside another project (such as TRADING), because the skills write a `replica/` folder and project files there.
2. Open Claude Code in that folder.
3. Have the target app's URL, App Store link or screenshots ready.

## The eleven skills

| # | Command | Reads | Produces |
|---|---|---|---|
| 1 | `/replica-recon <url>` | The target app's public pages, help docs, store listings, screenshots | A recon map: screens, flows, components, inferred data model and a feature matrix (`recon-map.md`, `features.csv`) |
| 2 | `/replica-architect` | Recon map | Stack choice, SQL schema with indexes and access rules, route list by flow, and a build order that starts with a thin vertical slice |
| 3 | `/replica-design` | Recon map, architecture | Design tokens (colour roles, type scale, spacing, radius, shadows) and component specs with their states. Uses original assets. Includes a WCAG contrast checker (`contrast.py`) |
| 4 | `/replica-build` | Recon map, tokens | The app built screen by screen: shell first, then the core flow, then every screen with all its states. Ticks off the feature matrix as it goes |
| 5 | `/replica-backend` | Architecture, built UI | Auth, migrations, payments (Stripe), email, background jobs, integrations via official APIs only, and a security checklist |
| 6 | `/replica-test` | Recon flows | Test plan, Playwright end-to-end tests, a browser click-through where tests aren't possible, and bug reports with severity, steps and evidence |
| 7 | `/replica-diff` | Feature matrix, screenshots | A parity score weighted by must/should/could, the missing features in build order, and a colour-blind screenshot layout diff (`parity.py`, `imgdiff.py`) |
| 8 | `/replica-entrepreneur` | Public reviews (App Store, Google Play, G2, Capterra, Trustpilot, Reddit, Hacker News, feature-request boards) | Ranked user complaints and gaps, with verbatim linked quotes, a fix plan and a positioning angle (`reviews.py`, `themes.json`) |
| 9 | `/replica-brand` | Positioning, design tokens | Name candidates with trademark, domain and handle checks to run, a new palette checked for contrast, a logo brief, a voice guide, and a sweep for leftovers from the original (`sweep.py`) |
| 10 | `/replica-launch` | Positioning, brand | Landing page, pricing set against the original's public pricing, and an App Store / Play listing linted against store limits (`listing.py`) |
| 11 | `/replica-deploy` | Everything above | A preflight gate, production database and env vars, hosting, DNS for the domain and email, Stripe live mode, OAuth redirects, monitoring, and mobile builds to TestFlight and Play |

## Typical session

```
mkdir my-clone && cd my-clone
claude
> /replica-recon https://example-app.com
> /replica-architect
> /replica-design
> /replica-build
...
```

You do not need the exact command. Saying "clone Calendly", "what do users hate about X?" or "how close is my clone?" triggers the matching skill.

## Using single skills on their own

- `/replica-entrepreneur` alone is a market-gap and review analysis for any app, with no building involved.
- `/replica-diff` alone scores any clone against an original.
- `/replica-brand` alone helps name and rebrand any project.
- Skipping steps is fine, but later skills work better with the earlier outputs.

## Helper tools

All are standard-library Python. They make no network calls and work only on local files.

| Tool | Skill | Purpose |
|---|---|---|
| `contrast.py` | design | WCAG contrast checks on colour pairs |
| `parity.py` | diff | Weighted feature parity score from the matrix |
| `imgdiff.py` | diff | Layout comparison of screenshots, ignoring colour |
| `reviews.py` | entrepreneur | Clusters review rows into themes and feature requests |
| `sweep.py` | brand | Finds leftover names, links and copy from the original |
| `listing.py` | launch | Lints store listings against character limits and copycat rules |

## Rules to keep in mind

- Write everything fresh. Do not copy the original's code, logo, icons, illustrations, licensed fonts or text.
- Use official APIs only for integrations.
- Use the original's public information only.
- Run `/replica-brand` before `/replica-launch`, so nothing of the original ships.
- `/replica-deploy` refuses to proceed until tests pass, the rebrand sweep is clean and legal pages exist.

## Quick troubleshooting

- **Commands not showing up:** restart Claude Code and check that the folders exist in `C:\Users\91986\.claude\skills\`.
- **A skill seems to lack context:** make sure you are in the same folder as the `replica/` directory from earlier steps.
- **Python tool errors:** confirm `python --version` is 3.8 or newer.
- **To update or reinstall:** pull the repo again and copy the `replica-*` folders over the installed ones.
