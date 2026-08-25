#!/usr/bin/env python3
"""Rehearse tomorrow's delivery before pushing it (lane: infra). Never touches the repo's
own state: temp git repos, a scratch store, out/rehearse-infra/. No LLM, no Bright Data.

    python tests/rehearse_infra.py --conflict   # replay the real 2026-08-24 stamp loss on temp repos
    python tests/rehearse_infra.py --mail       # a scoped run with a failed pre-step, a stale publish
                                                #   stamp and yesterday's failed publish injected
    python tests/rehearse_infra.py --notice     # the failure notice, as the outcome step would write it
    python tests/rehearse_infra.py --golden REV # digests/latest.md from the same inputs at REV vs the tree
    python tests/rehearse_infra.py --all

Each mode prints what it proved and exits non-zero on the first thing that does not hold.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "out", "rehearse-infra")
PERSIST = os.path.join(ROOT, "persist_state.py")


def _g(cwd, *args):
    p = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=r", "-c", "user.email=r@x", *args],
                       cwd=cwd, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"git {args}: {p.stderr.decode('utf-8', 'replace')}")
    return p.stdout.decode("utf-8", "replace")


def _check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def conflict():
    """The 2026-08-24 night, replayed: listing-hunt lands `repair` at 22:12; auto-expand,
    checked out at 20:00, pushes at 23:40 into a conflict. Origin must hold both stamps,
    both registry rows and the deletion the refresh made on purpose."""
    print("== conflict: the 0b41823 night on temp repos")
    real_stamps = json.load(open(os.path.join(ROOT, "cloud_state", "pipeline_stages.json"), encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="rehearse-infra-")
    origin = os.path.join(tmp, "origin.git")
    _g(tmp, "init", "-q", "--bare", origin)
    _g(origin, "symbolic-ref", "HEAD", "refs/heads/master")
    hunt, expand = os.path.join(tmp, "hunt"), os.path.join(tmp, "expand")
    _g(tmp, "clone", "-q", origin, hunt)
    os.makedirs(os.path.join(hunt, "cloud_state"))
    base = {k: v for k, v in real_stamps.items() if k != "repair"}
    json.dump(base, open(os.path.join(hunt, "cloud_state", "pipeline_stages.json"), "w", encoding="utf-8"), indent=1, sort_keys=True)
    hdr = "company_name,ats_platform,token,api_url,active,notes\n"
    open(os.path.join(hunt, "companies.csv"), "w", encoding="utf-8", newline="").write(
        hdr + "Alpha,scrape,,https://alpha/careers,false,monitored candidate\n"
              "Beta,scrape,,https://beta/jobs,false,no listing found\n")
    json.dump({"Alpha": [{"title": "old"}], "Gone": [{"title": "x"}]},
              open(os.path.join(hunt, "scraped_cache.json"), "w", encoding="utf-8"))
    _g(hunt, "add", "-A"); _g(hunt, "commit", "-q", "-m", "seed"); _g(hunt, "push", "-q", "origin", "HEAD:master")
    _g(tmp, "clone", "-q", origin, expand)                       # auto-expand checks out at 20:00
    # 22:12 listing-hunt: stamps repair, verifies Beta
    st = dict(base); st["repair"] = {"date": "2026-08-24", "finished_at": "2026-08-24T22:12:18+00:00"}
    json.dump(st, open(os.path.join(hunt, "cloud_state", "pipeline_stages.json"), "w", encoding="utf-8"), indent=1, sort_keys=True)
    open(os.path.join(hunt, "companies.csv"), "w", encoding="utf-8", newline="").write(
        hdr + "Alpha,scrape,,https://alpha/careers,false,monitored candidate\n"
              "Beta,scrape,,https://beta/jobs,true,no listing found | listing-hunt 2026-08-24: verified 2 IL\n")
    r = subprocess.run([sys.executable, PERSIST, "commit", "--cwd", hunt, "--as", "audit-bot", "-m", "listing-hunt 2026-08-24",
                        "--sleep", "0", "--gate", "", "--branch", "master",
                        "--own", "companies.csv", "scraped_cache.json", "cloud_state/pipeline_stages.json",
                        "cloud_state/registry_ladder.json"], capture_output=True, cwd=ROOT)
    _check(r.returncode == 0, "listing-hunt pushed cleanly: " + r.stdout.decode().strip().splitlines()[-1])
    # 23:40 auto-expand from the 20:00 checkout: stamps expand, triages Alpha, drops Gone
    st2 = dict(base); st2["expand"] = {"date": "2026-08-24", "finished_at": "2026-08-24T23:40:42+00:00"}
    json.dump(st2, open(os.path.join(expand, "cloud_state", "pipeline_stages.json"), "w", encoding="utf-8"), indent=1, sort_keys=True)
    open(os.path.join(expand, "companies.csv"), "w", encoding="utf-8", newline="").write(
        hdr + "Alpha,scrape,,https://alpha/careers,false,monitored candidate | dark-triage 2026-08-24: page-empty\n"
              "Beta,scrape,,https://beta/jobs,false,no listing found\n")
    json.dump({"Alpha": [{"title": "old"}]}, open(os.path.join(expand, "scraped_cache.json"), "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, PERSIST, "commit", "--cwd", expand, "--as", "expand-bot", "-m", "auto-expand 2026-08-24",
                        "--sleep", "0", "--gate", "", "--branch", "master",
                        "--own", "companies.csv", "scraped_cache.json", "cloud_state/pipeline_stages.json"],
                       capture_output=True, cwd=ROOT)
    out = r.stdout.decode()
    _check(r.returncode == 0 and "conflict on attempt 1" in out, "auto-expand hit the conflict and recovered")
    got = json.loads(_g(origin, "show", "master:cloud_state/pipeline_stages.json"))
    _check(got.get("repair", {}).get("finished_at") == "2026-08-24T22:12:18+00:00", "origin keeps listing-hunt's `repair` stamp")
    _check(got.get("expand", {}).get("finished_at") == "2026-08-24T23:40:42+00:00", "origin keeps auto-expand's `expand` stamp")
    csv = _g(origin, "show", "master:companies.csv")
    _check("dark-triage 2026-08-24: page-empty" in csv and "listing-hunt 2026-08-24: verified 2 IL" in csv
           and "Beta,scrape,,https://beta/jobs,true" in csv, "both registry writes survive, Beta stays activated")
    cache = json.loads(_g(origin, "show", "master:scraped_cache.json"))
    _check("Gone" not in cache and "Alpha" in cache, "the deletion auto-expand made on purpose stands (BACKLOG 95)")
    log = _g(origin, "log", "--format=%s", "master")
    _check("(row-merged)" in log, "the recovery commit is labelled: " + log.splitlines()[0])
    shutil.rmtree(tmp, ignore_errors=True)


def mail():
    """Tomorrow's mail with three things wrong, on a scratch store: a pre-step failed, the
    publish stamp is two days old, yesterday's board publish failed."""
    print("== mail: a scoped run with injected failures")
    import datetime as dt
    for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER", "AGGREGATOR_ENABLED",
              "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY"):
        os.environ.pop(k, None)
    os.environ["JD_BD"] = "0"
    scratch = os.path.join(OUT, "mail")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(os.path.join(scratch, "cloud_state"))
    for f in ("seen.db", "roles.jsonl", "roles_text.jsonl"):
        shutil.copy(os.path.join(ROOT, "cloud_state", f), os.path.join(scratch, "cloud_state", f))
    from pipeline import run as R, stages
    today = dt.date.today()
    stamps = json.load(open(stages.PATH, encoding="utf-8"))
    stamps["publish"] = {"date": (today - dt.timedelta(days=2)).isoformat(), "finished_at": "x"}
    stamps["repair"] = {"date": (today - dt.timedelta(days=1)).isoformat(), "finished_at": "x"}
    stages.PATH = os.path.join(scratch, "stages.json")
    json.dump(stamps, open(stages.PATH, "w", encoding="utf-8"))
    last = os.path.join(scratch, "last_run.json")
    json.dump({"date": (today - dt.timedelta(days=1)).isoformat(), "status": "failure",
               "run_url": "https://github.com/AnalystJobsIL/pipeline/actions/runs/0",
               "failed_steps": {"publish": "failure"}}, open(last, "w", encoding="utf-8"))
    R.LAST_RUN_PATH = last
    R._load_secrets_env = lambda: None
    os.environ["WORKFLOW_STEP_OUTCOMES"] = json.dumps({"discovery": {"outcome": "success"}, "liveness": {"outcome": "failure"}})
    summary_path = os.path.join(scratch, "summary.md")
    os.environ["GITHUB_STEP_SUMMARY"] = summary_path
    status0 = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True).stdout
    payload, base = R.run(use_llm=False, only=["Fiverr", "Wix", "Lightricks"], run_date=today.isoformat(),
                          out_dir=os.path.join(scratch, "out"), db_path=os.path.join(scratch, "cloud_state", "seen.db"))
    md = open(base + ".md", encoding="utf-8").read()
    alarms = payload["summary"]["stage_alarms"]
    print("  alarms:", *alarms, sep="\n    ")
    _check(any(a.startswith("workflow step 'liveness' failure") for a in alarms), "the failed pre-step is an alarm")
    _check(any(a == "publish last ran 2d ago — yesterday's digest never completed" for a in alarms), "the stale publish stamp is an alarm")
    _check(any("run failure: publish (failure)" in a for a in alarms), "yesterday's failed publish is an alarm")
    _check(not any(a.startswith("repair") for a in alarms), "a repair stamp from last evening is NOT an alarm")
    fold = md.index("<details>")
    _check(all(md.index(a.split(" — ")[0][:40]) < fold for a in alarms if "'liveness'" in a), "the alarm sits above the fold")
    paths = payload["summary"]["paths"]
    _check(sum(paths.values()) == payload["summary"]["israel_matched"], f"Decision paths reconcile: {paths}")
    _check(os.path.exists(os.path.join(scratch, "out", "docs-preview", "index.html")), "the scoped run wrote out/docs-preview/, not docs/")
    _check(os.path.exists(summary_path) and "workflow step 'liveness'" in open(summary_path, encoding="utf-8").read(),
           "the run page summary carries the same alarm")
    status1 = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True).stdout
    _check(status0 == status1, "the repo's own state is untouched")
    print("  mail head:", md.splitlines()[0])


def notice():
    print("== notice: what the outcome step writes when the pipeline crashed")
    import persist_state as P
    into = os.path.join(OUT, "notice")
    shutil.rmtree(into, ignore_errors=True)
    root_backup = P.ROOT
    P.ROOT = os.path.join(OUT, "notice-root")
    os.makedirs(os.path.join(P.ROOT, "out"), exist_ok=True)
    json.dump({"phase": "classify 4844 Israel-matched postings", "exc_type": "KeyError", "message": "'company'",
               "traceback_tail": ["  File \"pipeline/roles.py\", line 300, in classify_grouped", "KeyError: 'company'"]},
              open(os.path.join(P.ROOT, "out", "crash.json"), "w", encoding="utf-8"))
    os.environ["STEPS_JSON"] = json.dumps({"discovery": {"outcome": "success"}, "liveness": {"outcome": "failure"},
                                           "pipeline": {"outcome": "failure"}, "mark_sent": {"outcome": "success"},
                                           "gate": {"outcome": "success"}, "persist": {"outcome": "success"},
                                           "publish": {"outcome": "skipped"}})
    os.environ["JOB_STATUS"] = "failure"
    os.environ["RUN_URL"] = "https://github.com/AnalystJobsIL/pipeline/actions/runs/0"
    rc = P.main(["outcome", "--into", into, "--date", "2026-08-26"])
    P.ROOT = root_backup
    _check(rc == 0, "outcome exits 0")
    text = open(os.path.join(into, "digests", "latest.md"), encoding="utf-8").read()
    print("  " + "\n  ".join(text.splitlines()[:9]))
    _check(text.startswith("# ⚠️ No digest for 2026-08-26"), "a dated title (a new relay hash every day)")
    _check("`pipeline` (outcome: failure)" in text and "KeyError: 'company'" in text and "phase `classify" in text, "names the step, the phase, the exception")
    _check("collect:" in text, "carries the real stage stamps")
    last = json.load(open(os.path.join(into, "cloud_state", "last_run.json"), encoding="utf-8"))
    _check(last["failed_steps"] == {"liveness": "failure", "pipeline": "failure"} and last["notice"], "last_run.json lists every failed step")


def golden(rev):
    """The same inputs rendered by the tree and by REV: the only differences allowed are the
    alarm lines this lane added (so the run.py edits changed nothing else in the mail)."""
    print(f"== golden: tree vs {rev}")
    import difflib
    scratch = os.path.join(OUT, "golden")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)
    wt = os.path.join(scratch, "wt")
    subprocess.run(["git", "worktree", "add", "-q", wt, rev], cwd=ROOT, check=True)
    try:
        outs = {}
        for label, cwd in (("tree", ROOT), ("rev", wt)):
            st = os.path.join(scratch, label)
            os.makedirs(os.path.join(st, "cloud_state"))
            for f in ("seen.db", "roles.jsonl", "roles_text.jsonl"):
                shutil.copy(os.path.join(ROOT, "cloud_state", f), os.path.join(st, "cloud_state", f))
            env = {k: v for k, v in os.environ.items() if k not in ("WORKFLOW_STEP_OUTCOMES", "GITHUB_STEP_SUMMARY",
                   "GITHUB_ACTIONS", "BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "CLAUDE_CODE_OAUTH_TOKEN")}
            env["JD_BD"] = "0"
            subprocess.run([sys.executable, "-m", "pipeline.run", "--only", "Fiverr,Wix,Lightricks", "--no-llm",
                            "--db", os.path.join(st, "cloud_state", "seen.db"), "--out", os.path.join(st, "out"),
                            "--date", "2026-08-26"], cwd=cwd, env=env, check=True, capture_output=True)
            outs[label] = open(os.path.join(st, "out", "digest-2026-08-26.md"), encoding="utf-8").read().splitlines()
        diff = [l for l in difflib.unified_diff(outs["rev"], outs["tree"], lineterm="", n=0)
                if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        print("  " + "\n  ".join(diff) if diff else "  byte-identical")
        allowed = ("- **Stages:**", "+- **Stages:**", "-- **Stages:**")
        bad = [l for l in diff if not (l[1:].startswith("- **Stages:**"))]
        _check(not bad, "only the Stages line differs")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=ROOT, capture_output=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    os.makedirs(OUT, exist_ok=True)
    if not a or "--conflict" in a or "--all" in a:
        conflict()
    if "--notice" in a or "--all" in a:
        notice()
    if "--mail" in a or "--all" in a:
        mail()
    if "--golden" in a:
        golden(a[a.index("--golden") + 1])
    print("rehearsal done")
