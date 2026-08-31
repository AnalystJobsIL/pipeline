# 2026-08-30 → 2026-08-31 — registry (e): the queue was never 546 names of work

*Lane: `registry`. One session at a time; I held it. Predecessors today: `registry-verify`
(00:42/03:45), `registry` (09:34), `registry-c` (15:29–18:40).*

## The two things that outlast tonight's drain

**1. A name the gate could not spell in ASCII vouched for every page on earth (`510`).**
`_name_targets("קבוצת שיבולת")` is the empty set, so `is_foreign` answered False for every
url on earth, `board_vouches` turned that into `True`, and `identity_ok` returned its
blanket `True`. The drain proposed **TheMarker's labour-news section** as that company's
board with `10/10 IL` — ten bylined articles counted as Israel jobs — and `apply_proposals`
would have written it **active**. An adversarial pass found it; I dropped the proposal by
hand; nothing in the code would have.

Fixed rather than made unactivatable, and the rule is **no ASCII bits is not a vouch — it is
"ask the page"**. `board_vouches` → `None`; `identity_ok` requires positive page
confirmation; `page_names_company` reads the name's **own script**, which it could not do
before (it answered False for `הפניקס` on `הפניקס`'s own careers page, where the name occurs
70 times). Hebrew filler is filtered exactly as `_NAME_FILLER` filters English — `קבוצת`
("group of") occurs **twice** on TheMarker's page and would otherwise have vouched, while
`שיבולת` occurs **zero** times. No token **and** no ASCII fallback answers `None`, never
`False`: an Israeli company's careers page is often entirely in English (`מטריקס` →
matrixdna.ai, 0 occurrences), so the gate defers rather than stamping a claim it cannot
support. Measured over all five active rows in this class — **1 activates on its own page,
4 defer (2 English/JS-rendered, 2 bot-walled), 0 accused.** The residue of the class is
unactivatable by default, and that is the honest cost.

**2. "Owed" was one number over three states, and it was wrong by 3x.** `queue_state.census`
printed `STILL OWED AN ANSWER 546`, and every plan of 2026-08-30 — four registry sessions
and the operator's own brief — was sized against it:

| state | count | what it means | what moves it |
|---|---|---|---|
| **OWED** | **172** | the drain would select it tonight | the drain |
| on cadence | 200 | a rung answered it inside 14 days | time |
| answered on disk | 174 | live retirement, or already a row | `--retire-settled` (free) |

OWED is now defined as *"`queue_resolve_search` would select it"* and the census **imports
that selector** instead of re-deriving it — a census that can disagree with the rung it
describes is exactly how 546 stood for a week. The `next rung` histogram, computed over the
owed set only, changes beyond recognition: `resolve-llm 234 · own-site 202 · (every rung
tried) 84` becomes **`own-site 164 · resolve-llm 6 · (every rung tried) 2`**. The honest
core — names no rung can reach — is **2**, not the 48 the brief estimated or the 84 the old
census implied.

And the number now reaches the mail. `pipeline/stages.summary()` renders `ORDER` and nothing
else, and **`queue` was not in it**: the stamp was written nightly and read by nobody, so the
registry's queue was un-named in the one place a human looks daily. The line leads with the
actionable count — `queue: 172 owed (-47 …, falling), 200 on cadence, 174 answered on disk
(546 unsettled)` — and the `GROWING` alarm keys on OWED, so a night that merely accumulates
answered-but-unapplied names no longer reads as a backlog forming.

## The number, and why the brief's version of it was the wrong shape

The brief said **546 owed · next rung resolve-llm 103 · own-site ~39 · every-rung-tried ~48
· search ~15**. Re-derived at `7f17156` with `python queue_state.py`, the owed total is
right and every rung count is wrong — they sum to 205, not 546:

| next rung | brief | measured |
|---|---|---|
| resolve-llm | 103 | **234** |
| own-site | ~39 | **202** |
| (every rung tried) | ~48 | **84** |
| search | ~15 | 20 |
| comeet-token / slug-probe | — | 5 / 1 |

But the rung census is not the number that decides anything, because **`next_rung` is not
what the drain selects on.** The paid rung is `search-llm`, which is not in `RUNGS` at all;
it selects on its own 14-day cadence plus three files. Asking it directly:

```
SELECTABLE for the paid search-llm rung right now: 172   (164 never tried by any rung)
OWED BUT NOT SELECTABLE:                          385
   searched by search-llm within 14 days          294
   live retirement (duplicate-of 64, not-an-employer 15, acquired-by 2)   81
   already a registry row (case/spelling)          10
```

Zero unexplained. **The queue was not 546 names waiting for work. It was 172 actionable
names, 294 already answered and waiting out a cadence, and 91 whose answer is on disk and
merely needs folding out.** Every plan tonight followed from that.

And the age profile settles the rest. Of those 172 selectable names, **163 first entered the
queue TODAY**; the entire older residue is **9 names**. There is no ancient backlog.

## What I spent, and what it bought

**187 Bright Data credits** (1 canary + 186 drain), **~172 sonnet calls**, 0 SerpApi
(exhausted), inside the unlimited window that ends 2026-09-01 00:00 UTC. Four local shards,
`--cap 90 --budget-min 200`, no shard hit its budget:

```
queue-resolve-search: 43 names (shard i/4)   x4  =  172 searched, 172 scored
TOTAL proposals 172:  monitor 81 (47%) · refused 67 (39%) · scrape 24 (14%)
refusals: no candidate was this company's live page 46 · their page, but not a board 19
          · no-search-results 2
```

**105 of 172 (61%) produced a usable answer.** The free ladder was run first over the whole
queue (`drain_queue --search 0`, 561 names, 0 credits) and is **exhausted**: 14 proposals,
1 of them a board — `never-hunted 1/561 = 0.2%`. That is the finding that set the night's
shape: on this queue the free rungs are tapped out and the paid rung is the only lever.

## Does it ever end — the sentence the brief asked for

Two numbers from real runs, not constants.

* **In.** Brand-new names/day, by name-set diff of every commit of `research_companies.json`:
  258 · 53 · 75 · 109 · 652 · 161 · **174 (today)** → median **161**, mean **212**. This
  reproduces `registry-c`'s measurement exactly.
* **Out.** Cloud drain **112/night** (`nightly_capacity()`, 4 shards x a self-budgeted 28).
  Tonight, by hand, **172**.

At today's rate in exceeds out and the queue grows — but the composition says why, and it is
fixable. Of the 172 selectable names, **141 (82%) come from the secrethunter CATALOG** and
only 20 from LinkedIn. `discovery` capped that arm at `SECRETHUNTER_DAY_CAP = 40` **tonight**
(its effective offer measured ~31/day). Post-cap the selectable inflow is bounded by roughly
**40 catalog + ~20 LinkedIn + ~10 other ≈ 70/day against 112/night** — so out exceeds in by
~42/night and **the owed number should stop growing from 2026-08-31 onward**.

**That is a projection from the cap's ceiling, not a measurement, and I could not verify it
tonight**: the cap's first unattended proof is tomorrow's digest. The morning-check row I
added is exactly that test. If the `[secrethunter]` line does not read `day window 40`, or
selectable inflow lands above 112, this paragraph is wrong and the capacity item
(`491@infra` item 3) is live again.

**The treadmill is not capacity.** 294 owed names sit in the 14-day cadence, and the verdict
census says ~109 of them are *refusals* (`no candidate was this company's live page` 85,
`their page, but not a board` 19, `no-search-results` 5) — plus tonight's 67. Those ~176
names are re-searched every 14 days for ever at one paid credit each. More capacity buys
nothing there; a judged retirement does. That is the honest core, and it is **176, not 48**.

## The two bugs the Sunday audit will otherwise re-create on 2026-09-06

Both attributions in the brief were wrong, and the difference moves the fix:

* The `JPMorgan Chase` / `JPMorganChase` twin was written by **`crack_walled`**'s `cracked`
  branch (its own note in `7319f85`: `crack-walled 2026-08-30: oraclecloud via oraclehcm`),
  not `audit_empty_rows:491` — though that site had the identical missing guard.
* The `Renesas Electronics` smartrecruiters-on-a-company-site row was written by
  **`deep_validate.apply_verdict`**'s LLM tier. `crack_walled` cannot emit `smartrecruiters`
  at all. The LLM proposes platform, token and url independently and
  `fetch_smartrecruiters` appends its query to whatever it is handed, so the row verified
  with 905 jobs and nothing downstream objected.

**`audit_empty_rows.active_twin`** is the guard, keyed four ways (platform+token, exact url,
host+path, Comeet uid, plus the ATS board a `scrape` row is really reading), fed the rows the
write is about to mutate. **`deep_validate`** now repairs an off-host native endpoint to the
platform's canonical form from the `SIGS` template, re-verifies it, **and puts the repaired
address back through the identity gate and the twin check** before writing. Refusals stamp
`twin-board; not activated` / `endpoint off-host; unverified` — never `not-ours` (the board
IS the company's) and never `alias-of` (which row survives is a human's call; an activating
tool that retires coverage is the larger bug).

`502@registry` closed on the way past: proposal files and the search cache write through
`pipeline.atomic`, and an unreadable shard is a `::warning::ingest:` line rather than a
silent skip that re-buys the night's searches.

## What the adversarial waves found in my own diff

Two Opus waves, four agents. They returned nine findings; **three would have shipped a bug,
two of them mine and both `blocks-push`:**

1. **Five tools flip `active` off a verified board, not three.** `listing_hunt` and
   `repair_extract_gap` do it **nightly**, and the second activates off the row's STORED
   address — the shape that puts parked `Orca-AI` on active `Orca AI`'s careers page, one
   trailing slash apart. My doc said three and my test named a list of three. The test now
   scans for `fr[4] = "true"` exactly as its sibling scans for the identity gate.
2. **The repaired endpoint faced neither gate.** `activation_verdict` was asked about the url
   the *model* proposed; the repair then wrote a different one (the
   `CyberArk -> paloaltonetworks` shape). And the twin check ran *before* the repair, so it
   could not see the twin the repair itself created — a red B2 at the persist gate, the exact
   thing this change exists to prevent. Repair now runs first; the address that will be
   written faces both.
3. **My predicate retyped a weaker key than the repo already owns.** It now imports
   `apply_proposals._url_keys` and `COMEET_UID`. Both were live misses: `AWS` /
   `Amazon Web Services (AWS)` share one amazon.jobs page differing only by `?loc_query=`,
   and `DealHub` / `DealHub.ai` share one Comeet board — 189 active Comeet rows had no key at
   all. A greenhouse `/embed/job_board?for=<tenant>` puts the tenant in the QUERY, so
   host+path is skipped there and the path word `embed` is not read as a tenant.

Also applied: a twin refusal no longer routes the row into the **paid** deep rung; `{plat}`
is out of the off-host note (it cost one row its `in_pool` membership and 37 more their hunt
ownership); and two claims I had written were measured false and corrected — the notes **do**
evict (215 of 583 rows lose a pool token to the twin segment, 47 lose `listing_hunt`
ownership), and a refused row waits `_revalidatable` **30 days**, not "next Sunday".

**Two live duplicate pairs the guard surfaced and did not create:** `AWS` /
`Amazon Web Services (AWS)`, and `DealHub` / `DealHub.ai`. Both are active today, both
publish one board's roles under two employer names, and `check_invariants` B2 cannot see
either (its key carries the query string). Which row survives is an operator call, so I
parked nothing — filed.

## Not finished

* The **dispose pass on the ~176-name honest core** — judged retirement is the only exit for
  a name the paid rung has refused, and re-searching them every 14 days is the treadmill.
* The **two live twin pairs** need an operator decision on which row survives.
* `193@infra` carries the measured path-signature `PLATFORM_HOST` diff (C2 is blind to seven
  platforms; bare hosts would strict-break five live rows because eightfold/phenom/
  successfactors serve from the tenant's own domain). Until `infra` applies it, C2 cannot
  catch the class `deep_validate` now guards at its own write site.
* The rehearsal (`tests/rehearse_registry.py`) does not exercise `deep_validate` at all, so
  its green is not evidence for any of these notes.
