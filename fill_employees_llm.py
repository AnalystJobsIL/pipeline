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
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline.firmographics import ResearchUnavailable, band_for, identity_key
from pipeline.store import SeenStore

# chain redirects stdout to a file -> cp1252 on Windows -> Hebrew names crash prints
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RETRY_MISS_DAYS = 30  # a company neither pass could measure retries monthly, not every 6h

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
    """A linkedin count worth re-verifying: weak title match, bucket contradiction,
    or implausibly tiny. NOTE the blind spot this closes: a wrong-page fill is often
    internally consistent (count inside the wrong page's own bucket), so weak matches
    are ALWAYS re-checked regardless of numbers, and the bucket slack is tight (2x, not
    5x — member counts run above self-reported size, but not that far)."""
    src = rec.get("employees_source") or ""
    if not src.startswith("linkedin"):
        return False
    if src == "linkedin-weakmatch":
        return True
    n = rec.get("employees_global")
    if not n:
        return False
    if n < 10:
        return True
    b = _bucket_bounds(rec.get("employees_range"))
    return bool(b and (n < b[0] or n > 2 * b[1]))


def lookup(company, rec, timeout=240):
    prompt = _PROMPT.format(company=company, sector=rec.get("sector", "?"),
                            sub=rec.get("sub_sector", ""), il=rec.get("il_center", "?"))
    try:
        proc = subprocess.run(["claude", "-p", "--allowedTools", "WebSearch"],
                              input=prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, shell=True)
    except Exception as e:  # noqa: BLE001 — infrastructure, not the company
        raise ResearchUnavailable(str(e))
    if proc.returncode != 0:
        raise ResearchUnavailable((proc.stderr or proc.stdout or "")[:200])
    m = re.search(r"\{.*\}", (proc.stdout or ""), re.S)
    if not m:
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
    retry_cutoff = (dt.date.today() - dt.timedelta(days=RETRY_MISS_DAYS)).isoformat()
    targets = {c: r for c, r in recs.items()
               if (not r.get("employees_global") or suspect(r))
               and not (r.get("employees_lookup_miss") or "") > retry_cutoff}
    # one lookup per identity per run — two name-forms of one company must not both pay
    seen_ids, deduped = set(), {}
    for c, r in targets.items():
        ik = identity_key(c)
        if ik in seen_ids:
            continue
        seen_ids.add(ik)
        deduped[c] = r
    targets = deduped
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
    fixed = missed = infra_streak = 0
    pending_miss = []
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = {ex.submit(lookup, c, r): c for c, r in targets.items()}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                out = fut.result()
            except ResearchUnavailable as e:
                # outage: no miss stamp — a 30-day gate for a whole cohort because the
                # CLI was logged out at 03:00 would be a timeliness disaster
                infra_streak += 1
                print(f"  UNAVAILABLE {c}: {e} (no miss recorded)", flush=True)
                if infra_streak >= 3:
                    print("3 consecutive infrastructure errors — aborting; nothing was gated")
                    ex.shutdown(cancel_futures=True)
                    break
                continue
            infra_streak = 0
            if not out:
                missed += 1
                # DEFERRED: stamps and quarantines apply only after the run proves it
                # wasn't a soft outage (exit-0 prose, broken tool grant) — a broken run
                # must not month-gate the cohort or destroy weak-match counts
                pending_miss.append(c)
                print(f"  miss {c} (pending)", flush=True)
                continue
            rec = recs[c]
            rec["employees_global"] = out["employees"]
            rec["size_band"] = band_for(out["employees"])  # keep band and count consistent
            rec["employees_source"] = f"web: {out['source']}" + (" (estimate)" if out["is_estimate"] else "")
            rec["employees_as_of"] = today
            rec.pop("employees_lookup_miss", None)
            st.save_firmographics({c: rec}, today)
            fixed += 1
            print(f"  ok   {c}: {out['employees']}{' ~' if out['is_estimate'] else ''} ({out['source']})", flush=True)
    if pending_miss and fixed == 0 and len(pending_miss) >= 5:
        print(f"mass-failure guard: 0 fills, {len(pending_miss)} misses — suspected soft "
              "outage; no stamps or quarantines applied, names retry next run")
    else:
        for c in pending_miss:
            rec = recs[c]
            if (rec.get("employees_source") or "") == "linkedin-weakmatch":
                # QUARANTINE: a name-fragment page match that verification couldn't
                # confirm — an honest null beats a namesake's number served forever
                rec["employees_global"] = None
                rec.pop("employees_range", None)
                rec["size_band"] = ""
                rec["employees_source"] = "linkedin-weakmatch-quarantined"
                print(f"  quarantined weak-match count for {c}", flush=True)
            rec["employees_lookup_miss"] = today
            st.save_firmographics({c: rec}, today)
    print(f"=== fixed {fixed} · miss {missed} ===")


if __name__ == "__main__":
    main()
