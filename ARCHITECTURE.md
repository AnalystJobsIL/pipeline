# Architecture — how jobs get pulled, verified, and delivered

This is the **durable system model**: how the thing works and the rules that cost real data
to learn. It does not describe what happened last night — that is `HANDOFF.md`.

| doc | holds | changes |
|---|---|---|
| `CLAUDE.md` | the 2-minute orientation, loaded automatically | rarely |
| **this file** | the model, the rules, the runbooks | when behaviour changes |
| `HANDOFF.md` | current state, watch list, unclaimed work | every session |
| `docs/BACKLOG.md` | known gaps that outlive a session | when one is found or closed |
| `docs/AGENT_BRIEF.md` | the lane table: who may write which file | when the lanes change |
| `docs/MODULES.md` | every module, and whether it is live | when a module is added |
| `docs/sessions/` | what past sessions found, in their own words | append-only |

**Every section below is tagged with the lane that owns it** (`docs/AGENT_BRIEF.md` has the
full table). A tag means: that lane may change the behaviour this section describes, and
must update the section in the same commit. `shared` means the section describes plumbing
every lane imports and no lane owns — changing it is a report-it-loudly event.

## The whole system on one screen

```
  ┌ 1 INTAKE ────────────────────────────────────────────────── lane: discovery ┐
  │  discovery_daily.py    LinkedIn + Indeed via Bright Data ─┐                  │
  │  discovery_telegram.py public t.me/s channel previews    ─┼─▶ discovered_cache.json
  │                        new employer names                ─┴─▶ research_companies.json
  └───────────────────────────────────────────────────────────── 05:00, in-digest ┘
                   │
  ┌ 2 REGISTRY ───────────────────────────────────────────────── lane: registry ┐
  │  auto_expand → resolve_deep → resolve_llm   08:00 / 20:00                    │
  │  listing_hunt · repair_* · crack_walled · deep_validate · triage_dark        │
  │  every row carries a dated verdict in `notes` (§2)      ──▶ companies.csv    │
  └────────────────────────────────────── ~1,200 rows · run check_invariants.py for today's split ──┘
                   │
  ┌ 3 FETCH ──────────────────────────── lanes: ats-fetch (API) · scraper (page) ┐
  │  pipeline/fetchers.py  16 platforms, 433 API rows      live, every digest    │
  │  scrape_universal.py   5 escalating strategies, 412 rows (+1 discovery row)  │
  │  refresh_scrape_cache.py 00:00                          ──▶ scraped_cache.json
  └──────────────────────────────────────────────────────────────────────────────┘
                   │
  ┌ 4 ENRICH ─────────────────────────── lanes: jd-text · company-intel ────────┐
  │  pipeline/jdfill.py + enrich_*_jd.py   a description for every relevant role │
  │  pipeline/firmographics.py             sector / stage / size / founded       │
  │                                        ──▶ cloud_state/firmographics.json    │
  └──────────────────────────────────────────────────────────────────────────────┘
                   │
  ┌ 5 CLASSIFY ───────────────────────────────────────────────── lane: classifier┐
  │  pipeline/israel.py    is this role in Israel?                               │
  │  pipeline/seniority.py keyword rules, then `claude -p` for the ambiguous      │
  │                        judgments cached per company|title ──▶ seen.db matched │
  └──────────────────────────────────────────────────────────────────────────────┘
                   │
  ┌ 6 RENDER ─────────────────────────────────────────────────── lane: render ───┐
  │  pipeline/digest.py + roleprofile.py   the board, the archive, the email,     │
  │                                        every tag on a role card              │
  └──────────────────────────────────────────────────────────────────────────────┘
                   │
  ┌ 7 DELIVER ────────────────────────────────────────────────── lane: infra ────┐
  │  commit state (merge_csv_rows / merge_json_cache) → publish board →           │
  │  AnalystJobsIL/board · digest issue → AnalystJobsIL/inbox → email 05:45/08:30 │
  └──────────────────────────────────────────────────────────────────────────────┘
```

Counts are from the working tree on 2026-08-23; re-derive them with the snippets in §5c
rather than trusting this line.

## 0. Start here: what the user actually receives
*lane: `docs` — every lane must keep it true*

Two deliverables, both produced by the **digest run** (the 05:00 UTC GitHub Actions
workflow `daily-digest.yml` — everything in this system runs as GitHub Actions cron jobs,
no server):

1. **A daily email** — only roles **new in the last 48h**, grouped by company. Delivery is
   keyless: the digest is posted as a GitHub issue in the *private* repo
   `AnalystJobsIL/inbox` with a `cc @owner` mention, and GitHub emails the mention
   (workflow `digest-email.yml` there; deduped by content hash).
2. **The job board** — a rolling **2-week** searchable page, `docs/index.html`, published
   to the public repo `AnalystJobsIL/board` → https://analystjobsil.github.io/board/.

**Per-company caps** (`pipeline/run.py`): the email shows at most **3** roles per company,
the board **8** — so "only one Wix role arrived" can be the cap, not a coverage gap.

**What qualifies as a role** (the actual product decision, implemented in
`pipeline/seniority.py`): experienced (**~3+ years**) data-analysis work — data/BI/product/
marketing analytics, analytics leadership. **The title does not matter**: a "Data Scientist"
posting counts if the work is really product/business analytics. **Out**: core ML/model
building, data engineering, software engineering, finance/FP&A, security/SOC, and
junior/intern/entry-level. Deterministic keyword rules decide the clear cases; ambiguous
titles go to `claude -p`, whose YES/NO **role judgment** is cached per `company|title` in
`cloud_state/seen.db` (distinct from a row's coverage **verdict**, §2).

**Vocabulary** (used consistently below):
- **the digest** = the 05:00 run that produces both the email and the board.
- **the job board** = our published 2-week page. **a careers board** = a company's own ATS
  listing. Never abbreviate either to "the board" alone.
- **role judgment** = classifier YES/NO on one posting. **row verdict** = the dated
  coverage note on a `companies.csv` row.
- **parked** = `active=false` with a verdict explaining why; parked rows are still
  re-checked (§2), never forgotten.
- **JD** = job description text. **discovery net** = the LinkedIn/Indeed/Telegram sweeps.

**Repo layout note:** `pipeline/` holds the digest-run library (`run.py`, `fetchers.py`,
`seniority.py`, `israel.py`, `store.py`, `digest.py`, `health.py`, `recruiters.py`).
**Every other script named in this document lives at the repo root.**

### Run it locally without side effects

**Two traps:** several root scripts have no `if __name__ == "__main__"` guard, so *importing*
them executes them (`merge_research.py` rewrites `research_companies.json` on import).
And **25 of the 77 workflow steps carry `continue-on-error: true`** (counted 2026-08-24 by
`docs/check_docs.py`, which fails if this sentence and the workflows disagree), so a hard
failure in an audit/hunt step still shows a green run — check the step log, not the badge.

```bash
python -m pipeline.run --only "Fiverr,Wix" --no-llm    # produce-only: NEVER emails/publishes
                                                      # scoped runs write out/docs-preview/,
                                                      # never the published docs/
python -m pipeline.run --db /tmp/scratch.db            # don't touch the real seen-store
python scrape_universal.py "Company" "https://…/careers"   # test extraction on one page
python audit_empty_rows.py                             # dry-run (add --apply to write)
```
`pipeline.run` only writes `out/digest-<date>.{html,txt,json}` — emailing and board
publishing are separate workflow steps, so a local run cannot notify anyone. Most tools
follow the same convention: **dry-run by default, `--apply` to write**. Useful env vars:
`SCRAPE_LLM=1` (LLM extraction fallback), `SCRAPE_ASSUME_IL=1` (accept page-level Israel
signal), `SCRAPE_VIA_UNLOCKER=1` (**spends Bright Data**: residential fetch of a page the
plain fetch could not read), `SCRAPE_WORKERS` / `SCRAPE_COMPANY_BUDGET_S` /
`SCRAPE_REFRESH_TIME_BUDGET_MIN` (refresh pool size / per-company seconds / minutes before
the tail is carried over), `SCRAPE_CACHE_OUT` / `SCRAPE_ROT_OUT` / `SCRAPE_STAGES_OUT`
(redirect the refresh's three outputs), `LLM_RESOLVE_CAP`, `JD_ENRICH_CAP`/`JD_ENRICH_BD_CAP`, `SERPAPI_KEY`,
`BRIGHTDATA_API_KEY`/`BRIGHTDATA_ZONE`, `CLAUDE_CODE_OAUTH_TOKEN` (subscription OAuth, not
an API key). Local secrets live in the gitignored `secrets.env`.

### The common job shape

Every fetcher and scraper must return a list of dicts in exactly this shape — this is the
contract that makes sources interchangeable:

```python
{"company": "Fiverr", "title": "Senior Business Data Analyst",
 "location": "Tel Aviv, Israel", "country_code": "IL",       # "" if unknown; israel.py falls back to text
 "url": "https://…/apply/12345", "posted_date": "2026-08-21",  # ISO; "" if unknown
 "ats_platform": "comeet", "job_id": "23.F66",                 # job_id must be stable per posting
 "description": "About the role… Requirements…"}               # plain text, ≤6000 chars, "" allowed
```

One-screen mental model:

```
 SOURCES                     NORMALIZE            CLASSIFY              DELIVER
 ───────                     ─────────            ────────              ───────
 native ATS APIs  ──┐
 (comeet/greenhouse/│
  lever/ashby/      │        pipeline/fetchers.py  pipeline/seniority.py  digest email (issue relay)
  workday/oraclehcm…)│  ──►  one normalizer per ──► keyword layer +   ──► rolling 2-week board
 scraped listings ──┤        source → common job    claude -p for         (docs/index.html →
 (scraped_cache)    │        shape → israel.py      ambiguous titles      AnalystJobsIL/board)
 discovery nets   ──┘        location filter        (verdict cached
 (LinkedIn/Indeed via                               per company|title)
  Bright Data, Telegram
  channels)
```

Everything below exists to answer one question honestly: **"which Israeli-relevant
companies have open roles right now?"** — with a verifiable trail for every claim,
including the claim "none".

## 1. Coverage tiers (how a company's jobs are read)
*lanes: `ats-fetch` (tier 1) · `scraper` (tier 2) · `discovery` (tier 3)*

1. **Native ATS fetchers** — `pipeline/fetchers.py` `FETCHERS` map. A `companies.csv` row
   whose `ats_platform` names a platform is fetched live every digest run via its public
   JSON API, sequentially, ~1 s a row (median 0.5 s; `oraclehcm` 4–15 s, the slowest
   single row a 22 s greenhouse): **436 API rows on
   2026-08-24** — comeet 123, greenhouse 104, workday 66, ashby 50, lever 24, workable 22,
   smartrecruiters 16, bamboohr 11, recruitee 8, breezy 5, oraclehcm 4, jazzhr 1,
   custom_json 1, microsoft 1 — beside 425 scrape rows and the 1 discovery row (862 active).
   Re-derive, never trust:
   `python -c "import csv,collections;r=[x for x in csv.DictReader(open('companies.csv',encoding='utf-8')) if x['active']=='true'];print(len(r),collections.Counter(x['ats_platform'] for x in r).most_common())"`.
   Adding a platform = one `fetch_x(row)` normalizer + a map entry (§6). **The loop is
   sequential and it is most of the pipeline step's time:** the per-row fetch times sum to
   7.0–7.2 min (421 s / 434 s over 436 rows, two censuses on 2026-08-24, the census
   script's own 3 s Workday pacing excluded), i.e. ~69 % of the "Run the pipeline" step
   (10 m 14 s) and ~26 % of the 27-minute digest job (05:42→06:09; the 05:00 cron queued
   42 min). Parallelising it lives in `pipeline/run.py` (`infra`, `docs/BACKLOG.md` 83);
   Workday's tolerance for parallel POSTs is unmeasured (one burst of 25 at 10 threads
   answered 200; one earlier burst answered 500 on 14 tenants and never reproduced).
2. **Scrape rows** (`ats_platform=scrape`; **425 active on 2026-08-24**, re-derive with the
   one-liner above) — `api_url` holds a LISTINGS page URL. `refresh_scrape_cache.py`
   (00:00 UTC, `scrape-refresh.yml`, step `Refresh the scrape cache`, with `SCRAPE_LLM=1`
   and `SCRAPE_VIA_UNLOCKER=1`) renders every row with `scrape_universal.py` in a process
   pool (`SCRAPE_WORKERS`, default `min(4, cpus)`; one Playwright per process, `spawn` on
   every platform) and rewrites `scraped_cache.json`; the digest reads the cache via
   `fetch_scrape`. `scrape_universal` is two halves: `_render(url)`, the only Playwright
   touchpoint (page state, XHR bodies, rendered links, HTML, the main document's HTTP
   status — or an error code when navigation failed), and `_extract(...)`, a pure function
   of that bundle — testable offline — that escalates through **5 strategies, the first that
   yields wins** (one exception: fewer than 3 structured hits may be a "featured posting"
   widget, so the DOM pass still runs and is unioned in as `structured+dom`): structured JSON (JSON-LD / `__NEXT_DATA__` / captured XHR bodies) →
   rendered-DOM job links with an Israel token near the title → repeated heading /
   class-hinted card groups → position-links (N same-prefix links, each page fetched) →
   **LLM extraction** (`SCRAPE_LLM=1`: Claude reads the visible text, returns JSON; gated
   on jobs-signals). `scrape_result()` returns the jobs plus `status` ∈ `ok` / `empty` /
   `error` and the winning strategy; `scrape()` — what every other lane calls — is its
   list-only wrapper and never raises. One company gets `SCRAPE_COMPANY_BUDGET_S` (150 s)
   of wall clock; every network wait is clamped to what is left. Measured 2026-08-24: the
   last sequential cloud run (`gh run list -R AnalystJobsIL/pipeline --workflow
   scrape-refresh.yml`, then `gh run view 32677334301 --log`) did 428 rows in 111.6 min,
   median 11.4 s, max 368 s (Ford); the first pooled run, local, LLM and unlocker off, did
   425 rows in 37 min, median 17 s, p95 37 s, max 103 s. Local scoped runs write nothing to
   the repo — `python refresh_scrape_cache.py --only "Wix,Fiverr"` (add `--apply` to merge
   the hits into `scraped_cache.json`, or `SCRAPE_CACHE_OUT=<file>` to merge elsewhere;
   `--dry-run` for every row) — but they still render live pages, so with `SCRAPE_LLM` or
   `SCRAPE_VIA_UNLOCKER` set (`secrets.env`!) they still spend.
3. **Discovery nets** — `discovery_daily.py` (Bright Data LinkedIn/Indeed keyword sweeps)
   and `discovery_telegram.py` (public t.me/s channel previews) write
   `discovered_cache.json`, read by `fetch_discovery`. This is the safety net for
   companies with no readable board — and the intake that feeds NEW companies into
   resolution (below).

Full `FETCHERS` map — **18 keys, 16 platforms** (this line said 16 keys until 2026-08-24;
`python -c "from pipeline.fetchers import FETCHERS;print(len(FETCHERS),sorted(FETCHERS))"`):
comeet, greenhouse, lever, smartrecruiters, recruitee, ashby, workday, oraclehcm,
custom_json (Amazon), jazzhr (returns `[]` by design — no public API), workable, breezy,
bamboohr, **eightfold** (the `/api/pcsx/search` endpoint; `microsoft` is the same fetcher
under the name its rows have always carried, because the store keys roles on
`{ats_platform}:{job_id}`), **phenom** (`POST /widgets`), plus the pseudo-platforms `scrape`
and `discovery`. Five fetchers ask the board for Israel itself and carry
`israel_scoped = True` — workday, eightfold/microsoft, phenom, custom_json — which §5a
explains.

Support policy: a platform seen 3+ times gets native support; otherwise the scraper's
strategies carry it. **Eightfold and Phenom now have validated native fetchers** (2026-08-24:
`careers.qualcomm.com` → `count=36`, 31–36 roles by requisition per call (its pager is
unstable), where its scrape row is verified at 8; `careers.gehealthcare.com` → 20, where its active scrape row reports 0) **but no active
row uses them yet** — the conversion is a `companies.csv` write and sits in `docs/BACKLOG.md`
for `registry`. iCIMS (7 rows), SuccessFactors (7) and Avature (2) have none; `python
registry_health.py --ats` is the queue.

## 1a. Intake — the discovery net
*lane: `discovery`*

Tier 3 of §1, written out. Intake is the only step that can add a company the registry has
never heard of, and one pass feeds **two** funnels:

```
  discovery_daily.py     LinkedIn  keyless guest endpoint, Unlocker fallback ─┐
                         Workable  one ATS, every tenant, keyless            ─┤ jobs
                         Indeed    Web Unlocker                              ─┼──▶ discovered_cache.json
                         LinkedIn-targeted  BD dataset, per broken-board co  ─┤    (21-day TTL at READ)
  discovery_telegram.py  6 public t.me/s feeds, keyless                      ─┘
                                                                              │
                         every employer name not already in ─────────────────┴──▶ research_companies.json
                         companies.csv                                             drained by auto_expand (§3)
```

The jobs funnel is a safety net — it publishes roles at companies whose own board we cannot
read. **The names funnel is the point of this stage**: it is how `companies.csv` grows, and
it is why a feed with almost no analyst roles in it can still be worth reading.

**Judge every source by NEW COMPANIES PER RUN, not by records or jobs.** A source can be
alive, inside budget and completely useless at once — the LinkedIn sweep returned **0 new
companies** while its record count looked healthy, and nothing printed the number that would
have shown it. Each source now prints its own, and a LinkedIn sweep yielding zero says so:

```
[yield] linkedin: 364 employers -> 182 NEW companies
[yield] workable: 11 employers -> 7 NEW companies
```

**`linkedin-targeted` is not a discovery source.** It asks only about companies already in
`companies.csv` whose board returns zero, so it can almost never return an unknown employer.
It is *backfill for known-broken rows* and lives here for historical reasons — worth keeping
(it found roles at 15 active companies whose own board reports 0), never counted towards
discovery, and the first thing to cut if the Bright Data budget binds.

### The five live sources

Costs and counts are the 2026-08-23 measurements; re-derive with
`python -c "import json;print(json.load(open('cloud_state/source_health.json')))"`.

| source | how it is read | key? | measured |
|---|---|---|---|
| `linkedin` | **the discovery source.** `linkedin.com/jobs/search`, 9 keywords × (national + 2 peripheral-city windows: Be'er Sheva, Haifa — city queries free-only), `f_TPR` past week. KEYLESS guest endpoint first, Web Unlocker only where blocked | no* | 364 employers → 182 new companies, 7 credits, 113s |
| `workable` | `jobs.workable.com/api/v1/jobs?location=Israel` — one ATS, EVERY tenant. The only source returning the employer's own website | no | 20 rows → 11 kept, 11/11 with a real careers lead |
| `indeed` | `il.indeed.com/jobs` through the Web Unlocker; parsed from the `mosaic-provider-jobcards` blob | yes | 58 raw → 46 kept |
| `telegram` | public `t.me/s/<channel>` previews — no bot, no account, no quota | no | 6 channels, 16–18 of 20 parsed each |
| `linkedin-targeted` | BD dataset, one input per broken-board company, scoped by the **`company` field**. Backfill, **NOT discovery** | yes | 88 companies → 67 records, 57 on-target |

\* the paid path is a fallback; `SOURCE_PATH` records which one served, and the run warns if
everything is suddenly billed.

**Five things about this table cost real coverage to learn**, and the workings are in
`docs/sessions/2026-08-24-discovery.md`:

1. **The two LinkedIn endpoints have different ceilings.** The paid page caps at ~80 jobs per
   query; the keyless guest endpoint goes **200+ deep**. Bounding the free walk with the paid
   measurement shipped 10 jobs out of a 201-job pool.
2. **`company` is a FIELD, not text in the keyword.** Concatenated into `keyword`, the
   targeted sweep returned 160 records and **0** on-target; in its own field, 25 records and 22.
3. **Width beats one clever query.** The pool is per QUERY, so a boolean
   `("data analyst" OR …)` buys one window instead of nine — 10 new companies against 76.
   If yield falls, add a keyword; never a boolean, never more paid pages.
4. **The Indeed dataset is dead** (`gd_l4dx9j9sscpvs7no2`, `rate_limit` on every input for
   five days). Do not re-enable it; Indeed goes through the Unlocker.
5. **A city location is its own query window** — the per-query cap applies to geography too.
   Measured against the national window: Be'er Sheva 14 of 20 jobs unseen nationally, Haifa
   11 of 20; Jerusalem 3 of 31 and Herzliya **0 of 20** (Tel Aviv metro is already inside the
   Tel Aviv-weighted national window — metro cities buy nothing). City queries pass a paid
   budget of ZERO, so they structurally cannot bill: the paid worst case stays the national
   sweep's ~18 whatever LinkedIn does to the runner.

### What it costs, and what stops it costing more

**One Bright Data pool: 5,000 credits/month**, shared by Web Unlocker + SERP + Web Scraper
API at one credit per request or record, resetting on the 1st with no rollover
(`docs.brightdata.com/general/account/billing-and-pricing/free-tier`, verified 2026-08-23).
Per MONTH, not per day.

| | credits/day |
|---|---|
| LinkedIn breadth — keyless guest endpoint, 9 keywords × 50 pages + 18 city queries (free-only) | **~7** (≤18 if LinkedIn blocks it outright; the city product cannot bill) |
| Workable — keyless, all tenants | **0** |
| Indeed — Unlocker, 5 queries + retries | 6 |
| LinkedIn targeted backfill — dataset, per RECORD | 67 |
| everything else (JD enrichment, rescue, crack, repair) | ~44 |
| **total before SERP** | **~124** → ~3,700/month, inside the free pool |

Three of the five sources need no key at all, which is why `main()` does **not** return early
when `BRIGHTDATA_API_KEY` is missing — that gate used to sit above the keyless sources *and*
above `sources.record()`, so a rotated secret took the free half dark and silenced the
detector built to notice.

Two mechanisms keep this honest, and both exist because the number was wrong before:

- **`report_bd_spend()`** prints the whole pool every run and projects month-end with a
  dollar figure, warning past 80%. Counting only dataset records under-reported 4,106 as
  2,989. `/customer/balance` is 403 for this token, so the figure is reconstructed from
  `datasets/v3/snapshots` + `zone/cost`; an unreadable or unrecognised reply reads as
  **unknown**, never as zero.
- **`plan_spend()`** pro-rates what is left over the days left in the month. Breadth is never
  throttled (per-request, usually free); the per-record backfill absorbs a tight month and is
  skipped entirely when nothing is left.

**The largest uncontrolled spender is not this layer.** `DEEP_BD_SEARCH_CAP` reads like a
daily ceiling of 150 and is per-PROCESS — six scripts import `google_via_unlocker` in
processes of their own — so the real ceiling is ~450 credits on a weekday and ~750 at the
weekend. `docs/BACKLOG.md` item 6.

*Full workings — the per-endpoint billing model, the depth/recency measurements, the
month-end cost table and every rejected alternative — are in
`docs/sessions/2026-08-24-discovery.md`.*

### Telegram channels

`CHANNELS` in `discovery_telegram.py`, all secrethunter-format so `parse_post` is
deterministic and an unparseable post is **skipped and counted, never guessed**. Probe before
adding — the number that decides is how many of the ~20 front-page messages parse:

```bash
python -c "
import discovery_telegram as d
p=d._fetch('https://t.me/s/CHANNEL'); m=list(d._MSG.finditer(p))
print(len(m),'msgs',sum(1 for x in m if d.parse_post(d._clean_text(x.group('body')),x.group('dt'))),'parsed')"
```

Live: `secretdatajobs` · `secretmarketingjobs` · `secretproductjobs` · `secretcyberjobs` ·
`secretfinancejobs` · `secretsalesjobs` (16–18 of 20 each). Rejected on **relevance**:
`secrethrjobs`, `secretqajobs`. Rejected for having no public `t.me/s` preview at all:
`secretbizdevjobs`, `secretanalystjobs`, `secretdesignjobs`, `secretstudentjobs`,
`secretjobs`. Rejected as unstructured (2026-08-21): `israjobs`, `hightechforolims`,
`jobs_SQL`.

Widening intake is cheap **because the resolver queue is not the bottleneck** — measured
2026-08-23, `auto_expand`'s drainable backlog was 77 against a limit of 200 per run, twice a
day. Check that before assuming otherwise (command in `docs/sessions/2026-08-24-discovery.md`).
### What intake refuses, and where each gate lives

A name that gets past here becomes a `companies.csv` row two `auto_expand` runs later, so
this is the cheapest place in the system to say no. Both bridges apply the same three:

| gate | module | rejects |
|---|---|---|
| already known | `pipeline/companies.py` (`load_companies`) | any name already in the registry, active or parked |
| `looks_like_junk` | `pipeline/firmographics.py` | a leaked job title / category / team phrase ("Data researcher - Navina", "AppSec") |
| `is_recruiter` | `pipeline/recruiters.py` | staffing and placement firms, which re-post dozens of clients' roles |

Job-level exclusion happens later and separately, in `fetchers.fetch_discovery`: the 21-day
TTL, `is_recruiter` again (a discovery job carries the real employer name, so it bypasses
the row-level check in `pipeline/run.py`), and `company_identity.url_names_other_company`
for a card whose URL slug names a different employer — 147 board rows were once published
under the wrong company that way.

**A Latin entry in `_CONFIRMED` does not cover the Hebrew spelling.** One live Indeed query
on 2026-08-23 returned `קומבלק איי.טי. בע"מ` (Comblack IT — `comblack` had been on the list
since 2026-08-17) and `חברה דיסקרטית` ("discreet company", the Hebrew of the `confidential`
entry). Both passed `is_recruiter` AND `looks_like_junk` and were one `auto_expand` run from
an active row. Both are in `_HEBREW_MARKERS` now, guarded by
`test_a_hebrew_spelling_does_not_walk_past_a_latin_recruiter_entry`. **When you add a name
to `_CONFIRMED`, add its Hebrew form in the same commit** — the registry carries agencies
under both.

There is deliberately **no junior/student filter on the Telegram path**, though
`discovery_daily.py` has one (`_JUNIOR_HE`). `secretdatajobs` really does carry them ("Data
analyst (student position)", Upstream Security, 2026-08-23) but `seniority.classify` rejects
every one on the free keyword path — `reject / keyword / junior-intern-entry-level`, no LLM
call — while the post still contributes its employer to the names funnel. A second filter
here would cost coverage and buy nothing.

### Three rules this layer costs data to re-learn

1. **Merge `discovered_cache.json`, never truncate it.** `discovery_daily.py` runs first and
   `discovery_telegram.py` second, into the same file. A truncating write on 2026-08-21
   deleted every Telegram-sourced job — **79 verified roles, unrecoverable**, because the
   Telegram watermark in `cloud_state/telegram_seen.json` had already advanced past them.
   Both writers merge by `(company, title)` with this run's copy winning, and prune past the
   21-day TTL.
2. **Record source liveness BEFORE any early return.** `pipeline/sources.py` exists to
   answer one question — did this source return anything today — and its whole value is that
   a **zero gets recorded as a zero**. `discovery_telegram.main()` used to `return` on an
   empty scan with the `sources.record` call below that return, so Telegram was invisible to
   it: on 2026-08-23 `cloud_state/source_health.json` held `indeed` / `linkedin` /
   `linkedin-targeted` and **no `telegram` key at all**, while `discovered_cache.json` held
   104 telegram-sourced jobs. Guarded by
   `test_telegram_records_source_health_before_its_early_return`. Corollary: count what the
   source PRODUCED (posts parsed), not what survived dedup — a healthy channel repeating a
   role we already hold would report 0 and read as dead. Every `per_source` entry is raw
   records for the same reason; the kept count is printed beside it.
3. **A fixed prefix over a re-sorted list is not a sample, it is a blind spot.**
   `_targeted_inputs` took `unresolved[:20]`, and `cloud_state/stale.json` is rebuilt every
   digest in `companies.csv` row order (`pipeline/health.py`'s `record` iterates
   `results.items()`), so the **same 20 names went to Bright Data every day and the other 90
   of 110 were never searched once**. The window now advances by day-of-year — same records
   per run, all 88 targetable companies covered in 5 days. It also skips
   `misconfig-scrape-on-ats` (22 of the 110): that reason is a warning about the ROW's shape,
   not a broken board, and the digest reads those companies fine every morning. Guarded by
   `test_targeted_discovery_window_rotates_over_every_stale_company`.

### Known limitations of this layer

- **The seed URL a bridge can offer is always an aggregator**, because a discovered job's
  `url` IS its posting on LinkedIn / Indeed / secrethunter — 206 of 1,233 queue entries and
  45 registry rows carry one. `secrethunter.io/jobz/<id>` cannot be followed to the real
  posting: it is a 33,495-byte JS shell, byte-identical for every job id. The fix belongs to
  `registry` (`auto_expand.py`) and is item 2 in `docs/BACKLOG.md`.
- **A single Telegram channel dying is not visible in the mail** — one aggregate `telegram`
  key, because `sources.stale()` has one 2-day threshold for every key. Per-channel counts
  are in the step log. `docs/BACKLOG.md` item 3.
- The **breadth** sweep is now the only unscoped LinkedIn query, and unscoped means
  LinkedIn decides what "relevant" is. Before the `company` fix the targeted sweep was
  effectively a second breadth sweep, and it did find 17 employers we had never seen
  (J&J MedTech, Vishay, IAI, Ben-Gurion University …). That accidental breadth is gone;
  it was replaced deliberately with two more keywords on the breadth sweep, and whether
  that trade is net-positive has NOT been measured over more than one run.

## 2. Row lifecycle — every company carries a dated, evidence-based verdict
*lane: `registry` — one session at a time. The rules in this section are `shared`: every
lane that writes `companies.csv` obeys them.*

### The registry in two minutes

Read this block, run the one command, and stop. Everything below is the long version.

```bash
python registry_health.py        # read-only: census, who re-checks what, which rungs work
```

**What the registry is.** One row per company in `companies.csv`
(`company_name, ats_platform, token, api_url, active, notes`). `active=true` means the digest
fetches it every morning. For API rows `api_url` is the endpoint; for scrape rows it is the
**listings page URL**. `notes` is an append-log: each tool appends ` | <tool> <date>:
<finding>` and strips only its own previous stamp, so a row accumulates one current verdict
per tool. **Never write that cell by hand — use `pipeline/notes.py`.** Three real rows, one
of each kind:

```csv
Fiverr,comeet,60.002,https://www.comeet.com/careers-api/2.0/company/60.002/positions?token=62188018812631018862C4188,true,
Google Israel,scrape,,https://www.google.com/about/careers/applications/jobs/results/?location=Israel,true,re-audit 2026-08-22: user-found listing URL; heading-group scrape verified 20 IL (page 1)
Imagindairy,scrape,https://www.imagindairy.com/careers,https://imagindairy.com/careers/,false,"chrome-verified 2026-08-22: careers live, CURRENT OPENINGS empty (true 0) - monitored candidate"
```

**Five questions, five answers:**

| you want to know | answer | where |
|---|---|---|
| why isn't company X in my email? | read its row's `notes` — it names the tool, the date and the finding | §5b has the ordered runbook |
| what re-checks a parked row? | run the command above; it prints the pool of every scheduled tool, derived from that tool's own filter. **A row is usually claimed by several** | "the ownership matrix" |
| can I just flip a row to `active=true`? | **No.** The gates live in `pipeline/identity_gate` (four, one per caller shape -- the `GATE_CALLERS` table at the top of that module); `company_identity`'s primitives alone are inert on a walled ATS | "The activation rule" |
| a company vanished from the file — why? | `python registry_health.py` diffs against `cloud_state/registry_census.json` and prints every vanished name with its last note. **Deleting a row is not durable**; park it | "Never DELETE a row" |
| which ATS should we build a fetcher for? | `python registry_health.py --ats` — it separates `BUILD` (no fetcher) from `WIRE` (fetcher exists, the row just needs its tenant cracked) | §1's support policy |

**The identity problem is the whole difficulty of this lane.** "There are Israel jobs on this
page" is not "these are THIS company's jobs", and all three gates below are inert on a
walled/multi-tenant ATS. `pipeline/identity_gate.py` answers it; every registry writer imports
it at module level — see "The activation rule". **Never count those write paths by hand:**
every hand-written list of them here has been wrong, including one written to prevent a
miscount. Derive it —

```bash
python -m pytest tests/test_registry.py -k every_registry_writer   # asserts all of them are gated
python tools/mutate.py --all                                       # asserts the gates are real
```

— because `test_every_registry_writer_consults_an_identity_predicate` finds writers in **both**
source shapes: `fr[3] = …` / `fr[4] = "true"`, and the whole-row literal
`[name, plat, tok, api, "true", note]`, which the AST guard in `tests/test_units.py` cannot
see (a list literal has no subscript assignment). `apply_resolved.py` is gated upstream
instead, in `resolve_llm._verify`: it cannot activate a row, but can re-point an active one.
How each rule below was got wrong is in `docs/sessions/2026-08-24-registry.md`; this section
states what is true.

**Before you change any row filter:** re-run the command above and read the `OWNED BY
NOTHING` line. A row owned by no recurring job is coverage that silently never happens — the
single most common way this codebase breaks (§8). Taxonomy of verdicts:

| state | active | meaning | who re-checks it |
|---|---|---|---|
| (verified board) | true | endpoint/listing verified to return real jobs | every digest / daily refresh |
| `… N/0 IL` (N>0) | true | board healthy, N global roles, none in Israel | every digest — lights up automatically |
| `… 0/0 IL` | true | zero of zero: **may be a dead token/moved board**, `pipeline/health.py` calls this `empty-board`. Discriminator: comeet returns HTTP **400** for dead creds, **200 + `[]`** for a live empty board | digest → `stale.json` → 06:00 self-heal (5 strikes) |
| `host documented, 0 IL now` | false | walled-ATS host found, extraction unproven | daily probe + hunt |
| `monitored candidate` / `host documented` | false | real page documented, extraction unproven | daily probe + 14-day re-hunt |
| `probe-woken: re-hunt pending` | false | probe saw signals rise; awaiting same-day hunt | that evening's 19:00 hunt (fast-path) |
| `no listing found` / `no ATS detected` | false | full render found nothing parseable | weekly audit + hunt cron |
| `unsupported ATS <x>` | false | ATS known, no extraction path yet. **Run `python registry_health.py --ats`** — it splits `WIRE` (a fetcher exists, the row just needs its tenant cracked) from `BUILD` (no fetcher) and reports which `BUILD` names clear §1's "seen 3+ times" threshold. *(Typing that split into this cell has produced a wrong statement twice; run it.)* | several jobs claim it — run `registry_health.py`, don't trust this cell |
| `domain-dead …` | false | DNS/conn dead (GET-verified, lenient TLS — strict TLS on the scanning machine produced 6 false positives) | re-tested **daily** by `scan_dead_domains` (`_rescannable` defaults to 1d) inside the 05:00 digest, and again by the Sunday audit; **a revived domain clears the flag automatically** |
| `defunct: …` | false | company confirmed shut down/acquired | permanently excluded |
| `alias-of <name>` | false | a SECOND row for a company already scanned at the same board (eBay / eBay Israel) | nobody — **terminal**, and re-opening it republishes every role twice |
| `chrome-verified …` | either | a human-equivalent browser check confirmed the state | as per its class |

Recruiting/staffing agencies are excluded everywhere via `pipeline/recruiters.py`
(`is_recruiter`) — rows, discovery jobs, and resolution queues all check it.

### State transitions (who moves a row, and when)

```
   new name (discovery / manual)
            │  research_companies.json queue
            ▼
   ┌──── auto_expand (08:00/20:00) ────┐   resolve_deep → resolve_llm (capped, else deferred)
   │ resolved+verified │  failed        │
   ▼                   ▼                ▼
 ACTIVE ROW        parked: "scanned; no open" / "unreachable" / "aggregator URL"
   │  ▲                   │
   │  │                   │ listing_hunt 19:00 (finds listings URL, verifies >=1 IL job)
   │  │                   │ crack_walled / deep_validate (on demand)
   │  │                   │ audit_empty_rows (Sun) — re-verifies ALL parked rows
   │  └───────────────────┘
   │
   │ scrape ERRORS for ROT_PARK_DAYS(7) → parked "scrape rotted" → back to listing_hunt
   │ (an EMPTY scrape never parks; a 45-day empty streak only asks triage to re-read)
   │ API fetch fails → stale.json → self-heal 06:00 re-resolves (weekly retry, 5 strikes)
   ▼
 parked: "monitored candidate" (URL known, extraction unproven)
   │  probe_candidates (05:00 daily) sees job/Israel signals rise vs baseline
   ▼  → note becomes "probe-woken: re-hunt pending"
 listing_hunt 19:00 takes the FAST-PATH: scrape the stored URL directly; verified -> ACTIVE
```

Every state except `defunct:` and `domain-dead` is re-checked on some cadence. **A failing
API row keeps `active=true`** (its roles stay on the job board via the failed-company
exemption, §5a) while a rotting *scrape* row is parked, because only parked rows are visible
to the hunt/audit machinery. **Empty is not broken:** `page-empty` rows are ACTIVE, because a
validated working careers page with no openings today is a healthy daily source; only ERRORS
park a row, at 7 days, and a 45-day empty streak just asks triage to re-read the page (it can
tell "no openings" from "openings we fail to extract"). So the ownership matrix below applies
to rows that are still `active=false`.

### The verdict-string rule (read before changing ANY resolver)

Re-check pools are **allowlists of note substrings**, and the allowlist now lives in ONE
place: `pipeline/verdicts.py` (`TOKENS` / `in_pool` / `stale`). Add any new verdict string
to `TOKENS` there. `audit_empty_rows` and `deep_validate` import `in_pool`; the tools that
legitimately want a subset (`crack_walled` → walled ATSes, `probe_candidates` → documented
candidates) narrow it explicitly rather than re-implementing it. **If a string is missing from
`TOKENS`, its coverage is lost with no error anywhere** — hand-maintained copies have already
cost 64 companies two of their pools, and a verdict spelled only in the writing tool
(`bd_rescue.py`'s `scanned via brightdata; …`) stranded 52 rows.
Corollary: a diagnostic verdict must **append** (`base | tool date: finding`), never
replace the cell — overwriting also destroys the `monitored candidate` / `host documented`
tokens that `listing_hunt`'s fast-path keys on.

**The pool is still spelled in THREE places that do not agree** — `verdicts.TOKENS`,
`listing_hunt.HUNT_POOL`, `check_invariants.POOL`. (`registry_health` was a fourth; it now
IMPORTS `HUNT_POOL`, which is the pattern to copy. The inline copies persist only because
`listing_hunt` has no extractable `targets(rows)` yet — `docs/BACKLOG.md`, "One pool predicate
per tool".) A token the inline copies know and `TOKENS` does not makes its rows invisible to
`audit_empty_rows` and `deep_validate`;
`test_the_three_copies_of_the_re_check_pool_still_agree_where_they_are_supposed_to` pins the
gap so it cannot grow while the fix waits. Print the diff, and the rows it costs:

```bash
python -c "from pipeline.verdicts import TOKENS;import check_invariants as ci;t={x.lower() for x in TOKENS};c={x.lower() for x in ci.POOL.split('|') if x and '(' not in x};print('inline, NOT in TOKENS:',sorted(c-t));print('TOKENS, not inline:',sorted(t-c))"
python -c "import csv;from pipeline.verdicts import in_pool;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>=6][1:];n=[x for x in r if 'url-cleared' in x[5].lower() or 'url-flagged' in x[5].lower()];print(len(n),len([x for x in n if not in_pool(x[5])]))"
```

**Append through `pipeline/notes.py`, never by hand.** The cell is capped at 220 chars, and a
writer that makes room by SLICING the base — `(base + " | " + seg)[:220]` or
`base[:220 - len(seg) - 3]` — eats exactly the thing worth keeping, because the newest
segment lives at the END (87 rows once read `dark-triage 2026-08-22: page-emp`, a mode no
downstream filter matches). `notes.append()` drops OLD WHOLE segments until the new one fits;
`notes.replace_own(marker)` re-stamps this tool's own segment and leaves every other tool's
alone. Keep segments SHORT — one full URL is 117 characters and will evict everything else.
`test_every_note_writer_uses_the_append_log_helper` fails on the next hand-rolled trim, and
`test_activation_branches_append_to_the_note_instead_of_replacing_it` on the next whole-CELL
assignment (`fr[5] = <not a call>`), which the helper guard cannot see because a whole-cell
assignment does no hand-rolled trim. Whole-CELL is worst on an **activation** branch: it
deletes the `alias-of` / `domain-dead` token that keeps the row out of the wrong pool and the
`dark-triage` mode that routed it there. Whole-ROW replacement is legitimate where the tool
builds a row from scratch (`retry_unreachable._row_for`, `recheck_suspects`' and
`validate_empty`'s *promote* branches) — re-derive that list rather than trusting it:
`grep -n '\[5\] *=' *.py` takes ten seconds.

Every re-check filter must have a **staleness escape** (`_stale_hunt` 14d, `_revalidatable`
30d, `_recrackable` **1d** — daily, because the ATS host is already documented, so a re-check
is one fetch of a known endpoint rather than a rediscovery). A filter of the form
`"tool-name" not in note` freezes coverage forever — that pattern has been introduced and
removed three times.

### The activation rule (read before flipping any row to active)

"There are Israel jobs on this page" is not "these are THIS company's jobs", and it is not
"this is a page that lists jobs". A row may only be activated when all three hold:

**Acquisitions are DECLARED, not parsed.** A company that legitimately posts under another
tenant (Habana Labs under `intel`, Momentis under `memic`) is a row in
`pipeline/identity_facts.py`'s `DECLARED` table -- tenant tokens plus the evidence -- and the
gates consult that table before any string heuristic. Do not rename the row, invent a note
token (`alias-of` means the OPPOSITE: a duplicate to park), or teach a matcher a new trick;
`python registry_health.py --explain "<name>"` shows whether a row is declared and what the
gates conclude.

1. `pipeline.aggregators.is_aggregator(url)` is false — an aggregator's "similar jobs"
   sidebar is other employers' roles.
2. `pipeline.company_identity.is_foreign(company, url)` is false — FairFly was activated off
   fireflyspace.com (25 Firefly Aerospace roles); `pipeline/identity_gate.py`'s docstring
   lists the rest. For an ATS host the identity is the TENANT SLUG, and a rebrand or
   acquisition looks identical to a mis-resolution — Momentis really does post under `memic`
   — so identity is settled by page content, never by the domain alone. **`weak` is not part
   of this**: `company_identity.verdict()` produces `"weak"` and nothing in the repo reads it
   (`grep -rn '"weak"' --include=*.py .` returns the producing line and one test), so a
   `weak` row — `Phoenix Financial -> phoenixtma.com`, that module's own example of "a real
   company, not the right one" — passes every gate except a page test. Giving `weak` a
   consumer is `pipeline` plumbing: `docs/BACKLOG.md` 43.
3. `pipeline.company_identity.looks_like_a_job_listing_page(url)` is true — `SCRAPE_ASSUME_IL`
   makes every card on the page an Israel role, so a nav menu scores like a board:
   `iai.co.il/solution/research-academy-space` "verified 6 IL" whose titles were "Domain
   Operations" and "Press Releases".

`test_every_activation_path_checks_company_identity` walks the AST of every root script for
`row[4] = "true"` and fails if that module never consults `company_identity`.

**On a walled ATS all three clauses are inert.** The tenant lives in the SUBDOMAIN
(`careers-bancorpbank.icims.com`) and `company_identity.verdict` only checks a tenant in the
PATH, so it returns the blanket `"ats"` — its own docstring defines that as *"we cannot
tell"* — and `is_foreign` reads it as False; the other two say yes, because it IS a real
listings page, just somebody else's. That is what let `Bancor` (Israeli crypto) onto The
Bancorp Bank's board. `pipeline/identity_gate.py` is the answer, in three rules. Both
directions were measured — a tenant veto costs 36 legitimate acquisitions, a mandatory page
read costs 358 path-tenant rows whose endpoints return 0–28 bytes (`docs/BACKLOG.md` 21 and
33) — so **a readable page decides in BOTH directions; the tenant may ADMIT where nothing is
readable, and only an explicit subdomain-tenant mismatch refuses without one.**

1. **`activation_ok(name, api_url, n_jobs, html="")` — a readable page in hand decides,
   either way.** A page the caller already holds beats a re-fetch, so when
   `page_names_company` can read it its answer settles the row in BOTH directions. Only an
   UNREADABLE page (`None` — machine endpoints returning 0–28 bytes, bot walls) falls through
   to `tenant_is_this_company`, which keeps the path-tenant rows activatable. **A page fetch
   is the last resort, not the first.** Zero `n_jobs` is the `empty-board` shape: refused.
2. **`embedded_board_ok(name, token, api_url)` — a board found INSIDE a held page must vouch
   for itself.** For callers that fetch the row's careers page and run `extract_ats` on it,
   the page is evidence about the PAGE, not about whatever board it embeds: a stale shared
   template embed promoted Riskified's Greenhouse onto Cogniteam's row. **A held page can
   REFUSE a board, never ADMIT one** — the extracted tenant must near-equal the company name,
   and "cannot tell" refuses here (unlike in `tenant_is_this_company`) because both callers
   surface the refusal visibly on a row that stays parked with its re-check tokens.
3. **Refusing to ACTIVATE is not enough — the hand-off rule.** A gate that blocks activation
   but still writes the candidate into `api_url` moves the wrong activation to the next night
   under another tool's name, because `host documented` is a `probe_candidates` pool token
   AND `listing_hunt`'s documented fast-path token. `ok_to_write` therefore gates the WRITE
   rather than any one `return`, and requires `page_names_company(...) is True` — unreadable
   is refused too. **Every refusal note ends in a pool token**, so the row is handed to a
   named receiver rather than dropped; that receiver's selector is `listing_hunt.HUNT_POOL`,
   imported and guarded, never retyped.

On ordinary domains `is_foreign` still does the work, because a page test there would refuse
every JS-rendered careers page — the same silent-exclusion trap in the other direction.

### The single-writer rule (most dangerous rule here — read before any write)

`companies.csv` writers must **re-read the file immediately before every write**
(read-modify-write per verdict, matching on **company name, never row index**) and never
hold a start-of-run snapshot; two concurrent snapshot-writers silently destroy each other's
verdicts (lost-update incident 2026-08-22).

**Every `companies.csv` writer, by safety class.** The census is what a new writer gets
checked against, so its being short is the whole risk — re-derive it rather than trusting the
list below, and note the grep must accept `CSV_PATH` as well as the literal or it misses
`resolve_any` and `resolve_unknowns`, which open a filename held in a variable:

```bash
for f in *.py; do grep -qE 'companies.csv|CSV_PATH' "$f" && grep -qE 'write_csv_rows|csv\.writer' "$f" && echo "$f"; done | wc -l
```

- **Compliant** (re-read + match by name before every write): `crack_walled.py`,
  `probe_candidates.py`, `listing_hunt.py`, `audit_empty_rows.py`, `deep_validate.py`,
  `scan_dead_domains.py`, `refresh_scrape_cache.py` (parking pass), `triage_dark.py`,
  `repair_dead_urls.py`, `repair_extract_gap.py`.
- **Modified-rows merge** (equally safe — merges only the names it changed into a fresh
  read): `bd_rescue.py`, `retry_unreachable.py`, `wayback_rescue.py`, `validate_empty.py`,
  `validate_bd.py`, `recheck_suspects.py`.
- **Append-only** (safe): `auto_expand.py`, `comeet_resolve.py`, `ingest_research.py`,
  `resolve_any.py`, `resolve_parallel.py`, `resolve_unknowns.py`.
  (`resolve_deep.py` and `scrape_batch.py` write only `out/*.csv`, never the registry.)
- **Line-based snapshot, sub-second window** (tolerated): `apply_resolved.py`.
- **The git layer, not the in-process one**: `merge_csv_rows.py` — the one writer with no
  in-process safety class, and the tool the deletion rule below blames.

No whole-snapshot index-keyed writer remains; add one and it will silently revert concurrent
verdicts. Use one of the first three patterns.

**Never DELETE a row. Park it with a reason.** No tool deletes rows, but a human commit does,
and a deletion is the one registry edit the git layer does not preserve: a concurrent cloud
run's conflict path runs `merge_csv_rows`, whose `changed` set still holds the row, and
`target.append(r)` resurrects it — after which someone re-deletes it silently inside an
unrelated commit. `check_invariants.py` checks the registry's SHAPE, never its SIZE, so every
commit in that cycle passes; the worked example with hashes is in
`docs/sessions/2026-08-24-registry.md`. Two rules follow:

1. **A row leaves the registry by being parked, not by being removed.** A parked row keeps
   its evidence, stays in a re-check pool if it should, and cannot be resurrected into a
   different meaning by a merge. Use `defunct:`, `alias-of`, `domain-dead`, or an explicit
   `removed <date>: <reason>` segment.
2. **If you do delete, the reason must be in the row's own note before it goes** — `python
   registry_health.py` (census diff against `cloud_state/registry_census.json`;
   `--census` re-baselines after an intentional removal) is the only detector, and the note
   is the only place it can find the reason afterwards. Every row count it prints is **body
   rows**, header excluded — `wc -l` gives one more, and mixing the two is the standing
   confusion `HANDOFF.md` flags.

**Concurrency has TWO layers — both must be handled.** In-process discipline (above) protects
writers on one machine. The **git layer** needs `merge_csv_rows.py`: a cloud run commits a
file whose baseline may be hours old, so `git pull --rebase` hits a content conflict and the
retry loop would discard the entire run (a 3.5-hour listing-hunt cycle was lost this way,
2026-08-22). Every csv-committing workflow therefore snapshots `/tmp/base.csv` right after
checkout, and on conflict resets to origin and replays only the rows this run changed
(`merge_csv_rows.py base ours target`). Copy that pattern into any new workflow that writes
the registry — and **`git add` the csv in it**: the digest's candidate probe writes verdicts
there while `candidate_probe.json` advances baselines, and committing one without the other
loses the wake *and* consumes its signal.

Cloud workflows that commit the csv serialize via the `repo-state` concurrency group — eight
of them (audit-coverage, auto-expand, deep-validate, listing-hunt, retry-unreachable,
scrape-refresh, self-heal, triage-dark) — **except `daily-digest.yml`**, which uses its own
group, so a digest CAN overlap an audit/hunt run; both re-read, so verdicts survive. A local
`--apply` run adds a third writer: avoid the cron windows in §4, and never run two
browser-driving tools at once (Playwright sync instances conflict).

### Who re-checks a parked row — the ownership matrix

Every inactive row must be owned by at least one *recurring* job, or it is permanently dark.
**There is no hand-written matrix here any more**: `registry_health.pools()` computes it by
importing each scheduled tool's own predicate, so it cannot drift from the tool it describes.

```bash
python registry_health.py | sed -n '/re-check ownership/,/OWNED BY NOTHING/p'
```

It prints one line per pool — the `pools()` keys below, verbatim — with the parked rows that
tool claims tonight, then a final `OWNED BY NOTHING` line. **That last line is the one to
read:** `orphans()` subtracts pool membership, so a pool that over-counts can only ever
UNDER-report orphans, the one direction that loses coverage silently. Counts move nightly (the
18:00 triage re-stamps rows), which is why they are derived, not typed; staleness cooldowns
are deliberately NOT applied, because a cooldown delays a re-check without removing ownership,
so a given night processes fewer rows than the pool holds.

| `pools()` key | cron (`.github/workflows/`) | what it owns | activates? |
|---|---|---|---|
| `triage_dark (18:00 daily)` | `triage-dark.yml` `0 18 * * *` | rows matching its own `TARGET_NOTES` minus `SKIP_NOTES` — classifies a dark row's failure mode and routes it | no |
| `listing_hunt (19:00 daily)` | `listing-hunt.yml` `0 19 * * *` | parked rows matching `HUNT_POOL`, minus terminal, recruiters, discovery junk and `_triaged_page_empty` | **yes** |
| `repair_extract_gap (19:00 daily)` | `listing-hunt.yml` `0 19 * * *` | rows triage stamped `extract-gap` (the tool's own `MODE`) that carry an `http` address | **yes** |
| `crack_walled (19:00 daily + Sun)` | `listing-hunt.yml` `0 19 * * *`, `audit-coverage.yml` `0 4 * * 0` | rows `identity_gate.is_walled` claims — the note token OR a walled ATS host — minus terminal and recruiters | **yes** |
| `probe_candidates (05:00 daily)` | `daily-digest.yml` `0 5 * * *` | rows matching `PROBE_POOL` with an `http` address, minus terminal; wakes rather than activates (`_wake_note` strips every stale segment) | no |
| `audit_empty_rows (Sun 04:00)` | `audit-coverage.yml` `0 4 * * 0` | `verdicts.in_pool` minus terminal and recruiters | **yes** |
| `deep_validate (Sat 04:00)` | `deep-validate.yml` `0 4 * * 6` | the same selector as the audit, at a different depth (Chromium render + network sniff) | **yes** |

`scan_dead_domains` (05:00 digest and the Sunday audit) is deliberately **not** a pool: it
tests liveness, never roles, and excludes only `defunct` rather than the whole terminal list,
because re-testing a `domain-dead` row is its purpose. Audit and deep-validate selecting the
identical row set 24 hours apart is this lane's clearest consolidation target
(`docs/BACKLOG.md`).

**Never retype a pool regex — import the tool's constant.** The guarded constants are
`listing_hunt.HUNT_POOL`, `probe_candidates.PROBE_POOL`, `pipeline/verdicts.TERM_RX` (the one
terminal list; `alias-of` is in it) and `identity_gate.is_walled`.
`test_the_ownership_matrix_is_built_from_the_tools_own_predicates` asserts the matrix holds
the tools' own objects — identity, not equality — so a retyped mirror fails the suite. Every
mirror this repo has had was wrong in the LOOSE direction; the four are listed in the session
log.

Four more rules this matrix exists to enforce, each violated in production at least once:

- **An activating pool must exclude the terminal states itself** —
  `test_no_activating_pool_can_re_open_a_terminal_row`. An `alias-of` row points at a board
  that *works*, so an audit would find it, verify real Israel jobs and re-activate the
  duplicate: every role published twice under two company names, which `check_invariants`
  check B cannot catch because the names differ.
- **A wake must clear *every* stamp any downstream filter excludes on, and survive to its
  receiver.** `probe_candidates._wake_note` strips `dark-triage`, which also resets
  `triage_dark._needs_triage` — so the 18:00 triage re-claimed the woken row an hour before
  the 19:00 hunt, and a re-stamped `page-empty` removed it from the hunt entirely
  (`_actionable_mode` is False for `page-empty` and `acquired`). Nothing is recoverable
  afterwards: the baseline is persisted **before** the wake test. `triage_dark` now skips any
  row carrying `probe-woken`.
- **Any new time budget needs a rotation key in the same commit.** `scan_dead_domains` and
  `probe_candidates` run inside the 05:00 digest on 10-minute budgets over loops in **CSV
  file order**, and a row found ALIVE writes nothing — so a truncated run re-walked the same
  prefix nightly, never reached the tail, and a row past the cut could never wake (a wake
  needs two observations). Both now sort least-recently-checked first
  (`cloud_state/scan_seen.json`, and a `last` key in `candidate_probe.json`).
- **A pool token must survive note erosion.** Each re-stamp trims the base to fit 220 chars;
  once the verdict eroded (`no IL listing; monitored candidate` → `no `) the row matched no
  pool at all. `triage_dark.TARGET_NOTES` therefore matches its **own** `dark-triage` stamp,
  which makes it self-sustaining.

## 3. Resolution ladder — how a dark company becomes covered
*lane: `registry`*

New names enter via discovery (`research_companies.json` queue) or manual seeding. Then:

1. `auto_expand.py` (cron 08:00/20:00): deterministic `resolve_deep` — recognizable ATS
   URLs, iframes. Failures get ONE shot at tier 2 (capped `LLM_RESOLVE_CAP`/run; excess
   **deferred**, not parked).
2. `resolve_llm.py`: evidence bundle (page fetch + SerpApi search + ATS-hint extraction) →
   single `claude -p` proposal `{platform, token, api_url}` → **verified** via the real
   fetcher. One retry carrying the verification error.
3. `listing_hunt.py` (cron 19:00): for rows still dark — find the LISTINGS URL (harvested
   links; Claude picks; rebrand redirects resolved), verify via `scrape_universal`.
   Woken/documented rows take the **fast-path**: scrape the stored URL first.
4. `deep_validate.py` (Sat 04:00) / `crack_walled.py` (daily 19:00 + Sun): Chromium render + network-request
   sniffing (`/wday/cxs/`, `careers-api`, `COMEET.init` static token extraction, …),
   platform host guessing, Claude evidence judgment.
5. Manual Chrome sweep: a human/agent reads the page in a real browser; every miss becomes
   a new detection pattern in the code.

**Verification invariants (never bypass):** see also "The activation rule" in §2, which is
the short version of the three gates and the code that enforces them.

- No row activates unless its endpoint/listing **returned real jobs through the production
  fetch path** at resolution time (for scrape rows: ≥1 *Israel* job) — AND the page claims
  to list jobs at all (`looks_like_a_job_listing_page`). Real Israel jobs are not enough:
  `SCRAPE_ASSUME_IL` turns every card on a page into an Israel role, so a nav menu and a
  blog index both "verify".
- Slug/tenant must resemble the company name — `_slug_matches` (`audit_empty_rows.py`,
  and also `listing_hunt.py:178`, a fifth call site this list omitted),
  enforced in `audit_empty_rows`, `deep_validate`, `crack_walled`, and `resolve_llm._verify`.
  **Known coverage holes in this guard:** comeet uids (`XX.XXX`) are exempt by design (the
  uid comes from the company's own page), and `_resolve_rebrand` in `listing_hunt.py` can
  only *document* a non-matching cross-domain redirect — it cannot tell a rebrand
  (piiano→a16y.ai, legitimate) from an acquisition (deci.ai→nvidia.com), so those need a
  human/LLM call before activation.
  Search fallbacks WILL offer another company's board that verifies with real jobs:
  **CyberArk→PANW** and **Imperva→Thales** were applied and had to be reverted (see their
  `companies.csv` notes); **Lili→Eli Lilly** was caught only by the 0-Israel-jobs gate.
  Historical note: `resolve_llm` relied on prompt-grounding alone until 2026-08-22.
  Since 2026-08-23 every activation path calls `company_identity` — there are **six**
  that write `active` or `api_url`, not the four this line claimed until 2026-08-24
  (`docs/AGENT_BRIEF.md` L104 still says four; that is `docs`-lane). Section 3 is this
  lane's and neither commit that took the count from four to five to six touched it,
  which is the same failure as leaving a closed hole documented. (This line also said a
  `weak` domain verdict "is settled by whether the fetched page NAMES the company as a
  phrase". Nothing reads `weak` — see section 2 and `docs/BACKLOG.md` 43.)
- **Every rung that searches needs all three fallbacks.** The ladder is SerpApi (cheapest,
  currently useless) → `deep_validate.ddg` (free) → `deep_validate.google_via_unlocker`
  (Bright Data, capped by `DEEP_BD_SEARCH_CAP`). Verified against the live account on
  2026-08-23: `total_searches_left: 0`, `this_month_usage: 250`, Free Plan, resets
  2026-09-01 —
  `python -c "import os,json,urllib.request;from bd_rescue import _load_secrets;_load_secrets();print(json.load(urllib.request.urlopen('https://serpapi.com/account?api_key='+os.environ['SERPAPI_KEY'])).get('total_searches_left'))"`.
  So a SerpApi-only rung returns `[]` **before it makes a request**, and a whole run of
  "found nothing" is indistinguishable from "cannot search".
  `resolve_broken._careers_url_via_serp` was given the fallback on 2026-08-23.
  **`audit_empty_rows.serp()` was not, and it got it on 2026-08-23** — it is the search
  behind the Sunday audit's phase 2 over the ~255-row parked pool, i.e. the rung that finds
  boards which MOVED rather than broke, and it had been a silent no-op for a week. Measured
  after the fix (3 pool companies, SerpApi still at 0): `Upsolver` 4 URLs, `Cognata` 4 URLs
  (`cognata.com/hiring/` — an iCIMS row), `Sproutt` 0; before the fix all three were `[]`.
  When every rung comes back empty the tool now prints a `::warning::` naming which
  credential was missing, because that is a broken run, not a measurement.
- **DuckDuckGo is rate-limited from the dev machine, not blocked.** Repeatedly documented
  here as "returns nothing"; measured on 2026-08-23 it returned 4 good URLs for `Wix`
  (`careers.wix.com/positions`) and 4 for `Fortinet` (including its real oraclecloud CX
  site), then `0` for the same query minutes later. Treat it as a rung that *sometimes*
  answers — which is why it can never be the only one. It is reliable on the runners; the
  unlocker works from both.
- Never activate a scrape of an aggregator page (LinkedIn/Indeed/Glassdoor/secrethunter) —
  their "similar jobs" sidebars attribute other companies' roles to the target. Enforced at
  resolution (all resolvers) **and at runtime** in `pipeline/run.py`, which drops such rows
  from the digest with a SKIP line. Note `scrape_universal.py` itself has no aggregator
  logic — never call it directly on an aggregator URL.
- A mass-zero result (e.g. 0 finds across a whole run) is a **broken run, not a
  measurement** — strip its verdicts and re-run after diagnosis (nested-Playwright
  incident: two sync Playwright instances in one thread fail silently). To strip: verdicts
  are ` | listing-hunt <date>: …` suffixes in the `notes` column; remove that suffix, or the row waits
  14 days for `_stale_hunt` to re-admit it. (Before 2026-08-22 the `no listing found`
  verdict was **terminal** — a bad batch retired hundreds of companies permanently.)
  Only `refresh_scrape_cache.py` self-protects automatically (aborts if the rebuilt cache
  shrinks >20%); every other runner needs the operator to apply this rule.

## 4. Schedules and latency guarantees (UTC)
*lane: `infra` — one session at a time. Checked against the real crons by `docs/check_docs.py`.*

This table is the **only** schedule in the repo, and `docs/check_docs.py` fails if any
`.github/workflows/*.yml` cron is missing from it or disagrees with it. It was wrong for
two workflows and one hour until 2026-08-23 — `triage-dark` and `deep-validate` were not
listed at all, and listing-hunt was written as 14:00 while its cron said 19:00.

| cron (UTC) | workflow | effect |
|---|---|---|
| `0 0 * * *` | scrape-refresh | re-render all scrape rows (JD carry-forward keeps enrichment) |
| `30 2 * * *` | retry-unreachable | Bright Data re-fetch of flaky endpoints |
| `0 5 * * *` | daily-digest | discovery → telegram → liveness scan → probe candidates → JD-enrich → fetch ALL active rows → classify → persist state → **publish board (persist runs first, on purpose)** |
| — 05:45 / 08:30 | inbox relay (private repo `AnalystJobsIL/inbox`, not this repo's crons) | digest → email via issue+mention, content-hash dedup |
| `0 6 * * *` | self-heal | re-resolve stale/rotted boards |
| `0 8,20 * * *` | auto-expand | drain resolution queue (deterministic + LLM tiers) |
| `0 18 * * *` | triage-dark | classify every parked row by failure mode (`dark-triage <date>: <mode>`) |
| `0 19 * * *` | listing-hunt | repair-extract-gap (35 min) → re-hunt woken/eligible dark rows (200 min) → walled-ATS re-crack (60 min) |
| `0 4 * * 6` | deep-validate | Saturday: Chromium render + network sniff over `_revalidatable` rows |
| `0 4 * * 0` | audit-coverage | Sunday: wayback rescue, empty cross-validation, full parked-row re-audit, **liveness re-scan (revives domains), walled-ATS re-crack**, coverage report |
| on push | tests | `pytest`, `check_invariants.py`, `pipeline.platform_check`, `docs/check_docs.py` — the only workflow with no `continue-on-error` step |

**Concurrency:** eight of the nine scheduled workflows share the `repo-state` group, so a
long run makes the next one queue or be superseded with no error. `daily-digest.yml` has its
own group on purpose, so a digest CAN overlap an audit/hunt run; both re-read before writing,
so verdicts survive (§2, the single-writer rule).

**A third scheduler exists and is not in this table:** the Windows scheduled task
`IsraeliJobs-Firmographics` runs `run_firmo_chain.cmd` every 6h on the owner's machine (§7).
It is not a GitHub Action and nothing here can see whether it ran.

Latency: active API rows — **same-day**; active scrape rows — **~1 day** (00:00 refresh →
05:00 digest); monitored candidates — **~1–2 days** (probe wake → 19:00 hunt verify → next
digest); deep re-hunt every 14 days and the weekend audits are backstops only.

## 5. State files
*lane: `infra` (who writes what) — `shared` for everyone who reads them*

| file | contents | written by |
|---|---|---|
| `companies.csv` | the coverage registry + verdicts | resolvers/audits (see rule below) |
| `cloud_state/seen.db` | tables: `sent` (email dedup), `matched` (job-board rows), `llm_cache` (role judgments), `company_info` (blurbs), `firmographics` | pipeline runs |
| `scraped_cache.json` | rendered scrape-row jobs (+enriched JDs) | scrape-refresh, enrich, auto-expand |
| `discovered_cache.json` | discovery-net jobs (21-day TTL at read) | discovery_daily, discovery_telegram |
| `research_companies.json` | resolution queue (names + seed URLs) | discovery bridges; drained by auto-expand |
| `cloud_state/telegram_seen.json` | last message id per channel | discovery_telegram |
| `cloud_state/candidate_probe.json` | probe signal baselines | probe_candidates |
| `cloud_state/stale.json` | per-company health verdicts: `fetch-error`, `regressed-to-zero`, `empty-board`, `misconfig-scrape-on-ats` | pipeline/health.py during digest |
| `cloud_state/health_baseline.json` | **all-time high-water** job count per company (monotonic — never decreases, which is why `regressed-to-zero` latches) | pipeline/health.py |
| `cloud_state/resolve_attempts.json` | self-heal retry throttle (weekly; 5 strikes → abandoned) | resolve_broken.py |
| `cloud_state/scrape_rot.json` | consecutive empty/error days per scrape row, with the last error code / HTTP status (§5a) | refresh_scrape_cache.py |
| `cloud_state/firmographics.json` | **the shared, git-mergeable export of the `firmographics` table.** sqlite cannot be merged, so this text file is what the local and cloud stores converge through; the digest reads sqlite ∪ this file (fresher `as_of` wins) and writes the union back | `research_firmographics.py --export`, `pipeline/run.py` |
| `cloud_state/pipeline_stages.json` | which nightly stage last finished and how much it did (`pipeline/stages.py`) — the digest warns in its audit when a prerequisite stage did not run today | each stage's workflow, via `python -m pipeline.stages stamp <stage>` — except `collect`, which `refresh_scrape_cache.py` stamps itself with its counts (§5a) |
| `cloud_state/source_health.json` | per discovery source: records returned this run, and the last day it returned any (`pipeline/sources.py`). A source that goes quiet is a workflow warning AND a line in the digest audit — Indeed returned zero for five days unnoticed | discovery_daily, discovery_telegram |
| `state/` (gitignored) | resume markers (audit done-list). Written in the cloud too but **never committed**, so the Sunday audit re-audits every parked row from scratch (a SerpApi budget fact) | audit/local runs |

(The single-writer and commit-together rules live with the csv schema in §2.)

## 5a. Fetch-failure semantics (what a broken careers board does to our job board)
*lanes: `ats-fetch` · `scraper` · `infra`*

A company whose fetch raises does **not** crash the run (`pipeline/run.py` per-company
try/except): it lands in `companies_failed` and gets `reason: fetch-error` in `stale.json`,
with the exception text. Its already-matched roles **stay on the board** — `_alive` in
`run.py` exempts failed companies for 7 days (`fail_grace`) so a transient outage doesn't
blank a company. Repair path: `stale.json` → 06:00 self-heal (`resolve_broken.py`,
re-resolves via careers-page capture; the search rung uses `SERPAPI_KEY` when set and
falls back to `deep_validate.google_via_unlocker` — this sentence said "needs
`SERPAPI_KEY`" until 2026-08-24, which was false since the unlocker fallback landed;
retries at most weekly, abandons after 5 strikes → "discovery covers it").

**What `pipeline/health.py` writes to `stale.json`, in the order it decides** (every
digest, from each row's outcome; `health_check.py` is the weekly backstop with the same
code): `misconfig-scrape-on-ats` (a `scrape` row whose URL is a native-ATS host) →
`fetch-error` (raised) → `regressed-to-zero` (baseline > 0, now 0; the baseline is the
all-time high, so this latches) → `empty-board` (0 postings, no baseline). **Zero is a
measurement, not a fault, for a fetcher marked `israel_scoped`** — workday, eightfold /
microsoft, phenom, custom_json ask the board for Israel, so their empty list means "no
Israel roles today": on 2026-08-24 `stale.json` held 26 Workday `empty-board` rows (25
distinct URLs — Broadcom and VMware share one) and **25 were live tenants with 2 to ~2,726
postings and none in Israel** (Helios 2, Adobe 741, Capital One ~1,867, Micron ~2,726 —
these drift daily), re-resolved by the self-heal every week for nothing. `health.py`
reads the attribute off the fetcher; `platform_check` flags a fetcher whose source narrows
to Israel without declaring it (`oraclehcm` declares `False`: its newest-500 pass is
unscoped, so its zero is evidence). The 26th, Dell Technologies, had 0 postings worldwide:
when Workday's, Eightfold's or Phenom's Israel request comes back empty the fetcher asks
the board for its total once (`fetchers._whole_board_or_raise` — Workday `searchText=""`,
Eightfold `location=`, Phenom no facet; `custom_json`'s one handler has no probe) and raises `fetchers.BoardEmpty` on 0 — a fetch failure with a reason,
named in the mail. The probe **fails closed on a 4xx** (the endpoint itself is dead, which
is the finding — except 401 / 403 / 408 / 429, which mean "not now") and **open on 5xx / network
/ malformed** ("could not tell" stays `[]`); the first version swallowed every probe error
and so failed open on exactly the condition it was there to detect. A board that reports N
Israel hits and serves an empty first page is a third thing — unreadable, not empty — and
raises with that reason. Comeet needs no probe: a dead uid/token is HTTP 400, a live empty
board is 200 `[]` (verified 2026-08-24).

**`regressed-to-zero` is not raised for scoped fetchers either.** Their baseline is a
search-hit count, not an Israel-role count — Workday's `searchText=Israel` returns text
matches from anywhere (NVIDIA: 40 postings, 0 tagged IL) — so "had 1, now 0" is noise (53
of 83 Workday rows carry a baseline > 0 on 2026-08-24, 11 of them 1–3), and the probe above
already answers the question a regression flag was asking. It still fires for every other
platform (today's 25 entries are all `scrape` rows). Two blind spots no health rule can
see: a `site` that moved to another business unit's postings (`n > 0`, all foreign), and an
Eightfold `?domain=` that serves a different tenant with real postings — both are
registry-validation problems.

**It reaches the reader — two bullets in the audit block** (`health.mail_lines(stale,
previous, scanned)`):

```
- **Boards** changed today: new: Dell Technologies: fetch-error · cleared: Guardz
- **Boards** standing: 4 fetch errors (Decart: HttpError: HTTP 404 for …; Dell Technologies:
  BoardEmpty: … 0 postings worldwide) · 25 regressed to zero (…) · 36 empty (…) · 25 scrape rows on an ATS host
```

Read the first line every morning and the second only when a number moved: the standing
counts are the same most days, which is why a new fetch error gets its own line. `new` is
a row that entered `stale.json` or changed reason since yesterday; `cleared` means
recovered — judged only over rows this run scanned (a row deactivated overnight is not a
recovery) and never for an Israel-scoped fetcher's measurement zero. Six names per class,
then `+k more`. No line at all means every board was healthy and nothing changed. Beside
it, `Failed companies: Decart (HttpError: HTTP 404 for …)`, eight names then a count —
until 2026-08-24 that line said `(HttpError)` and the empty/regressed counts reached
nobody. The same lines are `::warning::` in the run log. A scoped run (`--only`/`--limit`)
prints them but does not write `stale.json`. **Both are public**: `digests/latest.md` is
committed to the public pipeline repo and the Actions log is world-readable; the text is
an exception's first 70 characters with every URL query string stripped first (`?token=`
sat at character 75 of the two shortest Comeet URLs — a 5-character margin is not a
redaction step; `docs/index.html` renders none of it).

Scrape rows rot differently, in `refresh_scrape_cache.py`, and the two words matter
(constants re-read from the code 2026-08-24 — this paragraph said `ROT_PARK_DAYS` was 3 and
that empties parked; the code had said 7 / never since 2026-08-23):

- **empty** — the page answered and had no Israel roles. Dropped from the cache, an `empty`
  streak in `cloud_state/scrape_rot.json`, **never parked** (a company here can post nothing
  for a month); at `EMPTY_REVALIDATE_DAYS` (45) the row is flagged `empty-but-suspect` for
  triage and stays active and scanned.
- **error** — the page could not be read (`scrape_result().status == "error"`: Playwright
  launch or navigation failure; HTTP ≥ 400 on the main document with no jobs; an HTTP-200
  wall — Akamai `Access Denied`, a Cloudflare/PerimeterX/Incapsula/DataDome/Distil challenge
  page, stamped `block:access-denied` / `block:cloudflare` / … in the rot file — unless plain
  HTTP got a readable page; a 200 with nothing captured at all; a
  browser that failed mid-way and captured fewer roles than yesterday, for at most
  `PARTIAL_MAX_NIGHTS` (2)). Yesterday's jobs are carried forward for at most
  `CARRY_MAX_DAYS` (14) — never forever — and after `ROT_PARK_DAYS` (7) **observed** error
  nights (a flip from `empty` starts a new streak; a night the budget skipped does not
  count) the row is parked (`scrape rotted (error Nd) …`) so the registry's re-check pools own it again (the hunt
  pool lists that token; a row that also carries a `page-empty` triage stamp is owned by
  triage only — `docs/BACKLOG.md` 84), because **active rows are otherwise invisible to
  listing-hunt and the weekly audits**. The first night that can produce an `error` at all
  is 2026-08-25, so `parked=0` is the only possible value until about 2026-08-31. Until 2026-08-24 `scrape()` swallowed every navigation failure into `[]`, so
  this branch had never run: the rot file held 207 `empty` entries and 0 `error`, and a 403
  night silently deleted a company's jobs. The first pooled dry-run (425 rows, 2026-08-24,
  residential IP, LLM and unlocker off) found 48 errors: 24 Cloudflare walls, 4 Incapsula,
  9 HTTP 404, 8 HTTP 403, 1 HTTP 503, 2 navigation failures. The cloud run has the LLM tier
  and the unlocker on, so its `with_jobs` should be a little higher and its walls fewer.
  `no_il` in the stamp counts companies where roles were found but none in Israel — the
  case that used to be byte-identical to "nothing on the page".
- **a broken night is not a measurement.** Errors above `MASS_FAILURE_PCT` (20% of ≥ 20
  rows) mean the runner broke, not a hundred sites at once: no streak advances, nothing is
  parked, and the cache that IS written and committed is last night's plus tonight's
  successes — nothing is removed, and **nothing ages**: while the condition persists the
  cache is frozen and only the alarm says so (`CARRY_MAX_DAYS` does not apply to it). It
  recovers by itself at the next healthy 00:00; do not re-dispatch (the 05:00–08:30 rule, the no-manual-dispatch rule in `CLAUDE.local.md`, and
  the `repo-state` group all say so). If more than 20% of the companies that had jobs
  yesterday **and were scraped tonight** (≥ 5 of them) came back with none, nothing is
  written either — measured over what was processed, so a night the budget cut short cannot
  hide it. Companies left unprocessed by the time budget carry last night's entry. A worker
  that produces nothing for `STALL_S` (3 × the company budget) is stuck, not slow: its
  children are terminated, its rows are `hang` errors, and the next chunk starts on a fresh
  pool — one hung Chromium used to turn a finished night into a 330-minute killed job. The
  processing order rotates by the day, so a budget cut never strands the same rows twice.
  Known and not mine: on a push CONFLICT the workflow's `merge_json_cache.py` keeps every
  company key that only origin has, so a night's deletions (empties, expired carries, parks)
  are undone for that night — `docs/BACKLOG.md` 95, `infra`.

Every exit stamps the `collect` stage with its counts, and the digest prints that line in
its audit, keys alphabetical — the local rehearsal of 2026-08-24 rendered exactly:

    - Stage order: repair: … | collect: 2026-08-24 (TODAY) carried=6 empty=160 errors=48
      minutes=37 no_il=0 parked=0 rows=425 scraped=425 unprocessed=0 with_jobs=217 workers=4 | …

Read it with this arithmetic, which holds on every exit: `with_jobs + empty + errors =
scraped`, `scraped + unprocessed = rows`, `no_il ≤ empty` (roles found, none in Israel),
`carried ≤ errors` (error rows whose cached jobs, up to 14 nights old, were kept). A line
that does not reconcile, or that lacks a key, is not from this code. `alarm=` appears only
when something is wrong — `mass-failure-errors-NN%`,
`errors-NN%`, `shrink-abort-A-to-B`, `unprocessed-N` (above 5% of rows), `no-jobs` — and a
line reading `collect: <yesterday> (1d ago)` means the refresh crashed before stamping (the
workflow no longer re-stamps it blindly): on such a night nothing was committed at all —
the refresh step is not `continue-on-error` and the commit step has no `if: always()` — so
the digest served the previous cache; `gh run list -R AnalystJobsIL/pipeline --workflow
scrape-refresh.yml` finds the run, the failing step is `Refresh the scrape cache`. Both
cases are also a **bold `- **Stages:**` line in the audit and a `::warning::` in the digest
log** (`stages.alarms("collect")`, read by `pipeline/run.py`): a stamp older than today, or
one carrying `alarm=`. Offline,
`scrape_rot.json` carries each empty/error row's last error code, HTTP status, roles found
before the Israel filter, and the number of nights observed.

**The four unrelated "14"s** — don't conflate them: the job board's 14-day `first_seen`
window; `CARRY_MAX_DAYS`=14 (stale scrape jobs); the 14-day deep re-hunt cadence; and
`_stale_hunt`'s 14-day suppression of a row carrying a hunt verdict.

## 5b. Diagnosing "why isn't company X in my email?"
*lane: any — this is the runbook every lane starts from*

In order — each step names the file to open:

1. **`companies.csv`** — is there a row? Is `active=true`? Read the `notes` verdict: it
   names the tool, date, and finding (e.g. `monitored candidate`, `domain-dead`, `defunct`).
2. **`pipeline/recruiters.py`** — `is_recruiter(name)` true? Agencies are excluded by design.
3. **Aggregator SKIP** — the digest run prints `SKIP <company>: scrape row points at an
   aggregator`; such rows are dropped at runtime.
4. **API row failing?** `cloud_state/stale.json` (`fetch-error` / `regressed-to-zero`) and
   `cloud_state/health_baseline.json` (last-known-good counts) → repaired by 06:00 self-heal.
5. **Scrape row?** Look for the company key in `scraped_cache.json` (jobs extracted last
   refresh) and `cloud_state/scrape_rot.json` (consecutive dead days). Remember scrape data
   is up to a day old by design.
6. **Job present but not emailed?** Two filters remain: `pipeline/israel.py`
   (`is_israel_job`) and `pipeline/seniority.py` (`classify`). Reproduce a single decision:
   ```bash
   python -c "from pipeline.seniority import classify; print(classify({'title':'Senior Data Analyst','company':'X','description':'…'}, use_llm=False))"
   ```
   It returns the decision, path (`keyword` / `llm` / `llm_cache` / `keyword_nollm` /
   `llm_failed_fallback`) and reason. The cache key column in `llm_cache` is `title_key`. A cached role judgment lives in `cloud_state/seen.db` → `llm_cache`
   (key `company|title`); delete that row to force re-judgment.
7. **Emailed before?** `seen.db` → `sent` table is the across-day dedup: a role is emailed
   once. The 2-week job board still shows it; the email only carries the last 48h.
8. **Not in `companies.csv` at all?** Check `research_companies.json` (resolution queue) and
   `discovered_cache.json` (discovery-net jobs, 21-day TTL) — it may be mid-onboarding.

Inspect the store directly with sqlite: tables are `sent`, `matched` (job board rows),
`llm_cache` (role judgments), `company_info` (blurbs), `firmographics`.

**Trap:** the `cloud_state/*.json` files are snapshots of the **last committed cloud run**,
not live views of `companies.csv` — a company's absence from `health_baseline.json` or
`stale.json` proves nothing about whether it is being fetched (as of 2026-08-22, 158 of 722
active rows had no baseline entry). To settle it, run the row yourself:
`python -m pipeline.run --only "<name>" --no-llm`.

## 5c. Debugging entry points
*lane: any*

- "Why isn't company X in my email?" → §5b above (ordered runbook).
- "Is this verdict true?" → the row's `notes` names the tool and date; re-run that tool.
- "Did the run actually work?" → `gh run view <id> -R AnalystJobsIL/pipeline --log`.
  **25 of the 77 workflow steps are `continue-on-error`, so a green run can still hide a
  failed step** — read the step, not the badge.
- Coverage snapshot:
  ```bash
  python -c "import csv;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>5];print(len(r),'rows',sum(1 for x in r if x[4]=='true'),'active')"
  ```
- **Orphan check — run after touching ANY row filter** (see the ownership matrix in §2).
  **Use `python registry_health.py` and read its `OWNED BY NOTHING` line** — it derives
  ownership from each tool's own predicate. The hand-typed one-liner below is kept because it
  needs no imports, but it is a DIFFERENT definition and gives a different answer (4 vs 1 on
  2026-08-23, with zero name overlap), and `check_invariants.py` gives a third (0, because it
  whitelists **seven** names in `ALLOWED_ORPHANS`). Three detectors, three answers; reconciling
  them is in `docs/BACKLOG.md`. The one-liner's "must print 0" was never true:
  ```bash
  python -c "
  import csv,re
  T=re.compile(r'no listing found|no IL listing|no ATS detected|dark-triage',re.I)
  S=re.compile(r'defunct|domain-dead|recruiter|duplicate|redundant',re.I)
  P=re.compile(r'monitored candidate|host documented|no IL listing',re.I)
  rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>=6]
  dark=[r for r in rows if r[4]=='false' and 'dark-triage' in (r[5] or '')]
  orph=[r for r in dark if not ((T.search(r[5]) and not S.search(r[5])) or
        (P.search(r[5]) and 'domain-dead' not in r[5] and (r[3] or '').startswith('http')))]
  print(len(orph),'orphaned of',len(dark),'dark'); [print('  ',r[0]) for r in orph[:10]]"
  ```
- "Did tonight's dark-row work reach the pool?" — the hunt pool should be non-zero and
  shrink over successive nights:
  ```bash
  python -c "
  import csv,re,collections
  rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>5]
  c=collections.Counter(m.group(1) for r in rows if (m:=re.search(r'dark-triage [0-9-]+: ([a-z-]+)',r[5])))
  print(sum(c.values()),'triaged:',dict(c))"
  ```
  **A count of ~0 here means a concurrent writer clobbered the notes column** — check the
  most recent `row-merged state` commit and see §8 item 3b before re-running triage.

(Moved here from `HANDOFF.md` §5 on 2026-08-23.)

## 6. Recipes
*lanes: `registry` (add a company) · `ats-fetch` (add a platform) · `discovery` (add a channel)*

- **BEFORE adding any company (every time):** (1) grep the name **stem**, not the marketing
  name — `grep -in deci companies.csv` finds a row that `Deci AI` misses; many rows omit the
  `AI`/`Labs`/`Technologies` suffix. (2) Check the careers URL's **final** host:
  `curl -sIL <url> | grep -i ^location` — an acquired Israeli startup keeps a live URL that
  301s to the acquirer's global board (`deci.ai/careers/` → `nvidia.com`), which *will*
  verify with the acquirer's Israel jobs and attribute them to the wrong company. Acquired
  companies get `active=false` + a `defunct:` note, never an active row.
- **Add a company you found manually**: never hand-write an unverified row. Verify first —
  `python -c "from audit_empty_rows import verify; print(verify('Name','greenhouse','slug','https://boards-api.greenhouse.io/v1/boards/slug/jobs'))"`
  (returns `(total, israel)`; raises if the endpoint is bad) or, for a listings page,
  `python scrape_universal.py "Name" "https://…"` — it must extract ≥1 Israel job. Then add
  the row with `active=true` and a dated note, e.g.
  `Deci AI,scrape,,https://deci.ai/careers/,true,manual 2026-08-22: listing verified 4 IL`.
  Never point a scrape row at LinkedIn/Indeed/Glassdoor/secrethunter (§3 invariant).
- **Add an ATS platform**: write `fetch_x(row)` in `pipeline/fetchers.py` returning the
  common job shape (§0) — copy `fetch_ashby` as the simplest template, `fetch_phenom` if
  the API is a POST search — stamp `ats_platform` from the row and pick the **stable**
  id (the store keys on `{ats_platform}:{job_id}`; changing either re-emails every role),
  and set `fetch_x.israel_scoped = True` if the request already narrows to Israel (§5a).
  Add the `FETCHERS` entry, then wire **the five detection tables** or no resolver will
  ever discover the platform on its own: `SIGS` (`audit_empty_rows.py`), `_HTML_ATS`
  (`resolve_broken.py`, self-heal), `ATS_PATTERNS` (`resolve_deep.py`), the pattern list
  **and platform enum** in `resolve_llm.py`'s prompt, and `ATS_HOST` (`pipeline/health.py`).
  `deep_validate.py` re-imports `SIGS`, so it needs nothing. `python -m
  pipeline.platform_check` prints the grid: 24 MISSING cells on 2026-08-24 — 22 in
  `registry`'s resolver files (resolve_broken 8, resolve_deep 8, resolve_llm 3, SIGS 3)
  and 2 in `health.ATS_HOST` for `eightfold`/`phenom`, left out on purpose
  (`docs/BACKLOG.md` 78); the last two columns check that a fetcher narrowing to Israel
  declares `israel_scoped` and that health's empty-board verdict matches the declaration —
  behaviour, not source text. Validate against a live
  tenant with canned payloads in `tests/test_units.py` — the previous Eightfold fetcher
  shipped "shape confirmed" against an endpoint that 403s every real tenant. Verify with
  the `verify(...)` one-liner above before adding rows.
- **Add a Telegram channel**: append to `CHANNELS` in `discovery_telegram.py` (must have a
  public t.me/s preview; secrethunter-format parses deterministically).
- **A company's verdict looks wrong**: check its `notes` for the evidence date and method,
  reproduce with the named tool, and if the verdict flips — fix the row AND encode the
  miss as a detection pattern so the class is covered, not the instance.

## 7. Company firmographics — the company-type layer
*lane: `company-intel`*

Structured per-company facts (sector, stage, size, business model) that join with the
matched jobs to answer **"what does this TYPE of company ask for?"**. Built 2026-08-22;
distinct from the prose blurbs in `company_info` (§0's "About" text) — same lazy-cached
pattern, structured JSON instead of two sentences.

### The record

One JSON object per company, produced by `pipeline/firmographics.py::research_company`
(a `claude -p --allowedTools WebSearch` call, ~15-60s) and validated before caching:

```json
{"sector": "cybersecurity", "sub_sector": "cloud security (CNAPP)",
 "stage": "acquired-by-bigtech",              // enum: public | acquired-by-bigtech | growth-private | early-private
 "stage_note": "acquired by Google $32B, closed 2026-03",
 "size_band": "L",                            // enum: S <200 | M 200-1000 | L 1000-5000 | XL >5000
 "employees_global": 3148, "founded": 2020,   // founded accepts 1600..today (Barclays=1690!)
 "business_model": "SaaS per cloud workload", "customer_type": "enterprises",
 "il_center": "Tel Aviv", "as_of": "2026-08-22",
 "employees_source": "linkedin", "employees_as_of": "2026-08-22"}   // present when a fill pass touched it
```

**Validation philosophy: reject, never repair.** A record with no identifiable sector, an
out-of-enum stage, or an implausible number is dropped entirely (`_coerce` returns None) —
a failure is retried on a later pass, junk is never cached. The researcher is instructed
to answer null over guessing; the fill passes below close the nulls.

**Retry throttles (quota protection, added after adversarial review 2026-08-22):**
research failures land in the `firmo_failed` table (both the bulk script and the run.py
hook consult it) and retry at most **weekly** — so ambiguous names can't re-spend a
web-search call every chain run or capture the hook's 5-per-run budget. Companies whose
employee count neither fill pass could establish get `employees_lookup_miss` stamped on
the record and retry **monthly**. Anything that writes `employees_global` must re-derive
`size_band` via `pipeline.firmographics.band_for` — the researcher's `_coerce` and both
fill passes all do; a band/count contradiction means someone bypassed it. All three
chain scripts force UTF-8 stdout (`sys.stdout.reconfigure`): under the scheduled task
stdout is a redirected file, Windows picks cp1252, and a Hebrew company name in a print
used to kill the whole stage.

**Failure-classification semantics (wave-2 review):** `research_company` distinguishes
the NAME failing (model answers unknown / junk / validation reject → returns None →
caller records a `firmo_failed` strike) from the INFRASTRUCTURE failing (CLI logged out,
timeout, network → raises `ResearchUnavailable` → caller records **nothing**; the bulk
script and web fill abort after 3 consecutive, the run.py hook stops its loop). Without
this, one expired-login chain run at 03:00 stamped week/month gates onto the entire
pending backlog.

**Identity rules (wave-2 review):** leaked job-title "companies" ("Sql developer - X",
"my team") are pre-filtered by `firmographics.looks_like_junk` — never researched; the
earlier claim that research "correctly fails" them was false (the model profiles the
company mentioned *inside* the string, creating a duplicate under the junk key).
Company identity is **normalized** (`store._norm_company`) when targeting research and
when `company_type_analysis` joins jobs to profiles — "SolarEdge" and "SolarEdge
Technologies" are one company; 9 such duplicate pairs were merged on 2026-08-22.
Re-research of an existing record **merge-preserves** the `employees_*` fields the fill
passes paid for whenever the fresh record has no count of its own — `--refresh-days`
must never regress established counts to null.

### Collection & re-collection (three layers, all idempotent)

1. **Bulk / catch-up** — `research_firmographics.py` researches every company that is
   missing or stale (`--refresh-days N`; `as_of` is the staleness clock). Targets =
   active `companies.csv` rows **∪ companies appearing in `cloud_state/seen.db` matched**
   (CI's discovery surfaces employers we never listed). `--dry-run` reports, `--export`
   writes `state/firmographics.json`. Thread-pooled, saves per-company — Ctrl-C-safe.
2. **Employee fills** — `bd_employees.py` fetches LinkedIn company pages via Bright Data
   Web Unlocker (1 credit/page) for null `employees_global`; then `fill_employees_llm.py`
   re-researches (a) remaining nulls and (b) **suspect LinkedIn matches** — a count
   contradicting the page's own size bucket or under 10, which is how generic names
   (Bit, Aleph, Sunflower) match the wrong page. Every filled count carries
   `employees_source` + `employees_as_of`.
3. **Steady state** — two automatic paths keep it current with zero operator effort:
   - the Windows scheduled task **`IsraeliJobs-Firmographics`** (every 6h:
     09:00/15:00/21:00/03:00 local, catch-up on wake) runs `run_firmo_chain.cmd` =
     research → LinkedIn fill → web verify/fill → export, logging to `state/firmo_chain.log`;
   - `pipeline/run.py` researches up to `FIRMO_MAX_PER_RUN` (5) unprofiled board companies
     per digest run (stat `firmographics_researched`) — this is the only writer on the
     **cloud** side.

### The split-store trap — CLOSED 2026-08-23 (read this before "why is the data missing?")

It used to be: the full dataset lived in the **local** `state/seen.db` (`firmographics`
table) and its gitignored export, while the **cloud** `cloud_state/seen.db` held only what
its own 5-per-run hook had accumulated. 919 researched profiles sat on one laptop while the
cloud digest — the only thing that RENDERS them — had an empty table and re-researched from
zero. sqlite is the reason: git cannot merge a binary, so neither store could publish to
the other.

The stores now converge through **`cloud_state/firmographics.json`**, a sorted JSON export
that git diffs line by line. `research_firmographics.py --export` writes it (so the 6-hourly
Windows chain publishes automatically), and `pipeline/run.py` reads **sqlite ∪ export**,
fresher `as_of` winning per company, then writes the union back. Whichever machine did the
research, every consumer sees it.

If you add another table with two writers, do the same thing — do not seed one sqlite from
the other, which lasts exactly until the next conflict-recovery commit reverts it.

### Consumption

`company_type_analysis.py` joins matched jobs (default `--db cloud_state/seen.db`) with
the export, runs `pipeline/roleprofile.py::extract` per job, and aggregates requirement
stats (top skills, median years, degree-required rate, lead share, AI-mention rate) along
three axes: sector / stage / size_band → `out/company_type_analysis.{json,md}`.
Free-text sectors are collapsed through `primary_sector()`'s alias table there — extend
that table when a new sector variant fragments the grouping; don't edit stored records.

### Known limitations

- Discovery sometimes leaks **job titles or categories as company names** ("AppSec",
  "my team", "Sql developer - …"); `looks_like_junk` pre-filters the title-shaped ones
  for free, but bare category words ("AppSec") pass the filter and burn weekly-gated
  research attempts until the discovery-side parser is fixed.
- "Discovery"-class **ambiguous names** can't be researched safely without JD context;
  the run.py hook passes context, the bulk script does not.
- Employee counts for acquired subsidiaries are the **unit's** approximate headcount
  (see `employees_source` for the story) — don't sum them with parent-company records.
- The researcher found several listed companies **dead or absorbed** (Alike Health,
  Syte, Sckipio, SimilarTech, NanoLock, Rewire R&D) — firmographics is currently the only
  place that knowledge lands; the `companies.csv` rows are not auto-parked from it.

## 8. Failure classes — what this codebase does instead of erroring
*lane: any — every lane has been bitten by these*

Moved verbatim from `HANDOFF.md` §2 on 2026-08-23, where it was filed as session news. It
is the most reusable page in the repo: **a green workflow means nothing here.**

1. **Silent exclusion is the dominant bug class here.** Every serious defect found was a
   row quietly leaving a re-check pool: a verdict string missing from an allowlist, a
   `"marker" not in note` filter with no staleness escape, or a note overwrite that erased
   another tool's token. None of them error. See §2, "the verdict-string rule".
2. **A mass-zero result is a broken run, not a measurement.** A hunt cycle once reported
   0/501 because two sync Playwright instances collided silently. Strip those verdicts and
   re-run; never let them commit.
3. **Two concurrency layers.** In-process (re-read before every write) *and* git-layer
   (`merge_csv_rows.py`). A 3.5-hour cycle was discarded because only the first existed.
   Heavy local pushes during a long cloud run used to destroy it; now they don't.
3b. **The notes column is an append-log, so row-level merging is not enough.** On 2026-08-22
   the 14:00 hunt committed a `row-merged state` whose row versions predated the evening
   triage: `merge_csv_rows` applied its rows wholesale and the `dark-triage` segment
   vanished from **351 of 352 rows** (the hunt pool then computed to literally 0). The merge
   is now segment-aware (`_merge_notes`, keyed by owning tool). **If you add a new verdict
   token, add it to `_TOOL` in `merge_csv_rows.py` too** — an unrecognised segment is keyed
   by its first 28 chars, so two different runs of it collide and one is dropped.
   Guarded by `test_merge_unions_note_segments_from_both_writers`.
4. **Search results will hand you another company's board** — and it verifies, with real
   jobs. `_slug_matches` guards it. But note the inverse: CyberArk→PANW and Imperva→Thales
   looked like false matches and were actually **real acquisitions**. Check before "fixing".
5. **DuckDuckGo is RATE-LIMITED from this developer machine, not blocked** (corrected
   2026-08-23; §3 has the measurement — 4 good URLs for `Wix`, then 0 for the same query
   minutes later). Treat it as a rung that sometimes answers, which is why it may never be
   the only one. It is reliable on the runners. Local resolution work should still carry the
   Bright Data path (`deep_validate.google_via_unlocker`). SerpApi quota resets
   **2026-09-01**.
6. **Never overwrite a file you didn't read.** `pipeline/aggregators.py` already existed and
   held `fetch_serpapi_google_jobs`; creating a same-named module destroyed it silently
   (restored). The tooling warned; the warning was missed.
7. `python -m pipeline.run` with `--only`/`--limit` now writes `out/docs-preview/`, not the
   published board. Several root scripts have **no `__main__` guard** — importing them runs
   them (`merge_research.py` rewrites state on import).

### The guard rails, and what each one is for

| guard | runs | catches |
|---|---|---|
| `tests/test_units.py` | `pytest`, on every push and before every commit | 123 cases from 54 functions, **every one a bug that shipped**. Add one for every bug you fix. |
| `check_invariants.py` | blocking gate inside the digest, and in `tests.yml` | registry-shape violations: alias rows, an ATS row whose endpoint is not on that ATS, eroded verdicts. Some checks are warnings on purpose — see §K in `docs/sessions/2026-08-23.md` for why a blocking check once discarded a whole run. |
| `pipeline/platform_check.py` | `tests.yml` | an ATS platform wired into some of its ~22 sites and not the others |
| `docs/check_docs.py` | `tests.yml`, via `test_docs_are_consistent_with_the_code` | a document that names a file that no longer exists, a dead link or a §N pointer left behind by a renumber, a cron table that disagrees with the crons, a root module nobody classified, a `HANDOFF.md` growing back past 250 lines |

If a change makes these red, the change is wrong — they were all written from real
incidents.
