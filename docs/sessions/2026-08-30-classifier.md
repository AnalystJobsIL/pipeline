# 2026-08-30 — `classifier`: the scope rule, and the drain that was never going to carry it

Lane: `classifier`. Worktree `classifier-0830` off `origin/master` `fd07897`. Spent: **~135
sonnet calls** on `CLAUDE_CODE_OAUTH_TOKEN` (96 + 19 measurement, ~20 verification and
adversarial). Bright Data: **0**. SerpApi: **0**. No workflow dispatched, none cancelled.

## The task, and what was actually wrong

The operator narrowed the product: analyst roles in Israel, all levels, all dates, but the
work must be **quantitative** — analysis of measured data — and not a **qualitative** opinion
or research report. Nothing in the classifier said so. The decision and its rejected
alternatives are `docs/decisions/2026-08-30-quantitative-scope.md`; the mechanism is
`ARCHITECTURE.md` §7b. This note is what the session found on the way, most of which was not
in the brief.

## The four things that were not what they looked like

### 1. The stale pool was not a queue, and raising the cap would not have moved it

The brief's reading — 191 roles on a superseded contract, cap 60, therefore "roughly two
weeks" to propagate a scope change — is the arithmetic the alarm invites, and the alarm is
what is wrong. Measured against the two committed caches under the new contract:

```
  175  stale, UNREACHABLE (a superseded |jd verdict, no description this run)
   82  stale NO   -> capped re-judge          -> 2 runs at cap 60
   45  fresh      -> LLM
   16  stale YES  -> the board                -> 1 run (uncapped, see below)
    9  keyword-accept (no text to read)
    1  bare prior + text -> upgrade call
```

A `|jd` verdict is never re-judged on a bare title — the invariant the bare/jd split exists
for, and the one the drain must not break. So a superseded `|jd` row whose role has no
description **today** cannot be drained at any cap, ever; it drains when `jdfill` delivers a
description and not before. Of the 191 the mail alarmed about, most were that. The cap was
not the binding constraint and raising it would have bought nothing.

So the cap stays at 60 and the alarm was split into the three different facts it had been
reporting as one: the queue (with runs-to-empty), the part no cap can reach (addressed to
`jd-text`, `458`), and a **stall** — the drain moved nothing while the seam was up and the
budget unspent, which is the line that says the propagation has stopped.

### 2. A superseded YES is not the same object as a superseded NO

A stale YES is a role **on the board right now** under a spec the operator has retired, and
there are only ever as many as the board is long (16 here). A stale NO is invisible until it
flips, and there are hundreds. Capped together, the budget is spent in encounter order —
alphabetically — and a retired-spec role sits on the board behind a queue of rejections. So a
superseded YES is exempt from `CLASSIFY_REJUDGE_CAP`; NOs stay under it. The board therefore
carries the new scope after **one run**, not five. The cohort is self-limiting (each is
drained once and rewritten under the current contract) and `cap` / `budget_min` still bound
the tier as a whole.

### 3. `has_text` and `jdfill` had stopped asking the same question, and it cost a call a day

The cache key said `|jd` when `len(raw) >= 300`, with a comment claiming this was "the same
measure `jdfill.maybe_fill` gates on". It was, until `jdfill` moved to `looks_like_jd`
(`jdfill.py:1774`). A nav bar and a cookie banner clear 300 characters, so:

- the key said `|jd` — verified text — for a role whose text was page furniture;
- the staging line refused to cache it, correctly, as untrustworthy;
- and the next morning the same posting was judged again, and the answer thrown away again.

Silent, daily, and invisible in `llm_cache` by construction. 4 of the 102 title-passing
postings that carry text on the committed caches, `Modellama | Research Analyst` (a real
742-char JD with no section headers) among them. The fix is one definition instead of two:
`has_text = looks_like_jd(desc)`. Furniture now keys `|bare`, is served from cache like any
bare verdict, and is re-judged the day a real description arrives. Guard:
`test_furniture_text_is_not_re_bought_every_morning` runs three mornings and asserts one call.

### 4. The twelve "never judged" roles were three different things, and none was a seam bug

The brief called this "the most important thing in this prompt". Traced end to end
(`run.py:269-364`, `roles.py:334-384`, `fetchers.py:950-968`): the only filter between fetch
and `clf.classify` is the Israel gate, every cached posting is re-classified every run, and a
posting is skipped before judgement only as a `merged-copy`.

- **Playtika ×3 — an artefact of the audit.** `_norm_company` strips `Ltd`, so the rows are
  `v3.…|playtika|…|jd`, not `playtika ltd|…`. All three exist; two are cached NO, which is why
  they are not in `matched`. `leak_audit.py` normalises differently from production and
  reports them as unjudged.
- **Kibeeri, finbounce, Beamup, Comcast — pending input, not lost.** Their
  `scraped_cache.json` entries were committed at 14:22Z and 17:43Z on 08-29; the last digest
  finished at **11:59Z**. Kibeeri and Beamup had no `companies.csv` row at that commit at all.
  No run has seen them yet.
- **Google Israel — 20 cards, every one with a 0-char description.** The single title that
  passes the gate is `Part-Time Research Scientist PhD Intern, 2027`, rejected by `_NOT_A_JOB`.

What the trace did find in this lane's own file is §3 above. `leak_audit.py` lives in the
orchestrator's directory and is not this lane's to edit; the two corrections it needs are
production's `_norm_company` and a comparison against the digest's own head commit rather than
today's tree.

## What shipped

| change | measured before shipping |
|---|---|
| condition (5) of `LLM_RULES` — quantitative, not qualitative | **0 false negatives of 96** postings with descriptions; 2 verdicts moved, both correct |
| `_QUALITATIVE_HINT` demotes `strong` → `signal` (never rejects) | **0 of 252** golden rows, **0 of 4,266** distinct live (company, title) pairs |
| a strong+senior title **with** a description is read, not assumed | of 19 such roles, the seam rejects **5** (`373@classifier`, closed with the rate) |
| a superseded YES is exempt from the re-judge cap | 16 stale YES → the board carries the new scope in **1 run** |
| legacy `company\|title` rows join the drain | **235** rows, **193 unreachable**, **42 reachable** (36 NO) — ≤42 calls once |
| `has_text` = `looks_like_jd` | 4 postings stop being re-bought daily |
| the stale alarm split three ways + a stall line | 175 unreachable vs 82 queued, which the old single line could not say |

Three words were **removed** from `_QUALITATIVE_HINT` after they demoted quantitative roles:
`intelligence` (`business intelligence developer`, 3 golden rows), `strateg(y|ic)`
(`strategic product analyst`), `consumer` (redundant with `insights`/`market`).

## What the adversarial pass changed, before the push

Three Opus attackers, read-only, against a throwaway COPY of this worktree. Wave 1 (the rule)
spent 40 sonnet calls and found three things worth fixing and two worth filing.

**Fixed.**

1. **The demotion turned an accept into a REJECT with no LLM to ask.** Ten titles flipped
   `strong`/accept → `signal`/reject in `--no-llm` and breaker-open mode, four of them SENIOR,
   including `Customer Insights Analyst` — a phrase `_STRONG` names itself. `_sig_accept_nollm`
   cannot rescue them because `_DATA_ANCHOR` deliberately does not match "analyst". The
   fallback now asks "would this be strong but for the qualitative hint?"; the `_BA_DOMAIN`
   and `_AGENCY_EMPLOYER` demotions are deliberately NOT lifted, because those are titles we
   positively do not want accepted blind. Nor is a hard-excluded title lifted — caught by the
   golden fixture, which moved 1 of 252 on my first attempt at this fix
   (`data engineer (product & customer insights)`).
2. **The vocabulary was singular-only** — `survey` missed `Surveys`, `economist`
   missed `Economists`, `policy` missed `Policies`. The same half-enumerated class that
   let `Data Analyst Interns` through `_NOT_A_JOB` on 2026-08-28, and I made it again two days
   later in the other direction. It is stems with no trailing boundary now.
3. **Five words the scope statement names verbatim were missing**: brand, category, industry,
   qualitative, competitor (only `competitive` was there), plus voice-of-the-customer,
   ethnographic, focus group and user/UX research. Eight constructed titles were being
   accepted unread; all eight now reach the seam.

**Filed, not fixed:** `459` and `460` below.

### Wave 2 — the drain and the cache key. Three breaks, all of them mine, all fixed

Zero LLM calls; the fake seam and constructed caches. Every one of these was created by this
session's own changes, and none was caught by 1,397 passing tests.

1. **The keyword shortcut sat ABOVE the cache lookup — and the worst thing I nearly shipped.**
   Gating the shortcut on "no description" (`373`) meant a role whose fill fails on alternate
   mornings alternated between the verdict the seam was PAID for and a guess from its title:
   measured over four runs, `reject, accept, reject, accept` — on the board and in the email on
   every accept day. The role that demonstrates it is `EPAM | Managing Principal / Senior
   Director, Data Analytics Consulting`, i.e. precisely the role the change was made to catch.
   The shortcut now sits **below** the lookup and fires only when nothing has ever judged the
   role. Guard:
   `test_a_cached_verdict_outranks_the_keyword_shortcut_on_a_day_with_no_description`.
2. **The mass-flip guard measured its two halves on different populations.** The ratio came
   from the same-contract cohort, the one-sidedness from the GLOBAL flip counters — and once
   legacy rows joined the drain, their flips landed in those counters. **Two** unrelated legacy
   rows flipping the other way silenced the guard on a morning where 12 of 12 same-contract
   verdicts flipped one way, committing 14 corrupted verdicts for a year. Both halves now read
   the same cohort. Guard:
   `test_a_mass_flip_morning_is_still_caught_when_legacy_rows_are_draining`.
3. **The uncapped YES cohort could starve the fresh roles behind it.** "There are only ever as
   many as the board is long" is an assumption about the data, and the code did not enforce it:
   unbounded, the drain spent the run in encounter order and every fresh role came back
   `llm_skipped`. That is not a re-buy — `run.py` selects the email cohort on `posted_date`, so
   a role skipped today can fall out of the 48-hour window and never be mailed. There is now a
   separate, deliberately generous ceiling (`CLASSIFY_REJUDGE_YES_CAP`, 150, against a 91-role
   board and 16 forecast stale YES), and the two cohorts are counted apart so the mail's
   "N done against cap 60" is true of the pool the cap actually bounds. Guard:
   `test_the_stale_yes_drain_cannot_starve_the_fresh_roles_behind_it`.

Wave 2 also re-raised `123` for the legacy cohort (a legacy drain bought and then withheld by
a mass-flip it did not cause). I had already found and fixed that one an hour earlier — its
guard is `test_a_legacy_re_judgement_is_a_drain_purchase_and_is_never_withheld` — and the
attacker's copy of the tree predated the fix. Invariants it attacked and could **not** break: a
`|jd` verdict is never re-judged on a bare title; `_drain_keys` is never withheld; the fresh
and re-judged quarantine cohorts stay separate; the shared-description guard; idempotence.

### Wave 3 — the fact-checker, and four numbers of mine that were wrong

1. **"240 legacy rows, 192 unreachable, 41 reachable, 35 NO" did not add up** (192 + 41 = 233).
   240 counted the 7 `jdq1|` rows the next sentence excluded, and the split had dropped the two
   legacy keys whose TITLE contains a `|`. Correct: **235 = 193 unreachable + 42 reachable, 36
   of them NOs.**
2. **`HANDOFF.md` welded two measurements**: "175 of 191" put the new contract's forecast
   inside the old contract's live alarm. They are different pools and must not be subtracted.
3. **I filed "~247 legacy rows" as a number the brief got wrong. It was right** — 254 − 7 = 247
   exactly. The new fact is the composition, not a contradiction.
4. **The Matrix title was mis-quoted two different ways** in two documents; both now carry the
   verbatim cache key.
5. **The FN artifact had never been saved** — the headline claim rested on a file that did not
   exist. The 77-row llm-tier pass was re-run (77 more calls) and the result is committed as
   `tests/fixtures/classifier/2026-08-30-scope.json`. Re-running it also produced the session's
   most uncomfortable finding: **the measurement is not bit-reproducible.** The same 77
   postings moved 2 verdicts on the first pass and 3 on the second; `Play Perfect | Fraud
   Analyst` appeared only in the second. It is a genuine borderline, not a flapping rule — but
   a single pass is evidence about a cohort, never an oracle for one role, and the documents
   now say so.

**A number the attacker could not reproduce, and was right to challenge.** "0 of 4,266
distinct live pairs" is over `(company, title)` pairs in the two caches that pass
`is_israel_job`; the attacker built a different corpus (3,583 distinct TITLES across five
sources) and also got 0. Both are now stated with their command. The finding underneath is
the honest one: **`_STRONG ∧ _QUALITATIVE_HINT` matches nothing in today's corpus at all**, so
the demotion is inert today — it is a guard for the day a `Customer Insights Analyst` is added,
which is exactly why finding (1) above mattered before it shipped rather than after.

**Condition (5) itself survived.** 18 of 19 constructed boundary cases answered correctly,
including the ones designed to break it: a BI analyst *inside a market-research agency* (IN),
a marketing analyst who "presents insights to brand teams" (IN), a product analyst who runs
NPS surveys and owns the event funnel (IN), a genuinely qualitative UX researcher (OUT), a
market-research analyst running focus groups (OUT). The one miss is `460`, and the attacker
proved it is the prompt window and not the rule — the pre-change four-condition prompt answers
NO on the same slice.

## The three test-set roles, decided

- **`Modellama | Research Analyst` — IN.** "Strong SQL (SQL Server), Python or R, statistical
  thinking, 3–5 years as a Data Analyst, large sports datasets." The title word "research" is
  exactly why this had to be an OUTPUT judgement rather than a title rule.
- **`Hila & Co. | Consumer & Market Insights (CMI) Manager` — OUT**, on two conditions: the
  output is qualitative market research ("ניהול מחקרי שוק מקצה לקצה", agency-planner
  background, work with research institutes), and it is posted by a headhunter (condition 4).
  Its registry row has since been parked by `registry` independently.
- **`Percepto | Data Insights Operations` — OUT.** A client-delivery role on drone imagery;
  no analysis of measured data. It was a **current-contract YES** — a rule-(1) over-read of
  the word "insights" — and the seam under the new rules answers NO with that reason. It is
  one of the 16 stale YESs, so it leaves the board on the first run.

## Numbers in the brief that my own measurement contradicts

- "~247 legacy rows" — **confirmed, not contradicted**, and I first wrote this up as a
  contradiction, which a fact-check caught. There are **254** non-contract rows and 254 − 7 =
  247 is exactly the brief's number. What is new is only the composition: **235 legacy
  `company|title` + 12 title-only + 7 `jdq1|<sha1>`**, the last being
  `enrich_matched_jd.py`'s JD-quality cache sharing the table, which is not a classifier
  verdict and which no count of "legacy verdicts" should include.
- "12 of the 30 keyword-accepts have no description": **11** have none, 19 have one.
- "roughly TWO WEEKS before the new scope reaches every role": the reachable pool is 98 rows
  and clears in **2 runs**; the board clears in **1**. The 175 unreachable rows are not on a
  timetable at all — they wait on descriptions.
- "12 roles have a real description and have never been judged": see §4.

## What I did NOT finish

- **The unattended run has not happened.** Nothing here is proven in production until a
  `schedule` digest containing this commit prints its `classify:` line. `## Morning checks`
  carries the row and the date.
- **`461`** — no visitor-facing surface states the quantitative boundary (`docs`/`render`).
- **`462`** — a `?location=Israel` listing URL makes every card on the page Israeli
  (`scraper`): 14 Comcast and 116 Hunter Douglas US postings are Israel-matched today.
- **`455@roles`** (a second reproduction folded into their item) — `BD_RUN_CAP=0`, which the brief tells every session to set, makes
  `test_bd_rescue_reads_the_unlockers_error_code_and_never_retries_a_policy_host` fail on a
  clean master (`infra`).
- **`463`** — the drain counters live only in the mail; the one-line `run.py` stamp diff is
  written out and filed for `infra`.
- **`454@roles`** — a NO keeps no evidence. They filed it the same day and own the schema, so mine was withdrawn rather than duplicated.
- **`464`** — the 175 unreachable stale verdicts need descriptions (`jd-text`).
- **`116`** — purging the 192 unreachable legacy rows is still open and still must not be
  done from a local checkout.
- **`465`** — a `|jd` verdict is never re-judged when the DESCRIPTION changes. This is the
  cost of reading a strong+senior role instead of assuming it: 2 of the 5 rejections rest on
  text that is not the role's (`Ballerine`, product marketing; `Hunter Douglas`, another job's
  JD), and a `|jd` NO is permanent. Fixing it honestly needs a text identity in the verdict,
  and `llm_cache` has no column for one — that table is `roles`'.
- **`466`** — `prompt_slice` truncates before the quantitative evidence in exactly the shape
  the new rule judges. Deliberately not fixed here: `CONTRACT` hashes the rules and the model
  but **not** the slice geometry, so widening the window would change what every verdict was
  made from while every cached verdict kept being served as current — the precise failure the
  contract key exists to prevent. Whoever takes it takes both halves.

## Traps this session hit

- **A quoted heredoc collapsed `\n` in a Python patch script**, so a `str.replace` matched
  nothing and the assert fired. Every patch script here builds backslash sequences as
  `chr(92) + "n"` or avoids them in the matched text entirely.
- **`BD_RUN_CAP=0` in the environment turns an unrelated registry test red.** Two of the
  "baseline failures" this session started with were self-inflicted: that one, and a full
  suite that was still running while files changed under it. Re-derive a baseline on a clean
  worktree with nothing exported.
- **`docs/backlog.py` needs a struck title.** A dated `**CLOSED …**` paragraph deep in the
  body does not close an item: it is either a struck title plus a dated closure anywhere, or
  a dated closure in the item's own first two lines.
- Attackers get a **throwaway copy** of the tree, never a worktree — a previous session's
  attacker ran `git checkout --` in another lane's work.
