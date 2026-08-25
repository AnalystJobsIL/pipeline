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
import re as _re
import sys
import traceback
from collections import Counter

from . import aggregators
from . import company_intel

EMAIL_MAX_ROLES = 40   # a daily email nobody scrolls is a daily email nobody reads
FIRST_SCAN_MAX_ROLES = 15  # roles at employers this digest is seeing for the first time
BOARD_MAX_ROLES = 1500  # page-weight backstop; each role renders a full detail card
from . import digest as digest_mod
from . import fetchers, israel, seniority, store
from .companies import load_companies

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "out")
LAST_RUN_PATH = os.path.join(REPO_ROOT, "cloud_state", "last_run.json")

# ---- the run's own legibility (lane: infra) ------------------------------------------
# The Actions log of a digest is ~900 lines with no structure; a crash was a bare traceback
# and, because `digests/latest.md` was left as yesterday's, no email at all (the relay dedups
# by content hash). `_phase` groups the log under Actions and records where the run is, so
# `main()` can write out/crash.json for the failure notice (`persist_state.py outcome`).
_PHASE = {"name": "start"}


def _phase(name):
    """Mark a milestone: a collapsible `::group::` in the Actions log, the phase name for
    the crash file. Plain print elsewhere, so local runs and tests read unchanged."""
    if os.environ.get("GITHUB_ACTIONS"):
        if _PHASE["name"] != "start":
            print("::endgroup::", flush=True)
        print(f"::group::{name}", flush=True)
    _PHASE["name"] = name


def _workflow_step_alarms(env=None):
    """`daily-digest.yml`'s pre-steps are continue-on-error; a failed one used to be a red
    line in a log nobody opens. The workflow passes `toJSON(steps)` as
    WORKFLOW_STEP_OUTCOMES; every failed/cancelled step becomes one bold line in the mail."""
    env = os.environ if env is None else env
    raw = env.get("WORKFLOW_STEP_OUTCOMES")
    if not raw:
        return []
    try:
        steps = json.loads(raw)
    except ValueError:
        return ["workflow step outcomes unreadable (WORKFLOW_STEP_OUTCOMES is not JSON)"]
    if not isinstance(steps, dict):
        return []
    return [f"workflow step '{k}' {v.get('outcome')} before the pipeline ran — its output is "
            f"missing from this digest; see the run log"
            for k, v in steps.items()
            if isinstance(v, dict) and v.get("outcome") in ("failure", "cancelled")]


def _last_run_alarms(run_date, path=None):
    """`persist_state.py outcome` records a failed run in cloud_state/last_run.json (a step
    after the pipeline -- mark_sent, the gate, persist, the board publish -- cannot reach
    the mail it failed to deliver). The next digest says so; older than two days is silent."""
    path = path or LAST_RUN_PATH
    try:                                  # a reporter never raises: a malformed state file is silence
        with open(path, encoding="utf-8") as f:
            last = json.load(f)
        if not isinstance(last, dict):
            return []
        failed = last.get("failed_steps")
        failed = failed if isinstance(failed, dict) else {}
        status = str(last.get("status", ""))
        if status == "success" and not failed:
            return []
        age = (dt.date.fromisoformat(run_date) - dt.date.fromisoformat(str(last.get("date")))).days
        if not 0 <= age <= 1:             # yesterday's or today's; the file is only rewritten on failure
            return []
        when = "an earlier run today" if age == 0 else f"the {last.get('date')} run"
        what = ", ".join(f"{k} ({v})" for k, v in failed.items()) or status
        verdict = f"{status}: {what}" if status != "success" else f"completed with a failed step: {what}"
        url = str(last.get("run_url") or "")
        return [f"{when} {verdict}" + (f" — {url}" if url.startswith("https://") else "")]
    except Exception:  # noqa: BLE001
        return []


def _write_step_summary(summary, run_date, docs_dir):
    """The mail's alarm lines and audit counts, on the run page ($GITHUB_STEP_SUMMARY)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    g = lambda k: summary.get(k, "?")  # noqa: E731 -- a reporter never raises
    lines = [f"## Digest {run_date}: email {g('new')} · board {g('board_count')} · "
             f"scanned {g('companies_scanned')} ({g('companies_failed')} failed) · "
             f"LLM calls {g('llm_calls')}", ""]
    for key, label in (("stage_alarms", "Stages"), ("registry_alarms", "Registry"),
                       ("dead_sources", "Sources not producing"), ("render", "Render"),
                       ("fetch_health", "Boards"), ("company_intel", "Company intel"), ("roles", "Roles")):
        for x in summary.get(key) or []:
            lines.append(f"- **{label}:** {x}")
    lines += ["", "```", *str(summary.get("stages", "")).split(" | "), "```",
              f"paths: {summary.get('paths')} · board written to `{docs_dir}`", ""]
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lines))
    except Exception as e:  # noqa: BLE001 -- runs after the digest is written; must not cost it
        print(f"  [summary] not written: {e}", flush=True)


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
    # the role record (lane: roles, ARCHITECTURE §7c): sqlite ∪ the text ledger beside it,
    # before anything reads `matched`; its alarms join the bold `Stages:` line below
    from . import roles
    ledger = roles.Ledger(st, run_date)
    ledger.open_sync()

    # Ordering contract (pipeline/stages.py): this run's input quality depends on stages
    # that ran EARLIER, in other workflows. If one of them did not run, the digest is
    # built on stale URLs / a stale cache — that must be visible in the audit, not silent.
    _phase("prerequisites")
    from . import stages
    stages.require("repair", 1)
    stages.require("collect", 1)
    stages.require("enrich", 1)
    # every stage's own verdict on itself — a crashed refresh, a mass-failure night, a hunt
    # that never stamped, yesterday's digest that never reached its stamp (BACKLOG 114) —
    # a bold line above the fold and a workflow warning, not a token in a collapsed block.
    # Then the workflow's: a pre-step that failed, and a step after yesterday's pipeline
    # that failed (mark_sent / gate / persist / publish reach the mail only the next day).
    _stage_alarms = (stages.alarms("collect") + stages.alarms("repair", 1)
                     + stages.alarms("expand", 1)
                     # `publish` is this run's own stage: a stamp older than yesterday means
                     # yesterday's digest never reached its stamp (a crash or a timeout)
                     + [a.replace("— the digest read stale input", "— yesterday's digest never completed")
                        for a in stages.alarms("publish", 1)]
                     + _workflow_step_alarms() + _last_run_alarms(run_date) + ledger.alarms)
    for _line in _stage_alarms:
        print(f"::warning::stage {_line}", flush=True)
    # a discovery source that has quietly stopped returning records is invisible otherwise
    from . import sources as _sources_mod
    _dead_sources = _sources_mod.stale()
    for _line in _dead_sources:
        print(f"::warning::discovery source {_line}", flush=True)
    # Registry health reaches a reader (docs/BACKLOG.md 12/13/34). alarms_state, NOT
    # alarms(): the latter probes the resolution ladder and this job installs no Playwright.
    # Registry facts only, no env, no network, ~0.25s; judged against YESTERDAY's census
    # (the census re-baselines after the invariant gate, later in the workflow).
    try:
        from registry_health import alarms_state as _registry_alarms
        _registry_alarms_lines = _registry_alarms()
    except Exception as e:              # noqa: BLE001 -- never block the product, but SAY so
        print(f"  [registry] health check skipped: {e!r}", file=sys.stderr, flush=True)
        _registry_alarms_lines = [f"registry health check crashed: {e.__class__.__name__}: {str(e)[:80]}"]
    for _line in _registry_alarms_lines:
        print(f"::warning::registry {_line}", flush=True)

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
    # ONE classifier per run (lane: classifier, ARCHITECTURE §7b): the LLM tier's cap, time
    # budget, circuit breaker and verdict staging live on it; the mail line comes from it
    clf = seniority.Classifier(use_llm=use_llm, llm_cache=llm_cache)
    failed_companies = []
    failed_names = set()                      # by NAME: 15 registry names contain " (" themselves
    candidates = []                           # Israel-matched postings, judged once per ROLE below
    health_results = {}                       # free detection: outcome per company this run

    _phase(f"fetch {len(rows)} boards")
    for r in rows:
        stats["companies_scanned"] += 1
        try:
            jobs = fetchers.fetch_company(r)
        except Exception as e:  # noqa: BLE001
            stats["companies_failed"] += 1
            # the mail used to say "(HttpError)" — the class alone, so nobody could tell a
            # 404 (dead board) from a 500 (their outage) without opening the run log
            # ...and the URL's query string goes first: it lands in the public digest, and
            # a Comeet `?token=` sat 5 characters past the cut on the two comeet.co rows
            _msg = _re.sub(r'\?\S*', '', str(e))[:70]
            why = f"{e.__class__.__name__}: {_msg}"
            failed_companies.append(f"{r['company_name']} ({why})")
            failed_names.add(r["company_name"])
            health_results[r["company_name"]] = {"platform": r["ats_platform"], "n": 0,
                                                  "status": "error", "api": r.get("api_url", ""),
                                                  "error": why}
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
            candidates.append(j)

    # one judgment per ROLE, not per board it is listed on (lane: roles, BACKLOG 124): a
    # role fetched from two rows is judged once, on its longest description; copies count
    # as `merged-copy` so `sum(paths) == israel_matched` still reconciles below
    _phase(f"classify {len(candidates)} Israel-matched postings")
    accepted = roles.classify_grouped(candidates, clf, jdfill, stats, paths)
    print("  " + jdfill.summary(), flush=True)
    # the enrich stage's verdict on itself (both backfill scripts stamp it) and the inline fill's
    for _line in stages.alarms("enrich") + jdfill.alarms():
        _stage_alarms.append(_line); print(f"::warning::stage {_line}", flush=True)

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
        gcands = [j for j in gjobs if israel.is_israel_job(j)]
        stats["israel_matched"] += len(gcands)
        accepted += roles.classify_grouped(gcands, clf, jdfill, stats, paths)

    # persist this run's LLM verdicts NOW (not after rendering): an exception anywhere in the
    # rendering / company-intel code below must not lose what was paid for (a runner timeout
    # still loses it — the commit lives in the Persist step). `commit` withholds a quarantined
    # cohort (alarmed below); `save` writes only new/changed rows so `updated` is real.
    stats["llm_calls"] = clf.attempts
    if clf.commit():
        st.save_llm_cache(llm_cache, run_date)
    print("  " + clf.summary(), flush=True)
    # the classifier's verdict on itself: breaker open, budget spent, a mass-NO/YES morning
    for _line in clf.alarms():
        _stage_alarms.append(_line); print(f"::warning::stage {_line}", flush=True)
    if sum(paths.values()) != stats["israel_matched"]:
        _line = (f"classify paths {sum(paths.values())} != israel-matched "
                 f"{stats['israel_matched']} — the audit block does not reconcile")
        _stage_alarms.append(_line); print(f"::warning::stage {_line}", flush=True)

    # free, daily detection: record which boards returned 0/error so the self-heal step can
    # re-resolve them (and discovery can backfill). Never let health tracking break the digest.
    _phase("board health")
    _fetch_health_lines = []
    try:
        from . import health
        if only or limit:
            # A scoped run saw 5 companies, not 894. Recording it REPLACES stale.json with
            # those five outcomes and the self-heal job then has nothing to re-resolve —
            # same footgun as a scoped run overwriting the published board, which is
            # already guarded below. Judge without writing, so the audit line still works.
            print(f"  [health] scoped run ({len(rows)} companies): not touching stale.json")
        _previous = health.previous()               # before record() rewrites the file
        stale = health.record(health_results, write=not (only or limit))
        # ...and reach the reader: stale.json is read by the self-heal job, not by a person
        _fetch_health_lines = health.mail_lines(stale, _previous, scanned=health_results)
        for _line in _fetch_health_lines:
            print(f"::warning::boards {_line}", flush=True)
    except Exception as e:  # noqa: BLE001
        # every `Boards` line AND stale.json (the self-heal's queue) just vanished: say so
        print(f"  [health] skipped: {e}", file=sys.stderr)
        _line = f"board health crashed: {e.__class__.__name__}: {str(e)[:80]} — no Boards lines, stale.json not written"
        _stage_alarms.append(_line); print(f"::warning::stage {_line}", flush=True)

    _phase("role record")
    stats["accepted"] = len(accepted)
    merged = store.merge_duplicates(accepted)
    # one posting fetched under two company names (two registry rows on one board) is ONE
    # role: kept under one name, the other named in the mail — never published twice
    merged, _claim_lines = ledger.resolve_claims(merged, failed=failed_names,
                                                 scanned={r["company_name"] for r in rows})
    for _line in _claim_lines:
        print(f"::warning::roles {_line}", flush=True)
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
    # (`failed_names` is collected by name in the fetch loop: splitting the mail string on
    # " (" broke for the 15 registry names that contain " (" — Microsoft (Xbox/Gaming) …)
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
    alive_jobs = list(board_jobs)             # the role record judges closure on THIS, not the capped page
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

    # the role record's own verdict on the run: what closed, reopened, was re-posted; the
    # ledger flushed (or why not). Closure is judged only where this run actually looked.
    _role_lines = ledger.record_run(
        run_date, board_jobs=alive_jobs, merged=merged,
        scanned_ok={r["company_name"] for r in rows}, failed=failed_names, paths=paths,
        scoped=bool(only or limit))
    _role_lines = _role_lines + _claim_lines
    for _line in [a for a in ledger.alarms if a not in _stage_alarms]:
        _stage_alarms.append(_line); print(f"::warning::stage {_line}", flush=True)

    # Company intel — blurbs + researched facts for every card (pipeline/company_intel.py,
    # lane: company-intel, ARCHITECTURE §7). One call: bounded in calls and minutes (FIRMO_MAX_PER_RUN /
    # FIRMO_TIME_BUDGET_MIN / BLURB_MAX_PER_RUN), never raises, never writes the shared
    # export on a scoped run, and reports itself into the audit block below.
    _phase("company intel")
    company_info, firmo_display, _intel = company_intel.enrich_for_run(
        st, board_jobs=board_jobs, email_jobs=email_jobs,
        all_companies={j["company"] for j in st.get_matched_since("0000-01-01")},
        run_date=run_date, use_llm=use_llm, scoped=bool(only or limit),
        profiles_path=os.path.join(REPO_ROOT, "company_profiles.json"))
    _intel_lines, _intel_warn = company_intel.audit_lines(_intel)
    for _line in _intel_warn:
        print(f"::warning::company-intel {_line}", flush=True)
    print(f"  [company-intel] {'; '.join(_intel_lines)}", flush=True)
    stats["firmographics_researched"] += _intel["researched"]
    stats["company_summaries"] += _intel["blurbs_written"]

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
        "registry_alarms": _registry_alarms_lines,
        "stage_alarms": _stage_alarms,
        "fetch_health": _fetch_health_lines,
        "company_intel": _intel_lines,
        "roles": _role_lines,
        "paths": dict(paths),
        "failed_companies": failed_companies,
    }

    # optional aggregate analytics: set GOATCOUNTER_CODE to your goatcounter subdomain
    gc = os.environ.get("GOATCOUNTER_CODE", "").strip()
    analytics_html = (f'<script data-goatcounter="https://{gc}.goatcounter.com/count" '
                      f'async src="//gc.zgo.at/count.js"></script>') if gc else \
        os.environ.get("ANALYTICS_SNIPPET", "")
    contact_url = os.environ.get("CONTACT_URL",
                                 "https://github.com/AnalystJobsIL/board/issues/new")
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
    # Render every product in one call (lane: render, ARCHITECTURE §7d): board and archive
    # first, so what went wrong rendering them reaches the email that is built last; the
    # role record supplies "also listed as" / re-posted / closed-on. Never raises — a product
    # that fails is reported (a warning here, a bold line in the mail) and NOT written, so
    # yesterday's file stays; a failed email ships a stub that names the failure.
    _phase("render")
    rendered = digest_mod.render_all(email_jobs, board_jobs, arch, run_date, summary, company_info,
                                     firmographics=firmo_display, board_url=os.environ.get("BOARD_URL", ""),
                                     analytics_html=analytics_html, contact_url=contact_url,
                                     ledger=ledger.records)
    for _line in rendered["warnings"]:
        print(f"::warning::{_line}", flush=True)
    summary["render"] = rendered["render_lines"]
    subject, md_body = rendered["subject"], rendered["md_body"]
    if not rendered["email_ok"]:
        # the stub is not a digest: nothing in it was delivered, so nothing may be marked sent
        email_jobs = []
    _phase("write")
    base = os.path.join(out_dir, f"digest-{run_date}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(rendered["html"])
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(rendered["text"])
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(md_body)
    # interactive board for GitHub Pages (served from /docs)
    # a scoped run (--only / --limit) must NOT overwrite the published board with a
    # partial one; local experiments were clobbering docs/index.html
    docs_dir = os.path.join(out_dir, "docs-preview") if (only or limit) else os.path.join(REPO_ROOT, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    for _name, _ok in (("index.html", rendered["board_ok"]), ("archive.html", rendered["archive_ok"])):
        if _ok:                                   # a failed product keeps yesterday's file
            with open(os.path.join(docs_dir, _name), "w", encoding="utf-8") as f:
                f.write(rendered["board_html" if _name == "index.html" else "archive_html"])
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

    if os.environ.get("GITHUB_ACTIONS"):
        print("::endgroup::", flush=True)
    _PHASE["name"] = "done"
    _write_step_summary(summary, run_date, docs_dir)
    print(f"\n=== digest {run_date} ===")
    print(f"email (last 48h): {summary['new']} roles · board (active): {summary['board_count']} roles"
          f"  (scanned {summary['companies_scanned']} cos, {summary['companies_failed']} failed, "
          f"{summary['llm_calls']} LLM calls)")
    # the real directory: a scoped run writes out/docs-preview/, never the published board
    try:
        _rel = os.path.relpath(docs_dir, REPO_ROOT)
    except ValueError:                    # another drive on Windows
        _rel = docs_dir
    print(f"wrote: {base}.html / .txt / .md / .json + {_rel}/index.html")
    return payload, base


def _record_crash(exc, out_dir=OUT_DIR):
    """out/crash.json: what `persist_state.py outcome` puts in the failure notice."""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tail = "".join(tb).splitlines()[-15:]
    rec = {"phase": _PHASE["name"], "exc_type": type(exc).__name__, "message": str(exc)[:300],
           "traceback_tail": tail, "when": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "crash.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return rec


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
    try:
        run(use_llm=not a.no_llm, limit=a.limit,
            only=a.only.split(",") if a.only else None,
            run_date=a.date, out_dir=a.out, db_path=a.db)
    except Exception as e:  # noqa: BLE001 -- a crash must name its phase, on the run page and in the notice
        rec = _record_crash(e, a.out)
        if os.environ.get("GITHUB_ACTIONS") and _PHASE["name"] not in ("start", "done"):
            print("::endgroup::", flush=True)
        print(f"::error::pipeline crashed in phase '{rec['phase']}': {rec['exc_type']}: {rec['message']}", flush=True)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
