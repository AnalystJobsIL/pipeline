"""POC: richer per-company profile — join firmographics with requirement signals.

Proves the concept on 5 companies from different fields (cyber, fintech, medical AI,
automotive, SaaS). Pulls their LIVE Israel postings through the existing fetchers,
runs roleprofile.extract on each, and folds the results into a per-company
"requirement fingerprint". Firmographics (sector, size, stage, model) are merged in
from poc_firmographics.json (researched once per company, like company_info blurbs).

    python poc_company_profile.py            # writes out/poc_company_profiles.json

The point of the POC: with both halves in one record, the board can answer
"what does this TYPE of company ask for" instead of only "what does this company ask for".
"""
from __future__ import annotations

import json
import os
from collections import Counter

from pipeline.companies import load_companies
from pipeline.fetchers import fetch_company
from pipeline.israel import is_israel_job
from pipeline import roleprofile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "poc_company_profiles.json")
FIRMO = os.path.join(HERE, "poc_firmographics.json")

POC_COMPANIES = ["Wiz", "Melio", "Aidoc", "Mobileye", "monday.com"]


def fingerprint(jobs):
    """Fold per-job role profiles into one company-level requirement fingerprint."""
    profiles = [roleprofile.extract(j.get("title", ""), j.get("description", "") or j.get("snippet", "")) for j in jobs]
    fams = Counter(p["family"] for p in profiles)
    skills = Counter(n for p in profiles for n, _c in p["skills"])
    tracks = Counter(p["track"] for p in profiles)
    years = [p["years"] for p in profiles if p["years"]]
    degrees = Counter(f"{p['degree']['level']} ({p['degree']['status']})"
                      for p in profiles if p.get("degree"))
    ai = Counter(lbl for p in profiles for lbl, _tok in (p.get("ai") or []))
    return {
        "israel_openings": len(jobs),
        "role_families": dict(fams.most_common()),
        "top_skills": dict(skills.most_common(15)),
        "track_mix": dict(tracks),
        "years_experience": {
            "median": sorted(years)[len(years) // 2] if years else None,
            "asked_in_n_jobs": len(years),
        },
        "degree_asks": dict(degrees.most_common(5)),
        "ai_mentions": dict(ai.most_common(5)),
        "sample_titles": [j.get("title", "") for j in jobs[:10]],
    }


def main():
    rows = {r["company_name"]: r for r in load_companies()}
    firmo = {}
    if os.path.exists(FIRMO):
        with open(FIRMO, encoding="utf-8") as f:
            firmo = json.load(f)

    result = {}
    for name in POC_COMPANIES:
        row = rows.get(name)
        if not row:
            print(f"!! {name}: not in companies.csv (or inactive)")
            continue
        try:
            jobs = fetch_company(row)
        except Exception as e:  # noqa: BLE001
            print(f"!! {name}: fetch failed: {e}")
            continue
        il = [j for j in jobs if is_israel_job(j)]
        print(f"{name}: {len(jobs)} jobs total, {len(il)} Israel")
        result[name] = {
            "firmographics": firmo.get(name, {}),
            "requirements": fingerprint(il),
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
