#!/usr/bin/env python3
"""Backfill JD text for EVERY matched role, whatever its source or age.

`enrich_scrape_jd.py` fills descriptions in `scraped_cache.json` — i.e. only for
scrape-source companies. But four API fetchers return no description at all
(`workday` 88 companies, `smartrecruiters` 19, `bamboohr` 12, `microsoft` 1: the
JD is simply not in their LIST response), so those roles reach the board with a
title and nothing else — no requirements, no skills, no tags, and a classifier
that had to judge on the title alone.

This walks the `matched` table itself, which is the one place that holds every
role we ever accepted, and fills any row whose stored description is too short to
be a real JD. It is deliberately age-blind: a role first seen last week that we
never got the text for is exactly the case the board is missing today.

    plain GET -> Bright Data Web Unlocker (budget-capped) -> store, or stamp
    `jd_attempted` and retry after 7 days.

Idempotent, safe to re-run, and never shortens a description it already has.

Usage: python enrich_matched_jd.py [--db cloud_state/seen.db] [--limit N] [--dry-run]
Env:   MATCHED_JD_TIME_BUDGET_MIN (default 25), MATCHED_JD_BD_CAP (default 250)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import time

from bd_rescue import _load_secrets, unlock
from enrich_scrape_jd import _plain_fetch, extract_jd

MIN_DESC = 300          # below this it is a stub, not a job description
RETRY_DAYS = 7


def _ensure_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matched)")}
    if "jd_attempted" not in cols:
        conn.execute("ALTER TABLE matched ADD COLUMN jd_attempted TEXT")
        conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="cloud_state/seen.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _load_secrets()
    budget_min = int(os.environ.get("MATCHED_JD_TIME_BUDGET_MIN", "25"))
    bd_cap = int(os.environ.get("MATCHED_JD_BD_CAP", "250"))
    bd_ok = bool(os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE"))
    today = dt.date.today().isoformat()
    retry_before = (dt.date.today() - dt.timedelta(days=RETRY_DAYS)).isoformat()

    if not os.path.exists(args.db):
        print(f"no {args.db}; nothing to enrich")
        return 0
    conn = sqlite3.connect(args.db)
    _ensure_column(conn)

    rows = conn.execute(
        """SELECT mkey, company, title, url, length(COALESCE(description,'')),
                  COALESCE(jd_attempted,'')
           FROM matched
           WHERE length(COALESCE(description,'')) < ?
           ORDER BY last_seen DESC, first_seen DESC""", (MIN_DESC,)).fetchall()
    todo = [r for r in rows if (r[3] or "").startswith("http") and r[5] <= retry_before]
    cooling = len(rows) - len(todo)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(rows)} matched roles under {MIN_DESC} chars; "
          f"{cooling} in cooldown/no-url; attempting {len(todo)}", flush=True)

    t0 = time.time()
    n_ok = n_bd = n_fail = 0
    for i, (mkey, comp, title, url, _n, _a) in enumerate(todo, 1):
        if budget_min and (time.time() - t0) / 60 > budget_min:
            print(f"  time budget {budget_min}m spent at {i}/{len(todo)}", flush=True)
            break
        html = _plain_fetch(url)
        jd = extract_jd(html) if html else ""
        if not jd and bd_ok and n_bd < bd_cap:
            n_bd += 1
            try:
                jd = extract_jd(unlock(url))
            except Exception:  # noqa: BLE001
                jd = ""
        tag = "OK " if jd else "-- "
        print(f"  [{tag}] {i}/{len(todo)} {comp[:26]:<26} {title[:40]:<40} "
              f"{len(jd)}", flush=True)
        if args.dry_run:
            continue
        if jd:
            conn.execute("UPDATE matched SET description=?, jd_attempted=? WHERE mkey=?",
                         (jd[:6000], today, mkey))
            n_ok += 1
        else:
            conn.execute("UPDATE matched SET jd_attempted=? WHERE mkey=?", (today, mkey))
            n_fail += 1
        conn.commit()

    conn.close()
    print(f"=== matched JD backfill: {n_ok} filled ({n_bd} via Bright Data), "
          f"{n_fail} unfetchable (retry in {RETRY_DAYS}d) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
