# 2026-08-31 — classifier: the drain's first morning, and the rows nothing could reach

Lane `classifier` (`ARCHITECTURE.md` §7b). One commit. **74 LLM calls, 0 Bright Data
credits.** Cross-lane: eight lines in `pipeline/run.py` (`infra`) and eleven in
`pipeline/roles.py` (`roles`), applied on the operator's explicit ruling in-session.

## 1. The drain's own alarm: `_rules()` is intact, and the 19 flips are right

Run `33387229779` (`schedule`, `f2f272b`, 11:29Z) printed
`contract v3.da2cb878 re-judged 147/cap 250 + 3 stale-yes/cap 150, served stale 12
(12 unreachable without a description); 2 judged bare (shared description)`, attempts 192
in 10.7 min, `flipped +19/-1`, and the alarm addressed to this lane:

> the contract drain moved 19 of 150 re-judged verdicts and ALL of them the same way
> (+19/-0) — expected after a scope change, and what a mangled rules string looks like;
> check `_rules()`

**The mangled-string hypothesis is ruled out**, four ways: `pipeline/seniority.py` is
byte-identical between the run's commit and `origin/master`; `LLM_RULES` is one line of
2,507 characters with 0 newlines and all five condition markers; a recomputed
`sha1(LLM_RULES + "|" + LLM_MODEL)[:8]` reproduces `da2cb878`, the run's own contract; and
`_claude`'s `system` default IS the object `_contract()` hashes.

**The flips were enumerated and read, 0 LLM calls.** Diffing `llm_cache` between the
state commits `8eb1340` → `34da0fe` gives 192 new current-contract rows, 155 with a prior,
**20 moved and every one NO→YES**. The seam's own line reads `flipped +19/-1` overall and
`+19/-0` for the drain: 19 of my 20 are the drain's, the twentieth is a legacy/upgrade flip
outside `_drain_keys`, and the `-1` has **no cache row at all** — the most likely candidate is
one of the run's two shared-description verdicts, which count in `flipped_to_no` and are
deliberately never staged. I could not reconcile that one individually and say so rather than
rounding it away. Title and stored description read for all 20 from
`matched`:

* **16 plainly right** under the current scope — `mećkano | Data Analyst` (the case that
  retired the experience bar), Unity, Tailor Brands, SolarEdge, Nift, entrypoint, Nestlé,
  Computer Guard, dentsu, Ashley Digital, Helfy, Harel, EY (FSO data analyst), ONE ZERO, Paz,
  Mizrahi-Tefahot.
* **2 thin but defensible** — Diageo and Oak, both judged on 172-character snippets.
* **1 the operator's own question** — `Chainalysis | Intelligence Analyst - Fraud
  Researcher`, which shipped in the mail. See §2: the rule was wrong, not the verdict.
* **1 inconsistency** — `EY | אנליסט שכר והטבות` YES while `Medison Pharma | Senior Total
  Rewards Analyst` NO the same morning. Both hold under the new rules too, and the seam's
  own reasons draw the line between *analysing* compensation data and *managing*
  compensation policy. Filed, not legislated.

**The one real defect this hunt found** is in the seam, not the rules.
`_claude(prompt, *, system=LLM_RULES, …)` bound the rules at `def` time while
`set_experience_bar()` rebinds the `LLM_RULES` and `CONTRACT` globals — so after a flip every
verdict would be KEYED under the new contract and JUDGED against the old rules: the entire
cache superseded and re-judged one-directionally, with this very alarm pointing at a
`_rules()` where nothing is wrong. Unreachable from production today (the env var is read at
import), unpinned by any test, and exactly the failure the alarm's own text describes. Now
`system=None`, resolved in the body, with
`test_the_claude_system_default_follows_a_rules_change` (written red first).

**Morning-check answer: PASS.** The forecast was 210 drained in one run; 150 were re-judged
and 12 are description-blocked (`464@jd-text`). The reason is not the caps — none bound
(147 < 250, 3 < 150, 192 attempts < the 370 the reserve allows). The drain is
**encounter-limited**: it only reaches a superseded verdict when that posting appears in the
run, so the pool empties at the rate the boards re-list, not at the rate the cap permits.
89 stale suffixes remain (57 `v2`, 26 legacy, 6 `v3.a517bb77`; 12 prior YES).

## 2. The scope, re-ruled by the operator

Full record and the measurement: `docs/decisions/2026-08-31-domain-scope.md`. In short — the
enforced rules and the written decision disagreed about fraud/security, and the operator
answered that neither was what he wanted: *"the fact its finance or security don't matter. I
expect classifier to get descriptions and understand from them if the role is relevant"*,
and *"sales is fine. domain specific is fine, most data analysts are domain specific. FP&A,
SOC and 'market intelligence' specifically can be excluded"*.

Condition (2)'s categorical tail is replaced by a WORK test plus four **named exclusions**
(FP&A / budgeting / forecasting / accounting close; SOC / security monitoring and
investigations; market intelligence; pure PM / architect). Measured in three rounds, 30
calls: **0 of 17 moved** under a first wording; then **1 of 13** under the shipped wording —
`Chainalysis | Intelligence Analyst - Fraud Researcher`, the posting that raised the whole
question, now NO as security-investigation work, with every marketing, sales, compensation
and commercial-analytics YES holding; then **2 of 2** finance-titled postings the keyword
tier rejects, both NO. Contract `v3.da2cb878` → `v3.7cb6831f`, once, for both changes.
Chainalysis needs no retraction: its YES was made under the old contract, so the drain
re-judges it on the next run — the mechanism working as designed.

**The first wording was wrong twice and an adversarial read caught both.** It said "answer NO
**only where the work itself is not analysis**: FP&A, …", which a model can read as
*examples* and escape by judging one FinOps posting to BE analysis; and it left `market
intelligence` in condition (5) under "judge the WORK DESCRIBED, never the title", where a
quantitative market-intelligence analyst still passed. The operator named all three as
exclusions; the shipped text states them as exclusions.

**And the limit I nearly shipped as a false claim.** "The domain never decides" is true of
the LLM tier and **not** of the gate above it: `_HARD_EXCLUDE` still rejects a bare
`Financial / Compliance / Security / SOC / Credit / Equity / Investment Analyst` on the
`keyword` path with no description read. The 17-row measurement structurally could not catch
that — every row in it had already passed the gate. The gate is left alone on evidence (0 of
116 `excluded`-tier rejections in the exhaustive 08-28 measurement was a real analyst role;
both live finance-titled postings with a description are NO; 20 of the 28 affected titles are
SOC/security), the limit is now stated in the decision record, `ARCHITECTURE.md` §7b and §0,
and `README.md`, and the reopening measurement is `529`.

## 3. The 33 rows nothing could reach — the lane's number

**33 of the 167 published rows had no classifier decision ever recorded** (not ~48: that was
the 08-30 file, and `roles`' purge/withdraw machinery removed 15 of them this morning). Every
one `closed`; 30 with a real JD, 2 snippets, and one with no text at all
(`Taboola | Product Analyst (Maternity-Leave Replacement)`, judged title-only).

`rec["class"]` has exactly one writer (`roles.py`, from this run's `merged` jobs), so a role
that closed before that field existed (2026-08-25) is never in `merged` again. The contract
drain cannot reach them either — it re-judges RECORDED verdicts. **Nothing in the system was
going to fix this**, and the pile grows by every role that closes during an outage.

`pipeline/class_backfill.py` judges them under the current contract and hands `record_run` a
map it applies to EMPTY cells only, after the live stamping. Four isolations, each a way it
could have broken the run it rides in — it never touches `paths` (the `Decision paths:`
reconciliation still sums); it is **not a fresh cohort** (30 historical accepts at a ~100 %
YES rate would have quarantined the morning's real roles); a **quarantined morning discards
it entirely**, because `rec["class"]` is written once and never re-judged while a withheld
drain verdict is merely re-bought tomorrow; and it does not consult `fresh_reserve` (it runs
after both classify sites, so the reserve has nothing left to protect; `CLASSIFY_BACKFILL_CAP`
= 60 and the run cap bound it, and a held record is alarmed rather than dropped).

**Result: 42 verdict-less records, 41 judged (17 YES, 24 NO) + 1 keyword-free, 0 held; empty
`class_decision` 33 → 0.** Of the 24 rejects, 18 were published rows; each was re-read against
the seam's reason AND its stored description, **14 given a retraction line and four lifted** —
`Minute Media | Data Scientist` (condition (1) says a Data Scientist counts when the work is
experimentation, and the JD says "This is the core of the role"; it had been **emailed on
08-23**), `Mobileye | Experienced Data Analyst` and `Questar Auto | Senior Data Scientist`
(judged on text `looks_like_jd` rejects — everywhere else in this seam such a verdict is
provisional, while a retraction is permanent), and `Central Bottling | BI Developer 17621` (a
BI-developer boundary no decision record draws, `532`). All four keep an honest
`class_decision=reject` and are revisable. Next run, rehearsed on a scratch copy:
**167 → 153 rows, 0 empty, reconciliation `holds: True`**.

The shipped queue is narrower than that first pass: `candidates()` takes only `open`/`closed`,
after measuring that **9 of the 42 were purged or withdrawn and all 9 were `strong`** — 21 %
of the pass buying cells no reader can see.

`seen.db` is deliberately **not** committed: the paid verdicts are recorded durably in the
ledger's `class` field, `candidates()` excludes a record that has one, so tomorrow buys
nothing — and a hand-committed binary is a rebase conflict nobody can resolve. `roles.csv`
and its meta are not committed either: they are derived, the next run regenerates them, and
a local export silently reverted `published_on_pages` to `false` (no `ROLES_PAGES_URL` here)
and carried 32 cells of unrelated `emailed_on`/`ai` drift.

## 4. Also reported, not fixed

**NVIDIA bought two calls for one employer.** `NVIDIA | Senior Business Intelligence Analyst`
and `NVIDIA AI | Senior Business Intelligence Analyst` were judged separately at 12:03:28Z
and 12:03:41Z. Classification sees two jobs because the cache key is `company|title`; the
mail already carries `title-twin NVIDIA/NVIDIA AI`. The fix is identity, which is `roles`'.

**12 superseded verdicts cannot be re-judged** (no description this run; a `|jd` verdict is
never re-judged on a bare title) and **2 roles were judged on the title alone** because a
sibling at the same employer carried byte-identical text. Both are `jd-text`'s (`464`), and
both alarms fired exactly as designed. Recorded, not taken.

## 5. What two Opus attackers found in my own diff, before it was pushed

Both were pointed at the staged diff and told to find defects. Between them they found
**fourteen real ones**, and the two worst would have corrupted production data. Every one
below is fixed in the commit; each has a test unless the note says otherwise.

| what | why it mattered |
|---|---|
| **The CLI wrote descriptions into the record ledger.** `Ledger._absorb` puts the description on the record in memory and only `flush` strips it; my `main()` called `roles.dump` | `roles.jsonl` **267 kB → 915 kB**, 193 of 193 records carrying a duplicate of `roles_text.jsonl` — and the inline copy then SHADOWS the text file at the next `open_sync` for any record with no sqlite row, so a jd-text repair would be ignored. `_writable()` + a test |
| **A quarantined morning still stamped the dataset, permanently** | The map went to `record_run` with no quarantine check, so a seam this run had just declared broken could write `class_decision=reject` onto published rows — and `rec["class"]` is written ONCE and never re-judged (the drain re-judges cache rows, not ledger fields). Now the map is dropped with an alarm, and the backfill's keys lost their quarantine exemption |
| The `record(s) NO` alarm counted only LLM rejects | Three published rows could be stamped `reject` by the keyword or cache tier with nobody told; and it counted purged rows the dataset never publishes, overstating the human's work |
| The one print in the seam that was not `_ascii`-wrapped | Two of the 42 records carry U+FFFD; on a cp1252 console the CLI aborts **after** the calls are paid, and inside `run.py` the guard swallowed it and discarded the whole map with no alarm |
| A hook failure went to stderr only | The one failure this feature exists to close — "included but never judged, and nobody was told" — was exactly what its own error path produced. Now a `Stages:` alarm |
| No shared-description guard, no experience-bar clause | Two ways a backfill verdict could disagree with `_classify` about the same posting and put a `class_decision` in the public file that contradicts the board |
| `backfill_cap` 40 vs a pool of 42 | The documented "0 held" needed a non-default `--cap`; a default that cannot drain the backlog it was sized for documents a result nobody can reproduce. Now 60 |
| `candidates()` bought 9 calls for rows no reader can see | Its own docstring said they would be "cheap"; measured, all 9 were `strong` |
| A `|bare` verdict served to a record with a full JD | Everywhere else a bare verdict is provisional and upgraded; this column is written once |
| `class` tested for truthiness, not for `decision` | A record whose class dict lost its decision would look judged for ever while shipping an empty cell |
| Local-clock date in the CLI | `roles.load` breaks a duplicate `role_id` by `max(updated)`, so an evening pass in UTC+3 stamps tomorrow and outranks the cloud's next-day line (the shape of `269`) |
| Four unsafe withdrawals, and a false evidence string | §3 above; the keyword-tier row claimed a description had been read |
| Eight reasons cut mid-word at 253 chars | They are published in `meta.removed[].reason`, where a stranger reads them |
| **"The domain never decides" was false as written** | §2 above — the claim of the document that defines the product |

Rejected from their findings, with the reason: **`AppsFlyer | Senior FinOps Analyst` stays
withdrawn** (one attacker read it as a quantitative analyst in a finance domain; the operator
named that exact row as one that "would be REJECTED today", and FP&A is now a named
exclusion), and **the two Guardio rows keep two lines** (they are one Comeet posting under a
renamed title, so both `role_id`s need withdrawing).

## 6. `guard-kill` refused a test twice, and it was right both times

The first push (`3508ee0`) went red on `guard-kill` alone — 11 of 12 new tests KILLED,
and `test_a_backfill_retraction_line_shape_validates` was **CANNOT-FAIL**: it built a
retraction dict in a tmp dir and validated *that*, so it passed identically on a tree
without the commit. It asserted on nothing the commit contained.

The fix pointed it at the real file (`cloud_state/roles_retractions.jsonl`, the 14 lines
this lane shipped) and I verified it killed — red against the file at `9554c4c`, green
against the shipped one. It went red again on `b6764c7`, and **that was also correct**:
`guard-kill` measures against the previous master commit, which by then was `3508ee0` —
the commit that shipped the data. *"0 non-test file(s) put back"*. A test that guards DATA
shipped in an EARLIER commit can never fail on the revert, whatever the assertion says.

The only sanctioned escape is `CATALOGUED` — a docstring `Kills \`<id>\`` naming a
`tests/mutations.json` record — and no code mutation can vouch for an assertion about a
hand-written data file. So the test is **removed**, not exempted and not re-aimed at a
weaker target: it is a data check, and the tool's own docstring names that shape
("the assertion does not depend on the change it shipped with").

What was verified once, by hand, and what protects it from here:

* measured on the shipped file — **17 entries, 0 bad, 14 mine, 0 duplicate urls, every
  reason ending on a finished word, every one matched to a record** (0 `unmatched`);
* standing protection is production, not a unit test: `Retractions.load` counts bad lines
  and `Ledger` alarms `roles retractions unreadable (N bad line(s))` in the mail, and an
  unmatched url alarms as `roles retraction unmatched`. Both are read daily.

The lesson worth keeping: **a follow-up commit cannot add a guard for the commit before
it.** If a test is worth having, it ships in the same commit as the change it guards, or
it ships as a mutation record.

## Traps this session hit

* **A heredoc mangled a 12 kB test block** on the first attempt (`unexpected EOF`). The
  working path is `Write` to the scratchpad, then a two-line Python append.
* **`_record_run`'s status loop iterates SQLITE rows, not ledger records.** A test that built
  a ledger without inserting into `matched` never reached the live-stamp branch, and the
  backfill looked as though it had overwritten a live verdict when in truth the live path had
  never run. The backfill's own application sits after that loop, so it reaches records with
  no sqlite row — pinned in the test.
* **`HANDOFF.md` had 79 words of headroom** (3,121 of 3,200) before this session wrote a
  line. Three rewrites; the fold of this lane's own 08-30 (b) entry is what made it fit.
* **The retraction file is not applied by `pipeline.roles export`.** It is read in
  `record_run`, so a local export shows the rows still present — the withdrawal is only
  visible after a run. Rehearse it on a copied `cloud_state` rather than concluding the lines
  did not work.
