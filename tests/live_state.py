"""The door a test must use to read the repository's LIVE state -- and the lock on every other.

`companies.csv`, `scraped_cache.json`, `discovered_cache.json`, `research_companies.json` and
everything under `cloud_state/` and `digests/` are rewritten by the crons several times a day.
A test that reads them and asserts on what they hold is a test whose verdict a CRON moves while
the tree stands still, so it reds whichever lane pushes next. Two instances in two days
(2026-09-11/12): `test_every_name_this_lane_publishes_facts_for_has_them` read red at 12:59 after
auto-expand and green after the 14:28 intel cron, same code; and
`test_the_delta_audit_lines_bind_to_exactly_one_record_each` read red the morning `roles`' title
canon renamed a record. BACKLOG 599's sibling, and the second structural caveat of 2026-09-13.

How it works: `tests/conftest.py` wraps every test in `guard(<file>::<test>)`, which intercepts
`open`/`io.open` (so `pathlib` too) and `sqlite3.connect`. A path that resolves to live state
raises `LiveStateInTests` unless the test is in `tests/live_state_allowlist.json` with the
files it may read and WHY. A path under `tmp_path`, a fixture, or anything else is untouched.

It is a BaseException for the reason `PaidCallInTests` is: code under test catches `Exception`
around its file reads, and a guard it could swallow would read as a missing file.

The two ways out, in the order to prefer them:
  1. a dated snapshot under `tests/fixtures/` (the classifier's `2026-09-11-delta-audit.json` is
     the model) -- the assertion keeps its teeth and stops moving with the crons;
  2. if the property is only true of TODAY's data, it is not a unit test: it belongs where a
     human reads it daily (a `Stages:` clause in the mail, or `check_invariants.py`, which runs
     before every persist). An allowlist entry is the last resort, and says which.

`LIVE_STATE_REPORT=<path>` records instead of raising: one JSON line per (test, file). That is
how the class was measured before it was locked.

**The read is never interrupted** (`violations=` list, which `conftest` uses): the open goes
through and the TEST fails at teardown. Found on the first CI run: `jdfill._registry_board`
sets its process cache to `{}` and then loads `companies.csv`, so an exception raised mid-load
left an empty registry for every later test in the session -- a lock that changes the tests it
guards. A process-wide cache is charged to the first test that fills it, so a SUBSET run (`-k`,
a mutation shard) can blame a test the full order never does; the mutation harness therefore
runs with the lock off (`AJIL_MUTANT=1`), and the full suite in CI is where it is judged.
"""
from __future__ import annotations

import builtins
import contextlib
import fnmatch
import io
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST = os.path.join(ROOT, "tests", "live_state_allowlist.json")
LIVE_FILES = ("companies.csv", "scraped_cache.json", "discovered_cache.json",
              "research_companies.json")
LIVE_DIRS = ("cloud_state", "digests")


# The dated snapshots the converted tests read instead. One place, so a re-cut is one line and
# a reader can see every frozen copy of live state the suite carries.
SNAPSHOTS = {
    "companies.csv": os.path.join(ROOT, "tests", "fixtures", "registry", "2026-09-13-companies.csv"),
}


def snapshot(name):
    """The dated fixture that stands in for live `name` in a test."""
    return SNAPSHOTS[name]


class LiveStateInTests(BaseException):
    """A test opened a file the crons rewrite. See tests/live_state.py for the two ways out."""


def message(test, rel):
    return (f"{test} opened {rel}, which a cron rewrites: its verdict moves while the tree "
            f"stands still and reds whoever pushes next. Read a dated snapshot under "
            f"tests/fixtures/ instead, or -- if the property is only true of today's data -- "
            f"move it into check_invariants.py or the mail. Last resort: an entry with a "
            f"reason in tests/live_state_allowlist.json (see tests/live_state.py).")


def live_path(path, root=ROOT):
    """The repo-relative live path `path` names ('/'-separated), or None."""
    if isinstance(path, int):
        return None
    try:
        p = os.fspath(path)
    except TypeError:
        return None
    if isinstance(p, bytes):
        p = p.decode("utf-8", "replace")
    if p.startswith("file:"):                               # a sqlite URI
        p = p[5:].split("?", 1)[0]
    if not p or p == ":memory:":
        return None
    full = os.path.normcase(os.path.abspath(p))
    base = os.path.normcase(os.path.abspath(root)) + os.sep
    if not full.startswith(base):
        return None
    rel = full[len(base):].replace(os.sep, "/")
    if rel in {f.lower() if os.sep == "\\" else f for f in LIVE_FILES} or rel in LIVE_FILES:
        return rel
    top = rel.split("/", 1)[0]
    return rel if top in LIVE_DIRS and "/" in rel else None


def load_allowlist(path=ALLOWLIST):
    try:
        with builtins.open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def allowed(test, rel, allowlist):
    entry = allowlist.get(test) or {}
    return any(fnmatch.fnmatch(rel, pat.lower() if os.sep == "\\" else pat)
               for pat in entry.get("files", ()))


@contextlib.contextmanager
def guard(test, root=ROOT, allowlist=None, report=None, violations=None):
    """Refuse every open of live state by `test`: raise, or -- given a `violations` list --
    let the read through and append the path, for the caller to fail the test afterwards.
    With `report`, record one JSON line per (test, file) instead."""
    allowlist = load_allowlist() if allowlist is None else allowlist
    report = os.environ.get("LIVE_STATE_REPORT") if report is None else report
    real_open, real_io_open, real_connect = builtins.open, io.open, sqlite3.connect
    seen = set()

    def check(path):
        rel = live_path(path, root)
        if rel is None or allowed(test, rel, allowlist):
            return
        if report:
            if rel not in seen:
                seen.add(rel)
                with real_open(report, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"test": test, "file": rel}) + "\n")
            return
        if violations is not None:
            if rel not in violations:
                violations.append(rel)
            return
        raise LiveStateInTests(message(test, rel))

    def _open(file, *a, **k):
        check(file)
        return real_open(file, *a, **k)

    def _io_open(file, *a, **k):
        check(file)
        return real_io_open(file, *a, **k)

    def _connect(database, *a, **k):
        check(database)
        return real_connect(database, *a, **k)

    builtins.open, io.open, sqlite3.connect = _open, _io_open, _connect
    try:
        yield
    finally:
        builtins.open, io.open, sqlite3.connect = real_open, real_io_open, real_connect
