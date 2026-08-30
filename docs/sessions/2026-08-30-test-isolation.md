# 2026-08-30 — `infra` (test isolation): how much of the green is vacuous — a number, a list, and the owners

Base: `origin/master` @ `d01213f`. Clean worktree `.claude/worktrees/testiso-0830`, no
`secrets.env` (dry — nothing here needs a credential; the conftest sentinel keeps it so).

**Spent: 0 Bright Data credits, 0 LLM calls, 0 workflow dispatches.** Every `gh` call a read.

## 0. The brief, re-derived

| claim in the brief | measured |
|---|---|
| `_UNLOCK_SPENT` leaks and a leaked counter that reaches `_UNLOCK_BUDGET` makes the rung inert | the counter leaks (0 → 1, once, in `test_the_unlocker_rung_inside_the_page_test_still_exists`) and **never gets near 100**. It is not the mechanism. |
| every later guard over that rung then passes vacuously | **exactly one guard can, and only in one order** (§2). The rung's precondition (`html < 2000` **and** a key) is reached by **2 of 1,496 tests**. |
| the polluter is a `bd_rescue` test in the same file (386's text) | no. The polluter is an **import**: `confirm_zero`, `apply_proposals` and `drain_queue` each set `identity_gate._UNLOCK_BUDGET = 0` and `PAGE_UNLOCK_BUDGET=0` at module import. Monkeypatch cannot undo either. |
| `-p no:randomly` still fails, so it is ordering | true — and `pytest-randomly` is **not installed** (`pip list`: pytest 9.1.1 only), so the flag is a no-op and the suite order is simply file order: `test_company_intel`, `test_registry`, `test_units`. |
| the full suite is green | true: 1,495 passed, 1 skipped, both with and without the tracer. |

## 1. Method — a tracer, not a reading

Two pytest plugins, run from the scratchpad (`-p trace_rung`, `-p trace_state`), never
committed:

* **`trace_rung`** wraps `identity_gate.page_names_company` ONCE at `pytest_configure` —
  a per-test wrapper is exactly the stale-binding bug it would be measuring (root modules
  bind the name at import, tests `monkeypatch.setattr` it, and the restore hands back the
  previous test's wrapper; the first draft attributed 54 callers to 15) — and records, per
  call, `len(html) < 2000`, whether a key was set, the budget and counter at that moment,
  and whether the counter moved. Per test, budget/counter/`bd_rescue.SPENT`/env before and
  after teardown, and which of the three tools were in `sys.modules`.
* **`trace_state`** snapshots every int/str/dict/list/set attribute of every repo module in
  `sys.modules` (plus the seven credential/budget env names) around each test and reports
  what is still changed after teardown.

Three orders: the default (`python -m pytest`), the same with `-p no:randomly` (identical,
see §0), and the failing two-file order `tests/test_units.py tests/test_registry.py`.

## 2. (1) How many guards pass vacuously — **one**, in one order; **zero** in the shipped order

Tests whose own calls reach the rung's precondition, whole suite, default order:

| idx | test | rung calls | fired | budget in | outcome |
|---|---|---|---|---|---|
| 252 | `test_registry::test_the_unlocker_rung_inside_the_page_test_still_exists` | 4 | 2 | 100 | passed — the positive control |
| 338 | `test_registry::test_the_queue_drain_cannot_spend_a_bright_data_credit` | 1 | 0 | 100 → 0 by its own imports | passed — asserts the lock, real |

Nothing else reaches it: 15 tests call `page_names_company` at all, 13 with long pages or no
key; the other ~40 callers stub the function outright. The budget goes 100 → 0 at idx 338
(`drain_queue`/`apply_proposals` imported inside the test) and `confirm_zero` lands at
345; every test after that runs with the rung dead, and **none of them asks it anything**.

Two-file order (`test_units` first): `test_units::test_the_own_site_rung_demands_a_linkback_
and_cannot_spend_a_credit` (idx 836) imports `confirm_zero` through `auto_expand` and the
budget is 0 from there on.

| test | in that order | with both locks deleted from `drain_queue.py` + `apply_proposals.py` |
|---|---|---|
| the positive control (252) | **FAILS** — `assert None is True`, the brief's reproduction | — |
| the drain-lock guard (338) | passes | **still passes** (2 passed) — VACUOUS: `confirm_zero` had already zeroed the budget |
| the drain-lock guard, default order | passes | **FAILS** — real |

So: **one guard passes vacuously, and only when `test_units` runs first; in the order CI
and every lane's pre-push run use, zero.** The positive control does not pass vacuously
in any order — it fails, which is the better failure and why 386 was noticed at all.

## 3. (2) Other leaked module-level state — 23 names across 54 tests, 4 of the same shape

`trace_state`, default order, after teardown (the pre-existing conftest reset already
covers `bd_rescue.SPENT`):

| shape | names (tests that leave it changed) | reaches its cap in a run? |
|---|---|---|
| **cap counter gating a paid/LLM rung** — the `_UNLOCK_SPENT` shape | `deep_validate._BD["used"]` vs `DEEP_BD_SEARCH_CAP`=150 (1); `listing_hunt._LLM_USED` vs `HUNT_LLM_CAP`=200 (2, self-reset per `main()`); `drain_queue.SEARCH_SPENT` (0 — no test drives it); `identity_gate._UNLOCK_SPENT` (1) | **no** — one or two tests each, single-digit increments |
| **say-once flag** — the `SPENT["capped"]` shape | `audit_empty_rows._SEARCH["warned"]` (1) | one test touches it; a second test asserting the warning would be order-dependent |
| **import-time lock** — the actual 386 mechanism | `identity_gate._UNLOCK_BUDGET` (1), `env.PAGE_UNLOCK_BUDGET` (1 — and inherited by every `subprocess` a later test spawns) | n/a — fixed here |
| single-writer "names I rewrote" sets | `bd_rescue._MOD` (5, grows 0→7), `validate_empty._MODIFIED` (3), `wayback_rescue._MODIFIED` (2), `retry_unreachable._MODIFIED` (1) | grows across tests; whether any merge assertion depends on it is **not measured** — `registry`'s files |
| discovery tallies | `discovery_daily.LI_CARDS_PRESENT` (11), `_blank_retry` (10, reset per sweep), `SOURCE_PATH` (8), `UNLOCKER_CALLS` (4), `_li_last_present` (4) | report-only counters, no cap |
| memo caches | `pipeline.jdfill._registry_rows` (1 — the REAL 1,099-row registry, cached), `_greenhouse_slugs` (1), `queue_pipeline._SEEDS` (1), `resolve_llm._PAGES` (3), `resolve_llm.LAST` (6), `bd_rescue.LAST` (2), `pipeline.run._PHASE` (1), `pipeline.secretsenv._warned` (1) | a leaked cache of the real registry into a test built on a `tmp_path` one is the shape to watch; not measured |
| credential env | `BRIGHTDATA_API_KEY` / `_ZONE` absent ↔ empty (4) | harmless: conftest re-arms the sentinel before each test |

## 4. (3) The fix, and what it changes — measured

`tests/conftest.py`: an autouse fixture puts `_UNLOCK_BUDGET`, `_UNLOCK_SPENT` and
`PAGE_UNLOCK_BUDGET` back to their session-start values BEFORE each test, and prints who
lowered them at session end (`[unlock-rung]`). By §2, no test's rung calls change except the
two: the positive control passes in every order, the drain-lock guard becomes real in every
order. `tests/test_registry.py` needs **no change** — the 386 text's "polluter" diagnosis
does, see §6.

| run | before | after |
|---|---|---|
| `python -m pytest` | 1,495 passed, 1 skipped | **1,499 passed, 12 skipped** (4 new guards; the skip count is the runner-only tests, unchanged) |
| `python -m pytest tests/test_units.py tests/test_registry.py` | 1 failed (the positive control) | **the positive control passes**; 1,357 passed on the first post-fix run, whose one failure was my own docstring tripping the `Kills` scanner — fixed before the commit, re-run pending (§7) |

`[unlock-rung]` at session end names the four tests that lower the budget — the three that
import a locking tool and the positive control's own spend — which is the leak made visible.

## 5. (4) A guard that cannot fail — `tools/guard_kill.py`, and the day's number

`tools/mutate.py` verifies the 226 catalogued mutations and nothing else. `guard_kill`
takes every test function that exists at HEAD and not at `--base`, puts every non-test-side
file back to `--base` in a `git archive` copy (test-side = `tests/test_*.py`, `conftest.py`,
`fixtures/`; `tests/schedule_census.py` and `tests/rehearse_*.py` are code under test and
are reverted — the first draft kept them and mis-called a census guard), and runs the new
tests there. KILLS / CATALOGUED (docstring ``Kills `<id>` `` naming a real record) /
CANNOT-FAIL; exit 1 on the last. `tests.yml` runs it on every push in its own `guard-kill`
job (`fetch-depth: 0`, base = `github.event.before`, `HEAD~1` when that sha is unknown).
Four unit guards in `tests/test_units.py`; the CI-shape one was red until the job existed.

**Today's range, `bfdff0f..d01213f`, 184 new tests** (first run, whole `tests/` kept at
HEAD): KILLS 170, CATALOGUED 2, CANNOT-FAIL 11, NOT-RUN 1. **Corrected run (test-side
only): KILLS 171, CATALOGUED 2, CANNOT-FAIL 10, NOT-RUN 1** — the one that moved was mine.

The 10 (plus mine, plus the skip), with the commit that added each — **the owners** (§6
files them):

| lane | test | commit |
|---|---|---|
| `jd-text` | `test_native_url_derives_the_workday_tenant_from_the_host_label_by_default` | `40aa439` |
| `jd-text` | `test_a_registry_row_on_another_workday_host_cannot_rewrite_a_posting_address` | `40aa439` |
| `jd-text` | `test_the_scrape_pass_is_idempotent_within_a_day` | `40aa439` |
| `jd-text` | `test_merge_json_cache_keeps_the_longer_description_and_a_card_origin_never_saw` | `40aa439` |
| `jd-text` | `test_the_archive_left_and_paid_cooldown_keys_are_the_shape_the_mail_needs` | `fc25aac` |
| `jd-text` | `test_the_archive_nights_verdict_survives_the_morning_that_follows_it` | `fc25aac` |
| `roles` | `test_a_corrupt_file_is_not_a_baseline_for_the_shrink_guard` | `2c8fbe4` |
| `roles` | `test_the_two_sent_ledgers_agree_by_seen_id_not_by_row_count` | `2c8fbe4` |
| `classifier` | `test_a_mass_flip_morning_is_still_caught_when_legacy_rows_are_draining` | `3bf54c2` |
| `registry` | `test_the_judge_never_re_judges_a_name_a_human_overruled` | `861050d` |
| `infra` | `test_cron_watch_alarms_on_a_dropped_or_late_slot_and_on_nothing_else` | `e5fee4d` — mine; it reads `tests/schedule_census.py`, which the first run kept at HEAD. **KILLS** in the corrected run. |
| `docs` (NOT-RUN) | `test_ci_itself_confirms_why_the_tree_check_cannot_run_there` | `7ac03d0` — skipped outside CI; a skip has no node id in `-rA`, so it is reported, not judged |

A CANNOT-FAIL is not automatically a bug: a test that pins behaviour older than the range is
one. It is a test whose author has not shown it can fail, which is the thing this repo has
no other measurement of.

## 6. Filed, per lane — nothing fixed outside `infra`'s files

* `registry` — 386's own text: the polluter is the import-time lock in three of its tools,
  not a `bd_rescue` test; the conftest fixture closes the test-side leak, and the text should
  say so. And the production-side shape found on the way, **unmeasured, for the lane to
  verify**: `queue_pipeline.py --verify-existing` (listing-hunt.yml, key present) →
  `board_verify._mechanical_opinion` calls `gate.identity_ok(name, url)` and then
  `import apply_proposals` — from the second board of the run, the gate's paid rung is at
  budget 0 in that process. Importing `auto_expand`, `pipeline.run`, `registry_health`,
  `queue_pipeline` or `board_verify` at module level leaves the budget at 100 (checked, all
  five), so this is only the function-local import path.
* `registry` — the `_MODIFIED`/`_MOD` sets grow across tests (§3); whether a merge assertion
  in `test_registry.py` depends on a name a previous test rewrote is the measurement to make.
* the 11 CANNOT-FAIL owners above, one item per lane.

## 7. Not finished

* The corrected today-range run and the post-fix suite runs are quoted above only if the
  `TBD_` markers are gone; if one is still here, the run did not finish in the session.
* `guard_kill` judges a push by `github.event.before`; a push of several commits is one
  range, so a test added in commit 2 and its fix in commit 3 is KILLS, and a test whose fix
  landed in an EARLIER push is CANNOT-FAIL on the push that adds it. That is the intended
  reading, and it will name pure regression guards until their authors catalogue them.
* CI verdict: TBD_CI.
