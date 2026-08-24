#!/usr/bin/env python3
"""Backfill job-description text for scrape-source jobs in scraped_cache.json.

Scrape-source cards carry title/url/location but no JD, which starves the board's
requirements/skills/experience rendering (every API source stores full JDs). This walks the
cache's description-less, relevance-gated jobs through `pipeline.jdfill.fetch_jd` — native
JSON, then plain HTTP, then a budget-capped Bright Data Web Unlocker for bot-walled pages —
and persists the text into the cache's `description` field. store.py already refreshes
`matched.description` on merge, so existing board rows light up on the next run.

- Runs daily in the digest workflow, before pipeline.run. Idempotent: only touches jobs with
  an empty description. A page that was read and carried no JD is stamped `_jd_attempted`
  and retried after 7 days; a transient failure (timeout, 5xx, Unlocker unavailable) after 1.
- The nightly scrape-refresh rebuilds the cache but CARRIES FORWARD descriptions and stamps
  by url/job_id (refresh_scrape_cache._carry_jd), so nothing is re-burned.
- What it did lands in the `enrich` stage stamp (`pipeline.jdfill.record_enrich`) and from
  there in the daily mail's `Stage order:` line — an alarm in the bold `Stages:` line.

Env: JD_ENRICH_TIME_BUDGET_MIN (default 25) is the real limit — the count caps
     JD_ENRICH_CAP (2000) / JD_ENRICH_BD_CAP (400) are only runaway backstops.
Usage: python enrich_scrape_jd.py [--cache scraped_cache.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

from pipeline.atomic import write_json
from pipeline.fetchers import clean_scraped as _clean_scraped
from pipeline.jdfill import (DESC_MAX as _DESC_MAX, MIN_DESC as _MIN_TEXT,  # noqa: F401 - re-exports
                             RETRY_DAYS as _RETRY_DAYS, Item, Unlocker, _JD_MARKERS, alarm_for,
                             extract_jd, html_to_text, load_secrets, plain_fetch, record_enrich,
                             run_backfill)
from pipeline.seniority import _relevance

for _s in (sys.stdout, sys.stderr):        # a cp1252 pipe must not kill the report
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CACHE = "scraped_cache.json"


def _plain_fetch(url, timeout=25):
    """Kept for importers of the old name: the body, "" on any failure."""
    return plain_fetch(url, timeout=timeout)[1]


def _todo(cache):
    """Every job worth a fetch: no description, an http url, a title the classifier could
    accept, and not page chrome ("Analytics Cookies" passes the relevance gate)."""
    for comp, jobs in cache.items():
        for j in jobs or []:
            if not isinstance(j, dict) or (j.get("description") or "").strip():
                continue
            url = j.get("url") or ""
            if not url.startswith("http"):
                continue
            if _relevance((j.get("title") or "").lower()) in ("excluded", "none"):
                continue
            if not _clean_scraped([j]):
                continue
            yield Item(j, url, f"{comp} | {j.get('title') or ''}", j.get("_jd_attempted") or "", comp)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=_RETRY_DAYS)
    args = ap.parse_args(argv)
    # a run against a copy stamps beside the copy, never the repo's cloud_state file
    stamp = None if args.cache == CACHE else args.cache + ".stages.json"
    try:
        return _run(args, stamp)
    except Exception as e:  # noqa: BLE001 - say so in the mail, then fail the step loudly
        record_enrich(alarm=f"crash:{type(e).__name__}", path=stamp)
        raise


def _run(args, stamp):
    load_secrets()
    try:
        import json
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:  # noqa: BLE001
        print(f"no {args.cache}; nothing to enrich")
        return 0

    bd = Unlocker(cap=int(os.environ.get("JD_ENRICH_BD_CAP", "400")))

    def save(item, text, stamp):
        item.key["_jd_attempted"] = stamp
        if text:
            item.key["description"] = text

    try:
        c = run_backfill(list(_todo(cache)), save=save,
                         minutes=float(os.environ.get("JD_ENRICH_TIME_BUDGET_MIN", "25")),
                         count_cap=int(os.environ.get("JD_ENRICH_CAP", "2000")),
                         bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days)
    finally:
        if not args.dry_run:                  # keep what was fetched even if the loop died
            write_json(args.cache, cache, sort_keys=True)
    if not args.dry_run:
        record_enrich(alarm=alarm_for(c, bd), path=stamp, scrape_ran=1,
                      scrape_filled=c["filled"], scrape_bd=c["bd"], scrape_fail=c["fail"],
                      scrape_bd_unavailable=c["bd_unavailable"], scrape_cooldown=c["cooldown"],
                      scrape_unfillable=c["unfillable"])
    print(f"=== JD enrichment: {c['filled']} filled ({c['bd']} via Bright Data), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{c['bd_unavailable']} waiting on Bright Data"
          + (f" [{bd.unavailable}]" if bd.unavailable else "")
          + (f", {c['skipped_budget']} left for tomorrow (budget)" if c["skipped_budget"] else "")
          + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
