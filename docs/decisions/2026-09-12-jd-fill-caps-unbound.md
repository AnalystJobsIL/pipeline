# 2026-09-12 — the digest's JD caps stop binding

*lane: `infra`. Supersedes the NUMBERS in `2026-08-31-indeed-paid-rung.md` (see its addendum),
not its mechanism. The "optimize once" `2026-09-11-bd-unlimited-optimize-once.md` asked for.*

## The state this replaces

Bright Data has been unlimited by operator ruling since 2026-09-11 — 5,000 is the FREE TIER
and a soft line, past which a credit is $1.50/1,000 and this September projects about $14. One
consumer was still bound, and it was the dataset-critical one. The 2026-09-12 mail:

```
inline jd-fill: the Bright Data cap bound at 30 — the postings past it were judged with no description
inline jd-fill: the Indeed cap bound at 25 — 15 Indeed postings judged on their snippet tonight
classify 9 superseded verdicts CANNOT be re-judged: the role has no description this run
classify 5 roles judged on the title alone
```

The same mail's gauge read `7-day rate 452/day (search 339 unlock 90 discovery 18 jd-fill 5)`.
And the same library's *other* pool — `enrich_scrape_jd.py --archive-only` at 12:30, filling
text for postings nobody publishes tonight — gets `JD_ENRICH_BD_CAP=1000` per run
(`jd-archive.yml`). The pool that decides what is emailed this morning got **30**.

**`jd-fill 5/day` is a measurement artefact, and the honest number is stronger.**
`_book_jd_fill()` shipped on the evening of 09-11, so `cloud_state/bd_spend.jsonl` labels
`jd-fill` credits only from that date: 0/day for 09-01…09-10, then 25 and 38. What the rung
actually did is spend **its whole cap on 6 of the last 8 nights**, and on the other two the
monthly ceiling had switched it off entirely.

## Measured demand

From the `jd-fill:` line of each digest's pipeline step. The two clean readings are the nights
the ceiling turned the paid rung fully off, so the entire demand printed rather than the part
that fitted:

| night | reading | total | Indeed | non-Indeed |
|---|---|---|---|---|
| 09-10 | `the paid rung is configured and UNUSABLE (monthly-ceiling) with 53 postings the free rungs could not read`; `auth-walled 44` | **53** | 44 | 9 |
| 09-11 | same shape, **49**; `auth-walled 41` | **49** | 41 | 8 |
| 09-12 | `Bright Data 23/40 filled (30 credits)` + `auth-walled 15` | **55** | 40 | 15 |

p95 ≈ **59** total and **44** Indeed. **The Indeed cards are a SUBSET of the total, not an
addend** — `pipeline/jdfill.py` increments both `refused[(platform,"auth-walled")]` and
`bd_unavailable_work` for the same card — and a first pass at this record added them, which
would have sized the caps against a demand of 92 that does not exist.

## What changed

| `daily-digest.yml`, the `Run the pipeline` step | from | to |
|---|---|---|
| `JDFILL_BD_CAP` | 30 | **150** |
| `JDFILL_INDEED_CAP` | *(unset — an invisible default of 25)* | **60** |
| `JDFILL_TIME_BUDGET_MIN` | 25 | **35** |
| step `timeout-minutes` | 110 | **130** |
| job `timeout-minutes` | 340 | **360** |

**150 is a circuit breaker, not a budget** — the wording `jd-archive.yml` already uses for the
same library's other pool. 2.5× p95, meant never to bind; `0` still disables the rung.
**60 is set explicitly** because a default nobody can see is not a configuration: it was an
invisible 25 for twelve days while the mail reported it binding every night. It is a **sub-cap**
of the one above, so raising it alone would only move the refusal from `indeed-capped` to
`bd-capped` and the mail would still say `cap bound`. 60 × 30 = 1,800/month worst case against
an expectation of 44 × 30 = 1,320.

**Precondition, load-bearing: `JDFILL_RENDER_CAP` stays 0.** A render is 5.8–27.8 s against a
raw fetch's 4.3 s median, so 150 renders is 69 minutes and none of the arithmetic below holds.

## The three bounds behind it, because raising one moves the bind

This is the 2026-09-04 lesson: `WAYBACK_REQ_CAP` 140 bound before `WAYBACK_DAY_CAP` 150, so a
session raised a cap and moved the bind instead of lifting it.

* **Cap-saturated cost.** 150 × 6.0 s (the documented max for a raw residential fetch) = 15 min.
* **The tail, which is the one that bites.** `Unlocker.__call__` defaults to `timeout=90`, and
  the failing-streak breaker opens at `_failing_at = max(breaker*2, min(breaker*4, max(3, cap//2)))`
  — **15 at cap 30, and 20 for any cap ≥ 40**. A night where every paid call times out is
  20 × 90 s = **30 min**, which was already 90 % of the old 25-minute budget *before* anything
  was raised. Hence 35.
* **The step is additive**, because `JDFiller` and `seniority.Classifier` interleave in one loop:
  fetch 8 + jd-fill 35 + classify 60 (`CLASSIFY_TIME_BUDGET_MIN`'s default, set in no workflow)
  + intel 15 + render 2 = **120**. At 110 with jd-fill at 25 that sum was **110 exactly** — zero
  margin, and the step's own comment omitted the jd-fill budget from its arithmetic.
* Measured against all of it: the 09-12 pipeline step ran **17.4 min** of its 110 and the whole
  job **67** of its 285. The relay cutoff (`RELAY_LAST_POLL_UTC` 23:39) is not in play.

`test_the_inline_jd_caps_bind_before_the_clock_and_the_clock_before_the_kill` derives all three
from the workflow and the real `Unlocker`, so the next raise cannot skip one.

**`BD_RUN_CAP` is not one of the bounds, and that is worth knowing.** `pipeline/jdfill.py`'s
`Unlocker` POSTs `api.brightdata.com` itself and says so at its own definition: "neither
`BD_RUN_CAP` nor `BD_PAID_RUNGS` nor the ceiling reached this layer". 2026-09-11 closed the
*ceiling* half. So an operator setting `BD_RUN_CAP=0` to stop spending does **not** stop the
digest's JD fill, and the only network-independent backstop on this rung is the cap itself.
Filed.

## The allowance table is knowingly short, and was not re-cut

`pipeline/bd_budget.ALLOWANCES["jd-fill"]` = 1,500/month was sized against a 30/night cap
(= 900/month). At 150 the ceiling is **4,500/month** and the expectation ~1,770, so the
allowance is 2–3× short.

It was **not** re-cut, and the reason is arithmetic rather than caution: the table is a **5,000
split of a 13,560/month measured demand** (`search` runs 339/day = 10,173 against an allowance
of 2,000; `unlock` 90/day = 2,697 against 700). **No re-cut inside `SOFT` can cover 4,500**, and
any attempt takes credits from `search`, which is the registry drain that is *this morning*
reporting itself behind its own intake. The mechanism enforces nothing today — `BD_ALLOWANCES`
is set in no workflow — and `bd_budget.py` states its own precondition for enabling it: "a
second consecutive month projecting past `SOFT` with the operator **unwilling** to pay it". The
09-11 ruling is the operator willing.

The deeper point, filed with the re-cut: **`SOFT` is a PRICE line, not a capacity.** Splitting
the free tier is splitting the wrong number, and a table whose sum must equal it cannot express
a month that legitimately costs $14.

`test_the_jd_fill_allowance_is_knowingly_short_of_its_cap_and_the_number_is_written_down`
asserts the mismatch and that this record names it, so the re-cut and its filing move together.

## Indeed needs no purpose of its own

Traced end to end: an Indeed card's paid call goes `maybe_fill` → `fetch_jd` → `_bd_call` →
`Unlocker.__call__` → `_monthly_ceiling_reached()` → `bd_budget.may_spend("jd-fill")` →
`_book_jd_fill()`. It is the **same** consult, the same purpose and the same product — one
Unlocker `/request` for a posting's own description before the classifier judges it — and
`bd_rescue` defines the four purposes as "the ones a budget would ever be split along", of which
host is not one. A `jd-fill-indeed` label would be folded into `unlock` by `rates()` and would
silently inflate the mail's gauge.

Two consequences of the raise that are *not* fixed here and are filed for `jd-text`, whose file
`pipeline/jdfill.py` is: `indeed_tried` is printed nowhere and becomes ~44 of ~59 credits (it
only reaches the mail today when the cap BINDS, which is exactly what this change stops), and
the allowance consult is lazy — once per run on first spend — so a run that starts inside its
allowance may now overshoot by up to 150 credits rather than 30.

## Rejected

| alternative | the number |
|---|---|
| cap **80** instead of 150 | the tail is identical (`_failing_at` saturates at 20 for any cap ≥ 40), so 80 buys the same clock cost as 150 and less headroom over a p95 of 59 |
| raise the Indeed cap only | it nests inside the BD cap: the refusal moves to `bd-capped` and the mail says `cap bound` either way |
| re-cut `ALLOWANCES` to fit | 4,500 against a 5,000 table whose other three classes already hold 3,500 against 13,419/month of real demand — the arithmetic refuses it |
| a `jd-fill-indeed` purpose | `rates()` folds an unknown purpose into `unlock`, so it would corrupt the gauge; doing it properly moves `PURPOSES`, `ALLOWANCES`, the sum guard, `TOOL_PURPOSE` and `docs/BRIGHTDATA.md` for a reporting split |
| leave `JDFILL_TIME_BUDGET_MIN` at 25 | 20 × 90 s = 30 min > 25: the roles past the clock are judged with no description, which is the defect being removed |

## The measurement to make tomorrow

`HANDOFF.md`'s 2026-09-13 `infra` row: no `cap bound` clause of either kind, no
`bd-capped`/`bd-render-capped` in the `jd-fill:` line's `failed:` terms, no
`discovery-indeed auth-walled` in its `unfillable` terms, `bd:` `jdfill=` above 30, and both
`judged on the title alone` and `CANNOT be re-judged` falling. **If the mail reports the TIME
budget binding instead, the cap raise worked and the second bound is the answer, not the cap.**
