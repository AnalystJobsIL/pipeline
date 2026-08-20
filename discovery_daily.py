#!/usr/bin/env python3
"""Daily discovery layer: LinkedIn + Indeed jobs scrapers (Bright Data) for Israel analytics roles.

- Triggers small discovery queries (quota-capped), waits, fetches records.
- Jobs are normalized and written to discovered_cache.json -> read by fetch_discovery in the
  pipeline (company shown as the real employer, url = posting link).
- Companies NOT already in companies.csv are written to out/discovered_companies.json — the
  auto-expand loop then resolves their own ATS so they migrate to free direct scanning.

Budget: ~40 records/day * 30 = ~1200/mo of the 5k free tier, split LinkedIn/Indeed.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

from bd_rescue import _load_secrets
from pipeline.companies import load_companies

QUERIES = {
    "linkedin": ("gd_lpfll7v5hcqtkxl6l", "keyword", [
        {"location": "Israel", "keyword": "data analyst", "country": "IL"},
        {"location": "Israel", "keyword": "business intelligence", "country": "IL"},
    ], 15),
    "indeed": ("gd_l4dx9j9sscpvs7no2", "keyword", [
        {"country": "IL", "domain": "il.indeed.com", "keyword_search": "data analyst",
         "location": "Israel"},
    ], 15),
}


def _req(url, data=None, method="GET", timeout=60):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def run_query(name):
    ds, disc, inputs, limit = QUERIES[name]
    return run_query_raw(ds, disc, inputs, limit)


def run_query_raw(ds, disc, inputs, limit):
    q = urllib.parse.urlencode({"dataset_id": ds, "type": "discover_new", "discover_by": disc,
                                "limit_per_input": str(limit)})
    sid = json.loads(_req(f"https://api.brightdata.com/datasets/v3/trigger?{q}",
                          data=json.dumps(inputs).encode(), method="POST")).get("snapshot_id")
    if not sid:
        return []
    for _ in range(60):
        st = json.loads(_req(f"https://api.brightdata.com/datasets/v3/progress/{sid}")).get("status")
        if st == "ready":
            break
        if st in ("failed", "error"):
            return []
        time.sleep(15)
    body = _req(f"https://api.brightdata.com/datasets/v3/snapshot/{sid}?format=json", timeout=120)
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return [json.loads(l) for l in body.splitlines() if l.strip()]


_REL = re.compile(r"(\d+)\+?\s*(?:days?|ימים|ימי)", re.I)
_JUNIOR_HE = ("ללא ניסיון", "סטודנט", "משרת סטודנט", "junior")


def _fix_date(raw):
    """Relative dates ('5 days ago', 'לפני 3 ימים') -> ISO; '30+ days' -> None (stale)."""
    import datetime as dt
    t = str(raw or "")
    if len(t) >= 10 and t[4:5] == "-":
        return t[:10]
    m = _REL.search(t)
    if not m:
        return ""
    days = int(m.group(1))
    if "+" in t or days > 21:
        return None                       # stale — drop the job
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def normalize(name, r):
    title = r.get("job_title") or r.get("title") or ""
    comp = r.get("company_name") or r.get("company") or ""
    loc = r.get("job_location") or r.get("location") or "Israel"
    url = r.get("apply_link") or r.get("url") or r.get("job_url") or ""
    date = _fix_date(r.get("job_posted_date") or r.get("date_posted") or r.get("posted_date") or "")
    if date is None:
        return None                        # 30+ days old — not board-worthy
    desc = (r.get("job_summary") or r.get("job_description") or r.get("description") or "")[:1800]
    if not title or not comp:
        return None
    tl = (str(title) + " " + str(r.get("job_summary") or ""))[:400].lower()
    if any(k in tl for k in _JUNIOR_HE):
        return None                        # junior/student postings out
    return {"company": str(comp)[:80], "title": str(title)[:140], "location": str(loc)[:80],
            "country_code": "IL", "url": url, "posted_date": date,
            "ats_platform": f"discovery-{name}", "job_id": url or f"{comp}|{title}",
            "description": re.sub(r"<[^>]+>", " ", str(desc))}


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _targeted_inputs(cap=20):
    """LinkedIn queries aimed at the companies whose direct ATS is broken AND that the free
    re-capture couldn't fix — the 'unresolvable remainder' (anti-bot Workday, custom-board
    movers). Discovery is the free safety net for exactly these, so we search each by name."""
    stale = _load_json("cloud_state/stale.json")
    resolved = _load_json("out/resolved_configs.json")
    unresolved = [n for n in stale if n not in resolved]
    return [{"location": "Israel", "keyword": f"{name} data analyst", "country": "IL"}
            for name in unresolved[:cap]]


def main():
    _load_secrets()
    if not os.environ.get("BRIGHTDATA_API_KEY"):
        print("no BRIGHTDATA_API_KEY; skipping discovery")
        return
    jobs, seen = [], set()
    runs = [(n, *QUERIES[n]) for n in QUERIES]
    targeted = _targeted_inputs()
    if targeted:
        li_ds = QUERIES["linkedin"][0]
        runs.append(("linkedin-targeted", li_ds, "keyword", targeted, 8))
        print(f"targeting {len(targeted)} unresolved-broken companies via discovery")
    for n, ds, disc, inputs, limit in runs:
        try:
            recs = run_query_raw(ds, disc, inputs, limit)
        except Exception as e:  # noqa: BLE001
            print(f"[{n}] ERR {type(e).__name__}: {str(e)[:120]}")
            recs = []
        print(f"[{n}] {len(recs)} records")
        for r in recs:
            j = normalize(n, r)
            if not j:
                continue
            k = (j["company"].lower(), j["title"].lower())
            if k in seen:
                continue
            seen.add(k)
            jobs.append(j)
    if jobs:
        with open("discovered_cache.json", "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=1)
    else:
        print("no records fetched — keeping yesterday's discovered_cache.json")
    # companies we don't scan directly yet -> hand to the auto-expand resolver
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    new_cos = {}
    for j in jobs:
        c = j["company"].strip()
        if c.lower() not in have and c.lower() not in new_cos:
            new_cos[c.lower()] = {"name": c, "careers_url": j["url"], "ats": "unknown", "slug": ""}
    with open("out/discovered_companies.json", "w", encoding="utf-8") as f:
        json.dump(list(new_cos.values()), f, ensure_ascii=False, indent=1)
    print(f"=== {len(jobs)} discovered jobs cached · {len(new_cos)} new companies for migration ===")


if __name__ == "__main__":
    main()
