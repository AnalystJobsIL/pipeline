#!/usr/bin/env python3
"""Join firmographics with ACTUAL matched jobs: what does each TYPE of company ask for?

Reads real board jobs from the matched table (default: cloud_state/seen.db — the CI-
accumulated set; --db to point elsewhere), runs roleprofile.extract on each, joins each
company's firmographics record (the committed cloud_state/firmographics.json), and aggregates
requirement patterns along three company-type axes: sector, stage, size_band.

    python company_type_analysis.py                # writes out/company_type_analysis.{json,md}
    python company_type_analysis.py --db state/seen.db

Per axis value it reports: companies, jobs, top skills, median years-experience,
degree-required rate, lead-role share, and AI-usage mention rate — the concrete
"company type <-> requirement type" connection the profiles were built for.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

# printed company names include Hebrew; redirected stdout on Windows is cp1252 without this
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline import roleprofile
from pipeline.firmographics import SHARED_EXPORT, identity_key

HERE = os.path.dirname(os.path.abspath(__file__))
# the COMMITTED export — `state/firmographics.json` is gitignored and absent in the cloud
FIRMO = SHARED_EXPORT


# The researcher's free-text sectors fragment ("adtech", "adtech / martech", "marketing
# technology / adtech" were three different groups). Collapse to a canonical primary
# sector: first alias hit wins, else the text before the first "/", cleaned.
_SECTOR_ALIASES = [
    ("cybersecurity", ("cyber", "security")),
    ("fintech", ("fintech", "payments", "banking", "insur", "crypto", "trading")),
    ("healthtech", ("health", "medical", "pharma", "biotech", "life science")),
    ("adtech / martech", ("adtech", "martech", "marketing tech", "advertising")),
    ("gaming", ("gaming", "igaming", "casino")),
    ("automotive / semiconductors", ("automotive", "semiconductor", "chip", "lidar", "mobility")),
    ("SaaS", ("saas", "productivity", "enterprise software", "work management")),
    ("data / AI infrastructure", ("data analytics", "ai infrastructure", "devtools", "cloud comput",
                                  "platform engineering", "data infrastructure", "observability")),
    ("e-commerce / marketplace", ("e-commerce", "ecommerce", "marketplace", "retail tech")),
    ("IT services", ("it services", "consulting", "outsourcing", "recruitment", "staffing")),
]


def primary_sector(raw):
    s = (raw or "").lower()
    for canon, keys in _SECTOR_ALIASES:
        if any(k in s for k in keys):
            return canon
    return (raw or "(unknown)").split("/")[0].strip() or "(unknown)"


def load_jobs(db):
    con = sqlite3.connect(db)
    rows = con.execute("SELECT company, title, description FROM matched").fetchall()
    con.close()
    return rows


def fold(jobs_with_profiles):
    """Aggregate (job_profile, firmo) pairs into one stats block."""
    skills = Counter()
    years, lead, deg_req, ai_jobs = [], 0, 0, 0
    companies = set()
    for prof, firmo, company in jobs_with_profiles:
        companies.add(company)
        for n, _c in prof["skills"]:
            skills[n] += 1
        if prof.get("years"):
            years.append(prof["years"])
        if prof.get("track") == "Lead":
            lead += 1
        d = prof.get("degree")
        if d and d.get("status") == "required":
            deg_req += 1
        if prof.get("ai"):
            ai_jobs += 1
    n = len(jobs_with_profiles)
    return {
        "companies": len(companies),
        "jobs": n,
        "top_skills": dict(skills.most_common(10)),
        "median_years": sorted(years)[len(years) // 2] if years else None,
        "degree_required_rate": round(deg_req / n, 2) if n else None,
        "lead_share": round(lead / n, 2) if n else None,
        "ai_mention_rate": round(ai_jobs / n, 2) if n else None,
    }


def main():
    fetched = os.path.join(HERE, "state", "cloud_seen_fetch.db")  # chain-extracted, CI-fresh
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=fetched if os.path.exists(fetched)
                    else os.path.join(HERE, "cloud_state", "seen.db"),
                    help="seen.db holding the matched jobs (default: the chain's fetched "
                         "copy of CI's db when present, else the worktree cloud_state)")
    ap.add_argument("--firmo", default=FIRMO, help="firmographics export to join (default: "
                    "the committed cloud_state/firmographics.json)")
    a = ap.parse_args()

    print(f"db: {a.db}\nfirmographics: {a.firmo}")
    with open(a.firmo, encoding="utf-8") as f:
        firmo = json.load(f)
    jobs = load_jobs(a.db)

    # join falls back to normalized identity — "SolarEdge" (board) must find
    # "SolarEdge Technologies" (profile); exact-string-only silently splits companies.
    # Exact match wins first so a deliberate subsidiary record ("Bosch Israel") is
    # preferred over the identity-collapsed parent when both exist.
    norm_index = {identity_key(k): v for k, v in firmo.items()}
    joined, unmatched = [], Counter()
    for company, title, desc in jobs:
        rec = firmo.get(company) or norm_index.get(identity_key(company))
        if not rec:
            unmatched[company] += 1
            continue
        if (rec.get("employees_source") or "") == "linkedin-weakmatch":
            # pending verification: the count/band may belong to a NAMESAKE company.
            # Sector/stage are researcher data and stay usable; size must not be served
            # until the verify pass confirms (verified windows can lag under outages).
            rec = {**rec, "size_band": "", "employees_global": None}
        joined.append((roleprofile.extract(title, desc or ""), rec, company))
    print(f"{len(jobs)} matched jobs, {len(joined)} joined to firmographics, "
          f"{sum(unmatched.values())} jobs at {len(unmatched)} unprofiled companies")
    if unmatched:
        print("  unprofiled:", ", ".join(sorted(unmatched)))

    axes = {}
    for axis, key in (("by_sector", "sector"), ("by_stage", "stage"), ("by_size", "size_band")):
        groups = defaultdict(list)
        for prof, rec, company in joined:
            val = primary_sector(rec.get(key)) if key == "sector" else (rec.get(key) or "(unknown)")
            groups[val].append((prof, rec, company))
        axes[axis] = {v: fold(g) for v, g in
                      sorted(groups.items(), key=lambda kv: -len(kv[1]))}

    out = {"jobs_analyzed": len(joined), "source_db": a.db, "axes": axes}
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    jp = os.path.join(HERE, "out", "company_type_analysis.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # human-readable companion
    lines = [f"# Company type ↔ requirement type ({len(joined)} jobs)\n"]
    for axis, title in (("by_sector", "By sector"), ("by_stage", "By stage"), ("by_size", "By size band")):
        lines.append(f"\n## {title}\n")
        lines.append("| type | companies | jobs | median yrs | degree req | lead share | AI rate | top skills |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for val, s in axes[axis].items():
            top = ", ".join(list(s["top_skills"])[:5])
            lines.append(f"| {val} | {s['companies']} | {s['jobs']} | {s['median_years'] or '—'} | "
                         f"{s['degree_required_rate']} | {s['lead_share']} | {s['ai_mention_rate']} | {top} |")
    mp = os.path.join(HERE, "out", "company_type_analysis.md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {jp}\nwrote {mp}")


if __name__ == "__main__":
    main()
