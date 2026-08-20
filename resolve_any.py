#!/usr/bin/env python3
"""General careers-API resolver: load a company's careers page in Playwright, watch the network for
whichever ATS API it calls (Greenhouse/Lever/Ashby/SmartRecruiters/Recruitee/Workable/Workday) or
read window.comeetvar, extract the exact platform + slug/tenant, build the canonical api_url and
verify it returns Israel jobs. This resolves "custom" career sites that proxy to a known ATS
(most big companies do) without guessing slugs.

Usage:
  python resolve_any.py "Wiz" https://www.wiz.io/careers
  python resolve_any.py --queue path.json          # [{name, careers_url}, ...]; appends verified rows
"""
from __future__ import annotations

import csv
import json
import re
import sys

from pipeline import fetchers, israel
from pipeline.companies import CSV_PATH, load_companies

PATTERNS = [
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/?]+)")),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([^/?]+)")),
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/embed/job_board\?for=([^&]+)")),
    ("lever", re.compile(r"api\.(?:eu\.)?lever\.co/v0/postings/([^/?]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/api/non-user-graphql")),  # slug from page url
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([^/?]+)")),
    ("recruitee", re.compile(r"https?://([^.]+)\.recruitee\.com/api")),
    ("workable", re.compile(r"workable\.com/api/[^/]+/(?:widget/)?accounts/([^/?]+)")),
    ("workday", re.compile(r"https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/wday/cxs/([^/]+)/([^/]+)/")),
]

URLBUILD = {
    "greenhouse": lambda m: ("greenhouse", m.group(1),
                             f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs"),
    "lever": lambda m: ("lever", m.group(1),
                        f"https://api.lever.co/v0/postings/{m.group(1)}?mode=json"),
    "smartrecruiters": lambda m: ("smartrecruiters", m.group(1),
                                  f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings"),
    "recruitee": lambda m: ("recruitee", m.group(1),
                            f"https://{m.group(1)}.recruitee.com/api/offers/"),
    "workable": lambda m: ("workable", m.group(1),
                           f"https://apply.workable.com/api/v1/widget/accounts/{m.group(1)}?details=true"),
    "workday": lambda m: ("workday", f"{m.group(1)}/{m.group(4)}",
                          f"https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com/wday/cxs/"
                          f"{m.group(3)}/{m.group(4)}/jobs"),
}


def detect(name, careers_url):
    """Return (platform, token, api_url) or None by watching the careers page's network + comeetvar."""
    from playwright.sync_api import sync_playwright
    seen = []
    comeet = {}

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        pg.on("request", lambda r: seen.append(r.url))
        try:
            pg.goto(careers_url, wait_until="load", timeout=35000)
            pg.wait_for_timeout(4000)
            pg.mouse.wheel(0, 2500)
            pg.wait_for_timeout(3500)
            cfg = pg.evaluate("()=>window.comeetvar?{u:window.comeetvar.comeet_uid,"
                              "t:window.comeetvar.comeet_token}:null")
            if cfg:
                comeet = cfg
            # ashby slug lives in the page URL, not the request
            page_url = pg.url
        except Exception:
            page_url = careers_url
        finally:
            b.close()

    if comeet.get("u") and comeet.get("t"):
        return ("comeet", comeet["u"],
                f"https://www.comeet.com/careers-api/2.0/company/{comeet['u']}/positions?token={comeet['t']}")

    for url in seen:
        for plat, rx in PATTERNS:
            m = rx.search(url)
            if not m:
                continue
            if plat == "ashby":
                am = re.search(r"ashbyhq\.com/([^/?#]+)", page_url) or \
                    re.search(r"ashbyhq\.com/([^/?#]+)", url)
                if am:
                    s = am.group(1)
                    return ("ashby", s, f"https://api.ashbyhq.com/posting-api/job-board/{s}")
                continue
            return URLBUILD[plat](m)
    return None


def resolve_and_verify(name, careers_url):
    try:
        r = detect(name, careers_url)
    except Exception as e:  # noqa: BLE001
        print(f"  [xx] {name}: detect error {type(e).__name__}: {str(e)[:60]}")
        return None
    if not r:
        print(f"  [--] {name}: no known ATS API detected ({careers_url})")
        return None
    plat, tok, api = r
    row = {"company_name": name, "ats_platform": plat, "token": tok, "api_url": api}
    try:
        jobs = fetchers.fetch_company(row)
    except Exception as e:  # noqa: BLE001
        print(f"  [xx] {name}: detected {plat} but fetch failed: {type(e).__name__}")
        return None
    il = sum(1 for j in jobs if israel.is_israel_job(j))
    print(f"  [OK] {name}: {plat} token={tok} jobs={len(jobs)} israel={il}")
    return {"name": name, "plat": plat, "tok": tok, "api": api, "jobs": len(jobs), "il": il}


def main(argv):
    if "--queue" in argv:
        import os
        with open(argv[argv.index("--queue") + 1], encoding="utf-8") as f:
            items = [(e["name"], e["careers_url"]) for e in json.load(f) if e.get("careers_url")]
        if "--shard" in argv:                          # --shard I N  -> process items[I::N]
            i, n = int(argv[argv.index("--shard") + 1]), int(argv[argv.index("--shard") + 2])
            items = items[i::n]
        outfile = os.environ.get("RESOLVE_OUTFILE", CSV_PATH)
        have = {r["company_name"].lower() for r in load_companies(active_only=False)}
        added = 0
        for name, url in items:
            if name.lower() in have:
                continue
            r = resolve_and_verify(name, url)
            if r and r["jobs"] > 0:
                with open(outfile, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([r["name"], r["plat"], r["tok"], r["api"], "true",
                                            f"resolved via network capture; {r['jobs']} jobs / {r['il']} Israel"])
                have.add(name.lower())
                added += 1
        print(f"\n=== added {added} ===")
        return 0
    if len(argv) >= 3:
        resolve_and_verify(argv[1], argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
