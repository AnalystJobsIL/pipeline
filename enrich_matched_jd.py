#!/usr/bin/env python3
"""Backfill JD text for EVERY matched role, whatever its source or age.

`enrich_scrape_jd.py` fills descriptions in `scraped_cache.json` — only scrape-source
companies. But four list endpoints return no description at all (workday, smartrecruiters,
bamboohr, Microsoft's Eightfold search — see `pipeline/jdfill.py`), so those roles reach the
board with a title and nothing else, and a classifier that judged on the title alone.

This walks the `matched` table itself — the one place that holds every role we ever
accepted — and fills any row whose stored description is too short to be a real JD. It is
deliberately age-blind: a role first seen last week that we never got the text for is
exactly the case the board is missing today.

    native JSON -> plain GET -> Bright Data Web Unlocker (budget-capped) -> store, or stamp
    `jd_attempted` ("YYYY-MM-DD", or "YYYY-MM-DD transient" for a failure worth retrying
    tomorrow rather than in 7 days).

Idempotent, safe to re-run, never shortens a description it already has, and records what it
did in the `enrich` stage stamp so the daily mail can say when it failed.

Usage: python enrich_matched_jd.py [--db cloud_state/seen.db] [--limit N] [--dry-run]
                                   [--cooldown-days 7]
Env:   MATCHED_JD_TIME_BUDGET_MIN (default 25), MATCHED_JD_BD_CAP (default 250)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from pipeline.jdfill import (DESC_MAX, MIN_DESC, RETRY_DAYS, Item, Unlocker, alarm_for,
                             load_secrets, record_enrich, run_backfill)

for _s in (sys.stdout, sys.stderr):        # a cp1252 pipe must not kill the report
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _ensure_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matched)")}
    if "jd_attempted" not in cols:
        conn.execute("ALTER TABLE matched ADD COLUMN jd_attempted TEXT")
        conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="cloud_state/seen.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=RETRY_DAYS)
    args = ap.parse_args(argv)
    # a run against a copy stamps beside the copy, never the repo's cloud_state file
    stamp = None if args.db == ap.get_default("db") else args.db + ".stages.json"
    try:
        return _run(args, stamp)
    except Exception as e:  # noqa: BLE001 - say so in the mail, then fail the step loudly
        record_enrich(alarm=f"crash:{type(e).__name__}", path=stamp)
        raise


def _run(args, stamp):
    load_secrets()
    if not os.path.exists(args.db):
        print(f"no {args.db}; nothing to enrich")
        return 0
    conn = sqlite3.connect(args.db)
    _ensure_column(conn)
    rows = conn.execute(
        """SELECT mkey, company, title, url, COALESCE(jd_attempted,'')
           FROM matched WHERE length(COALESCE(description,'')) < ?
           ORDER BY last_seen DESC, first_seen DESC""", (MIN_DESC,)).fetchall()
    items = [Item(mkey, url, f"{comp} | {title}", att, comp)
             for mkey, comp, title, url, att in rows if (url or "").startswith("http")]
    print(f"{len(rows)} matched roles under {MIN_DESC} chars, {len(items)} with a url"
          + (f"; attempting at most {args.limit}" if args.limit else ""), flush=True)

    bd = Unlocker(cap=int(os.environ.get("MATCHED_JD_BD_CAP", "250")))

    def save(item, text, stamp):
        if text:
            conn.execute("UPDATE matched SET description=?, jd_attempted=? WHERE mkey=?",
                         (text[:DESC_MAX], stamp, item.key))
        else:
            conn.execute("UPDATE matched SET jd_attempted=? WHERE mkey=?", (stamp, item.key))
        conn.commit()

    c = run_backfill(items, save=save,
                     minutes=float(os.environ.get("MATCHED_JD_TIME_BUDGET_MIN", "25")),
                     bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                     count_cap=args.limit, log=lambda s: print(s, flush=True))
    conn.close()
    if not args.dry_run:
        record_enrich(alarm=alarm_for(c, bd), path=stamp, matched_ran=1,
                      matched_filled=c["filled"], matched_bd=c["bd"], matched_fail=c["fail"],
                      matched_bd_unavailable=c["bd_unavailable"], matched_cooldown=c["cooldown"],
                      matched_unfillable=c["unfillable"])
    print(f"=== matched JD backfill: {c['filled']} filled ({c['bd']} via Bright Data), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{c['bd_unavailable']} waiting on Bright Data"
          + (f" [{bd.unavailable}]" if bd.unavailable else "") + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
