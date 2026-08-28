# 2026-08-28 — the Bright Data ceiling, and who is allowed to switch a paid rung on

**Lane `infra`. Settles the contradiction between `192@discovery` and `335@infra`, and closes
the mechanism half of both. The number is the operator's decision; the mechanism is this
lane's.**

## The two numbers, and the answer

| source | ceiling | dated |
|---|---|---|
| `192@discovery` | **4,500** for the whole project | decision of 2026-08-25, "from 2026-09" |
| `335@infra` | **5,000** | instruction of 2026-08-27, "self-sufficient at 5,000 monthly" |
| the code | 5,000 (`discovery_daily.py`'s default) | set in **no workflow at all** |

**Operator's answer, 2026-08-28: no ceiling for the rest of August; 5,000 from 2026-09-01.**

August is deliberately uncapped because the pool already stood at ~6,798 month-to-date and a
5,000 ceiling makes `budget_per_day()` return 0 — which is why `335` records the targeted
backfill printing `SKIPPED this run — no budget` while paid credits sat unused in the account.
Capping a month that is already over its old ceiling buys nothing and costs coverage.

The rule is encoded **once**, in `pipeline/bd_budget.ceiling()`, with
`test_the_bright_data_ceiling_changes_itself_on_2026_09_01` pinning **both sides** of the
boundary. A dated constant that nobody verifies is precisely the confidently-wrong document
this repo punishes hardest, so the date may only live in code because a guard proves it fires.
`BD_MONTHLY_BUDGET` still overrides it, for a month that needs a different answer.

## What was actually wrong, measured

`.github/workflows/scrape-refresh.yml:52` set `SCRAPE_VIA_UNLOCKER: "1"` — hardcoded, no
dispatch input, no cap of any kind — on a nightly cron nobody watches. What that bought, from
`cloud_state/pipeline_stages.json` on 2026-08-28:

```
unlock_calls 72  ->  unlock_ok 63  ->  unlock_won 10
```

**72 credits to win 10 boards.** That number existed in a committed state file and appeared
nowhere a human looks. Three further facts made it unbounded rather than merely unwatched:

* **Every cap in this repo is per-PROCESS.** `DEEP_BD_SEARCH_CAP`, `PAGE_UNLOCK_BUDGET`,
  `LLM_BD_SEARCH_CAP`, `jdfill.Unlocker`'s caps — each resets in every new process, and each
  workflow step is a new process. Nothing bounded a whole job, let alone a night.
* **There is no persisted credit ledger anywhere in the repo.** The only month-to-date figure
  in existence is fetched live from the account by `discovery_daily.bd_spend_this_month()`,
  printed, and thrown away.
* **`SCRAPE_VIA_UNLOCKER` arms on any non-empty value, including the string `"0"`**, because
  every reader is `os.environ.get(...)`. A switch that reads `0` and means ON is worse than no
  switch.

## The mechanism, in three parts

**1. A switch that is not a source edit.** `SCRAPE_VIA_UNLOCKER` is now
`${{ (github.event.inputs.unlocker || vars.BD_PAID_RUNGS || 'on') == 'off' && '' || '1' }}` at
all five sites (`scrape-refresh`, `listing-hunt` ×3, `triage-dark`). `BD_PAID_RUNGS` is a repo
**variable** — settable in Settings, no commit, no run — and a `workflow_dispatch` input
overrides it for one run. Off yields the **empty string**, never `"0"`, for the reason above.

**2. A per-run bound that does not depend on the network.** `BD_RUN_CAP`, enforced in
`bd_rescue.unlock_status` — the one chokepoint that ten of the ~thirteen spend paths reach
(`scrape_universal`, `crack_walled`, `triage_dark`, `repair_dead_urls`, `resolve_broken`,
`identity_gate`, `deep_validate` and through it `listing_hunt`/`resolve_llm`/`audit_empty_rows`/
`registry_health`, plus `discovery_daily`'s Indeed and LinkedIn sweeps).

It **defaults to 0 = unlimited**, deliberately: a lane that does not set it sees byte-for-byte
the behaviour it saw before. A capped call returns `bd-capped` — the same string
`jdfill.Unlocker` already uses — so no caller can read a refusal as "the page was empty", which
is `110@`'s whole lesson. `scrape-refresh` gets **150** (measured: 72). Everything else gets
**250**, and that number is honestly a **blast-radius limit, not a budget**: it exists so one
job's loop cannot run away — `retry-unreachable` could buy 600 credits a night and
`crack_walled` about 2,000, and neither had any limit at all. It is not derived from a
measurement, because no per-workflow measurement existed. Which brings us to:

**3. The measurement that did not exist.** `bd_rescue` now reports what each process bought, on
the way out, to the log and to `$GITHUB_STEP_SUMMARY`. `unlock_calls` was stamped only by
`refresh_scrape_cache`, so the other six workflows that spend reported nothing — their caps
could only ever have been guesses. After a week of `[bd-spend]` lines the 250s should be
replaced by numbers. That is filed, not assumed.

`scrape-refresh` also prints its own spend and win-rate to the run page, and a preflight step
decides — in one place — whether the run may buy anything at all, combining the switch with
`pipeline/bd_budget`'s monthly verdict.

## Failing open, on purpose

When the month-to-date figure cannot be read — API down, token rotated, network blip — the
preflight **spends anyway** and says so. Throttling on a number we could not fetch would
silently zero a night's coverage, which is the worst failure mode in this repo
(`pipeline/sources.py` exists because of one); the opposite mistake costs a few dollars.
`discovery_daily.budget_per_day` already takes exactly this view. `BD_RUN_CAP` is the bound
that holds when the network does not.

## Cost of this decision

Credits spent producing it: **zero**. Every step was local or a read of committed state; the
one live call made was `pipeline/bd_budget`'s own report, which reads `datasets/v3/snapshots`
and `zone/cost` — metadata endpoints that bill nothing — and which returned `unknown` locally
because this machine has no `secrets.env`. That is also the fail-open path, proven by running
it.

## What is left

* Replace the 250s with measured numbers once `[bd-spend]` has a week of history.
* `pipeline/bd_budget`'s preflight is wired into `scrape-refresh` only. The other six spenders
  get `BD_RUN_CAP` but not the monthly gate; extending it is mechanical and is filed.
* `264@infra` (the digest never reports its Bright Data spend) is now **partly** closed by the
  per-process `[bd-spend]` line; the digest's own summary line is not written yet.
