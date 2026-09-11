# 2026-09-11 — Bright Data: unlimited, optimise once, then let it drive itself

**Lane `infra`. Supersedes the NUMBER in `docs/decisions/2026-08-28-bd-ceiling.md`, not its
mechanism** — the ceiling still lives in exactly one place (`pipeline/bd_budget.ceiling()`),
still has a date on it, and every side of every boundary is still pinned by a guard.

**The operator's ruling, 2026-09-11:** *"unlimited budget for now; optimize once, then let it
drive itself."*

## 1. Why the ceiling had to go, and it is not the reason anyone assumed

On 2026-09-11, the 11th day of the month, the live account read
`Bright Data: 5,804 of 5,000 credits (116%) — CEILING REACHED`. Thirteen tools kept buying
anyway: only `pipeline/jdfill.py` (`_monthly_ceiling_reached`) and `enrich_scrape_jd.py`
consult `bd_budget.verdict()`. So the one consumer the ceiling stopped was the
**dataset-critical** one — the digest's JD fill. That morning's mail:

```
inline jd-fill: the paid rung is configured and UNUSABLE (monthly-ceiling) with 49 postings
the free rungs could not read — those roles are judged on the title alone
classify 10 superseded verdicts CANNOT be re-judged
```

A ceiling that binds one spender of fourteen is not a budget. It is a filter that removes
whichever consumer was best-behaved about asking permission.

**And the money was never the problem.** 5,000/month is Bright Data's FREE TIER (Unlocker +
SERP + Web Scraper share it, 1 credit per request or record, resets on the 1st, no rollover).
Beyond it, pay-as-you-go is **$1.50 per 1,000**. September at the 09-01..09-11 rate projects
~15,400 credits — about **$15**. The ruling prices that correctly: the free tier stays as a
SOFT line that alarms in the mail, and nothing refuses a call on it.

## 2. What the credits actually buy — measured, not assumed

`cloud_state/bd_spend.jsonl`, 2026-09-01..09-11, 5,375 credits, by tool:

| tool | credits | share | what it is |
|---|---|---|---|
| `listing_hunt.py` | 1,741 | 32 % | Google search + the pages it finds, over a 617-row parked pool |
| `bd_rescue.py` | 1,032 | 19 % | page unlocks for the 02:30 unreachable chain (17 rows) |
| `crack_walled.py` | 847 | 16 % | walled-ATS re-cracks, 74 rows, **daily** |
| `queue_resolve_search.py` | 658 | 12 % | the intake queue's paid search |
| `resolve_broken.py` | 463 | 9 % | the 06:00 self-heal's search |
| `discovery_daily.py` | 231 | 4 % | LinkedIn paid pages + Indeed renders + the dataset |
| `audit_empty_rows.py` | 155 | 3 % | the Sunday audit |
| the other six | 248 | 5 % | `queue_pipeline`, `repair_*`, `triage_dark`, `deep_validate`, `auto_expand` |

By PURPOSE: Google search through the unlocker (`deep_validate.google_via_unlocker`, called
by twelve tools) **4,105 = 76 %**; page unlocks **1,032 = 19 %**; discovery **231 = 4 %**.

Two ledgers disagree and both are right. The ACCOUNT read 5,804 on 09-11 and splits it
`unlocker_reqs=3378, serp_reqs=2308, dataset_records=118`; the repo's ledger read 5,375 and
attributes 76 % to "search" TOOLS. The account is counting PRODUCTS and the ledger counts
CALLERS — a search tool spends one SERP credit and then unlocks the candidate pages it found,
so its credits land in both columns. The gap of ~429 is the 118 dataset records plus every
spender that does not go through `bd_rescue` (chiefly `jdfill.Unlocker`), which §4 closes.

**No job waits on any of it.** Every active company's board read — 1,363 rows each morning —
and the LinkedIn guest endpoint are FREE rungs and are untouched by everything below. The
operator's question was "will I wait 14 days to hear about a job": **no.** The cadences in
§3 apply only to PARKED rows, which by definition have no readable board today; a parked
row's re-check is how it becomes active again, and the pool it sits in is re-walked in full
every fortnight instead of every three nights.

## 3. The waste, and the one predicate that removes it

### 3a. The cadence existed and the notes column ate it

`listing_hunt.stale_hunt` has said "re-hunt after 14 days" since 2026-08-21. Measured on
2026-09-11: of the 93 rows the hunt would take tonight, **80 carry no `listing-hunt` stamp at
all** — and 62 of those 80 have notes 160-220 characters long. The stamp was not missing; it
was **evicted**. `pipeline/notes.py` drops the oldest unprotected segment to fit the 220-char
cap, twelve tools write into that cell, and the hunt's own dated segment is unprotected. A
row whose stamp was evicted reads as *never hunted* and sorts FIRST.

The consequence is the number: the 617-row pool was re-walked every **3-4 nights**
(178 rows on 09-10, 272 on 09-09, 252 on 09-08) instead of every 14.

`crack_walled` had no such accident: `_recrackable(note, days=1)` is **daily by design** — 22
of its 74 rows due today, 8 at a fortnight, 55-81 credits a night for 2-3 `cracked-api`.

`bd_rescue` had no dated token for its commonest outcome at all: `validated` (a page was
read, no board on it) writes `scanned via brightdata`, which carries no date, so `_skip`'s
7-day `bd-tried` cooldown never applied. 15 of the 17 rows in the pool are in exactly that
state, which is why four consecutive nights read `rescued 0 · validated 16-18` at 80-95
credits each.

### 3b. The fix: store the attempt where eviction cannot reach it

`cloud_state/queue_state.json` already is an append-log of dated attempts per NAME per RUNG,
with one cadence predicate (`queue_state.tried_within`). It was built for intake names; a
parked ROW needs exactly the same record. So the three paid row tools record their attempts
there, under rungs `bd-rescue`, `listing-hunt` and `crack-walled`, and select on one new
wrapper:

> **A parked row is re-bought by a paid tool only if `queue_state.json` holds no attempt by
> that tool inside 14 days, or the row's ADDRESS changed since that attempt, or a dated wake
> or triage mode newer than the attempt says its evidence changed. A row with no attempt is
> bought the first night it appears.**

`queue_state.row_due(state, name, rung, days=14, url=...)` is that sentence, and it is a
composition of `tried_within` rather than a second cadence — this repo has one predicate per
question on purpose.

**No pool predicate changed.** `in_hunt_pool`, `in_crack_pool` and `in_retry_pool` are
untouched, so `registry_health.pools()` and the 14-night rehearsal see the same membership;
what changed is only how often a member is PAID for. The note stamps stay, because
`registry_health --explain` and every human reader use them — they are simply no longer the
schedule.

**The alternative, rejected on a number:** protect the `listing-hunt` segment in
`pipeline/notes.py` the way `dark-triage` and `unsupported ATS` are protected. 62 of the 80
affected rows carry notes of 160-220 characters, i.e. they are at or near the cap already, so
one more protected segment means `notes.append` starts DROPPING THE NEWCOMER — the newest
verdict, from whichever tool ran last. The notes column is a 220-character budget shared by
twelve writers; a schedule does not belong in it, which is the general form of the lesson.

### 3c. What each tool loses

Nothing that was not a repeat.

| tool | before | after | what is lost |
|---|---|---|---|
| `bd_rescue` (02:30) | 83/day, the same 16 rows re-validated nightly, 0 rescued in 4 nights | ~6/day | a row is re-read on day 14 instead of every day. A row whose ADDRESS changed is re-read that night |
| `listing_hunt` (19:00) | 137/day, pool re-walked every 3-4 nights | ~35/day | nothing: the pool is walked in FULL every 14 nights, which is what the code always said it did |
| `crack_walled` (19:00 + Sun) | 71/day over 22 due rows | ~6/day | a documented ATS host is re-cracked fortnightly. Its yield was 2-3 `cracked-api` a night out of 74 |

`queue_resolve_search` is **not** touched, and the measurement is why: of the 84 names it
searched on 2026-09-10, every one had exactly ONE `search-llm` attempt ever (690 of the 755
queue names do). Its 14-day cadence already works, because a NAME has no notes column to
evict. Cutting it would cut first-time research, which is the opposite of the goal.

### 3d. The projection, honestly

Cadence alone takes the daily rate from **468** (7-day mean, 09-05..09-11) to about **225**,
i.e. ~6,700/month steady, and September lands near **9,650** (~$7 PAYG). The spawn brief
hoped for 3,000-4,000/month; that is not reachable by cadence, because after it the remaining
80 % is the search rung itself, which is §5's lever and not a schedule problem.

## 4. The gauge — what "let it drive itself" means

A run page nobody opens is not an alarm. The operator reads the mail daily, so the mail
carries the meter:

* **`bd:` on `Stage order:`** — month-to-date from the LIVE account, the 7-day rate per
  purpose (search / unlock / discovery / jd-fill) from the ledger, and the month's
  projection.
* **a `Stages:` clause** when the projection crosses `SOFT` (5,000), naming the rate per
  purpose and the PAYG dollars. It alarms; it stops nothing.

For that to be true the ledger had to learn two things it did not know: **which purpose** a
credit served (`bd_rescue.book(purpose)`, defaulting to `unlock` so every existing caller is
unchanged), and **that the digest's JD fill spends at all** — `jdfill.Unlocker` POSTs to
Bright Data itself and had never written a ledger line, which is a large part of why the
account (5,804) and the ledger (5,375) disagree.

## 5. The search rung — small and measured, not a vendor migration

76 % of the spend is one function. Every alternative was researched against the $1.50/1,000
PAYG price and **rejected on the number**: Serper ($1.00/1K, saves ~$1/month, $50 up front),
Brave ($5/1K beyond a $5 monthly credit), SerpApi (250/month free, $15-25/1K), Google Custom
Search (closed to new customers, dies 2027-01-01), Gemini grounding (free but not a raw SERP,
`site:` survival unverified), Anthropic `web_search` ($10/1K, 6.7× the status quo), Apify /
Firecrawl / Crawlbase / ScrapingBee / Scrapfly / ScraperAPI / Browserless (all cost more per
month than paying Bright Data for the same volume, except as ceiling relief — and there is no
ceiling any more), and the operator's NordVPN subscription (against NordVPN's own terms,
detected, and it would attach the personal account to the pipeline — see `CLAUDE.local.md`).

What ships instead:

1. **A free keyless rung ahead of the paid one**, measured before it is trusted. DuckDuckGo's
   HTML endpoint already exists in the tree (`deep_validate.ddg`) and is already first in
   seven tools; it is hardened (a 202 is a soft block, never retried in the same run; ≥ 2 s
   pacing) and added to the three tools that had no free rung at all. It is kept only if it
   AGREES with the unlocker on ≥ 70 % of the names it answers, measured by a free A/B that
   prints `[search-ab]` on the 19:00 run. If it does not, the next session deletes it and
   says so.
2. **LinkedIn stays free**: the guest endpoint is already first; it gets 2.5 s spacing and one
   paced re-ask so a 429 never escalates into the paid render. The dataset trigger
   (`datasets/v3/trigger`, **1 credit per RECORD** — 391 measured once) goes behind an explicit
   flag: it ran unattended on eight mornings this month for 118 records and **one** new
   company, and it re-arms itself every 1st because its own budget reads the account.
3. **Indeed stays on the unlocker** (~750 credits/month, 15 % of the free tier): the Publisher
   API shut in 2023, the XML feed in 2024, and both RSS hosts return 404 today. There is no
   legitimate feed to move to.
4. **Not built, filed instead:** a Haiku 4.5 result-picker. It cannot fetch; it would replace
   "fetch four candidates" with "fetch one", saving up to 3 page credits per resolution at
   ~$0.003 of tokens — worth doing when the page credits, not the SERP credits, are the cost.

## 6. The reserve mechanism: built, and OFF

Per-purpose monthly allowances (`bd_budget.may_spend(consumer_class)`, the digest's JD rungs
privileged so they may borrow every other class's remainder) exist behind `BD_ALLOWANCES=1`
and are **off**. The reason to build them now and not later is that the seam is the hard part
and it is only obvious while all fourteen spenders are in view; the reason not to arm them is
that this month has no ceiling to enforce. What would turn them on: a second consecutive
month projecting past `SOFT` with the operator unwilling to pay it.

## 7. Cost of this decision

Credits spent producing it: **zero**. Every number is from committed state
(`cloud_state/bd_spend.jsonl`, `companies.csv`, `cloud_state/persist_log.jsonl`), from
`gh run view --log`, or from the account's own metadata endpoints, which bill nothing.
