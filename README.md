# AnalystJobsIL pipeline

The aggregation pipeline behind the **[AnalystJobsIL board](https://analystjobsil.github.io/board/)** —
a free board of experienced (≈3+ yrs) data-analyst / BI / analytics openings at Israeli high-tech
companies. The board holds every role we can still see on its employer's own careers page; once a
role comes off that page it moves to the [archive](https://analystjobsil.github.io/board/archive.html),
and it stays in the store either way. A daily email carries the roles posted in the last 48h.

Instead of scraping aggregators, it polls 1,000+ companies' **own public ATS endpoints**
(Comeet, Greenhouse, Lever, SmartRecruiters, Recruitee, Ashby, Workday, and per-company custom
JSON APIs) on a daily schedule via GitHub Actions, filters to Israel-located analytics roles,
dedupes across days and platforms, and publishes the board.

## companies.csv

The editable company list. Columns:

- `company_name` — display name
- `ats_platform` — one of `comeet`, `greenhouse`, `lever`, `smartrecruiters`, `recruitee`, `ashby`,
  `workable`, `bamboohr`, `breezy`, `oraclehcm`, `jazzhr`, `workday`, `microsoft`, `custom_json`,
  `scrape` (no public API — read from the rendered careers page) or `discovery` (the synthetic row
  that reads the LinkedIn/Indeed/Telegram discovery cache)
- `token` — the platform-specific board token/slug/id used to build the API URL
- `api_url` — the exact endpoint the scraper hits (pre-built so no guessing at runtime)
- `active` — `true`/`false`. Set to `false` to pause polling a company without deleting the row.
- `notes` — free text (e.g. "also on Lever - dedupe by job id")

The daily pipeline pulls the latest version of this file from the repo before each run, so edits
made in the GitHub UI are picked up on the next scheduled run (no redeploy needed).

To add a company:
1. Find its careers page and identify the ATS platform (check the URL — e.g. `jobs.lever.co/x`,
   `boards.greenhouse.io/x`, `comeet.com/jobs/x/...`).
2. Build the `api_url` per the pattern for that platform (see below) and confirm it loads valid
   JSON in a browser or `curl`.
3. Add a row.

### API URL patterns by platform

- Comeet: `https://www.comeet.com/careers-api/2.0/company/{token}/positions?token={token}`
  (token is embedded in the public careers page HTML/JS — not guessable from the URL alone)
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs`
- Lever: `https://api.lever.co/v0/postings/{token}?mode=json` (some companies use
  `api.eu.lever.co` instead — try both)
- SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/{token}/postings`
- Recruitee: `https://{token}.recruitee.com/api/offers/`
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{token}`
- JazzHR: no consistent public JSON API — needs per-company verification
- Workday: `https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` — **POST**
  only (a plain GET 400s), body like `{"searchText":"Israel","limit":20,"offset":0}`. `{tenant}`,
  `{N}` (wd1/wd3/wd5/wd12...), and `{site}` all vary per company and must be discovered from the
  live careers page's network requests.
- Custom JSON (e.g. Amazon): one-off per company, discovered via the careers page's own network
  requests. No shared pattern — verify and document each individually in `notes`.

### Multinationals — global boards need a location filter

Rows marked "Global board" in `notes` (Workday and other multinational-scale companies) return
job postings from **every country**, not just Israel. The scraper filters these to Israel (by
request body `searchText`/location facet for Workday, or a location field in the response)
before they reach the classification step, or the board would drown in postings from every
other office worldwide.

### Known duplicates across platforms

A few companies run boards on two ATS platforms simultaneously (e.g. WalkMe and Cloudinary
appear on both Greenhouse and Lever; Papaya Global appears on both Comeet and Greenhouse).
Both rows are kept intentionally — the pipeline dedupes by job title + company at digest time,
not by dropping rows here.

## The pipeline (code)

`pipeline/` is a zero-dependency (stdlib-only) Python package:
- `http.py` — GET/POST JSON with retry/backoff.
- `fetchers.py` — one normalizer per ATS platform → common job shape.
- `israel.py` — deterministic Israel-location filter (country code, then place-name scan).
- `seniority.py` — keyword pre-filter + `claude -p` fallback for ambiguous titles only.
- `store.py` — SQLite seen-store (across-day dedup + cross-platform merge) + LLM cache.
- `digest.py` — HTML/plaintext digest with an auditable run summary.
- `run.py` — orchestrator. `python -m pipeline.run` produces `out/digest-<date>.{html,txt,json}`
  (produce-only: never publishes). `verify_company.py` and `probe_ats.py` are the
  live-verification research tools.

Scheduling and the supporting cloud workflows (coverage auto-expansion, stale-board self-heal,
unreachable-endpoint retry, scrape-cache refresh) are documented in `SCHEDULING.md`.

Deliberately excluded as scrape sources: Glassdoor and LinkedIn Jobs. Both aggressively block
automated access and enforce their ToS against scrapers, so they'd be fragile and legally risky
— the opposite of "deterministic." They're also aggregators, so anything posted there already
exists on the company's own career site, which is what this pipeline targets directly.
