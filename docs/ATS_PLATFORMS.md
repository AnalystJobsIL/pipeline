# The company registry and the ATS platforms

Moved verbatim out of `README.md` on 2026-08-23 — it is reference material for whoever is
adding a company or a platform, not the first thing a visitor should read. The rules that
govern *writing* to this file (the verdict log, the single-writer rule, the activation
gates) are in `ARCHITECTURE.md` §2; the recipes for adding a row or a platform safely are
in `ARCHITECTURE.md` §6. **Never hand-write an unverified row** — §6 has the one-liner that
verifies an endpoint before you add it.

Lane: `registry` owns `companies.csv`; `ats-fetch` owns the fetchers behind these patterns.
`docs` owns this page and re-verified every pattern below against a live row on 2026-08-27.

## companies.csv

The editable company list. Columns:

- `company_name` — display name
- `ats_platform` — **exactly one of the keys in `pipeline/fetchers.py`'s `FETCHERS` map**;
  `fetch_company` raises `ValueError: unknown ats_platform` on anything else, so a value from
  a stale list breaks the row. Today (re-derive with
  `python -c "from pipeline.fetchers import FETCHERS; print(sorted(FETCHERS))"`):
  `ashby`, `bamboohr`, `breezy`, `comeet`, `custom_json`, `eightfold`, `greenhouse`,
  `jobvite`, `lever`, `microsoft`, `oraclehcm`, `phenom`, `recruitee`, `smartrecruiters`,
  `successfactors`, `workable`, `workday` — plus the two pseudo-platforms `scrape` (no public
  API; read from the rendered careers page) and `discovery` (the synthetic row that reads the
  LinkedIn/Indeed/Telegram cache). **`jazzhr` was retired on 2026-08-26** and this list carried
  it until 2026-08-27; `eightfold`, `phenom`, `successfactors` and `jobvite` were missing from
  it while having live rows. `microsoft` is an alias key served by `fetch_eightfold`.
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
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs`. **The EU region has
  the same JSON API** at `https://boards.eu.greenhouse.io/v1/boards/{token}/jobs` — verified
  2026-08-27, Unframe `unframe` returns 32 postings on both hosts, and `fetch_greenhouse`
  reads it unmodified. What does not exist is `boards-api.eu.greenhouse.io` (NXDOMAIN), which
  is the form an earlier note tested before concluding there was no EU API.
- Lever: `https://api.lever.co/v0/postings/{token}?mode=json`. Some companies are on
  `api.eu.lever.co`; **no code picks between them**, the row's `api_url` has to name the right
  host, and Mobileye's is currently failing with a network error against the EU host.
- SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/{token}/postings`
- Recruitee: `https://{token}.recruitee.com/api/offers/`
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{token}`
- Workable: `https://apply.workable.com/api/v1/widget/accounts/{token}?details=true` (21 rows)
- BambooHR: `https://{token}.bamboohr.com/careers/list` (10 rows)
- Breezy: `https://{token}.breezy.hr/json` (5 rows)
- Oracle HCM: `https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber={site}` (5 rows)
- Eightfold: `https://{careers-host}/api/pcsx/search?domain={domain}` (2 rows, incl. `microsoft`)
- SuccessFactors: no JSON at all — the `/tile-search-results/` HTML fragment is parsed (2 rows)
- Jobvite: `https://jobs.jobvite.com/{token}/search` (1 row)
- Phenom: `https://{careers-host}/widgets` (1 row)
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

