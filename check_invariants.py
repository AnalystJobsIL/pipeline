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
import sys
from collections import Counter

from pipeline.aggregators import is_aggregator
from pipeline.recruiters import is_recruiter

NOTE_CAP = 220
# deliberate, permanent deactivations — keep this list short and dated in the notes
ALLOWED_ORPHANS = {
    "NICE", "Via Transportation", "Marvell Israel", "SeeTree", "Google",
    "Alpha | Similarweb Partner", "Orca-AI",
}
POOL = (r"no ATS detected|unsupported ATS|scrape rotted|monitored candidate|host documented|"
        r"probe-woken|scanned; no open|unreachable|aggregator URL|no listing found|"
        r"redirects to|scanned via brightdata|empty-but-suspect|needs re-resolution|"
        r"needs manual resolution|dark-triage")
TERMINAL = r"defunct|domain-dead"
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

    # C. active rows must be scannable
    for r in (r for r in body if len(r) > 4 and r[4] == "true"):
        if not (r[1] or "").strip():
            bad(f"active row with no platform: {r[0]}")
        if not (r[3] or "").strip() and r[1] != "discovery":
            bad(f"active row with no api_url: {r[0]}")
        if is_aggregator(r[3]):
            bad(f"active row on an aggregator: {r[0]} -> {r[3][:50]}")
        if is_recruiter(r[0]):
            bad(f"active recruiting agency: {r[0]}")

    # D. every inactive row must be in SOME re-check pool
    orphans = [r[0] for r in body
               if len(r) >= 6 and r[4] == "false"
               and not re.search(TERMINAL, r[5] or "", re.I)
               and not is_recruiter(r[0])
               and not re.search(POOL, r[5] or "", re.I)]
    unexpected = sorted(set(orphans) - ALLOWED_ORPHANS)
    if unexpected:
        bad(f"{len(unexpected)} inactive rows match NO re-check pool (retired coverage): "
            f"{unexpected[:10]}")

    # E. pools must not collapse
    pool_n = sum(1 for r in body if len(r) >= 6 and r[4] == "false"
                 and re.search(POOL, r[5] or "", re.I)
                 and not re.search(TERMINAL, r[5] or "", re.I))
    if pool_n < 50:
        bad(f"re-check pool collapsed to {pool_n} rows (floor 50) — predicate inverted?")

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
        from pipeline.israel import _IL_PLACES
        gone = [p for p in _IL_PLACES if not ISRAEL_LOC.search(p)]
        if gone:
            bad(f"scraper city regex no longer covers: {gone[:8]}")
    except Exception as e:  # noqa: BLE001
        bad(f"could not verify city-list drift: {e}")

    # H. board attribution
    try:
        import sqlite3
        db = sqlite3.connect("file:cloud_state/seen.db?mode=ro", uri=True)
        wrong = 0
        for comp, url in db.execute("select company, url from matched"):
            m = re.search(r"/jobs/view/(.+?)-\d{6,}", url or "")
            if not m:
                continue
            slug = m.group(1).replace("-", " ").lower()
            c = re.sub(r"[^a-z0-9 ]", "", (comp or "").lower())
            if c and not any(w in slug for w in c.split() if len(w) > 3):
                wrong += 1
        if wrong:
            bad(f"{wrong} board rows whose URL names a DIFFERENT company (mis-attribution)")
    except Exception:  # noqa: BLE001
        pass

    active = sum(1 for r in body if len(r) > 4 and r[4] == "true")
    for w in warnings:
        print(f"::warning::companies.csv: {w}")
    if err:
        print("INVARIANT VIOLATIONS:", file=sys.stderr)
        for e in err:
            print("  -", e, file=sys.stderr)
        return 1
    print(f"companies.csv OK: {len(body)} rows, {active} active, 0 orphans, "
          f"pool={pool_n}, widths={dict(widths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
