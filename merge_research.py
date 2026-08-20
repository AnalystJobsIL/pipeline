"""Merge all out/research_*.json (+ research_companies.json) into one de-duplicated list,
written back to research_companies.json for ingest_research.py to process."""
import glob
import json
import os

seen = {}
files = sorted(glob.glob("out/research_*.json"))
if os.path.exists("research_companies.json"):
    files.append("research_companies.json")

for fp in files:
    try:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"  skip {fp}: {type(e).__name__}")
        continue
    n0 = len(seen)
    for e in data:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        k = name.lower()
        # prefer an entry that specifies a known ats+slug over an "unknown" duplicate
        if k not in seen or (seen[k].get("ats") in (None, "", "unknown") and
                             e.get("ats") not in (None, "", "unknown")):
            seen[k] = e
    print(f"  {fp}: +{len(seen) - n0} new (had {len(data)})")

out = list(seen.values())
with open("research_companies.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(f"=== merged {len(out)} unique companies -> research_companies.json ===")
