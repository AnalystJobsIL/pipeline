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
| 2026-09-20 | registry | **the folds fire and both repointed rows publish.** First schedule digest ⊇ this push: `alias fold` names `הפניקס<-Phoenix Financial` and `Group19<-Group19 Tech`; `Group19` and `Discount Bank` each N >= 1 IL (`oraclehcm`, `/job/5108`); `Pagaya`/`רם אדרת` gone. No fold clause = `ALIASES` missing (`571`), **FAIL** | | |
| 2026-09-20 | company-intel | **the pushes are green on a runner.** `gh run view 35416466374 --json jobs` reads 28/28 `success`. `35415388118` (`a25e1c3`) is EXPECTED RED — two tests `f036253` re-aimed; a red on `35415997435` or later is mine | | |
| 2026-09-20 | company-intel | **the seven declarations survive a cron.** Digest ⊇ `fdc9e70`: `firmographics.json` holds `Group19`, no `Pagaya`/`Group19 Tech`/`בנק דיסקונט` key, count **1,695**±new, no `union DROPS`. A key back = sqlite won | | |
| 2026-09-20 | registry | **the re-applied Harel row survives a cron.** After the 09-19 19:00 `listing-hunt` commits, `Harel Insurance & Finance` is still `adamtotal` / `harel` / `active=true` in `companies.csv`. Parked again = `644` is live and the merge needs its BASE | | |
| 2026-09-21 | classifier | the drain has re-superseded the 882 `v3.0f84ab84` cells: `classify: ... stale` back to its 09-18 level, no `drain moved` one-way alarm | | |
| 2026-09-20 | jd-text | first schedule `jd-archive` on this commit: `scrape_recleaned` <= 274, no `archive:reclean-refused` | | |
| 2026-09-21 | jd-text | `matched_via_render` >= 2, `matched_render_capped` 0; N/A until `infra`'s step (`636` for Discount) | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-20 | infra | **one ceiling a job.** First schedule `jd-archive` ⊇ this push: `jobs` >= **60** (39 on 09-18), `captured` >= **25**, every `pending` with a `job_id`, <= **5** `il.indeed.com` all `excluded`. `net` rises by design; `jobs` < 60 is **FAIL** | | |
| 2026-09-20 | registry | **the queue stamp stops crying wolf and the back-off shows.** The 09-20 `queue:` stamp: **no** `alarm=queue GREW`, `ledger_contradicted=0`, `new_intake` present, `selectable` <= 176, and `direction=lapsed` on any day `delta` > 0 with `new_intake=0`. `delta` is a reading, not a clause. Then on 09-29 `selectable` <= **176** (flat-14 would have read 225) | | |
| 2026-09-20 | scraper | **jdfill re-read the moved addresses.** The 05:00 digest after that refresh: `scraped_cache.json`'s Deloitte `AI Engineer- R&D and Innovation Center` has a description whose first 120 characters name that role and not `Administrative Assistant`, and Camtek `PM & System Engineer`'s does not contain `Operativer Einkäufer` | | |
| 2026-09-20 | roles | first `event: schedule` digest after `91b9676`: `Roles:` carries `alias folds: 1 renamed (Harel Insurance & Finance<-הראל ביטוח ופיננסים)`, `store.renamed` grows to 6, and the Hebrew role_id is gone from `roles.csv` with its open role published under the Latin key | | |
| 2026-09-20 | ats-fetch | first `event: schedule` digest whose headSha has `348811e`: every `stale.json` entry carries `nights`; `new:` names no `regressed to zero` at `nights 1`; standing carries `watching`. N/A if none ran | | |
| 2026-09-21 | ats-fetch | two containing digests on: `new: ... regressed to zero` names at most the rows whose `nights` reached **2** that morning, and no name is announced twice in three days | | |
| 2026-09-20 | infra | **the browser is there and the rung fires.** Digest ⊇ `89e75eb`: `Install Playwright` `success`, `matched_via_render` >= 1; `render-unavailable` = FAIL | | |
| 2026-09-21 | infra | **a one-night row buys no strike.** First self-heal after a digest that WROTE `nights`: no `attempt 1 - no working ATS` on a `nights 1` row | | |
| 2026-09-21 | infra | **a cron leaves a session's row alone.** First `(row-merged)` commit under 6 h after an `ajil-bot` `companies.csv` push: both-changed rows keep the session's cols 1-4, `J conflicts` named | | |

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
- **2026-09-19 `infra`** — no Chromium in the digest, so the render rung latched: step added, 358/360; `635` one `one_night_reading`. `644`: a one-sided merge reverted Harel's activation (83/83 IL); now three-way per column and segment, conflicts keep origin and reach `Stages:`. 1 of 15 rows, 19 days. CI `35433908530` UNVERIFIED. **NOT finished:** `646`, `638`, `604`.
