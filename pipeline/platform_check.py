"""Consistency self-check for ATS platform wiring.

Adding a platform means touching ~22 places across ~14 files. Miss one and the platform is
SILENTLY half-wired: it fetches when hand-configured, but no resolver can ever discover it,
or its rows are permanently mis-flagged. That failure is invisible — there is no error, just
coverage that never happens (jazzhr has sat in stale.json as `empty-board` forever for
exactly this reason).

This converts that silent half-wiring into a visible report. Read-only.

    python -m pipeline.platform_check          # report
    python -m pipeline.platform_check --strict # exit 1 if anything is missing (CI gate)
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# platforms that are not real ATS integrations
PSEUDO = {"scrape", "discovery"}
# fetchers that legitimately return [] and must be exempt from the empty-board flag
BY_DESIGN_EMPTY = {"jazzhr"}


def _read(rel):
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def check():
    from .fetchers import FETCHERS

    platforms = sorted(p for p in FETCHERS if p not in PSEUDO)
    sources = {
        "ATS_HOST(health)": _read("pipeline/health.py"),
        "ATS_HOST(resolve_broken)": _read("resolve_broken.py"),
        "SIGS(audit)": _read("audit_empty_rows.py"),
        "ATS_PATTERNS(resolve_deep)": _read("resolve_deep.py"),
        "llm-prompt(resolve_llm)": _read("resolve_llm.py"),
        "empty-exempt(health)": _read("pipeline/health.py"),
    }
    # a platform is "known" to a source if its name or its canonical host appears there
    hosts = {
        "comeet": "comeet", "greenhouse": "greenhouse", "lever": "lever",
        "smartrecruiters": "smartrecruiters", "recruitee": "recruitee", "ashby": "ashby",
        "workday": "myworkdayjobs", "oraclehcm": "oraclecloud", "workable": "workable",
        "breezy": "breezy", "bamboohr": "bamboohr", "jazzhr": "jazzhr|applytojob",
        "microsoft": "microsoft", "custom_json": "amazon",
    }
    rows, missing_total = [], 0
    for p in platforms:
        h = hosts.get(p, p)
        rx = re.compile(h, re.I)
        row = {"platform": p}
        for label, text in sources.items():
            if label == "empty-exempt(health)":
                m = re.search(r'plat not in \(([^)]*)\)', text)
                exempt = (m.group(1) if m else "")
                need = p in BY_DESIGN_EMPTY
                ok = (p in exempt) if need else True
                row[label] = "ok" if ok else "MISSING"
            else:
                row[label] = "ok" if rx.search(text) else "MISSING"
            missing_total += row[label] == "MISSING"
        rows.append(row)

    labels = list(sources)
    w = max(len(p) for p in platforms) + 1
    print(f"{'platform':<{w}} " + " ".join(f"{l[:14]:<15}" for l in labels))
    for r in rows:
        line = f"{r['platform']:<{w}} " + " ".join(
            f"{('ok' if r[l] == 'ok' else 'MISSING'):<15}" for l in labels)
        print(line)
    print(f"\n{len(platforms)} platforms · {missing_total} missing wirings")
    if missing_total:
        print("A MISSING cell means resolvers cannot discover that platform on their own —\n"
              "hand-added rows still fetch, but nothing will ever find it in the wild.")
    return missing_total


if __name__ == "__main__":
    n = check()
    if "--strict" in sys.argv and n:
        sys.exit(1)
