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
streak, parked for re-hunt after ROT_PARK_DAYS). Two error shapes are treated differently
(2026-08-26): an IP-SHAPED code (`links:*`, `block:*`, `http:403`, `http:429`) says the runner's
address was refused, not that the page is gone — such a row is never parked (the hunt runs on the
same address and would re-activate it into a loop), and a `links:` code — the listing is alive and
lists positions we could not open — carries yesterday's jobs without expiry, never discarding them.
If errors exceed MASS_FAILURE_PCT of the rows processed, the runner broke — not 100 sites at once —
and the run is not a measurement: the cache keeps every old entry, no streak advances, nothing is
parked, and the `collect` stamp carries `alarm=mass-failure…` so the morning email says so.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
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
# ...and a read that knew NO posting's address is held back only when it also collapsed to
# under this fraction of yesterday. A board really can shrink; what it does not do is shrink
# by two thirds on the one night we could not address a single role (Quantum Machines, 18 -> 4).
WEAK_SHRINK_RATIO = 3
# an address refused this many nights running is nobody's to repair automatically: it is
# never parked (a hunt runs on the same address), so it is named for a human instead (216)
STALE_IP_NIGHTS = 30
# how long the cloud keeps a board only a home address could read, and how early it asks for
# a fresh one. A fortnight is one local pass; after that the roles are too old to publish.
RESIDENTIAL_MAX_DAYS = 14
RESIDENTIAL_WARN_DAYS = 3
# strategy 5 asks once per company that reaches it; more calls than this means the signal
# gate broke open, not that the fleet changed (438 rows, 128 calls on 2026-08-26)
LLM_RUNAWAY_CALLS = 250
# the mass-EMPTY guard needs far fewer rows to be meaningful than the mass-error one: it
# only counts companies that HAD jobs yesterday and were scraped tonight
SHRINK_MIN_ROWS = 5
DEFAULT_WORKERS = min(4, os.cpu_count() or 1)
TASKS_PER_WORKER = 25            # rows per worker process before it is recycled
STALL_S = 3 * COMPANY_BUDGET_S   # no result for this long = a worker is stuck, not slow
# One error code on at least this share of the rows is an event with a name (a WAF on the
# runner's address, a dead CDN) — below the mass-failure bar, above what a normal night shows
# (the 17-of-440 event of 2026-08-25 is 3.9 %; wave-1 attacker B measured 5 % missing it).
CODE_ALARM_PCT = 3


def _today():
    """The one clock for the streak date and the day-rotation. Two `date.today()` calls used
    to straddle midnight (the cron starts AT 00:00 UTC); the tests pin this name."""
    return _dt.date.today()


def _rotate(rows, day):
    """Rotate the processing order by the day, so a night the budget cuts short does not leave
    the same registry tail unprocessed (and carried) every night. Pure; asserted directly."""
    if not rows:
        return rows
    k = day.toordinal() % len(rows)
    return rows[k:] + rows[:k]


def _code(res):
    """The error code without a `partial:` wrapper — the shape decides parking and carrying."""
    return str(res.get("error") or "").removeprefix("partial:")


def _ip_shaped(code):
    """The runner's ADDRESS was refused, not the page: a wall, a 403/429, or a listing whose
    position pages could not be opened. The listing-hunt runs on the same address, so parking
    such a row only re-finds the same URL and re-parks it a week later (design critic, 2026-08-25)."""
    return code.startswith(("links:", "block:")) or code in ("http:403", "http:429")


def _runner_shaped(code):
    """Our own process broke, not the site: a stuck Chromium, a dead pool, a missing driver,
    a company budget that ran out mid-crawl (`deadline:` — the board is slow, not gone)."""
    return code.startswith(("hang:", "worker:", "pool:", "internal:", "launch:", "deadline:"))


def _shape(code):
    """The KIND of error, which is what a streak is made of: `links` (positions unreadable),
    `ip` (the address refused), `weak` (a reading that knew no posting's address), `runner`
    (our process), `page` (the page itself). Wave-1
    attacker B: with the streak keyed on the word "error" alone, twenty carried `links:`
    nights funded both the carry expiry and the park clock, and one page-shaped night from
    the same cloaking WAF (a 404) dropped the jobs AND parked the row with no alarm."""
    if code.startswith("links:"):
        return "links"
    if _ip_shaped(code):
        return "ip"
    if code.startswith("weak:"):
        return "weak"
    if _runner_shaped(code):
        return "runner"
    return "page"


def _parkable(code):
    """Only a PAGE-shaped code (404/410/5xx, navigation failure, a blank render) may park a
    row. A `weak:` read is about OUR reading of a live page, never about the company."""
    return bool(code) and _shape(code) == "page"


@dataclass
class RunState:
    cache: dict = field(default_factory=dict)
    successes: dict = field(default_factory=dict)
    parked: list = field(default_factory=list)
    revalidate: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: {"scraped": 0, "with_jobs": 0, "empty": 0,
                                                  "no_il": 0, "errors": 0, "carried": 0,
                                                  "unprocessed": 0, "links_unread": 0,
                                                  "carried_residential": 0})
    spend: dict = field(default_factory=lambda: {"llm_calls": 0, "llm_won": 0, "llm_fail": 0,
                                                 "llm_skipped": 0, "unlock_calls": 0,
                                                 "unlock_ok": 0, "unlock_won": 0})
    strategies: dict = field(default_factory=dict)
    codes: dict = field(default_factory=dict)      # error code -> count, for the per-code alarm
    llm_errors: dict = field(default_factory=dict) # LLMUnavailable kind -> count (auth/transient/...)
    errors: list = field(default_factory=list)
    unread: list = field(default_factory=list)     # companies whose positions could not be opened
    stale_ip: list = field(default_factory=list)   # (name, nights) refused for STALE_IP_NIGHTS+
    residential_due: list = field(default_factory=list)  # (name, nights left) to re-read here


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
                "weak_read": bool(getattr(res, "weak_read", False)),
                "llm_calls": int(getattr(res, "llm_calls", 0) or 0),
                "llm_error": str(getattr(res, "llm_error", "") or ""),
                "llm_skipped": int(getattr(res, "llm_skipped", 0) or 0),
                "unlock_calls": int(getattr(res, "unlock_calls", 0) or 0),
                "unlock_ok": int(getattr(res, "unlock_ok", 0) or 0),
                "seconds": round(res.elapsed_s, 1)}
    except BaseException as e:  # noqa: BLE001
        return {"name": name, "jobs": [], "status": "error",
                "error": f"worker:{type(e).__name__}", "http_status": None, "strategy": "",
                "llm_calls": 0, "llm_error": "", "llm_skipped": 0,
                "unlock_calls": 0, "unlock_ok": 0,
                "seconds": round(time.time() - t0, 1)}


def _scrape_all(rows, *, workers, budget_min=0, pool_cls=None, grace_s=600, worker=None,
                tasks_per_worker=TASKS_PER_WORKER, stall_s=STALL_S, clock=time.time):
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
    t0 = clock()

    def over():
        return bool(budget_min) and (clock() - t0) / 60 > budget_min

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
                left = None if not budget_min else max(0.0, budget_min * 60 - (clock() - t0))
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
                    late, pending = cf.wait(pending, timeout=0)     # landed during the stall
                    for f in late:
                        yield _result_of(f, futs[f])
                    for f in pending:
                        if not f.cancelled():
                            yield {"name": futs[f], "jobs": [], "status": "error",
                                   "error": f"hang:>{int(stall_s)}s", "http_status": None,
                                   "strategy": "", "rescued": False, "llm_calls": 0,
                                   "llm_error": "", "unlock_calls": 0, "unlock_ok": 0,
                                   "seconds": float(stall_s)}
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
            "http_status": None, "strategy": "", "llm_calls": 0, "llm_error": "",
            "unlock_calls": 0, "unlock_ok": 0, "seconds": 0.0}


# ---------------------------------------------------------------------------------------------
# per-company bookkeeping (pure: no I/O)
# ---------------------------------------------------------------------------------------------
def _jd_identities(j):
    """Every name last night's card can be recognised by tonight: its address, its id, and
    its (title, place). The last one matters because an address can CHANGE while the posting
    does not — that is exactly what a promotion does (a url-less reading given its own
    address by a later strategy), and without it the first night of promotions would drop the
    fetched description of up to 345 cards and re-buy them from Bright Data (wave-0 critic)."""
    return [x for x in (j.get("url") or "", j.get("job_id") or "") if x] + [
        "T:%s|%s" % ((j.get("title") or "").strip().lower(), (j.get("location") or "").strip().lower())]


def _carry_jd(new_jobs, old_jobs):
    """A rebuilt card with an empty description inherits the previous run's text (keyed by
    url/job_id/title) so daily refreshes stop wiping what enrich_scrape_jd fetched — and the
    `_jd_attempted` stamp travels regardless, or failed enrichments lose their 7-day
    cooldown every night and re-burn Bright Data calls on the same unfetchable URLs."""
    prev = {}
    for j in old_jobs:
        if isinstance(j, dict):
            for k in _jd_identities(j):
                prev.setdefault(k, j)
    for j in new_jobs:
        pj = next((prev[k] for k in _jd_identities(j) if k in prev), None)
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
    shape = _shape(_code(res or {})) if why == "error" else ""
    e = rot.get(name)
    # how long the runner's ADDRESS has been refused, across every shape that means it. The
    # streak `n` is per shape by design, and a WAF that answers 403 on the listing one night
    # and refuses the position pages the next flips between `ip` and `links` — restarting the
    # streak each time, so a per-row age alarm keyed on `n` could never fire (wave-0 critic).
    ip_since = (e or {}).get("ip_since") if shape in ("ip", "links") else None
    if e is None or e.get("why") != why or (shape and e.get("shape") not in (None, shape)):
        e = rot[name] = {"since": today, "why": why, "n": 0}
    if shape:
        e["shape"] = shape                   # an entry from before shapes existed adopts tonight's
    if shape in ("ip", "links"):
        e["ip_since"] = ip_since or e.get("ip_since") or today
    else:
        e.pop("ip_since", None)
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


def _mark_residential(jobs, today):
    """Stamp each card with where and when it was read. Rides on the job dict beside
    `_jd_attempted`, so nothing downstream needs to know about it."""
    for j in jobs:
        j["_via"], j["_read"] = "residential", today
    return jobs


def _residential_age(jobs, today):
    """Nights since these cards were read from a home address, or None when they were not.
    Every card must carry the mark: one cloud-read card means the cloud can read the board."""
    if not jobs or not all(isinstance(j, dict) and j.get("_via") == "residential" for j in jobs):
        return None
    read = min(str(j.get("_read") or "") for j in jobs)
    try:
        return (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(read)).days
    except ValueError:
        return None


def _ip_age(entry, today):
    """Nights this row's ADDRESS has been refused, counting across every shape that means it
    (`ip_since`, which a 403 -> links flip does not restart). 0 when it is not refused."""
    since = (entry or {}).get("ip_since")
    return 0 if not since else (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(since)).days + 1


def _spent(res):
    """What this company cost, for the progress line — and only when it cost something, so
    the 400 ordinary lines stay one line long. Until 2026-08-26 the night's 128 LLM calls and
    48 unlocker requests were a total with no way back to who spent them."""
    parts = []
    if res.get("unlock_calls"):
        parts.append(f"unlock={res.get('unlock_ok', 0)}/{res['unlock_calls']}")
    if res.get("llm_calls"):
        won = "won" if "llm" in str(res.get("strategy") or "").split("+") else "0"
        kind = str(res.get("llm_error") or "").split(":")[0]
        parts.append(f"llm={res['llm_calls']}->{kind or won}")
    elif res.get("llm_skipped"):
        parts.append(f"llm=skip:{str(res.get('llm_error') or '').split(':')[-1]}")
    return (" " + " ".join(parts)) if parts else ""


def _apply_result(row, res, old, rot, today, st: RunState):
    """Fold one company's result into the run: cache, rot streaks, park/flag lists."""
    name = row["company_name"]
    st.counts["scraped"] += 1
    # what the company cost, whatever it returned (the LLM tier and the unlocker are the two
    # shared quotas this script spends; until 2026-08-26 neither call was counted anywhere)
    st.spend["llm_calls"] += int(res.get("llm_calls") or 0)
    if res.get("llm_error") and int(res.get("llm_calls") or 0):
        st.spend["llm_fail"] += 1            # a CALL failed; a breaker/deadline skip is not one
        kind = str(res["llm_error"]).split(":")[0]
        st.llm_errors[kind] = st.llm_errors.get(kind, 0) + 1
    st.spend["llm_skipped"] += int(res.get("llm_skipped") or 0)
    st.spend["unlock_calls"] += int(res.get("unlock_calls") or 0)
    st.spend["unlock_ok"] += int(res.get("unlock_ok") or 0)
    jobs = None if res["status"] == "error" else res["jobs"]   # ERROR != confirmed-empty
    il = [j for j in (jobs or []) if israel.is_israel_job(j)]
    if il and int(res.get("unlock_ok") or 0):
        st.spend["unlock_won"] += 1            # a company whose read passed through the unlocker
    # a partial read: yesterday's fuller list stays and tonight is an error — for at most
    # PARTIAL_MAX_NIGHTS, after which the smaller list is the board's new truth (a board that
    # genuinely shrank must converge; the first version compared against the list it had
    # carried itself and never did). Two ways to be partial:
    #   `rescued`  the browser failed mid-way and these jobs are what landed before it did
    #   `weak`     the board was read as bare titles, none of them addressed, and it collapsed
    #              — Quantum Machines' 18 Comeet postings became 4 card titles on 2026-08-26
    partial = ((res.get("rescued") and res.get("error"))
               or (res.get("weak_read") and name in old
                   and len(il) * WEAK_SHRINK_RATIO < len(old[name])))
    if (jobs is not None and partial and name in old and len(il) < len(old[name])
            and not (rot.get(name, {}).get("why") == "error"
                     and str(rot[name].get("error", "")).startswith("partial:")
                     and int(rot[name].get("n", 0)) >= PARTIAL_MAX_NIGHTS)):
        res = {**res, "error": f"partial:{res.get('error') or 'weak:read'}"}
        jobs = None
    if jobs is None:
        code = _code(res)
        st.counts["errors"] += 1
        st.codes[code] = st.codes.get(code, 0) + 1
        st.errors.append(f"{name} ({res['error']})")
        days, nights = _rot_bump(rot, name, "error", today, res)
        if str(res.get("error") or "").startswith("links:"):     # not a partial read that DID open pages
            # the listing is alive and lists positions we could not open from here: the
            # roles demonstrably exist, so yesterday's are kept for as long as that holds —
            # never discarded on a clock (operator decision, 2026-08-25). The carry ends the
            # night the listing itself lists fewer than three positions (an ordinary empty).
            st.counts["links_unread"] += 1
            st.unread.append(name)
        if name in old and (days < CARRY_MAX_DAYS or code.startswith("links:")):
            st.cache[name] = old[name]
            st.counts["carried"] += 1
        elif name in old:
            print(f"  {name}: carry expired after {CARRY_MAX_DAYS}d of errors — dropping "
                  f"stale jobs", flush=True)
        if nights >= ROT_PARK_DAYS and _parkable(code):        # nights of THIS shape only
            st.parked.append((name, f"error {days}d"))
        ip_age = _ip_age(rot.get(name), today)
        if ip_age >= STALE_IP_NIGHTS:
            # never parked (parking hands it to a hunt on the same refused address), so after
            # a month somebody has to look: is it us, the site, or a URL that moved? (216)
            st.stale_ip.append((name, ip_age))
        return
    if il:
        st.counts["with_jobs"] += 1
        st.strategies[res["strategy"]] = st.strategies.get(res["strategy"], 0) + 1
        if "llm" in str(res.get("strategy") or "").split("+"):
            st.spend["llm_won"] += 1
        st.cache[name] = st.successes[name] = _carry_jd(il, old.get(name, []))
        rot.pop(name, None)                                    # healthy again
    else:
        st.counts["empty"] += 1
        if jobs:
            st.counts["no_il"] += 1                            # found roles, none in Israel
        days, _ = _rot_bump(rot, name, "empty", today, res)
        # a board only a home address can read (the cloud gets a degraded page from its
        # datacenter IP) keeps the jobs somebody read here, for as long as that read is
        # fresh. Never silently: the night it expires says so, and three nights before that
        # it asks — the row would otherwise go dark for a day before anyone could re-run it.
        age = _residential_age(old.get(name), today)
        if age is not None and age <= RESIDENTIAL_MAX_DAYS:
            st.cache[name] = old[name]
            st.counts["carried_residential"] += 1
            if age >= RESIDENTIAL_MAX_DAYS - RESIDENTIAL_WARN_DAYS:
                st.residential_due.append((name, RESIDENTIAL_MAX_DAYS - age))
            return                    # a live residential read is not an un-revalidated empty
        if age is not None:
            print(f"  {name}: residential read of {age}d ago expired — dropping (re-read it "
                  f"with: python refresh_scrape_cache.py --only \"{name}\" --residential)",
                  flush=True)
        # NEVER park on empty — see EMPTY_REVALIDATE_DAYS. A long streak asks triage to
        # read the page with an LLM; the row stays ACTIVE and scanned daily either way.
        if days >= EMPTY_REVALIDATE_DAYS:
            st.revalidate.append((name, days))


_TOKEN_RX = re.compile(r"[^A-Za-z0-9_.%+:-]")


def _token(s):
    """A stamp value must be one space-free token (`stages.summary()` renders k=v joined by
    spaces); anything else becomes `-`, so an error code can never break the line."""
    return _TOKEN_RX.sub("-", str(s))[:40] or "-"


def _via(strategies):
    """`links73+cards59+dom47` — which strategies carried the night, in the stamp, so a
    strategy collapsing (an extractor change, a blocked address) is visible the next morning
    instead of only in the step log."""
    items = sorted(strategies.items(), key=lambda kv: (-kv[1], kv[0]))
    return "+".join(f"{_token(k or 'unknown').replace('+', '-')}{v}" for k, v in items) or "none"


def _alarm(st: RunState, *, mass_failure=False, shrink=None, rot_unreadable=False):
    """Space-free tokens: `stages.summary()` renders k=v joined by spaces and stages by ` | `."""
    c, tokens = st.counts, []
    if mass_failure:
        tokens.append(f"mass-failure-errors-{100 * c['errors'] // max(1, c['scraped'])}%")
    elif c["scraped"] >= MASS_FAILURE_MIN_ROWS and c["errors"] * 100 > MASS_FAILURE_PCT * c["scraped"]:
        tokens.append(f"errors-{100 * c['errors'] // c['scraped']}%")
    if shrink:
        tokens.append(f"shrink-abort-{shrink[0]}-to-{shrink[1]}")
    if c["unprocessed"] * 20 > (c["scraped"] + c["unprocessed"]):     # more than 5% of rows
        tokens.append(f"unprocessed-{c['unprocessed']}")
    if c["scraped"] >= MASS_FAILURE_MIN_ROWS and not c["with_jobs"]:
        tokens.append("no-jobs")
    # the operator's rule: a listing whose positions could not be opened is never quiet
    if c["links_unread"]:
        tokens.append(f"links-unread-{c['links_unread']}")
    # one code on many rows, below the mass-failure bar: the band where neither guard speaks
    rows = c["scraped"] + c["unprocessed"]
    for code, n in sorted(st.codes.items(), key=lambda kv: (-kv[1], kv[0])):
        if not mass_failure and n * 100 >= CODE_ALARM_PCT * max(1, rows) and n >= MASS_FAILURE_MIN_ROWS // 4:
            tokens.append(f"code-{_token(code)}-{n}")
    s = st.spend
    if s["llm_calls"] >= 3 and s["llm_fail"] >= s["llm_calls"]:
        tokens.append("llm-down")            # every call failed: the token, the CLI, the quota
    if s["llm_calls"] > LLM_RUNAWAY_CALLS:
        tokens.append(f"llm-calls-{s['llm_calls']}")   # the signal gate broke open
    # a row crossing the month mark tonight — once per row per month, never a standing alarm
    crossed = [n for n, nights in st.stale_ip if nights % STALE_IP_NIGHTS == 0]
    if crossed:
        tokens.append(f"stale-ip-{len(crossed)}")
    if rot_unreadable:
        tokens.append("rot-unreadable")
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
    flipped = []
    for fr in fresh:
        if fr and len(fr) > 5 and fr[0] in names and fr[4].strip().lower() == "true":
            fr[4] = "false"
            fr[5] = _note_replace(
                fr[5], "scrape rotted",
                f"scrape rotted ({names[fr[0]]}) {today}: extraction yields 0 — "
                f"no ATS detected; parked for re-hunt")
            flipped.append(fr[0])
    write_csv_rows(CSV_PATH, fresh)
    print(f"parked {len(flipped)} rotted scrape rows for re-hunt: {flipped[:8]}")
    return flipped                      # the streaks of the rest stay on disk


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
    residential: bool = False
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
        elif a == "--residential":
            o.residential = o.apply = True
        elif a == "--workers":
            o.workers = int(next(it))
        else:
            raise SystemExit(f"unknown argument {a!r} — see the module docstring")
    if o.residential:
        # a claim about WHERE the page was read from, so only a run that can honestly make it
        if os.environ.get("GITHUB_ACTIONS"):
            raise SystemExit("--residential is a read from a home address; the runner cannot "
                             "claim one (that address is the reason the row is empty)")
        if not o.scoped:
            raise SystemExit("--residential needs --only or --only-missing: it merges INTO "
                             "the cloud's cache and must never rewrite the whole of it")
        for flag in ("SCRAPE_LLM", "SCRAPE_VIA_UNLOCKER"):
            if os.environ.get(flag):
                raise SystemExit(f"--residential must be reproducible for 0 spend; unset {flag}")
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
    """(data, state). `state` is "ok", "absent" (no file — an interrupted atomic write leaves
    nothing) or "unreadable" (present and not a JSON object, zero bytes included — a hard
    kill leaves those, and a `{}` in their place was 25 companies gone in the rehearsal). Until 2026-08-26 every case read as `{}` and a momentarily
    unreadable cache was rebuilt from tonight's successes alone and written back over 1,200
    jobs (docs/BACKLOG.md 156)."""
    raw = None
    for attempt in range(3):            # another lane's os.replace() can race one read
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            break
        except FileNotFoundError:
            return {}, "absent"
        except OSError:
            time.sleep(0.2 * (attempt + 1))
    if raw is None:
        return {}, "unreadable"
    if not raw.strip():
        return {}, "unreadable"         # zero bytes is what a hard kill leaves: not "no cache"
    try:
        data = json.loads(raw)
    except ValueError:
        return {}, "unreadable"
    return (data, "ok") if isinstance(data, dict) else ({}, "unreadable")


def run(argv=None, *, pool_cls=None, worker=None, clock=time.time):
    o = _parse(sys.argv[1:] if argv is None else argv)
    old, old_state = _load(CACHE_PATH)
    rot, rot_state = _load(ROT_PATH)
    day = _today()                      # read once: the cron fires AT midnight
    today = day.isoformat()
    rows = _select_rows(o, old)
    if not o.scoped:
        rows = _rotate(rows, day)
    budget = float(os.environ.get("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0"))
    grace = int(os.environ.get("SCRAPE_INFLIGHT_GRACE_S", "600"))
    st = RunState()
    if old_state == "unreadable" and not (o.scoped or o.dry_run):
        # the one file this script must not rebuild from a night's successes alone: without
        # yesterday's entries nothing can be carried and the shrink guard is blind, so the
        # write would be the 1,200-job deletion BACKLOG 156 describes. Refuse before spending
        # 30 minutes of Chromium; stamp first so the mail says why (the commit step is
        # `if: always()` and owns the stamp file).
        print(f"::error::{CACHE_PATH} is unreadable — refusing to rebuild the cache without it",
              flush=True)
        st.counts["unprocessed"] = len(rows)
        stages.stamp("collect", rows=len(rows), **st.counts, parked=0, workers=o.workers,
                     minutes=0, via=_via({}), alarm="cache-unreadable")
        return 1
    if rot_state == "unreadable":
        # derivable state: a night of coverage is worth more than a streak counter. The
        # unreadable file is REPLACED by tonight's streaks (they restart from 1); nothing
        # is parked on evidence this run cannot see.
        print(f"::warning::{ROT_PATH} is unreadable — streaks restart tonight, nothing is parked",
              flush=True)
    print(f"refreshing {len(rows)} scrape rows with {o.workers} worker(s)"
          + (f", budget {budget:g} min" if budget else "")
          + (" [scoped: nothing is written]" if o.scoped and not o.apply else "")
          + (" [dry-run]" if o.dry_run else ""), flush=True)
    t0 = clock()
    results = {}
    for res in _scrape_all(rows, workers=o.workers, budget_min=budget, pool_cls=pool_cls,
                           grace_s=grace, worker=worker, clock=clock):
        results[res["name"]] = res
        # progress in COMPLETION order, so the cloud log is readable while the pool runs;
        # the bookkeeping below is in registry order, so the output is deterministic
        what = (f"ERROR {res['error']}" if res["status"] == "error"
                else f"{len(res['jobs'])}" + (f" via {res['strategy']}" if res["jobs"] else ""))
        print(f"  [{len(results)}/{len(rows)}] {res['name']}: {what} "
              f"({res['seconds']:.0f}s){_spent(res)}", flush=True)
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
    if st.unread:
        # the operator's rule (2026-08-25): a listing whose positions we could not open is
        # never quietly empty. Named here, counted in the stamp, kept in the cache.
        kept = sum(1 for n in st.unread if n in st.cache)
        print(f"::warning::positions unreadable from this runner for {len(st.unread)} "
              f"companies ({kept} with yesterday's jobs carried; all kept active): "
              f"{st.unread[:12]}", flush=True)
    if st.residential_due:
        print(f"::warning::{len(st.residential_due)} companies the cloud cannot read are "
              f"living on a home-address read that expires within {RESIDENTIAL_WARN_DAYS} "
              f"nights — re-run `--residential` for: "
              f"{[n for n, _ in sorted(st.residential_due, key=lambda x: x[1])[:12]]}",
              flush=True)
    if st.stale_ip:
        # never parked by design, so nothing else will ever raise its hand (BACKLOG 216)
        print(f"::warning::the runner's address has been refused for {STALE_IP_NIGHTS}+ nights "
              f"by {len(st.stale_ip)} companies — hand-check (is it us, the site, or a moved "
              f"URL?): {sorted(st.stale_ip, key=lambda x: -x[1])[:12]}", flush=True)
    c = st.counts
    minutes = int((clock() - t0) / 60)
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
    alarm = _alarm(st, mass_failure=mass_failure, shrink=shrink,
                   rot_unreadable=rot_state == "unreadable")
    parks = 0 if (mass_failure or shrink or rot_state == "unreadable") else len(st.parked)
    detail = dict(rows=len(rows), **c, parked=parks, workers=o.workers, minutes=minutes,
                  via=_via(st.strategies))
    # the two shared quotas, only on a run that could have spent them (a local run without
    # the flags would otherwise carry five permanent zeros)
    if os.environ.get("SCRAPE_LLM"):
        detail.update(llm_calls=st.spend["llm_calls"], llm_won=st.spend["llm_won"],
                      llm_fail=st.spend["llm_fail"], llm_skipped=st.spend["llm_skipped"])
    if os.environ.get("SCRAPE_VIA_UNLOCKER"):
        detail.update(unlock_calls=st.spend["unlock_calls"], unlock_ok=st.spend["unlock_ok"],
                      unlock_won=st.spend["unlock_won"])
    if alarm:
        detail["alarm"] = alarm
    print(f"=== collect: " + " ".join(f"{k}={v}" for k, v in detail.items())
          + f" | strategies {st.strategies}" + (f" | llm errors {st.llm_errors}" if st.llm_errors else "")
          + (f"\n    errors: {st.errors[:12]}" if st.errors else ""),
          flush=True)

    if o.dry_run:
        print("dry-run: nothing written")
        return 0
    if o.scoped:
        if o.apply and st.successes:
            fresh, state = _load(CACHE_PATH)          # re-read: another writer may have added keys
            if state == "unreadable":
                print(f"::error::{CACHE_PATH} is unreadable — not merging over it")
                return 1
            merged = ({k: _mark_residential(v, today) for k, v in st.successes.items()}
                      if o.residential else st.successes)
            fresh.update(merged)
            write_json(CACHE_PATH, fresh, sort_keys=True)
            print(f"merged {len(merged)} companies into {CACHE_PATH}"
                  + (f" as residential reads — the cloud keeps them for "
                     f"{RESIDENTIAL_MAX_DAYS} nights" if o.residential else ""))
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
    if parks:
        # the registry first: if this write fails, the streaks that justified it are still
        # on disk for tomorrow; only a row the write really flipped loses its streak
        for name in _park(st.parked, today):
            rot.pop(name, None)       # a re-activated row gets its ROT_PARK_DAYS of grace again
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
