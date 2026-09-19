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
| 2026-09-19 | company-intel | **the push is green on a runner.** `gh run view 35366756545 --json jobs` (headSha `dd37f9f`) reads every job `success` at JOB level, including the 20 `mutation-gate` shards of `62eab37`. Still `queued` behind three lanes at 16:09Z, which is why this is a row. A `rc 137` shard with no `SURVIVING` line is `631`, not mine | | |
| 2026-09-19 | company-intel | **the three duplicate records stay gone.** The first `event: schedule` digest whose headSha contains this push: `cloud_state/firmographics.json` holds **no** `DoiT`, `Flare` or `Trivago` key, the run's export line reads no `refusing to publish: the union DROPS`, and the record count is **1,701 ± the day's new research**. A key back = the sqlite side won and `settle_keys` did not run at that view | | |
| 2026-09-19 | company-intel | **the two brands render.** Same run: the board's company cell reads `Trivago` for the Holisto role and `Flare` for the Hello Flare role (`display_name` on both records), and `Render:` carries no `display-collision` and no `blurb-names-other` naming either. An empty cell means `rolecard.display_name` refused the override — FAIL, and `632` is the reader | | |
| 2026-09-19 | company-intel | **the two folds cost the dataset exactly three rows.** Same run: published `roles.csv` is **183** rows with `excluded superseded` **20** (from 186/17), `Flare` and `Trivago` absent from its `company` column, the role_ids `hello flare` + `senior data analyst` and `holisto` + `senior data analyst` present. A different delta is not a FAIL by itself — the day's own churn moves both — but the two names must be gone | | |
| 2026-09-19 | classifier | the mail's `roles withdrawn` names all **7** new lines (Clal, Glow, Sunflower Marketing Analyst, Zipher Senior Data Analyst, Osem sales control, Jazz, Upwind Head of Data) and there is **no** `retraction unmatched` | | |
| 2026-09-19 | classifier | ...and an **eighth**: `gamida cell\|senior business analyst commercial data analytics` reads `withdrawn`, not `closed` | | |
| 2026-09-19 | classifier | published `roles.csv` carries **0** rows with `class_decision=reject`, and Amitim / Migdal / Navina / Phoenix 50400095 / Play Perfect / Team8-Briya are `accept`, not withdrawn | | |
| 2026-09-19 | classifier | the digest's `backfill:` line carries `a published reject owed a live verdict` with N >= 6, and `classify:` names contract `v3.0a439b16` | | |
| 2026-09-19 | classifier | `CANNOT be re-judged (...)` carries `no-text-unattempted`, never `?` | | |
| 2026-09-19 | registry | `test_the_sunday_audit_escalates_what_its_cheap_rung_left_dark` is CALENDAR ROT, not a regression: red on pristine `a0aab6d` the moment the clock turned (named by `classifier`) | | |
| 2026-09-21 | classifier | the drain has re-superseded the 882 `v3.0f84ab84` cells: `classify: ... stale` back to its 09-18 level, no `drain moved` one-way alarm | | |
| 2026-09-19 | jd-text | first schedule digest on this commit: `matched_recleaned` <= 3, no `matched:reclean-refused`, `grep -c '&#' cloud_state/roles_text.jsonl` = 0, no `? 1` on `classify` | | |
| 2026-09-20 | jd-text | first schedule `jd-archive` on this commit: `scrape_recleaned` <= 274, no `archive:reclean-refused` | | |
| 2026-09-19 | jd-text | the Waze row reads `ok:own-address:www.google.com`, 3,000+ ch; N/A if its listing GET < 5,000 ch | | |
| 2026-09-21 | jd-text | `matched_via_render` >= 2, `matched_render_capped` 0; N/A until `infra`'s Playwright step, and Discount needs `636` | | |
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-19 | registry | **the Trivago fold fires, or says why not.** The first `event: schedule` digest whose headSha contains this park prints an `alias fold` clause naming `Holisto<-Trivago`, or `left N record(s) in place, no twin` — and `Trivago` is absent from the board and from `roles.csv`'s `company` column while `holisto\|senior data analyst` is still there. NO fold clause at all means `company-intel`'s `ALIASES["trivago"]="holisto"` did not land: that is the 571 shape, a park with no declaration, and it is **FAIL** with the missing half named | | |
| 2026-09-19 | infra | **28 of 28.** `tests.yml` `35406466497` on `8a9666c` at JOB level, no `rc 137`, every shard under **1,800 s** | | |
| 2026-09-20 | infra | **one ceiling a job.** First schedule `jd-archive` ⊇ this push: `jobs` >= **60** (39 on 09-18), `captured` >= **25**, every `pending` with a `job_id`, <= **5** `il.indeed.com` all `excluded`. `net` rises by design; `jobs` < 60 is **FAIL** | | |
| 2026-09-19 | infra | **the hidden role has a name.** `digests/latest.md` reads `the title is a card blob: ONE datAI: Business Data Analyst \| SQL & Power BI`, with no `fix the scrape`. A bare count is **FAIL** | | |
| 2026-09-19 | registry | **Harel publishes, once.** First schedule digest: `Harel Insurance & Finance` with N >= 1 IL via adamtotal, and an `alias fold` naming `Harel Insurance & Finance<-הראל ביטוח ופיננסים` or `left N record(s) in place` | | |
| 2026-09-19 | registry | **a ledger refusal holds through a hunt.** The 09-18 19:00 `listing-hunt` (`event: schedule`, headSha ⊇ this commit): `Kima`, `PayPlus`, `Mars Antennas And Rf Systems`, `Phoenix Financial` and `Ethos` all still `active=false` in `companies.csv` after it, and no `[OK]` line names `careers.akima.com`, `payplus.com` or `arizonafinancial.org`. A `ledger: another company's board` refusal line is the PASS shape; a re-activation is **FAIL — the veto is not in the arm that wrote it** | | |
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
| registry | **2494 rows · 1432 active · 0 orphans** | `python check_invariants.py` |
| last digest | **2026-09-18**, run `35330002476`, **186 rows / 3 new**; the 09-19 run is the first on today's eight lanes | `digests/latest.md` |
| guards | **2,116 passed · 13 skipped · 0 failed** locally on `93cf720` (`render`); CI runs of 09-18 read 10/16 until `62eab37`'s twenty shards | `python -m pytest` (not `-q`) |

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
- **2026-09-01 → 09-04 and 09-11 → 09-13, twenty-two sessions** — folded to pointers (two lines merged 09-19 for the cap); every key they listed is a `docs/BACKLOG.md` item, 9 of 28 sampled since closed. `docs/sessions/2026-09-0[1-4]-*.md`, `docs/sessions/2026-09-1[123]-*.md`.
- **2026-09-15 -> 2026-09-16 `infra`** - folded to a pointer by its own lane; numbers and CI ids in `docs/sessions/2026-09-1[56]-infra.md`. NOT finished: `620`.
- **2026-09-18 `registry`** — a NOT-THEIRS ledger read bound nothing; the hunt re-activated Kima, PayPlus. `board_verify.refuses` vetoes both hunt arms and `--verify-existing`; `ledger_contradicted` **3→0**. Lapse alarm fixed; back-off 14→28→56/90 (09-29 **225→123**). Harel ACTIVE `adamtotal` **83/83 IL**, Hebrew `alias-of`+`ALIASES` (`621` closed); `Trivago` `alias-of Holisto`. BD **2**, seam **2**. CI `35359064839` **10/16** (`631`). **NOT finished:** `622`, `459`. Record: `docs/sessions/2026-09-18-registry.md`.
- **2026-09-18 `classifier`** — the 09-14 data-platform ruling was in no contract, and 11 published rows carried a `reject` cell nothing could reach. Contract `v3.0a439b16` on a measured 2-of-20 flip set; `reject_owed` + `ADJUDICATED`; **8 withdrawn**, 6 kept; 32 stale keys forgotten. 74 calls, 0 BD. CI `35359208215` **10/16** (`631@infra`). **NOT finished:** `551`. Record: `docs/sessions/2026-09-18-classifier.md`.
- **2026-09-18 `scraper`** — 54 cards carried a neighbour's link, 20 a sibling's text, אסם its navbar slogan. Card bounds, own-address carry key, h1-anchored place, `608`(a); replays: 447 boards 0 lost / 43 addresses corrected, 452 pages 35 places moved, 10 cards voided. BD 2. CI `35360358542`, verdict owed. **NOT finished:** `616`, `623`-`625`. Record: `docs/sessions/2026-09-18-scraper.md`.
- **2026-09-18 `jd-text`** — folded by its lane on 09-19, CI `35366136014` **28/28**. Record: `docs/sessions/2026-09-18-jd-text.md`.
- **2026-09-19 `jd-text`** — a cooldown parked the FREE rungs, `<base href>` was ignored, an Oracle site label passed as a posting id. Free render rung, registry-listing donor, `_SITE_LABEL`; 0 credits, `630` answered. **NOT finished:** 636-640. Record: `docs/sessions/2026-09-19-jd-text.md`.
- **2026-09-18 `infra`** - `WAYBACK_TIMEOUT_S` applied twice a job: 240 meant 480, and 09-17 spent 11,199 worker-seconds on 34 jobs and 15 captures (p90 305 s). One budget, remaining-clock bound, 180. `bad-request` -> 30 days. Shards 8 -> **20**. `614`(b) names the title. 0 BD/seam. CI `35366136014` **28/28**; `35406466497` 09-19. **NOT finished:** `634`. Record: `docs/sessions/2026-09-18-infra.md`.
- **2026-09-18 `company-intel`** — three employers held two records each, and a new brand arrived with a blurb about a Canadian company. `ALIASES` flare/trivago, `alias_only_folds` (`618`), `DISPLAY_NAME_OVERRIDES["Holisto"]`; export **1,704→1,701**, +2 display names. Group19 sector CONFIRMED, its board is `633`. Seam **1**, BD **0**. CI `35366756545` queued. **NOT finished:** `632`, `633`. Record: `docs/sessions/2026-09-18-company-intel.md`.
- **2026-09-18 `ats-fetch`** — six SuccessFactors boards timed out in one run (0.5 s from here: a blip), and `regressed to zero` was last night's reading. `fetch_adamtotal` + its declared query-string tenant (Harel **83/83 IL**, `621` half); `REGRESSION_NIGHTS` **2** on 81 runs / **41** one-night. 0 BD/seam. CI `35407446121`/`35408195028`. **NOT finished:** `621`, `635`, `606`. Record: `docs/sessions/2026-09-18-ats-fetch.md`.
- **2026-09-18 `roles`** — 11 published rows shipped `class_decision=reject`, and a LinkedIn mirror's text outranked the own board on length. Reject→withdrawn sweep + tripwire; provenance rule; `_rename_record` shared; twin tie-break; `607` closed (4 groups re-ranked); gate 6/6. 0 BD/seam. CI `35407135797` **27/28**, sole red the Sunday-audit calendar rot (`registry`, fixed upstream by `8b1e33e`). **NOT finished:** `627`, `628`. Record: `docs/sessions/2026-09-18-roles.md`.
- **2026-09-19 `render`** — `blurb-names-other` named **6** of 188 cached blurbs, 0 impersonations, 1 on the board. Block (c) asks two questions now: victims are filtered (a two-word key is not its second noun), accusers are not (`ALIASES`, `display_name`). **6→2**, both real duplicates; board **1→0**. `632` closed. 0 BD/seam. CI `35413055599`. **NOT finished:** `614`(a). Record: `docs/sessions/2026-09-19-render.md`.
