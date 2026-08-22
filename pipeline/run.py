#!/usr/bin/env python3
"""Daily pipeline orchestrator.

  fetch (companies.csv) → Israel filter → seniority/relevance classify
  → merge cross-platform dups → keep only NEW (unseen) → write digest files

By default this PRODUCES the digest to ./out/ and does NOT send anything and does NOT mark
postings as sent (safe to re-run). The real email send is done separately via the Gmail
MCP tools after the format is approved; `mark_sent.py` then records the postings as sent.

Usage:
  python -m pipeline.run                     # produce digest for today, all active companies
  python -m pipeline.run --no-llm            # deterministic only (skip claude -p fallback)
  python -m pipeline.run --limit 20          # only first 20 active companies (quick test)
  python -m pipeline.run --only Fiverr,Wix   # only named companies
  python -m pipeline.run --date 2026-08-14   # override run date label
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import traceback
from collections import Counter

from . import aggregators
from . import company_info as company_info_mod
from . import firmographics as firmographics_mod

FIRMO_MAX_PER_RUN = 5  # research calls can web-search (~1-3 min each); bulk = backfill script
from . import digest as digest_mod
from . import fetchers, israel, seniority, store
from .companies import load_companies

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "out")


def _load_secrets_env():
    """Load KEY=VALUE lines from a gitignored secrets.env into the environment (local runs).
    Lets the pipeline pick up JSEARCH_API_KEY etc. without exporting shell vars. In GitHub
    Actions the same names come from repo secrets instead, so this file is simply absent."""
    path = os.path.join(REPO_ROOT, "secrets.env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def run(*, use_llm=True, limit=None, only=None, run_date=None, out_dir=OUT_DIR, db_path=None):
    run_date = run_date or dt.date.today().isoformat()
    _load_secrets_env()
    os.makedirs(out_dir, exist_ok=True)
    st = store.SeenStore(db_path) if db_path else store.SeenStore()
    llm_cache = st.load_llm_cache()
    llm_cache_before = len(llm_cache)

    rows = load_companies()
    # never scan recruiting/staffing agencies — they re-post dozens of client roles and flood
    # the digest; they are not direct employers (same exclusion as SiiRA/Megayeset).
    from .recruiters import is_recruiter
    rows = [r for r in rows if not is_recruiter(r["company_name"])]
    # runtime last line of defense: a scrape row pointing at an aggregator ingests that
    # page's "similar jobs" sidebar — OTHER companies' roles attributed to this one.
    # Resolvers refuse to create such rows, but a hand-added row would otherwise sail through.
    import re as _re
    _AGG_HOST = _re.compile(r"//[^/]*(linkedin\.|indeed\.|glassdoor\.|secrethunter\.)", _re.I)
    _agg = [r for r in rows if r["ats_platform"] == "scrape" and _AGG_HOST.search(r["api_url"] or "")]
    for r in _agg:
        print(f"  SKIP {r['company_name']}: scrape row points at an aggregator "
              f"({r['api_url'][:60]}) — would ingest other companies' jobs", flush=True)
    rows = [r for r in rows if r not in _agg]
    if only:
        want = {o.strip().lower() for o in only}
        rows = [r for r in rows if r["company_name"].strip().lower() in want]
    if limit:
        rows = rows[:limit]

    stats = Counter()
    paths = Counter()
    failed_companies = []
    accepted = []
    health_results = {}                       # free detection: outcome per company this run

    for r in rows:
        stats["companies_scanned"] += 1
        try:
            jobs = fetchers.fetch_company(r)
        except Exception as e:  # noqa: BLE001
            stats["companies_failed"] += 1
            failed_companies.append(f"{r['company_name']} ({e.__class__.__name__})")
            health_results[r["company_name"]] = {"platform": r["ats_platform"], "n": 0,
                                                  "status": "error", "api": r.get("api_url", "")}
            print(f"  [fetch-fail] {r['company_name']}: {e}", file=sys.stderr)
            continue
        health_results[r["company_name"]] = {
            "platform": r["ats_platform"], "n": len(jobs),
            "status": "ok" if jobs else "empty", "api": r.get("api_url", "")}
        stats["jobs_fetched"] += len(jobs)
        for j in jobs:
            if not israel.is_israel_job(j):
                continue
            stats["israel_matched"] += 1
            c = seniority.classify(j, use_llm=use_llm, llm_cache=llm_cache)
            paths[c["path"]] += 1
            if c["path"] == "llm":
                stats["llm_calls"] += 1
            if c["decision"] == "accept":
                j["_class"] = c
                accepted.append(j)

    # Aggregator breadth layer: Google-for-Jobs via SerpApi (covers Israel). Gated behind
    # AGGREGATOR_ENABLED=1 (set only in the scheduled cloud job) so local/test runs never
    # burn the free 100/month SerpApi quota. Skipped cleanly if the key isn't set.
    gjobs = []
    if os.environ.get("AGGREGATOR_ENABLED") == "1":
        try:
            gjobs = aggregators.fetch_serpapi_google_jobs()
        except Exception as e:  # noqa: BLE001
            print(f"  [aggregator] skipped: {e}", file=sys.stderr)
            gjobs = []
    if gjobs:
        stats["google_jobs_fetched"] = len(gjobs)
        stats["jobs_fetched"] += len(gjobs)
        for j in gjobs:
            if not israel.is_israel_job(j):
                continue
            stats["israel_matched"] += 1
            c = seniority.classify(j, use_llm=use_llm, llm_cache=llm_cache)
            paths[c["path"]] += 1
            if c["path"] == "llm":
                stats["llm_calls"] += 1
            if c["decision"] == "accept":
                j["_class"] = c
                accepted.append(j)

    # free, daily detection: record which boards returned 0/error so the self-heal step can
    # re-resolve them (and discovery can backfill). Never let health tracking break the digest.
    try:
        from . import health
        stale = health.record(health_results)
        stats["stale_boards"] = len(stale)
    except Exception as e:  # noqa: BLE001
        print(f"  [health] skipped: {e}", file=sys.stderr)

    stats["accepted"] = len(accepted)
    merged = store.merge_duplicates(accepted)
    stats["after_merge"] = len(merged)

    # persist every matched role into the rolling store (first_seen kept on conflict), then
    # derive the two windows: email = last ~48h, board = last 2 weeks.
    for j in merged:
        st.upsert_matched(j, run_date)
    today = dt.date.fromisoformat(run_date)
    cutoff_email = (today - dt.timedelta(days=1)).isoformat()    # ~48h (date granularity)
    cutoff_board = (today - dt.timedelta(days=14)).isoformat()   # 2 weeks
    def _posted_in(j, cutoff):
        p = (j.get("posted_date") or "")[:10]
        if len(p) == 10 and p[4] == "-":
            return p >= cutoff
        # No real posted-date (common for scraped roles). Previously this returned True, so
        # undated roles bypassed the 48h window entirely and flooded the email. Fall back to
        # when WE first saw it — an undated role is only "recent" if we discovered it recently.
        fs = (j.get("first_seen") or "")[:10]
        return fs >= cutoff if (len(fs) == 10 and fs[4] == "-") else False

    # companies whose fetch failed THIS run keep yesterday's last_seen — don't mass-drop them
    failed_names = {f.split(" (")[0] for f in failed_companies}
    yesterday = (today - dt.timedelta(days=1)).isoformat()

    def _alive(j):
        return (j.get("last_seen", "") >= yesterday) or (j.get("company") in failed_names)

    def _cap_per_company(jobs, n):
        """Keep at most n roles per company (most-recent first) so one employer — or a batch
        of freshly-migrated companies — can't flood the digest. Order is otherwise preserved."""
        seen = Counter()
        out = []
        for j in sorted(jobs, key=lambda x: str(x.get("posted_date") or x.get("first_seen") or ""),
                        reverse=True):
            c = j.get("company", "")
            if seen[c] < n:
                seen[c] += 1
                out.append(j)
        return out

    email_jobs = [j for j in st.get_matched_since(cutoff_email)
                  if _posted_in(j, cutoff_email) and _alive(j)]
    email_jobs = st.filter_new(email_jobs)      # never email the same posting twice
    email_jobs = _cap_per_company(email_jobs, 3)   # tight daily digest: <=3 per company
    board_jobs = [j for j in st.get_matched_since(cutoff_board) if _alive(j)]
    board_jobs = _cap_per_company(board_jobs, 8)   # searchable 2-week board: generous cap
    stats["new"] = len(email_jobs)
    stats["board_count"] = len(board_jobs)

    # persist any freshly-computed LLM verdicts (safe even in produce/dry-run)
    if len(llm_cache) != llm_cache_before:
        st.save_llm_cache(llm_cache, run_date)

    # company summaries ("what it does + how it earns money") for the interactive digest.
    # Precedence: researched static profiles (company_profiles.json, committed) > claude
    # cache (sqlite) > freshly generated claude summary (fallback so nothing is blank).
    profiles = {}
    ppath = os.path.join(REPO_ROOT, "company_profiles.json")
    if os.path.exists(ppath):
        try:
            with open(ppath, encoding="utf-8") as f:
                profiles = json.load(f)
        except (ValueError, OSError):
            profiles = {}
    company_info = {**st.load_company_info(), **{k: v for k, v in profiles.items() if v}}
    if use_llm:
        for company in {j["company"] for j in board_jobs}:
            if not company_info.get(company):
                ctx = next((j.get("description") for j in board_jobs
                            if j["company"] == company and j.get("description")), "")
                summ = company_info_mod.summarize_company(company, ctx)
                company_info[company] = summ
                st.save_company_info({company: summ}, run_date)
                stats["company_summaries"] += 1

    # Structured firmographics for companies the store hasn't researched yet. Same lazy
    # cached pattern as the blurbs above, but each call may web-search (~1-3 min), so cap
    # per run and let research_firmographics.py do bulk backfill.
    if use_llm:
        firmo = st.load_firmographics()
        missing = sorted(c for c in {j["company"] for j in board_jobs} if c not in firmo)
        for company in missing[:FIRMO_MAX_PER_RUN]:
            ctx = next((j.get("description") for j in board_jobs
                        if j["company"] == company and j.get("description")), "")
            rec = firmographics_mod.research_company(company, ctx)
            if rec:
                st.save_firmographics({company: rec}, run_date)
                stats["firmographics_researched"] += 1

    summary = {
        "companies_scanned": stats["companies_scanned"],
        "companies_failed": stats["companies_failed"],
        "jobs_fetched": stats["jobs_fetched"],
        "israel_matched": stats["israel_matched"],
        "accepted": stats["accepted"],
        "after_merge": stats["after_merge"],
        "new": stats["new"],
        "board_count": stats["board_count"],
        "llm_calls": stats["llm_calls"],
        "paths": dict(paths),
        "failed_companies": failed_companies,
    }

    # email = last ~48h (concise daily); board = last 2 weeks (searchable/sortable)
    subject, html, text = digest_mod.build_digest(email_jobs, run_date, summary)
    md_title, md_body = digest_mod.build_markdown(email_jobs, run_date, summary, company_info,
                                                  board_url=os.environ.get("BOARD_URL", ""))
    # optional aggregate analytics: set GOATCOUNTER_CODE to your goatcounter subdomain
    gc = os.environ.get("GOATCOUNTER_CODE", "").strip()
    analytics_html = (f'<script data-goatcounter="https://{gc}.goatcounter.com/count" '
                      f'async src="//gc.zgo.at/count.js"></script>') if gc else \
        os.environ.get("ANALYTICS_SNIPPET", "")
    contact_url = os.environ.get("CONTACT_URL",
                                 "https://github.com/AnalystJobsIL/board/issues/new")
    board_html = digest_mod.build_board_html(board_jobs, run_date, summary, company_info,
                                             analytics_html=analytics_html, contact_url=contact_url)

    base = os.path.join(out_dir, f"digest-{run_date}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(text)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(md_body)
    # interactive board for GitHub Pages (served from /docs)
    docs_dir = os.path.join(REPO_ROOT, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(board_html)
    # archive: everything ever matched that is NOT on the current board
    onboard = {(j["company"], j["title"]) for j in board_jobs}
    arch = [j for j in st.get_matched_since("0000-01-01")
            if (j["company"], j["title"]) not in onboard]
    arch_html = digest_mod.build_board_html(arch, run_date, summary, company_info=company_info,
                                        heading="archived roles (expired or filled)")
    with open(os.path.join(docs_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(arch_html)
    # machine-readable payload for the send + mark-sent steps
    payload = {
        "run_date": run_date,
        "subject": subject,
        "summary": summary,
        "jobs": [
            {k: j.get(k) for k in ("company", "title", "location", "url", "posted_date",
                                   "sources", "seen_ids", "first_seen")}
            for j in email_jobs
        ],
    }
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    st.close()

    print(f"\n=== digest {run_date} ===")
    print(f"email (last 48h): {summary['new']} roles · board (last 2wk): {summary['board_count']} roles"
          f"  (scanned {summary['companies_scanned']} cos, {summary['companies_failed']} failed, "
          f"{summary['llm_calls']} LLM calls)")
    print(f"wrote: {base}.html / .txt / .json + docs/index.html")
    return payload, base


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-llm", action="store_true", help="deterministic only; skip claude -p")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--date", help="run-date label (YYYY-MM-DD); default today")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--db", help="override seen-store path")
    a = ap.parse_args()
    run(use_llm=not a.no_llm, limit=a.limit,
        only=a.only.split(",") if a.only else None,
        run_date=a.date, out_dir=a.out, db_path=a.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
