#!/usr/bin/env python3
"""Mutation-survival gate for the registry's identity gates.

**Why this exists.** Six `inspect.getsource` / `ast.parse` guards in this repo either broke
when the code they guarded was legitimately improved, or were defeated by one-token edits
that preserved the source text while inverting the logic -- with `python -m pytest` reporting
green throughout. Two that actually shipped:

    if verdict.startswith("cracked") and not ok_to_write(...)
 -> if verdict == "cracked-scrape" and not ok_to_write(...) and n_il < 0

    elif verdict == "found" and not identity_ok(name, url)
 -> elif verdict == "found" and identity_ok(name, url) is None

A guard that asserts HOW a thing is written breaks when the thing improves and passes when
the thing breaks. This turns "the guards are fake" from a judgement call into an exit code:
apply a mutation, run the suite, and require it to go RED.

Usage:
    python tools/mutate.py --all              # every mutation in tests/mutations.json
    python tools/mutate.py --class M1,M2      # only those classes
    python tools/mutate.py --id crack-narrow  # one mutation
    python tools/mutate.py --coverage         # only the derived-coverage check

Exit 0 iff every mutation was killed AND the coverage check passes. Read-only with respect to
the repo: each mutation is applied to a `git archive HEAD` copy under the system temp dir.

lane: `registry`.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE = os.path.join(ROOT, "tests", "mutations.json")

# A test is STATIC if it reasons about source text, BEHAVIOURAL if it runs the code. The
# distinction is the whole point of `must_be_killed_by_behavioural`.
_STATIC_MARKERS = ("inspect.getsource", "ast.parse", "ast.walk")
_BEHAVIOURAL_MARKERS = ("tmp_path", "monkeypatch")

# Mutation classes, each seeded from a defect that actually shipped here.
CLASSES = {
    "M1": "gate-removal: the gate call is replaced by a constant, or its `if` deleted",
    "M2": "gate-inversion: truthiness inverted while the source token survives",
    "M3": "branch-narrowing: a guarded branch is made to cover fewer cases",
    "M4": "dead-conjunct: an always-false term appended so the guard never fires",
    "M5": "population-widening: a row selector is widened or removed",
    "M6": "fallback-removal: a rung is dropped from a search/resolution ladder",
    "M7": "constant-drift: a note length, throttle, budget or terminal token is changed",
}


def _load():
    with open(CATALOGUE, encoding="utf-8") as fh:
        return json.load(fh)


def _archive(dest):
    """git archive HEAD -> dest. Never touches the working tree."""
    os.makedirs(dest, exist_ok=True)
    tar = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    p = subprocess.Popen(["tar", "-x", "-C", dest], stdin=subprocess.PIPE)
    p.communicate(tar)
    if p.returncode:
        raise SystemExit("git archive/tar failed")


def _classify_killer(work, test_id):
    """Is the test that killed this mutation behavioural, or does it only read source?"""
    name = test_id.split("::")[-1].split("[")[0]
    for path in glob.glob(os.path.join(work, "tests", "test_*.py")):
        src = open(path, encoding="utf-8").read()
        m = re.search(r"^def %s\(.*?(?=^def |\Z)" % re.escape(name), src, re.S | re.M)
        if not m:
            continue
        body = m.group(0)
        if any(k in body for k in _BEHAVIOURAL_MARKERS):
            return "behavioural"
        if any(k in body for k in _STATIC_MARKERS):
            return "static"
        return "direct"          # calls the predicate itself: real behaviour, no fixture
    return "unknown"


def run_one(mut, work_root):
    work = os.path.join(work_root, mut["id"])
    _archive(work)
    target = os.path.join(work, mut["file"])
    src = open(target, encoding="utf-8").read()
    n = src.count(mut["find"])
    if n != 1:
        return ("FAIL", "stale mutation: %d matches for `find`, re-aim it" % n, "")
    open(target, "w", encoding="utf-8").write(src.replace(mut["find"], mut["replace"], 1))

    # NO `-x`. "A static guard may never be the SOLE killer" is a claim about the whole set
    # of failing tests, and `-x` reports only the first one -- which is file/definition
    # order, not significance. Five mutations were reported as static-only kills purely
    # because a source-text guard happened to be defined above the behavioural fixture that
    # also caught them. The harness must not manufacture its own finding.
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=work, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1800)
    if proc.returncode == 0:
        return ("FAIL", "SURVIVED — the suite is green with this mutation applied", "")
    # pytest -q prints `FAILED tests/x.py::test_y - AssertionError` in the short summary and
    # `tests\x.py:NNN: AssertionError` in the traceback. Match the summary first. Without a
    # killer we cannot enforce `must_be_killed_by_behavioural`, which is half the point here.
    out = proc.stdout or ""
    killers = re.findall(r"^FAILED ([\w./\\]+::\w+)", out, re.M) or \
        re.findall(r"^([\w./\\]+\.py::\w+)", out, re.M)
    if not killers:
        return ("KILLED", "unknown", "?")
    kinds = {k: _classify_killer(work, k) for k in killers}
    real = [k for k, v in kinds.items() if v in ("behavioural", "direct")]
    if mut.get("must_be_killed_by_behavioural", True) and not real:
        return ("FAIL", "killed ONLY by source-text guard(s): %s"
                % ", ".join(k.split("::")[-1] for k in killers[:3]), killers[0])
    best = real[0] if real else killers[0]
    return ("KILLED", kinds[best], best)


def _registry_writers():
    """Both write shapes, derived — the same detector tests/test_registry.py uses."""
    import ast
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        hit = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for tg in n.targets:
                    if not (isinstance(tg, ast.Subscript)
                            and isinstance(tg.slice, ast.Constant)):
                        continue
                    # index 4 only when it ACTIVATES. `fr[4] = "false"` is a park and needs
                    # no identity evidence -- refresh_scrape_cache parks rotted scrapes that
                    # way. Same rule as tests/test_registry.py's detector; they must agree.
                    if tg.slice.value == 3:
                        hit = True
                    elif (tg.slice.value == 4 and isinstance(n.value, ast.Constant)
                            and n.value.value == "true"):
                        hit = True
            elif isinstance(n, ast.List) and len(n.elts) >= 6:
                e = n.elts[4]
                if isinstance(e, ast.Constant) and e.value == "true":
                    hit = True
        if hit:
            out.append(os.path.basename(path))
    return out


def coverage(muts):
    """Every ACTIVATING writer must carry a mutation in M1, M2 and M3.

    Derived, not hand-listed: a seventh activating tool becomes a red build on the commit
    that adds it, instead of a review finding eight waves later.
    """
    from collections import defaultdict
    have = defaultdict(set)
    for m in muts:
        have[m["file"]].add(m["class"].split("-")[0])
    covered = json.load(open(os.path.join(ROOT, "tests", "mutations.json"),
                             encoding="utf-8"))  # noqa: F841  (documents the source)
    exempt = set(_load_exempt())
    gaps = []
    for w in _registry_writers():
        if w in exempt:
            continue
        missing = {"M1", "M2", "M3"} - have.get(w, set())
        if missing:
            gaps.append((w, sorted(missing)))
    return gaps


def _load_exempt():
    """Writers whose col-3/4 write is not a proposal, or that no workflow runs.

    Kept in one place with `tests/test_registry.py`'s allow-list, which asserts none of the
    unscheduled ones has become scheduled.
    """
    path = os.path.join(ROOT, "tests", "test_registry.py")
    src = open(path, encoding="utf-8").read()
    names = re.findall(r'"([a-z_]+\.py)":\s*"', src)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--id", default="")
    ap.add_argument("--cls", "--class", dest="cls", default="")
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args()

    muts = _load()
    gaps = coverage(muts)
    if a.coverage:
        for w, missing in gaps:
            print("COVERAGE GAP  %-24s missing %s" % (w, ",".join(missing)))
        print("%d writer(s) with a coverage gap" % len(gaps))
        return 1 if gaps else 0

    if a.id:
        muts = [m for m in muts if m["id"] == a.id]
    elif a.cls:
        want = {c.strip() for c in a.cls.split(",")}
        muts = [m for m in muts if m["class"].split("-")[0] in want]
    elif not a.all:
        ap.error("pass --all, --id, --class or --coverage")

    work_root = os.path.join(tempfile.gettempdir(), "ajil_mutants")
    shutil.rmtree(work_root, ignore_errors=True)
    os.makedirs(work_root, exist_ok=True)

    print("%-30s %-22s %-11s %s" % ("id", "class", "result", "killed by"))
    print("-" * 100)
    bad = 0
    for m in muts:
        status, detail, killer = run_one(m, work_root)
        if status == "FAIL":
            bad += 1
            print("%-30s %-22s %-11s %s" % (m["id"], m["class"], "** FAIL **", detail))
        else:
            print("%-30s %-22s %-11s %s (%s)" % (m["id"], m["class"], "killed",
                                                 killer.split("::")[-1][:52], detail))
    for w, missing in gaps:
        bad += 1
        print("%-30s %-22s %-11s missing %s" % (w, "coverage", "** FAIL **", ",".join(missing)))

    print("-" * 100)
    print("%d mutation(s): %d killed, %d SURVIVING/failed; %d coverage gap(s)"
          % (len(muts), len(muts) - (bad - len(gaps)), bad - len(gaps), len(gaps)))
    if bad:
        print("\nA surviving mutation means the gate it targets is not actually guarded.")
    shutil.rmtree(work_root, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
