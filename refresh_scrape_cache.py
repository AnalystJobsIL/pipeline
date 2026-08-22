#!/usr/bin/env python3
"""Re-scrape every `scrape` company in companies.csv and rewrite scraped_cache.json.

Run out-of-band (weekly workflow or locally) so the daily pipeline can read fresh scraped jobs
without doing slow Playwright work itself. Shardable via --shard I N for parallel local runs.
"""
import json
import os
import sys

from pipeline import israel
from pipeline.companies import load_companies
from scrape_universal import scrape


def main():
    rows = [r for r in load_companies(active_only=True) if r["ats_platform"] == "scrape"]
    if "--shard" in sys.argv:
        i, n = int(sys.argv[sys.argv.index("--shard") + 1]), int(sys.argv[sys.argv.index("--shard") + 2])
        rows = rows[i::n]
    out_path = os.environ.get("SCRAPE_CACHE_OUT", "scraped_cache.json")
    try:
        old = json.load(open(out_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        old = {}
    cache = {}
    for r in rows:
        try:
            jobs = scrape(r["company_name"], r["api_url"])
        except Exception:  # noqa: BLE001
            jobs = None                       # scrape ERROR != confirmed-empty
        if jobs is None:
            if r["company_name"] in old:      # carry forward last good result
                cache[r["company_name"]] = old[r["company_name"]]
            print(f"  {r['company_name']}: ERROR (kept previous)", flush=True)
            continue
        il = [j for j in jobs if israel.is_israel_job(j)]
        if il:
            # carry forward enriched JDs: a rebuilt card with an empty description inherits
            # the previous run's text (keyed by url/job_id) so daily refreshes stop wiping
            # what enrich_scrape_jd fetched (and re-burning its Unlocker budget)
            prev = {(j.get("url") or j.get("job_id") or ""): j
                    for j in old.get(r["company_name"], []) if isinstance(j, dict)}
            for j in il:
                if not (j.get("description") or "").strip():
                    pj = prev.get(j.get("url") or j.get("job_id") or "")
                    if pj and (pj.get("description") or "").strip():
                        j["description"] = pj["description"]
                        if pj.get("_jd_attempted"):
                            j["_jd_attempted"] = pj["_jd_attempted"]
            cache[r["company_name"]] = il
        print(f"  {r['company_name']}: {len(il)}", flush=True)
    if old and len(cache) < 0.8 * len(old):
        print(f"ABORT: cache would shrink {len(old)} -> {len(cache)} (>20%); keeping old file")
        return
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"=== refreshed {len(cache)} scrape companies -> {out_path} ===")


if __name__ == "__main__":
    main()
