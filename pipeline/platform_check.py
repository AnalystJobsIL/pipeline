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
        src = inspect.getsource(fn)
        narrows = bool(re.search(r"Israel|ISR", src))                     # a hybrid pass)
        verdict_ok = (health.stale_reason(p, "", 0, "empty", 0) is None) == scoped
        # Can the board-freshness verdict (`health.abandoned`) judge this platform? `scoped`:
        # never (its postings are Israel hits, not the board). `undated`: never (the list
        # publishes no dates — the fetcher writes a literal `"posted_date": ""` and DECLARES
        # `undated = True`). `ok`: yes. MISSING, both directions like the scope cell: a
        # fetcher that writes the blank without declaring it, or declares it and dates its
        # postings (the declaration is a lie). A SOURCE-level cell, and it says so: a
        # platform whose tenants leave the date field empty (bamboohr: 0 dated of 82
        # postings on 2026-08-30; successfactors 0 of 28) reads `ok` here and is blind at
        # runtime — the census, not this grid, is what sees that.
        # The cell sits BEFORE the two behaviour cells: `tests/test_units.py` reads those
        # two positionally as the last two tokens of the printed line.
        blank = bool(re.search(r'"posted_date":\s*""', src))
        undated = bool(getattr(fn, "undated", False))
        row["freshness(judge)"] = ("MISSING" if blank != undated else
                                   "scoped" if scoped else "undated" if undated else "ok")
        # both directions: narrows ⇒ declared (a forgotten attribute flags healthy zeros);
        # scoped ⇒ narrows (a fetcher that does NOT ask for Israel yet claims to would
        # switch empty-board detection off for its whole platform)
        row["israel-scoped(fetcher)"] = "ok" if ((declared or not narrows) and (narrows or not scoped)) else "MISSING"
        row["empty->flag(health)"] = "ok" if verdict_ok else "MISSING"
        missing_total += row["freshness(judge)"] == "MISSING"
        missing_total += row["israel-scoped(fetcher)"] == "MISSING"
        missing_total += row["empty->flag(health)"] == "MISSING"
        rows.append(row)

    labels = list(sources) + ["freshness(judge)", "israel-scoped(fetcher)", "empty->flag(health)"]
    w = max(len(p) for p in platforms) + 1
    print(f"{'platform':<{w}} " + " ".join(f"{l[:14]:<15}" for l in labels))
    for r in rows:
        # the freshness cell has three healthy words; every other cell is ok / MISSING
        line = f"{r['platform']:<{w}} " + " ".join(
            f"{(r[l] if l == 'freshness(judge)' or r[l] == 'ok' else 'MISSING'):<15}" for l in labels)
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
