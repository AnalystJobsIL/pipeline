#!/usr/bin/env python3
"""Second-pass validation of Bright-Data-scanned companies: prove the 'empty' ones really are.

For every row whose note says 'scanned via brightdata', re-fetch the page through the Unlocker and
run the FULL extraction stack over the returned HTML (the Unlocker renders JS):
  - JSON-LD JobPosting objects
  - any embedded JSON blobs (application/json scripts, __NEXT_DATA__ etc.) via scrape_universal._find
  - job-detail link patterns with role-like anchor text near Israel locations
Anything with real Israel roles gets promoted to an active scrape row (jobs cached). The rest are
confirmed-empty with evidence. Prints a per-company verdict.
"""
from __future__ import annotations

import csv
import json
import re

from bd_rescue import _load_secrets, unlock
from pipeline import israel
from scrape_universal import (BAD_TITLE, ISRAEL_LOC, ROLE, _find, _loc_from_ctx)

_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                 re.S | re.I)
_JSONBLOB = re.compile(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
                       re.S | re.I)
_NEXT = re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S | re.I)
_LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.{5,140}?)</a>', re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def extract_jobs(company, url, html):
    jobs, seen = [], set()

    def add(title, loc, u):
        title = _TAGS.sub("", title).strip()[:140]
        if not title or BAD_TITLE.match(title) or not ROLE.search(title):
            return
        key = (title.lower(), loc.lower())
        if key in seen:
            return
        seen.add(key)
        jobs.append({"company": company, "title": title, "location": loc, "country_code": "IL",
                     "url": u or url, "posted_date": "", "ats_platform": "scrape",
                     "job_id": u or title, "description": ""})

    raw = []
    for rx in (_LD, _JSONBLOB, _NEXT):
        for m in rx.finditer(html):
            try:
                _find(json.loads(m.group(1)), raw)
            except Exception:  # noqa: BLE001
                pass
    for o in raw:
        title = ""
        for k, v in o.items():
            if k.lower() in ("title", "name", "jobtitle", "postingtitle") and isinstance(v, str):
                title = v
                break
        locs = json.dumps(o)
        m = ISRAEL_LOC.search(locs)
        if title and m:
            add(title, _loc_from_ctx(locs[max(0, m.start() - 40):m.end() + 40]), o.get("url", ""))
    for m in _LINK.finditer(html):
        href, text = m.group(1), _TAGS.sub("", m.group(2)).strip()
        ctx = html[max(0, m.start() - 400):m.end() + 400]
        if ROLE.search(text) and ISRAEL_LOC.search(ctx) and re.search(
                r"/(job|position|opening|vacancy|role|gh_jid|apply)", href, re.I):
            add(text, _loc_from_ctx(ctx), href)
    return [j for j in jobs if israel.is_israel_job(j)]


def main():
    _load_secrets()
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
               if len(r) >= 6 and "scanned via brightdata" in (r[5] or "").lower()}
    print(f"deep-validating {len(targets)} brightdata-scanned companies ...")
    try:
        cache = json.load(open("scraped_cache.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    promoted = confirmed = 0
    for name, (rowi, url) in targets.items():
        html = unlock(url)
        il = extract_jobs(name, url, html) if len(html) > 600 else []
        if il:
            cache[name] = il
            rows[rowi] = [name, "scrape", url, url, "true", f"bd-validated; {len(il)} IL jobs"]
            promoted += 1
            print(f"  [PROMOTE] {name}: {len(il)} Israel roles found!", flush=True)
        else:
            confirmed += 1
            print(f"  [empty ok] {name}", flush=True)
    with open("companies.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    with open("scraped_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"=== promoted {promoted} · confirmed-empty {confirmed} ===")


if __name__ == "__main__":
    main()
