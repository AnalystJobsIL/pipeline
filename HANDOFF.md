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
| 2026-09-01 | classifier | published `roles.csv`: empty `class_decision` = **0** (33 today), ~**153** rows; the log carries `backfill: 0 verdict-less` and `classify: … v3.7cb6831f`; a one-way `drain moved` alarm is EXPECTED | | not yet due |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-08-31 | infra | first `listing-hunt` run (`event: schedule`, headSha ⊇ the 08-30 infra (b) commit) prints `retire-settled: queue N -> M` BEFORE its `queue-resolve-search:` lines, and `ingested N new attempts` from the step `Ingest the drain's attempt log`; quote its `S s/name over K scored` line into `491` item 3 (6 shards vs a 45-min step) | | |
| 2026-09-01 | infra | `tests.yml` on ANOTHER lane's push: `mutation-gate (0)`..`(4)` all `success`, every shard's `timing    wall` under **1,800 s**; over that ⇒ add a matrix entry, never the budget | | not yet due |
| 2026-08-31 | infra | the first `event: schedule` digest on a headSha ⊇ the 08-30 infra (b) commit logs `persist_state: pushed` and `relay notified:`, and no `dry run:` line | | not yet due |
| 2026-09-01 | infra | first scheduled digest after 08-30: log `cron watch: window_days=3`, subject `(schedule run <id>)`, `Stages:` `ci …`/`cron …` or silent; inline filler `bd_tried` > 0 (448); a `tests.yml` run on another lane's commit: 10 jobs, verdicts on all | | not yet due |
| 2026-09-07 | infra | 7 mornings from 09-01: `Company intel:` backlog **median <= 10**, delta **<= 0 on >= 5 of 7**, `firmo` **left = 0, age <= 1** (`450`); `10:17` lag **< 180 min** (305) | | not yet due |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0`; above that, strip that run's verdicts | | |
| 2026-09-01 | registry | **the `out/` fix works UNATTENDED and a disarmed key would now say so.** Tonight's `listing-hunt` (`event: schedule`, headSha >= this commit; it starts 21:00-22:00Z, not 19:00): the four `queue-resolve-search: N names` lines sum **>= 60** (selectable was **65** at 14:20Z, capacity 112 - NOT the 08-30 row's 112), `s1/` lines carry **non-zero url counts**, `ingested N new attempts` **N >= 60**, **4 `[bd-spend]` lines**. Next digest's `queue:` stamp: `searched_recently >= 60`, `empty_search_share` **< 0.1**, no `drain_alarm`. **Judge on `ingested`, not `owed`** - `owed` read 369 in the 08-31 mail and 65 by 14:20Z (that run's dispose ran after its own stamp) and intake adds 92-169/day. FAIL shapes now self-name: all `s` lines `0 urls` + `BOUGHT NOTHING` = dead key; `IDLE ... but the shards BOUGHT n` = died mid-run; `IDLE ... NO Bright Data credit` = never started | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-02 | registry | the query-URL parks HELD without a session: `python registry_health.py --query-urls` prints `parked by the audit (in the hunt's pool): 20` (or more), `grep -c 'query-filter 2026-08-30: filter' companies.csv` >= **19**, and no 19:00 log since 08-30 carries `verified N IL via jobs.comcast.com`; `grep -c 'query URL' <listing-hunt log>` >= 1 shows the guard firing | | |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due until 2026-09-07 (`audit-coverage.yml` is `0 4 * * 0`; the first Sunday after the deep rung shipped is 09-06) |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | | not yet due |
| 2026-08-31 | roles | **BUILT, NOT YET PUBLISHED: the retraction lands in the PUBLIC file only when a digest run's publish step runs** (today's schedule run exited 1 on a benign delivery refusal, so Pages still serves the 09:15 manual run's file with all the bad rows). Run `curl -s https://analystjobsil.github.io/board/roles.csv \| grep -c 'Comcast\|Jobgether'` → **0** (3 on 08-30) and `curl -s https://analystjobsil.github.io/board/roles.csv.meta.json \| python -c "import sys,json;d=json.load(sys.stdin);print(d['generated_at'],d['rows'],d['published_on_pages'],len(d['removed']))"` → a 2026-08-31 stamp, `True`, 12+; the mail's `Roles:` says `withdrawn 2` and `Stages:` `roles withdrawn 2 role(s)`. Still 3 ⇒ the publish step was skipped again — check `steps.pipeline.outcome` on that run | 2026-08-31 | PASS — run `33387229779` (schedule, `f2f272b`): board-repo file comcast/jobgether **0**, meta `2026-08-31 · 167 · True · removed 20`; mail `withdrawn 3 · purged 10`. Pages CDN lags: no `pages-build-deployment` run yet |
| 2026-09-01 | roles | Pages csv header carries `company_registry`+`description_quality`; `grep -c ',finbounce,\|,Checkout,'` → **0**; `Faye,withfaye` present; `zipher\|data analyst` url on `zipher.ai` | 2026-08-31 | PASS, early (board-repo copy) — header ✓; finbounce/Checkout **0**; `Faye,withfaye` ×1; zipher url `zipher.ai` len 1859 `jd`. Residuals filed: `entrypoint` (`512`), LTX/Navan on Indeed, full JDs (`261`) |
| 2026-08-30 | jd-text | the `enrich` stamp after both runs carries **`archive_ran` = 1** (the night survived the morning), **`scrape_thin_remaining` <= 760** and **`matched_llm_unavailable` = 0** | 2026-08-31 | FAIL — `matched_llm_unavailable=16` (`llm-auth9`, 08-30 16:55Z stamp): the LLM seam auth-refused on the runner (Open item 3), not a fetch failure; `archive_ran=1` and `scrape_thin_remaining=300` PASS |
| 2026-09-01 | jd-text | first `event: schedule` digest on headSha ⊇ the Indeed-rung commit: enrich log carries `bd/ok-indeed`, TransUnion + אסם pass `looks_like_jd` in that evening's committed `seen.db`, no `matched: bd-spent(... 0 filled)` clause (the stamp SUMS flows if a session also ran) | | |
| 2026-09-02 | docs | **the escalation caught something rather than merely being green.** `git log --since=2026-08-30 -p -- HANDOFF.md` shows at least one row ANSWERED or re-dated with `until` by a lane other than `docs`. Zero in three days means the rule is being satisfied by not writing rows at all, which is the failure it replaced wearing a different coat | | not yet due |
| 2026-08-31 | docs | **the session-start hook actually runs.** A session opened in this repo shows a `tree: N behind origin/master ...` line in its context before it reads `CLAUDE.md`. It is a hook in a committed `.claude/settings.json` and it CANNOT be tested from inside the session that writes it, so it ships under the same rule as any scheduled step: unverified until something nobody started produces the line. If it is absent, the schema or the Windows shell is wrong - `claude --debug` names it - and the fallback is `python docs/check_docs.py --tree`, which needs no hook | | not yet due |
| 2026-08-31 | docs | **the three tree/row/unattended guards pass ON A RUNNER.** `gh run list -R AnalystJobsIL/pipeline --workflow tests.yml --limit 1 --json headSha,conclusion` shows this session's sha and `success`, and the run log carries the `CI checkout: shallow=... origin/master=... commits=...` line from `test_ci_itself_confirms_why_the_tree_check_cannot_run_there`. They passed on every laptop and failed on every push until now, which is the only reason `tests.yml` had this session's name on it | 2026-08-30 | PASS, early - `Unit guards` = **success** on runs 33293548117, 33294213125, 33294986316 and 33295877346 (all four cancelled LATER, at step 9). The runner reported `CI checkout: shallow='true' origin/master='61bbc99a' commits='1'`, which corrected the reason: origin/master IS the built commit, so `behind` is 0 by construction |
| 2026-08-31 | company-intel | the first unattended digest after this push prints `registry backlog N (±D since 2026-08-30)` and `bulk cron: … of N to do` on `Company intel:`, no `Tel Aviv` blurb drop; `(first measurement)` on 08-31 = the `intel` stamp lost to persist (`451`) | 2026-08-31 | PASS — run `33387229779`: `registry backlog 28 (+7 since 2026-08-30)`, a signed delta (the `intel` stamp survived persist); `bulk cron: … 13 of 15`. **The gap does NOT hold unattended: 21 → 28.** |
| 2026-09-01 | company-intel | first unattended digest on a headSha ⊇ the `display_name` commit logs `display_names=71 (+0/-0) divergent=56 sectors_folded=0` (±drift) in step `firmo_drain` | | not yet due |
| 2026-09-02 | company-intel | **a transient no longer costs the research; the anchor makes the retry answerable.** `N transient, retried next run` never beside `claude unavailable after N blurbs calls (transient:`; `registry backlog` **<= 12**, delta **<= 0** | | not yet due |
| 2026-08-31 | render | the first unattended mail's H1 number == `grep -cE '^- \*\*[^*]*\*\*( — [^ ]+)? · 📍 ' digests/latest.md` no `email subject says` line; `same-posting` names both 08-30 pairs unless `registry` parked them (`487`) | | not yet due |
| 2026-09-01 | render | first digest after company-intel's `display_name` commit: mail heading shows the brand (`### Faye`-class), board cell agrees; finbounce stays `finbounce`, no `display-collision` (refused at source) | | not yet due |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | | not yet due |

## State at handoff — 2026-08-30 ~09:30 UTC, every number re-derived

Every cell below carries the command that re-derives it — the 08-27 table here was wrong
in two cells; the command is what keeps this honest.

| | | how |
|---|---|---|
| registry | **2,045 rows · 1,099 active · 946 parked · 0 orphans** | `python check_invariants.py` (it prints 2,046: it counts the header) |
| by tier | **525 native-ATS · 573 scrape · 1 discovery** | `python registry_health.py` |
| intake queue | **557 owed of 572** (210 at 09:xx) | `python queue_state.py` |
| last digest | **2026-08-29**, `scanned=1000`, **4 emailed** (no 05:00 slot has fired at 05:00 since 08-26) | `digests/latest.md` |
| guards | **1,469 passed · 12 skipped · 0 failed** locally at `06f07cd` | `python -m pytest` (not `-q`) |

**Green here is not green in CI**, and on a commit master has moved past. Each lane's line names its run.

## Watch list for the next session

0. **`python digest_watchdog.py` is still not installed** (`292@infra`, operator action) — the only tripwire off GitHub's scheduler; a dropped slot is otherwise just a `cron …` mail line.

0b. **A patch script wrote a literal backslash-n into `daily-digest.yml` where a
   continuation was meant** — syntactically valid (`bash -n` misses it), and it would have
   broken every run, daily. Guard: `test_no_workflow_run_block_fakes_a_line_continuation`;
   **read it before writing a patch script that emits YAML.**

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
3. **`cloud_state/seen.db` is 1.54 MB** and still holds a `firmographics` table that also
   travels as JSON; dropping it and VACUUMing is the biggest single win on the daily binary.
4. **iCIMS is the only unsupported ATS left** — see Open items 2; `registry_health.py
   --ats` is derived and correct. HiBob is at **1** active row, moving away from the
   3-row trigger.
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

5. **GitHub dispatches these crons when it feels like it** — a dropped or +720-min-late slot is a `cron …` clause on the mail's `Stages:` line (`schedule_census.py --alarm`); the recovery-cron decision is the 09-10 row.

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

- **2026-08-24 → 2026-08-31, 58 session lines, ten lanes** — folded to pointers (338, 361), all at the word cap. Records: `docs/sessions/2026-08-*.md`; `registry` (d) in `2026-08-30-infra-b.md` §0. NOT finished: 491/501/502, 464/116/503/504, 505-508, 500@roles, 529-532 (`classifier` 08-31: `class_decision` 33 → 0, 14 withdrawn, `v3.7cb6831f`). `docs` (c) CI `3453a2a` 33329623016 `success` 13/13.
- **2026-08-31 `registry`** — `owed` said 546, meant 172, now **1**: OWED is the drain's own selection, split from on-cadence and answered-on-disk; `queue` and `intel` reach the mail. Twin guard on five writers; `identity_ok` no longer vouches for any page (`510`); the drain had no `out/` dir. CI `33366050922` **success** 13/13. **NOT finished:** `459` (needs company-intel), `511`. Record: `docs/sessions/2026-08-30-registry-e.md`.
- **2026-08-31 `roles`** — five public-csv defects: board-url donation + aggregator-url ratchet (Zipher), posting-key claim guard (`488`), `description_quality`, `company` brand + `company_registry`, `489` line; two Opus waves' 11 breaks fixed+pinned. CI `33386238895` 12/13 `success`; sole red inherited (`514`). Proof: the rows above. **NOT finished:** `498`, `512`, `514`, `261`. Record: `docs/sessions/2026-08-31-roles.md`.
- **2026-08-31 `jd-text`** — Indeed "auth-walled" falsified: the SERP `vjk=` pane fills **90 of 92** cached postings raw (`paid_only`, cap 8/night); marker bar + `_after_the_wall` fix the long-failing rows (14→11→4 structural). 104 credits; `468` applied, `421` closed 08-29. CI `f2f272b` 33386238895 12/13 `success` (`rehearse worst,1` red INHERITED since `feb38a5`). **NOT finished:** the 09-01 row, `443`-half, `513@registry`. Record: `docs/sessions/2026-08-31-jd-text.md`.
- **2026-08-31 `registry` (b)** — `514` misfiled: no overwrite (the 220 cap evicted, by design); the red was retry's OWN segment carrying `validate_empty`'s only selector. `_fold_empty` carries it forward; `_keep_selectors` refuses on a saturated cell. The restore is REFUSED with the measurement. A disarmed drain was INVISIBLE — preflight plus `empty_search_share`/`bd_spend`. Intel 22→18. **NOT finished:** `513`, `516`-`520`. Record: `docs/sessions/2026-08-31-registry.md`.
- **2026-08-31 `company-intel`** — the backlog was built from the EMPTY STRING: the bulk pass asked `research_company(name, "")`, so 21 names struck `could not identify`; every retry re-asked it. Anchors now; a transient blurb no longer skips research. **28 → 4**. **NOT finished:** 521-528. Record: `docs/sessions/2026-08-31-company-intel.md`
