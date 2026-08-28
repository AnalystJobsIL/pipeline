"""The project's Bright Data ceiling, in one place, with a date on it (lane: infra).

    python -m pipeline.bd_budget            # report MTD vs the ceiling; 0 = spend, 1 = stop

WHY THIS EXISTS. Until 2026-08-28 the ceiling was a default argument in `discovery_daily`
(`BD_MONTHLY_BUDGET`, 5,000) that NO workflow set, and two documents disagreed about what it
should be: `docs/BACKLOG.md` 192 recorded the operator's decision of 2026-08-25 ("next month
must not pass 4,500"), while 335 quoted an instruction of 2026-08-27 ("self-sufficient at
5,000 monthly"). Nobody could tell which was current, and meanwhile `scrape-refresh.yml`
armed a paid rung with no cap at all and spent 72 credits a night unattended.

THE RULE, settled by the operator on 2026-08-28: **unlimited for the rest of August, 5,000
from 2026-09-01.** It is encoded here ONCE rather than written in a workflow someone must
remember to edit, and `tests/test_units.py` pins BOTH SIDES of the boundary — so it changes
itself on the day, and a guard proves it did. A ceiling nobody re-derives is the whole point:
this repo has already shipped a document that was confidently wrong for three days.

WHAT THE NUMBER IS. Month-to-date is read from the LIVE Bright Data account, not from a
counter in this repo. That matters more than it looks: every cap in this codebase is
per-PROCESS, each workflow job is a fresh process, and there is no persisted credit ledger
anywhere — so a repo-side counter could never see what the other nine workflows spent. The
account can. `discovery_daily.bd_spend_this_month()` already does exactly this read
(datasets + zone/cost, because `/customer/balance` is 403 for our token) and is reused rather
than re-implemented.

FAILING OPEN IS DELIBERATE. When the reading is unavailable — the API is down, the token is
rotated, the network blips — this reports UNKNOWN and lets the run spend. Throttling on a
number we could not fetch would silently zero a night's coverage, which is the worst failure
mode in this repo (`pipeline/sources.py` exists because of one), and the cost of the opposite
mistake is a few dollars. `budget_per_day` in `discovery_daily` already takes the same view.
The per-run `BD_RUN_CAP` in `bd_rescue` is the bound that does NOT depend on the network.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

# The operator's rule of 2026-08-28. `SWITCH` is the first day the ceiling binds.
SWITCH = dt.date(2026, 9, 1)
CEILING_AFTER = 5000
UNLIMITED = 0


def ceiling(today=None):
    """The monthly credit ceiling in force on `today`. 0 means unlimited (August 2026)."""
    today = today or dt.date.today()
    if os.environ.get("BD_MONTHLY_BUDGET"):         # an explicit override still wins
        try:
            return max(0, int(os.environ["BD_MONTHLY_BUDGET"]))
        except ValueError:
            pass
    return CEILING_AFTER if today >= SWITCH else UNLIMITED


def spent_this_month(today=None):
    """(credits, breakdown) from the live account; (None, None) when it cannot be read."""
    try:
        from discovery_daily import bd_spend_this_month, _load_secrets
        try:
            _load_secrets()
        except Exception:  # noqa: BLE001 -- secrets.env is optional; the env may already hold them
            pass
        return bd_spend_this_month(today)
    except Exception as e:  # noqa: BLE001 -- a budget reader never costs the run it reports on
        print(f"  [bd-budget] spend unreadable ({e.__class__.__name__}) — not throttling",
              flush=True)
        return None, None


def verdict(today=None):
    """(may_spend, line). `line` is one sentence fit for a run page and a log."""
    today = today or dt.date.today()
    cap = ceiling(today)
    mtd, _ = spent_this_month(today)
    if cap == UNLIMITED:
        seen = "unknown" if mtd is None else f"{mtd:,}"
        return True, (f"Bright Data: {seen} credits month-to-date, **no ceiling in force** "
                      f"until {SWITCH} (then {CEILING_AFTER:,}).")
    if mtd is None:
        return True, (f"Bright Data: month-to-date UNREADABLE against a ceiling of {cap:,} — "
                      f"spending anyway, because throttling on a number we could not fetch "
                      f"is its own silent failure.")
    pct = mtd * 100.0 / cap
    if mtd >= cap:
        return False, (f"Bright Data: **{mtd:,} of {cap:,} credits ({pct:.0f}%) — CEILING "
                       f"REACHED.** Paid rungs are skipped this run.")
    return True, f"Bright Data: {mtd:,} of {cap:,} credits month-to-date ({pct:.0f}%)."


def main(argv=None):
    """Report to stdout and to the run page. Exit 1 means the paid rungs must not run."""
    may, line = verdict()
    print(f"[bd-budget] {line}", flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n- {line}\n")
        except OSError as e:
            print(f"  [bd-budget] step summary not written: {e}", flush=True)
    if not may:
        print("::warning::Bright Data ceiling reached — this run buys no credits", flush=True)
    return 0 if may else 1


if __name__ == "__main__":
    sys.exit(main())
