#!/usr/bin/env python3
"""Re-scrape every `scrape` company in companies.csv and rewrite scraped_cache.json.

Run out-of-band (weekly workflow or locally) so the daily pipeline can read fresh scraped jobs
without doing slow Playwright work itself. Shardable via --shard I N for parallel local runs.
"""
import datetime as _dt
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
    # rot tracking: an active scrape row that yields nothing (empty OR erroring) for days
    # is a redesigned/blocked site, not a company with no roles. Without this, empties are
    # silently dropped forever and errors carry stale jobs forever (both fail-silent).
    ROT_PATH = "cloud_state/scrape_rot.json"
    CARRY_MAX_DAYS = 14
    ROT_PARK_DAYS = 3
    try:
        rot = json.load(open(ROT_PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        rot = {}
    today = _dt.date.today().isoformat()

    def _rot_bump(name, why):
        e = rot.setdefault(name, {"since": today, "why": why})
        e["why"], e["last"] = why, today
        return (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(e["since"])).days

    cache = {}
    parked = []
    for r in rows:
        try:
            jobs = scrape(r["company_name"], r["api_url"])
        except Exception:  # noqa: BLE001
            jobs = None                       # scrape ERROR != confirmed-empty
        if jobs is None:
            days = _rot_bump(r["company_name"], "error")
            if r["company_name"] in old and days < CARRY_MAX_DAYS:
                cache[r["company_name"]] = old[r["company_name"]]
                print(f"  {r['company_name']}: ERROR (kept previous, day {days})", flush=True)
            else:
                print(f"  {r['company_name']}: ERROR (carry expired after "
                      f"{CARRY_MAX_DAYS}d — dropping stale jobs)", flush=True)
            if days >= ROT_PARK_DAYS:
                parked.append((r["company_name"], f"error {days}d"))
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
            rot.pop(r["company_name"], None)               # healthy again
        else:
            days = _rot_bump(r["company_name"], "empty")
            if days >= ROT_PARK_DAYS:
                parked.append((r["company_name"], f"empty {days}d"))
        print(f"  {r['company_name']}: {len(il)}", flush=True)

    if old and len(cache) < 0.8 * len(old):
        print(f"ABORT: cache would shrink {len(old)} -> {len(cache)} (>20%); keeping old file")
        return
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(rot, open(ROT_PATH, "w", encoding="utf-8"), indent=1)

    # park rotted rows so the listing-hunt pool re-finds/re-verifies them (active rows are
    # structurally invisible to listing-hunt and the weekly audits — this is the handoff)
    if parked:
        import csv as _csv
        fresh = list(_csv.reader(open("companies.csv", encoding="utf-8")))
        names = dict(parked)
        for fr in fresh:
            if fr and len(fr) > 5 and fr[0] in names and fr[4] == "true":
                fr[4] = "false"
                fr[5] = (f"scrape rotted ({names[fr[0]]}) {today}: extraction yields 0 — "
                         f"no ATS detected; parked for re-hunt")[:220]
        _csv.writer(open("companies.csv", "w", encoding="utf-8", newline="")).writerows(fresh)
        print(f"parked {len(parked)} rotted scrape rows for re-hunt: "
              f"{[n for n, _ in parked][:8]}")
    print(f"=== refreshed {len(cache)} scrape companies -> {out_path} ===")


if __name__ == "__main__":
    main()
