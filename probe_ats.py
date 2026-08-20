#!/usr/bin/env python3
"""Probe the guessable public ATS platforms for a company, to resolve its board.

For the ATS platforms whose token is a human-readable slug (greenhouse, lever, ashby,
smartrecruiters, recruitee) this tries a set of candidate slugs and reports which endpoint
returns valid JSON, how many jobs it has, and how many look Israel-based. Comeet (numeric
token) and Workday (per-tenant host) are NOT guessable and must be found from the careers
page's network requests — this tool skips them.

Usage:
  python probe_ats.py "monday.com" monday mondaycom
  python probe_ats.py "Silverfort"            # auto-derives slug variants from the name
"""
from __future__ import annotations

import sys

from pipeline import http, israel
from pipeline.fetchers import (fetch_ashby, fetch_greenhouse, fetch_lever,
                               fetch_recruitee, fetch_smartrecruiters)


def slug_variants(name):
    base = name.lower().strip()
    for junk in (" ", ".", ",", "'", "’", "-", "&"):
        base = base.replace(junk, "")
    n = name.lower().strip()
    variants = {
        base,
        n.replace(" ", ""),
        n.replace(" ", "-"),
        n.replace(" ", "_"),
        n.split()[0] if n.split() else n,
        base.replace("com", "") if base.endswith("com") else base,
        base + "inc",
        base + "hq",
    }
    return sorted(v for v in variants if v)


_PLATFORMS = [
    ("greenhouse", lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs", fetch_greenhouse),
    ("lever", lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json", fetch_lever),
    ("lever-eu", lambda s: f"https://api.eu.lever.co/v0/postings/{s}?mode=json", fetch_lever),
    ("ashby", lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}", fetch_ashby),
    ("smartrecruiters", lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings", fetch_smartrecruiters),
    ("recruitee", lambda s: f"https://{s}.recruitee.com/api/offers/", fetch_recruitee),
]


def probe(name, slugs):
    print(f"### {name}  (slugs: {', '.join(slugs)})")
    hits = []
    for slug in slugs:
        for plat, urlfn, fetch in _PLATFORMS:
            url = urlfn(slug)
            plat_norm = "lever" if plat.startswith("lever") else plat
            row = {"company_name": name, "ats_platform": plat_norm, "token": slug, "api_url": url}
            try:
                jobs = fetch(row)
            except http.HttpError:
                continue
            except Exception:  # noqa: BLE001
                continue
            # SmartRecruiters returns HTTP 200 + empty list for ANY slug (even bogus),
            # so an SR result only counts as a real board when it actually has postings.
            if plat == "smartrecruiters" and not jobs:
                continue
            il = sum(1 for j in jobs if israel.is_israel_job(j))
            tag = "  <== ISRAEL JOBS" if il else ("  (0 israel now)" if jobs else "  (board exists, 0 jobs)")
            print(f"  HIT {plat:16s} slug={slug:22s} jobs={len(jobs):4d} israel={il:4d}{tag}")
            hits.append((plat, slug, url, len(jobs), il))
    if not hits:
        print("  (no guessable-platform hit — check the careers page for comeet/workday/custom)")
    return hits


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    name = argv[1]
    slugs = argv[2:] if len(argv) > 2 else slug_variants(name)
    probe(name, slugs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
