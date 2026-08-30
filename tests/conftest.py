"""The pre-push gate may not spend money (lane: infra; BACKLOG 374, 381).

`python -m pytest` is the one command every session runs before every push
(`docs/AGENT_BRIEF.md`, "Rules that will bite you"), and on pristine master it was a spender:
it printed `[bd-spend] this step bought 3 Bright Data credit(s)` and appended
`{"credits":3,"tool":"__main__.py"}` to the tracked `cloud_state/bd_spend.jsonl`. With a
`secrets.env` beside it -- which `CLAUDE.md` tells sessions to keep for local runs, and which
the `jd-text` lane copied into a worktree on 2026-08-28 -- the same run reaches the live
account. Bright Data is 5,000 requests/month with no rollover and the overage is a one-time
sum the operator will not top up, so an accidental credit is permanent.

WHY THE TRANSPORT AND NOT THE VENDOR'S ENV VARS. The obvious locks were all measured against
this tree and all fail:

  * `BD_RUN_CAP=0` guards ONE of the four modules that POST to `api.brightdata.com`
    (`bd_rescue`, `bd_employees`, `pipeline/jdfill`, `setup_brightdata`) and neither of the
    two that trigger a `datasets/v3` job -- and `tests/test_units.py`'s own run_cap guard
    pops `BD_RUN_CAP` from `os.environ` with no restore, so every test after it would run
    uncapped anyway. It also breaks `tests/test_registry.py`'s stubbed-unlock assertion.
  * `PAGE_UNLOCK_BUDGET=0` (what `drain_queue._lock_the_paid_rungs` does) buys nothing here --
    the gate's paid rung goes through `bd_rescue.unlock` like everything else -- and breaks
    `test_the_unlocker_rung_inside_the_page_test_still_exists`, which uses the ambient budget
    as its positive control.
  * `sys.modules["bd_rescue"] = None` broke 77 tests when `drain_queue` tried it. A lock whose
    blast radius is the interpreter is a landmine, not a lock.

Banning the transport covers every present and future spender, breaks no test (every test that
exercises the wire replaces `urlopen` itself, and monkeypatch restores OUR wrapper), and
behaves identically in CI, in the primary checkout and in a worktree -- so it cannot produce
the false local green that `docs/BACKLOG.md` records from the last environment-conditional
guard. `tests.yml` passes no Bright Data secrets, so this only ever changes a developer
machine: it makes a local run behave like the CI run that is already green.
"""
import os
import sys
import urllib.request
from urllib.parse import urlsplit

import pytest

# Hosts that bill. `api.brightdata.com` serves both the Web Unlocker (`/request`) and the
# dataset triggers (`/datasets/v3/trigger`), which bill per RECORD.
PAID_HOSTS = {"api.brightdata.com"}


class PaidCallInTests(BaseException):
    """Raised when a test reaches a host that costs money.

    **`BaseException`, deliberately.** `bd_rescue.unlock_status`, `bd_employees.unlock` and
    `pipeline/jdfill`'s unlocker all wrap their request in a blanket `except Exception` that
    turns any failure into `("", "timeout")`. An `Exception` subclass would be swallowed
    there and the suite would stay green while this guard did nothing -- the silent-pass
    shape this repo keeps paying for.
    """


_real_urlopen = urllib.request.urlopen


def _no_paid_calls(req, *args, **kwargs):
    url = req if isinstance(req, str) else getattr(req, "full_url", "")
    if urlsplit(url).hostname in PAID_HOSTS:
        raise PaidCallInTests(
            f"a test reached {url} -- that is real money. Stub `urllib.request.urlopen` (or "
            f"the caller) in this test; see tests/conftest.py and docs/BACKLOG.md 381."
        )
    return _real_urlopen(req, *args, **kwargs)


urllib.request.urlopen = _no_paid_calls

# SET TO EMPTY, NEVER POPPED -- and that one word is the difference between working and not.
# Four modules carry their own copy of `_load_secrets` (`bd_rescue`, `bd_employees`,
# `pipeline/run`, `pipeline/jdfill`) and every one of them arms the environment from
# `secrets.env` with `os.environ.setdefault`, which fills a name that is ABSENT. Popping the
# names therefore hands the key straight back the first time any of them runs; an empty string
# is present, so `setdefault` declines, and it is falsy everywhere the repo tests for a
# credential (`identity_gate`'s paid rung, `bd_rescue.main`'s presence check).
#
# Measured, not assumed: with a `secrets.env` beside it and these names merely POPPED, the
# registry file re-armed the key and `test_validate_empty_a_readable_page_decides_and_a_refusal
# _is_visible` reached `https://api.brightdata.com/request` for real. That is the 381 incident,
# reproduced. With them emptied it takes the no-key path -- byte for byte what CI does, which
# is the point: a local run must not diverge from the run that is already green.
for _k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE"):
    os.environ[_k] = ""


_leaked: list[tuple[str, int]] = []
_rung_leaked: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def _the_gates_paid_rung_is_re_armed_before_each_test(request):
    """`pipeline/identity_gate`'s `_UNLOCK_BUDGET` / `_UNLOCK_SPENT` and `PAGE_UNLOCK_BUDGET`
    are put back to their session-start values BEFORE every test (BACKLOG 386, measured
    2026-08-30 -- `docs/sessions/2026-08-30-test-isolation.md`).

    The leak is not the counter. `_UNLOCK_SPENT` reaches 1 of 100 in a whole run. The leak is
    the BUDGET: `confirm_zero`, `apply_proposals` and `drain_queue` each set
    `identity_gate._UNLOCK_BUDGET = 0` and `PAGE_UNLOCK_BUDGET=0` at IMPORT, monkeypatch
    cannot undo either, and the first test to import one of them (a function-local import,
    so it depends on which test runs first) disarms the rung for every test after it.
    Measured per test with a tracing plugin: exactly two tests in the suite reach the rung's
    precondition. `test_the_unlocker_rung_inside_the_page_test_still_exists` is the positive
    control and FAILS, not vacuously passes, when it runs after the import (`pytest
    tests/test_units.py tests/test_registry.py`); `test_the_queue_drain_cannot_spend_a_
    bright_data_credit` asserts the locks and passes VACUOUSLY in that order -- with both
    locks deleted it still passed, because `confirm_zero` had zeroed the budget earlier.
    Re-arming before each test makes the first pass in every order and the second real in
    every order; no other test's rung calls change, because no other test makes any.

    Re-armed BEFORE, like the credential sentinel: a test's own imports may then lower the
    budget (that is what the drain guard asserts), and the next test starts at 100 again.
    Who left it lowered is printed at session end, never failed -- the polluter is another
    lane's file."""
    gate = sys.modules.get("pipeline.identity_gate")
    if gate is not None:
        gate._UNLOCK_BUDGET = _INITIAL_UNLOCK_BUDGET
        gate._UNLOCK_SPENT = 0
    if _INITIAL_PAGE_UNLOCK_ENV is None:
        os.environ.pop("PAGE_UNLOCK_BUDGET", None)
    else:
        os.environ["PAGE_UNLOCK_BUDGET"] = _INITIAL_PAGE_UNLOCK_ENV
    yield
    gate = sys.modules.get("pipeline.identity_gate")
    if gate is not None and (gate._UNLOCK_BUDGET != _INITIAL_UNLOCK_BUDGET or gate._UNLOCK_SPENT):
        _rung_leaked.append((request.node.nodeid,
                             f"budget {gate._UNLOCK_BUDGET} spent {gate._UNLOCK_SPENT}"))


# Read ONCE, at conftest import: the gate's budget comes from this env var at ITS import, and
# every test must start where the session started, not where the previous test left it.
_INITIAL_PAGE_UNLOCK_ENV = os.environ.get("PAGE_UNLOCK_BUDGET")
_INITIAL_UNLOCK_BUDGET = int(os.environ.get("PAGE_UNLOCK_BUDGET", "100") or 0)   # identity_gate.py:81


@pytest.fixture(autouse=True)
def _no_bright_data_state_survives_a_test(request):
    """Two pieces of shared mutable state, re-armed BEFORE each test and drained after it.

    **Before: the empty-string sentinel.** Restoring it per test is not belt-and-braces, it
    closes a real hole. Several tests `delenv` these names, and a name that is ABSENT is one
    `_load_secrets` away from holding the operator's real key again -- `setdefault` fills an
    absent name and declines a present one. Setting it at the START (not the end) also makes
    the state independent of whether monkeypatch's finaliser happens to run before or after
    this one, which is not ordered between two function-scoped fixtures.

    **After: `bd_rescue.SPENT`.** It is module state shared by the whole session, and a test
    that drives the real `unlock_status` mutates it IN PLACE, which monkeypatch cannot undo.
    One test leaves it at 3 and the `atexit` reporter then announces three credits nobody
    bought. Remember who leaked, so the number is a name rather than a mystery. This CONTAINS
    the leak; it does not fix the test that causes it, which is another lane's file. A printed
    line, never a failure -- turning someone else's test red is not this guard's job.
    """
    for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE"):
        if os.environ.get(k):
            os.environ[k] = ""                  # a real value must never reach a test
        elif k not in os.environ:
            os.environ[k] = ""                  # absent is what lets setdefault re-arm it
    yield
    mod = sys.modules.get("bd_rescue")          # no import: adding one would put this file
    if mod is None:                             # into the MODULES.md import graph for nothing
        return
    if mod.SPENT.get("n"):
        _leaked.append((request.node.nodeid, mod.SPENT["n"]))
        mod.SPENT.update(n=0, capped=False)


def pytest_sessionfinish(session, exitstatus):
    if _rung_leaked:
        print(f"\n[unlock-rung] {len(_rung_leaked)} test(s) left identity_gate's paid rung "
              f"disarmed or spent (re-armed before the next test by tests/conftest.py):",
              flush=True)
        for nodeid, what in _rung_leaked:
            print(f"  {what:<22} {nodeid}", flush=True)
    if not _leaked:
        return
    total = sum(n for _, n in _leaked)
    print(f"\n[bd-spend] {len(_leaked)} test(s) left bd_rescue.SPENT non-zero "
          f"({total} phantom credit(s), reset by tests/conftest.py):", flush=True)
    for nodeid, n in _leaked:
        print(f"  {n:>3}  {nodeid}", flush=True)
