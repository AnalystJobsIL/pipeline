"""Rehearse tomorrow's digest CLASSIFIER path against SCRATCH COPIES only — zero spend, zero
tree writes (ARCHITECTURE.md §7b, "Start here"). Not a test; run by hand:

    python tests/rehearse_classifier.py --case yes --only "Fiverr,Wix,Lightricks"
    python tests/rehearse_classifier.py --case fail|is_error|unknown_flag|sleep|flaky|all_no|all_yes|no_structured|rate_limit ...
    python tests/rehearse_classifier.py --case nollm ...        # --no-llm, the fake never runs
    python tests/rehearse_classifier.py --case yes --fresh ...  # empty scratch llm_cache: every LLM-tier role is fresh

Copies cloud_state/seen.db + the stage stamp to a scratch work dir, strips every key from the
env, puts the fake `claude` shim (tests/fixtures/classifier, FAKE_CLAUDE=<case>) first on PATH,
runs pipeline.run.run(...) scoped, then PROVES from the produced digest: the audit block's
`Decision paths` reconcile to `Israel-matched`, the `Stages:` line carries the classify alarm
the case predicts (or none), the scratch db gained exactly the verdicts it should (none on a
quarantined or breaker morning), and `git status` is unchanged. Prints PASS/FAIL per check.
"""
import argparse, json, os, re, shutil, sqlite3, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
S = os.environ.get("REHEARSE_SCRATCH") or os.path.join(REPO, "out", "rehearse")
FIXTURES = os.path.join(HERE, "fixtures", "classifier")
ap = argparse.ArgumentParser()
ap.add_argument("--case", default="yes")
ap.add_argument("--only", default="Fiverr,Wix")
ap.add_argument("--tag", default="")
ap.add_argument("--fresh", action="store_true",
                help="empty llm_cache in the SCRATCH copy so every LLM-tier role is a fresh verdict "
                     "(the quarantine judges fresh verdicts; re-judgements of legacy rows are expected to move)")
a = ap.parse_args()
sys.path.insert(0, REPO); os.chdir(REPO)
status0 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
W = os.path.join(S, "classify_" + (a.tag or a.case)); shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
shutil.copy(os.path.join(REPO, "cloud_state", "seen.db"), os.path.join(W, "seen.db"))
shutil.copy(os.path.join(REPO, "cloud_state", "pipeline_stages.json"), os.path.join(W, "stages.json"))
if a.fresh or a.case in ("all_no", "all_yes"):
    con = sqlite3.connect(os.path.join(W, "seen.db")); con.execute("delete from llm_cache"); con.commit(); con.close()
    print("scratch llm_cache emptied (--fresh)")
for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER", "AGGREGATOR_ENABLED",
          "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLASSIFY_LLM_CAP", "CLASSIFY_TIME_BUDGET_MIN"):
    os.environ.pop(k, None)
os.environ["JD_BD"] = "0"
os.environ["PATH"] = FIXTURES + os.pathsep + os.environ["PATH"]
os.environ["FAKE_CLAUDE"] = a.case
os.environ["FAKE_CLAUDE_LOG"] = os.path.join(W, "claude_calls.log")
os.environ["FAKE_CLAUDE_COUNTER"] = os.path.join(W, "counter")
os.environ["FAKE_CLAUDE_SLEEP"] = "4"
os.environ["CLASSIFY_TIMEOUT"] = "2" if a.case == "sleep" else "45"
os.environ["CLASSIFY_QUARANTINE_MIN"] = "10"     # a 10-company rehearsal yields ~13 fresh verdicts
from pipeline import run as R, stages, seniority
R._load_secrets_env = lambda: None
stages.PATH = os.path.join(W, "stages.json")
print("claude ->", shutil.which("claude"))
rows_before = sqlite3.connect(os.path.join(W, "seen.db")).execute("select count(*) from llm_cache").fetchone()[0]
t0 = time.time()
payload, base = R.run(use_llm=a.case != "nollm",
                      only=[x.strip() for x in a.only.split(",") if x.strip()] or None,
                      out_dir=os.path.join(W, "out"), db_path=os.path.join(W, "seen.db"))
print(f"elapsed {time.time() - t0:.0f}s; outputs in {W}")
md = open(base + ".md", encoding="utf-8").read()
summ = payload["summary"]
calls = [json.loads(l) for l in open(os.environ["FAKE_CLAUDE_LOG"], encoding="utf-8")] \
    if os.path.exists(os.environ["FAKE_CLAUDE_LOG"]) else []
rows_after = sqlite3.connect(os.path.join(W, "seen.db")).execute("select count(*) from llm_cache").fetchone()[0]
paths = summ["paths"]
stage_line = next((l for l in md.splitlines() if l.startswith("- **Stages:**")), "")
checks = []
checks.append(("paths reconcile: %s = israel %s" % (sum(paths.values()), summ["israel_matched"]),
               sum(paths.values()) == summ["israel_matched"]))
# attempts >= llm + failed: a failed RE-judge keeps the cached bare verdict (path llm_cache)
checks.append(("llm_calls = attempts (%s) >= llm + failed" % summ["llm_calls"],
               summ["llm_calls"] >= paths.get("llm", 0) + paths.get("llm_failed_fallback", 0)))
expect_alarm = {"fail": "llm-unavailable(auth", "is_error": "llm-unavailable(auth", "unknown_flag": "llm-unavailable(drift",
                "rate_limit": "llm-unavailable(transient", "sleep": "llm-unavailable(transient",
                "all_no": "mass-no", "all_yes": "mass-yes",
                "no_structured": "LLM calls failed (answer: no structured verdict"}.get(a.case)
if a.fresh and not expect_alarm and paths.get("llm", 0) >= 10:
    # every LLM-tier role is fresh: the quarantine judges this run's yes-rate, whatever the case
    yes = sum(1 for l in md.splitlines() if False)   # the md does not carry the count; read the log
    log = [l for l in open(os.environ["FAKE_CLAUDE_LOG"], encoding="utf-8")]
    expect_alarm = {"no": "mass-no", "all_no": "mass-no", "all_yes": "mass-yes"}.get(a.case)
if expect_alarm:
    checks.append((f"Stages line says {expect_alarm}: {stage_line[:160]}", expect_alarm in stage_line))
    checks.append(("no verdict cached on a broken morning: %d -> %d rows" % (rows_before, rows_after),
                   rows_after == rows_before))
else:
    checks.append((f"no classify alarm: {stage_line[:120] or '(none)'}", "classify" not in stage_line))
if a.case in ("yes", "no", "prose_before_json", "flaky") and not expect_alarm:
    checks.append(("fresh verdicts cached: %d -> %d rows (llm=%s)" % (rows_before, rows_after, paths.get("llm", 0)),
                   rows_after == rows_before + paths.get("llm", 0)))
if a.case == "nollm":
    checks.append(("the fake never ran under --no-llm", calls == []))
if calls:
    argv = calls[0]["argv"]
    checks.append(("argv is the pinned seam (tools off, json, schema, THE FULL rules, no session)",
                   all(f in argv for f in ("--tools", "--json-schema", "--system-prompt", "--no-session-persistence"))
                   and argv[argv.index("--tools") + 1] == ""
                   and argv[argv.index("--system-prompt") + 1] == seniority.LLM_RULES))
    checks.append(("cwd is not the repo", os.path.abspath(calls[0]["cwd"]) != REPO))
status1 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
checks.append(("git status unchanged", status0 == status1))
print(f"case={a.case} paths={paths} llm_calls={summ['llm_calls']} calls={len(calls)} rows {rows_before}->{rows_after}")
print("audit lines:")
for l in md.splitlines():
    if l.startswith(("- Decision paths", "- LLM calls", "- **Stages", "- Jobs fetched")):
        print("   ", l)
ok = True
for label, passed in checks:
    print(("PASS " if passed else "FAIL ") + label); ok &= passed
sys.exit(0 if ok else 1)
