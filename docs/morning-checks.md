# Morning checks — the archive

Append-only. `HANDOFF.md`'s `## Morning checks` table holds rows that are due soon or were
answered in the last week; once a row is older than that it moves here **verbatim**, so the
repo keeps a record of how often its own predictions came true.

That record is worth keeping for one reason: on 2026-08-27 the `docs` lane found **fourteen**
`Morning check <date>:` sentences buried in `HANDOFF.md`'s prose and **not one of them had
ever been answered**. When they were finally answered in a batch, **8 of the 17 clauses
failed** — including two that had shipped to subscribers twice (`### Tel Aviv` and
`### Jobgether` both appeared as employer headings in the 2026-08-26 email against checks
that said neither would). A prediction nobody checks is not a safety net; it is a note.

`docs/check_docs.py::check_morning_checks` warns on a row past its date with an empty
verdict, and errors on a verdict the reader cannot check. An unanswered check is deliberately
a **warning** — the session that wrote it is rarely the session that is pushing when it comes
due, and the cheapest way to make an error go green would be to delete the check.

## 2026-08

*(Nothing has aged out yet. The first rows will arrive from `HANDOFF.md` on or after
2026-09-02, seven days after the batch answered on 2026-08-27.)*

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-26 | roles | `Roles:` says `ledger N = store N`; `roles.jsonl` in that day's state commit | 2026-08-27 | PASS — `ledger 135 = store 135`; `b2090f6` lists `cloud_state/roles.jsonl` |

**Moved from `HANDOFF.md` 2026-08-27 by the `roles` lane, verbatim.** The table had sixteen rows answered the same morning and the file sat 3 words under its 3,200-word cap, so no lane could add an entry at all — the cap is meant to force this move, and the "older than a week" rule in the header could not fire because every answered row was from today. Rows due on or before 2026-08-26 and answered are here; the pending ones stayed.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-26 | render | `- **Render:** board N cards` reconciles with the board's row count | 2026-08-27 | PASS — `board 76 cards`, `docs/index.html` 76 rows, `publish: board=76` |
| 2026-08-26 | render | nothing on `Needs a look` from `render` | 2026-08-27 | FAIL — `- **Render:** title-twin Port/Port.io — one posting may be under the wrong name` |
| 2026-08-26 | registry | `tests.yml` mutation gate green under 15 min | 2026-08-27 | FAIL — 08-26 runs 28 and 29 min, both `failure`; 40 consecutive red pushes since 08-25T16:00 |
| 2026-08-26 | registry | 02:30 log `validated N` with those rows keeping `scanned via brightdata` | 2026-08-27 | PASS — `rescued 0 · validated 4 · still unreachable 5` |
| 2026-08-26 | registry | 08:00 auto-expand under 10 min with `dfer (<reason>)` and `LLM-cracked N` | 2026-08-27 | PASS — 4 min; `resolved 3 (LLM-cracked 3) … deferred 247` |
| 2026-08-26 | registry | digest census step without `rung DOWN` | 2026-08-27 | PASS — no match in the digest log |
| 2026-08-26 | registry | mail `Registry:` line = SeeTree only | 2026-08-27 | FAIL — `re-check pool grew: probe_candidates 127 -> 224 (a predicate widened?)`; see the watch list |
| 2026-08-25 | company-intel | `N newer than the store` is 0 after the seed | 2026-08-27 | FAIL — the 08-25 mail read `export 940 records, newest 2026-08-24, 20 newer than the store` |
| 2026-08-26 | infra | the inbox issue at ~06:20 | 2026-08-27 | FAIL — 08-26 issue 07:10:36Z, 08-25 09:01:19Z. NOT the digest's fault: it finished 06:04:14Z, inside the 06:17 window. The relay's OWN polls ran 07:10/08:01/09:04/10:52 — same scheduler, +35..53 min |
| 2026-08-26 | infra | `Stage order:` shows `repair: <date>`; no `workflow step` line on `Stages:` | 2026-08-27 | PASS — `repair: 2026-08-25 (1d ago)`, `Stages: collect links-unread-1` only |
| 2026-08-26 | discovery | `[linkedin] … blocked=` appears | 2026-08-27 | PASS — `free=224 blank=58 blocked=30 paid=13` |
| 2026-08-26 | discovery | no `### Tel Aviv` in the mail | 2026-08-27 | FAIL — `digests/latest.md` still carries `### Tel Aviv` with three secrettelaviv.com jobs |
| 2026-08-26 | discovery | `cache: dropped ~163 agency cards` | 2026-08-27 | FAIL — it dropped **277**; the prediction was 70% low, the mechanism worked |
| 2026-08-26 | ats-fetch | Akamai/Bright Security as `fetch-error scrape:`; `cleared:` names Fortinet/Reindeer/myInterview; Questar and Wiliot absent | 2026-08-27 | PARTIAL — Akamai `fetch-error scrape: http:403 (2 nights)`, Questar/Wiliot absent, Fortinet+Reindeer cleared; **Bright Security is `regressed-to-zero`, not `fetch-error`** |

## Moved 2026-08-27 by the `discovery` lane

Answered the day it came due and moved straight here: `HANDOFF.md` stood at 3,194 of
its 3,200-word cap before this session, so the table could not hold another answered
row and a session line at the same time. Record: `docs/sessions/2026-08-27-discovery.md`.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-27 | discovery | `recovered=N`, `cache: dropped ~18 agency cards`, no `### Jobgether` | 2026-08-27 | PASS — run 33092547374 (the 05:00 cron, 11h18m late): `recovered=5` against `blank=75`, so NOT ~0 — **the re-ask stays**; `cache: dropped 117 agency cards`; `Jobgether` refused by name at intake, so no `### Jobgether` heading |

## Moved 2026-08-28 by the `docs` lane

Answered on 2026-08-27 and moved here **verbatim** the next morning rather than after the
seven days the header names, for the reason BACKLOG 338 records: `HANDOFF.md` stood at
3,194 of its 3,200-word cap, so the 2026-08-28 answers below could not be written until
these came out. Record: `docs/sessions/2026-08-28-docs.md`.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-27 | scraper | Get SAT/BlueBird/Red Access/WSC Sports in `with_jobs` or `links_unread`, never `empty` | 2026-08-27 | PASS on the artefact — no rot record for any of the four; `via` sums to `with_jobs` 201; no `llm-down` |
| 2026-08-27 | ats-fetch | `29 regressed to zero` standing; 0 `?` in `stale.json`; `new:` grouped; no myInterview under `cleared:` | 2026-08-27 | PARTIAL — `stale.json` has 29 `regressed-to-zero` and zero `?`; the two mail-rendered clauses are unanswerable, **no 08-27 digest ran** |
| 2026-08-27 | company-intel | `Company intel:` names sonnet, `N searches`, no `SEARCHLESS`, export count matches the file | — | N/A — no 08-27 digest ran. For the record `firmographics.json` is 973 and `seen.db` 946; the 08-26 mail said 942, so whatever it prints, two of those three will disagree |
| 2026-08-27 | jd-text | `Stage order:` carries `scrape_bd_calls=`/`matched_short=`; `jd-fill:` denominator ~121 | — | N/A — no 08-27 digest ran. 08-26 baseline: `jd-fill: 110/148 … discovery-indeed http-401 17` |
| 2026-08-28 | registry | the drain survived the REAL merge, and the auto-expand `probe:` line shows `N resolved` with `probe-dup-board` among its refusals | 2026-08-27 | PASS, early — `599d7b8` 16:42 UTC: queue **1,693 -> 517** in one commit; the 17:00 run printed `probe: 11 resolved, refused 18 (... probe-dup-board 4 ...)` |

### Answered 2026-08-28, moved the same day

The three checks this morning's `docs` session could answer with a PASS. The `mutation-gate`
row it answered FAIL stays in `HANDOFF.md`, because a failure is a live watch item and a pass
is history. Moved the day they were answered, not after seven days, because `HANDOFF.md` was
84 words over its cap once the `scraper` lane's session line landed in the same rebase —
which is BACKLOG 338 happening for the third time in two days, and BACKLOG 361 is the fix.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-28 | infra | the digest log's `deliver:` line says `delivered`, and `cloud_state/last_delivered.json` carries `2026-08-28` with a sha256 matching `digests/latest.md` | 2026-08-28 | PASS — `deliver: 2026-08-28 delivered -- 5 role(s), sha 5d4a0f8a4256, first delivery for the day`; `last_delivered.json` holds that date and sha, and it is the sha256 of the `digests/latest.md` blob at `9bbaf69` (run 33148916309) |
| 2026-08-28 | infra | the mail's `Stages:` says `the last digest that reached the mail was 2026-08-26 (2d ago)` — once. If it says nothing, `_receipt_alarms` is not wired; if it repeats on 08-29, `deliver` is not writing the receipt | 2026-08-28 | PASS — once, in run 33148916309 and in `digests/latest.md`: `the last digest that reached the mail was 2026-08-26 (2d ago) -- 1 morning(s) produced no digest email`. `_receipt_alarms` is wired |
| 2026-08-28 | registry | the 05:00 `classify:` judges more than yesterday. 42 intake companies went active overnight with 0 cache entries; ~0 judged ⇒ an uncached scrape row ships nothing | 2026-08-28 | PASS — `classify: 5403 judged = keyword 5055 + llm 16 (1 yes) + cache 332` (run 33148916309) against 08-27's `classify: 5263 judged` (run 33092547374) |

**Moved from `HANDOFF.md` 2026-08-28 by the `infra` lane.** The row was kept in `HANDOFF.md` that morning because a FAIL is a live watch item; it stopped being one when the gate was sharded the same afternoon, so it moves here under the rule in the header rather than sitting as a closed failure in the current-state file.

| due | lane | must be true | answered | verdict |
|---|---|---|---|---|
| 2026-08-28 | infra | the `mutation-gate` job FINISHES rather than hitting `timeout-minutes: 45`. It already timed out once: `30bc39f` ran **45m16s, `cancelled`**. It was 44m16s on `c1323d5` before this session, and this session's guards add +19.1s to the baseline suite. A timeout names no surviving mutant — BACKLOG 195/311 | 2026-08-28 | FAIL — `33123785072` was `cancelled` at 45m20s. CLOSED the same day: the catalogue went 105 → 204 while `timeout-minutes: 45` stood still, so the gate was OFF, not slow. Sharded 3 ways (74/64/66), split computed from the catalogue at run time (195@infra) |
