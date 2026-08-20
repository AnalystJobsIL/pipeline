#!/usr/bin/env python3
"""Confirm the Google-for-Jobs (SerpApi) source works, WITHOUT printing the key.

Loads secrets.env (if present), runs one SerpApi google_jobs query for Israel, and reports
how many Israel analytics jobs came back. Safe to share output — never echoes the API key.
"""
from __future__ import annotations

import os

from pipeline import israel
from pipeline.aggregators import fetch_serpapi_google_jobs
from pipeline.run import _load_secrets_env


def main():
    _load_secrets_env()
    if not (os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI_API_KEY")):
        print("No SERPAPI_KEY found (set it in secrets.env or the environment).")
        return 1
    jobs = fetch_serpapi_google_jobs(queries=["data analyst"])
    il = [j for j in jobs if israel.is_israel_job(j)]
    print(f"SerpApi OK: {len(jobs)} jobs returned, {len(il)} Israel-matched.")
    for j in il[:8]:
        print(f"  - {j['company']}: {j['title']} | {j['location']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
