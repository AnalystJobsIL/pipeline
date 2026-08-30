# registry — 2026-08-30 (c): capacity is the item, not the backlog

Against `origin/master` `c1fda51`, in a clean worktree; nothing below was measured from the
shared checkout (207 commits stale). Every number the brief gave was re-derived first.

## The brief's numbers, re-derived

| brief said | measured on `c1fda51` | how |
|---|---|---|
| 401 in the queue · 61 never tried · 393 owed | **572 · 175 · 557** (`queue_state.py`); `--census`: **384 owed + 188 queue names already carrying a retirement** | two digest runs (`ce61e13` +191, `8eb1340` +171) landed after the brief |
| intake 98.5 median / 177 mean | **brand-new names/day, 7d: 258 · 53 · 75 · 109 · 652 · 161 · 173 → median 161, mean 212**; gross adds ~2× that, because intake re-adds retired names | name-set diff of every commit of `research_companies.json` against the file's whole history (2,729 names ever) |
| the cloud arm does 120/night | the OLD queue arm did `queue arm: 60 intake names (cap 60)` on 08-28/29 and is OFF; the NEW drain (4 × `--cap 30`) has run once in the cloud and selected **1 name** (run 33276177460) — its throughput was unmeasured, its cap 120, and the shard's own budget now makes it **112** | run log, `queue_resolve_search.nightly_capacity()` |
| 61 never tried — "a new class" | 175 never tried, **173 are that day's brand-new intake** (2 are retired names intake put back) (arrived 10:06Z and 10:54Z; the only rung that touches a queue NAME is the 19:00 drain). The class is "arrived since the last drain" and exists every day between 05:00 and 19:00 | `queue_state.json` keys vs the queue |
| 37 rows with a location query | **60** (`cloud_state/query_filter.json`; 34 of them spell it `location=`) | `audit_query_urls.has_location_query` |
| Hila & Co., Peak Innovation have no row | **wrong** — Peak Innovation is ACTIVE (`verified 45 IL`), Hila & Co. is PARKED (`wrong-url … needs re-resolution`); the missing intel is `firmographics.json`'s | `companies.csv` |

**Steady state, two numbers: the drain does 112 a night; brand-new intake is 161/day at the
median (212 mean).** It cannot hold. The queue refilled 210 → 572 in one day while a session
was draining it, which is the proof that draining by hand is not the job. What this lane
could fix, it fixed (below); the shard count, cap and timeouts are `listing-hunt.yml`'s
(`491@infra`, four diffs with the arithmetic), and the retired names intake puts back every
morning are `discovery`'s (`441`, whose "intake re-added zero" was measured this morning
over a window in which retirements were hours old — 189 of today's 362 adds carried one).

## Four defects in the drain, all in this lane's files

1. **`targets()` never read the disposition ledger.** Intake re-adds a retired name every
   morning and `--retire-settled` runs three steps AFTER the drain, so on **2026-09-12** —
   the night their 14-day `search-llm` cadence lapsed — 174 names with a RETIRABLE verdict
   (84 `no-board`, 64 `duplicate-of`, 15 `not-an-employer`, 15 `already-a-row`, 9
   `covered-by-row`, 2 `acquired-by`) would each have bought a paid search to re-learn an answer already on
   disk. The ledger's vocabulary (`RETIRABLE`, `REOPEN_DAYS`, `is_reopened`,
   `disposition_verdict`) moved into `queue_disposition.py` so the drain reads the ledger's
   module and not the 1,300-line orchestrator; `queue_pipeline` re-exports every name.
   `cannot-tell`, `overturned-*` and an expired `no-board` stay owed, and the census now
   counts "retired with evidence" by the same call. Two more holes the first draft had,
   both found by the adversarial pass: the cleanup's own `covered-by-row` /
   `already-a-row` verdicts were not retirements to the drain (`Faye`, `Strauss Group` and
   seven more were selectable while the census counted them retired — `is_retired` covers
   both), and the lookup was case-sensitive (`NATASHA DENONA IL` re-added as `Natasha
   Denona Il` escaped it — `record_for` folds case).
2. **File order is oldest-first**, so the day's 173 new names waited behind every older
   residue (the docstring said "newest rung first"; there was no sort). Never-searched
   first, then the oldest search, stable, before the shard stride — and one slot in five
   reserved for the stalest re-try, because with intake above capacity "new first" alone
   freezes every refused name at its first refusal (`select`).
3. **A slow shard erased every shard's night.** `queue_state.py --ingest` sits after `wait`
   inside the 30-minute drain step; GitHub kills the process group, the ingest never runs,
   the same 120 names are selected and re-bought tomorrow, every refusal is lost, the IDLE
   alarm fires naming three causes that are not this one, and every step is green. The
   shard now budgets itself (`QRS_TIME_BUDGET_MIN` 26, `QRS_SEC_PER_NAME` 55 → selects 28,
   stops between names on the clock, prints `budget hit (26 min), N names not
   searched/scored`). A name never reached is written nowhere; a name whose search was
   PAID and whose page went unread is recorded as a `budget hit` refusal — an adversarial
   pass showed the first draft dropped those and they would have been re-bought tomorrow.
   The step order that makes a kill harmless is `491@infra` item 1.
4. **`search_one` returned a 4-tuple on its error path** where every other exit is a dict:
   `TypeError` in `main`, the shard dead, the malformed entry already persisted into the
   search cache so a re-run died on the same name. Dict now; a malformed cache entry is
   re-searched. And `queue_state.load()` answered `{}` to a corrupt file — one truncated
   log plus one `--ingest` would have persisted ~120 names over 6,589 attempts. A corrupt
   log is a hard stop; an absent one is still `{}`.

The stamp carries `new_intake` and `retired_in_queue` beside `selectable`, so `queue GREW`
can be read as arrivals or as resurrection; `DRAIN_NIGHTLY_CAP` is derived from the drain's
constants and `test_the_drain_capacity_constants_match_the_workflow` pins them to the YAML.

## Comcast, and the class it belongs to

`jobs.comcast.com/search-jobs?location=Israel` returned 14 US postings; `scrape_universal.
_page_is_il` stamped `location='Israel'` on every one because the URL said so; the hunt
counted the stamps as `verified 14 IL`; two Houston/Pennsylvania roles reached the mail, the
board and the public CSV. Traced on the real predicates: a parked query-URL row is
**re-activated by the next 19:00 hunt** — `in_hunt_pool` True, the same query URL tried
first, `_page_is_il` True, `il >= 1`, `is_foreign` False on the company's own host,
`identity_ok` True — and `probe_candidates` counts the page's echo of our own filter chip as
Israel signal, wakes it, and `probe-woken` promotes it to the weakest gate in the file. So a
park alone was a 24-hour delay.

`audit_query_urls.py` is the instrument. Evidence is **card-level and independent of the
query** — the card's own url path, title tail, `country_code` (a description is never
evidence alone: ASML's cards say "China, Connecticut" in boilerplate on a filter it
honours); `ignored` needs ≥ max(3, 10% of the cards) foreign and 0 Israeli, `leaks` a
foreign majority; rows the cache cannot judge get one RENDERED read whose (title, location)
pairs must literally occur in the page text with the page's echo of our own query struck
out first (the model extracts, the code counts). The park holds because `audit_query_urls.
il_jobs` is the one test over scraped cards on all seven activation paths (`listing_hunt`,
the drain's `_score`, `crack_walled`, `repair_extract_gap`, `resolve_deep`,
`retry_unreachable` — the first draft guarded two, and the adversarial pass showed the drain
re-admitting the class through its own door) and `probe_candidates.il_signal` strikes the
echoed query value before counting.

**Result over the 60 rows:** parked **20** — 17 `ignored` (Comcast 8/14 cards
US, AT&T 3/3 Phoenix, Zoom 29/30 San Jose, Rapid7 16/16, adidas 11/19, ASML 17/25, Lenovo
10/10, Fujitsu 10/10 Portugal, IQVIA, Siemens, Electronic Arts, Shopify, Microsoft ×2, Skoda,
Teradyne, Hunter Douglas) and 3 `leaks` (Snap: 1 Israeli card of 175; Align: 1 of 88;
Rapyd: 11 of 25 — a page that dumps its board is Comcast with a fig leaf, and the
scraper's stamp publishes the foreign majority as Israeli, so the few real roles are the
lesser loss until `462@scraper` reads a card's own place); honoured **21**
(Google Israel: 20 of 20 rendered postings in Tel Aviv or Haifa — the plain fetch's visible
text names no posting at all, which is why the read escalates to a render when it sees none; Apple, Meta, Amazon, PepsiCo, Stratasys, Texas Instruments …); unverifiable
**19** (re-read in 3 days; never parked). Active rows 1,099 → 1,079.
The cache alone found 7 of the 20; the grounded reads found the other 13 — Zoom's and
Rapid7's cached cards carried no city at all. Ledger `cloud_state/query_filter.json`. Comcast's cell could not take
the pool token — 215 chars of a 220 cap, every segment PROTECTED, one a `url-dead` tombstone
on a live address (`493@registry`) — so its park stands on the pool tokens it already carried.

**For `roles`:** the two Comcast records in the store/board/CSV (`Analyst, Enterprise Data
Analytics - Comcast Advertising`, Pennsylvania; `Manager 2, Business Operations & Analytics`,
Houston) are US roles published as Israeli. Their purge path keys on aggregator rows; this is
a new reason (`query-filter ignored`) and the keys are in `cloud_state/query_filter.json`
under `Comcast`. Not renamed, not purged from here.

## The CANNOT-FAIL test

`test_the_judge_never_re_judges_a_name_a_human_overruled` passes at the guard-kill base
`bfdff0f` **correctly**: there `dispose`'s filter was the stricter `n not in state`; `6c16026`
opened the hole (`raw_verdict not in RETIRABLE`) and `861050d` closed it, both inside
`bfdff0f..d01213f`. It pins behaviour the base had by accident. It is CATALOGUED now:
`dispose-rejudges-overruled` in `tests/mutations.json` (the `and not is_reopened(n, state)]`
conjunct removed), `Kills` on the docstring, proved by `tools/mutate.py`. Three more records
for this session's own gates: `hunt-query-url-stamped-il`, `query-audit-park-on-description`,
`drain-targets-ignore-disposition`.

## Decisions and triage

* **F2's 109** — decision: yes, the message must stop firing; the fix is `282@infra`'s one
  line (import `triage_dark.MODES`), recorded as `492`. Not patched (not my file).
* **441** amended with the evening measurement (intake re-added 189 retired names in two
  runs; the merge rescued 17 of 74). **458** stays infra's. **459**: no rename. **460**:
  corrected (Peak Innovation active, Hila & Co. parked). **461/462@registry**: open, one
  line each in the index; **462@scraper** amended with the 60-row measurement and the
  exact root fix. **493**: the protected-tombstone class.
* Morning checks: the two 08-30 rows were answered by the morning session; the 08-31 queue
  row is `N/A - superseded` (the queue it predicted `<= 210` for was 572 by noon) and re-aimed
  at tonight's run; `deep rung` row re-dated legally (`until 2026-09-07`); new rows for
  09-13 (the cadence-lapse night: 0 retired names bought) and 09-02 (the parks held).

## Spend

Bright Data: 0 credits (no `bd_spend.jsonl` entry after the morning's cron; every render was
local Playwright). `claude -p`: about 80 calls (opus: 48 rows read, 26 of them twice because
the plain fetch showed no posting, plus 5 re-reads under the `leaks` rule). 0 for anything queue-related — every
queue change is a lookup over records already on disk.

## What I did NOT do, and what is NOT verified

* **The drain has still never selected a name at scale in the cloud.** Tonight's 19:00 run is
  the first on this code; the 08-31 HANDOFF row names the lines it must print.
* **Capacity is not raised** — that is the workflow, `491@infra`. 112 < 161 stands.
* **The 40 no-signal rows are only as judged as one read each** — 19
  stayed unverifiable; `audit_query_urls.py` is `operator` until infra schedules it.
* `discovery`'s intake still re-adds retired names; the registry side is now a lookup
  either way.
* **Wave 2 (confirmation) took the first eight fixes apart and found five more, all taken:**
  the cleanup's PRUNE path still looked the ledger up by exact key (classified `Natasha
  Denona Il` every night, never pruned it — `record_for` there too); `--stamp` died in
  `census` before the new UNREADABLE alarm could print (caught in `main`, stamped instead);
  the title-tail rule captured `VA` and not `Reston, VA` (a comma opens the tail and no longer
  ends it, plus a US state-code pattern); `has_location_query` matched `locale=` / `lang=` /
  `block=` and `il_jobs` fails CLOSED, so a benign query could refuse a genuine board (a
  not-a-filter list); the disposition ledger failed OPEN on a corrupt file while the drain
  now depends on it (a hard stop, like the attempt log). Hunter Douglas had been parked under
  the first draft's absolute floor (4 of 116); under the shipped 10% floor its grounded read
  decided instead: 136 postings, 123 abroad, 0 Israeli — the park stands on that evidence.
* **Wave findings not taken**, deliberately: the digest still publishes the scraper's
  stamped cards on `honoured` rows (right, since the filter works) and on the 19
  unverifiable ones (unknown) — the publication-side fix is the scraper's (`462@scraper`);
  a query-URL row whose postings print only "Israel" with no city can no longer wake through
  the probe (a coverage cost, accepted and written into §2).
* **CI on the landed commit `56901b8`: run 33312937940, conclusion `failure`** — `guard`,
  `guard-kill`, `mutation-gate (1)`, `mutation-gate (2)` and all five `rehearse (mixed)`
  green; `rehearse (worst, seed 1)` red exactly as on the two runs before mine (33312345558,
  33305567382 — `rehearsal FAILED: 14 night(s), policy worst`, inherited); and
  **`mutation-gate (0)` timed out at its 40-minute budget** — that shard is class M1 alone
  (86 records, 25 min on 2026-08-30 morning) and this session added three M1 records whose
  import-graph subset is 936 tests (~6 min each locally; the shard printed the baseline and
  no per-record line). The workflow's own error says `add a shard (SHARDS) rather than
  minutes`; `tests.yml` is infra's, so that is `491` item 5. Until it lands every push is red
  on that shard. The records themselves are proven killed by this lane's own tests in a
  mutated `git archive` copy (rc=1 mutated / rc=0 unmutated, all four), and `guard_kill
  --base c1fda51` reports KILLS 16, CANNOT-FAIL 0. Full suite on the pushed tree: 1,526
  passed, 12 skipped, 0 failed.
