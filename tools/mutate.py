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

**How a mutation is judged (2026-08-25).** The gate ran the WHOLE suite once per record --
108 records x 55 s on the runner -- and `tests.yml` cancelled it at 45 minutes on every push
from `f720627` on (docs/BACKLOG.md 170). Now:

  1. one BASELINE run of the unmutated archive learns which tests are red at HEAD; those
     are `--deselect`ed from every mutant run and can never count as a killer (a
     baseline-red test would otherwise make every mutation look KILLED);
  2. per record, the tests that can SEE the mutated module run first -- derived from the
     import graph (the module and everything that imports it, transitively) and from each
     test's own references (function-local imports, module-level aliases, module names in
     strings, helpers it calls), plus any `Kills \`<id>\`` docstring and an optional
     `killers` field on the record;
  3. a KILLED verdict that satisfies the record's rule ends there -- the full suite is a
     superset of the subset, so it would contain the same killer; otherwise (subset green,
     empty, or killed only by source-text guards) the FULL suite runs exactly as before.
     The verdict semantics are therefore unchanged; only the cost of the common case is;
  4. records run in parallel (`--jobs`, default min(4, cpus)); each mutant has its own
     `git archive HEAD` copy, so nothing is shared.

Usage:
    python tools/mutate.py --all              # every mutation in tests/mutations.json
    python tools/mutate.py --class M1,M2      # only those classes
    python tools/mutate.py --id crack-narrow  # one mutation
    python tools/mutate.py --coverage         # only the derived-coverage check
    python tools/mutate.py --all --catalogue tests/mutations.json --catalogue other.json
    python tools/mutate.py --id x --skip-baseline   # local iteration; killers unfiltered

Exit 0 iff every mutation was killed AND the coverage check passes. Read-only with respect to
the repo: each mutation is applied to a `git archive HEAD` copy under the system temp dir.

lane: `registry`.
"""
from __future__ import annotations

import argparse
import ast
import atexit
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE = os.path.join(ROOT, "tests", "mutations.json")
TESTS_DIR = os.path.join(ROOT, "tests")

# A test is STATIC if it reasons about source text, BEHAVIOURAL if it runs the code. The
# distinction is the whole point of `must_be_killed_by_behavioural`.
_STATIC_MARKERS = ("inspect.getsource", "ast.parse", "ast.walk")
_BEHAVIOURAL_MARKERS = ("tmp_path", "monkeypatch")

# Windows' CreateProcess limit is 32 KiB; past this the node ids of the largest file
# collapse to that whole file (still a subset -- test_registry.py alone is ~10 s).
_ARGV_CAP = 24_000

# Mutation classes, each seeded from a defect that actually shipped here.
CLASSES = {
    "M1": "gate-removal: the gate call is replaced by a constant, or its `if` deleted",
    "M2": "gate-inversion: truthiness inverted while the source token survives",
    "M3": "branch-narrowing: a guarded branch is made to cover fewer cases",
    "M4": "dead-conjunct: an always-false term appended so the guard never fires",
    "M5": "population-widening: a row selector is widened or removed",
    "M6": "fallback-removal: a rung is dropped from a search/resolution ladder",
    "M7": "constant-drift: a note length, throttle, budget or terminal token is changed",
    "M8": "argument-mis-passing: a gate's argument replaced, transposed or wrongly bound",
}

Baseline = namedtuple("Baseline", "red_ids red_names seconds summary")
_NO_BASELINE = Baseline(frozenset(), frozenset(), 0.0, "baseline skipped")


def shard(muts, spec):
    """The records shard `i` of `n` runs, for `spec` = "i/n" (0-based i, like the
    `mutation-gate` matrix; the registry's `QRS_SHARD` is 1-based -- say which you mean).

    By RECORD, not by class: `tests.yml` used to bin-pack the `M<n>` classes, and the
    fattest class (`M1-gate-removal`, 89 of 233 on 2026-08-30) is one class, so a fourth
    shard changed nothing while shard 0 was killed at its 40-minute budget on every push
    (BACKLOG 476). Sorted by id and strided, so the split is a function of the catalogue
    alone -- no list here to fall out of date -- and every record lands in exactly one
    shard (`test_the_mutation_shards_partition_the_whole_catalogue` proves that over the
    real catalogue). An EMPTY shard is refused by the caller: fewer records than shards
    means a matrix entry that goes green having run nothing."""
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", spec or "")
    if not m:
        raise ValueError("--shard wants I/N (0-based), got %r" % (spec,))
    i, n = int(m.group(1)), int(m.group(2))
    if n < 1 or not 0 <= i < n:
        raise ValueError("--shard %d/%d: I must be in 0..N-1 and N >= 1" % (i, n))
    ordered = sorted(muts, key=lambda r: r["id"])
    return ordered[i::n]


def _load(paths=None):
    """The catalogue(s). Several may be passed (`--catalogue`, docs/BACKLOG.md 104); the
    coverage check runs over their union."""
    out = []
    for p in (paths or [CATALOGUE]):
        with open(p, encoding="utf-8") as fh:
            out.extend(json.load(fh))
    return out


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
        # Strip the docstring before looking for markers. These tests EXPLAIN themselves,
        # and a docstring that says "was caught only by an inspect.getsource assertion"
        # made its own test classify as static -- so a behavioural guard was reported as a
        # source-text one purely for describing the bug it fixes.
        body = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)
        if any(k in body for k in _BEHAVIOURAL_MARKERS):
            return "behavioural"
        if any(k in body for k in _STATIC_MARKERS):
            return "static"
        return "direct"          # calls the predicate itself: real behaviour, no fixture
    return "unknown"


# --------------------------------------------------------------------------------------
# Test selection: which tests can SEE the mutated module. Over-approximation is harmless
# (a bigger subset); under-approximation costs one full-suite fallback, never a verdict.
# --------------------------------------------------------------------------------------

def _module_name(path, root=ROOT):
    """`pipeline/identity_gate.py` -> `pipeline.identity_gate`; `crack_walled.py` -> same."""
    rel = os.path.relpath(path, root).replace("\\", "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _known_modules(root=ROOT):
    mods = {}
    for p in glob.glob(os.path.join(root, "*.py")) + glob.glob(os.path.join(root, "pipeline", "*.py")):
        rel = os.path.relpath(p, root).replace("\\", "/")[:-3].replace("/", ".")
        if rel.endswith("__init__"):
            continue
        mods[rel] = p
    return mods


def _resolve_import(node, here, known):
    """The known modules an Import/ImportFrom node names (whole-file walk: imports in this
    repo are often function-local)."""
    out = set()
    if isinstance(node, ast.Import):
        for a in node.names:
            if a.name in known:
                out.add(a.name)
    elif isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:                       # `from . import x` inside pipeline/
            pkg = here.rsplit(".", 1)[0] if "." in here else ""
            base = (pkg + "." + base).strip(".") if base else pkg
        if base in known:
            out.add(base)
        for a in node.names:
            cand = (base + "." + a.name).strip(".")
            if cand in known:
                out.add(cand)
    return out


def _import_graph(root=ROOT):
    """module -> set(modules it imports), over root *.py and pipeline/*.py."""
    known = _known_modules(root)
    graph = {}
    for mod, path in known.items():
        deps = set()
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            graph[mod] = deps
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                deps |= _resolve_import(n, mod, known)
        graph[mod] = deps
    return graph


def _dependents(graph, module):
    """`module` plus everything that imports it, transitively (reverse closure)."""
    out = {module}
    changed = True
    while changed:
        changed = False
        for m, deps in graph.items():
            if m not in out and deps & out:
                out.add(m)
                changed = True
    return out


def _strip_docstring(fn):
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _test_refs(test_path, known):
    """{test_name: set(modules it references)} for one test file.

    A reference is: an import anywhere inside the function (or its decorators); a
    module-level alias (`IG = ...`, `from pipeline import verdicts`) whose name appears in
    the body; a string constant naming a module (`importlib.import_module("crack_walled")`,
    `subprocess.run([..., "crack_walled.py"])`); and, to a fixpoint, the refs of any
    module-level helper or fixture the test names. Docstrings are excluded (the same
    lesson as `_classify_killer`).
    """
    import warnings
    src = open(test_path, encoding="utf-8").read()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")              # a test's own `\(` escapes are not ours
        tree = ast.parse(src)
    aliases = {}                                     # bound name -> module
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in known:
                    aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            for a in n.names:
                cand = (base + "." + a.name).strip(".")
                if cand in known:
                    aliases[a.asname or a.name] = cand
                elif base in known:
                    aliases[a.asname or a.name] = base
    basenames = {m.split(".")[-1]: m for m in known}
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for n in tree.body:
        # pytest collects only `Test*` classes (python_classes); a helper class with a
        # `test_`-prefixed method would emit a node id pytest cannot resolve (wave-1 F3)
        if isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
            for f in n.body:
                if isinstance(f, ast.FunctionDef):
                    funcs[n.name + "::" + f.name] = f

    def direct(fn):
        refs, calls = set(), set()
        nodes = [x for b in _strip_docstring(fn) for x in ast.walk(b)]
        nodes += [x for d in fn.decorator_list for x in ast.walk(d)]
        for x in nodes:
            if isinstance(x, (ast.Import, ast.ImportFrom)):
                refs |= _resolve_import(x, "tests", known)
            elif isinstance(x, ast.Name):
                if x.id in aliases:
                    refs.add(aliases[x.id])
                if x.id in funcs:
                    calls.add(x.id)
            elif isinstance(x, ast.Constant) and isinstance(x.value, str):
                # `"crack_walled.py"`, `"pipeline.identity_gate"`, `"auto_expand"` -- but
                # not a bare English word that happens to be a module stem ("run",
                # "digest", "store"), which selected half the suite for every record
                s = x.value.strip()
                if s in known:
                    refs.add(s)
                elif s.endswith(".py") and s[:-3] in basenames:
                    refs.add(basenames[s[:-3]])
                elif "_" in s and s in basenames:
                    refs.add(basenames[s])
        for a in fn.args.args:                        # fixtures by argument name
            if a.arg in funcs:
                calls.add(a.arg)
        return refs, calls

    cache = {name: direct(fn) for name, fn in funcs.items()}
    out = {}
    for name, fn in funcs.items():
        refs, seen, todo = set(), set(), [name]
        while todo:
            cur = todo.pop()
            if cur in seen or cur not in cache:
                continue
            seen.add(cur)
            r, c = cache[cur]
            refs |= r
            todo.extend(c)
        out[name] = refs
    return {k: v for k, v in out.items()
            if k.startswith("test_") or "::test_" in k}


_KILLS_RX = re.compile(r"Kills\s+`([^`]+)`")


def _kills_map(tests_dir=TESTS_DIR):
    """{record id: set(node ids)} from `Kills \\`<id>\\`` docstring conventions."""
    out = {}
    for path in sorted(glob.glob(os.path.join(tests_dir, "test_*.py"))):
        rel = "tests/" + os.path.basename(path)
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
                doc = ast.get_docstring(n) or ""
                for mid in _KILLS_RX.findall(doc):
                    out.setdefault(mid, set()).add(rel + "::" + n.name)
    return out


_SELECTOR_CACHE = {}


def _selector_state(root, tests_dir):
    """(known, graph, {test file: refs}, kills map) -- derived once per (root, tests_dir):
    the derivation costs ~0.4 s and the sweep asks 100+ times."""
    key = (root, tests_dir)
    if key not in _SELECTOR_CACHE:
        known = _known_modules(root)
        refs = {}
        for path in sorted(glob.glob(os.path.join(tests_dir, "test_*.py"))):
            try:
                refs["tests/" + os.path.basename(path)] = _test_refs(path, known)
            except SyntaxError:
                continue
        _SELECTOR_CACHE[key] = (known, _import_graph(root), refs, _kills_map(tests_dir))
    return _SELECTOR_CACHE[key]


def _collectable_ids(work):
    """Every node id pytest could collect from `work/tests` -- the archive the mutant runs
    in, not the working tree the selector read (wave-1 F2: an uncommitted or renamed test
    in this shared checkout is a ghost id in the archive, and a ghost id is rc 4 with zero
    tests run)."""
    out = set()
    for path in glob.glob(os.path.join(work, "tests", "test_*.py")):
        rel = "tests/" + os.path.basename(path)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
                out.add(rel + "::" + n.name)
            elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
                out |= {rel + "::" + n.name + "::" + f.name for f in n.body
                        if isinstance(f, ast.FunctionDef) and f.name.startswith("test_")}
    return out


def select_tests(root, mut, tests_dir=None):
    """Node ids of the tests that can see `mut["file"]`, sorted; [] means no subset."""
    tests_dir = tests_dir or os.path.join(root, "tests")
    known, graph, refs, kills = _selector_state(root, tests_dir)
    deps = _dependents(graph, _module_name(os.path.join(root, mut["file"]), root))
    ids = set()
    for rel, per_test in refs.items():
        ids |= {rel + "::" + name for name, mods in per_test.items() if mods & deps}
    ids |= kills.get(mut["id"], set())
    ids |= set(mut.get("killers") or [])
    return sorted(ids)


# --------------------------------------------------------------------------------------
# Running pytest and reading its verdict
# --------------------------------------------------------------------------------------

def _pytest_argv(node_ids, deselect=()):
    ids = list(node_ids)
    # `no:warnings` is load-bearing, not tidiness. `_parse_failures` falls back to
    # `^<file>.py::<name>` when a run names no FAILED/ERROR line - i.e. on a GREEN run - and
    # on a green run the lines with that shape are the WARNINGS SUMMARY. The baseline read 49
    # of them as red and refused to start (`HEAD is not a suite to mutate against (rc=0, 49
    # red)`), 2026-08-28. The count tracks the size of the suite, not its health: 31 at
    # 21a8700, 48 one commit later, against a `> 40` refusal.
    base = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "no:warnings"]
    des = [x for d in deselect for x in ("--deselect", d)]

    def total(cur):
        return len(" ".join(base + cur + des))
    # collapse file by file (largest first) until the WHOLE argv -- deselects included
    # (wave-1 F6: they were appended after the check) -- fits the Windows limit
    while ids and total(ids) > _ARGV_CAP and any("::" in i for i in ids):
        by_file = {}
        for i in ids:
            by_file.setdefault(i.split("::")[0], []).append(i)
        expanded = {f: v for f, v in by_file.items() if any("::" in i for i in v)}
        biggest = max(expanded, key=lambda f: len(expanded[f]))
        ids = [biggest] + [i for f, v in by_file.items() if f != biggest for i in v]
    return base + ids + des


def _pytest(work, node_ids, deselect=()):
    # NO `-x`. "A static guard may never be the SOLE killer" is a claim about the whole set
    # of failing tests, and `-x` reports only the first one -- which is file/definition
    # order, not significance. Five mutations were reported as static-only kills purely
    # because a source-text guard happened to be defined above the behavioural fixture that
    # also caught them. The harness must not manufacture its own finding.
    # A mutant's pytest must not write the REAL run page. `pipeline/run.py` appends the
    # audit block to `$GITHUB_STEP_SUMMARY` whenever that variable is set, and this harness
    # runs the suite up to 200 times, so the summary reached 1,087 KB and Actions dropped it
    # whole: `$GITHUB_STEP_SUMMARY upload aborted, supports content up to a size of 1024k`.
    # The gate's own table was the thing lost (2026-08-27).
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    # A mutant's source is DELIBERATELY not HEAD's, so any test that asserts "the source
    # matches what is recorded about it" fires on every single mutation and reads as a
    # universal killer -- which would make this whole gate vacuous. Exactly one such test
    # exists (`test_no_mutation_record_goes_stale_unnoticed`, which checks that every
    # record's `find` still matches its file); it skips when it sees this.
    env["AJIL_MUTANT"] = "1"
    return subprocess.run(_pytest_argv(node_ids, deselect), cwd=work, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1800,
                          env=env)


def _parse_failures(out):
    """Full node ids (with `[param]`, spaces included) of every FAILED/ERROR line in a `-q`
    run. `ERROR: not found: x` (a ghost id, rc 4) is deliberately NOT a failure."""
    out = out or ""
    ids = re.findall(r"^(?:FAILED|ERROR) ([\w./\\-]+::.*?)(?: - .*)?$", out, re.M)
    if not ids and re.search(r"\b\d+ (?:failed|errors?)\b", out):
        # The fallback reads ANY `<file>.py::<name>` line, and it fires only when no
        # FAILED/ERROR line was found - which is precisely a GREEN run, where the lines with
        # that shape are pytest's WARNINGS SUMMARY. It was therefore systematically wrong
        # exactly where it fired: on 2026-08-28 the baseline read 49 warning lines as red
        # and refused to start, with `rc=0` in its own message. So it may run only when the
        # summary says something actually failed. It still covers what it was written for -
        # a red run that names no FAILED line - because such a run still says "N failed".
        ids = re.findall(r"^([\w./\\-]+\.py::\w+)", out, re.M)
    return [i.strip() for i in ids if "::" in i]


def _bare(node_id):
    return node_id.split("[")[0].replace("\\", "/")


UNSETTLED = ("UNSETTLED", "pytest did not run the tests", "")


def _verdict(returncode, out, baseline_red, work, must_beh):
    """None = this run is GREEN for the mutant (nothing but baseline-red tests failed);
    ("KILLED", kind, killer) / ("FAIL", detail, killer); or UNSETTLED when pytest did not
    actually judge the tests -- rc 2/3/4 (usage error, interrupted, a node id it could not
    resolve: `ERROR: not found`), or a red run whose failures it did not name. Wave-1 F1:
    that last shape used to read as a KILL with zero tests run, and it bypassed the
    behavioural rule. `baseline_red` holds FULL node ids: one red `[caseA]` retires that
    case only, never the whole parametrised test (F4)."""
    if returncode in (0, 5):
        return None
    if returncode not in (0, 1):
        return UNSETTLED
    fails = [f for f in _parse_failures(out) if f.replace("\\", "/") not in baseline_red]
    if not fails:
        if _parse_failures(out):
            return None                   # only baseline-red tests failed
        return UNSETTLED                  # rc 1 with no FAILED line: not a measurement
    killers = []
    for f in fails:
        b = _bare(f)
        if b not in killers:
            killers.append(b)
    kinds = {k: _classify_killer(work, k) for k in killers}
    real = [k for k, v in kinds.items() if v in ("behavioural", "direct")]
    if must_beh and not real:
        return ("FAIL", "killed ONLY by source-text guard(s): %s"
                % ", ".join(k.split("::")[-1] for k in killers[:3]), killers[0])
    best = real[0] if real else killers[0]
    return ("KILLED", kinds[best], best)


def _baseline(work_root):
    """One full run of the UNMUTATED archive: which tests are red at HEAD, and how long
    the whole suite takes here. Those tests are deselected from every mutant run and
    never count as a killer."""
    work = os.path.join(work_root, "_baseline")
    _archive(work)
    t = time.time()
    proc = _pytest(work, [])
    secs = time.time() - t
    if proc.returncode in (2, 3, 4):
        raise SystemExit("baseline pytest did not run cleanly (rc=%d):\n%s"
                         % (proc.returncode, (proc.stdout or "")[-2000:]))
    red = _parse_failures(proc.stdout)
    if proc.returncode not in (0, 1) or len(red) > 40:
        raise SystemExit("baseline: HEAD is not a suite to mutate against (rc=%d, %d red) --"
                         " fix the suite first; the deselect list has no shorter form"
                         % (proc.returncode, len(red)))
    # pytest.ini already carries `-q`, so our `-q` makes it `-qq`: no "N passed" line, only
    # the progress dots. Count those instead of parsing a summary that is not printed.
    prog = [ln for ln in (proc.stdout or "").splitlines() if re.match(r"^[.FsxXE]+\s+\[", ln)]
    dots = sum(ln.split()[0].count(".") for ln in prog)
    summary = "%d passed, %d failed" % (dots, len(red)) if prog else "?"
    return Baseline(frozenset(red), frozenset(_bare(r) for r in red), secs, summary)


def run_one(mut, work_root, baseline=_NO_BASELINE):
    """{'status','detail','killer','mode','subset','secs'} for one record."""
    t0 = time.time()
    work = os.path.join(work_root, mut["id"])
    _archive(work)
    target = os.path.join(work, mut["file"])
    src = open(target, encoding="utf-8").read()
    n = src.count(mut["find"])
    if n != 1:
        return {"status": "FAIL", "detail": "stale mutation: %d matches for `find`, re-aim it" % n,
                "killer": "", "mode": "-", "subset": 0, "secs": time.time() - t0}
    open(target, "w", encoding="utf-8").write(src.replace(mut["find"], mut["replace"], 1))
    must_beh = mut.get("must_be_killed_by_behavioural", True)
    deselect = sorted(baseline.red_ids)

    # 1. the subset that can see the mutated module -- only ids the ARCHIVE can collect
    #    (a `killers` typo or a test that exists only in the working tree is a ghost id:
    #    rc 4, zero tests run, and until wave-1 F1 that read as a kill). A KILLED here is
    #    final: the full suite is a superset and would contain the same killer. Anything
    #    else falls back.
    wanted = select_tests(ROOT, mut)
    ok_ids = _collectable_ids(work)
    ghosts = [i for i in mut.get("killers") or [] if i not in ok_ids]
    if ghosts:
        return {"status": "FAIL", "detail": "catalogue names test(s) the archive has not: %s"
                % ", ".join(ghosts)[:80], "killer": "", "mode": "-", "subset": 0,
                "secs": time.time() - t0}
    subset = [i for i in wanted if i in ok_ids]
    reason = "no-subset"
    if subset:
        v = _verdict(*_run(work, subset, deselect), baseline.red_ids, work, must_beh)
        if v and v[0] == "KILLED":
            return {"status": "KILLED", "detail": v[1], "killer": v[2],
                    "mode": "subset", "subset": len(subset), "secs": time.time() - t0}
        reason = "green" if v is None else ("unsettled" if v is UNSETTLED else "static-only")
    # 2. the whole suite, exactly as the gate always ran it
    v = _verdict(*_run(work, [], deselect), baseline.red_ids, work, must_beh)
    if v is UNSETTLED:
        return {"status": "FAIL", "detail": "pytest did not judge the full suite (rc 2/3/4 or "
                "an unnamed failure) -- harness or archive problem, not a verdict",
                "killer": "", "mode": "fallback:" + reason, "subset": len(subset),
                "secs": time.time() - t0}
    if v is None:
        return {"status": "FAIL", "detail": "SURVIVED — the suite is green with this mutation applied",
                "killer": "", "mode": "fallback:" + reason, "subset": len(subset),
                "secs": time.time() - t0}
    return {"status": v[0], "detail": v[1], "killer": v[2], "mode": "fallback:" + reason,
            "subset": len(subset), "secs": time.time() - t0}


def _run(work, node_ids, deselect):
    proc = _pytest(work, node_ids, deselect)
    return proc.returncode, proc.stdout or ""


# --------------------------------------------------------------------------------------
# Derived coverage: every activating writer's gate call site carries its mutations
# --------------------------------------------------------------------------------------

def _registry_writers():
    """Both write shapes, derived — the same detector tests/test_registry.py uses."""
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        hit = False
        for n in ast.walk(tree):
            if _row_write(n):
                hit = True
            elif isinstance(n, ast.List) and len(n.elts) >= 6:
                e = n.elts[4]
                if isinstance(e, ast.Constant) and e.value == "true":
                    hit = True
        if hit:
            out.append(os.path.basename(path))
    return out


def _row_write(n):
    """Does this statement write companies.csv column 3 (api_url) or ACTIVATE column 4?

    The one rule both detectors share (tests/test_registry.py imports this). Shapes:
    `fr[3] = x` / `fr[4] = "true"` (bare or tuple targets -- `apply_resolved.py:61` is
    `fields[1], fields[2], fields[3] = ...`); `fr[3] += x` and every other augmented
    assignment; a slice target `fr[3:4] = ...`; `fr.__setitem__(3, x)`. Exempt on purpose:
    `fr[4] = "false"` (a park needs no identity evidence) and `fr[3] = ""` (a clearing,
    not a proposal). Column 4 with ANY value other than those two constants counts
    (`fr[4] = flag` is an activation the reader cannot rule out -- wave-1 F7).
    """
    def col(tg):
        if isinstance(tg, ast.Subscript):
            if isinstance(tg.slice, ast.Slice):
                return "slice"
            if isinstance(tg.slice, ast.Constant) and tg.slice.value in (3, 4):
                return tg.slice.value
        return None
    if isinstance(n, ast.Assign):
        targets = []
        for tg in n.targets:
            targets.extend(tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg])
        for i, tg in enumerate(targets):
            c = col(tg)
            if c is None:
                continue
            if c == "slice":
                return True
            v = n.value
            if isinstance(v, (ast.Tuple, ast.List)) and len(v.elts) == len(targets):
                v = v.elts[i]
            if c == 3 and not (isinstance(v, ast.Constant) and v.value == ""):
                return True
            if c == 4 and not (isinstance(v, ast.Constant) and v.value == "false"):
                return True
        return False
    if isinstance(n, ast.AugAssign):
        return col(n.target) is not None
    if isinstance(n, ast.Call):
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr == "__setitem__" and n.args:
            a0 = n.args[0]
            return isinstance(a0, ast.Constant) and a0.value in (3, 4)
        if isinstance(f, ast.Attribute) and f.attr == "setitem" and len(n.args) >= 2:
            a1 = n.args[1]
            return isinstance(a1, ast.Constant) and a1.value in (3, 4)
    return False


def _gate_call_sites(path, gate_names=("activation_ok", "ok_to_write", "identity_ok")):
    """Every line that calls the identity gate, as its stripped source text.

    PER CALL SITE, not per file. `retry_unreachable` and `auto_expand` each call
    `activation_ok` TWICE -- once for an `ats` payload and once, three lines below, for a
    `scrape` one. A per-file rule counted the `ats` mutations and reported no gap, so the
    scrape gate had no mutation at all: deleting its `not` inverted the write in both
    directions (activating `Voiceitt`, parking `Pliops`) with 253 tests green.
    """
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    # The three ACTIVATION gates only. `page_names_company` and
    # `tenant_is_this_company` are the building blocks those are made of: they are
    # called in places that compute a verdict rather than gate a write (e.g. inside
    # `crack_walled.crack_one`), and they are covered by their own mutations against
    # `pipeline/identity_gate.py`. Requiring M1/M2/M3 at every internal call of them
    # would demand ~30 mutations for predicates that gate nothing.
    # `gate_names` is a parameter so tests/test_registry.py can derive identity_gate's
    # GATE_CALLERS with embedded_board_ok included; coverage() keeps the three-name default
    # (demanding M1/M2/M3 at every embedded_board_ok site would red the sweep for nothing).
    gate_names = set(gate_names)
    # ALIASES FIRST. `check = _gate.activation_ok` (or `from pipeline.identity_gate
    # import activation_ok as check`) then `if not check(...)` is a working gate whose
    # call line names no gate -- this detector saw nothing, so the site needed no
    # mutation, so a defeat there was invisible. The repo bans the import-as form for a
    # different reason (alias binding breaks monkeypatching), but a detector should not
    # depend on a style rule staying obeyed.
    aliases = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Attribute, ast.Name)):
            nm = getattr(n.value, "attr", None) or getattr(n.value, "id", None)
            if nm in gate_names:
                aliases.update({t.id: nm for t in n.targets if isinstance(t, ast.Name)})
        elif isinstance(n, ast.ImportFrom) and "identity_gate" in (n.module or ""):
            aliases.update({a.asname: a.name for a in n.names
                            if a.name in gate_names and a.asname})
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fname = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if fname in gate_names:
                out.add((lines[n.lineno - 1].strip(), fname))
            elif fname in aliases:
                # the RESOLVED gate name rides along: the M8 demand keys on it, and an
                # aliased call's source line does not contain the gate's name (wave-5 R2)
                out.add((lines[n.lineno - 1].strip(), aliases[fname]))
    return out


def coverage(muts):
    """Every gate CALL SITE in an activating writer must carry an M1, M2 and M3 mutation.

    Derived, not hand-listed: a new activating tool -- or a second gate call inside an
    existing one -- becomes a red build on the commit that adds it, instead of a review
    finding a wave later.
    """
    from collections import defaultdict
    per_site = defaultdict(set)
    for m in muts:
        per_site[(m["file"], m["find"].strip())].add(m["class"].split("-")[0])
    exempt = set(_load_exempt())
    gaps = []
    for w in _registry_writers():
        if w in exempt:
            continue
        sites = _gate_call_sites(os.path.join(ROOT, w))
        if not sites:
            # This tool gates with a composite of the building blocks rather than one of the
            # three named activation gates (`deep_validate`'s tenant-or-page expression,
            # `repair_dead_urls`' `names_us`). Fall back to the per-FILE rule for those.
            classes = set()
            for (f, _find), cls in per_site.items():
                if f == w:
                    classes |= cls
            missing = {"M1", "M2", "M3"} - classes
            if missing:
                gaps.append((w, sorted(missing)))
            continue
        for site, callee in sorted(sites):
            classes = set()
            for (f, find), cls in per_site.items():
                if f == w and site in find:
                    classes |= cls
            # M8 (argument mutation) is demanded at activation_ok sites since wave-4 R2:
            # M1/M2/M3 mutate a call's PRESENCE and POLARITY, and a catalogue satisfying
            # only those never asks whether the ARGUMENTS are right -- the dead-platform
            # transposition and the truthy-constant count both lived in that gap. Scoped
            # to activation_ok because its sites carry the row-building payloads;
            # ok_to_write/identity_ok take (name, url) already covered by their own
            # gate-level records.
            need = {"M1", "M2", "M3"} | ({"M8"} if callee == "activation_ok" else set())
            missing = need - classes
            if missing:
                gaps.append(("%s  [%s]" % (w, site[:52]), sorted(missing)))
    return gaps


def _load_exempt():
    """Writers whose col-3/4 write is not a proposal, or that no workflow runs.

    THE SAME FILE `tests/test_registry.py` loads -- its allow-list test asserts none of the
    unscheduled entries has become scheduled, and this driver exempts exactly that set from
    mutation coverage. The first version regexed the TEST FILE's source for `"<x>.py": "`,
    which matched any dict with .py keys anywhere in 2,500 lines of tests -- an unrelated
    test table could silently widen this exemption.
    """
    with open(os.path.join(ROOT, "tests", "writer_allowlist.json"), encoding="utf-8") as f:
        d = json.load(f)
    return list(d["restore_only"]) + list(d["legacy_unscheduled"])


# --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--id", default="")
    ap.add_argument("--cls", "--class", dest="cls", default="")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--catalogue", action="append", default=None,
                    help="catalogue file(s); default tests/mutations.json")
    ap.add_argument("--shard", default="",
                    help="I/N (0-based): run only every N-th record from the I-th, by id; "
                         "applied after --all/--class")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--skip-baseline", action="store_true",
                    help="local iteration only: no baseline run, no red-test filtering")
    a = ap.parse_args()

    muts = _load(a.catalogue)
    ids = [m["id"] for m in muts]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        print("** FAIL ** duplicate mutation id(s): %s" % ", ".join(dupes))
        return 1
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
    if a.shard:
        try:
            muts = shard(muts, a.shard)
        except ValueError as e:
            ap.error(str(e))
        if not muts:
            print("** FAIL ** shard %s selected no records -- fewer records than shards, so "
                  "this matrix entry would go green having run nothing; lower SHARDS" % a.shard)
            return 1
        print("shard %s: %d record(s), %s .. %s" % (a.shard.strip(), len(muts),
                                                    muts[0]["id"], muts[-1]["id"]))

    # Per-PROCESS, and cleaned up on the way out. The path was a fixed `ajil_mutants` that
    # every run `rmtree`d at startup, so two concurrent runs deleted each other's mutant
    # copies mid-test: one died with `NotADirectoryError: [WinError 267]` and another
    # reported a SURVIVED that a serial re-run showed was `killed`. A mutation gate that
    # reports the wrong verdict under load is worse than one that is slow -- and running
    # two at once is exactly what a reviewer does (2026-08-27).
    work_root = tempfile.mkdtemp(prefix=f"ajil_mutants_{os.getpid()}_")
    atexit.register(shutil.rmtree, work_root, True)
    t_all = time.time()

    baseline = _NO_BASELINE
    if a.skip_baseline:
        print("WARNING: --skip-baseline: killers are UNFILTERED -- with even one test red at "
              "HEAD every mutation reads as killed by it. Local iteration only.")
    if not a.skip_baseline:
        baseline = _baseline(work_root)
        print("baseline  %s in %.0f s; %d red at HEAD (excluded from every verdict)%s"
              % (baseline.summary, baseline.seconds, len(baseline.red_ids),
                 ":" if baseline.red_ids else ""))
        for r in sorted(baseline.red_ids):
            print("          " + r)
            if os.environ.get("GITHUB_ACTIONS"):
                print("::warning::mutation gate: %s is red at HEAD and cannot count as a killer" % r)

    print("%-30s %-22s %-11s %-42s %-16s %s" % ("id", "class", "result", "killed by", "mode", "secs"))
    print("-" * 124)
    jobs = max(1, a.jobs)
    bad = 0
    results = []
    # Each row is printed the moment its verdict is in (catalogue order, so a slow record
    # holds the rows behind it, never the rows before it). `list(ex.map(...))` used to
    # collect every verdict first, so a shard killed at its budget left NOTHING on the run
    # page -- "the per-record lines above say how far it got" was false on the one path it
    # was written for (2026-08-30, run 33320619890: 40 minutes, no line). Flushed, because
    # a runner's stdout is a pipe and the kill drops the buffer.
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for m, r in zip(muts, ex.map(lambda m: run_one(m, work_root, baseline), muts)):
            results.append(r)
            mode = "%s%s" % (r["mode"], " %d" % r["subset"] if r["subset"] else "")
            if r["status"] == "FAIL":
                bad += 1
                print("%-30s %-22s %-11s %-42s %-16s %.0f" % (
                    m["id"], m["class"], "** FAIL **", r["detail"][:42], mode, r["secs"]),
                    flush=True)
            else:
                print("%-30s %-22s %-11s %-42s %-16s %.0f" % (
                    m["id"], m["class"], "killed",
                    "%s (%s)" % (r["killer"].split("::")[-1][:30], r["detail"]), mode, r["secs"]),
                    flush=True)
    for w, missing in gaps:
        bad += 1
        print("%-30s %-22s %-11s missing %s" % (w, "coverage", "** FAIL **", ",".join(missing)))

    print("-" * 124)
    sizes = sorted(r["subset"] for r in results) or [0]
    fb = [r["mode"] for r in results if r["mode"].startswith("fallback")]
    from collections import Counter
    fbc = Counter(x.split(":", 1)[1] for x in fb)
    print("selection %d records; subset size min/median/max %d/%d/%d; %d full-suite fallback(s)%s"
          % (len(results), sizes[0], sizes[len(sizes) // 2], sizes[-1], len(fb),
             (" (" + ", ".join("%s %d" % kv for kv in sorted(fbc.items())) + ")") if fb else ""))
    slow = max(results, key=lambda r: r["secs"], default=None)
    wall = time.time() - t_all
    print("timing    wall %.0f s with %d worker(s); pytest time %.0f s; slowest %s %.0f s (%s)"
          % (wall, jobs, sum(r["secs"] for r in results),
             muts[results.index(slow)]["id"] if slow else "-", slow["secs"] if slow else 0,
             slow["mode"] if slow else "-"))
    # The rule "past ~1,800 s add a matrix entry, never the budget" (195/476) lived only in a
    # workflow comment and a morning-check row, so it was noticed a fortnight late: all five
    # shards had been over for days and two were being killed at 40 min. A shard that is over
    # now says so on its own run page, while it is still green.
    warn_at = float(os.environ.get("MUTATE_WALL_WARN", "1800"))
    if warn_at > 0 and wall > warn_at:
        print("::warning::mutation shard walled %.0f s, past the %.0f s ceiling -- add a "
              "matrix entry AND bump SHARDS in .github/workflows/tests.yml, never the budget "
              "(BACKLOG 195/476)" % (wall, warn_at), flush=True)
    print("%d mutation(s): %d killed, %d SURVIVING/failed; %d coverage gap(s)"
          % (len(muts), len(muts) - (bad - len(gaps)), bad - len(gaps), len(gaps)))
    if bad:
        print("\nA surviving mutation means the gate it targets is not actually guarded.")
    shutil.rmtree(work_root, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
