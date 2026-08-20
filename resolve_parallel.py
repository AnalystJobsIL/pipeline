#!/usr/bin/env python3
"""Fast PARALLEL HTTP resolver over research_companies.json.

For each company (not already in companies.csv):
  - known slug-ATS (greenhouse/lever/ashby/smartrecruiters/recruitee/workable/breezy/bamboohr):
    verify the researched slug; keep if the board returns jobs.
  - workday (slug 'tenant/site'): probe the wd-number.
  - unknown/comeet: fast slug-probe from the careers domain + name across greenhouse/lever/ashby/
    workable/recruitee; keep a hit only with Israel jobs. Whatever is left is written to
    out/comeet_queue.json for the Playwright pass (resolve_any.py).

Runs many companies concurrently (threads) since each is an independent network wait.
"""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor

from pipeline import http as _http

_orig = _http._request
_http._request = lambda *a, **k: _orig(*a, **{**k, "retries": 1, "timeout": 6})

from pipeline.companies import CSV_PATH, load_companies  # noqa: E402
from ingest_research import (URL, _cand_slugs, _try, _try_workday)  # noqa: E402

PROBE_FAST = ["greenhouse", "lever", "ashby", "workable", "recruitee"]


def worker(e):
    """Return ('add', row_dict) or ('queue', entry) or ('skip', name)."""
    name = (e.get("name") or "").strip()
    ats, slug = e.get("ats"), e.get("slug")
    try:
        if ats == "workday":
            hit = _try_workday(name, slug)
            return ("add", (name, hit)) if hit and hit["jobs"] else ("queue", e)
        if ats in URL and slug:                       # researched slug on a known ATS
            hit = _try(ats, slug, name)
            return ("add", (name, hit)) if hit and hit["jobs"] else ("queue", e)
        # unknown / comeet / teamtailor -> fast domain+name slug-probe
        for s in _cand_slugs(name, e.get("careers_url", ""))[:2]:
            for plat in PROBE_FAST:
                r = _try(plat, s, name)
                if r and r["il"] > 0:
                    return ("add", (name, r))
        return ("queue", e)
    except Exception:  # noqa: BLE001
        return ("queue", e)


def main():
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in entries if (e.get("name") or "").strip().lower() not in have]
    print(f"resolving {len(todo)} new companies ({len(entries) - len(todo)} already present) ...")

    added, queue, seen = [], [], set()
    with ThreadPoolExecutor(max_workers=24) as ex:
        for kind, payload in ex.map(worker, todo):
            if kind == "add":
                name, hit = payload
                k = name.lower()
                if k in seen or k in have:
                    continue
                seen.add(k)
                added.append((name, hit))
                print(f"  [OK] {name:26} {hit['plat']:15} {str(hit['slug'])[:24]:24} "
                      f"jobs={hit['jobs']:4} il={hit['il']}")
            elif kind == "queue":
                queue.append(payload)

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for name, h in added:
            w.writerow([name, h["plat"], h["slug"], h["url"], "true",
                        f"research-resolved; {h['jobs']} jobs / {h['il']} Israel"])
    with open("out/comeet_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=1, ensure_ascii=False)
    print(f"\n=== added {len(added)} over HTTP · {len(queue)} queued for Playwright ===")


if __name__ == "__main__":
    main()
