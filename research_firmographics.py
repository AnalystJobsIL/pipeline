"""Backfill structured firmographics for every company in companies.csv.

    python research_firmographics.py --dry-run          # who's missing / stale
    python research_firmographics.py --limit 25         # research a batch
    python research_firmographics.py                    # research all missing
    python research_firmographics.py --refresh-days 365 # also re-research stale records
    python research_firmographics.py --budget-min 60    # launch no new call after 60 min

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
import math
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

# the 6-hourly chain redirects stdout to a log file, which makes Python pick cp1252 on
# Windows — a Hebrew company name in a print then kills the whole run (UnicodeEncodeError)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline import firmographics as F
from pipeline import stages
from pipeline.companies import load_companies
from pipeline.firmographics import (ResearchUnavailable, band_for, identity_key,
                                    load_shared_status, not_a_company, research_company,
                                    save_shared, sync_store, union_store)
from pipeline.store import SeenStore

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.join(HERE, "poc_firmographics.json")
EXPORT = os.path.join(HERE, "state", "firmographics.json")
# The SHARED copy. `state/` is gitignored, so 919 researched profiles lived on one
# laptop and the cloud digest — which renders them — had an empty table and was
# re-researching from zero at 5/run. sqlite cannot be git-merged; a sorted JSON export
# can, so this is the artifact the two stores converge through (ARCHITECTURE §7 /
# HANDOFF §4d item 1, scoped to the one table that has a consumer).
SHARED_EXPORT = os.path.join(HERE, "cloud_state", "firmographics.json")
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


def _failure_union(st, cloud_db, today=""):
    """Every failure memory this machine can see, merged by `firmographics.merge_failures`.

    Three sources, and until 2026-08-28 only two of them, neither durable in the cloud:

    1. `st.load_firmo_failures()` — this machine's sqlite. On a RUNNER this is a brand-new
       empty file every run, because `store.DEFAULT_DB` is the gitignored `state/seen.db`.
    2. the committed `cloud_state/seen.db`, written only by the daily digest.
    3. `cloud_state/firmo_failed.json` — the committed ledger THIS script writes, and the
       only path by which a strike recorded in the cloud survives its own runner.

    Merging is `merge_failures`: `attempts` and `last` taken independently, so an older
    source's higher count is never thrown away with its date. The hand-rolled merge this
    replaced kept `max(attempts)` INSIDE `if last > have[1]`, so ("Chalk", 3, "2026-08-20")
    beside a fresh single strike collapsed to (1, "2026-08-27") — resetting 3 -> 1, the
    exact reset it promised to prevent.
    """
    sources = [F.load_failures(today)[0], st.load_firmo_failures()]
    rows = {}
    if cloud_db and os.path.exists(cloud_db):
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{cloud_db}?mode=ro", uri=True)
            rows = {c: (a, l) for c, a, l in
                    con.execute("SELECT company, attempts, last FROM firmo_failed")}
            con.close()
        except Exception as e:  # noqa: BLE001 — a missing table is not an error worth a run
            print(f"  (other store's failure memory unreadable: {e!r})", flush=True)
    out = F.merge_failures(*sources, rows)
    added = len(out) - len(sources[1])
    if added > 0:
        print(f"failure memory: +{added} name(s) struck elsewhere "
              f"(ledger + committed store)", flush=True)
    return out


def _stamp_ok():
    """Write the health heartbeat firmo_health_check.py watches."""
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)  # gitignored: absent on a fresh clone
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


def plan_counts(n_new, n_refresh, limit):
    """(attempted, refreshes_deferred) for a run with `limit`.

    Refresh names are appended LAST and `--limit` truncates from the end, so whenever the
    new-name backlog alone exceeds the limit, refresh gets ZERO slots. The ordering is
    right -- a company with no facts renders a card with no chips, which is worse than one
    whose chips are six months old -- but it was silent, and it bites exactly when the
    registry is growing fast, which is when a reader would most want to know."""
    total = n_new + n_refresh
    attempted = min(total, limit) if limit else total
    return attempted, min(max(0, total - attempted), n_refresh)


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
    ap.add_argument("--export", action="store_true", help="write the union to cloud_state/firmographics.json and exit")
    # A wall-clock bound beside the count bound (2026-08-30). `--limit` is a proxy for the
    # thing the 120-minute job actually runs out of, and a proxy misses in both directions:
    # 08-28 added 155 active rows in one day against a cap of 150, and a queue of 40 that
    # times out per call costs 40 x 240 s regardless of the cap. Names are LAUNCHED only
    # while the budget lasts; a call already in flight finishes and is saved. Everything
    # left is counted in the stamp as `left`, which is what makes a late or truncated run
    # legible the next morning instead of a green step.
    ap.add_argument("--budget-min", type=float, default=0.0,
                    help="stop launching new research calls after this many minutes (0 = no bound)")
    a = ap.parse_args()
    if a.limit is not None and a.limit < 0:
        # argparse accepts `--limit -5`, and the workflow_dispatch input is free text.
        # `todo[:-5]` then attempts 152 of 157 names while the run announces "-5 to do".
        ap.error("--limit must be >= 0 (0 means unbounded)")
    if not (a.budget_min >= 0) or math.isinf(a.budget_min):
        # `nan < 0` is False, so a plain sign check let `--budget-min nan` through: it
        # launched nothing, stamped `budget_min: NaN` into a committed JSON file (not JSON),
        # and wrote the health heartbeat (wave-1)
        ap.error("--budget-min must be a finite number >= 0 (0 means no bound)")
    t0 = time.time()        # the RUN's clock, from here: `minutes` in the stamp is wall time

    st = SeenStore()
    today = dt.date.today().isoformat()

    if a.export:
        # the UNION, atomically — the local table alone overwrote the file and deleted
        # every record the cloud digest had researched since (19 at risk on 2026-08-24).
        #
        # Read the STATUS, not just the records. `union_store(st)` calls `load_shared()`,
        # which drops `load_shared_status`'s verdict — so over a corrupt or half-written
        # export the union was the sqlite table ALONE, and this line published it over the
        # file with an encouraging `exported N records`. That is the one thing
        # `load_shared_status`'s own docstring says must never happen ("a corrupt one must
        # never be silently REPLACED by the smaller sqlite table"), and the digest hook is
        # the only caller that was honouring it (`company_intel.py`, `export_status`).
        shared, status = load_shared_status()
        if status in ("corrupt", "partial"):
            print(f"::error::company-intel cloud_state/firmographics.json is {status.upper()} "
                  "— refusing to publish over it, because what we could read is the SMALLER "
                  "side and this write would delete every record we could not read. Restore "
                  "the file (git checkout) and re-run --export.")
            return 1
        recs = union_store(st, shared)
        # The union is a superset by construction (`merge` is field-level and drops no key).
        # Asserted anyway, because this file has lost records twice — 19 at risk on
        # 2026-08-24 and 22 destroyed on 2026-08-26 — and both times the write looked fine.
        lost = sorted(set(shared) - set(recs))
        if lost:
            print("::error::company-intel refusing to publish: the union DROPS %d record(s) "
                  "the export already holds (%s%s)"
                  % (len(lost), ", ".join(lost[:5]), " ..." if len(lost) > 5 else ""))
            return 1
        os.makedirs(os.path.dirname(EXPORT), exist_ok=True)
        with open(EXPORT, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=2, sort_keys=True)
        if not save_shared(recs):
            print("::error::company-intel the export was NOT written (nothing to write)")
            return 1
        print(f"exported {len(recs)} records ({len(recs) - len(shared):+d}) "
              f"-> {EXPORT} + {SHARED_EXPORT}")
        return

    seeded = seed_poc(st, today)
    if seeded:
        print(f"seeded {seeded} POC records")

    # sqlite ∪ the committed export: a company the cloud digest researched this morning
    # must not be bought again here (Phoenix Financial and SHILA were, on 2026-08-24)
    synced = sync_store(st, today)
    if synced:
        print(f"synced {synced} records from the shared export into the local store")
    have = union_store(st)
    names = [r["company_name"] for r in load_companies()]
    # also cover companies that appear on the actual board (CI's matched table) but are
    # not in companies.csv — CI's discovery layer surfaces jobs from employers we never
    # explicitly listed, and those jobs deserve a profile too
    cloud_db = fetch_cloud_db() or os.path.join(HERE, "cloud_state", "seen.db")
    if os.path.exists(cloud_db):
        import sqlite3
        con = sqlite3.connect(cloud_db)
        # BACKLOG 141: `SELECT DISTINCT company` includes superseded-only rows (OTORIO,
        # Meta Israel, Port.io) that `run.py`'s all_companies excludes, so the bulk pass
        # bought facts for names the board can never render.
        board = [r[0] for r in con.execute(
            "SELECT DISTINCT company FROM matched WHERE COALESCE(status,'') != 'superseded'")]
        con.close()
        names += [n for n in board if n not in names]
    # leaked job titles ("Sql developer - X", "my team") are never companies: skip for
    # free, forever — researching them profiles the embedded company under a junk key
    # not_a_company, not looks_like_junk: this is the 10:00 UTC cron that owns the
    # registry backlog, and it reads from `matched`, the same table that held
    # `Tel Aviv`. looks_like_junk deliberately excludes the place arm (it is shared
    # with the registry's pools); this spender needs it (wave-1).
    # the discovery pseudo-row is not an employer and can never be profiled -- exclude it
    # by PLATFORM, the same rule the mail's registry-backlog gauge uses. A name rule would be
    # wrong: `Discovery Inc` is a real company.
    pseudo = {r["company_name"] for r in load_companies(active_only=False)
              if str(r.get("ats_platform") or "").strip().lower() == "discovery"}
    if pseudo:
        names = [n for n in names if n not in pseudo]
    junk = [n for n in names if not_a_company(n)]
    if junk:
        print(f"skipping {len(junk)} junk (job-title) names: {', '.join(junk[:5])}"
              + (" ..." if len(junk) > 5 else ""))
        names = [n for n in names if n not in set(junk)]
    # failure gates FIRST — gated names must not win refresh-cap slots they then vacate
    # (that starved real refreshes), and permanently failing refreshes (4+ strikes ~ a
    # month of weekly retries) are evicted from the refresh layer entirely so squatters
    # can never consume the whole cap once the store ages
    failures = _failure_union(st, cloud_db, today)
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
        print(f"refreshing {len(refresh)} stale records (cap {REFRESH_CAP}/run)", flush=True)
    seen_norms.update(identity_key(n) for n in refresh)
    # Refresh goes LAST and `--limit` truncates from the end, so whenever the new-name
    # backlog alone exceeds the limit, refresh gets ZERO slots. That ordering is right --
    # a company with no facts renders a card with no chips, which is worse than a company
    # whose chips are six months old -- but it was SILENT, and it bites exactly when the
    # registry is growing fast, which is when a reader would most want to know. Say it.
    attempt, deferred = plan_counts(len(todo), len(refresh), a.limit)
    todo.extend(refresh)
    # the count a reader can reconcile against the `ok`/`FAIL` lines below: this printed the
    # PRE-limit number, so a `--limit 40` run announced "137 to do" and attempted 40.
    print(f"{len(names)} active companies, {len(have)} researched, {attempt} to do"
          + (f" of {len(todo)}" if attempt != len(todo) else "")
          + (f" ({len(gated)} recent-failure names gated to weekly retry)" if gated else "")
          + (f" [refresh deferred: {deferred} stale record(s) had no slot under "
             f"--limit {a.limit}]" if deferred else ""), flush=True)
    if a.dry_run or not todo:
        for n in todo:
            print("  -", n)
        if not a.dry_run:
            _stamp_ok()  # a clean zero-todo run IS healthy: the chain ran and nothing is
            # stuck — without this, a quiet weekend fires false Desktop alerts that
            # train the user to ignore the one channel real outages depend on
            # ...and the SAME argument applies to the cloud stamp, which was added below
            # the early return and so was never written on exactly those healthy runs.
            # Live: after the 08-28 drain every remaining backlog name is strike-gated, so
            # the 08-29 cron does its job, returns here, and the 08-30 mail would have said
            # `firmo never ran`. That is the false alarm this lane rejected two commits
            # earlier, rebuilt in the replacement for it.
            # ...and in the SAME shape as the main stamp, or a drained queue reads as the
            # dead-cron shape the numbers were added to tell apart. An empty NAME list
            # against a non-empty store is not a drained queue, it is a registry that read
            # as nothing (CLAUDE.md rule 2) -- and it used to stamp as a healthy night.
            # `not names` alone: companies.csv always has rows, and requiring a non-empty
            # store as well disarmed this on the double mass-zero -- registry AND export
            # both unreadable -- which is the worst morning, not the exempt one (wave-2)
            _empty = ({"alarm": f"empty-registry(0 names read, {len(have)} records held)"}
                      if not names else {})
            stages.stamp("firmo", researched=0, failed=0, records=len(have),
                         todo=0, attempted=0, left=0, gated=len(gated), names=len(names),
                         minutes=round((time.time() - t0) / 60, 1), **_empty)
        return
    queued = len(todo)          # the whole queue this run set out to clear, BEFORE any cap
    if a.limit:
        todo = todo[: a.limit]

    # The seam's own audit. Without it this job spends the subscription
    # invisibly: the digest hook reports `N calls, Ns, N searches[, N
    # SEARCHLESS]` and warns on a searchless answer, and this job -- now the
    # MAIN spender since the bulk moved to the 10:00 cron -- said nothing at
    # all. A searchless answer is a parametric guess, and nothing
    # re-researches before 2027-02 at --refresh-days 180.
    meta = {}
    done = failed = 0
    done_names = set()
    infra_streak = infra_errors = 0
    failed_names = []
    launch_t0 = time.time()
    deadline = launch_t0 + a.budget_min * 60 if a.budget_min else None
    pending, queue, attempted, aborted = {}, list(todo), 0, False

    def _record(rec, name):
        """One finished call -> the store, the counters, one `ok`/`FAIL` line."""
        nonlocal done, failed
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
            done_names.add(name)
            print(f"ok   {name}: {rec['sector']} / {rec.get('stage') or '?'} / {rec.get('size_band') or '?'}", flush=True)
        else:
            failed += 1
            failed_names.append(name)
            print(f"FAIL {name} (strike pending)", flush=True)

    def _stamp_kwargs():
        return dict(researched=done, failed=failed, records=len(have) + done, todo=queued,
                    attempted=attempted, left=queued - attempted, unavailable=infra_errors,
                    gated=len(gated), minutes=round((time.time() - t0) / 60, 1),
                    budget_min=a.budget_min)

    try:
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            # LAZY submission: the old `{ex.submit(...) for name in todo}` handed the whole
            # queue to the pool at once, so a budget could only be enforced by cancelling
            # futures, and `--limit` was the only thing standing between a 155-name night and
            # the job's own 120-minute timeout. Keep `workers` calls in flight, launch the next
            # only while the clock allows, and let whatever is in flight finish and save.
            def _launch():
                nonlocal attempted
                while queue and not aborted and len(pending) < max(1, a.workers) \
                        and (deadline is None or time.time() < deadline):
                    name = queue.pop(0)
                    pending[ex.submit(research_company, name, "", 240, meta)] = name
                    attempted += 1
            _launch()
            while pending:
                ready, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for fut in ready:
                    name = pending.pop(fut)
                    try:
                        rec = fut.result()
                    except ResearchUnavailable as e:
                        # infrastructure outage (CLI logged out, network): NOT the name's
                        # fault -- no firmo_failed stamp, and 3 in a row means everything
                        # else will fail too, so launch nothing more. What is IN FLIGHT is
                        # still collected: `shutdown(cancel_futures=True)` here waited for
                        # those calls anyway and then threw their paid answers away (wave-1).
                        infra_streak += 1
                        infra_errors += 1
                        print(f"UNAVAILABLE {name}: {e} (no failure recorded)", flush=True)
                        if infra_streak >= 3 and not aborted:
                            print("3 consecutive infrastructure errors -- no more launches; "
                                  "calls already in flight are kept", flush=True)
                            aborted = True
                        continue
                    # sticky past the abort line: a late success must not un-abort the
                    # run's verdict about its own infrastructure
                    infra_streak = 0 if infra_streak < 3 else infra_streak
                    _record(rec, name)
                _launch()
    except KeyboardInterrupt:
        raise                   # an operator stopping the run is not a crash (wave-2): the
                                # docstring promises "safe to Ctrl-C", and a stamp here would
                                # put `crashed(KeyboardInterrupt)` into a TRACKED file
    except BaseException as e:  # noqa: BLE001 -- the stamp is the only trace a crash leaves
        # A crash between the first launch and the stamp used to leave YESTERDAY's stamp in
        # place, and `stages.alarms("firmo", 2)` reads a one-day-old stamp as healthy: the
        # 120-minute job timeout, an OOM, a locked sqlite in `_record` -- each silent for
        # three mornings. Stamp what was done with the crash named, then re-raise.
        stages.stamp("firmo", alarm=f"crashed({type(e).__name__})", **_stamp_kwargs())
        raise
    left = queued - attempted
    minutes = (time.time() - t0) / 60
    # strikes are recorded only once the run proves it wasn't broken: neither an infra
    # abort nor an all-fail run (soft outage: exit-0 prose, broken WebSearch grant) is
    # evidence about company names
    struck, mass_failure = [], False
    if infra_streak >= 3:
        print(f"infra abort: {failed} soft failures NOT recorded")
    elif done == 0 and attempted < queued and failed:
        # the budget (or the cap) stopped the run BELOW the mass-failure guard: four refusals
        # out of a 40-name soft outage are not four bad names, they are the first four of
        # forty. This is the objection the 08-28 record raised against `--budget-min` and
        # the lazy pool answered only half of (wave-1). No strikes, names retry next run.
        print(f"truncated run produced nothing: {failed} failure(s) NOT recorded "
              f"({attempted} of {queued} attempted -- below the mass-failure guard by construction)")
    elif failed >= 5 and done == 0:
        mass_failure = True
        print(f"mass-failure guard: {failed} failures, 0 successes — no strikes recorded "
              "(suspected soft outage; names retry next run)")
    else:
        struck = list(failed_names)
        for n in struck:
            st.record_firmo_failure(n, today)
    # Publish the strike memory, or this run's gating knowledge dies with the runner.
    # RE-READ the store: `failures` above is the PRE-RUN union, so serialising it would
    # have written a ledger without the very names this run just struck -- the 2026-08-27
    # run's Sivo / ImagineArt / Chalk / Instacart, missing all over again.
    # `done_names` are cleared: a company that has just been researched is not a name we
    # failed on, and absence is the only way this ledger can express that (the merge on
    # the conflict path is base-aware, so a deliberate drop is honoured and a concurrent
    # ADD by another writer is kept).
    ledger = F.merge_failures(failures, st.load_firmo_failures())
    # The COUNT has to be incremented against the merged prior, not against sqlite. On a
    # runner `record_firmo_failure` writes 1 into a brand-new empty table every time, and
    # `merge_failures` takes `max(ledger_n, 1)` -- so attempts stayed pinned at 1 for ever
    # while the date advanced, and `refresh_abandoned` (4+) still could not fire in the
    # cloud. Persisting the strike is only half the fix; this is the other half.
    for n in struck:
        ledger[n] = (F.strike_attempts(failures.get(n, (0, ""))[0]) + 1, today)
    written, status = F.save_failures(ledger, cleared=done_names)
    if written:
        print(f"strike ledger: {len(set(ledger) - done_names)} name(s) -> "
              f"cloud_state/firmo_failed.json ({len(struck)} struck, "
              f"{len(done_names & set(ledger))} cleared)", flush=True)
    else:
        print(f"::warning::company-intel strike ledger NOT written "
              f"(cloud_state/firmo_failed.json is {status}) — {len(struck)} strike(s) from "
              f"this run will not survive their runner", flush=True)
    # Stamp the shared stage file. This is the ONLY thing that measures "the 10:00 cron
    # ran", and it has to be a stamp rather than a property of the export: the digest hook
    # researches board companies too and stamps them with today's date, so the export's
    # newest record moves on most mornings whether or not this job ever fired. Measured --
    # on 2026-08-28, the day this cron did NOT run, the 08:54 digest added two records
    # dated 08-28 and carried `export_newest` from 08-27 to 08-28, so an alarm reading that
    # field would have been silent on the exact morning it was built for.
    _alarm = ("infra-abort" if infra_streak >= 3 else
              "mass-failure" if mass_failure else "")
    # A queue that was NOT empty and a run that produced NOTHING, for a reason neither guard
    # above has a name for: a budget of zero, a cap that let nothing through, one or two
    # unavailable calls below the abort line. Without this the stamp read exactly like a
    # healthy zero-todo night (2026-08-30) -- the shape jd-text's enricher wore for four
    # green nights. Wave 1 carved out "a handful of junk names all refused with every call
    # answered" as routine; wave 2 showed that carve-out is exactly the soft-outage shape on
    # the steady-state queue (strike-gated names never reach `todo`, so a 1-4 name queue is
    # NEW rows, and 4 of 4 refused is an outage that also strikes 4 real names). Every
    # all-fail night alarms; the text says "N failed", and a reader can tell one leftover
    # junk name from a dead morning by the number.
    if not _alarm and done == 0:
        _alarm = (f"zero-produce({queued} to do, 0 researched, {failed} failed, "
                  f"{infra_errors} unavailable, {left} unattempted)")
    # `todo` is what the run set out to clear before any cap, `attempted` what it launched,
    # `left` what it did not reach. The three are what the next morning's digest reads to
    # tell "the cron drained the queue" from "the cron ran and left 99 behind" (08-28) --
    # a run that starts twelve hours late, or not at all, has to be legible by its stamp.
    stages.stamp("firmo", researched=done, failed=failed, records=len(have) + done,
                 todo=queued, attempted=attempted, left=left, unavailable=infra_errors,
                 gated=len(gated), minutes=round(minutes, 1), budget_min=a.budget_min,
                 **({"alarm": _alarm} if _alarm else {}))
    print(f"\n{done} researched, {failed} failed, {len(have) + done} total in store; "
          f"{queued} to do, {attempted} attempted, {left} left ({minutes:.1f} min"
          + (f" of a {a.budget_min:g}-min budget" if a.budget_min else "") + ")")
    if meta.get("calls"):
        models = ", ".join(
            "%s%s" % (m, "" if n == 1 else " x%d" % n)
            for m, n in sorted(meta.get("models", {}).items(), key=lambda kv: -kv[1]))
        extra = ""
        if meta.get("searchless"):
            extra = ", %d SEARCHLESS" % meta["searchless"]
        print("seam: %s | %d calls, %.0fs, %d searches%s" % (
            models, meta["calls"], meta.get("seconds", 0), meta.get("searches", 0), extra))
    if meta.get("searchless"):
        print("::warning::company-intel %d research answer(s) made no web search - "
              "those records are guesses, not researched facts" % meta["searchless"])
    # health heartbeat: stamped ONLY when the run PROVED the infrastructure works —
    # something was researched, or every attempt at least reached the model (zero infra
    # errors) and it wasn't an all-fail soft outage. A 1-2 name run where EVERY attempt
    # was an infra failure never trips the 3-streak abort, so gating the stamp on the
    # abort alone let a dead login stamp "trustworthy" forever.
    # ...and zero attempts is not "every attempt reached the model": a budget already spent
    # at the first launch check wrote the heartbeat with nothing proven (wave-1).
    # ...nor is a truncated all-fail run: the no-strike branch above sits ahead of the
    # mass-failure guard, so `mass_failure` stays False there and the old predicate wrote
    # "proved good" over an 8-name night that failed 6 of 6 under a cap (wave-2)
    if done > 0 or (attempted > 0 and infra_errors == 0 and failed < 5 and attempted == queued):
        _stamp_ok()


if __name__ == "__main__":
    # `main` returns a non-zero code when it REFUSES to publish (a corrupt export, a union
    # that would drop records). Without this the refusal printed an `::error::` and the
    # workflow step still exited 0 — CLAUDE.md rule 1, from the inside.
    sys.exit(main() or 0)
