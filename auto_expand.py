#!/usr/bin/env python3
"""Self-draining resolver. Each run takes the next batch of companies that are researched but not
yet in companies.csv, resolves them (iframe-ATS / scrape / follow-jobs-link via resolve_deep), and
writes results DIRECTLY into companies.csv + scraped_cache.json. Scheduled in the cloud it keeps
shrinking the unresolved set every run until it reaches zero — no PC, no babysitting.

Env:  AUTO_EXPAND_LIMIT (default 200) companies per run.
Prints the remaining-unresolved count so the workflow / log shows progress.

**This tool WRITES BY DEFAULT**, unlike every other registry tool, which is dry-run until
`--apply`. The auto-expand workflow invokes it with no flags, so the default cannot be
flipped from here without silently disabling the 08:00/20:00 cron (that is a workflow
change: docs/BACKLOG.md, "auto_expand writes by default"). Until then it says so on
startup, and `--dry-run` gives an agent a safe way to inspect the batch — added 2026-08-23
after a routine dry-run of the nightly chain appended two junk rows ("Qualitest acq",
"Keter", both on secrethunter.io aggregator URLs) to the live registry.

Usage: python auto_expand.py [--dry-run]
"""
from __future__ import annotations

import sys

import csv
import json
import os
from urllib.parse import urlparse

from pipeline.aggregators import is_aggregator as _is_agg_url
from pipeline import identity_gate as _gate
from pipeline.companies import CSV_PATH, load_companies
from resolve_deep import resolve

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



DRY_RUN = "--dry-run" in sys.argv


def _load_cache():
    try:
        with open("scraped_cache.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _row_for_scrape(name, jobs2, good_url, seed_url, cache):
    """The scrape row builder — the seam a test can reach, like `_row_for_ats` below.

    This branch lived inline in `main()`, and `main()` writes through the ABSOLUTE
    `CSV_PATH`, so no fixture could drive it without touching the real registry. The
    mutation catalogue carried M1/M2/M3 for this gate and all three SURVIVED a full sweep:
    the gate existed, and nothing could prove it did anything.

    Order matters and is preserved: `is_aggregator` first (a "similar jobs" sidebar is
    OTHER companies' postings — the Telegram bridge seeds job-post links as careers_url),
    then the identity gate, because `is_aggregator` asks "is this a job board for many
    employers", NOT "is this THIS company's page" — FairFly was activated off
    fireflyspace.com by a path with exactly this shape. `cache` is written only on accept.
    """
    from pipeline.aggregators import is_aggregator
    if is_aggregator(good_url):
        return [name, "scrape", good_url, good_url, "false",
                "aggregator URL; resolve real careers page before activating"]
    if not _gate.activation_ok(name, good_url, len(jobs2)):
        # SEED url, not the refused page -- the same rule `_row_for_ats` and
        # `retry_unreachable._row_for` follow (docs/BACKLOG.md 54): `good_url` is a
        # FOLLOWED link that routinely leaves the company's own host, and a refused
        # ATS-hosted page persisted into cols 2-3 puts a foreign host into the row's
        # address, which `identity_gate.is_walled` reads as crack-pool membership.
        return [name, "scrape", seed_url, seed_url, "false",
                "scraped page is not this company's; no listing found"]
    cache[name] = jobs2
    return [name, "scrape", good_url, good_url, "true",
            f"auto-expand scrape; {len(jobs2)} IL"]


def _row_for_ats(payload, seed_url):
    """The `ats` row builder, extracted so the gate has a seam a test can reach.

    `main()` writes through `pipeline.companies.CSV_PATH`, which is an ABSOLUTE path fixed
    at import time from the repo root — a `chdir` fixture does not redirect it, so driving
    `main()` in a test would append to the real registry. The row builder is the honest unit
    to test, and `retry_unreachable._row_for` is the same shape for the same reason.
    """
    nm, plat, tok, api, n_all, il = payload
    if not _gate.activation_ok(nm, api, n_all):
        # SEED url in cols 2-3, never the refused board. Persisting the refused `api` put
        # a FOREIGN host into the row's address, and `identity_gate.is_walled` derives
        # crack_walled's pool membership from that host -- so a row parked this way joined
        # the crack pool pointing at Novartis's Workday (docs/BACKLOG.md 54). The sibling
        # `retry_unreachable._row_for` already reset to the row's own URL; now both do.
        # And the note carries `no listing found` -- the hand-off token -- for the same
        # reason as retry's: a token-free refusal orphans the row out of every pool.
        return [nm, "scrape", seed_url, seed_url, "false",
                "auto-expand: another company's board; no listing found"]
    return [nm, plat, tok, api, "true", f"auto-expand; {n_all}/{il} IL"]


def main():
    print("auto_expand: " + ("DRY RUN — nothing will be written"
                             if DRY_RUN else
                             "WRITING to companies.csv + scraped_cache.json "
                             "(pass --dry-run to inspect without writing)"), flush=True)
    limit = int(os.environ.get("AUTO_EXPAND_LIMIT", "200"))
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    from pipeline.recruiters import is_recruiter
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have
            and not is_recruiter(e.get("name"))]      # never migrate recruiting/staffing agencies
    batch = todo[:limit]
    print(f"unresolved: {len(todo)} · processing {len(batch)} this run", flush=True)

    cache = _load_cache()
    # Every company gets a row so it leaves the unresolved set — the loop converges to zero:
    #   resolved -> active row with jobs; empty/unreachable -> inactive row (validated scan).
    # Exception: when the LLM fallback tier exists but this run's cap is exhausted, the
    # company is DEFERRED (no row) so a later run gives it its one LLM shot.
    import shutil as _shutil
    llm_available = bool(_shutil.which("claude"))
    llm_budget = int(os.environ.get("LLM_RESOLVE_CAP", "10")) if llm_available else 0
    n_resolved = n_empty = n_unreach = n_llm = n_defer = 0
    for e in batch:
        name, url = e["name"].strip(), e["careers_url"]
        try:
            r = resolve(name, url)
        except Exception:  # noqa: BLE001
            r = ("unreachable", None)
        kind = r[0] if r else "unreachable"

        # LLM fallback: deterministic resolution failed outright, or "succeeded" only by
        # scraping an aggregator page (which the guard below refuses to activate anyway).
        _scrape_url = ""
        if kind == "scrape":
            _j2, _scrape_url = r[1] if isinstance(r[1], tuple) else (r[1], url)
        needs_llm = (kind in ("empty", "unreachable")
                     or (kind == "scrape" and _is_agg_url(_scrape_url)))
        if needs_llm and llm_available:
            if llm_budget <= 0:
                n_defer += 1
                print(f"  dfer {name} (LLM cap reached; retried next run)", flush=True)
                continue
            llm_budget -= 1
            from resolve_llm import resolve_llm
            lr = resolve_llm(name, url)
            if lr:
                r, kind = lr, "ats"
                n_llm += 1
        if kind == "ats":
            row = _row_for_ats(r[1], url)
            n_resolved += 1 if row[4] == "true" else 0
            n_unreach += 0 if row[4] == "true" else 1
        elif kind == "scrape":
            jobs2, good_url = r[1] if isinstance(r[1], tuple) else (r[1], url)
            row = _row_for_scrape(name, jobs2, good_url, url, cache)
            n_resolved += 1 if row[4] == "true" else 0
            n_unreach += 0 if row[4] == "true" else 1
        elif kind == "empty":
            row = [name, "scrape", url, url, "false", "scanned; no open Israel roles now"]
            n_empty += 1
        else:
            row = [name, "scrape", url, url, "false", "unreachable; could not scan"]
            n_unreach += 1
        if not DRY_RUN:
            with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        have.add(name.lower())
        print(f"  {'[dry] ' if DRY_RUN else ''}{kind[:4]:4} {name}", flush=True)

    if not DRY_RUN:
        with open("scraped_cache.json", "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    remaining = len(todo) - len(batch) + n_defer
    print(f"=== resolved {n_resolved} (LLM-cracked {n_llm}), empty {n_empty}, "
          f"unreachable {n_unreach}, deferred {n_defer}; "
          f"~{remaining} still to scan ===", flush=True)


if __name__ == "__main__":
    main()
