# Handoff — current state

**What this file is:** the state of the system *right now* — what changed last session,
what is known-broken, what nobody has claimed. Nothing else.

**Three caps, and why there are three.** `docs/check_docs.py` holds this file to 250
lines, 3,200 words and 60 words per line. The line cap alone was defeated: immediately
before the trim this file was 247 lines and **65,338 bytes**, because eighteen sessions
had each written their whole narrative as one line — the longest was 9,011 characters,
thirty-six times the cap. (The first version of this paragraph said 56,515 bytes and
4,960 characters: correct numbers, measured at `ae6eeae` the evening before, six commits
stale by the time the trim ran.) The word caps make
the three mutually reinforcing: a narrative that will not fit on one line has to wrap,
and wrapping blows the line count, which is what pushes it to `docs/sessions/`, which is
where it already was. Thirteen of the eighteen already ended with `Record:`.

**The shape of a session entry** (enforced, so "add exactly ONE line" has an upper bound):

    - **<YYYY-MM-DD> `<lane>`** — <what was wrong>. <what changed>. **NOT finished:** <backlog keys>. Record: `docs/sessions/<date>-<lane>.md`.

Where the other things went:

| you want | read |
|---|---|
| the durable system model, the rules, the runbooks | `ARCHITECTURE.md` |
| a design debt or a known gap that outlives a session | `docs/BACKLOG.md` |
| what one past session found and fixed, in its own words | `docs/sessions/<date>-<lane>.md` |
| where to start as a spawned agent | `CLAUDE.md`, then `docs/AGENT_BRIEF.md` |

---

## Morning checks — a prediction is not finished until it has an answer

A session that predicts what tomorrow's mail will say writes the prediction **here**, with
the date it comes due, and whoever is next **answers it**. `docs/check_docs.py` warns on a
row past its date with an empty verdict, and refuses the old free-text form — fourteen
`Morning check <date>:` sentences were buried in prose across this file and **not one had
ever been answered**. Two had already failed in public twice: `### Tel Aviv` and
`### Jobgether` both shipped as employer headings in the 2026-08-26 email against checks
that said neither would.

A verdict is `PASS`, `FAIL — <what actually happened>`, or `N/A — <why>`, and it carries a
**grep-able string**, never an adjective. Answered rows older than 7 days move to
`docs/morning-checks.md`.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-31 | classifier | the scope rule is **live and draining** in an UNATTENDED run: the `classify:` line names a contract that is NOT `v3.a517bb77` and `re-judged` is above 0. `re-judged 0` with the breaker closed means the `drain did NOT move this run` alarm fired and it has stalled | | not yet due (first 05:00 slot after the push + 180 min) |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-08-29 | registry | `publish.scanned` **>=1,000** (was 969) and the board carries Mixtiles *VP Data*, RealPlay, lab42, Alma Lasers; and `grep -c 'needs re-resolution' companies.csv` falls below **36** — still 36 on 08-30 means the hunt owns the routed rows but does not act (`375`) | 2026-08-29 | PARTIAL - scanned **1000** PASS (08-28 run). Board has RealPlay, Alma Lasers, withfaye; **Mixtiles and lab42 absent**. `needs re-resolution` **FAIL: 120** - the zero audit routed ~85 rows in; re-check 08-31 |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0`; above that, strip that run's verdicts | | |
| 2026-08-30 | registry | digest scans **>=1,015** (was 1,000), `collect:` under **55** min (cap 110); **>=35 of the 56** `queue-drain 2026-08-29` rows produce a posting | | |
| 2026-08-30 | registry | `grep -c 'needs re-resolution' companies.csv` **below 75**; still 75 on 08-31 means the hunt owns the routed rows and does not act (`375`) | | |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due (`audit-coverage.yml` is `0 4 * * 0`) |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl`; it is provisional on n=3 (ARCHITECTURE §5d) | | not yet due |
| 2026-08-31 | roles | **the dataset regenerates without a session.** In the 2026-08-31 state commit, `cloud_state/roles.csv.meta.json` carries `"run_date": "2026-08-31"` and `cloud_state/funnel.csv` has gained its FIRST row (it ships header-only). Also: the 7 `purged` records gain a `purge_reason` (the seed wrote 0 — only a real run writes it). If the meta still says 2026-08-30, the mail's `Stages:` line must say `roles dataset stale` — an artefact that silently stopped regenerating is the failure the alarm exists for, so a stale file with NO alarm is the worse outcome and the one to report | | |
| 2026-08-30 | jd-text | the `enrich` stamp after both runs carries **`archive_ran` = 1** (the night survived the morning), **`scrape_thin_remaining` <= 760** and **`matched_llm_unavailable` = 0** | | |
| 2026-09-02 | docs | **the escalation caught something rather than merely being green.** `git log --since=2026-08-30 -p -- HANDOFF.md` shows at least one row ANSWERED or re-dated with `until` by a lane other than `docs`. Zero in three days means the rule is being satisfied by not writing rows at all, which is the failure it replaced wearing a different coat | | not yet due |
| 2026-08-31 | docs | **the session-start hook actually runs.** A session opened in this repo shows a `tree: N behind origin/master ...` line in its context before it reads `CLAUDE.md`. It is a hook in a committed `.claude/settings.json` and it CANNOT be tested from inside the session that writes it, so it ships under the same rule as any scheduled step: unverified until something nobody started produces the line. If it is absent, the schema or the Windows shell is wrong - `claude --debug` names it - and the fallback is `python docs/check_docs.py --tree`, which needs no hook | | not yet due |
| 2026-08-31 | docs | **the three tree/row/unattended guards pass ON A RUNNER.** `gh run list -R AnalystJobsIL/pipeline --workflow tests.yml --limit 1 --json headSha,conclusion` shows this session's sha and `success`, and the run log carries the `CI checkout: shallow=... origin/master=... commits=...` line from `test_ci_itself_confirms_why_the_tree_check_cannot_run_there`. They passed on every laptop and failed on every push until now, which is the only reason `tests.yml` had this session's name on it | 2026-08-30 | PASS, early - `Unit guards` = **success** on runs 33293548117, 33294213125, 33294986316 and 33295877346 (all four cancelled LATER, at step 9). The runner reported `CI checkout: shallow='true' origin/master='61bbc99a' commits='1'`, which corrected the reason: origin/master IS the built commit, so `behind` is 0 by construction |
| 2026-08-31 | company-intel | the first unattended digest after this push prints `registry backlog N (±D since 2026-08-30)` and `bulk cron: … of N to do` on `Company intel:`, and its step log has no `blurb dropped, not a company: Tel Aviv`. `(first measurement)` on 08-31 means the `intel` stamp did not survive persist (`451`); once 449 lands, any `claude unavailable` on that line names a `subtype` | | not yet due |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | | not yet due |

## State at handoff — 2026-08-27 07:5x UTC, every number re-derived

The table this replaces was dated 2026-08-23 and **every cell in it was stale**, including
the `docs` lane's own re-count four lines below it. Two snapshots of a four-day-old
morning, both presented as current state, in the file the brief tells every agent to read
in full. Commands are given so the next reader re-derives rather than trusting.

| | | how |
|---|---|---|
| registry | **1,266 rows · 893 active · 373 parked** | `python check_invariants.py` (it prints 1,267: it counts the header) |
| by tier | **451 native-ATS · 421 scrape · 1 discovery** | `python registry_health.py --census` — and note this moved 18 rows in the hour between `ae6eeae` and `623b2a9` |
| store | **135 matched · 59 sent · 946 firmographics · 516 llm_cache · 112 company_info** | `sqlite3 cloud_state/seen.db` |
| ledger | **135 `roles.jsonl` · 132 `roles_text.jsonl`**, reconciling with the store | `wc -l cloud_state/roles*.jsonl` |
| firmographics export | **973** records — the sqlite table holds 946 and the 08-26 mail said 942 | `len(json.load(open('cloud_state/firmographics.json')))` |
| last digest | **2026-08-26** — 870 scanned, 3 failed, 28 LLM calls, 96 accepted → 65 merged → **8 emailed**, board 76, archive 56 | `digests/latest.md` |
| guards | **1,270 collected** (968 `test_units` / 205 `test_registry` / 97 `test_company_intel`) — **1,256 passed, 3 failed, 11 skipped** in 5m17s. The `988` this row carried until 2026-08-28 was stale by 282. | `python -m pytest -q` |

**`tests.yml` is red, and the three failures are not the one this file named yesterday.**
Re-measured by `infra` at `759ba36`, clean worktree, 2026-08-28 evening:
`test_no_two_active_rows_share_a_board` (`registry`),
`test_native_url_is_derived_from_the_public_url_alone` and
`test_every_open_role_in_the_ledger_carries_a_job_description`. Each reads live state, so a
cron can break or fix one without anyone touching code. **Never read a red `tests.yml` as
"someone else's problem" without re-deriving the list** — it has changed twice in two days.

## Watch list for the next session

0. **RUN THIS, OR TOMORROW LOOKS EXACTLY LIKE TODAY: `python digest_watchdog.py`.**
   2026-08-27 was not dropped crons, it was **absurdly late** ones: the 00:00 slot landed at
   05:41 and the 02:30 slot at **12:57, +627 min**. For the digest that is the same thing —
   the relay's last poll is 10:17, so late past it is no mail. Nothing in the repo said so;
   a human looking was the only detection. The watchdog is the one tripwire not on GitHub's
   scheduler — read-only, no credential, no dispatch — but it is **not installed**:
   registering the task is an operator action, command in its docstring. `292@infra`.

0b. **A patch script wrote a literal backslash-n into `daily-digest.yml` where a
   continuation was meant.** It would have broken every run: bash reads the `n` as an
   argument, the pipeline step goes red, no board and no mail — daily. It is
   *syntactically valid*, so `bash -n` misses it. Guard:
   `test_no_workflow_run_block_fakes_a_line_continuation`. **Read it before writing a patch
   script that emits YAML.**

0. **Active rows with an all-time-high of ZERO — this item has been wrong five times and is
   now a COMMAND plus a record.** `python confirm_zero.py --scrape-only` audits the pool and
   `cloud_state/zero_confirm.json` is the durable answer per row. 2026-08-29: 215 at the start,
   ~139 answered, none recorded empty without a rendered page and an LLM read. **Two sibling
   classes the pool cannot see by construction, because it needs a baseline of exactly 0:**
   region variants (`registry_health.py --regions`, 32 rows, 1 real) and abandoned tenants
   (`--stale-boards`, 18 rows whose newest posting is over a year old, one of them EMAILED).
   `docs/sessions/2026-08-28-registry-evening.md`; `399`, `406`, `407`.

1. **`merge_key` should move onto `firmographics.identity_key`.** `ARCHITECTURE.md` §7c
   counts **13** identity groups where two active rows read one board (this said ~15). It is
   the `matched` PRIMARY KEY, so it needs a migration. `docs/BACKLOG.md` 132–139, `roles`.
2. **`mark_sent` still records intent, not delivery.** `daily-digest.yml` runs it at step
   `Mark digested roles as sent`, before `Persist state back to the repo` and long before the
   06:17 relay. A role can still be burned unsent.
3. **`cloud_state/seen.db` is 1.54 MB** (`ls -l`, not the ~1.2 MB this said) and still holds a
   946-row `firmographics` table that also travels as a 973-record JSON. Dropping it and
   VACUUMing is the biggest single win on the daily binary.
4. **iCIMS is the only unsupported ATS left.** `eightfold`, `phenom`, `successfactors` and
   `jobvite` all have fetchers now; `jazzhr` was deliberately retired. `registry_health.py
   --ats` is derived and correct — run it instead of trusting a list. HiBob is down to **1**
   active row, not 2, so it is moving away from the 3-row trigger, not toward it.
6. **~24 active rows are re-checked by NOTHING, and `ARCHITECTURE.md` §2's headline claim
   ("every state except `defunct:` and `domain-dead` is re-checked on some cadence") is
   false because of it.** Found by `registry` on 2026-08-27.
   `health.zero_is_a_measurement()` exempts `israel_scoped` fetchers from `empty-board` for
   a good, documented reason — 25 healthy Workday boards clogged the self-heal queue on
   08-24 — but the cost was never written down: such a row never enters `stale.json`, so it
   never enters `resolve_broken.candidates()` (whose scope IS `stale.json`), and every
   parked pool excludes it on `active == false`. `repair_dead_urls` is the one pool with no
   active filter and it selects on the hostname failing to resolve, which a live Workday
   tenant's does not. Broadcom's note says "Tel Aviv postings confirmed live" while its
   all-time high is 0; one free POST settles which.

5. **GitHub dispatches these crons when it feels like it, and nothing notices a run that
   never started.** On 2026-08-27 the 00:00 scrape refresh ran at **05:41**, and the 02:30,
   05:00 and 06:00 crons had not fired at all by 07:41 — so no board, no mail, and no alarm,
   because every "the run broke" path fires from *inside* a later digest. `firmographics.yml`
   (added 08-26, cron `0 10 * * *`) has **never once fired**. `docs/AUTOMATION.md` has the
   measured drift; the fix is `infra`'s (`docs/BACKLOG.md`).

## Open items — highest value first

1. **~370 parked rows carry a triage mode and the hunt is time-budgeted (200 min)**, so it
   will not clear the pool in one night; expect a trickle. `extract-gap` needs no search and
   should land first. The mode table that used to sit here was superseded by its own
   footnote within a day — **run `python registry_health.py` for today's pools** rather than
   reading a number here.
2. **iCIMS** is the one platform with rows and no native fetcher (recipe: `ARCHITECTURE.md`
   §6). The old "3+ rows earns a fetcher" rule was replaced by the operator on 2026-08-26:
   one row earns it.
3. **`CLAUDE_CODE_OAUTH_TOKEN` may expire.** Symptom: `LLM calls this run: 0` with a large
   `llm_failed_fallback`. Re-run `claude setup-token` and reset the secret.
4. **SerpApi exhausted until 2026-09-01.** The working search is
   `deep_validate.google_via_unlocker`.
5. **`--census` rewrites its own baseline every digest run**, so a pool alarms at most once
   and a slow drift never alarms at all. `315@registry`.

**Closed since this list was written, verified 2026-08-27:**
*(6) `candidate_probe.json` and `scrape_rot.json` were never-yet-exercised in cloud — both
are present and in the 08-26 state commit. (7) CI conflict-recovery clobbering `seen.db` —
`grep -rn "reset --hard" .github/workflows/*.yml` returns nothing; all nine state-committing
workflows go through `persist_state.py commit`, which the `infra` session recorded three
entries further down this same file.*

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24, six lanes** — `ats-fetch`, `classifier`, `company-intel`, `jd-text`,
  `registry`, `scraper`. Folded to a pointer on 2026-08-27 to keep this file inside the
  word cap it sets: each entry named a record and the records hold the long version.
  `docs/sessions/2026-08-24-*.md`.
- **2026-08-25, five lanes** — `discovery`, `infra`, `registry`, `render`, `roles`.
  Folded to a pointer on 2026-08-28 by `classifier`, as the 2026-08-24 batch was on
  2026-08-27 and for the same reason (`docs/BACKLOG.md` 338): no lane could fit an entry.
  `docs/sessions/2026-08-25-*.md`.
- **2026-08-28, 10 lanes** — `infra` (×2), `docs` (×2), `classifier` (×2), `registry`, `scraper`, `company-intel`, `jd-text`. Folded 2026-08-30. `docs/sessions/2026-08-28-*.md`.
- **2026-08-26, five lanes** — `ats-fetch` (×2), `scraper` (×2), `discovery`,
  `company-intel`, `jd-text`. Folded to a pointer on 2026-08-28 by `docs`, as the
  2026-08-24 batch was on 08-27 and the 2026-08-25 batch on 08-28, and for the same
  reason (`docs/BACKLOG.md` 338): the word cap left nine words and no lane could fit an
  entry. `docs/sessions/2026-08-26-*.md`.
- **2026-08-27, five lanes** — `registry` (×3), `infra`, `docs`, `roles`, `discovery`.
  Folded to a pointer on 2026-08-28 by `classifier`, as the 2026-08-24/25/26 batches
  were, and for the same reason (`docs/BACKLOG.md` 338, 361): the word cap left twelve
  words too few for one entry. `docs/sessions/2026-08-27-*.md`.
- **2026-08-30 `jd-text`** - the inline filler was never idle: **128/146, 132/164, 132/167** a morning, into `matched` not the caches. `linkedin no-markers` is HONEST; the Unlocker reads those pages **5 of 5**, so it may now buy (**9 of 10**) - INERT until infra applies 448. **UNVERIFIED IN CI**: `guard` cancels at its 10-min timeout (442). `docs/sessions/2026-08-30-jd-text.md`. **NOT done:** 445-448.
- **2026-08-29, two lanes** - `jd-text`, `registry` (queue). Folded 2026-08-30 by `classifier`. `docs/sessions/2026-08-29-*.md`.
- **2026-08-30 `registry`** - three checks disagreed on whose board a URL is; **29 rows existed despite a NOT-THEIRS verdict**, one ACTIVE on a VC's jobs page. `board_verify.py` renders before reading; a non-reproducing verdict is UNVERIFIABLE. **151 wrong addresses cleared, 0 left.** Drain wired at 19:00. **NOT finished:** 481 owed (retried nightly), the cron has not run. `docs/sessions/2026-08-30-registry-verify.md`.
- **2026-08-30 `docs`** - the definition of done never said WHOSE output, so a 3-second nightly step that filled 0 was `done`; and `docs check` exited 0 with 12 warnings, so every unanswered prediction passed the pre-push contract. Seven predictions answered from runs, 12 -> 0 warnings, deletion and staleness are errors now. **NOT finished:** 436-440. Record: `docs/sessions/2026-08-30-docs.md`.
- **2026-08-30 `docs` (CI + outcomes)** - **UNVERIFIED IN CI**: my four pushes produced runs 33293548117, 33294213125, 33294986316, 33295877346, every one **cancelled** on the `guard` job's 10-minute timeout (`442`), so no verdict exists; `Unit guards` passed within each. Definition of done leads with the number now. **NOT finished:** `442`-`444`. Record: `docs/sessions/2026-08-30-docs-ci.md`.
- **2026-08-30 `company-intel`** — the gap was a level, the cap never bound, a truncated or crashed cron night stamped like a drained one. Direction on the mail line, `todo/attempted/left` + alarms in the stamp, `--budget-min`, blurb purged once. **UNVERIFIED IN CI:** run 33296542486 in progress at push; every run since 04:55Z cancelled (`442`). **NOT finished:** 449-452. Record: `docs/sessions/2026-08-30-company-intel.md`.
- **2026-08-30 `roles`** - `seniority` was computed and dropped (**0 of 154**), the funnel printed once and discarded, retention unguarded. Now **`cloud_state/roles.csv`, 143 rows**, 60-day window on `last_seen`; seniority **154/154**; `funnel.csv`; `dump()` refuses to shrink. Raw-URL public, **NOT on Pages** (`453@infra`). Both red tests pre-existing (`455`). **NOT finished:** 453-455, proof due 08-31. Record: `docs/sessions/2026-08-30-roles.md`.
- **2026-08-30 `classifier`** - scope is QUANTITATIVE analyst work now. The stale alarm invited a cap raise that buys nothing: most of that pool no cap reaches. Condition (5) plus a demote-only hint (**0 FN of 96**); strong+senior with a JD is READ (**5 of 19 rejected**, `373`/`121` closed). **NOT finished:** 461-466, the unattended run. Record: `docs/sessions/2026-08-30-classifier.md`.
