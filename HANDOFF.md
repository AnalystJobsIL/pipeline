# Handoff — current state

**What this file is:** the state of the system *right now* — what changed last session,
what is known-broken, what nobody has claimed. Nothing else.

**Three caps.** `docs/check_docs.py` holds this file to 250 lines, 3,200 words and 60 words
per line. The line cap alone was defeated — 247 lines and **65,338 bytes**, eighteen whole
narratives on one line each — so the three reinforce: a narrative that cannot fit one line
wraps, wrapping blows the line count, and that pushes it to `docs/sessions/`.
**The caps are PRE-PUSH only since 2026-09-01** (`infra`): in CI they caught races — three
doc-only reds at +1/+3/+6 words on 08-31. The shape check still runs there.

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
`Morning check <date>:` sentences were buried in prose here and **not one had ever been
answered**, while `### Tel Aviv` and `### Jobgether` shipped as employer headings in the
2026-08-26 email against checks saying neither would.

A verdict is `PASS`, `FAIL — <what actually happened>`, or `N/A — <why>`, and it carries a
**grep-able string**, never an adjective. Answered rows older than 7 days move to
`docs/morning-checks.md`.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-09-02 | classifier | first scheduled digest on a headSha containing this commit: the `classify:` line names **`v3.0f84ab84`**; a `roles withdrawn` alarm names **34** roles (21 newly withdrawn + 13 whose reason string this commit rewrites — `_record_run` appends on a reason change too) and `roles retraction lifted` names **Parametrix**, which returns reading `class_decision=reject` until `544` lands; rows **137** (157 − 21 + 1), or **134** if `roles`' pending-exclusion and Nestlé/אסם fold land too — both BEFORE that morning's intake, which added 4 on 09-01, so a higher count is not a failure; no `roles retraction unmatched`; empty `class_decision` still 0 | run `33613841435` | PASS on all six. `contract v3.0f84ab84 re-judged 250/cap 250 + 96 stale-yes/cap 150, served stale 84 (15 unreachable)`; `roles withdrawn 34 role(s)`; `roles retraction lifted for 1 role(s) ... Parametrix GmbH`; 0 `retraction unmatched`; empty `class_decision` 0 **of 151**. Rows 151 not 137 is its own before-intake clause. Parametrix returned reading `class_decision=reject` |
| 2026-09-03 | classifier | `roles.csv`: **0** `class_decision=reject` but the `parametrix` row; `roles.csv.meta.json` `removed[]` names all **7**; `roles withdrawn` names 7; no `retraction unmatched`; Gamida, Holisto x2, Ballerine, Prisma still published. Calculum's `Junior Data/Financial Analyst` and IAI's `תהליכי בקרה ו-AI` read `accept`, `llm` up ~**2** not 30; Prisma and Ballerine still published; Zoll absent **by design**. `served stale` under **84**, `re-judged` under 250 | | not yet due |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-09-01 | infra | first scheduled digest after 08-30: log `cron watch: window_days=3`, subject `(schedule run <id>)`, `Stages:` `ci …`/`cron …` or silent; inline filler `bd_tried` > 0 (448); a `tests.yml` run on another lane's commit: 10 jobs, verdicts on all | 2026-09-01 | PASS on the stamps - run `33494404810`: `cron watch: window_days=3 ... dropped=0 late=0`, subject `(schedule run 33494404810)`, `ci: red_streak=0`. Two corrections to the claim: `bd_tried` is not a printed key (the filler says `Bright Data cap bound at 30`), and CI is **13** jobs not 10 - `33448520621` 13/13 |
| 2026-09-02 | infra | **the quality judge has a token.** First `event: schedule` digest on a headSha ⊇ this commit: `enrich` stamp `matched_llm_unavailable=0`, `matched_llm_calls` > 0, no `jd-quality-unavailable` clause. `llm-no-token` = the secret is missing from some other step; `llm-auth` now means one was sent and refused | | |
| 2026-09-02 | infra | **eight shards, all under the wall.** First `tests.yml` at or after this commit: `mutation-gate (0)`..`(7)` `success`, **16 jobs** (was 13), every `timing    wall` under **1,800 s**, no `::warning::mutation shard walled` | 2026-09-01 | PARTIAL, early - the wall clause PASSES twice: `33522769201` walled **1126-1611 s** and `33529418065` **1147-1578 s**, all 16 shard-runs under 1,800, no warning, 16 jobs. The `all success` clause fails on SURVIVING records, not the clock: 6 of them, `roles`' five fixed the same evening, jd-text's open (`564`) |
| 2026-09-02 | infra | **the text is on Pages and the meta says so.** After the first digest on this commit: `curl -sI .../board/roles_text.jsonl` is `200` (same for `roles_archive.csv`), and the meta reads `description_text.published_on_pages: true` + `archive.published_on_pages: true`. Still `false` ⇒ the env names never reached `build_meta` (498) | | |
| 2026-09-07 | infra | 7 mornings from 09-01: `Company intel:` backlog **median <= 10**, delta **<= 0 on >= 5 of 7**, `firmo` **left = 0, age <= 1** (`450`); `10:17` lag **< 180 min** (305) | | not yet due |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0`; above that, strip that run's verdicts | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-02 | registry | **the Oak fold fires unattended, and the repairs hold** (`522`): `grep -c '^Oak,' companies.csv` = **0**, `oak\|product analyst` gains a `superseded_by` in `roles.jsonl` (empty ⇒ the fold refused and nothing records why), and `Failed companies:` names neither **Sisense** (repaired greenhouse→ashby) nor `Decart`/`Akamai` (parked) | | |
| 2026-09-02 | registry | the query-URL parks HELD without a session: `python registry_health.py --query-urls` prints `parked by the audit (in the hunt's pool): 20` (or more), `grep -c 'query-filter 2026-08-30: filter' companies.csv` >= **19**, and no 19:00 log since 08-30 carries `verified N IL via jobs.comcast.com`; `grep -c 'query URL' <listing-hunt log>` >= 1 shows the guard firing | | |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due until 2026-09-07 (`audit-coverage.yml` is `0 4 * * 0`; the first Sunday after the deep rung shipped is 09-06) |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | | not yet due |
| 2026-09-02 | jd-text | first schedule digest ⊇ this commit: **`matched_llm_calls` > 0 and `matched_llm_unavailable` < `matched_llm_candidates`** (a Counter always PRINTS `matched_llm_refuted`, so its presence proves nothing — wave B); `techbiz global` not back at 6,000 soup chars; **Ballerine still 1,662, not 4,000** (both stores were repaired; the cache card is the thing that would hand it back); Prisma keeps Product-Analyst text | | |
| 2026-09-02 | docs | **the escalation caught something rather than merely being green.** `git log --since=2026-08-30 -p -- HANDOFF.md` shows at least one row ANSWERED or re-dated with `until` by a lane other than `docs`. Zero in three days means the rule is being satisfied by not writing rows at all, which is the failure it replaced wearing a different coat | | not yet due |
| 2026-09-01 | company-intel | first unattended digest on a headSha ⊇ the `display_name` commit logs `display_names=71 (+0/-0) divergent=56 sectors_folded=0` (±drift) in step `firmo_drain` | | not yet due |
| 2026-09-01 | company-intel | **a live role is never "cannot identify".** First unattended digest, headSha ⊇ this commit: `registry backlog 0` (a FLOOR — rows added overnight lift it); no BOARD company refused `model could not identify the name`, whose honest replacement is `unidentified despite role evidence`; `display_names=84` (was 71 before this commit's `Landa` + `Kidum`) | | not yet due |
| 2026-09-02 | company-intel | **a transient no longer costs the research; the anchor makes the retry answerable.** `N transient, retried next run` never beside `claude unavailable after N blurbs calls (transient:`; `registry backlog` **<= 12**, delta **<= 0** | | not yet due |
| 2026-09-01 | render | first digest after company-intel's `display_name` commit: mail heading shows the brand (`### Faye`-class), board cell agrees; finbounce stays `finbounce`, no `display-collision` (refused at source) | | not yet due |
| 2026-09-02 | roles | **the publish gate holds unattended.** First `event: schedule` digest on a headSha ⊇ this commit: **no published row has `description_quality` `snippet` or `none`**; `grep -c 'Manager Bi' docs/index.html` = **0**; `Roles:` carries `weak N (S structural, P pending)`; `reconciliation` holds with `pending_excluded`; the אסם fold logged ONCE (`superseded` 10⇒11) and never on 09-03 | | not yet due |
| 2026-09-03 | roles | **the retraction lands on one record and the fold stops colliding.** First `event: schedule` digest on a headSha containing this commit: `Stages:` carries NO `roles seen-id collision`; `grep -c 'Data Insights Operations' cloud_state/roles.csv` = **0** while the `percepto` Senior Product Analyst record is still `open` in `roles.jsonl`; `roles withdrawn` names **Percepto Data Insights Operations**; no `roles retraction unmatched` | | |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | | not yet due |
| 2026-09-04 | discovery | **the anonymised-employer gate fires unattended.** First `event: schedule` digest on a headSha containing `0a45de4`: `grep -c 'Stealth Startup\|Confidential Company\|Confidential Global Company\|Discreet Company' discovered_cache.json` = **0** (11 cards today, 7 of them `Stealth Startup`), and the step log's `cache: dropped N agency cards` is 11 higher than the 09-03 run's. No ACTIVE row may be lost: `check_invariants.py` still reads **1,195+ active** | | |

## State at handoff — 2026-09-01 ~17:00 UTC, every number re-derived

Every cell carries the command that re-derives it; the 08-30 table was stale in all five.

| | | how |
|---|---|---|
| registry | **2,127+ rows · 1,132+ active · 0 orphans** | `python check_invariants.py` |
| by tier | **556 native-ATS · 575 scrape · 1 discovery** | `python registry_health.py` |
| intake queue | **37 OWED** (546 on 08-31; the drain runs now) | `python queue_state.py` |
| last digest | **2026-09-01**, `scanned=1130`, **10 emailed** | `digests/latest.md` |
| guards | **1,766 passed · 13 skipped · 0 failed** locally | `python -m pytest` (not `-q`) |

**Green here is not green in CI**, and on a commit master has moved past. Each lane's line names its run.

## Watch list for the next session

0. **`python digest_watchdog.py` is still not installed** (`292@infra`, operator action) — the only tripwire off GitHub's scheduler.

0b. **Before writing a patch script that emits YAML**, read
   `test_no_workflow_run_block_fakes_a_line_continuation`: a literal backslash-n where a
   continuation was meant is valid YAML, `bash -n` misses it, and it breaks every run.

0. **Active rows with an all-time-high of ZERO — a COMMAND, not a number** (it has been wrong
   five times): `python confirm_zero.py --scrape-only` audits the pool and
   `cloud_state/zero_confirm.json` is the durable per-row answer (2026-08-29: 215 at the start,
   ~139 answered, none recorded empty without a rendered page and an LLM read). Two sibling
   classes it cannot see, needing a baseline of exactly 0: region variants (`--regions`, 32 rows,
   1 real) and abandoned tenants (`--stale-boards`, 18 rows over a year old, one EMAILED).
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
6. **~24 active rows are re-checked by NOTHING, which falsifies `ARCHITECTURE.md` §2's headline
   claim that every state but `defunct:`/`domain-dead` is re-checked** (`registry`, 2026-08-27).
   An ACTIVE `israel_scoped` fetcher returning 0 never enters `stale.json` —
   `health.zero_is_a_measurement()` exempts it for a documented reason (25 healthy Workday boards
   clogged the self-heal on 08-24) — so it never reaches `resolve_broken.candidates()`, and every
   parked pool excludes it on `active == false`. `repair_dead_urls` has no active filter but
   selects on a hostname that stops resolving, which a live Workday tenant's does not.

5. **GitHub dispatches these crons when it feels like it** — a dropped or +720-min-late slot is a `cron …` clause on the mail's `Stages:` line (`schedule_census.py --alarm`); the recovery-cron decision is the 09-10 row.

## Open items — highest value first

1. **~370 parked rows carry a triage mode and the 19:00 hunt is time-budgeted (200 min)**, so
   expect a trickle; `extract-gap` needs no search and lands first. **Run `python
   registry_health.py` for today's pools** — the table that sat here was superseded within a day.
2. **iCIMS** is the one platform with rows and no native fetcher (recipe: `ARCHITECTURE.md`
   §6). The old "3+ rows earns a fetcher" rule was replaced by the operator on 2026-08-26:
   one row earns it.
3. **`CLAUDE_CODE_OAUTH_TOKEN` may expire.** Symptom: `LLM calls this run: 0` with a large
   `llm_failed_fallback`. Re-run `claude setup-token` and reset the secret.
4. **SerpApi did NOT reset on 2026-09-01** — measured that morning: `total_searches_left: 0`,
   `this_month_usage: 250`, Free Plan. Five docs say "exhausted until 2026-09-01", which reads as
   "back today". The working search stays `deep_validate.google_via_unlocker` (`4@discovery`).
5. **`--census` rewrites its own baseline every digest run**, so a pool alarms at most once
   and a slow drift never alarms at all. `315@registry`.

*Items (6)-(7), closed and verified 2026-08-27, pruned 2026-08-30 for the word cap — the
verifications live in `docs/sessions/2026-08-2[6-7]-*.md`.*

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24 → 2026-08-31, 58 session lines, ten lanes** — folded to pointers, all at the word cap (`registry` 08-31 by `company-intel`: OWED 546→1, `510`, CI 33366050922 13/13; `classifier` 08-31: 33→0, 14 withdrawn, CI 33412050175 13/13; 338, 361). Records: `docs/sessions/2026-08-*.md`; `registry` (d) in `2026-08-30-infra-b.md` §0. NOT finished: 491/501/502, 464/116/503/504, 505-508, 459/511, 500@roles, 529-532.
- **2026-08-31, five sessions** — `roles` (a+b), `jd-text` (a+b), `company-intel` (a+b), `registry` (b). Numbers, CI run ids and the defects each wave found are in `docs/sessions/2026-08-31-*.md`; folded here for the cap. NOT finished: `261`, `498`, `512`, `513`, `514`, `516`-`520`, `530`, `534`-`538`.
- **2026-09-01 `classifier`** — 57-row audit adjudicated: **21 withdrawn, 1 lifted, 7 refuted, 7 deferred**; three records close `531`+`532`; bump → **`v3.0f84ab84`**, rows 157→**137**. Caught first: superseded verdicts ordered by contract HASH, which this bump would have detonated (`541`). CI `33514763993` **10/13**; no red is this diff's, each attributed in the record. **NOT finished:** 09-02 proof, `542`-`544`. Record: `docs/sessions/2026-09-01-classifier.md`.
- **2026-09-01 `jd-text`** — 8 published rows carried another role's text; 4 repaired through the rungs, in BOTH stores. Four guards over WHOSE posting a text is. Two waves found 10 defects in my own diff. CI `33521239034`: `guard`+`guard-kill` **success**, 1,796 passed; `rehearse (worst, seed 1)` red is INHERITED (`558@registry`). **NOT finished:** `535`, `550`-`554`. Record: `docs/sessions/2026-09-01-jd-text.md`.
- **2026-09-01 `roles`** — the ruling reached the dataset only, and only structural blockers: board and mail published two pending weak rows, burned in `sent`. One judge now gates csv+board+mail. Nestlé/אסם sat in no evidence bucket. **157→154, every row `jd`.** 4 of my own mutations survived (`564`), repaired; CI 33526272540 **14/16**, both reds inherited. **NOT finished:** `555`–`557`. Record: `docs/sessions/2026-09-01-roles.md`.
- **2026-09-01 `registry`** — a parked NON-EMPLOYER on a declared alias string cancelled the roles fold (`522`): the veto is `name in registry_names`, any state. `Oak` renamed; Landa's rows are one (`538`); `526` five→TWO; Sisense repaired, Decart+Akamai parked. CI `33521632298` **failure, 7/13** — mine KILLED, reds are other lanes' survivors + inherited `558`. **NOT finished:** `546`-`549`, `559`, `563`. Record: `docs/sessions/2026-09-01-registry.md`.
- **2026-09-01 `infra`** — the jd-quality judge 401'd three mornings: its step carried
- **2026-09-02 `roles`** - a retraction bound to a LIVE role through another posting's stray `seen_id` (`545`); a fold the ledger had recorded re-collided in `merged` every morning. Own-url binding over BOTH stores; a settled twin group drops. CI **33670937402 16 of 16 green**, both inherited reds closed (`558@registry`, `564@jd-text`). **NOT finished:** `555`-`557`, `565`. Record: `docs/sessions/2026-09-02-roles.md`.
  no token while classify made 372 calls in the same job. An anchor test reddened under
  every mutant, so its shard scored everything `killed` (`540` — really 79 of 86); all five
  were past the wall. Fixed, plus `498`, `458`, `515`, caps pre-push. **NOT
  finished:** the 09-02 rows prove the rest; `560`-`562`, `564` (6 survivors my 8 shards
  reported; `roles` fixed 5 that evening, jd-text's is open). CI `33522769201` **10 of 16**,
  then `33529418065` **14 of 16**, both reds attributed: `550@registry` and `564`.
  Shards **1147-1578 s**, all under the wall, no warning.
  Record: `docs/sessions/2026-09-01-infra.md`.
- **2026-09-02 `classifier`** — 09-01's deferrals closed: **7 withdrawn, 6 kept**. A closed row is judged by the LIVE contract on its own READABLE text — sparing Parametrix, Ballerine and a Prisma line two waves killed on another posting's JD. `542`: its "no shared predicate" was **wrong** (22 reach all three). CI `33678158696` **16/16**. **NOT finished:** `566`, `567`. Record: `docs/sessions/2026-09-02-classifier.md`.
- **2026-09-03 `discovery`** — do DESCRIPTION terms reach analyst roles our title keywords miss? **10 probes, 1,163 postings, 53 new employers, 0 new in-scope roles**; **0 of 53 came via an analyst-shaped posting**, and the 30 marker-densest gate-rejected postings judged **0 in scope**. Wired nothing (`568`, `569`). Shipped `is_anonymous_employer` (8 of 2,757 names, **0 active**). Record: `docs/sessions/2026-09-03-discovery.md`.
