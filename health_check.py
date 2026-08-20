#!/usr/bin/env python3
"""Standalone full health sweep — the weekly BACKSTOP to the free detection that pipeline.run
now does inline every day. Fetches every active company and records the same stale-board list
+ baseline via pipeline.health, catching slow drift the daily run might smooth over.

Writes cloud_state/stale.json (the re-resolve queue) + cloud_state/health_baseline.json.
"""
from __future__ import annotations

import csv

from pipeline import fetchers, health, israel


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    results = {}
    for r in rows[1:]:
        if len(r) < 5 or (r[4] or "").strip().lower() != "true":
            continue
        name, plat, tok, api = r[0], r[1], r[2], r[3]
        try:
            jobs = fetchers.fetch_company({"company_name": name, "ats_platform": plat,
                                           "token": tok, "api_url": api})
            il = sum(1 for j in jobs if israel.is_israel_job(j))
            results[name] = {"platform": plat, "n": len(jobs),
                             "status": "ok" if jobs else "empty", "api": api}
            st = "ok" if jobs else "empty"
        except Exception as e:  # noqa: BLE001
            results[name] = {"platform": plat, "n": 0, "status": "error", "api": api}
            il, st = 0, f"error:{type(e).__name__}"
        print(f"  {name[:26]:27} {st:14} {results[name]['n']:>4}/{il:>3} IL", flush=True)
    stale = health.record(results)
    print(f"\n=== {len(results)} checked · {len(stale)} STALE -> {health.STALE} ===", flush=True)


if __name__ == "__main__":
    main()
