"""Backfill structured firmographics for every company in companies.csv.

    python research_firmographics.py --dry-run          # who's missing / stale
    python research_firmographics.py --limit 25         # research a batch
    python research_firmographics.py                    # research all missing
    python research_firmographics.py --refresh-days 365 # also re-research stale records

Each company is one `claude -p` call (web search allowed, ~1-3 min), run on a small
thread pool and saved to the store as each finishes — safe to Ctrl-C and rerun; already-
researched companies are skipped. Seeds the 5 hand-researched POC records from
poc_firmographics.json first so they're never re-paid for. The daily run (pipeline/run.py)
keeps the cache topped up for newly discovered companies; this script is for bulk.

Export for inspection/commit: python research_firmographics.py --export
    -> writes state/firmographics.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# the 6-hourly chain redirects stdout to a log file, which makes Python pick cp1252 on
# Windows — a Hebrew company name in a print then kills the whole run (UnicodeEncodeError)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.companies import load_companies
from pipeline.firmographics import ResearchUnavailable, looks_like_junk, research_company
from pipeline.store import SeenStore, _norm_company

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.join(HERE, "poc_firmographics.json")
EXPORT = os.path.join(HERE, "state", "firmographics.json")


def seed_poc(st, today):
    """Load the hand-researched POC records into the store (idempotent)."""
    if not os.path.exists(POC):
        return 0
    with open(POC, encoding="utf-8") as f:
        poc = json.load(f)
    existing = st.load_firmographics()
    fresh = {k: v for k, v in poc.items() if not k.startswith("_") and k not in existing}
    if fresh:
        st.save_firmographics(fresh, today)
    return len(fresh)


def is_stale(rec, refresh_days):
    if not refresh_days:
        return False
    try:
        return (dt.date.today() - dt.date.fromisoformat(rec.get("as_of", ""))).days > refresh_days
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max companies to research this run")
    ap.add_argument("--workers", type=int, default=3, help="parallel claude -p calls")
    ap.add_argument("--refresh-days", type=int, default=None,
                    help="also re-research records older than this many days")
    ap.add_argument("--dry-run", action="store_true", help="only report, no research")
    ap.add_argument("--export", action="store_true", help="write state/firmographics.json and exit")
    a = ap.parse_args()

    st = SeenStore()
    today = dt.date.today().isoformat()

    if a.export:
        recs = st.load_firmographics()
        with open(EXPORT, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"exported {len(recs)} records -> {EXPORT}")
        return

    seeded = seed_poc(st, today)
    if seeded:
        print(f"seeded {seeded} POC records")

    have = st.load_firmographics()
    names = [r["company_name"] for r in load_companies()]
    # also cover companies that appear on the actual board (CI's matched table) but are
    # not in companies.csv — CI's discovery layer surfaces jobs from employers we never
    # explicitly listed, and those jobs deserve a profile too
    cloud_db = os.path.join(HERE, "cloud_state", "seen.db")
    if os.path.exists(cloud_db):
        import sqlite3
        con = sqlite3.connect(cloud_db)
        board = [r[0] for r in con.execute("SELECT DISTINCT company FROM matched")]
        con.close()
        names += [n for n in board if n not in names]
    # leaked job titles ("Sql developer - X", "my team") are never companies: skip for
    # free, forever — researching them profiles the embedded company under a junk key
    junk = [n for n in names if looks_like_junk(n)]
    if junk:
        print(f"skipping {len(junk)} junk (job-title) names: {', '.join(junk[:5])}"
              + (" ..." if len(junk) > 5 else ""))
        names = [n for n in names if n not in set(junk)]
    # identity is normalized (suffix/case-insensitive): "SolarEdge" and "SolarEdge
    # Technologies" are one company — don't research (and pay for) both
    have_norms = {_norm_company(n) for n in have}
    todo, seen_norms = [], set()
    for n in names:
        nn = _norm_company(n)
        if n in have:
            if is_stale(have[n], a.refresh_days):
                todo.append(n)
            continue
        if nn in have_norms or nn in seen_norms:
            continue  # a variant of an already-profiled (or already-queued) company
        seen_norms.add(nn)
        todo.append(n)
    # names that keep failing (junk from discovery, ambiguous) retry at most WEEKLY so
    # they don't re-spend a web-search claude call every 6-hour chain run forever
    failures = st.load_firmo_failures()
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    gated = [n for n in todo if n in failures and failures[n][1] > week_ago]
    todo = [n for n in todo if n not in gated]
    print(f"{len(names)} active companies, {len(have)} researched, {len(todo)} to do"
          + (f" ({len(gated)} recent-failure names gated to weekly retry)" if gated else ""))
    if a.dry_run or not todo:
        for n in todo:
            print("  -", n)
        return
    if a.limit:
        todo = todo[: a.limit]

    done = failed = 0
    infra_streak = 0
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = {ex.submit(research_company, name): name for name in todo}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                rec = fut.result()
            except ResearchUnavailable as e:
                # infrastructure outage (CLI logged out, network): NOT the name's fault —
                # no firmo_failed stamp, and 3 in a row means everything else will fail
                # too, so stop burning the queue and let the next chain run retry cleanly
                infra_streak += 1
                print(f"UNAVAILABLE {name}: {e} (no failure recorded)")
                if infra_streak >= 3:
                    print("3 consecutive infrastructure errors — aborting run; nothing was gated")
                    ex.shutdown(cancel_futures=True)
                    break
                continue
            infra_streak = 0
            if rec:
                if name in have:
                    # merge-preserve: re-research must not destroy what the fill passes
                    # paid for — keep an established count when the fresh record has none
                    old = have[name]
                    if not rec.get("employees_global") and old.get("employees_global"):
                        for k in ("employees_global", "size_band", "employees_source",
                                  "employees_as_of", "employees_range"):
                            if old.get(k):
                                rec[k] = old[k]
                    if old.get("employees_lookup_miss") and not rec.get("employees_global"):
                        rec["employees_lookup_miss"] = old["employees_lookup_miss"]
                st.save_firmographics({name: rec}, today)  # main thread owns sqlite
                done += 1
                print(f"ok   {name}: {rec['sector']} / {rec.get('stage') or '?'} / {rec.get('size_band') or '?'}")
            else:
                failed += 1
                st.record_firmo_failure(name, today)
                strikes = st.load_firmo_failures().get(name, (1, ""))[0]
                print(f"FAIL {name} (strike {strikes}; weekly retry)")
    print(f"\n{done} researched, {failed} failed, {len(have) + done} total in store")


if __name__ == "__main__":
    main()
