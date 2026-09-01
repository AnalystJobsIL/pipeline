# 2026-09-01 — classifier: adjudicating the dataset audit, and the three boundaries under it

Lane `classifier` (`ARCHITECTURE.md` §7b). One commit. **36 LLM calls, 0 Bright Data
credits.** Cross-lane: one kwarg at an existing call site in `pipeline/run.py` (`infra`), one
new read method in `pipeline/store.py` (shared plumbing), 21 appended + 1 deleted line in
`cloud_state/roles_retractions.jsonl` (`roles`' hand-curated input, the sanctioned channel;
the 08-31 precedent wrote 14 of its 17 lines from this lane).

The operator's row-by-row audit of the published dataset returned **57 findings** — 24 OUT,
27 BORDERLINE, 1 IN, 5 REINSTATE?, plus Minute Media's recorded reject it judged IN. The
audit is one reading, not truth. Every finding is adjudicated below: agreed and recorded, or
refuted with the rule.

## 1. The morning check, answered first — because it is the evidence base

Run **33494404810** (`schedule`, headSha `3d76fcd`, 09:51Z, conclusion `success`).

| the 09-01 prediction | measured | verdict |
|---|---|---|
| published `roles.csv` empty `class_decision` = 0 | **0 of 157** | **PASS** |
| ~153 rows | **157** | PASS (the forecast was made before that morning's intake) |
| log carries `backfill: 0 verdict-less` | `backfill: 0 verdict-less record(s), 0 judged … 0 held` | **PASS** |
| `classify:` names `v3.7cb6831f` | `contract v3.7cb6831f re-judged 242/cap 250 + 97 stale-yes/cap 150, served stale 66 (13 unreachable without a description)` | **PASS** |
| a one-way `drain moved` alarm is EXPECTED back | **did not fire**: the drain moved `+5/-8` — two-directional | **PASS, and better than predicted** |

The 08-31 note said the one-directional alarm's *absence* would be the surprise. It is
absent because the drain's second morning moves verdicts both ways once the easy cohort is
drained; 339 re-judged, 13 moved. The 14 retraction lines that lane wrote were applied by
this run (withdrawn 3 → 18, `retracted_on` stamped), which is what made the audit's
REINSTATE? findings cost a real lift rather than a line deletion.

**Two counters, not one, and they must not be added.** `re-judged 242/cap 250 + 97
stale-yes` are the DRAIN's (339); `rejudged 352 (flipped +5/-8)` is the seam's own
re-judgement total and its GLOBAL flip direction. The one-directional alarm reads neither
of those: it fires on `min(drain_to_yes, drain_to_no) == 0` over the drain cohort alone.
So its silence means the drain moved verdicts BOTH ways or moved none — the log does not
say which, and `+5/-8` cannot decide it. An adversarial read caught this session claiming
it could.

## 2. The defect that would have detonated on my own bump

**The lane's number was wrong by 2.8×, and so was production.** `Classifier._lookup`
resolved a job with several superseded verdicts by `older[max(older)]` — a string comparison
over hex digests, under a comment reading *"the newest scheme wins"*. The live lineage by
judgment date is `v2` (08-25) < `v3.a517bb77` (08-28) < `v3.da2cb878` (08-30) <
`v3.7cb6831f` (09-01), and **`v3.7cb6831f` sorts third**.

It was dormant because the current contract is answered by an exact key one branch above and
never enters `older`. **My bump retires it, which is what detonates it**: measured on the
committed 09-01 cache, **336 jobs would have served the older verdict, and for 12 of them the
two verdicts disagree** — a dozen roles silently reverting to a pre-08-31-scope answer until
the drain re-reached them. The new contract `v3.0f84ab84` sorts lower still.

The same bug had a second home in `tools/measure_scope_rule.py`'s `prior_for`, under a
docstring claiming it mirrored production, and a third in `docs/AGENT_BRIEF.md`'s own
re-derive command for this lane's queue — which is why that cell read **537 of 561**
superseded on a morning whose true figure was **189 of 561**. All three fixed; the brief's
cell now carries the corrected one-liner and both readings.

Ordering is now by the `updated` column (`store.load_llm_cache_dates` → `cache_dates`), with
the prefix kept as a deterministic tie-break so a cache with no dates behaves exactly as
before. Two tests, both written red first and **both verified failing on the un-fixed tree**:
`test_the_stalest_of_several_superseded_verdicts_never_outranks_the_newest` and
`test_the_classifier_is_given_the_judgment_dates_the_store_keeps` — the second exists because
the first passes on a tree where `run.py` never hands the dates over, which is the
cannot-fail shape `guard-kill` caught this lane writing on 08-31. Filed as `541` with the
residual risk: `updated` is only meaningful while `save_llm_cache` keeps writing rows only
when new or changed, and nothing asserts that.

## 3. The three boundaries

Full records, each with worked examples from the stored JDs and its own rejected
alternatives:

* `docs/decisions/2026-09-01-analytics-engineer-boundary.md` — **closes `532`**
* `docs/decisions/2026-09-01-the-posting-must-describe-a-workplace.md`
* `docs/decisions/2026-09-01-execution-is-not-an-analysis-output.md` — **closes `531`**

One contract bump for all four changes (the three boundaries plus `531`'s clause):
**`v3.7cb6831f` → `v3.0f84ab84`**.

**What each is, in one line.** (a) *Who consumes the deliverable*: a reporting layer that
business, commercial or product decision-makers consume makes a role IN even when the same
person builds the ETL beneath it; it is OUT when the delivered thing ends at datasets or
pipelines consumed by engineers, researchers or product features. (b) *Does the posting
describe a workplace at all*: a requisition number, an unnamed client and a client-industry
ask, against a text that never once describes the advertiser's own product, team or systems.
(c) *Analysis that steers your own execution is not an output*: whoever runs the campaigns is
running campaigns, however many numbers they read.

**An adversarial read killed two drafts before they shipped.** The first drew (a) so that
Central Bottling was IN and Ecoppia OUT — and the two JDs are the same role, so no sentence
separates them. They land **together, IN**, and the audit's Ecoppia finding is refuted. The
first draft of (b) said the burden flips *at a consultancy*, which asks the model for a fact
it is never sent (the seam receives title, company, location, description — not a
firmographic record); it is now written entirely on textual tells. A first draft of (c) made
"data analysis — an advantage" decisive on its own, which measured against the audit's own
borderline set would have taken Migdal, Paz, CloudHiro and withfaye — four roles with a real
reporting deliverable — off the board; it is corroboration, not a test.

## 4. Measured before shipping: 36 calls, three committed artifacts

`tests/fixtures/classifier/2026-09-01-boundaries.json` (24 rows),
`tests/fixtures/classifier/2026-09-01-boundaries-b.json` (8) and
`tests/fixtures/classifier/2026-09-01-gate-false-negatives.json` (4, §8). Every call
through the production seam, `sonnet`, one per posting; the "before" leg is the verdict
deciding each row today, read by production's own precedence.

**3 NO→YES · 9 YES→NO · 17 held · 3 with no prior verdict.** Every NO→YES is a boundary working
(Central Bottling, Ecoppia, SuperPlay). No quantitative analyst role moved to NO for its
domain, and **0 of 4 fixed-term roles was lost for being temporary** — Check Point, Taboola
News and WalkMe all YES, AppsFlyer NO on the FP&A ground alone, which is exactly the
measurement `531` asked for.

**`tools/measure_scope_rule.py` gained `--source ledger` + `--only`, and it had to.** The
existing sample reads the two committed caches, and **a closed role is in neither** — its
text lives in `roles_text.jsonl`. Of the rows this audit named, 0 of Guardio's, Mobileye's,
NVIDIA's or Global-e's postings carry ≥300 characters in those caches, so the tool as it
stood would have returned a near-empty sample and called it a measurement. The golden fixture
was run as a **negative control only** and is named as one: it asserts the title-only keyword
tier, which a change to `LLM_RULES` cannot move by construction.

**Two seam verdicts disagreed with my adjudication and I adjudicated both** (the pre-committed
abort rule was >3 disagreements ⇒ stop and file):

* `Parametrix | Technical Data Analyst` — seam YES, I had it OUT. Its text is cut mid-word at
  the 1,800-char capture cap. **Reinstated**; see §6.
* `Zipher | Data Scientist` — seam YES, an evidence pass had it OUT and called it its own
  least confident call. "Build dashboards, reports, and internal tools that help teams
  understand product performance" is condition (1). The accept **stands**.

## 5. The 57, adjudicated

**22 confirmed OUT, 21 of them carrying a retraction line** (open or closed alike; see §7
for why open rows need one too): d-fend, Mobileye Forecast Analyst, Mobileye Business
Analyst, Chainalysis, LTX, Bylith, Global-e Payment Operations, Alma Lasers, Hila, Matrix,
Peak Innovation, EPAM, INGIMA, entrypoint, Compie, G-Stat, TLVTech, Aidoc, Similarweb,
Kibeeri, Natural Intelligence.

**The 22nd — `Percepto | Data Insights Operations` — is adjudicated OUT and is NOT
withdrawn, and that is the most important line in this note.** Its line was written, and an
adversarial wave caught before the push that the url matches **two** records:
`Retractions.match_all` matches a record by its own url *and by any `seen_id` that is a
url*, and `percepto|senior product analyst` carries
`scrape:…/data-insights-operations-ff-c6f/` as a stray `seen_id` while its own url is
`https://percepto.co/careers/`. That second record is `open`, `accept`, on the board, and
genuinely in scope — *"dashboards, reporting, and customer usage analysis at the hiring
company itself"*. The line would have deleted a real analyst role from the board, the mail
and the dataset, and published it in `meta.removed[]` under a reason describing a different
posting. Keying by `role_id` does not escape it — `bind()` puts the record's own url back.
Measured: **1 of 39 lines over-matched, 0 after the drop**. Filed as `545@roles` with both
fixes. I had checked for over-withdrawal earlier in the session and got a clean answer,
because I compared url keys against the ledger myself instead of calling `match_all` — the
predicate that actually decides. Checking a belt with a hand-rolled copy of it is not
checking it.

**7 findings REFUTED — the audit's reading did not survive the JD:**

| row | the audit said | the rule that refutes it |
|---|---|---|
| `Ecoppia \| Senior BI Developer` | OUT, core data engineering | boundary (a): "Analyze data and create business insights" + Tableau reporting for "business stakeholders across the company". Seam agrees, NO→YES |
| `SuperPlay \| Head of BI` | OUT, management not analysis | condition (1) says analytics leadership counts; the leader is accountable for the analytical OUTPUT. Seam agrees, NO→YES |
| `Guardio \| Director of Data` | borderline, management | same line; "Provide insights and analytics on … business and product metrics" |
| `Play Perfect \| Fraud Analyst` | OUT, develops fraud models | the fraud DOMAIN is in scope since 08-31; model work is one bullet of five analysis bullets. The 08-30 record that named it a reject also recorded that it appeared in only one of two passes — "a genuine borderline". Seam: YES |
| `Zipher \| Senior Data Analyst` | OUT, production pipelines | "Own end-to-end analytics for core product areas"; KPIs and dashboards "used by engineering, product, and executives" |
| `Central Bottling \| BI Developer 17621` | borderline | boundary (a), IN — its recorded `reject` is now wrong and frozen (`544`) |
| `Minute Media \| Data Scientist` | REINSTATE, condition (1) | seam NO under the new rules: "building ML models (pricing optimization, bandits, regression) and an experimentation platform". Its honest `reject` stands and the row stays published |

**7 DEFERRED, `desc_mismatch=true`** — TransUnion, Diageo, Prisma, TechBiz, Holisto, Gamida,
Ballerine. Not adjudicated, deliberately: their stored text is another posting's, jd-text is
re-fetching it in a parallel session, and **a retraction is permanent while a verdict is
provisional**. They re-judge themselves under `v3.0f84ab84` the day their text lands.

**3 not in the ledger** — Clal (`אנליסט/ית אשראי`), dt, Bank Discount. They are board-side
rows with no role record, so there is nothing in the dataset to act on; their cached verdicts
re-judge under the new contract.

**The rest keep their current verdict** and are named in the boundary records as worked
examples: Cato Networks, Edikted, Migdal, Paz-yellow, withfaye, CloudHiro, Sunflower ×2,
NVIDIA, Oak ×2, Team8/Briya, Mobileye Experienced Data Analyst (published reject), Questar
Auto (published reject).

## 6. The five reinstatement candidates: four refuted, one lifted

All five had been fully withdrawn by the 09-01 digest (`retracted_on` stamped), so a
reinstatement now costs a real lift with a loud alarm, not a quiet line deletion.

* **`Parametrix | Technical Data Analyst` — WITHDRAWAL LIFTED**, its line deleted in this
  commit. It is the only one. Its text is cut mid-word at the capture cap so the
  qualifications were never read; the seam, re-reading that same partial text under the new
  rules, says YES on the dashboards it builds "to help the Product and Sales teams see global
  cloud stability and exposure at a glance". Everywhere else in this seam a verdict on partial
  text is provisional and re-judged when the text arrives — while a retraction is permanent
  and nothing re-checks it. That asymmetry is the whole argument, and it is the 08-31
  record's own rule, which lifted two rows for exactly this.

  **"Lifted" is the honest word and "reinstated" was not.** The lift returns the ROW; it does
  not overturn the verdict. Nothing rewrites `rec["class"]` for a closed role — the live path
  only stamps roles in `merged`, and the backfill fills empty cells only — so Parametrix comes
  back into `roles.csv` still reading `class_decision=reject`, under a contract this commit
  retires. An adversarial wave caught the overclaim before the push. `Central Bottling | BI
  Developer 17621`, the NO→YES the analytics-engineer record was drawn for, is frozen exactly
  the same way and has no line to lift at all — which is the clearest argument in the tree for
  `544@roles`.
* **Guardio ×2 — REFUTED.** "Building the data pipelines that power our cybersecurity data
  infrastructure"; consumers are "analysts, researchers and security experts" and product
  features; **zero dashboards in 3,300 characters**. Boundary (a) puts them out. (They are
  one Comeet posting under two titles — 3,300 and 3,299 bytes, identical but for the title
  word — so both `role_id`s keep a line.)
* **Global-e Chargeback — REFUTED.** The audit is right that the domain cannot decide, and
  the domain is not the ground: "Review and represent chargebacks and retrieval requests",
  SQL "Advantage" — dispute case-handling, boundary (c).
* **NoTraffic — REFUTED.** "Own commission administration, calculations and payout
  validation" plus HRIS ownership. Compensation is in scope as a domain; policy and payout
  execution is not an analysis output.

## 7. Why a confirmed OUT needs a human line even when the seam already said NO

An adversarial review of the plan found this and it changed the shape of the session.
`rec["class"]` has one writer, fed from `merged`, and `merged` is the **accepted** output of
`classify_grouped` — so a role the drain flips to reject is never in it. The cell keeps
`accept`, the row drops off the board, and it closes as a false accept the dataset publishes
for the whole 90-day window.

**Three rows in the file prove it today.** `Percepto` was measured YES→NO on 2026-08-30.
`Chainalysis` was moved to NO by the 08-31 domain ruling, whose own text says "the drain
re-judges it on the next run — the mechanism working as designed"; the cache moved and the
cell did not. `EPAM` carries a stale keyword-tier accept from before descriptions were read.
All three still read `accept` this morning. So the plan's original split — retraction lines
for closed rows, "let the drain handle" the open ones — was incoherent, and all 22 get a
line. Filed as **`543@roles`** with the ~6-line diff (`classify_grouped` already computes
`m["_class"]` on a reject and merely drops it).

**The 14 reason strings from 08-31 were rewritten** in the same commit: each began "re-judged
OUT OF SCOPE under contract `v3.7cb6831f`", a hash this commit retires, and those strings are
published to downloaders in `meta.removed[].reason`. Today's 22 cite the adjudication and its
decision record instead. Matching is by url, so the reason text was free to edit.

## 7b. The count tomorrow depends on another lane, and it was agreed live

157 − 22 + 1 = **136** if this commit lands alone. The `roles` session running the same
afternoon confirmed by message that its own change takes the file **157 → 154** (two pending
weak-text rows excluded — Madanes and בנק דיסקונט — plus the Nestlé/אסם duplicate folded), so
if both land in the same digest the answer is **133**. None of its three rows is one of my 22,
which is why the two changes simply add. The 09-02 morning check states both numbers rather
than one, because a check that is wrong when a sibling lane ships is a check that teaches the
next reader to distrust the table.

That lane also answered the ledger-cell question directly: **file the diff, do not hand-edit**
(`544`), it is not taking a reconcile-from-cache pass tonight, and it asked that any
reinstated row be NAMED in the handoff line so its next session can check that cell —
Parametrix is named there. Two of my findings are now its items: the Oak pair will NOT fold
(3,735 vs 3,685 characters, and its arm folds only byte-identical text — deliberately, because
the Mobileye pair differs by 8 characters and must stay two roles), and the sharper problem it
had not seen is that `_twin_winner_at_rest` elects open over closed, so folding Oak would keep
the weaker Indeed source over the canonical ATS one.

## 7c. What the two adversarial waves found in this diff

Both were pointed at the staged diff. Between them, **eleven** real defects; the two that
would have reached production are §5's Percepto over-match and the count corrections below.

| what | why it mattered |
|---|---|
| **One line withdrew two roles** | §5. An open, in-scope, published role, deleted under another posting's reason |
| **"1 reinstated" was half true** | A lift returns the ROW, not a verdict: `rec["class"]` is never rewritten for a closed role, so Parametrix returns reading `reject` — and Central Bottling, the headline NO→YES, is frozen the same way with no line to lift. Both now said plainly; `544` |
| The `roles withdrawn` alarm will name **34**, not 21 | `_record_run` appends on a *reason change* too, and this commit rewrites 13 reasons. The morning check would have failed on its own arithmetic |
| I claimed a cause the code rules out | The one-way drain alarm reads `min(drain_to_yes, drain_to_no)`; I explained its silence with the seam's GLOBAL `flipped +5/-8`, a different counter |
| A record cited a fixture for rows it does not contain | The workplace record said "eight of these rows are in the 24-row pass"; six are. Matrix, Peak Innovation and Oak were adjudicated, not measured — now labelled as such |
| `--source ledger` unscoped would buy **203** calls | It applies no text filter and `--dry-run` is off by default. Now it demands `--only` or `--limit` |
| ...and printed ">= 300 chars of text" for a source that filters nothing | The tool's own output asserting a filter it does not apply |
| `544` misstated its own mechanism | "`class` is fill-once" is false for the live path, which overwrites unconditionally; a verdict freezes because a CLOSED role never re-enters `merged` |
| `544` mixed two states of the file | numerator from today's 157 rows, denominator from tomorrow's 136 |
| `543` understated its blast radius | 12 published rows already show cached-NO against a published `accept`, not the 3 that name it |
| 32 calls / two artifacts | stale after the gate work made it 36 / three |

Rejected from their findings, with the reason: **the condition-5 corroboration clause stays
as written.** One wave measured that "an advantage"/"יתרון" appears in 45 % of the prompt
slices this seam sends and argued the clause is keyed on a near-half base rate. That is a
real measurement and the right thing to have raised — but the clause cannot demote on its
own: it reads *"where the responsibilities genuinely split ... treat data analysis offered
only as 'an advantage' ... as corroboration that it is the secondary half"*, so it only
breaks a tie the "leads with" test has already found. The measurement to run before
tightening it is a junior/marketing cohort through `--source ledger --only`, which is filed
rather than done, because the four weak-IN rows it would most likely move (Migdal, Paz,
CloudHiro, withfaye) all held YES in this session's own pass.

## 8. What I did NOT do, and why

* **No hand-edit of `cloud_state/roles.jsonl`.** It is `roles`' file, single-writer
  `daily-digest` with an `s_ours` merge strategy — a hand-edit pushed mid-digest is discarded
  silently, with no conflict and no alarm — and a `roles` session was live all afternoon. The
  two rows that want a cell rewritten (`Central Bottling`, and `Parametrix` if it returns
  `closed` rather than `open`) are filed as `544` and messaged to that lane directly.
* **The title gate is untouched** (`542`) — but no longer for want of evidence. Late in the
  session the orchestrator's two gate audits handed over 4 confirmed misses that are alive
  and already carry cached text; judged through the seam (4 calls, artifact
  `tests/fixtures/classifier/2026-09-01-gate-false-negatives.json`), **3 of 4 are YES**:
  Calculum (finance hard-exclude — the measured false negative `529` asks for), IAI and Zoll
  Medical (titles with no analytics signal at all, which **no demotion reaches**). Elbit is a
  correct reject. Both classes are written into `542` separately so nobody cites this as
  proof that the cheap fix covers them; it covers one of the three. Not fixed tonight
  because a gate change needs the 252-row fixture and a priced LLM volume, and this commit
  already carries a contract bump and 22 withdrawals. Boundary (a) admits the hybrid the industry calls
  an "analytics engineer" and `_relevance("senior analytics engineer")` is `excluded` with no
  appeal — the same shape as `529` for the domain rule, and stated in the record rather than
  hidden. Two gate audits the same day put its false-negative rate at ~0.35 %; only **3 live
  Israeli titles** are affected and **2 of the 4 confirmed misses no demotion can reach**,
  their titles carrying no signal at all.
* **`_AGENCY_EMPLOYER` is not extended.** All five new consultancy names already reach the
  LLM (`strong` + seniority `unknown`), so a demotion buys no routing — and that list is
  excluded from the no-LLM rescue, so a wrong entry becomes a deterministic reject on a
  breaker-open morning. The 08-28 record's "a wrong name costs one call, never a role" does
  not transfer.
* **`321@registry` is untouched**: whether these consultancies should be `active` rows is the
  registry's call on all thirteen at once, as the 08-27 record measured.

## 9. Three CI reds, none of them this diff — and my first diagnosis of one was wrong

`tests.yml` on this commit is **run 33514763993, 10 of 13 jobs `success`**. Written out
because "10/13" must not be read as three defects in one commit:

| red | what it is |
|---|---|
| `rehearse (worst, seed 1)` | **inherited** from `09fdb95`; registry's `550`. Below |
| `mutation-gate (2)` | **rc 137, wall time, 0 SURVIVED records** — every per-record line reads `killed` |
| `mutation-gate (4)` | the same |

**The mutation gate failed on a budget, not on a mutant, and the numbers say so.** Both
shards were killed at the 40-minute `timeout`, and neither printed a single SURVIVED record.
Measured against the last green run of the same catalogue (33448520621), the shards were
already at 88–96 % of budget before this commit existed:

| shard | 33448520621 (green) | 33514763993 (this) |
|---|---|---|
| 0 | 35.0 min | 38.4 |
| 1 | 38.3 | 32.0 |
| 2 | 37.4 | **41.1 FAIL** |
| 3 | 35.9 | 39.5 |
| 4 | 36.9 | **41.4 FAIL** |

Shard 1 got *faster* (38.3 → 32.0), which is the signature of runner variance rather than a
workload change. This diff adds 2 tests to the per-record subsets (`subset 1236`,
`subset 57`) — ~0.16 % more tests on the large ones, not two minutes — so I do not claim a
zero contribution, only that the cliff pre-dates it. `SHARDS = 5` against a catalogue of 260
growing records is the number to move, and the workflow's own error text says so ("add a
matrix entry and bump SHARDS rather than minutes"). It is `infra`'s file and its 2026-09-01
morning-check row already answers FAIL on exactly this; the timings above were sent to that
lane. **Twice in two days a lane's push has been marked red by a budget rather than a
defect** (the 08-31 classifier session hit shard 2, rc 137, zero SURVIVED, on run
33410420520), and the cost is that "the mutation gate is red" stops meaning "someone let a
mutant live".

### The rehearsal red

`rehearse (worst, seed 1)` is **not caused by this push**, and I proved that rather than
asserting it: the same rehearsal run at my commit's PARENT in a separate worktree fails
byte-identically
(`FAIL night 1: pool listing_hunt (19:00 daily) lost 1 rows it should keep: ['Synopsys
Israel']`). Bisected: `c3f9903` (the last CI-green commit) passes; `09fdb95`
— *listing-hunt 2026-09-01, `[skip ci]`* — fails, and every commit after it does too.

**My causal explanation was wrong, and the registry lane corrected it.** I read the
`Synopsys Israel` notes diff, saw `zero-confirm 2026-08-29 … needs re-resolution` gone, and
called it the append-log violation of `CLAUDE.md` rule 3. It is not. Replayed through the
real helper, `notes.replace_own` evicted that segment because the incoming one did not fit
under the 220-char cap and it was the oldest UNPROTECTED segment — the append-log doing
exactly what it documents. And the eviction is not why the row leaves the pool: the
surviving cell still carries `host documented`, so `HUNT_POOL.search(cell)` is **True**
(verified). The row leaves because `triage_dark` stamps it `page-empty` and
`listing_hunt.in_hunt_pool` ends with `and not _triaged_page_empty(...)` — a deliberate
hand-off, whose comment says "triage proved page-empty rows have a live page with no roles".
`orphans` is 0 on both nights: nothing is unowned.

So the rehearsal is a per-pool check reading a designed hand-off as a loss, its forgiveness
set has no "another pool took ownership tonight" clause, and it is registry's (`550`). I
verified both halves of that correction myself before writing this paragraph, because the
first version of it was confidently wrong in a document — which is the thing this repo
punishes hardest, and I had it staged.

**The meta-hazard is worth more than the bug.** All five 2026-09-01 cron commits carry
`[skip ci]`, so no run judged the data they committed; a guard went red on state that CI
never looked at, and it surfaced only because an unrelated lane pushed. `550` carries it.

## Traps this session hit

* **`docs/backlog.py next` said 534 when I drafted and 541 when I filed** — four other lanes
  filed while this session measured. Two decision records already cited `534`/`535` in prose;
  both were patched before the push. Run `next` immediately before writing the item, not when
  planning it.
* **A Windows console is cp1252** and every one of these JDs may be Hebrew: `PYTHONIOENCODING=utf-8`
  or the read dies mid-print, after the calls are paid.
* **The shared checkout was dirty** with another lane's local `bd_spend.jsonl` and `seen.db`,
  so `git pull --rebase` refused. Neither is mine to stash or discard — this session worked
  from a fresh worktree at `origin/master` instead and left the checkout alone.
* **`Retractions.load` is a classmethod taking a path**, not a constructor taking lines; the
  constructor takes already-parsed entries and will happily accept strings and fail later.
