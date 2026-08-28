# Firmographics refresh: 180 days stands, and the 12-call measurement was dropped

**2026-08-28, lane `company-intel`.** Decision: **keep `--refresh-days 180`. Build no refresh
cadence.** The measurement that was going to justify a change could not have answered the
question, and saying so is the finding.

Every number here is pinned to `origin/master@759ba36` and re-derived with the command beside
it. Supersedes nothing; this is the first time the question was asked with numbers.

## The question

`ARCHITECTURE.md` §7 says stage and headcount age silently — a company profiled once is
described as it was then. `firmographics.yml` sets `--refresh-days 180`, so nothing
re-researches before **2027-02-17**. Is that horizon right?

## What is free to measure, and what it says

**1. There is no stale tail. The oldest record is seven days old.**

```bash
python -c "import json,io,collections;d=json.load(io.open('cloud_state/firmographics.json',encoding='utf-8'));print(sorted(collections.Counter(v['as_of'] for v in d.values()).items()))"
```

| as_of | records |
|---|---|
| 2026-08-21 | 394 |
| 2026-08-22 | 378 |
| 2026-08-23 | 154 |
| 2026-08-24 | 14 |
| 2026-08-25 | 15 |
| 2026-08-26 | 18 |
| 2026-08-27 | 22 |
| 2026-08-28 | 2 |

The corpus was born in one week. §7's "a company profiled once in July" cannot be true —
there is no July. **Calendar staleness is not measurable in this store today**, because the
population it would be measured on does not exist.

**2. The evidence inside the records is older than the records — but that is not staleness.**

Newest year cited in `stage_note`: 2026 → 172, 2025 → 185, 2024 → 91, and **548 of 997 cite
nothing newer than 2023** (405 cite an older year, 143 cite none; the split moves with the
regex, the total does not). One record cites **2027**, a year that has not happened
(`Alma Labs`).

This is a signal, not a defect. A 2015 company that last raised in 2021 has a *correct* 2021
note. It cannot distinguish "our record is stale" from "nothing has happened to this company",
which is exactly why it needed the paid check below — and why the paid check had to be able to
tell those apart.

**3. The thundering herd. This is the real finding.**

Because all 997 share a birth week, at `--refresh-days 180` the **entire store turns stale
between 2027-02-17 and 2027-02-24**, at once. `REFRESH_CAP = 20/run` then needs ~50 runs to
drain it — while new registry rows compete for the same queue.

**4. And the refresh layer cannot currently run at all when the backlog is large.**

`research_firmographics.py`: refresh names are appended **last** (`todo.extend(refresh)`) and
`--limit` truncates **from the end** (`todo = todo[:a.limit]`). So whenever the new-name
backlog alone exceeds `--limit`, refresh gets **zero** slots. With `--limit 40` and today's
137-name backlog, `plan_counts(137, 20, 40) == (40, 20)` — all twenty deferred.

The ordering is right and stays: a company with **no** facts renders a card with no chips,
which is worse than a company whose chips are six months old. What was wrong is that it was
silent. It is now reported (`refresh deferred: N stale record(s) had no slot under --limit M`)
and the `N to do` line prints what the run will actually attempt rather than the pre-limit
count — it announced "137 to do" and attempted 40.

## Why the 12-call measurement was dropped

The plan was: re-research 12 records (6 with `stage_note` ≤2023 and a private stage, 6 public
or acquired), count material changes, and build a cadence if ≥3 of 12 changed. Two independent
reasons that could not have worked, both fatal:

**It would have measured instrument noise, not staleness.** Every candidate record is ≤7 days
old. Re-researching one produces a second `sonnet` / `effort=low` answer to the same prompt.
Nothing material changes about a company in seven days, so **the entire observed disagreement
would have been model variance** — and the decision rule attributed 100% of it to elapsed time.
The same 12 records re-researched twice on one afternoon would have produced the same
disagreement rate, and the rule would have read it as staleness.

**And n=12 with a ≥3 threshold has unusable error rates in both directions:**

```bash
python -c "from math import comb; f=lambda k,n,p: sum(comb(n,i)*p**i*(1-p)**(n-i) for i in range(k,n+1)); [print(p, round(f(3,12,p),3)) for p in (0.05,0.10,0.20,0.30)]"
```

| true material rate | P(the rule says "build it") |
|---|---|
| 5 % | 0.020 |
| **10 %** (a plausible pure noise floor) | **0.111** — says "build it" 1 time in 9 with nothing stale |
| **20 %** (clearly worth building) | **0.442** — says "build nothing" **56 %** of the time |
| 30 % | 0.747 |

A rule that cannot say "no" for the right reason is not a measurement.

**What a real measurement would cost, so the next session does not re-derive it.** It needs a
control arm — records whose evidence is current, where any disagreement *must* be noise — and
enough per arm to separate two rates. To separate a 10 % noise floor from a 40 % real rate at
80 % power needs **~20–30 per arm, i.e. 40–60 calls**, not 12:

| n per arm | power (10 % vs 40 %) |
|---|---|
| 6 | 0.36 |
| 10 | 0.50 |
| 20 | 0.76 |
| 30 | 0.89 |

And it is **not runnable today at any n**, because the aged arm does not exist: a `stage_note`
citing 2023 is a company with no recent news, not an aged record. The measurement becomes
possible only when records have actually aged.

Note also that running it through `research_firmographics.py` would have *altered* what it
measured: the field-generic merge-preserve backfills every empty fresh field from the old
record and re-derives `size_band`, so a store-side diff systematically under-counts change —
and `st.save_firmographics` stamps a new `as_of`, destroying the very birth-week uniformity
under study.

## Decision

**`--refresh-days 180` stands. No refresh cadence is built, no jitter, no per-stage horizon.**
Nothing in this store is stale, the mechanism to refresh it already exists, and the honest
answer to "is 180 the right number" is *not yet knowable* — an unmeasured worry is not a
finding, and neither is a measurement that cannot fail.

**Re-measure when either is true:**

1. **2026-11-19** — the day the oldest record passes 90 days, the first date at which an aged
   arm exists at all. Run the two-arm design above at ≥20 per arm (~40–60 calls).
2. **Immediately**, if the `Company intel:` line's new stall alarm ever fires on a shrunk
   export rather than a dropped cron.

**Before 2027-02-17**, whoever owns this lane must decide what happens to the herd — 997
records going stale in one week against a 20/run cap and a new-name queue that outranks them.
Two candidates, neither measured and so neither built: a per-company jitter on `is_stale` so
the birth week spreads, or a refresh budget independent of `--limit`. Filed as
`387@company-intel`. It has six months of warning and should not be spent now.

## What was shipped instead

Nothing about the horizon; two things about being able to see it:

- the refresh starvation is reported instead of silent (`plan_counts`, guarded)
- the `Company intel:` line raises `::warning::company-intel` when `export_newest` is more
  than `EXPORT_STALE_DAYS` old — the alarm for a bulk cron that stopped running, which is the
  failure that actually happened this week

**Spent on this decision: 0 LLM calls, 0 Bright Data credits.**
