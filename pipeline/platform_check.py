"""Consistency self-check for ATS platform wiring.

Adding a platform means touching ~22 places across ~14 files. Miss one and the platform is
SILENTLY half-wired: it fetches when hand-configured, but no resolver can ever discover it,
or its rows are permanently mis-flagged. That failure is invisible — there is no error, just
coverage that never happens (`jazzhr` sat in stale.json as `empty-board` for weeks for
exactly this reason, before the platform was retired on 2026-08-26 — no public JSON, its one
row is a scrape row now).

This converts that silent half-wiring into a visible report. Read-only.

    python -m pipeline.platform_check          # report
    python -m pipeline.platform_check --strict # exit 1 if anything is missing (CI gate)
"""
from __future__ import annotations

import inspect
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# platforms that are not real ATS integrations
PSEUDO = {"scrape", "discovery"}


def _read(rel):
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def check():
    from . import health
    from .fetchers import FETCHERS

    platforms = sorted(p for p in FETCHERS if p not in PSEUDO)
    sources = {
        "ATS_HOST(health)": _read("pipeline/health.py"),
        "ATS_HOST(resolve_broken)": _read("resolve_broken.py"),
        "SIGS(audit)": _read("audit_empty_rows.py"),
        "ATS_PATTERNS(resolve_deep)": _read("resolve_deep.py"),
        "llm-prompt(resolve_llm)": _read("resolve_llm.py"),
    }
    # a platform is "known" to a source if its name or its canonical host appears there
    hosts = {
        "comeet": "comeet", "greenhouse": "greenhouse", "lever": "lever",
        "smartrecruiters": "smartrecruiters", "recruitee": "recruitee", "ashby": "ashby",
        "workday": "myworkdayjobs", "oraclehcm": "oraclecloud", "workable": "workable",
        "breezy": "breezy", "bamboohr": "bamboohr",
        "microsoft": "microsoft", "custom_json": "amazon",
        "eightfold": "eightfold|pcsx", "phenom": "phenom|/widgets",
        # 2026-08-26: no shared host — a SuccessFactors career site lives on the tenant's own
        # domain (jobs.sap.com, careers.stratasys.com), so the path is what identifies it
        "successfactors": "successfactors|tile-search-results", "jobvite": "jobvite",
    }
    rows, missing_total = [], 0
    for p in platforms:
        rx = re.compile(hosts.get(p, p), re.I)
        row = {"platform": p}
        for label, text in sources.items():
            row[label] = "ok" if rx.search(text) else "MISSING"
            missing_total += row[label] == "MISSING"
        # BEHAVIOUR, not source text. Two things can drift and both are checked:
        #  (1) a fetcher whose request narrows to Israel ("Israel" / "ISR" in its source)
        #      must DECLARE `israel_scoped` (True; or False for a hybrid like oraclehcm whose
        #      unscoped pass makes a zero real evidence), or health flags its healthy zeros;
        #  (2) health's verdict for an empty fetch must be None exactly for scoped
        #      platforms. A regex over health.py's source stood here before
        #      and went stale the day that line changed.
        fn = FETCHERS[p]
        scoped = bool(getattr(fn, "israel_scoped", False))
        declared = hasattr(fn, "israel_scoped")      # True, or an explicit False (oraclehcm:
        narrows = bool(re.search(r"Israel|ISR", inspect.getsource(fn)))   # a hybrid pass)
        verdict_ok = (health.stale_reason(p, "", 0, "empty", 0) is None) == scoped
        # both directions: narrows ⇒ declared (a forgotten attribute flags healthy zeros);
        # scoped ⇒ narrows (a fetcher that does NOT ask for Israel yet claims to would
        # switch empty-board detection off for its whole platform)
        row["israel-scoped(fetcher)"] = "ok" if ((declared or not narrows) and (narrows or not scoped)) else "MISSING"
        row["empty->flag(health)"] = "ok" if verdict_ok else "MISSING"
        missing_total += row["israel-scoped(fetcher)"] == "MISSING"
        missing_total += row["empty->flag(health)"] == "MISSING"
        rows.append(row)

    labels = list(sources) + ["israel-scoped(fetcher)", "empty->flag(health)"]
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
