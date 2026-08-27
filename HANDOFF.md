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
| 2026-08-27 | scraper | Get SAT/BlueBird/Red Access/WSC Sports in `with_jobs` or `links_unread`, never `empty` | 2026-08-27 | PASS on the artefact — no rot record for any of the four; `via` sums to `with_jobs` 201; no `llm-down` |
| 2026-08-27 | ats-fetch | `29 regressed to zero` standing; 0 `?` in `stale.json`; `new:` grouped; no myInterview under `cleared:` | 2026-08-27 | PARTIAL — `stale.json` has 29 `regressed-to-zero` and zero `?`; the two mail-rendered clauses are unanswerable, **no 08-27 digest ran** |
| 2026-08-27 | discovery | `recovered=N`, `cache: dropped ~18 agency cards`, no `### Jobgether` | — | N/A — **no 08-27 digest ran**. The pre-committed rule stands: `recovered=`~0 on the runner ⇒ REMOVE the re-ask, do not tune it |
| 2026-08-27 | company-intel | `Company intel:` names sonnet, `N searches`, no `SEARCHLESS`, export count matches the file | — | N/A — no 08-27 digest ran. For the record `firmographics.json` is 973 and `seen.db` 946; the 08-26 mail said 942, so whatever it prints, two of those three will disagree |
| 2026-08-27 | jd-text | `Stage order:` carries `scrape_bd_calls=`/`matched_short=`; `jd-fill:` denominator ~121 | — | N/A — no 08-27 digest ran. 08-26 baseline: `jd-fill: 110/148 … discovery-indeed http-401 17` |
| 2026-08-28 | infra | the digest log's `deliver:` line says `delivered`, and `cloud_state/last_delivered.json` carries `2026-08-28` with a sha256 matching `digests/latest.md` | — | not yet due |
| 2026-08-28 | infra | the mail's `Stages:` says `the last digest that reached the mail was 2026-08-26 (2d ago)` — once. If it says nothing, `_receipt_alarms` is not wired; if it repeats on 08-29, `deliver` is not writing the receipt | — | not yet due |
| 2026-08-28 | infra | `firmographics.yml` fired on its 10:00 slot (BACKLOG 293). At 11:01 on 08-27 its run list was still empty, 61 min after its first real slot — inside the 180-min grace `tests/schedule_census.py` holds before calling a slot dropped | — | not yet due |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-08-28 | infra | the `mutation-gate` job FINISHES rather than hitting `timeout-minutes: 45`. It already timed out once: `30bc39f` ran **45m16s, `cancelled`**. It was 44m16s on `c1323d5` before this session, and this session's guards add +19.1s to the baseline suite. A timeout names no surviving mutant — BACKLOG 195/311 | — | not yet due |
| 2026-08-28 | infra | the `mutation-gate` job finished, rather than hitting `timeout-minutes: 45`. It measured **44 min 16 s** on `c1323d5` and 37 min 44 s on `623b2a9`, both before this session's code. A timeout names no surviving mutant, and `tests.yml` is already red for other reasons — BACKLOG 195 | — | not yet due |
| 2026-08-28 | roles | `ledger N = store N`; `purged 7` once; `reopened` NOT ~70 | — | |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due (`audit-coverage.yml` is `0 4 * * 0`) |

## State at handoff — 2026-08-27 07:5x UTC, every number re-derived

The table this replaces was dated 2026-08-23 and **every cell in it was stale**, including
the `docs` lane's own re-count four lines below it. Two snapshots of a four-day-old
morning, both presented as current state, in the file the brief tells every agent to read
in full. Commands are given so the next reader re-derives rather than trusting.

| | | how |
|---|---|---|
| registry | **1,244 rows · 873 active · 371 parked** | `python check_invariants.py` (it prints 1,245: it counts the header) |
| by tier | **451 native-ATS · 421 scrape · 1 discovery** | `python registry_health.py --census` — and note this moved 18 rows in the hour between `ae6eeae` and `623b2a9` |
| store | **135 matched · 59 sent · 946 firmographics · 516 llm_cache · 112 company_info** | `sqlite3 cloud_state/seen.db` |
| ledger | **135 `roles.jsonl` · 132 `roles_text.jsonl`**, reconciling with the store | `wc -l cloud_state/roles*.jsonl` |
| firmographics export | **973** records — the sqlite table holds 946 and the 08-26 mail said 942 | `len(json.load(open('cloud_state/firmographics.json')))` |
| last digest | **2026-08-26** — 870 scanned, 3 failed, 28 LLM calls, 96 accepted → 65 merged → **8 emailed**, board 76, archive 56 | `digests/latest.md` |
| guards | **988 collected** across `test_units` / `test_registry` / `test_company_intel`; **1 failing** | `python -m pytest -q` |

**`tests.yml` has been red on 40 consecutive pushes** (2026-08-25T16:00 → now), which means
`CLAUDE.md`'s pre-push contract has been broken on every push for two days. The failure is
one assertion: `test_a_role_is_filled_from_another_address_it_was_seen_at` (`assert 170 ==
2021`) — a `jd-text` guard that reads the live `scraped_cache.json`, so a cron can re-break
it without anyone touching code. Filed as `docs/BACKLOG.md` 289 by `registry`; the fix is
`jd-text`'s. **Do not read a red `tests.yml` as "someone else's problem" without checking
it is still only that one.**

## Watch list for the next session

0. **RUN THIS, OR TOMORROW LOOKS EXACTLY LIKE TODAY: `python digest_watchdog.py`.**
   2026-08-27 was not dropped crons, it was **absurdly late** ones: the 00:00 slot landed at
   05:41 and the 02:30 slot at **12:57, +627 min**. For the digest that is the same thing —
   the relay's last poll is 10:17, so late past it is no mail. Nothing in the repo said so;
   a human looking was the only detection. The watchdog is the one tripwire not on GitHub's
   scheduler — read-only, no credential, no dispatch — but it is **not installed**:
   registering the task is an operator action, command in its docstring. `292@infra`.

0b. **A patch script wrote a literal backslash-n into `daily-digest.yml` where a
   continuation was meant.** It would have broken every run: bash reads the `n` as an
   argument, the pipeline step goes red, no board and no mail — daily. It is
   *syntactically valid*, so `bash -n` misses it. Guard:
   `test_no_workflow_run_block_fakes_a_line_continuation`. **Read it before writing a patch
   script that emits YAML.**

0. **250 active rows have an all-time-high job count of ZERO** — 186 of them `scrape` rows
   (where zero is often the correct answer) and **64 native-ATS rows**, which is the
   "the board has moved" set worth chasing. Feed a recovery run the 64, never the 250.
   *(This said 189/61 for one commit on 2026-08-27. The command below refutes it, and it
   was three lines above the command. Re-run it; do not trust this line either.)*

   ```bash
   python -c "import json,csv,io,collections;b=json.load(io.open('cloud_state/health_baseline.json',encoding='utf-8'));r={x['company_name']:x for x in csv.DictReader(io.open('companies.csv',encoding='utf-8')) if x['active']=='true'};z=[n for n,v in b.items() if int(v)==0 and n in r];print(len(z),collections.Counter(r[n]['ats_platform'] for n in z).most_common())"
   ```

   This item has been 75, then 256, then 250 in three places in this file at once, and the
   snippet it shipped with had no `encoding=` so it crashed with a `UnicodeDecodeError` on
   the operator's own Windows machine. Both are fixed above. `ARCHITECTURE.md` §5b carries
   the durable version; **5 active rows still have no baseline entry at all** (it said 0).

   **The Greenhouse EU JSON API does exist** — this item said it did not.
   `boards.eu.greenhouse.io/v1/boards/<slug>/jobs` answers the same JSON as the US host
   (Unframe `unframe`: 32 postings on both). What is NXDOMAIN is `boards-api.eu…`, the
   `-api` form. **Outbrain is not rescued by it either** — it answers `meta.total 0` on both
   hosts — so the worked example this item was built on needs a different diagnosis.

1. **`merge_key` should move onto `firmographics.identity_key`.** `ARCHITECTURE.md` §7c
   counts **13** identity groups where two active rows read one board (this said ~15). It is
   the `matched` PRIMARY KEY, so it needs a migration. `docs/BACKLOG.md` 132–139, `roles`.
2. **`mark_sent` still records intent, not delivery.** `daily-digest.yml` runs it at step
   `Mark digested roles as sent`, before `Persist state back to the repo` and long before the
   06:17 relay. A role can still be burned unsent.
3. **`cloud_state/seen.db` is 1.54 MB** (`ls -l`, not the ~1.2 MB this said) and still holds a
   946-row `firmographics` table that also travels as a 973-record JSON. Dropping it and
   VACUUMing is the biggest single win on the daily binary.
4. **iCIMS is the only unsupported ATS left.** `eightfold`, `phenom`, `successfactors` and
   `jobvite` all have fetchers now; `jazzhr` was deliberately retired. `registry_health.py
   --ats` is derived and correct — run it instead of trusting a list. HiBob is down to **1**
   active row, not 2, so it is moving away from the 3-row trigger, not toward it.
5. **GitHub dispatches these crons when it feels like it, and nothing notices a run that
   never started.** On 2026-08-27 the 00:00 scrape refresh ran at **05:41**, and the 02:30,
   05:00 and 06:00 crons had not fired at all by 07:41 — so no board, no mail, and no alarm,
   because every "the run broke" path fires from *inside* a later digest. `firmographics.yml`
   (added 08-26, cron `0 10 * * *`) has **never once fired**. `docs/AUTOMATION.md` has the
   measured drift; the fix is `infra`'s (`docs/BACKLOG.md`).

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
5. **The probe pool alarms every morning and the registry lane calls the same jump
   intentional.** The mail reads `re-check pool grew: probe_candidates 127 -> 224 (a
   predicate widened?)`; the 08-25 session records `probe 127→228` as the designed effect of
   keying pools on row facts. One of the two is wrong. Either re-baseline
   `cloud_state/registry_census.json` in the same commit as a deliberate widening, or stop
   calling the pool flat. `registry`.

**Closed since this list was written, verified 2026-08-27:**
*(6) `candidate_probe.json` and `scrape_rot.json` were never-yet-exercised in cloud — both
are present and in the 08-26 state commit. (7) CI conflict-recovery clobbering `seen.db` —
`grep -rn "reset --hard" .github/workflows/*.yml` returns nothing; all nine state-committing
workflows go through `persist_state.py commit`, which the `infra` session recorded three
entries further down this same file.*

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24 `scraper`** — error is not empty **NOT finished:** rot-parked page-empty rows never reach the hunt (`registry`, 84). Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-24 `ats-fetch`** — see the record **NOT finished:** the row edits, BACKLOG 76-83. Record: `docs/sessions/2026-08-24-ats-fetch.md`.
- **2026-08-24 `company-intel`** — one bounded cloud path **NOT finished:** chain retirement (BACKLOG 97), 29 duplicate groups (98), stage label (99, `render`). Record: `docs/sessions/2026-08-24-company-intel.md`.
- **2026-08-24 `jd-text`** — one ladder, a reason for every failure, the layer in the mail **NOT finished:** BACKLOG 105–113. Record: `docs/sessions/2026-08-24-jd-text.md`.
- **2026-08-24 `classifier`** — one bounded seam, a reason for every verdict, the tier in the mail — 2 Opus design attacks + 5 attacker sessions + 3 confirmers **NOT finished:** 116, 118–124, 126, 128–130. Record: `docs/sessions/2026-08-24-classifier.md`.
- **2026-08-25 `registry`** — today's logs, the pending backlog, §2/§3 re-verified **NOT finished:** batches 4–5 (path-tenant 33/50/22/37/198/9/51. Record: `docs/sessions/2026-08-25-registry.md`.
- **2026-08-25 `infra`** — one delivery path, the mail says when a run broke **NOT finished:** BACKLOG 153–170 (167–169 are today's mail oddities. Record: `docs/sessions/2026-08-24-infra.md`.
- **2026-08-25 `render`** — the split: `jdtext.py` (text->structure) -> `rolecard.py` (one card, never raises) -> `digest.py` (rendering only); the `Render:` mail line and its alarms. **NOT finished:** BACKLOG 142-146. Record: `docs/sessions/2026-08-24-render.md`.
- **2026-08-25 `roles`** — the role record gets an owner, a text ledger and a mail line — 1 Opus design attack + 4 attacker sessions, wave 2 confirmers **NOT finished:** BACKLOG 132–139 (retire `matched`, the 13 registry alias groups, a jsonl row-merge on the conflict path, discovery roles never close). Record: `docs/sessions/2026-08-24-roles.md`.
- **2026-08-25 `discovery`** — the run audit **NOT finished:** the `Tel Aviv` row/cache/7 ledger roles (registry+roles, 167), the false `linkedin-targeted: nothing for 3d` alarm from 08-26 (179), 178–187. Record: `docs/sessions/2026-08-24-discovery.md`.
- **2026-08-26 `ats-fetch`** — the scraper's overnight verdict reaches board health **NOT finished:** 207–214. Record: `docs/sessions/2026-08-26-ats-fetch.md`.
- **2026-08-26 `scraper`** — never discard what the runner cannot read **NOT finished:** 215–220 (why the runner is refused is only knowable from the 08-27 rot codes). Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-26 `ats-fetch`** — the mail hid two of three new fetch errors **NOT finished:** 227–237. Record: `docs/sessions/2026-08-26-ats-fetch.md`.
- **2026-08-26 `discovery`** — the coverage audit, and the dry run that changed the answer Record: `docs/sessions/2026-08-24-discovery.md`.
- **2026-08-26 `company-intel`** — the last bare `claude -p` Record: `docs/sessions/2026-08-26-company-intel.md`.
- **2026-08-26 `scraper`** — a reading that names roles but knows none of their addresses must not END the ladder **NOT finished:** , and each says why: 243 (harness tooling), 247 (a place list is never finished. Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-26 `jd-text`** — what the layer spends, what it refuses to fetch, and the text that was already ours **NOT finished:** 155's inline half ONLY, and it is a real dependency. Record: `docs/sessions/2026-08-26-jd-text.md`.
- **2026-08-27 `registry`** — the tier that never once reached the model **NOT finished:** nothing in the rehearsal, the `no-url` false alarm (282, `check_invariants.py` -- `triage_dark.MODES` is exported and pinned, so it is one import line), the `Registry:` production line (275…. Record: `docs/sessions/2026-08-24-registry.md`.

- **2026-08-27 `infra`** — the recovery cron and the watchdog I came to build are both REJECTED: 0 isolated cron drops measured, and a watchdog writing `latest.md` can silently overwrite a delivered digest. What was broken was the unconditional `cp`; `persist_state.py deliver` replaces it. **NOT finished:** 292, 304-308. Record: `docs/sessions/2026-08-27-infra.md`.
- **2026-08-27 `docs`** — the linter was green while three attackers found 46 measured contradictions in these same documents. Numbers a doc states are registered facts now; HANDOFF is 56 KB -> 18 KB with all 14 morning checks answered (8 failed); `docs/backlog.py` gives a lane its own list. **NOT finished:** BACKLOG 291, 295-302. Record: `docs/sessions/2026-08-27-docs.md`.
- **2026-08-27 `roles`** — one `seen_id` named sixteen roles, and the merge kept the best member, not the best field. Shipped: a tenant-keyed `seen_id`, an origin-gated merge, a run log. **NOT finished:** 311-313. Record: `docs/sessions/2026-08-27-roles.md`.

*The 2026-08-23 morning session (seventeen defects, A–Q) and the digest-run history that
used to open this file are in `docs/sessions/2026-08-23.md`, which is where the long
version already was.*
