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

THE SAMPLE has two sources. `--source cache` (the default) is every posting in the committed
caches that (a) is in Israel, (b) the title gate sends onward or fast-accepts, and (c) carries
a real description — because a rule about a role's OUTPUT can only be measured where the
output is described. `--source ledger` judges rows of the PUBLISHED dataset named by `--only`
(role_ids), which is the only way to reach a CLOSED role: its text lives in
`roles_text.jsonl`, not in either cache. That source applies no filters at all, so it demands
`--only` or `--limit`. `--tier` picks which of the cache source's own tiers to sample:

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


def prior_dates(db_path):
    """`{job: {prefix: updated}}` -- when each cached verdict was judged."""
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    out = {}
    for key, updated in con.execute("select title_key, updated from llm_cache"):
        split = seniority._versioned(key)
        if split:
            suffix, prefix = split
            out.setdefault(suffix.rsplit("|", 1)[0], {})[prefix] = updated or ""
    con.close()
    return out


def prior_for(job_key, by_job, legacy, contract, dates=None):
    """(verdict, which) under production's own precedence, or (None, '').

    `dates` is `{job: {prefix: updated}}`; with it the newest SUPERSEDED verdict wins, which
    is what `Classifier._lookup` does. Without it the prefix breaks the tie, and the prefix is
    a hash: sorting it is alphabetical, not chronological (docs/BACKLOG.md 541)."""
    seen = by_job.get(job_key) or {}
    if contract in seen:
        return seen[contract], "current"
    older = {p: v for p, v in seen.items() if p != contract}
    if older:
        when = (dates or {}).get(job_key) or {}
        return older[max(older, key=lambda p: (when.get(p, ""), p))], "superseded"
    if job_key in legacy:
        return legacy[job_key], "legacy"
    return None, ""


def sample_ledger(root, only):
    """The same shape as `sample()`, sourced from the ROLE LEDGER instead of the caches.

    A closed role is not in either cache -- its text lives in `roles_text.jsonl` -- so the
    cache sample cannot reach the published dataset at all: of the rows the 2026-09-01 audit
    named, 0 of Guardio's, Mobileye's, NVIDIA's or Global-e's postings carry >= MIN_TEXT
    there. `--only` takes role_ids (comma-separated), which is how a boundary is measured on
    the rows it was drawn for rather than on 96 postings it does not bear on."""
    recs = {}
    with io.open(os.path.join(root, "cloud_state", "roles.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                recs[r.get("role_id")] = r
    text = {}
    with io.open(os.path.join(root, "cloud_state", "roles_text.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                text[d.get("role_id")] = str(d.get("description") or "")
    wanted = [x.strip() for x in only.split(",") if x.strip()] if only else sorted(recs)
    rows, missing = [], []
    for rid in wanted:
        rec = recs.get(rid)
        if rec is None:
            missing.append(rid)
            continue
        desc = text.get(rid) or ""
        job = {"company": rec.get("company"), "title": rec.get("title"),
               "location": rec.get("location"), "url": rec.get("url"), "description": desc}
        title_l = (job["title"] or "").lower()
        rel = seniority._relevance(title_l, (job["company"] or "").lower())
        sen = seniority._seniority(title_l)
        tier = "keyword" if (rel == "strong" and sen == "senior") else "llm"
        key = (seniority._norm_company(job["company"]), seniority._norm(job["title"]))
        rows.append((key, job, rel, sen, tier))
    if missing:
        print("NOT IN THE LEDGER (%d): %s" % (len(missing), ", ".join(missing)))
    return rows


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
    ap.add_argument("--source", choices=("cache", "ledger"), default="cache",
                    help="cache = the two committed caches (open postings); "
                         "ledger = cloud_state/roles.jsonl + roles_text.jsonl (the PUBLISHED "
                         "dataset, closed rows included)")
    ap.add_argument("--only", default="", help="comma-separated role_ids (--source ledger)")
    a = ap.parse_args()

    if a.source == "ledger":
        # The cache sample filters to >= MIN_TEXT before it ever reaches the seam; this one
        # does not filter at all, so an unscoped `--source ledger` would buy one call for
        # every record in the ledger (203 today), silently, against a subscription four
        # consumers share. The caller must say which rows.
        if not (a.only or a.limit):
            ap.error("--source ledger needs --only or --limit: it applies no text filter, "
                     "so unscoped it would judge every ledger record")
        if a.tier != "both":
            ap.error("--tier applies to --source cache (the ledger source judges the rows "
                     "you name, whatever tier they are)")
        rows = sample_ledger(a.root, a.only)
    else:
        if a.only:
            ap.error("--only applies to --source ledger")
        rows = sample(a.root, a.tier)
    if a.limit:
        rows = rows[:a.limit]
    by_job, legacy = prior_verdicts(os.path.join(a.root, "cloud_state", "seen.db"))
    dates = prior_dates(os.path.join(a.root, "cloud_state", "seen.db"))
    print("contract now: %s   model: %s" % (seniority.CONTRACT, a.model))
    if a.source == "ledger":
        # no MIN_TEXT filter here on purpose: the caller names the rows, and a published row
        # with thin text is exactly the kind a boundary has to be measured on. Saying ">= 300
        # chars" for this source would be a false header.
        thin = sum(1 for _k, j, _r, _s, _t in rows
                   if len(str(j.get("description") or "")) < MIN_TEXT)
        print("sample: %d ledger rows named by --only%s"
              % (len(rows), (", %d under %d chars" % (thin, MIN_TEXT)) if thin else ""))
    else:
        print("sample: %d postings with >= %d chars of text (tier %s)"
              % (len(rows), MIN_TEXT, a.tier))
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
        was, which = prior_for(job_key, by_job, legacy, seniority.CONTRACT, dates)
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
