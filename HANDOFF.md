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
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | 2026-09-11 (`docs`, orchestrator) | PASS - `python tests/schedule_census.py --days 14` on 2026-09-11: `ISOLATED SINGLE-SLOT DROPS: 0`, `due 134 · fired 134 · not seen 0`; the recovery cron stays rejected |
| 2026-09-07 | infra | 7 mornings from 09-01: `Company intel:` backlog **median <= 10**, delta **<= 0 on >= 5 of 7**, `firmo` **left = 0, age <= 1** (`450`); `10:17` lag **< 180 min** (305) | 2026-09-11 (`docs`, orchestrator) | PARTIAL - digests 09-05..09-11 `registry backlog` 6, 7, 7, 9, 9, 10, 10: median **9** <= 10 PASS; delta <= 0 on **4 of 7** (wanted >= 5) FAIL; `firmo` `left=0` dated TODAY all 7 PASS; inbox issue 09:38-10:16Z six mornings, **10:50Z on 09-07** (digest started 10:02Z) |
| 2026-09-12 | registry | **the six folds fire unattended.** First `event: schedule` digest on a headSha ⊇ this commit: the `Roles:` line carries NO `claim conflicts` clause (was `claim conflicts 2 (Gong<-Gong.io, Port<-Port.io)` daily since 08-16); `alias folds:` names `autods<-AutoDS - Automatic Dropshipping Tools` superseded, and `Digital Turbine<-DT` superseded (a `digital turbine\|senior data scientist` record exists by then) or `left in place, no twin` — both are PASS, name which; `מנורה מבטחים החזקות<-` folds `left in place`; board `grep -c 'Direct Travel' docs/index.html` = **0** and one AutoDS card, not two | | |
| 2026-09-12 | registry | **the two repointed boards produce, unattended.** Same run's `collect:` stamp and `docs/index.html`: `Digital Turbine` ≥ 5 cards (Workday `digitalturbine/Digital_Turbine_External_Careers`, 7 IL live on 09-11, 2 accepted in a scoped run); `Cal (Israel Credit Cards)` ≥ 1 card with `unlock_calls` ≥ 1 — if 0, the row is honest but the `SCRAPE_VIA_UNLOCKER` export did not reach it, which is `infra`'s. The 06:00 self-heal must NOT have rewritten either row: `git log -p -1 --format=%H -- companies.csv` on that morning's self-heal commit | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | 2026-09-11 (`docs`, orchestrator) | FAIL - `registry_health.py --stale-boards` on 2026-09-11: `ABANDONED (newest >= 365d) 19` (wanted <= 17; was 18) - two aged in, none repaired. The 09-28 `zero-confirm 2026-08-29` clause is carried into the 2026-09-27 row |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | 2026-09-11 (`docs`, orchestrator) | PASS - audit-coverage run 34021992338 (09-06, schedule): `deep rung: 181 of 287 dark rows are due a Chromium render`, `recovered 34, unsupported 22, dark 124, unreachable 1 · BD searches used: 150`; commit 00aaacc `audit_seen.json: 316 -> 615 keys` |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | 2026-09-11 (`docs`, orchestrator) | PARTIAL - measured, the threshold pick is the 2026-09-11 `infra` brief's: 79 `persist_log.jsonl` lines; `scraped_cache.json` n=37, max lost/before **0.088** (36/410, 08-31), then 0.056, 0.036; `stale.json` **0.38** (41/108, 08-28); every other path 0.0 |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | 2026-09-11 (`docs`, orchestrator) | PASS - `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` hits 4eee7f5 (`discovery` 09-03), 6195aa6 (`finisher` 09-03, five rows answered), 7995b5e (`infra` 09-04); 0 non-cron commits 09-05..09-11, so no session ran to be stopped this week |
| 2026-09-04 | discovery | **the anonymised-employer gate fires unattended.** First `event: schedule` digest on a headSha containing `0a45de4`: `grep -c 'Stealth Startup\|Confidential Company\|Confidential Global Company\|Discreet Company' discovered_cache.json` = **0** (11 cards today, 7 of them `Stealth Startup`), and the step log's `cache: dropped N agency cards` is 11 higher than the 09-03 run's. No ACTIVE row may be lost: `check_invariants.py` still reads **1,195+ active** | 2026-09-11 (`docs`, orchestrator) | PARTIAL - `grep -c 'Stealth Startup\|Confidential Company\|Confidential Global Company\|Discreet Company' discovered_cache.json` = **0** PASS; `check_invariants.py` **1,363 active** PASS; run 33858255664 logs `cache: dropped 80 agency cards` vs 89 on 09-03 - LOWER by 9, not +11: the day's card mix moved and the +11 clause cannot be read as written |
| 2026-09-04 | classifier | **the gate reads the posting, unattended.** First `event: schedule` digest on a headSha containing this commit: `Zoll` published or named in `classify:` - the claim is it REACHES the tier; `llm N` at most **25** above 09-03's **89**; `re-judged` under 250; `roles.csv` `grep -c`: **0** `DoiT` (1 today), **1** `Investing` (2), **1** `נספרסו` (2); Prisma `description_len` **2617** | 2026-09-11 (`docs`, orchestrator) | PASS - run 33858255664: `Zoll Medical Corporation \| Business Operations, CMS` published (`roles.csv`, open since 09-04); `classify: ... llm 92` vs 89 on 09-03 (+3 <= 25); `rejudged 2`; 09-11 `roles.csv`: `DoiT` **0** (`doitintl` 1), `Investing` **1**, `נספרסו` **1**, Prisma `description_len` **2617** |
| 2026-09-05 | infra | **the archive step ran unattended and the ledger grew.** First `event: schedule` `jd-archive` run on a headSha ⊇ this commit: step log `[wayback] submitted N` with N > 0 and `requests` <= 140; `grep -c '"at":"2026-09-05' cloud_state/wayback_ledger.jsonl` >= N; the 09-06 digest's `Stage order:` carries `wayback: 2026-09-05`; open one `il.linkedin.com` `snap` by hand - a posting or a login wall? Throttled/`host_parked` > 0 is a reading, not a failure | 2026-09-11 (`docs`, orchestrator) | PASS - jd-archive run 33974602663 (09-05, schedule): `[wayback] submitted 72, failed 2, backlog 4835, ... throttled 0, requests 112`; `grep -c '"at":"2026-09-05' cloud_state/wayback_ledger.jsonl` = **84** >= 72; the 09-06 digest carries `wayback: 2026-09-05`; snap `20260904164942` of the Migdal `il.linkedin.com` posting opens as the posting (`<title>Business Analyst ב Migdal Group — Petah Tikva`, דרישות present), not a login wall |
| 2026-09-05 | registry | **the guard holds unattended, and the cap is not the lever.** The 01:40/12:53 `auto-expand` runs on a headSha ⊇ this commit leave `check_invariants.shared_boards` empty; the 12:30 `jd-archive` stamp reads `submitted` <= 115 and `requests` <= 140 whatever `WAYBACK_DAY_CAP` says, and `backlog` > 4,659 until `577` lands | 2026-09-11 (`docs`, orchestrator) | PASS - `check_invariants.py` on 2026-09-11 prints no B2 `board(s) read by more than one active row` warning after seven `auto-expand` runs; jd-archive stamps 09-05..09-10: `submitted` max **72** <= 115, `requests` max **140** (09-08) <= 140, `backlog` **5,613** on 09-10 > 4,659 - `577` still open |

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

- **2026-08-24 → 2026-08-31, 63 session lines, ten lanes** — folded to pointers; numbers, CI run ids and defects are in `docs/sessions/2026-08-*.md` (`registry` (d) in `2026-08-30-infra-b.md` §0). NOT finished: 491/501/502, 464/116/503/504, 505-508, 459/511, 500@roles, 529-532, `261`, `512`-`514`, `516`-`520`, `530`, `534`-`538`.
- **2026-09-01, five sessions** — `classifier` (57-row audit, `v3.0f84ab84`), `jd-text` (four guards over WHOSE posting a text is), `roles` (one judge gates csv+board+mail), `registry` (alias veto = `name in registry_names`), `infra` (the judge step had no token; eight shards; caps pre-push). Records: `docs/sessions/2026-09-01-*.md`. NOT finished: `535`, `542`-`544`, `546`-`557`, `559`-`563`.
- **2026-09-02 `roles`** - a retraction bound to a LIVE role through another posting's stray `seen_id` (`545`); a fold the ledger had recorded re-collided in `merged` every morning. Own-url binding over BOTH stores; a settled twin group drops. CI **33670937402 16 of 16 green**, both inherited reds closed (`558@registry`, `564@jd-text`). **NOT finished:** `555`-`557`, `565`. Record: `docs/sessions/2026-09-02-roles.md`.
- **2026-09-02 `classifier`** — 09-01's deferrals closed: **7 withdrawn, 6 kept**. A closed row is judged by the LIVE contract on its own READABLE text — sparing Parametrix, Ballerine and a Prisma line two waves killed on another posting's JD. `542`: its "no shared predicate" was **wrong** (22 reach all three). CI `33678158696` **16/16**. **NOT finished:** `566`, `567`. Record: `docs/sessions/2026-09-02-classifier.md`.
- **2026-09-03 `discovery`** — do DESCRIPTION terms reach analyst roles our title keywords miss? **10 probes, 1,163 postings, 53 new employers, 0 new in-scope roles**; **0 came via an analyst-shaped posting**, 30 marker-densest gate-rejected postings judged **0 in scope**. Wired nothing (`568`-`570`). Shipped `is_anonymous_employer` (8 of 2,757, **0 active**). CI `33756838492` **15/16**, `guard` red INHERITED. Record: `docs/sessions/2026-09-03-discovery.md`.
- **2026-09-03 `finisher`** - four defective rows and one gate phrase. `_desc_appealed` reads the posting (23 cards, 0 BD by construction); Prisma repaired in BOTH stores (`jd-text`); `doit`->`doitintl` declared (`company-intel`); two url-precise retractions (`roles`); marker arm REFUSED (`568`); `570` closed so `guard` is green again. CI `33793856880` **16/16**. **NOT finished:** `571`-`574`. Record: `docs/sessions/2026-09-03-finisher.md`.
- **2026-09-04 `infra`** — postings vanished before disputes settled; nothing wrote to the Archive. `archive_evidence.py` (first step of `jd-archive.yml`): 100 postings + 25 boards a day to Save Page Now, text-free lines in `cloud_state/wayback_ledger.jsonl`, `wayback` stamp + `Stages:` clause. Live **2 of 3**, backlog **4,603**. CI `33881713053` **15/16**, `guard` red = `576@registry`. **NOT finished:** the 09-05 row; `445`. Record: `docs/sessions/2026-09-04-infra.md`.
- **2026-09-04 `registry`** — `576`: `Aristocrat (Product Madness)` parked `alias-of Aristocrat`. WHY: `_boards_now` keyed boards on the token and `resolve_llm` spelled the Workday token its own way; it now keys the ADDRESS too, and `resolve_llm` writes the composite. Dispensation `WAYBACK_DAY_CAP` 100→150 — `WAYBACK_REQ_CAP` 140 binds first (`577@infra`). OWED **35**. CI `33912078326` **16/16**. **NOT finished:** `577`. Record: `docs/sessions/2026-09-04-registry.md`.
- **2026-09-11 `registry`** — six employers published one opening under two names; every declaration was dead because the alias string was itself a row (`571`, third time). A parked row's dated `alias-of <R>` verdict is now READ, and folds when `ALIASES` agrees: 7 pairs, `571` CLOSED. Digital Turbine repointed to Workday (0→7 IL). **NOT finished:** `578`, `579`. Record: `docs/sessions/2026-09-11-registry.md`.
