#!/usr/bin/env python3
"""Repair `extract-gap` rows: the URL is already correct and triage confirmed roles are on
the page — our extractor simply failed. So re-scrape the KNOWN url with the LLM tier forced
on, and activate the row only if >=1 Israel job comes back through the production path.

This needs no search, which matters because DuckDuckGo blocks some networks; it is the one
dark-row mode that can be repaired without discovery.

Usage: python repair_extract_gap.py [--apply] [--limit N]
Env:   REPAIR_TIME_BUDGET_MIN
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
import time

from pipeline.atomic import write_csv_rows

TODAY = dt.date.today().isoformat()
MODE = re.compile(r"dark-triage \d{4}-\d{2}-\d{2}: extract-gap")


def main():
    apply = "--apply" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    budget = int(os.environ.get("REPAIR_TIME_BUDGET_MIN", "0"))
    os.environ["SCRAPE_LLM"] = "1"          # roles are known present: force the LLM tier
    os.environ["SCRAPE_ASSUME_IL"] = "1"

    from scrape_universal import scrape
    from pipeline.israel import is_israel_job

    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [r for r in rows if r and len(r) >= 6 and r[4] == "false"
               and MODE.search(r[5] or "") and (r[3] or "").startswith("http")]
    if limit:
        targets = targets[:limit]
    print(f"repairing {len(targets)} extract-gap rows\n", flush=True)

    fixed = still = 0
    t0 = time.time()
    for n, r in enumerate(targets, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print("time budget reached — stopping cleanly", flush=True)
            break
        try:
            jobs = scrape(r[0], r[3]) or []
        except Exception as e:  # noqa: BLE001
            jobs = []
            print(f"  [ERR] {r[0][:26]}: {str(e)[:50]}", flush=True)
        il = [j for j in jobs if is_israel_job(j)]
        if il:
            fixed += 1
            print(f"  [OK]  {n}/{len(targets)} {r[0][:26]:26} {len(il)} IL", flush=True)
            if apply:
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == r[0] and len(fr) >= 6:
                        fr[1], fr[2], fr[3] = "scrape", "", r[3]
                        fr[4] = "true"
                        fr[5] = f"repair {TODAY}: extract-gap fixed via LLM tier; {len(il)} IL"
                write_csv_rows("companies.csv", fresh)
                # cache immediately so the next digest sees it without waiting for a refresh
                import json
                try:
                    cache = json.load(open("scraped_cache.json", encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    cache = {}
                cache[r[0]] = jobs
                with open("scraped_cache.json", "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        else:
            still += 1
            print(f"  [--]  {n}/{len(targets)} {r[0][:26]:26} still 0", flush=True)
    print(f"\n=== repair: {fixed} activated, {still} still dark ===", flush=True)


if __name__ == "__main__":
    main()
