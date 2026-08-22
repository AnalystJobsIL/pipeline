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
import sys


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def merge(base_path, ours_path, target_path):
    base = {r[0]: r for r in _read(base_path) if r}
    ours = _read(ours_path)
    target = _read(target_path)
    tgt_idx = {r[0]: i for i, r in enumerate(target) if r}

    changed = [r for r in ours if r and (r[0] not in base or base[r[0]] != r)]
    applied = added = 0
    for r in changed:
        if r[0] in tgt_idx:
            if target[tgt_idx[r[0]]] != r:
                target[tgt_idx[r[0]]] = r
                applied += 1
        else:
            target.append(r)
            added += 1

    with open(target_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(target)
    print(f"merge_csv_rows: {len(changed)} rows changed by this run "
          f"→ {applied} applied, {added} appended, "
          f"{len(changed) - applied - added} already identical")
    return applied + added


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
