#!/usr/bin/env python3
"""Which accumulated roles were never emailed, and why (lane: infra; read-only).

    python tests/role_leak.py                    # the default store
    python tests/role_leak.py --db /tmp/copy.db  # a copy, if a run may be writing
    python tests/role_leak.py --days 10

A lane harness beside `rehearse_infra.py` and `schedule_census.py`: it opens the store
read-only, writes nothing, and answers one question the product is actually judged on --
**of the roles this pipeline accumulated, how many reached a reader?**

WHY (2026-08-27). `pipeline/run.py` selects the mail with

    cutoff_email = today - 1 day
    email_jobs   = [j for j in st.get_matched_since(cutoff_email) if _posted_in(j, cutoff_email)]

Two different clocks. `get_matched_since` filters on **first_seen** -- when WE saw the role --
and the eligibility test `_posted_in` uses **posted_date** -- when the EMPLOYER posted it.
The window moves every day, and a role only gets one pass through it. So a role is lost when:

  * it was capped out. `_cap_per_company(email_jobs, 3)` and `EMAIL_MAX_ROLES = 40` drop the
    surplus, and `run.py` says of them "Overflow is not lost: it stays unsent and leads
    tomorrow". It does not: tomorrow `cutoff_email` has advanced past its `first_seen`, so
    `get_matched_since` never returns it again. Same false claim in
    `persist_state.build_notice` ("those roles lead the next digest").
  * its `posted_date` arrived LATE. A role first seen with no date fails `_posted_in` and is
    skipped; when `jd-text` enrichment backfills the date days later the row is already
    outside the `first_seen` window, so nothing ever reconsiders it. This is the majority of
    the measured leak: on 2026-08-27, six of the seven leaked roles carried
    `posted_date 2026-08-25` against `first_seen` of 08-22, 08-23 and 08-24.
  * a digest was never delivered that day (the 2026-08-27 class -- see ARCHITECTURE section 4).

The fix is NOT this lane's: the selection block belongs to `roles`, the caps to `render`,
the late `posted_date` to `jd-text`. BACKLOG 309 and 310. This tool exists so that whoever
takes it can measure before and after instead of arguing.

A role counted here is NOT necessarily recoverable -- `--all` shows the ones correctly
excluded too, and they are the majority. The headline number is deliberately the narrow one:
roles that had a posted_date inside their own window on the day we first saw them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from collections import defaultdict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "cloud_state", "seen.db")


def load(db):
    """Open read-only. A measurement must never be able to change what it measures."""
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    sent = {r[0] for r in con.execute("select seen_id from sent")}
    rows = con.execute("select first_seen, seen_ids, company, title, posted_date, "
                       "coalesce(status,''), last_seen from matched").fetchall()
    con.close()
    return sent, rows


def classify(sent, rows, days, today=None):
    """(delivered, leaked, excluded) -- leaked = eligible on its own day and never emailed."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    floor = (today - dt.timedelta(days=days)).isoformat()
    delivered, leaked, excluded = [], [], []
    for first_seen, seen_ids, company, title, posted, status, last_seen in rows:
        if status == "superseded" or not first_seen or first_seen < floor:
            continue
        # `matched.seen_ids` is joined with "+", not "," (`store.upsert_matched` does
        # `"+".join(sorted(new_sids))` and `get_matched_since` splits on "+"). Splitting on
        # "," yielded ONE element -- the whole joined string -- which is never a key in
        # `sent`, so every role carrying two or more seen_ids was counted as never-emailed.
        # That inflated the leak and deflated the delivered count; found 2026-08-27 by the
        # `roles` lane while trying to reach the number this tool defines.
        ids = [x for x in (seen_ids or "").split("+") if x]
        rec = (first_seen, company, title, posted, last_seen)
        if any(i in sent for i in ids):
            delivered.append(rec)
            continue
        # eligible = the employer's posted_date fell inside the 48h window on the day we
        # first saw it. That is the test `_posted_in` applies, replayed against the day the
        # row actually had its one pass through the selection window.
        try:
            ok = bool(posted) and dt.date.fromisoformat(str(posted)[:10]) >= \
                dt.date.fromisoformat(first_seen) - dt.timedelta(days=1)
        except ValueError:
            ok = False
        (leaked if ok else excluded).append(rec)
    return delivered, leaked, excluded


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--days", type=int, default=10, help="how far back to look")
    ap.add_argument("--all", action="store_true", help="also list the correctly-excluded rows")
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        raise SystemExit("no store at %s" % a.db)
    delivered, leaked, excluded = classify(*load(a.db), days=a.days)
    total = len(delivered) + len(leaked) + len(excluded)
    print(f"# roles accumulated in the last {a.days} days: {total}")
    print(f"#   emailed                              : {len(delivered)}")
    print(f"#   NEVER emailed, and were eligible     : {len(leaked)}   <-- the leak")
    print(f"#   never emailed, correctly excluded    : {len(excluded)}"
          f"   (no posted_date, or one outside the window)\n")
    if leaked:
        print("first_seen   posted       last_seen    company — title")
        by = defaultdict(int)
        for first_seen, company, title, posted, last_seen in sorted(leaked, reverse=True):
            print(f"{first_seen}   {str(posted or '-'):10}   {str(last_seen or '-'):10}   "
                  f"{company} — {title[:44]}")
            if posted and str(posted)[:10] > first_seen:
                by["posted_date backfilled after the window closed"] += 1
        for why, n in by.items():
            print(f"\n  {n} of {len(leaked)}: {why}")
        print("  Fix owners: `roles` (the selection block), `render` (the caps), "
              "`jd-text` (late posted_date). BACKLOG 309/310.")
    if a.all and excluded:
        print("\n--- correctly excluded (shown for contrast) ---")
        for first_seen, company, title, posted, last_seen in sorted(excluded, reverse=True):
            print(f"{first_seen}   {str(posted or '-'):10}   {company} — {title[:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
