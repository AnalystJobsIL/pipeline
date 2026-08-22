"""Backfill structured firmographics for every company in companies.csv.

    python research_firmographics.py --dry-run          # who's missing / stale
    python research_firmographics.py --limit 25         # research a batch
    python research_firmographics.py                    # research all missing
    python research_firmographics.py --refresh-days 365 # also re-research stale records

Each company is one `claude -p` call (web search allowed, ~1-3 min), run on a small
thread pool and saved to the store as each finishes — safe to Ctrl-C and rerun; already-
researched companies are skipped. Seeds the 5 hand-researched POC records from
poc_firmographics.json first so they're never re-paid for. The daily run (pipeline/run.py)
keeps the cache topped up for newly discovered companies; this script is for bulk.

Export for inspection/commit: python research_firmographics.py --export
    -> writes state/firmographics.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline.companies import load_companies
from pipeline.firmographics import research_company
from pipeline.store import SeenStore

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.join(HERE, "poc_firmographics.json")
EXPORT = os.path.join(HERE, "state", "firmographics.json")


def seed_poc(st, today):
    """Load the hand-researched POC records into the store (idempotent)."""
    if not os.path.exists(POC):
        return 0
    with open(POC, encoding="utf-8") as f:
        poc = json.load(f)
    existing = st.load_firmographics()
    fresh = {k: v for k, v in poc.items() if not k.startswith("_") and k not in existing}
    if fresh:
        st.save_firmographics(fresh, today)
    return len(fresh)


def is_stale(rec, refresh_days):
    if not refresh_days:
        return False
    try:
        return (dt.date.today() - dt.date.fromisoformat(rec.get("as_of", ""))).days > refresh_days
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max companies to research this run")
    ap.add_argument("--workers", type=int, default=3, help="parallel claude -p calls")
    ap.add_argument("--refresh-days", type=int, default=None,
                    help="also re-research records older than this many days")
    ap.add_argument("--dry-run", action="store_true", help="only report, no research")
    ap.add_argument("--export", action="store_true", help="write state/firmographics.json and exit")
    a = ap.parse_args()

    st = SeenStore()
    today = dt.date.today().isoformat()

    if a.export:
        recs = st.load_firmographics()
        with open(EXPORT, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"exported {len(recs)} records -> {EXPORT}")
        return

    seeded = seed_poc(st, today)
    if seeded:
        print(f"seeded {seeded} POC records")

    have = st.load_firmographics()
    names = [r["company_name"] for r in load_companies()]
    todo = [n for n in names if n not in have or is_stale(have.get(n, {}), a.refresh_days)]
    print(f"{len(names)} active companies, {len(have)} researched, {len(todo)} to do")
    if a.dry_run or not todo:
        for n in todo:
            print("  -", n)
        return
    if a.limit:
        todo = todo[: a.limit]

    done = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = {ex.submit(research_company, name): name for name in todo}
        for fut in as_completed(futs):
            name = futs[fut]
            rec = fut.result()
            if rec:
                st.save_firmographics({name: rec}, today)  # main thread owns sqlite
                done += 1
                print(f"ok   {name}: {rec['sector']} / {rec.get('stage') or '?'} / {rec.get('size_band') or '?'}")
            else:
                failed += 1
                print(f"FAIL {name} (will retry next run)")
    print(f"\n{done} researched, {failed} failed, {len(have) + done} total in store")


if __name__ == "__main__":
    main()
