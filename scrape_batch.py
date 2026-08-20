#!/usr/bin/env python3
"""Run the universal scraper across still-unresolved researched companies. For each that yields
Israel jobs, cache the jobs and emit a `scrape` CSV row. Shardable for parallelism.

  SCRAPE_CACHE_OUT / SCRAPE_CSV_OUT env vars set per-shard output files.
  --shard I N  processes todo[I::N].
"""
import csv
import json
import os
import sys

from pipeline import israel
from pipeline.companies import load_companies
from scrape_universal import scrape


def main():
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have]
    if "--shard" in sys.argv:
        i, n = int(sys.argv[sys.argv.index("--shard") + 1]), int(sys.argv[sys.argv.index("--shard") + 2])
        todo = todo[i::n]

    cache_out = os.environ.get("SCRAPE_CACHE_OUT", "out/scrape_cache.json")
    csv_out = os.environ.get("SCRAPE_CSV_OUT", "out/scrape_rows.csv")
    cache = {}
    ok = 0
    for e in todo:
        name = e["name"].strip()
        url = e["careers_url"]
        try:
            jobs = scrape(name, url)
        except Exception:  # noqa: BLE001
            jobs = []
        il = [j for j in jobs if israel.is_israel_job(j)]
        if il:
            cache[name] = il
            with open(csv_out, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([name, "scrape", url, url, "true",
                                        f"universal-scrape; {len(il)} Israel jobs"])
            ok += 1
            print(f"  [OK] {name}: {len(il)} Israel jobs", flush=True)
    with open(cache_out, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"=== scraped {ok} companies with Israel jobs ===", flush=True)


if __name__ == "__main__":
    main()
