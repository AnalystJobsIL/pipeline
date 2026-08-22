#!/usr/bin/env python3
"""Deep-recheck 'empty-but-suspect' companies (raw HTML showed role-words near Israel cities).
Runs the FULL deep resolver (render + scrape + follow-jobs-link). Promotes any with real Israel
jobs; otherwise clears the suspicion back to confirmed-empty. Updates companies.csv in place."""
from __future__ import annotations

import csv
import json

from resolve_deep import resolve


_MODIFIED = set()   # names this run rewrote (single-writer merge)


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
            _MODIFIED.add(nm)
            promoted += 1
            print(f"  [PROMOTE] {name}: {plat} {il} IL", flush=True)
        elif kind == "scrape":
            cache[name] = payload
            _MODIFIED.add(name)
            rows[rowi] = [name, "scrape", url, url, "true",
                          f"suspect-promoted scrape; {len(payload)} IL"]
            promoted += 1
            print(f"  [PROMOTE] {name}: scrape {len(payload)} IL", flush=True)
        else:
            rows[rowi][5] = "scanned; no open Israel roles now (suspect cleared)"
            _MODIFIED.add(name)
            cleared += 1
    # single-writer discipline: merge back only rows this run modified
    changed = {r[0]: r for r in rows if r and len(r) > 5 and r[0] in _MODIFIED}
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for _i, fr in enumerate(fresh):
        if fr and len(fr) > 5 and fr[0] in changed:
            fresh[_i] = changed[fr[0]]
    with open("companies.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(fresh)
    with open("scraped_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"=== promoted {promoted} · cleared {cleared} ===")


if __name__ == "__main__":
    main()
