#!/usr/bin/env python3
"""Walk the WHOLE intake queue with the free evidence rungs and emit a PROPOSAL FILE.

    python drain_queue.py --exhaust "<dir>/hq_s*.json" --out out/queue_proposals.json

Why this exists. `auto_expand` drains the queue at `AUTO_EXPAND_SITE_MAX=25` twice a day,
so the free rung clears ~50 names/day against a queue of 786 that grows ~150/day. The cloud
limit is not cost or politeness: it is the 330-minute job timeout and the shared `repo-state`
concurrency group, because a successful site guess triggers a full `resolve_deep` (~342 s per
name) and a timed-out job may never reach its `if: always()` persist step (`339@registry`).
NONE OF THAT EXISTS LOCALLY -- a previous session walked all 498 names in 293 s with 8
threads. So the walk happens here and the writing happens in `apply_proposals.py`, in
reviewed batches, through the normal identity-gate path.

**This module cannot write the registry, and that is structural rather than a flag.** It
imports no csv writer, names no registry path and has no `--apply`. `tests/test_registry.py`
::`test_the_queue_drain_cannot_write_the_registry` asserts that over the AST, so the module
never enters `tools/mutate.py::_registry_writers()` and needs no `GATE_CALLERS` entry. A
dry-run you can turn off is a dry-run somebody turns off at 02:00.

THE RUNGS, and why in this order

    R0  exhaust replay   0 requests    a previous night's `listing_hunt` sweep, replayed
    R1  comeet-token     1 GET         the rung that did not exist -- see below
    R2  slug probe       <=18 GET      auto_expand._probe_resolve, imported not copied
    R3  own-site guess   <=4 GET       auto_expand._site_from_guess
    R4  page + gate      1 GET         whatever address survived R0-R3

R1 sits above the shipped probe for two measured reasons. `probe_ats._PLATFORMS` has **no
comeet entry**, so the slug probe can never find a Comeet board however many slugs it tries --
and Comeet is 133 of the 969 active rows, the second-largest platform in the registry. And a
native ATS row is fetched by API on every digest, while a `scrape` row contributes NOTHING
until `refresh_scrape_cache.py` puts it in `scraped_cache.json` (233 active scrape rows were
in exactly that state on 2026-08-28). Converting a name to a native row is therefore worth
strictly more than parking it as a page to scrape, and it is the only rung whose output is
complete the moment it is written.

`listing_hunt.hunt_one` is deliberately NOT a rung. It drives Playwright (~39 s/name measured
over the 488-name exhaust), two sync Playwright instances in one thread throw
(`listing_hunt.py:300`), and the 19:00 cron already feeds it 60 minutes a night through
`queue_targets()`. This is the free, threadable, HTTP-only complement to that cron, not a
replacement for it.

WHAT IT SPENDS: nothing. Not by intention -- by four locks, because the previous session
asserted "zero Bright Data credits" in a commit message while the key was set. See
`_lock_the_paid_rungs()`.
"""
from __future__ import annotations

import argparse
import concurrent.futures as _cf
import json
import os
import re
import sys
import time
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------------------- #
# The four locks. These run BEFORE `pipeline.identity_gate` is imported, on purpose.
# --------------------------------------------------------------------------------------- #
def _lock_the_paid_rungs():
    """Make a Bright Data charge unreachable, four independent ways.

    "I will not export BRIGHTDATA_API_KEY" is NOT sufficient on the operator's machine.
    `bd_rescue._load_secrets()` reads `secrets.env` from the repo root and `setdefault`s
    every key in it into `os.environ`, and EIGHT root modules call it (audit_empty_rows,
    bd_rescue, crack_walled, deep_validate, discovery_daily, listing_hunt, registry_health,
    bd_employees). One convenience import re-arms `identity_gate`'s paid rung, and the
    failure is silent because `identity_gate` swallows the exception (`:549-551`).

      1. env: `PAGE_UNLOCK_BUDGET=0`. `identity_gate._UNLOCK_BUDGET` is read AT IMPORT
         (`:80`), so this must happen first; with it 0 the `_UNLOCK_SPENT < _UNLOCK_BUDGET`
         conjunct is false forever.
      2. env: the key itself is removed from this process.
  3. (REMOVED 2026-08-28, and the removal is the lesson.) This slot held
         `sys.modules["bd_rescue"] = None`, so the lazy `from bd_rescue import unlock` would
         raise before the counter increments. It works -- and it poisons the whole PROCESS:
         under pytest it made every test that imports `bd_rescue`, directly or through
         `discovery_daily`, fail with `import of bd_rescue halted; None in sys.modules`.
         77 of them. A lock whose blast radius is the interpreter is not a lock, it is a
         landmine for whoever imports this module next. Locks 1 and 4 are sufficient and
         have no blast radius at all.
      4. every gate call in this module passes `html=` of a page we already hold and only
         when it is >= 2000 chars -- the condition under which `page_names_company` neither
         fetches nor unlocks (`:536`).

    Lock 4 alone is the real argument; 1 and 2 exist because lock 4 is a property of code I
    have to keep true, while they are properties of the process. `_receipt()` prints the
    counter at the end of every run so the claim is a number rather than a sentence."""
    os.environ["PAGE_UNLOCK_BUDGET"] = "0"
    os.environ.pop("BRIGHTDATA_API_KEY", None)
    os.environ.pop("BRIGHTDATA_ZONE", None)


_lock_the_paid_rungs()

from pipeline import identity_gate as _gate           # noqa: E402  (after the locks)

# Lock 1 again, on the module object. The env form is ORDER-DEPENDENT -- the gate reads
# PAGE_UNLOCK_BUDGET at ITS import (`identity_gate.py:80`), so if anything imported the gate
# before this module the variable arrives too late and the budget is already 100. In this
# module's own process the order is guaranteed (it is `__main__`), but the guard imports it
# into a process that imported the gate first, which is the adversarial order and the one
# that found this. Setting the attribute is the only form that does not depend on who
# imported what.
_gate._UNLOCK_BUDGET = 0
from pipeline.aggregators import is_aggregator        # noqa: E402
from pipeline.companies import load_companies         # noqa: E402
from pipeline.firmographics import looks_like_junk    # noqa: E402
from pipeline.recruiters import is_recruiter          # noqa: E402


def _receipt():
    """The Bright Data claim, as a number. `_UNLOCK_SPENT` is the gate's own counter."""
    spent = getattr(_gate, "_UNLOCK_SPENT", None)
    print("unlock_spent=%s (budget %s)" % (spent, getattr(_gate, "_UNLOCK_BUDGET", "?")),
          flush=True)
    assert spent == 0, "the drain spent %r Bright Data unlocks" % (spent,)


# --------------------------------------------------------------------------------------- #
# `auto_expand` is imported for its rungs, and its import-time bindings have to be neutered
# first: `DRY_RUN` is bound from `sys.argv` at :79 and SITE_MAX/SITE_BUDGET_S from env at
# :369-370. We drive `_site_from_guess` ourselves and never call `main()`, so the values do
# not matter -- but a stray `--apply` on OUR argv must not become auto_expand's `DRY_RUN`.
# Import, never copy: a private copy of `_lossless_slugs` is how the refusal policy drifts.
# --------------------------------------------------------------------------------------- #
_argv, sys.argv = sys.argv, ["auto_expand"]
os.environ.setdefault("AUTO_EXPAND_SITE_MAX", "100000")
os.environ.setdefault("AUTO_EXPAND_SITE_BUDGET_S", "1")
import auto_expand as AE                               # noqa: E402
import probe_ats                                       # noqa: E402
sys.argv = _argv

QUEUE_PATH = "research_companies.json"
COMEET_URL = re.compile(r"comeet\.com/jobs/([^/?#]+)/([0-9A-Za-z]{2}\.[0-9A-Za-z]{3})", re.I)
COMEET_API = re.compile(r"comeet\.com/careers-api/2\.0/company/([0-9A-Za-z]{2}\.[0-9A-Za-z]{3})",
                        re.I)
# The hosted Comeet page carries the API token in plain HTML. Verified live 2026-08-28 on
# birdaero/97.006 (19 positions) and xsightlabs/46.00C (15) through the real fetcher. This is
# what makes the rung free: `comeet_resolve` reads `window.comeetvar` with Playwright, and a
# previous session found no comeetvar on the JS shell at all.
COMEET_TOKEN = re.compile(r"[\"']?token[\"']?\s*[:=]\s*[\"']([0-9A-Fa-f]{24,48})[\"']")

NAME_S = 45.0            # per-name deadline
# The mass-zero abort, and it is measured over the REPLAY SUBSET rather than the queue.
#
# The first version compared the whole run's yield to the 488-name exhaust's 33% found rate
# and aborted at 13.5%. That was a mis-calibration, not a catch: the exhaust's 33% is
# `listing_hunt`'s number -- Playwright plus a search engine -- and these rungs are HTTP-only,
# so the comparison was against a different rung. Worse, it lumped two populations together:
# the 296 names a previous night already answered, where a low rate really would mean
# something broke, and the ~490 never-hunted names, where a low rate is the measurement
# (`auto_expand`'s own sweep found a guessable board for only 7.9% of them).
#
# So the floor sits on the replay subset, which has a known expected value near 1.0: a name
# whose exhaust record says `found` with an address should produce a proposal almost always.
# If THAT collapses, the network or a rung is broken and no proposal file is written. The
# unhunted tail's rate is reported and never gates -- it is the thing being measured.
MIN_REPLAY_YIELD = 0.60


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _comeet_api(uid, token):
    return ("https://www.comeet.com/careers-api/2.0/company/%s/positions?token=%s"
            % (uid, token))


# --------------------------------------------------------------------------------------- #
# R1 -- the rung the ladder did not have
# --------------------------------------------------------------------------------------- #
def comeet_from_hosted_page(name, url, deadline):
    """`comeet.com/jobs/<slug>/<uid>` -> a native comeet row, free and with no browser.

    Returns an evidence dict or None. Three facts come back that no other rung in this repo
    gets for free, and the third is the interesting one:

      * the uid, which is already in the URL;
      * the API token, from the hosted page's own HTML (see COMEET_TOKEN);
      * **`company_name`, asserted by the board itself.** Every other identity signal on this
        path is derived from the name we started with -- which is exactly `317@registry`'s
        complaint about `board_vouches`, where a slug synthesised from the name near-equals a
        target by construction and carries zero bits. The Comeet API states whose board it is
        in a field, independently. `board_vouches` returns None for a Comeet uid by design
        ("a uid vouches for nothing"), so without this the only identity evidence would be
        the hosted page's own text, and the page is the thing being questioned.

    The fetch is `auto_expand._get_page`, so it inherits that function's total deadline and
    400 KB cap rather than a fresh `timeout=` that a slow trickle can defeat."""
    m = COMEET_URL.search(url or "")
    if not m:
        return None
    slug, uid = m.group(1), m.group(2)
    final, html = AE._get_page(url, deadline)
    if not html:
        return {"why": "comeet-unread", "uid": uid, "slug": slug}
    t = COMEET_TOKEN.search(html)
    if not t:
        # A real per-board outcome, not a failure of the rung: orchid_security/4A.001 has no
        # token in its HTML. Recorded so the count is honest and the row can be re-tried by
        # the browser rung that owns that case.
        return {"why": "comeet-notoken", "uid": uid, "slug": slug,
                "page_chars": len(html), "final_url": final}
    return {"uid": uid, "slug": slug, "token": t.group(1), "api": _comeet_api(uid, t.group(1)),
            "page_chars": len(html), "final_url": final, "html": html}


def comeet_verify(name, api):
    """Fetch through the PRODUCTION path and count Israel jobs the production way.

    Never a local location predicate. An ad-hoc "is 'israel' in the location blob" check over
    the raw API JSON reported 0 Israel jobs for a board the exhaust had measured at 19, which
    would have refused a real board on the strength of my own bug. `fetch_comeet` normalises
    the posting into the common job shape and `israel.is_israel_job` is what every other
    consumer applies to it."""
    from pipeline.fetchers import fetch_company
    from pipeline.israel import is_israel_job
    jobs = fetch_company({"company_name": name, "ats_platform": "comeet",
                          "token": "", "api_url": api})
    il = [j for j in jobs if is_israel_job(j)]
    return jobs, il


# --------------------------------------------------------------------------------------- #
# the per-name walk
# --------------------------------------------------------------------------------------- #
def walk_one(entry, exhaust, boards_now, names_now):
    """One queue entry -> a proposal dict, or None.

    None means "learned nothing", and it is NOT a park. `auto_expand`'s own docstring makes
    the distinction and an adversarial pass proved the cost of losing it: a name the rung
    declines must keep its place in the queue, because parking it creates a row, the 05:00
    prune then drops the name from the queue because the registry "holds" it, and a bad
    network night retires 786 companies with a success line. Nothing here parks anything --
    but emitting a `refused` record for a name we merely failed to reach would let the
    applier park it, so the abstention has to happen at this end."""
    name = (entry.get("name") or "").strip()
    seed = (entry.get("careers_url") or "").strip()
    if not name or is_recruiter(name) or looks_like_junk(name):
        return None
    deadline = time.time() + NAME_S
    ex = exhaust.get(name.lower().strip())
    url = seed
    rung = ""
    if ex and ex.get("verdict") == "found" and ex.get("url"):
        url, rung = ex["url"], "exhaust"

    # ---- R1: comeet -----------------------------------------------------------------
    for cand in (url, seed):
        if not COMEET_URL.search(cand or ""):
            continue
        got = comeet_from_hosted_page(name, cand, deadline)
        if not got or got.get("why"):
            break
        key = ("comeet", got["uid"].lower())
        if key in boards_now:
            return {"name": name, "kind": "refused", "rung": "comeet-token",
                    "why": "dup-board", "evidence": {"uid": got["uid"], "seed_url": seed}}
        try:
            jobs, il = comeet_verify(name, got["api"])
        except Exception as e:                                    # noqa: BLE001
            return {"name": name, "kind": "unverified", "rung": "comeet-token",
                    "why": "fetch:%s" % e.__class__.__name__,
                    "evidence": {"uid": got["uid"], "api_url": got["api"], "seed_url": seed}}
        asserts = sorted({(j.get("company") or "") for j in jobs if j.get("company")})
        # the gate, with the page WE hold, >= 2000 chars: no fetch, no unlock (lock 4)
        html = got["html"] if len(got["html"]) >= 2000 else ""
        verdict = _gate.activation_verdict(name, got["api"], len(il), html=html)
        return {"name": name, "kind": "ats", "rung": rung or "comeet-token",
                "platform": "comeet", "token": got["uid"], "api_url": got["api"],
                "proposed_active": bool(il) and verdict == "ok",
                "note_if_applied": "queue-drain %s comeet-token; %d/%d IL"
                                   % (_today(), len(jobs), len(il)),
                "evidence": {
                    "seed_url": seed, "candidate_url": cand, "final_url": got.get("final_url"),
                    "page_chars": got.get("page_chars"), "hosted_slug": got["slug"],
                    "n_jobs": len(jobs), "n_il": len(il),
                    "il_titles": [j.get("title") for j in il][:8],
                    "board_asserts_company": asserts,
                    "board_name_matches": any(_norm(a) == _norm(name) for a in asserts),
                    "gate": "activation_verdict", "gate_verdict": verdict,
                    "gate_html_held": bool(html),
                    "board_vouches": _gate.board_vouches(name, got["uid"], got["api"]),
                    "is_aggregator": is_aggregator(got["api"]),
                }}

    # ---- R0 replay of a non-comeet exhaust hit ---------------------------------------
    if rung == "exhaust":
        return _page_proposal(name, url, seed, "exhaust", deadline, ex.get("il") or 0)

    # ---- R2: the slug probe -----------------------------------------------------------
    slugs = AE._lossless_slugs(name, _handle(entry))
    if slugs:
        payload, why = AE._probe_resolve(name, _handle(entry), boards_now, deadline)
        if payload:
            plat, slug, board_url, n_all, n_il, html = payload
            return {"name": name, "kind": "ats", "rung": "slug-probe", "platform": plat,
                    "token": slug, "api_url": board_url,
                    "proposed_active": True,
                    "note_if_applied": "queue-drain %s slug-probe; %d/%d IL"
                                       % (_today(), n_all, n_il),
                    "evidence": {"seed_url": seed, "candidate_url": board_url,
                                 "n_jobs": n_all, "n_il": n_il,
                                 "page_chars": len(html or ""),
                                 "gate": "deferred-to-applier",
                                 "board_vouches": _gate.board_vouches(name, slug, board_url),
                                 "is_aggregator": is_aggregator(board_url)}}
        if why and why not in ("probe-noboard", "probe-noslug"):
            return {"name": name, "kind": "refused", "rung": "slug-probe", "why": why,
                    "evidence": {"seed_url": seed}}

    # ---- R3/R4: the company's own site -------------------------------------------------
    h = _handle(entry)
    if h:
        got = AE._site_from_guess(name, h)
        if got:
            return _page_proposal(name, got[0], seed, "own-site", deadline, 0,
                                  html=got[1])
    return None


def _handle(entry):
    """The LinkedIn handle, and ONLY when the queue really asserts one.

    `_lossless_slugs` gives the handle a slot because it is "the one identity in a queue entry
    that is not name-derived". Measured 2026-08-28: that is false for most of the queue. 524
    of 786 entries come from secrethunter, whose `slug` is generated FROM the name -- 494 of
    496 normalise to it exactly, carrying zero bits. Feeding those to `_site_from_guess` binds
    a domain to a guess we made rather than to a handle LinkedIn asserted, which is the
    two-way binding's whole point. So the slot is filled only by an `il.linkedin.com` entry
    whose slug actually differs from the name."""
    host = urllib.parse.urlparse(entry.get("careers_url") or "").netloc.lower()
    slug = (entry.get("slug") or "").strip()
    if "linkedin.com" not in host or not slug:
        return ""
    return "" if _norm(slug) == _norm(entry.get("name")) else slug


def _page_proposal(name, url, seed, rung, deadline, il_hint, html=None):
    """A careers PAGE -> a `scrape` proposal. Never activated here.

    The counts on this path are a previous night's, and `il >= 1` is only a gate while it is
    current -- so the proposal records what was seen and the applier decides, with the row's
    age in hand. `is_aggregator` runs before anything else because it answers a different
    question from the identity gate: "is this a board for many employers" rather than "is this
    THIS company's page", and an aggregator's company page passes the second by naming the
    company correctly. That is how `jobkarov.com/Search/Company/16928` -- Menora Mivtachim's
    page on an Israeli job board -- was activated on 2026-08-27."""
    if not url:
        return None
    if html is None:
        _final, html = AE._get_page(url, deadline)
    html = html or ""
    agg = is_aggregator(url)
    ok = None
    if not agg and len(html) >= 2000:
        ok = _gate.ok_to_write(name, url, html=html)
    return {"name": name, "kind": "scrape", "rung": rung, "platform": "scrape",
            "token": "", "api_url": url,
            "proposed_active": False,          # the applier re-verifies; see apply_proposals
            "note_if_applied": "queue-drain %s %s; no IL listing; monitored candidate"
                               % (_today(), rung),
            "evidence": {"seed_url": seed, "candidate_url": url, "page_chars": len(html),
                         "n_il_when_hunted": il_hint, "is_aggregator": agg,
                         "gate": "ok_to_write", "gate_verdict": ok,
                         "gate_html_held": len(html) >= 2000}}


def _today():
    import datetime as dt
    return dt.date.today().isoformat()


# --------------------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exhaust", default="", help="glob of hq_s*.json records to replay")
    ap.add_argument("--out", default="out/queue_proposals.json")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated names (a scoping aid)")
    ap.add_argument("--run-s", type=float, default=3600.0)
    ap.add_argument("--min-replay-yield", type=float, default=MIN_REPLAY_YIELD,
                    help="abort without writing if the REPLAYABLE names yield under this")
    a = ap.parse_args(argv)

    with open(QUEUE_PATH, encoding="utf-8") as f:
        queue = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in queue if (e.get("name") or "").strip().lower() not in have]
    if a.only:
        want = {x.strip().lower() for x in a.only.split(",") if x.strip()}
        todo = [e for e in todo if (e.get("name") or "").strip().lower() in want]
    if a.limit:
        todo = todo[:a.limit]

    exhaust = {}
    if a.exhaust:
        import glob
        for fn in glob.glob(a.exhaust):
            try:
                for r in json.load(open(fn, encoding="utf-8")):
                    exhaust[(r.get("name") or "").lower().strip()] = r
            except Exception as e:                                # noqa: BLE001
                print("  exhaust unreadable %s: %r" % (fn, e), flush=True)

    boards_now = AE._boards_now()
    names_now = AE._names_now()
    print("drain: queue %d, unresolved %d, exhaust records %d, threads %d"
          % (len(queue), len(todo), len(exhaust), a.threads), flush=True)

    out, t0 = [], time.time()
    bound = "queue"
    # ONE `bounded_http` context, in the main thread, around the whole pool. It patches the
    # module global `pipeline.http._request` and restores it in `finally` (probe_ats.py:54);
    # entering it per-thread races that restore and leaks a 4 s/1-retry patch into whatever
    # imports `pipeline.http` next -- which probe_ats's own docstring names as a shipped bug.
    with probe_ats.bounded_http():
        with _cf.ThreadPoolExecutor(max_workers=a.threads) as pool:
            futs = {pool.submit(walk_one, e, exhaust, boards_now, names_now): e for e in todo}
            for i, fut in enumerate(_cf.as_completed(futs), 1):
                if time.time() - t0 > a.run_s:
                    bound = "clock:run"
                    for f2 in futs:
                        f2.cancel()
                    break
                try:
                    r = fut.result()
                except Exception as e:                            # noqa: BLE001
                    r = {"name": futs[fut].get("name"), "kind": "unverified",
                         "rung": "", "why": "crash:%s" % e.__class__.__name__}
                if r:
                    out.append(r)
                if i % 50 == 0:
                    print("  ... %d/%d walked, %d proposals, %ds"
                          % (i, len(todo), len(out), time.time() - t0), flush=True)

    hits = {r["name"] for r in out if r.get("kind") in ("ats", "scrape")}
    # the two populations, reported apart because they mean different things
    replayable = {(e.get("name") or "").strip() for e in todo
                  if (exhaust.get((e.get("name") or "").lower().strip()) or {}
                      ).get("verdict") == "found"}
    fresh = {(e.get("name") or "").strip() for e in todo} - replayable
    r_rate = (len(hits & replayable) / len(replayable)) if replayable else 1.0
    f_rate = (len(hits & fresh) / len(fresh)) if fresh else 0.0
    by_rung = {}
    for r in out:
        by_rung[r.get("rung") or "-"] = by_rung.get(r.get("rung") or "-", 0) + 1
    print("drain: walked %d, proposals %d (ats %d, scrape %d, refused %d, unverified %d), "
          "bound=%s, %ds"
          % (len(todo), len(out),
             sum(1 for r in out if r["kind"] == "ats"),
             sum(1 for r in out if r["kind"] == "scrape"),
             sum(1 for r in out if r["kind"] == "refused"),
             sum(1 for r in out if r["kind"] == "unverified"),
             bound, time.time() - t0), flush=True)
    print("drain: replay %d/%d = %.1f%% (the GATE) . never-hunted %d/%d = %.1f%% "
          "(the MEASUREMENT) . by rung %s"
          % (len(hits & replayable), len(replayable), 100 * r_rate,
             len(hits & fresh), len(fresh), 100 * f_rate,
             sorted(by_rung.items(), key=lambda x: -x[1])), flush=True)
    _receipt()

    if replayable and r_rate < a.min_replay_yield:
        # A mass-zero result is a broken run, not a measurement (CLAUDE.md rule 2) -- but
        # only the replay subset can tell the two apart. These names were ANSWERED by a
        # previous night with an address in hand, so a collapse here is the network or a
        # rung, and writing a proposal file would launder it into verdicts.
        print("::error::replay yield %.1f%% is under --min-replay-yield %.1f%% (%d of %d "
              "names a previous sweep had already answered produced nothing) -- NO proposal "
              "file written. Diagnose the rung; this is not a measurement."
              % (100 * r_rate, 100 * a.min_replay_yield,
                 len(replayable) - len(hits & replayable), len(replayable)), flush=True)
        return 1

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"generated": _today(), "queue_entries": len(queue), "walked": len(todo),
                   "exhaust_records": len(exhaust), "bound": bound,
                   "unlock_spent": getattr(_gate, "_UNLOCK_SPENT", None),
                   "registry_rows": len(have), "proposals": out},
                  f, ensure_ascii=False, indent=1, sort_keys=True)
    print("wrote %s (%d proposals)" % (a.out, len(out)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
