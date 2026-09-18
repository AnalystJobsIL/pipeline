# 2026-09-18 — classifier: a ruling the seam could not see, and eleven cells nothing could flip back

Lane `classifier` (`ARCHITECTURE.md` §7b). **74 `claude-sonnet-5` calls through
`pipeline/llm.py`, 0 Bright Data credits** (every invocation `JD_BD=0 BD_RUN_CAP=0`, run from
the SHARED checkout — a worktree has no credentials and returns a convincing mass-zero —
while the code and docs were written in a worktree). Planned ≤ 75. Calls: 3 (Jazz under the
live contract) + 20 (one candidate-contract call per row over the contract-bump population) +
4 (the two flips re-read twice more) + 27 (the eleven reject cells) + 14 (the delta audit) +
2 (the Cal gate card) + 4 (the two record-settled rows escalated to a triple).

**Nothing was cached.** Every vote is `Classifier._judge`, which does not write `llm_cache`,
and the harness never opened the store — `cloud_state/seen.db` is byte-identical to
`origin/master` at the end of this session (the 09-13 trap: *opening* the store rewrites it).

Cross-lane, all named: seven lines appended to `cloud_state/roles_retractions.jsonl` (the
sanctioned channel, agreed with the `roles` session by message — they write the mechanism,
this lane writes the lines); two lines in `pipeline/roles.py`'s backfill loop, named to
`roles` before the push.

Every number was read on 2026-09-18 from `origin/master` `a96ee8a`.

## 1. The 09-14 ruling — and why a record alone would have been a hand-drain

The operator ruled on 2026-09-14 that **data-platform leadership is OUT**: a role that leads
data engineers, or owns the data platform, is out even with a BI team under it. The record is
`docs/decisions/2026-09-14-data-platform-leadership.md` (dated to the ruling), and it
supersedes the 2026-09-11 addendum to the analytics-engineer record on exactly one phrase —
"the platform is the means" — where the platform is the person's own stated core.

**The measurement that decided the form.** Under the contract live this morning
(`v3.0f84ab84`) the seam was asked three times about `jazz | senior bi developer` and bought
**YES / YES / YES**, reaching the 09-11 addendum's own reasoning freshly ("Despite building
the data platform, the role's own output includes defining company KPIs and building
executive dashboards"). A ruling the seam cannot see costs a human reading for ever, so the
sentence goes **into condition (2)** and the `CONTRACT` hash moves.

**Measured before it landed**, one production-seam call per row with the candidate sentence
spliced into `LLM_RULES` in-process (nothing written to the tree): every published
BI-developer / Head-of-BI / Head-of-Data / BI-team-lead / analytics-leadership row in the
ledger, plus the two withdrawn anchors the ruling must keep OUT.

| | rows | which |
|---|---|---|
| moved accept → reject | **2** | `jazz\|senior bi developer`, `upwind\|head of data` |
| already OUT, stayed OUT | 2 | `superplay\|head of bi`, `guardio\|senior bi developer` |
| unchanged IN | 16 | Alma, BioCatch, Central Bottling 17621, Clalit 49965, Connecteam, Ecoppia, Insightec, Intelligent Business, Investing, Menora, Nebius ×2, Pagaya, Phoenix Digital Analytics Team Lead, Sunflower BI Developer, Sunflower BI Developer – Payments |

Both flips are nameable and both are the ruling's own arms; each was re-read twice more and
both are **NO/NO/NO** under the candidate contract. `upwind | head of data` was NOT in the
audit's non-IN set — the bump measurement found it, and its text is the operator's sentence
verbatim: *"Lead and develop the BI team, including a team of data engineers and data
analysts"*, *"Build a scalable, reliable data platform"*. Both rows get a retraction line
today; the bump makes the class durable from tonight.

The drain re-supersedes the **882** cells carrying `v3.0f84ab84` at the existing cap of
250 NO + 150 YES a morning — roughly three mornings. **The cap is not raised** (2026-08-30:
an uncapped drain starves the email window).

## 2. The eleven reject cells — the class, and what could reach it

`roles.csv` published **11** closed rows carrying `class_decision=reject` (12 in the ledger;
`madanes insurance agency|manager bi` is the twelfth, outside the 90-day file). The operator's
bar is that a published row is IN under the live contract or EXCLUDED with a counted reason,
and a reject cell is neither.

**What could flip one back: nothing.** `roles.reject_map` stamps the run's NO onto a closed
record (`543`); `_record_run`'s backfill loop refuses any cell that names a contract; and
`class_backfill.candidates` reads only `roles.class_unjudged`. `tools/rejudge_rows.py`'s
docstring said "the next digest stamps the record from the cache it finds" — **false for this
class**, and corrected in this commit.

**Measured**, published records whose stored cell contradicts the live-contract cache row for
the same job: **3 rows contradicted, but only 1 honestly** — `amitim` and `אסם` are contradicted
by a `|bare` row while their own `|jd` row agrees with the cell, and a `|bare` verdict is
provisional by construction. Restricted to `|jd`, the class is exactly **1: Navina**
(`v3.0f84ab84|navina|data researcher|jd => 1`, 2026-09-04, against a cell reading
`reject/keyword` "no analytics signal in title"). That is a `reject_map` artefact, not a seam
NO: `_relevance("data researcher", "navina")` is `none` on the title alone and `signal` with
the record's own 3,087 characters, so the cell was stamped on a morning the run's card had no
text. **The pool is `|jd` only**, and that is the correction the measurement made to the plan.

**The adjudication, three fresh votes each** (one first where a record already settles the
row, escalated on a NO):

| row | fresh votes | verdict |
|---|---|---|
| `amitim pension funds \| data analyst` | YES/YES/YES | **IN** — the cell is a stale `\|jd` NO of 09-06 |
| `clal … \| אנליסט.ית אשראי` | NO/NO/NO | **withdrawn** — credit underwriting on financial statements for a credit committee |
| `glow \| data analyst` | NO/NO/NO | **withdrawn** — "This isn't a traditional BI or Product Analytics role", "Build and modify logic in system components" |
| `migdal \| data analyst` | NO/NO/**YES** | **IN** — a flap keeps, *and* the 09-01 execution record adjudicated this exact posting IN |
| `navina \| data researcher` | YES (+ live `\|jd` YES) | **IN** — the cache-contradicted refill |
| `phoenix financial \| business analyst 50400095` | YES/YES/YES | **IN** |
| `play perfect \| fraud analyst` | NO/**YES/YES** | **IN** — a flap keeps; the domain never decides (08-31) |
| `sunflower \| marketing analyst` | NO/NO/NO | **withdrawn** — leads with managing the campaigns the analysis steers |
| `team8 \| briya- medical data analyst` | NO/NO/NO | **IN** — the documented condition-(4) miss `2026-09-01-the-posting-must-describe-a-workplace.md` names by title; a record that ruled on a tell the seam cannot see overrides three NOs |
| `zipher \| senior data analyst` | NO/NO/NO | **withdrawn** — the 09-13 triple was NO/YES/NO and a flap kept it; a second triple that is unanimous is a stable NO |
| `אסם \| אנליסט/ית בקרת מכירות` | NO/NO/NO | **withdrawn** — leads with budget control and trade-spend management, the named FP&A exclusion |
| `madanes insurance agency \| manager bi` | — | **not adjudicable**: 0 stored characters, every cache row `\|bare`. jd-text's, not this lane's |

**6 IN, 5 withdrawn, 1 undecidable.** The withdrawal rule is the 09-11 one and it was not
bent: a withdrawal needs three fresh NO in one sitting or a documented seam miss, which is
also why a row expected to keep was bought ONE vote first — a single fresh YES makes 3-of-3
impossible and ends the question. That protocol is what kept the pass inside 75 calls.

## 3. The delta audit — 5 OUT and 10 BORDERLINE claims

Auditor claims are claims. **9 kept, 1 withdrawn (Clal, above), 2 held, 1 reversed by the
ruling (Jazz).**

* **Kept on a fresh YES**, the auditor's reading refused: `הראל … | אנליסט.ית תחקור ובקרה`
  (the OUT claim never got a first NO — the seam said YES on 09-16 and again today; the
  registry/roles fold of the Hebrew row into `Harel Insurance & Finance` does not touch the
  verdict), Digital Turbine Senior DS, ONE ZERO Bank Data Analyst, Practical Vision Web
  Analyst ×2, Edikted Retail Analyst Team Lead ("Develop and maintain dashboards and reports
  … to leadership" is the withfaye line that separates it from the sibling withdrawn on
  09-11), Koladin, ONE datAI Incentive & Compensation Analyst.
* **Kept on a flap**: EY `מנתח.ת נתונים סניור` NO/YES/YES, and `datamind bi ai | business
  intelligence developer qlik` **NO/YES/YES** — the plan predicted NO×3 on the Qlik Israel
  precedent and the measurement refused it. The title/body mismatch ("Business Intelligence
  Developer" over a project-manager body) is a jd-text/scraper question, not a scope one.
* **Held, deliberately**: `gamida cell | senior business analyst commercial data analytics`
  stays published — the 09-02 rule forbids a withdrawal on text that is not the row's, and
  566's description arm is silenced by the board's own Kiryat Gat BY DESIGN. jd-text
  re-slices the own posting this batch; the condition-5 line is written then, not before.
  `google israel | research data scientist ii waze` is undecidable on a 573-character
  listing-card stub; its `|jd` verdict is void and the key is forgotten the day jd-text lands
  the posting's own text (`551` b).

## 4. The gate: the "false negative" was not one

The audit read 491 new title-only rejects and called **1** a false negative,
`cal (israel credit cards) | מפתח.ת מודלים`. On the live path it is not a miss at all:

* `_relevance` on the title alone: **`none`**. With the card's own 955 characters:
  **`signal`** — `_desc_appealed` lifts it (phrase "Data Analytics", output "דוחות", tool
  "SQL"; `_DESC_ML` hits once, under the floor of two).
* `python tools/measure_title_gate.py --cache scraped_cache.json --tier passing --dry-run`:
  591 boards, 3,368 postings judged by the gate, **`tier=passing: 168 postings
  {'signal': 130, 'strong': 38}`** — and the card is inside it.
* The seam has therefore already read it and refused it: cached
  `v3.0f84ab84|cal (israel credit cards)|מפתח.ת מודלים|jd => 0` (2026-09-14), plus **NO/NO**
  fresh today ("the role centers on developing and maintaining predictive and decision
  models"). A stable NO on condition (2).

**No vocabulary change.** מודל stays out of `_HEBREW_SIGNAL`: the same measurement shows the
appeal does NOT lift the TASE `כלכלן/ית ליחידת מודלים ונגזרים` card or max's
`מנהל/ת מחלקת סיכוני אשראי, מודלים ואנליזה`, so a stem arm would admit exactly the rows the
auditor itself leans OUT on. The **12** borderline rejects are 0 in scope on their own
reasons, and three of them (`Senior AI Enablement`, `Senior ERP Specialist`, `Senior Product
Designer`) share one byte-identical Total-Rewards body — a scraper misattribution, so no
verdict on them belongs to anyone. That list went to the scraper session.

## 5. The `?` in the unreachable alarm

`classify N superseded verdicts CANNOT be re-judged (not-a-job-url 3, ? 1, wrong-address 1)`
prints every morning. `_jd_why` is stamped only by `jdfill.maybe_fill`'s exits, so a card
jd-fill never attempted carries none and `seniority.py` printed the bare `"?"`. The row is
`v3.0f84ab84|gong|senior data scientist - ai research & reliability|jd` — a LinkedIn
discovery card with 0 characters, no matched row, and Gong's own Greenhouse board does not
list it. The fallback now reads **`no-text-unattempted`** at both sites (the printed line and
the grouped alarm), so no held row is named `?` again. Making jd-fill stamp a reason on every
held card is jd-text's half (their prompt's item 3); this is the name, not the plumbing.

## 5b. Verdicts bought on another posting's text, voided

The `scraper` session's C1 (`2bb1553`) repointed 87 cards whose stored address was a
neighbour's and named five `llm_cache` verdicts judged on a DIFFERENT posting's text. A
verdict on the wrong evidence is not a verdict, and `cache_keys` carries no text hash
(`551` b), so it is served for ever unless the key is deleted under **every** prefix — the
`_versioned` lookup answers a job by its suffix, so deleting only the live-contract row
leaves a superseded one to decide the posting.

**Voided: 13 keys over 4 jobs.** `mer group | data scientist, data & ai` (1 key — the text
is `Tech Lead, Data & AI`'s); `cheq | data & analytics` (1); `legit security | security team
analyst lead` (6, legacy + `v2` + four contracts — Head of Engineering's text); `telus
digital | media search analyst - hebrew (israel)` (5). **Not voided, and named as owners by
the lane that measured them**: `telus digital | online data analyst - israel` and `medison
pharma | senior total rewards analyst` (8 keys between them) — one text under two titles
voids the borrower, never the owner. **0 of the four is a ledger record at all**, so nothing
published moved and no retraction line is owed. Three sibling spellings of the TELUS
media-search job (`fully remote: …`, `remote job: … in israel`, `… (hebrew language) in
israel`) were left alone: scraper named one job, and widening another lane's measurement is
how a void becomes a guess.

## 6. What shipped, and the three shapes it took

**The ruling entered the contract**: the sentence sits inside condition (2) of `LLM_RULES`,
`v3.0f84ab84` -> **`v3.0a439b16`**. The 882 cells under the old hash are superseded from
tonight and the drain re-judges them at the existing 250 NO + 150 YES cap; the cap is NOT
raised.

**`class_backfill.reject_owed`** is the second pool. A `reject` cell is the one verdict a
reader can see the consequence of — since this morning `roles.Ledger._withdraw_rejected`
takes the row out of the dataset on it — so it must be current, and nothing could make it
current. Three arms, all reject-to-accept only and all self-draining:

1. a **written adjudication** (below) — costs no call;
2. the cell names a **retired contract**. This is the arm the plan did not have, and the
   bump is what forced it: a bump supersedes every cached verdict, so the `|jd` arm below
   would have been empty for exactly the mornings the eleven needed it;
3. the **live contract's own `|jd` row** says YES, which is Navina and only Navina.

A *superseded* `|jd` YES is deliberately not an arm: it would re-select all eleven every
morning for ever, because the judge writes `reject` again where it still means it and the
stale YES is still there tomorrow. Arm 2 reaches the same rows exactly once.

**`roles.class_refillable`** replaces three inline copies of "may this cell be refilled"
(`candidates`, `apply_to`, `Ledger._record_run`'s backfill loop) — the three disagreeing is
how the CLI and the in-run hook produced two answers for one role before 09-13. It is
**one-way**: accept-to-reject is refused in every pool by every arm, because the channel for
taking a row out is a url-precise line in `roles_retractions.jsonl`. That is the
`roles.py` edit named to the `roles` session (orchestrator answer 6); it sits in the loop
that already runs BEFORE their sweep, so a cell refilled to `accept` this morning is never
withdrawn the same morning.

**`seniority.ADJUDICATED`** is the shape the plan did not anticipate and the roles
mechanism forced. Two rows — Migdal and Team8/Briya — are IN by a decision record and answer
**NO to the seam every time**: NO/NO/NO fresh for Team8, and the seam cannot apply either
record's ground (that Team8's board carries Briya; that the 09-01 execution record already
read Migdal's split). Until this morning that cost nothing, because a `reject` cell was only
a label. From this morning it deletes the row, so without a reader for the records the next
unattended run would have dropped two rows the operator's own records adjudicated IN, and
the only way back would have been a human re-judging them every morning. It is the
`recruiters._CONFIRMED` shape (2026-09-11), keyed by `role_id`, **accept-only**, every entry
naming a `docs/decisions/` file that must exist, and read at BOTH judging sites so a row that
reopens is not re-rejected by the live path. Three properties, three assertions.

**Not done, and why**: `docs/RUN_LOG.md` carries neither the `backfill:` nor the
`CANNOT be re-judged` line, so the plan's item there was a no-op — the two strings live in
`ARCHITECTURE.md`'s alarm table, and the `no-text-unattempted` name is now in it.

## 7. Green, and where

**Locally, from the worktree rebased onto `origin/master` `267e6ac`**, `python -m pytest`
(not `-q`, and with neither `JD_BD` nor `BD_RUN_CAP` in the environment, which reds paid-rung
tests on their own): **2,066 passed, 13 skipped, 0 failed**. `python check_invariants.py`
`companies.csv OK: 2485 rows, 1430 active, 0 orphans, pool=889`. `python docs/check_docs.py`
**0 errors, 2 warnings over 141 documents** — both inherited (`README.md` and `CLAUDE.md`
carry a `1,000+` floor for `active_rows`, now 1430; the `docs` lane's, and neither file is
this lane's to raise). `python docs/backlog.py check` clean.

`python tools/guard_kill.py --base origin/master`: first reading **KILLS 5, CANNOT-FAIL 2**.
Both CANNOT-FAILs were tests of things that already existed at the base — the decision record
(added in commit A) and the description appeal (unchanged, because the measurement's answer
was that no vocabulary arm is warranted). Each was **folded into a test that kills** rather
than filed: second reading **KILLS 5, CANNOT-FAIL 0**.

`python tools/mutate.py --id <one at a time>` — `--id` is not repeatable, which is worth
knowing before reading a one-line table as four: **all four killed**,
`backfill-ignores-a-reject-cell-under-a-retired-contract` (direct),
`refill-lets-an-accept-cell-become-a-reject` (direct),
`a-decision-record-stops-outranking-the-seam-on-the-live-path` (direct),
`unreachable-reason-prints-a-bare-question-mark-again` (behavioural).

**Binding check on the seven lines** (`Retractions.load` -> `bind(records, extra=<sqlite
matched rows>)` -> `match_all` over the live ledger): **67 lines, 7 new, each new line binds
exactly 1 record, 0 bad, 0 unmatched.**

**Clause 1 — the lane's number.** *0 role records without a classifier verdict*: 0 before,
0 after. The number under it: **published rows carrying a `reject` cell, 11 -> 0 predicted**
(5 by a line, 6 by a refill), and **published `reject` cells that no writer could reach,
11 -> 0 by construction**.

**Clause 2 — delivered, or a hand-drain.** Delivered: the ruling (it is in the contract, so
the seam applies it with nobody watching), `reject_owed`, `ADJUDICATED` and the
`no-text-unattempted` name all run inside `daily-digest.yml` at 05:00 UTC. A hand-drain by
construction: the seven retraction lines and the two `ADJUDICATED` entries, which are
deliberately a hand-maintained list of two.

## 8. Clause 4

* *Deleted or unified?* Two test functions deleted, by folding them into tests that kill. Unified: the "is this cell owed a verdict" question
  now has a second half in one place — `class_backfill.candidates` gains the
  cache-contradicted pool rather than a second loop in `run.py`, and `_record_run`'s existing
  backfill loop is the only writer that applies it.
* *Extended, not duplicated:* `class_backfill.candidates`/`apply_to`, `Ledger._record_run`'s
  backfill loop, `Classifier`'s unreachable-reason fallback, `tools/rejudge_rows.py`'s
  docstring, `LLM_RULES` condition (2).
* *Rejected, with the number:* a `מודל` vocabulary arm (0 cards admitted that the live appeal
  does not already lift, and 2 the auditor leans OUT on); a contract bump built on anything
  wider than the measured flip set (2 of 20); withdrawing Harel, EY, Datamind, ONE ZERO,
  Edikted, Koladin, ONE datAI, Practical Vision ×2 or Digital Turbine (none reached 3-of-3
  NO; seven never got a first one); withdrawing Gamida on text that is not the row's (the
  09-02 qualifier); a `--restamp` hand-write into `roles.jsonl` (a hand-drain is not
  delivered — the backfill pool is); counting a `|bare` contradiction as a contradiction
  (2 of the 3 measured rows).
* *Would the next session find it?* `grep -n "cache_contradicted" pipeline/class_backfill.py`;
  `grep -n "no-text-unattempted" pipeline/seniority.py`; `grep -n "2026-09-14" ARCHITECTURE.md`
  lands on the §7b paragraph; `ls tests/fixtures/classifier/` shows the artifact.
* *Cross-lane debt.* The `roles.py` edit was named to the `roles` session by message TWICE and neither reached it — a sibling implementer is not an addressable agent from here (`No agent named …`). Their `_withdraw_rejected` sweep and this refill are coherent only because their sweep runs at the END of `_record_run`, after the backfill loop; if that order ever moves, a cell refilled to `accept` is withdrawn the same morning. `621` is the number THEIR session filed for the class this commit closes, so nothing was filed here — `docs/backlog.py next` returned 621 too, which is the collision the `next` command cannot see.
* *Harder for the next lane, counted — five.* (1) A second pool in the backfill, which widens
  what a morning may spend and needs the cache in hand (`candidates` now takes `cache` and
  `contract`). (2) A `cache-contradicted N` clause on the `backfill:` line. (3) A reject cell
  is no longer permanent, so "the cell says reject" is not a safe read of "the seam refused
  it today". (4) A contract bump: every `v3.0f84ab84` cell is superseded from tonight and the
  `classify:` line's stale counts rise for about three mornings. (5) `ADJUDICATED`: a
  hand-maintained list that outranks the seam, which is exactly the kind of thing that
  rots quietly — it is two entries, accept-only, and each names a record a test opens.
