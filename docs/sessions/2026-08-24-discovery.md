# 2026-08-24 — `discovery` lane

> **Date note.** The session was briefed as 2026-08-24; the machine clock reads
> **2026-08-23 17:37 UTC** (`date -u`). Every measurement below is dated **2026-08-23**,
> which is when it was taken. Only this filename follows the brief.

Scope: the intake layer — `discovery_daily.py`, `discovery_telegram.py`,
`pipeline/aggregators.py`, `pipeline/recruiters.py`, and the new `ARCHITECTURE.md` §1a.
Nothing else was written. Bright Data spend: **945 dataset records + 14 Web Unlocker
requests** — 190 on the first dry run, 126 on the targeting A/B and full-scale tests, 176 on
the depth/recency experiments, 453 on the final full run. Claude tokens: **0** — nothing here calls `claude -p`. SerpApi: 0 (429, exhausted).
For scale: the account has billed 2,249 records in total since 2026-08-15.

## What was wrong

Four defects, every one silent, every one in the class `ARCHITECTURE.md` §8 item 1 calls
"a row quietly leaving a re-check pool".

**1. Telegram was invisible to the dead-source detector.** `discovery_telegram.main()`
`return`ed as soon as a scan produced nothing, and the `sources.record()` call sat *below*
that return. `pipeline/sources.py` exists for exactly one purpose — to notice that a source
which used to produce has stopped — and it was written because the Bright Data Indeed
dataset returned zero for five days with a green workflow every morning. Proof it never saw
Telegram: `cloud_state/source_health.json` held `indeed`, `linkedin` and `linkedin-targeted`
and **no `telegram` key at all**, while `discovered_cache.json` held **104 telegram-sourced
jobs**. A source that cannot record a zero can never be reported dead.

It also recorded `len(added)` — jobs surviving dedup against the cache — so a channel
producing normally but repeating a role we already held would have scored 0 and read as
dead. It now records posts *parsed*.

**2. The targeted LinkedIn sweep asked about the same 20 companies every day, forever.**
`_targeted_inputs` took `unresolved[:20]`, and `cloud_state/stale.json` is rebuilt every
digest in `companies.csv` row order (`pipeline/health.py`'s `record` iterates
`results.items()`), so the slice was a stable prefix, not a sample. **110 stale entries, 20
searched, 90 never once.** It also spent inputs on `misconfig-scrape-on-ats` rows — 22 of
the 110 — which is a warning about the *row's shape*, not a broken board; the digest reads
those companies fine every morning.

Fixed: the window advances by day-of-year over the three reasons that mean "the board has
moved" (`empty-board`, `regressed-to-zero`, `fetch-error`). *(Superseded later the same
session — see the follow-up below. Once the query was scoped by `company` the whole list fit
in one run for 67 records, so the rotation now only bounds a `stale.json` past 100.)*

**3. `per_source["indeed"]` meant something different from every other key** — post-filter
unique jobs where the dataset sources record raw records. Same field, two meanings, and an
Indeed page whose cards were all rejected as junior/stale would have scored as a dead
source. Now raw records everywhere; the kept count prints beside it.

**4. A Latin entry in `_CONFIRMED` does not cover the Hebrew spelling.** The file's own
docstring warns about this ("a Latin-only list let one back in as an ACTIVE row after the
English ones were purged") and it was live again. **One** Indeed query returned
`קומבלק איי.טי. בע"מ` (Comblack IT — `comblack` on the list since 2026-08-17) and
`חברה דיסקרטית` ("discreet company", the Hebrew of the `confidential` entry). Re-running the
scan over the 99 companies a full intake pass queued found two more: `קבוצת יעל` (Yael
Group) and `לוג-און תוכנה` (Log-On Software) — **both already on the Latin list**. All four
passed `is_recruiter` AND `looks_like_junk`, i.e. each was one `auto_expand` run from an
active row. Agencies rejected at the source went from **9 → 16** in one pass.

Verified no coverage was lost: **0** existing registry rows match the four new markers, and
`0` active rows are now flagged as recruiter.

## What was added

**Three Telegram channels — `secretcyberjobs`, `secretfinancejobs`, `secretsalesjobs`.**
Keyless, no quota, no key. Seventeen candidates were probed for the secrethunter layout the
parser needs; the number that decides is how many of the ~20 front-page messages parse:

| verdict | channels |
|---|---|
| added | `secretcyberjobs` 16/20 · `secretfinancejobs` 18/20 · `secretsalesjobs` 18/20 |
| rejected on **relevance**, not capability | `secrethrjobs` 17/20 · `secretqajobs` 15/20 — they parse fine, they have no analyst yield |
| no public `t.me/s` preview (0 messages — the parser can never see them) | `secretbizdevjobs` · `secretanalystjobs` · `secretdesignjobs` · `secretstudentjobs` · `secretjobs` |

Widening intake is cheap here **because the resolver queue is not the bottleneck**:
`auto_expand`'s drainable backlog was **77 entries against an `AUTO_EXPAND_LIMIT` of 200 per
run, twice a day**. That is the number to re-check before adding more (command in §1a).

## What the whole layer does when it runs — measured, not asserted

Both scripts were run end to end against sandbox copies of every state file, in the
workflow's order. `pipeline/companies.py` and `pipeline/sources.py` resolve paths against
the **package, not `cwd`**, so `sources.PATH` had to be redirected explicitly or the run
would have written live state — the recipe is in §1a.

*(This run is the PRE-fix configuration — 2 breadth keywords, unscoped targeting at 160
records. The follow-up section below replaces both numbers.)*

```
[indeed:data analyst] 15 cards        [linkedin] 30 records
[indeed:business intelligence] 0      [linkedin-targeted] 160 records
[indeed:BI developer] 10 cards        [secretdatajobs]    3 parsed,  1 skipped
[indeed:product analyst] 15 cards     [secretmarketingjobs] 0 parsed, 1 skipped
[indeed:אנליסט] 15 cards               [secretproductjobs]  4 parsed,  1 skipped
[indeed] 55 raw -> 47 kept            [secretcyberjobs]   81 parsed, 19 skipped
                                      [secretfinancejobs] 91 parsed,  9 skipped
                                      [secretsalesjobs]   89 parsed, 11 skipped
137 discovery jobs cached · 262 telegram jobs merged
16 agencies rejected before they could become rows · 99 new companies queued
```

| | before | after |
|---|---|---|
| `discovered_cache.json` | 205 | 517 |
| `research_companies.json` | 1,233 | 1,332 |
| `source_health.json` keys | 3 | 4 (`telegram` present for the first time) |
| `sources.stale()` | — | `[]`, no dead source |

Then the same cache through tomorrow's classify step (`--no-llm`, no writes): the read-side
filters in `fetchers.fetch_discovery` drop 146 of the 517 (**103 past the 21-day TTL, 44
recruiters** — Experis Israel, MalamTeam, Log-On Software, G-STAT, Gotfriends, Moveo Source
… — 0 mis-attributed), leaving 371 against 184 before. **Accepted roles 39 → 42.**

Be honest about what that costs: `keyword_nollm` went 49 → 62, so ~13 more ambiguous titles
reach the LLM tier. That is a **one-off**, not per-day — `llm_cache` is keyed
`company|title`. Against 163 LLM calls on the 08-23 digest it is under 10%, and the real
return is not the +3 roles, it is the 86 new employer names, which is the path by which
`companies.csv` grows.

The **backfill was deliberately not committed.** Three new channels walk back 5 pages on
their first run; letting that happen in the cloud keeps the jobs and the Telegram watermark
in the same commit. Advancing the watermark locally and committing only part of it is how
79 verified roles were lost on 2026-08-21.

## Follow-up, same session: two challenges from the operator

**"20 on LinkedIn seems a low limit."** It was our own default argument, not a platform
limit — but raising it was the wrong dial, and finding that out replaced the fix above.
Re-measuring the day's own targeted run: of **160 records spent on 20 named companies, 0
came back for any of the 20**, and 0 for any of the 110 stale companies. The 26 jobs it
produced were J&J MedTech, Vishay, IAI, Ben-Gurion University — a generic sweep wearing a
targeted label.

The cause: **the dataset takes a dedicated `company` input field** and the code was
concatenating the name into `keyword` ("Explorium data analyst"), so LinkedIn ranked on
"data analyst" and read the name as spare tokens. A/B tested live, same 20 companies:

| form | records billed | on-target |
|---|---|---|
| `keyword: "<name> data analyst"` | 160 | **0** |
| `company: "<name>"` | 25 | **22** |

Scoping is cheaper *because* it is accurate: an unscoped query always fills
`limit_per_input` (LinkedIn can find 8 of something), a scoped one returns only what that
employer has. So `cap` went **20 → 100** and the full list was run for real:

| | companies | records | on-target |
|---|---|---|---|
| before | 20 | 160 | 0 |
| after | **88** | **67** | **57 (85%)** |

**2.4× cheaper for 4.4× the companies**, recovering live Israel analyst roles at 15 active
rows whose own board reports zero: Apple 8, Wiliot 8, Revolut 8, IEC 8, Infinidat 7, Deel 4,
Rakuten Viber 3, At-Bay 2, Aman Group 2, Menora 2, Dell 1, ASTERRA 1, Chargeflow 1, Utila 1,
Rhino 1. That is `HANDOFF.md` watch-item 0, the largest open coverage item in the repo.

The freed budget bought two more keywords on the *breadth* sweep (2 → 4: `product analyst`,
`BI developer`), because the broken targeted sweep had been supplying accidental breadth —
17 new employers — and that disappears with the fix. **Net daily spend 190 → ~127 records.**
Whether swapping accidental breadth for two deliberate keywords is net-positive is NOT
measured beyond one run.

Two things deliberately left alone: `limit_per_input` is now the binding constraint (4 of
the 88 returned exactly 8, i.e. truncated; 8 → 15 would cost ≤28 more records) but changing
two dials when only one was measured is how a budget number becomes fiction. And I found a
bug in my own change before it shipped — `cap=100` over an 88-long list made the
wrap-around emit 12 duplicate inputs, each a second bill; guarded by
`test_the_targeted_window_never_asks_about_the_same_company_twice`.

**"What are you searching on LinkedIn — aren't you searching for jobs?"** Yes, jobs, always.
One dataset (`gd_lpfll7v5hcqtkxl6l`, LinkedIn *job listings*, `discover_by=keyword`), and
`company` is a filter on that job search, not a company lookup. The two funnels come out of
one pass: `normalize()` writes the job records to `discovered_cache.json`, and `main()`
separately harvests employer names not already in `companies.csv` into
`research_companies.json`.

The question is worth more than the clarification, because it points at a gap I had left
open: the targeted sweep asks each of the 88 companies about **one** keyword, `data analyst`,
while the product also covers BI / product / marketing analytics. So I tested it —
Apple / Outbrain / Snyk × `business intelligence` + `product analyst`, 15 records:

- Outbrain and Snyk returned **0** for both keywords.
- All 15 Apple records were noise: Performance Modeling Architect, VLSI Product Engineer,
  Full Stack Developer, Biomechanical Research Engineer. **8 were roles the `data analyst`
  keyword had not returned, and not one was an analyst role.**
- Two came back twice, once per keyword — billed twice for one posting.

So with `company` set, LinkedIn's keyword match goes loose and extra keywords buy noise at
full price. **One keyword on the targeted sweep is correct**; breadth belongs on the
unscoped sweep, where ranking still works. Recorded in §1a so nobody re-runs it — this is a
change I would have made on intuition and it would have cost records for nothing.

**"Why can't you verify Hebrew-named companies — can't you search the web?"** Fair; I could
and should have. Researched, and the answers were not what I assumed:

- **עידור מחשבים (Idor Computers) → excluded.** ~100 staff, "professional IT outsourcing
  services" for banks and insurers. Settled not by the web but by its own posting, which
  names a CLIENT and not itself: `אנליסט/ית אקטואר לחברת ביטוח מובילה בפתח תקווה` —
  actuarial analyst *for a leading insurance company*. Same class as `log-on software` /
  `abra` / `malam team`.
- **מטריקס (Matrix) → NOT excluded, and I had this backwards.** 16,000 staff, TASE-listed
  (MTRX). It sells outsourcing but is also a large direct employer, **and we already scan
  it**: `Matrix` (comeet) and `Matrix IT` (breezy) are both active rows, deep-verified 25/0
  and 34/0 IL on 2026-08-21. Blocking the Hebrew form would have contradicted two verified
  rows. The actual defect is that `מטריקס` is a *third identity* for one employer — an alias
  problem, not a recruiter one.
- **Software AG-SPL → NOT excluded.** It surfaced from the same scan
  (`Network security analyst לארגון בטחוני במרכז`) but it is Software AG's Israeli R&D
  centre, formerly SPL. The client-naming pattern is a **finding aid for names to research,
  never a filter** — 2 hits in 517 postings, and one of them was a false positive.

**Bright Data quota, since it decides all of the above:** `/customer/balance` returns 403,
the key lacks the permission, so the "5k free tier" in every docstring here is inherited
belief. The one real ledger is `datasets/v3/snapshots` — **2,249 records billed 2026-08-15
→ 08-23**. Command in §1a; visibility filed as backlog item 6.

## Round 3: the breadth sweep was discovering nothing, and my own fix made it worse

The operator's point: **LinkedIn exists to find NEW UNKNOWN companies — this is the
discovery stage.** Measured against that goal, the layer was failing and my `company`-scoping
fix had made one half of it structurally incapable of succeeding:

| sweep | employers | **new companies** |
|---|---|---|
| `discovery-linkedin` (breadth) | 27 | **0** |
| `discovery-linkedin-targeted` (before my fix) | 58 | 7 |
| `discovery-linkedin-targeted` (after my fix) | 14 | 1 |

Every new company LinkedIn had ever contributed came from the *misconfigured* query. Scoping
it to `company` means it only ever asks about names already in `companies.csv`, so it can
almost never return an unknown employer. **The targeted sweep is backfill for known-broken
rows, not discovery** — it is worth keeping for what it does (roles at 15 active companies
whose own board reports 0, all confirmed as existing `active=true` rows) but it must never
be counted towards this stage, and it is the first thing to cut if budget binds.

The breadth sweep's zero had two causes, both fixed:

**Depth.** `limit_per_input` was 15. LinkedIn ranks by relevance, the head is saturated with
large employers and staffing agencies (11 of its 27 employers were agencies we discard), and
**unknown companies live in the tail** — the yield *accelerates* with depth:
1 new at 15 records, 3 at 30, 3 at 50, **15 at 100**.

**Recency.** No window, so every run re-ranked the same head. `time_range` is honoured:
`"Past week"` overlapped the unfiltered run by only 14/61 records. It also makes depth
**self-limiting** — it bills what was posted in the window (61 against a limit of 100) — and
wins on yield per record: 10 new from 61, against 15 from an unfiltered 100.

Full run with both: **391 records → 147 employers → 58 NEW companies**, against 0. Across
all sources: 74 new companies for migration, 61 queued, cache 305 jobs this run.

Both dials are env-tunable (`LINKEDIN_LIMIT`, `LINKEDIN_WINDOW`) because the quota is
unreadable. And the metric that would have caught this in the first place now prints per
source — `[yield] linkedin: 147 employers -> 58 NEW companies` — because the whole failure
was that a source could be alive, on-budget and useless with nothing saying so.

**Indeed was failing silently about two queries in five.** Found while measuring the above:
`indeed_search` collapsed an unlocker exception, a bot wall, and a genuinely empty result
into the same `[]`. `"business intelligence"` returned 0 on two consecutive runs and **15 on
the retry** — never empty, just a transient fetch failure reported as a measurement. One
retry, and it now names which of the three happened.

**Cost of this round: 391 + 62 + 176 (the depth and recency experiments) dataset records.**
Steady-state daily spend goes ~190 → ~455 records. That is a deliberate trade for 0 → 58 new
companies a day, taken on the operator's explicit "we can always exclude companies", and it
is the first number to revisit if the quota bites.

## Round 4: "isn't LinkedIn one big request a day?" — yes, and that was the bug

It is one trigger. But **the two Bright Data products bill differently**: the Web Scraper
API (the dataset) charges **1 credit per RECORD**, the Web Unlocker charges **1 credit per
REQUEST**. So a single dataset trigger returning 391 jobs cost 391 credits, while one
rendered page of LinkedIn's *public* job search carries **60 cards for 1 credit**. Depth was
being charged by the row.

Moved the breadth sweep to `linkedin.com/jobs/search` through the Unlocker
(`linkedin_search`). Measured the same day:

| | credits/day | new companies |
|---|---|---|
| dataset, limit 100 | **391** | 58 |
| Unlocker, 4 keywords, full depth | **10** | 35 |

`f_TPR=r604800` is the past-week filter and verifiably filters (past-week vs past-month
overlapped 20 of 60); pagination stops when a page yields nothing fresh, so it self-limits
at ~2–3 requests per keyword. The run now prints its own bill —
`[linkedin] 272 raw cards … for 10 Unlocker credits (27 cards/credit)`.

The parser splits into **card blocks first** and reads each field inside its own block.
Running one regex per field over the page and zipping the lists would silently shift every
pairing after a card missing a location — and a job attributed to the wrong employer is the
failure this repo guards hardest against.

What is given up is `job_summary`: the public search carries no description. Acceptable for
the breadth sweep specifically, whose product is employer NAMES; the classifier decides
clear cases on title alone and `jdfill` fills survivors later.

**Steady state, measured:** breadth 10 + targeted 67 + Indeed 6 + everything else ~44 =
**127 credits/day = 3,810/month, inside the free 5,000.** So the answer to "is it
sustainable" changed from "~$15/month" to "**free, with ~1,200 credits/month of headroom**".

Two inversions came out of it. The `linkedin-targeted` backfill is now **87% of discovery's
credit cost** — 67/day against the breadth sweep's 10 — for 1 new company, because it is the
only sweep still billed per record; moving it to the Unlocker needs LinkedIn's numeric `f_C`
company id, which we do not have. And `DEEP_BD_SEARCH_CAP` is now the largest uncontrolled
spender in the pipeline at ~450–750 SERP credits/day of effective ceiling, against a whole
discovery layer that spends 83.

Also removed the dataset breadth config rather than leaving it in place looking live — an
unused constant that reads like a setting is exactly how the Indeed dataset sat "configured"
for five days returning zero.

## Round 5: the cheap path looked worse until it was made wider

The operator caught the hole in round 4's framing: the expensive dataset found **58** new
companies and the cheap Unlocker path found **35**. The cost saving was real but I had led
with it and glossed over the gap.

The gap was reach, and the cause is a hard cap. LinkedIn's public search returns **80
distinct jobs per query and no more** — `start=50`, `75`, `100` all return zero new — so the
first four keywords hit a ceiling the per-record dataset does not. There is no depth to buy
at any price. But a keyword costs ~2 credits, so the fix is width:

| | credits | employers | new companies |
|---|---|---|---|
| dataset, per record | **391** | 147 | 58 |
| Unlocker, 4 keywords | 10 | 95 | 35 |
| Unlocker, **9 keywords** | **18** | **184** | **76** |

Keywords added on measured marginal yield, each counted on top of the ones before it:
`data scientist` +11 new, `growth analyst` +16, `marketing analyst` +7, `אנליסט` +5,
`analytics` +2. Dropped as saturated: `BI analyst` (+1 employer) and `insights analyst`
(+0). Marginal yield is order-dependent, so the list must be re-measured whole, not row by
row.

`LINKEDIN_PAGES` also went 4 → 2: two requests reach all 80, so the third was pure waste
(~9 credits/day across the list).

**And a combined boolean query is a trap** — asked directly, tested directly. The cap is per
QUERY, not per keyword:

| | credits | employers | new companies |
|---|---|---|---|
| one `("data analyst" OR "data scientist" OR …)` query | 2 | 50 | **10** |
| nine separate queries | 18 | 184 | **76** |

Each distinct query gets its own window; nine queries buy nine windows. Sixteen extra
credits for sixty-six extra companies. That is why the keyword list is long and flat rather
than clever, and it is recorded next to the Google-for-Jobs negative so nobody re-runs it.

**Final: 18 credits/day, 184 employers, 76 new companies — cheaper than the 4-keyword
version AND better than the 391-credit dataset.**

## Claims I could NOT verify

- **Whether SerpApi's `google_jobs` covers Israel at all.** `daily-digest.yml` says it was
  "verified to NOT cover Israel"; `CLAUDE.md` says the quota is exhausted. Both cannot be
  true as the reason it is off, and the key answers **HTTP 429**, so neither is testable
  before 2026-09-01. Marked UNVERIFIED with the date in `pipeline/aggregators.py` and
  `ARCHITECTURE.md` §1a; the delete-or-keep decision is `docs/BACKLOG.md` item 4. What IS
  settled: `AGGREGATOR_ENABLED` is set in no workflow, test or script, so
  `fetch_serpapi_google_jobs` has **never run in the cloud**.
- **Whether `מטריקס` (Matrix) and `עידור מחשבים` (Idor Computers) should be excluded.** Both
  are Israeli IT-services firms that also hire directly, neither has a Latin entry to
  inherit from, and this lane has no evidence either way. Named in `pipeline/recruiters.py`
  as deliberately not listed.
- `[indeed:business intelligence] 0 cards` in the dry run. Every other query returned
  10–15. Not diagnosed — could be Indeed genuinely having nothing inside `fromage=7`, or one
  unlocker response failing. Worth one look if it repeats; `sources.py` will not catch it
  because the aggregate was 55.

## Claims I deleted

- `discovery_daily.py`'s "Budget: ~40 records/day * 30 = ~1200/mo". Measured: **108 dataset
  records + 5 unlocker requests per day, ~3,240/month** against the 5k free tier. The line
  predated the targeted sweep, which is by itself two thirds of the spend.
- `pipeline/aggregators.py`'s docstring framing SerpApi google_jobs as a live daily source
  ("enough for a once-daily run with a few queries"). It has never run.
- The idea that Google for Jobs could be recovered through the Bright Data unlocker.
  Tested, 3 credits: `google.com/search?q=…&ibp=htl;jobs` returns **HTTP 200 with a
  zero-byte body** (client-rendered widget); the same URL *without* `ibp=htl;jobs` returns
  440,906 bytes, which is why `deep_validate.google_via_unlocker` works on organic links and
  a jobs-widget version cannot. Recorded so nobody re-runs the experiment.

## What I did NOT finish — all of it outside this lane, all in `docs/BACKLOG.md`

1. **A company can leave `companies.csv` and nothing says so.** `check_invariants.py` checks
   the registry's shape, never its size; `merge_csv_rows.merge()` iterates `ours` only, so a
   name in `base` and missing from `ours` is neither restored nor mentioned; the mail's run
   audit has no registry delta. Three commits have shrunk the file — `88d2b50` −13,
   `c0f7635` −3, `0180e75` −2 — all deliberate, all explained in the commit subject, none
   visible to the pipeline or to the reader of the mail. **An untracked `registry_health.py`
   appeared in the working tree mid-session**: the `registry` lane is building the detection
   half and reports 15 name-deletions across the file's history. Do not build a second one.
   The half still missing is getting the delta into the email (`infra` + `render`).
2. **The seed URL a discovery bridge can offer is always an aggregator** — a discovered
   job's `url` IS its posting. **206 of 1,233** queue entries carry one (132 secrethunter,
   45 linkedin, 26 indeed) and **45 registry rows** do. `auto_expand` guards its `scrape`
   branch but its `empty`/`unreachable` branches write the seed URL into the row unguarded.
   `secrethunter.io/jobz/<id>` cannot be followed to the real posting either: a 33,495-byte
   JS shell, byte-identical for every job id, no external link but tracking pixels. Discovery
   cannot drop the field — `auto_expand`'s `todo` filter requires it truthy, so a company
   with no `careers_url` would never drain. Fix belongs to `registry`.
3. **Per-channel Telegram liveness.** `sources.stale()` applies one 2-day threshold to every
   key and that line goes in the mail, so six channels as six keys would put a niche feed's
   quiet weekend in front of the reader. One aggregate `telegram` key is recorded and the
   per-channel counts go to the step log — which means **a single channel dying alone is
   still invisible**. `secretmarketingjobs` returned 0 new posts in the dry run. Needs a
   per-key threshold in `pipeline/sources.py`, which is shared plumbing no lane owns.
4. **`looks_like_junk` let `"Infrastructure Team"` through** into the resolver queue. Its
   team-phrase rule is anchored `^(my team|our team|the team)$`. The function lives in
   `pipeline/firmographics.py` (`company-intel`). Same family as backlog item 9 from the
   ten-agent audit.
5. ~~`linkedin-targeted` yields 4/43 on-target~~ — **superseded and fixed**, see the
   follow-up section above. It was worse than filed (0/20, not 4/43) and the fix was to
   scope by `company`, not to cut the budget. What remains open is whether the two extra
   breadth keywords replace the 17 employers/day the broken version found by accident, and
   whether `limit_per_input` should go 8 → 15.
6. **`מנורה מבטחים החזקות` and `Menora Mivtachim Group` are the same employer under two
   scripts** — the alias problem in "One identity layer", now with a Hebrew case.
