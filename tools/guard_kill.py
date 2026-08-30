#!/usr/bin/env python3
"""Every guard added since a base ref must FAIL when the code it guards is put back.

**Why.** On 2026-08-30 six lanes each shipped assertions and nobody could say how many of
them could fail. `tools/mutate.py` answers that for the 226 catalogued mutations, and for
nothing else: a new test is verified only if someone also writes a mutation record for it.
This is the cheap general form of the same question: take every test function that exists at
HEAD and did not exist at `--base`, put every NON-test tracked file back to `--base` (the
"fix" the tests came with), keep `tests/` at HEAD, and run those tests. A test that still
passes never saw its fix, and a guard that cannot fail is the defect this repo is built
around (`CLAUDE.md`, rule 1; `docs/BACKLOG.md` 386).

Three buckets, printed per test:

  KILLS       failed or errored without the fix -- verified.
  CATALOGUED  passed, but its docstring carries ``Kills `<id>` `` naming a record in
              tests/mutations.json, so `tools/mutate.py` verifies it against that mutation.
  CANNOT-FAIL passed with its fix reverted, and no mutation record vouches for it. Either the
              range contains no fix for it (`no non-test change in range` is printed when the
              revert was a no-op) or the assertion does not depend on the change it shipped
              with. Both are the shape this tool exists to name.

Exit 1 iff any test is CANNOT-FAIL. Read-only: the revert happens in a `git archive HEAD`
copy under the temp dir, never in the working tree. `--base` defaults to the merge base with
`origin/master` (in CI, tests.yml passes the push's `before` sha).

Usage:
    python tools/guard_kill.py                       # new tests since merge-base(origin/master)
    python tools/guard_kill.py --base a07e743~1      # since a commit
    python tools/guard_kill.py --base HEAD~1 --keep  # leave the reverted copy for inspection

lane: `infra` (the test harness; see docs/AGENT_BRIEF.md).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = "tests"
_KILLS_RX = re.compile(r"Kills\s+`([^`]+)`")
_ARGV_CAP = 24_000          # Windows CreateProcess limit is 32 KiB; see tools/mutate.py


def _git(*args, check=True, text=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check,
                          text=text, encoding="utf-8" if text else None,
                          errors="replace" if text else None)


def default_base():
    try:
        return _git("merge-base", "HEAD", "origin/master").stdout.strip()
    except subprocess.CalledProcessError:
        return "HEAD~1"


def _test_names(src, path):
    """{name: docstring} of every top-level `test_*` function and `Test*.test_*` method."""
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out[node.name] = ast.get_docstring(node) or ""
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    out[f"{node.name}::{sub.name}"] = ast.get_docstring(sub) or ""
    return out


def _tracked_at(ref, path):
    r = _git("show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def new_tests(base):
    """[(node id, docstring)] for tests at HEAD that `base` does not have."""
    files = [p for p in _git("ls-tree", "-r", "--name-only", "HEAD", TESTS_DIR).stdout.split("\n")
             if re.search(r"(^|/)test_[^/]*\.py$", p)]
    out = []
    for path in files:
        head = _test_names(_tracked_at("HEAD", path) or "", path)
        old = _tracked_at(base, path)
        before = _test_names(old, path) if old is not None else {}
        for name, doc in head.items():
            if name not in before:
                out.append((f"{path}::{name}", doc))
    return out


def is_test_side(path):
    """What stays at HEAD: the test files, conftest and fixtures. Everything else under
    tests/ is code under test -- `tests/schedule_census.py`, `tests/rehearse_*.py`,
    `tests/role_leak.py` -- and is reverted like any module (the first measurement kept the
    whole directory and wrongly called a census guard CANNOT-FAIL for that reason)."""
    return bool(re.match(r"tests/(test_[^/]*\.py|conftest\.py|fixtures/)", path))


def changed_non_test_paths(base):
    """Tracked paths that differ between base and HEAD and are not test-side."""
    names = _git("diff", "--name-only", f"{base}", "HEAD").stdout.split("\n")
    return [p for p in names if p and not is_test_side(p)]


def build_reverted_copy(base, dest):
    """git archive HEAD into dest, then put every changed non-test file back to `base`."""
    os.makedirs(dest, exist_ok=True)
    tar = _git("archive", "HEAD", text=False).stdout
    p = subprocess.Popen(["tar", "-x", "-C", dest], stdin=subprocess.PIPE)
    p.communicate(tar)
    if p.returncode:
        raise SystemExit("git archive/tar failed")
    reverted = []
    for path in changed_non_test_paths(base):
        target = os.path.join(dest, path)
        old = _git("show", f"{base}:{path}", check=False, text=False)
        if old.returncode == 0:
            os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
            with open(target, "wb") as f:
                f.write(old.stdout)
        elif os.path.exists(target):
            os.remove(target)                       # the file did not exist at base
        reverted.append(path)
    return reverted


def _chunks(node_ids):
    cur, size = [], 0
    for nid in node_ids:
        if cur and size + len(nid) + 1 > _ARGV_CAP:
            yield cur
            cur, size = [], 0
        cur.append(nid)
        size += len(nid) + 1
    if cur:
        yield cur


def run_tests(work, node_ids):
    """{node id: PASSED|FAILED|ERROR|SKIPPED|NOT-RUN} from `-rA` lines."""
    verdict = {}
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    env["AJIL_MUTANT"] = "1"                        # see tools/mutate.py: source != HEAD here
    for chunk in _chunks(node_ids):
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider",
                            "-p", "no:warnings", "--no-header", *chunk], cwd=work,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=1800, env=env)
        for m in re.finditer(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) ([^\s]+::\S+)", r.stdout, re.M):
            status, nid = m.group(1), m.group(2).split("[")[0].replace("\\", "/")
            # a test that both errored in setup and failed keeps the first verdict seen;
            # a SKIPPED line carries file:line, not a node id, so a skip reads as NOT-RUN
            verdict.setdefault(nid, status)
        for nid in chunk:
            verdict.setdefault(nid, "NOT-RUN")
    return verdict


def _catalogued_ids():
    try:
        with open(os.path.join(ROOT, TESTS_DIR, "mutations.json"), encoding="utf-8") as f:
            return {m["id"] for m in json.load(f)}
    except (OSError, ValueError, KeyError):
        return set()


def classify(tests, verdicts, catalogued):
    """[{test, verdict, bucket, kills}] -- pure, so a unit test can drive it."""
    rows = []
    for nid, doc in tests:
        v = verdicts.get(nid, "NOT-RUN")
        kills = [k for k in _KILLS_RX.findall(doc or "") if k in catalogued]
        if v in ("FAILED", "ERROR"):
            bucket = "KILLS"
        elif v == "PASSED" and kills:
            bucket = "CATALOGUED"
        elif v == "PASSED":
            bucket = "CANNOT-FAIL"
        else:
            bucket = v                               # SKIPPED / NOT-RUN: say so, do not judge
        rows.append({"test": nid, "verdict": v, "bucket": bucket, "kills": kills})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=None, help="ref the new tests are measured against")
    ap.add_argument("--keep", action="store_true", help="keep the reverted copy")
    ap.add_argument("--json", default=None, help="write the per-test verdicts here")
    args = ap.parse_args(argv)
    base = args.base or default_base()
    base_sha = _git("rev-parse", "--short", base).stdout.strip()
    tests = new_tests(base)
    if not tests:
        print(f"guard_kill: no new tests since {base_sha}")
        return 0
    work = tempfile.mkdtemp(prefix="guard_kill_")
    try:
        reverted = build_reverted_copy(base, work)
        print(f"guard_kill: {len(tests)} new test(s) since {base_sha}; "
              f"{len(reverted)} non-test file(s) put back to {base_sha}; copy at {work}")
        verdicts = run_tests(work, [nid for nid, _ in tests])
        rows = classify(tests, verdicts, _catalogued_ids())
        for r in rows:
            extra = f" (via {','.join(r['kills'])})" if r["bucket"] == "CATALOGUED" else ""
            print(f"  {r['bucket']:<11} {r['verdict']:<8} {r['test']}{extra}")
        if not reverted:
            print("  note: no non-test change in range -- the revert was a no-op, so every "
                  "PASSED test above is one whose fix is not in this range")
        counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in
                  ("KILLS", "CATALOGUED", "CANNOT-FAIL", "SKIPPED", "NOT-RUN")}
        print("guard_kill: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({"base": base_sha, "reverted": reverted, "tests": rows}, f, indent=1)
        return 1 if counts["CANNOT-FAIL"] else 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
