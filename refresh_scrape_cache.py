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
from collections import Counter as _Counter
from dataclasses import dataclass, field

from pipeline import israel
from pipeline import stages
from pipeline.atomic import write_csv_rows, write_json
from pipeline.companies import load_companies
from pipeline.notes import append as _note_append, replace_own as _note_replace
from scrape_universal import COMPANY_BUDGET_S, _ip_shaped, scrape_result

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
# The alarm is a RATCHET against an ANCHOR, not a difference against yesterday, and the
# growth is adjusted for the pool. Wave 1 measured all three reasons on the real series
# (reconstructed from scrape_rot.json's since/last/n, which reproduces the committed
# 08-27 stamp's empty=196 exactly): the night-to-night deltas are +10, +29, +29, +4, so a
# 25-row one-night bar fires on 2 of the 4 nights on record and NONE was a regression;
# the whole 216 -> 287 jump of 2026-08-28 is the pool moving 421 -> 496, i.e. entirely
# the registry activating rows; and a leak of 24 a night is silent forever against a
# yesterday baseline -- 168 rows, a third of the pool, in seven quiet nights.
# So: `uncached_base`/`rows_base` anchor the comparison, the anchor RATCHETS DOWN when
# coverage improves and holds when it worsens, and pool growth since the anchor is
# subtracted. A leak of 24 a night now fires on the second night, benign expansion never
# does, and a same-day re-run recomputes the same verdict instead of erasing it.
# Rows the registry has activated that the cache cannot answer for are invisible to every
# downstream stage -- the digest reads scraped_cache.json and nothing else -- and until
# 2026-08-28 nothing counted them: 287 of 496 active scrape rows (58%), 216 of 421 the
# night before. The LEVEL must never be an alarm: 196 of those 216 were `empty`, which
# this file calls a measurement, so any ratio bar under ~50% would light the mail's
# `Stages:` line every morning and bury the tokens that line exists to carry. A JUMP is
# the event, and the bar is MEASURED, not chosen: `empty` moved by 3 between the 08-26 and
# 08-27 stamps (199 -> 196), while the one extraction regression on record flipped 30 rows
# in a night and was found by hand a day later. The percentage keeps the bar in proportion
# as the registry grows (5% of 496 = 24, so the floor of 25 governs today).
UNCACHED_JUMP_MIN = 25
UNCACHED_JUMP_PCT = 5


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



# `_ip_shaped` lives in `scrape_universal` (imported above): `_classify` and this file's
# shape/park logic must agree on what "the ADDRESS was refused" means, and two copies
# drifting is how a wall got booked as an empty page (lakeFS http:403, 2026-08-30).


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
    the same cloaking WAF (a 404) dropped the jobs AND parked the row with no alarm.

    It strips its own `partial:` wrapper, because the ROT FILE stores the wrapped code and
    the next reader of a stored code would otherwise shape `partial:weak:read` as `page` —
    parkable, which `_parkable`'s docstring promises it can never be (wave-1 attacker B)."""
    code = str(code or "").removeprefix("partial:")
    if code.startswith("links:"):
        return "links"
    if _ip_shaped(code):
        return "ip"
    # both say "our READING failed", never "this company's page did": a url-less collapse and
    # an expired home-address read. Neither may ever park a row.
    if code.startswith(("weak:", "residential:")):
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
                                                  "carried_residential": 0,
                                                  "dropped_residential": 0,
                                                  "loc_unknown": 0})
    spend: dict = field(default_factory=lambda: {"llm_calls": 0, "llm_won": 0, "llm_fail": 0,
                                                 "llm_skipped": 0, "unlock_calls": 0,
                                                 "unlock_ok": 0, "unlock_won": 0})
    strategies: dict = field(default_factory=dict)
    codes: dict = field(default_factory=dict)      # error code -> count, for the per-code alarm
    llm_errors: dict = field(default_factory=dict) # LLMUnavailable kind -> count (auth/transient/...)
    errors: list = field(default_factory=list)
    unread: list = field(default_factory=list)     # companies whose positions could not be opened
    stale_ip: list = field(default_factory=list)   # (name, nights, crossed_tonight) — see 216
    residential_due: list = field(default_factory=list)  # (name, nights left) to re-read here
    embeds: list = field(default_factory=list)     # (name, '<plat>:<token>:<why>') - see _from_embedded_board


# ---------------------------------------------------------------------------------------------
# the scrape, in or out of process
# ---------------------------------------------------------------------------------------------
def _never_ran(name, error, seconds=0.0):
    """A result for a company the scraper never got to read — the worker raised, the pool
    died, the process hung. ONE builder, because there were three hand-copied copies and they
    had already drifted: two lacked `weak_read`, all three lacked `llm_skipped`, and every
    consumer is a `.get()` away from a `KeyError` on paths that only ever fire in the cloud
    (BACKLOG 245, `scraper` 2026-08-26 evening). Every code it carries is runner-shaped, so
    such a night carries the company's jobs and never parks the row."""
    return {"name": name, "jobs": [], "status": "error", "error": error, "http_status": None,
            "strategy": "", "rescued": False, "weak_read": False, "llm_calls": 0,
            "llm_error": "", "llm_skipped": 0, "loc_unknown": 0,
            "unlock_calls": 0, "unlock_ok": 0,
            "embed": "", "embed_seen": "", "seconds": seconds}


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
                "loc_unknown": int(getattr(res, "loc_unknown", 0) or 0),
                "unlock_calls": int(getattr(res, "unlock_calls", 0) or 0),
                "unlock_ok": int(getattr(res, "unlock_ok", 0) or 0),
                "embed": str(getattr(res, "embed", "") or ""),
                "embed_seen": str(getattr(res, "embed_seen", "") or ""),
                "seconds": round(res.elapsed_s, 1)}
    except BaseException as e:  # noqa: BLE001
        return _never_ran(name, f"worker:{type(e).__name__}", round(time.time() - t0, 1))


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
                            yield _never_ran(futs[f], f"hang:>{int(stall_s)}s", float(stall_s))
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
    return _never_ran(name, f"pool:{type(exc).__name__}")


# ---------------------------------------------------------------------------------------------
# per-company bookkeeping (pure: no I/O)
# ---------------------------------------------------------------------------------------------
def _is_own_address(j, listing):
    """Does this card name a page of its own, rather than the listing it was read from?
    Unknowable without the listing url, and an unknown answer must not accuse a card of being
    a re-post — so no listing means "cannot tell", and the carry behaves as it always did."""
    if not listing:
        return False
    from scrape_universal import _is_strong
    return _is_strong(j.get("url"), listing)


def _title_key(j):
    """A card's (title, place) — what survives a night when its ADDRESS changed."""
    title = (j.get("title") or "").strip().lower()
    return "T:%s|%s" % (title, (j.get("location") or "").strip().lower()) if title else ""


def _addresses(j):
    """The names a card keeps between nights: its address and its id."""
    return [x for x in (j.get("url") or "", j.get("job_id") or "") if x]


def _carry_jd(new_jobs, old_jobs, listing=""):
    """A rebuilt card with an empty description inherits the previous run's text so daily
    refreshes stop wiping what enrich_scrape_jd fetched — and the `_jd_attempted` stamp
    travels too, or failed enrichments lose their 7-day cooldown every night and re-burn
    Bright Data calls on the same unfetchable URLs.

    Matched by (title, place) FIRST, and only when it names exactly one card on each side.
    A card's ADDRESS is the less stable key of the two: it changes when a later strategy
    gives a url-less reading its own address, and it changed for a whole board the night
    `_card_href` stopped taking the previous card's link — put the address first and 59
    postings across 6 boards inherit the neighbouring role's description on that one night
    (wave-1 attacker C), which is also what `pipeline/seniority.py` would classify.

    Two openings of one role at one place are common, so a non-unique title falls back to
    the address. The 7-day `_jd_attempted` cooldown follows the ADDRESS rather than the
    match: an unchanged one is certainly the same posting, while a moved one may be a
    re-post, which from here looks exactly like a promotion — and jdfill must stay free to
    read a posting that is really new (wave-1 attacker B)."""
    prev = {k: j for j in old_jobs if isinstance(j, dict) for k in _addresses(j)}
    by_title, new_titles = {}, _Counter(_title_key(j) for j in new_jobs)
    for j in old_jobs:
        if isinstance(j, dict) and (k := _title_key(j)):
            by_title.setdefault(k, []).append(j)
    for j in new_jobs:
        k = _title_key(j)
        twins = by_title.get(k) or []
        pj = twins[0] if k and len(twins) == 1 and new_titles[k] == 1 else None
        if pj is None:
            pj = next((prev[a] for a in _addresses(j) if a in prev), None)
        if pj is None:
            continue
        same_address = bool(set(_addresses(j)) & set(_addresses(pj)))
        # A title match across TWO DIFFERENT addresses that each name their own page is a
        # re-post, not a promotion: yesterday's `Data Analyst / Tel Aviv` closed and a new one
        # opened. Carrying the text there put a dead role's description on a live opening and
        # kept it (jdfill skips a card that already has one). A promotion is the other shape
        # — yesterday's card had NO address of its own — and still carries (BACKLOG 249).
        reposted = (not same_address and _is_own_address(pj, listing)
                    and _is_own_address(j, listing))
        if (not reposted and not (j.get("description") or "").strip()
                and (pj.get("description") or "").strip()):
            j["description"] = pj["description"]
        # the cooldown follows an unchanged ADDRESS, whichever key found the card: a posting
        # whose address moved may be a re-post rather than a promotion, and jdfill must stay
        # free to read it — but the ordinary night, where nothing moved, must keep its 7-day
        # cooldown or every card re-enters the Bright Data pool nightly.
        if same_address and pj.get("_jd_attempted") and not j.get("_jd_attempted"):
            j["_jd_attempted"] = pj["_jd_attempted"]
    return new_jobs


def _rot_bump(rot, name, why, today, res=None):
    """Advance a company's streak. Returns (days since the streak began, nights observed).

    A streak is one kind of outcome: flipping empty→error starts a NEW streak (the first
    version kept `since`, so a company that had been honestly empty for 60 days would have
    been parked on its first transient error). Parking counts observed nights, not wall-clock
    days, so nights the budget skipped a row do not advance its clock."""
    raw = str((res or {}).get("error") or "")      # `_code` strips the wrapper we test for
    held = raw.startswith("partial:")
    code = _code(res or {})
    shape = _shape(code) if why == "error" else ""
    e = rot.get(name)
    if not isinstance(e, dict):
        # `_load` validates only the TOP level, and this file is merged per key on a push
        # conflict. One scalar value used to raise `AttributeError` here, in the parent
        # loop, after 30 minutes of Chromium and before the cache was written -- no cache,
        # no stamp, the whole night gone. Same reachability, and the same remedy, as the
        # malformed date `_ip_age` was hardened against (wave-1 attacker A, F5).
        e = None
    # Two clocks survive a change of shape, because the streak `n` is per shape by design:
    #   `ip_since`   how long the runner's ADDRESS has been refused. A WAF answers 403 on the
    #                listing one night and refuses the position pages the next, flipping
    #                `ip`/`links`, and our OWN failures (`runner`) say nothing either way — a
    #                clock reset by any of them could never reach a month (wave-0/1 critics).
    #   `partial_n`  nights a read was held back as partial. It survives every ERROR night,
    #                held or not — one 403 between two weak nights would otherwise clear it
    #                and an 18 -> 4 shrink would be held forever (wave-2 confirmer proved the
    #                first version did exactly that: 60 alternating nights, `partial_n` never
    #                past 1 against a bar of 2). A night that is not an error is a read we
    #                believed, and it ends the hold.
    keep_ip = shape in ("ip", "links", "runner")
    carried = {k: v for k, v in (e or {}).items()
               if (k == "ip_since" and keep_ip) or (k == "partial_n" and why == "error")}
    if e is None or e.get("why") != why or (shape and e.get("shape") not in (None, shape)):
        e = rot[name] = {"since": today, "why": why, "n": 0}
    e.update(carried)
    if shape:
        e["shape"] = shape                   # an entry from before shapes existed adopts tonight's
    if shape in ("ip", "links"):
        e["ip_since"] = e.get("ip_since") or today
    elif not keep_ip:
        e.pop("ip_since", None)
    if e.get("last") != today:
        e["n"] = int(e.get("n", 0)) + 1
        if held:
            e["partial_n"] = int(e.get("partial_n", 0)) + 1
    else:
        e["n"] = int(e.get("n", 1))          # an entry from before `n` existed, bumped today
    if why != "error":
        e.pop("partial_n", None)             # a believed read ends the hold
    e["last"] = today
    if res is not None:                      # what actually happened, for the offline reader
        e["error"] = res.get("error") or ""
        e["found"] = len(res.get("jobs") or [])          # jobs seen before the Israel filter
        if res.get("embed_seen"):
            e["embed"] = res["embed_seen"]               # the handoff, on the row it is about
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


def _expire_residential(name, age, rot, today, st):
    """Drop a home-address read the cloud can no longer stand behind — out loud, counted, and
    leaving a code board health can read.

    Without the code the row goes quiet: an empty cache beside a `why: empty` rot entry is
    what `health.overnight_verdict` reads as `regressed-to-zero`, so a company that is merely
    unreadable from the runner would enter the weekly self-heal and the LinkedIn rotation —
    the exact class `overnight_verdict` was built to keep out (wave-1 attacker B)."""
    st.counts["dropped_residential"] += 1
    _rot_bump(rot, name, "error", today,
              {"error": "residential:expired", "jobs": [], "http_status": None})
    print(f"  {name}: residential read of {age}d ago expired — dropping (re-read it with: "
          f'python refresh_scrape_cache.py --only "{name}" --residential)', flush=True)


def _ip_age(entry, today):
    """Nights this row's ADDRESS has been refused, counting across every shape that means it
    (`ip_since`, which a 403 -> links flip does not restart). 0 when it is not refused, and 0
    rather than a crash on a malformed stamp: a rot file is merged by another process on a
    conflict night, and one bad date used to take the whole run down AFTER all the Chromium
    work — no cache, no stamp (wave-1 attacker B)."""
    since = (entry or {}).get("ip_since")
    try:
        return 0 if not since else (_dt.date.fromisoformat(today)
                                    - _dt.date.fromisoformat(since)).days + 1
    except (ValueError, TypeError):
        return 0


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
        parts.append(f"llm=skip:{_token(str(res.get('llm_error') or '').split(':')[-1])}")
    return (" " + " ".join(parts)) if parts else ""


def _apply_result(row, res, old, rot, today, st: RunState):
    """Fold one company's result into the run: cache, rot streaks, park/flag lists."""
    name = row["company_name"]
    st.counts["scraped"] += 1
    if res.get("embed_seen"):
        # a board found INSIDE this page, with the identity gate's verdict on it. Recorded
        # whatever the verdict: a REFUSED board on a row that yields nothing is the only
        # nightly handoff `registry` has for "this row should be a comeet/ashby row".
        st.embeds.append((name, res["embed_seen"]))
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
    # role-shaped cards refused because NOTHING placed them (496): the level that shows a
    # board hiding its locations — before 2026-08-30 the query stamped these "Israel"
    st.counts["loc_unknown"] += int(res.get("loc_unknown") or 0)
    if res["status"] == "empty" and _ip_shaped(_code(res)):
        # the belt to `_classify`'s own fix: an "empty" that carries an ip-shaped refusal
        # code is a wall that answered the plain client a decoy 200 (lakeFS, Nokia,
        # Schneider Electric on 2026-08-30 — 5 nights each as `why: empty` while
        # `health.overnight_verdict` had the fetch-error verdict waiting on the word
        # "error"). An unread board is an error night, whatever a stale or foreign
        # scrape_universal said; ip-shaped never parks, so this can only make rows LOUDER.
        # (dict(...) and not a literal: `_never_ran` is the ONE builder of error results,
        # and a source assertion holds it to that — this line flips a status, builds nothing.)
        res = dict(res, status="error")
    jobs = None if res["status"] == "error" else res["jobs"]   # ERROR != confirmed-empty
    il = [j for j in (jobs or []) if israel.is_israel_job(j)]
    # a partial read: yesterday's fuller list stays and tonight is an error — for at most
    # PARTIAL_MAX_NIGHTS, after which the smaller list is the board's new truth (a board that
    # genuinely shrank must converge; the first version compared against the list it had
    # carried itself and never did). Two ways to be partial:
    #   `rescued`  the browser failed mid-way and these jobs are what landed before it did
    #   `weak`     the board was read as bare titles, none of them addressed, and it collapsed
    #              — Quantum Machines' 18 Comeet postings became 4 card titles on 2026-08-26
    # `weak_read` counts what the ADDER accepted; the shrink compares what `pipeline.israel`
    # accepts. A board whose Israel roles all genuinely closed, read weakly, satisfied the
    # second test with an empty `il` and was booked as an error instead of an honest empty
    # (wave-1 attacker B), so the guard needs a reading that is still Israeli.
    partial = ((res.get("rescued") and res.get("error"))
               or (res.get("weak_read") and il and name in old
                   and len(il) * WEAK_SHRINK_RATIO < len(old[name])))
    if (jobs is not None and partial and name in old and len(il) < len(old[name])
            and int((rot.get(name) or {}).get("partial_n", 0)) < PARTIAL_MAX_NIGHTS):
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
        res_age = _residential_age(old.get(name), today)
        if res_age is not None and not 0 <= res_age <= RESIDENTIAL_MAX_DAYS:
            # a home-address read has ONE expiry, whatever tonight's code is: an error night
            # carries for 14 days and a `links:` one carries forever, and either would have
            # kept a months-old read on the board (wave-1 attacker B)
            _expire_residential(name, res_age, rot, today, st)
        elif name in old and (days < CARRY_MAX_DAYS or code.startswith("links:")):
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
            # The row records the age it was last announced at, so ONE skipped night cannot
            # lose the alarm for another month, and a re-run cannot raise it twice.
            announced = int(rot[name].get("ip_announced", 0))
            st.stale_ip.append((name, ip_age, ip_age >= announced + STALE_IP_NIGHTS))
            if ip_age >= announced + STALE_IP_NIGHTS:
                rot[name]["ip_announced"] = ip_age
        return
    if il:
        st.counts["with_jobs"] += 1
        st.strategies[res["strategy"]] = st.strategies.get(res["strategy"], 0) + 1
        stages_won = str(res.get("strategy") or "").split("+")
        if "llm" in stages_won:
            st.spend["llm_won"] += 1
        # the unlocker only ever feeds the position-page rung and the listing re-fetch, so a
        # win it paid for is one where those read the board — not merely a night where the
        # unlocker answered and another strategy won (wave-1 attacker B)
        if int(res.get("unlock_ok") or 0) and {"links", "llm", "cards"} & set(stages_won):
            st.spend["unlock_won"] += 1
        st.cache[name] = st.successes[name] = _carry_jd(il, old.get(name, []),
                                                     row.get("api_url", ""))
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
        # NEVER park on empty — see EMPTY_REVALIDATE_DAYS. A long streak asks triage to
        # read the page with an LLM; the row stays ACTIVE and scanned daily either way. A
        # residential carry is still an un-revalidated empty: the cloud has not read this
        # board in weeks, which is exactly what triage should look at.
        if days >= EMPTY_REVALIDATE_DAYS:
            st.revalidate.append((name, days))
        age = _residential_age(old.get(name), today)
        if age is None:
            return
        if 0 <= age <= RESIDENTIAL_MAX_DAYS:
            st.cache[name] = old[name]
            st.counts["carried_residential"] += 1
            if age >= RESIDENTIAL_MAX_DAYS - RESIDENTIAL_WARN_DAYS:
                st.residential_due.append((name, RESIDENTIAL_MAX_DAYS - age))
            return
        _expire_residential(name, age, rot, today, st)


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


def _uncached(rows, cache, parking=()):
    """Active scrape rows this run leaves with NO entry in `cache` -- invisible to the
    digest, to `stale.json` and to the mail. Measured over the rows this run SELECTED,
    because only an unscoped run stamps and an unscoped run selects every active scrape row
    (`_rotate` is a permutation). A re-read of the registry instead would annex the one
    `ats_platform=discovery` row `_select_rows` deliberately never touches.

    Rows this same exit is PARKING are not counted: the registry write that follows makes
    them inactive, and an inactive row is not coverage this pipeline is missing. The bound
    on that: a park the CSV write does not match (the registry renamed the row mid-run)
    undercounts by at most `parked`, for one night -- and a park write that RAISES never
    reaches the stamp at all, so the morning reads `collect: <yesterday> (1d ago)` instead
    of a wrong number."""
    gone = {n for n, _ in parking}
    return sum(1 for r in rows
               if r["company_name"] not in cache and r["company_name"] not in gone)


def _unvisited(rows, cache, rot, parking=()):
    """Of the uncached rows, the ones with no `scrape_rot.json` entry either: no run has an
    OUTCOME for them at all. Zero on any night that scraped every selected row, BY
    CONSTRUCTION -- `_apply_result` leaves a company in the cache (`with_jobs`, an error
    carry, a residential carry) or in the rot file (`empty`, `error`), never in neither --
    so `unvisited <= unprocessed`, and any non-zero value names rows the night never reached
    that nothing has ever scraped. It is the leading indicator of the 287 uncached rows of
    2026-08-28, one night before it is 287."""
    gone = {n for n, _ in parking}
    return sum(1 for r in rows
               if r["company_name"] not in cache and r["company_name"] not in rot
               and r["company_name"] not in gone)


def _uncached_grew(uncached, rows, base):
    """Has coverage LOST ground since the anchor, beyond what the registry added?

    `max(0, rows - base_rows)` is the pool's growth since the anchor: every row the
    registry activates arrives uncached by construction, and that is triage's business,
    not extraction's. Subtracting it is what separates the two causes the operator has to
    tell apart -- and both numbers are already on the same stamp line, so the reader can
    check the arithmetic without yesterday's file. A pool that SHRANK adds nothing."""
    base_u, base_r = base
    jump = max(UNCACHED_JUMP_MIN, UNCACHED_JUMP_PCT * max(rows, 0) // 100)
    return (uncached - base_u) - max(0, rows - base_r) >= jump


def _next_base(uncached, rows, base, fired):
    """The anchor tomorrow measures from. It ratchets DOWN on any improvement, resets when
    the alarm fires (so one loss is announced once, not every night after), and otherwise
    HOLDS -- which is the whole point: a slow leak accumulates against a fixed point."""
    if base is None or fired or uncached <= base[0]:
        return uncached, rows
    return base


def _uncached_base(key="uncached"):
    """The ANCHOR the growth alarm measures from: `(<key>, rows)` of the last stamp that
    set one, read BEFORE `stages.stamp()` replaces the whole entry. One reader for both
    anchored counters — `uncached` and, from 2026-08-31, `ownless` (postings whose url is
    the listing, 434); `_uncached_grew`/`_next_base` are already pure and shared.

    Not "yesterday": yesterday is both too noisy (the real deltas are +10/+29/+29/+4) and
    too forgiving (a 24-a-night leak never shows). The anchor holds while coverage worsens
    and ratchets DOWN the moment it improves, so slow loss accumulates against a fixed
    point and a recovery re-arms it. `rows` rides along because the pool grows: the
    registry moved 421 -> 496 in one night and the whole apparent jump was that.

    A night that could not READ the cache measured nothing and stamps `uncached=rows`;
    anchoring there would hide the next real jump behind an apparent fall, so it is
    refused. An older stamp that predates these keys falls back to its own `uncached`, so
    the first night after this lands is silent and the second is armed. None means NO
    token, never a guess. `cloud_state/pipeline_stages.json` is committed by
    scrape-refresh.yml and merged per stage by `persist_state`, so the anchor survives the
    runner and a push conflict."""
    e = stages._load().get("collect") or {}
    if "cache-unreadable" in str(e.get("alarm") or ""):
        return None
    try:
        u = int(e[f"{key}_base"]) if f"{key}_base" in e else int(e[key])
        # each anchor carries its OWN rows: the two ratchet on different nights, and the
        # pool-growth subtraction must read the pool as it was on THIS anchor's night
        rk = "rows_base" if key == "uncached" else f"{key}_rows_base"
        r = int(e.get(rk, e.get("rows", 0)))
    except (KeyError, TypeError, ValueError):
        return None
    return u, r


def _alarm(st: RunState, *, mass_failure=False, shrink=None, rot_unreadable=False,
           uncached=None, unvisited=0, base=None, row_count=0, fabricated=0,
           ownless=None, own_base=None):
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
    crossed = [n for n, _, is_new in st.stale_ip if is_new]
    if crossed:
        tokens.append(f"stale-ip-{len(crossed)}")
    # Rows the digest cannot see. The LEVEL is never a token -- `uncached=N` is in the stamp
    # every night for that, and a permanently-lit alarm would cost the reader the whole
    # line. A JUMP is the event: extraction that stopped extracting, or a registry
    # activating rows nothing can read. `A-to-B` follows `shrink-abort-A-to-B`, so B
    # reconciles against the `uncached` key on the SAME line and the reader never needs
    # yesterday's file.
    # `row_count`, not the local `rows` twelve lines up (which is scraped+unprocessed):
    # they are equal today only because the bookkeeping loop visits every selected row,
    # and a bar that silently moves with a refactor is not a bar (wave-1 attacker A, F7).
    if uncached is not None and base is not None and _uncached_grew(uncached, row_count, base):
        tokens.append(f"uncached-up-{base[0]}-to-{uncached}")
    # the same anchored-jump event for postings that carry no address of their own (434):
    # extraction stopped finding per-job links, or a big board's markup changed
    if ownless is not None and own_base is not None and _uncached_grew(ownless, row_count, own_base):
        tokens.append(f"ownless-up-{own_base[0]}-to-{ownless}")
    # neither a cache entry nor a rot entry: the night never reached these rows and nothing
    # ever has. Zero on a complete night by construction, so any N is an event.
    if unvisited:
        tokens.append(f"unvisited-{unvisited}")
    # a bare "Israel" with no provenance in TONIGHT's fresh reads is a bug by construction:
    # since 2026-08-30 every write path stamps `_loc_src` (own/group/assumed), so any count
    # here means a regression re-opened the query-stamp class (496), a write path bypassed
    # `_Adder`, or a foreign tree fed the cache. Zero is the design, which is the point.
    if fabricated:
        tokens.append(f"fabricated-loc-{fabricated}")
    if rot_unreadable:
        tokens.append("rot-unreadable")
    return "+".join(tokens)


def _unprovenanced(jobs):
    """Postings carrying the bare word "Israel" with none of the three provenance values —
    pre-2026-08-30 stamps in carried entries (`legacy_loc`, must ratchet to 0 as boards
    re-scrape) or, in tonight's fresh reads, a fabrication (`fabricated-loc-N` alarms)."""
    return sum(1 for j in jobs or [] if str(j.get("location", "")).strip().lower() == "israel"
               and j.get("_loc_src") not in ("own", "group", "assumed"))


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
            if not o.only:
                # `--only "$COMPANY"` with COMPANY unset used to parse to the empty set,
                # which is falsy, so `scoped` was False and the run rewrote the whole
                # cache, parked rows in companies.csv and STAMPED -- the opposite of what
                # the flag was typed to do (wave-1 attacker A, F4). `--limit 0` is caught
                # by the same rule below.
                raise SystemExit("--only was given an empty list: refusing to run "
                                 "UNSCOPED on an argument that was meant to narrow")
        elif a == "--limit":
            o.limit = int(next(it))
            if o.limit <= 0:
                # 0 is falsy, so `scoped` would be False and a flag typed to NARROW
                # the run would rewrite the whole cache and stamp (wave-1 A, F4).
                raise SystemExit("--limit must be positive")
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
        if not (o.only or o.only_missing):
            # `scoped` is also true for --limit and --shard, and `--shard 0 1` IS the whole
            # registry: one command would stamp every company as read from a home address
            # and the cache would stop converging for a fortnight (wave-1 attacker B)
            raise SystemExit("--residential needs --only or --only-missing: it merges INTO "
                             "the cloud's cache and must never rewrite the whole of it")
        for flag in ("SCRAPE_LLM", "SCRAPE_VIA_UNLOCKER"):
            if os.environ.get(flag):
                raise SystemExit(f"--residential must be reproducible for 0 spend; unset {flag}")
    return o


def _select_rows(o: Opts, cache, rot=None):
    rows = [r for r in load_companies(CSV_PATH, active_only=True)
            if r["ats_platform"].strip().lower() == "scrape"]
    if o.only:
        rows = [r for r in rows if r["company_name"].strip().lower() in o.only]
    if o.only_missing:
        rows = [r for r in rows if not cache.get(r["company_name"])]
        # NEVER-VISITED FIRST. A scoped run is not day-rotated (`_rotate` is skipped below),
        # and the registry appends, so the rows no run has ever seen sit at the very END of
        # this selection: on 2026-08-28 all 71 of them were at positions 217-287 of 287, and
        # every one of the 70 boards this pass recovered came from that tail. A time budget
        # that binds would therefore strand exactly the rows `--only-missing` exists to
        # reach -- and this is the command the `unvisited-N` alarm tells the operator to run.
        # Stable within each group, so the order is still deterministic.
        rows.sort(key=lambda r: r["company_name"] in (rot or {}))
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
    # the rot file as it was BEFORE tonight touched it. `_apply_result` pops a healthy
    # company's entry and `_rot_bump` inserts a rotting one, but the two ABORT exits
    # return without writing any of that -- so a count taken from the live dict describes
    # a file that does not and will never exist. That cost `unvisited` its own invariant:
    # a row scraped SUCCESSFULLY tonight, absent from yesterday's cache, read as
    # never-visited on a shrink-abort night, and `unvisited > unprocessed` (wave-1
    # attacker A, F1/F2). Same discipline as `written` below, one file along.
    rot_at_start = dict(rot)
    day = _today()                      # read once: the cron fires AT midnight
    today = day.isoformat()
    rows = _select_rows(o, old, rot)
    if not o.scoped:
        rows = _rotate(rows, day)
    base = _uncached_base()               # BEFORE any stamp replaces the entry
    own_base = _uncached_base("ownless")
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
        # `uncached = rows`: this run can read no cache AT ALL, so as far as tonight can
        # tell nothing is covered. That is the honest value, and it is why
        # `_prev_uncached()` refuses this stamp as tomorrow's baseline. The alarm stays the
        # single token `cache-unreadable` -- it already says everything a second would.
        stages.stamp("collect", rows=len(rows), **st.counts, parked=0,
                     uncached=_uncached(rows, {}), unvisited=_unvisited(rows, {}, rot),
                     embeds=0, embeds_won=0,
                     workers=o.workers, minutes=0, via=_via({}), alarm="cache-unreadable")
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
              f"URL?): {[(n, a) for n, a, _ in sorted(st.stale_ip, key=lambda x: -x[1])][:12]}",
              flush=True)
    if st.embeds:
        # the gate's two non-admissions, named explicitly: a negation over the record
        # vocabulary called a WIN a refusal (own guard, 2026-08-28).
        refused = [(n, s) for n, s in st.embeds
                   if s.endswith((":not-ours", ":unverified"))]
        won = sum(1 for _, s in st.embeds if s.endswith(":won"))
        print(f"::warning::{len(st.embeds)} rows the ladder could not read embed a board "
              f"this repo already fetches; {won} were read through it and {len(refused)} "
              f"were NOT ADMITTED by the identity gate "
              f"and are the `registry` handoff -- declare the tenant in "
              f"pipeline/identity_facts.py, or convert the row's ats_platform: "
              f"{refused[:12]}", flush=True)
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
    parks = 0 if (mass_failure or shrink or rot_state == "unreadable") else len(st.parked)
    # ONE dict decides both the count and the write, so the stamp can never describe a cache
    # that was not written: tonight's rebuild, the mass-failure keep (every old entry plus
    # tonight's successes), or the file the shrink abort leaves untouched. A mass-failure
    # night therefore stamps a LOW `uncached`, correctly -- the abort's whole purpose is
    # that the digest still reads yesterday's cache.
    written = ({**old, **st.successes} if mass_failure else old if shrink else st.cache)
    # ...and the rot file this exit actually leaves on disk: the abort paths return before
    # `write_json(ROT_PATH, rot)`, so for them it is the file as it was found.
    rot_written = rot_at_start if (mass_failure or shrink) else rot
    parking = st.parked if parks else ()
    uncached = _uncached(rows, written, parking)
    unvisited = _unvisited(rows, written, rot_written, parking)
    # provenance over what this exit actually writes: fresh reads must never carry an
    # unprovenanced "Israel" (alarm), carried entries may until their board re-scrapes (level)
    fabricated = sum(_unprovenanced(v) for v in st.successes.values())
    legacy_loc = sum(_unprovenanced(v) for k, v in written.items() if k not in st.successes)
    # postings whose url is the LISTING they were found on (434): no fetch layer can ever
    # read them a description. A level with the same anchored-jump alarm as `uncached` —
    # the level itself is ~large and moves with promotions, so only a JUMP is an event.
    listings = {r["company_name"]: r.get("api_url", "") for r in rows}
    ownless = sum(1 for name, v in written.items()
                  for j in v or [] if not _is_own_address(j, listings.get(name, "")))
    alarm = _alarm(st, mass_failure=mass_failure, shrink=shrink,
                   rot_unreadable=rot_state == "unreadable",
                   uncached=uncached, unvisited=unvisited,
                   base=base, row_count=len(rows), fabricated=fabricated,
                   ownless=ownless, own_base=own_base)
    fired = "uncached-up-" in alarm
    base_u, base_r = _next_base(uncached, len(rows), base, fired)
    own_u, own_r = _next_base(ownless, len(rows), own_base, "ownless-up-" in alarm)
    # `embeds` counts rows whose page carried a third-party board the ladder had not read;
    # `embeds_won` the ones the identity gate admitted AND whose API answered with an
    # Israel role. The gap between them is the handoff, and it is the larger half.
    embeds_won = sum(1 for _, s in st.embeds if s.endswith(":won"))
    detail = dict(rows=len(rows), **c, parked=parks, uncached=uncached,
                  unvisited=unvisited, uncached_base=base_u, rows_base=base_r,
                  legacy_loc=legacy_loc, ownless=ownless, ownless_base=own_u,
                  ownless_rows_base=own_r,
                  embeds=len(st.embeds), embeds_won=embeds_won,
                  workers=o.workers, minutes=minutes, via=_via(st.strategies))
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
        # not a measurement: keep every old entry, advance no streak, park nothing.
        # `written` is the SAME dict the stamp counted, built once above -- a second
        # rebuild here is how a stamp starts describing a cache that was not written.
        write_json(CACHE_PATH, written, sort_keys=True)
        stages.stamp("collect", **detail)
        print(f"MASS FAILURE: {c['errors']} of {c['scraped']} rows errored — cache kept "
              f"({len(written)} companies), rot and registry untouched")
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
