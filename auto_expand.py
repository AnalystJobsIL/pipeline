#!/usr/bin/env python3
"""Self-draining resolver. Each run takes the next batch of companies that are researched but not
yet in companies.csv, resolves them (iframe-ATS / scrape / follow-jobs-link via resolve_deep), and
writes results DIRECTLY into companies.csv + scraped_cache.json. Scheduled in the cloud it keeps
shrinking the unresolved set every run until it reaches zero — no PC, no babysitting.

Env:  AUTO_EXPAND_LIMIT (default 200) companies per run; LLM_RESOLVE_CAP (default 10)
`claude -p` calls per run; AUTO_EXPAND_SEARCH_CAP (default 40) names that may enter the
LLM tier per run (each costs a free search and at most one capped unlock; a call is
charged only when a page was read, so the search cap is the one that paces the queue).
Prints the remaining-unresolved count so the workflow / log shows progress.

An AGGREGATOR seed (a LinkedIn / Indeed / secrethunter posting -- 338 of the 342 queued
names on 2026-08-25) never goes through `resolve_deep`: rendering that page can only yield
a refusal, `empty` or `unreachable` (its jobs are other employers'), and it used to cost
17-25 s of Playwright per name AFTER the LLM cap was spent -- 76 wasted minutes a run,
twice a day, with the 10 names that did get a shot buried as `scanned; no open Israel
roles now` with the aggregator shell as their address (docs/BACKLOG.md 177). Such a name
is now DEFERRED, never parked, and the tier walks the queue least-recently-tried first
(`cloud_state/auto_expand_seen.json` is the rotation key -- ARCHITECTURE.md section 2:
a budget without a rotation key re-walks the same prefix forever).

**This tool WRITES BY DEFAULT**, unlike every other registry tool, which is dry-run until
`--apply`. The auto-expand workflow invokes it with no flags, so the default cannot be
flipped from here without silently disabling the 08:00/20:00 cron (that is a workflow
change: docs/BACKLOG.md, "auto_expand writes by default"). Until then it says so on
startup, and `--dry-run` gives an agent a safe way to inspect the batch — added 2026-08-23
after a routine dry-run of the nightly chain appended two junk rows ("Qualitest acq",
"Keter", both on secrethunter.io aggregator URLs) to the live registry.

Usage: python auto_expand.py [--dry-run]
       python auto_expand.py --clear-agg-urls [--apply]   # un-bury rows parked on an
                                                          # aggregator seed (dry-run default)
"""
from __future__ import annotations

import sys

import csv
import json
import os
import re
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
SEEN_PATH = os.path.join("cloud_state", "auto_expand_seen.json")


def _today():
    import datetime as _dtm
    return _dtm.date.today().isoformat()


def _load_seen():
    """{name: date last given an LLM-tier shot}. Absent or unreadable -> {} (a rotation
    key, not a verdict: losing it costs order, never a row)."""
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            d = json.load(f)
        # only str dates sort against str; a hand-edited or merged value of another type
        # would TypeError the whole (non-continue-on-error) expand step (wave-1 F7)
        return {k: v for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


_LI_SITE = re.compile(r'data-tracking-control-name="about_website"[^>]+href="([^"?]+)', re.I)


def _site_from_slug(slug, timeout=8):
    """The company's own website from its public LinkedIn company page -- the one
    non-aggregator seed intake can produce (BACKLOG 178; 399 of 1,544 queue entries carry
    a slug). One bounded GET; "" on anything but a clear `about_website` link."""
    if not slug or not re.fullmatch(r"[a-z0-9-]+", str(slug)):
        return ""
    try:
        import urllib.request
        req = urllib.request.Request(f"https://www.linkedin.com/company/{slug}/about/",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(400_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    m = _LI_SITE.search(html)
    site = (m.group(1) if m else "").strip()
    return site if site.startswith("http") and not _is_agg_url(site) else ""


def _names_now():
    """The registry's names RIGHT NOW -- re-read before every append (rule 4): a
    concurrent writer that added the same company mid-run would otherwise get a twin."""
    return {r["company_name"].strip().lower() for r in load_companies(CSV_PATH, active_only=False)}


_CACHE_OK = {"readable": True}


def _load_cache():
    """ABSENT is {}; CORRUPT is reported and the run's cache write is SKIPPED -- writing
    `{}` over a momentarily unreadable file deleted every company's cards (BACKLOG 156;
    the guard discovery_daily already has)."""
    _CACHE_OK["readable"] = True
    if not os.path.exists("scraped_cache.json"):
        return {}
    try:
        with open("scraped_cache.json", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("not an object")
        return d
    except Exception as e:  # noqa: BLE001
        print(f"::error::scraped_cache.json is unreadable ({str(e)[:60]}) -- this run will NOT "
              f"write it; cards resolved tonight are kept in the registry only", flush=True)
        _CACHE_OK["readable"] = False
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
    have = _names_now()
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have
            and not is_recruiter(e.get("name"))]      # never migrate recruiting/staffing agencies
    # least-recently-tried first, file order within a day (stable sort): deferred names
    # are never parked, so without this the same prefix would get every run's shots
    seen = _load_seen()
    todo.sort(key=lambda e: seen.get((e.get("name") or "").strip(), ""))
    batch = todo[:limit]
    print(f"unresolved: {len(todo)} · processing {len(batch)} this run", flush=True)

    cache = _load_cache()
    # Every company gets a row so it leaves the unresolved set — the loop converges to zero:
    #   resolved -> active row with jobs; empty/unreachable -> inactive row (validated scan).
    # Exceptions, both DEFERRED (no row, retried on rotation): an aggregator seed the LLM
    # tier could not crack this run, and any name whose tier-2 shot is capped out.
    import shutil as _shutil
    from collections import Counter
    llm_available = bool(_shutil.which("claude"))
    llm_budget = int(os.environ.get("LLM_RESOLVE_CAP", "10")) if llm_available else 0
    search_budget = int(os.environ.get("AUTO_EXPAND_SEARCH_CAP", "40"))
    n_resolved = n_empty = n_unreach = n_llm = n_dupe = 0
    deferred = Counter()
    for e in batch:
        name, url = e["name"].strip(), e["careers_url"]
        agg_seed = _is_agg_url(url)
        if agg_seed and e.get("slug") and search_budget > 0:
            # the slug can turn an aggregator seed into the company's OWN site (BACKLOG 178):
            # one GET, bounded by the same search cap as the LLM tier; a real site is a
            # tier-1 seed like any other, and the LLM tier then reads a real page too
            site = _site_from_slug(e.get("slug"))
            if site:
                search_budget -= 1
                url, agg_seed = site, False
                print(f"  slug {name}: {e.get('slug')} -> {site[:60]}", flush=True)
        if agg_seed:
            # never rendered: the page is a posting on someone else's board (see module doc)
            r, kind = None, "unreachable"
        else:
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
        needs_llm = (agg_seed or kind in ("empty", "unreachable")
                     or (kind == "scrape" and _is_agg_url(_scrape_url)))
        defer = ""
        if needs_llm and llm_available:
            if llm_budget <= 0 or search_budget <= 0:
                defer = "cap"
            else:
                search_budget -= 1
                seen[name] = _today()
                import resolve_llm as _llm
                lr = _llm.resolve_llm(name, url)
                llm_budget -= _llm.LAST["calls"]   # charge CALLS (retries included), not attempts
                if lr:
                    r, kind = lr, "ats"
                    n_llm += 1
                elif agg_seed:
                    defer = "llm-none" if _llm.LAST["asked"] else "no-candidates"
        elif needs_llm and agg_seed:
            defer = "no-llm"
        if defer:
            deferred[defer] += 1
            print(f"  dfer {name} ({defer}; retried on rotation)", flush=True)
            continue
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
            if name.lower() in _names_now():      # re-read before the append (rule 4)
                n_dupe += 1
                print(f"  dupe {name} (already in the registry; not appended)", flush=True)
                continue
            with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        print(f"  {'[dry] ' if DRY_RUN else ''}{kind[:4]:4} {name}", flush=True)

    if not DRY_RUN:
        if _CACHE_OK["readable"]:
            with open("scraped_cache.json", "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.makedirs(os.path.dirname(SEEN_PATH) or ".", exist_ok=True)
        from pipeline.atomic import write_json
        write_json(SEEN_PATH, seen)
    n_defer = sum(deferred.values())
    remaining = len(todo) - len(batch) + n_defer
    why = ", ".join(f"{k} {v}" for k, v in sorted(deferred.items())) or "-"
    print(f"=== resolved {n_resolved} (LLM-cracked {n_llm}), empty {n_empty}, "
          f"unreachable {n_unreach}, deferred {n_defer} ({why}), dupes {n_dupe}; "
          f"~{remaining} still to scan ===", flush=True)


# Verdicts this tool writes on a parked row (its own, per pipeline.verdicts.TOKENS) --
# the rows `--clear-agg-urls` may touch.
_OWN_PARKED = ("scanned; no open", "unreachable", "aggregator URL")


def clear_agg_urls(apply=False, path=None):
    """Un-bury rows this tool parked with an aggregator shell as their address.

    Until 2026-08-25 an aggregator-seeded name that the LLM tier could not crack was
    written as `scanned; no open Israel roles now` with the LinkedIn / secrethunter URL in
    cols 2-3 -- 28 real employers on that day (ctera, Houzz, yad2, Upwind Security ...),
    each re-tested against a JS shell by every re-check. The address is blanked and the
    row stamped `url-cleared <date>: <host> aggregator seed`, the shape
    `state/sess/cleanup_after_hunt.py` already gave 23 rows: `url-cleared` is in
    `listing_hunt.HUNT_POOL`, so the row stays the hunt's, which searches by NAME when the
    seed is empty. Dry-run unless `apply`. Re-reads immediately before the one write.
    """
    from pipeline.atomic import write_csv_rows
    from pipeline.notes import append as _note_append
    path = path or CSV_PATH
    rows = list(csv.reader(open(path, encoding="utf-8")))
    changed = []
    for r in rows[1:]:
        if len(r) < 6 or r[4] != "false" or not _is_agg_url(r[3] or ""):
            continue
        note = r[5] or ""
        from pipeline.notes import split as _segments
        if not any(seg.startswith(t) for seg in _segments(note) for t in _OWN_PARKED):
            continue                     # any SEGMENT, not only the first
        host = urlparse(r[3]).netloc
        r[2] = r[3] = ""
        r[5] = _note_append(note, f"url-cleared {_today()}: {host} aggregator seed")
        changed.append(r[0])
        print(f"  {'' if apply else '[dry] '}clear {r[0]}: {host}", flush=True)
    if apply and changed:
        write_csv_rows(path, rows)
    print(f"=== cleared {len(changed)} aggregator-seeded rows"
          f"{'' if apply else ' (dry run; pass --apply)'} ===", flush=True)
    return changed


if __name__ == "__main__":
    if "--clear-agg-urls" in sys.argv:
        clear_agg_urls(apply="--apply" in sys.argv)
    else:
        main()
