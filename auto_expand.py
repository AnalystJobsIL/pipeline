#!/usr/bin/env python3
"""Self-draining resolver. Each run takes the next batch of companies that are researched but not
yet in companies.csv, resolves them (iframe-ATS / scrape / follow-jobs-link via resolve_deep), and
writes results DIRECTLY into companies.csv + scraped_cache.json. Scheduled in the cloud it keeps
shrinking the unresolved set every run until it reaches zero — no PC, no babysitting.

Env:  AUTO_EXPAND_LIMIT (default 200) companies per run.
Prints the remaining-unresolved count so the workflow / log shows progress.
"""
from __future__ import annotations

import csv
import json
import os
from urllib.parse import urlparse

from pipeline.companies import CSV_PATH, load_companies
from resolve_deep import resolve


def _load_cache():
    try:
        with open("scraped_cache.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def main():
    limit = int(os.environ.get("AUTO_EXPAND_LIMIT", "200"))
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    from pipeline.recruiters import is_recruiter
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have
            and not is_recruiter(e.get("name"))]      # never migrate recruiting/staffing agencies
    batch = todo[:limit]
    print(f"unresolved: {len(todo)} · processing {len(batch)} this run", flush=True)

    cache = _load_cache()
    # Every company gets a row so it leaves the unresolved set — the loop converges to zero:
    #   resolved -> active row with jobs; empty/unreachable -> inactive row (validated scan).
    n_resolved = n_empty = n_unreach = 0
    for e in batch:
        name, url = e["name"].strip(), e["careers_url"]
        try:
            r = resolve(name, url)
        except Exception:  # noqa: BLE001
            r = ("unreachable", None)
        kind = r[0] if r else "unreachable"
        if kind == "ats":
            nm, plat, tok, api, n_all, il = r[1]
            row = [nm, plat, tok, api, "true", f"auto-expand; {n_all}/{il} IL"]
            n_resolved += 1
        elif kind == "scrape":
            jobs2, good_url = r[1] if isinstance(r[1], tuple) else (r[1], url)
            host = urlparse(good_url).netloc.lower()
            if any(a in host for a in ("linkedin.", "indeed.", "glassdoor.")):
                # Scraping an aggregator page ingests its "similar jobs" sidebar — postings
                # from OTHER companies attributed to this one. Park inactive instead.
                row = [name, "scrape", good_url, good_url, "false",
                       "aggregator URL; resolve real careers page before activating"]
                n_unreach += 1
            else:
                cache[name] = jobs2
                row = [name, "scrape", good_url, good_url, "true",
                       f"auto-expand scrape; {len(jobs2)} IL"]
                n_resolved += 1
        elif kind == "empty":
            row = [name, "scrape", url, url, "false", "scanned; no open Israel roles now"]
            n_empty += 1
        else:
            row = [name, "scrape", url, url, "false", "unreachable; could not scan"]
            n_unreach += 1
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
        have.add(name.lower())
        print(f"  {kind[:4]:4} {name}", flush=True)

    with open("scraped_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    remaining = len(todo) - len(batch)
    print(f"=== resolved {n_resolved}, empty {n_empty}, unreachable {n_unreach}; "
          f"~{remaining} still to scan ===", flush=True)


if __name__ == "__main__":
    main()
