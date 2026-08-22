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
from pipeline.firmographics import (ResearchUnavailable, band_for, identity_key,
                                    looks_like_junk, research_company)
from pipeline.store import SeenStore

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.join(HERE, "poc_firmographics.json")
EXPORT = os.path.join(HERE, "state", "firmographics.json")
REFRESH_CAP = 20  # stale-record refreshes per run; 4 chain runs/day -> full store ~10 days


def fetch_cloud_db():
    """Fetch origin and extract CI's committed cloud_state/seen.db to a state/ file.

    NEVER pulls the worktree: a dirty companies.csv (routine — other sessions annotate
    it) blocks --ff-only forever with no error anyone reads, silently freezing the
    board-company target feed. Blob extraction has no such failure mode.
    Returns the extracted path, or None (offline / git trouble) — caller falls back to
    the possibly-stale worktree copy.
    """
    import subprocess
    out = os.path.join(HERE, "state", "cloud_seen_fetch.db")
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=HERE, capture_output=True, timeout=120)
        blob = subprocess.run(["git", "show", "origin/master:cloud_state/seen.db"],
                              cwd=HERE, capture_output=True, timeout=60)
        if blob.returncode != 0 or len(blob.stdout) < 1024:
            return None
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(blob.stdout)
        return out
    except Exception:  # noqa: BLE001
        return None


def _stamp_ok():
    """Write the health heartbeat firmo_health_check.py watches."""
    with open(os.path.join(HERE, "state", "firmo_last_ok.txt"), "w", encoding="utf-8") as f:
        f.write(dt.datetime.now().isoformat(timespec="seconds"))


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
    cloud_db = fetch_cloud_db() or os.path.join(HERE, "cloud_state", "seen.db")
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
    # failure gates FIRST — gated names must not win refresh-cap slots they then vacate
    # (that starved real refreshes), and permanently failing refreshes (4+ strikes ~ a
    # month of weekly retries) are evicted from the refresh layer entirely so squatters
    # can never consume the whole cap once the store ages
    failures = st.load_firmo_failures()
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    failed_norms = {identity_key(c) for c, (att, last) in failures.items() if last > week_ago}
    refresh_abandoned = {c for c, (att, last) in failures.items() if att >= 4}
    # identity is normalized (repeated-suffix/site/alias-insensitive): "SolarEdge" and
    # "SolarEdge Technologies" are one company — don't research (and pay for) both
    have_norms = {identity_key(n) for n in have}
    todo, gated, seen_norms = [], [], set()
    stale_pick = {}  # identity group -> its STALEST variant (rotates variants over passes)
    for n in names:
        nn = identity_key(n)
        if n in have:
            if is_stale(have[n], a.refresh_days) and n not in refresh_abandoned:
                if nn in failed_norms:
                    gated.append(n)
                    continue
                cur = stale_pick.get(nn)
                if cur is None or have[n].get("as_of", "") < have[cur].get("as_of", ""):
                    stale_pick[nn] = n
            continue
        if nn in have_norms or nn in seen_norms:
            continue  # a variant of an already-profiled (or already-queued) company
        if nn in failed_norms:
            gated.append(n)
            continue
        seen_norms.add(nn)
        todo.append(n)
    # rolling refresh: stalest first, capped per run — the whole store shares a birth
    # date, so an uncapped refresh would try ~770 researches in one chain run. One
    # stalest variant per group per pass also rotates through variant records over time.
    refresh = sorted(stale_pick.values(), key=lambda n: have[n].get("as_of", ""))[:REFRESH_CAP]
    if refresh:
        print(f"refreshing {len(refresh)} stale records (cap {REFRESH_CAP}/run)")
    seen_norms.update(identity_key(n) for n in refresh)
    todo.extend(refresh)
    print(f"{len(names)} active companies, {len(have)} researched, {len(todo)} to do"
          + (f" ({len(gated)} recent-failure names gated to weekly retry)" if gated else ""))
    if a.dry_run or not todo:
        for n in todo:
            print("  -", n)
        if not a.dry_run:
            _stamp_ok()  # a clean zero-todo run IS healthy: the chain ran and nothing is
            # stuck — without this, a quiet weekend fires false Desktop alerts that
            # train the user to ignore the one channel real outages depend on
        return
    if a.limit:
        todo = todo[: a.limit]

    done = failed = 0
    infra_streak = infra_errors = 0
    failed_names = []
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
                infra_errors += 1
                print(f"UNAVAILABLE {name}: {e} (no failure recorded)")
                if infra_streak >= 3:
                    print("3 consecutive infrastructure errors — aborting run; nothing was gated")
                    ex.shutdown(cancel_futures=True)
                    break
                continue
            infra_streak = 0
            if rec:
                if name in have:
                    # FIELD-GENERIC merge-preserve: a degraded re-research (out-of-enum
                    # stage coerced to "", founded not re-found) must never regress a
                    # validated value to empty — for ANY field, not just employee counts.
                    # A fresh non-empty value always wins; only empties inherit.
                    old = have[name]
                    fresh_count = bool(rec.get("employees_global"))
                    for k, ov in old.items():
                        if ov in ("", None) or k == "as_of":
                            continue
                        if fresh_count and k in ("employees_lookup_miss", "employees_linkedin_miss",
                                                 "employees_source", "employees_as_of",
                                                 "employees_range", "size_band_pre_linkedin"):
                            continue  # companions describe the OLD count; a fresh count
                            # clears the gates and supersedes the old provenance
                        if rec.get(k) in ("", None):
                            rec[k] = ov
                    if rec.get("employees_global"):
                        # the one bypass left: an INHERITED count next to the fresh record's
                        # own band — re-derive so the band/count invariant holds everywhere
                        rec["size_band"] = band_for(rec["employees_global"])
                st.save_firmographics({name: rec}, today)  # main thread owns sqlite
                done += 1
                print(f"ok   {name}: {rec['sector']} / {rec.get('stage') or '?'} / {rec.get('size_band') or '?'}")
            else:
                failed += 1
                failed_names.append(name)
                print(f"FAIL {name} (strike pending)")
    # strikes are recorded only once the run proves it wasn't broken: neither an infra
    # abort nor an all-fail run (soft outage: exit-0 prose, broken WebSearch grant) is
    # evidence about company names
    if infra_streak >= 3:
        print(f"infra abort: {failed} soft failures NOT recorded")
    elif failed >= 5 and done == 0:
        print(f"mass-failure guard: {failed} failures, 0 successes — no strikes recorded "
              "(suspected soft outage; names retry next run)")
    else:
        for n in failed_names:
            st.record_firmo_failure(n, today)
    print(f"\n{done} researched, {failed} failed, {len(have) + done} total in store")
    # health heartbeat: stamped ONLY when the run PROVED the infrastructure works —
    # something was researched, or every attempt at least reached the model (zero infra
    # errors) and it wasn't an all-fail soft outage. A 1-2 name run where EVERY attempt
    # was an infra failure never trips the 3-streak abort, so gating the stamp on the
    # abort alone let a dead login stamp "trustworthy" forever.
    if done > 0 or (infra_errors == 0 and not (failed >= 5 and done == 0)):
        _stamp_ok()


if __name__ == "__main__":
    main()
