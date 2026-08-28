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
| 2026-08-29 | infra | `firmographics.yml` fired on its 10:00 slot (BACKLOG 293). At 11:01 on 08-27 its run list was still empty, 61 min after its first real slot — inside the 180-min grace `tests/schedule_census.py` holds before calling a slot dropped | — | not yet due — re-dated by `docs` at 07:57Z, before the 10:00 slot |
| 2026-09-10 | infra | `python tests/schedule_census.py --days 14` — **≥ 3 isolated single-slot drops ⇒ build the recovery digest cron; otherwise it stays rejected.** It was 0 on 2026-08-27 | — | not yet due |
| 2026-08-28 | roles | `ledger N = store N`; `purged 7` once; `reopened` NOT ~70 | — | |
| 2026-08-29 | registry | the 08:00 auto-expand log ends `bound=batch`, `walked N of N`, `probe-noboard` among its refusals | — | not yet due — re-dated by `docs` at 07:57Z; `auto-expand.yml` is `0 8,20` and the 08:00 slot had not fired (33140809914 at 04:05Z is 08-27's delayed 20:00) |
| 2026-08-29 | infra | the 02:28 `bd_rescue` pass reports ~43 NEW names, **≤215 unlock calls** (`registry` widened `in_retry_pool` 4 → 47 for `320`); too costly ⇒ narrow the paid half | — | not yet due — re-dated by `docs`: the 02:30 `retry-unreachable` slot did not fire on 08-28; its last run 33074336185 is 08-27T12:57Z, so there is no pass to read (BACKLOG 358) |
| 2026-08-31 | registry | `deep rung: N of M dark rows` in the audit log; `audit_seen.json` in that day's state commit | — | not yet due (`audit-coverage.yml` is `0 4 * * 0`) |
| 2026-08-29 | infra | **the relay's first end-to-end proof.** The 05:00 digest logs `relay notified:` and `AnalystJobsIL/inbox` shows an `event=push` run that CREATES an issue. Key + both secrets installed; trigger, credential and content path proven, `gh issue create` under a push event not | | not yet due |
| 2026-09-11 | infra | re-measure the cache-shrink threshold from a fortnight of `cloud_state/persist_log.jsonl`: `>=10 keys AND >=3%` is provisional on n=3 (16/279, 16/221, 24/243). Fired on a night nobody thinks was wrong ⇒ loosen it (§5d) | | not yet due |
| 2026-08-29 | scraper | the 05:00 `collect:` line carries `uncached=` and `unvisited=`, and `Stage order:` renders both. The 70 boards cached on 08-28 are scanned: expect **~22 new title-passing roles judged, of which ~6 accept deterministically and ~16 reach the LLM tier** | | not yet due |

## State at handoff — 2026-08-27 07:5x UTC, every number re-derived

The table this replaces was dated 2026-08-23 and **every cell in it was stale**, including
the `docs` lane's own re-count four lines below it. Two snapshots of a four-day-old
morning, both presented as current state, in the file the brief tells every agent to read
in full. Commands are given so the next reader re-derives rather than trusting.

| | | how |
|---|---|---|
| registry | **1,266 rows · 893 active · 373 parked** | `python check_invariants.py` (it prints 1,267: it counts the header) |
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
it is still only that one** — on 2026-08-27 it was not (`320@registry`, closed).

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

0. **Active rows with an all-time-high job count of ZERO — run the command, do not read a
   number here.** This line has now been wrong three times in one day (75, then 256, then
   250/186/64) and every correction was overtaken within hours by a digest rewriting the
   baseline. After the 13:04 run it is 241 / 182 scrape / 59 native-ATS, and 0 active rows
   have no baseline entry at all (it said 5).

   **And the framing was worse than the numbers.** This item called the native-ATS slice
   "the board has moved" and told the next session it was the highest-yield recovery set.
   Measured by `registry` on 2026-08-27: **36 of the 59 are already in `stale.json`**, i.e.
   already owned by the 06:00 self-heal; the great majority carry their own
   `re-audit 2026-08-21: verified 0/0 IL` note; and **exactly one row (Dell) carries
   moved-tenant evidence.** It is not a recovery set. The defect-shaped slice inside it is
   the Workday globals — see watch-item 6.

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
6. **~24 active rows are re-checked by NOTHING, and `ARCHITECTURE.md` §2's headline claim
   ("every state except `defunct:` and `domain-dead` is re-checked on some cadence") is
   false because of it.** Found by `registry` on 2026-08-27.
   `health.zero_is_a_measurement()` exempts `israel_scoped` fetchers from `empty-board` for
   a good, documented reason — 25 healthy Workday boards clogged the self-heal queue on
   08-24 — but the cost was never written down: such a row never enters `stale.json`, so it
   never enters `resolve_broken.candidates()` (whose scope IS `stale.json`), and every
   parked pool excludes it on `active == false`. `repair_dead_urls` is the one pool with no
   active filter and it selects on the hostname failing to resolve, which a live Workday
   tenant's does not. Broadcom's note says "Tel Aviv postings confirmed live" while its
   all-time high is 0; one free POST settles which.

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
5. **`--census` rewrites its own baseline every digest run**, so a pool alarms at most once
   and a slow drift never alarms at all. `315@registry`.

**Closed since this list was written, verified 2026-08-27:**
*(6) `candidate_probe.json` and `scrape_rot.json` were never-yet-exercised in cloud — both
are present and in the 08-26 state commit. (7) CI conflict-recovery clobbering `seen.db` —
`grep -rn "reset --hard" .github/workflows/*.yml` returns nothing; all nine state-committing
workflows go through `persist_state.py commit`, which the `infra` session recorded three
entries further down this same file.*

## Session log — newest last

One line per session, in the shape at the top of this file. The long version is the
`Record:` each line names.

- **2026-08-24, six lanes** — `ats-fetch`, `classifier`, `company-intel`, `jd-text`,
  `registry`, `scraper`. Folded to a pointer on 2026-08-27 to keep this file inside the
  word cap it sets: each entry named a record and the records hold the long version.
  `docs/sessions/2026-08-24-*.md`.
- **2026-08-25 `registry`** — today's logs, the pending backlog, §2/§3 re-verified **NOT finished:** batches 4–5. Record: `docs/sessions/2026-08-25-registry.md`.
- **2026-08-25 `infra`** — one delivery path, the mail says when a run broke **NOT finished:** BACKLOG 153–170 (167–169 are today's mail oddities. Record: `docs/sessions/2026-08-24-infra.md`.
- **2026-08-25 `render`** — the split: `jdtext.py` (text->structure) -> `rolecard.py` (one card, never raises) -> `digest.py` (rendering only); the `Render:` mail line and its alarms. **NOT finished:** BACKLOG 142-146. Record: `docs/sessions/2026-08-24-render.md`.
- **2026-08-25 `roles`** — the role record gets an owner, a text ledger and a mail line — 1 Opus design attack + 4 attacker sessions, wave 2 confirmers **NOT finished:** BACKLOG 132–139 (retire `matched`, the 13 registry alias groups, a jsonl row-merge on the conflict path, discovery roles never close). Record: `docs/sessions/2026-08-24-roles.md`.
- **2026-08-25 `discovery`** — the run audit **NOT finished:** the `Tel Aviv` row/cache/7 ledger roles (registry+roles, 167), the false `linkedin-targeted: nothing for 3d` alarm from 08-26 (179), 178–187. Record: `docs/sessions/2026-08-24-discovery.md`.
- **2026-08-26 `ats-fetch`** — the scraper's overnight verdict reaches board health **NOT finished:** 207–214. Record: `docs/sessions/2026-08-26-ats-fetch.md`.
- **2026-08-26 `scraper`** — never discard what the runner cannot read **NOT finished:** 215–220 (why the runner is refused is only knowable from the 08-27 rot codes). Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-26 `ats-fetch`** — the mail hid two of three new fetch errors **NOT finished:** 227–237. Record: `docs/sessions/2026-08-26-ats-fetch.md`.
- **2026-08-26 `discovery`** — the coverage audit, and the dry run that changed the answer Record: `docs/sessions/2026-08-24-discovery.md`.
- **2026-08-26 `company-intel`** — the last bare `claude -p` Record: `docs/sessions/2026-08-26-company-intel.md`.
- **2026-08-26 `scraper`** — a reading that names roles but knows none of their addresses must not END the ladder **NOT finished:** 243, 247. Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-26 `jd-text`** — what the layer spends, what it refuses to fetch, and the text that was already ours **NOT finished:** 155's inline half ONLY, and it is a real dependency. Record: `docs/sessions/2026-08-26-jd-text.md`.
- **2026-08-27 `registry`** — the tier that never once reached the model **NOT finished:** 275, 282. Record: `docs/sessions/2026-08-24-registry.md`.
- **2026-08-27 `registry` (2)** — the intake queue was owned by nothing and the one search rung returned `[]` for every query. Fixed both; 134 names became rows, 42 active. **NOT finished:** ~350 exhausting, the classifier count, 340. Record: the session log's "Continuation state".

- **2026-08-27 `infra`** — the recovery cron and the watchdog I came to build are both REJECTED: 0 isolated cron drops measured, and a watchdog writing `latest.md` can silently overwrite a delivered digest. What was broken was the unconditional `cp`; `persist_state.py deliver` replaces it. **NOT finished:** 292, 304-308. Record: `docs/sessions/2026-08-27-infra.md`.
- **2026-08-27 `docs`** — the linter was green while three attackers found 46 measured contradictions in these same documents. Numbers a doc states are registered facts now; HANDOFF is 56 KB -> 18 KB with all 14 morning checks answered (8 failed); `docs/backlog.py` gives a lane its own list. **NOT finished:** BACKLOG 291, 295-302. Record: `docs/sessions/2026-08-27-docs.md`.
- **2026-08-27 `roles`** — one `seen_id` named sixteen roles, and the merge kept the best member, not the best field. Shipped: a tenant-keyed `seen_id`, an origin-gated merge, a run log. **NOT finished:** 311-313. Record: `docs/sessions/2026-08-27-roles.md`.
- **2026-08-27 `registry`** — `activation_ok` admitted 9 of 12 name-guessed boards, 6 another employer's: a slug made from the name near-equals the name. Shipped a free rung on `il>=1` + a queue drain (1,693->498); the 17:00 run added 11 rows, 3 relevant roles, 0 credits. **NOT finished:** 317-323. Record: `docs/sessions/2026-08-27-registry.md`.
- **2026-08-27 `discovery`** — secrethunter's JSON-LD is crawler-UA-gated; the sitemap is not. Shipped it as a names source (2,002 new, 150/run, 0 credits), backfilled 71 of 135 missing handles, + the reject ledger (70). **NOT finished:** 321, 333-339 (339 = the coupled intake/site-guess caps). Record: `docs/sessions/2026-08-27-discovery.md`.

*The 2026-08-23 morning session (seventeen defects, A–Q) and the digest-run history that
used to open this file are in `docs/sessions/2026-08-23.md`, which is where the long
version already was.*
- **2026-08-28 `jd-text`** - 10 of 70 open roles held text our own parser rejects, 4 of them page furniture with no JD. `is_job_url` reads a `/careers/<slug>` with the role's title, `looks_like_jd` replaces the length-only gate, a JD outranks furniture even when shorter. **67 of 70 now carry a description, was 60.** **NOT finished:** 341-344, the render bug. Record: `docs/sessions/2026-08-28-jd-text.md`.
- **2026-08-28 `scraper`** - 287 of 496 active `scrape` rows had no cache entry, so nothing downstream saw them and nothing counted them. Cached **70 boards / 435 postings** for **0 BD credits**; `uncached`/`unvisited` now stamp on `collect`; wave 1 killed an identity leak before it shipped. **NOT finished:** 345, 348, 350, 356. Record: `docs/sessions/2026-08-28-scraper.md`.
- **2026-08-28 `infra`** - the relay fires on a PUSH from the digest, not a clock GitHub is dropping; the unlocker rung is switchable, capped and visible; every commit measures the caches it pushes - 279->263 was 16/16 `why=empty`, NOT the error class (363@scraper); `mutation-gate` sharded after 105->204. **NOT finished:** 292/308, 365, 305. Record: `docs/sessions/2026-08-28-infra.md`.
- **2026-08-28 `docs`** - a census fact that fails because the project is WORKING is a broken check: `active_rows` blew its `~900` bracket at 969 and would have skipped `Registry invariants` on the next push. Census claims are one-sided floors now. **NOT finished:** BACKLOG 357-362, 368. Record: `docs/sessions/2026-08-28-docs.md`.
