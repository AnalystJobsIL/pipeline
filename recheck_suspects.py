#!/usr/bin/env python3
"""Deep-recheck 'empty-but-suspect' companies (raw HTML showed role-words near Israel cities).
Runs the FULL deep resolver (render + scrape + follow-jobs-link). Promotes any with real Israel
jobs; otherwise clears the suspicion back to confirmed-empty. Updates companies.csv in place."""
from __future__ import annotations

import csv
import json

from resolve_deep import resolve


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "empty-but-suspect" in (r[5] or "").lower()}
    print(f"deep-rechecking {len(idx)} suspects ...")
    try:
        cache = json.load(open("scraped_cache.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    promoted = cleared = 0
    for name, (rowi, url) in idx.items():
        try:
            kind, payload = resolve(name, url)
        except Exception:  # noqa: BLE001
            kind, payload = "empty", None
        if kind == "ats":
            nm, plat, tok, api, n_all, il = payload
            rows[rowi] = [nm, plat, tok, api, "true", f"suspect-promoted; {n_all}/{il} IL"]
            promoted += 1
            print(f"  [PROMOTE] {name}: {plat} {il} IL", flush=True)
        elif kind == "scrape":
            cache[name] = payload
            rows[rowi] = [name, "scrape", url, url, "true",
                          f"suspect-promoted scrape; {len(payload)} IL"]
            promoted += 1
            print(f"  [PROMOTE] {name}: scrape {len(payload)} IL", flush=True)
        else:
            rows[rowi][5] = "scanned; no open Israel roles now (suspect cleared)"
            cleared += 1
    with open("companies.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    with open("scraped_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"=== promoted {promoted} · cleared {cleared} ===")


if __name__ == "__main__":
    main()
