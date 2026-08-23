#!/usr/bin/env python3
"""Scrape jobs for rows activated since the last cache refresh and merge them in.

listing_hunt ACTIVATES a row (platform=scrape + verified url) but never writes the jobs it
just proved exist into scraped_cache.json. pipeline.fetchers.fetch_scrape only READS that
cache, so a company activated after the nightly 00:00 refresh contributes nothing to the
morning digest — its roles wait a full day for no reason.

Usage: python cache_new_rows.py [--apply] [--marker TEXT] [--shard i/n]
Env:   CACHE_NEW_TIME_BUDGET_MIN
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time

MARKER = "listing-hunt"          # default: rows a hunt activated


def main():
    apply = "--apply" in sys.argv
    marker = (sys.argv[sys.argv.index("--marker") + 1]
              if "--marker" in sys.argv else MARKER)
    shard = sys.argv[sys.argv.index("--shard") + 1] if "--shard" in sys.argv else ""
    budget = int(os.environ.get("CACHE_NEW_TIME_BUDGET_MIN", "0"))
    out_path = os.environ.get("CACHE_NEW_OUT", "scraped_cache.json")

    from scrape_universal import scrape
    from pipeline.israel import is_israel_job

    rows = [r for r in csv.reader(open("companies.csv", encoding="utf-8"))
            if r and len(r) >= 6]
    try:
        cache = json.load(open("scraped_cache.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}

    targets = [r for r in rows if r[4] == "true" and r[1] == "scrape"
               and marker in (r[5] or "") and (r[3] or "").startswith("http")
               and not cache.get(r[0])]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        targets = targets[i - 1::n]
    print(f"caching {len(targets)} newly-activated rows\n", flush=True)

    found = {}
    t0 = time.time()
    for n_, r in enumerate(targets, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print("time budget reached — stopping cleanly", flush=True)
            break
        try:
            jobs = scrape(r[0], r[3]) or []
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR] {r[0][:28]}: {str(e)[:44]}", flush=True)
            continue
        il = [j for j in jobs if is_israel_job(j)]
        print(f"  {'[OK]' if il else '[--]'} {n_}/{len(targets)} {r[0][:28]:28} {len(il)} IL",
              flush=True)
        if il:
            found[r[0]] = il

    if apply and found:
        # re-read: a concurrent shard may have added entries since we loaded
        try:
            fresh = json.load(open(out_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            fresh = {}
        fresh.update(found)
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(fresh, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, out_path)
    print(f"\n=== cached {len(found)} companies with Israel roles ===", flush=True)


if __name__ == "__main__":
    main()
