"""Rehearse tomorrow's digest ROLE-RECORD path against SCRATCH COPIES only — zero spend, zero
tree writes (ARCHITECTURE.md §7c, "Start here"). Not a test; run by hand:

    python tests/rehearse_roles.py                     # --case happy: six scripted days
    python tests/rehearse_roles.py --case clobber      # sqlite loses rows -> the ledger rehydrates
    python tests/rehearse_roles.py --case corrupt      # a wrecked ledger -> alarm, never overwritten
    python tests/rehearse_roles.py --case massclose    # every board empties -> statuses HELD
    python tests/rehearse_roles.py --real --only "Fiverr,Wix,Lightricks"   # live fetch, no LLM/BD
    python tests/rehearse_roles.py --golden            # HEAD (git worktree) vs this tree, same fixture

The scripted cases replace `fetchers.fetch_company` and `load_companies` with
tests/fixtures/roles/days.json (the shapes found in the committed store on 2026-08-25: one
posting under two names by seen_id and by url+title, a repost, a failed board, a closure, a
reopening) and run `pipeline.run.run` once per day against a scratch store + ledger, with
the LLM off and every key stripped. Then PROVES from the produced digests: the `Roles:` line
says what the day did, `Decision paths` reconcile, the board holds exactly the expected
roles, the ledger on disk agrees with sqlite, and `git status` is unchanged.
"""
import argparse, json, os, re, shutil, sqlite3, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("REHEARSE_REPO") or os.path.abspath(os.path.join(HERE, ".."))   # --golden points this at HEAD's worktree
S = os.environ.get("REHEARSE_SCRATCH") or os.path.join(REPO, "out", "rehearse")
FIX = json.load(open(os.path.join(HERE, "fixtures", "roles", "days.json"), encoding="utf-8"))
ap = argparse.ArgumentParser()
ap.add_argument("--case", default="happy", choices=["happy", "clobber", "corrupt", "massclose"])
ap.add_argument("--real", action="store_true", help="live fetchers on a scratch copy of cloud_state (no LLM, no BD)")
ap.add_argument("--only", default="Fiverr,Wix,Lightricks")
ap.add_argument("--golden", action="store_true", help="run the fixture through HEAD and this tree; diff the outputs")
ap.add_argument("--tag", default="")
a = ap.parse_args()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, REPO)
os.chdir(REPO)
status0 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER", "AGGREGATOR_ENABLED",
          "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
    os.environ.pop(k, None)
os.environ["JD_BD"] = "0"
checks = []


def _job(spec):
    if isinstance(spec, str):
        return dict(FIX["jobs"][spec])
    return {**FIX["jobs"][spec["base"]], **{k: v for k, v in spec.items() if k != "base"}}


def _run_day(R, W, day, fetch_map, only=None):
    from pipeline import fetchers, stages
    from pipeline import run as _rm

    def fake_fetch(row):
        got = fetch_map.get(row["company_name"], [])
        if got == "ERROR":
            raise RuntimeError("HTTP 503 (fixture)")
        return [_job(s) for s in got]
    fetchers.fetch_company = fake_fetch
    _rm.load_companies = lambda: [dict(r) for r in FIX["companies"]]
    stages.PATH = os.path.join(W, "stages.json")
    return R.run(use_llm=False, only=only, run_date=day, out_dir=os.path.join(W, "out"),
                 db_path=os.path.join(W, "seen.db"))


def scripted(case, W):
    from pipeline import run as R
    try:
        from pipeline import roles
    except ImportError:                      # --golden runs this driver against HEAD, which has no ledger
        class roles:                          # noqa: N801 — a stub so the days still run
            MASS_CLOSE_MIN = 10
            ledger_paths = staticmethod(lambda db: (os.path.join(os.path.dirname(db), "roles.jsonl"),
                                                    os.path.join(os.path.dirname(db), "roles_text.jsonl")))
            load = staticmethod(lambda path: ({}, "missing", 0))
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    shutil.copy(os.path.join(REPO, "cloud_state", "pipeline_stages.json"), os.path.join(W, "stages.json"))
    R._load_secrets_env = lambda: None
    ledger_path, text_path = roles.ledger_paths(os.path.join(W, "seen.db"))
    if case == "massclose":
        roles.MASS_CLOSE_MIN = 2          # the fixture has 5 roles; the real floor is 10
    days = FIX["days"]
    for i, d in enumerate(days):
        fetch = dict(d["fetch"])
        if case == "massclose" and i >= 4:
            fetch = {c: [] for c in fetch}   # two empty days: `_alive` gives one day's grace
        if case == "clobber" and i == 2:
            con = sqlite3.connect(os.path.join(W, "seen.db"))
            con.execute("delete from matched")
            con.execute("delete from sent")
            con.commit()
            con.close()
        if case == "corrupt" and i == 2:
            open(ledger_path, "w", encoding="utf-8").write("{wreck\n{wreck\n{wreck\n")
            wreck = open(ledger_path, encoding="utf-8").read()
        # scoped on purpose: an unscoped run() writes the REAL docs/*.html, stale.json and
        # health_baseline.json (the same guard every other rehearsal relies on)
        payload, base = _run_day(R, W, d["date"], fetch, only=[c["company_name"] for c in FIX["companies"]])
        s = payload["summary"]
        md = open(base + ".md", encoding="utf-8").read()
        line = next((l for l in md.splitlines() if l.startswith("- **Roles:**")), "")
        stg = next((l for l in md.splitlines() if l.startswith("- **Stages:**")), "")
        print(f"[{d['date']}] {line}")
        if stg:
            print(f"           {stg}")
        exp = d.get("expect", {})
        checks.append((f"{d['date']} Decision paths reconcile", sum(s["paths"].values()) == s["israel_matched"]))
        # the board = still-open roles, from out/docs-preview (scoped) or docs (full) — read the payload instead
        con = sqlite3.connect(os.path.join(W, "seen.db"))
        has_status = "status" in {r[1] for r in con.execute("pragma table_info(matched)")}   # HEAD (--golden) has none
        board = sorted(f"{c}|{t}" for c, t in con.execute(
            "select company, title from matched where last_seen>=?"
            + (" and coalesce(status,'')!='superseded'" if has_status else ""),
            ((__import__('datetime').date.fromisoformat(d["date"]) - __import__('datetime').timedelta(days=1)).isoformat(),)))
        sup = sorted(c for (c,) in con.execute("select company from matched where status='superseded'")) if has_status else []
        con.close()
        if case == "corrupt" and i >= 2:
            checks.append((f"{d['date']} corrupt ledger is on the Stages line", "roles ledger corrupt" in stg))
            checks.append((f"{d['date']} corrupt ledger not overwritten", open(ledger_path, encoding="utf-8").read() == wreck))
            checks.append((f"{d['date']} Roles line says frozen", "ledger frozen" in line))
            continue
        if case == "massclose" and i == 4:
            continue
        if case == "massclose" and i == 5:
            checks.append((f"{d['date']} mass-close is HELD and on the Stages line", "mass-close held" in stg))
            recs, st_, _ = roles.load(ledger_path)
            want_open = days[4]["expect"]["board_n"]
            checks.append((f"{d['date']} statuses held ({want_open} still open, only day 5's closure stands)",
                           sum(1 for r in recs.values() if r["status"] == "open") == want_open))
            continue
        if case == "clobber" and i == 2:
            checks.append((f"{d['date']} rehydrated after the clobber", "rehydrated" in stg and re.search(r"rehydrated \d+", line) is not None))
        if "claims" in exp and not (case == "clobber" and i == 2):
            checks.append((f"{d['date']} claim line", exp["claims"] in line))
        if "board" in exp:
            checks.append((f"{d['date']} board is exactly {exp['board']}", board == exp["board"]))
        if "board_n" in exp and case != "massclose":
            checks.append((f"{d['date']} board has {exp['board_n']} roles", len(board) == exp["board_n"]))
        if "closed_today" in exp and case != "massclose":
            checks.append((f"{d['date']} closed today {exp['closed_today']}", f"closed today {exp['closed_today']} " in line))
        if "reopened" in exp:
            checks.append((f"{d['date']} reopened {exp['reopened']}", f"reopened {exp['reopened']} " in line))
        if "reposted" in exp:
            checks.append((f"{d['date']} reposted {exp['reposted']}", f"reposted {exp['reposted']} " in line))
        if "failed" in exp:
            checks.append((f"{d['date']} failed {exp['failed']}", s["companies_failed"] == exp["failed"]))
        # the losers were collapsed BEFORE they ever reached the store, so nothing to supersede
        # (a loser already in the store is the unit test's case: the sweep at open)
        checks.append((f"{d['date']} no loser ever entered the store", sup == []))
        recs, st_, _ = roles.load(ledger_path)
        checks.append((f"{d['date']} ledger ok and = store", st_ == "ok" and " = store " in line and "!=" not in line))
        for k, u in exp.get("canonical_url", {}).items():
            checks.append((f"{d['date']} canonical url of {k} is the board's, not the card's",
                           (recs.get(k) or {}).get("url") == u))
        if "closed" in exp:
            checks.append((f"{d['date']} closed: {exp['closed']}",
                           all(recs.get(k.lower(), {}).get("status") == "closed" for k in exp["closed"])))
        if "episodes" in exp:
            checks.append((f"{d['date']} episodes {exp['episodes']}",
                           all(len(recs.get(k, {}).get("episodes", [])) == n for k, n in exp["episodes"].items())))
        checks.append((f"{d['date']} no description text in roles.jsonl",
                       not any("description" in r for r in recs.values())))
        checks.append((f"{d['date']} every record carries tags/class/attribution",
                       all(r.get("tags") and r.get("attribution") is not None for r in recs.values())))


def real(W):
    from pipeline import run as R
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    for f in ("seen.db", "pipeline_stages.json", "roles.jsonl", "roles_text.jsonl"):
        src = os.path.join(REPO, "cloud_state", f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(W, "stages.json" if f == "pipeline_stages.json" else f))
    from pipeline import stages
    R._load_secrets_env = lambda: None
    stages.PATH = os.path.join(W, "stages.json")
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    payload, base = R.run(use_llm=False, only=only, out_dir=os.path.join(W, "out"), db_path=os.path.join(W, "seen.db"))
    s = payload["summary"]
    md = open(base + ".md", encoding="utf-8").read()
    for l in md.splitlines():
        if l.startswith(("- **Roles:**", "- **Stages:**", "- Decision paths")):
            print(l)
    checks.append(("Decision paths reconcile", sum(s["paths"].values()) == s["israel_matched"]))
    line = next((l for l in md.splitlines() if l.startswith("- **Roles:**")), "")
    checks.append(("Roles line present with ledger = store", "ledger" in line and " = store " in line))
    checks.append(("ledger written beside the scratch db", os.path.exists(os.path.join(W, "roles.jsonl"))))
    checks.append(("real cloud_state untouched", not os.path.exists(os.path.join(REPO, "cloud_state", "roles.jsonl"))
                   or status0 == subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout))


def golden(W):
    """Same fixture, HEAD vs this tree: per day, the email payload (company|title) and the
    board set must agree except for the claim collapse (HEAD publishes Port.io beside Port
    and OTORIO beside Armis) — proof that the windows did not move."""
    head = os.path.join(W, "head")
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)
    r = subprocess.run(["git", "worktree", "add", "--detach", head, "HEAD"], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr)
        sys.exit(2)
    try:
        driver = os.path.join(HERE, "rehearse_roles.py")
        got = {}
        for label, repo in (("head", head), ("tree", REPO)):
            env = {**os.environ, "REHEARSE_SCRATCH": os.path.join(W, "s"), "REHEARSE_REPO": repo}
            p = subprocess.run([sys.executable, driver, "--case", "happy", "--tag", label], cwd=repo,
                               env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(f"--- {label}: rc={p.returncode}" + ("" if p.returncode == 0 else " (expected for HEAD: no Roles line)"))
            if p.returncode != 0:
                print(p.stderr[-600:])
            w = os.path.join(W, "s", "roles_" + label)
            con = sqlite3.connect(os.path.join(w, "seen.db"))
            per_day = {}
            for d in FIX["days"]:
                pj = json.load(open(os.path.join(w, "out", f"digest-{d['date']}.json"), encoding="utf-8"))
                per_day[d["date"]] = sorted(f"{j['company']}|{j['title']}" for j in pj["jobs"])
            has_status = "status" in {r[1] for r in con.execute("pragma table_info(matched)")}
            board = sorted(f"{c}|{t}" for c, t in con.execute(
                "select company, title from matched" + (" where coalesce(status,'')!='superseded'" if has_status else "")))
            con.close()
            got[label] = (per_day, board)
            if label == "tree":
                got["tree_rc"] = p.returncode
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", head], cwd=REPO, capture_output=True)
    # EXACT, not a subset: with the collapse disabled `h - t` is empty and a subset check
    # passes — the golden must prove the feature ran, not only that nothing got worse
    allowed = {"OTORIO|Senior Data Analyst", "Port.io|Senior BI Analyst Tel Aviv - Israel"}
    checks.append(("the tree's run succeeded", got["tree_rc"] == 0))
    for date in got["head"][0]:
        h, t = set(got["head"][0][date]), set(got["tree"][0][date])
        print(f"[{date}] email head={len(h)} tree={len(t)} head-only={sorted(h - t)} tree-only={sorted(t - h)}")
        expect = h & allowed                     # whatever HEAD emailed under a loser's name, and only that
        checks.append((f"{date} email differs from HEAD by exactly the claim collapse ({sorted(expect)})",
                       (h - t) == expect and not (t - h)))
    hb, tb = set(got["head"][1]), set(got["tree"][1])
    print(f"board head={len(hb)} tree={len(tb)} head-only={sorted(hb - tb)} tree-only={sorted(tb - hb)}")
    checks.append(("board differs from HEAD by exactly the two collapsed doubles", (hb - tb) == allowed and not (tb - hb)))


W = os.path.join(S, "roles_" + (a.tag or ("real" if a.real else "golden" if a.golden else a.case)))
if a.golden:
    golden(W)
elif a.real:
    real(W)
else:
    scripted(a.case, W)
status1 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
checks.append(("git status unchanged (nothing in the tree was written)", status0 == status1))
ok = all(v for _, v in checks)
for label, v in checks:
    print(("PASS " if v else "FAIL ") + label)
print(f"outputs in {W}")
sys.exit(0 if ok else 1)
