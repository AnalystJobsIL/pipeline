#!/usr/bin/env python3
"""Resolve Comeet companies' api_url by rendering the careers page with Playwright and reading
window.comeetvar (comeet_uid + comeet_token) — reliable across Comeet's newer lazy-loading widget.

Single:  python comeet_resolve.py "Silverfort" https://www.silverfort.com/careers/
Batch:   python comeet_resolve.py --batch     (uses the CANDIDATES list below; prints CSV rows
                                               for those that verify with Israel jobs, and appends
                                               them to companies.csv)

Requires: pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import csv
import sys

from pipeline import fetchers, israel
from pipeline.companies import CSV_PATH, load_companies

# (company_name, careers_url) — careers pages likely to embed the Comeet widget.
CANDIDATES = [
    ("Silverfort", "https://www.silverfort.com/careers/"),
    ("Panaya", "https://www.panaya.com/careers/"),
    ("Overwolf", "https://www.overwolf.com/careers/"),
    ("Aidoc", "https://www.aidoc.com/careers/"),
    ("LSports", "https://lsports.eu/careers/"),
    ("Natural Intelligence", "https://www.naturalint.com/careers/"),
    ("WSC Sports", "https://wsc-sports.com/careers"),
    ("Glassbox", "https://www.glassbox.com/careers/"),
    ("Coralogix", "https://coralogix.com/careers/"),
    ("Varonis", "https://www.varonis.com/careers"),
    ("Digital Turbine", "https://www.digitalturbine.com/careers/"),
    ("Pentera", "https://pentera.io/careers/"),
    ("Cynerio", "https://www.cynerio.com/careers"),
    ("Sygnia", "https://www.sygnia.co/careers/"),
    ("Hunters", "https://www.hunters.security/careers"),
    ("Cyberint", "https://cyberint.com/careers/"),
    ("Perception Point", "https://perception-point.io/careers/"),
    ("Cynet", "https://www.cynet.com/careers/"),
    ("Mesh Payments", "https://www.meshpayments.com/careers"),
    ("PayEm", "https://www.payem.io/careers"),
    ("Trustmi", "https://www.trustmi.ai/careers"),
    ("DagsHub", "https://dagshub.com/careers"),
    ("Anecdotes", "https://www.anecdotes.ai/careers"),
    ("Firefly", "https://www.firefly.ai/careers"),
    ("Zesty", "https://zesty.co/careers/"),
    ("Codefresh", "https://codefresh.io/careers/"),
    ("Walnut", "https://www.walnut.io/careers/"),
    ("Demostack", "https://www.demostack.com/careers"),
    ("Syte", "https://www.syte.ai/careers/"),
    ("TytoCare", "https://www.tytocare.com/careers/"),
    ("Healthy.io", "https://healthy.io/careers/"),
    ("Nucleai", "https://www.nucleai.com/careers"),
    ("Genoox", "https://www.genoox.com/careers/"),
    ("Hailo", "https://hailo.ai/careers/"),
    ("Innoviz", "https://innoviz.tech/careers"),
    ("Theator", "https://theator.io/careers/"),
    ("NoTraffic", "https://notraffic.tech/careers/"),
    ("Upwind", "https://www.upwind.io/careers"),
    ("Loox", "https://loox.io/careers"),
    ("Carbyne", "https://carbyne.com/careers/"),
    ("Deep Instinct", "https://www.deepinstinct.com/careers"),
    ("Imperva", "https://www.imperva.com/company/careers/"),
    ("eToro", "https://www.etoro.com/careers/"),
    ("Priority Software", "https://www.priority-software.com/careers/"),
    ("Logz.io", "https://logz.io/about-us/careers/"),
    ("Verbit", "https://verbit.ai/careers/"),
]


def resolve(careers_url, timeout_ms=35000):
    """Render the careers page; return (api_url, uid, token) from window.comeetvar, or None."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        try:
            pg.goto(careers_url, wait_until="load", timeout=timeout_ms)
            pg.wait_for_timeout(5000)
            cfg = pg.evaluate("()=>{return (window.comeetvar)?"
                              "{uid:window.comeetvar.comeet_uid,token:window.comeetvar.comeet_token}:null;}")
        except Exception:
            cfg = None
        finally:
            b.close()
    if not cfg or not cfg.get("uid") or not cfg.get("token"):
        return None
    uid, token = cfg["uid"], cfg["token"]
    api = f"https://www.comeet.com/careers-api/2.0/company/{uid}/positions?token={token}"
    return api, uid, token


def resolve_and_verify(name, careers_url):
    r = resolve(careers_url)
    if not r:
        print(f"  [--] {name}: no comeetvar found ({careers_url})")
        return None
    api, uid, token = r
    row = {"company_name": name, "ats_platform": "comeet", "token": uid, "api_url": api}
    try:
        jobs = fetchers.fetch_company(row)
    except Exception as e:  # noqa: BLE001
        print(f"  [xx] {name}: comeetvar found (uid={uid}) but fetch failed: {e}")
        return None
    il = sum(1 for j in jobs if israel.is_israel_job(j))
    print(f"  [OK] {name}: uid={uid} jobs={len(jobs)} israel={il}")
    return {"name": name, "uid": uid, "api": api, "jobs": len(jobs), "il": il}


def _load_queue(path):
    import json
    with open(path, encoding="utf-8") as f:
        return [(e["name"], e["careers_url"]) for e in json.load(f) if e.get("careers_url")]


def main(argv):
    if "--queue" in argv:
        path = argv[argv.index("--queue") + 1]
        candidates = _load_queue(path)
    else:
        candidates = CANDIDATES
    if "--batch" in argv or "--queue" in argv:
        have = {r["company_name"].lower() for r in load_companies(active_only=False)}
        resolved = 0
        for name, url in candidates:
            if name.lower() in have:
                continue
            r = resolve_and_verify(name, url)
            if r and r["jobs"] > 0:
                # append immediately so an interruption never loses resolved companies
                note = f"resolved via Playwright/comeetvar; {r['jobs']} jobs / {r['il']} Israel"
                with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([r["name"], "comeet", r["uid"], r["api"], "true", note])
                have.add(name.lower())
                resolved += 1
        print(f"\n=== resolved {resolved}, appended to companies.csv ===")
        return 0
    if len(argv) >= 3:
        resolve_and_verify(argv[1], argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
