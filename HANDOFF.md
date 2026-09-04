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
| 2026-09-03 | classifier | `roles.csv`: **0** `class_decision=reject` but the `parametrix` row; `roles.csv.meta.json` `removed[]` names all **7**; `roles withdrawn` names 7; no `retraction unmatched`; Gamida, Holisto x2, Ballerine, Prisma still published. Calculum's `Junior Data/Financial Analyst` and IAI's `תהליכי בקרה ו-AI` read `accept`, `llm` up ~**2** not 30; Prisma and Ballerine still published; Zoll absent **by design**. `served stale` under **84**, `re-judged` under 250 | run `33739498960` | PASS on every clause. Only `class_decision=reject` is `parametrix`; `meta.removed[]` carries all 7; `roles withdrawn 8 role(s)` (7 + `roles`' Percepto); 0 `retraction unmatched`; Gamida, Holisto x2, Ballerine, Prisma, Calculum, IAI all `accept`; Zoll absent by design. `served stale 11`, `re-judged 51/cap 250`. `llm 89` vs 09-02's 376 (the bump's own drain) - not separable |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-09-02 | infra | **the quality judge has a token.** First `event: schedule` digest on a headSha ⊇ this commit: `enrich` stamp `matched_llm_unavailable=0`, `matched_llm_calls` > 0, no `jd-quality-unavailable` clause. `llm-no-token` = the secret is missing from some other step; `llm-auth` now means one was sent and refused | 2026-09-04 (`infra`) | PASS - run `33613841435` (09-02): `matched_llm_calls=30`, `matched_llm_unavailable=0`, 49 candidates; 09-03 calls 7; `jd-quality-unavailable` 0 in that digest |
| 2026-09-02 | infra | **eight shards, all under the wall.** First `tests.yml` at or after this commit: `mutation-gate (0)`..`(7)` `success`, **16 jobs** (was 13), every `timing    wall` under **1,800 s**, no `::warning::mutation shard walled` | 2026-09-01 | PARTIAL, early - the wall clause PASSES twice: `33522769201` walled **1126-1611 s** and `33529418065` **1147-1578 s**, all 16 shard-runs under 1,800, no warning, 16 jobs. The `all success` clause fails on SURVIVING records, not the clock: 6 of them, `roles`' five fixed the same evening, jd-text's open (`564`) |
| 2026-09-02 | infra | **the text is on Pages and the meta says so.** After the first digest on this commit: `curl -sI .../board/roles_text.jsonl` is `200` (same for `roles_archive.csv`), and the meta reads `description_text.published_on_pages: true` + `archive.published_on_pages: true`. Still `false` ⇒ the env names never reached `build_meta` (498) | 2026-09-04 (`infra`) | PASS - `curl -sI .../board/roles_text.jsonl` **200** (923,589 bytes), `roles_archive.csv` **200**; `roles.csv.meta.json`: `description_text.published_on_pages: true`, `archive.published_on_pages: true` |
| 2026-09-07 | infra | 7 mornings from 09-01: `Company intel:` backlog **median <= 10**, delta **<= 0 on >= 5 of 7**, `firmo` **left = 0, age <= 1** (`450`); `10:17` lag **< 180 min** (305) | | not yet due |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0`; above that, strip that run's verdicts | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-02 | registry | **the Oak fold fires unattended, and the repairs hold** (`522`): `grep -c '^Oak,' companies.csv` = **0**, `oak\|product analyst` gains a `superseded_by` in `roles.jsonl` (empty ⇒ the fold refused and nothing records why), and `Failed companies:` names neither **Sisense** (repaired greenhouse→ashby) nor `Decart`/`Akamai` (parked) | 2026-09-04 (`infra`) | PASS - `grep -c '^Oak,'` = **0**; `oak\|product analyst` has `superseded_by` = `oak identity security os\|product analyst`; the 09-02 digest (`1eb7391`) has no `Failed companies:` line |
| 2026-09-02 | registry | the query-URL parks HELD without a session: `python registry_health.py --query-urls` prints `parked by the audit (in the hunt's pool): 20` (or more), `grep -c 'query-filter 2026-08-30: filter' companies.csv` >= **19**, and no 19:00 log since 08-30 carries `verified N IL via jobs.comcast.com`; `grep -c 'query URL' <listing-hunt log>` >= 1 shows the guard firing | 2026-09-04 (`infra`) | FAIL - `parked by the audit (in the hunt's pool): 16` (wanted 20+); `query-filter 2026-08-30: filter` = **14** (wanted 19+); the guard fires (`query URL` x14 in run `33808490759`, comcast 0). Resolved out, or stamps lost, is `registry`'s to read |
| 2026-09-05 | registry | `registry_health.py --stale-boards` **<=17** (was 18; only HiBob repaired) (`391`); and on 09-28, `zero-confirm 2026-08-29: confirmed` rows **<=5%** with `health_baseline > 0` | | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due until 2026-09-07 (`audit-coverage.yml` is `0 4 * * 0`; the first Sunday after the deep rung shipped is 09-06) |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | | not yet due |
| 2026-09-02 | jd-text | first schedule digest ⊇ this commit: **`matched_llm_calls` > 0 and `matched_llm_unavailable` < `matched_llm_candidates`** (a Counter always PRINTS `matched_llm_refuted`, so its presence proves nothing — wave B); `techbiz global` not back at 6,000 soup chars; **Ballerine still 1,662, not 4,000** (both stores were repaired; the cache card is the thing that would hand it back); Prisma keeps Product-Analyst text | 2026-09-04 (`infra`) | PARTIAL - run `33613841435`: calls 30, unavailable 0 < 49; techbiz 695 chars; Prisma 2,617. FAIL: **Ballerine 3,998 chars in `matched`** - the 4,000 is back (`572`) |
| 2026-09-02 | docs | **the escalation caught something rather than merely being green.** `git log --since=2026-08-30 -p -- HANDOFF.md` shows at least one row ANSWERED or re-dated with `until` by a lane other than `docs`. Zero in three days means the rule is being satisfied by not writing rows at all, which is the failure it replaced wearing a different coat | 2026-09-04 (`infra`) | PASS - `6195aa6` (`finisher`, 09-03) answered four rows against run `33739498960`; this session answers eight, two FAIL/PARTIAL |
| 2026-09-01 | company-intel | first unattended digest on a headSha ⊇ the `display_name` commit logs `display_names=71 (+0/-0) divergent=56 sectors_folded=0` (±drift) in step `firmo_drain` | run `33739498960` | PASS with the drift this row allows: `display_names=108 (+0/-0) divergent=77 sectors_folded=0` - both exact, counts up from 71/56 |
| 2026-09-01 | company-intel | **a live role is never "cannot identify".** First unattended digest, headSha ⊇ this commit: `registry backlog 0` (a FLOOR — rows added overnight lift it); no BOARD company refused `model could not identify the name`, whose honest replacement is `unidentified despite role evidence`; `display_names=84` (was 71 before this commit's `Landa` + `Kidum`) | run `33739498960` | PASS on all three: `registry backlog 4` clears a FLOOR of 0; **0** occurrences of `model could not identify the name`; `display_names=108`, past 84 |
| 2026-09-02 | company-intel | **a transient no longer costs the research; the anchor makes the retry answerable.** `N transient, retried next run` never beside `claude unavailable after N blurbs calls (transient:`; `registry backlog` **<= 12**, delta **<= 0** | 2026-09-04 (`infra`) | PARTIAL - 09-04 mail: `1 transient, retried next run`, no `claude unavailable after`; `registry backlog 7` <= 12 but **+3 since 2026-09-03**, not <= 0 |
| 2026-09-01 | render | first digest after company-intel's `display_name` commit: mail heading shows the brand (`### Faye`-class), board cell agrees; finbounce stays `finbounce`, no `display-collision` (refused at source) | run `33739498960` | PARTIAL - board half PASSES, mail half unobservable. `docs/index.html` renders `title="withfaye">Faye` and `roles.csv` reads `company=Faye, company_registry=withfaye`; `finbounce` 0, `display-collision` 0. **No `### Faye`-class heading existed to check.** Re-due when a divergent employer posts |
| 2026-09-02 | roles | **the publish gate holds unattended.** First `event: schedule` digest on a headSha ⊇ this commit: **no published row has `description_quality` `snippet` or `none`**; `grep -c 'Manager Bi' docs/index.html` = **0**; `Roles:` carries `weak N (S structural, P pending)`; `reconciliation` holds with `pending_excluded`; the אסם fold logged ONCE (`superseded` 10⇒11) and never on 09-03 | 2026-09-04 (`infra`) | PARTIAL - `roles.csv` 151 rows, all `description_quality` `jd`; `Manager Bi` **0** in `docs/index.html`; `weak N (`, `reconciliation` and the אסם clause did not grep out of run `33858255664` - unverified, none failed |
| 2026-09-03 | roles | **the retraction lands on one record and the fold stops colliding.** First `event: schedule` digest on a headSha containing this commit: `Stages:` carries NO `roles seen-id collision`; `grep -c 'Data Insights Operations' cloud_state/roles.csv` = **0** while the `percepto` Senior Product Analyst record is still `open` in `roles.jsonl`; `roles withdrawn` names **Percepto Data Insights Operations**; no `roles retraction unmatched` | run `33739498960` | PASS on all four. No `roles seen-id collision` (0 in the log, 2 ids on 09-02); `grep -c 'Data Insights Operations' cloud_state/roles.csv` = **0**; `percepto\|senior product analyst` still `open`/`accept`; `meta.removed[]` names it; 0 `roles retraction unmatched` |
| 2026-09-06 | docs | **the three checks are still meaningful SOMEWHERE.** They skip in CI by design (a depth-1 checkout has nothing to be behind), so the only place they fire is a lane's own pre-push run. Evidence they still do: `git log --since=2026-08-30 --grep='tree\|morning check\|unattended'` finds a session that hit one, or ask the orchestrator whether any lane was stopped by one. If nothing in a week, they are decoration and belong in `docs/BACKLOG.md` as such | | not yet due |
| 2026-09-04 | discovery | **the anonymised-employer gate fires unattended.** First `event: schedule` digest on a headSha containing `0a45de4`: `grep -c 'Stealth Startup\|Confidential Company\|Confidential Global Company\|Discreet Company' discovered_cache.json` = **0** (11 cards today, 7 of them `Stealth Startup`), and the step log's `cache: dropped N agency cards` is 11 higher than the 09-03 run's. No ACTIVE row may be lost: `check_invariants.py` still reads **1,195+ active** | | |
| 2026-09-04 | classifier | **the gate reads the posting, unattended.** First `event: schedule` digest on a headSha containing this commit: `Zoll` published or named in `classify:` - the claim is it REACHES the tier; `llm N` at most **25** above 09-03's **89**; `re-judged` under 250; `roles.csv` `grep -c`: **0** `DoiT` (1 today), **1** `Investing` (2), **1** `נספרסו` (2); Prisma `description_len` **2617** | | |
| 2026-09-05 | infra | **the archive step ran unattended and the ledger grew.** First `event: schedule` `jd-archive` run on a headSha ⊇ this commit: step log `[wayback] submitted N` with N > 0 and `requests` <= 140; `grep -c '"at":"2026-09-05' cloud_state/wayback_ledger.jsonl` >= N; the 09-06 digest's `Stage order:` carries `wayback: 2026-09-05`; open one `il.linkedin.com` `snap` by hand - a posting or a login wall? Throttled/`host_parked` > 0 is a reading, not a failure | | |

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
- **2026-09-04 `infra`** — postings vanished before disputes settled; nothing had ever WRITTEN to the Archive. `archive_evidence.py` (first step of `jd-archive.yml`): 100 postings + 25 boards a day to Save Page Now, one text-free line each in `cloud_state/wayback_ledger.jsonl`, `wayback` stamp + `Stages:` clause, runbook ARCHITECTURE §5. Live **2 of 3**, backlog **4,603**. **NOT finished:** the 09-05 row; `445`. Record: `docs/sessions/2026-09-04-infra.md`.
