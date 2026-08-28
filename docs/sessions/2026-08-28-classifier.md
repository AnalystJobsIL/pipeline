# 2026-08-28 — `classifier` lane: the tier that was never dead, and a cache key that expires

Spec: `ARCHITECTURE.md` §7b. Scope decision: `docs/decisions/2026-08-28-analyst-scope.md`.
Open items: `docs/BACKLOG.md` 369–373. Every number here was produced by a command run this
session, and the command is beside it.

## The finding I was given, and what it actually was

> Yesterday `scraper` cached 65 boards that had never been read, adding 423 postings. The
> title predicate passed 22; 3 reached `matched`; **19 dropped**. The digest reported
> **0 LLM calls**. The adjudicating tier did not fire, so everything ambiguous fell to a
> deterministic fallback and was dropped silently.

**The funnel reproduces exactly. The conclusion does not.**

```
boards before 209 -> after 263                                  = 65 new       reproduces
  (net +54: 11 boards in the baseline are GONE from master -- not part of this
   finding, but the two numbers do not reconcile without it)
postings on the new boards                                      = 423          reproduces
_relevance: strong 6 · signal 16 · excluded 116 · none 285                      reproduces
title-passing 22, of which 21 carry 400+ chars                                  reproduces
```

`llm_calls` is `Classifier.attempts` (`pipeline/run.py:292`) — calls **launched**. A verdict
served from cache is invisible in it. And **three digest runs happened that morning**, at
07:08, 08:54 and 10:29 UTC (commits `9bbaf698`, `1f3b830d`, `8243d05a`, each "cloud run:
state + digest for 2026-08-28"; their Actions run records were deleted per `CLAUDE.local.md`
§3, so the logs are gone and the commits are the evidence).

**The proof is the per-run cache delta**, not any one digest file. `cloud_state/seen.db`
fetched at each of the three commits (blobs API — the contents API truncates >1 MB):

| after the run at | `llm_cache` rows | of them stamped `2026-08-28` | added by that run |
|---|---|---|---|
| 07:08 (`9bbaf698`) | 577 | 16 | — |
| 08:54 (`1f3b830d`) | 593 | 32 | **+16** |
| 10:29 (`8243d05a`) | 593 | 32 | **+0** |

A row reaches `llm_cache` only on the `llm` path (`seniority.py`, `self.staged[key] = verdict`
after `_judge` returned non-None), so every one is a real adjudication. The day was
**16 + 16 + 0**, and the third run demonstrably bought nothing. 16 of the 19 "dropped" roles
are named in those rows.

Two corrections a wave-1 attacker forced, both of which I had wrong:

- **`digests/latest.md` is the same file at all three commits.** Only the 07:08 run wrote it
  (`persist_state.py deliver` "refuses a weaker same-date replacement", because a second
  same-day run renders 0 new roles once `filter_new` has drained `sent`). So its
  `LLM calls this run: 16` describes run **one**, and citing it at the third commit reads as
  the opposite of what it says. It is quoted here at `9bbaf698`, where it belongs.
- **"32 calls" is a floor, not a count.** `store.save_llm_cache` writes only new-or-changed
  rows and only the success path stages one, so failed calls and any quarantined cohort are
  invisible. Run one's 16 rows match its own reported 16 attempts exactly (0 failures, 0
  quarantine); for run two we know only **≥ 16**. The day was **at least 32**.

**Why `attempts == 0` cannot mean a broken tier.** `self.attempts += 1` is the *first*
statement of `_judge`, before the subprocess is spawned — so a call that 401'd, timed out or
found no CLI would still have counted. And `off_reason` is assigned only inside `_strike`,
reachable only from `_judge`, and is not persisted across runs, so **the breaker cannot be
open at zero attempts**. `CLASSIFY_LLM_CAP=0` is the one alternative that would look the same,
and it is ruled out by `daily-digest.yml`, which sets no `CLASSIFY_*` variable at all and
passes no `--no-llm`. (I originally argued this from `llm_failed_fallback == 0`; that path is
*unreachable by construction* when `attempts == 0`, so it was a tautology, not evidence.)

**The morning was not fine, and the record should not read as if it were.**
`cloud_state/last_run.json` at `d47b3323` and `d0e3b00a` both say
`{"status": "failure", "failed_steps": {"pipeline": "failure"}}`. The LLM tier did not fail;
the two later runs did, at the `pipeline` step. All three run records were deleted, which is
what `CLAUDE.local.md` §3 asks for after a manual dispatch — so runs two and three were
probably dispatches, and run one's id is unrecoverable.

**Still inference, not proof:** that the 10:45 measurement was run three rather than an
untraced local run at 10:45. Nothing distinguishes them, and it does not matter —
`seen.db` has not changed since 10:29, so any run after it made 0 calls for the same reason.

## The 19, with a verdict each

Judged under the new contract through the production seam
(`tools/measure_title_gate.py --tier passing`, 22 calls, 38 s). Pinned as
`tests/fixtures/classifier/2026-08-28-newboards.json`.

| verdict | n | which |
|---|---|---|
| **correct reject** | **16** | Apptor-AI DS (builds churn/recommendation models) · Exodigo Signal Analyst (sensor/geophysical DSP) · IBI ×4 (investment, financial-reporting, strategic-projects, FP&A — finance is out) · KELA Threat Intelligence (security is out) · Logica-IT ×2 (ML dev, and an agency posting a client's role) · Opmed.ai DS Tech Lead (model development and fine-tuning) · Peak Innovation Data Analyst (a recruitment agency — the JD is FIZE Medical's, contacts `@pickpeak.co`) · REAL DEV INC (finance-facing, no description exists) · Teads Senior DS ×2 (5+ yrs coding ML at scale, MSc/PhD, recommender systems) · מטריקס DBA (DBA/ETL via an integrator) · מטריקס BI developer (ETL/DWH/Qlik admin, for a client) |
| **real miss** | **1** | `mećkano | Data Analyst | Petah Tikva` — SQL, Power BI/Tableau/Looker, dashboards, stakeholders, at a real Israeli SaaS company hiring for itself. Rejected **only** on the experience bar ("At least 2 years"). The operator removed that bar today; it is now a YES. |
| **inconclusive** | **1** | `הפניקס | אנליסט/ית טרנספורמציית AI` — the model's own reason: *"contains only website navigation/menu text with no actual job description"*. 4,000 chars of site nav stored as the description. Not a classifier verdict at all; filed as `370@jd-text`. |
| **not actually dropped** | **1** | `Tenengroup Ltd. | Business Analyst` — a YES, and in `matched` with `last_seen 2026-08-28`. It is on the board under the **duplicate registry row** `Tenengroup` (`371@registry`), which is why it read as missing. |

Two more of the 22 were not in the list of 19: `Ashley Digital | Marketing Analyst` (YES, in
`matched` but `last_seen 2026-08-21`, so it refreshes) and `EPAM Systems, Inc. | Managing
Principal / Senior Director, Data Analytics Consulting` — see the precision gap below.

**So: 1 real miss, recovered.** Not nine, not nineteen. Saying so is the deliverable.

## The title gate above this lane, measured for the first time

`_relevance` is this lane's, but `enrich_scrape_jd.py:39` and `pipeline/jdfill.py:865` import
it, so **this vocabulary decides which postings ever get a description** and therefore what
the tier can ever read. Its false-negative rate had never been measured. All **401** rejected
postings on those 65 boards were judged by the production seam — exhaustive, not a sample,
because a rate quoted off a sample invites the next session to re-derive it.

```
python tools/measure_title_gate.py --cache scraped_cache.json --baseline <older copy> \
    --tier rejected --workers 8            # 401 calls, 820 s
```

| cohort | analyst roles found | rate |
|---|---|---|
| all 401 | **1** | **0.25 %** |
| the 103 that carried a description — the only subset where the model knew more than the gate | 1 | 0.97 % |
| the 298 with a title only | 0 | 0.00 % |
| the 116 `excluded` (the hard-exclude list) | 0 | 0.00 % |
| the 285 `none` | 1 | 0.35 % |

The one: `Align Technology | Global Fulfillment Lead` — a title with no analytics word in it
at all, whose JD is dashboards and BI for logistics. No title vocabulary catches that without
admitting every "Lead".

**The gate is sound and stays. Nothing is owed to `jd-text`.** Across the whole cache it
rejects 1,528 of 1,607 Israel postings, so at the measured rate it is hiding **~4 roles in
total** — one-time, not per day — and removing it would cost ~1,528 description fetches plus
~1,528 LLM calls per pass to find them. The question is closed rather than handed on.

## What changed in the code

All of it in `pipeline/seniority.py`. `pipeline/llm.py` untouched; no other lane's file edited.

1. **The cache key expires.** `CONTRACT = "v3." + sha1(LLM_RULES + "|" + model)[:8]` replaces
   the literal `"v2"`. `KEY_VERSION` was hand-typed and was bumped **once, ever**, which is
   why `v2|apptor-ai|data scientist|jd` carried a NO from 2026-08-25 into every later run.
   A superseded verdict is **still served** — it is evidence, not garbage — and
   `CLASSIFY_REJUDGE_CAP` (60) of them are re-bought per run, so a scope change drains
   instead of cliff-edging. Drained roles are rewritten under the current contract and never
   return, which is also the shape `122@classifier` asks for.
2. **The trap that creates, fixed in the same commit.** Removing the experience bar flips a
   large cohort NO→YES all one way; `_suspect()` would call that `mass-flip` and `commit()`
   would withhold exactly the verdicts the run paid for, re-buying them every morning
   (`123@classifier`). `_v2_rejudged`/`_v2_flips` now count **same-contract** re-judgements
   only, for the same reason legacy verdicts were already exempt. I would have shipped this
   silently.
3. **The scope decision, as one flag each.** `EXPERIENCE_BAR` (default off) and
   `_AGENCY_EMPLOYER`. `_JUNIOR` splits into `_NOT_A_JOB` (still rejects) and `_EARLY_CAREER`
   (no longer does) and survives as their union because `pipeline/rolecard.py` imports it for
   the card's chip. `LLM_RULES` is now built by `_rules(bar)` and has four conditions.
4. **The employer normalisation.** `_norm_company` folds legal-form suffixes out of the key.
   Measured over the 969 active names: **12 keys change, exactly 2 pairs merge**
   (`Tenengroup`/`Tenengroup Ltd.`, `Nexar`/`Nexar Inc.`), both duplicate rows, **0 false
   collisions**. Descriptive words (`group`, `holdings`) deliberately not stripped.
5. **The shared-description guard.** A second, differently-titled role at one employer
   arriving with byte-identical text is judged **bare**, counted as `shared_text` and alarmed.
   Six companies in the cache store one careers page as every posting's description (Get SAT:
   10 postings, one 4,000-char blob). A bandage — the *first* role still gets judged on the
   page — and the real fix is `370@jd-text`.
6. **A zero explains itself.** `summary()` now prints `0 calls: all N residue roles served
   from cache` / `no role reached the tier`.

### The measurement that changed a change

Deleting the seniority test from `_sig_accept_nollm` outright moved **20 of the golden
fixture's 252 title-only rows** from reject to accept — `analytics ai engineer`,
`מהנדס/ת נתונים` (a data engineer), `people operations & analytics` — because with no
description `_DATA_ANCHOR` matches the word "data" in the title and nothing is left to
disagree. That rule runs **only when the LLM is unavailable**, i.e. exactly when nobody is
watching. So the rule became "less seniority evidence means **more** description evidence": a
non-senior signal title must show `_DESC_ANALYTICS` in its DESCRIPTION. Fixture movement
after that: **0 of 252**. The vocabulary is provably untouched.

## The precision gap this measurement exposed

`EPAM Systems, Inc. | Managing Principal / Senior Director, Data Analytics Consulting` is on
the board on the `strong` + `senior` keyword shortcut, and the seam — asked directly —
answered **NO**: *"a senior consulting/leadership and sales role (managing engagements,
selling, executive advisory) at a consulting firm, not a hands-on data analyst role"*. The
shortcut is by design and documented, and one instance is not a rate. Filed as
`373@classifier` **with the command that would measure it** rather than acted on, because
routing every strong+senior title to the tier is a real spend increase.

## The adversarial wave, and what it cost me

Three Opus attackers, read-only, pointed at a throwaway copy of the tree — never at the
worktree, because one of them ran `git checkout --` in another lane's yesterday and destroyed
uncommitted work. **Every defect below passed the suite as it stood.**

### The measurement attacker — the conclusion held, the evidence did not

Confirmed the three-run story from the workflow (`daily-digest.yml:235` is the only place that
commit message is emitted) and produced the per-run cache split that is now the proof. Broke
three things I had asserted: `digests/latest.md` is byte-identical at all three commits and
describes run **one**, so citing it at the third read as the opposite of what it says; "32
calls" is a floor because failed and quarantined verdicts write no row; and
`llm_failed_fallback == 0` is *unreachable by construction* when `attempts == 0`, so it was a
tautology dressed as corroboration. It also caught the omission that matters most for an
honest record: **both later runs are recorded `status: failure`**. All four corrections are in
the section above.

### The silent-exclusion attacker — three defects that lose a real role

| # | defect | what it cost | fixed |
|---|---|---|---|
| 1 | **the drain re-judged a JD-backed verdict on a bare title** — the exact invariant the `\|jd`/`\|bare` split exists for. Reproduced: a superseded `\|jd` ACCEPT re-judged on today's empty description became a cached `\|bare` REJECT, and an exact `\|bare` hit short-circuits before the suffix lookup, so the good evidence is never consulted again | **every one of the 321 `\|jd` rows**, on the first morning after the contract changed | `drainable` now also requires `has_text or not prior[1]` |
| 2 | a verdict judged on **another role's** page blob was cached; which of two roles keeps the text is decided by ATS listing order, and the loser's `\|bare` verdict is served for as long as the blob persists | a coin toss made permanent | a degraded verdict is judged but **not staged** |
| 3 | `has_text` (`len >= 300`) stopped agreeing with `jdfill.looks_like_jd` on 2026-08-28, so a verdict made on a nav bar is cached under `\|jd` — a terminal state | 10 of the 70 open roles carry exactly that text | same fix as 2 |
| 5 | the re-judge budget was charged **before** the call, so a run of timeouts reported "3 re-judged" having bought nothing | the mail lied and the drain stalled | charged on delivery |
| 8 | `EXPERIENCE_BAR` could be half-applied — the deterministic layer flips while the rules sent to the model and the CONTRACT do not | a spec nobody is running, answered in schema | `set_experience_bar()` moves all three |

It also checked and cleared three things I would otherwise have had to: the `_JUNIOR` union is
exactly equivalent to the regex it replaced (174 brute-forced combinations, 0 differences),
`_relevance`'s new default `company_l=""` cannot change what descriptions get fetched, and
`_norm_company` creates no new cross-employer key.

### The cache-migration attacker — the doc that would have destroyed the cache

The one to read twice: **`docs/BACKLOG.md` 116's purge command,
`DELETE FROM llm_cache WHERE title_key NOT LIKE 'v2|%'`, now deletes exactly the wrong half** —
every current-contract verdict, including the ones the run just paid for, keeping only the
superseded rows. Rewritten, with the reason, and the count one-liner in §7b fixed with it.
Also confirmed and fixed: `quarantined_keys()` withheld the drain's verdicts along with the
bare→jd cohort (**780 calls over seven mornings where 341 were needed**, and 24 re-bought every
morning at steady state); `_norm_company`'s trailing-punctuation strip ran on names the legal
suffix never matched, orphaning an ACCEPT (`hila & co.`); and `_versioned` matched the `v2`/`v3.`
prefixes by name, making the *next* bump a 100 % cliff. Its drain simulation is what the
prediction now rests on.

**Accepted and documented rather than fixed**, with the reason:

- `max(older)` picks among several superseded contracts by SHA-1, not by recency — `updated`
  holds the right answer and `store.load_llm_cache` discards it. Only bites with two or more
  superseded contracts at once, and the drain clears them in ~6 mornings. `store.py` is not
  this lane's file.
- `CONTRACT` hashes the model **alias** (`sonnet`), so a re-pointed alias does not re-judge.
  The `model drift` alarm covers the detectable half.
- The cache grows and nothing purges it: 593 → ~934 after the drain, ~35 new rows a day.
  That is `116@classifier`, now with a command that will not destroy anything.
- The golden fixture has **zero junior rows**, so it could not have caught the experience-bar
  change in either direction. `test_an_internship_is_not_a_job_but_a_junior_analyst_is` is the
  guard for that, not `titles.json`.

### Wave 2 — are the guards real?

A confirmer mutation-tested every new guard and independently re-derived every headline
number. **12 of 14 mutations were caught**; B1–B7 all CONFIRMED (65 new boards / 423 postings;
`strong 4 · signal 18` with the employer and `strong 6 · signal 16` without; 1/401 = 0.249 %;
3 YES of 22; 7 merged name pairs, all one employer; 7 orphaned rows, none an accept; 0 golden
movement).

Of the two that escaped, one was an off-target mutation (a STRONG title beats `_HARD_EXCLUDE`
by design, so `signal` is the correct answer and green was right — proved with two
harm-equivalent mutations that both fail the test). **The other was a fair hit: one of my
assertions was decorative.** `assert not _NOT_A_JOB.search(title)` is unfalsifiable in the
weakening direction — gut the pattern and it passes trivially — so it could only ever catch
someone *broadening* it. It now asserts the outcome the docstring promises (the role reaches
the tier) plus a positive control, and I re-ran the mutation to confirm the test fails where
it used to pass.

Two incidental facts it turned up: **11 boards present in the baseline are gone from master**,
so the cache grew by a net 54 while 65 are new; and 14 of the 247 "legacy" cache rows are
malformed rather than legacy (12 one-part, 2 three-part) and are unreachable dead weight —
`116@classifier`.

## Verification

| gate | before (origin/master `6c2c6db`) | after |
|---|---|---|
| `python -m pytest` | 1142 passed, 11 skipped, **0 failed** | **1166 passed**, 11 skipped, **0 failed** |
| `python check_invariants.py` | exit 0 (1466 rows, 969 active) | exit 0, unchanged |
| `python docs/check_docs.py` | 0 errors, 6 warnings | 0 errors, 6 warnings |

`tests/rehearse_classifier.py` (fake CLI, scratch DB, zero spend) — `yes`, `fail`, `nollm`,
`all_no`: every check PASS, including *argv is the pinned seam (tools off, json, schema, THE
FULL rules, no session)*, *cwd is not the repo* and *git status unchanged*. `all_no` needs ≥10
companies to reach the quarantine floor; with `--only "Fiverr,Wix"` it fails for that reason
and not a regression.

**A non-zero call count on the same input**, which is what the finding asked for:

```
classify: 46 judged = keyword 45 + llm 1 (1 yes) + cache 0 + failed 0 + skipped 0;
  failed calls 0; attempts 1 in 0.0 min, rejudged 1 (flipped +0/-0);
  model claude-sonnet-5 x1; breaker closed;
  contract v3.a517bb77 re-judged 1/cap 60, served stale 0
```

### The prediction, and why it is a number rather than a hope

`HANDOFF.md`'s morning check for 2026-08-29 says `LLM calls this run` **>= 60** and the board
moves 72 -> 74-80. The call count is not an estimate: replaying the real 593-row cache against
the 1,607 Israel postings of the SCRAPE tier alone, with a fake seam and zero spend, gives

```
classify: 1607 judged = keyword 1539 + llm 59 + cache 9; attempts 59; rejudged 54
```

and the full digest carries ~3.7x that many Israel-matched postings (6,022 on 2026-08-28), so
the 60-call drain cap binds and fresh roles are added on top. **0, or anything under 60,
falsifies the contract key.** The board band is softer: +`mećkano` and +Ashley Digital are
measured YES, -`מטריקס` BI analyst is the agency decision, and ~3 more come from flips among
the 60 re-judged (the 22-role sample flipped 1 in 19 on the experience bar). A cache-migration
attacker simulated the whole drain at **6 mornings / 341 calls** at one run a day, or 3
mornings if the day has three runs.

## What I spent

- **`CLAUDE_CODE_OAUTH_TOKEN`**: **~440 sonnet calls** — 401 for the title-gate measurement,
  22 for the regression set, 1 smoke test, ~15 across four rehearsals (those used the *fake*
  CLI, so 0 real), and the scoped verification runs. All through `pipeline/llm.py` with
  `--tools ""`, no web search, scratch cwd.
- **Bright Data: 0** (`JD_BD=0` on every local run). **SerpApi: 0.** **Actions minutes: 0** —
  no dispatches; the crons run on their own.

## What I did NOT finish

- `369@docs`+`render` — the product still calls itself "experienced (≈3+ yrs)" in
  `README.md`, `CLAUDE.md`, `ARCHITECTURE.md` §0 and the digest's own H1. My change makes
  those untrue. **Do this before the next digest.** Not edited here because `docs` owns three
  of them and `render` owns `digest.py`, and `docs` was live the same afternoon.
- `370@jd-text` — one careers page stored as every posting's description; my guard only stops
  the *second* role being judged on it.
- `371@registry` — the two duplicate active rows are still both scanned.
- `372@infra` — the stdout one-liner still prints a bare `0 LLM calls`; the one-line fix is
  in the item.
- `373@classifier` — the strong+senior shortcut is unmeasured. `116@classifier` (purging the
  247 legacy rows) is untouched and now matters more, since superseded `v2|` rows accumulate
  beside the new ones and nothing removes either.
- `360@docs` — I date-stamped §7b's `862 companies`; L2777 is `company-intel`'s and is not.
