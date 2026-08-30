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
| 2026-08-31 | classifier | the scope rule is **live and draining** in an UNATTENDED run: the `classify:` line names a contract that is NOT `v3.a517bb77`, `re-judged` above 0, and the `SUPERSEDED` clause GONE (08-30 evening caps: one-run drain; a one-directional `drain moved` line is expected) | | not yet due |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-08-31 | infra | first `listing-hunt` run (`event: schedule`, headSha ⊇ the 08-30 infra (b) commit) prints `retire-settled: queue N -> M` BEFORE its `queue-resolve-search:` lines, and `ingested N new attempts` from the step `Ingest the drain's attempt log`; quote its `S s/name over K scored` line into `491` item 3 (6 shards vs a 45-min step) | | |
| 2026-09-01 | infra | `tests.yml` on ANOTHER lane's push: `mutation-gate (0)`..`(4)` all `success`, every shard's `timing    wall` under **1,800 s**; over that ⇒ add a matrix entry, never the budget | | not yet due |
| 2026-08-31 | infra | the first `event: schedule` digest on a headSha ⊇ the 08-30 infra (b) commit logs `persist_state: pushed` and `relay notified:`, and no `dry run:` line | | not yet due |
| 2026-09-01 | infra | first scheduled digest after 08-30: log `cron watch: window_days=3`, subject `(schedule run <id>)`, `Stages:` `ci …`/`cron …` or silent; inline filler `bd_tried` > 0 (448); a `tests.yml` run on another lane's commit: 10 jobs, verdicts on all | | not yet due |
| 2026-09-07 | infra | 7 mornings from 09-01: `Company intel:` backlog **median <= 10**, delta **<= 0 on >= 5 of 7**, `firmo` **left = 0, age <= 1** (`450`); `10:17` lag **< 180 min** (305) | | not yet due |
| 2026-08-29 | registry | `publish.scanned` **>=1,000** (was 969) and the board carries Mixtiles *VP Data*, RealPlay, lab42, Alma Lasers; and `grep -c 'needs re-resolution' companies.csv` falls below **36** — still 36 on 08-30 means the hunt owns the routed rows but does not act (`375`) | 2026-08-29 | PARTIAL - scanned **1000** PASS (08-28 run). Board has RealPlay, Alma Lasers, withfaye; **Mixtiles and lab42 absent**. `needs re-resolution` **FAIL: 120** - the zero audit routed ~85 rows in; re-check 08-31 |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0`; above that, strip that run's verdicts | | |
| 2026-08-30 | registry | digest scans **>=1,015** (was 1,000), `collect:` under **55** min (cap 110); **>=35 of the 56** `queue-drain 2026-08-29` rows produce a posting | 2026-08-30 | PARTIAL - `minutes=35` PASS; queue-drain PASS **128 of 138**. scans N/A: no 05:00 digest by 06:28Z; run `33250362574` had `scanned=1000` |
| 2026-08-30 | registry | `grep -c 'needs re-resolution' companies.csv` **below 75**; still 75 on 08-31 means the hunt owns the routed rows and does not act (`375`) | 2026-08-30 | FAIL - **309** rows carry `needs re-resolution` (was 120): `--verify-existing` cleared 151 wrong addresses into this token; the pool fills faster than the hunt drains it |
| 2026-08-31 | registry | the queue converges with no session: the 19:00 `listing-hunt` run (`event: schedule`, headSha containing this commit) prints `retire-settled: queue N -> M` and `queue: N owed` **<= 210** | 2026-08-30 | N/A - superseded the same day: two digest runs re-added 362 names (189 already retired), queue 210 -> **572**; the 08-31 row below carries the re-aimed prediction |
| 2026-08-31 | registry | the drain ran UNATTENDED on this commit: the 19:00 `listing-hunt` log (`event: schedule`) shows the four `queue-resolve-search: N names` lines summing to **>= 100**, an `ingested N new attempts` line, `retire-settled: queue 572 -> <= 400`, and the stamp line `queue: N owed (... falling)` with `new_intake` and `retired_in_queue` in the stage stamp; a `budget hit` line is fine, a shard with 0 proposals and no `budget hit` is not | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-02 | registry | the query-URL parks HELD without a session: `python registry_health.py --query-urls` prints `parked by the audit (in the hunt's pool): 20` (or more), `grep -c 'query-filter 2026-08-30: filter' companies.csv` >= **19**, and no 19:00 log since 08-30 carries `verified N IL via jobs.comcast.com`; `grep -c 'query URL' <listing-hunt log>` >= 1 shows the guard firing | | |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due until 2026-09-07 (`audit-coverage.yml` is `0 4 * * 0`; the first Sunday after the deep rung shipped is 09-06) |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | | not yet due |
| 2026-08-31 | roles | **the dataset regenerates without a session.** In the 2026-08-31 state commit, `cloud_state/roles.csv.meta.json` carries `"run_date": "2026-08-31"` and `cloud_state/funnel.csv` has gained its FIRST row (it ships header-only). Also: the 7 `purged` records gain a `purge_reason` (the seed wrote 0 — only a real run writes it). If the meta still says 2026-08-30, the mail's `Stages:` line must say `roles dataset stale` — an artefact that silently stopped regenerating is the failure the alarm exists for, so a stale file with NO alarm is the worse outcome and the one to report | 2026-08-30 | PASS, early — run **33306411751** (`event: schedule`, headSha `ba3d804` ⊇ `a1033c3`): meta `run_date 2026-08-30` at 10:52:46Z, `funnel.csv` first row `2026-08-30`, `purge_reason` **7 of 7**. Its pipeline step exited 1 on infra's `deliver: refused`, so Pages kept the 10:06 file (155 rows) while master holds 161 |
| 2026-08-31 | roles | **BUILT, NOT YET PUBLISHED: the retraction lands in the PUBLIC file only when a digest run's publish step runs** (today's schedule run exited 1 on a benign delivery refusal, so Pages still serves the 09:15 manual run's file with all the bad rows). Run `curl -s https://analystjobsil.github.io/board/roles.csv \| grep -c 'Comcast\|Jobgether'` → **0** (3 on 08-30) and `curl -s https://analystjobsil.github.io/board/roles.csv.meta.json \| python -c "import sys,json;d=json.load(sys.stdin);print(d['generated_at'],d['rows'],d['published_on_pages'],len(d['removed']))"` → a 2026-08-31 stamp, `True`, 12+; the mail's `Roles:` says `withdrawn 2` and `Stages:` `roles withdrawn 2 role(s)`. Still 3 ⇒ the publish step was skipped again — check `steps.pipeline.outcome` on that run | | not yet due |
| 2026-08-30 | jd-text | the `enrich` stamp after both runs carries **`archive_ran` = 1** (the night survived the morning), **`scrape_thin_remaining` <= 760** and **`matched_llm_unavailable` = 0** | | |
| 2026-09-02 | docs | **the escalation caught something rather than merely being green.** `git log --since=2026-08-30 -p -- HANDOFF.md` shows at least one row ANSWERED or re-dated with `until` by a lane other than `docs`. Zero in three days means the rule is being satisfied by not writing rows at all, which is the failure it replaced wearing a different coat | | not yet due |
| 2026-08-31 | docs | **the session-start hook actually runs.** A session opened in this repo shows a `tree: N behind origin/master ...` line in its context before it reads `CLAUDE.md`. It is a hook in a committed `.claude/settings.json` and it CANNOT be tested from inside the session that writes it, so it ships under the same rule as any scheduled step: unverified until something nobody started produces the line. If it is absent, the schema or the Windows shell is wrong - `claude --debug` names it - and the fallback is `python docs/check_docs.py --tree`, which needs no hook | | not yet due |
| 2026-08-31 | docs | **the three tree/row/unattended guards pass ON A RUNNER.** `gh run list -R AnalystJobsIL/pipeline --workflow tests.yml --limit 1 --json headSha,conclusion` shows this session's sha and `success`, and the run log carries the `CI checkout: shallow=... origin/master=... commits=...` line from `test_ci_itself_confirms_why_the_tree_check_cannot_run_there`. They passed on every laptop and failed on every push until now, which is the only reason `tests.yml` had this session's name on it | 2026-08-30 | PASS, early - `Unit guards` = **success** on runs 33293548117, 33294213125, 33294986316 and 33295877346 (all four cancelled LATER, at step 9). The runner reported `CI checkout: shallow='true' origin/master='61bbc99a' commits='1'`, which corrected the reason: origin/master IS the built commit, so `behind` is 0 by construction |
| 2026-08-31 | company-intel | the first unattended digest after this push prints `registry backlog N (±D since 2026-08-30)` and `bulk cron: … of N to do` on `Company intel:`, and its step log has no `blurb dropped, not a company: Tel Aviv`. `(first measurement)` on 08-31 means the `intel` stamp did not survive persist (`451`); once 449 lands, any `claude unavailable` on that line names a `subtype` | | not yet due |
| 2026-08-31 | render | the first unattended mail's H1 number == `grep -cE '^- \*\*[^*]*\*\*( — [^ ]+)? · 📍 ' digests/latest.md` no `email subject says` line; `same-posting` names both 08-30 pairs unless `registry` parked them (`487`) | | not yet due |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | | not yet due |

## State at handoff — 2026-08-30 ~09:30 UTC, every number re-derived

The 2026-08-27 table that stood here said registry **1,266 rows · 893 active** (it is 2,045 ·
1,099) and *"`tests.yml` is red ... 3 failed"* (1,469 pass, 0 fail). Every cell below carries
the command that re-derives it, because that is the only thing that keeps this honest.

| | | how |
|---|---|---|
| registry | **2,045 rows · 1,099 active · 946 parked · 0 orphans** | `python check_invariants.py` (it prints 2,046: it counts the header) |
| by tier | **525 native-ATS · 573 scrape · 1 discovery** | `python registry_health.py` |
| intake queue | **557 owed of 572** (210 at 09:xx) | `python queue_state.py` |
| last digest | **2026-08-29**, `scanned=1000`, **4 emailed** (no 05:00 slot has fired at 05:00 since 08-26) | `digests/latest.md` |
| guards | **1,469 passed · 12 skipped · 0 failed** locally at `06f07cd` | `python -m pytest` (not `-q`) |

**Green here is not green in CI**, and on a commit master has moved past. Each lane's line names its run.

## Watch list for the next session

0. **`python digest_watchdog.py` is still not installed** (`292@infra`, operator action). Since 2026-08-30 a dropped or +720-min-late slot is a `cron …` line in the mail; the watchdog is the only tripwire off GitHub's scheduler.

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

5. **GitHub dispatches these crons when it feels like it.** Since 2026-08-30 a dropped or +720-min-late slot is a `cron …` clause on the mail's `Stages:` line (`schedule_census.py --alarm`); the recovery-cron decision is the 09-10 row.

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

*Items (6)-(7), closed and verified 2026-08-27, pruned 2026-08-30 for the word cap — the
verifications live in `docs/sessions/2026-08-2[6-7]-*.md`.*

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24 → 2026-08-30, 51 session lines across ten lanes** — folded to pointers (338, 361), last by `docs` (c). Records: `docs/sessions/2026-08-2[4-9]-*.md`, `docs/sessions/2026-08-30-*.md`; `registry` (d) is in `2026-08-30-infra-b.md` §0. CI runs no record holds: 33298814000, 33299353269, 33298892195.
- **2026-08-30 `infra` (b)** — `mutation-gate (0)` killed at 40 min (M1 is ONE class): split by RECORD, 5 shards, verdicts printed as they land. Drain: ingest its own `always()` step, retire-settled first, cap 350/budgets 327. Commit gate `--strict` refuses twins/off-host rows; `dry_run` digest dispatch; the 08-27 lag is GitHub's (§4). **NOT finished:** 491 item 3, 501, 502. Record: `docs/sessions/2026-08-30-infra-b.md`.
- **2026-08-30 `docs` (c)** — clause 4 (evidence, not adjectives); cross-lane debt: a filed diff is applied by the next lane in the file (`check_debt_on_touched_files`, 5 of 66 commits today); `next` reads master, the gate refuses new collisions. CI: `dc3a787` 33328309775 and `3453a2a` 33329623016 both `success` 13/13; `a13045a`/`6ef03c9` `failure` (HANDOFF over cap, mine). Record: `docs/sessions/2026-08-30-docs-craft.md`.
- **2026-08-30 `classifier` (b)** — drain fits one run: `LLM_CAP` 450 (the real bound), `REJUDGE_CAP` 250, fresh-reserve 80; bare-Israel rule REJECTED (10/11 FN). **NOT finished:** the 05:00 run; 464, 116, 503. Record: `docs/sessions/2026-08-30-classifier-b.md`.
