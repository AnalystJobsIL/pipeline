#!/usr/bin/env python3
"""Backfill job-description text for scrape-source jobs in scraped_cache.json.

Scrape-source cards carry title/url/location but no JD, which starves the board's
requirements/skills/experience rendering (every API source stores full JDs). This walks the
cache's description-less, relevance-gated jobs through `pipeline.jdfill.fetch_jd` — native
JSON, then plain HTTP (and the page's own schema.org JobPosting), then a budget-capped Bright
Data Web Unlocker for bot-walled pages — and persists the text into the cache's `description`
field. store.py already refreshes `matched.description` on merge, so existing board rows light
up on the next run.

TWO POOLS, ONE BUDGET (2026-08-29). The TITLE pool is what the classifier could accept today;
the ARCHIVE pool is every other Israel-passing card. The archive exists because the corpus is
what a re-judge reads: the title gate is correct for deciding (0.25 % false negatives over 401
postings) and was never justified for KEEPING, and it dropped 1,393 of 1,718 cards on
2026-08-29 while 3,477 of 4,091 collected postings carried under 400 characters. The title pool
runs FIRST with the whole budget and cannot be starved by the archive; the archive gets what is
left, walks oldest-attempt-first round-robin over companies, and reports its own lap length.

- Runs daily in the digest workflow, before pipeline.run (title pool), and nightly in
  jd-archive.yml (`--archive-only`). Idempotent: only touches jobs whose description is too
  short to be one. A page that was read and carried no JD is stamped `_jd_attempted`; the free
  rungs re-read it every night regardless (~1 s a card), and only the PAID rung honours the
  stamp with the 7/14/28 ladder -- until 2026-08-29 one stamp parked every rung for a week and
  the step did nothing at all on three mornings out of four (13 of 13, 20 of 21, 18 of 20
  candidates parked). A transient failure (timeout, 5xx, Unlocker unavailable) retries after 1.
- The nightly scrape-refresh rebuilds the cache but CARRIES FORWARD descriptions and stamps
  by url/job_id (refresh_scrape_cache._carry_jd), so nothing is re-burned.
- What it did — and what it SPENT — lands in the `enrich` stage stamp
  (`pipeline.jdfill.record_enrich`) and from there in the daily mail's `Stage order:` line,
  with an alarm in the bold `Stages:` line.

Env: JD_ENRICH_TIME_BUDGET_MIN (default 25) is the real limit — the count caps
     JD_ENRICH_CAP (2000) / JD_ENRICH_BD_CAP (1000) are only runaway backstops. A cap that
     BINDS is an alarm (`bd-capped`), never a clean stop.
Usage: python enrich_scrape_jd.py [--cache scraped_cache.json] [--dry-run]
                                  [--archive-only | --title-only]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

from pipeline.atomic import write_json
from pipeline.fetchers import clean_scraped as _clean_scraped
from pipeline.israel import is_israel_job
from pipeline.jdfill import (DESC_MAX as _DESC_MAX, MIN_DESC as _MIN_TEXT,  # noqa: F401 - re-exports
                             RETRY_DAYS as _RETRY_DAYS, Item, MIN_DESC, Unlocker, _JD_MARKERS,
                             looks_like_jd,
                             alarm_for, extract_jd, html_to_text, load_secrets, plain_fetch,
                             is_job_url, native_candidates, record_enrich, run_backfill,
                             stamp_path_for, why_string)
from pipeline.seniority import _relevance

for _s in (sys.stdout, sys.stderr):        # a cp1252 pipe must not kill the report
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CACHE = "scraped_cache.json"
# 2026-08-26: was 400, against a 5,000-credit MONTHLY pool already at 118 %. Measured need
# over the three preceding days: 7, 0, 1. A runaway backstop, not an allowance.
# 2026-08-29: raised to 1,000. Bright Data is unlimited for the rest of August and the
# ceiling from 2026-09-01 is enforced in ONE place that reads the live account
# (`pipeline.bd_budget`), so a per-run count cap is a CIRCUIT BREAKER only. At 40 it would
# have bound on the first archive night and truncated the pass while reporting success --
# the same defect shape as a silent cooldown. `bd-capped` is an alarm when it bites.
BD_CAP = 1000
# How many bought bodies with no posting in them park a host for the rest of a run.
BD_HOST_SHELLS = 3
# How many RENDERED Unlocker calls one run may make. Credits are not the constraint (unlimited
# through August, and one place enforces the September ceiling); WALL CLOCK is: measured on the
# first archive pass, 2026-08-29, nineteen consecutive rendered calls each timed out at 90 s --
# 28 minutes of a 90-minute budget for nothing -- before the failing-streak breaker opened. A
# shell we may no longer render is skipped rather than bought raw, because an unrendered credit
# on a JavaScript page returns the same shell the free rung already read.
RENDER_CAP = 60
# One lap of the archive pool that takes longer than this is starvation, not patience.
ARCHIVE_STARVED_DAYS = 14
# Written every N saves: `finally` does not run when the runner SIGTERMs a step at its
# timeout, and a killed night must not lose 1,400 fetches.
CHECKPOINT_EVERY = 100


def _plain_fetch(url, timeout=25):
    """Kept for importers of the old name: the body, "" on any failure."""
    return plain_fetch(url, timeout=timeout)[1]


def _todo(cache):
    """(title_items, archive_items, stats) — every card worth a fetch, split into the pool the
    classifier could accept today and the pool that is only for the archive.

    The gates, in order, each counted, because they are silent by construction: a card that
    already carries a job description; no http url; page chrome ("Analytics Cookies" passes the
    relevance gate); not an Israel posting; a url another card already claimed; an address with
    nothing to fetch at it. What is left is split by `_relevance`.

    `stats` exists because the title gate alone removed 1,393 of 1,718 cards on 2026-08-29 and
    nothing anywhere said so, which means a regression in `_relevance` would look exactly like
    a quiet morning. `dropped_israel` is the same canary one filter along: it is 0 today (every
    scrape card carries an Israeli location), so any non-zero is news.

    A SEARCH page is refused HERE rather than inside the ladder. `run_backfill` stamps whatever
    it walks, so a listing url reaching the loop is parked for a week as if it had been read --
    and on 2026-08-26 one of them (`careers.dhl.com/search-results?keywords=Israel`) bought a
    Bright Data credit. A native rung outranks the url rule: a Comeet or HiBob address is a
    posting whatever its path looks like.

    Deduped by url: several cards can share a listing url (8fig and SuperMeat each contributed
    two on 2026-08-26), and each duplicate was a second fetch — and a second credit — for one
    page. The title pool is built first, so a shared url lands there."""
    stats, seen, title, archive = Counter(), set(), [], []
    for comp, jobs in cache.items():
        for rank, j in enumerate(jobs or []):
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
            if not _clean_scraped([j]):
                stats["chrome"] += 1
                continue
            # Positive evidence only. `is_israel_job` answers False for a card carrying NO
            # location and no country code, and this driver's job is to fetch text, not to
            # judge relevance -- `pipeline/run.py` re-applies the real Israel filter after
            # this layer, so a wrong drop here costs a description for ever while a wrong
            # keep costs about a second. It is a CANARY (0 of 2,141 cards on 2026-08-29):
            # `scrape_dropped_israel` going non-zero is news about the filter, not routine.
            if ((j.get("location") or "").strip() or (j.get("country_code") or "").strip()) \
                    and not is_israel_job(j):
                stats["dropped_israel"] += 1
                continue
            if url in seen:
                stats["duplicate_url"] += 1
                continue
            title_s = str(j.get("title") or "")
            if not (native_candidates(url, comp) or is_job_url(url, title_s)):
                stats["not_job_url"] += 1
                continue
            seen.add(url)
            item = Item(j, url, f"{comp} | {title_s}", j.get("_jd_attempted") or "",
                        comp, title_s)
            if _relevance(title_s.lower()) in ("excluded", "none"):
                stats["dropped_title"] += 1
                archive.append((item, rank))
            else:
                title.append(item)
    # Every card lands in exactly one bucket. Silent exclusion is the failure class
    # ARCHITECTURE.md section 8 is about and this layer has been caught by it twice; the
    # sister driver asserts the same sum over its own rows.
    _accounted = (stats["has_desc"] + stats["no_url"] + stats["chrome"] + stats["dropped_israel"]
                  + stats["duplicate_url"] + stats["not_job_url"] + len(title) + len(archive))
    assert _accounted == stats["cards"], (
        "bucket leak: %d cards, %d accounted (%s, title %d, archive %d)"
        % (stats["cards"], _accounted, dict(stats), len(title), len(archive)))
    return title, _archive_order(archive), stats


def _archive_order(pairs):
    """`[(Item, rank_in_company)]` -> the order one budgeted night should walk them in.

    Oldest attempt first (never-attempted is ""), then a ROUND ROBIN over companies: lap N
    reaches every company's Nth card before any company's N+1th. Without it the 287 empty
    Comeet cards and the 46 Nebius ones are walked in solid blocks, and a budget that stops
    halfway has enriched two employers and none of the other 32.

    This ordering IS the resumability: a night starts where the last one stopped, because
    everything it touched carries today's stamp and sorts last. There is deliberately no
    `_jd_tries` on a card — `refresh_scrape_cache._carry_jd` (the `scraper` lane) carries
    `description` and `_jd_attempted` and nothing else, so a tries key would be silently
    dropped every night and the backoff it drove would look live while being dead."""
    return [it for it, _r in sorted(
        pairs, key=lambda p: (str(p[0].attempted or "")[:10], p[1], p[0].label))]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=_RETRY_DAYS)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--archive-only", action="store_true",
                   help="only the cards the title gate drops (jd-archive.yml)")
    g.add_argument("--title-only", action="store_true",
                   help="only the cards the classifier could accept (the digest's own step)")
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

    bd = Unlocker(cap=int(os.environ.get("JD_ENRICH_BD_CAP", str(BD_CAP))),
                  host_breaker=BD_HOST_SHELLS,
                  render_cap=int(os.environ.get("JD_ENRICH_RENDER_CAP", str(RENDER_CAP))))
    items, archive, gates = _todo(cache)
    if args.archive_only:
        items = []
    if args.title_only:
        archive = []
    # The one state in which a broken layer read as a quiet morning: with an empty todo every
    # alarm is suppressed by design (a driver with nothing to do IS healthy), so a `_relevance`
    # regression that swallowed 946 of 948 cards produced no bold line at all. The gate is
    # allowed to drop almost everything — that is its job — but not to drop EVERYTHING while
    # the cache still holds cards.
    gate_alarm = (f"scrape:jd-gate-swallowed({gates['dropped_title']} of {gates['cards']} cards)"
                  if gates["cards"] and not items and not archive
                  and (gates["dropped_title"] or gates["dropped_israel"]) else "")
    print(f"{len(items)} cache jobs to fetch and {len(archive)} for the archive; "
          f"{gates['dropped_title']} dropped by the title gate (archive pool), "
          f"{gates['dropped_israel']} not Israel, {gates['duplicate_url']} duplicate urls, "
          f"{gates['chrome']} page chrome, {gates['not_job_url']} not a job address, "
          f"{gates['no_url']} without a url", flush=True)

    saves = [0]

    def save(item, text, stamp_v):
        item.key["_jd_attempted"] = stamp_v
        # the same rule `enrich_matched_jd._store_text` applies: a real JD beats text that is
        # not one even when it is shorter, and only between two JDs does length decide
        have = str(item.key.get("description") or "")
        if text and (looks_like_jd(text) or not looks_like_jd(have)) and                 (looks_like_jd(text) != looks_like_jd(have) or len(text) > len(have)):
            item.key["description"] = text
        saves[0] += 1
        # A checkpoint, not a nicety: the `finally` below covers an exception, and the runner
        # kills a step at `timeout-minutes` with SIGTERM, which runs no `finally` at all. At
        # 1,400 cards a night that is the difference between losing one card and losing all of
        # them. 3.3 MB written atomically, milliseconds, once per CHECKPOINT_EVERY.
        if not args.dry_run and saves[0] % CHECKPOINT_EVERY == 0:
            write_json(args.cache, cache, sort_keys=True)

    minutes = float(os.environ.get("JD_ENRICH_TIME_BUDGET_MIN", "25"))
    cap = int(os.environ.get("JD_ENRICH_CAP", "2000"))
    probe_cell, t0 = set(), time.time()
    ca = Counter()
    try:
        # The title pool first, with the WHOLE budget. It is the pool the mail is made of, and
        # ordering is the only thing that could starve it: the archive is 40x larger and its
        # never-attempted cards would sort ahead of title cards that already carry a stamp.
        c = run_backfill(items, save=save, minutes=minutes, count_cap=cap,
                         bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                         probe_cell=probe_cell, free_rungs_ignore_cooldown=True)
        if archive:
            left = max(0.0, minutes - (time.time() - t0) / 60)
            print(f"-- {len(archive)} archive cards, {left:.1f} min left", flush=True)
            ca = run_backfill(archive, save=save, minutes=left,
                              count_cap=max(0, cap - (c["tried"] - c["probe"])),
                              bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                              timeout=15, probe_cell=probe_cell,
                              free_rungs_ignore_cooldown=True)
    finally:
        if not args.dry_run:                  # keep what was fetched even if the loop died
            write_json(args.cache, cache, sort_keys=True)
    # The denominator tomorrow's fill count is read against. Without it a 0 from the cron is
    # indistinguishable from "nothing left to do", which is exactly how three mornings of zero
    # yield went unnoticed.
    thin_left = sum(1 for jobs in cache.values() for j in (jobs or [])
                    if isinstance(j, dict) and not looks_like_jd((j.get("description") or "").strip()))
    worked = ca["tried"] - ca["probe"]
    cycle_days = round(ca["todo"] / worked, 1) if worked else 0
    minutes_used = round((time.time() - t0) / 60, 1)
    if not args.dry_run:
        arch_alarms = []
        if archive:
            # A lap of 1,400 cards is EXPECTED to run out of clock every night until it
            # closes, so `jd-budget-spent` is suppressed for this pool — an alarm that fires
            # every morning is one that gets trained away. What IS news: a lap that has
            # stopped moving, and a pass that tried something and filled nothing.
            arch_alarms.append(alarm_for(ca, bd, driver="scrape:archive", report_budget=False))
            if cycle_days > ARCHIVE_STARVED_DAYS:
                arch_alarms.append(f"scrape:archive:jd-starved(one lap takes {cycle_days} days)")
            if worked and not ca["filled"]:
                arch_alarms.append(f"scrape:archive:zero-fill(0 of {worked} tried, "
                                   f"{thin_left} cards still thin)")
        alarm = "; ".join(a for a in ([alarm_for(c, bd, driver="scrape"), gate_alarm]
                                      + arch_alarms) if a)
        record_enrich(alarm=alarm, path=stamp, scrape_ran=1, scrape_cards=gates["cards"],
                      scrape_archive_todo=ca["todo"], scrape_archive_filled=ca["filled"],
                      scrape_archive_fail=ca["fail"], scrape_archive_bd=ca["bd"],
                      scrape_archive_unfillable=ca["unfillable"],
                      scrape_archive_skipped=ca["skipped_budget"],
                      scrape_archive_gone=ca["gone"], scrape_archive_probe=ca["probe"],
                      scrape_archive_cycle_days=cycle_days,
                      scrape_archive_why=why_string(ca),
                      scrape_archive_minutes=minutes_used,
                      scrape_thin_remaining=thin_left,
                      scrape_not_job_url=gates["not_job_url"],
                      scrape_dropped_israel=gates["dropped_israel"],
                      scrape_bd_shell=c["bd_shell"] + ca["bd_shell"],
                      scrape_bd_rendered=getattr(bd, "rendered", 0),
                      scrape_render_capped=int(bool(getattr(bd, "render_capped", False))),
                      scrape_bd_parked=c["bd_parked"] + ca["bd_parked"],
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
    if archive:
        free = ca["filled"] - ca["bd"]
        print(f"=== archive: {ca['filled']} filled ({free} free, {ca['bd']} paid), "
              f"{ca['fail']} failed, {ca['skipped_budget']} left for tomorrow, "
              f"{thin_left} remaining thin, {minutes_used} min used, "
              f"one lap {cycle_days} days ===", flush=True)
    if bd.used:
        print(f"=== Bright Data: {bd.used} calls ({getattr(bd, 'rendered', 0)} rendered), "
              f"{bd.ok} bodies, "
              f"{c['bd_shell'] + ca['bd_shell']} of them with no posting in them, "
              f"{c['bd'] + ca['bd']} filled"
              + (f", hosts parked: {', '.join(sorted(getattr(bd, 'parked', ()) or ()))}"
                 if getattr(bd, "parked", None) else "")
              + (" -- CAP REACHED, the pass was truncated" if bd.capped else "") + " ===",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
