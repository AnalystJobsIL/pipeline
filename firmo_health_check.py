#!/usr/bin/env python3
"""Tripwire for the firmographics chain: is classification actually happening?

The chain's per-run guards abort silently BY DESIGN (correct for transient outages),
and cmd wrappers eat exit codes — so a permanently dead claude login used to look like
success forever (Task Scheduler LastTaskResult 0, log nobody reads). This check runs as
the chain's LAST step:

  - healthy  -> exit 0, remove any standing alert file
  - unhealthy (no trustworthy research run in ALERT_HOURS) -> exit 1 (Task Scheduler
    shows a failing LastTaskResult) AND write an alert file to the user's Desktop —
    the one place guaranteed to be seen.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = os.path.join(HERE, "state", "firmo_last_ok.txt")
ALERT = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                     "FIRMOGRAPHICS-ALERT.txt")
ALERT_HOURS = 48  # 8 consecutive failed 6-hourly runs before we call it dead


def main():
    now = dt.datetime.now()
    last = None
    if os.path.exists(STAMP):
        try:
            last = dt.datetime.fromisoformat(open(STAMP, encoding="utf-8").read().strip())
        except ValueError:
            pass
    age_h = (now - last).total_seconds() / 3600 if last else None

    if last and age_h <= ALERT_HOURS:
        print(f"firmo health OK: last trustworthy research run {age_h:.1f}h ago")
        if os.path.exists(ALERT):
            os.remove(ALERT)
        return 0

    reason = (f"no trustworthy research run for {age_h:.0f}h"
              if last else "no successful research run ever recorded")
    msg = (f"[{now.isoformat(timespec='seconds')}] FIRMOGRAPHICS CHAIN UNHEALTHY: {reason}.\n"
           f"Most likely cause: expired `claude` CLI login (run `claude /login`) or dead "
           f"Bright Data key.\nDetails: {os.path.join(HERE, 'state', 'firmo_chain.log')}\n"
           f"This file is recreated by every unhealthy chain run and auto-removed once "
           f"a run succeeds.\n")
    with open(ALERT, "w", encoding="utf-8") as f:
        f.write(msg)
    print("firmo health ALERT:", reason)
    return 1


if __name__ == "__main__":
    sys.exit(main())
