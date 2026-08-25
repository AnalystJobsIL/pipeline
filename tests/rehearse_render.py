"""Rehearse the render layer (lane: render, ARCHITECTURE.md §7d) without spending anything.

    python tests/rehearse_render.py --golden <baseline_digest.py>   # every product byte-equal?
    python tests/rehearse_render.py --cards [--cards-golden cards.json]   # the card model, diffed
    python tests/rehearse_render.py --real --only "Fiverr,Wix,Lightricks" # live scoped run, no LLM/BD
    python tests/rehearse_render.py --full                            # tomorrow's email, scratch copy

All modes work on a scratch copy of `cloud_state/` (seen.db + both roles ledgers + the stage
stamps). Bright Data and the LLM are unreachable by construction (keys stripped, JD_BD=0,
use_llm=False). Nothing under the repo is written except by `--full`, which is an unscoped
`pipeline.run` and therefore rewrites `docs/*.html`, `cloud_state/stale.json` and
`health_baseline.json` — it copies them aside and restores them with `git checkout --`.

`--golden` renders the same jobs, blurbs and facts twice — once with the module at the path
given (a snapshot of digest.py from before a change) and once with this tree — and reports
byte-equality per product plus a diff. A pure move must come back 6/6 identical; a behaviour
change must come back with exactly the diff its commit message enumerates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

REPO = os.environ.get("REHEARSE_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.environ.get("REHEARSE_SCRATCH") or os.path.join(REPO, "out", "rehearse-render")
sys.path.insert(0, REPO)

ap = argparse.ArgumentParser()
ap.add_argument("--golden", metavar="BASELINE_PY", help="path to a snapshot of pipeline/digest.py")
ap.add_argument("--cards", action="store_true", help="dump the card model for every store role")
ap.add_argument("--cards-golden", metavar="JSON", help="compare --cards against this dump")
ap.add_argument("--real", action="store_true")
ap.add_argument("--full", action="store_true")
ap.add_argument("--only", default="Fiverr,Wix,Lightricks")
ap.add_argument("--date", default=None, help="run_date for --golden/--cards (default: today)")
a = ap.parse_args()

status0 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "JDFILL", "SCRAPE_VIA_UNLOCKER", "AGGREGATOR_ENABLED",
          "SERPAPI_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GOATCOUNTER_CODE", "ANALYTICS_SNIPPET", "BOARD_URL"):
    os.environ.pop(k, None)
os.environ["JD_BD"] = "0"
checks = []


def _scratch(tag):
    W = os.path.join(S, tag)
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    for f in ("seen.db", "pipeline_stages.json", "roles.jsonl", "roles_text.jsonl"):
        src = os.path.join(REPO, "cloud_state", f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(W, "stages.json" if f == "pipeline_stages.json" else f))
    return W


def _load_module(name, path):
    """Load a digest.py snapshot AS a member of the `pipeline` package, so its relative
    imports (`from . import roleprofile`) resolve against this tree."""
    spec = importlib.util.spec_from_file_location(f"pipeline.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _inputs(W, run_date):
    """The renderers' inputs, assembled the way run.py assembles them, from the scratch store."""
    from pipeline import store, company_intel
    try:
        from pipeline import roles
    except ImportError:                       # a tree older than the roles lane
        roles = None
    st = store.SeenStore(os.path.join(W, "seen.db"))
    ledger = None
    if roles is not None:
        ledger = roles.Ledger(st, run_date)
        ledger.open_sync()
    today = dt.date.fromisoformat(run_date)
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    everything = st.get_matched_since("0000-01-01")
    board = [j for j in everything if (j.get("last_seen") or "") >= yesterday]
    onboard = {(j["company"], j["title"]) for j in board}
    arch = [j for j in everything if (j["company"], j["title"]) not in onboard]
    arch.sort(key=lambda x: str(x.get("last_seen") or x.get("first_seen") or ""), reverse=True)
    cutoff = (today - dt.timedelta(days=2)).isoformat()
    email = [j for j in board if (j.get("first_seen") or "") >= cutoff][:40]
    company_info, firmo, _rep = company_intel.enrich_for_run(
        st, board_jobs=board, email_jobs=email, all_companies={j["company"] for j in everything},
        run_date=run_date, use_llm=False, scoped=True,
        profiles_path=os.path.join(REPO, "company_profiles.json"))
    # a summary with every key populated, so every audit line renders in every product
    summary = {
        "companies_scanned": 862, "companies_failed": 2, "jobs_fetched": 22859,
        "israel_matched": 4844, "accepted": 71, "after_merge": 54, "new": len(email),
        "board_count": len(board), "llm_calls": 0, "jd_filled_inline": 3, "email_overflow": 0,
        "first_scan": 0, "stages": "collect 2026-08-25 00:12 · enrich 2026-08-25 03:05",
        "dead_sources": ["indeed (0 for 3 days)"], "registry_alarms": ["census unchanged"],
        "stage_alarms": ["collect: unprocessed-14"], "fetch_health": ["changed today: 0 new / 1 cleared", "standing: empty-board 3"],
        "company_intel": ["blurbs 0 · researched 0 · export 940 records"],
        "roles": ["open 60 · closed today 0 · reopened 0 · reposted 0 · ledger 111 = store 111"],
        "paths": {"keyword_nollm": 4840, "merged-copy": 4}, "failed_companies": ["Acme (HTTP 503)"],
    }
    rec = (ledger.records if ledger is not None else {})
    st.close()
    return dict(email=email, board=board, arch=arch, company_info=company_info, firmo=firmo,
                summary=summary, ledger=rec)


def _render(mod, inp, run_date):
    """Every product the lane ships, from one module. Returns {name: text}."""
    import inspect
    kw = {"ledger": inp["ledger"]} if "ledger" in inspect.signature(mod.build_board_html).parameters else {}
    out = {}
    _t, out["latest.md"] = mod.build_markdown(inp["email"], run_date, inp["summary"], inp["company_info"],
                                              board_url="https://analystjobsil.github.io/board/",
                                              firmographics=inp["firmo"], **kw)
    out["index.html"] = mod.build_board_html(inp["board"], run_date, inp["summary"], inp["company_info"],
                                             analytics_html="", contact_url="https://github.com/AnalystJobsIL/board/issues/new",
                                             firmographics=inp["firmo"], **kw)
    out["archive.html"] = mod.build_board_html(inp["arch"], run_date, inp["summary"], company_info=inp["company_info"],
                                               heading="archived roles (no longer on the employer's careers page)",
                                               firmographics=inp["firmo"], **kw)
    subject, html, text = mod.build_digest(inp["email"], run_date, inp["summary"])
    out["digest.html"] = html
    out["digest.txt"] = text
    out["subject"] = subject
    return out


def golden(baseline_py):
    run_date = a.date or dt.date.today().isoformat()
    W = _scratch("golden")
    inp = _inputs(W, run_date)
    base = _load_module("_baseline_digest", baseline_py)
    from pipeline import digest as tree
    got_b = _render(base, inp, run_date)
    got_t = _render(tree, inp, run_date)
    print(f"golden: {len(inp['board'])} board · {len(inp['arch'])} archive · {len(inp['email'])} email roles, run_date {run_date}")
    for name in got_b:
        same = got_b[name] == got_t[name]
        checks.append((f"{name} byte-identical to baseline", same))
        for tag, txt in (("baseline", got_b[name]), ("tree", got_t[name])):
            with open(os.path.join(W, f"{tag}-{name}"), "w", encoding="utf-8") as f:
                f.write(txt)
        if not same:
            # the board body is one line: split at tag boundaries so the diff says WHAT moved
            _split = (lambda t: t.replace("><", ">\n<").splitlines()) if name.endswith(".html") else str.splitlines
            bl, tl = _split(got_b[name]), _split(got_t[name])
            d = list(difflib.unified_diff(bl, tl, "baseline", "tree", lineterm="", n=0))
            adds = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
            dels = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
            print(f"  {name}: +{adds} -{dels} lines differ (full diff in {W})")
            for l in d[:40]:
                print("   ", l[:160])
    print(f"products written to {W}")


def cards():
    run_date = a.date or dt.date.today().isoformat()
    W = _scratch("cards")
    inp = _inputs(W, run_date)
    from pipeline import rolecard
    dump = {}
    for kind, jobs in (("board", inp["board"]), ("archive", inp["arch"])):
        for j in jobs:
            c = rolecard.build(j, run_date, ledger_rec=inp["ledger"].get(j.get("mkey")),
                               company_info=inp["company_info"], firmographics=inp["firmo"],
                               archived=(kind == "archive"))
            dump[f"{kind}|{j.get('mkey') or j['company'] + '|' + j['title']}"] = c
    issues = rolecard.cross_check([dump[k] for k in dump])
    dump["_cross_check"] = issues
    path = os.path.join(W, "cards.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
    degraded = sum(1 for k, c in dump.items() if k != "_cross_check" and c.get("issues"))
    print(f"cards: {len(dump) - 1} cards · {degraded} with issues · cross-check {issues} → {path}")
    if a.cards_golden:
        old = json.load(open(a.cards_golden, encoding="utf-8"))
        dump = json.loads(json.dumps(dump, ensure_ascii=False, default=str))   # tuples -> lists, like the file
        keys = sorted(set(old) | set(dump))
        changed = {}
        for k in keys:
            o, n = old.get(k), dump.get(k)
            if o != n:
                if isinstance(o, dict) and isinstance(n, dict):
                    fields = sorted(f for f in set(o) | set(n) if o.get(f) != n.get(f))
                else:
                    fields = ["<whole>"]
                changed[k] = fields
        from collections import Counter
        by_field = Counter(f for fs in changed.values() for f in fs)
        print(f"cards vs golden: {len(changed)} cards differ; fields: {dict(by_field)}")
        for k in list(changed)[:12]:
            print("   ", k, changed[k])
        checks.append(("card golden compared (see counts above)", True))


def real():
    from pipeline import run as R, stages
    W = _scratch("real")
    R._load_secrets_env = lambda: None
    stages.PATH = os.path.join(W, "stages.json")
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    payload, base = R.run(use_llm=False, only=only, out_dir=os.path.join(W, "out"),
                          db_path=os.path.join(W, "seen.db"))
    md = open(base + ".md", encoding="utf-8").read()
    for l in md.splitlines():
        if l.startswith(("- **Render:**", "- **Roles:**", "- **Stages:**", "- Decision paths")):
            print(l)
    s = payload["summary"]
    checks.append(("Decision paths reconcile", sum(s["paths"].values()) == s["israel_matched"]))
    checks.append(("Render line present in the mail", any(l.startswith("- **Render:**") for l in md.splitlines())))
    checks.append(("docs-preview board written, not docs/", os.path.exists(os.path.join(W, "out", "docs-preview", "index.html"))))


def full():
    """Tomorrow's email: an UNSCOPED run over the whole registry on a scratch store. Live
    fetches (no LLM, no Bright Data). ~30-60 min. Restores the four tree files it rewrites."""
    from pipeline import run as R, stages
    W = _scratch("full")
    R._load_secrets_env = lambda: None
    stages.PATH = os.path.join(W, "stages.json")
    tree_files = ["docs/index.html", "docs/archive.html", "cloud_state/stale.json", "cloud_state/health_baseline.json"]
    # an unscoped run rewrites these four tracked files; put back the BYTES that were there
    # (another lane's uncommitted edit included), never `git checkout --`
    before = {f: open(os.path.join(REPO, f), "rb").read() for f in tree_files if os.path.exists(os.path.join(REPO, f))}
    try:
        payload, base = R.run(use_llm=False, out_dir=os.path.join(W, "out"), db_path=os.path.join(W, "seen.db"))
        for f in ("docs/index.html", "docs/archive.html"):
            shutil.copy(os.path.join(REPO, f), os.path.join(W, os.path.basename(f)))
    finally:
        for f, data in before.items():
            with open(os.path.join(REPO, f), "wb") as fh:
                fh.write(data)
    md = open(base + ".md", encoding="utf-8").read()
    s = payload["summary"]
    print(f"full: scanned {s['companies_scanned']} failed {s['companies_failed']} · board {s['board_count']} · email {s['new']}")
    for l in md.splitlines():
        if l.startswith(("- **Render:**", "- **Roles:**", "- **Stages:**", "- **Registry:**", "- Decision paths", "- Companies scanned")):
            print(l)
    rows = open(os.path.join(W, "index.html"), encoding="utf-8").read().count('<tr class="row"')
    print(f"board rows rendered: {rows} (stats board_count {s['board_count']})")
    checks.append(("Decision paths reconcile", sum(s["paths"].values()) == s["israel_matched"]))
    checks.append(("Render line present", any(l.startswith("- **Render:**") for l in md.splitlines())))
    checks.append(("products copied to scratch", os.path.exists(os.path.join(W, "archive.html"))))


if a.golden:
    golden(a.golden)
if a.cards:
    cards()
if a.real:
    real()
if a.full:
    full()

status1 = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=REPO).stdout
checks.append(("git status unchanged", status0 == status1))
ok = True
for label, passed in checks:
    print(("PASS " if passed else "FAIL ") + label)
    ok = ok and passed
sys.exit(0 if ok else 1)
