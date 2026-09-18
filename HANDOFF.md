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
| 2026-09-19 | classifier | the mail's `roles withdrawn` names all **7** new lines (Clal, Glow, Sunflower Marketing Analyst, Zipher Senior Data Analyst, Osem sales control, Jazz, Upwind Head of Data) and there is **no** `retraction unmatched` | | |
| 2026-09-19 | classifier | published `roles.csv` carries **0** rows with `class_decision=reject`, and Amitim / Migdal / Navina / Phoenix 50400095 / Play Perfect / Team8-Briya are `accept`, not withdrawn | | |
| 2026-09-19 | classifier | the digest's `backfill:` line carries `a published reject owed a live verdict` with N >= 6, and `classify:` names contract `v3.0a439b16` | | |
| 2026-09-19 | classifier | `CANNOT be re-judged (...)` carries `no-text-unattempted`, never `?` | | |
| 2026-09-19 | classifier | `tests.yml` run `35362343421` (sha `dd0c894`, queued behind six runs at 15:45Z) is read job-level: `guard`, `guard-kill` and all seven `rehearse` shards green; any red is a mutation shard on the 40-minute wall (`617@infra`), never a surviving mutant | | |
| 2026-09-21 | classifier | the drain has re-superseded the 882 `v3.0f84ab84` cells: `classify: ... stale` back to its 09-18 level, no `drain moved` one-way alarm | | |
| 2026-09-19 | jd-text | first schedule digest on this commit: `matched_recleaned` <= 3, no `matched:reclean-refused`, `grep -c '&#' cloud_state/roles_text.jsonl` = 0, no `? 1` on `classify` | | |
| 2026-09-20 | jd-text | first schedule `jd-archive` on this commit: `scrape_recleaned` <= 274, no `archive:reclean-refused` | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-19 | registry | **the Trivago fold fires, or says why not.** The first `event: schedule` digest whose headSha contains this park prints an `alias fold` clause naming `Holisto<-Trivago`, or `left N record(s) in place, no twin` — and `Trivago` is absent from the board and from `roles.csv`'s `company` column while `holisto\|senior data analyst` is still there. NO fold clause at all means `company-intel`'s `ALIASES["trivago"]="holisto"` did not land: that is the 571 shape, a park with no declaration, and it is **FAIL** with the missing half named | | |
| 2026-09-19 | registry | **the push is green on a runner.** `gh run view 35359064839 --json jobs` (headSha `267e6ac`) reads 16 of 16 success at job level; any red is NAMED with its owner | 2026-09-18 (`registry`) | FAIL — **10 of 16**: `guard`, `guard-kill` and all five `rehearse` SUCCESS; `mutation-gate` 1 and 6 success, **0/2/3/4/5/7 FAILURE, every one `rc 137` at the 40-minute wall with ZERO `SURVIVING` lines** (41/42/42/44/44/48 records done of ~52, all `killed`). Not a dead guard and not this lane's: the catalogue went **391 → 416 on 09-18** across five lanes (`registry` filed 6 of the 25) and the last GREEN run at 391 records already had walls of 30.6–39.1 min against a 40-minute budget — **~1 minute of headroom**. `631`, `infra` |
| 2026-09-20 | infra | **the mutation gate fits its wall again.** After `631` is applied, the first `tests.yml` run on master reads **16 of 16** (or 16+N with the new matrix entries) and NO `mutation-gate` job exits `rc 137`; each shard's `timing wall` line is under **1,800 s**, the number `tests.yml`'s own comment names as the trigger. A shard over 1,800 s that still passes is FAIL — the headroom is gone again and the per-record cost, not the record count, is the variable (suite 1,766 → 2,072 tests) | | |
| 2026-09-19 | registry | **a ledger refusal holds through a hunt.** The 09-18 19:00 `listing-hunt` (`event: schedule`, headSha ⊇ this commit): `Kima`, `PayPlus`, `Mars Antennas And Rf Systems`, `Phoenix Financial` and `Ethos` all still `active=false` in `companies.csv` after it, and no `[OK]` line names `careers.akima.com`, `payplus.com` or `arizonafinancial.org`. A `ledger: another company's board` refusal line is the PASS shape; a re-activation is **FAIL — the veto is not in the arm that wrote it** | | |
| 2026-09-20 | registry | **the queue stamp stops crying wolf and the back-off shows.** The 09-20 `queue:` stamp: **no** `alarm=queue GREW`, `ledger_contradicted=0`, `new_intake` present, `selectable` <= 176, and `direction=lapsed` on any day `delta` > 0 with `new_intake=0`. `delta` is a reading, not a clause. Then on 09-29 `selectable` <= **176** (flat-14 would have read 225) | | |
| 2026-09-19 | scraper | **the push is green on a runner.** `gh run view 35360358542 --json jobs` (headSha `ca405b7`, the last commit of this session) reads **16 of 16** `success` at JOB level - `guard`, `guard-kill`, six `rehearse`, eight `mutation-gate` shards. The run was still `queued` behind two lanes' runs 50 minutes after the push, which is why this is a row and not a number in the line. A red names its job and whether it is this lane's | | |
| 2026-09-19 | scraper | **a card takes its own link.** First `scrape-refresh` `event: schedule` whose headSha contains `b36a653`: the step log reads `Deloitte: 7 via cards`, and in `scraped_cache.json` the one-liner of `434` (own-address cards sharing a url with another title) names neither `Deloitte` nor `Camtek` (09-18: 54 cards / 10 boards). The same run's `collect:` stamp carries `carried_twins=2` - Cal's two branch cards are the floor, and 3+ is the carry back | | |
| 2026-09-19 | scraper | **אסם reads its postings' own place.** Same run: at most **1** `אסם` card is located `שדרות` (`מנהל/ת אחזקה שדרות`, whose own title says so), against 10 of 12 on 09-18; at least one reads `Petah Tikva` and at least one `Modiin`. N/A if that row's `scrape_rot` entry reads `http:403` - the pages are behind Incapsula and only the unlocker opened them | | |
| 2026-09-19 | scraper | **Logica-IT is still unreachable, or it is not.** Same run: `cloud_state/scrape_rot.json['Logica-IT']` has `found` > 0 and `scraped_cache.json` holds 0 titles matching `(גוש דן\|השפלה\|השרון\|ירושלים\|BACKEND\|DEVOPS)$` - else the row quotes the rot `n` (6 on 09-19, parking at 7) and `624` is the item | | |
| 2026-09-20 | scraper | **jdfill re-read the moved addresses.** The 05:00 digest after that refresh: `scraped_cache.json`'s Deloitte `AI Engineer- R&D and Innovation Center` has a description whose first 120 characters name that role and not `Administrative Assistant`, and Camtek `PM & System Engineer`'s does not contain `Operativer Einkäufer` | | |
| 2026-09-19 | roles | first `event: schedule` digest with the reject sweep: `roles.csv` holds **0** `class_decision=reject` (was 11); `dataset 173 roles`; meta `excluded.withdrawn` **74** | | |
| 2026-09-19 | roles | same digest: `closure text on 2 board-listed row(s) (ignored)`, no HiBob/Meta closure; `twin folds 1` and ONE BioCatch BI-developer row | | |
| 2026-09-19 | roles | same digest: no `alias fold left` and no `alias folds: N renamed` line — the no-twin rename has no declared pair (`de531b1` parked BOTH Harel rows) | | |

## State at handoff — 2026-09-01 ~17:00 UTC, every number re-derived

Every cell carries the command that re-derives it; the 08-30 table was stale in all five.

| | | how |
|---|---|---|
| registry | **2,127+ rows · 1,132+ active · 0 orphans** | `python check_invariants.py` |
| by tier | **556 native-ATS · 575 scrape · 1 discovery** | `python registry_health.py` |
| intake queue | **190 OWED** vs a drain of **176/night** (2026-09-13 13:xxZ; 112/night until then) | `python queue_state.py` |
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
- **2026-09-01 → 2026-09-04, seven sessions** — folded to pointers, as 2026-08-24→08-31 was: `classifier` x2, `jd-text`, `roles`, `registry` x2, `discovery`, `finisher`, `infra`. Numbers, CI run ids and defects are in `docs/sessions/2026-09-0[1-4]-*.md`. NOT finished: `535`, `542`-`544`, `546`-`557`, `559`-`563`, `565`-`567`, `571`-`574`, `577`, `445`.
- **2026-09-11 → 2026-09-13, fifteen sessions** — folded to pointers, as 2026-09-01→09-04 was: `registry` x2, `classifier` x2, `roles`, `jd-text` x2, `company-intel` x2, `infra` x3, `ats-fetch` x2, `scraper`. Numbers, CI run ids and defects are in `docs/sessions/2026-09-1[123]-*.md`. NOT finished: `321`, `518`, `548`, `551`, `573`, `578`-`584`, `587`, `589`-`591`, `593`-`619`.
- **2026-09-15 `infra`** — two `zero-produce` nights were the archive DOWN, read as four hosts refusing (0 refusal lines in 768). Two failure families; `_pause` x2 for a 429 or an 8-streak; boards 1-in-6; `refusals` vs attempts; `captured`/`net`/`server`/`refused` stamped. 0 credits. CI `35026108993` **16/16**. **NOT finished:** `620`. Record: `docs/sessions/2026-09-15-infra.md`.
- **2026-09-16 `infra`** — the anonymous archive rung named ~9 a night. `9bae94a`: the account's SPN2 API — a job per url read to its end. Schedule run `35126457407`: 56 jobs, 37 captured, `net 43` = a 30-s POST cut-off, fixed in `cf2b775`. 0 credits. CI `35135060150` **16/16**. **NOT finished:** `620` (re-scoped); the 09-18 rows. Record: `docs/sessions/2026-09-16-infra.md`.
- **2026-09-18 `registry`** — a NOT-THEIRS ledger read bound nothing; the hunt re-activated Kima and PayPlus. `board_verify.refuses` vetoes both hunt arms and `--verify-existing`; `ledger_contradicted` **3→0**. Lapse alarm fixed; back-off 14→28→56/90 (09-29 **225→123**). Harel board found, gate refuses (`621`); `Trivago` `alias-of Holisto`. BD **2**, seam **2**. CI `35359064839` **10/16**, 6 shards `rc 137` (`631`). **NOT finished:** `621`, `622`, `459`. Record: `docs/sessions/2026-09-18-registry.md`.
- **2026-09-18 `classifier`** — the 09-14 data-platform ruling was in no contract, and 11 published rows carried a `reject` cell nothing could flip back. Record; contract `v3.0a439b16` on a measured 2-of-20 flip set; `reject_owed` + `ADJUDICATED`; 7 withdrawn, 6 kept; 13 keys voided. 74 calls, 0 BD. CI `35359208215` **10/16**, six shards walled (`631@infra`). **NOT finished:** `551`. Record: `docs/sessions/2026-09-18-classifier.md`.
- **2026-09-18 `scraper`** — 54 cards carried a neighbour's link, 20 a sibling's text, אסם its navbar slogan. Card bounds, own-address carry key, h1-anchored place, `608`(a); replays: 447 boards 0 lost / 43 addresses corrected, 452 pages 35 places moved, 10 cards voided. BD 2. CI `35360358542`, verdict owed. **NOT finished:** `616`, `623`-`625`. Record: `docs/sessions/2026-09-18-scraper.md`.
- **2026-09-18 `jd-text`** — own-board nav bracketed two published texts; 26 rows carried raw entities. Mirror rule, 3 markers, unescape, listing-card veto, `failed:` reasons, defective-text arm; 46 re-cleaned, fixed point proved, 2 credits. CI RUNID. **NOT finished:** 607, 608, 629, 630. Record: `docs/sessions/2026-09-18-jd-text.md`.
- **2026-09-18 `roles`** — 11 published rows shipped `class_decision=reject`. Reject→withdrawn sweep (12 records, reversible) + export tripwire; a closure sentence needs the row's OWN address (0 closures, 2 counted); `_rename_record` shared, alias no-twin rename, BioCatch tie-break. 0 BD/seam. CI `35362047730` QUEUED 0/16, verdict owed. **NOT finished:** `627`, `628`. Record: `docs/sessions/2026-09-18-roles.md`.
