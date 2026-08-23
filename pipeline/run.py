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
BLURB_MAX_PER_RUN = 30  # one claude call each, inside the digest timeout
EMAIL_MAX_ROLES = 40   # a daily email nobody scrolls is a daily email nobody reads
FIRST_SCAN_MAX_ROLES = 15  # roles at employers this digest is seeing for the first time
BOARD_MAX_ROLES = 1500  # page-weight backstop; each role renders a full detail card
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

    # Ordering contract (pipeline/stages.py): this run's input quality depends on stages
    # that ran EARLIER, in other workflows. If one of them did not run, the digest is
    # built on stale URLs / a stale cache — that must be visible in the audit, not silent.
    from . import stages
    stages.require("repair", 1)
    stages.require("collect", 1)
    stages.require("enrich", 1)
    # a discovery source that has quietly stopped returning records is invisible otherwise
    from . import sources as _sources_mod
    _dead_sources = _sources_mod.stale()
    for _line in _dead_sources:
        print(f"::warning::discovery source {_line}", flush=True)

    rows = load_companies()
    # never scan recruiting/staffing agencies — they re-post dozens of client roles and flood
    # the digest; they are not direct employers (same exclusion as SiiRA/Megayeset).
    from .recruiters import is_recruiter
    rows = [r for r in rows if not is_recruiter(r["company_name"])]
    # runtime last line of defense: a scrape row pointing at an aggregator ingests that
    # page's "similar jobs" sidebar — OTHER companies' roles attributed to this one.
    # Resolvers refuse to create such rows, but a hand-added row would otherwise sail through.
    from .aggregators import is_aggregator
    _agg = [r for r in rows if r["ats_platform"] == "scrape" and is_aggregator(r["api_url"] or "")]
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
    from .jdfill import JDFiller
    jdfill = JDFiller()
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
            # the JD is what the LLM tier reads; workday/smartrecruiters/bamboohr/microsoft
            # list responses carry none, so fetch it before judging (budgeted, title-gated)
            if jdfill.maybe_fill(j):
                stats["jd_filled_inline"] += 1
            c = seniority.classify(j, use_llm=use_llm, llm_cache=llm_cache)
            paths[c["path"]] += 1
            if c["path"] == "llm":
                stats["llm_calls"] += 1
            if c["decision"] == "accept":
                j["_class"] = c
                accepted.append(j)

    print("  " + jdfill.summary(), flush=True)

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
        if only or limit:
            # A scoped run saw 5 companies, not 894. Recording it REPLACES stale.json with
            # those five outcomes and the self-heal job then has nothing to re-resolve —
            # same footgun as a scoped run overwriting the published board, which is
            # already guarded below.
            print(f"  [health] scoped run ({len(rows)} companies): not touching stale.json")
        else:
            stale = health.record(health_results)
            stats["stale_boards"] = len(stale)
    except Exception as e:  # noqa: BLE001
        print(f"  [health] skipped: {e}", file=sys.stderr)

    stats["accepted"] = len(accepted)
    merged = store.merge_duplicates(accepted)
    stats["after_merge"] = len(merged)

    # WHICH COMPANIES DID WE ALREADY KNOW, before this run wrote anything? An undated role
    # at a company we are scanning for the FIRST time is a backfill, not news — see
    # `_posted_in`. This must be read before the upserts below, or every company looks old.
    seen_before = {c for (c,) in st.conn.execute(
        "SELECT DISTINCT company FROM matched WHERE first_seen < ?", (run_date,))}

    # persist every matched role into the rolling store (first_seen kept on conflict), then
    # derive the two windows: email = roles posted in the last ~48h, board = still open.
    for j in merged:
        st.upsert_matched(j, run_date)
    today = dt.date.fromisoformat(run_date)
    cutoff_email = (today - dt.timedelta(days=1)).isoformat()    # ~48h (date granularity)
    def _posted_in(j, cutoff):
        p = (j.get("posted_date") or "")[:10]
        if len(p) == 10 and p[4] == "-":
            return p >= cutoff
        # No real posted-date (common for scraped roles). Previously this returned True, so
        # undated roles bypassed the 48h window entirely and flooded the email. Fall back to
        # when WE first saw it — an undated role is only "recent" if we discovered it recently.
        # EXCEPT on a company's first scan: 336 companies were activated overnight, and
        # "we discovered it today" says nothing about when the role was POSTED. Their whole
        # back catalogue would read as 48h-fresh and bury the actual news. They are on the
        # board from today; they become email-eligible once we have a day of history for
        # that employer and can tell a new posting from its back catalogue.
        if j.get("company") not in seen_before:
            return False
        fs = (j.get("first_seen") or "")[:10]
        return fs >= cutoff if (len(fs) == 10 and fs[4] == "-") else False

    # companies whose fetch failed THIS run keep yesterday's last_seen — don't mass-drop them
    failed_names = {f.split(" (")[0] for f in failed_companies}
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    # ...but only while the failure is FRESH. Without this, a board that breaks permanently
    # freezes its roles on the job board forever, and they are the ones a reader applies to.
    fail_grace = (today - dt.timedelta(days=7)).isoformat()

    def _alive(j):
        """Is this role still open? = we saw it in the latest scan of its company."""
        last = j.get("last_seen", "")
        if last >= yesterday:
            return True
        return j.get("company") in failed_names and last >= fail_grace

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
    # Hard ceiling on the email. Uncapped, one good day of coverage growth produces a
    # thousand-role wall of text that nobody reads — and mark_sent would then burn every
    # one of them as "delivered". Overflow is not lost: it stays unsent and leads tomorrow.
    stats["email_overflow"] = max(0, len(email_jobs) - EMAIL_MAX_ROLES)
    if stats["email_overflow"]:
        print(f"  email capped at {EMAIL_MAX_ROLES} roles; {stats['email_overflow']} more "
              f"stay unsent and lead tomorrow's digest", flush=True)
        email_jobs = email_jobs[:EMAIL_MAX_ROLES]

    # A company's FIRST scan: `_posted_in` rightly refuses to call its back catalogue
    # "posted in the last 48h" — we have no idea when those roles were posted. But they ARE
    # news to the reader, who has never seen this employer before. They go in the email
    # under their own heading, honestly labelled, rather than being silently withheld for a
    # day. Tightly capped: 336 companies were activated overnight.
    # ...minus anything the 48h list already carries. A first-scan company's role CAN have
    # a real posted_date inside the window — `_posted_in` returns on the ISO branch before
    # it ever reaches the first-scan gate — and it would then be listed in both sections.
    already = {(j.get("company"), j.get("title")) for j in email_jobs}
    first_scan = [j for j in st.get_matched_since(run_date)
                  if j.get("company") not in seen_before and _alive(j)
                  and (j.get("company"), j.get("title")) not in already]
    first_scan = st.filter_new(first_scan)
    first_scan = _cap_per_company(first_scan, 2)[:FIRST_SCAN_MAX_ROLES]
    for j in first_scan:
        j["_new_company"] = True
    stats["first_scan"] = len(first_scan)
    email_jobs = email_jobs + first_scan
    # The board holds ACTIVE roles — every role still present on its employer's careers
    # page — not "roles first seen in the last two weeks". A role open for three weeks is
    # still open, and dropping it off the board (into a page headed "expired or filled")
    # while it is live was both a coverage hole and a lie about its status. Liveness comes
    # from `_alive`, i.e. from actually re-fetching it, so nothing lingers once it is gone.
    # No per-company cap here: the board IS the set of active roles, and hiding a live
    # opening because its employer has nine of them would make the board wrong. Flooding is
    # an EMAIL problem (capped at 3/company above); the board is sortable and searchable.
    board_jobs = [j for j in st.get_matched_since("0000-01-01") if _alive(j)]
    if len(board_jobs) > BOARD_MAX_ROLES:
        # Pure page-weight backstop, not a policy: every role renders a full detail card,
        # so an unbounded board is a multi-megabyte page nobody can load on a phone.
        board_jobs.sort(key=lambda x: str(x.get("posted_date") or x.get("first_seen") or ""),
                        reverse=True)
        print(f"  board: {len(board_jobs)} active roles, rendering the newest "
              f"{BOARD_MAX_ROLES}", flush=True)
        board_jobs = board_jobs[:BOARD_MAX_ROLES]
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
        # Budgeted like the firmographics below: the board is no longer a 14-day window, so
        # the "companies with no blurb yet" set can be large on the first run after a
        # coverage jump — and each blurb is a claude call inside the digest's own timeout.
        todo = sorted(c for c in {j["company"] for j in board_jobs} if not company_info.get(c))
        if len(todo) > BLURB_MAX_PER_RUN:
            print(f"  company blurbs: {len(todo)} missing, doing {BLURB_MAX_PER_RUN} this "
                  f"run (cached; the rest follow on later runs)", flush=True)
        for company in todo[:BLURB_MAX_PER_RUN]:
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
        import datetime as _dt
        firmo = st.load_firmographics()
        # failure memory: permanently failing names (junk/ambiguous) retry at most weekly,
        # so they can't capture the fixed per-run budget and starve real new companies
        failures = st.load_firmo_failures()
        week_ago = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
        # identity is normalized (§7): "SolarEdge Technologies" on the board must find the
        # stored "SolarEdge" profile, and a failure strike on one variant gates the other
        _idk = firmographics_mod.identity_key
        firmo_norms = {_idk(c) for c in firmo}
        failed_norms = {_idk(c) for c, (att, last) in failures.items() if last > week_ago}
        candidates = sorted(c for c in {j["company"] for j in board_jobs}
                            if c not in firmo
                            and _idk(c) not in firmo_norms
                            and not firmographics_mod.looks_like_junk(c)
                            and _idk(c) not in failed_norms)
        # intra-batch dedupe: "X" and "X Israel" surfacing in one digest are one company —
        # they must not spend two of the five budget slots and mint a duplicate group
        missing, _batch = [], set()
        for c in candidates:
            if _idk(c) not in _batch:
                _batch.add(_idk(c))
                missing.append(c)
        for company in missing[:FIRMO_MAX_PER_RUN]:
            ctx = next((j.get("description") for j in board_jobs
                        if j["company"] == company and j.get("description")), "")
            try:
                rec = firmographics_mod.research_company(company, ctx)
            except firmographics_mod.ResearchUnavailable:
                break  # infrastructure outage: don't blame names, don't burn the budget
            if rec:
                st.save_firmographics({company: rec}, run_date)
                stats["firmographics_researched"] += 1
            else:
                st.record_firmo_failure(company, run_date)

    # sqlite ∪ the committed JSON export. The two stores (local `state/seen.db`, cloud
    # `cloud_state/seen.db`) cannot be git-merged, which is how 919 researched profiles
    # ended up on one laptop while the cloud digest that RENDERS them had an empty table.
    # The export is the artifact both sides read; the fresher `as_of` wins per company.
    _shared = firmographics_mod.load_shared()
    _firmo_store = dict(_shared)
    for _c, _rec in st.load_firmographics().items():
        _firmo_store[_c] = firmographics_mod.newer(_shared.get(_c), _rec)
    # Look the record up under the NORMALIZED identity, so "SolarEdge Technologies" on the
    # board finds the stored "SolarEdge" (ARCHITECTURE §7), and cover every company we have
    # ever matched — the archive renders the same card and showed facts for 5 of 50.
    _by_key = {firmographics_mod.identity_key(k): v for k, v in _firmo_store.items()}
    _all_companies = {j["company"] for j in st.get_matched_since("0000-01-01")}
    firmo_display = {c: (_firmo_store.get(c) or _by_key.get(firmographics_mod.identity_key(c)))
                     for c in _all_companies}
    firmo_display = {k: v for k, v in firmo_display.items() if v}

    # write the union back out so this run's own research reaches the other store too
    try:
        firmographics_mod.save_shared(_firmo_store)
    except Exception as e:  # noqa: BLE001
        print(f"  [firmographics] shared export skipped: {e}", file=sys.stderr)

    # Stamp BEFORE the summary is built, or the audit block this run prints says
    # "publish: never run" about the very run printing it — the stamp was written after
    # `stages.summary()` had already been captured.
    if not (only or limit):
        stages.stamp("publish", email=stats["new"], board=stats["board_count"],
                     scanned=stats["companies_scanned"])

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
        "jd_filled_inline": stats["jd_filled_inline"],
        "email_overflow": stats["email_overflow"],
        "first_scan": stats["first_scan"],
        "stages": stages.summary(),
        "dead_sources": _dead_sources,
        "paths": dict(paths),
        "failed_companies": failed_companies,
    }

    # email = last ~48h (concise daily); board = last 2 weeks (searchable/sortable)
    subject, html, text = digest_mod.build_digest(email_jobs, run_date, summary)
    md_title, md_body = digest_mod.build_markdown(email_jobs, run_date, summary, company_info,
                                                  board_url=os.environ.get("BOARD_URL", ""),
                                                  firmographics=firmo_display)
    # optional aggregate analytics: set GOATCOUNTER_CODE to your goatcounter subdomain
    gc = os.environ.get("GOATCOUNTER_CODE", "").strip()
    analytics_html = (f'<script data-goatcounter="https://{gc}.goatcounter.com/count" '
                      f'async src="//gc.zgo.at/count.js"></script>') if gc else \
        os.environ.get("ANALYTICS_SNIPPET", "")
    contact_url = os.environ.get("CONTACT_URL",
                                 "https://github.com/AnalystJobsIL/board/issues/new")
    # researched company facts (sector / stage / employees / founded / IL centre). They were
    # being collected for every board company and rendered nowhere. Look them up under the
    # normalized identity so "SolarEdge Technologies" on the board finds stored "SolarEdge".
    board_html = digest_mod.build_board_html(board_jobs, run_date, summary, company_info,
                                             analytics_html=analytics_html,
                                             contact_url=contact_url,
                                             firmographics=firmo_display)

    base = os.path.join(out_dir, f"digest-{run_date}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(text)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(md_body)
    # interactive board for GitHub Pages (served from /docs)
    # a scoped run (--only / --limit) must NOT overwrite the published board with a
    # partial one; local experiments were clobbering docs/index.html
    if only or limit:
        docs_dir = os.path.join(out_dir, "docs-preview")
    else:
        docs_dir = os.path.join(REPO_ROOT, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(board_html)
    # archive: everything ever matched that is NOT on the current board
    onboard = {(j["company"], j["title"]) for j in board_jobs}   # = still open
    arch = [j for j in st.get_matched_since("0000-01-01")
            if (j["company"], j["title"]) not in onboard]
    # The store keeps every role forever — which is the point, it IS the archive — but the
    # PAGE renders a full detail card per role, so it would grow without bound. Newest
    # first; the database keeps the tail whether or not the page shows it.
    arch.sort(key=lambda x: str(x.get("last_seen") or x.get("first_seen") or ""), reverse=True)
    if len(arch) > BOARD_MAX_ROLES:
        print(f"  archive: {len(arch)} closed roles in the store, rendering the newest "
              f"{BOARD_MAX_ROLES}", flush=True)
        arch = arch[:BOARD_MAX_ROLES]
    arch_html = digest_mod.build_board_html(arch, run_date, summary, company_info=company_info,
                                        heading="archived roles (no longer on the "
                                                "employer's careers page)",
                                        firmographics=firmo_display)
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
    print(f"email (last 48h): {summary['new']} roles · board (active): {summary['board_count']} roles"
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
