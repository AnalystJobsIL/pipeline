"""Rehearse tomorrow's digest company-intel path against SCRATCH COPIES only — zero spend,
zero tree writes (ARCHITECTURE.md §7). Not a test; run by hand:

    python tests/rehearse_company_intel.py --case a                       # LLM off
    python tests/rehearse_company_intel.py --case json --hole "Wix,Fiverr" --only "Wix,Fiverr"
    python tests/rehearse_company_intel.py --case fail|is_error|unknown|prose|no_search|sleep
    python tests/rehearse_company_intel.py --case a --export corrupt|missing
    python tests/rehearse_company_intel.py --all                          # every case, one exit code

Copies cloud_state/seen.db + the export to a scratch work dir, strips every key from the env,
puts the fake `claude` shim (tests/fixtures/company_intel/, FAKE_CLAUDE=<case>) first on PATH,
monkeypatches SHARED_EXPORT / stages.PATH / _load_secrets_env, calls pipeline.run.run(...) and
CHECKS THE RESULT. `--hole` deletes the named companies from the SCRATCH copies so there is
research to do.

IT EXITS NON-ZERO WHEN A CHECK FAILS, and that is the point of the rewrite (BACKLOG 246).
Until 2026-08-26 this driver had no assertions at all: it printed a plausible line and
returned 0 even when every research call had failed, and it wrote FAKE_CLAUDE_LOG without
ever reading it. An attacker proved it printed a BYTE-IDENTICAL line with the flagship fix
(dropping a blurb cached under a non-company name) deleted from the source. A rehearsal that
cannot fail is not a rehearsal — it is a screenshot.
"""
import argparse
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.environ.get("REHEARSE_SCRATCH") or os.path.join(HERE, "..", "out", "rehearse")
FIXTURES = os.path.join(HERE, "fixtures", "company_intel")

ap = argparse.ArgumentParser()
ap.add_argument("--case", default="a")
ap.add_argument("--all", action="store_true", help="run every case and sum the exit codes")
ap.add_argument("--only", default="")
ap.add_argument("--export", default="copy")
ap.add_argument("--tree", default=os.path.abspath(os.path.join(HERE, "..")))
ap.add_argument("--tag", default="")
ap.add_argument("--hole", default="",
                help="companies whose profile+blurb+strikes are deleted from the SCRATCH copies")
a = ap.parse_args()
REPO = a.tree
sys.path.insert(0, REPO)

# what each case must produce. `line` fragments must ALL appear; `absent` must not.
EXPECT = {
    "a":        {"line": ["research off (--no-llm)"], "kinds": set(), "strikes": 0},
    # blurbs are not guaranteed: on a scoped run every board company may already have one,
    # and `derive_blurb` is free. Research is what --hole makes certain.
    "json":     {"line": ["researched"], "kinds": {"research"}, "strikes": 0},
    "unknown":  {"line": ["failed", "why failed:"], "kinds": {"research"}, "strikes": None},
    "prose":    {"line": ["failed"], "kinds": {"research"}, "strikes": None},
    # the CLI IS invoked once and fails -- that is how the outage is found. What matters is
    # that it STOPS there and blames nobody: max_calls 1, and zero strikes against real names.
    "fail":     {"line": ["claude unavailable"], "max_calls": 1, "strikes": 0},
    "is_error": {"line": ["claude unavailable"], "max_calls": 1, "strikes": 0},
    "no_search": {"line": ["SEARCHLESS"], "kinds": {"research"}, "strikes": 0,
                  "warn": ["no web search"]},
}


def run_case(case, tag, hole, only, export_mode):
    checks, work = [], os.path.join(S, "work_" + (tag or case))

    def check(ok, what, detail=""):
        checks.append((bool(ok), what, detail))

    os.makedirs(S, exist_ok=True)
    os.chdir(REPO)
    status0 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                             cwd=REPO).stdout
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    shutil.copy(os.path.join(REPO, "cloud_state", "seen.db"), os.path.join(work, "seen.db"))
    exp = os.path.join(work, "firmographics.json")
    if export_mode == "copy":
        shutil.copy(os.path.join(REPO, "cloud_state", "firmographics.json"), exp)
    elif export_mode == "corrupt":
        io.open(exp, "w", encoding="utf-8").write('{"a": ')
    shutil.copy(os.path.join(REPO, "cloud_state", "pipeline_stages.json"),
                os.path.join(work, "stages.json"))

    if hole:
        names = [x.strip() for x in hole.split(",") if x.strip()]
        con = sqlite3.connect(os.path.join(work, "seen.db"))
        for n in names:
            for tbl in ("firmographics", "company_info", "firmo_failed"):
                con.execute(f"DELETE FROM {tbl} WHERE company=?", (n,))
        con.commit()
        con.close()
        if os.path.exists(exp):
            d = json.load(io.open(exp, encoding="utf-8"))
            for n in names:
                d.pop(n, None)
            json.dump(d, io.open(exp, "w", encoding="utf-8"), ensure_ascii=False, indent=2,
                      sort_keys=True)

    for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER",
              "AGGREGATOR_ENABLED", "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        os.environ.pop(k, None)
    os.environ["PATH"] = FIXTURES + os.pathsep + os.environ["PATH"]
    os.environ["FAKE_CLAUDE"] = case
    log = os.path.join(work, "claude_calls.log")
    os.environ["FAKE_CLAUDE_LOG"] = log

    from pipeline import company_intel as CI
    from pipeline import firmographics as F
    from pipeline import run as R
    from pipeline import stages
    R._load_secrets_env = lambda: None
    F.SHARED_EXPORT = exp
    stages.PATH = os.path.join(work, "stages.json")

    # the import-time trap: the knobs must be what the env says, at CALL time
    check(CI._report()["cap"] == CI._knob("FIRMO_MAX_PER_RUN"),
          "the budget knobs are read from the env at call time")

    buf, real = io.StringIO(), sys.stdout

    class Tee:
        def write(self, t):
            buf.write(t)
            real.write(t)

        def flush(self):
            real.flush()

    t0 = time.time()
    sys.stdout = Tee()
    try:
        R.run(use_llm=case != "a",
              only=[x.strip() for x in only.split(",") if x.strip()] or None,
              out_dir=os.path.join(work, "out"), db_path=os.path.join(work, "seen.db"))
    finally:
        sys.stdout = real
    out = buf.getvalue()
    secs = time.time() - t0

    # ---- 1. the shim was never asked something it could not classify --------------------
    calls = [json.loads(l) for l in io.open(log, encoding="utf-8").read().splitlines()
             if l.strip()] if os.path.exists(log) else []
    unknown = [c for c in calls if c.get("kind") == "unknown"]
    check(not unknown, "the shim classified every argv it was given",
          f"{len(unknown)} unclassifiable")

    exp_case = EXPECT.get(case, {})
    kinds = {c["kind"] for c in calls}
    want_kinds = exp_case.get("kinds")
    if want_kinds is not None:
        check(want_kinds <= kinds or not want_kinds,
              f"the calls this case must make happened: {sorted(want_kinds) or 'none'}",
              f"saw {sorted(kinds)}")
    if want_kinds == set():
        check(not [c for c in calls if c["kind"] in ("research", "blurb")],
              "no research or blurb call was spent", f"saw {sorted(kinds)}")
    if "max_calls" in exp_case:
        spent = [c for c in calls if c["kind"] in ("research", "blurb")]
        check(len(spent) <= exp_case["max_calls"],
              f"the outage stopped it after <= {exp_case['max_calls']} call(s)",
              f"spent {len(spent)}")

    # ---- 2. the argv the real seam builds ----------------------------------------------
    for c in calls:
        if c["kind"] != "research":
            continue
        argv = c["argv"]
        check("--model" in argv and argv[argv.index("--model") + 1],
              "research pins a model", " ".join(argv[:6]))
        check(argv[argv.index("--tools") + 1] == "WebSearch" and "--allowedTools" in argv,
              "research grants WebSearch on BOTH axes")
        check("israeli-jobs-pipeline" not in str(c.get("cwd", "")).lower(),
              "the call did not run from the repo", str(c.get("cwd"))[:60])
        break
    for c in calls:
        if c["kind"] == "blurb":
            check(c["argv"][c["argv"].index("--tools") + 1] == "",
                  "the blurb is tool-less")
            break

    # ---- 3. the mail line ---------------------------------------------------------------
    _refusal = ("blurb dropped,", "blurb refused,", "research refused,", "FAILED:",
                "store sync skipped", "registry backlog not counted", "shared export NOT")
    line = next((l for l in out.splitlines()
                 if "[company-intel]" in l and not any(r in l for r in _refusal)), "")
    check(line, "the company-intel audit line was printed")
    for frag in exp_case.get("line", []):
        check(frag in line, f"the line says {frag!r}", line[:120])
    for frag in exp_case.get("warn", []):
        check(any(frag in l for l in out.splitlines() if "::warning::company-intel" in l),
              f"a warning says {frag!r}")
    try:
        line.encode("cp1252")
        check(True, "the line survives a cp1252 console")
    except UnicodeEncodeError as e:
        check(False, "the line survives a cp1252 console", str(e)[:80])

    # ---- 4. the export the reader can open NOW -----------------------------------------
    if export_mode == "copy":
        after = json.load(io.open(exp, encoding="utf-8"))
        before = len(json.load(io.open(os.path.join(REPO, "cloud_state",
                                                    "firmographics.json"), encoding="utf-8")))
        check(len(after) >= before - len([x for x in hole.split(",") if x.strip()]),
              "the scratch export never SHRANK", f"{len(after)} records")
        if "export " in line:
            said = int(line.split("export ", 1)[1].split(" ", 1)[0])
            check(said == len(after) or "NOT written" in line or "scoped" in line,
                  "the line's export count matches the file", f"line {said} vs file {len(after)}")
    elif export_mode == "corrupt":
        check(io.open(exp, encoding="utf-8").read() == '{"a": ',
              "a corrupt export was left BYTE-IDENTICAL")

    # ---- 5. strikes only where the case predicts them -----------------------------------
    con = sqlite3.connect(os.path.join(work, "seen.db"))
    strikes = con.execute("SELECT count(*) FROM firmo_failed WHERE last=?",
                          (time.strftime("%Y-%m-%d"),)).fetchone()[0]
    con.close()
    want_strikes = exp_case.get("strikes")
    if want_strikes is not None:
        check(strikes == want_strikes,
              f"strikes recorded today == {want_strikes}", f"saw {strikes}")

    # ---- 6. nothing that is not a company rendered --------------------------------------
    bad = [n for n in json.load(io.open(exp, encoding="utf-8"))] if export_mode == "copy" else []
    check(not [n for n in bad if F.not_a_company(n) and n not in (hole or "")],
          "no name the gate refuses was written to the export")

    # ---- 7. NOTHING A REFUSED NAME OWNS REACHES A RENDERED ARTEFACT ---------------------
    # This is the check the first version of this rewrite did not have, and its absence was
    # proven the same way the old driver's was: delete the poisoned-blurb drop from
    # company_intel and all 14 other checks still passed, because they only ever looked at
    # the EXPORT. The poison lives in `company_info`, which goes to the CARDS. So look at
    # what the reader actually receives.
    rendered = ""
    outdir = os.path.join(work, "out")
    for root, _dirs, files in os.walk(outdir):
        for fn in files:
            if fn.endswith((".html", ".md", ".txt")):
                rendered += io.open(os.path.join(root, fn), encoding="utf-8",
                                    errors="replace").read()
    check(bool(rendered), "the run produced a rendered board/digest to inspect")
    con = sqlite3.connect(os.path.join(work, "seen.db"))
    cached = {c: b for c, b in con.execute("SELECT company, summary FROM company_info") if b}
    con.close()
    leaked = []
    for name, blurb in cached.items():
        if not F.not_a_company(name):
            continue
        probe = " ".join(blurb.split())[:60]
        if probe and probe in " ".join(rendered.split()):
            leaked.append((name, probe[:40]))
    check(not leaked,
          "no blurb cached under a refused name reached a card",
          "; ".join(f"{n} -> {t}..." for n, t in leaked))
    # A NOTE, not a check. The section HEADING comes from role records, not from this lane:
    # `### Tel Aviv` survives because 7 open ledger rows keep it inside the board window, and
    # that is BACKLOG 223, lane `roles`. Asserting it here would make this driver permanently
    # red for an item this lane cannot close. What this lane owes is that nothing IT owns --
    # the blurb above, the facts chips -- attaches to such a name.
    refused_headings = [n for n in cached if F.not_a_company(n) and f"### {n}" in rendered]
    if refused_headings:
        print(f"    NOTE  a refused name still has a digest section: {refused_headings} "
              f"-- role records, BACKLOG 223 (lane: roles), not this lane's to remove")

    # ---- 8. the tree is untouched --------------------------------------------------------
    status1 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                             cwd=REPO).stdout
    check(status0 == status1, "git status is unchanged", "the rehearsal wrote to the tree!")

    failed = [c for c in checks if not c[0]]
    print(f"\n--- {case}: {len(checks) - len(failed)}/{len(checks)} PASS, {secs:.0f}s, "
          f"{len(calls)} fake calls -> {work}")
    for ok, what, detail in checks:
        if not ok:
            print(f"    FAIL  {what}" + (f"  [{detail}]" if detail else ""))
    return len(failed)


if __name__ == "__main__":
    cases = ["a", "json", "unknown", "prose", "fail", "is_error", "no_search"] if a.all else [a.case]
    bad = 0
    for i, case in enumerate(cases):
        if i:
            for m in ("pipeline.run", "pipeline.company_intel", "pipeline.firmographics"):
                sys.modules.pop(m, None)
        bad += run_case(case, a.tag or case, a.hole, a.only, a.export)
    print(f"\n==== {'ALL CHECKS PASS' if not bad else str(bad) + ' CHECK(S) FAILED'} ====")
    sys.exit(1 if bad else 0)
