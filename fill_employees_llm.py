#!/usr/bin/env python3
"""Fill/verify employee counts the LinkedIn pass missed or got suspiciously wrong.

Targets: firmographics records with null employees_global, PLUS linkedin-sourced counts
that contradict the page's own self-reported bucket (count below the bucket floor, or
>5x its cap, or a tiny count under 10 — generic-name pages often match the wrong company).

Each target gets ONE focused `claude -p` web lookup that explicitly checks the company's
own website (About/Team/Careers), recent press, and LinkedIn, using the record's sector +
Israel site for disambiguation. Approximations are accepted and flagged (is_estimate),
because for small privates an honest "~40 (press, 2025)" beats null.

    python fill_employees_llm.py            # fix all targets
    python fill_employees_llm.py --dry-run  # just list targets
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline.store import SeenStore

_PROMPT = (
    "What is the current global employee count of the company \"{company}\"?\n"
    "Disambiguation — it is specifically: {sector}; {sub}; Israel site: {il}. "
    "Do not confuse it with other companies of the same name.\n"
    "Check, in order: the company's own website (About/Team/Careers pages), recent press "
    "or funding coverage, LinkedIn. If it was acquired, give the unit's approximate "
    "headcount if reported, else the best pre-acquisition figure.\n"
    'Output ONLY JSON: {{"employees": <integer or null>, "is_estimate": <true|false>, '
    '"source": "<one line: where the number came from, with year>"}}. '
    "An approximate figure with is_estimate=true is fine; null only if nothing credible exists."
)


def _bucket_bounds(rng):
    if not rng:
        return None
    m = re.match(r"(\d+)(?:-(\d+)|\+)", str(rng))
    if not m:
        return None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else 10 ** 9
    return lo, hi


def suspect(rec):
    """A linkedin count that contradicts its own bucket, or is implausibly tiny."""
    if rec.get("employees_source") != "linkedin":
        return False
    n = rec.get("employees_global")
    if not n:
        return False
    if n < 10:
        return True
    b = _bucket_bounds(rec.get("employees_range"))
    return bool(b and (n < b[0] or n > 5 * b[1]))


def lookup(company, rec, timeout=240):
    prompt = _PROMPT.format(company=company, sector=rec.get("sector", "?"),
                            sub=rec.get("sub_sector", ""), il=rec.get("il_center", "?"))
    try:
        proc = subprocess.run(["claude", "-p", "--allowedTools", "WebSearch"],
                              input=prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, shell=True)
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"\{.*\}", (proc.stdout or ""), re.S)
    if proc.returncode != 0 or not m:
        return None
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return None
    n = out.get("employees")
    if not (isinstance(n, (int, float)) and 1 <= n <= 5_000_000):
        return None
    return {"employees": int(n), "is_estimate": bool(out.get("is_estimate")),
            "source": " ".join(str(out.get("source", "")).split())[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    st = SeenStore()
    recs = st.load_firmographics()
    targets = {c: r for c, r in recs.items() if not r.get("employees_global") or suspect(r)}
    print(f"{len(targets)} targets "
          f"({sum(1 for r in targets.values() if not r.get('employees_global'))} null, "
          f"{sum(1 for r in targets.values() if suspect(r))} suspect linkedin matches)")
    if a.dry_run:
        for c, r in sorted(targets.items()):
            why = "null" if not r.get("employees_global") else \
                f"suspect: {r['employees_global']} vs bucket {r.get('employees_range')}"
            print(f"  - {c} ({why})")
        return

    today = dt.date.today().isoformat()
    fixed = missed = 0
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = {ex.submit(lookup, c, r): c for c, r in targets.items()}
        for fut in as_completed(futs):
            c = futs[fut]
            out = fut.result()
            if not out:
                missed += 1
                print(f"  miss {c}", flush=True)
                continue
            rec = recs[c]
            rec["employees_global"] = out["employees"]
            rec["employees_source"] = f"web: {out['source']}" + (" (estimate)" if out["is_estimate"] else "")
            rec["employees_as_of"] = today
            st.save_firmographics({c: rec}, today)
            fixed += 1
            print(f"  ok   {c}: {out['employees']}{' ~' if out['is_estimate'] else ''} ({out['source']})", flush=True)
    print(f"=== fixed {fixed} · miss {missed} ===")


if __name__ == "__main__":
    main()
