# 2026-09-12 — the LinkedIn walk keeps its pacing and gains a clock

*lane: `infra`. Supersedes nothing; it bounds what `47b9d07` (2026-09-11) added.*

## What happened

The 2026-09-12 digest's `discovery` step was killed at `timeout-minutes: 25` and printed
**one line** — the timeout error. Two things had to be untangled before anything could be
fixed, and the second one reverses the obvious conclusion.

**The data was not lost. The evidence was.** That run's own commit (`71aff56`) carries
`discovered_cache.json` **+5,398/−1,021** and `cloud_state/source_health.json`
`linkedin: {last_run: "2026-09-12", last_count: 4888}`. `sources.record` is the last call in
`main()`, so `main()` completed. What died was all 52 `print` lines, in python's stdio buffer
— and the day before proves the mechanism, because every discovery line in the 2026-09-11 log
carries the single timestamp `09:31:33`: one flush, at exit.

**And the process outlived its own cancellation.** The step ended at `09:34:06`;
`discovery_daily.py`'s `atexit` Bright Data ledger line is stamped `09:37:46`. `timeout-minutes`
does not kill a process — it abandons it. In those 3 m 40 s it wrote `research_companies.json`,
while the *telegram* step (started `09:34:06`) wrote the same file at `09:34:10`. Two writers on
the intake queue, in two workflow steps, which is a failure class that cannot exist until a step
overruns. Both are `ARCHITECTURE.md` §8 items 8 and 8b now.

## The decision that could have gone the wrong way

The pacing added on 2026-09-11 — 2.5 s between guest pages, 20 s before one re-ask of a hard
block — is what made the step overrun. The obvious move is to delete it, and the brief that
commissioned this work said to delete it unless it measurably prevents the 429.

It does. Two committed measurements, neither of them in the lost log:

| night | pacing | `source_health` linkedin urns | `bd_spend` `discovery_daily.py` credits |
|---|---|---|---|
| 2026-08-28 … 09-11 (16 nights) | off | 1,400 – 3,016 | 17 – 23, **every night** |
| **2026-09-12** | **on** | **4,888** | **6** |

Indeed buys 5 of those credits nightly (5 queries × 1 unlock), so **LinkedIn's paid pages fell
from ~12–18 to ~1**, and the distinct postings the *free* rung reached rose 62 % on the best
previous night. Day of week does not explain it: the previous Saturday, 09-05, unpaced, cost 21
credits for 1,999 urns. The mechanism is in the walk's own code — an unpaced walk earns 200-empty
soft-limit pages, breaks on `blanks >= LINKEDIN_BLANK_TOLERANCE`, and then **buys** a page to
tell an empty keyword from a rate limit. The free rung was buying the paid one twice over.

**The reading that says otherwise, and why it loses.** Over the five *unpaced* nights the
blocked COUNT is a flat 34–36 (35/365, 34/276, 36/250, 34/316, 34/334 = 9.6–14.4 %) across a
1.46× swing in request volume, which looks exactly like a quantity set by the query count rather
than the request rate — i.e. like something a 2.5-second gap cannot move. That is a sound
reading of those five nights and the sixth refutes it. It is recorded here because it is the
conclusion a future session will reach from the same five rows.

## What shipped instead

A page cap cannot bound a walk whose per-page cost is a sleep. The arithmetic, on 09-11's own
counters (`free=302 blank=28 blocked=35` = 365 guest requests over 27 queries):

* 338 charged pauses × 2.5 s = **845 s**
* 18–27 block re-asks × 20 s = **360–540 s**
* on a 252 s sweep = **24.3–27.4 min against a 25-minute step**

So the overrun was arithmetic, not weather, and the bound is a clock:

**`LINKEDIN_TIME_BUDGET_MIN` = 18**, read in `main()` and anchored at `main()` **entry**.

* Read in `main()`, never at module scope: `auto_expand.py:103` records a module-scope budget
  defeating the two guards written to prove the run deadline worked.
* Anchored at entry, so Indeed and Workable **compose** with it rather than adding to it — a
  pathological head starves the walk instead of extending the run, which is the safe direction.
* Past the deadline a query makes **no guest request at all** and goes straight to the paid
  render (national, 2 pages, the 18-credit worst case `plan_spend` already advertises). A query
  **already walking** stops and **buys nothing**: its pool is in `out`, and there is
  deliberately no `elif out: break` in the loop, so falling through would spend `pages`
  renders re-reading what the free rung had just read. A clock must never convert a productive
  free walk into spend.
* No pause of any kind runs past the deadline (`archive_evidence._Pool.slot`'s rule).
* `0` disables it.

The bound is a guarantee, not a routine: the whole 09-11 sweep was ~3 of its 4 min 12 s, and
when 18 minutes does bind it lands in the **city tail**, which `_li_queries()` runs last and
which was worth **1 new card of 990** on 09-11 (18 queries, 169 cards, 1 new).

Above it, the step now runs under `timeout --signal=INT --kill-after=30 22m`, so the process
dies rather than being abandoned. Below it, two sub-budgets stay and their relationship is
written down: `LINKEDIN_BLANK_RETRY_SECONDS` (90 s per sweep, charged *inside* `_guest_page`
where the outer clock cannot see) and the per-query block re-ask.

## Rejected

| alternative | the number that killed it |
|---|---|
| delete the per-page pause (the brief's default) | 6 credits and 4,888 urns against 17–23 and 1,400–3,016 |
| lower the pause to 1.5 s so 18 min covers the 09-12 depth | it moves the one variable that produced the win, in the same commit as the bound. 09-13's log will price it; if the budget cuts into the 9 NATIONAL queries, the pause is the next thing to move, and then it moves with a number |
| raise the step's `timeout-minutes` instead | the file's step budgets already summed to 313 against a job cap of 285 (a comment claiming 270 and claiming the cap sat above the sum), so raising a step makes a false invariant falser. GNU `timeout` is strictly better: the process actually dies |
| `scrape_universal.Deadline` | it means importing the Playwright/`bd_rescue` render stack into the keyless intake layer, whose own habit is to import the spender *inside* `linkedin_search` |
| fold `LINKEDIN_BLANK_RETRY_SECONDS` into the new clock | it bounds time spent *inside* one `_guest_page`, which the between-pages deadline cannot see, and it is per SWEEP where the new one is per RUN. Deleting it lets one pathological query eat 13 of the 18 minutes and starve the other 26 |
| remove the blank re-ask (a standing `discovery` rule: `recovered` ~0 ⇒ remove) | it reads KEEP. 09-11's `recovered=0` is the outlier; the four nights before read 12 / 7 / 10 / 4 |

## The measurement to make tomorrow

`HANDOFF.md`'s 2026-09-13 `infra` rows. The one that decides this record: **`source_health`
linkedin ≥ 3,000 with `discovery_daily.py` credits ≤ 12.** A bounded walk that loses the
pacing's win is a FAIL even with a green step.
