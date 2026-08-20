#!/usr/bin/env python3
"""Coverage report: of every researched company, how many have we SCANNED (validated) and how many
are still to scan. A company counts as scanned whether it has open Israel roles or not — the only
gap is 'still to scan'. Run any time to see convergence toward everyone-scanned."""
import csv
import json

from pipeline.companies import load_companies


def main():
    with open("research_companies.json", encoding="utf-8") as f:
        researched = {(e.get("name") or "").strip().lower() for e in json.load(f) if e.get("name")}

    active = {}
    scanned_empty = unreachable = 0
    for r in csv.DictReader(open("companies.csv", encoding="utf-8")):
        name = (r["company_name"] or "").strip().lower()
        note = (r.get("notes") or "").lower()
        is_active = str(r.get("active")).lower() in ("true", "1", "yes")
        if is_active:
            active[name] = True
        elif "no open israel" in note or "scanned" in note:
            scanned_empty += 1
        elif "unreachable" in note:
            unreachable += 1

    all_csv = {(r["company_name"] or "").strip().lower() for r in
               csv.DictReader(open("companies.csv", encoding="utf-8"))}
    n_active = len(load_companies(active_only=True))
    still = sorted(researched - all_csv)

    total = len(researched | all_csv)
    scanned = len(all_csv)
    print("=" * 56)
    print("  COVERAGE REPORT")
    print("=" * 56)
    print(f"  Researched companies ............ {len(researched)}")
    print(f"  Live boards (active, scanned daily) {n_active}")
    print(f"  Validated-empty (0 open IL roles) . {scanned_empty}")
    print(f"  Unreachable (bad/dead careers URL)  {unreachable}")
    print(f"  ----------------------------------------")
    print(f"  SCANNED / VALIDATED so far ........ {scanned} of ~{total}")
    print(f"  STILL TO SCAN (loop draining) ..... {len(still)}")
    print("=" * 56)
    if still and "--list" in __import__("sys").argv:
        for s in still[:60]:
            print("   -", s)


if __name__ == "__main__":
    main()
