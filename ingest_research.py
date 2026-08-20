#!/usr/bin/env python3
"""Ingest research_companies.json: resolve + verify each company's public ATS board over HTTP
and append the live ones (returning real Israel jobs) to companies.csv.

- Entries with a known ats+slug: build the api_url, fetch, keep if the board returns jobs.
- Entries with ats="unknown": slug-probe greenhouse/lever/ashby/smartrecruiters/recruitee;
  keep a hit only when it returns Israel jobs (guards against a wrong-company slug collision).
- Unknowns with no HTTP hit are written to out/comeet_queue.json for the Playwright pass.
"""
from __future__ import annotations

import csv
import json

from pipeline import http as _http

# Probing hits many dead/slow hosts; keep it snappy (6s, single try) so a hang can't stall the run.
_orig_req = _http._request
_http._request = lambda *a, **k: _orig_req(*a, **{**k, "retries": 1, "timeout": 6})

from pipeline import israel
from pipeline.companies import CSV_PATH, load_companies
from pipeline.fetchers import (fetch_ashby, fetch_bamboohr, fetch_breezy, fetch_greenhouse,
                               fetch_lever, fetch_recruitee, fetch_smartrecruiters, fetch_workable,
                               fetch_workday)
from probe_ats import slug_variants

WD_N = [5, 1, 3, 12, 2, 101, 103, 10]


def _try_workday(name, slug):
    """slug is 'tenant/site'; probe the wd-number and return the first combo that returns jobs."""
    if "/" not in (slug or ""):
        return None
    tenant, site = slug.split("/", 1)
    for n in WD_N:
        url = f"https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        row = {"company_name": name, "ats_platform": "workday", "token": slug, "api_url": url}
        try:
            jobs = fetch_workday(row)
        except Exception:  # noqa: BLE001
            continue
        if jobs:
            il = sum(1 for j in jobs if israel.is_israel_job(j))
            return {"plat": "workday", "slug": slug, "url": url, "jobs": len(jobs), "il": il}
    return None

URL = {
    "greenhouse": lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "lever": lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json",
    "ashby": lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}",
    "smartrecruiters": lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings",
    "recruitee": lambda s: f"https://{s}.recruitee.com/api/offers/",
    "workable": lambda s: f"https://apply.workable.com/api/v1/widget/accounts/{s}?details=true",
    "breezy": lambda s: f"https://{s}.breezy.hr/json/",
    "bamboohr": lambda s: f"https://{s}.bamboohr.com/careers/list",
}
FETCH = {
    "greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters, "recruitee": fetch_recruitee,
    "workable": fetch_workable, "breezy": fetch_breezy, "bamboohr": fetch_bamboohr,
}
PROBE_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee",
               "workable", "breezy", "bamboohr"]
# For guessing an UNKNOWN's slug, only probe platforms that 404 fast on a bad slug. breezy/bamboohr
# return their full marketing HTML (~100KB) for any bad slug, which is slow to download+reject.
PROBE_FAST = ["greenhouse", "lever", "ashby", "workable", "recruitee"]


def _cand_slugs(name, careers_url):
    """Best-guess ATS slugs for an unknown: the careers-domain label (often IS the slug) + name forms."""
    import re
    cands = []
    m = re.search(r"https?://(?:www\.|jobs\.|careers\.|apply\.)?([^./]+)", careers_url or "")
    if m:
        cands.append(m.group(1).lower())
    n = (name or "").lower().strip()
    base = n
    for j in (" ", ".", ",", "'", "’", "-", "&", "/"):
        base = base.replace(j, "")
    cands += [base, n.replace(" ", ""), n.split()[0] if n.split() else n]
    out = []
    for c in cands:
        if c and c not in out and len(c) > 1:
            out.append(c)
    return out[:4]


def _try(plat, slug, name):
    url = URL[plat](slug)
    row = {"company_name": name, "ats_platform": plat, "token": slug, "api_url": url}
    try:
        jobs = FETCH[plat](row)
    except Exception:  # noqa: BLE001
        return None
    if plat == "smartrecruiters" and not jobs:
        return None
    if not jobs:
        return None
    il = sum(1 for j in jobs if israel.is_israel_job(j))
    return {"plat": plat, "slug": slug, "url": url, "jobs": len(jobs), "il": il}


def main():
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}

    added, queue, skipped = [], [], 0
    for e in entries:
        name = e["name"].strip()
        if name.lower() in have:
            skipped += 1
            continue
        ats, slug = e.get("ats"), e.get("slug")
        if ats in ("comeet", "teamtailor"):
            queue.append(e)               # browser / unsupported ATS -> Playwright pass
            continue
        if ats == "workday":
            hit = _try_workday(name, slug)
            if hit:
                added.append((name, hit))
                have.add(name.lower())
                print(f"  [OK] {name:26} workday         {hit['slug']:26} "
                      f"jobs={hit['jobs']:4} israel={hit['il']}")
            else:
                queue.append(e)
            continue
        if ats == "unknown":
            # try a fast slug-probe from the domain + name before handing to the Playwright pass;
            # the careers domain is very often the real ATS slug (rapyd.net -> "rapyd").
            hit = None
            for s in _cand_slugs(name, e.get("careers_url", ""))[:2]:
                for plat in PROBE_FAST:
                    r = _try(plat, s, name)
                    if r and r["il"] > 0:
                        hit = r
                        break
                if hit:
                    break
            if hit:
                added.append((name, hit))
                have.add(name.lower())
                print(f"  [OK] {name:26} {hit['plat']:15} slug={hit['slug']:20} "
                      f"jobs={hit['jobs']:4} israel={hit['il']} (probed)")
            else:
                queue.append(e)
            continue
        hit = _try(ats, slug, name) if (ats in URL and slug) else None  # trust researched slug
        if hit:
            added.append((name, hit))
            have.add(name.lower())
            print(f"  [OK] {name:26} {hit['plat']:15} slug={hit['slug']:20} "
                  f"jobs={hit['jobs']:4} israel={hit['il']}")
        else:
            print(f"  [--] {name:26} ({ats}/{slug}) board not live")

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for name, h in added:
            note = f"research-verified; {h['jobs']} jobs / {h['il']} Israel"
            w.writerow([name, h["plat"], h["slug"], h["url"], "true", note])

    with open("out/comeet_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=1)

    print(f"\n=== added {len(added)} via HTTP · {len(queue)} unknowns queued for Playwright "
          f"· {skipped} already present ===")


if __name__ == "__main__":
    main()
