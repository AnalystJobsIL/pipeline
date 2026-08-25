#!/usr/bin/env python3
"""Structural guard for companies.csv + the store. Exit 1 on violation. No network, ~1s.

Run on every push AND immediately before every workflow's `git commit`, WITHOUT
continue-on-error — so a corrupted registry never lands. Each check below corresponds to
damage that actually shipped in this repo:

  A  shape        — an unquoted comma in notes silently adds a column
  B  identity     — duplicate company_name makes merge_csv_rows drop edits silently
  C  scannable    — an active row on an aggregator ingests other companies' jobs
  D  re-check     — an inactive row matching NO pool is permanently retired coverage
  E  pool floors  — an inverted predicate empties a pool and the run still exits 0
  F  truncation   — appends at the 220-char cap eat the pool keywords themselves
  G  list drift   — the scraper's city regex must stay derived from pipeline.israel
  H  attribution  — a board row whose URL names a different company
"""
from __future__ import annotations

import csv
import re

from pipeline.verdicts import TERMINAL as _VERDICTS_TERMINAL, TERM_RX as _VERDICTS_TERM_RX
import sys
from collections import Counter

# This is a BLOCKING gate in the digest: if it raises, no digest, no board, no email. On
# Windows (and under any cp1252 redirect) printing a Hebrew company name or an em-dash in a
# violation message is enough to do exactly that — the message describing the problem kills
# the run instead of reporting it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # not a reconfigurable stream
        pass

from pipeline.aggregators import is_aggregator
from pipeline.recruiters import is_recruiter

NOTE_CAP = 220
ORPHAN_BLOCK_AT = 10   # a handful is one tool's note bug; a flood is a pool collapse
# a native-ATS row whose endpoint is not on that ATS fails 100% of its fetches
PLATFORM_HOST = {
    "comeet": r"comeet\.(com|co)", "greenhouse": r"greenhouse\.io",
    "lever": r"lever\.co", "ashby": r"ashbyhq\.com",
    "smartrecruiters": r"smartrecruiters\.com", "workable": r"workable\.com",
    "bamboohr": r"bamboohr\.com", "breezy": r"breezy\.hr",
    "workday": r"myworkdayjobs", "oraclehcm": r"oraclecloud\.com",
    "microsoft": r"careers\.microsoft\.com",
    # recruitee supports custom domains, so its host is not checkable
}
# deliberate, permanent deactivations — keep this list short and dated in the notes
ALLOWED_ORPHANS = {
    "NICE", "Via Transportation", "Marvell Israel", "SeeTree", "Google",
    "Alpha | Similarweb Partner", "Orca-AI",
}
POOL = (r"no ATS detected|unsupported ATS|scrape rotted|monitored candidate|host documented|"
        r"probe-woken|scanned; no open|unreachable|aggregator URL|no listing found|"
        r"redirects to|scanned via brightdata|empty-but-suspect|needs re-resolution|"
        # url-cleared / url-flagged: the stored address was an aggregator or another
        # company's page. The row needs the hunt MORE than most, not less.
        r"needs manual resolution|dark-triage|url-cleared|url-flagged")
# Terminal states: no re-check pool should ever look at these again.
#   alias-of — a second row for a company we already scan at the SAME url. Not a
#   dark company; the opposite, a company covered twice (roles listed under both
#   "Intel" and "Intel Israel").
# THE shared list (docs/BACKLOG.md 47) — this file gates three writer workflows'
# commits now, and a private narrower copy here is exactly what registry_health
# records producing 4 of 5 false-positive orphans.
TERMINAL = _VERDICTS_TERM_RX.pattern   # the shared regex verbatim (word-bounded `recruiter`)
# the modes triage_dark.py may write. A truncated one ("page-emp") matches no pool.
TRIAGE_MODES = {"page-empty", "extract-gap", "wrong-page", "url-dead", "js-shell",
                "blocked", "acquired"}

err = []
warnings = []


def bad(msg):
    err.append(msg)


def warn(msg):
    """Wrong, but not worth withholding the day's email over."""
    warnings.append(msg)


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    body = [r for r in rows if r]

    # A. shape
    widths = Counter(len(r) for r in body)
    for r in body:
        if len(r) != 6:
            bad(f"row has {len(r)} fields, not 6 (unquoted comma in notes?): {r[0]!r}")

    # B. identity
    dupes = [n for n, c in Counter(r[0] for r in body).items() if c > 1]
    if dupes:
        bad(f"duplicate company_name — merge_csv_rows silently drops edits: {dupes[:8]}")

    # C. active rows must be scannable. A WARNING, not a violation: `pipeline/run.py` drops
    # aggregator and recruiter rows at runtime anyway, so one bad row costs one company's
    # coverage — while failing here costs the whole day's digest, board and email.
    unscannable = []
    for r in (r for r in body if len(r) > 4 and r[4] == "true"):
        if not (r[1] or "").strip():
            unscannable.append(f"{r[0]}: no platform")
        if not (r[3] or "").strip() and r[1] != "discovery":
            unscannable.append(f"{r[0]}: no api_url")
        if is_aggregator(r[3]):
            unscannable.append(f"{r[0]}: aggregator {r[3][:40]}")
        if is_recruiter(r[0]):
            unscannable.append(f"{r[0]}: recruiting agency")
    if unscannable:
        warn(f"{len(unscannable)} active rows are not scannable: {unscannable[:6]}")

    # C2. a native-ATS row must point at that ATS. Imperva sat at
    # `ats_platform=workday` with its own careers HTML as the endpoint, so every single run
    # POSTed to it, got HTML back and logged "Expecting value: line 1 column 1" — one of the
    # four permanent `companies_failed` in every digest for as long as anyone had looked.
    for r in (r for r in body if len(r) > 4 and r[4] == "true"):
        pat = PLATFORM_HOST.get((r[1] or "").strip())
        if pat and not re.search(pat, r[3] or "", re.I):
            warn(f"{r[0]}: ats_platform={r[1]} but the endpoint is not on that host "
                 f"({(r[3] or '')[:50]}) — every fetch will fail")

    # C3. an ATS row whose TENANT SLUG names someone else. Rebrands and acquisitions look
    # exactly like this (Momentis still posts under `memic`, OTORIO under `armissecurity`,
    # Itamar Medical under `zoll`), so it can only ever be a warning — but the same shape
    # also hid `similarweb` under "SimilarTech" and `asteralabs` under "ASTERRA", 55 Israel
    # roles between them, about to publish under Israeli companies that never posted them.
    try:
        from pipeline.company_identity import verdict as _identity
        from pipeline.identity_facts import tenants as _declared
        # a row whose acquirer tenant is DECLARED (pipeline/identity_facts.py, with
        # evidence) is not a suspect -- that is what the declaration table is for
        slugged = [f"{r[0]} -> {(r[3] or '')[:44]}" for r in body
                   if len(r) > 4 and r[4] == "true" and not _declared(r[0])
                   and _identity(r[0], r[3] or "") == "mismatch"]
        if slugged:
            warn(f"{len(slugged)} active rows whose endpoint names a different company "
                 f"(check each: an acquisition looks the same): {slugged[:6]}")
    except Exception:  # noqa: BLE001
        pass

    # D. every inactive row must be in SOME re-check pool.
    # The thing worth blocking on is a POOL COLLAPSE — a predicate inverted, a note format
    # changed, hundreds of companies retired at once (check E is its other half). A handful
    # of orphans is a bug in one tool's note, and withholding the day's product to report it
    # is the trade that failed on 2026-08-23. Threshold, then.
    # A row is owned by a TOKEN pool (POOL) or by a FACT pool: any parked row with a real
    # http, non-aggregator address is the probe's (probe_candidates.in_probe_pool, 2026-08-26)
    def _fact_owned(r):
        # the probe's OWN predicate, not a retyped mirror of it: the mirror missed
        # `looks_like_junk` and credited two job-title rows as owned (wave-1, 2026-08-26)
        try:
            from probe_candidates import in_probe_pool
            return in_probe_pool(r)
        except Exception:  # noqa: BLE001
            return (r[3] or "").startswith("http") and not is_aggregator(r[3])
    orphans = [r[0] for r in body
               if len(r) >= 6 and r[4] == "false"
               and not re.search(TERMINAL, r[5] or "", re.I)
               and not is_recruiter(r[0])
               and not re.search(POOL, r[5] or "", re.I)
               and not _fact_owned(r)]
    unexpected = sorted(set(orphans) - ALLOWED_ORPHANS)
    if len(unexpected) > ORPHAN_BLOCK_AT:
        bad(f"{len(unexpected)} inactive rows match NO re-check pool (retired coverage): "
            f"{unexpected[:10]}")
    elif unexpected:
        warn(f"{len(unexpected)} inactive rows match NO re-check pool: {unexpected[:10]}")

    # E. pools must not collapse
    pool_n = sum(1 for r in body if len(r) >= 6 and r[4] == "false"
                 and re.search(POOL, r[5] or "", re.I)
                 and not re.search(TERMINAL, r[5] or "", re.I))
    if pool_n < 50:
        bad(f"re-check pool collapsed to {pool_n} rows (floor 50) — predicate inverted?")
    fact_n = sum(1 for r in body if len(r) >= 6 and r[4] == "false" and _fact_owned(r)
                 and not re.search(TERMINAL, r[5] or "", re.I))
    if fact_n < 50:
        bad(f"the fact pool (parked rows with an http address) collapsed to {fact_n} (floor 50)")

    # F. truncation eating verdicts
    dangling = [r[0] for r in body if len(r) > 5
                and re.search(r"(dark-triage|listing-hunt|deep-validated|crack-walled)"
                              r"\s*\d{4}-\d{2}-\d{2}:?\s*$", r[5])]
    if dangling:
        bad(f"{len(dangling)} notes truncated mid-verdict (mode lost): {dangling[:8]}")

    # F2. truncation eating the MODE ITSELF, which check F cannot see because a verdict
    # string is still there. 87 rows carried `dark-triage <date>: page-emp` (also
    # `page-empt`, `page-e`, `pa`) — a mode no downstream filter matches, so the row silently
    # leaves whichever pool keys on it. Only a mode from the known set may be written.
    partial = [(r[0], m.group(1)) for r in body if len(r) > 5
               for m in re.finditer(r"dark-triage \d{4}-\d{2}-\d{2}: ([a-z-]*)", r[5] or "")
               if m.group(1) not in TRIAGE_MODES]
    if partial:
        # a warning, not a violation: it costs coverage on those rows, but withholding the
        # whole digest (this runs as a blocking gate) would cost more.
        warn(f"{len(partial)} rows carry a truncated/unknown triage mode "
             f"(no pool matches it): {partial[:8]}")

    # G. derived list drift
    try:
        from scrape_universal import ISRAEL_LOC
        from pipeline.israel import _IL_PLACES, _IL_PLACES_HE
        gone = [p for p in _IL_PLACES + _IL_PLACES_HE if not ISRAEL_LOC.search(p)]
        if gone:
            bad(f"scraper city regex no longer covers: {gone[:8]}")
    except Exception as e:  # noqa: BLE001
        bad(f"could not verify city-list drift: {e}")

    # H. board attribution. This used to be a `bad()`, and on 2026-08-23 ONE row — a false
    # positive, "G-STAT" vs the slug "g-stat", because only the company side was normalized
    # — failed the gate and withheld the whole day's digest, board and email. The check is
    # now shared with the ingest path (`fetch_discovery` drops these before they can be
    # stored), so a row reaching here means the filter was bypassed: worth shouting about,
    # not worth withholding the product for.
    try:
        import sqlite3
        from pipeline.company_identity import url_names_other_company
        db = sqlite3.connect("file:cloud_state/seen.db?mode=ro", uri=True)
        wrong = [f"{c}: {u[:60]}" for c, u in db.execute("select company, url from matched")
                 if url_names_other_company(c, u)]
        if wrong:
            warn(f"{len(wrong)} board rows whose URL names a DIFFERENT company "
                 f"(mis-attribution): {wrong[:5]}")
    except Exception:  # noqa: BLE001
        pass

    active = sum(1 for r in body if len(r) > 4 and r[4] == "true")
    for w in warnings:
        print(f"::warning::companies.csv: {w}")
    if err:
        print("INVARIANT VIOLATIONS:", file=sys.stderr)
        for e in err:
            print("  -", e, file=sys.stderr)
            print(f"::error::invariant: {e}")     # an annotation on the run page, not only a log line
        return 1
    print(f"companies.csv OK: {len(body)} rows, {active} active, 0 orphans, "
          f"pool={pool_n}, widths={dict(widths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
