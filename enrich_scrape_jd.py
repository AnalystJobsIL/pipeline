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
postings) and was never justified for KEEPING: measured over the committed cache on 2026-08-29
it routed 1,204 of 2,141 cards away from the fetch, and 1,709 of those 2,141 carried no job
description at all. The title pool
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
                                  [--archive-only | --with-archive]
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
# have bound on the first archive night (1,204 cards) and truncated the pass reporting success --
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
# timeout, and a killed night must not lose a lap of fetches.
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

    `stats` exists because the gates are silent: the title gate alone routed 1,204 of the 2,141
    committed cards away from the title pool on 2026-08-29 (and 1,393 of 1,718 in that morning
    production run, against a cache that had not yet been rebuilt), and nothing anywhere said
    so — which means a regression in `_relevance` would look exactly like a quiet morning.
    `dropped_israel` is the same canary one filter along: it is 0 over all 2,141 cards, so any
    non-zero is news.

    A SEARCH page is refused HERE rather than inside the ladder. `run_backfill` stamps whatever
    it walks, so a listing url reaching the loop is parked for a week as if it had been read --
    and on 2026-08-26 one of them (`careers.dhl.com/search-results?keywords=Israel`) bought a
    Bright Data credit. A native rung outranks the url rule: a Comeet or HiBob address is a
    posting whatever its path looks like.

    Deduped by url: several cards can share a listing url (8fig and SuperMeat each contributed
    two on 2026-08-26), and each duplicate was a second fetch — and a second credit — for one
    page. The title pool is built first, so a shared url lands there."""
    stats, seen, title, archive = Counter(), set(), [], []
    ranks = Counter()          # how many ARCHIVE cards this company has contributed so far
    for comp, jobs in cache.items():
        for j in (jobs or []):
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
                # the rank among this company ARCHIVE cards, not its index in the company
                # whole job list: a company whose archive cards sit at indices 20+ (because it
                # lists twenty analyst titles first) would otherwise be walked in one solid
                # block after every company whose cards start at 0 -- the exact blocking the
                # round robin exists to prevent (wave 1, P2-B).
                archive.append((item, ranks[comp]))
                ranks[comp] += 1
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
    # THE DEFAULT IS THE TITLE POOL, and that is not a preference. `daily-digest.yml` runs
    # `python enrich_scrape_jd.py` with no flag, on the mail critical path, inside a 30-minute
    # step -- so a default that included the archive would put a 1,200-card walk (and, with
    # BD_CAP now 1000, up to a thousand credits spent on the CORPUS) in front of the morning
    # mail. The archive is opt-in, and `jd-archive.yml` is what opts in.
    g.add_argument("--archive-only", action="store_true",
                   help="ONLY the cards the title gate drops (jd-archive.yml)")
    g.add_argument("--with-archive", action="store_true",
                   help="both pools in one process (a local catch-up; no workflow does this)")
    args = ap.parse_args(argv)
    stamp = stamp_path_for(args.cache, CACHE)
    try:
        return _run(args, stamp)
    except Exception as e:  # noqa: BLE001 - say so in the mail, then fail the step loudly
        if not args.dry_run:
            record_enrich(alarm=f"{'archive' if args.archive_only else 'scrape'}:crash:"
                                f"{type(e).__name__}", path=stamp,
                          **({"archive_ran": 1} if args.archive_only else {"scrape_ran": 1}))
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

    if not cache:
        # `cache-missing` and `cache-unreadable` both alarm; a cache that parses to `{}` did
        # not, and it is the same news (wave 3, P2-6).
        print(f"::error::{args.cache} holds no companies at all", flush=True)
        record_enrich(alarm="scrape:cache-empty", path=stamp, scrape_ran=1, scrape_todo=0)
        return 1
    # `--dry-run` MEANS DRY. The Unlocker used to be built and handed to the loop regardless,
    # and only `save()` was gated -- so a rehearsal bought credits: 6 in a four-card fixture,
    # and up to 274 over the live cache, from a command whose name promises none. The cap raise
    # in this file multiplied that bill by 25 (wave 2, P0-1).
    bd = None if args.dry_run else Unlocker(
        cap=int(os.environ.get("JD_ENRICH_BD_CAP", str(BD_CAP))),
        host_breaker=BD_HOST_SHELLS,
        render_cap=int(os.environ.get("JD_ENRICH_RENDER_CAP", str(RENDER_CAP))))
    items, archive, gates = _todo(cache)
    # the gate canary is computed from what `_todo` SAW, before a flag empties a pool
    gate_alarm = ("scrape:jd-gate-swallowed(_relevance no longer accepts 'data analyst')"
                  if gates["cards"] and _relevance("data analyst") in ("excluded", "none") else "")
    if args.archive_only:
        items = []
    elif not args.with_archive:
        archive = []
    # The one state in which a broken layer read as a quiet morning: with an empty todo every
    # alarm is suppressed by design (a driver with nothing to do IS healthy), so a `_relevance`
    # regression that swallowed 946 of 948 cards produced no bold line at all. The gate is
    # allowed to drop almost everything — that is its job — but not to drop EVERYTHING while
    # the cache still holds cards.
    # `gate_alarm` is set above, from what `_todo` saw, because a flag that empties a pool must
    # not be able to manufacture it. The gate may drop almost everything -- that is its job --
    # but it may not stop recognising a role we KNOW is in scope. This used to be inferred from
    # the counts ("todo 0 while cards remain"), and that inference died with the archive pool:
    # the title pool legitimately empties on a good night, because a card it filled yesterday
    # is skipped as `has_desc` today, so the old condition would alarm every morning and get
    # trained away. `_relevance` is `seniority`s, and the day it stops accepting
    # `data analyst` is the day the classifier judges nothing either.
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
        # 1,200 cards a night that is the difference between losing one card and losing all of
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
            # NEVER 0: `run_backfill` reads `count_cap=0` as "no cap at all", so a title pool
            # that spent the whole allowance would hand the archive an UNLIMITED one -- the
            # backstop disabling itself at exactly the moment it binds (wave 1, P2-A).
            ca = run_backfill(archive, save=save, minutes=left,
                              count_cap=max(1, cap - (c["tried"] - c["probe"])) if cap else 0,
                              bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                              timeout=15, probe_cell=probe_cell,
                              free_rungs_ignore_cooldown=True)
    finally:
        if not args.dry_run:                  # keep what was fetched even if the loop died
            write_json(args.cache, cache, sort_keys=True)
    # The denominator tomorrow's fill count is read against. Without it a 0 from the cron is
    # indistinguishable from "nothing left to do", which is exactly how three mornings of zero
    # yield went unnoticed.
    # What is left FOR TOMORROW, which is not every thin card in the file: a card with no url,
    # page chrome, a non-Israel posting and a listing page are all thin for ever and no pool
    # can reach them, so counting them gave the number a floor it could never cross and
    # inflated the `zero-fill` alarm text with it (wave 1, P2-D). `_todo` is pure and cheap,
    # so ask it again over the cache as it now stands.
    _t2, _a2, _g2 = _todo(cache)
    thin_left = len(_t2) + len(_a2)
    # `unfillable` is excluded for the same reason `jd-massfail` excludes it: a refused address
    # is nothing to fetch and nobody failure, so counting it as work made `zero-fill` fire on a
    # pass that behaved perfectly (wave 3, P1-3).
    # `max(0, ...)`: `unfillable` counts rows refused BEFORE the loop reached them as well as
    # rows whose fetch came back with an unfillable reason, so the subtraction can go negative
    # -- and a negative `worked` is truthy, which fired `zero-fill(0 of -1 tried)` and
    # suppressed the nothing-attempted clause that should have spoken instead.
    worked = max(0, ca["tried"] - ca["probe"] - ca["unfillable"])
    # How many days one lap takes = what is LEFT over what a night gets through. It used to be
    # `todo / worked`, and `todo` counts rows the loop never attempts -- terminal `gone` rows
    # and refused hosts -- so a lap that walked every workable card, filled all of them and
    # left NOTHING for tomorrow reported "one lap takes 20 days" and raised `jd-starved`
    # (wave 3, P1-2). A lap that closed has nothing left and takes one night, by definition.
    # -1, never 0, when a lap worked nothing: 0 is what a lap that closes instantly shows, so
    # the gauge introduced to detect starvation read healthiest exactly when it was worst
    # (wave 1, P1-D).
    cycle_days = (round(ca["skipped_budget"] / worked + 1, 1) if worked
                  else (-1 if ca["todo"] else 0))
    minutes_used = round((time.time() - t0) / 60, 1)
    if not args.dry_run:
        arch_alarms = []
        if archive:
            # A lap of 1,400 cards is EXPECTED to run out of clock every night until it
            # closes, so `jd-budget-spent` is suppressed for this pool — an alarm that fires
            # every morning is one that gets trained away. What IS news: a lap that has
            # stopped moving, and a pass that tried something and filled nothing.
            arch_alarms.append(alarm_for(ca, bd, driver="archive", report_budget=False))
            if not worked and (ca["skipped_budget"] or ca["cooldown"] or ca["paid_cooldown"]):
                # The whole starvation surface used to collapse on one refused-host card:
                # `alarm_for`s nothing-attempted clause needs `not unfillable`, the budget
                # clause is suppressed for this pool by design, `zero-fill` needs `worked`, and
                # `cycle_days` reported 0 -- which is BELOW the starved threshold, so it read
                # as the healthiest possible number (wave 1, P1-D).
                arch_alarms.append(f"archive:jd-nothing-attempted("
                                   f"{ca['skipped_budget']} of {ca['todo']} left, 0 worked)")
            if getattr(bd, "render_capped", False):
                # the same shape as a binding credit cap: a pass cut short reporting success
                arch_alarms.append(f"archive:render-capped({getattr(bd, 'rendered', 0)} rendered, "
                                   f"the rest of the JavaScript pages went unread)")
            if cycle_days > ARCHIVE_STARVED_DAYS:
                arch_alarms.append(f"archive:jd-starved(one lap takes {cycle_days} days)")
            if worked and not ca["filled"]:
                arch_alarms.append(f"archive:zero-fill(0 of {worked} tried, "
                                   f"{thin_left} cards still thin)")
        alarm = "; ".join(a for a in ([alarm_for(c, bd, driver="scrape"), gate_alarm]
                                      + arch_alarms) if a)
        # The archive keys are written ONLY by a run that walked that pool. They are gauges, so
        # a run that did not touch the archive would REPLACE the night's lap length, minutes
        # and todo with zeros -- and the 05:00 digest runs this driver every morning. The
        # night's verdict has to survive the morning that follows it (wave 3, P0-1).
        arch = dict(scrape_archive_todo=ca["todo"], scrape_archive_filled=ca["filled"],
                    scrape_archive_fail=ca["fail"], scrape_archive_bd=ca["bd"],
                    scrape_archive_unfillable=ca["unfillable"],
                    scrape_archive_left=ca["skipped_budget"],
                    scrape_archive_gone=ca["gone"], scrape_archive_probe=ca["probe"],
                    scrape_archive_cycle_days=cycle_days,
                    scrape_archive_why=why_string(ca),
                    scrape_archive_minutes=minutes_used,
                    archive_ran=1) if archive else {}
        title_keys = dict(scrape_ran=1, scrape_dropped_title=gates["dropped_title"],
                          scrape_todo=c["todo"], scrape_filled=c["filled"], scrape_bd=c["bd"],
                          scrape_fail=c["fail"], scrape_cooldown=c["cooldown"],
                          scrape_unfillable=c["unfillable"], scrape_probe=c["probe"],
                          scrape_bd_unavailable=c["bd_unavailable"],
                          scrape_skipped=c["skipped_budget"],
                          scrape_why=why_string(c)) if not args.archive_only else {}
        record_enrich(alarm=alarm, path=stamp, scrape_cards=gates["cards"],
                      **arch, **title_keys,
                      scrape_thin_remaining=thin_left,
                      scrape_not_job_url=gates["not_job_url"],
                      scrape_dropped_israel=gates["dropped_israel"],
                      scrape_paid_cooldown=c["paid_cooldown"] + ca["paid_cooldown"],
                      scrape_bd_shell=c["bd_shell"] + ca["bd_shell"],
                      scrape_bd_rendered=getattr(bd, "rendered", 0),
                      scrape_render_capped=int(bool(getattr(bd, "render_capped", False))),
                      scrape_bd_parked=c["bd_parked"] + ca["bd_parked"],
                      scrape_bd_calls=getattr(bd, "used", 0), scrape_bd_ok=getattr(bd, "ok", 0))
    print(f"=== JD enrichment: {c['filled']} filled ({c['bd']} via Bright Data), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{c['unfillable']} nothing to fetch, {getattr(bd, 'used', 0)} Bright Data "
          f"requests spent" + (f" [{bd.unavailable}]" if getattr(bd, "unavailable", "") else "")
          + (f", {c['skipped_budget']} left for tomorrow (budget)" if c["skipped_budget"] else "")
          + " ===")
    if archive:
        free = ca["filled"] - ca["bd"]
        print(f"=== archive: {ca['filled']} filled ({free} free, {ca['bd']} paid), "
              f"{ca['fail']} failed, {ca['skipped_budget']} left for tomorrow, "
              f"{thin_left} remaining thin, {minutes_used} min used, "
              f"one lap {cycle_days} days ===", flush=True)
    if getattr(bd, "used", 0):
        print(f"=== Bright Data: {bd.used} calls ({getattr(bd, 'rendered', 0)} rendered), "
              f"{bd.ok} bodies, "
              f"{c['bd_shell'] + ca['bd_shell']} of them with no posting in them, "
              f"{c['bd'] + ca['bd']} filled"
              + (f", hosts parked: {', '.join(sorted(getattr(bd, 'parked', ()) or ()))}"
                 if getattr(bd, "parked", None) else "")
              + (" -- CAP REACHED, the pass was truncated"
                 if getattr(bd, "capped", False) else "") + " ===",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
