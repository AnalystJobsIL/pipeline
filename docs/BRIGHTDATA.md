# Bright Data integration — how it's set up and how to redo it

*Re-verified against the tree on 2026-08-27 by the `docs` lane. The API shape, the
`bd_rescue.py` wiring and the dashboard steps held; the product table and the budget model
did not, and both are rewritten below.*

## What we use and why
| Product | Used for | Cost |
|---|---|---|
| **Web Unlocker API** | Every residential fetch in the repo: a careers page the runner's address cannot read, a position page the scraper could not open, a JD the plain GET was refused, and `deep_validate.google_via_unlocker` (the working search since SerpApi ran out) | 1 credit/request; free tier = 5,000 credits/mo, renews monthly, no rollover. **See the budget section — there is no single "weekly pass" any more.** The "~107 blocked pages" this row used to quote is not re-derivable from anything in the tree today |
| **LinkedIn Jobs dataset** (`LINKEDIN_DATASET`, `discovery_daily.py`) | **LIVE**, not planned — it has been running in `daily-digest.yml` since before 2026-08-23. Used by the *targeted* backfill, which needs the `company` field. Each record carries company + apply-URL → we resolve that company's own board once and scan it directly from then on | **1 credit per RECORD**: one trigger returning 391 jobs costs 391 credits |
| **Web Unlocker for the LinkedIn breadth sweep** | the same sweep's wide pass, through the keyless guest endpoint | **1 credit per PAGE** — the code documents the difference as ~55x, which is why the breadth sweep uses this and the targeted one uses the dataset |
| Browser API / SERP API | not used | — |

## Dashboard configuration (done via Chrome automation, Aug 2026)
1. brightdata.com/cp → left nav **Web Access** → **Add API**
2. Choose **Web Unlocker API** (not Browser API / SERP) → Continue
3. Configure: **Name: `web_unlocker1`** (cannot be changed later), CAPTCHA Solver ON → Continue
4. **Add payment method** — user-only step (Claude never touches payment fields). Free credits
   still apply first; card is only charged beyond the free 5,000/mo
5. **API token**: avatar (top-right) → API tokens (or zone Overview tab)

## Local/CI wiring
- `setup_brightdata.py` (Desktop launcher `Set-BrightData-Key.cmd`): prompts for token + zone,
  writes `secrets.env` (`BRIGHTDATA_API_KEY`, `BRIGHTDATA_ZONE`), sets the same as GitHub Actions
  secrets, verifies with ONE request against a known-blocked page. Values never shown to Claude.
- `bd_rescue.py`: for every `unreachable` row in companies.csv → POST
  `https://api.brightdata.com/request` `{zone, url, format:"raw"}` with `Authorization: Bearer` →
  extract ATS/Comeet/Workday signature from unblocked HTML (`wayback_rescue.extract_ats`) →
  verify against the LIVE ATS API → promote, or mark validated-scanned.
- `.github/workflows/retry-unreachable.yml` runs `bd_rescue.py` first whenever the secret exists
  (daily, `BD_LIMIT=120`).

## API shape (verified against 2026 docs)
```
POST https://api.brightdata.com/request
Authorization: Bearer <API_KEY>
Content-Type: application/json
{"zone": "web_unlocker1", "url": "<target>", "format": "raw"}
-> response body = unblocked page HTML
```
Proxy-mode alternative: `brd.superproxy.io:44445`, user `brd-customer-<id>-zone-<name>`.

## MCP server (optional, for interactive Claude sessions)
Bright Data ships an official MCP server (`@brightdata/mcp`, docs.brightdata.com → MCP) exposing
scrape/search tools backed by the same account. To add to Claude Code:
`claude mcp add brightdata -e API_TOKEN=<token> -- npx -y @brightdata/mcp`
(user runs this themselves so the token stays out of Claude's context). The pipeline deliberately
uses the REST API instead — deterministic, works in GitHub Actions, no MCP dependency.

## Budget guardrails — one pool, many consumers

There is **one** 5,000-credit monthly pool and **eight workflows hold the key**
(`audit-coverage`, `auto-expand`, `daily-digest`, `listing-hunt`, `retry-unreachable`,
`scrape-refresh`, `self-heal`, `triage-dark`). The "our weekly pass ≈ 430/mo" line this
section used to carry described a world with one consumer and has been wrong for weeks —
the pool was measured at **118 % (5,906/5,000)** on 2026-08-26.

Month-to-date accounting and the projection live in `discovery_daily.py`
(`BD_MONTHLY_BUDGET`, default 5000) and print as a `[bd-spend]` line in the digest log.
That is the number to read; nothing else totals the pool.

Per-consumer caps, all env vars, all re-derivable with
`grep -rn "_BD_CAP\|BD_LIMIT\|UNLOCK_PAGES" --include=*.py --exclude-dir=.claude .`:

| cap | default | who spends it |
|---|---|---|
| `BD_LIMIT` | 120/day in CI | `bd_rescue.py`, `bd_employees.py` |
| `JD_ENRICH_BD_CAP` | 40 | `enrich_scrape_jd.py` |
| `MATCHED_JD_BD_CAP` | 25 | `enrich_matched_jd.py` |
| `DEEP_BD_SEARCH_CAP` / `LLM_BD_SEARCH_CAP` / `AUDIT_BD_SEARCH_CAP` | 5 | `deep_validate.py`, `resolve_llm.py`, the Sunday audit |
| `SCRAPE_UNLOCK_PAGES` | 5 | `scrape_universal.py`, per company |
| `JD_BD` | **`1` — it defaults to SPENDING** | every JD enricher; set `JD_BD=0` for any local run |

`JD_BD` is the one to remember: it is not a cap but a switch, it defaults to on, and every
rehearsal harness in `tests/` sets it to `0` for exactly that reason.
