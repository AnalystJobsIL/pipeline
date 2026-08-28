# -*- coding: utf-8 -*-
"""Measure the title gate's FALSE-NEGATIVE rate (lane: classifier).

`pipeline.seniority._relevance` decides, from the title alone, which postings ever get a
description fetched (`enrich_scrape_jd.py:85`, `pipeline/jdfill.py:865`) and which are
rejected before the LLM tier ever sees them. It is a hand-maintained regex, and until
2026-08-28 nobody had measured what it throws away.

This asks the production seam -- the same rules, model and schema the digest uses -- to judge
the postings `_relevance` REJECTED, and reports how many of them the classifier would have
accepted had it been allowed to look. It is a measurement tool, not part of any run: nothing
imports it and no workflow calls it.

    python tools/measure_title_gate.py --cache scraped_cache.json \
        --baseline old_cache.json --tier rejected --out out/title_gate.json

`--baseline` restricts the corpus to boards the baseline did not have, which is how the
2026-08-28 measurement was scoped to the 65 boards cached that morning. `--tier passing`
judges the other side instead -- the postings the gate let through -- which is how the
regression set for those boards was produced.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import israel, seniority  # noqa: E402
from pipeline.llm import LLMUnavailable  # noqa: E402

REJECTED = ("excluded", "none")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def corpus(cache, baseline=None, tier="rejected", israel_only=True):
    """Every posting on the boards under test, bucketed by what the title gate said."""
    boards = cache if not baseline else {k: v for k, v in cache.items() if k not in baseline}
    out = []
    for company, jobs in boards.items():
        for j in jobs:
            j = dict(j, company=j.get("company") or company)
            if israel_only and not israel.is_israel_job(j):
                continue
            rel = seniority._relevance((j.get("title") or "").lower(),
                                       (j.get("company") or "").lower())
            want = rel in REJECTED if tier == "rejected" else rel not in REJECTED
            if want or tier == "all":
                out.append((rel, j))
    return boards, out


_SCRATCH = os.path.join(tempfile.gettempdir(), "gate-scratch")


def judge(job, model, timeout):
    """One production-contract verdict, or ('ERROR', why). `cwd` is a scratch directory that
    must EXIST -- never the repo, or every call reads CLAUDE.md into its prompt."""
    os.makedirs(_SCRATCH, exist_ok=True)
    try:
        r = seniority._claude(seniority._posting(job), model=model, timeout=timeout,
                              cwd=_SCRATCH)
    except LLMUnavailable as e:
        return "ERROR", f"{e.kind}: {e}"
    return (r["verdict"] or "OFF-SCHEMA"), r["reason"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="scraped_cache.json")
    ap.add_argument("--baseline", default="")
    ap.add_argument("--tier", default="rejected", choices=["rejected", "passing", "all"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=seniority.LLM_MODEL)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default="out/title_gate.json")
    ap.add_argument("--dry-run", action="store_true", help="bucket the corpus, spend nothing")
    a = ap.parse_args(argv)

    cache = _load(a.cache)
    baseline = _load(a.baseline) if a.baseline else None
    boards, items = corpus(cache, baseline, a.tier)
    buckets = Counter(rel for rel, _ in items)
    print(f"boards under test: {len(boards)} · postings judged by the gate: "
          f"{sum(len(v) for v in boards.values())}", flush=True)
    print(f"tier={a.tier}: {len(items)} postings  {dict(buckets)}", flush=True)
    if a.limit:
        items = items[:a.limit]
    if a.dry_run:
        return 0

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    lock, done, t0 = threading.Lock(), [0], time.time()

    def one(pair):
        rel, j = pair
        verdict, reason = judge(j, a.model, a.timeout)
        with lock:
            done[0] += 1
            if done[0] % 25 == 0:
                print(f"  {done[0]}/{len(items)}  {time.time() - t0:.0f}s", flush=True)
        return {"company": j.get("company"), "title": j.get("title"),
                "location": j.get("location"), "url": j.get("url"),
                "desc_len": len(str(j.get("description") or "")),
                "relevance": rel, "seniority": seniority._seniority((j.get("title") or "").lower()),
                "verdict": verdict, "reason": reason}

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(one, items))

    tally = Counter(r["verdict"] for r in rows)
    judged = tally["YES"] + tally["NO"]
    yes = tally["YES"]
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"tier": a.tier, "model": a.model, "boards": len(boards),
                   "contract": seniority.CONTRACT, "tally": dict(tally), "rows": rows},
                  fh, ensure_ascii=False, indent=1)

    print(f"\n=== tier={a.tier} · {len(rows)} judged in {time.time() - t0:.0f}s ===")
    print(f"verdicts: {dict(tally)}")
    if judged:
        label = "FALSE-NEGATIVE rate" if a.tier == "rejected" else "accept rate"
        print(f"{label}: {yes}/{judged} = {100.0 * yes / judged:.1f}%  "
              f"(of {len(items)} in tier, {tally['ERROR'] + tally['OFF-SCHEMA']} unanswered)")
    for r in rows:
        if r["verdict"] == "YES":
            print(f"  YES  [{r['relevance']}] {r['company']} | {r['title']} | {r['reason'][:110]}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
