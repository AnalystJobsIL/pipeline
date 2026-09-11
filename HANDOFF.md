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
| 2026-09-12 | registry | **the six folds fire unattended.** First `event: schedule` digest on a headSha ⊇ `9d0dc00` carries the two lines a rehearsal already produced (`--only` the six companies against a COPY of `seen.db`): `roles alias folds: 3 superseded (Digital Turbine<-DT, Investing<-Investing.com, autods<-AutoDS - Automatic Dropshipping Tools)` and `alias fold left 1 record(s) in place, no twin (מנורה מבטחים החזקות)`; and NO `claim conflicts` clause, which has read `claim conflicts 2 (Gong<-Gong.io, Port<-Port.io)` every morning since 08-16. Board: `grep -c 'Direct Travel' docs/index.html` = **0**, and one AutoDS card, not two | | |
| 2026-09-12 | registry | **the two repointed boards produce, unattended.** Same run's `collect:` stamp and `docs/index.html`: `Digital Turbine` ≥ 5 cards (Workday `digitalturbine/Digital_Turbine_External_Careers`, 7 IL live on 09-11, 2 accepted in a scoped run); `Cal (Israel Credit Cards)` ≥ 1 card with `unlock_calls` ≥ 1 — if 0, the row is honest but the `SCRAPE_VIA_UNLOCKER` export did not reach it, which is `infra`'s. The 06:00 self-heal must NOT have rewritten either row: `git log -p -1 --format=%H -- companies.csv` on that morning's self-heal commit | | |
| 2026-09-12 | jd-text | **the chrome class stays at 0 unattended.** First `event: schedule` digest on a headSha ⊇ this commit: `grep -c 'עבודות דומות' cloud_state/roles_text.jsonl` = **0**; the enrich stamp has no `reclean-refused` and `matched_recleaned` <= 5 (the one-off did 96); `description_len` for `alma` / senior data analyst **576**, Ballerine **1,662**, Amitim **848** after the run's own `open_sync` | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-13 | registry | the night the 14-day cadence lapsed (searches of 08-29), the drain bought NOTHING already answered: `grep -c` of the run log's phase-1 `s1/` names against `cloud_state/queue_disposition.json` RETIRABLE verdicts = **0**, and `retired_in_queue` in the stamp is what `retire-settled` removed that night | | |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl` (n=3 today; ARCHITECTURE §5d) | 2026-09-11 (`infra`) | PASS - KEPT at `>= 10 keys AND >= 3%` on n=79 commits: `scraped_cache.json` is 37 of them, **5 fires**, max 36/410 (8.8%), rest 3.2-5.6%; every other keyed cache lost 0 all fortnight. `cloud_state/stale.json` EXEMPTED (`persist_state.SHRINK_EXEMPT`): 9 fires of 18 commits, up to 41/108 (38%), every one a board HEALING - an alarm on the good outcome teaches its reader to skip the line |
| 2026-09-12 | classifier | **the agency mechanism and the six withdrawals ran unattended.** First `event: schedule` digest on a headSha containing this commit: `Stages:` carries `roles withdrawn 6 role(s)` naming Peak Innovation, Edikted, Flex, aQurate, Qlik Israel and Bank Leumi; **no** `roles retraction lifted` and **no** `roles retraction unmatched` (INGIMA stays `withdrawn`, `583`); the step log's `[discovery] … dropped: recruiter N` reads **>= 3** (0 on 09-11 before the change); `roles.csv` has **0** `peak innovation` rows and `grep -c '"role_id"' cloud_state/roles_retractions.jsonl` equals its line count; the step log prints at least one `[classify] superseded verdict cannot be re-judged` line | | |
| 2026-09-12 | roles | **the verdict cell tells the truth about itself** (`543`, `544`). First `event: schedule` digest on a headSha ⊇ this commit: `roles.csv` header carries `class_contract` and **58** columns (57 today); `roles.csv.meta.json` `classifier_contract.live` = the `classify:` line's contract, and the three row counts sum to the file; `grep -c 'v3.0f84ab84' cloud_state/roles.csv` is near the open-row count (140 today; closed rows read `""` until re-judged); `Roles:` carries `class-rejected N` ONLY if a flip happened (0 prints nothing, which is the healthy steady state); no `classify reject map DISCARDED`; no `roles mass-reject` | | |
| 2026-09-12 | roles | **the title canon fires once and keeps every fact** (`585`). Step log `title folds: 5 renamed (...)` on 09-12 and NOT on 09-13; `grep -ci "hiring" cloud_state/roles.csv` = **0** (2 today, both Practical Vision); `grep -c '"renamed_from"' cloud_state/roles.jsonl` = **5**; `Roles:` carries `title canon at intake` and `ledger N = store N`; the two Practical Vision rows keep `first_seen 2026-09-07` and `emailed=true` and are NOT re-emailed; `roles.csv.meta.json` `store.renamed` names all five. Any `title fold left ... key is taken` = a collision to read | | |
| 2026-09-12 | roles | **a posting whose page says closed leaves the board** (`586`). `Roles:` carries `closed by page 4`; the `Migdal Group` `Business Analyst` row in `cloud_state/roles.csv` reads `closed` with `closed_on 2026-08-28`; `grep -c '"closed_by": "page"' cloud_state/roles.jsonl` = **4**; `grep -ci migdal docs/index.html` = **0**; and on 09-13 `reopened 0` with NO `closed by page` clause — the discovery cache re-serves those cards for 21 days and a repeat means the upsert skip is not holding | | |
| 2026-09-12 | infra | **the ceiling is gone and the gauge is in the mail.** The 09-12 digest's `enrich` alarm carries NO `monthly-ceiling` and `matched_bd_calls` > 0; `Stage order:` carries `bd:` with a numeric `mtd=` and `projected=`; `Stages:` carries `bd projected ...` (it should: the 7-day rate is 469/day) |  |  |
| 2026-09-12 | infra | **the 14-day cadence holds unattended.** The 19:00 `listing-hunt` run on a headSha ⊇ this commit: the hunt step's `[bd-spend]` under **100** (95 rows due tonight, 84% of which bought a search) and `cracking N` ≤ **15** (8 due); `[search-ab] duckduckgo answered N of M ... agreed K (x%)` — **keep the free rung at >= 70%, delete it below that and say so** |  |  |
| 2026-09-13 | infra | **the rescue pass stops re-buying what it already answered.** The 02:30 `retry-unreachable` log: `bright-data rescuing 0` (all 17 rows answered 09-11, next due 09-25) or `validated` ≤ 5, with `this step bought` ≤ 30 or no `[bd-spend]` line at all |  |  |
| 2026-09-14 | infra | **`577` landed and the archive advances.** The first `jd-archive` schedule run ⊇ this commit that does NOT print `stopped: throttled`: `[wayback] submitted` > **115** with `requests` ≤ 220; and `backlog` lower than the previous day's on at least one of 09-12..09-14. If every run throttles, this is FAIL with the `throttled` count and the answer is `580`, not the cap |  |  |

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
- **2026-09-11 `registry`** — six employers published one opening under two names; each declaration was dead because the alias string was a row (`571`, third time). The row's own dated `alias-of <R>` verdict is now READ, and folds when `ALIASES` agrees: 7 pairs, `571` CLOSED. Digital Turbine 0→7 IL. CI `34608347234` **15/16**, 4 inherited. **NOT finished:** `578`, `579`. Record: `docs/sessions/2026-09-11-registry.md`.
- **2026-09-11 `classifier`** — 25 audit claims adjudicated: **6 withdrawn, 18 kept, 1 deferred** (hand lines, `543`). `peak innovation`/`hila & co.` in `_CONFIRMED` + tripwire test; retraction lines re-keyed by `role_id` after INGIMA's re-post (`583`). Refused: five vocabulary arms, the suffix (`584`); chrome 14/32, 0 moved. CI 34611525857 **14/16**, reds inherited. **NOT finished:** `583`, `584`, `321`, `518`. Record: `docs/sessions/2026-09-11-classifier.md`.
- **2026-09-11 `roles`** - three ways a published row lied about itself. `reject_map` stamps the run's own NOs (`543`); `class_contract` shows a frozen verdict (`544`, 38 of 262); `canonical_title` renames 5 blob-keyed records (`585`); `page_closed` closes 4 LinkedIn rows their page had closed (`586`). Taboola 8035268 never in git. **NOT finished:** `580`, `587`; the 09-12 rows. Record: `docs/sessions/2026-09-11-roles.md`.
- **2026-09-11 `jd-text`** — 62 of 177 published rows carried other employers' postings as their description; `extract_jd` cut stored text with the classifier's prose regex. Head+tail furniture, `_HEAD_SKIP`, `page_slice`, durable `jd_refuted`, `closed-by-page`; 96 re-cleaned, 11 re-captured, two-store fixed point. Class **0**, no-JD **10 of 248**, 0 credits. CI `34616479937`: guard-kill success, shards UNRUN. **NOT finished:** `580`, `581`, `591`. Record: `docs/sessions/2026-09-11-jd-text.md`.
- **2026-09-11 `infra`** — the BD ceiling bound 1 of 14 spenders: the digest's JD fill. Unlimited by operator ruling, `bd:` gauge in the mail, one 14-day cadence for three paid row tools in `queue_state` (a notes cell eleven writers evict). CI `34622790874` **15 of 16**, the red `roles`' surviving `page-closed-row-is-upserted-anyway`. **NOT finished:** 582, 589, 590, 592. Record: `docs/sessions/2026-09-11-infra.md`.
