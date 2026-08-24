"""Rehearse tomorrow's digest company-intel path against SCRATCH COPIES only — zero spend,
zero tree writes (ARCHITECTURE.md §7, "Guards and how to rehearse"). Not a test; run by hand:

    python tests/rehearse_company_intel.py --case a                       # LLM off
    python tests/rehearse_company_intel.py --case json --hole "Phoenix Financial" --only "Phoenix Financial,Wix"
    python tests/rehearse_company_intel.py --case fail|unknown|prose|sleep ...
    python tests/rehearse_company_intel.py --case a --export corrupt|missing

Copies cloud_state/seen.db + the export to a scratch work dir, strips every key from the env,
puts the fake `claude` shim (tests/fixtures/company_intel/claude.cmd, FAKE_CLAUDE=<case>)
first on PATH, monkeypatches SHARED_EXPORT / stages.PATH / _load_secrets_env, calls
pipeline.run.run(...) and asserts `git status` is unchanged. `--hole` deletes the named
companies from the SCRATCH copies so there is research to do. Windows shim; on Linux write a
`claude` shell script with the same contract next to it.
"""
import argparse, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
S = os.environ.get("REHEARSE_SCRATCH") or os.path.join(HERE, "..", "out", "rehearse")
os.makedirs(S, exist_ok=True)
FIXTURES = os.path.join(HERE, "fixtures", "company_intel")
ap = argparse.ArgumentParser(); ap.add_argument("--case", default="a"); ap.add_argument("--only", default="")
ap.add_argument("--export", default="copy"); ap.add_argument("--tree", default=os.path.abspath(os.path.join(HERE, "..")))
ap.add_argument("--tag", default="run"); ap.add_argument("--hole", default="", help="companies whose profile+blurb+strikes are deleted from the SCRATCH copies"); a = ap.parse_args()
REPO = a.tree; sys.path.insert(0, REPO); os.chdir(REPO)
status0 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
W = os.path.join(S, "work_" + a.tag); shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
shutil.copy(os.path.join(REPO, "cloud_state", "seen.db"), os.path.join(W, "seen.db"))
exp = os.path.join(W, "firmographics.json")
if a.export == "copy": shutil.copy(os.path.join(REPO, "cloud_state", "firmographics.json"), exp)
elif a.export == "corrupt": open(exp, "w").write('{"a": ')
shutil.copy(os.path.join(REPO, "cloud_state", "pipeline_stages.json"), os.path.join(W, "stages.json"))
if a.hole:
    import sqlite3, json as _j
    names = [x.strip() for x in a.hole.split(",") if x.strip()]
    con = sqlite3.connect(os.path.join(W, "seen.db"))
    for n in names:
        for tbl in ("firmographics", "company_info", "firmo_failed"):
            con.execute(f"DELETE FROM {tbl} WHERE company=?", (n,))
    con.commit(); con.close()
    if os.path.exists(exp):
        d = _j.load(open(exp, encoding="utf-8"))
        for n in names: d.pop(n, None)
        _j.dump(d, open(exp, "w", encoding="utf-8"), ensure_ascii=False, indent=2, sort_keys=True)
    print("hole punched for", names)
for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER", "AGGREGATOR_ENABLED", "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
    os.environ.pop(k, None)
os.environ["PATH"] = FIXTURES + os.pathsep + os.environ["PATH"]
os.environ["FAKE_CLAUDE"] = a.case; os.environ["FAKE_CLAUDE_LOG"] = os.path.join(W, "claude_calls.log")
from pipeline import run as R, firmographics as F, stages
R._load_secrets_env = lambda: None
F.SHARED_EXPORT = exp; stages.PATH = os.path.join(W, "stages.json")
if a.case != "a":
    print("where claude ->", subprocess.run(["where", "claude"], capture_output=True, text=True, shell=True).stdout.split("\n")[0])
t0 = time.time()
R.run(use_llm=a.case != "a", only=[x.strip() for x in a.only.split(",") if x.strip()] or None,
      out_dir=os.path.join(W, "out"), db_path=os.path.join(W, "seen.db"))
print(f"elapsed {time.time()-t0:.0f}s; outputs in {W}")
status1 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
print("GIT STATUS UNCHANGED" if status0 == status1 else "!!! GIT STATUS CHANGED:\n" + status1)
