#!/usr/bin/env python3
"""Pass 1 of unknown-resolution: a FAST HTTP slug-probe of the queued custom careers pages.
Tries the 2-3 most likely slugs against greenhouse/lever/ashby/smartrecruiters/recruitee and keeps
a hit only when it returns Israel jobs (strong signal it's the right company). Everything still
unresolved is written to out/comeet_queue2.json for the Playwright/comeet pass.
"""
from pipeline import http as _http

_orig = _http._request
_http._request = lambda *a, **k: _orig(*a, **{**k, "retries": 1, "timeout": 6})

import csv  # noqa: E402
import json  # noqa: E402

from pipeline.companies import CSV_PATH, load_companies  # noqa: E402
from ingest_research import PROBE_ORDER, _try  # noqa: E402


def variants(name):
    n = name.lower().strip()
    base = n
    for j in (" ", ".", ",", "'", "’", "-", "&", "/"):
        base = base.replace(j, "")
    cand = [base, n.replace(" ", ""), n.split()[0] if n.split() else n]
    out = []
    for v in cand:
        if v and v not in out:
            out.append(v)
    return out[:3]


def main():
    with open("out/comeet_queue.json", encoding="utf-8") as f:
        q = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    added, remaining = [], []
    for e in q:
        name = e["name"].strip()
        if name.lower() in have:
            continue
        hit = None
        for sv in variants(name):
            for plat in PROBE_ORDER:
                r = _try(plat, sv, name)
                if r and r["il"] > 0:
                    hit = r
                    break
            if hit:
                break
        if hit:
            added.append((name, hit))
            have.add(name.lower())
            print(f"  [OK] {name:24} {hit['plat']:15} slug={hit['slug']:18} "
                  f"jobs={hit['jobs']} il={hit['il']}")
        else:
            remaining.append(e)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for name, h in added:
            w.writerow([name, h["plat"], h["slug"], h["url"], "true",
                        f"research-http; {h['jobs']} jobs / {h['il']} Israel"])
    with open("out/comeet_queue2.json", "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=1)
    print(f"\n=== http-added {len(added)} · {len(remaining)} remain for Playwright ===")


if __name__ == "__main__":
    main()
