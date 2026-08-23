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
from pipeline.notes import append as _note_append, replace_own as _note_replace

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


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
    from pipeline.company_identity import is_foreign, looks_like_a_job_listing_page
    from listing_hunt import _identity_ok        # noqa: F401  (shared identity gate)
    from pipeline.aggregators import is_aggregator

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
        # "There are Israel jobs on this page" is not "these are THIS company's jobs".
        # The stored URL of a dark row is often the hunt's BEST GUESS, deliberately kept so
        # a human can check where we looked — FairFly's was fireflyspace.com, and this
        # repair activated it off 25 Firefly Aerospace roles. The hunt has gated on identity
        # since 2026-08-23; this path had not.
        if il and is_aggregator(r[3]):
            # An aggregator page's "similar jobs" sidebar is OTHER companies' roles. The
            # resolvers refuse to CREATE such a row; re-activating one is the same mistake
            # one step later (SeatPick, off djinni.co — caught only by check_invariants,
            # which fails the whole digest commit rather than this one row).
            still += 1
            print(f"  [XX]  {n}/{len(targets)} {r[0][:26]:26} {len(il)} IL but the URL is an "
                  f"aggregator ({r[3][:44]}) — not activated", flush=True)
            il = []
        if il and not looks_like_a_job_listing_page(r[3]):
            still += 1
            print(f"  [XX]  {n}/{len(targets)} {r[0][:26]:26} {len(il)} IL but {r[3][:40]} "
                  f"is not a listings page — not activated", flush=True)
            il = []
        if il and not _identity_ok(r[0], r[3]):
            # `is_foreign` alone was the gate here, and it returns False for every ATS host
            # by design - so on an ATS this branch had no identity test at all, while it
            # sets fr[4] = "true" and runs at 19:00 THIRTY MINUTES BEFORE `listing_hunt` in
            # the same job. Six of the 40 rows in tonight's pool are on such a host:
            #
            #   Sight Diagnostics  recruiting2.ultipro.com/SIG1008SIGH/...
            #       -> the IDENTICAL board `Sight Sciences` is already ACTIVE on. Two
            #          company names, one board: every role published twice.
            #   NanoLock Security  gen.wd1.myworkdayjobs.com   (Gen Digital's Workday)
            #   Amimon / Duve / Fieldin  www.comeet.com    Fetcher  jobs.gem.com
            #
            # This tool also forces SCRAPE_LLM=1 + SCRAPE_ASSUME_IL=1, which turns every
            # location-less card on an Israel-token page into an Israel role - so the
            # `il` count that reaches this line is the weakest evidence in the repo.
            #
            # `crack_walled`'s commit message and `listing_hunt._identity_ok`'s docstring
            # both called the hunt "the last activating path in that class". They were
            # wrong: ARCHITECTURE.md's own schedule table lists this tool as
            # `activates? yes` on the line above, and nobody read it.
            still += 1
            print(f"  [XX]  {n}/{len(targets)} {r[0][:26]:26} {len(il)} IL but the page "
                  f"belongs to another company ({r[3][:44]}) — not activated", flush=True)
            il = []
        if il:
            fixed += 1
            print(f"  [OK]  {n}/{len(targets)} {r[0][:26]:26} {len(il)} IL", flush=True)
            if apply:
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == r[0] and len(fr) >= 6:
                        fr[1], fr[2], fr[3] = "scrape", "", r[3]
                        fr[4] = "true"
                        # append, never overwrite: the note is a shared append-log and a
                        # wholesale rewrite drops every other tool's verdict segment (the
                        # documented #1 bug class here).
                        fr[5] = _note_replace(
                            fr[5], "repair ",
                            f"repair {TODAY}: extract-gap fixed via LLM tier; {len(il)} IL")
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
