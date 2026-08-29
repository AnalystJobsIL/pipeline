#!/usr/bin/env python3
"""Drain the intake queue, and keep every address in the registry LLM-verified.

    python queue_pipeline.py --verify-existing            # dry run: what would be parked
    python queue_pipeline.py --verify-existing --apply
    python queue_pipeline.py --census                     # the table, from the files on disk

**The standard this exists to enforce.** Every name that ever entered
`research_companies.json` ends as exactly one of: a duplicate / an acquired company / not an
employer, RETIRED with its evidence; or a real company whose board we found, as an ACTIVE row
or an LLM-VERIFIED monitor row. Nothing "owed", and no address in `companies.csv` that a model
has not read.

**Why the verify arm comes first.** Measured 2026-08-29 over the live registry: 554 parked rows
carry `monitored candidate`, of which **187 were written by the `listing-hunt` cron and were
never LLM-checked at all** and 147 more were admitted by a mechanical title match; 197 ACTIVE
rows written from the queue carry no QA record; and **29 rows exist despite a `NOT-THEIRS`
verdict** in an earlier run of the same tool (`Greylock Partners`, refused once and admitted
once, is ACTIVE on a VC's portfolio-jobs page).

That is not cosmetic debt. `probe_candidates` fetches every parked row's address DAILY, and
`listing_hunt.hunt_one`'s fast path (`listing_hunt.py:297`) ACTIVATES the row the moment that
page shows Israel roles -- on `il and not is_foreign(...)`, with no model in the loop and
`is_foreign` inert on every ATS host. **A wrong monitor address is a wrong ACTIVE row on a
timer**, publishing another employer's jobs under this company's name.

**What a failed verdict does.** The row is parked AND ITS ADDRESS IS CLEARED: an address that
is not this company's must leave `probe_candidates`' pool, or the daily probe keeps fetching
it and the fast path keeps its chance. The note is written through `pipeline.notes.append` and
carries `needs re-resolution`, which is in `verdicts.TOKENS` and in `listing_hunt`'s hunt pool,
so the row lands in a re-check pool rather than in silence (the defect `confirm_zero` had).
`UNVERIFIABLE` -- we could not READ the page -- changes nothing: it is not a refusal, and
turning "we failed to look" into a verdict is the error this repo punishes hardest.

lane: `registry`.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TODAY = dt.date.today().isoformat()
QUEUE = "research_companies.json"
CSV = "companies.csv"
RECEIPT = os.path.join("cloud_state", "queue_receipt.json")

# a row this lane wrote from the queue, whatever rung wrote it
QUEUE_MARKERS = ("queue-drain", "queue-search", "queue-hunt")
MONITOR_TOKEN = "monitored candidate"


def rows():
    with open(CSV, encoding="utf-8") as f:
        return [r for r in csv.reader(f) if r]


def from_queue(r):
    return any(m in (r[5] or "") for m in QUEUE_MARKERS)


def needs_verify(r, state):
    """Rows whose address is live and unverified: every parked monitor, and every ACTIVE row
    this lane wrote from the queue. A row whose address a model has already passed within the
    cadence is skipped, so a re-run is cheap and idempotent."""
    from pipeline import board_verify as BV
    if len(r) < 6 or not (r[3] or "").startswith("http"):
        return False
    is_monitor = r[4] == "false" and MONITOR_TOKEN in (r[5] or "")
    is_queue_active = r[4] == "true" and from_queue(r)
    if not (is_monitor or is_queue_active):
        return False
    return not BV.is_ok(state, r[0], r[3])


def park_unverified(name, employer, apply=False):
    """Park the row and CLEAR its address. Re-reads the file immediately before the write and
    matches by NAME, never by index (rule 4)."""
    from pipeline.atomic import write_csv_rows
    from pipeline.notes import append
    fresh = rows()
    hit = None
    for r in fresh:
        if r and r[0].strip().lower() == name.strip().lower():
            hit = r
            break
    if hit is None:
        return False
    seg = "wrong-url %s: %s; needs re-resolution" % (
        TODAY, ("board names %s" % employer)[:60] if employer else "not this company's board")
    note = append(hit[5] if len(hit) > 5 else "", seg)
    if seg not in note:
        # the append-log refused the segment (cap/eviction). Deactivating a row whose note
        # could not record WHY is how a row lands in no pool at all -- so do neither.
        return False
    if not apply:
        return True
    hit[3] = ""                      # out of probe_candidates' pool: no address, no daily fetch
    hit[4] = "false"
    hit[5] = note
    write_csv_rows(CSV, fresh)
    return True


def verify_existing(limit=0, apply=False, allow_paid=True, shard=""):
    from pipeline import board_verify as BV
    state = BV.load()
    todo = [r for r in rows() if needs_verify(r, state)]
    if shard and "/" in shard:
        i, n = (int(x) for x in shard.split("/", 1))
        todo = todo[i - 1::n]
    if limit:
        todo = todo[:limit]
    print("rows with a live address and no fresh verdict: %d%s"
          % (len(todo), " (shard %s)" % shard if shard else ""), flush=True)
    stats = collections.Counter()
    for i, r in enumerate(todo, 1):
        rec = BV.verify(r[0], r[3], state=state, allow_paid=allow_paid)
        v = rec.get("verdict")
        stats[v] += 1
        flag = ""
        if v in (BV.NOT_THEIRS, BV.NOT_A_BOARD):
            ok = park_unverified(r[0], rec.get("employer_named") or "", apply=apply)
            stats["parked" if (ok and apply) else "would-park" if ok else "park-refused"] += 1
            flag = "-> PARKED, address cleared" if apply else "-> would park"
        print("  [%d/%d] %-30s %-6s %-13s %-22s %s"
              % (i, len(todo), r[0][:30], "ACTIVE" if r[4] == "true" else "park", v,
                 (rec.get("employer_named") or "")[:22], flag), flush=True)
        BV.save(state)                       # per row: this pays for renders and credits
    print("\n=== verify-existing %s: %s" % (TODAY, dict(stats)))
    if not apply:
        print("(dry run: companies.csv untouched)")
    return stats


def census():
    """The table, from the files on disk. Reports names STILL OWED, never names with a verdict."""
    from pipeline import board_verify as BV
    import queue_state as QS
    try:
        disp = json.load(open(os.path.join("cloud_state", "queue_disposition.json"),
                              encoding="utf-8"))
    except Exception:                                             # noqa: BLE001
        disp = {}
    queue = [(e.get("name") or "").strip()
             for e in json.load(open(QUEUE, encoding="utf-8"))]
    retired = {n for n, v in disp.items() if v.get("verdict") == "already-a-row"}
    ever = sorted(set(queue) | retired | set(disp))
    by_name = {r[0].strip().lower(): r for r in rows()}
    state = BV.load()

    b = collections.Counter()
    owed = []
    for n in ever:
        r = by_name.get(n.lower())
        if r is not None:
            if r[4] == "true":
                b["ROW, ACTIVE"] += 1
            elif (r[3] or "").startswith("http"):
                b["ROW, parked with an address (daily probe)"] += 1
            else:
                b["ROW, parked, NO address"] += 1
            continue
        if n in retired or (disp.get(n) or {}).get("verdict") in (
                "no-board", "not-an-employer", "duplicate-of", "acquired-by"):
            b["retired with evidence"] += 1
            continue
        b["STILL OWED"] += 1
        owed.append(n)

    unverified = sum(1 for r in rows() if needs_verify(r, state))
    print("EVERY NAME THAT EVER ENTERED THE QUEUE: %d\n" % len(ever))
    for k in sorted(b):
        print("  %-46s %5d" % (k, b[k]))
    print("\n  %-46s %5d" % ("rows with an UNVERIFIED live address", unverified))
    receipt = {"date": TODAY, "buckets": dict(b), "unverified_rows": unverified,
               "owed": owed[:2000]}
    os.makedirs("cloud_state", exist_ok=True)
    from pipeline.atomic import write_json
    write_json(RECEIPT, receipt)
    print("\nwrote %s" % RECEIPT)
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify-existing", action="store_true",
                    help="LLM-verify every live address that has no fresh verdict")
    ap.add_argument("--census", action="store_true", help="print the table and write a receipt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default=os.environ.get("QP_SHARD", ""))
    ap.add_argument("--no-paid", action="store_true", help="never spend a Bright Data credit")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.verify_existing:
        verify_existing(limit=a.limit, apply=a.apply, allow_paid=not a.no_paid, shard=a.shard)
    if a.census or not a.verify_existing:
        census()
    return 0


if __name__ == "__main__":
    sys.exit(main())
