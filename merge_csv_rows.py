#!/usr/bin/env python3
"""Git-layer single-writer merge for companies.csv.

The in-process discipline (re-read before every write) protects concurrent writers inside
one machine. It does NOT protect against the git layer: a long cloud run commits a whole
file whose baseline is hours old, and `git pull --rebase` then hits a CONTENT CONFLICT and
the workflow's retry loop gives up — silently discarding the entire run (a 3.5-hour
listing-hunt cycle was lost this way on 2026-08-22).

This applies a run's OWN row changes onto whatever master looks like now:

    cp companies.csv /tmp/base.csv          # BEFORE the tool runs
    python <tool>.py --apply                # tool rewrites companies.csv
    cp companies.csv /tmp/ours.csv          # AFTER
    git checkout --theirs companies.csv     # or: fetch+reset to origin's version
    python merge_csv_rows.py /tmp/base.csv /tmp/ours.csv companies.csv

Rows are matched by company_name. A row is applied only when ours differs from base, so
untouched rows never clobber what another writer changed in the meantime. Rows the run
ADDED (absent from base) are appended if still missing.
"""
from __future__ import annotations

import csv
import re
import sys

from pipeline.atomic import write_csv_rows

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



_TOOL = re.compile(r"^\s*(dark-triage|listing-hunt|deep-validated|crack-walled|domain-dead|"
                   r"re-audit|repair|probe-woken|bd-tried|scanned via brightdata|"
                   # empty-but-suspect joined in wave 7: its varying `N IL` count sat
                   # inside the seg[:28] fallback key, so a conflict Sunday carried TWO
                   # suspect segments per row (bounded, but 23 wasted segments measured;
                   # docs/BACKLOG.md 67)
                   # `scrape rotted (error 7d) <date>` (refresh_scrape_cache): the day count and
                   # date sat inside the seg[:28] key, so two nights' segments both survived a
                   # conflict merge (scraper lane, 2026-08-24)
                   # 2026-08-25 (infra): every dated tool prefix found in the live registry, so
                   # a conflict day cannot carry two of any tool's segment -- `url-repaired`
                   # (12 live rows) and `self-heal` (4) were keyed by seg[:28] (BACKLOG 35/67)
                   r"empty-but-suspect|scrape rotted|url-repaired|url-cleared|url-flagged|"
                   r"self-heal|activated|platform-fix|identity|chrome-verified)\b")


def _seg_key(seg):
    m = _TOOL.match(seg)
    return m.group(1) if m else seg[:28]


def _merge_notes(theirs: str, ours: str, cap: int = 220, base: str | None = None) -> str:
    """Union the ` | `-separated verdict segments of two notes, ours winning per tool.

    Each tool owns a segment (`dark-triage <date>: …`, `listing-hunt <date>: …`). Two
    writers touching the same row must not delete each other's segments — that is how 351
    triage modes were lost. Segments are keyed by tool name; untagged prose is kept once.

    With `base` (the row's note at checkout): a segment that was in base and that ours
    DROPPED is a deliberate deletion — `probe_candidates._wake_note` strips the
    `listing-hunt` / `dark-triage` segments so the hunt re-selects the row — and it is not
    resurrected from theirs unless theirs rewrote it since (BACKLOG 15/60: 47 of 152 wakes
    were being spent by the conflict merge).
    """
    def split(n):
        return [s.strip() for s in (n or "").split("|") if s.strip()]

    base_keys = {_seg_key(s): s for s in split(base)} if base is not None else {}
    ours_keys = {_seg_key(s) for s in split(ours)}
    seen, out = {}, []
    for seg in split(ours) + split(theirs):       # ours first: it wins its own tool key
        key = _seg_key(seg)
        if key in seen:
            continue
        if key in base_keys and key not in ours_keys and base_keys[key] == seg:
            continue                              # ours deleted it; theirs still has the old one
        seen[key] = True
        out.append(seg)
    joined = " | ".join(out)
    if len(joined) <= cap:
        return joined
    # `out` is ours-first then theirs-unique, so pop() trims from the THEIRS tail --
    # the stale duplicates -- and ours' own segments survive. Measured on the real
    # registry: 0 of 1210 rows lose their own pool selector this way.
    while out and len(" | ".join(out)) > cap:
        out.pop()
    return " | ".join(out)[:cap]


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def merge(base_path, ours_path, target_path):
    base = {r[0]: r for r in _read(base_path) if r}
    ours = _read(ours_path)
    target = _read(target_path)
    tgt_idx = {r[0]: i for i, r in enumerate(target) if r}

    changed = [r for r in ours if r and (r[0] not in base or base[r[0]] != r)]
    applied = added = merged_notes = kept_urls = 0
    for r in changed:
        if r[0] in tgt_idx:
            cur = target[tgt_idx[r[0]]]
            if cur != r:
                # The notes column is an APPEND-LOG of per-tool segments, so replacing the
                # whole row drops segments another tool wrote while this run was going.
                # (A 7-hour hunt did exactly that to 351 freshly-written triage modes.)
                # Union the segments instead, keeping ours where a tool wrote both.
                if len(r) > 5 and len(cur) > 5:
                    ours_note = r[5]                       # BEFORE the union below
                    r = list(r)
                    _b = base.get(r[0])
                    r[5] = _merge_notes(cur[5], r[5], base=_b[5] if _b and len(_b) > 5 else None)
                    merged_notes += 1
                    # A long run carries the address the row had at CHECKOUT. If another
                    # writer has since replaced a dead hostname with a verified one, that
                    # is strictly newer knowledge — never hand the row back its NXDOMAIN.
                    # Test ours_note, not r[5]: the union above already copied the stamp in.
                    if (len(r) > 3 and cur[3] != r[3]
                            and "url-repaired" in (cur[5] or "")
                            and "url-repaired" not in (ours_note or "")):
                        r[3] = cur[3]
                        kept_urls += 1
                target[tgt_idx[r[0]]] = r
                applied += 1
        else:
            target.append(r)
            added += 1

    # ATOMIC, like every other companies.csv truncating writer. This was the ONE that
    # wrote in place: a runner eviction mid-write left a 400-line registry behind `|| true`
    # on the digest's conflict path, and the invariant gate there could only catch it
    # after the fact (wave-6 R2, B4). `os.replace` makes the kill window leave the OLD
    # file, which is always a valid registry.
    write_csv_rows(target_path, target)
    print(f"merge_csv_rows: {len(changed)} rows changed by this run "
          f"→ {applied} applied, {added} appended, "
          f"{len(changed) - applied - added} already identical"
          + (f", {kept_urls} repaired URLs preserved" if kept_urls else ""))
    return applied + added


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
