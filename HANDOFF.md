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
| 2026-09-19 | company-intel | **the push is green on a runner.** `gh run view 35366756545 --json jobs` (headSha `dd37f9f`) reads every job `success` at JOB level, including the 20 `mutation-gate` shards of `62eab37`. Still `queued` behind three lanes at 16:09Z, which is why this is a row. A `rc 137` shard with no `SURVIVING` line is `631`, not mine | 2026-09-19 (`company-intel`) | PASS — 28 of 28 jobs `success` |
| 2026-09-19 | company-intel | **the three duplicate records stay gone.** The first `event: schedule` digest whose headSha contains this push: `cloud_state/firmographics.json` holds **no** `DoiT`, `Flare` or `Trivago` key, the run's export line reads no `refusing to publish: the union DROPS`, and the record count is **1,701 ± the day's new research**. A key back = the sqlite side won and `settle_keys` did not run at that view | | |
| 2026-09-19 | company-intel | **the two brands render.** Same run: the board's company cell reads `Trivago` for the Holisto role and `Flare` for the Hello Flare role (`display_name` on both records), and `Render:` carries no `display-collision` and no `blurb-names-other` naming either. An empty cell means `rolecard.display_name` refused the override — FAIL, and `632` is the reader | | |
| 2026-09-19 | company-intel | **the two folds cost the dataset exactly three rows.** Same run: published `roles.csv` is **183** rows with `excluded superseded` **20** (from 186/17), `Flare` and `Trivago` absent from its `company` column, the role_ids `hello flare` + `senior data analyst` and `holisto` + `senior data analyst` present. A different delta is not a FAIL by itself — the day's own churn moves both — but the two names must be gone | | |
| 2026-09-19 | classifier | the mail's `roles withdrawn` names all **7** new lines (Clal, Glow, Sunflower Marketing Analyst, Zipher Senior Data Analyst, Osem sales control, Jazz, Upwind Head of Data) and there is **no** `retraction unmatched` | | |
| 2026-09-19 | classifier | ...and an **eighth**: `gamida cell\|senior business analyst commercial data analytics` reads `withdrawn`, not `closed` | | |
| 2026-09-19 | classifier | published `roles.csv` carries **0** rows with `class_decision=reject`, and Amitim / Migdal / Navina / Phoenix 50400095 / Play Perfect / Team8-Briya are `accept`, not withdrawn | | |
| 2026-09-19 | classifier | the digest's `backfill:` line carries `a published reject owed a live verdict` with N >= 6, and `classify:` names contract `v3.0a439b16` | | |
| 2026-09-19 | classifier | `CANNOT be re-judged (...)` carries `no-text-unattempted`, never `?` | | |
| 2026-09-20 | registry | **the folds fire and both repointed rows publish.** First schedule digest ⊇ this push: `alias fold` names `הפניקס<-Phoenix Financial` and `Group19<-Group19 Tech`; `Group19` and `Discount Bank` each N >= 1 IL (`oraclehcm`, `/job/5108`); `Pagaya`/`רם אדרת` gone. No fold clause = `ALIASES` missing (`571`), **FAIL** | | |
| 2026-09-20 | company-intel | **the pushes are green on a runner.** `gh run view 35416466374 --json jobs` reads 28/28 `success`. `35415388118` (`a25e1c3`) is EXPECTED RED — two tests `f036253` re-aimed; a red on `35415997435` or later is mine | | |
| 2026-09-20 | company-intel | **the seven declarations survive a cron.** Digest ⊇ `fdc9e70`: `firmographics.json` holds `Group19`, no `Pagaya`/`Group19 Tech`/`בנק דיסקונט` key, count **1,695**±new, no `union DROPS`. A key back = sqlite won | | |
| 2026-09-20 | registry | the three gate wrappers are pure functions: **N/A by construction** | 2026-09-19 (`registry`) | N/A — four `--id` records and 2 behavioural tests are the whole proof |
| 2026-09-20 | registry | **the re-applied Harel row survives a cron.** After the 09-19 19:00 `listing-hunt` commits, `Harel Insurance & Finance` is still `adamtotal` / `harel` / `active=true` in `companies.csv`. Parked again = `644` is live and the merge needs its BASE | | |
| 2026-09-19 | registry | **the two pushes are green on a runner.** `gh run view 35414525033 --json jobs` (`078763c`, the eight code commits) and `35414627658` (`325e824`, docs) read every job `success` at JOB level, `guard-kill` and all twenty `mutation-gate` shards included. Both were `queued` behind four lanes at 02:05Z, which is why this is a row. A red naming any `*-token-dropped`, `expand-ats-*`, `retry-ats-*`, `bd-activate-*` or `wayback-*` record is THIS lane's; a shard on the 40-minute wall with 0 `SURVIVING` is `631@infra` | | |
| 2026-09-21 | classifier | the drain has re-superseded the 882 `v3.0f84ab84` cells: `classify: ... stale` back to its 09-18 level, no `drain moved` one-way alarm | | |
| 2026-09-19 | jd-text | first schedule digest on this commit: `matched_recleaned` <= 3, no `matched:reclean-refused`, `grep -c '&#' cloud_state/roles_text.jsonl` = 0, no `? 1` on `classify` | | |
| 2026-09-20 | jd-text | first schedule `jd-archive` on this commit: `scrape_recleaned` <= 274, no `archive:reclean-refused` | | |
| 2026-09-19 | jd-text | the Waze row reads `ok:own-address:www.google.com`, 3,000+ ch (N/A if its listing GET < 5,000) | | |
| 2026-09-21 | jd-text | `matched_via_render` >= 2, `matched_render_capped` 0; N/A until `infra`'s step (`636` for Discount) | | |
| 2026-09-19 | jd-text | **28 of 28.** `tests.yml` `35413985160` on `6db99de`, at JOB level | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-19 | registry | **the Trivago fold fires, or says why not.** The first `event: schedule` digest whose headSha contains this park prints an `alias fold` clause naming `Holisto<-Trivago`, or `left N record(s) in place, no twin` — and `Trivago` is absent from the board and from `roles.csv`'s `company` column while `holisto\|senior data analyst` is still there. NO fold clause at all means `company-intel`'s `ALIASES["trivago"]="holisto"` did not land: that is the 571 shape, a park with no declaration, and it is **FAIL** with the missing half named | | |
| 2026-09-19 | infra | **28 of 28.** `tests.yml` `35406466497` on `8a9666c` at JOB level, no `rc 137`, every shard under **1,800 s** | | |
| 2026-09-20 | infra | **one ceiling a job.** First schedule `jd-archive` ⊇ this push: `jobs` >= **60** (39 on 09-18), `captured` >= **25**, every `pending` with a `job_id`, <= **5** `il.indeed.com` all `excluded`. `net` rises by design; `jobs` < 60 is **FAIL** | | |
| 2026-09-19 | infra | **the hidden role has a name.** `digests/latest.md` reads `the title is a card blob: ONE datAI: Business Data Analyst \| SQL & Power BI`, with no `fix the scrape`. A bare count is **FAIL** | | |
| 2026-09-19 | registry | **Harel publishes, once.** First schedule digest: `Harel Insurance & Finance` with N >= 1 IL via adamtotal, and an `alias fold` naming `Harel Insurance & Finance<-הראל ביטוח ופיננסים` or `left N record(s) in place` | | |
| 2026-09-20 | registry | **the queue stamp stops crying wolf and the back-off shows.** The 09-20 `queue:` stamp: **no** `alarm=queue GREW`, `ledger_contradicted=0`, `new_intake` present, `selectable` <= 176, and `direction=lapsed` on any day `delta` > 0 with `new_intake=0`. `delta` is a reading, not a clause. Then on 09-29 `selectable` <= **176** (flat-14 would have read 225) | | |
| 2026-09-19 | scraper | **the push is green on a runner.** `gh run view 35360358542 --json jobs` (headSha `ca405b7`, the last commit of this session) reads **16 of 16** `success` at JOB level - `guard`, `guard-kill`, six `rehearse`, eight `mutation-gate` shards. The run was still `queued` behind two lanes' runs 50 minutes after the push, which is why this is a row and not a number in the line. A red names its job and whether it is this lane's | | |
| 2026-09-19 | scraper | **a card takes its own link.** First `scrape-refresh` `event: schedule` whose headSha contains `b36a653`: the step log reads `Deloitte: 7 via cards`, and in `scraped_cache.json` the one-liner of `434` (own-address cards sharing a url with another title) names neither `Deloitte` nor `Camtek` (09-18: 54 cards / 10 boards). The same run's `collect:` stamp carries `carried_twins=2` - Cal's two branch cards are the floor, and 3+ is the carry back | | |
| 2026-09-19 | scraper | **אסם reads its postings' own place.** Same run: at most **1** `אסם` card is located `שדרות` (`מנהל/ת אחזקה שדרות`, whose own title says so), against 10 of 12 on 09-18; at least one reads `Petah Tikva` and at least one `Modiin`. N/A if that row's `scrape_rot` entry reads `http:403` - the pages are behind Incapsula and only the unlocker opened them | | |
| 2026-09-19 | scraper | **Logica-IT is still unreachable, or it is not.** Same run: `cloud_state/scrape_rot.json['Logica-IT']` has `found` > 0 and `scraped_cache.json` holds 0 titles matching `(גוש דן\|השפלה\|השרון\|ירושלים\|BACKEND\|DEVOPS)$` - else the row quotes the rot `n` (6 on 09-19, parking at 7) and `624` is the item | | |
| 2026-09-20 | scraper | **jdfill re-read the moved addresses.** The 05:00 digest after that refresh: `scraped_cache.json`'s Deloitte `AI Engineer- R&D and Innovation Center` has a description whose first 120 characters name that role and not `Administrative Assistant`, and Camtek `PM & System Engineer`'s does not contain `Operativer Einkäufer` | | |
| 2026-09-19 | roles | first `event: schedule` digest with the reject sweep: `roles.csv` holds **0** `class_decision=reject` (was 11); `dataset 173 roles`; meta `excluded.withdrawn` **74** | | |
| 2026-09-19 | roles | same digest: `closure text on 2 board-listed row(s) (ignored)`, no HiBob/Meta closure; `twin folds 1` and ONE BioCatch BI-developer row | | |
| 2026-09-19 | roles | same digest: no `alias fold left` and no `alias folds: N renamed` line — the no-twin rename has no declared pair (`de531b1` parked BOTH Harel rows) | 2026-09-19 | N/A — premise overtaken: `91b9676` activated Harel and declared the alias, so the branch HAS a live input; re-stated below |
| 2026-09-20 | roles | first `event: schedule` digest after `91b9676`: `Roles:` carries `alias folds: 1 renamed (Harel Insurance & Finance<-הראל ביטוח ופיננסים)`, `store.renamed` grows to 6, and the Hebrew role_id is gone from `roles.csv` with its open role published under the Latin key | | |
| 2026-09-19 | roles | first `event: schedule` digest with `607`: the HiBob AI-product and Meta product-analytics rows no longer store a text opening `כבר לא מקבלים בקשות`; the `classify` line carries no `? 1`; meta `description_text.blocked` gains a `failed:shell` key and `pending` reads 2 | | |
| 2026-09-19 | ats-fetch | the 09-19 digest (`event: schedule`) prints no SF name under `new:`, and `cleared:` names >=5 of Alstom, Dentsply Sirona, EY, SAP, Sapiens, West Pharmaceutical. N/A if `boards changed today` never printed | | |
| 2026-09-19 | ats-fetch | the 09-19 self-heal log: how many of the same six print `attempt 1 - no working ATS` (prediction **6**, ~12 credits). A second failing night authorises the SF unlocker rung, <=6/night | | |
| 2026-09-20 | ats-fetch | first `event: schedule` digest whose headSha has `348811e`: every `stale.json` entry carries `nights`; `new:` names no `regressed to zero` at `nights 1`; standing carries `watching`. N/A if none ran | | |
| 2026-09-21 | ats-fetch | two containing digests on: `new: ... regressed to zero` names at most the rows whose `nights` reached **2** that morning, and no name is announced twice in three days | | |
| 2026-09-19 | ats-fetch | **the two pushes are green on a runner.** `gh run view 35407446121 --json jobs` (`2b59be3`, the fetcher) and `35408195028` (`348811e`, health) read **20 of 20** success at JOB level, `guard-kill` and every `mutation-gate` shard included - the seven records this branch filed or re-anchored live in those shards. Both were still `queued` behind five lanes at 00:10Z, which is why this is a row. A red naming `adamtotal-*`, `regression-*`, `a-blip-that-vanished-*`, `same-day-rewrite-*`, `declared-tenant-labels-*` or `identity-jobvite-open` is THIS lane's | | |
| 2026-09-19 | render | **no `blurb-names-other` in the mail.** First `event: schedule` digest ⊇ this push; a `doitintl→Google Israel` fragment on the `Render:` line is **FAIL** | | |
| 2026-09-19 | render | **the push is green on a runner.** `gh run view 35413055599 --json jobs` (`93cf720`): **28 of 28** `success` at JOB level. All 28 read `queued` at 01:35Z | | |

## State at handoff — 2026-09-19 ~01:00 UTC, every number re-derived

| | | how |
|---|---|---|
| registry | **2495 rows · 1430 active · 0 orphans** | `python check_invariants.py` |
| last digest | **2026-09-18**, run `35330002476`, **186 rows / 3 new**; the 09-19 run is the first on today's eight lanes | `digests/latest.md` |
| guards | **2,136 passed · 13 skipped · 0 failed** locally on `078763c` (`registry`); CI runs of 09-18 read 10/16 until `62eab37`'s twenty shards | `python -m pytest` (not `-q`) |

## Watch list for the next session

0. **`digest_watchdog.py` is not installed** (`292@infra`, operator) — the only off-GitHub tripwire. A patch script that emits YAML trips `test_no_workflow_run_block_fakes_a_line_continuation`.

0. **Active rows with an all-time-high of ZERO are a COMMAND, not a number** (wrong five times): `python confirm_zero.py --scrape-only`; `cloud_state/zero_confirm.json` is the per-row answer; siblings `--regions` and `--stale-boards`. `docs/sessions/2026-08-28-registry-evening.md`; `399`, `406`, `407`.

1. **`merge_key` should move onto `firmographics.identity_key`** — the `matched` PRIMARY KEY, so a migration (`132`–`139`, `roles`; §7c counts **13** such identity groups).
2. **`mark_sent` still records intent, not delivery** — a role can be burned unsent (`6@infra`, `161`; CLAUDE.md rule 6 names the step).
3. **`cloud_state/seen.db` is 1.54 MB**, duplicating `firmographics`; drop, VACUUM.
6. **~24 active rows are re-checked by NOTHING** (`registry`, 2026-08-27): an ACTIVE `israel_scoped` fetcher returning 0 never enters `stale.json` (`health.zero_is_a_measurement()` exempts it), so no self-heal or parked pool reaches it; `ARCHITECTURE.md` §2's "every state is re-checked" overstates.

## Open items — highest value first

1. **~370 parked rows carry a triage mode and the 19:00 hunt is time-budgeted (200 min)**, so
   expect a trickle; `extract-gap` needs no search and lands first. **Run `python
   registry_health.py` for today's pools** — the table that sat here was superseded within a day.
2. **iCIMS** is the one platform with rows and no native fetcher (recipe: `ARCHITECTURE.md`
   §6). The old "3+ rows earns a fetcher" rule was replaced by the operator on 2026-08-26:
   one row earns it. `registry_health.py --ats` is derived; HiBob has **1** active row.
3. **`CLAUDE_CODE_OAUTH_TOKEN` may expire**: `LLM calls this run: 0` with a large
   `llm_failed_fallback`. `claude setup-token`.
4. **SerpApi did NOT reset on 2026-09-01** (`total_searches_left: 0`, Free Plan), whatever five
   docs imply. The working search stays `deep_validate.google_via_unlocker` (`4@discovery`).
5. **`--census` rewrites its own baseline every digest run**, so a pool alarms at most once
   and a slow drift never alarms at all. `315@registry`.

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24 → 2026-08-31, 63 session lines, ten lanes** — folded to pointers; numbers, CI run ids and defects are in `docs/sessions/2026-08-*.md` (`registry` (d) in `2026-08-30-infra-b.md` §0). NOT finished: 491/501/502, 464/116/503/504, 505-508, 459/511, 500@roles, 529-532, `261`, `512`-`514`, `516`-`520`, `530`, `534`-`538`.
- **2026-09-01 → 09-04 and 09-11 → 09-13, twenty-two sessions** — folded to pointers (merged 09-19 for the cap); every key they listed is a `docs/BACKLOG.md` item. `docs/sessions/2026-09-0[1-4]-*.md`, `docs/sessions/2026-09-1[123]-*.md`.
- **2026-09-15 -> 2026-09-16 `infra`** - folded to a pointer by its own lane; numbers and CI ids in `docs/sessions/2026-09-1[56]-infra.md`. NOT finished: `620`.
- **2026-09-18, eight sessions** — folded to a pointer the next morning: `registry`, `classifier`, `scraper`, `jd-text`, `infra`, `company-intel`, `ats-fetch`, `roles`. 76 commits b51642b..5dbec81; CI proven 28/28 on `35366136014` after the gate went to twenty shards. Numbers, run ids and defects are in `docs/sessions/2026-09-18-*.md`. NOT finished: `622`, `459`, `551`, `616`, `623`, `625`, `634`, `632`, `633`, `621`, `635`, `606`, `627`, `628`.
- **2026-09-19 `jd-text`** — four held rows: a cooldown over the FREE rungs, an ignored `<base href>`, an Oracle site label. Free render rung, registry donor, `_SITE_LABEL`; 0 credits, 10/10 mutants. **NOT finished:** 636-640. Record: `docs/sessions/2026-09-19-jd-text.md`.
- **2026-09-19 `render`** — `blurb-names-other` named **6** of 188 cached blurbs, 0 impersonations, 1 on the board. Block (c) asks two questions now: victims are filtered (a two-word key is not its second noun), accusers are not (`ALIASES`, `display_name`). **6→2**, both real duplicates; board **1→0**. `632` closed. 0 BD/seam. CI `35413055599`. **NOT finished:** `614`(a). Record: `docs/sessions/2026-09-19-render.md`.
- **2026-09-19 `company-intel`** — two parks were **eighteen days** inert for want of an `ALIASES` half (`571`). Seven declarations (export **1,701→1,695**), `Group19`'s own record (3 seam calls, 0 BD, `633` closed), the superset guard that refused its own fold (`645`). I pushed before the suite: 2 reds, re-aimed. Suite **2,140**; CI `35415997435`. **NOT finished:** `645`. Record: `docs/sessions/2026-09-19-company-intel.md`.
- **2026-09-19 `registry`** — the gate wrappers dropped the row's token, refusing a DECLARED board; `Discount Bank` scraped a JS shell; a cron had reverted Harel (**83/83 IL** lost). Forwarded (`621` closed, 21 records re-aimed); `oraclehcm` **67/67**; five folds; `Matrix IT` declared; census **6→2**. 0 BD, seam 4. Suite **2,136**; CI `35414525033` owed. **NOT finished:** `622`, `641`-`644`. Record: `docs/sessions/2026-09-19-registry.md`.
