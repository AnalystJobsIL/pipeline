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
| 2026-09-27 | registry | of rows stamped `zero-confirm 2026-08-28: confirmed`, **<=5%** have `health_baseline > 0` (and on 09-28 the same for `zero-confirm 2026-08-29: confirmed` rows, carried from the 09-05 row); above that, strip that run's verdicts | | |
| 2026-09-18 | company-intel | **the held class is legible the morning it is asked.** The first digest whose drain reaches `Mars Antennas And Rf Systems` (gated 7 days by `[2, 2026-09-11]`) prints `1 held (mars-antennas-and-rf)` — or a record landed and it prints nothing |  |  |
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
- **2026-09-01 → 2026-09-04, seven sessions** — folded to pointers, as 2026-08-24→08-31 was: `classifier` x2, `jd-text`, `roles`, `registry` x2, `discovery`, `finisher`, `infra`. Numbers, CI run ids and defects are in `docs/sessions/2026-09-0[1-4]-*.md`. NOT finished: `535`, `542`-`544`, `546`-`557`, `559`-`563`, `565`-`567`, `571`-`574`, `577`, `445`.
- **2026-09-11 `registry`** — six employers published one opening under two names; each declaration was dead because the alias string was a row (`571`, third time). The row's own dated `alias-of <R>` verdict is now READ, and folds when `ALIASES` agrees: 7 pairs, `571` CLOSED. Digital Turbine 0→7 IL. CI `34608347234` **15/16**, 4 inherited. **NOT finished:** `578`, `579`. Record: `docs/sessions/2026-09-11-registry.md`.
- **2026-09-11 `classifier`** — 25 audit claims adjudicated: **6 withdrawn, 18 kept, 1 deferred** (hand lines, `543`). `peak innovation`/`hila & co.` in `_CONFIRMED` + tripwire test; retraction lines re-keyed by `role_id` after INGIMA's re-post (`583`). Refused: five vocabulary arms, the suffix (`584`); chrome 14/32, 0 moved. CI 34611525857 **14/16**, reds inherited. **NOT finished:** `583`, `584`, `321`, `518`. Record: `docs/sessions/2026-09-11-classifier.md`.
- **2026-09-11 `roles`** - three ways a published row lied about itself. `reject_map` stamps the run's own NOs (`543`); `class_contract` shows a frozen verdict (`544`, 38 of 262); `canonical_title` renames 5 blob titles (`585`); `page_closed` closes 4 LinkedIn rows (`586`). A mutant of mine survived CI; killer in `a44abaa`. CI `34639079051` 16/16. **NOT finished:** `580`, `587`. Record: `docs/sessions/2026-09-11-roles.md`.
- **2026-09-11 `jd-text`** — 62 of 177 published rows carried other employers' postings as their description; `extract_jd` cut stored text with the classifier's prose regex. Head+tail furniture, `_HEAD_SKIP`, `page_slice`, durable `jd_refuted`, `closed-by-page`; 96 re-cleaned, 11 re-captured, two-store fixed point. Class **0**, no-JD **10 of 248**, 0 credits. CI `34616479937`: guard-kill success, shards UNRUN. **NOT finished:** `580`, `581`, `591`. Record: `docs/sessions/2026-09-11-jd-text.md`.
- **2026-09-11 `company-intel`** — the gauge read 10 and the same ten names were in it, each held on another company's board and re-asked weekly. Name-only second ask, `fold_aliases`, the drain label (`474`). Queue **10 -> 1**; 12 seam calls, 0 BD. Waves took back an echo arm accepting 13 ruled-different pairs. CI `34650341661` 16/16. **NOT finished:** 595-599. Record: `docs/sessions/2026-09-11-company-intel.md`.
- **2026-09-11 `infra`** — the BD ceiling bound 1 of 14 spenders: the digest's JD fill. Unlimited by operator ruling, `bd:` gauge in the mail, one 14-day cadence for three paid row tools in `queue_state` (a notes cell eleven writers evict). CI `34622790874` **15 of 16**, the red `roles`' surviving `page-closed-row-is-upserted-anyway`. **NOT finished:** 582, 589, 590, 591. Record: `docs/sessions/2026-09-11-infra.md`.

- **2026-09-11 `ats-fetch`** - the freshness verdict sat uncommitted since 08-30 while its class grew 18 -> 19. Landed `BoardAbandoned`/`abandoned-board`; the census read its own refusal; 11 rows re-pointed (9 successfactors), 15 parked: **19 -> 1**. `_sf_country` +6/-0. Applied `193`; `459` untouched (3-lane migration). BD 1. CI `34646349375` **16 of 16**. **NOT finished:** `593`, `594`. Record: `docs/sessions/2026-09-11-ats-fetch.md`.
- **2026-09-12 `infra`** — the discovery step was killed at 25 min printing NOTHING; the pacing that overran it WORKS (4,888 urns/6 credits vs 1,400-3,016/17-23). `PYTHONUNBUFFERED` x11; GNU `timeout` (it outlived cancellation, racing the queue write); `LINKEDIN_TIME_BUDGET_MIN` 18; `discovery` stamp (`180`); JD caps 150/60 + both bounds. CI 34699025683 guard 1,974/1, red INHERITED (`classifier`). **NOT finished:** 599-603. Record: `docs/sessions/2026-09-12-infra.md`.
