# 2026-08-28 · infra · the pre-push gate was a spender

Base: `origin/master` @ `759ba36`, in a clean worktree. Closes `docs/BACKLOG.md` **381** and
the `[bd-spend] bought 3` line `registry` routed here as **374** — one event, not two.
Decision and rejected alternatives: `docs/decisions/2026-08-28-tests-cannot-spend.md`.

**Spent: 0 Bright Data credits, 0 LLM calls.** Nothing here touches the network; the one
experiment that needed a credential used a deliberately fake key.

## What was wrong

`python -m pytest` could buy Bright Data credits, and did.

Reproduced at `759ba36`, no `secrets.env` anywhere:

```
$ python -m pytest tests/test_registry.py -q
[bd-spend] this step bought 3 Bright Data credit(s) (no cap set)
$ git status --porcelain
 M cloud_state/bd_spend.jsonl
$ tail -1 cloud_state/bd_spend.jsonl
{"at":"...","cap":null,"capped":false,"credits":3,"pid":34508,"tool":"__main__.py"}
```

With a `secrets.env` beside it, **4 credits across two tests — 381's number exactly**:

```
    1  test_validate_empty_a_readable_page_decides_and_a_refusal_is_visible
    3  test_bd_rescue_reads_the_unlockers_error_code_and_never_retries_a_policy_host
```

**The 3 were phantom; the 1 was real.** The second test stubs `urlopen`. The first does not —
with the new guard installed it dies on `PaidCallInTests: a test reached
https://api.brightdata.com/request`. 381 hoped "the count is probably phantom, but nothing
proves it". Something proves it now: three quarters phantom, and one request really bought.

Two defects, both this lane's:

1. `SPENT["n"] += 1` sat one line **above** the two `os.environ[...]` reads in
   `unlock_status`, so a call that died on a missing zone booked a credit it never spent.
2. The `atexit` reporter added that morning (`47719bc`) wrote those fabrications into the
   tracked ledger — and `persist_state` auto-owns that path for every workflow, so a
   fabricated line is staged and committed **by design**. The artefact built to be believed
   by a later session was the one being falsified.

## What changed

- **`tests/conftest.py`** (new; there was none). Wraps `urllib.request.urlopen` and refuses
  `api.brightdata.com`. Holds both credential names present-and-empty, re-armed before every
  test. Drains `bd_rescue.SPENT` after every test and names the leaker in one line at session
  end.
- **`bd_rescue.py`.** The credit is counted after the request is built. `_report_spend`
  refuses the ledger when `pytest` is in `sys.modules` and `ROOT` holds a `.git`. The record
  gains `ci: true|false`.
- **Five guards** in the `lane: infra` block of `tests/test_units.py`.
- Docs: `ARCHITECTURE.md` §1a (a third cost mechanism) and the §5 state-file row;
  `docs/AGENT_BRIEF.md` (rule 5 — it had **no rule about money at all**, and its "local runs
  are safe by default" line was false about spend); `docs/BRIGHTDATA.md` (the ceiling moved to
  `pipeline/bd_budget.py`; `BD_RUN_CAP` was missing from the cap table).

## The three things that were nearly wrong, and are worth remembering

1. **`Exception` would have been swallowed.** All three unlockers end in a blanket
   `except Exception` that returns `("", "timeout")` or `None`. A guard raising an `Exception`
   subclass leaves the suite green while doing nothing. `PaidCallInTests` derives from
   `BaseException` for that one reason.
2. **Popping the credential names is not a lock — it is the hole.** All four `_load_secrets`
   copies arm the environment with `os.environ.setdefault`, which fills an *absent* name. The
   first version of the conftest popped them; with a `secrets.env` present the key came
   straight back and a test reached the live account. Measured, then changed to
   present-and-empty. **Do not "tidy" that back into a `pop`.**
3. **A guard that passes alone and fails in the suite is telling you something.**
   `test_the_suite_holds_no_bright_data_credential` went red only in the full run: tests that
   `delenv` these names leave them ABSENT, which is exactly the state `setdefault` re-arms.
   The fixture now restores the sentinel *before* each test rather than after — also because
   the ordering between two function-scoped fixtures' finalisers is not defined.

Three cap-shaped guards were tried and rejected on measurement, not taste: `BD_RUN_CAP=0`
(guards one of six billing paths, and `tests/test_units.py` pops the variable mid-session),
`PAGE_UNLOCK_BUDGET=0` (reds `test_the_unlocker_rung_inside_the_page_test_still_exists`), and
`sys.modules["bd_rescue"] = None` (`drain_queue` records that it broke 77 tests).

## What I did NOT finish

- **382–386**, all filed: the `SPENT`/`BD_RUN_CAP` leaks in `tests/test_registry.py`
  (registry's file, and registry was live on 380 tonight); the ledger that has a writer and no
  reader; the three other `secrets.env` loaders; `bd_employees.unlock` as a second
  uninstrumented spend path; and `identity_gate._UNLOCK_SPENT` leaking the way `SPENT` did,
  which makes later guards pass vacuously.
- **The worktree half of 381 has no mechanism, deliberately.** A deliberate
  `python -m pipeline.run` or `python bd_rescue.py` from a worktree with a copied `secrets.env`
  still spends. That is rule 5 in `docs/AGENT_BRIEF.md` and `JD_BD=0 BD_RUN_CAP=0`, not code —
  the reasoning, including why a worktree-conditional guard is the wrong cut, is in the
  decision record.
- Master is **not** fully green: three failures pre-date this session and none is this lane's
  (`test_no_two_active_rows_share_a_board`, `test_native_url_is_derived_from_the_public_url_alone`,
  `test_every_open_role_in_the_ledger_carries_a_job_description`). The list is byte-identical
  before and after this change.
