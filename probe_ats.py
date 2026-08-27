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

import contextlib
import sys
import time

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


@contextlib.contextmanager
def bounded_http(timeout=4, retries=1):
    """Probe bounds, SCOPED. `pipeline/http.py` defaults to timeout=30/retries=3, which is
    right for a board we own and absurd for a guess: 8 slugs x 6 platforms x 3 tries at 30 s
    is a ~72-minute worst case for ONE name.

    `ingest_research.py:18` solves this by patching `pipeline.http._request` at import and
    never restoring it — process-global, inherited by everything that imports it. Restored in
    `finally` here, because a leaked patch makes `resolve_llm._verify`'s PRODUCTION fetch run
    at 4 s/1 try, so a slow-but-live board reads as 0 jobs and its row parks `empty`.
    """
    orig = http._request
    http._request = lambda *a, **k: orig(*a, **{**k, "retries": retries, "timeout": timeout})
    try:
        yield
    finally:
        http._request = orig


def probe_bounded(name, slugs, deadline=None, budget=18, stop_early=False):
    """`probe()` without stdout, with bounds, and with NORMALIZED platform names.

    Returns [{plat, slug, url, jobs, il}]. `plat` is `lever`, never `lever-eu`: this function
    exists to feed a registry row, and `lever-eu` dispatches to no fetcher while
    `check_invariants` C2 looks it up in `PLATFORM_HOST`, gets `None`, and cannot even warn.

    Early exit is at the SLUG level, never inside a slug's platform loop: one name can have
    two real boards (`Wayve` answers on greenhouse AND ashby, 2026-08-27), and stopping at
    the first would make `_PLATFORMS`'s file order an identity decision.
    """
    hits, req = [], 0
    for slug in slugs:
        got_il = False
        for plat, urlfn, fetch in _PLATFORMS:
            if req >= budget or (deadline and time.time() > deadline):
                return hits
            url = urlfn(slug)
            norm = "lever" if plat.startswith("lever") else plat
            req += 1
            try:
                jobs = fetch({"company_name": name, "ats_platform": norm,
                              "token": slug, "api_url": url})
            except Exception:  # noqa: BLE001
                continue
            if deadline and time.time() > deadline:
                # Checked AFTER the fetch too, not only before it. `fetch_smartrecruiters`
                # paginates inside this one slot with no page cap, and its `total` comes
                # from the server: an attacker drove 13,961 requests and 60 s+ out of a
                # single "1-request" slot on 2026-08-27. This cannot abort a fetch already
                # in flight -- so one overrun per name remains, and that is the residual --
                # but it stops the NEXT one, which is what turns 13,961 back into a bound.
                return hits
            if plat == "smartrecruiters" and not jobs:
                continue          # SR answers 200 + [] for ANY slug, even bogus
            il = sum(1 for j in jobs if israel.is_israel_job(j))
            hits.append({"plat": norm, "slug": slug, "url": url, "jobs": len(jobs), "il": il})
            if il:
                got_il = True
        if got_il and stop_early:
            # OFF for the resolution rung. This break is at the SLUG level, and it defeats
            # the caller's "two Israel-positive boards -> defer" guard by construction: the
            # ambiguity set can then only ever hold one slug, so the decision is made by
            # slug ORDER instead. Demonstrated 2026-08-27 -- feeding ['chalk','chamelio']
            # accepts chalk and ['chamelio','chalk'] accepts chamelio, both real boards.
            # This docstring already closed the same hole on the PLATFORM axis; the slug
            # axis was left open. 0 live cases found, and identity is not a thing to leave
            # to list order on a zero count.
            break
    return hits


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
