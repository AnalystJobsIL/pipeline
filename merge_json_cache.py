#!/usr/bin/env python3
"""Three-way merge for the company-keyed JSON caches (scraped_cache.json).

`scraped_cache.json` is written by at least eight tools across six workflows, each of which
loads the whole dict and writes the whole dict back. On a push conflict the recovery path
restored OUR copy wholesale — which is our copy *as it was at checkout*, so every company
another workflow had cached in the meantime was silently deleted. Same shape as the
`companies.csv` incident that `merge_csv_rows.py` exists to prevent, one file along.

The merge is per company key, against the checkout-time baseline:

    ours differs from base  -> this run changed it: keep ours
    otherwise               -> keep theirs (origin's, possibly newer)
    key only in theirs      -> keep it (this is the deletion that was happening)
    key only in ours        -> keep it (we just cached it)

Usage: python merge_json_cache.py BASE OURS THEIRS OUT
       (THEIRS is the file currently in the tree after `git reset --hard origin`)
"""
from __future__ import annotations

import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def merge(base, ours, theirs):
    out = dict(theirs)
    kept = changed = 0
    for k, v in ours.items():
        if k not in base or base[k] != v:
            out[k] = v            # this run touched it
            changed += 1
        elif k not in theirs:
            out[k] = v            # untouched by us and absent from theirs: don't lose it
            kept += 1
    return out, changed, kept


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    base, ours, theirs, out = sys.argv[1:5]
    b, o, t = load(base), load(ours), load(theirs)
    merged, changed, kept = merge(b, o, t)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"merged {out}: {len(merged)} companies "
          f"(theirs {len(t)}, ours {len(o)}, {changed} changed by this run, {kept} rescued)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
