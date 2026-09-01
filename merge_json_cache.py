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
    key in base, not in ours, unchanged in theirs -> DROP it: this run deleted it on purpose
                               (an empty scrape, an expired carry, a parked row) and origin
                               never touched it. Without this rule a night's deletions came
                               back on every push-conflict night (docs/BACKLOG.md 95).
    key in base and ours (untouched by us), absent from theirs -> DROP it: ORIGIN retired it
                               while we held an older checkout, and that deletion stands too
                               (2026-09-01, docs/BACKLOG.md 458). It used to be rescued
                               unconditionally, which made the two deletion arms asymmetric:
                               44 names retired by two commits were back 13 minutes later,
                               re-added by a cron's own state commit.
                               EXCEPT when origin lost a quarter of the keys (or all of
                               them): CLAUDE.md rule 2 calls that a broken run, not a
                               measurement, so we keep our copies. That mirrors the guard
                               `persist_state.s_company_dict` already applies to OUR side --
                               before 458 the unconditional rescue was providing it for
                               origin's side by accident, and every caller of this function
                               relied on it without saying so.

Usage: python merge_json_cache.py BASE OURS THEIRS OUT
       (THEIRS is the file currently in the tree after `git reset --hard origin`)
"""
from __future__ import annotations

import json
import sys

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



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
    # Origin's deletions stand (458) -- but a side that lost a QUARTER of the keys did not
    # delete them, it broke (CLAUDE.md rule 2). `persist_state.s_company_dict` already refuses
    # that from OUR side; until 458 the unconditional rescue below was silently providing the
    # same protection for ORIGIN's side, and `_keyed_list` has no other guard at all. So the
    # rescue survives for exactly the case it was accidentally covering.
    origin_lost = [k for k in base if k not in theirs]
    origin_broke = len(base) >= 20 and len(origin_lost) > 0.25 * len(base)
    for k, v in ours.items():
        if k not in base or base[k] != v:
            out[k] = v            # this run touched it
            changed += 1
        elif k not in theirs and (not theirs or origin_broke):
            # Origin is empty, unreadable, or has dropped a quarter of the cache: that is a
            # broken run, not a deletion, so don't lose the key. It used to rescue whatever
            # origin said, which made the two deletion arms asymmetric -- ours honoured,
            # origin's undone -- so any process holding an older checkout re-added every key
            # origin had retired since. Measured 2026-08-30 (registry, 458): 44 names retired
            # by 1ce0db5 and a07e743 between 00:28 and 00:54 were back in
            # research_companies.json at 00:41, put there by 5ccd60e, the listing-hunt cron's
            # own state commit, checked out before those retirements.
            out[k] = v
            kept += 1
    for k in base:
        if k not in ours and k in theirs and theirs[k] == base[k]:
            del out[k]            # we deleted it, origin left it alone: the deletion stands
    return out, changed, kept


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    base, ours, theirs, out = sys.argv[1:5]
    b, o, t = load(base), load(ours), load(theirs)
    merged, changed, kept = merge(b, o, t)
    from pipeline.atomic import write_json
    write_json(out, merged, indent=1, sort_keys=True)     # atomic, like every other state writer
    print(f"merged {out}: {len(merged)} companies "
          f"(theirs {len(t)}, ours {len(o)}, {changed} changed by this run, {kept} rescued)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
