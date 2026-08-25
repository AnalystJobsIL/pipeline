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
  │                        judgments cached v2|company|title|jd|bare ▶ seen.db   │
  └──────────────────────────────────────────────────────────────────────────────┘
                   │
  ┌ 6 RENDER ─────────────────────────────────────────────────── lane: render ───┐
  │  jdtext.py → rolecard.py → digest.py   the board, the archive, the email,     │
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
titles go to one bounded, tool-less `claude -p` call (§7b), whose YES/NO **role judgment** is
cached in `cloud_state/seen.db` under `v2|company|title|jd` or `|bare` — a verdict judged
on a bare title is re-judged once the description arrives (distinct from a row's coverage
**verdict**, §2).

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
And **33 of the 72 workflow steps carry `continue-on-error: true`** (counted 2026-08-25 by
`docs/check_docs.py`, which fails if this sentence and the workflows disagree; nine of the 35
are the `Stage stamps on the run page` / CLI-install steps added that day, tolerated on
purpose — their outcome is what the mail and the run page read, never the badge), so a hard
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

### The five live sources (four running, 2026-08-25)

Costs and counts are the 2026-08-23 measurements, with the 2026-08-25 cloud run beside
them where it differs; re-derive with
`python -c "import json;print(json.load(open('cloud_state/source_health.json')))"`.
The 2026-08-25 run (32813499709): Indeed 63 raw → 54 kept · Workable 20 → 12 new ·
LinkedIn 1,493 cards across 27 queries, `free=159 paid=14` · Telegram 15 parsed, 13 merged ·
**targeted skipped (cap 0, pool at 111%) — cap 4 and zero records on 08-24, cap 0 on 08-25**.

| source | how it is read | key? | measured |
|---|---|---|---|
| `linkedin` | **the discovery source.** `linkedin.com/jobs/search`, 9 keywords × (national + 2 peripheral-city windows: Be'er Sheva, Haifa — city queries free-only), `f_TPR` past week. KEYLESS guest endpoint first, Web Unlocker only where blocked | no* | 364 employers → 182 new companies, 7 credits, 113s (08-23); 312 → 158 new, 14 credits (08-25) |
| `workable` | `jobs.workable.com/api/v1/jobs?location=Israel` — one ATS, EVERY tenant. The only source returning the employer's own website | no | 20 rows → 11 kept, 11/11 with a real careers lead |
| `indeed` | `il.indeed.com/jobs` through the Web Unlocker; parsed from the `mosaic-provider-jobcards` blob | yes | 58 raw → 46 kept |
| `telegram` | public `t.me/s/<channel>` previews — no bot, no account, no quota | no | 6 channels, 16–18 of 20 parsed each |
| `linkedin-targeted` | BD dataset, one input per broken-board company, scoped by the **`company` field**. Backfill, **NOT discovery** | yes | 88 companies → 67 records, 57 on-target |

\* the paid path is a fallback; `SOURCE_PATH` records which one served — `linkedin_free`,
`linkedin_blank` (a 200 with no cards: a hole in the pool or a soft limit), `linkedin_blocked`
(403/429/timeout: a request MADE that produced nothing) and `linkedin_paid` — all four on the
`[linkedin] … path free= blank= blocked= paid=` line from the 2026-08-26 run on (the 08-25
log still shows `free=159 paid=14`), and the run warns if
everything is suddenly billed. Before that day a blocked request was counted nowhere: 7 of 9
national keywords and 13 of 18 city queries hit a block on 2026-08-25 and the log could not
say so. Every query that stops for any reason other than a drained pool prints
`stopped with N jobs: <why>` — a free-only city query that found nothing counts as
drained (an empty Be'er Sheva keyword is ordinary; a soft-limit spike shows in `blank=`); the old boolean printed "raise LINKEDIN_GUEST_PAGES" for five
queries LinkedIn had blocked (guarded by
`test_a_blocked_guest_walk_does_not_print_the_raise_the_cap_tripwire`).

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
   sweep's ~18 whatever LinkedIn does to the runner. **First cloud measurement,
   2026-08-25:** the 18 city queries returned 119 cards → 15 new jobs (all Be'er Sheva);
   **Haifa returned 0 cards on all 9 keywords** and 4 of the 5 non-empty Be'er Sheva walks
   were cut short by a block — whether Haifa was refused or empty was undecidable until the
   `blocked=` counter landed the same day. Re-measure on the 08-26 log before backing the
   city product off; the paid cost stayed at 14 (the national sweep's), as designed.

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
| **discovery's own share, before SERP** | **~124** → ~3,700/month |

**That ~3,700 was discovery-only arithmetic presented as the pool total, and the pool is
NOT inside the free tier.** Measured 2026-08-25 (day 25 of 31), what `report_bd_spend()`
printed: **5,553 / 5,000 credits (111%)**, projected **6,886** (≈ $2.39 at PAYG) —
`dataset_records=2989, unlocker_reqs=1649, serp_reqs=915`. 2,919 of the 2,989 records are
this layer's own LinkedIn dataset (`gd_lpfll7v5hcqtkxl6l`), **1,527 of them spent on
2026-08-23** during that day's A/B measurements (both from the Bright Data
`datasets/v3/snapshots` ledger, read live by the 2026-08-25 review — not reproducible
offline); the 915 SERP requests are
`deep_validate.google_via_unlocker` from six other scripts (BACKLOG 6) and were excluded
from the old table by construction. Breadth (LinkedIn ≤18 + Indeed ~6 Unlocker requests)
is deliberately never throttled and spends BEFORE `plan_spend()` runs, so on a day that
prints `budget 0 credits/day` the run has already billed ~20; the targeted sweep is what
`plan_spend()` cuts: cap 4 on 08-24 (a doomed trigger, 0 records), cap 0 on 08-25 (72 targetable rows in
`cloud_state/stale.json` have no recovery path until the pool resets on 2026-09-01).

Three of the five sources need no key at all, which is why `main()` does **not** return early
when `BRIGHTDATA_API_KEY` is missing — that gate used to sit above the keyless sources *and*
above `sources.record()`, so a rotated secret took the free half dark and silenced the
detector built to notice.

Two mechanisms keep this honest, and both exist because the number was wrong before:

- **`report_bd_spend()`** prints the whole pool every run and projects month-end with a
  dollar figure, warning past 80%. Counting only dataset records under-reported 4,106 as
  2,989 (2026-08-23; on 08-25 it is 5,553 against the same 2,989). `/customer/balance` is 403 for this token, so the figure is reconstructed from
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

**Widening intake is no longer free — the resolver queue IS the bottleneck.** On 2026-08-23
`auto_expand`'s drainable backlog was 77 against a batch of 250 per run (the workflow's
limit; the module default is 200) and the sentence here said widening was cheap.
Re-measured 2026-08-25: **342 drainable names** (`research_companies.json` holds 1,544
entries, 514 seeded with an aggregator URL), and the last five `auto-expand.yml` runs each
printed `resolved 0 (LLM-cracked 0), empty 10, unreachable 0` — the last three with
`deferred 240`. The binding dial is `LLM_RESOLVE_CAP=10`, not the batch size: 338 of the
342 seeds are aggregator postings (222 `linkedin.com/jobs/view/…`, 91 the
`secrethunter.io/jobz/<id>` JS shell, 25 `il.indeed.com`), `resolve_llm` starts with zero
candidate pages for an aggregator seed and asks
SerpApi (exhausted until 2026-09-01) for more, so the 10 names that get their one LLM shot
per run come back `None` and are written as `scanned; no open Israel roles now` rows with
the shell URL as their board — 44 such rows now (ctera, Houzz, yad2, Upwind Security, RISCO
Group …). Of the 70 aggregator-seeded rows 7 are active: six turned on by dark-triage
(`activated 2026-08-23: validated page`) and exactly one by `listing_hunt` — `Tel Aviv`,
the wrong one. So the
`[yield] linkedin: 312 employers -> 158 NEW companies` line is a true count of names and a
false promise of coverage until the queue drains. Fix is `registry`'s (BACKLOG 177/178);
re-derive with the `gh run view … --log | grep -E "unresolved:|=== resolved"` command in
`docs/sessions/2026-08-24-discovery.md` (2026-08-25 section).
### What intake refuses, and where each gate lives

A name that gets past here becomes a `companies.csv` row two `auto_expand` runs later, so
this is the cheapest place in the system to say no. Both bridges apply the same three:

| gate | module | rejects |
|---|---|---|
| already known | `pipeline/companies.py` (`load_companies`) | any name already in the registry, active or parked |
| `looks_like_junk` | `pipeline/firmographics.py` | a leaked job title / category / team phrase ("Data researcher - Navina", "AppSec") |
| `is_recruiter` | `pipeline/recruiters.py` | staffing and placement firms, which re-post dozens of clients' roles. Since 2026-08-25 it also judges the LinkedIn `company_slug` — "Dialog" is `dialog-recruiting` — and its own firmographics record is evidence: Nisha Pro shipped in the 08-25 mail as "newly covered" with a blurb saying "staffing" |
| `is_place_name` | `discovery_telegram.py` — **the Telegram path only**, cache AND queue | a name that is exactly a city / region / country (`pipeline/israel`'s place lists plus the spellings the channels write, spaces squashed: "Petahtikva"). Only a Telegram post can put a city in the employer slot, and the same check on the structured sources would veto real employers that share a place name (Nesher, Eilat, Airport City). A company named "Tel Aviv" defeats every downstream identity check because its host is named after the same city (`registry_health --explain "Tel Aviv"` → `tenant_is_this_company = True`); 1 of 1,633 distinct name strings across registry ∪ queue ∪ cache on 2026-08-25, and it IS an active row until `registry` parks it (BACKLOG 167) |

Job-level exclusion happens later and separately, in `fetchers.fetch_discovery`: the 21-day
TTL, `is_recruiter` again (a discovery job carries the real employer name, so it bypasses
the row-level check in `pipeline/run.py`), and `company_identity.url_names_other_company`
for a card whose URL slug names a different employer — 147 board rows were once published
under the wrong company that way. **Since 2026-08-25 the cache WRITE is the layer's own
chokepoint:** `discovery_daily` judges every card it writes and every card it carries by
name + LinkedIn slug (8 "Dialog" / `dialog-recruiting` cards had sat in the committed cache
while `fetch_discovery` judged the display name only — BACKLOG 184), strips the private
`_junior` flag from carried records, and both bridges prune from `research_companies.json`
whatever the gates now refuse, on every run whether or not they found anything new
(`auto_expand` re-checks the name only; "Dialog" was at position 129 of its next batch).
Every rejection prints the name, so a wrong one can be appealed from the step log.

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

### Four rules this layer costs data to re-learn

1. **Merge `discovered_cache.json`, never truncate it.** `discovery_daily.py` runs first and
   `discovery_telegram.py` second, into the same file. A truncating write on 2026-08-21
   deleted every Telegram-sourced job — **79 verified roles, unrecoverable**, because the
   Telegram watermark in `cloud_state/telegram_seen.json` had already advanced past them.
   Both writers merge by `(company, title)`. `discovery_daily` lets this run's copy win and
   prunes past the 21-day TTL; `discovery_telegram` only appends keys the cache does not
   hold and prunes nothing (the read side's TTL covers it) — stated here because the
   sentence used to claim both did both (found wrong 2026-08-25).
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
4. **A Telegram post with no company line is skipped, never shifted.** The secrethunter
   format is positional and one post in ~160 (2 of 320 live posts, 2026-08-25) omits the
   company: title / city / date / skills / seniority / url. Positional parsing then emits the
   CITY as the employer and the DATE as the city — `{"company": "Tel Aviv", "location":
   "20/8/26, Israel"}` was queued on 2026-08-20, resolved by `listing_hunt` onto
   `jobs.secrettelaviv.com` (secrethunter's city board, not on the aggregator list until
   2026-08-25), activated, and put **7 of the 81 roles on the 2026-08-25 board and 2 in that
   day's mail** under a company that does not exist, with a blurb about Alma. `parse_post`
   now returns `None` when the date sits in the city slot; the secrethunter link is a JS
   shell, so there is no employer to recover. Guarded by
   `test_a_telegram_post_with_no_company_line_is_skipped_not_shifted_into_a_city_named_employer`.

### Known limitations of this layer

- **The seed URL a bridge can offer is always an aggregator**, because a discovered job's
  `url` IS its posting on LinkedIn / Indeed / secrethunter — **514 of 1,544** queue entries
  and **70** registry rows carry one (2026-08-25; was 206 of 1,233 and 45 on 08-23). The
  LinkedIn bridge already writes a `slug` (`nishapro`, `shavit-software`) that `auto_expand`
  ignores — the one non-aggregator seed this layer can produce. `secrethunter.io/jobz/<id>` cannot be followed to the real
  posting: it is a 33,495-byte JS shell, byte-identical for every job id. The fix belongs to
  `registry` (`auto_expand.py`) and is item 2 in `docs/BACKLOG.md`.
- **A single Telegram channel dying is not visible in the mail** — one aggregate `telegram`
  key, because `sources.stale()` has one 2-day threshold for every key. Per-channel counts
  are in the step log. `docs/BACKLOG.md` item 3.
- **A deliberately skipped sweep reads as a dead one.** `linkedin-targeted` records a zero
  on every budget-starved run (correct — an unwritten key froze `last_run`), but
  `sources.stale()` cannot tell "skipped: no budget" from "died": from 2026-08-26 the mail's
  *Sources not producing* line will say `linkedin-targeted: nothing for 3d` and count up
  daily until the pool resets on 2026-09-01. Needs a per-key reason in `pipeline/sources.py`
  (shared plumbing) — BACKLOG 179.
- **This layer has no line of its own in the mail.** `pipeline/stages.ORDER` has no
  `discover` stamp, so the mail shows source deaths (`dead_sources`) and nothing else about
  intake — the yield, the blocked count and the queue depth live in the step log only.
  BACKLOG 180 (`infra`).
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
   │ resolved+verified │  failed        │   an AGGREGATOR seed (a LinkedIn / Indeed /
   ▼                   ▼                ▼   secrethunter posting — 338 of the 342 queued
 ACTIVE ROW        parked: "scanned; no open" / "unreachable"     names on 2026-08-25) skips
                   (never for an aggregator seed: it is DEFERRED  resolve_deep and is only
                    and rotated via cloud_state/auto_expand_seen.json) ever deferred
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
tokens that `listing_hunt`'s fast-path keys on. The one legitimate removal is of a token the
tool has **disproved and owns**: `bd_rescue`'s validated branch strips `unreachable` (its
own, per `TOKENS`) because that token is the selector of the 02:30 `retry_unreachable`
pass that runs 90 seconds later — leaving it in re-selected the row and, until 2026-08-25,
the retry rebuilt the cell and erased the verdict Bright Data had just been paid for
(`git show b3d1d49 -- companies.csv`: 9 rows, nightly, `recovered 0`).

**The pool is still spelled in THREE places** — `verdicts.TOKENS`, `listing_hunt.HUNT_POOL`,
`check_invariants.POOL` — and since 2026-08-25 `TOKENS` is a superset of both inline copies
(`url-cleared` / `url-flagged` joined it when `auto_expand --clear-agg-urls` started writing
the first). The one deliberate remaining difference is `HUNT_POOL` lacking `dark-triage`
(triage owns those rows). `registry_health` IMPORTS `HUNT_POOL`, which is the pattern to
copy; `test_the_three_copies_of_the_re_check_pool_still_agree_where_they_are_supposed_to`
pins every difference so a new one is red. Print the diff, and the rows it would cost
(on 2026-08-25 the first prints two empty lists and `[]`; the second `46 1`, the 1 being
a carrier that is also terminal):

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
`dark-triage` mode that routed it there. **No scheduled tool rebuilds the cell from a literal
any more** (2026-08-25: `retry_unreachable._row_for` takes the row's note and appends through
`replace_own`; `bd_rescue`, `wayback_rescue` and `validate_empty`'s write site do the same on
activation) — the whole-ROW literal `[name, plat, tok, api, "true", f"..."]` is the shape the
guard above now walks too. The two tools that still build a row from scratch,
`recheck_suspects` and `validate_bd`, are `legacy_unscheduled` in `tests/writer_allowlist.json`
and run in no workflow. Re-derive rather than trust: `grep -n '"true", f"' *.py`.

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
   (`grep -rn '"weak"' --include=*.py .` — the producer, tests and `registry_health`'s explain line; no consumer), so a
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
of them (audit-coverage, auto-expand, listing-hunt, retry-unreachable, scrape-refresh,
self-heal, triage-dark) — **except `daily-digest.yml`**, which uses its own
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
| `repair_extract_gap (19:00 daily)` | `listing-hunt.yml` `0 19 * * *` | `in_extract_gap_pool`: rows triage stamped `extract-gap` (`MODE`) with an `http` address, minus terminal and recruiters — the terminal exclusion arrived 2026-08-25, the day it selected a freshly parked `alias-of` twin | **yes** |
| `crack_walled (19:00 daily + Sun)` | `listing-hunt.yml` `0 19 * * *`, `audit-coverage.yml` `0 4 * * 0` | rows `identity_gate.is_walled` claims — the note token OR a walled ATS host — minus terminal and recruiters | **yes** |
| `probe_candidates (05:00 daily)` | `daily-digest.yml` `0 5 * * *` | rows matching `PROBE_POOL` with an `http` address, minus terminal; wakes rather than activates (`_wake_note` strips every stale segment) | no |
| `audit_empty_rows (Sun 04:00)` | `audit-coverage.yml` `0 4 * * 0` | `verdicts.in_pool` minus terminal and recruiters | **yes** |
| `deep_validate rung (Sun 04:00)` | `audit-coverage.yml` `0 4 * * 0`, inside `audit_empty_rows` | the rows the cheap rung left dark, minus those deep-validated within 30 d — Chromium render + network sniff, `deep_validate.validate_one`/`apply_verdict` | **yes** |

`scan_dead_domains` (05:00 digest and the Sunday audit) is deliberately **not** a pool: it
tests liveness, never roles, and excludes only `defunct` rather than the whole terminal list,
because re-testing a `domain-dead` row is its purpose. The **02:30 chain** is not in `pools()`
either, and it activates: `bd_rescue` then `retry_unreachable` (`retry-unreachable.yml`) both
select parked rows carrying `unreachable` (retry minus terminal since 2026-08-25); adding them
as `in_*_pool` entries is `docs/BACKLOG.md` (registry). Audit and deep-validate used to select
the identical row set 24 hours apart (270 rows on 2026-08-25); since 2026-08-26 the Chromium
render is the audit's second rung over what its cheap rung left dark, with its own 30-day
cooldown and `AUDIT_DEEP_BUDGET_MIN` — one Sunday pass, one workflow fewer.

**Never retype a pool regex — import the tool's constant.** The guarded constants are
`listing_hunt.HUNT_POOL`, `probe_candidates.PROBE_POOL`, `pipeline/verdicts.TERM_RX` (the one
terminal list; `alias-of` is in it), `identity_gate.is_walled` and
`repair_extract_gap.in_extract_gap_pool`.
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
   URLs, iframes — for a seed on the company's own site. An **aggregator seed** (a LinkedIn /
   Indeed / secrethunter posting) never reaches it: rendering that page can only yield a
   refusal, `empty` or `unreachable`, and until 2026-08-25 it cost 17–25 s of Playwright per
   name AFTER the LLM cap was spent (76 wasted minutes a run, twice a day, with the ten names
   that did get a shot buried as `scanned; no open Israel roles now` under the posting's URL).
   Failures go to tier 2, capped two ways per run — `LLM_RESOLVE_CAP` (10) `claude -p` CALLS,
   charged only when a page was read, and `AUTO_EXPAND_SEARCH_CAP` (40) names that may enter
   the tier — and a name the tier cannot crack is **deferred**, never parked, on a
   least-recently-tried rotation (`cloud_state/auto_expand_seen.json`; the log says why:
   `dfer <name> (no-llm|cap|no-candidates|llm-none)`). The 28 rows buried before that date
   were un-addressed with `auto_expand.py --clear-agg-urls --apply` (`url-cleared`, hunt-owned).
2. `resolve_llm.py`: evidence bundle (page fetch + the search ladder SerpApi →
   `deep_validate.ddg` → `google_via_unlocker`, the paid rung capped per run by
   `LLM_BD_SEARCH_CAP`, default 5 → ATS-hint extraction) → single `claude -p` proposal
   `{platform, token, api_url}` → **verified** via the real fetcher. One retry carrying the
   verification error. The call goes through the shared seam `pipeline/llm.py::call_json`
   (`--model sonnet` via `LLM_RESOLVE_MODEL`, `--tools ""`, a JSON schema with the platform
   enum, scratch cwd, no shell) — until 2026-08-25 it was the last bare `claude -p` in the
   repo. **No page read, no call**: with zero reachable pages the model is
   not asked (`LAST["asked"]` tells the caller), because 0 of 50 evidence-free shots ever
   resolved. Live control 2026-08-25: `Upwind Security` (a buried secrethunter seed) →
   comeet `49.004`, 51/15 IL, 29 s, one call, DDG only.
3. `listing_hunt.py` (cron 19:00): for rows still dark — find the LISTINGS URL (harvested
   links; Claude picks; rebrand redirects resolved), verify via `scrape_universal`.
   Woken/documented rows take the **fast-path**: scrape the stored URL first.
4. `deep_validate.py` (the Sunday audit's second rung; `--only` on demand) / `crack_walled.py` (daily 19:00 + Sun): Chromium render + network-request
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
  (Bright Data, capped by `DEEP_BD_SEARCH_CAP` in `deep_validate`/`audit_empty_rows`, and by
  `resolve_llm`'s own `LLM_BD_SEARCH_CAP` since 2026-08-25 — it had been SerpApi-only, i.e.
  a no-op, for the whole month). Verified against the live account on
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

## 4. Schedules, delivery, and what happens when a run breaks (UTC)
*lane: `infra` — one session at a time. The cron table is checked against the real crons by `docs/check_docs.py`.*

This table is the **only** schedule in the repo, and `docs/check_docs.py` fails if any
`.github/workflows/*.yml` cron is missing from it or disagrees with it. It was wrong for
two workflows and one hour until 2026-08-23 — `triage-dark` and `deep-validate` were not
listed at all, and listing-hunt was written as 14:00 while its cron said 19:00.

| cron (UTC) | workflow | effect |
|---|---|---|
| `0 0 * * *` | scrape-refresh | re-render all scrape rows (JD carry-forward keeps enrichment) |
| `30 2 * * *` | retry-unreachable | Bright Data re-fetch of flaky endpoints |
| `0 5 * * *` | daily-digest | discovery → telegram → liveness scan → probe candidates → JD-enrich → fetch ALL active rows → classify → persist state → **publish board (persist runs first, on purpose)** → report the run's outcome |
| — `17 6,7,8,10 * * *` | inbox relay (private repo `AnalystJobsIL/inbox`, not this repo's crons) | digest → email via issue+mention, content-hash dedup |
| `0 6 * * *` | self-heal | re-resolve stale/rotted boards |
| `0 8,20 * * *` | auto-expand | drain resolution queue (deterministic + LLM tiers) |
| `0 18 * * *` | triage-dark | classify every parked row by failure mode (`dark-triage <date>: <mode>`) |
| `0 19 * * *` | listing-hunt | repair-extract-gap (35 min) → re-hunt woken/eligible dark rows (200 min) → walled-ATS re-crack (60 min) |
| `0 4 * * 0` | audit-coverage | Sunday: wayback rescue, empty cross-validation, full parked-row re-audit (cheap rung, then `deep_validate`'s Chromium rung over what stayed dark — the Saturday cron until 2026-08-26), **liveness re-scan (revives domains), walled-ATS re-crack**, coverage report |
| on push | tests | `pytest` (which runs `docs/check_docs.py`), `check_invariants.py`, `pipeline.platform_check`, the mutation gate — the only workflow with no `continue-on-error` step |

**When the email actually arrives.** The 05:00 cron is queued by GitHub for ~35 minutes
and the job runs ~30 (05:36→06:08 on 2026-08-25, run 32813499709), so the digest lands on
`master` at ~06:08. The relay used to poll at 05:45 and 08:30: the 05:45 pass found
yesterday's file every morning (run 32815273635 at 06:02 printed `already posted … 08-24`)
and the mail waited for 08:30 — inbox issues at 05:59, 08:59, 06:23 on three consecutive
days. Since 2026-08-25 the relay polls at **06:17, 07:17, 08:17 and 10:17**, deduped by the
sha256 of `digests/latest.md`, so **expect the email at ~06:20 UTC (09:20 Israel)**; a
slow run or a re-run is caught by the later passes. Re-derive with
`gh issue list -R AnalystJobsIL/inbox --limit 5 --json createdAt,title`.

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

### The delivery path: one script, nine workflows (2026-08-25)

Every workflow that commits state ends in the same step —

```yaml
- name: Commit verdicts            # (the name varies; the shape does not)
  if: always()                     # a crash or a timeout no longer discards the night's work
  timeout-minutes: 10
  run: python persist_state.py commit --as audit-bot -m "listing-hunt $(date -u +%F) [skip ci]" \
         --own companies.csv scraped_cache.json cloud_state/pipeline_stages.json cloud_state/registry_ladder.json
```

— and `persist_state.py` (root, `infra`; `python persist_state.py table` prints the rules)
does what nine hand-copied shell blocks used to do, with the lessons they had each learned
separately now enforced once. `--own` is the whole contract: **a path this job does not own
is never staged, never restored, never merged** (the old blocks ended in `git add -A .`).
Before staging, every owned `*.json`/`*.jsonl` must parse, `seen.db` must pass `PRAGMA
quick_check` (opened read-write, so a hot rollback journal is replayed rather than read as
corruption), `digests/latest.md` must start with a heading, `docs/*.html` must be ≥ 500
bytes, and `companies.csv` must pass `check_invariants.py`; a file that fails is restored
from the checkout commit, everything else still lands, and the step exits 1 — user-approved
on 2026-08-25 as the replacement for "a run that broke an invariant loses its work". Sqlite
side files (`-journal`, `-wal`, `-shm`) and atomic-write leftovers (`.tmp_*`, `*.tmp`) are
never staged; a tracked file that vanished from an owned directory is restored, never
committed as a deletion (`rm -rf cloud_state` + `--own cloud_state` used to push an empty
tree and report success). On a push conflict the script aborts the rebase, resets to
origin, and rebuilds each owned path from three versions — the checkout commit (the base;
there is no snapshot step any more), the run's own commit, and origin's — by the file's own
rule (the table is in §5, beside the writers); a second conflict in the same run is judged
against the first merge, not the checkout. After a *clean* rebase only the files git
actually rewrote are re-gated, and a rewrite that does not parse goes through the per-file
merge instead of being pushed.

Why per-key for the stamps: on 2026-08-24 listing-hunt stamped `repair` at 22:12
(`82d425c`); auto-expand, checked out at 20:00, hit a conflict at 23:40 and its block
copied its own `pipeline_stages.json` back over origin's, deleting the key (`0b41823`,
author expand-bot) — the mail then said `repair: never run`. Same on 08-23 (`33d0306` →
`bab228f`). `tests/rehearse_infra.py --conflict` replays that night on temporary repos and
asserts origin keeps both stamps, both registry writes and the refresh's deliberate
deletion; the unit guards are the `lane: infra` block at the end of `tests/test_units.py`.

### When a run breaks, the mail says so

The alarm channel *is* the email, so a run that produced no email used to be silent: the
relay dedups on the content hash of `digests/latest.md`, and a crashed digest left
yesterday's file in place. Four mechanisms, all in `daily-digest.yml` + `pipeline/run.py`:

1. **A failed pre-step is a bold line.** Every step has an `id`; the pre-steps
   (discovery, telegram, liveness, probe, the two JD backfills, the census) are
   `continue-on-error` *without* the old `|| echo "… skipped"` (which made a crash read
   as success), and the pipeline step receives `WORKFLOW_STEP_OUTCOMES: ${{ toJSON(steps) }}`
   → `- **Stages:** workflow step 'liveness' failure before the pipeline ran — its output
   is missing from this digest; see the run log`, above the fold.
2. **Every stage alarms, not two.** `run.py` reads `stages.alarms` for `collect`,
   `enrich`, `repair` (1 day), `expand` (1 day) and `publish` (1 day — *yesterday's digest
   never completed*), closing BACKLOG 114; the health and registry excepts append an alarm
   instead of only writing stderr.
3. **A lost digest becomes a mailed notice.** The last step, `persist_state.py outcome
   --commit` (`if: always()`), reads `toJSON(steps)`, `job.status`, out/crash.json (written
   by `run.py main()` with the phase — fetch / classify / board health / role record /
   company intel / render / write — and the traceback tail) and the stage stamps. When the
   `pipeline`, `gate` or `persist` step failed, the job was cancelled before persist
   succeeded, or the job is red and the pipeline never ran (skipped behind a failed
   checkout / setup / CLI install — the CLI install is `continue-on-error` for that reason,
   the classifier degrades to `missing` and says so), it writes a dated `digests/latest.md`:
   `# ⚠️ No digest for <date> — the daily run failed` · *Failed at* `pipeline` · phase ·
   exception · run link · what did run tonight · whether a digest was built (and that
   nothing was marked sent) · that yesterday's board stays published · whether the caches
   were saved. It commits that file and `cloud_state/last_run.json` **alone, from a fresh
   worktree of `origin/master`**, so a half-merged registry can never ride along — and
   **delivery decides, not step outcomes**: when origin's `latest.md` already carries a
   digest headed with today's date (this run's, or an earlier run's the same day), no
   notice is written, whatever went red (a persist step that pushed the digest and then
   refused one file; a failed board publish; a `mark_sent` crash — those are tomorrow's
   line). Every field the notice prints is escaped the way `digest.py` escapes the mail (an
   exception message can carry a scraped page). `tests/rehearse_infra.py --notice` prints it.
4. **A step after the pipeline reaches tomorrow's mail.** `cloud_state/last_run.json`
   (written only when something failed: date, status, failed steps, run URL) → the next
   digest's `Stages:` line: `the 2026-08-25 run failure: publish (failure) — <url>`.
   Two days old is silent.

`mark_sent` stays before the persist step on purpose: the `sent` marks (sqlite + the
ledger mirror) and `digests/latest.md` land in **one** commit, so a failed persist burns
nothing; the one window left is the relay itself (BACKLOG 6). A `mark_sent` crash is
`continue-on-error` (a re-emailed role beats a withheld digest) and reaches tomorrow's mail
through `cloud_state/last_run.json`.

**Reading a run.** The digest log is grouped by phase (`::group::`), every failure is an
annotation (`::error::pipeline crashed in phase 'classify …': KeyError: …`,
`::error::invariant: …`), and the run page's summary carries the mail's alarm lines, the
audit counts and one stage stamp per line (`$GITHUB_STEP_SUMMARY`; every other workflow
appends `python -m pipeline.stages`). Locally, `python tests/rehearse_infra.py --mail`
runs three boards with a failed pre-step, a stale `publish` stamp and yesterday's failed
publish injected, and `--golden <rev>` proves the mail differs from `<rev>` only in the
alarm lines (2026-08-25 against `dcca442`: exactly `+ - **Stages:** repair never ran`).

## 5. State files
*lane: `infra` (who writes what) — `shared` for everyone who reads them*

| file | contents | written by |
|---|---|---|
| `companies.csv` | the coverage registry + verdicts | resolvers/audits (see rule below) |
| `cloud_state/seen.db` | tables: `sent` (email dedup), `matched` (job-board rows), `llm_cache` (role judgments), `company_info` (blurbs), `firmographics` | the digest (and `enrich_matched_jd.py` inside the same job) — the one cloud writer, so a conflict day keeps the run's file whole |
| `cloud_state/roles.jsonl`, `roles_text.jsonl` | the role record (§7c) | the digest |
| `scraped_cache.json` | rendered scrape-row jobs (+enriched JDs) | scrape-refresh, enrich, auto-expand, retry-unreachable, audit-coverage, listing-hunt — merged per company on a conflict |
| `discovered_cache.json` | discovery-net jobs (21-day TTL at read) | discovery_daily, discovery_telegram — merged by `(company, title)` on a conflict |
| `research_companies.json` | resolution queue (names + seed URLs) | discovery bridges; read by auto-expand — merged by name on a conflict |
| `cloud_state/telegram_seen.json` | last message id per channel | discovery_telegram |
| `cloud_state/candidate_probe.json` | probe signal baselines | probe_candidates |
| `cloud_state/stale.json` | per-company health verdicts: `fetch-error`, `regressed-to-zero`, `empty-board`, `misconfig-scrape-on-ats` | pipeline/health.py during digest, and self-heal's Monday `health_check.py` — merged per company on a conflict (the Monday copy was never committed until 2026-08-25) |
| `cloud_state/health_baseline.json` | **all-time high-water** job count per company (monotonic — never decreases, which is why `regressed-to-zero` latches) | pipeline/health.py (digest) and self-heal's Monday `health_check.py` — merged per company on a conflict |
| `cloud_state/resolve_attempts.json` | self-heal retry throttle (weekly; 5 strikes → abandoned) | resolve_broken.py |
| `cloud_state/scrape_rot.json` | consecutive empty/error days per scrape row, with the last error code / HTTP status (§5a) | refresh_scrape_cache.py |
| `cloud_state/scan_seen.json` | the liveness re-scan's rotation | scan_dead_domains (digest; the Sunday audit commits it since 2026-08-25 — BACKLOG 17) |
| `cloud_state/firmographics.json` | **the shared, git-mergeable export of the `firmographics` table.** sqlite cannot be merged, so this text file is what the local and cloud stores converge through; the digest reads sqlite ∪ this file (fresher `as_of` wins) and writes the union back | `research_firmographics.py --export`, `pipeline/run.py` — merged per company on a conflict |
| `cloud_state/pipeline_stages.json` | which nightly stage last finished and how much it did (`pipeline/stages.py`) — the digest alarms in the mail when a prerequisite stage did not run today | listing-hunt (`repair`), scrape-refresh (`collect`, with its counts), auto-expand (`expand`), the digest (`enrich` via `jdfill.record_enrich`, `publish`) — **merged per stage key on a conflict** (§4; until 2026-08-25 a conflict deleted other jobs' stamps) |
| `cloud_state/last_run.json` | the digest job's outcome when something failed: date, status, failed steps, run URL (§4) | `persist_state.py outcome`, from the digest's last step |
| `cloud_state/registry_census.json`, `registry_alarms.json`, `registry_ladder.json` | the registry health census, its alarms, the resolution-ladder probe | `registry_health.py` (digest `--census`; listing-hunt `--ladder`) |
| `cloud_state/source_health.json` | per discovery source: records returned this run, and the last day it returned any (`pipeline/sources.py`). A source that goes quiet is a workflow warning AND a line in the digest audit — Indeed returned zero for five days unnoticed | discovery_daily, discovery_telegram |
| `digests/latest.md`, `docs/index.html`, `docs/archive.html` | the email, the board, the archive — what the relay and the board repo read | the digest (`latest.md` is also the failure notice on a lost day, §4) |
| `out/` (gitignored) | `digest-<date>.{md,html,txt,json}`, crash.json on a crash, `rehearse-*/` | pipeline.run, the rehearsal scripts |
| `state/` (gitignored) | resume markers (audit done-list). Written in the cloud too but **never committed**, so the Sunday audit re-audits every parked row from scratch (a SerpApi budget fact) | audit/local runs |

**How each file is rebuilt on a push conflict** (`persist_state.py table`):

| path | rule |
|---|---|
| `companies.csv` | rows by company name, note segments unioned per tool (`merge_csv_rows.merge`); a segment the run deleted on purpose (`probe-woken` strips the hunt/triage stamps) stays deleted unless origin rewrote it (BACKLOG 15/60) |
| `scraped_cache.json`, `cloud_state/firmographics.json`, `health_baseline.json`, `stale.json`, `scan_seen.json` | per company key (`merge_json_cache.merge`); a key the run dropped and origin left alone stays dropped (BACKLOG 95) — unless the run dropped more than a quarter of the base (a broken run, not deletions: kept, with a warning); a corrupt side yields to the other, never `{}` |
| `cloud_state/pipeline_stages.json` | per stage key; the side that did not touch a stage yields, both touched → the newer `finished_at`; a stamp is never deleted |
| `discovered_cache.json`, `research_companies.json` | JSON lists merged by `(company, title)` / `name` (BACKLOG 10/30) |
| everything else the job owns (`seen.db`, `roles*.jsonl`, `digests/latest.md`, `docs/*.html`, the per-workflow state files) | the run's bytes — one cloud writer each; an unlisted path is taken the same way with a `::warning::` |

The writers column is the `--own` list of each workflow's persist step (`grep -n -- --own
.github/workflows/*.yml`); `test_every_path_a_workflow_owns_has_a_persist_strategy` fails
when a workflow names a path the table above does not know. (The single-writer and
commit-together rules live with the csv schema in §2.)

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
  Until 2026-08-25 a push CONFLICT undid a night's deletions (empties, expired carries,
  parks) — `merge_json_cache.py` kept every company key origin still had; the deletion
  rule now stands (BACKLOG 95, `infra`; `tests/rehearse_infra.py --conflict` proves it).

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
   It returns the decision, path (`keyword` / `keyword_nollm` / `llm` / `llm_cache` /
   `llm_failed_fallback` / `llm_skipped`) and reason (§7b). A cached role judgment lives in
   `cloud_state/seen.db` → `llm_cache`, column `title_key`, key `v2|<company>|<title>|jd`
   (judged with the description) or `|bare` (title only; re-judged once text arrives), with
   the 2026-08-24 rows still under the legacy `company|title`; delete the row to force a
   re-judgment. The step log carries the LLM's one-line reason for every fresh verdict
   (`[llm] company | title -> YES/NO: …`).
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
  **33 of the 72 workflow steps are `continue-on-error`, so a green run can still hide a
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

## 7. Company intel — the facts and the blurb on every card
*lane: `company-intel`*

Two things about the employer render on every board, archive and email card: the **facts**
chips (sector · stage · ~employees · founded · Israel centre) and the two-sentence **About**
blurb. Three files: `pipeline/firmographics.py` (the record, its identity, the `claude` seam,
the shared export), `pipeline/company_info.py` (the blurb prompt and `derive_blurb`), and
`pipeline/company_intel.py` (the digest hook `enrich_for_run` — one call produces both — and
`audit_lines`, the one line in the mail's run audit that says what it did). Everything below was re-verified on 2026-08-24 (`docs/sessions/2026-08-24-company-intel.md`
has the commands); a number without a command next to it is a number to distrust.

### The record

One JSON object per company, from `research_company` (a `claude -p --allowedTools WebSearch`
call, **40–80 s** measured at 3 workers on 2026-08-24; the 240 s timeout does trip), validated
before caching:

```json
{"sector": "cybersecurity", "sub_sector": "cloud security (CNAPP)",
 "stage": "acquired-by-bigtech",   // enum: public | acquired-by-bigtech | growth-private | early-private | private-enterprise
 "stage_note": "acquired by Google $32B, closed 2026-03",
 "size_band": "L",                 // enum: S <200 | M 200-1000 | L 1000-5000 | XL >5000 — always band_for(employees_global)
 "employees_global": 3148, "founded": 2020,   // founded accepts 1600..today (Barclays=1690)
 "business_model": "SaaS per cloud workload", "customer_type": "enterprises",
 "il_center": "Tel Aviv", "as_of": "2026-08-22",
 "employees_source": "linkedin", "employees_as_of": "2026-08-22"}   // present when a fill pass touched it
```

**Validation: reject, never repair.** No sector, an out-of-enum stage, an implausible number →
`_coerce` returns None and nothing is cached. `growth-private` vs `private-enterprise` is the
funding model, not size or age (Stripe is growth-private; Bosch, EY, a bank are
private-enterprise). Anything that writes `employees_global` re-derives `size_band` with
`band_for` — 0 of 940 records contradict it (`python -c "import json;from pipeline.firmographics import band_for as b;d=json.load(open('cloud_state/firmographics.json',encoding='utf-8'));print(sum(1 for r in d.values() if r.get('employees_global') and b(r['employees_global'])!=r['size_band']))"`).

**Identity.** `firmographics.identity_key` (not `store._norm_company`, which strips one
suffix) folds repeated suffixes, `X Israel` site-forms and a small alias map, and is what every
targeting decision, join and display lookup uses. The export still holds **29 identity groups
with more than one record** (AMD / AMD Israel, Intel / Intel Corporation / Intel Israel, …):
`python -c "import json,collections;from pipeline.firmographics import identity_key as k;d=json.load(open('cloud_state/firmographics.json',encoding='utf-8'));g=collections.defaultdict(list);[g[k(c)].append(c) for c in d];print(sum(1 for v in g.values() if len(v)>1))"`.
They are researched-once legacies and cost nothing now; a group answers for a board name through
`display_index` — the canonical name first ("Amazon", not the alias "AWS" nor the suffixed
"Dell Technologies"), then a non-site-form ("Dell Technologies" over "Dell Israel"), then the
fullest record — so a fill pass touching a site record cannot promote it to speak for the
group, and the answer no longer depends on sort order. Merging them is a data change, filed in
`docs/BACKLOG.md`. Leaked job titles ("Sql developer - X", "my team") and bare category words
("AppSec", "DevOps") are refused by `looks_like_junk` before any call; a partial-word title
("Senior Data Analyst") still passes (BACKLOG, `company-intel`).

### Where the data lives — one file, two sqlite caches

`cloud_state/firmographics.json` is the record of truth: sorted JSON that git merges line by
line. `cloud_state/seen.db` (the runner) and the gitignored `state/seen.db` (the owner's laptop)
are caches. Every reader and both writers go through `union_store` (export ∪ sqlite, `merge`
per company: later `as_of` wins, a same-day tie goes to the record with more filled fields, and
the winner inherits the loser's non-empty fields — an employee fill that never bumps `as_of`
cannot lose, and a re-research that re-found no `founded` cannot erase the one we had).
`load_shared_status` tells `ok` from `missing` from `corrupt`; a corrupt file is reported in the
mail and **never overwritten** — the old `{}`-on-any-error would have replaced 940 records with
the 921 in sqlite (rehearsed 2026-08-24, case d). `save_shared` writes through a per-process
temp name (the digest and the local chain both write this file on the laptop) and returns
whether the file now holds the union; an unwritten export is `export NOT written (…)` in the
mail. A scoped local run (`--only`/`--limit`) is produce-only: it writes neither the export
nor the sqlite cache.

**Who commits the file.** The cloud digest, every morning (`daily-digest.yml` stages
`cloud_state/`). The Windows chain below writes it and does **not** commit it — the previous
version of this section said the chain "publishes automatically"; the record showed HEAD at 924
records against 940 on disk, with the last export commit made by hand (`git log --format='%h %an %s' -- cloud_state/firmographics.json`).

### The digest hook (the cloud side — the writer of record)

`pipeline/run.py` makes one call, `company_intel.enrich_for_run(st, board_jobs=…, email_jobs=…,
all_companies=…, run_date=…, use_llm=…, scoped=…, profiles_path=…)`, which returns
`(company_info, firmo_display, report)` and **never raises** — a locked sqlite used to take the
whole morning's email and board down with it. In order:

1. read the export (status), seed sqlite from it (`sync_store`, idempotent), build the union;
   start the ONE wall clock — `FIRMO_TIME_BUDGET_MIN` (15) covers blurbs and research together
   (a research-only budget let 30 blurbs run 45 minutes before the budget started);
2. **blurbs** for board companies without one, one per identity ("Meta" and "Meta Israel" had
   both paid): `company_profiles.json` (hand-written; filtered through the same junk rule as a
   generated blurb) > sqlite > one `claude -p` each, at most `BLURB_MAX_PER_RUN` (30), each
   call clamped to the minutes left. An empty answer (UNKNOWN / junk / CLI text) is cached as
   `''` and retried **monthly**, not every morning (5 names were re-bought daily for a week);
   three empties in a row stop the loop, and if nothing at all was written that is a blurb
   outage: the three `''` rows are taken back, research is skipped, the mail warns;
3. **research** for board companies with no record under any identity: the email's companies
   first, then the board by live-role count, at most `FIRMO_MAX_PER_RUN` (5) calls inside what
   is left of the clock, each call clamped to it. A name failure (unknown / prose / rejected)
   is a `firmo_failed` strike and a weekly retry; an infrastructure failure
   (`ResearchUnavailable`: CLI missing, non-zero exit, timeout) stops both loops and records
   **nothing**; `SOFT_OUTAGE_MIN_FAILS` (3) failures with no success — checked inside the loop —
   is an outage too, no strikes. With fewer than three candidates a soft outage is
   indistinguishable from bad names: the names are struck (weekly retry) and the mail warns;
4. `firmo_display` for every company ever matched, looked up by identity, each record passed
   through `chip_safe` (`il_center` cut to its first `;` clause, ≤48 chars, no dangling
   parenthesis — 426 of 940 stored answers are paragraphs; the stored text is untouched);
5. a company with facts but no blurb gets `company_info.derive_blurb` — the facts read as prose,
   free, never cached, replaced the day a real blurb arrives;
6. publish the union back to the export, unless the run is scoped or the export was corrupt.

Env knobs, defaults = today's behaviour: `FIRMO_MAX_PER_RUN`, `FIRMO_TIME_BUDGET_MIN`,
`BLURB_MAX_PER_RUN`. Worst case per morning: 35 calls, 15 minutes. All three consumers of the
CLI (`research_company`, `summarize_company`, `fill_employees_llm.lookup`) go through one seam,
`firmographics._claude` — `shell` only on Windows (the old `shell=True` on Linux ran a bare
`claude`; on Windows the timeout is advisory, it kills `cmd.exe` not its child), and
`extract_json` takes the first *substantive* JSON object anywhere in the answer (the old greedy
`\{.*\}` turned a valid answer with one brace in its preamble into a weekly strike; a restated
`{"unknown": true}` before the real answer is skipped).

### What the mail says

`audit_lines(report)` is one `- **Company intel:** …` line in the run audit (markdown, text
and HTML) plus a `::warning::company-intel …` in the workflow log for anything abnormal. The
arithmetic reconciles: `researched + failed + skipped + waiting = candidates`.

| state | line |
|---|---|
| nothing to do | `all 54 board companies profiled (1 more unprofiled: research failed, weekly retry) · blurbs: 0 asked, 0 written · export 940 records, newest 2026-08-24, 20 newer than the store` |
| work done | `2 of 54 board companies unprofiled (cap 5/run, budget 15m): 2 researched, 0 failed · blurbs: 2 asked, 2 written, 1 derived from facts · export …` |
| budget | `… 2 researched, 3 skipped (budget 15m spent) · blurbs: 12 asked, 11 written, 1 empty, 18 skipped (budget)` |
| names failed | `… 0 researched, 2 failed … · blurbs: 2 asked, 0 written, 2 empty` + warning `every research answer failed (2 of 2) — below the 3-fail outage rule, so the names were struck` |
| CLI down | `claude unavailable after 0 blurbs calls (Not logged in …) — 2 unprofiled board companies wait for the next run` + warning, **no strikes** |
| soft outage | `research soft outage suspected: every answer failed and none succeeded — stopped, no strikes recorded` / `blurb soft outage suspected: three empty answers and none written — stopped, nothing cached, research skipped` + warning |
| export | `export MISSING at …` (recreated) / `export CORRUPT at … — cards render from sqlite only (921 records); file left untouched` / `export NOT written (PermissionError: …)` + warning |
| hook crashed | `company intel FAILED (OperationalError: database is locked) — cards render from whatever was assembled` + warning |
| `--no-llm` | `research off (--no-llm); all 55 board companies profiled · blurbs: 0 asked, 0 written · …` |

`N newer than the store` is the number of export records the runner's sqlite lacked or held an
older copy of — after the daily seed it is the count of profiles that arrived from outside the
cloud since yesterday, i.e. the only evidence in the mail that the Windows chain ran. Every
line above was produced by the rehearsal driver on 2026-08-24 against scratch copies with a
fake `claude` on PATH (`docs/sessions/2026-08-24-company-intel.md`, "Rehearsal").

### The local chain (optional accelerator, proposed for retirement)

The Windows scheduled task `IsraeliJobs-Firmographics` runs `run_firmo_chain.cmd` every 6 h
(03/09/15/21 local; §4 notes it is invisible to Actions): `research_firmographics.py --workers 3
--refresh-days 180` (all ~883 active registry rows ∪ matched, not just the board; 20 stale
refreshes per run once records pass 180 days — none do before 2027-02) → `bd_employees.py`
(LinkedIn via Bright Data, 1 credit/page, null counts only — 0 today) → `fill_employees_llm.py`
(web verify for nulls and suspect LinkedIn matches) → `--export` → `firmo_health_check.py`
(exit 1 + a Desktop alert file after 48 h without a trustworthy run). Since 2026-08-24 the
chain reads and writes the **union**: it no longer re-buys a company the cloud researched that
morning (Phoenix Financial and SHILA Medical were, on 2026-08-24 — two of the day's four
researched) and its `--export` no longer deletes the cloud's records (19 were at risk that
evening). It still spends the shared subscription on ~800 registry rows that never render;
only the board needs facts, and the digest hook covers the board on its own. Retirement is a
`docs/BACKLOG.md` item with the condition (seven mornings of a healthy mail line first).

### Consumption

`company_type_analysis.py` joins matched jobs (default db: `state/cloud_seen_fetch.db` when the
chain has fetched it, else `cloud_state/seen.db`; both printed) with the committed export
(`--firmo` to override — it used to read the gitignored `state/firmographics.json`, absent in the
cloud), runs `pipeline/roleprofile.py::extract` per job and aggregates requirement stats along
sector / stage / size_band → `out/company_type_analysis.{json,md}`. Free-text sectors collapse
through `primary_sector()`'s alias table there; extend the table, don't edit stored records.

### Guards and how to rehearse

`tests/test_company_intel.py` (55 cases, one per shipped bug or claim above; no test spawns
`claude` or touches `cloud_state/`; 17 of 18 mutations in `tests/fixtures/company_intel/mutations.json`
are killed by them, the 18th is an equivalent mutant). To rehearse tomorrow's digest without
spending anything: `python tests/rehearse_company_intel.py --case json --hole "X" --only "X,Wix"`
— it copies the stores to a scratch dir, puts the fake `claude` shim
(`tests/fixtures/company_intel/claude.cmd`, cases `a|json|unknown|prose|fail|sleep`) first on
PATH, points `firmographics.SHARED_EXPORT` at the copy, runs `pipeline.run.run(...)` and
asserts `git status` is unchanged afterwards.

### Known limitations

- Bare category words are refused exactly (`CATEGORY_NAMES`); a name that is entirely role
  words ("Senior Data Analyst") still passes `looks_like_junk` (BACKLOG, `company-intel`).
- Ambiguous discovery names are researched with the job's text as context in the digest; the
  bulk script passes no context.
- Employee counts for acquired subsidiaries are the unit's approximate headcount (see
  `employees_source`) — don't sum them with parent-company records.
- The researcher keeps finding listed companies dead or absorbed (Alike Health, Syte, Sckipio,
  SimilarTech, NanoLock, Rewire R&D); that knowledge lands only in the record — rows are not
  auto-parked from it (BACKLOG "Let company-death knowledge flow back").
- `private-enterprise` renders as the raw enum on a card (`_STAGE_LABEL` in `pipeline/digest.py`
  has no entry; 44 records) — `render` lane, BACKLOG.

## 7a. Job-description text — the jd-text layer
*lane: `jd-text` — `pipeline/jdfill.py` (the library), `enrich_scrape_jd.py`, `enrich_matched_jd.py`*

**What it is for.** The classifier's LLM tier reads the description and judges; the board's
requirements, skills, years, degree and every tag are computed from it (§6, `docs/TAGGING.md`).
A role without text is judged on its title and renders a bare card. Four list endpoints carry
no description at all — `workday` 66 active rows, `smartrecruiters` 16, `bamboohr` 11,
Microsoft's Eightfold search 1 (re-derived 2026-08-24:
`python -c "import csv,collections;print(collections.Counter(r['ats_platform'] for r in csv.DictReader(open('companies.csv',encoding='utf-8-sig')) if r['active']=='true'))"`;
the `eightfold`/`phenom` fetchers return `""` too but have 0 rows) — and scrape cards and
discovery cards arrive empty as well.

**One ladder, three callers** (`pipeline.jdfill.fetch_jd`):

```
native JSON ──▶ plain HTML ──▶ Bright Data Web Unlocker      (each rung only if the previous failed)
 workday cxs      extract_jd     drivers only; never inline; never for a search/list URL
 smartrecruiters  (two section
 bamboohr          markers,      every outcome carries a REASON: ok · shell · no-markers ·
 comeet            role-start    http-NNN · timeout · not-a-job-url · bd-unavailable · bd-capped
 greenhouse        trim)         transient (timeout / 5xx / bd-*) ⇒ retry tomorrow, else in 7 days
```

| caller | when | what it walks | Bright Data |
|---|---|---|---|
| `JDFiller` (`pipeline/run.py`, before `seniority.classify`) | 05:00, in the digest | every Israel-matched role whose title the classifier could accept, `JDFILL_TIME_BUDGET_MIN` (25) | never |
| `enrich_scrape_jd.py` | 05:00, before the pipeline | description-less, relevance-gated, non-chrome jobs in `scraped_cache.json` | `JD_ENRICH_BD_CAP` 400, `JD_ENRICH_TIME_BUDGET_MIN` 25 |
| `enrich_matched_jd.py` | 05:00, before the pipeline | every `matched` row under 300 chars, any age, any source | `MATCHED_JD_BD_CAP` 250, `MATCHED_JD_TIME_BUDGET_MIN` 20 (yml) |

The native rung is derived from the **public job URL alone** (host + path; the `matched`
table has no platform column and a job dict has no `api_url`): Workday
`/wday/cxs/{host label}/{site}/job/…` (tenant == host label on all 83 registry rows —
`test_native_url_is_derived_from_the_public_url_alone`), SmartRecruiters
`api.smartrecruiters.com/v1/companies/{token}/postings/{id}`, BambooHR `/careers/{id}/detail`,
comeet.com pages (the posting is embedded as JSON sections), Greenhouse
`boards-api…/boards/{slug}/jobs/{id}` incl. `?gh_jid=` embeds (slug: the registry's greenhouse
token for that company, then the name, then the host label). Measured live 2026-08-24 with
`python <scratch>/smoke.py` (session record): Workday 4,616 chars, Comeet 4,334, Greenhouse
6,000, SmartRecruiters 2,799, BambooHR 3,192, each in ≤ 1.2 s and 0 credits. **Why it had to
exist:** to a plain GET the Workday job page is 17,099 bytes of script and `html_to_text()`
returns **0 characters**, and Bright Data refuses the host outright
(`x-brd-error-code: policy_20140` — robots.txt, no-KYC residential) — so before this rung
those roles could never be filled by anything, and the Unlocker credits spent on them were
wasted. Eightfold's `/api/apply/v2/jobs/{id}?domain=` also answered (Microsoft, 7.9 KB) but is
not wired: 1 row, and the domain is not in the URL. Phenom: 0 rows, **unverified**.

**What each morning's numbers mean.** The `enrich` stage stamp
(`cloud_state/pipeline_stages.json`) is written by the two drivers through
`jdfill.record_enrich`, which UNION-merges into today's stamp (two scripts, one stamp);
its keys appear verbatim in the mail's `Stage order:` line and its `alarm` in the bold
`- **Stages:**` line (`stages.alarms("enrich")`, read by `pipeline/run.py` right after the
fetch loop, next to the `collect` alarm). The workflow's `if: always()` step no longer stamps
(that erased the counts — same defect the scraper lane fixed for `collect`); it calls
`record_enrich()` with no arguments, which only names a driver whose `<name>_ran=1` is
missing from today's stamp (`alarm=no-report(scrape)`) — the line you get when a script died
at import behind `|| echo`, which no `except` can see.

| in the mail | meaning |
|---|---|
| `enrich: <date> (TODAY) scrape_filled=7 scrape_bd=7 scrape_fail=6 scrape_bd_unavailable=0 scrape_cooldown=14 matched_filled=0 …` | a normal morning; compare with the baseline below |
| `- **Stages:** enrich bd-unavailable(http-401)` | the Unlocker key is dead / the pool is gone; the roles that needed it were stamped `transient` and retry tomorrow — nothing was parked for a week |
| `- **Stages:** enrich jd-massfail(shell x12)` | ≥10 tried, 0 filled — a broken run, not a measurement (rule 2); the top reason is named (`bd-unavailable` takes precedence when both hold) |
| `- **Stages:** enrich crash:DatabaseError` | a driver raised; the step log has the traceback |
| `- **Stages:** enrich no-report(scrape,matched)` | the named driver(s) never reached their stamp today (import death, kill, timeout); the stamp's `date` is left where it was, so `Stage order:` still shows when the layer last really ran |
| `- **Stages:** inline jd-fill 0/153 — every fetch failed (workday shell 90, …)` | the inline path failed wholesale inside the digest |
| `jd-fill: 93/153 descriptions fetched inline (native 80, html 13); failed: workday shell 40 …` | step log only (`run.py`); per platform × reason. **Not in the markdown mail** — `docs/BACKLOG.md` 106 |

**Baseline to compare tomorrow against** (`gh run view 32694484572 --log`, 2026-08-24, before
this layer existed): inline `jd-fill: 93/153`; scrape backfill `7 filled (7 via Bright Data),
6 unfetchable, 14 in cooldown`; matched backfill `0 filled (4 via Bright Data), 4 unfetchable`
— those 4 credits went to URLs that are not job pages (two Meta *search* pages, an Indeed
page, a `?gh_jid=` embed), which `is_job_url` now refuses before the Unlocker. Where the value
is: the native rung covers **0 of the 20** jobs the scrape backfill will attempt (they are
comeet 6, shopify 5, nebius 3 …; comeet and `gh_jid` are covered by their own rungs) and **1
of the 7** short `matched` rows; its measurable value is the **inline** path — the 60 roles a
day that were judged on a bare title.

**Cooldown.** A stamp is `YYYY-MM-DD` (page read, no JD: retry after 7 days — unchanged) or
`YYYY-MM-DD transient` (retry after 1 day: timeout, 5xx, Unlocker unavailable/capped/gateway
5xx). A URL with a native rung ignores the cooldown — one JSON GET is cheaper than the
bookkeeping, and rows stamped before the rung existed would otherwise wait a week. A
search/list URL is `unfillable`, counted apart from failures. `refresh_scrape_cache._carry_jd`
copies the value verbatim across the nightly rebuild; `--cooldown-days N` on either driver is
the one dial. Per-URL patience: 15 s inline, 25 s in the backfills. The Unlocker
(`jdfill.Unlocker`) stops the run on a 401/402/403 *from the API itself* or a missing key
(account-level, cannot be caused by a target page — measured: a bad token is a real 401),
treats a 200 with `x-brd-error-code` as that URL's failure (`reject_block` is a walled page,
`policy_*` a refused host), and trips a breaker after 5 consecutive failures with no success
in the run. `JD_BD=0` disables it for a local run — necessary, because `load_secrets()`
re-arms the keys from `secrets.env`, so `env -u BRIGHTDATA_API_KEY` alone spends credits.

**Rehearse it without side effects:**

```bash
cp scraped_cache.json /tmp/c.json && cp cloud_state/seen.db /tmp/s.db
JD_BD=0 python enrich_scrape_jd.py --cache /tmp/c.json --dry-run
JD_BD=0 python enrich_matched_jd.py --db /tmp/s.db --cooldown-days 0 --dry-run
JDFILL=1 python -m pipeline.run --only "Palo Alto Networks,Wix,Bringoz,Port.io" --no-llm --db /tmp/s.db
```
A driver pointed at a copy (`--cache`/`--db` not the default) stamps `<copy>.stages.json`
beside it, never the repo's `cloud_state/pipeline_stages.json` (`JD_STAGES_OUT` overrides
either way) — an attacker session found the first version of this layer writing a scratch
run's counts into the real stamp, which the mail would have quoted. Guards: the `jd-text
lane, 2026-08-24` block of `tests/test_units.py` (21 tests, incl. the mutation-sweep set),
`test_a_re_sighting_without_a_description_never_erases_the_stored_one` (the store never
downgrades a description), `test_the_jd_filler_only_spends_a_fetch_on_a_role_that_could_be_accepted`.

**Known limitations** (all in `docs/BACKLOG.md`, with owners): the markdown mail does not
print the inline count (106); a role rejected on a bare title keeps its cached `llm_cache`
verdict after the text arrives (107); `merge_json_cache` merges per company, so on a conflict
day the enrichment's copy of a company wins over origin's newer cards (108); 6 of the 7
short `matched` rows carry URLs that are not job pages, acquired from discovery sources (109);
`bd_rescue.unlock` still discards the status the Unlocker reports (110); the aggregator loop
in `run.py` (dark) has no inline fill (111); the two drivers could be one module (112).

## 7b. Classification — which roles qualify, and how the LLM tier is bounded
*lane: `classifier` — `pipeline/israel.py`, `pipeline/seniority.py`, the `llm_cache` table's key scheme*

Step 5 of the flow. Every Israel-matched posting goes through two deterministic gates and,
for the ambiguous residue, one bounded LLM call. Written 2026-08-24 and attacked the same day
(five Opus reviewers, then three confirmers — `docs/sessions/2026-08-24-classifier.md`).
**Start here — rehearse tomorrow's classifier morning without spending anything:**

```bash
python tests/rehearse_classifier.py --case fail --only "Fiverr,Wix,Similarweb,Taboola"
#   --case yes|no|all_no|all_yes|is_error|no_structured|prose_before_json|unknown_flag|
#          fail|rate_limit|sleep|flaky   (12 fake-CLI modes) | nollm (the fake never runs)
```
It copies `seen.db` to a scratch dir, puts `tests/fixtures/classifier/` first on PATH, runs
`pipeline.run` scoped, and prints PASS/FAIL per check (paths reconcile, attempts ≥ llm+failed,
the predicted `Stages:` text, the cache-row delta, the full argv incl. the rules text, cwd ≠
repo, `git status` unchanged; the argv/cwd checks only when the fake was called). Every
number below carries the command that re-derives it, or says it does not.

### The two gates, in order

**Gate 1 — is it in Israel?** `israel.is_israel_job(job)` is **per posting, never per
company**: an explicit country code decides (`IL`/`ISR` yes, anything else no — `IS`/`ISL`
are Iceland), and only when the code is blank does a place-name scan of `location` + `url`
decide. Two lists, Latin `_IL_PLACES` and Hebrew `_IL_PLACES_HE`; a space in a name also
matches a hyphen, apostrophes and the Hebrew maqaf are spelling (`Kfar-Saba`, `Giv'atayim`,
`תל־אביב` all pass), a digit after a name blocks it (`lod3BakeYZ7` does not pass) but not before (`u0022Israel`, a mangled feed, does). The scraper's `ISRAEL_LOC` is
derived from both lists (`check_invariants` G). So a multinational with an Israeli branch
passes on the posting's own location (the Workday / Eightfold / Phenom / `custom_json`
fetchers are `israel_scoped`: they ask the board for Israel), an Israeli-only employer passes
because its postings name the city or district, and a scrape row is pre-filtered at scrape
time (a location-less card counts only when the listing URL is Israel-filtered, or under
`SCRAPE_ASSUME_IL` for rows the resolvers pre-vetted). There is **no company-level Israel
flag** — `companies.csv` has six columns and none is one — and the measurement says none is
needed:

> 70 random active API rows (comeet/greenhouse/ashby/lever/workable/smartrecruiters/recruitee/
> breezy/bamboohr), 2026-08-24: **3,370 postings → 674 pass**; dropped 1,493 on a non-IL
> country code, 601 remote/hybrid, 599 other cities, 3 with no location. The only "bare
> Remote/Hybrid, no country" employers were Cloudflare (296 — greenhouse's `location.name` is
> a work-mode there, the office lives in `offices[]`; BACKLOG 118) and Aim Security (6, US
> sales); the genuine loss class (an Israeli employer's bare "Remote") was ≈5 postings, 0.15 %.
> The sampling script is in the session note; the wave-1 reviewer's independent live pull of
> 41 boards (1,401 jobs → 187 Israel) found **0 false negatives and 0 false positives**.
> Scrape rows: `python -c "import json;from pipeline import israel;d=json.load(open('scraped_cache.json',encoding='utf-8'));j=[x for v in d.values() for x in v];print(len(j),sum(israel.is_israel_job(x) for x in j))"` → `1225 1221` (the 4 dropped are Siemens rows whose location is the junk `lod3BakeYZ7`).

Known and accepted: `Nazareth, PA` and `Eilat Street, Brooklyn` pass when a feed sends no
country code (0 such postings in 3,723 today); bare `acre` is deliberately absent (US street
addresses). Latin names the Hebrew list had and this one lacked (Yavne, Afula, Tiberias, Eilat,
Dimona, Safed/Tzfat, Akko, Nahariya), six districts in seven spellings, and 23 towns — 40 entries — were added
on 2026-08-24 (`test_the_latin_place_list_has_the_hebrew_lists_cities`).

**Gate 2 — does it qualify?** `seniority` decides from the lowercased **title** first:

| title says | decision | `path` |
|---|---|---|
| engineering / ML / infra / PM / finance (FP&A, actuary) / a non-data "<x> analyst" (`_HARD_EXCLUDE`, `_HARD_EXCLUDE_MISC`) — **unless a strong analyst phrase is also present**, then the LLM decides ("Business Analyst, Software Solutions") | reject | `keyword` |
| no analytics signal at all (`_SIGNAL`, Hebrew included) | reject | `keyword` |
| junior / intern / student / entry-level (`_JUNIOR`, Hebrew included) | reject | `keyword` |
| a strong analyst title **and** a senior marker (`_STRONG` + `_SENIOR`) — unless a systems/finance domain word sits beside it (`_BA_DOMAIN`: Salesforce BA, HRIS BA, credit …), then the LLM decides | accept | `keyword` |
| anything else with an analytics signal — the residue | **the LLM tier** | `llm` `llm_cache` `llm_failed_fallback` `llm_skipped` |
| the residue under `--no-llm` | keywords + description veto (`_sig_accept_nollm`, `_desc_is_ml`) | `keyword_nollm` |

The keyword tier is frozen by a golden fixture: `tests/fixtures/classifier/titles.json` holds
301 rows (every `llm_cache` key and every matched role on 2026-08-24); the **252 title-only
rows** are asserted by `test_classify_keyword_tier_matches_the_golden_fixture`, the 49
description-backed rows are skipped (the fixture stores no text — the description veto is
guarded by its own tests). Three rows changed on purpose in wave 1 and carry `"changed"`:
`salesforce business analyst` (→ LLM tier) and two Hebrew senior data titles (→ accepted in
fallback). `_desc_is_ml` counts ML words in the **requirements section** (when `_REQ_HEADER`
finds one — a header, not the EEO footer's "basis of qualifications, merit") and analytics
words over the whole role text; the wave-1 reviewer's corpus (1,336 real (company, title,
description) rows) moved **0** decisions under that change.

### The LLM tier — one seam, bounded four ways

`Classifier` (one per run, held by `pipeline/run.py`, which calls `clf.classify(j)` at its two
classify sites, then `clf.commit()` and `save_llm_cache` right after the loop — before rendering
and company intel, so a crash there cannot lose paid verdicts; `Classifier._judge → seniority._claude → llm.call` is
the only path to the CLI (`pipeline/llm.py` is the shared seam); the decision dict and the one-posting reproduce command are in §5b
item 6) calls:

```
claude -p --model sonnet --effort low --tools "" --no-session-persistence
          --output-format json --json-schema {verdict: YES|NO, reason} --system-prompt <LLM_RULES>
```
posting on stdin, `shell=False` on every OS (`shutil.which("claude")`), `cwd=` one fixed
scratch directory — **never the repo**: from the repo root every call read `CLAUDE.md` and the
gitignored `CLAUDE.local.md` (24,845 cache-creation input tokens against 4,633 from a scratch
dir; re-derive with `claude -p --output-format json "Reply OK"` from each directory and read
`modelUsage[*].cacheCreationInputTokens`). `LLM_RULES` is one line on purpose: a `.cmd` shim
(cmd.exe) truncates an argv element at a newline, and the Windows rehearsals were running 116
of 1,336 chars of rules before wave 1. The posting the model sees (`_posting`): title, company
and location each whitespace-collapsed and capped (200/120/200 chars), then
`prompt_slice(description)` — HTML stripped, the company intro skipped (`_ROLE_START`),
**requirements-first** (`role[:600] … requirements[:800]` when the header sits past 600 chars;
`LLM_WINDOW` = 1,400, `_ROLE_HEAD` = 600 — in 29 of 375 stored JDs the requirements began
past the old window). The rules say the posting is data; two live injection probes
(wave 1: a forged "hiring-panel approval" through the title field, a "SYSTEM OVERRIDE" plus a
schema-escape payload through the description) answered NO with the injection named. The
reason of every fresh verdict is printed to the step log: `[llm] company | title -> YES/NO: …`.

| bound | default | env / constant | what the mail says when it bites |
|---|---|---|---|
| calls per run | 300 | `CLASSIFY_LLM_CAP` — a runaway backstop; the minutes bind first at ~14 s/call | `classify llm-budget(cap 300 calls) — N roles judged on keywords alone (A accepted and emailed, R rejected until the next run), B served their cached bare verdict` |
| minutes per run (sum of call durations incl. timeouts, not wall-clock) | 60 | `CLASSIFY_TIME_BUDGET_MIN` | `classify llm-budget(60 min spent) — …` |
| seconds per call | 45 | `CLASSIFY_TIMEOUT` / `LLM_TIMEOUT` | a `transient` failure |
| model | `sonnet` | `CLASSIFY_MODEL` / `LLM_MODEL` | `classify model drift: asked sonnet, served …` when the answering model (largest `inputTokens` in `modelUsage`) is another family |
| quarantine floor | 30 fresh verdicts | `CLASSIFY_QUARANTINE_MIN` / `QUARANTINE_MIN_FRESH` (the rehearsal sets 10) | see below |

An explicit constructor argument beats the environment (`Classifier(cap=2)` in a test is 2).

**Failure contract.** `_claude` reads the JSON envelope first, whatever the exit code — on
CLI 2.1.241 a bad token exits 1 with an **empty stderr** and the envelope on stdout
(`is_error: true`, `api_error_status: 401`, `result: "Failed to authenticate…"`), and a
keychain-less login exits **0** with `is_error: true`. Infrastructure raises
`LLMUnavailable(kind)`: `auth` (`api_error_status` 401/403, or `_AUTH` on the envelope's
`result`/stderr — never on a good call's stdout, which is the posting's own words), `drift`
(`unknown option` — the CLI is pinned `@2.1.241` in `daily-digest.yml` for this reason),
`missing` (no `claude` on PATH), `transient` (timeout, 429/529, anything else). The first
three open the circuit breaker on the **first** hit; `transient` after
`BREAKER_CONSECUTIVE` = 3 in a row, or ≥5 failures making up at least half of the last
`BREAKER_WINDOW` = 10 attempts. An answer that is not in-schema is a fact about the model
(`llm_failed_fallback`, not cached, no strike; `structured_output` missing ⇒ the `result`
JSON is read instead). With the breaker open, every further residue role is served its cached
bare verdict if one exists (path `llm_cache`), else judged by the `--no-llm` rule (path
`llm_skipped`). Before 2026-08-24 an expired token cost up to 163 × 90 s of silent timeouts
with no line in the mail; now it is one call and one bold line.

**Quarantine.** Two cohorts, judged separately at the end of the run. FRESH verdicts (roles
never judged before): ≥30 with 0 YES, or a YES rate above `MASS_YES_RATE` = 55 % (the cache's
base rate is 18 %: 45 of 247), is a broken morning, not a measurement. RE-JUDGEMENTS of
verdicts **this seam** made (`v2|…|bare`): ≥10 of them, more than half flipping and fewer than
a tenth of the flips going the other way, is the same thing — legacy verdicts (another
prompt, another model, judged bare) are *expected* to move when their JD arrives and do not
count. The digest still ships; only the suspect cohort is withheld from the cache (the staged
verdicts still decide postings later in the same run); the mail says
`classify mass-no(…) — N of this run's M verdicts NOT cached`. A withheld cohort is re-bought
tomorrow, bounded by the cap; nothing escalates yet (BACKLOG 123).

### The verdict cache (`cloud_state/seen.db` → `llm_cache`, column `title_key`)

Key `v2|<company>|<title>|jd` when the raw description is ≥ `MIN_DESC` = 300 chars (the same
measure `jdfill.maybe_fill` gates on), else `v2|<company>|<title>|bare`; company and title
NFKC-normalised, typographic dashes folded, replacement characters dropped, `|` → `/`,
lowercased (`_norm`; five committed keys carry an en/em dash — the fold that matters today; the replacement-character and NFKC folds are preventive, 0 keys need them). Lookup order: `|jd`, then `|bare`, then the legacy `company|title` key — **the 235
committed `company|title` rows are read as bare verdicts** (12 older title-only rows are
unreachable) **and never purged from a local checkout** (BACKLOG 116). These counts decay from the first v2 run on — re-derive the split, and the base rate the quarantine uses, with
`python -c "import sqlite3;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);print(c.execute(\"select count(*), sum(title_key like 'v2|%'), sum(title_key not like 'v2|%' and instr(title_key,'|')>0), sum(instr(title_key,'|')=0), round(1.0*sum(verdict)/count(*),3) from llm_cache\").fetchone())"` → `(247, 0, 235, 12, 0.182)` on 2026-08-25. A bare verdict is
re-judged **once** when the description arrives (BACKLOG 107, closed — `mobileye|experienced
data analyst` was a NO judged on an empty description and served forever after the JD came);
a `|jd` verdict is never re-judged on a bare title, so a role whose inline fetch fails one
day does not flip-flop. `store.save_llm_cache` writes only new or changed boolean rows, so
`updated` is the judgment date from the first v2 run on (before, every row was upserted every
run: all 247 said `2026-08-24`). Rows:
`python -c "import sqlite3;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);print(c.execute('select count(*),sum(verdict),sum(title_key like \"v2|%\") from llm_cache').fetchone())"`

### What the mail says — the audit block, its arithmetic, and the alarms

`- Decision paths: keyword=…, keyword_nollm=…, llm=…, llm_cache=…, llm_failed_fallback=…,
llm_skipped=…` (alphabetical, only non-zero paths) sums to `Israel-matched` — checked in
`run.py`; a breach is a `::warning::` and a `Stages:` line, non-blocking. `- LLM calls this
run:` is **attempts** (fresh + failed; a failed re-judge that kept its cached bare verdict is an
attempt on the `llm_cache` path, so attempts ≥ llm + failed). The step log adds one line:
`classify: N judged = keyword K + llm A (Y yes) + cache C + failed F + skipped S; failed calls
X; attempts T in M min, rejudged R (flipped +a/-b); model …; breaker closed|…` — `keyword K`
merges the `keyword` and `keyword_nollm` paths, `failed F` is the path count and `failed calls
X` the attempt failures (the alarm below uses X). The classifier's alarms ride the bold
**`Stages:`** line — rendered **above** the collapsed audit under **Needs a look**, so nobody has to expand anything to see them (`::warning::stage classify …`):

| morning | `Stages:` says | rehearsed by |
|---|---|---|
| healthy | nothing from `classify` | `yes`, `no`, `flaky`, `prose_before_json`, `nollm` |
| token expired / logged out | `classify llm-unavailable(auth: Failed to authenticate. API Error: 401 …) — N roles judged on keywords alone (A accepted and emailed, R rejected until the next run), B served their cached bare verdict` | `fail`, `is_error` |
| CLI drift (flag removed) | `classify llm-unavailable(drift: error: unknown option '--json-schema') — …` | `unknown_flag` |
| rate-limited / timing out | `classify llm-unavailable(transient: API Error: 429 … x3) — …` | `rate_limit`, `sleep` |
| ≥10 calls answered off-schema | `classify N of N LLM calls failed (answer: no structured verdict xN)` | `no_structured` |
| cap or minutes spent | `classify llm-budget(…) — N roles judged on keywords alone (…)` | unit test only (`test_the_cap_and_the_time_budget_skip_instead_of_failing_v2`) |
| every fresh verdict NO / mostly YES | `classify mass-no(…) — N of this run's M verdicts NOT cached` | `all_no`, `all_yes` (the driver empties the scratch cache for these; `--fresh` does it for any mode; needs ≥ `CLASSIFY_QUARANTINE_MIN` fresh roles — 10 companies, not 4) |
| re-judgements of this seam's verdicts flipping one way | `classify mass-flip(…) — …` | unit test only (`test_mass_flip_is_a_ratio_not_a_cliff`) |

Real-CLI rehearsal (15 companies, sonnet, 2026-08-24): `classify: 232 judged = keyword 213 +
llm 19 (4 yes) + cache 0 + failed 0 + skipped 0; attempts 19 in 4.3 min, rejudged 18 (flipped
+1/-3)`. Full `--no-llm` pass over every active row: 862 companies, 23,190 jobs, **4,837
Israel-matched = 4,563 keyword + 274 keyword_nollm**; the 274 are the LLM residue, so day 1
after this change is at most 274 attempts (estimate: 100–190 — a legacy verdict is re-judged
only where the inline fill now delivers a description).

### Guards
`tests/test_units.py`, classifier block (61 cases added 2026-08-24; the file collects 344,
the suite 509): the argv is pinned (tools off, json, schema, the full one-line rules, no
session, no shell, cwd ≠ repo); every failure kind incl. the real 2.1.241 401 envelope; the
`_AUTH` regex on request ids and the model's own words; envelope-not-first-brace and the
bounded scan; `result` fallback; the served model; every posting field bounded; the
requirements-first slice; key v2 lookup order, legacy read, re-judge-once, bare→jd→bare = one
call, `|` in a title; explicit args beat env; breaker first-hit, three-in-a-row and steady
half-rate; failed calls charge the budget; cap and budget; quarantine per cohort, fresh-only
rate, ratio flips, complete commits; summary arithmetic; model drift; the wrapper's signature;
`--no-llm` never touching the seam; `run.py` wiring by source (both classify sites,
commit-then-save before company intel, `llm_calls = attempts`); `save_llm_cache` writing only
changed boolean rows; the digest labelling `llm_skipped`; place-name parity and the accepted
false positives; the fake CLI reachable through the real seam on this OS — on ubuntu that is
the exec-bit `claude` shim, and `tests.yml` proves the Linux argv path on every push (no
manual dispatch needed, `CLAUDE.local.md` §3).

### Which model, and why

Bare `claude -p` on this subscription runs **claude-fable-5** (`total_cost_usd` 0.577 for a
one-word answer; sonnet 0.104–0.137; haiku 0.027 — read `total_cost_usd` from
`--output-format json`). Yesterday's 163 fresh calls were the most expensive model in the
lineup answering YES/NO. A/B on 25 description-backed postings the keyword tier could not
decide, hand-labelled from the JD (19 confident labels, 6 the JD itself leaves open), each
judged once by each model through `_claude(model=…)` (75 calls, 2026-08-24):

| model | agrees with the 19 labels | YES / 25 | mean wall s |
|---|---|---|---|
| `sonnet` (default) | **18** | 11 | 14.1 |
| `fable` (the old default) | 17 | 11 | 14.7 |
| `haiku` | 15 | 14 | 26.6 |

sonnet–fable agree on 23/25, sonnet–haiku 18/25. The one sonnet miss is a JD whose years
line only exists in a sibling posting. Per call, measured locally: `duration_api_ms` 3–5 s,
wall 14–16 s — the difference is CLI start-up, not the flags (three argv variants within
0.1 s); each call reads ≈21k cached input tokens for ≈$0.009. **Unverified as of 2026-08-24:**
the start-up cost on the ubuntu runner (tomorrow's `classify:` line prints `attempts N in M
min`), and whether `--bare` with the OAuth token env would trim it (`--bare` skips the
keychain and breaks the local login; no token on this machine to test the CI shape).

### The proof: the first digest run after this lands (pushed 2026-08-25, after that day's 05:00 run)
`Decision paths` sums to `Israel-matched`; no `classify` text on the `Stages:` line;
`LLM calls this run` between 100 and 274 (below 100 or above 274 wants a second look); the step log's `classify:` line names
`claude-sonnet-5` and its `attempts N in M min` is the runner's real per-call cost; the
`cloud run:` commit's `seen.db` has `v2|…|jd` rows dated 2026-08-25 and the legacy rows
untouched.

## 7c. The role record — the entity the product is about
*lane: `roles` — `pipeline/roles.py`, `pipeline/store.py` (`matched`/`sent`), the role-selection block of `pipeline/run.py`*

Step 6 of the flow. A ROLE is one opening at one employer; a POSTING is one listing of it on
one board. Until 2026-08-25 the role had no owner and no durable record: `matched` (sqlite,
committed as a binary) keyed on `company|title`, forgot its history on every >3-day gap,
stored nothing about closure, reposts, tags or the classifier's verdict — and held the same
posting under two company names three times over (Armis+OTORIO, Port+Port.io, Meta+Meta
Israel; Port and Port.io both *active*, so the board showed one posting twice). Written
2026-08-25 and attacked the same day (four Opus reviewers, then confirmers —
`docs/sessions/2026-08-24-roles.md`). **Start here — rehearse tomorrow's role morning
without spending anything:**

```bash
python tests/rehearse_roles.py --case happy       # six scripted days; also clobber | corrupt | massclose
python tests/rehearse_roles.py --golden           # HEAD vs this tree on the same days: only the claim collapse may differ
python tests/rehearse_roles.py --real --only "Fiverr,Wix,Lightricks"   # live fetch, no LLM, no Bright Data
```
Each replaces the fetchers with `tests/fixtures/roles/days.json` (the shapes found in the
committed store), runs `pipeline.run` scoped against a scratch store + ledger, and prints
PASS/FAIL per check from the produced digests (the `Roles:` line, `Decision paths`
reconcile, the exact board, the ledger equals the store, `git status` unchanged).

### The record, and where it lives

Two text files beside the sqlite store, written by `pipeline/roles.py` through
`pipeline/atomic` and committed by the digest's existing `git add cloud_state`:

| file | one line per | changes on a normal day |
|---|---|---|
| `cloud_state/roles.jsonl` | role (`role_id` = today's `mkey`), sorted, keys sorted | one short line per open role (`last_seen`, `updated`) |
| `cloud_state/roles_text.jsonl` | role's description (`sha1`, `len`, text) | only when a description changes (a JD backfill day) |

A record carries everything the pipeline knows about the role: the `matched` columns
(`company title location url posted_date seniority sources[] seen_ids[] first_seen last_seen
jd_attempted`), `status` (`open | closed | superseded | purged`, with `closed_on` /
`superseded_by`), `episodes` (every opening — sqlite *resets* `first_seen` on a >3-day
reappearance because the email must re-alert, and the ledger keeps the earlier opening
instead of undoing that), `reposts` (dates the posting was bumped ≥3 days past its
episode's `first_seen` — the render rule, recorded at ingest), `class` (decision / path /
reason from the classifier), `tags` (`roleprofile.extract` snapshot, `v: 1`, recomputed when
the description's sha1 changes — `render` owns the vocabulary, this lane owns the column),
`attribution` (platform, host, tenant slug, `claimed_by`: the other company names that
fetched the same posting), `sent` (`seen_id → first_sent`, mirrored from the `sent` table)
and `emailed_on` (`store.mark_sent` stamps the mirror itself, so it lands in the same
commit as the `sent` table — `mark_sent.py` runs after the digest flushed the ledger).
Nothing is ever deleted; a wrong row becomes `superseded` or `purged`.

**The contract, in §7's words: the export is authoritative, sqlite is a per-machine cache.**
`matched` stays the working index because four other tools read or write it by SQL
(`enrich_matched_jd.py`, `company_type_analysis.py`, `research_firmographics.py`,
`check_invariants.py`). At open, `Ledger.open_sync` reconciles the two field by field
(`roles.reconcile`: longer description wins either way, `jd_attempted` is kept so a
rehydrated store does not re-spend Bright Data, `first_seen` is sqlite's whenever the row
exists, lists union) and supplies whatever one side lacks — a role sqlite lost is
re-inserted from the ledger with its text, and a `sent` mark the ledger carries is
re-inserted so the role is not re-emailed. sqlite holds exactly one status, `superseded`;
open/closed live in the ledger alone (a rehydrated row that carried `open` once out-voted the
ledger's closure — caught by the clobber rehearsal, pinned). **No ledger seam can take the
digest down:** a line that is valid JSON but wrong-typed is a bad line (`roles._valid`),
and `open_sync` / `resolve_claims` / `record_run` are guarded — an exception becomes
`roles <seam> failed: …` on the bold `Stages:` line, the ledger freezes for the day and
the run goes on (an unguarded `open_sync` once raised out of `run()`, past the Persist
step: no email, no board, the morning's verdicts lost). A record without ISO dates is
never rehydrated (it would be invisible to every `first_seen >= ?` read and re-inserted
forever); the mail says `ledger N != store N` when they differ.

**What the ledger does NOT protect against, stated so nobody relies on it:** the conflict
path in `daily-digest.yml` restores `cloud_state/` wholesale (`cp -rT`), and both ledger
files ride the same commit as `seen.db` — a day lost that way is lost in both. What it buys:
a diffable, line-tolerant record (`git log -p cloud_state/roles.jsonl` answers "when did
this role close"), rehydration when the sqlite copy alone is damaged, and the precondition
for a row-level merge on the conflict path (`docs/BACKLOG.md` 134, `infra`).

A ledger that is unparseable, or has more than 10 % bad lines, is **corrupt**: nothing is
read from it, nothing is written to it, sqlite carries the day, and the mail's bold
`Stages:` line says `roles ledger corrupt (…) — not overwritten` until a human looks (a
corrupt `roles_text.jsonl` alone freezes only itself; statuses still record and the text
is read from sqlite). A BOM, CRLF, blank lines and the odd bad line are tolerated
(skipped, counted, reported).

### One posting under two names — the wrong-company guard

`job["company"]` is copied verbatim from the registry row (`pipeline/fetchers.py`, 14
sites; `scrape_universal.py:485`), so a posting is attributed by *which row fetched it*, and
two active rows read the same board in 13 identity groups today (`registry`, BACKLOG 133).
This layer makes the product right regardless: after `merge_duplicates`,
`Ledger.resolve_claims` groups this run's postings across companies by `roles.same_posting`
— the titles must agree (equal, or the longer one is the shorter plus words from that
job's own *location*: the scraper glues it on) **and** they share a strong `seen_id` or a
url. Never a url alone (Meta's url is the listing page, shared by every Meta role) and
never an id alone (a scrape row's `job_id` is sometimes the listing page, `#` or a
`mailto:` — six SpearUAV roles carried one id); "Data Analyst" vs "Data Analyst, Growth"
is two roles, and because that agreement is not transitive (its word-set is the longer
job's own location) a group collapses only when every pair agrees. Each group keeps ONE
company (`Ledger._winner`): the one whose own name is in the url or tenant slug (`armis`
in `armissecurity`, `port` in `/jobs/port/`; the ATS hosts themselves and path plumbing
never count — `Smart Shooter` is not named by every smartrecruiters url; TLD-ish tokens
ignored, three-letter tokens must match a segment exactly) — evidence outranks
incumbency, or a wrong name stored before this guard existed would be sticky forever; else
the one already holding the posting (no flip-flop); else a native-ATS row over a scrape
over a discovery card; else not the "X Israel" site form, not a lowercase stub row, then
the shortest identity, then A–Z. The losers' `seen_ids` and sources are unioned into the
winner (so `filter_new` still sees them sent — a posting emailed yesterday under the wrong
name is therefore not re-emailed under the right one), the losers are named on the
winner's `attribution.claimed_by` and in the mail, and a loser row already in the store
becomes `superseded` — kept, off the board and the archive (`get_matched_since` excludes
it by default). A superseded row fetched again while its winner is neither fetched nor in
fetch-failure grace reclaims itself (`N reclaimed` in the mail): the winner's registry row
was parked, and the opening must not vanish from every product. `Ledger.sweep_store`
applies the same rule at open to what the store already holds, so a double whose other
half was parked (OTORIO, Meta Israel) does not sit in the archive under the wrong name
forever. It is a dedupe with stability, not an attribution judgement: for a
Broadcom/VMware-class pair both names are real employers, the winner is the stable one,
and the card shows only the winner (BACKLOG 137 asks `render` for an "also listed as").

Measured against the committed store on 2026-08-25 (read-only):
```bash
python -c "import sqlite3;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);print(*c.execute(\"select url,group_concat(company,' | ') from matched where url!='' group by url having count(distinct company)>1\"),sep='\n')"
```
→ 3 urls under two names each (the three above). A full no-LLM dry run on a **scratch
copy** the same day (`--no-llm`, real fetchers, no Bright Data; the scratch store grew from
111 to 165 roles because a keyword-only run accepts more than the LLM tier does, which is
also why its board says 135 against the 61 the production run published on 08-24):
**862 scanned · 6 failed · 22,859 jobs · 4,844 Israel-matched · `claim conflicts 2
(Port<-Port.io, HP<-HP Indigo)`** — the HP pair was not known before the run found it.
Unverified against a production run until the 2026-08-26 mail.

### Judged once per role per text (closes BACKLOG 124)

Classification now happens after the fetch loop, in `roles.classify_grouped`: candidates
are grouped by `store.merge_key`; every copy that carries its **own** description is
judged, longest first (two listings under one title can be two openings with two JDs, and
the one that qualifies must not be lost to the other), the fullest copy gets the inline
JD fill, and a copy with no text of its own never pays a call — it inherits the first
accepting verdict, is marked `_inherited`, and `store.merge_duplicates` never lets it be
the canonical: a bare LinkedIn card's url must not become the role's record, while the
posting date it carries is real and is kept (`merge_duplicates` never discards a known
ISO date — so a role first met through a two-week-old card is not "48h-new" merely
because the board row is undated). Skipped copies count as `merged-copy` in `Decision
paths`, so the classifier's reconciliation (`sum(paths) == Israel-matched`) still holds;
the classifier's own `classify:` line says "N judged" with N smaller by exactly that
count. Dry run 2026-08-25: `keyword 4146 + keyword_nollm 244 + merged-copy 454 = 4844`.
Proof against HEAD: `tests/rehearse_roles.py --golden` carries a same-company pair (bare
dated card + undated board row) and requires the emails to agree on every day.

### Open, closed, reopened, re-posted — and the mass-close hold

`_alive` in `run.py` stays the liveness rule (seen in the latest scan of its employer, or
a 7-day grace while that board errors), judged on the alive set *before* the page-weight
cap. `Ledger.record_run` only *records* what it decided: on a full run every company but
the failed ones is judged (a role whose employer is no registry row — a discovery card, a
recruiter stripped from the scan — cannot be fetched and is dead by `_alive`, so it
closes too); on a scoped `--only` run only the scanned companies are, so a local run
closes nothing elsewhere. A failed board closes nothing (`failed_names` is collected by
name in the fetch loop — splitting the mail string on `" ("` used to turn
`Microsoft (Xbox/Gaming)` into `Microsoft` for `_alive` and the ledger alike; 15 registry
names contain `" ("`). A record absorbed for the first time is classified, never
counted as a closure. open→closed stamps `closed_on`; closed→open appends an episode and
counts `reopened`; a bumped `posted_date` is a repost. **A mass-close is an alarm, never a
closure:** more closures in one run than `max(10, 25 % of the open set)`
(`MASS_CLOSE_MIN`, `MASS_CLOSE_FRAC`; 50 % let a morning where 40 % of boards answered
`[]` close 80 roles silently) is a broken fetch, not a measurement — statuses are held
and the bold `Stages:` line says `roles mass-close held (N of M …)`. Rehearsed:
`--case massclose`.

### What the mail says

One line in the audit block, from `summary["roles"]`:

```
- **Roles:** open 146 · closed today 16 · reopened 0 · reposted 12 · merged-copy 454 · ledger 165 = store 165; claim conflicts 2 (Port<-Port.io, HP<-HP Indigo)
```
`open` is this run's count of records left `open`: the alive set, plus roles at companies
the run did not judge that were open before (a scoped run), plus a held cohort on a
mass-close morning — so it can exceed `board` (measured: `open 64` against `board 61` on
a scoped A/B); `ledger N = store N` is the reconciliation — a
`!=` is an alarm; `rehydrated N` appears when sqlite had lost rows. On the FIRST run after
this lands `reposted` counts every historical bump at once (the record is new); from then
on it is the day's. A run that finds NO ledger beside a populated store says
`roles ledger missing — N role(s) absorbed from sqlite` on the `Stages:` line and
`absorbed N (M already closed)` on the `Roles:` line: those are classifications, not
closures, and never trip the mass-close hold — which is why the seed files are committed
already judged. Alarms travel on the existing bold `Stages:` line and as
`::warning::stage …` in the step log: `roles ledger corrupt (…)`, `roles ledger rehydrated
N role(s) sqlite had lost`, `roles ledger write failed: …` (the sqlite side still commits),
`roles ledger N != store N after sync`, `roles mass-close held (…)`. Claim conflicts also
print `::warning::roles …`.

### Guards

`tests/test_units.py`, "lane: roles" — 42 cases, every one a defect the rehearsal or an
attacker reproduced: the file contract (round-trip, bad-line tolerance, the corrupt
threshold, duplicate-id resolution, wrong-typed lines, a text-only wreck, the run date);
every `reconcile` rule; identity (the three real double shapes kept once; Bounce/Bounce
AI, two Meta titles and "Data Analyst, Growth" NOT merged; a listing-page id shared by six
roles; every pair in a bucket; url evidence over incumbency; the stub-row and TLD-token
tie-breaks; a superseded row reclaiming itself); the store sweep, idempotent; judged once
per text with the paths arithmetic, the inherited copy never canonical, a known date kept;
closure only where the run looked, every company on a full run, never on a failed board
(names with `" ("`), on the alive set not the capped page, the mass-close hold and its
25 %, a fresh record never a closure; episodes and reposts across a reopening;
rehydration of rows and `sent` marks, `sent` stamped by `mark_sent`; `jd_attempted`
declared. `tests/rehearse_roles.py --golden` is the regression proof against HEAD.

### Known limitations

- The ledger is not a merge on the conflict path (above; BACKLOG 134).
- `open` on a scoped local run counts roles at unscanned companies as whatever they were —
  the number is the ledger's state, not that run's board.
- A collapse into an established company can cost an email item: `HP<-HP Indigo` with
  both rows new keeps `HP`, which is `seen_before` with an old `posted_date`, so the role
  is emailed under neither name (a correct dedupe; the first-scan section selects on the
  company). And a loser's `seen_id` already in `sent` suppresses the winner from today's
  email — the same posting is never emailed twice, even to correct its name.
- A scoped `--only` run never reclaims a superseded row: its winner may be out of scope
  rather than parked; only a full run (or one that scanned the winner's company) can.
- Other SQL readers of `matched` do not know `status`: `enrich_matched_jd.py` will keep
  trying to backfill a superseded row's empty description (BACKLOG 140, `jd-text`) and
  `research_firmographics.py` still counts superseded-only companies (141).
- Tags are only as good as the text captured while the role was open (`docs/TAGGING.md`).

## 7d. Render — how a role reads (jdtext → rolecard → digest)
*lane: `render` — `pipeline/jdtext.py`, `pipeline/rolecard.py`, `pipeline/digest.py`, `pipeline/roleprofile.py`, `docs/TAGGING.md`*

Step 6 of the flow. Three products come out of one set of cards every morning: the email
(`build_markdown` → `digests/latest.md`), the board and the archive (`build_board_html` →
`docs/index.html`, `docs/archive.html`). Until 2026-08-25 all of it lived in one 1,444-line
`digest.py` (`git show 60fae33:pipeline/digest.py | wc -l`) that derived and rendered in the same loop, filtered mangled titles without a
trace, never saw the role record, and kept its own copies of four other lanes' vocabularies.
Every number here was produced on 2026-08-25 by the command beside it. **Start here —
rehearse tomorrow's products without spending anything:**

```bash
git show 60fae33:pipeline/digest.py > out/base_digest.py && python tests/rehearse_render.py --golden out/base_digest.py --date 2026-08-25
#   6 products vs the pre-split file, loaded as a member of `pipeline`. Against 60fae33 TODAY this is 1/6 (subject only):
#   the five diffs are the enumerated behaviour changes below plus the roles lane's `Roles:` line. A PURE move must be 6/6.
python tests/rehearse_render.py --cards [--cards-golden <an earlier out/rehearse-render/cards/cards.json>]  # the card model for every store role; degraded / cross-check counts; field-level diff against an earlier dump
python tests/rehearse_render.py --real --only "Fiverr,Wix,Lightricks"   # live scoped run, no LLM, no Bright Data; the Render line
python tests/rehearse_render.py --full                                  # tomorrow's email: unscoped, scratch store, ~30-60 min
```

### The two parts, four files

```
matched row (+ ledger record) ──▶ jdtext ──▶ rolecard.build ──▶ card ──▶ digest.build_* ──▶ product
                                  (text→structure)  (the role as it reads)     (escape + lay out)
```

| file | what it is | may import |
|---|---|---|
| `pipeline/jdtext.py` | **part 1a — the JD as text.** Requirements / responsibilities as bullets with MUST/PLUS badges, the "what the company does" sentence, the location label (`_LOC_GROUPS`: every spelling `israel.py` knows), the seniority chip, the posted-date labels. Pure functions; testable from a string. A fragment of 3–7 characters survives only when it IS a lexicon skill ("Python"); a two-word fragment starting with a capital is a decorative header unless it is a skill or a soft skill ("Team player"). | stdlib; `roleprofile.SKILLS`/`SOFT_SKILLS` for those two checks |
| `pipeline/rolecard.py` | **part 1b — the card.** `build(job, run_date, *, ledger_rec, company_info, firmographics, archived)` → one dict of raw strings and lists per role; `cross_check(cards)` → the wrong-company shapes across a product; `report(cards, hidden)` → the mail fragment. Holds the stage labels (total over `firmographics.STAGES`, asserted at import), the blurb gate (`company_info._JUNK_OUT` ∪ one render-only case), the seniority canon (`seniority._SENIOR/_JUNIOR/_HEBREW_SENIOR` + `roleprofile._LEAD`). | `jdtext`, `roleprofile`, `seniority`, `firmographics`, `company_info`, `roles` |
| `pipeline/roleprofile.py` | **the lexicon.** 98 skills, 5 clusters, 8 task groups, 3 AI buckets, 9 soft skills, degree, years, family. `docs/TAGGING.md` is its documentation. | stdlib |
| `pipeline/digest.py` | **part 2 — rendering.** `render_all` (run.py's one entry), `build_markdown`, `build_board_html`, the legacy `build_digest` (only its `subject` is read; BACKLOG 142). The only file that escapes (the two local `esc` closures, `_md_esc`, `_md_line`, `_md_blurb`, `_md_alarm`, `_safe_url`) — cards are never pre-escaped. | `rolecard`, `roleprofile`, `jdtext` (`_company_blurb`, `_age_note`) |

The split was a pure move first: with `tests/rehearse_render.py --golden` against a snapshot
of the pre-split file (the working tree of that hour: `60fae33` plus the roles lane's three
`Roles:` hunks — no longer reachable from git, so this number is the session's, not
re-derivable), all six products (board, archive, markdown, subject, legacy html/txt) came back
**byte-identical** over the committed store (57 board · 51 archive · 17 email roles) before
any behaviour changed; every change after that produced only its enumerated diff.

### The card, and what never raises

`rolecard.build` returns a bare card first (company, display name, title, url, location,
posted, age) and then fills it; an exception anywhere in the fill leaves the bare card with
`card["issues"] = ["card degraded (ValueError)"]`, and a malformed ledger record adds
`"ledger record unreadable (…)"`. `digest.render_all` wraps each product the same way: a
renderer that raises is reported — `::warning::render …` in the step log, a bold line in the
mail — and its file is **not written**, so yesterday's board stays published (wave 1 found the
first version shipping a 221-byte apology page over the live board); the other products still
ship. Measured 2026-08-25 over the store: **108 cards, 0 degraded** (`--cards`).

Cards are built **board and archive first, then the email** (`render_all`; the hook in
`pipeline/run.py`, approved out-of-lane 2026-08-25, replaced four `build_*` calls with one) —
that order is what lets a board-render problem reach the mail that is written last.

### What the mail says

Every run audit carries one line:

```
- **Render:** board N cards[, M degraded (card degraded M)][, K hidden: mangled title][, shared-board A/B][, title-twin A/B][, display-collision A/B][, blurb-names-other A→B] · archive N cards[…] · email N cards[…]
```

(the same list, machine-readable, is `summary["render"]` in the payload JSON and the `RENDER:` /
`<b>Render:</b>` line of the two legacy audits). The degraded, hidden, shared-board, title-twin
and FAILED cases — from the board, the archive and the email alike — also stand above the fold
under **Needs a look** as `- **Render:** …` and in the step log as `::warning::render …` (at
most three wrong-company alarms per product, de-duplicated); display-collision and
blurb-names-other are counted in the audit line only:

| fragment | meaning | who fixes |
|---|---|---|
| `M degraded (…)` | a card's derivation raised; the bare card rendered, the reason is in parentheses | `render` |
| `K hidden: mangled title` | the scraped title is a run-together card blob (`jdtext._MANGLED_TITLE`, or >100 chars); the row is not rendered — before 2026-08-25 this was silent | `scraper` |
| `shared-board A/B` | two *employers* (`rolecard.same_employer`: not one name and its prefix-spelling — Kornit Digital / kornit) whose cards were read from one ATS tenant (`rolecard._tenant`: host + first non-plumbing path segment on Greenhouse/Lever/Ashby/Comeet/SmartRecruiters/Workable, the host alone elsewhere; aggregator hosts and Comeet's API url are nobody's tenant; more than 3 employers on one key is a platform host, not a board) — the Scopio Labs / Sckipio class (the registry's "13 active groups read one board", `docs/BACKLOG.md:1978`, numbered 133 — the number is duplicated, 147): the winner is whatever `roles.Ledger._winner` decided, a human should look | `registry` |
| `title-twin A/B` | one normalised title under two names that are one employer by `rolecard.same_employer` (equal keys; equal without spaces — Spear UAV / SpearUAV; a name plus site/legal words — Port / Port.io, Kornit / Kornit Digital; a division written `X (Parent)` — Splunk (Cisco) / Cisco; never a name plus an arbitrary word — Aleph / Aleph Farms are two): the claim guard saw two postings; the reader sees one role twice. On the committed store on 2026-08-25: Port / Port.io and Bounce / Bounce AI | `roles` |
| `display-collision A/B` | two differently named companies whose short cell names collide (judged on the names as written — the identity key strips exactly the suffixes the short name drops) — both now render their full name; informational | — |
| `blurb-names-other A→B` | A's About text names employer B and not A — counted, never dropped (acquirers and customers are named legitimately; company-intel owns the blurb). A company whose only name token is an ordinary word (Global-e, Port, Meta, Rise) accuses nobody: it would fire on every blurb using the word | `company-intel` |
| `<product> FAILED (…) — yesterday's file kept` | a renderer raised. Board / archive: the file was not written, yesterday's page stays published. Email: a stub that names the failure IS written to `digests/latest.md` (a reader must learn why there is no digest), and `mark_sent` is given no roles, so nothing is burned as delivered | `render` |

`- **Render:** board …` missing from the mail means `render_all` was not reached — the run died
before rendering. If the *email* renderer raised, the mail is a stub whose only lines are the
alarms and that same `- **Render:** board … · archive …`. The verdicts were already saved
either way; see §7b.

### The wrong-company question, from this layer

A card shows `job["company"]` — the registry row that fetched the posting — and the ledger's
claim guard (§7c) decides which row keeps a posting two rows fetched. Render cannot
re-attribute; what it does is make the situation visible in every product:

- **also listed as X** — from the ledger's `attribution.claimed_by` (or this morning's
  `_claimed_by`, before the flush) on the board card, the archive card and the email heading
  (`### Port _(also listed as Port.io)_`); the name is in the search blob so a reader looking
  for the loser's name finds the card (closes the render half of BACKLOG 137).
- **shared-board**, **title-twin**, **display-collision**, **blurb-names-other** —
  `rolecard.cross_check`, above, run over the board, the archive and the email cards. On the
  committed store on 2026-08-25: `--cards` → `cross-check ['title-twin Bounce/Bounce AI',
  'title-twin Port/Port.io']` — the two doubles the wave-1 attacker found on the shipped board,
  now named in the mail; the fixture cases are pinned by
  `test_cross_check_names_the_wrong_company_shapes_and_only_those`.
- **Blurb and facts** are looked up by the raw company name (`company_intel.enrich_for_run`
  keys both maps by it), so a card cannot pick up another *name's* record; the known crossing
  is inside one identity group — `identity_key("AppSec Labs") == identity_key("AppSec")`, so
  one blurb serves both (BACKLOG 144, `company-intel`).

### What the ledger contributes — a record, not a cache

Only what the text cannot say: `also_listed_as`, the re-post dates (`reposts`; the same
`REPOST_DAYS = 3` rule render applies itself when no record is present), and — **archive
cards only** — `closed on <date>` (a mass-close-held board row must never say "closed" beside
an apply button). Tags are recomputed from the text on every render; the ledger's `tags`
snapshot is the roles lane's column (§7c), and using it here would let the archive render
last month's vocabulary beside today's board.

### Vocabularies: one owner each

| was | is | measured on the store (108 cards / 111 rows — the denominator is named per row) |
|---|---|---|
| `_STAGE_LABEL` with 3 keys the researcher cannot emit and without `private-enterprise` (44 of the 940 exported records) | total over `firmographics.STAGES`, asserted at import, pinned by test | `private-enterprise` → "private enterprise" on 2 board cards (the same 2 in the email) and 1 archive card — the 3 of 111 rows at such a company |
| `_ABOUT_JUNK`, a copy of `company_info._JUNK_OUT` missing `error:` and `UNKNOWN` | `_JUNK_OUT` ∪ `unable to (confirm|verify)` | no card changed |
| `_SEN_INFER` / `_SEN_LEAD` / `roleprofile._LEAD`, three regexes that disagreed on a bare "Analytics Lead" and knew no Hebrew | `rolecard.sen_canon` over the classifier's + the lexicon's | 2 titles Senior → Lead+ (no stored title is Hebrew; `sen_canon('', 'אנליסט בכיר') == 'Senior'` is pinned, unexercised) |
| `_LOC_CANON`, 34 spellings of the 121 + 68 `israel.py` knows | `jdtext._LOC_GROUPS`, every token resolves (pinned) | **16 of 108** cards relabelled (6 board · 10 archive; 17 of the 111 raw rows), 12 distinct pairs: `תל אביב -יפו` → Tel Aviv, `ראשון לציון` → Rishon LeZion, `Raanana` → Ra'anana, `Modiin-Maccabim-Reut` → Modi'in, `Office` → Tel Aviv, `On Site` → Kiryat Gat, `Center` / `Center District` / `Givat Haim (Me'uchad)` → Central Israel, `North District` → Northern Israel, `Haifa District` → Haifa area, `Tel Aviv District` → Tel Aviv area |
| `_REQ_HARD` matching the equal-opportunity footer that `seniority._REQ_HEADER` had been fixed for | the footer rejected inside `_req_header_match`'s candidate loop (the lookbehinds would have lost "The Requirements:") | 0 of 111 changed |
| `_bullets` dropping any fragment under 8 characters and any two-word fragment starting with a capital; `_RUNON_SPLIT` cutting "Fluent English" in half; no junk rule for a LinkedIn scrape's tail ("Send your CV to: x@y", "רמת ותק") | a short fragment survives only when it IS a lexicon skill; a two-word skill / soft skill is a bullet; no split after Fluent/Native/Excellent/Good/Strong; the tail is junk and a section end | 8 of 108 cards' requirement bullets changed, all for the better: one "Team player" (+ its chip); six rejoined "Fluent/Excellent … English" lines; three junk lines dropped on two cards (two LinkedIn tails, one "hr@…" address) — one card is in two of those groups (`--cards --cards-golden` diff, listed in the session record) |

Not unified, by decision: the four requirements-header regexes are three lanes' (`jdfill`,
`seniority`, this one) and each serves a different question (is there a JD at all / where does
the prompt slice start / where do the bullets start); the stored `matched.seniority` column is
empty for all 111 rows and is not read (BACKLOG 145).

### Guards

`tests/test_units.py`, the `# lane: render` block — 13 assertions plus the 8 wave-1 pins: a card never raises; hidden
and degraded counts reach the mail, the footer and the payload; a renderer that raises is not written and
the other products still ship; stage labels total; the blurb gate; the EEO footer; every
`israel.py` place resolves; the seniority vocabulary; the ledger supplies only what render
cannot compute (closed-on archive-only, tags never); `cross_check` names the four shapes and
nothing else (X / X Israel and LinkedIn hosts are not shapes); also-listed-as in all three
products, escaped; scraped text (`<script>`, `](x)`, `@user`, `` ` ``) never reaches any product
unescaped — including the email blurb, which went out raw before 2026-08-25, and `<`, which
`_md_esc` did not escape; and a behavioural run of `pipeline.run` proving the board renders
before the mail and the mail says so. Wave 1 added: a row with non-string fields is a bad
card, not a crash; a url with whitespace never reaches the mail bare; every line another lane
writes into `stats` is neutralised but readable; a mangled title is hidden from the mail too;
newlines, backslashes and stray chips cannot break the mail's structure; a failed board is
not written; "Fluent English" is one bullet and a LinkedIn tail is none; the email blurb
never describes an agency's client.

### Known limitations

- The `Render:` line reports *rendering*; a role attributed to the wrong company by the
  registry (one tenant, two identities) is *named*, not corrected — `registry`, BACKLOG 133.
- `build_digest` still runs and writes two files nothing reads (BACKLOG 142, `infra` removes
  the call; then `_text_audit`/`_html_audit` and the company-intel mutation fixture that pins
  their source text go with it).
- `roles.tenant_slug` is not the tenant the shared-board check needs: it returns the **second**
  non-plumbing segment of host+path, which for `job-boards.greenhouse.io/<slug>/jobs/<id>` is the
  posting id, not the slug (`segs[1]`, not `segs[0]`). `rolecard._tenant` keeps its own (host,
  first non-plumbing segment) rule and borrows only roles' `_PLUMBING` list — tolerant of the
  module being absent (BACKLOG 143).
- `same_employer` is a heuristic: a name plus a word outside `_SITE_WORDS` is two companies, a
  division must be written `X (Parent)` to be its parent's; the registry-wide worst case (every
  active company posting one "Data Analyst") measured 45 issues before these rules, most of
  them false — the mail caps them at 6 per line and 3 alarms per product.

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