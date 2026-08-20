# Bright Data integration — how it's set up and how to redo it

## What we use and why
| Product | Used for | Cost |
|---|---|---|
| **Web Unlocker API** | Fetching the ~107 anti-bot-blocked careers pages (Cloudflare etc.) through residential IPs; returns the real HTML from which we extract each company's ATS board | 1 credit/request; free tier = 5,000 credits/mo (renews monthly, no rollover). Our weekly pass ≈ 430/mo |
| **LinkedIn Jobs Scraper API** (planned) | Discovery catch-all: one daily query (analytics roles, Israel) sees postings from EVERY employer incl. Google/Meta/Apple. Each record carries company + apply-URL → we resolve that company's own ATS once (free) and scan it directly forever — LinkedIn quota is only spent on discovering NEW companies | 5K records/mo free tier |
| Browser API / SERP API / Datasets | not used | — |

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

## Budget guardrails
- Free tier: 5,000 credits/mo. bd_rescue caps per-run via `BD_LIMIT` (default 120/day in CI).
- LinkedIn scraper (when added): cap discovery query to ~100 records/day, dedupe against
  companies.csv before spending anything, migrate discovered companies to direct ATS scanning.
