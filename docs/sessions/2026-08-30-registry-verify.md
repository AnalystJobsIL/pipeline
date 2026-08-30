# registry — 2026-08-30: one verifier, and a drain that survives the session

## What was wrong

Three different checks decided "is this URL this company's board?" and they disagreed with
each other on live rows. The measurement, over the registry as it stood:

| | count |
|---|---|
| parked rows carrying `monitored candidate` | 554 |
| ...of those, written by the `listing-hunt` cron and **never LLM-checked at all** | 187 |
| ...admitted by a mechanical title match alone | 147 |
| ACTIVE rows written from the queue with no QA record | 276 |
| **rows that exist DESPITE a `NOT-THEIRS` verdict in an earlier run of the same tool** | **29** |

`qa_proposals` said `Greylock Partners` -> NOT-THEIRS on one run and `ok-by-model` on the
next, and the second run wrote an **ACTIVE** row for a VC's portfolio-jobs page. `Malam`,
`Aijobs AI`, `Acca Careers`, `McKinsey & Company`, `Minet Technologies` and `Chorus` have the
same shape. A single LLM read of raw HTML is not a verifier; it is a coin whose bias we liked.

And it is not cosmetic debt, because of `listing_hunt.py:297`: a parked row with an address is
in `probe_candidates`' DAILY pool, and the hunt's fast path ACTIVATES it the moment that page
shows Israel roles -- on `il and not is_foreign(...)`, with no model in the loop and
`is_foreign` inert on every ATS host. **A wrong monitor address is a wrong ACTIVE row on a
timer.**

## `pipeline/board_verify.py` — the one standard

The page is RENDERED before it is read (plain -> render -> unlocker, escalating on VISIBLE
text: `at-bay.com/careers` is 399,978 characters of markup and 4,628 of text, and a React
shell is the inverse). The model answers four questions -- own board, which employer, the
ISRAELI entity, what KIND of page -- and when the reading disagrees with the host-and-title
evidence it is asked AGAIN. **Two different answers mean `UNVERIFIABLE`, never `ok`**: a
verdict that does not reproduce is not a verdict, which is exactly what Greylock needed.

Calibrated against known cases before it was used on anything. It refuses `Greylock Partners`
(aggregator), `Aijobs AI`, `Acca Careers`, `Minet`, `Chorus` (a New Zealand telco) and
`Bdo International` -> **BDO India Services** -- the namesake-abroad class nothing here could
previously see -- while passing `KELA`, `Teva`, `Nebius` and `At-Bay`.

A fifth verdict came out of the run rather than the design: **`dead-url`**. `Enigmatos`,
`LightSolver` and `Pluri` each render 1-9 KB of text beginning *"Page not found"* under a live
registry row that `probe_candidates` was fetching daily. A page that says it does not exist is
evidence about the ADDRESS; a timeout or a bot wall is evidence about US, and collapsing them
would either hide dead rows or park live ones.

**Result: 760 verdicts, 151 rows pointing at a board that is not theirs, and 0 left.**

## Four defects the run found in my own code

* `UNVERIFIABLE` was re-asked on EVERY run and the cloud step is `--limit 60`. With 111 rows
  unreadable through all three routes, the nightly would re-read the same 111 for ever and
  never reach a row nobody had read -- green step, spent credits, no progress. 7-day cadence
  now, and never-read addresses sort first.
* `addressless` interleaved search and render in one loop, so after the first scrape every
  search returned "": **24 `no-search-results` out of 25**, on names including `Teva`,
  `Gong.io` and `Taldor`. A broken run wearing the clothes of a measurement (rule 2). Two
  phases now, and an AST test asserts no entrypoint can interleave them again.
* `park_unverified` refused 10 rows whose note was full -- leaving a WRONG board live to
  protect a note. It uses `replace_own` now and, if the cell still cannot take it, clears the
  address anyway: the reason is not lost, because `cloud_state/board_verify.json` holds the
  verdict and is committed.
* `board_verify.save()` overwrote. Four shards writing one document meant the last save
  discarded the other three -- the two-snapshot-writers rule, one file over.

## Two counts that were lies by omission

**`owed` is two states.** ~45% of judged names come back `cannot-tell`: a real employer whose
board we have not found. That is the honest verdict, and the operator's standard says such a
name is one to keep hunting -- so the queue reaching zero was never the target. The census now
separates `owed, a nightly rung retries it` from `STUCK: no cadence reaches it`, and the stamp
alarms on the second. It found exactly two, both bookkeeping rather than research:
`Infrastructure Team` (`junk`) and `Residenthome` (`resolved`) carried settled verdicts and
still sat in the queue, where `queue_resolve_search` skips them by design.
`--retire-settled` clears that class. **STUCK is 0.**

**`no address` is two states.** Parking a wrong board CLEARS the address -- that is the point,
it leaves `probe_candidates`' daily pool -- but that moved 127 rows into a bucket labelled
"watched by nothing" when `needs re-resolution` puts them in `listing_hunt.HUNT_POOL`. The
census asks the pools themselves (never a retyped mirror; `registry_health` records what a
mirrored pool cost) and reports `IN NO POOL` separately. **That is 0.**

## The drain now survives the session

Everything above ran by hand, and so did the two backlogs before it. Intake, from the last
commit of `research_companies.json` on each of nine days (arrivals; prunes excluded):

    08-22 +88   08-23 +21   08-24 +258  08-25 +53   08-26 +75
    08-27 +109  08-28 +642  08-29 +92        mean 167/day, median 92

against a scheduled queue arm capped at 60. **Raising that cap alone changes nothing**, and
that is the part worth writing down: the arm is bounded by RESERVED MINUTES, not the cap --
`HUNT_QUEUE_MIN=60` at ~60 s/name is ~60 names, so cap and clock already agree and the clock
wins. Reaching 92/day through it would need ~92 of the hunt's 200 minutes, taken from the row
pool, to buy a rung that resolved **2 of 57 names**.

So `HUNT_QUEUE_CAP=0` retires that arm (0 is OFF, not unlimited), `HUNT_QUEUE_MIN=0` returns
its minutes to the row pool, the hunt drops 200 -> 140, and the 60 released minutes buy
`queue_resolve_search` at 56%. Four steps at 19:00, and `test_the_queue_drain_is_actually_scheduled`
asserts both the wiring and the arithmetic: **140 + 95 + ~90 = 325 of a 330 cap** -- over it,
the job dies before `persist_state` commits the night's work.

## The cron ran, and here is its log rather than my hope

Run `33276177460`, 2026-08-29T21:28Z. All four steps green -- which proves nothing on its own,
so what they DID:

| step | wall | what it did |
|---|---|---|
| Resolve intake names (queue drain) | 7 s | **`queue-resolve-search: 0 names`** |
| Verify and apply queue proposals | 0 s | nothing to apply |
| Re-verify aged registry addresses | **11m 49s** | 60 rows: 22 PARKED (12 another company's, 14 dead-url), 11 ok, 21 unreadable |
| Stamp the queue | <1 s | fired its alarm |

```
queue: 508 owed (+5 since 2026-08-29, GROWING), 502 rows from the queue, 428 unverified
##[warning]queue GREW by 5 since 2026-08-29 -- the drain is not keeping pace with intake
```

**The drain finding 0 names is the cadence working, not a failure.** Every queue name had a
`search-llm` attempt from the same evening's local sweep, so all of them were inside
`tried_within(..., "search-llm", 14)`. It will select on the next day's intake. But it means
the drain arm is **unproven at scale in the cloud**, and this record says so rather than
implying the green tick settles it.

**The re-verify arm IS proven**: unattended, it parked 22 wrong or dead addresses. That is the
arm that removes live risk.

**The alarm works and it corrected me.** `GROWING +5` was true of the cloud's checkout at that
moment; my local tree had since retired 78 more. The two disagreed because the cron and I were
writing the same files concurrently -- the merge strategies handled the files, the STAMP read
mid-flight. That is a real limitation of a number computed at one instant, and it is the
reason the stamp reports a direction rather than a verdict.

### Does 60 a night sustain itself?

    addresses in the verify scope                       650
    re-reads at the 30-day cadence                    22/night
    unreadable re-tries at the 7-day cadence           19/night
    new rows                                           0/night  (verified BEFORE they become
                                                                 rows, by --apply-proposals)
    ------------------------------------------------------------
    needed                                            41/night
    the nightly step does                             60/night

It sustains. The backlog it inherited is already gone: **0 rows are due a read** as of this
record, from 829 when the verifier was written.

## What I did NOT finish

* **481 names owed**, every one of them retried by a nightly rung. Not zero, and the reason is
  in "`owed` is two states" above: a real company whose board we have not found is one to keep
  hunting, not one to retire.
* The DRAIN arm has never selected a name in the cloud (it found 0, correctly, because the
  local sweep had just touched every queue name). The re-verify and stamp arms are proven.
  Read the next run's `queue-resolve-search: N names` line before calling the drain proven.
* **425** (7 embedded Comeet tenants the gate cannot admit) and **426** (a worktree has no
  `secrets.env`, so paid rungs no-op in silence) are open.
