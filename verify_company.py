#!/usr/bin/env python3
"""Verify a company's ATS endpoint with a live fetch — the research discipline as a script.

Usage:
  # verify an ad-hoc candidate (does NOT touch companies.csv):
  python verify_company.py --platform greenhouse --token monday --company monday.com \
      --api-url https://boards-api.greenhouse.io/v1/boards/monday/jobs

  # verify an existing row already in companies.csv by (case-insensitive) name:
  python verify_company.py --name JFrog

  # smoke-test every active company in companies.csv (one line each):
  python verify_company.py --all
  python verify_company.py --all --platform comeet     # only one platform

Reports: total jobs returned, how many look Israel-based, and a few sample titles.
Exit code 0 on a successful fetch, 1 on failure — so it can gate additions.
"""
from __future__ import annotations

import argparse
import sys
import traceback

from pipeline import fetchers, israel
from pipeline.companies import load_companies


def _row_from_args(a):
    return {
        "company_name": a.company or a.token or "(candidate)",
        "ats_platform": a.platform,
        "token": a.token or "",
        "api_url": a.api_url,
        "active": "true",
        "notes": "",
    }


def verify_row(row, *, samples=5, verbose=True):
    """Fetch one company; print a summary line. Returns (ok, total, il_count)."""
    name = row["company_name"]
    try:
        jobs = fetchers.fetch_company(row)
    except Exception as e:  # noqa: BLE001 - want to report, not crash, per company
        if verbose:
            print(f"[FAIL] {name} ({row['ats_platform']}): {e}")
            if "--trace" in sys.argv:
                traceback.print_exc()
        return False, 0, 0

    il = [j for j in jobs if israel.is_israel_job(j)]
    if verbose:
        print(f"[ OK ] {name:32s} {row['ats_platform']:15s} "
              f"total={len(jobs):4d}  israel={len(il):4d}")
        for j in il[:samples]:
            print(f"         - {j['title']}  |  {j['location'] or '(no loc)'}  |  {j['posted_date']}")
    return True, len(jobs), len(il)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform")
    ap.add_argument("--token")
    ap.add_argument("--api-url")
    ap.add_argument("--company")
    ap.add_argument("--name", help="verify an existing companies.csv row by name")
    ap.add_argument("--all", action="store_true", help="smoke-test all active companies")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--trace", action="store_true")
    a = ap.parse_args()

    if a.all:
        rows = load_companies()
        if a.platform:
            rows = [r for r in rows if r["ats_platform"].strip().lower() == a.platform.lower()]
        ok = fail = tot_jobs = tot_il = 0
        for r in rows:
            good, n, il = verify_row(r, samples=a.samples)
            if good:
                ok += 1; tot_jobs += n; tot_il += il
            else:
                fail += 1
        print(f"\n=== {ok} ok, {fail} failed | {tot_jobs} jobs total, {tot_il} Israel-matched ===")
        return 0 if fail == 0 else 1

    if a.name:
        rows = [r for r in load_companies(active_only=False)
                if r["company_name"].strip().lower() == a.name.strip().lower()]
        if not rows:
            print(f"no company named {a.name!r} in companies.csv")
            return 1
        allok = True
        for r in rows:
            good, _, _ = verify_row(r, samples=a.samples)
            allok = allok and good
        return 0 if allok else 1

    if not (a.platform and a.api_url):
        ap.error("provide --name, --all, or (--platform and --api-url)")
    good, _, _ = verify_row(_row_from_args(a), samples=a.samples)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
