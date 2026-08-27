#!/usr/bin/env python3
"""Backfill job-description text for scrape-source jobs in scraped_cache.json.

Scrape-source cards carry title/url/location but no JD, which starves the board's
requirements/skills/experience rendering (every API source stores full JDs). This walks the
cache's description-less, relevance-gated jobs through `pipeline.jdfill.fetch_jd` — native
JSON, then plain HTTP (and the page's own schema.org JobPosting), then a budget-capped Bright
Data Web Unlocker for bot-walled pages — and persists the text into the cache's `description`
field. store.py already refreshes `matched.description` on merge, so existing board rows light
up on the next run.

- Runs daily in the digest workflow, before pipeline.run. Idempotent: only touches jobs whose
  description is too short to be one. A page that was read and carried no JD is stamped
  `_jd_attempted` and retried after 7 days; a transient failure (timeout, 5xx, Unlocker
  unavailable) after 1.
- The nightly scrape-refresh rebuilds the cache but CARRIES FORWARD descriptions and stamps
  by url/job_id (refresh_scrape_cache._carry_jd), so nothing is re-burned.
- What it did — and what it SPENT — lands in the `enrich` stage stamp
  (`pipeline.jdfill.record_enrich`) and from there in the daily mail's `Stage order:` line,
  with an alarm in the bold `Stages:` line.

Env: JD_ENRICH_TIME_BUDGET_MIN (default 25) is the real limit — the count caps
     JD_ENRICH_CAP (2000) / JD_ENRICH_BD_CAP (40) are only runaway backstops.
Usage: python enrich_scrape_jd.py [--cache scraped_cache.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from pipeline.atomic import write_json
from pipeline.fetchers import clean_scraped as _clean_scraped
from pipeline.jdfill import (DESC_MAX as _DESC_MAX, MIN_DESC as _MIN_TEXT,  # noqa: F401 - re-exports
                             RETRY_DAYS as _RETRY_DAYS, Item, MIN_DESC, Unlocker, _JD_MARKERS,
                             looks_like_jd,
                             alarm_for, extract_jd, html_to_text, load_secrets, plain_fetch,
                             record_enrich, run_backfill, stamp_path_for, why_string)
from pipeline.seniority import _relevance

for _s in (sys.stdout, sys.stderr):        # a cp1252 pipe must not kill the report
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CACHE = "scraped_cache.json"
# 2026-08-26: was 400, against a 5,000-credit MONTHLY pool already at 118 %. Measured need
# over the three preceding days: 7, 0, 1. A runaway backstop, not an allowance.
BD_CAP = 40


def _plain_fetch(url, timeout=25):
    """Kept for importers of the old name: the body, "" on any failure."""
    return plain_fetch(url, timeout=timeout)[1]


def _todo(cache):
    """(items, stats) — every job worth a fetch: no real description, an http url, a title the
    classifier could accept, and not page chrome ("Analytics Cookies" passes the relevance
    gate).

    `stats` counts what was dropped, because the gates are silent by construction: the title
    gate alone removed 934 of the 1,240 cached cards on 2026-08-26 and nothing anywhere said
    so, which means a regression in `_relevance` would look exactly like a quiet morning.

    Deduped by url: the cache holds one card per posting, but several cards can share a
    listing url (8fig and SuperMeat each contributed two on 2026-08-26), and each duplicate
    was a second fetch — and would be a second Bright Data credit — for the same page."""
    stats, seen, items = Counter(), set(), []
    for comp, jobs in cache.items():
        for j in jobs or []:
            if not isinstance(j, dict):
                continue
            stats["cards"] += 1
            # `looks_like_jd`, not a character count: a 25-character teaser used to recuse this
            # driver forever, and so — until 2026-08-28 — did 4,000 characters of the careers
            # site's own navigation, which is what this cache's own card builder stores when a
            # page yields no JD (`scrape_universal._read_position_page`, capped at 4,000 with no
            # marker test). The bar is now the one `extract_jd` applies to a fresh body.
            if looks_like_jd((j.get("description") or "").strip()):
                stats["has_desc"] += 1
                continue
            url = j.get("url") or ""
            if not url.startswith("http"):
                stats["no_url"] += 1
                continue
            if _relevance((j.get("title") or "").lower()) in ("excluded", "none"):
                stats["dropped_title"] += 1
                continue
            if not _clean_scraped([j]):
                stats["chrome"] += 1
                continue
            if url in seen:
                stats["duplicate_url"] += 1
                continue
            seen.add(url)
            items.append(Item(j, url, f"{comp} | {j.get('title') or ''}",
                              j.get("_jd_attempted") or "", comp, str(j.get("title") or "")))
    return items, stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=_RETRY_DAYS)
    args = ap.parse_args(argv)
    stamp = stamp_path_for(args.cache, CACHE)
    try:
        return _run(args, stamp)
    except Exception as e:  # noqa: BLE001 - say so in the mail, then fail the step loudly
        if not args.dry_run:
            record_enrich(alarm=f"scrape:crash:{type(e).__name__}", path=stamp, scrape_ran=1)
        raise


def _run(args, stamp):
    load_secrets()
    import json
    try:
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        print(f"no {args.cache}; nothing to enrich")
        record_enrich(alarm="scrape:cache-missing", path=stamp, scrape_ran=1, scrape_todo=0)
        return 0
    except Exception as e:  # noqa: BLE001
        # A cache that EXISTS but cannot be read is not "nothing to enrich": the old message
        # was a false statement and the step exited 0, so a corrupt cache was a green morning.
        # Refuse loudly and write nothing — the step is `continue-on-error`, so the digest
        # still runs, on yesterday's descriptions, and the mail says why.
        print(f"::error::{args.cache} exists but could not be read ({type(e).__name__}); "
              f"refusing to enrich or rewrite it", flush=True)
        record_enrich(alarm="scrape:cache-unreadable", path=stamp, scrape_ran=1)
        return 1

    bd = Unlocker(cap=int(os.environ.get("JD_ENRICH_BD_CAP", str(BD_CAP))))
    items, gates = _todo(cache)
    # The one state in which a broken layer read as a quiet morning: with an empty todo every
    # alarm is suppressed by design (a driver with nothing to do IS healthy), so a `_relevance`
    # regression that swallowed 946 of 948 cards produced no bold line at all. The gate is
    # allowed to drop almost everything — that is its job — but not to drop EVERYTHING while
    # the cache still holds cards.
    gate_alarm = (f"scrape:jd-gate-swallowed({gates['dropped_title']} of {gates['cards']} cards)"
                  if gates["cards"] and not items and gates["dropped_title"] else "")
    print(f"{len(items)} cache jobs to fetch; skipped {gates['dropped_title']} on the title "
          f"gate, {gates['duplicate_url']} duplicate urls, {gates['chrome']} page chrome, "
          f"{gates['no_url']} without a url", flush=True)

    def save(item, text, stamp_v):
        item.key["_jd_attempted"] = stamp_v
        # the same rule `enrich_matched_jd._store_text` applies: a real JD beats text that is
        # not one even when it is shorter, and only between two JDs does length decide
        have = str(item.key.get("description") or "")
        if text and (looks_like_jd(text) or not looks_like_jd(have)) and                 (looks_like_jd(text) != looks_like_jd(have) or len(text) > len(have)):
            item.key["description"] = text

    try:
        c = run_backfill(items, save=save,
                         minutes=float(os.environ.get("JD_ENRICH_TIME_BUDGET_MIN", "25")),
                         count_cap=int(os.environ.get("JD_ENRICH_CAP", "2000")),
                         bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days)
    finally:
        if not args.dry_run:                  # keep what was fetched even if the loop died
            write_json(args.cache, cache, sort_keys=True)
    if not args.dry_run:
        alarm = "; ".join(a for a in (alarm_for(c, bd, driver="scrape"), gate_alarm) if a)
        record_enrich(alarm=alarm, path=stamp, scrape_ran=1, scrape_cards=gates["cards"],
                      scrape_filled=c["filled"], scrape_bd=c["bd"], scrape_fail=c["fail"],
                      scrape_bd_unavailable=c["bd_unavailable"], scrape_cooldown=c["cooldown"],
                      scrape_unfillable=c["unfillable"], scrape_todo=c["todo"],
                      scrape_bd_calls=bd.used, scrape_bd_ok=bd.ok,
                      scrape_skipped=c["skipped_budget"], scrape_probe=c["probe"],
                      scrape_dropped_title=gates["dropped_title"], scrape_why=why_string(c))
    print(f"=== JD enrichment: {c['filled']} filled ({c['bd']} via Bright Data), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{c['unfillable']} nothing to fetch, {bd.used} Bright Data requests spent"
          + (f" [{bd.unavailable}]" if bd.unavailable else "")
          + (f", {c['skipped_budget']} left for tomorrow (budget)" if c["skipped_budget"] else "")
          + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
