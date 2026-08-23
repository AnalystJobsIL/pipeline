#!/usr/bin/env python3
"""Re-scrape every `scrape` company in companies.csv and rewrite scraped_cache.json.

Run out-of-band (weekly workflow or locally) so the daily pipeline can read fresh scraped jobs
without doing slow Playwright work itself. Shardable via --shard I N for parallel local runs.
"""
import datetime as _dt
import json
import time
import os
import sys

from pipeline import israel
from pipeline.companies import load_companies
from scrape_universal import scrape
from pipeline.atomic import write_csv_rows
from pipeline.notes import append as _note_append, replace_own as _note_replace


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
    # An ERROR means the page itself broke — real rot, but give transient blocks room.
    ROT_PARK_DAYS = 7
    # An EMPTY page is NOT rot. Companies in this market routinely have no openings for a
    # month or more; parking them on a 3-day empty streak retired healthy sources and meant
    # the next role posted there was invisible until something re-found the company. Empty
    # rows are NEVER parked. A very long streak only earns a re-VALIDATION by triage (which
    # can tell "no roles" from "roles we can't extract"), and the row stays active and
    # scanned daily the whole time.
    EMPTY_REVALIDATE_DAYS = 45
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
    revalidate = []
    # ~850 active scrape rows against a 330-minute job timeout. The cache is built from
    # scratch and only written AFTER the loop, so a timeout used to discard the entire run
    # — hours of scraping, nothing saved. Stop cleanly with time to spare, then carry the
    # UNPROCESSED companies over from the previous cache so a partial run still progresses
    # (processed-and-empty companies are correctly dropped; only untouched ones carry).
    budget = int(os.environ.get("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0"))
    t0 = time.time()
    done_names = set()
    for r in rows:
        if budget and (time.time() - t0) / 60 > budget:
            print(f"time budget {budget}min reached — carrying over "
                  f"{len(rows) - len(done_names)} unprocessed companies", flush=True)
            for rest in rows:
                if rest["company_name"] not in done_names and rest["company_name"] in old:
                    cache[rest["company_name"]] = old[rest["company_name"]]
            break
        done_names.add(r["company_name"])
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
                    # carry the attempt stamp REGARDLESS of whether text was found —
                    # otherwise failed enrichments lose their 7-day cooldown every night
                    # and re-burn Bright Data calls on the same unfetchable URLs
                    if pj and pj.get("_jd_attempted"):
                        j["_jd_attempted"] = pj["_jd_attempted"]
            cache[r["company_name"]] = il
            rot.pop(r["company_name"], None)               # healthy again
        else:
            days = _rot_bump(r["company_name"], "empty")
            # NEVER park on empty — see EMPTY_REVALIDATE_DAYS above. After a long streak,
            # ask triage to look at the page with an LLM (it distinguishes "genuinely no
            # openings" from "roles are there and our extractor misses them"); the row
            # stays ACTIVE and scanned daily either way.
            if days >= EMPTY_REVALIDATE_DAYS:
                revalidate.append((r["company_name"], days))
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
                fr[5] = _note_replace(
                    fr[5], "scrape rotted",
                    f"scrape rotted ({names[fr[0]]}) {today}: extraction yields 0 — "
                    f"no ATS detected; parked for re-hunt")
        write_csv_rows("companies.csv", fresh)
        print(f"parked {len(parked)} rotted scrape rows for re-hunt: "
              f"{[n for n, _ in parked][:8]}")

    # long-empty rows STAY ACTIVE; they are only flagged so triage re-reads the page with an
    # LLM and can tell "no openings" from "openings we fail to extract".
    if revalidate:
        import csv as _csv2
        fresh2 = list(_csv2.reader(open("companies.csv", encoding="utf-8")))
        ages = dict(revalidate)
        for fr in fresh2:
            if fr and len(fr) > 5 and fr[0] in ages and "empty-but-suspect" not in (fr[5] or ""):
                fr[5] = _note_append(
                    fr[5], f"empty-but-suspect {today}: {ages[fr[0]]}d with no roles "
                           f"— re-validate page")
        write_csv_rows("companies.csv", fresh2)
        print(f"flagged {len(revalidate)} long-empty rows for re-validation (still active)")
    print(f"=== refreshed {len(cache)} scrape companies -> {out_path} ===")


if __name__ == "__main__":
    main()
