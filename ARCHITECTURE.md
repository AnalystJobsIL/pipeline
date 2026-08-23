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
  └────────────────────────────────────── 1,199 rows · 846 active · 353 parked ──┘
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
And **24 of the 66 workflow steps carry `continue-on-error: true`** (counted 2026-08-23 by
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
signal), `LLM_RESOLVE_CAP`, `JD_ENRICH_CAP`/`JD_ENRICH_BD_CAP`, `SERPAPI_KEY`,
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
   JSON API. Adding a platform = one `fetch_x(row)` normalizer + a map entry.
2. **Scrape rows** (`ats_platform=scrape`) — `api_url` holds a LISTINGS page URL.
   `refresh_scrape_cache.py` (daily 00:00 UTC) renders it with `scrape_universal.py` and
   writes `scraped_cache.json`; the digest reads the cache via `fetch_scrape`.
   `scrape_universal.scrape()` escalates through **5 strategies**:
   captured XHR/JSON bodies → rendered-DOM job links → repeated heading/class-hinted card
   groups → position-links (N same-prefix links, fetch each page) → **LLM extraction**
   (`SCRAPE_LLM=1`: Claude reads the rendered text, returns JSON; gated on jobs-signals).
3. **Discovery nets** — `discovery_daily.py` (Bright Data LinkedIn/Indeed keyword sweeps)
   and `discovery_telegram.py` (public t.me/s channel previews) write
   `discovered_cache.json`, read by `fetch_discovery`. This is the safety net for
   companies with no readable board — and the intake that feeds NEW companies into
   resolution (below).

Full `FETCHERS` map (16): comeet, greenhouse, lever, smartrecruiters, recruitee, ashby,
workday, oraclehcm, custom_json, jazzhr, microsoft, workable, breezy, bamboohr, plus the
pseudo-platforms `scrape` and `discovery`.

Support policy: a platform seen 3+ times gets native support; otherwise the scraper's
strategies carry it (Phenom/Eightfold/iCIMS/Radancy/Rippling are all read via strategy 1
XHR-capture or 3/4 without native fetchers).

## 1a. Intake — the discovery net
*lane: `discovery`*

Tier 3 of §1, written out. Intake is the only step that can add something the registry has
never heard of, and it feeds **two** funnels from one pass — the second matters more:

```
  discovery_daily.py      Indeed (Web Unlocker)  ─┐         ┌─▶ discovered_cache.json
                          LinkedIn (BD dataset)  ─┤ jobs    │   read by fetchers.fetch_discovery
                          LinkedIn targeted      ─┤         │   (21-day TTL applied at READ)
  discovery_telegram.py   6 public t.me/s feeds  ─┘         │
                                                            │
                          employer names not in ────────────┴─▶ research_companies.json
                          companies.csv                         drained by auto_expand (§3)
```

The jobs funnel is a safety net: it publishes roles at companies whose own board we cannot
read. **The names funnel is the point of this stage** — it is how `companies.csv` gets
bigger — and it is why a channel with almost no analyst roles in it can still be worth
reading.

**Judge every source here by NEW COMPANIES PER RUN, not by records or by jobs.** A source
can be alive, inside budget and completely useless at the same time, and one was: the
LinkedIn breadth sweep returned **0 new companies** while its record count looked perfectly
healthy. Nothing printed that number — only the aggregate — so nobody could see it. Each
source now prints its own:

```
[yield] indeed: 29 employers -> 15 NEW companies
[yield] linkedin: 147 employers -> 58 NEW companies
[yield] linkedin-targeted: 14 employers -> 1 NEW companies
```

**One of the four sources is not a discovery source at all.** `linkedin-targeted` asks about
companies **already in `companies.csv`** whose board returns zero, so by construction it can
almost never return an unknown employer — the 1 above is incidental. It is *backfill for
known-broken rows*, and it lives in this script for historical reasons. Keep it for what it
is (it published roles at 15 active companies whose own board reports 0), but never count it
towards discovery, and if the Bright Data budget ever binds, it is the first thing to cut.

### The four live sources, and what each one costs

`cloud` is the 05:00 run of 2026-08-23 read out of `cloud_state/source_health.json`;
`dry-run` is a full local execution of both scripts against sandbox copies of the state
files the same evening (17:30 UTC), which is the check to repeat before trusting a change
here — it exercises the real Bright Data account and the real Telegram fetches.

| source | mechanism | cost per digest | cloud | dry-run |
|---|---|---|---|---|
| `indeed` | `il.indeed.com/jobs` through the Bright Data **Web Unlocker**, one request per `INDEED_QUERIES` entry; parsed out of the `mosaic-provider-jobcards` JSON blob | 5 unlocker requests | 33 | 55 raw → 47 kept |
| `linkedin` | BD dataset `gd_lpfll7v5hcqtkxl6l`, `discover_new` by keyword — **the discovery source**: 4 keywords, unscoped, `time_range` "Past week", `limit_per_input` 100 | ~390 dataset records | 30 (2 kw × 15 then) | **391 → 58 new companies** |
| `linkedin-targeted` | same dataset, one input per broken-board company, **scoped with the `company` field**. Backfill, not discovery | ~65 dataset records | 78 | 62 → 1 new |
| `telegram` | public `t.me/s/<channel>` HTML previews — **no bot, no account, no API key, no quota** | free | **no key in the file at all** | 268 posts parsed |

Re-derive the cloud column with
`python -c "import json;print(json.load(open('cloud_state/source_health.json')))"`.

**The Indeed *dataset* is dead and the Indeed *unlocker* is not.** BD dataset
`gd_l4dx9j9sscpvs7no2` returned `dataset_size: 0, error_codes: {"rate_limit": 15}` on every
run for five days; it is commented out in `QUERIES` and must not be re-enabled. The
replacement path is `indeed_search()` — verified live 2026-08-23: `"data analyst"` returned
**15 cards** in one request, no snapshot job, no polling.

**The company name belongs in the `company` field, never inside `keyword`.** The dataset
takes a dedicated `company` input; `_targeted_inputs` built `keyword: "<name> data analyst"`
until 2026-08-23, so LinkedIn ranked on "data analyst" and read the employer name as spare
tokens. A/B tested live over the same 20 stale companies:

| form | records billed | on-target |
|---|---|---|
| `keyword: "<name> data analyst"` | **160** | **0** |
| `company: "<name>"`, `keyword: "data analyst"` | **25** | **22 (88%)** |

Scoping is **cheaper as well as accurate**, and the reason is worth internalising before
tuning any cap here: an unscoped keyword query always returns `limit_per_input` records —
LinkedIn can always fill 8 slots with *something* — while a scoped one returns only what
that employer actually has, which for a company with no open Israel analyst role is
nothing at all. That is why `cap` went 20 → 100. The whole 88-company list was then run for
real on 2026-08-23:

| | companies asked | records billed | on-target |
|---|---|---|---|
| before | 20 | 160 | 0 |
| after | **88** | **67** | **57 (85%)** |

**2.4× cheaper for 4.4× the companies.** It recovered live Israel analyst roles at 15 active
rows whose own board reports zero — Apple 8, Wiliot 8, Revolut 8, IEC 8, Infinidat 7,
Deel 4, Rakuten Viber 3 — which is `HANDOFF.md`'s largest open coverage item. `cap` and the
day-of-year rotation survive only as a bound if `stale.json` grows past 100.

**Both sweeps search for JOBS — the employer names are a by-product.** There is one
dataset here (`gd_lpfll7v5hcqtkxl6l`, LinkedIn *job listings*, `discover_by=keyword`) and
`company` is a FILTER on that job search, not a company lookup. The two sweeps differ only
in whether the filter is set:

```
breadth   {location: Israel, country: IL, keyword: "data analyst"}          x4 keywords
targeted  {location: Israel, country: IL, keyword: "data analyst",
           company: "Explorium"}                                            x88 companies
```

Both return job records; `normalize()` turns each into the common job shape for
`discovered_cache.json`, and `main()` separately harvests employer names that are not yet in
`companies.csv` into `research_companies.json`. That is why the two funnels in the diagram
above come out of one pass.

**One keyword is enough on the targeted sweep, and this was tested rather than assumed.**
The obvious worry is that scoping to `company` + `keyword: "data analyst"` misses a
"BI Developer" at the same employer. Measured 2026-08-23 over Apple / Outbrain / Snyk ×
`business intelligence` + `product analyst`, 15 records: Outbrain and Snyk returned **0** for
both, and all 15 Apple records were noise — Performance Modeling Architect, VLSI Product
Engineer, Full Stack Developer, Biomechanical Research Engineer — of which **8 were roles
the `data analyst` keyword had not returned, and not one was an analyst role**. Two of them
came back twice, once per keyword, i.e. billed twice for one posting. With `company` set,
LinkedIn's keyword match goes loose and extra keywords buy noise at full price. **Do not add
keywords to the targeted sweep**; add them to the breadth sweep, where an unscoped query is
ranked properly.

**`limit_per_input` is now the binding constraint, not the company cap.** Four of the 88
returned exactly 8, i.e. they were truncated. Raising 8 → 15 would cost at most
`7 × 4 = 28` more records on that distribution — still under 100 for the whole sweep — and
would recover roles at precisely the companies we cannot read directly. **Not done and not
measured (2026-08-23):** the 67 above is the number for `limit_per_input=8`, and changing
two dials when only one was measured is how a budget claim becomes fiction.

### Depth and recency are what make the breadth sweep discover anything

It ran at `limit_per_input=15` and returned **0 new companies** — 29 jobs, 27 employers, 25
of them already registry rows and 11 of them staffing agencies. LinkedIn ranks by relevance
and the head of that ranking is saturated with large employers and agencies; **unknown
companies live in the tail**, and the yield *accelerates* with depth rather than flattening:

| depth | employers | new companies |
|---|---|---|
| 15 (as shipped) | 15 | **1** |
| 30 | 29 | 3 |
| 50 | 46 | 3 |
| 100 | 84 | **15** |

`time_range` is honoured by the dataset and is the other half: `"Past week"` overlapped the
unfiltered run by only **14 of 61 records**, and it makes depth **self-limiting** — it bills
what was actually posted in the window (61 against a limit of 100), so a deep limit costs
nothing on a quiet keyword. It also wins on yield per record: 10 new companies from 61
records against 15 from an unfiltered 100. Together, measured on a full run:

| | records | employers | **new companies** |
|---|---|---|---|
| before (15, no window) | 30 | 27 | **0** |
| after (100, Past week) | 391 | 147 | **58** |

Both dials are env-tunable without a code change — `LINKEDIN_LIMIT`, `LINKEDIN_WINDOW` —
because the Bright Data quota cannot be read (below). **If new-company yield ever prints 0
again, this sweep has re-saturated and depth is the first dial.**

**Indeed fails silently about two queries in five.** `indeed_search` collapsed an unlocker
exception, a bot wall with no mosaic blob, and a genuinely empty result set into the same
bare `[]`, and the caller printed "0 cards" for all three — `§8` item 2, a mass zero read as
a measurement. `"business intelligence"` returned 0 on two consecutive runs and **15 on the
retry**, so it had never been empty. It now retries once and prints which of the three
happened.

**Total spend after these changes: ~455 dataset records + 5–10 unlocker requests per day**
(391 breadth + 62 targeted), against ~190 before. That is a deliberate trade — the breadth
sweep went from 0 to 58 new companies a day — and it is the number to revisit first if the
quota bites. Re-derive actual billing from the account
itself — this is the only reliable ledger, and the `/customer/balance` endpoint is
permission-blocked for this key:

```bash
python -c "
import os,json,urllib.request,collections
from bd_rescue import _load_secrets; _load_secrets()
r=urllib.request.Request('https://api.brightdata.com/datasets/v3/snapshots?status=ready',
    headers={'Authorization':'Bearer '+os.environ['BRIGHTDATA_API_KEY']})
d=json.load(urllib.request.urlopen(r,timeout=60)); c=collections.Counter()
for x in d: c[x['created'][:10]]+=int(x.get('dataset_size') or 0)
print(dict(sorted(c.items())), 'total', sum(c.values()))"
```

It reported **2,249 records billed in total** between 2026-08-15 and 2026-08-23. The
docstring in `discovery_daily.py` claimed "~40 records/day = ~1,200/mo" until 2026-08-23; it
predated the targeted sweep entirely.

**Google for Jobs is not available to this pipeline.** `pipeline/aggregators.py` still holds
`fetch_serpapi_google_jobs`, and it has **never run in the cloud** — `pipeline/run.py` gates
it on `AGGREGATOR_ENABLED`, which is set in no workflow, no test and no script. The obvious
substitute does not work either: `google.com/search?q=…&ibp=htl;jobs` through the Web
Unlocker returns **HTTP 200 with a zero-byte body** (tested 2026-08-23, 3 credits) because
the jobs widget is client-rendered; the same URL without `ibp=htl;jobs` returns 440,906
bytes, which is why `deep_validate.google_via_unlocker` works on organic links and a
jobs-widget version of it cannot. **UNVERIFIED 2026-08-23:** whether SerpApi's `google_jobs`
covers Israel at all — `daily-digest.yml` says it does not, `CLAUDE.md` says the quota is
exhausted, and the key answers HTTP 429, so neither claim is testable before 2026-09-01.
The decision is filed in `docs/BACKLOG.md`.

### Telegram channels

`CHANNELS` in `discovery_telegram.py`. All are secrethunter-format (title / company / city /
date / skills / seniority / link), so `parse_post` is deterministic and an unparseable post
is **skipped and counted, never guessed**. Probe a candidate before adding it — the number
that matters is how many of the ~20 messages on the front page parse:

```bash
python -c "
import discovery_telegram as d
p=d._fetch('https://t.me/s/CHANNEL'); m=list(d._MSG.finditer(p))
print(len(m),'msgs',sum(1 for x in m if d.parse_post(d._clean_text(x.group('body')),x.group('dt'))),'parsed')"
```

| channel | parsed/20 (2026-08-23) | why |
|---|---|---|
| `secretdatajobs` | 18 | the core feed |
| `secretmarketingjobs` | 18 | marketing/growth analytics |
| `secretproductjobs` | 18 | mostly PM — kept for the NAMES funnel |
| `secretcyberjobs` | 16 | added 2026-08-23; deepest Israeli employer pool |
| `secretfinancejobs` | 18 | added 2026-08-23; business/fintech analysts |
| `secretsalesjobs` | 18 | added 2026-08-23; revenue/sales-ops analytics |

Rejected on **relevance, not capability**: `secrethrjobs` (17/20) and `secretqajobs` (15/20)
parse fine and have essentially no analyst yield. Rejected because they have no public
`t.me/s` preview at all (0 messages — the parser can never see them): `secretbizdevjobs`,
`secretanalystjobs`, `secretdesignjobs`, `secretstudentjobs`, `secretjobs`. Rejected
2026-08-21 as unstructured: `israjobs`, `hightechforolims`, `jobs_SQL`.

Widening intake is cheap **because the resolver queue is not the bottleneck**: measured
2026-08-23, `auto_expand`'s drainable backlog was **77 entries against an
`AUTO_EXPAND_LIMIT` of 200 per run, twice a day**. Check before assuming otherwise:

```bash
python -c "
import json
from pipeline.companies import load_companies
from pipeline.recruiters import is_recruiter
e=json.load(open('research_companies.json',encoding='utf-8'))
h={r['company_name'].strip().lower() for r in load_companies(active_only=False)}
print(sum(1 for x in e if x.get('careers_url') and (x.get('name') or '').strip().lower() not in h and not is_recruiter(x.get('name'))))"
```

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

### Dry-running tomorrow's intake, end to end

Both scripts resolve `companies.csv` and `cloud_state/source_health.json` **relative to the
package, not to `cwd`** (`pipeline/companies.py` builds `CSV_PATH` from `REPO_ROOT`;
`pipeline/sources.py` builds `PATH` from `os.path.dirname(__file__)`), so a `cd` into a
scratch directory is NOT enough to keep a test run off the live state — redirect
`sources.PATH` explicitly. Everything else the two scripts touch is `cwd`-relative:

```python
import os, sys
sys.path.insert(0, "/path/to/repo"); os.chdir("/path/to/sandbox")   # holds copies of
from pipeline import sources                                        # companies.csv,
sources.PATH = os.path.join(os.getcwd(), "cloud_state", "source_health.json")
import discovery_daily, discovery_telegram                          # discovered_cache.json,
discovery_daily.main(); discovery_telegram.main()                   # research_companies.json,
                                                                    # cloud_state/{stale,telegram_seen}.json
```

That run costs one real day of quota (5 unlocker requests + ~190 dataset records) and takes
about 5 minutes, most of it Bright Data snapshot polling. The 2026-08-23 pass produced:
137 discovery jobs + 262 Telegram jobs merged, `discovered_cache.json` 205 → 517,
`research_companies.json` 1,233 → 1,332, **16 agencies rejected at the source** (9 on the
08-23 cloud run, before the Hebrew markers), `sources.stale()` empty, and a `telegram` key
in `source_health.json` for the first time. Do NOT commit the sandbox's state files: the
Telegram watermark advancing locally without the jobs being committed is how 79 roles were
lost on 2026-08-21.

## 2. Row lifecycle — every company carries a dated, evidence-based verdict
*lane: `registry` — one session at a time. The rules in this section are `shared`: every
lane that writes `companies.csv` obeys them.*

`companies.csv` is **the source of truth for coverage** — the registry of who gets read and
the log of what we know. Columns: `company_name, ats_platform, token, api_url, active,
notes`. Three real rows, one of each kind:

```csv
Fiverr,comeet,60.002,https://www.comeet.com/careers-api/2.0/company/60.002/positions?token=62188018812631018862C4188,true,
Google Israel,scrape,,https://www.google.com/about/careers/applications/jobs/results/?location=Israel,true,re-audit 2026-08-22: user-found listing URL; heading-group scrape verified 20 IL (page 1)
Imagindairy,scrape,https://www.imagindairy.com/careers,https://imagindairy.com/careers/,false,"chrome-verified 2026-08-22: careers live, CURRENT OPENINGS empty (true 0) - monitored candidate"
```

For API rows `api_url` is the endpoint; for scrape rows it is the **listings page URL**.
`notes` is the row-verdict log: each tool appends ` | <tool> <date>: <finding>` and strips
its own previous suffix, so a row accumulates one current verdict per tool.
**Who still replaces instead of appending** (re-derived 2026-08-24; the four tools this
paragraph used to name had all been fixed and it was never updated —
`grep -n '\[5\] *=' *.py` is the check, and it takes ten seconds):

- **Whole ROW, deliberately** — `retry_unreachable._row_for`, `recheck_suspects.py`'s
  *promote* branch (not its cleared branch, which appends), `validate_empty.py`'s promote
  branch. These build a row from scratch; there is no prior verdict worth keeping.
- **Whole CELL — all three fixed 2026-08-24.** `audit_empty_rows`, `crack_walled` and
  `deep_validate` each overwrote `notes` on their *activation* branch. An activation is
  exactly when you can least afford it: the assignment deleted the `alias-of` /
  `domain-dead` token that keeps the row out of the wrong pool, and the `dark-triage` mode
  that routed it there. All three now call `notes.replace_own`.
  `test_activation_branches_append_to_the_note_instead_of_replacing_it` walks the AST for
  `fr[5] = <not a call>` and fails on the next one. Note the older guard
  `test_every_note_writer_uses_the_append_log_helper` could not see these: a whole-cell
  assignment does no hand-rolled trim, so it passed that check for months.

Never copy the replace pattern for a diagnostic verdict: overwriting destroys the
`monitored candidate` / `host documented` tokens that `listing_hunt`'s fast-path keys on.
Taxonomy:

| state | active | meaning | who re-checks it |
|---|---|---|---|
| (verified board) | true | endpoint/listing verified to return real jobs | every digest / daily refresh |
| `… N/0 IL` (N>0) | true | board healthy, N global roles, none in Israel | every digest — lights up automatically |
| `… 0/0 IL` | true | zero of zero: **may be a dead token/moved board**, `pipeline/health.py` calls this `empty-board`. Discriminator: comeet returns HTTP **400** for dead creds, **200 + `[]`** for a live empty board | digest → `stale.json` → 06:00 self-heal (5 strikes) |
| `host documented, 0 IL now` | false | walled-ATS host found, extraction unproven | daily probe + hunt |
| `monitored candidate` / `host documented` | false | real page documented, extraction unproven | daily probe + 14-day re-hunt |
| `probe-woken: re-hunt pending` | false | probe saw signals rise; awaiting same-day hunt | today's 14:00 hunt (fast-path) |
| `no listing found` / `no ATS detected` | false | full render found nothing parseable | weekly audit + hunt cron |
| `unsupported ATS <x>` | false | ATS known, no extraction path yet | crack_walled / listing-hunt |
| `domain-dead …` | false | DNS/conn dead (GET-verified, lenient TLS — strict TLS on the scanning machine produced 6 false positives) | re-tested after 30d by the Sunday audit; **a revived domain clears the flag automatically** |
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
   │  │                   │ listing_hunt 14:00 (finds listings URL, verifies ≥1 IL job)
   │  │                   │ crack_walled / deep_validate (on demand)
   │  │                   │ audit_empty_rows (Sun) — re-verifies ALL parked rows
   │  └───────────────────┘
   │
   │ scrape yields 0 for ROT_PARK_DAYS(3) → parked "scrape rotted" → back to listing_hunt
   │ API fetch fails → stale.json → self-heal 06:00 re-resolves (weekly retry, 5 strikes)
   ▼
 parked: "monitored candidate" (URL known, extraction unproven)
   │  probe_candidates (05:00 daily) sees job/Israel signals rise vs baseline
   ▼  → note becomes "probe-woken: re-hunt pending"
 listing_hunt 14:00 takes the FAST-PATH: scrape the stored URL directly; verified → ACTIVE
```

Terminal-ish states: `defunct:` (company gone — permanently excluded) and `domain-dead`
(DNS/conn dead, GET-verified — candidate for defunct research). Everything else is
re-checked on some cadence; **a failing API row keeps `active=true`** (its roles stay on
the job board via the failed-company exemption, §5a) while a rotting *scrape* row is
parked, because only parked rows are visible to the hunt/audit machinery.

### The verdict-string rule (read before changing ANY resolver)

Re-check pools are **allowlists of note substrings**, and the allowlist now lives in ONE
place: `pipeline/verdicts.py` (`TOKENS` / `in_pool` / `stale`). Add any new verdict string
to `TOKENS` there. `audit_empty_rows` and `deep_validate` import `in_pool`; the tools that
legitimately want a subset (`crack_walled` → walled ATSes, `probe_candidates` → documented
candidates) narrow it explicitly rather than re-implementing it. Hand-maintained copies
drifted once already — `listing_hunt` knew 15 tokens while the other two knew 7, leaving
**64 companies invisible to two pools**. If a string is missing from `TOKENS`,
its coverage is lost with no error anywhere. This is exactly how 52 rows became stranded
(`bd_rescue.py` wrote `scanned via brightdata; …`, which matched none of them).
Corollary: a diagnostic verdict must **append** (`base | tool date: finding`), never
replace the cell — overwriting also destroys the `monitored candidate` / `host documented`
tokens that `listing_hunt`'s fast-path keys on.

**The pool is defined in three places, and they do not agree** (measured 2026-08-24).
`pipeline/verdicts.TOKENS` is the module that claims to be the single source, but
`listing_hunt.main()` still carries its own 17-token regex and `check_invariants.POOL` a
third copy. Diff: `url-cleared` and `url-flagged` are in both inline copies and **missing
from `TOKENS`**, so the 57 rows carrying one of them are invisible to `audit_empty_rows`
and `deep_validate`, which import `in_pool`. And `verdicts.TERMINAL` omits `alias-of`,
which the two inline copies exclude — that omission is what put 2 alias rows into an
*activating* pool (below). Neither is fixable from this lane (`pipeline/verdicts.py` is
shared plumbing); both are in `docs/BACKLOG.md` under "One re-check pool definition" and
"One terminal-state list", and
`test_the_three_copies_of_the_re_check_pool_still_agree_where_they_are_supposed_to` pins
the current gap so it cannot grow while the fix waits. Reproduce:

```bash
python -c "
from pipeline.verdicts import TOKENS
import check_invariants as ci
t={x.lower() for x in TOKENS}
c={x.lower() for x in ci.POOL.split('|') if x and '(' not in x}
print('in the inline copies, NOT in TOKENS:', sorted(c-t))
print('in TOKENS, not in check_invariants :', sorted(t-c))"
```

**Append through `pipeline/notes.py`, never by hand** (2026-08-23). The cell is capped at
220 chars, and every writer used to make room by SLICING the base — `(base + " | " + seg)[:220]`
or `base[:220 - len(seg) - 3]`. The newest segment lives at the END of the base, so the trim
ate exactly the thing worth keeping: 87 rows came to read `dark-triage 2026-08-22: page-emp`
(also `page-e`, and on one row `pa`), naming a mode no downstream filter matches.
`notes.append()` drops OLD WHOLE segments until the new one fits; `notes.replace_own(marker)`
re-stamps this tool's own segment and leaves every other tool's alone. Keep segments SHORT —
one full URL in a segment is 117 characters and will evict everything else.
`test_every_note_writer_uses_the_append_log_helper` fails on the next hand-rolled trim.

Every re-check filter must have a **staleness escape** (`_stale_hunt` 14d, `_revalidatable`
30d, `_recrackable` 30d). A filter of the form `"tool-name" not in note` freezes coverage
forever — that pattern has been introduced and removed three times.

### The activation rule (2026-08-23 — read before flipping any row to active)

"There are Israel jobs on this page" is not "these are THIS company's jobs", and it is not
"this is a page that lists jobs". A row may only be activated when all three hold:

1. `pipeline.aggregators.is_aggregator(url)` is false — an aggregator's "similar jobs"
   sidebar is other employers' roles.
2. `pipeline.company_identity.is_foreign(company, url)` is false — FairFly was activated off
   fireflyspace.com (25 Firefly Aerospace roles), SimilarTech off greenhouse `similarweb`
   (25 of Similarweb's), "Moonsite - Moonsoft Development" off Moon Active's Ashby board.
   For an ATS host the identity is the TENANT SLUG, and a rebrand or acquisition looks
   identical to a mis-resolution — Momentis really does post under `memic` — so a `weak`
   verdict is settled by `page_mentions_company(..., strict=True)`, never by the domain
   alone.
3. `pipeline.company_identity.looks_like_a_job_listing_page(url)` is true — `SCRAPE_ASSUME_IL`
   makes every card on the page an Israel role, so a nav menu scores like a board:
   `iai.co.il/solution/research-academy-space` "verified 6 IL" whose titles were "Domain
   Operations" and "Press Releases".

`test_every_activation_path_checks_company_identity` walks the AST of every root script for
`row[4] = "true"` and fails if that module never consults `company_identity`.

### The single-writer rule (most dangerous rule here — read before any write)

`companies.csv` writers must **re-read the file immediately before every write**
(read-modify-write per verdict, matching on **company name, never row index**) and never
hold a start-of-run snapshot; two concurrent snapshot-writers silently destroy each other's
verdicts (lost-update incident 2026-08-22).

**All 20 `companies.csv` writers, by safety class** (verified 2026-08-22):

- **Compliant** (re-read + match by name before every write): `crack_walled.py`,
  `probe_candidates.py`, `listing_hunt.py`, `audit_empty_rows.py`, `deep_validate.py`,
  `scan_dead_domains.py`, `refresh_scrape_cache.py` (parking pass).
- **Modified-rows merge** (equally safe — merges only the names it changed into a fresh
  read): `bd_rescue.py`, `retry_unreachable.py`, `wayback_rescue.py`, `validate_empty.py`,
  `validate_bd.py`, `recheck_suspects.py`.
- **Append-only** (safe): `auto_expand.py`, `comeet_resolve.py`, `ingest_research.py`,
  `resolve_any.py`, `resolve_parallel.py`, `resolve_unknowns.py`.
  (`resolve_deep.py` and `scrape_batch.py` write only `out/*.csv`, never the registry.)
- **Line-based snapshot, sub-second window** (tolerated): `apply_resolved.py`.

No whole-snapshot index-keyed writer remains. If you add one it will silently revert
concurrent verdicts — use one of the first three patterns.

**Never DELETE a row. Park it with a reason** (2026-08-24). No tool deletes rows — every
writer above is read-modify-write or append-only — but a human commit does, and a deletion
is the one registry edit that does not survive the git layer. Worked example, reproducible
with `git log`:

| commit | rows | what happened |
|---|---|---|
| `9c4372ef` | 1190 | `Time To Know` deleted on purpose ("time.com is Time To Know") |
| `8644d8fd` | **1191** | a concurrent cloud run's conflict path ran `merge_csv_rows`, whose `changed` set still held that row, and `target.append(r)` **resurrected it** |
| `0180e755` | 1190 | re-deleted, silently, inside a commit whose subject is about Oracle HCM |

`check_invariants.py` checks the registry's SHAPE, never its SIZE, so all three passed.
Fifteen name-deletions exist in the whole 68-commit history of the file
(13 of them one deliberate purge of LinkedIn-sidebar-poisoned rows on 2026-08-21), and
nothing anywhere reported one. Two rules follow:

1. **A row leaves the registry by being parked, not by being removed.** A parked row keeps
   its evidence, stays in a re-check pool if it should, and cannot be resurrected into a
   different meaning by a merge. Use `defunct:`, `alias-of`, `domain-dead`, or an explicit
   `removed <date>: <reason>` segment.
2. **If you do delete, the reason must be in the row's own note before it goes** — that is
   the only place `registry_health.py` can find it afterwards.

`registry_health.py` is the detector: it keeps a census in
`cloud_state/registry_census.json` and reports every vanished name with its last known
note, split into explained and unexplained. It never writes `companies.csv`.

```bash
python registry_health.py            # census diff, pools, ladder, alarms — no writes
python registry_health.py --census   # re-baseline after an intentional removal
```

**Concurrency has TWO layers — both must be handled.** In-process discipline (above)
protects writers on one machine. The **git layer** needs `merge_csv_rows.py`: a cloud run
commits a file whose baseline may be hours old, so `git pull --rebase` hits a content
conflict and the retry loop would discard the entire run (a 3.5-hour listing-hunt cycle was
lost this way, 2026-08-22). Every csv-committing workflow therefore snapshots
`/tmp/base.csv` right after checkout, and on conflict resets to origin and replays only the
rows this run changed (`merge_csv_rows.py base ours target`). Copy that pattern into any
new workflow that writes the registry.

**Every workflow that edits `companies.csv` must `git add` it.** The digest workflow does —
the candidate probe writes verdicts there while `candidate_probe.json` advances baselines;
committing one without the other loses the wake *and* consumes its signal.

Cloud workflows that commit the csv serialize via the `repo-state` concurrency group —
eight of them (audit-coverage, auto-expand, deep-validate, listing-hunt, retry-unreachable,
scrape-refresh, self-heal, triage-dark) — **except `daily-digest.yml`**, which uses its own
group, so a digest CAN overlap an audit/hunt run; both re-read, so verdicts survive. A local `--apply` run adds a third
writer: avoid the cron windows in §4 (and never run two browser-driving tools at once —
Playwright sync instances conflict).

### Who re-checks a parked row — the ownership matrix

Every inactive row must be owned by at least one *recurring* job, or it is permanently dark.
**The matrix below is no longer typed by hand** — `registry_health.pools()` mirrors each
scheduled tool's own row filter, so one command re-derives it and the counts cannot rot:

```bash
python registry_health.py | sed -n '/re-check ownership/,/OWNED BY NOTHING/p'
```

Counts below are that command's output on **2026-08-24**, after this session's two pool
fixes. Ownership is by note content, not by mode. **The figures exclude each tool's
staleness cooldown** — a cooldown delays a re-check, it does not remove ownership — so the
rows a given night actually processes are fewer: `crack_walled` owns 28 and `_recrackable`
(daily) left **7** for tonight; `audit_empty_rows` owns 255 and `AUDIT_TTL_DAYS` (30) left
31 locally, but `state/` is gitignored so the cloud run re-audits all 255 (§5).

**Update 2026-08-23 — `page-empty` rows are ACTIVE now.** They were inactive, which meant a
role posted at one of them waited for the next triage cycle to be seen. But a `page-empty`
row has a *validated, working* careers page that simply has no openings today: that is a
healthy daily source, not a dark row. 130 were activated and are scraped every day like any
other company. Two rules follow, both now enforced:
- **Empty is not broken.** `refresh_scrape_cache` used to park any active scrape row that
  came back empty 3 days running — in this market a company can have no openings for a
  month. Empty rows are now NEVER parked; a 45-day streak only asks triage to re-read the
  page (it can tell "no openings" from "openings we fail to extract") and the row stays
  active throughout. Only ERRORS park a row, at 7 days.
- Consequently the table below applies to rows that are still `active=false`.

| tool | cadence | rows | claims rows whose note matches | activates? |
|---|---|---|---|---|
| `triage_dark` | daily 18:00 | 270 | `no listing found` / `no IL listing` / `no ATS detected` / **`dark-triage`** | no — but its rewrite drops the old `page-empty` stamp, re-opening the hunt |
| `listing_hunt` | daily 19:00 | 244 | the wide parked-shape regex, **minus** `page-empty`, terminal and recruiters | **yes** |
| `repair_extract_gap` | daily 19:00 | 25 | `dark-triage …: extract-gap` | **yes** |
| `probe_candidates` | daily 05:00 | 181 | `monitored candidate` / `host documented` / `no IL listing` | no — `_wake_note` strips every stale segment |
| `crack_walled` | daily 19:00 + weekly | 28 | `unsupported ATS` + not terminal + not recruiter | **yes** |
| `scan_dead_domains` | daily 05:00 | — | liveness only — **never looks at roles** | no |
| `audit_empty_rows` | weekly Sun 04:00 | 255 | `verdicts.in_pool` + not terminal + not recruiter + not audited in `AUDIT_TTL_DAYS` (30) | **yes** |
| `deep_validate` | weekly Sat 04:00 | 255 | `in_pool` + `_revalidatable` (30d) + not terminal + not recruiter | **yes** |

**Every activating pool must exclude the terminal states itself.** `verdicts.in_pool()`
does not: `TERMINAL` there is `defunct / domain-dead / duplicate of / redundant / recruiter`
and **omits `alias-of`**. On 2026-08-24 that put `GE HealthCare Israel` and `eBay Israel`
into `audit_empty_rows`' pool, and three more (`Chakratec`, plus those two) into
`crack_walled`'s, which had no terminal filter at all. Both tools activate directly, and an
alias row points at a board that *works* — so the audit would have searched, found that same
board, verified it with real Israel jobs and re-activated the duplicate: every eBay role
published twice under two company names. `check_invariants` check B would not catch it
(the names differ). Pools after the fix: audit 260 → **255**, crack 10 → **7**.
Guarded by `test_no_activating_pool_can_re_open_a_terminal_row`.

**`audit_empty_rows` and `deep_validate` now select the identical 255 rows** — same
predicate, different depth (raw HTML vs Chromium render + network sniff), 24 hours apart.
That is the clearest consolidation target in this lane; it is in `docs/BACKLOG.md`.

Two traps this matrix exists to prevent, both of which were live:
- **An inert wake.** `probe_candidates` cleared `listing-hunt|crack-walled` but not
  `dark-triage`, so `listing_hunt._triaged_page_empty` still excluded every woken
  page-empty row: 105/105 wakes went nowhere. A wake must clear *every* stamp that any
  downstream filter excludes on.
- **Note erosion retiring a row from its own pool.** Each re-stamp trims the base note to
  fit 220 chars; once the original verdict eroded (`no IL listing; monitored candidate` →
  `no `), the row matched no pool at all. `triage_dark.TARGET_NOTES` therefore matches its
  **own** `dark-triage` stamp, which makes it self-sustaining.

(Moved here from `HANDOFF.md` §1b on 2026-08-23: it is a durable rule, not session news.)

## 3. Resolution ladder — how a dark company becomes covered
*lane: `registry`*

New names enter via discovery (`research_companies.json` queue) or manual seeding. Then:

1. `auto_expand.py` (cron 08:00/20:00): deterministic `resolve_deep` — recognizable ATS
   URLs, iframes. Failures get ONE shot at tier 2 (capped `LLM_RESOLVE_CAP`/run; excess
   **deferred**, not parked).
2. `resolve_llm.py`: evidence bundle (page fetch + SerpApi search + ATS-hint extraction) →
   single `claude -p` proposal `{platform, token, api_url}` → **verified** via the real
   fetcher. One retry carrying the verification error.
3. `listing_hunt.py` (cron 14:00): for rows still dark — find the LISTINGS URL (harvested
   links; Claude picks; rebrand redirects resolved), verify via `scrape_universal`.
   Woken/documented rows take the **fast-path**: scrape the stored URL first.
4. `deep_validate.py` / `crack_walled.py` (on demand): Chromium render + network-request
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
- Slug/tenant must resemble the company name — `_slug_matches` (`audit_empty_rows.py`),
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
  Since 2026-08-23 all four activation paths call `company_identity`, and a `weak` domain
  verdict is settled by whether the fetched page NAMES the company as a phrase.
- **Every rung that searches needs all three fallbacks.** The ladder is SerpApi (cheapest,
  currently useless) → `deep_validate.ddg` (free) → `deep_validate.google_via_unlocker`
  (Bright Data, capped by `DEEP_BD_SEARCH_CAP`). Verified against the live account on
  2026-08-24: `total_searches_left: 0`, `this_month_usage: 250`, Free Plan, resets
  2026-09-01 —
  `python -c "import os,json,urllib.request;from bd_rescue import _load_secrets;_load_secrets();print(json.load(urllib.request.urlopen('https://serpapi.com/account?api_key='+os.environ['SERPAPI_KEY'])).get('total_searches_left'))"`.
  So a SerpApi-only rung returns `[]` **before it makes a request**, and a whole run of
  "found nothing" is indistinguishable from "cannot search".
  `resolve_broken._careers_url_via_serp` was given the fallback on 2026-08-23.
  **`audit_empty_rows.serp()` was not, and it got it on 2026-08-24** — it is the search
  behind the Sunday audit's phase 2 over the ~255-row parked pool, i.e. the rung that finds
  boards which MOVED rather than broke, and it had been a silent no-op for a week. Measured
  after the fix (3 pool companies, SerpApi still at 0): `Upsolver` 4 URLs, `Cognata` 4 URLs
  (`cognata.com/hiring/` — an iCIMS row), `Sproutt` 0; before the fix all three were `[]`.
  When every rung comes back empty the tool now prints a `::warning::` naming which
  credential was missing, because that is a broken run, not a measurement.
- **DuckDuckGo is rate-limited from the dev machine, not blocked.** Repeatedly documented
  here as "returns nothing"; measured on 2026-08-24 it returned 4 good URLs for `Wix`
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
| `cloud_state/scrape_rot.json` | consecutive empty/error days per scrape row | refresh_scrape_cache.py |
| `cloud_state/firmographics.json` | **the shared, git-mergeable export of the `firmographics` table.** sqlite cannot be merged, so this text file is what the local and cloud stores converge through; the digest reads sqlite ∪ this file (fresher `as_of` wins) and writes the union back | `research_firmographics.py --export`, `pipeline/run.py` |
| `cloud_state/pipeline_stages.json` | which nightly stage last finished and how much it did (`pipeline/stages.py`) — the digest warns in its audit when a prerequisite stage did not run today | each stage's workflow, via `python -m pipeline.stages stamp <stage>` |
| `cloud_state/source_health.json` | per discovery source: records returned this run, and the last day it returned any (`pipeline/sources.py`). A source that goes quiet is a workflow warning AND a line in the digest audit — Indeed returned zero for five days unnoticed | discovery_daily, discovery_telegram |
| `state/` (gitignored) | resume markers (audit done-list). Written in the cloud too but **never committed**, so the Sunday audit re-audits every parked row from scratch (a SerpApi budget fact) | audit/local runs |

(The single-writer and commit-together rules live with the csv schema in §2.)

## 5a. Fetch-failure semantics (what a broken careers board does to our job board)
*lanes: `ats-fetch` · `scraper` · `infra`*

A company whose fetch raises does **not** crash the run (`pipeline/run.py` per-company
try/except): it lands in `companies_failed` and gets `status: fetch-error` in `stale.json`.
Its already-matched roles **stay on the board** — `_alive` in `run.py` exempts failed
companies so a transient outage doesn't blank a company — bounded by the 14-day
`first_seen` window. Repair path: `stale.json` → 06:00 self-heal (`resolve_broken.py`,
re-resolves via careers-page capture, needs `SERPAPI_KEY` for the search step; retries at
most weekly, abandons after 5 strikes → "discovery covers it").

Scrape rows rot differently and are handled in `refresh_scrape_cache.py`: an **error**
carries the previous jobs forward for at most `CARRY_MAX_DAYS` (14) — never forever — while
an **empty** result carries nothing. Either state persisting `ROT_PARK_DAYS` (3) days parks
the row (`scrape rotted …`) so the listing-hunt pool re-finds and re-verifies it, because
**active rows are otherwise invisible to listing-hunt and the weekly audits**.

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
  **24 of the 66 workflow steps are `continue-on-error`, so a green run can still hide a
  failed step** — read the step, not the badge.
- Coverage snapshot:
  ```bash
  python -c "import csv;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>5];print(len(r),'rows',sum(1 for x in r if x[4]=='true'),'active')"
  ```
- **Orphan check — run after touching ANY row filter** (see the ownership matrix in §2). Must print 0; a non-zero count
  is companies no recurring job will ever look at again:
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
  common job shape (§0) — copy `fetch_ashby` as the simplest template — add the `FETCHERS`
  entry, then wire **all four detection tables** or no resolver will ever discover the
  platform on its own: `SIGS` (`audit_empty_rows.py`), `_HTML_ATS` (`resolve_broken.py`,
  self-heal), the pattern list **and platform enum** in `resolve_llm.py`'s prompt, and
  `ATS_HOST` (`pipeline/health.py`). `deep_validate.py` re-imports `SIGS`, so it needs
  nothing. Verify with the `verify(...)` one-liner above before adding rows.
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
5. **DuckDuckGo is blocked from this developer machine** (returns nothing) but works on
   GitHub runners. Local resolution work needs the Bright Data path
   (`deep_validate.google_via_unlocker`). SerpApi quota resets **2026-09-01**.
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
