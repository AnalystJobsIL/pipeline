"""How long will a scope change take to reach every role? (lane: classifier)

A contract change marks every cached verdict superseded, and `CLASSIFY_REJUDGE_CAP` bounds how
many are re-bought per run. The obvious arithmetic — pool / cap — is wrong, and this exists
because a session published that arithmetic and it was believed: a superseded `|jd` verdict
whose role has no description **this run** cannot be re-judged at all, because re-judging a
JD-backed verdict on a bare title is the one thing the bare/jd split forbids. No cap reaches
those. Only a description does.

So it forecasts the four cohorts a run actually encounters, from the two committed caches:

    python tools/drain_forecast.py                 # today's contract
    python tools/drain_forecast.py --active-only   # ...restricted to rows the run would fetch

READ-ONLY, and it SPENDS NOTHING: it walks the same code the run walks (`is_israel_job`,
`_relevance`, `_NOT_A_JOB`, `looks_like_jd`, `cache_keys`, `Classifier._lookup`) and stops
one line short of the call.

**It is a floor, and here is why.** The caches hold what the last refresh committed — 4,429
Israel postings on 2026-08-30 against the 7,173 a live run saw on 2026-08-29 — because a run
also fetches ~2,000 postings live from API boards, and `jdfill.maybe_fill` fills descriptions
inline at judgement time, which converts "unreachable" into "queued" for roles this cannot
see. Quote it as a shape, never as a prediction of tomorrow's `classify:` line.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import israel, seniority, store                 # noqa: E402
from pipeline.jdfill import looks_like_jd                     # noqa: E402


def _flatten(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    return [v for vs in d.values() for v in (vs if isinstance(vs, list) else [vs])
            if isinstance(v, dict)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--cap", type=int, default=int(os.environ.get("CLASSIFY_REJUDGE_CAP", 60)))
    ap.add_argument("--active-only", action="store_true",
                    help="only postings whose employer has an active companies.csv row")
    ap.add_argument("--group/--no-group", dest="group", default=True,
                    help="group by store.merge_key first, as classify_grouped does (default on)")
    a = ap.parse_args()

    postings = []
    for name in ("discovered_cache.json", "scraped_cache.json"):
        p = os.path.join(a.root, name)
        if os.path.exists(p):
            postings += _flatten(json.load(io.open(p, encoding="utf-8")))

    if a.active_only:
        with io.open(os.path.join(a.root, "companies.csv"), encoding="utf-8") as f:
            live = {r["company_name"].strip().lower() for r in csv.DictReader(f)
                    if r["active"].strip().lower() == "true"}
        postings = [j for j in postings if str(j.get("company") or "").strip().lower() in live]

    con = sqlite3.connect("file:%s?mode=ro"
                          % os.path.join(a.root, "cloud_state", "seen.db").replace("\\", "/"),
                          uri=True)
    cache = {k: bool(v) for k, v in con.execute("select title_key, verdict from llm_cache")}
    con.close()
    clf = seniority.Classifier(use_llm=True, llm_cache=cache, cap=10 ** 6, rejudge_cap=a.cap)

    # the run judges once per ROLE, on its fullest copy (roles.classify_grouped)
    if a.group:
        groups = collections.OrderedDict()
        for j in postings:
            groups.setdefault(store.merge_key(j), []).append(j)
        heads = [sorted(v, key=lambda x: -len(str(x.get("description") or "")))[0]
                 for v in groups.values()]
    else:
        heads = postings

    enc = collections.Counter()
    yes_stale = []
    for j in heads:
        if not israel.is_israel_job(j):
            continue
        title_l = (j.get("title") or "").lower()
        company_l = (j.get("company") or "").lower()
        rel = seniority._relevance(title_l, company_l)
        if rel in ("excluded", "none") or seniority._NOT_A_JOB.search(title_l):
            continue
        sen = seniority._seniority(title_l)
        has_text = looks_like_jd(str(j.get("description") or "").strip())
        key, jd_key, bare_key, legacy_key = seniority.cache_keys(j, has_text, clf.contract)
        prior = clf._lookup(jd_key, bare_key, legacy_key)
        # the shortcut sits BELOW the lookup in production (2026-08-30): a cached verdict
        # outranks a title, or a role whose fill fails flip-flops on alternate mornings
        if rel == "strong" and sen == "senior" and not has_text and prior is None:
            enc["keyword-accept (nothing judged, no text)"] += 1
            continue
        if prior is None:
            enc["fresh -> one call"] += 1
            continue
        if not (prior[1] or not has_text):
            enc["bare verdict + text arrived -> upgrade call"] += 1
            continue
        if prior[3]:
            enc["current contract -> served, no call"] += 1
        elif not (has_text or not prior[1]):
            enc["stale, UNREACHABLE (no description this run)"] += 1
        elif prior[0]:
            enc["stale YES -> re-judged, NOT capped"] += 1
            yes_stale.append((j.get("company"), j.get("title")))
        else:
            enc["stale NO -> re-judged, capped"] += 1

    no_q = enc["stale NO -> re-judged, capped"]
    yes_q = enc["stale YES -> re-judged, NOT capped"]
    fresh = enc["fresh -> one call"] + enc["bare verdict + text arrived -> upgrade call"]
    print("contract %s   cap %d   %s   %s"
          % (clf.contract, a.cap, "active-only" if a.active_only else "all cached rows",
             "grouped" if a.group else "ungrouped"))
    print()
    for k, v in enc.most_common():
        print("  %5d  %s" % (v, k))
    print()
    print("  first run buys      %d calls  (fresh %d + stale YES %d + stale NO %d of %d)"
          % (fresh + yes_q + min(no_q, a.cap), fresh, yes_q, min(no_q, a.cap), no_q))
    print("  the BOARD turns over in 1 run: every stale YES is re-judged uncapped")
    print("  the stale-NO queue empties in %d run(s) at cap %d"
          % (math.ceil(no_q / a.cap) if a.cap else 0, a.cap))
    print("  UNREACHABLE at any cap: %d - these wait on jd-text, not on a number"
          % enc["stale, UNREACHABLE (no description this run)"])
    if yes_stale:
        print("\n  the stale YES cohort (what leaves or stays on the board, run 1):")
        for c, t in yes_stale:
            print("     %-24s | %s" % (str(c)[:24], str(t)[:60]))


if __name__ == "__main__":
    main()
