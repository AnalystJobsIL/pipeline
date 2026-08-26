#!/usr/bin/env python3
"""Standalone full health sweep — the weekly BACKSTOP to the free detection that pipeline.run
now does inline every day. Fetches every active company and records the same stale-board list
+ baseline via pipeline.health, catching slow drift the daily run might smooth over.

Writes cloud_state/stale.json (the re-resolve queue) + cloud_state/health_baseline.json —
the same two files the digest wrote at 05:00, so this is a second writer of the queue on
Mondays. It carries the same exception text the digest does (until 2026-08-26 it recorded a
bare `status: error`, so a Monday overwrite stripped every `error` reason from stale.json)
and prints the same two `Boards` lines the mail shows, judged against the digest's file.

It is also where an operator corrects a LATCHED baseline, because a baseline is an all-time
high and nothing in the pipeline may lower one:

    python health_check.py --rebase-scrape 74570c6                     # the evidence
    python health_check.py --rebase-scrape 74570c6 --apply "NetApp,…"  # the correction

The report prints every scrape row that is `regressed-to-zero` today with the postings its
baseline was built from at <rev>; `--apply` zeroes the baselines named and drops their stale
rows (`pipeline.health.rebase`). A cached posting cannot be re-extracted, so when the
scraper's extractor changes, only a person can tell a lost role from lost page chrome.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys

from pipeline import fetchers, health, israel


def _cache_at(rev):
    """`scraped_cache.json` as it was at <rev> — a git revision or a path to a JSON file.

    The only way to see the postings a baseline was built from: a cache holds already-
    EXTRACTED cards, so when the extractor changes there is nothing to replay. `{}` when the
    revision or the file cannot be read — an empty report, never a crash."""
    if os.path.exists(rev):
        try:
            return json.load(open(rev, encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    try:
        out = subprocess.run(["git", "show", f"{rev}:scraped_cache.json"],
                             capture_output=True, timeout=60)
        return json.loads(out.stdout.decode("utf-8")) if out.returncode == 0 else {}
    except (ValueError, OSError, subprocess.SubprocessError):
        return {}


def rebase_report(rev, stale_path=health.STALE, baseline_path=health.BASELINE, out=print):
    """Every scrape row that is `regressed-to-zero` today, with its baseline and one line per
    posting the cache held at <rev>: title | location | url.

    EVIDENCE, not a verdict. No heuristic can make this call — on 2026-08-26 all 52 postings
    behind the thirty regressed rows passed today's `clean_scraped` and `is_israel_job`, and
    47 of them were still page chrome ("Sitemap" @ "Israel Jobs", thirteen NetApp nav pages
    @ "Tel Aviv, ISR") while five were real openings. Read it, then name the chrome-only rows
    to `--apply`. Returns the rows reported, {name: [postings]}."""
    stale, baseline, cache = health._load(stale_path), health._load(baseline_path), _cache_at(rev)
    rows = {n: v for n, v in sorted(stale.items())
            if isinstance(v, dict) and v.get("reason") == "regressed-to-zero"
            and (v.get("platform") or "").strip().lower() == "scrape"}
    out(f"=== {len(rows)} scrape rows regressed to zero; their postings at {rev} ===")
    reported = {}
    for name, v in rows.items():
        posts = [p for p in (cache.get(name) or []) if isinstance(p, dict)]
        reported[name] = posts
        out(f"\n{name}  (baseline {health._int(baseline.get(name), 0)}, {len(posts)} cached at {rev})")
        for p in posts:
            # the URL is the evidence — Sanofi's three "Israel" postings are only visibly
            # United States roles at character 44 of the path — so it is barely cut at all
            out(f"    {str(p.get('title') or '')[:60]:60} | {str(p.get('location') or '')[:28]:28} | {str(p.get('url') or '')[:140]}")
        if not posts:
            out("    (nothing cached at that revision — the baseline came from an earlier night)")
    return reported


def _rebase_cli(argv):
    """`--rebase-scrape <rev|path> [--apply "A,B,C"]` — the report, then the correction."""
    rev = argv[argv.index("--rebase-scrape") + 1]
    rebase_report(rev)
    if "--apply" not in argv:
        print("\n(report only; re-run with --apply \"Name,Name\" to zero those baselines)")
        return 0
    names = [n.strip() for n in argv[argv.index("--apply") + 1].split(",") if n.strip()]
    result = health.rebase(names, write=True)
    print(f"\n=== re-based {len(result['rebased'])} of {len(names)} ===")
    for name, old in sorted(result["rebased"].items()):
        print(f"  {name[:34]:35} baseline {old} -> 0, stale row dropped")
    for name, why in sorted(result["refused"].items()):
        print(f"  [XX] {name[:34]:35} {why}")
    return 0


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    results = {}
    for r in rows[1:]:
        if len(r) < 5 or (r[4] or "").strip().lower() != "true":
            continue
        name, plat, tok, api = r[0], r[1], r[2], r[3]
        try:
            jobs = fetchers.fetch_company({"company_name": name, "ats_platform": plat,
                                           "token": tok, "api_url": api})
            il = sum(1 for j in jobs if israel.is_israel_job(j))
            results[name] = {"platform": plat, "n": len(jobs),
                             "status": "ok" if jobs else "empty", "api": api}
            st = "ok" if jobs else "empty"
        except Exception as e:  # noqa: BLE001
            # the class AND the message, query strings stripped first — exactly what
            # pipeline/run.py records, so a Monday sweep does not erase Sunday's reasons
            msg = re.sub(r"\?\S*", "", str(e))[:70]
            why = f"{type(e).__name__}: {msg}"
            results[name] = {"platform": plat, "n": 0, "status": "error", "api": api,
                             "error": why}
            il, st = 0, f"error:{type(e).__name__}"
        print(f"  {name[:26]:27} {st:14} {results[name]['n']:>4}/{il:>3} IL", flush=True)
    previous = health.previous()                       # before record() rewrites the file
    stale = health.record(results)
    for line in health.mail_lines(stale, previous, scanned=results):
        print(f"  boards {line}", flush=True)
    print(f"\n=== {len(results)} checked · {len(stale)} STALE -> {health.STALE} ===", flush=True)


if __name__ == "__main__":
    sys.exit(_rebase_cli(sys.argv) if "--rebase-scrape" in sys.argv else main())
