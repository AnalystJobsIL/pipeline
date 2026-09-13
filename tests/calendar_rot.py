"""Calendar rot: a test whose verdict the CALENDAR moves and no push can (BACKLOG 599).

Six tests went red on trees nobody touched between 2026-09-10 and 2026-09-13, each inherited by
whichever lane pushed next. Two shapes, both scanned here over a test function's AST:

  (i)  LITERAL fixture, LIVE clock. A date written into the fixture (`"posted_date":
       "2026-08-20"`, `"generated": "2026-08-29"`) is judged by a predicate that reads
       `date.today()` inside a window (`linkedin_normalize` 21 days, `tried_within` 14). Green
       on the day it was written, red the day the window walks past it.
       Instances: `test_a_junior_posting_still_contributes_its_employer`,
       `test_workable_reads_the_field_names_the_api_actually_sends` (cc4a493),
       `test_a_hunted_queue_name_stops_being_a_hunt_target` (8e9af0c).
  (ii) LIVE fixture, FROZEN clock. The fixture is dated from `date.today()` and the predicate
       is handed a literal `today` (`bd_budget.gauge(root, dt.date(2026, 9, 11))`, a 7-day
       window). Green for a week after it was written, red from then on.
       Instances: `test_the_gauge_alarms_on_the_free_tier_and_refuses_nothing`,
       `test_an_unreadable_account_still_reports_a_gauge_from_the_repos_own_ledger` (5b59ff4).

A seventh, `test_wayback_run_writes_one_line_per_attempt_and_verifies_yesterdays_pending`, has
no shape in the test at all: the test passed `today=` and the FUNCTION stamped its ledger from
the wall clock. It was fixed in `archive_evidence._now(today)`, and no scan of a test can see it.

What is NOT a finding, by construction:
  * a literal already older than the window: nothing can make it fresh again, and a test that
    needs it stale is testing exactly that (`"2026-01-01T00:00:00Z"` in the rates test);
  * a FROZEN PAIR -- a literal `today` and a fixture dated from that same literal
    (`_ABND_TODAY - timedelta(days=n)`), which is the idiom to write;
  * a LIVE PAIR -- `_days_ago(n)` against a predicate reading the wall clock;
  * a date inside a docstring or a comment, or inside a longer string (a notes cell).

A finding can only DISAPPEAR as time passes: rule (i) counts every literal on or after
`today - window`, future dates included, so the scan cannot itself go red on the calendar.
"""
from __future__ import annotations

import ast
import datetime as dt
import re

# callee name -> window in days. The window a function is judged by is the LARGEST of the
# windowed calls it makes; a literal day count passed to `tried_within`/`row_due` wins.
WINDOWED = {
    # discovery_daily.FRESH_DAYS (21), read through fresh_cut() by every normalizer and by
    # pipeline/fetchers.fetch_discovery, the reader of the cache those normalizers write
    "fresh_cut": 21, "linkedin_normalize": 21, "workable_normalize": 21,
    "indeed_normalize": 21, "fetch_discovery": 21, "discovery_daily.main": 21,
    # queue_state: the per-rung cadence (default 14; the positional `days` wins when literal)
    "tried_within": 14, "row_due": 14,
    # pipeline/bd_budget: a 7-day rate inside a calendar month
    "gauge": 31, "rates": 31, "_ledger_lines": 31, "month_by_purpose": 31, "may_spend": 31,
    "spent_this_month": 31,
    # pipeline/health: a board is abandoned after a year without a posting
    "abandoned": 366,
}
# Deliberately NOT here, each measured as a false positive on the 2026-09-13 tree:
# `health.board_freshness` and `archive_evidence.read_ledger` read no clock at all, and
# `archive_evidence.eligible` takes `today` as a required argument. `archive_evidence.run`
# does default to the wall clock, but `run` names a dozen unrelated functions.

_DAYS_ARG = {"tried_within": 3, "row_due": 3}      # index of the positional `days`
_CLOCK_KW = {"today", "now", "day", "at", "on"}
_LIVE_ATTR = {"today", "now", "utcnow"}              # date.today(), datetime.now()/utcnow()
_LIVE_NAME = {"_days_ago", "_TODAY", "_iso_days_ago"}
_DATE_STR = re.compile(r"^(20\d\d)-(\d\d)-(\d\d)(?:[T ][0-9:.]+Z?)?$")
_PATCHED_CLOCK = re.compile(r"^_?(today|now|clock|utcnow)$")


def _callee(node):
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr == "main" and isinstance(f.value, ast.Name) \
            and f.value.id in ("dd", "discovery_daily"):
        return "discovery_daily.main"          # `main` alone names every tool in the repo
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _is_live(node):
    """date.today() / datetime.now() / datetime.utcnow() / time.time() / _days_ago(n) / _TODAY."""
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in _LIVE_ATTR:
            return True
        if isinstance(f, ast.Attribute) and f.attr == "time" and isinstance(f.value, ast.Name) \
                and f.value.id == "time":
            return True
        if isinstance(f, ast.Name) and f.id in _LIVE_NAME:
            return True
    return isinstance(node, ast.Name) and node.id in _LIVE_NAME


def _date_literal_call(node):
    """`date(2026, 9, 11)` / `dt.date(...)` / `datetime(...)` with constant ints, or
    `date.fromisoformat("2026-09-11")`."""
    if not isinstance(node, ast.Call):
        return False
    name = _callee(node)
    if name in ("date", "datetime") and node.args and all(
            isinstance(a, ast.Constant) and isinstance(a.value, int) for a in node.args[:3]):
        return True
    return name == "fromisoformat" and node.args and isinstance(node.args[0], ast.Constant)


def _docstring_node(fn):
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[0].value
    return None


def scan_function(fn, today):
    """[(shape, detail)] for one test function."""
    doc = _docstring_node(fn)
    frozen_names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and _date_literal_call(n.value):
            frozen_names |= {t.id for t in n.targets if isinstance(t, ast.Name)}

    def frozen(arg):
        return _date_literal_call(arg) or (isinstance(arg, ast.Name) and arg.id in frozen_names)

    window, windowed, frozen_clock, live = 0, [], False, False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = _callee(n)
            if name in WINDOWED:
                w = WINDOWED[name]
                i = _DAYS_ARG.get(name)
                if i is not None and len(n.args) > i and isinstance(n.args[i], ast.Constant) \
                        and isinstance(n.args[i].value, int):
                    w = n.args[i].value
                windowed.append(name)
                window = max(window, w)
                if any(frozen(a) for a in n.args) or any(
                        k.arg in _CLOCK_KW and frozen(k.value) for k in n.keywords):
                    frozen_clock = True
            # monkeypatch.setattr(mod, "_today", lambda: d0) freezes the clock the code reads
            if name == "setattr" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) \
                    and isinstance(n.args[1].value, str) and _PATCHED_CLOCK.match(n.args[1].value):
                frozen_clock = True
        if _is_live(n):
            live = True
    if not windowed:
        return []
    out = []
    if frozen_clock and live:
        out.append(("ii", "a live-clock fixture against a frozen `today` given to %s"
                    % sorted(set(windowed))))
    if not frozen_clock:
        cut = (today - dt.timedelta(days=window)).isoformat()
        fresh = sorted({n.value[:10] for n in ast.walk(fn)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and n is not doc and _DATE_STR.match(n.value) and n.value[:10] >= cut})
        if fresh:
            out.append(("i", "literal date(s) %s inside the %d-day window of %s"
                        % (fresh, window, sorted(set(windowed)))))
    return out


def scan(source, today=None):
    """[(test name, shape, detail)] over every `test_*` function in `source`."""
    today = today or dt.date.today()
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found += [(node.name, s, d) for s, d in scan_function(node, today)]
    return found
