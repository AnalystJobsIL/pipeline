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

## Round 6: two adversarial waves, and most of what they found was mine

An independent proposal wave and an independent attack wave, both read-only.

**The proposal wave** returned ten ideas, six live-probed. I re-verified the three that would
change the architecture and **one did not reproduce**: it reported Indeed readable keylessly
with browser headers; from this machine that is a flat **HTTP 403**. Not implemented.
Verified and implemented instead:

- **LinkedIn's guest endpoint is keyless and `_li_cards` parses it unchanged** — 62 jobs,
  8 free requests, **0 credits**. The Unlocker stays as a fallback because GitHub's Azure
  ranges are among LinkedIn's most-blocked.
- **The employer's LinkedIn slug was being stepped over** by the subtitle regex — present on
  61 of 62 cards, already paid for, and a stable identifier. `barak-recruitment-and-consultancy`
  behind a company displaying as "Recruitx" is a free agency signal.
- **Workable's cross-tenant board** — one ATS, every tenant, keyless: 20 Israeli jobs → 7 new
  companies, **all 7 carrying the employer's own website**. The first source that yields a
  real careers lead rather than a posting link, which is the root of BACKLOG item 2. The
  queue seed now prefers it. Pagination does NOT work (`page`/`offset`/`start`/`from`/the
  `nextPageToken` all return the identical first 20; POSTing the token 404s), so it reaches
  20 of 140 and is capped at one page rather than chased.
- **City queries open partly-separate windows**, measured free: Be'er Sheva 14 of 20 jobs
  unseen nationally, Haifa 11 of 20, Jerusalem 3 of 31, Herzliya **0 of 20** (Tel Aviv metro
  is already inside the national window). Not yet wired — the peripheral cities are worth it,
  the metro ones are not.

**The attack wave found twelve defects and I had written eleven of them today.** The four
worst:

| | what it did | silent? |
|---|---|---|
| unbounded last card | the last card on a page absorbed the right-rail block — a **London** "Senior Manager" emitted as a Tel Aviv job dated today, carrying the previous card's id | yes |
| `country_code: "IL"` | stamped because the QUERY said Israel; `is_israel_job` short-circuits on it, so the only geo gate was a **no-op for the entire discovery layer** | yes |
| `plan_spend` | `left = per_day - breadth_limit × n_kw` reserved 135 credits/day for a sweep costing 18, and the remainder was `per_day mod n_kw` — 0-8 **whatever the budget**. The backfill was starved below ~31,000/month while printing "budget reserved for the breadth sweep" | yes |
| telegram cache | `_load_json(path, [])` collapsed ABSENT and CORRUPT into `[]`, then wrote that back — one half-written file deletes every cached job, and the watermark advances in the same run. The exact mechanism that cost 79 roles on 2026-08-21 | yes |

Also fixed: only ONE paid page was ever fetched when the guest endpoint was blocked (~180
jobs/day dropped in exactly the documented GitHub-runner case); an HTTP-200-empty guest reply
killed a keyword with no message and no fallback; `SOURCE_PATH` had three writes and **zero
reads** — a guard that was documented and did not exist; a partial ledger returned its
dataset-only sum as if it were the truth (2,989 instead of 4,106, so the 80% warning could
never fire); undated cards never aged off the board; the junior cut discarded the EMPLOYER as
well as the job; a decorated Telegram post shifted every field by one; `indeed_search(tries=0)`
raised `UnboundLocalError`.

**Two of my own fixes were themselves wrong and caught by re-measuring**: the drift warning
compared a per-page urn count against a deduped parse total and read 43% on a healthy page
(now distinct-urn sets, reads 100%), and treating an exhausted guest pool as a block paid the
Unlocker 2 credits per keyword to re-read a pool already drained (now 0).

**The test that should have caught the budget bug asserted `targeted < breadth`** — and
`0 < 15` is true. It passed for hours while the backfill was starved. Rewritten to assert
what must be true, not what happened to hold. That is the lesson worth keeping from this
round.

Five findings are outside this lane and are filed unfixed as BACKLOG items 9-13 — the
`fetch_discovery` slug guard dropping real acquisitions uncounted (NVIDIA/`at-mellanox`,
Meta/`at-facebook`), the workflow conflict path restoring `discovered_cache.json` wholesale,
`looks_like_junk` being unable to catch a bare job title, `run.py` lacking the cp1252 stdout
guard, and the measured 1.1% cost of the `(company,title)` dedup key.

## Round 7: the fourth wave said YES-WITH-CAVEATS, and found the biggest miss of the day

Two more independent reviews. The third returned **NO** and named three blockers — and three
of ITS blockers were in my first round of fixes: a hard-blocked guest endpoint still fetched
only one paid page (the cause moved from `if i and out` to `elif out:`, neither of which
tests `ok`, so the effect was byte-identical), `bd_spend_this_month` treated only an
EXCEPTION as unreadable, and the guest endpoint emits intermittent 200-empty pages INSIDE
the pool. Genuinely new from that wave: **Workable read `published`/`created_at` when the API
sends `created`**, so all 20 Israeli jobs entered undated — and undated means permanent on a
public board; `discovery_daily`'s own cache merge still treated corrupt as empty in the very
process that WRITES that file; and the `BRIGHTDATA_API_KEY` gate was an early return above
the KEYLESS sources and above `sources.record()`.

The fourth wave returned **YES-WITH-CAVEATS** — safe to leave on the cron, but not doing its
job — and found what I had got most wrong all day:

**The "~80 jobs per query hard cap" was measured on the PAID endpoint and then used to bound
the FREE one.** They are different: the paid `/jobs/search` page serves 60 cards and is
exhausted by 80; the keyless guest endpoint serves 10 per page and goes **200+ deep**. Bound
at `pages * 6` = 12 pages, `linkedin_search` was shipping **10 jobs out of a 201-job pool**.
Worse, the bound was tied to `LINKEDIN_PAGES` — the PAID dial every docstring invites tuning
— so `LINKEDIN_PAGES=0` would have returned `[]` for every keyword in silence.

| | employers | new companies | paid credits |
|---|---|---|---|
| bounded by the paid dial | 184 | 76 | 18 |
| own bound, 30 pages | **364** | **182** | **7** |

**2.4× the companies for under half the credits**, 113 seconds. Two keywords still stop on
the 30-page cap — and now say so, because a walk that ran out of iterations must never look
like one that ran out of jobs.

Also fixed from that wave: a page of entirely-REPEATED cards ended the keyword, and the guest
endpoint's paging is unstable enough that the same keyword returned 16 jobs on one run and
100 minutes later — a swing that reads as saturation and sends the next reader to the wrong
dial. A blank page incremented `linkedin_free`, which made the "everything is billed now"
alarm unreachable in exactly the soft-block case it was written for. `per_source` for the
targeted sweep was recorded only in the no-budget branch, not the HEALTHY one its own comment
named. `bd_spend` validated key-presence rather than value, so a JSON `null` still produced a
confident zero. The corrupt-cache abort was a `return` sitting above `sources.record()` — the
same rule, in the same file, that I had moved code to fix in the other script. And a company
found by both Indeed and Workable kept Indeed's posting URL over Workable's real careers URL.

**One of my tests was vacuous and would have passed with the bug reinstated.** It looked only
at TOP-LEVEL `ast.Return` nodes in `main()`; the only return is nested inside `if cacheable:`,
so it found none and passed through its own `or` escape asserting nothing. Rewritten to walk
every Return at any depth. That is the second time today a test passed over the bug it was
written for — the first asserted `targeted < breadth`, and `0 < 15` is true.

## Round 8: the documentation had the same disease as the code

Asked directly whether the result was elegant and navigable, the honest answer was no on both
counts, and the numbers were the argument:

| | before today | after the review waves |
|---|---|---|
| `discovery_daily.py` | 804 lines | **1,214** |
| prose : code in that file | — | **0.77 : 1** |
| `ARCHITECTURE.md` | 818 lines | **1,571** |
| §1a, for one of seven pipeline stages | — | **500 lines = 32% of the whole document** |

The brief asked for infra an agent can orient in from in two minutes. I had written a
twenty-minute read and called it thorough. Every defect the four waves found got a paragraph;
individually defensible, collectively they buried the code and the document they protect.

**Fixed: §1a is 500 → 209 lines**, and `ARCHITECTURE.md` 1,571 → 1,281. Nothing was deleted —
the cost workings, the per-endpoint billing model, the depth/recency measurements and every
rejected experiment were **moved verbatim** into the appendix of this file, which is where the
repo's own doc contract puts dated narrative. §1a keeps the sources table, the intake gates,
the three durable rules, a summary of what it costs, and pointers here. At 209 lines it is now
proportionate to its siblings (§2 is 439, §7 is 122) rather than the largest thing in the file.

The preamble was also stale in a way the linter cannot see: its diagram still said
"LinkedIn (BD dataset)" after the sweep moved to the Unlocker and then to the keyless guest
endpoint, and it said "four sources" after Workable made five. `docs/check_docs.py` proves
paths and pointers resolve, not that a sentence is true — exactly the caveat that doc lane
wrote about itself.

**And I broke the file while fixing it.** The splice wrote `new + s[b:]` instead of
`s[:a] + new + s[b:]`, silently deleting §0, §1 and the doc table — 1,283 → 1,089 lines.
`docs/check_docs.py` caught it immediately (9 errors) because those sections are referenced
elsewhere. Restored from git and redone. The linter earned its keep on its author.

Not done, and filed as `docs/BACKLOG.md` items 14 and 15: splitting the 1,214-line module
(a rename, which the brief says breaks four lanes silently, and not something to do the same
day the file absorbed four review waves), and a second pass on the comment density by someone
who was not in the incidents.

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

---

## Appendix — the cost workings, moved verbatim from `ARCHITECTURE.md` §1a

Moved 2026-08-24. §1a had grown to 500 lines — 32% of the whole architecture
document for one of seven pipeline steps — against a brief that asks an agent to
orient in two minutes. Nothing here is rewritten; it is the same text, in the place
the repo's own doc contract puts dated narrative. §1a keeps the sources table, the
gates, the three durable rules and a summary of what it costs.


#### Depth and recency are what make the breadth sweep discover anything

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


#### The Bright Data budget, and why this layer throttles itself

**One pool, 5,000 credits a month, shared by every workflow that touches Bright Data.**
Verified against Bright Data's own docs 2026-08-23
(`docs.brightdata.com/general/account/billing-and-pricing/free-tier`): "5,000 free credits
per month", renewing on the 1st, **no rollover**, with Web Unlocker API, SERP API and Web
Scraper API each costing **one credit per request or record**. It is per MONTH — the "5k"
in this repo's older docstrings is that figure, and it is not per day.

Counting only dataset records understates the bill badly. On 2026-08-23 the snapshot ledger
said **2,989 records = 60% of the month**, which looked comfortable; adding the same
account's `reqs_unblocker` and `reqs_serp` made it **4,106 = 82%**:

| product | credits, month to date | who spends them |
|---|---|---|
| Web Scraper API records | 2,989 | `discovery_daily` LinkedIn sweeps |
| Web Unlocker requests | 646 | `discovery_daily` Indeed, `enrich_scrape_jd`, `enrich_matched_jd`, `bd_rescue`, `crack_walled`, `retry_unreachable` |
| SERP requests | 471 | `deep_validate.google_via_unlocker` (the resolution ladder's search rung) |
| **total** | **4,106 / 5,000** | |

**Most of that 4,106 is experiments, so it is the wrong number to plan with.** Split the
snapshot ledger by hour — the digest runs 05:00 UTC, anything outside ~05–08 is a manual or
test trigger — and take only days with a single clean digest (08-18/19/20/22; 08-21 and
08-23 had repeated re-dispatches, 08-15 was account setup):

| | production, per day |
|---|---|
| Web Scraper records per digest | **~94** (range 30–124) |
| Web Unlocker requests | **~49** (range 46–59) |
| SERP requests | **0 until 2026-08-21**, then 199 / 272 / 116 |

**Which means the pipeline had no headroom before this lane touched it.** 94 + 49 credits a
day is 4,292 a month — **86% of the pool with zero tests and zero SERP**. Add SERP at even a
weekend-only rate and it is 93%; at the rate observed over 08-21…08-23 it is **203%**. The
account was created 2026-08-15, so this is its first month and the pool has never actually
run out — it stood at 4,106 of 5,000 on 08-23 with eight days left. When it does run out,
every Bright-Data step fails silently and `continue-on-error` keeps the workflows green:
discovery, JD enrichment, `bd_rescue`, `crack_walled`, and the search rung of the resolution
ladder all return nothing at once.

SERP is the line to watch, and it is **new**: `resolve_broken._careers_url_via_serp` gained
its `deep_validate.google_via_unlocker` fallback on 2026-08-23 (§3), which is exactly when
`reqs_serp` went from 0 to hundreds a day. `DEEP_BD_SEARCH_CAP` defaults to **150 per run**.

`discovery_daily.report_bd_spend()` prints the pool total at the end of every run and emits
a `::warning::` past 80%. Two endpoints are needed because `/customer/balance` answers **403**
for this token — widening its billing scope at `brightdata.com/cp/setting/users` would let
the code read the account's real figure instead of the documented default:

```bash
python -c "
import discovery_daily as dd
from bd_rescue import _load_secrets; _load_secrets(); dd.report_bd_spend()"
```

**`plan_spend()` pro-rates what is left over the days left in the month.** Depth is what
makes the breadth sweep discover anything, but a sweep that spends the pool by the 24th
returns **zero** for the last week of every month — and a silent zero from a source that
used to produce is the worst failure mode in this repo. So:

- The **breadth sweep is served first** (it is the discovery source); `linkedin-targeted`
  takes only what is left, and is skipped entirely when nothing is.
- Depth is never throttled below `LINKEDIN_LIMIT_MIN` (15, the value that yielded 1 new
  company) nor above `LINKEDIN_LIMIT_MAX` (100).
- **An unreadable ledger does NOT throttle** — running at the maximum is correct when the
  number could not be fetched; throttling on a value we failed to read would be its own
  silent failure.
- **Breadth is never throttled** — it is billed per REQUEST (at most `LINKEDIN_PAGES` ×
  keywords ≈ 18, usually 0 because the guest endpoint is free), so throttling it saves
  nothing and starves the discovery source. The per-RECORD targeted backfill is what absorbs
  a tight month. This was wrong until 2026-08-23: `left = per_day - breadth_limit × n_kw`
  reserved 15 × 9 = **135 credits/day for something that costs 18**, and because `breadth`
  was itself derived from `per_day`, the remainder came out as `per_day mod n_kw` — 0 to 8
  **whatever the budget**. The backfill was starved at every budget below ~31,000/month
  while printing "budget reserved for the breadth sweep", which reserved nothing. The test
  that should have caught it asserted `targeted < breadth`, and `0 < 15` is true.

Worked numbers for 2026-08-23 (4,106 spent, 9 days left → 99 credits/day):
`breadth 9 keywords × 2 pages (~18 paid worst case) + targeted cap 100`. Breadth is not
throttled at any budget — it is per-request and usually free — and the targeted backfill
stays non-zero down to ~22 credits/day.


#### Is it sustainable? Yes, and free — once you stop paying per row

**The two Bright Data products bill differently and the gap is ~39×:**

| product | billed | what that means here |
|---|---|---|
| Web Scraper API (the dataset) | **1 credit per RECORD** | one trigger returning 391 jobs costs 391 credits — depth is charged by the row |
| Web Unlocker | **1 credit per REQUEST** | one rendered page of LinkedIn's public job search carries **60 cards**, so 60 jobs cost 1 credit |

($1.50/1K records vs $1.00/1K requests, `brightdata.com/pricing/web-scraper`, 2026-08-23.)

"LinkedIn is one big request a day" is true about *requests* — the dataset breadth sweep was
a single trigger — but the meter runs on rows. So the breadth sweep reads
`linkedin.com/jobs/search` through the Unlocker instead (`linkedin_search`), and the run
prints its own bill: `[linkedin] … for 18 Unlocker credits`. `f_TPR=r604800` is the
past-week filter and it verifiably filters (past-week and past-month overlapped by 20 of 60).

**Width AND depth — but only on the free endpoint.** The two endpoints have different
ceilings and conflating them cost 60-95% of the sweep for half a day:

| endpoint | page size | pool per query |
|---|---|---|
| paid `/jobs/search` via the Unlocker | 60 cards | **~80 jobs** — `start=50/75/100` all return zero new |
| **keyless `/jobs-guest/...`** | 10 cards | **200+ jobs** — measured `analytics` 236, `אנליסט` 264, still not exhausted at 30 pages |

The "80-job hard cap" was measured on the PAID page and then used to bound the FREE walk at
`pages * 6` = 12 pages. `linkedin_search` was shipping **10 jobs out of a 201-job pool**. The
free walk now has its own bound (`LINKEDIN_GUEST_PAGES`, 30) and **says so when it stops on
the cap rather than on exhaustion** — a walk that ran out of iterations must never look like
one that ran out of jobs. Measured over the full 9-keyword sweep, before and after:

| | employers | new companies | paid credits | wall clock |
|---|---|---|---|---|
| bounded by the paid dial | 184 | 76 | 18 | — |
| own bound, 30 pages | **364** | **182** | **7** | 113s |

A page of entirely-REPEATED cards is also not the end: the guest endpoint's paging is
unstable and re-serves a window, and breaking on the first repeat made the yield
nondeterministic across runs minutes apart (16 jobs vs 100) — which reads as keyword
saturation and sends the next reader to the wrong dial. Repeats are tolerated like blanks.

**Depth is free here; a combined boolean query is still a trap.** The ~80/200 pool is per
QUERY, not per keyword:

| | credits | employers | new companies |
|---|---|---|---|
| one `("data analyst" OR "data scientist" OR …)` query | 2 | 50 | **10** |
| nine separate keyword queries | 18 | 184 | **76** |
| the per-record dataset, for comparison | **391** | 147 | 58 |

Each distinct query gets its own window; nine queries buy nine windows. So the keyword list
is long and flat on purpose, `LINKEDIN_PAGES` is 2, and **the whole sweep costs 18 credits
and beats the 391-credit dataset by 18 companies.** If yield falls, add keywords — never
pages, and never `OR`.

**Two things the parser must keep doing, both learned by being broken.** The card block is
bounded by `</li>` as well as the next urn: without it the LAST card on a page runs to the
end of the document and absorbs the right-rail "people also viewed" block, which is built
from the same `base-search-card` component and carries no urn — a last card missing its own
subtitle emitted a **London** "Senior Manager" as a Tel Aviv job. And `country_code` is left
**blank**, never `"IL"`: `israel.is_israel_job` short-circuits on country_code before it
reads any text, so stamping IL because the QUERY said Israel made the pipeline's only geo
gate a no-op for the whole discovery layer.

What is given up is `job_summary` — the public search carries no description. That is
acceptable *for the breadth sweep specifically*, because its product is EMPLOYER NAMES and
the classifier decides the clear cases on title alone; a role that survives gets its text
from `pipeline/jdfill.py` later.

**The steady-state bill, measured:**

| | credits/day |
|---|---|
| LinkedIn breadth — **keyless guest endpoint**, 9 keywords × 30 pages | **~7** (≤18 if LinkedIn blocks it entirely) |
| Workable — keyless, all tenants | **0** |
| LinkedIn targeted — dataset, per record | **67** |
| Indeed — Unlocker, 5 keywords + retries | 6 |
| everything else (JD enrichment, rescue, crack, repair) | ~44 |
| **total before SERP** | **80** → 2,400/month, **comfortably inside the free 5,000** |

So it is sustainable at **$0**, with roughly 1,200 credits/month of headroom — which SERP
can still eat: at the weekend-only rate the month lands at 4,320 and fits; at the rate
observed 08-21…08-23 it lands at 9,690 and does not.

**Two things follow, and both are the opposite of where this started.** The `linkedin-targeted`
backfill is now **87% of discovery's entire credit cost** — 67 credits/day against the whole
breadth sweep's 10 — for 1 new company, because it is the only sweep still billed per record.
Moving it to the Unlocker needs LinkedIn's numeric `f_C` company id, which we do not have; it
is the obvious next optimisation and the first thing to cut regardless.

**And `DEEP_BD_SEARCH_CAP` is now the largest uncontrolled spender in the pipeline** — the
one that decides whether the month fits. It reads like a daily ceiling of 150 and is not
one: `deep_validate._BD` is a **module-level** counter, so the count resets in every
process, and six scripts import `google_via_unlocker` in processes of their own —
`resolve_broken` (06:00), `listing_hunt` (19:00), `crack_walled` (19:00 + weekly),
`repair_dead_urls`, `deep_validate` (Sat), `audit_empty_rows` (Sun). The effective ceiling
is **~450 SERP credits on a weekday and ~750 at the weekend**, against a discovery layer
that now spends 83 a day in total. Observed peak 272, i.e. two processes' worth. Guarded by
`test_the_shared_bd_search_cap_is_per_process_not_per_day`, and it is `docs/BACKLOG.md`
item 6.


#### Dry-running tomorrow's intake, end to end

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


#### The five live sources, and what each one costs

`cloud` is the 05:00 run of 2026-08-23 read out of `cloud_state/source_health.json`;
`dry-run` is a full local execution of both scripts against sandbox copies of the state
files the same evening (17:30 UTC), which is the check to repeat before trusting a change
here — it exercises the real Bright Data account and the real Telegram fetches.

| source | mechanism | cost per digest | measured 2026-08-23 |
|---|---|---|---|
| `linkedin` | **the discovery source.** `linkedin.com/jobs/search`, 9 keywords, unscoped, `f_TPR` past week. KEYLESS guest endpoint first, Web Unlocker only where blocked | **0 credits** when the guest endpoint answers; ≤`LINKEDIN_PAGES × 9` = 18 when it does not | 47–62 jobs/keyword-sweep, 100% parsed, **0 paid** |
| `workable` | `jobs.workable.com/api/v1/jobs?location=Israel` — one ATS, EVERY tenant, keyless. The only source that returns the employer's own website | **0 credits** | 20 rows → 11 kept, 11/11 with a real careers lead |
| `indeed` | `il.indeed.com/jobs` through the **Web Unlocker**, one request per `INDEED_QUERIES` entry; parsed from the `mosaic-provider-jobcards` blob | 5–10 unlocker requests (one retry) | 58 raw → 46 kept |
| `linkedin-targeted` | BD dataset `gd_lpfll7v5hcqtkxl6l`, one input per broken-board company, **scoped with the `company` field**. Backfill, NOT discovery | ~67 dataset records | 88 companies → 67 records, 57 on-target |
| `telegram` | public `t.me/s/<channel>` HTML previews — **no bot, no account, no API key, no quota** | free | 6 channels, 16–18 of 20 parsed each |

Re-derive with
`python -c "import json;print(json.load(open('cloud_state/source_health.json')))"`.

**Three of the five need no key at all.** `main()` therefore does NOT return early when
`BRIGHTDATA_API_KEY` is missing — that gate used to sit above Workable, the LinkedIn guest
endpoint *and* `sources.record()`, so a rotated secret took the whole intake layer dark,
including the free half, and silenced the mechanism built to notice.

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


#### Telegram channels

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
