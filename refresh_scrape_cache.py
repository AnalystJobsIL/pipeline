#!/usr/bin/env python3
"""Re-scrape every active `scrape` row in companies.csv and rewrite scraped_cache.json.

Runs at 00:00 UTC (`scrape-refresh.yml`) so the 05:00 digest reads fresh scraped jobs
without doing slow Playwright work itself. The digest's `fetch_scrape` only READS the cache.

    python refresh_scrape_cache.py                      # the cron: every row, full write
    python refresh_scrape_cache.py --only "Wix,Fiverr"  # SCOPED: scrapes, prints, writes nothing
    python refresh_scrape_cache.py --only-missing --apply   # merge rows absent from the cache
    python refresh_scrape_cache.py --dry-run            # every row, writes nothing

Scoped runs (`--only`, `--limit`, `--only-missing`, `--shard`) never touch companies.csv,
scrape_rot.json or the stage stamp; `--apply` lets one MERGE its successes into the cache
(additive, never drops). Same convention as `python -m pipeline.run --only`.

Env: SCRAPE_WORKERS (default min(4, cpus)) · SCRAPE_REFRESH_TIME_BUDGET_MIN · SCRAPE_INFLIGHT_GRACE_S
     SCRAPE_CACHE_OUT · SCRAPE_ROT_OUT · plus scrape_universal's SCRAPE_* flags.

What one night records (ARCHITECTURE.md §5a): a company that answered with no Israel roles is
EMPTY (dropped from the cache, `empty` streak in scrape_rot.json, never parked); one whose page
could not be read is an ERROR (yesterday's jobs carried for at most CARRY_MAX_DAYS, `error`
streak, parked for re-hunt after ROT_PARK_DAYS). If errors exceed MASS_FAILURE_PCT of the rows
processed, the runner broke — not 100 sites at once — and the run is not a measurement: the
cache keeps every old entry, no streak advances, nothing is parked, and the `collect` stamp
carries `alarm=mass-failure…` so the morning email says so.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from dataclasses import dataclass, field

from pipeline import israel
from pipeline import stages
from pipeline.atomic import write_csv_rows, write_json
from pipeline.companies import load_companies
from pipeline.notes import append as _note_append, replace_own as _note_replace
from scrape_universal import COMPANY_BUDGET_S, scrape_result

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CSV_PATH = os.environ.get("SCRAPE_CSV_OUT", "companies.csv")
CACHE_PATH = os.environ.get("SCRAPE_CACHE_OUT", "scraped_cache.json")
ROT_PATH = os.environ.get("SCRAPE_ROT_OUT", "cloud_state/scrape_rot.json")
if os.environ.get("SCRAPE_STAGES_OUT"):        # a redirected local run must not stamp the tracked file
    stages.PATH = os.environ["SCRAPE_STAGES_OUT"]
# An ERROR means the page itself broke: carry yesterday's jobs, but never forever.
CARRY_MAX_DAYS = 14
# ...and give transient blocks room before the row is parked for re-hunt.
ROT_PARK_DAYS = 7
# An EMPTY page is NOT rot. Companies in this market routinely have no openings for a
# month or more; parking them on a 3-day empty streak retired healthy sources and meant
# the next role posted there was invisible until something re-found the company. Empty
# rows are NEVER parked. A very long streak only earns a re-VALIDATION by triage (which
# can tell "no roles" from "roles we can't extract"), and the row stays active and
# scanned daily the whole time.
EMPTY_REVALIDATE_DAYS = 45
# The night the runner (Chromium build, driver, DNS, egress) breaks looks like 100+ sites
# erroring at once. Real sites do not do that: the measured baseline is 0 errors in 428.
# Above this share the run is declared not a measurement. The floor keeps a `--limit 3`
# or a budget-starved night from tripping it on one failure in three.
MASS_FAILURE_PCT = 20
MASS_FAILURE_MIN_ROWS = 20
# a rescued read smaller than yesterday's is held back this many nights before it is believed
PARTIAL_MAX_NIGHTS = 2
# the mass-EMPTY guard needs far fewer rows to be meaningful than the mass-error one: it
# only counts companies that HAD jobs yesterday and were scraped tonight
SHRINK_MIN_ROWS = 5
DEFAULT_WORKERS = min(4, os.cpu_count() or 1)
TASKS_PER_WORKER = 25            # rows per worker process before it is recycled
STALL_S = 3 * COMPANY_BUDGET_S   # no result for this long = a worker is stuck, not slow


@dataclass
class RunState:
    cache: dict = field(default_factory=dict)
    successes: dict = field(default_factory=dict)
    parked: list = field(default_factory=list)
    revalidate: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: {"scraped": 0, "with_jobs": 0, "empty": 0,
                                                  "no_il": 0, "errors": 0, "carried": 0,
                                                  "unprocessed": 0})
    strategies: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# the scrape, in or out of process
# ---------------------------------------------------------------------------------------------
def _worker(task):
    """Runs in a pool process (or inline). Returns a plain dict — nothing but str/list/float
    crosses the pickle boundary. Must never raise: a raised worker loses its slot."""
    name, url = task
    t0 = time.time()
    try:
        res = scrape_result(name, url)
        return {"name": name, "jobs": res.jobs, "status": res.status, "error": res.error,
                "http_status": res.http_status, "strategy": res.strategy,
                "rescued": bool(getattr(res, "rescued", False)),
                "seconds": round(res.elapsed_s, 1)}
    except BaseException as e:  # noqa: BLE001
        return {"name": name, "jobs": [], "status": "error",
                "error": f"worker:{type(e).__name__}", "http_status": None, "strategy": "",
                "seconds": round(time.time() - t0, 1)}


def _scrape_all(rows, *, workers, budget_min=0, pool_cls=None, grace_s=600, worker=None,
                tasks_per_worker=TASKS_PER_WORKER, stall_s=STALL_S):
    """Yield one result dict per row until the time budget is spent. `workers <= 1` runs
    inline (the reference path); otherwise a process pool, one Playwright per process —
    two sync Playwrights in ONE interpreter collided silently and zeroed a hunt cycle.

    Workers are recycled by hand: a fresh executor per chunk of `workers * tasks_per_worker`
    rows, so a Chromium that ignored close() is reclaimed several times a night. (CPython's
    own `max_tasks_per_child` hung the 2026-08-24 rehearsal at exactly 4 × 25 rows.)

    A stuck worker is never waited for: when nothing completes for `stall_s` — longer than
    any company is allowed to take — the chunk's children are terminated, the rows still in
    flight are reported as `hang` errors, and the next chunk starts on a fresh pool. Without
    this one hung Chromium turned a finished night into a 330-minute killed job."""
    tasks = [(r["company_name"], r["api_url"]) for r in rows]
    worker = worker or _worker
    t0 = time.time()

    def over():
        return bool(budget_min) and (time.time() - t0) / 60 > budget_min

    if workers <= 1:
        for t in tasks:
            if over():
                return
            yield worker(t)
        return
    import concurrent.futures as cf
    import multiprocessing as mp
    kw = {}
    if pool_cls is None:
        pool_cls = cf.ProcessPoolExecutor
        # spawn on every platform (Linux defaults to fork): identical behaviour to the dev
        # box, and a fresh interpreter per child
        kw = dict(mp_context=mp.get_context("spawn"))
    chunk = max(1, workers * tasks_per_worker)
    for start in range(0, len(tasks), chunk):
        if over():
            return
        ex = pool_cls(max_workers=workers, **kw)
        try:
            futs = {ex.submit(worker, t): t[0] for t in tasks[start:start + chunk]}
            pending = set(futs)
            while pending:
                left = None if not budget_min else max(0.0, budget_min * 60 - (time.time() - t0))
                wait_s = stall_s if left is None else min(stall_s, left)
                done, pending = cf.wait(pending, timeout=wait_s, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    yield _result_of(f, futs[f])
                if not pending:
                    break
                if over():
                    # queued work is dropped (carried over as unprocessed); the few in flight
                    # get a bounded grace so their hour is not wasted
                    children = _children_of(ex)
                    _abandon(ex, wait_s=0)
                    running = {f for f in pending if f.running()}
                    done, _ = cf.wait(running, timeout=grace_s)
                    for f in done:
                        yield _result_of(f, futs[f])
                    _kill_children(children)
                    return
                if not done:
                    # nothing finished in stall_s: whatever is running is stuck (a Chromium
                    # that will not close). Give up on it, not on the night.
                    children = _children_of(ex)
                    _abandon(ex, wait_s=0)
                    _kill_children(children)
                    for f in pending:
                        if f.done() and not f.cancelled():
                            yield _result_of(f, futs[f])
                        elif not f.cancelled():
                            yield {"name": futs[f], "jobs": [], "status": "error",
                                   "error": f"hang:>{int(stall_s)}s", "http_status": None,
                                   "strategy": "", "rescued": False, "seconds": float(stall_s)}
                    break
        finally:
            children = _children_of(ex)
            _abandon(ex, wait_s=0)
            _kill_children(children)


def _abandon(ex, wait_s=0):
    """Stop feeding the executor; never block on it."""
    try:
        ex.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass


def _children_of(ex):
    """A process pool's live children — read BEFORE shutdown(), which clears the table."""
    procs = getattr(ex, "_processes", None) or {}
    return [p for p in list(procs.values()) if p is not None]


def _kill_children(children):
    """Terminate them (a thread pool has none). The executor's own shutdown waits for a hung
    child forever; we do not."""
    for proc in children:
        try:
            if proc.is_alive():
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def _result_of(fut, name):
    exc = fut.exception()
    if exc is None:
        return fut.result()
    return {"name": name, "jobs": [], "status": "error", "error": f"pool:{type(exc).__name__}",
            "http_status": None, "strategy": "", "seconds": 0.0}


# ---------------------------------------------------------------------------------------------
# per-company bookkeeping (pure: no I/O)
# ---------------------------------------------------------------------------------------------
def _carry_jd(new_jobs, old_jobs):
    """A rebuilt card with an empty description inherits the previous run's text (keyed by
    url/job_id) so daily refreshes stop wiping what enrich_scrape_jd fetched — and the
    `_jd_attempted` stamp travels regardless, or failed enrichments lose their 7-day
    cooldown every night and re-burn Bright Data calls on the same unfetchable URLs."""
    prev = {(j.get("url") or j.get("job_id") or ""): j
            for j in old_jobs if isinstance(j, dict)}
    for j in new_jobs:
        pj = prev.get(j.get("url") or j.get("job_id") or "")
        if not pj:
            continue
        if not (j.get("description") or "").strip() and (pj.get("description") or "").strip():
            j["description"] = pj["description"]
        if pj.get("_jd_attempted") and not j.get("_jd_attempted"):
            j["_jd_attempted"] = pj["_jd_attempted"]
    return new_jobs


def _rot_bump(rot, name, why, today, res=None):
    """Advance a company's streak. Returns (days since the streak began, nights observed).

    A streak is one kind of outcome: flipping empty→error starts a NEW streak (the first
    version kept `since`, so a company that had been honestly empty for 60 days would have
    been parked on its first transient error). Parking counts observed nights, not wall-clock
    days, so nights the budget skipped a row do not advance its clock."""
    e = rot.get(name)
    if e is None or e.get("why") != why:
        e = rot[name] = {"since": today, "why": why, "n": 0}
    if e.get("last") != today:
        e["n"] = int(e.get("n", 0)) + 1
    else:
        e["n"] = int(e.get("n", 1))          # an entry from before `n` existed, bumped today
    e["last"] = today
    if res is not None:                      # what actually happened, for the offline reader
        e["error"] = res.get("error") or ""
        e["found"] = len(res.get("jobs") or [])          # jobs seen before the Israel filter
        if res.get("http_status") is not None:
            e["http"] = res["http_status"]
    return (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(e["since"])).days, e["n"]


def _apply_result(row, res, old, rot, today, st: RunState):
    """Fold one company's result into the run: cache, rot streaks, park/flag lists."""
    name = row["company_name"]
    st.counts["scraped"] += 1
    jobs = None if res["status"] == "error" else res["jobs"]   # ERROR != confirmed-empty
    il = [j for j in (jobs or []) if israel.is_israel_job(j)]
    if (jobs is not None and res.get("rescued") and res.get("error") and name in old
            and len(il) < len(old[name])
            and not (rot.get(name, {}).get("why") == "error"
                     and str(rot[name].get("error", "")).startswith("partial:")
                     and int(rot[name].get("n", 0)) >= PARTIAL_MAX_NIGHTS)):
        # the browser failed mid-way (a goto timeout after the first XHR page landed) and the
        # jobs are what was captured before it did: a partial read. Yesterday's fuller list
        # stays and tonight is an error — for at most PARTIAL_MAX_NIGHTS, after which the
        # smaller list is the board's new truth (a board that genuinely shrank must converge;
        # the first version compared against the list it had carried itself and never did).
        res = {**res, "error": f"partial:{res['error']}"}
        jobs = None
    if jobs is None:
        st.counts["errors"] += 1
        st.errors.append(f"{name} ({res['error']})")
        days, nights = _rot_bump(rot, name, "error", today, res)
        if name in old and days < CARRY_MAX_DAYS:
            st.cache[name] = old[name]
            st.counts["carried"] += 1
        elif name in old:
            print(f"  {name}: carry expired after {CARRY_MAX_DAYS}d of errors — dropping "
                  f"stale jobs", flush=True)
        if nights >= ROT_PARK_DAYS:
            st.parked.append((name, f"error {days}d"))
        return
    if il:
        st.counts["with_jobs"] += 1
        st.strategies[res["strategy"]] = st.strategies.get(res["strategy"], 0) + 1
        st.cache[name] = st.successes[name] = _carry_jd(il, old.get(name, []))
        rot.pop(name, None)                                    # healthy again
    else:
        st.counts["empty"] += 1
        if jobs:
            st.counts["no_il"] += 1                            # found roles, none in Israel
        days, _ = _rot_bump(rot, name, "empty", today, res)
        # NEVER park on empty — see EMPTY_REVALIDATE_DAYS. A long streak asks triage to
        # read the page with an LLM; the row stays ACTIVE and scanned daily either way.
        if days >= EMPTY_REVALIDATE_DAYS:
            st.revalidate.append((name, days))


def _alarm(st: RunState, *, mass_failure=False, shrink=None):
    """Space-free tokens: `stages.summary()` renders k=v joined by spaces and stages by ` | `."""
    c, tokens = st.counts, []
    if mass_failure:
        tokens.append(f"mass-failure-errors-{100 * c['errors'] // max(1, c['scraped'])}%")
    elif c["scraped"] and c["errors"] * 100 > MASS_FAILURE_PCT * c["scraped"]:
        tokens.append(f"errors-{100 * c['errors'] // c['scraped']}%")
    if shrink:
        tokens.append(f"shrink-abort-{shrink[0]}-to-{shrink[1]}")
    if c["unprocessed"] * 20 > (c["scraped"] + c["unprocessed"]):     # more than 5% of rows
        tokens.append(f"unprocessed-{c['unprocessed']}")
    if c["scraped"] and not c["with_jobs"]:
        tokens.append("no-jobs")
    return "+".join(tokens)


# ---------------------------------------------------------------------------------------------
# registry writes (single-writer discipline: re-read immediately before each write)
# ---------------------------------------------------------------------------------------------
def _park(parked, today):
    """Park rotted rows so the listing-hunt pool re-finds/re-verifies them — active rows are
    structurally invisible to listing-hunt and the weekly audits; this is the handoff."""
    import csv
    fresh = list(csv.reader(open(CSV_PATH, encoding="utf-8")))
    names = dict(parked)
    for fr in fresh:
        if fr and len(fr) > 5 and fr[0] in names and fr[4] == "true":
            fr[4] = "false"
            fr[5] = _note_replace(
                fr[5], "scrape rotted",
                f"scrape rotted ({names[fr[0]]}) {today}: extraction yields 0 — "
                f"no ATS detected; parked for re-hunt")
    write_csv_rows(CSV_PATH, fresh)
    print(f"parked {len(parked)} rotted scrape rows for re-hunt: {[n for n, _ in parked][:8]}")


def _flag(revalidate, today):
    """Long-empty rows STAY ACTIVE; flagged once so triage re-reads the page with an LLM."""
    import csv
    fresh = list(csv.reader(open(CSV_PATH, encoding="utf-8")))
    ages = dict(revalidate)
    for fr in fresh:
        if fr and len(fr) > 5 and fr[0] in ages and "empty-but-suspect" not in (fr[5] or ""):
            fr[5] = _note_append(
                fr[5], f"empty-but-suspect {today}: {ages[fr[0]]}d with no roles "
                       f"— re-validate page")
    write_csv_rows(CSV_PATH, fresh)
    print(f"flagged {len(revalidate)} long-empty rows for re-validation (still active)")


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------
@dataclass
class Opts:
    only: set = field(default_factory=set)
    limit: int = 0
    only_missing: bool = False
    shard: tuple | None = None
    dry_run: bool = False
    apply: bool = False
    workers: int = DEFAULT_WORKERS

    @property
    def scoped(self):
        return bool(self.only or self.limit or self.only_missing or self.shard)


def _parse(argv):
    o = Opts(workers=int(os.environ.get("SCRAPE_WORKERS", DEFAULT_WORKERS)))
    it = iter(argv)
    for a in it:
        if a == "--only":
            o.only = {x.strip().lower() for x in next(it).split(",") if x.strip()}
        elif a == "--limit":
            o.limit = int(next(it))
        elif a == "--only-missing":
            o.only_missing = True
        elif a == "--shard":
            o.shard = (int(next(it)), int(next(it)))
        elif a == "--dry-run":
            o.dry_run = True
        elif a == "--apply":
            o.apply = True
        elif a == "--workers":
            o.workers = int(next(it))
        else:
            raise SystemExit(f"unknown argument {a!r} — see the module docstring")
    return o


def _select_rows(o: Opts, cache):
    rows = [r for r in load_companies(CSV_PATH, active_only=True)
            if r["ats_platform"].strip().lower() == "scrape"]
    if o.only:
        rows = [r for r in rows if r["company_name"].strip().lower() in o.only]
    if o.only_missing:
        rows = [r for r in rows if not cache.get(r["company_name"])]
    if o.shard:
        i, n = o.shard
        rows = rows[i::n]
    if o.limit:
        rows = rows[:o.limit]
    return rows


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def run(argv=None, *, pool_cls=None, worker=None):
    o = _parse(sys.argv[1:] if argv is None else argv)
    old = _load(CACHE_PATH)
    rot = _load(ROT_PATH)
    today = _dt.date.today().isoformat()
    rows = _select_rows(o, old)
    if not o.scoped and rows:
        # rotate the processing order by the day, so a night the budget cuts short does not
        # leave the same registry tail unprocessed (and carried) every night
        k = _dt.date.today().toordinal() % len(rows)
        rows = rows[k:] + rows[:k]
    budget = float(os.environ.get("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0"))
    grace = int(os.environ.get("SCRAPE_INFLIGHT_GRACE_S", "600"))
    st = RunState()
    print(f"refreshing {len(rows)} scrape rows with {o.workers} worker(s)"
          + (f", budget {budget:g} min" if budget else "")
          + (" [scoped: nothing is written]" if o.scoped and not o.apply else "")
          + (" [dry-run]" if o.dry_run else ""), flush=True)
    t0 = time.time()
    results = {}
    for res in _scrape_all(rows, workers=o.workers, budget_min=budget, pool_cls=pool_cls,
                           grace_s=grace, worker=worker):
        results[res["name"]] = res
        # progress in COMPLETION order, so the cloud log is readable while the pool runs;
        # the bookkeeping below is in registry order, so the output is deterministic
        what = (f"ERROR {res['error']}" if res["status"] == "error"
                else f"{len(res['jobs'])}" + (f" via {res['strategy']}" if res["jobs"] else ""))
        print(f"  [{len(results)}/{len(rows)}] {res['name']}: {what} ({res['seconds']:.0f}s)",
              flush=True)
    # bookkeeping in REGISTRY order, in the parent: the pool and the inline path produce
    # byte-identical output, only the progress lines differ
    for r in rows:
        res = results.get(r["company_name"])
        if res is None:
            st.counts["unprocessed"] += 1
            if r["company_name"] in old:              # carry the untouched over from last night
                st.cache[r["company_name"]] = old[r["company_name"]]
            continue
        _apply_result(r, res, old, rot, today, st)
    if st.counts["unprocessed"]:
        print(f"time budget {budget:g}min reached — carried over {st.counts['unprocessed']} "
              f"unprocessed companies", flush=True)
    c = st.counts
    minutes = int((time.time() - t0) / 60)
    mass_failure = (c["scraped"] >= MASS_FAILURE_MIN_ROWS
                    and c["errors"] * 100 > MASS_FAILURE_PCT * c["scraped"])
    # the mass-EMPTY guard, measured over what was actually processed: of the companies that
    # had jobs yesterday and were scraped tonight, did more than 20% come back with none?
    # (counting the whole rebuilt cache let carried-unprocessed entries mask a broken night)
    had = [n for n in results if n in old]
    lost = [n for n in had if n not in st.cache]
    shrink = ((len(had), len(had) - len(lost))
              if not o.scoped and len(had) >= SHRINK_MIN_ROWS and len(lost) * 5 > len(had)
              else None)
    alarm = _alarm(st, mass_failure=mass_failure, shrink=shrink)
    parks = 0 if (mass_failure or shrink) else len(st.parked)
    detail = dict(rows=len(rows), **c, parked=parks, workers=o.workers, minutes=minutes)
    if alarm:
        detail["alarm"] = alarm
    print(f"=== collect: " + " ".join(f"{k}={v}" for k, v in detail.items())
          + f" | strategies {st.strategies}" + (f"\n    errors: {st.errors[:12]}" if st.errors else ""),
          flush=True)

    if o.dry_run:
        print("dry-run: nothing written")
        return 0
    if o.scoped:
        if o.apply and st.successes:
            fresh = _load(CACHE_PATH)                # re-read: another writer may have added keys
            fresh.update(st.successes)
            write_json(CACHE_PATH, fresh, sort_keys=True)
            print(f"merged {len(st.successes)} companies into {CACHE_PATH}")
        else:
            print(f"scoped run: nothing written (use --apply to merge {len(st.successes)} "
                  f"companies with Israel roles into {CACHE_PATH})")
        return 0
    if mass_failure:
        # not a measurement: keep every old entry, advance no streak, park nothing
        cache = dict(old)
        cache.update(st.successes)
        write_json(CACHE_PATH, cache, sort_keys=True)
        stages.stamp("collect", **detail)
        print(f"MASS FAILURE: {c['errors']} of {c['scraped']} rows errored — cache kept "
              f"({len(cache)} companies), rot and registry untouched")
        return 0
    if shrink:
        stages.stamp("collect", **detail)
        print(f"ABORT: {shrink[0] - shrink[1]} of {shrink[0]} companies that had jobs came back "
              f"empty (>20%); keeping the old cache, rot and registry untouched")
        return 0
    write_json(CACHE_PATH, st.cache, sort_keys=True)
    if st.parked:
        _park(st.parked, today)      # the registry first: if this write fails, the streaks
    for name, _why in st.parked:     # that justified it are still on disk for tomorrow
        rot.pop(name, None)          # a re-activated row gets its ROT_PARK_DAYS of grace again
    write_json(ROT_PATH, rot)
    if st.revalidate:
        _flag(st.revalidate, today)
    stages.stamp("collect", **detail)
    print(f"=== refreshed {len(st.cache)} scrape companies -> {CACHE_PATH} ===")
    return 0


def main():
    rc = run()
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(rc)        # never let an atexit join on a stuck child outlive the written cache


if __name__ == "__main__":
    main()
