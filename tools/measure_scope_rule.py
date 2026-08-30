"""What did a scope change actually move? (lane: classifier)

`tools/measure_title_gate.py` measures the roles the TITLE gate never sends to the seam.
This measures the other half: of the roles the seam DOES read, which verdicts move when the
rules text changes — and, for every one that moves, whether the move is the new rule working
or a false negative. It is the instrument `docs/decisions/2026-08-28-analyst-scope.md` asks
for ("a measured false-negative rate ... that makes the vocabulary the thing worth changing")
and the one `373@classifier` asks for on the keyword shortcut.

It is a measurement tool: nothing imports it and no workflow runs it.

    python tools/measure_scope_rule.py --dry-run          # build the sample, spend nothing
    python tools/measure_scope_rule.py --workers 4        # ~1 sonnet call per sampled posting

THE SAMPLE is every posting in the committed caches that (a) is in Israel, (b) the title gate
sends onward or fast-accepts, and (c) carries a real description — because a rule about a
role's OUTPUT can only be measured where the output is described. `--tier` picks which of the
gate's own tiers to sample:

    llm       the residue the seam reads today (relevance `signal`, or `strong` non-senior)
    keyword   the strong+senior fast-accepts, which no description has ever touched
    both      the default

THE COMPARISON is against `llm_cache`, read by the SAME lookup order production uses
(`seniority._versioned`, current contract then any superseded one then the legacy
`company|title` row), so "moved" means moved against the verdict that is deciding this
posting today — not against a key that happens to match.

Every call goes through the production seam (`seniority._claude`) with the module's CURRENT
`LLM_RULES`, so run it from a tree where the new rules are already in place: the artifact
stamps `seniority.CONTRACT`, which is what makes a before/after pair self-labelling.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import israel, seniority                      # noqa: E402
from pipeline.jdfill import looks_like_jd                   # noqa: E402

MIN_TEXT = seniority.MIN_DESC          # the same measure the cache key and jdfill gate on


def _load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _flatten(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    return [v for vs in d.values() for v in (vs if isinstance(vs, list) else [vs])
            if isinstance(v, dict)]


def sample(root, tier):
    """Every Israel posting with a real description that the title gate does not reject,
    de-duplicated the way the pipeline does it (`company|title`, longest text wins)."""
    postings = []
    for name in ("discovered_cache.json", "scraped_cache.json"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            postings += _flatten(_load(p))
    best = {}
    for j in postings:
        if not israel.is_israel_job(j):
            continue
        title_l = (j.get("title") or "").lower()
        company_l = (j.get("company") or "").lower()
        rel = seniority._relevance(title_l, company_l)
        if rel in ("excluded", "none") or seniority._NOT_A_JOB.search(title_l):
            continue
        sen = seniority._seniority(title_l)
        row_tier = "keyword" if (rel == "strong" and sen == "senior") else "llm"
        if tier != "both" and row_tier != tier:
            continue
        text = str(j.get("description") or "").strip()
        if len(text) < MIN_TEXT:
            continue
        key = (seniority._norm_company(j.get("company")), seniority._norm(j.get("title")))
        if key not in best or len(text) > len(str(best[key][0].get("description") or "")):
            best[key] = (j, rel, sen, row_tier)
    return [(k,) + v for k, v in sorted(best.items())]


def prior_verdicts(db_path):
    """`llm_cache` indexed the way `Classifier._lookup` reads it: by the JOB a key names."""
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    by_job, legacy = {}, {}
    for key, verdict in con.execute("select title_key, verdict from llm_cache"):
        split = seniority._versioned(key)
        if split:
            suffix, prefix = split
            job = suffix.rsplit("|", 1)[0]
            by_job.setdefault(job, {})[prefix] = bool(verdict)
        else:
            parts = str(key).split("|")
            if len(parts) == 2 and not key.startswith("jdq1|"):
                legacy[seniority._norm_company(parts[0]) + "|" + seniority._norm(parts[1])] = bool(verdict)
    con.close()
    return by_job, legacy


def prior_for(job_key, by_job, legacy, contract):
    """(verdict, which) under production's own precedence, or (None, '')."""
    seen = by_job.get(job_key) or {}
    if contract in seen:
        return seen[contract], "current"
    older = {p: v for p, v in seen.items() if p != contract}
    if older:
        return older[max(older)], "superseded"
    if job_key in legacy:
        return legacy[job_key], "legacy"
    return None, ""


def judge(job, model, timeout, cwd):
    try:
        out = seniority._claude(seniority._posting(job), model=model, timeout=timeout, cwd=cwd)
    except Exception as e:                      # noqa: BLE001 -- an unavailable seam is data
        return None, "%s: %s" % (type(e).__name__, str(e)[:90])
    return (out["verdict"] == "YES") if out["verdict"] in ("YES", "NO") else None, out["reason"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--tier", choices=("llm", "keyword", "both"), default="both")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=seniority.LLM_MODEL)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = sample(a.root, a.tier)
    if a.limit:
        rows = rows[:a.limit]
    by_job, legacy = prior_verdicts(os.path.join(a.root, "cloud_state", "seen.db"))
    print("contract now: %s   model: %s" % (seniority.CONTRACT, a.model))
    print("sample: %d postings with >= %d chars of text (tier %s)" % (len(rows), MIN_TEXT, a.tier))
    tiers = {}
    for _k, _j, _rel, _sen, t in rows:
        tiers[t] = tiers.get(t, 0) + 1
    print("  by gate tier: %s" % tiers)
    if a.dry_run:
        for k, j, rel, sen, t in rows:
            print("   %-8s %-7s %-6s %5d  %s | %s"
                  % (t, rel, sen, len(str(j.get("description") or "")),
                     str(j.get("company"))[:22], str(j.get("title"))[:52]))
        return

    cwd = os.path.join(tempfile.gettempdir(), "scope-scratch")
    os.makedirs(cwd, exist_ok=True)          # must EXIST, and never be the repo
    t0 = time.time()
    results = [None] * len(rows)

    def work(i):
        _k, j, _rel, _sen, _t = rows[i]
        return i, judge(j, a.model, a.timeout, cwd)

    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for n, (i, res) in enumerate(ex.map(work, range(len(rows))), 1):
            results[i] = res
            if n % 10 == 0:
                print("  ... %d/%d  (%.0fs)" % (n, len(rows), time.time() - t0), flush=True)

    out_rows, moved, tally = [], [], {}
    for (k, j, rel, sen, t), (verdict, reason) in zip(rows, results):
        job_key = "%s|%s" % k
        was, which = prior_for(job_key, by_job, legacy, seniority.CONTRACT)
        move = ("unjudged" if was is None else
                "kept" if was == verdict else
                "YES->NO" if was else "NO->YES") if verdict is not None else "no-answer"
        tally[move] = tally.get(move, 0) + 1
        row = {"company": j.get("company"), "title": j.get("title"), "tier": t,
               "relevance": rel, "seniority": sen, "url": j.get("url"),
               "desc_len": len(str(j.get("description") or "")),
               "looks_like_jd": bool(looks_like_jd(str(j.get("description") or ""))),
               "was": was, "was_from": which, "now": verdict, "move": move, "reason": reason}
        out_rows.append(row)
        if move in ("YES->NO", "NO->YES", "no-answer"):
            moved.append(row)

    print("\nverdicts: %s" % tally)
    yes = sum(1 for r in out_rows if r["now"] is True)
    print("YES rate under the current rules: %d/%d" % (yes, len(out_rows)))
    print("\nMOVED (label each by hand from its JD):")
    for r in moved:
        print("  %-8s %-22s | %-46s %s" % (r["move"], str(r["company"])[:22],
                                           str(r["title"])[:46], r["reason"][:90]))
    dest = a.out or os.path.join(tempfile.gettempdir(), "scope_rule.json")
    if os.path.dirname(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)   # 96 paid calls once died here
    with io.open(dest, "w", encoding="utf-8") as f:
        json.dump({"contract": seniority.CONTRACT, "model": a.model, "tier": a.tier,
                   "tally": tally, "rows": out_rows}, f, ensure_ascii=False, indent=1)
    print("\nwrote %s" % dest)


if __name__ == "__main__":
    main()
