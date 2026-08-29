#!/usr/bin/env python3
"""Make the documentation a build artifact that can go red.

The failure this repo punishes hardest is a confident document that is no longer true:
the root SCHEDULING.md told readers the daily email was unbuilt for three days after it
started shipping, and HANDOFF.md listed two modules a scheduled workflow imports as "safe
to delete". Nothing caught either, because prose has no test.

This is that test. It cannot prove a sentence is TRUE - only that the things a sentence
points at still exist and still agree with the code:

  1. every file path a doc names exists (or is on the deliberately-absent list below)
  2. every relative markdown link, same-file anchor and `ARCHITECTURE.md` section
     reference resolves
  3. every root `*.py` is classified exactly once in `docs/MODULES.md`, and the class
     agrees with the import graph (scheduled => a workflow runs it; library => something
     imports it; legacy => nothing live imports it)
  4. the schedule table in `ARCHITECTURE.md` section 4 matches the real crons, both ways
  5. the `continue-on-error` count the docs quote matches the workflows
  6. `HANDOFF.md` is still current-state-sized and still has its required sections

Each check was verified by breaking the thing it guards and watching it fail.

Run it: `python docs/check_docs.py`  (exit 1 on any error, 0 with warnings)
It also runs in `tests/test_units.py::test_docs_are_consistent_with_the_code`, so
`tests.yml` enforces it on every push.

Owned by the `docs` lane. Adding a check is cheap; adding one that is right 95% of the
time is not - a linter that cries wolf gets `# noqa`'d and then ignored.
"""
from __future__ import annotations

import ast
import collections
import glob
import os
import re
import sys

sys.dont_write_bytecode = True   # loading docs/backlog.py by path left a .pyc behind
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Docs that are prose we own. docs/index.html and archive.html are BUILD OUTPUT (the
# published board) and are not documentation - never lint them.
LIVE_DOC_GLOBS = ["README.md", "ARCHITECTURE.md", "HANDOFF.md", "CLAUDE.md", "docs/*.md"]
# Archives are frozen history: a session write-up may name a file that has since been
# deleted, and a superseded decision record may name a file that was never written. Their
# LINKS are still checked - a dead link is a navigation bug at any age - but their paths
# are not, because the alternative is editing history every time a file is removed.
ARCHIVE_DOC_GLOBS = ["docs/sessions/*.md", "docs/decisions/*.md"]
DOC_GLOBS = LIVE_DOC_GLOBS + ARCHIVE_DOC_GLOBS

# Paths a doc may legitimately name even though they are not in the tree. Each needs a
# reason: either it is generated/gitignored, or it is a proposal the backlog is asking for.
ABSENT_OK = {
    # gitignored or generated at runtime
    "secrets.env": "gitignored; local credentials",
    "CLAUDE.local.md": "gitignored; the identity rules for the public repos",
    "state/seen.db": "gitignored local store",
    "state/firmographics.json": "gitignored local export",
    "state/firmo_chain.log": "gitignored log",
    "digests/latest.html": "produced by the digest run",
    "cloud_state/registry_ladder.json": "produced by listing-hunt.yml (registry_health --ladder)",
    "run_daily.ps1": "present, but only referenced historically",
    # proposals, named on purpose so the backlog stays greppable
    "pipeline/ats.py": "docs/BACKLOG.md consolidation item 1",
    "pipeline/dates.py": "docs/BACKLOG.md consolidation item 3",
    "pipeline/jdtext.py": "docs/BACKLOG.md consolidation item 4",
    "metrics.jsonl": "docs/BACKLOG.md consolidation item 5",
    "israeli-jobs-private-notes/Set-Claude-Token.cmd": "lives outside this repo",
    "Set-BrightData-Key.cmd": "a Desktop launcher, outside this repo (docs/BRIGHTDATA.md)",
    "digest-email.yml": "lives in the private AnalystJobsIL/inbox repo, not this one",
    # retired 2026-08-26 (`registry`, 8a4deac): the Saturday cron became the Sunday audit's deep
    # rung; BACKLOG line 494 names the old file on purpose (BACKLOG 215)
    "deep-validate.yml": "retired workflow, named historically by docs/BACKLOG.md",
}

# Path-shaped tokens inside backticks. Deliberately narrow: extensions we actually use.
PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|json|jsonl|yml|yaml|csv|db|cmd|ps1|env|log|html))`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(check: str, msg: str) -> None:
    ERRORS.append("[%s] %s" % (check, msg))


def warn(check: str, msg: str) -> None:
    WARNINGS.append("[%s] %s" % (check, msg))


def docs(globs: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for g in (globs or DOC_GLOBS):
        out.extend(sorted(glob.glob(os.path.join(ROOT, g))))
    return out


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT).replace("\\", "/")


def read(p: str) -> str:
    return open(p, encoding="utf-8").read()


_BASENAMES: set[str] = set()
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "out", "node_modules", ".venv",
              ".claude"}   # agent worktrees hold stale copies of deleted files (BACKLOG 215)


def _basenames() -> set[str]:
    """Every filename in the tree, so a doc may say `fetchers.py` or `tests.yml`."""
    if not _BASENAMES:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            _BASENAMES.update(filenames)
    return _BASENAMES


# ---------------------------------------------------------------- 1. paths exist
def check_paths_exist() -> None:
    for doc in docs(LIVE_DOC_GLOBS):
        text = read(doc)
        for m in PATH_RE.finditer(text):
            path = m.group(1)
            if path.startswith(("http", "/", "~")) or path in ABSENT_OK:
                continue
            # A bare filename with no directory: accept it anywhere in the tree, because
            # docs say "fetchers.py" for "pipeline/fetchers.py" all the time.
            if "/" not in path:
                if path in _basenames():
                    continue
            elif os.path.exists(os.path.join(ROOT, path)):
                continue
            if any(path.startswith(p) for p in ("out/", "state/", "/tmp")):
                continue
            err("paths", "%s names `%s`, which does not exist "
                        "(add it to ABSENT_OK with a reason if that is deliberate)" % (rel(doc), path))


# ---------------------------------------------------------------- 2. links resolve
def check_links() -> None:
    for doc in docs():
        text = read(doc)
        anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                   for h in re.findall(r"^#{1,6} +(.+?)\s*$", text, re.M)}
        for m in LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                if target[1:] not in anchors:
                    warn("links", "%s links to anchor %s, which is not a heading in it" % (rel(doc), target))
                continue
            base = target.split("#", 1)[0]
            if not base:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(doc), base))
            if not os.path.exists(resolved) and base not in ABSENT_OK:
                err("links", "%s links to %s, which does not exist" % (rel(doc), target))


# ---------------------------------------------------------------- 2b. section references
SECTION_REF = re.compile(r"§\s?(\d+[a-z]?)")
# "was HANDOFF.md section 4d", "HANDOFF section 4d item 5", "HANDOFF.md section 4c/section 4d":
# a section number attributed to another document is provenance, not navigation.
OTHER_DOC = re.compile(
    r"(HANDOFF|README|CLAUDE|BACKLOG|MODULES|TAGGING|AGENT_BRIEF|BRIGHTDATA)"
    r"(\.md)?`?\s*(§\s?\d+[a-z]?\s*[/,and ]*)*$")


def check_section_refs() -> None:
    """ARCHITECTURE.md is the only document that numbers its sections, and every other doc
    cites those numbers. Sections get renumbered - this session moved three of them - and a
    dangling pointer sends a reader to the wrong rule, which is worse than sending them
    nowhere. Numbers attributed to another document are left alone."""
    have = set(re.findall(r"^#{2,3} (\d+[a-z]?)\.", read(os.path.join(ROOT, "ARCHITECTURE.md")), re.M))
    for doc in docs():
        text = read(doc)
        for m in SECTION_REF.finditer(text):
            if OTHER_DOC.search(text[max(0, m.start() - 40):m.start()]):
                continue
            if m.group(1) not in have:
                err("sections", "%s cites ARCHITECTURE.md section %s, which does not exist "
                                "(it has %s)" % (rel(doc), m.group(1), ", ".join(sorted(have))))


# ---------------------------------------------------------------- 3. module registry
def import_graph() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    roots = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py")))
    names = {os.path.splitext(f)[0] for f in roots}
    importers: dict[str, set[str]] = collections.defaultdict(set)
    for f in [os.path.join(ROOT, r) for r in roots] + \
             glob.glob(os.path.join(ROOT, "pipeline", "*.py")) + \
             glob.glob(os.path.join(ROOT, "tests", "*.py")):
        try:
            tree = ast.parse(read(f))
        except Exception:
            continue
        for n in ast.walk(tree):
            mod = None
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] in names:
                        importers[a.name.split(".")[0]].add(rel(f))
                continue
            if isinstance(n, ast.ImportFrom) and n.module:
                mod = n.module.split(".")[0]
            if mod in names:
                importers[mod].add(rel(f))
    runners: dict[str, set[str]] = collections.defaultdict(set)
    for w in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        # Strip `#` comments first. A workflow line reading "dropped the nightly
        # `python bd_employees.py` step; it is hand-run now" used to prove the opposite of
        # what it says, and the linter's suggested fix made MODULES.md claim a cron runs a
        # module nothing runs.
        txt = re.sub(r"(?m)#.*$", "", read(w))
        for m in names:
            mod = re.escape(m)
            # `python x.py`, `python -u x.py`, `python -X faulthandler x.py`, `./x.py`,
            # `python -m x`. The first version matched only the first two forms, so the
            # `operator`-a-workflow-runs arm - added specifically to catch firmographics.yml
            # - was a NO-OP for three spellings, and `python -m` is idiomatic in this repo
            # (daily-digest.yml runs `python -m pipeline.stages` and `python -m pipeline.run`).
            pat = (r"(?:^|[\s;&|(])(?:python3?|py)\b(?:\s+(?!\S*\.py\b)\S+)*\s+"
                   r"(?:[^\s;|&]*/)?" + mod + r"\.py\b"
                   r"|(?:^|[\s;&|(])(?:python3?|py)\b(?:\s+(?!\S*\.py\b)\S+)*?"
                   r"\s+-m\s+" + mod + r"\b")
            if re.search(pat, txt):
                runners[m].add(os.path.basename(w)[:-4])
    return importers, runners


def check_module_registry() -> None:
    path = os.path.join(ROOT, "docs", "MODULES.md")
    if not os.path.exists(path):
        err("modules", "docs/MODULES.md is missing - every root module must be classified")
        return
    text = read(path)
    # Section heading -> class. The headings are prose; the first word is the class.
    klass_of: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        h = re.match(r"^## (\w+)", line)
        if h:
            word = h.group(1).lower()
            current = word if word in ("scheduled", "libraries", "operator", "legacy") else None
            if current == "libraries":
                current = "library"
        cell = re.match(r"^\| `([A-Za-z0-9_]+)\.py` \|", line)
        if cell and current:
            name = cell.group(1)
            if name in klass_of:
                err("modules", "`%s.py` is listed twice in docs/MODULES.md" % name)
            klass_of[name] = current

    roots = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "*.py"))}
    for missing in sorted(roots - set(klass_of)):
        err("modules", "`%s.py` is not classified in docs/MODULES.md - add a row under the "
                       "class that fits (scheduled / libraries / operator / legacy)" % missing)
    for gone in sorted(set(klass_of) - roots):
        err("modules", "docs/MODULES.md lists `%s.py`, which no longer exists" % gone)

    # The bijection above is root-*.py only, so pipeline/ drift was unlinted: on
    # 2026-08-27 pipeline/roles.py - the `roles` lane's whole subject and the artifact
    # ARCHITECTURE.md section 7c is about - appeared in neither docs/MODULES.md nor the
    # lane table, because gen_modules.py skips a key it does not have.
    listed = set(re.findall(r"^\| `pipeline/([A-Za-z0-9_]+)\.py` \|", text, re.M))
    on_disk = {os.path.splitext(os.path.basename(f))[0]
               for f in glob.glob(os.path.join(ROOT, "pipeline", "*.py"))} - {"__init__"}
    for missing in sorted(on_disk - listed):
        err("modules", "`pipeline/%s.py` is not in docs/MODULES.md - add it to the PIPELINE "
                       "dict in docs/gen_modules.py and regenerate" % missing)
    for gone in sorted(listed - on_disk):
        err("modules", "docs/MODULES.md lists `pipeline/%s.py`, which no longer exists" % gone)

    importers, runners = import_graph()
    live = {m for m, k in klass_of.items() if k in ("scheduled", "library", "operator")}
    for m, k in sorted(klass_of.items()):
        if m not in roots:
            continue
        if k == "scheduled" and not runners.get(m):
            err("modules", "`%s.py` is classified `scheduled` but no workflow runs it" % m)
        if k == "library" and not importers.get(m):
            err("modules", "`%s.py` is classified `library` but nothing imports it" % m)
        if k == "operator" and runners.get(m):
            # The blind spot that hid a whole workflow: firmographics.yml landed on
            # 2026-08-26 running research_firmographics, firmo_death_watch and
            # company_type_analysis, and all three stayed filed as `operator` - "a human
            # runs this" - while a cron ran them daily. The three other classes were
            # checked in both directions and this one in neither.
            err("modules", "`%s.py` is classified `operator` (nothing in CI runs it) but %s "
                           "runs it. A module a cron runs is `scheduled`: fix the class in "
                           "docs/gen_modules.py and regenerate."
                % (m, ", ".join(sorted(runners[m]))))
        if k == "legacy":
            live_importers = sorted(i for i in importers.get(m, set())
                                    if os.path.splitext(os.path.basename(i))[0] in live
                                    or i.startswith("pipeline/"))
            if live_importers:
                err("modules", "`%s.py` is classified `legacy` but live code imports it: %s"
                    % (m, ", ".join(live_importers)))
            if runners.get(m):
                err("modules", "`%s.py` is classified `legacy` but %s runs it"
                    % (m, ", ".join(sorted(runners[m]))))


# ---------------------------------------------------------------- 4. the cron table
def check_schedule_table() -> None:
    real: dict[str, set[str]] = collections.defaultdict(set)
    for w in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        name = os.path.basename(w)[:-4]
        for m in re.finditer(r'^\s*-\s*cron:\s*["\']([^"\']+)["\']', read(w), re.M):
            real[name].add(" ".join(m.group(1).split()))

    arch = read(os.path.join(ROOT, "ARCHITECTURE.md"))
    section = re.search(r"^## 4\. Schedules.*?(?=^## 5\.)", arch, re.M | re.S)
    if not section:
        err("schedule", "ARCHITECTURE.md has no section 4 schedule table to check")
        return
    documented: dict[str, set[str]] = collections.defaultdict(set)
    for line in section.group(0).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) < 2:
            continue
        cron = re.match(r"^`([^`]+)`$", cells[0])
        if cron:
            documented[cells[1].split()[0]].add(" ".join(cron.group(1).split()))

    for wf, crons in sorted(real.items()):
        for c in sorted(crons):
            if c not in documented.get(wf, set()):
                err("schedule", "`%s.yml` runs on cron `%s`, which ARCHITECTURE.md section 4 "
                                "does not list for it (it lists %s)"
                    % (wf, c, sorted(documented.get(wf, set())) or "nothing"))
    for wf, crons in sorted(documented.items()):
        for c in sorted(crons):
            if c not in real.get(wf, set()):
                err("schedule", "ARCHITECTURE.md section 4 says `%s` runs on `%s`, but no such "
                                "cron is in .github/workflows/" % (wf, c))


# ---------------------------------------------------------------- 5. derived facts
# The generalisation of what used to be `check_continue_on_error` - the one check in this
# file that has never once been wrong. Commit 8f049f2 ("Make the docs a build artifact that
# can go red") introduced BOTH that check AND the sentences "846 companies" and "433
# through a native ATS API". Four days later the machine-checked number was still exactly
# right and every hand-typed one was stale. So: register the numbers, not the prose.
#
# Two classes, and the dividing line is WHO MOVES THE NUMBER:
#
#   EXACT   moves only when an agent commits a code change (len(FETCHERS), the module
#           count, the continue-on-error ratio). The person who can fix it is the person
#           pushing, so equality is the right contract and red is the right colour.
#
#   CENSUS  moves because eight cron jobs ran (active rows, registry rows). No session
#           causes the move, so equality punishes the innocent - and so does a two-sided
#           band, which is the same mistake with a wider mouth. A census site carries a
#           FLOOR and goes red only when the number COLLAPSES through it. The grammar and
#           the measurements behind it are above `_CENSUS`.
#
# Sites are an EXPLICIT per-fact file list, never `docs()`. The old check iterated
# DOC_GLOBS, which includes docs/sessions/ and docs/decisions/ - files this module declares
# frozen twenty lines above. The first session write-up to record "36 of the 80 workflow
# steps" would have made the check permanently red, fixable only by editing history.
#
# Patterns MUST bind a noun. ARCHITECTURE.md contains "a 1,200-job deletion"; a bare
# `~?1,200` would read it as a claim about the registry. And a DATED measurement in another
# lane's section ("435 API rows on 2026-08-26 (evening)") is a record, not a claim about
# today - it is deliberately not registered here, and must not be.

Fact = collections.namedtuple("Fact", "name kind compute unit sites why")


def _csv_rows() -> list[list[str]]:
    """companies.csv data rows. check_invariants.py prints one more than this: it counts
    the header. Both numbers are correct and they will keep looking like a discrepancy."""
    import csv as _csv
    with open(os.path.join(ROOT, "companies.csv"), encoding="utf-8", newline="") as fh:
        rows = [r for r in _csv.reader(fh) if r]
    return rows[1:]


def _active() -> list[list[str]]:
    return [r for r in _csv_rows() if len(r) > 4 and r[4] == "true"]


def _fetcher_keys() -> list[str]:
    """FETCHERS keys by AST, never by import: importing from a linter is a side effect
    waiting to happen, and several modules in this repo execute on import.

    Every non-literal form RAISES, and that is the whole point of this function. The first
    version filtered `isinstance(k, ast.Constant)` and silently returned a SHORT list for
    `{**_WALLED, "comeet": f}` (a `**` splat yields the key `None`), for a post-hoc
    `FETCHERS["b"] = f`, for `FETCHERS.update(...)`, for a variable key, and for a build
    loop - five of seven realistic forms. Silent is the bad half: the linter would then
    report the docs as wrong and the author, doing what it said, would write a false number
    into four documents and get a green build. An exception is `facts/uncomputable`, which
    is loud and correct."""
    tree = ast.parse(read(os.path.join(ROOT, "pipeline", "fetchers.py")))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "FETCHERS" for t in node.targets):
            if not isinstance(node.value, ast.Dict):
                raise RuntimeError("FETCHERS is not a dict literal (%s)"
                                   % type(node.value).__name__)
            if any(k is None or not isinstance(k, ast.Constant) for k in node.value.keys):
                raise RuntimeError("FETCHERS is not a PURE literal: it has a ** splat or a "
                                   "computed key, so its size cannot be read statically")
            keys = [k.value for k in node.value.keys]
            break
    else:
        raise RuntimeError("pipeline/fetchers.py has no top-level FETCHERS dict literal")
    src = read(os.path.join(ROOT, "pipeline", "fetchers.py"))
    if re.search(r"^\s*FETCHERS\s*\[|^\s*FETCHERS\.(update|setdefault|pop)\b", src, re.M):
        raise RuntimeError("FETCHERS is mutated after the literal, so the literal is not "
                           "the whole map")
    return keys


def _real_platforms() -> int:
    return len([k for k in _fetcher_keys() if k not in ("scrape", "discovery")])


def _has_main_guard(src: str) -> bool:
    """A real `if __name__ == "__main__":` at module level, parsed - not the substring.

    The substring test dropped `merge_research.py` (the canonical import-runs-it module,
    named by that very sentence) out of the list the moment somebody added a COMMENT
    warning that it has no guard. `gen_modules.py` uses the same helper, because if the two
    disagree the fact goes permanently red."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True                      # unparseable: never claim it is a trap
    for node in tree.body:
        if isinstance(node, ast.If):
            d = ast.dump(node.test)
            if "'__main__'" in d and "'__name__'" in d:
                return True
    return False


def _no_main_guard() -> int:
    return sum(1 for p in sorted(glob.glob(os.path.join(ROOT, "*.py")))
               if not _has_main_guard(read(p)))


def _unreferenced_roots() -> int:
    importers, runners = import_graph()
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        m = os.path.splitext(os.path.basename(p))[0]
        if not runners.get(m) and not importers.get(m):
            n += 1
    return n


def _coe_ratio() -> tuple:
    steps = coe = 0
    for w in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        txt = read(w)
        steps += len(re.findall(r"^\s*- name:", txt, re.M))
        coe += len(re.findall(r"^\s*continue-on-error:\s*true", txt, re.M))
    return coe, steps


# The one shape a census claim may take is a FLOOR. Four readings, one of them legal:
#   `800+`            FLOOR   - true iff today is at least 800. Growth cannot break it.
#   `875`             BARE    - an error; it will be wrong within a day.
#   `~900`            BRACKET - an error as of 2026-08-28: a band with soft edges.
#   `850-950`         RANGE   - an error as of 2026-08-28: a band with hard ones.
#
# Why one-sided, and why the two-sided forms are REFUSED rather than merely discouraged.
# A census number moves because the crons ran. Held to a band it fails when the project is
# WORKING, and worst exactly when growth is fastest: active rows went 873 -> 969 in the 14
# hours to 2026-08-28T07:08Z and blew a `~900` bracket written two days earlier. It turns
# `pytest` red - and `Registry invariants` and the fourteen rehearsed nights are steps
# BELOW `Unit guards` in the same `tests.yml` job, so a failure there SKIPS them (verified
# on runs 33115068319..33119862389, seven pushes on 2026-08-27, both `skipped` in each).
# A stale number in a README can switch off the registry gate.
#
# Widening the band was the rejected option, and this is the argument: at +96 rows in 14
# hours - 42 of them in 73 minutes, `0c69eaa` 20:26Z to `d76fb10` 21:39Z - any band narrow
# enough to mean something is a scheduled false alarm, and a band
# wide enough never to fire checks nothing. Widening is the move that deletes the alarm
# while looking like maintenance, and leaving the two-sided forms legal leaves it available.
#
# The signal worth keeping is the other direction. 969 -> 400 is a bad merge or a mass
# deactivation - section 8's mass-zero class - and a floor is exactly the check for it.
# Measured over all 111 commits that ever touched companies.csv: the largest legitimate
# FALL on record is 900 -> 846 on 2026-08-23, -6.0% inside ONE hour (`8644d8f` 05:44Z ->
# `c832a2a` 06:44Z); the largest single-commit rise is +140. A floor with more headroom
# than 6% catches the emergency and nothing that
# has ever happened normally.
#
# The lookaround is load-bearing: without it `the 2026-08-27 company profiles pass`
# captured `08-27` as the range 8-27, and `registry of 2026-08 rows` as a 2,000-wide
# bracket that would pass anything. `+` is inside the token and excluded from the trailing
# lookahead, so `800+` reads as one claim. The two-sided alternatives stay INSIDE the token
# on purpose: it must still CAPTURE `~900` so the checker can name the form it saw, instead
# of reporting the far more confusing "this site matches nothing any more".
_CENSUS = r"(?<![\d,\+\-–])(~?\d[\d,]*(?:[-–]\d[\d,]*)?\+?)(?![\d\-–+])"

FACTS = [
    Fact("coe_ratio", "exact", _coe_ratio, "continue-on-error of workflow steps",
         [("CLAUDE.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+(?:named\s+)?workflow steps"),
          ("ARCHITECTURE.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+(?:named\s+)?workflow steps"),
          ("docs/AGENT_BRIEF.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+(?:named\s+)?workflow steps")],
         "this is the number that tells a reader a green run proves nothing"),

    Fact("fetcher_platforms", "exact", lambda: (_real_platforms(),),
         "real ATS platforms in FETCHERS",
         [("ARCHITECTURE.md", r"pipeline/fetchers\.py\s+(\d+) platforms"),
          ("docs/AGENT_BRIEF.md", r"native ATS APIs\s+\((\d+) platforms\)"),
          ("docs/MODULES.md", r"the common job shape\. (\d+) platforms")],
         "an agent adding a platform must move this number in the same commit"),

    Fact("fetcher_map", "exact", lambda: (len(_fetcher_keys()), _real_platforms()),
         "FETCHERS keys and real platforms",
         [("ARCHITECTURE.md", r"\*\*(\d+) keys, (\d+) platforms\*\*")],
         "the one site that already carries its own recompute command - keep it exact"),

    Fact("root_py_count", "exact", lambda: (len(glob.glob(os.path.join(ROOT, "*.py"))),),
         "root *.py modules",
         [("README.md", r"~?(\d+) scripts at the repo root"),
          ("docs/MODULES.md", r"\*\*total root modules\*\* \| \*\*(\d+)\*\*")],
         "adding a root module without saying so is how two live modules reached a "
         "'safe to delete' list"),

    Fact("unreferenced_roots", "exact", lambda: (_unreferenced_roots(),),
         "root modules no workflow runs and nothing imports",
         [("README.md", r"(\d+) of them are reachable from no workflow"),
          ("docs/AGENT_BRIEF.md", r"(\d+) unreferenced root modules")],
         "it is quoted as the size of a to-do, so it has to be the real size"),

    Fact("no_main_guard", "exact", lambda: (_no_main_guard(),),
         "root modules with no `if __name__` guard",
         [("docs/MODULES.md", r"^(\d+) root modules have no")],
         "importing one of these RUNS it - merge_research.py rewrites state on import"),

    Fact("registry_rows", "census", lambda: (len(_csv_rows()),), "companies.csv data rows",
         [("README.md", r"registry of\s+" + _CENSUS + r"\s+rows"),
          ("CLAUDE.md", r"registry of\s+" + _CENSUS + r"\s+rows")],
         "the denominator of every coverage claim this project makes"),

    Fact("active_rows", "census", lambda: (len(_active()),), "active companies.csv rows",
         [("README.md", r"reads\s+" + _CENSUS + r"\s+companies'"),
          ("CLAUDE.md", r"reads\s+" + _CENSUS + r"\s+companies'"),
          ("docs/AGENT_BRIEF.md", r"companies\.csv\s+\(" + _CENSUS + r" active\)")],
         "the headline number of the product: how many boards we read each morning"),

    # api_rows / scrape_rows are DELIBERATELY NOT REGISTERED, and the reason is the point
    # of this whole section. Moving a row between those two buckets is literally the
    # registry lane's job: between ae6eeae and 623b2a9, about an hour apart on 2026-08-27,
    # the split went 436/439 -> 451/421 - 18 rows, inside one hour, with no doc edit and no
    # push by anyone who could have known. No bracket narrow enough to be informative can
    # survive that, so those sites carry the COMMAND instead of a number. Registering them
    # would be registering the wrong thing.

    # firmographics_profiles was registered here until 2026-08-28 and is now DELIBERATELY
    # not, for the same reason as api_rows above but arriving from the other side. Its one
    # site was a cell in docs/AGENT_BRIEF.md's flow diagram, whose reader is an AGENT - who
    # can run a command - and whose every other cell names the FILE a step produces rather
    # than how much of it there is. So the cell now names `cloud_state/firmographics.json`
    # and the count is one command away. Nothing that was checked stops being checked: a
    # bracket was never a collapse alarm. A real alarm for that store belongs on the
    # digest's `Company intel:` line, and is filed against `company-intel` in the backlog.

    Fact("facts_registry", "exact",
         lambda: (len(FACTS), sum(len(f.sites) for f in FACTS)),
         "registered facts and the sites they are checked at",
         [("docs/AGENT_BRIEF.md", r"(\d+) registered facts, (\d+) sites")],
         "the brief said `10 registered facts, 18 sites` while FACTS held 9 - the paragraph "
         "explaining the registry was the one number the registry did not check"),
]

# Regions where a number is NOT a claim: a URL, a markdown link target, an HTML comment.
# A number inside backticks or a fenced block IS a claim - the one-screen map is fenced and
# is the most-read diagram in the repo.
# `<!--(?:(?!<!--).)*?-->` so a SECOND opener terminates the scan: an unterminated
# `<!--` left by an edit, plus any well-formed comment further down, used to swallow
# everything between them - and every claim inside went silently unchecked, including a
# bare census number, which is otherwise always an error.
_VETO_RE = re.compile(r"https?://\S+|\]\([^)]*\)|<!--(?:(?!<!--).)*?-->", re.S)


def _veto_spans(text: str) -> list:
    return [m.span() for m in _VETO_RE.finditer(text)]


def _vetoed(span, spans) -> bool:
    return any(a <= span[0] and span[1] <= b for a, b in spans)


def _int(tok: str) -> int:
    return int(tok.replace(",", "").lstrip("~").rstrip("+"))


# The ONLY tolerance number in this file, and it never decides whether a check passes.
# `census_floor` is exact: today either clears the floor the author wrote or it does not.
# This constant answers the two advisory questions - "what floor should I suggest to an
# author who has to write one right now?" and "when has a floor fallen so far behind that
# it has stopped checking anything?" - and it is set from measurement, not taste. Over
# all 111 commits that ever touched companies.csv the largest legitimate fall is -6.0%
# (900 -> 846, 2026-08-23, inside one hour). A floor 15% below today therefore has about
# 2.5x the headroom of the worst thing that has ever normally happened.
CENSUS_HEADROOM = 0.15


# A floor is a plain, CANONICALLY GROUPED, ASCII, non-zero number and a plus. The first
# version accepted `\d[\d,]*\+`, and a wave-1 adversary walked straight through it: `1,30+`
# parsed as 130 because `_int` just strips commas, so one deleted keystroke drops the
# registry floor tenfold and the build stays green. `1,,200+` was worse than green - it
# parsed as 1,200, passed, and the near-miss `1,,+` produced the COLLAPSED message, which
# sends the reader hunting a registry incident caused by a comma. `0+` and `00+` are
# refused because a floor of zero is not a claim, and non-ASCII digits are refused because
# `\d` is Unicode-wide: `٨٠٠+` is TRUE (800) and unreadable in an English README.
_FLOOR_BODY = re.compile(r"\d{1,3}(?:,\d{3})*|\d+")


def census_form(tok: str) -> str:
    """What shape the author wrote: `floor`, `bare`, `band` or `malformed`.

    One function decides, so the check and the error message can never disagree about what
    they are looking at - which is the bug that made `bracket_holds(875, "875")` True while
    the parser called a bare number an error."""
    if tok.endswith("+"):
        body = tok[:-1]
        if not body.isascii() or not _FLOOR_BODY.fullmatch(body):
            return "malformed"
        return "floor" if int(body.replace(",", "")) > 0 else "malformed"
    if re.search(r"[-–]", tok) or tok.startswith("~"):
        return "band"
    return "bare"


def census_floor(tok: str):
    """The floor a census token claims, or None if it does not claim one.

    A floor is EXACT and one-sided: `800+` says the number is at least 800, and no rounding,
    precision or tolerance enters. That is the whole model, and it replaced a bracket model
    in which the trailing zeros of `~1,200` set a tolerance - correct, ingenious, and still
    a two-sided band, which is the thing that kept going red for growing."""
    return _int(tok) if census_form(tok) == "floor" else None


def floor_holds(true_value: int, tok: str) -> bool:
    """Defined in terms of census_floor so the tested function IS the running one."""
    floor = census_floor(tok)
    return floor is not None and true_value >= floor


def suggested_floor(value: int):
    """A floor to offer an author who has to write one now: today's value less
    CENSUS_HEADROOM, rounded DOWN to two significant figures so it reads like a number a
    person chose. 969 -> `820+`, 1,465 -> `1,200+`. Rounding down matters: a suggestion
    that rounded up could be above today's value, and the linter would then be proposing an
    edit that goes red the moment it is made.

    None when today's value cannot carry a floor at all. The first version returned `1+` for
    0 - a floor ABOVE the value, asserting "15% headroom" - on precisely the morning the
    number has gone to zero, which is the mass-zero class this whole check exists for and
    the one morning the message must not be nonsense."""
    target = int(value * (1 - CENSUS_HEADROOM))
    if target < 1:
        return None
    step = 10 ** max(0, len(str(target)) - 2)
    floor = (target // step) * step
    return "{:,}+".format(floor) if 0 < floor <= value else None


def floor_was_lowered(prev_tok, tok, value: int) -> bool:
    """True when a doc edit LOWERS a floor the number had not fallen through.

    A floor may only ever be raised. Nothing could see that until 2026-08-28: a wave-1
    adversary set all three `active_rows` sites to `0+`, and the build was GREEN with one
    warning in a pile of six - warnings do not touch the exit code. `floor_is_stale` cannot
    help, because it is a DECAY detector: it cannot tell `800+`-written-in-August from
    `0+`-written-this-morning. Lowering a floor is widening a band under another name, and
    the whole point of the change that introduced floors was to make that move unavailable.

    The `value >= prev` clause is what stops this deadlocking. If the registry really did
    collapse, the collapse error fires first and lowering the floor is then the correct
    repair; it is only forbidden while the OLD floor still holds, which is the case where
    lowering can be nothing but alarm-deletion."""
    prev = census_floor(prev_tok) if prev_tok else None
    new = census_floor(tok)
    return prev is not None and new is not None and new < prev and value >= prev


def _git(*args):
    """`git` in ROOT, or None. Same contract as `_committed_token`: any failure - no git, no
    repo, a ref that does not exist - is "there is nothing to compare against", never a
    refused push. Never fetches: a linter that reaches the network is one a lane learns to
    skip, and ten sessions running it at once would contend on the ref lock."""
    import subprocess
    try:
        out = subprocess.run(("git",) + args, cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        return None
    return out.stdout if out.returncode == 0 else None



def _committed_token(doc_rel: str, pattern: str):
    """The census token this site carried at HEAD, or None if it cannot be read.

    Reads the committed blob, never the working tree, so an edit in progress is compared
    against what is actually on the branch. Returns None outside a git checkout, on a new
    file, or when the site did not state a floor before - all of which mean "no ratchet to
    enforce", never "refuse the push"."""
    import subprocess
    try:
        out = subprocess.run(["git", "show", "HEAD:" + doc_rel], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
    except Exception:                                             # noqa: BLE001
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    spans = _veto_spans(out.stdout)
    for m in re.finditer(pattern, out.stdout, re.M):
        if _vetoed(m.span(), spans):
            continue
        toks = [g for g in m.groups() if g is not None]
        if toks:
            return toks[0]
    return None


def floor_is_stale(value: int, tok: str) -> bool:
    """True when a floor has been outgrown by twice the headroom it was written with, so it
    has quietly stopped checking anything. Advisory only - it raises a WARNING, never an
    error, because the growth that caused it was nobody's push."""
    floor = census_floor(tok)
    return floor is not None and value * (1 - 2 * CENSUS_HEADROOM) > floor


def _fact_report() -> list:
    """(fact, computed-or-exception, [(doc, line, token, ok, note)]). ok is None when the
    registered pattern matched nothing at all."""
    out = []
    for f in FACTS:
        try:
            got = f.compute()
        except Exception as e:                                    # noqa: BLE001
            out.append((f, e, []))
            continue
        rows = []
        for doc_rel, pattern in f.sites:
            path = os.path.join(ROOT, doc_rel)
            if not os.path.exists(path):
                rows.append((doc_rel, 0, None, None, "doc missing"))
                continue
            text = read(path)
            spans = _veto_spans(text)
            found = False
            for m in re.finditer(pattern, text, re.M):
                if _vetoed(m.span(), spans):
                    continue
                found = True
                line = text.count("\n", 0, m.start()) + 1
                toks = [g for g in m.groups() if g is not None]
                if f.kind == "exact":
                    ok = tuple(_int(t) for t in toks) == tuple(got)
                    note = "" if ok else "code says " + ", ".join(str(g) for g in got)
                else:
                    form = census_form(toks[0])
                    if form != "floor":
                        ok, note = False, form
                    else:
                        # floor_holds, NOT an inline `>=`. It was inlined here for two
                        # commits and `floor_holds` was therefore dead code reached only from
                        # the test suite - so the boundary guard pinned a function nothing
                        # called, and a wave-1 adversary flipped this `>=` to `>` and watched
                        # the linter AND all 23 census guards stay green. That is exactly the
                        # sin `bracket_holds`' old docstring described, reintroduced by the
                        # commit that fixed it.
                        floor = census_floor(toks[0])
                        ok = floor_holds(got[0], toks[0])
                        note = "" if ok else "today %d, below the floor %d" % (got[0], floor)
                rows.append((doc_rel, line, ", ".join(toks), ok, note))
            if not found:
                rows.append((doc_rel, 0, None, None, "pattern matches nothing"))
        out.append((f, got, rows))
    return out


def check_derived_facts() -> None:
    for f, got, rows in _fact_report():
        if isinstance(got, Exception):
            err("facts", "%s could not be computed (%s: %s). A fact that cannot be measured "
                         "belongs out of FACTS, not left to pass silently."
                % (f.name, type(got).__name__, got))
            continue
        if f.sites and not [r for r in rows if r[3] is not None]:
            err("facts", "%s (%s) is registered and no doc states it any more. Restore the "
                         "claim or delete the FACTS entry - a registry that quietly stops "
                         "matching is a linter that has become decorative."
                % (f.name, f.unit))
        for doc_rel, line, tok, ok, note in rows:
            if ok is None:
                # An ERROR, not a warning. A registered site that stops matching is a
                # sentence that is still asserting a number and is no longer checked - and
                # an unterminated HTML comment three paragraphs up is enough to cause it.
                # If the sentence was rewritten for the better, deleting the site is one
                # line, and that is the action this message asks for.
                err("facts", "%s: a site registered for %s matches nothing now (%s). The "
                             "sentence there is either gone or no longer says a number. "
                             "Restore the claim, or delete the site from FACTS - do not "
                             "leave a number asserting without a check."
                    % (doc_rel, f.name, note))
            elif note in ("bare", "band", "malformed"):
                sug = suggested_floor(got[0])
                err("facts", "%s:%d states %s (%s) as %s, and a census claim may only be "
                             "ONE-SIDED. This number moves because the crons ran, not "
                             "because anyone pushed: %s %s"
                    % (doc_rel, line, f.name, f.unit,
                       {"bare": "the bare number %s" % tok,
                        "band": "the two-sided claim %s" % tok,
                        "malformed": "the token %s, which is not a floor this check "
                                     "can read" % tok}[note],
                       {"bare": "a point value will be wrong within a day.",
                        "band": "a band fails when the project is WORKING - active rows "
                                "went 873 -> 969 in 14 hours and turned the build red - "
                                "and widening it is the move that deletes the alarm.",
                        "malformed": "a floor is a plain, comma-grouped, ASCII, non-zero "
                                     "number and a plus: `900+`, `1,300+`. `~900+`, `1,30+`, "
                                     "`0+` and non-ASCII digits are all refused, because each "
                                     "of them reads as a claim and is not one."}[note],
                       ("Write the floor you are willing to stand behind - `%s` has %d%% "
                        "headroom today - or replace it with the command that prints it."
                        % (sug, int(100 * CENSUS_HEADROOM))) if sug else
                       ("Today it is %d, which is too small to carry a floor at all. That is "
                        "the mass-zero class, not a documentation problem: diagnose the run "
                        "before you touch the doc." % got[0])))
            elif not ok and f.kind == "exact":
                err("facts", "%s:%d says %s for %s (%s); the code says %s. %s."
                    % (doc_rel, line, tok, f.name, f.unit,
                       ", ".join(str(g) for g in got), f.why))
            elif not ok:
                err("facts", "%s:%d claims %s for %s (%s) and today it is %d - the number "
                             "COLLAPSED through its floor. This is not a stale doc: growth "
                             "can never trip this check, so either a merge or a mass "
                             "deactivation dropped rows (section 8's mass-zero class), or "
                             "the measurement itself is broken. Diagnose before you edit the "
                             "doc; %s."
                    % (doc_rel, line, tok, f.name, f.unit, got[0], f.why))
            elif f.kind == "census" and floor_was_lowered(
                    _committed_token(doc_rel, dict(f.sites).get(doc_rel, "")), tok, got[0]):
                # An ERROR, and the one census error a doc edit alone can cause. Every other
                # census error is the crons' doing and this file is careful not to punish the
                # pusher for those - but LOWERING a floor is a keystroke, it is the "widen the
                # band" move under another name, and until this existed `0+` at all three
                # sites was a GREEN build with one warning in a pile of six.
                err("facts", "%s:%d LOWERS the floor for %s from %s to %s, and today's %d is "
                             "still above the old floor. A floor may only ever be RAISED. "
                             "Lowering one deletes the alarm without failing anything, which "
                             "is exactly what widening a band did. If the number really has "
                             "collapsed, its own error fires first and lowering is then the "
                             "repair - it is refused only while the old floor still holds."
                    % (doc_rel, line, f.name,
                       _committed_token(doc_rel, dict(f.sites).get(doc_rel, "")),
                       tok, got[0]))
            elif f.kind == "census" and floor_is_stale(got[0], tok):
                sug = suggested_floor(got[0])
                warn("facts", "%s:%d writes %s for %s; today it is %d, so the floor is more "
                              "than %d%% behind and has stopped checking much. Raise it to "
                              "`%s` while you are here - a floor may only ever be raised, "
                              "and raising it can never make a true doc false."
                     % (doc_rel, line, tok, f.name, got[0],
                        int(200 * CENSUS_HEADROOM), sug or "a number you can stand behind"))
        if not f.sites:
            warn("facts", "%s (%s) computes to %s and no doc states it."
                 % (f.name, f.unit, ", ".join(str(g) for g in got)))


def _raw(path: str) -> str:
    """The file's bytes as text, line endings PRESERVED. `read()` uses universal newlines,
    which is right for checking and wrong for writing: README.md is LF-only while the other
    five root docs are CRLF, so a naive rewrite produces a whole-file diff on five of six."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


# A line that draws a box or a table has a WIDTH, and a width-changing edit shears it.
# ARCHITECTURE.md's one-screen map is 82 characters wide and every row ends in a bar.
_RULED = re.compile(r"[─-╿]")
# A line that computes with the number cannot be edited one number at a time:
# ARCHITECTURE.md carries `846 rows x ~135 characters ~= 114 KB`.
_ARITH = re.compile(r"[×≈%]|(?<![-:=])=(?!=)")


def _line_of(text: str, pos: int):
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return a, (len(text) if b < 0 else b)


def _fmt_like(old: str, value: int) -> str:
    return "{:,}".format(value) if "," in old else str(value)


def fix_facts(apply: bool = False) -> int:
    """`--fix` for EXACT facts only, and never for census ones.

    A census number needs a judgement about the precision the author is willing to stand
    behind; a script must not make that. An exact number is arithmetic, and the agent who
    changed the code is the one standing here - which is the whole contract of the EXACT
    class. The first real use was an `infra` session adding a workflow step, which moves the
    continue-on-error ratio at four sites in three documents.

    Six guards, every one of them written from a real hazard in this tree:
      * bytes, not lines - line endings are preserved exactly (README.md is the only LF file)
      * region veto - a number inside a URL, a link target or an HTML comment is not a claim
      * width invariance - a length-changing edit inside a ruled or tabular line is REFUSED
      * arithmetic veto - a line that multiplies or equates is REFUSED
      * clean-tree gate - refuses to touch a file that is already dirty, so any mistake is
        one `git checkout --` from gone
      * verify-then-keep - the whole fact check is re-run against the result, and every file
        is restored if it does not come back clean
    """
    import subprocess
    targets, plan = set(), []
    for f in FACTS:
        if f.kind != "exact":
            continue
        try:
            got = f.compute()
        except Exception as e:                                    # noqa: BLE001
            err("facts", "%s cannot be computed, so it cannot be fixed (%s)" % (f.name, e))
            return 1
        for doc_rel, pattern in f.sites:
            path = os.path.join(ROOT, doc_rel)
            if not os.path.exists(path):
                continue
            raw = _raw(path)
            spans = _veto_spans(raw)
            for m in re.finditer(pattern, raw, re.M):
                if _vetoed(m.span(), spans):
                    continue
                idx = [g for g in range(1, (m.re.groups or 0) + 1) if m.group(g) is not None]
                if len(idx) != len(got):
                    continue
                if tuple(_int(m.group(g)) for g in idx) == tuple(got):
                    continue
                plan.append((doc_rel, path, m, idx, got, f.name))
                targets.add(doc_rel)
    if not plan:
        print("every EXACT fact already agrees with the code; nothing to fix")
        return 0

    if apply and targets:
        dirty = subprocess.run(["git", "status", "--porcelain", "--"] + sorted(targets),
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if dirty:
            # print, do not err(): --fix returns before main() reports ERRORS, so an err()
            # here is swallowed and the caller sees an exit code with no reason.
            print("REFUSED: --fix will not edit a file that is already modified, so any "
                  "mistake stays one `git checkout --` away. Commit or stash first:")
            print(dirty)
            return 1

    edits, refused = {}, 0
    for doc_rel, path, m, idx, got, name in sorted(plan, key=lambda p: (p[0], -p[2].start())):
        raw = edits.get(path, _raw(path))
        chunk = m.group(0)
        for pos, g in reversed(list(enumerate(idx))):
            a, b = m.span(g)
            chunk = chunk[:a - m.start()] + _fmt_like(m.group(g), got[pos]) + chunk[b - m.start():]
        if doc_rel == "docs/MODULES.md":
            print("REFUSED %s:%d (%s): this file is GENERATED. A hand edit is discarded by the "
                  "next run and the number comes back. Fix it at the source and regenerate:"
                  "  python docs/gen_modules.py"
                  % (doc_rel, raw.count("\n", 0, m.start()) + 1, name))
            refused += 1
            continue
        la, lb = _line_of(raw, m.start())
        line = raw[la:lb]
        tail = raw[m.end():lb]
        if len(chunk) != len(m.group(0)) and (_RULED.search(line) or "|" in tail):
            print("REFUSED %s:%d (%s): %r would change the width of a ruled or tabular line. "
                  "Edit it by hand and keep the column."
                  % (doc_rel, raw.count("\n", 0, m.start()) + 1, name, m.group(0)))
            refused += 1
            continue
        if _ARITH.search(line):
            print("REFUSED %s:%d (%s): the line computes with the number, so changing one "
                  "number alone would make it arithmetically false: %r"
                  % (doc_rel, raw.count("\n", 0, m.start()) + 1, name, line.strip()[:70]))
            refused += 1
            continue
        print("%-24s %s:%d  %r -> %r" % (name, doc_rel,
                                         raw.count("\n", 0, m.start()) + 1, m.group(0), chunk))
        edits[path] = raw[:m.start()] + chunk + raw[m.end():]

    if not apply:
        print("\ndry run: %d edit(s), %d refused. Re-run with `--fix --apply` to write."
              % (len(plan) - refused, refused))
        return 0

    del ERRORS[:]
    del WARNINGS[:]
    check_derived_facts()
    was = set(ERRORS)
    before = {p: _raw(p) for p in edits}
    for p, text in edits.items():
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    del ERRORS[:]
    del WARNINGS[:]
    check_derived_facts()
    now = set(ERRORS)
    introduced = now - was
    unfixed = [d for d, _p, m, _i, _g, _n in plan
               if any(d in e for e in now) and d not in ("docs/MODULES.md",)]
    if introduced or not (was - now):
        for p, text in before.items():
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        print("VERIFY FAILED, every file restored.")
        for e in sorted(introduced) or sorted(now):
            print("  " + e)
        return 1
    if unfixed:
        print("\nnote: %d site(s) still disagree because an edit was refused above." % len(unfixed))
    print("\nwrote %d file(s); %d refused. Re-run `python docs/check_docs.py` to confirm."
          % (len(edits), refused))
    return 0


def report_facts() -> int:
    """`python docs/check_docs.py --facts` - every registered number, what the code says
    today, and what each doc claims. One command instead of an archaeology dig."""
    print("%-22s %-7s %-11s %-4s %s" % ("fact", "class", "today", "", "site"))
    print("-" * 96)
    for f, got, rows in _fact_report():
        if isinstance(got, Exception):
            print("%-22s %-7s UNCOMPUTABLE  %s" % (f.name, f.kind, got))
            continue
        val = ", ".join(str(g) for g in got)
        if not rows:
            print("%-22s %-7s %-11s %-4s (no site registered)" % (f.name, f.kind, val, "-"))
        for i, (doc_rel, line, tok, ok, note) in enumerate(rows):
            mark = "ok" if ok else ("--" if ok is None else "RED")
            where = "%s:%d" % (doc_rel, line) if line else doc_rel
            print("%-22s %-7s %-11s %-4s %s%s%s"
                  % (f.name if i == 0 else "", f.kind if i == 0 else "",
                     val if i == 0 else "", mark, where,
                     " = " + tok if tok else "", "  " + note if note else ""))
    return 0


# ------------------------------------------------- 6. HANDOFF shape and the morning checks
# The 250-line cap was respected and useless. On 2026-08-27 HANDOFF.md was 245 lines and
# 56,515 BYTES: eighteen sessions had each written their whole narrative as a single line,
# the longest 4,960 characters, and thirteen of them ended with `Record: docs/sessions/...`
# — so the long version already existed and the HANDOFF copy was the duplicate. The file
# had been split from 753 lines on 2026-08-23 to fix exactly this, which is the point: the
# metric was gameable and got gamed.
#
# So the caps are made mutually reinforcing rather than mutually escapable. A narrative
# that cannot hide on one line has to wrap; wrapping blows the line count; the line count
# is what pushes it to docs/sessions/. Fenced blocks, indented blocks and table rows are
# exempt from the per-line cap, because this file legitimately carries multi-line recovery
# one-liners and a morning-check table.
HANDOFF_MAX_LINES = 250
HANDOFF_MAX_WORDS = 3200
HANDOFF_MAX_LINE_WORDS = 60
HANDOFF_REQUIRED = ["## State at handoff", "## Watch list", "## Open items"]


def _handoff_prose_lines(text: str):
    """(lineno, line) for lines the per-line cap applies to."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or line.startswith(("    ", "\t", "|")):
            continue
        yield n, line


# ------------------------------------------------- 5b. the product's SCOPE, as a claim
# FACTS above checks NUMBERS. This checks a CLAIM, and it exists because a claim had no
# test. On 2026-08-28 the operator removed the ~3+ years experience bar; `classifier`
# shipped it in 66d9e3c with `docs/decisions/2026-08-28-analyst-scope.md`; and README.md,
# CLAUDE.md, ARCHITECTURE.md §0, pipeline/__init__.py and four literals in
# pipeline/digest.py went on advertising the filter for the rest of the day - including the
# line the relay turns into the mail's subject, which reached the inbox at 08:29Z that
# morning reading "4 new senior analytics roles". This linter was green the whole time,
# because everything the docs POINT AT still existed. That is the old root SCHEDULING.md
# failure (wrong for three days about whether the daily email existed) in a new place.
#
# The contract is TWO-WAY, decided by the code. A blocklist would go green the moment the
# phrases were deleted and would say nothing about whether what replaced them is true - and
# the cheapest way to green it would be to stop telling visitors anything, which is a new
# inaccuracy, not a fix.
SCOPE_SURFACES = ("README.md", "CLAUDE.md", "ARCHITECTURE.md",
                  "pipeline/digest.py", "pipeline/__init__.py")

# The three that must also state the replacement. `pipeline/digest.py` says it too today,
# but requiring it there would freeze `render`'s wording of a rendered string; the PROMISE
# is the docs' to make.
SCOPE_MUST_STATE = ("README.md", "CLAUDE.md", "ARCHITECTURE.md")

# Whitespace-tolerant because this prose is hard-wrapped at ~95 columns and one of the real
# sites (`ARCHITECTURE.md`'s "0 new senior analytics\n   roles") wrapped straight through
# the phrase. Case-insensitive because the board's subtitle said "Experienced (" with a
# capital E and a case-sensitive first draft of this check sailed past the single most-read
# stale claim in the product.
_BAR_PROMISE = [
    (r"[≈~]\s*3\+\s*(?:yrs?|years?)", "the ≈3+ yrs idiom"),
    (r"experienced\s*\(\s*\**\s*[≈~]?\s*3\+", "\"experienced (3+ ...)\""),
    (r"senior\s+analytics\s+roles?", "\"senior analytics roles\""),
    (r"anything\s+junior/intern/entry-level", "the old junior/intern/entry-level clause"),
]
_BAR_FREE = r"any\s+experience\s+level"

# `senior analytics OPENINGS` is deliberately absent. Its only two sites are in
# `build_digest`, the dead renderer BACKLOG 142 deletes - it writes `out/digest-<date>.html`
# and a `subject` key nothing reads. The operator declined to polish strings in code that is
# scheduled for deletion, because doing so makes the dead code look maintained and 142
# harder to argue. If `build_digest` outlives 142, add `openings?` to the third pattern.
# `persist_state.py` and `.github/workflows/` are not surfaces either: they QUOTE a rendered
# example in a comment rather than promise anything to a reader, and they are `infra`'s.
# `docs/sessions/`, `docs/decisions/` and `docs/BACKLOG.md` quote the retired phrase on
# purpose - they are frozen archives, and `tests/test_units.py` already forbids registering
# one as a fact site for the same reason.


def scope_bar_default() -> bool:
    """`pipeline/seniority.py`'s EXPERIENCE_BAR as SHIPPED, by AST - not by importing, and
    not by reading the live global.

    Not by importing, for the reason `_fetcher_keys` gives. Not the live global, for a
    sharper reason found by an adversary: `EXPERIENCE_BAR` is `os.environ.get(...) == "1"`,
    so a guard that read `seniority.EXPERIENCE_BAR` would take the other branch under
    `CLASSIFY_EXPERIENCE_BAR=1` and assert the promise is PRESENT. It is present. That is a
    one-word green over the whole drift, from the environment of whoever runs the suite.

    Every other shape RAISES, which `check_derived_facts` reports as uncomputable - loud and
    correct, the same contract `_fetcher_keys` keeps."""
    path = os.path.join(ROOT, "pipeline", "seniority.py")
    tree = ast.parse(read(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "EXPERIENCE_BAR" for t in node.targets)):
            continue
        v = node.value
        if not (isinstance(v, ast.Compare) and len(v.comparators) == 1
                and isinstance(v.left, ast.Call) and len(v.left.args) == 2
                and all(isinstance(a, ast.Constant) for a in v.left.args)
                and isinstance(v.comparators[0], ast.Constant)):
            raise RuntimeError(
                "pipeline/seniority.py's EXPERIENCE_BAR is no longer `os.environ.get(NAME, "
                "DEFAULT) == VALUE` (%s). The scope check reads its shipped DEFAULT; teach "
                "it the new shape rather than letting it guess." % type(v).__name__)
        return v.left.args[1].value == v.comparators[0].value
    raise RuntimeError("pipeline/seniority.py no longer assigns EXPERIENCE_BAR. The product "
                       "scope is checked against it; find what replaced it.")


def check_scope_claims() -> None:
    bar = scope_bar_default()
    for surface in SCOPE_SURFACES:
        path = os.path.join(ROOT, surface)
        if not os.path.exists(path):
            err("scope", "%s is a registered scope surface and does not exist. Restore it, "
                         "or drop it from SCOPE_SURFACES - a surface that silently stops "
                         "being read is a claim that stops being checked." % surface)
            continue
        text = read(path)
        spans = _veto_spans(text)
        hits = []
        for pattern, label in _BAR_PROMISE:
            for m in re.finditer(pattern, text, re.I):
                if _vetoed(m.span(), spans):
                    continue
                hits.append((text.count("\n", 0, m.start()) + 1, label))
        if bar and not hits:
            err("scope", "%s states no experience bar, but pipeline/seniority.py ships "
                         "EXPERIENCE_BAR on. A filter the code enforces and the docs do not "
                         "mention is the same defect as one the docs promise and the code "
                         "dropped." % surface)
        for lineno, label in sorted(hits):
            if not bar:
                err("scope", "%s:%d still promises an experience bar (%s), and "
                             "pipeline/seniority.py ships EXPERIENCE_BAR OFF - there is no "
                             "minimum experience. Say what the product does now; see "
                             "docs/decisions/2026-08-28-analyst-scope.md."
                    % (surface, lineno, label))
    if bar:
        return
    for surface in SCOPE_MUST_STATE:
        path = os.path.join(ROOT, surface)
        if os.path.exists(path) and not re.search(_BAR_FREE, read(path), re.I):
            err("scope", "%s no longer promises an experience bar and does not say what it "
                         "does instead (`any experience level`). Deleting the claim is not "
                         "the same as correcting it: a visitor is now told nothing about "
                         "who the board is for." % surface)


def check_handoff() -> None:
    path = os.path.join(ROOT, "HANDOFF.md")
    if not os.path.exists(path):
        err("handoff", "HANDOFF.md is missing")
        return
    text = read(path)
    n = len(text.splitlines())
    if n > HANDOFF_MAX_LINES:
        err("handoff", "HANDOFF.md is %d lines (cap %d). It is the CURRENT-STATE file: move "
                       "dated narrative to docs/sessions/<date>-<lane>.md, durable rules to "
                       "ARCHITECTURE.md, and known gaps to docs/BACKLOG.md."
            % (n, HANDOFF_MAX_LINES))
    words = len(text.split())
    if words > HANDOFF_MAX_WORDS:
        err("handoff", "HANDOFF.md is %d words (cap %d). The line cap alone was defeated once "
                       "by writing a whole session as one 4,960-character line; this is the "
                       "cap that notices." % (words, HANDOFF_MAX_WORDS))
    for lineno, line in _handoff_prose_lines(text):
        if len(line.split()) > HANDOFF_MAX_LINE_WORDS:
            err("handoff", "HANDOFF.md:%d is %d words on one line (cap %d). That is a session "
                           "narrative, not a handoff line: put it in docs/sessions/ and leave "
                           "the five-part entry behind."
                % (lineno, len(line.split()), HANDOFF_MAX_LINE_WORDS))
    for required in HANDOFF_REQUIRED:
        if required not in text:
            err("handoff", "HANDOFF.md has no `%s` section" % required)


# PASS may stand alone; anything else must say what happened, because "FAIL" with no
# string is the same silence the table exists to end.
# One verb, then a separator, then evidence. Case-insensitive, and `:` / `,` / an em or en
# dash all count, because the previous version accepted a bare `PASS` - the exact thing its
# own error message argues against - while rejecting `FAIL: the inbox issue was 07:10Z` and
# `Pass - board 76 cards`. It also used to be satisfied by the hyphen inside an ISO date.
_VERDICT_OK = re.compile(
    r"^(?:PASS(?:ED)?|FAIL(?:ED|S)?|N/A|PARTIAL|INCONCLUSIVE|SKIPPED)\b[^:,\u2013\u2014-]*"
    r"[:,\u2013\u2014-]\s*\S.{9,}$|^not yet due\b.*$", re.I)
_LOOSE_CHECK = re.compile(r"morning check\s+\d{4}-\d\d-\d\d", re.I)

# A re-date, and it must carry the date it moves to. Five rows said "re-dated by `docs`" in
# the VERDICT cell with the due column untouched and no new date anywhere, which is how a
# check is answered by never answering it: the linter asks again tomorrow, gets the same
# sentence, and warns for ever. `until` moves the deadline; nothing else does.
_REDATE = re.compile(r"^not yet due\b[^|]*?\buntil\s+(\d{4}-\d\d-\d\d)\b", re.I)
_REDATE_WORDS = re.compile(r"re-?dated?|postpon|deferr|push(?:ed)?\s+(?:to|out)", re.I)
# Evidence, not an adjective: a verdict names a number or a grep-able string. Every live
# verdict already does; `INCONCLUSIVE - could not determine` is the shape this refuses.
# A DATE is not evidence: `PASS - confirmed on 2026-08-30` names the day it was written
# and nothing else. A digit outside an ISO date, or a grep-able string, is.
_ISO = re.compile(r"\d{4}-\d\d-\d\d")
_HAS_EVIDENCE = re.compile(r"\d|`")
# How long a row may stay unanswered past its date before it stops being a warning. One day
# is the first morning anyone can read the mail it predicts; two means a second session
# walked past it, and by then its author is gone.
MORNING_GRACE_DAYS = 2
MORNING_REDATE_MAX_DAYS = 14
MORNING_REDATE_MAX = 2
UNATTENDED_MAX_DAYS = 14

NL_SAFE = "\n"


def check_morning_checks() -> None:
    """A prediction about tomorrow's mail is not finished until it has an answer.

    Fourteen `Morning check <date>:` sentences were buried in HANDOFF.md's prose and NOT ONE
    had ever been answered. Two had already failed in public twice: `### Tel Aviv` and
    `### Jobgether` both shipped as employer headings in the 2026-08-26 mail against checks
    that said neither would.

    An unanswered check WARNS on its due date and the morning after, and is an ERROR from
    the second day. Half of the old reasoning still holds and is why the grace exists:
    `discovery` writes the check on Tuesday and it comes due while `jd-text` is pushing on
    Wednesday, so an immediate error punishes the wrong agent. The other half - "the
    cheapest way for that agent to go green would be to DELETE the check" - no longer
    holds: `check_morning_rows_survive` makes deletion an error, so the two cheapest exits
    left are the two the table wants, answering and re-dating in writing. Six rows sat past
    due saying `not yet due`, five of them "re-dated" with the due column untouched and no
    new date anywhere, under a build that was green all week.

    The SHAPE of a row is an error at any age, because that is the pushing session's own
    work."""
    rows = _morning_rows("HANDOFF.md")
    if rows is None:
        return
    if not rows:
        warn("morning-checks", "HANDOFF.md has no `## Morning checks` table. A prediction "
                               "with nowhere to be answered is how `### Tel Aviv` shipped "
                               "twice against a check that said it would not.")
    # The ARCHIVE gets the same SHAPE check and none of the age checks. Every answered row
    # ends up in docs/morning-checks.md, and until 2026-08-28 nothing read that file at all:
    # it had a table with a header and no separator row (so it rendered as prose, invisibly)
    # and nobody noticed for a day. Age is deliberately NOT checked there - an archived row
    # is history, and history that can go red for being old is history somebody will edit.
    for cells in _morning_rows("docs/morning-checks.md") or []:
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", cells[0]):
            err("morning-checks", "an archived morning check has no ISO due date: %r"
                % cells[0])
        elif cells[4] and not _VERDICT_OK.match(cells[4]):
            err("morning-checks", "archived morning check %s (`%s`) has a verdict the reader "
                                  "cannot check: %r" % (cells[0], cells[1], cells[4][:60]))
    text = read(os.path.join(ROOT, "HANDOFF.md"))
    lanes = _lane_names()
    today = _today()
    for cells in rows:
        due, lane, must, answered, verdict = cells[0], cells[1], cells[2], cells[3], cells[4]
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", due):
            err("morning-checks", "a morning-check row has no ISO due date: %r" % due)
            continue
        if lanes and lane not in lanes:
            err("morning-checks", "morning check %s names lane `%s`, which is not in "
                                  "docs/AGENT_BRIEF.md's table" % (due, lane))
        # Count re-DATES, not the word: an honest reason ("the drain does not run
        # until 2026-09-01 and nothing can be read until then") tripped the cap on
        # its FIRST use. And the cap that matters is total DISPLACEMENT, because a
        # session that overwrites the cell each morning resets any token count to 1
        # for ever - measured: such a row is silent on every day, permanently.
        eff, redates = due, len(re.findall(r"\buntil\s+\d{4}-\d\d-\d\d", verdict, re.I))
        m = _REDATE.match(verdict)
        if m:
            eff = m.group(1)
            if not _is_a_real_date(eff):
                # `due` is fullmatch-validated; `until` was not, so `2026-13-45` -
                # which string-sorts AFTER a real due date - reached strptime and
                # brought the whole linter down with a ValueError.
                err("morning-checks", "morning check %s (`%s`) re-dates itself to %r, which is not a date." % (due, lane, eff))
                eff = due
            if eff <= due:
                err("morning-checks", "morning check %s (`%s`) re-dates itself to %s, which "
                                      "does not move the deadline: `until` must be LATER "
                                      "than the due column." % (due, lane, eff))
                eff = due
            elif _days_between(due, eff) > MORNING_REDATE_MAX_DAYS:
                err("morning-checks", "morning check %s (`%s`) is pushed %d days out, to %s. Past %d days a check is not re-dated, it is abandoned: answer it, or drop the row and say why in the session record."
                    % (due, lane, _days_between(due, eff), eff, MORNING_REDATE_MAX_DAYS))
            elif False:
                warn("morning-checks", "morning check %s (`%s`) is pushed %d days out, to "
                                       "%s. A check moved more than %d days is a check "
                                       "abandoned - answer it, or drop it and say why."
                     % (due, lane, _days_between(due, eff), eff, MORNING_REDATE_MAX_DAYS))
            if redates > MORNING_REDATE_MAX:
                err("morning-checks", "morning check %s (`%s`) has been re-dated %d times. "
                                      "Answer it: `INCONCLUSIVE - <what the log showed>` "
                                      "with a run id IS an answer, and a %dth `until` is "
                                      "not." % (due, lane, redates, redates))
        elif verdict.lower().startswith("not yet due") and _REDATE_WORDS.search(verdict):
            err("morning-checks", "morning check %s (`%s`) says it was re-dated and carries "
                                  "no new date. Write `not yet due - until YYYY-MM-DD: "
                                  "<why>` so the linter knows which morning to ask again; "
                                  "five rows said this with the due column untouched, and "
                                  "the check warned about the same day for ever."
                % (due, lane))
            continue    # one defect, one edit, one error: the age
            #             rule below would say the same thing again
        unanswered = (verdict in ("", "\u2014", "-")
                      or verdict.lower().startswith("not yet due"))
        late = _days_between(eff, today) if eff <= today else 0
        if unanswered and late >= MORNING_GRACE_DAYS:
            err("morning-checks", "morning check due %s (`%s`) is %d days past its date "
                                  "with no verdict: %s. Answer it (PASS / FAIL - <what "
                                  "happened> / N/A - <why>, quoting a grep-able string) or "
                                  "re-date it as `not yet due - until YYYY-MM-DD: <why>`. "
                                  "Deleting the row is the one move the table forbids, and "
                                  "`check_morning_rows_survive` notices."
                % (due, lane, late, must[:70]))
        elif unanswered and eff <= today:
            warn("morning-checks", "morning check due %s (`%s`) has no verdict yet: %s"
                 % (due, lane, must[:70]))
        elif not unanswered:
            if not _VERDICT_OK.match(verdict):
                err("morning-checks", "morning check %s (`%s`) has a verdict the reader "
                                      "cannot check: %r. Use PASS / FAIL - <what happened> "
                                      "/ N/A - <why>, and quote a grep-able string, not an "
                                      "adjective." % (due, lane, verdict[:60]))
            elif not _HAS_EVIDENCE.search(_ISO.sub("", verdict)):
                err("morning-checks", "morning check %s (`%s`) answers with an adjective "
                                      "and no evidence: %r. A verdict names a number or a "
                                      "grep-able string - `INCONCLUSIVE - could not "
                                      "determine` is the shape this refuses."
                    % (due, lane, verdict[:60]))
            elif not answered:
                err("morning-checks", "morning check %s (`%s`) carries a verdict and an "
                                      "empty `answered` column. That date is how a reader "
                                      "tells a fresh answer from an inherited one."
                    % (due, lane))
    # Scan the WHOLE file, minus the table's own rows. The first version stopped at the
    # table header, so a session appending a prose check BELOW the table - which is where
    # a session appends things - was invisible to the check written to catch exactly that.
    body = NL_SAFE.join(l for l in text.splitlines() if not l.startswith("| "))
    for m in _LOOSE_CHECK.finditer(body):
        err("morning-checks", "HANDOFF.md states a morning check in prose (%r). Fourteen of "
                              "those existed and none was ever answered - put it in the "
                              "table, with the date you will answer it."
            % body[m.start():m.start() + 40])


def _morning_rows(doc_rel: str, text: str = None, quiet: bool = False):
    """Every 5-cell morning-check row in a document, or None if the file is not there.

    Split out on 2026-08-28 so the ARCHIVE can be held to the same shape as the live table
    without being held to its deadlines. It parses; the SHAPE errors it raises are the
    pushing session's own work, so they are errors in both files."""
    # `text` lets the deletion guard run these exact rules over a COMMITTED blob; `quiet`
    # suppresses the SHAPE errors while doing it, because a row that was malformed at
    # origin/master is not this session's work to fix.
    _e = (lambda *a: None) if quiet else err
    if text is None:
        path = os.path.join(ROOT, doc_rel)
        if not os.path.exists(path):
            return None
        text = read(path)
    rows, in_table, want_rule = [], False, False
    for line in text.splitlines():
        if line.startswith("| due | lane |"):
            in_table, want_rule = True, True
            continue
        if not in_table:
            continue
        # Collect every pipe row from the table header to the next `## ` heading. Stopping
        # at the first non-pipe line meant ONE blank line - or an HTML comment between rows
        # - silently dropped every row below it, and the check only complained when zero
        # rows survived. In the live table that was 20 of 21 predictions, with a green build.
        if line.startswith("## "):
            in_table, want_rule = False, False
            continue
        if not line.startswith("|"):
            continue
        # split on the pipes, never strip them: an EMPTY last cell - which is exactly what
        # an unanswered check looks like - is swallowed by strip("|") and the row then
        # fails the len() test and is silently dropped. Found by break-test.
        # `\\|` is the ONLY legal way to write a pipe inside a GFM cell, and the
        # `must be true` column is full of backticked shell - a naive split read
        # `wc \\| grep` as a column boundary and reported a 6-cell row.
        cells = [c.replace("\\|", "|").strip()
                 for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if not cells:
            continue          # a line that is exactly `|`: no cells, not a bad row
        if not re.match(r"\d{4}-\d\d-\d\d$", cells[0]) and len(cells) != 5:
            # a second table or a sub-heading under `## Morning checks` is not a
            # malformed morning check. HANDOFF.md is the file every lane appends to,
            # and one unrelated two-column table produced an error PER ROW.
            continue
        if set(cells[0]) <= set("-: "):
            want_rule = False
            continue
        if want_rule:
            # A header with no `|---|` under it renders as PROSE, not a table. The rows are
            # still there and still parse, so every check below passes while a human reader
            # sees a wall of pipes. docs/morning-checks.md shipped exactly that on
            # 2026-08-27 and nothing looked at it.
            _e("morning-checks", "%s has a morning-check table whose header is not followed "
                                  "by a `|---|` separator, so it renders as prose: %s"
                % (doc_rel, line.strip()[:70]))
            want_rule = False
        if len(cells) != 5:
            # A `|` inside a cell shifts every column right, so the verdict is read from the
            # wrong one and a real verdict is never validated. The `must be true` column is
            # full of backticked shell text, so this is one `| wc -l` away.
            _e("morning-checks", "%s: a morning-check row has %d cells, not 5 - a `|` "
                                  "inside a cell shifts the verdict column: %s"
                % (doc_rel, len(cells), line.strip()[:80]))
            continue
        rows.append(cells)
    return rows


def _rows_at(ref: str, doc_rel: str):
    """The morning-check rows a document carried at `ref`, or None if it cannot be read."""
    text = _git("show", "%s:%s" % (ref, doc_rel))
    return None if text is None else _morning_rows(doc_rel, text=text, quiet=True)


def _row_key(cells) -> tuple:
    """(due, lane, the first 40 characters of the claim, punctuation and case stripped).

    Three live rows share `2026-08-29` + `infra`, so the key has to reach into the claim. It
    is a PREFIX, and stripped of backticks and asterisks, because a session that answers a
    row often re-formats it and re-formatting is not withdrawal. Rewriting the first forty
    characters of a prediction reads as deleting it - the error message says so, and that is
    the price of a key stable enough to be worth having."""
    return (cells[0], cells[1], re.sub(r"[`*_ ]", "", cells[2])[:40].lower())


def check_morning_rows_survive() -> None:
    """A prediction cannot be withdrawn by deleting its row.

    This is the guard that makes escalating the age rules safe. Without it the cheapest way
    out of a red build is to delete somebody else's unanswered check, and the linter would
    destroy the mechanism it exists to protect. With it, the two cheapest exits are the two
    honest ones: answer the row, or re-date it in writing.

    The baseline is `origin/master` when that ref exists and differs from HEAD - the tree a
    lane is actually pushing onto - and `HEAD~1` otherwise, which is what a CI push build
    can see. Neither available means there is nothing to compare against, and this returns
    silently rather than inventing a verdict.

    FOR A READER OF A GREEN CI RUN: this check, `check_tree_is_current` and
    `check_unattended_proof` are LOCAL, pre-push guards. `actions/checkout@v5` clones one
    commit deep and this repo pushes straight to master, so on CI the merge-base IS HEAD
    and all three return silently. A green CI run is not proof that a row survived."""
    # The MERGE-BASE, never origin/master's tip. A row another lane ADDED after this branch
    # was cut has never existed here and cannot have been deleted here - the guard reported
    # exactly that on its first run, against a row `jd-text` pushed the same morning.
    base = _git("merge-base", "HEAD", "origin/master")
    base = base.strip() if base else None
    if base is None and _git("rev-parse", "-q", "--verify", "HEAD~1"):
        base = "HEAD~1"
    if base is None:
        return
    # Moving an unanswered row to the archive is the one way left to retire a prediction
    # without answering it, now that deleting it is an error. Only rows this branch ADDS are
    # judged: everything already in the archive is history, and history that can go red is
    # history somebody edits (`test_the_archive_is_checked_for_shape_but_never_for_age`).
    had = _rows_at(base, "docs/morning-checks.md")
    if had is not None:
        before = {_row_key(c) for c in had}
        for cells in (_morning_rows("docs/morning-checks.md") or []):
            if _row_key(cells) in before:
                continue
            if not cells[4] or cells[4].lower().startswith("not yet due"):
                err("morning-checks", "morning check %s (`%s`) was moved to "
                                      "docs/morning-checks.md with no answer. The archive is "
                                      "this repo's record of how often its own predictions "
                                      "came true - answer the row, then archive it."
                    % (cells[0], cells[1]))
            elif not _HAS_EVIDENCE.search(_ISO.sub("", cells[4])):
                # `PASS - nothing to report here` retired a prediction outright: the
                # archive checked the verb and the date and never the evidence. Judged
                # only for rows this branch ADDS - the same reason the rule above is.
                err("morning-checks", "morning check %s (`%s`) was archived with no "
                                      "evidence: %r. A verdict names a number or a "
                                      "grep-able string; a date is not evidence."
                    % (cells[0], cells[1], cells[4][:60]))
            elif not cells[3]:
                err("morning-checks", "morning check %s (`%s`) was archived with a "
                                      "verdict and no `answered` date."
                    % (cells[0], cells[1]))

    was = _rows_at(base, "HANDOFF.md")
    if not was:
        return
    # A SET let two rows sharing a key cover for each other, and the docstring above
    # says three live rows already share a due date and a lane - a 40-character prefix
    # collision is ordinary here, not exotic. Count them.
    import collections as _c
    live = _c.Counter(_row_key(c) for c in (_morning_rows("HANDOFF.md") or []))
    live += _c.Counter(_row_key(c) for c in (_morning_rows("docs/morning-checks.md") or []))
    for kk, n in _c.Counter(_row_key(c) for c in was).items():
        if live[kk] < n:
            cells = next(c for c in was if _row_key(c) == kk)
            err("morning-checks", "morning check %s (`%s`) was in HANDOFF.md at %s and is "
                                  "now in neither HANDOFF.md nor docs/morning-checks.md. "
                                  "Answer it, or move it VERBATIM to the archive: a "
                                  "prediction is not withdrawn by deleting it - %s"
                % (cells[0], cells[1], base, cells[2][:60]))



def _lane_names() -> set:
    path = os.path.join(ROOT, "docs", "AGENT_BRIEF.md")
    if not os.path.exists(path):
        return set()
    return set(re.findall(r"^\| \*\*`([a-z-]+)`\*\*", read(path), re.M))


def _is_a_real_date(s: str) -> bool:
    """`2026-13-45` passes a `\\d{4}-\\d\\d-\\d\\d` shape check and sorts after a real
    date. Only the calendar knows."""
    import datetime
    try:
        datetime.datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False



def _days_between(a: str, b: str) -> int:
    """Whole days from ISO date `a` to ISO date `b`; negative when `b` is earlier."""
    import datetime
    fmt = "%Y-%m-%d"
    return (datetime.datetime.strptime(b, fmt) - datetime.datetime.strptime(a, fmt)).days


def _today() -> str:
    """UTC, not local. Every cron, every stage stamp and every digest date in this repo is
    UTC; on an Israeli clock (+03:00) a local `today` reads a check as not-yet-due for the
    first three hours after it actually came due."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def check_session_record_dates() -> None:
    """A session file whose H1 date disagrees with its own filename. Three do:
    2026-08-24-{infra,render,roles}.md all open `# 2026-08-25`, because the lane-spawn
    prompt hard-codes `docs/sessions/2026-08-24-{lane}.md`. A warning, not an error: the
    rename touches ~24 citations and belongs to whoever is doing that pass."""
    for p in sorted(glob.glob(os.path.join(ROOT, "docs", "sessions", "*.md"))):
        fn = re.match(r"(\d{4}-\d\d-\d\d)", os.path.basename(p))
        if not fn:
            continue
        first = read(p).splitlines()[0] if read(p).splitlines() else ""
        h1 = re.search(r"(\d{4}-\d\d-\d\d)", first)
        if h1 and h1.group(1) != fn.group(1) and "→" not in first:
            warn("sessions", "%s opens with %s. The lane-spawn prompt hard-codes the date in "
                             "that path, which is why three files are a day out."
                 % (rel(p), h1.group(1)))

# ---------------------------------------------------------------- 6b. the backlog index
def _backlog():
    """docs/backlog.py as a module. It is a script, like this one; import it by path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backlog_tool", os.path.join(ROOT, "docs", "backlog.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_backlog() -> None:
    """The index at the top of docs/BACKLOG.md must be a faithful regeneration.

    Same contract as docs/MODULES.md: the file is generated, so a hand-edit is discarded by
    the next run and a number in it cannot be fixed in place. The lane check can be an ERROR
    on day one because it is green on HEAD by construction - `unassigned` is grandfathered
    and the count is printed on the first screen of the file, so the set can only shrink.
    """
    path = os.path.join(ROOT, "docs", "backlog.py")
    if not os.path.exists(path):
        return
    try:
        bl = _backlog()
        items = bl.parse()
    except Exception as e:                                    # noqa: BLE001
        err("backlog", "docs/backlog.py could not parse docs/BACKLOG.md (%s: %s)"
            % (type(e).__name__, e))
        return
    ok, why = bl.index_is_current()
    if not ok:
        err("backlog", why)
    lanes = _lane_names()
    for i in items:
        if lanes and i.lane not in lanes and i.lane != "unassigned":
            err("backlog", "docs/BACKLOG.md item %d names lane `%s`, which is not in "
                           "docs/AGENT_BRIEF.md's table. An item addressed to a lane that "
                           "does not exist is addressed to nobody." % (i.num, i.lane))
    held = [i for i in items if i.bullet_closed]
    if held:
        err("backlog", "%d items are closed only by a later section's bullet, with the "
                       "ORIGINAL NEVER EDITED, so a reader going top-down still files work "
                       "against them: %s. Paste the file's own marker - `**CLOSED "
                       "<date>**` - into the item's first two lines; the bullet may stay."
            % (len(held), ", ".join(i.key for i in held[:8])))
    unlaned = [i for i in items if not i.closed and i.lane == "unassigned"]
    if unlaned:
        err("backlog", "%d open items name no lane: an item addressed to nobody is the "
                       "state item 243 describes. Add `lane: `x`` to the item body - the "
                       "brief's table decides, and `python docs/backlog.py lane <x>` is how "
                       "a session finds its own work." % len(unlaned))


# ---------------------------------------------------------------- 6c. the tree itself
# The docs this file certifies are the docs in the tree it runs in, and nothing said so.
# The shared checkout on the operator's machine - the one whose CLAUDE.md is injected into
# every session on this machine - was 146 commits behind origin/master, claiming 846
# companies against a true 1,071 and 36 of 80 continue-on-error steps against 42 of 87,
# while `--facts` printed `coe_ratio ... ok` for all four of its sites. It was telling the
# truth: those numbers do match THAT tree's workflows. A green docs check on a stale tree
# certifies the stale tree.
CERTIFIED_DOCS = ["CLAUDE.md", "README.md", "ARCHITECTURE.md", "HANDOFF.md", "docs/"]
TREE_STALE_HOURS = 24


def _rebase_in_progress() -> bool:
    for what in ("rebase-merge", "rebase-apply"):
        p = (_git("rev-parse", "--git-path", what) or "").strip()
        if p and os.path.exists(os.path.join(ROOT, p)):
            return True
    return False


def _origin_fetch_age_hours():
    """Hours since this repo last fetched, or None. Read from the COMMON dir, so a worktree
    sees the fetch its parent repo did."""
    import time
    common = (_git("rev-parse", "--git-common-dir") or "").strip()
    if not common:
        return None
    p = os.path.join(ROOT, common, "FETCH_HEAD")
    if not os.path.isabs(p):
        p = os.path.join(ROOT, common, "FETCH_HEAD")
    if not os.path.exists(p):
        return None
    return (time.time() - os.path.getmtime(p)) / 3600.0


def tree_state():
    """(commits behind, the certified docs that differ, hours since the merge-base, fetch age)
    or None when there is nothing to compare against.

    Never fetches. A linter that reaches the network is one a lane learns to skip, and ten
    concurrent sessions would contend on the ref lock; the fetch belongs to the session-start
    hook, which is allowed to be slow and is allowed to fail."""
    import time
    if os.environ.get("GITHUB_ACTIONS"):
        return None                    # CI builds the commit that was pushed, shallowly
    if _git("rev-parse", "--is-inside-work-tree") is None or _rebase_in_progress():
        return None
    if _git("rev-parse", "-q", "--verify", "origin/master") is None:
        return None
    behind = _git("rev-list", "--count", "HEAD..origin/master")
    if behind is None:
        return None
    behind = int(behind.strip() or 0)
    base = (_git("merge-base", "HEAD", "origin/master") or "").strip()
    age = None
    if base:
        when = _git("log", "-1", "--format=%ct", base)
        if when and when.strip().isdigit():
            age = (time.time() - int(when.strip())) / 3600.0
    differ = []
    for doc in CERTIFIED_DOCS:
        if _git("diff", "--quiet", "HEAD", "origin/master", "--", doc) is None:
            differ.append(doc)
    return behind, differ, age, _origin_fetch_age_hours()


def check_tree_is_current() -> None:
    """This checkout is the thing being certified; say so when it is not master's.

    ERROR is deliberately NOT "behind by one". Every lane's push touches `HANDOFF.md`, so
    "the docs differ" alone would be red for nine sessions every time a tenth pushed, and a
    linter that cries wolf gets skipped - this file's own header says so. What is never
    innocent is a checkout whose merge-base is a DAY old: nobody is mid-task on a branch cut
    yesterday, and that is the shape of the shared checkout that was 146 behind."""
    state = tree_state()
    if state is None:
        return
    behind, differ, base_age, fetch_age = state
    # The ERROR needs a FRESH fetch behind it: `behind` is measured against a LOCAL ref,
    # so the staler the fetch the greener this got - the exact shape of the failure it
    # was written for.
    fresh = fetch_age is not None and fetch_age <= TREE_STALE_HOURS
    if behind and differ and fresh and base_age is not None and base_age > TREE_STALE_HOURS:
        err("tree", "this checkout is %d commit(s) behind origin/master, its merge-base is "
                    "%.0f hours old, and the docs this check certifies differ from master's "
                    "(%s). A green docs check on a stale tree certifies the stale tree: the "
                    "shared checkout was 146 behind, claiming 846 companies against 1,071, "
                    "with every registered fact `ok`. Rebase, or cut the worktree from "
                    "origin/master." % (behind, base_age, ", ".join(differ)))
    elif behind and differ:
        warn("tree", "this checkout is %d commit(s) behind origin/master and %s differ(s) "
                     "from master's. Fine mid-session; read a number off master, not off "
                     "here." % (behind, ", ".join(differ)))
    elif behind:
        warn("tree", "this checkout is %d commit(s) behind origin/master (code and state "
                     "only; the certified docs are master's)." % behind)
    if not behind and (fetch_age is None or fetch_age > TREE_STALE_HOURS):
        warn("tree", "origin/master was last fetched %s, so `0 behind` is only as good "
                     "as that fetch. `git fetch origin master`."
             % ("%.0f hours ago" % fetch_age if fetch_age is not None else "never, here"))



# ---------------------------------------------------------------- 6d. unattended proof
# "Verified by its output, not its exit code" never said WHOSE output, so a local run
# satisfied it. `enrich_scrape_jd.py` ran 3 seconds of a 30-minute budget and filled 0 on
# the 2026-08-29 digest - green - and every session on that lane reported done.
RUN_ID = re.compile(r"\brun\s+(\d{9,})\b")
WORKFLOW_FILE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")


def check_unattended_proof() -> None:
    """A branch that changes a SCHEDULED workflow must name the morning its run is read.

    Deliberately narrow. It fires only on a workflow file that actually carries a
    `schedule:` trigger, and it is satisfied by either a NEW morning-check row due today or
    later. (An earlier draft also accepted a HANDOFF line citing `run <id>`; simulation
    showed an unrelated answered verdict satisfied it.) It is NOT extended to the modules
    `docs/MODULES.md` classes `scheduled` - `auto_expand.py` and its neighbours change most
    days, and a check that fires on every registry commit is one the registry lane would
    learn to route around within a week.

    Measured before shipping: of the 11 commits touching `.github/workflows/` since the
    morning-check table existed (2026-08-27), 4 added a row in the same commit and 7 did
    not - and one of those 7 is the 19:00 drain whose own HANDOFF entry says "the cron has
    not run"."""
    base = _git("merge-base", "HEAD", "origin/master")
    if base is None or os.environ.get("GITHUB_ACTIONS"):
        return
    base = base.strip()
    changed = _git("diff", "--name-only", "%s...HEAD" % base)
    if changed is None:
        return

    def _substantive(name):
        """True when the branch changed something other than comments and blank lines.

        Fixing a typo in a comment should not cost a prediction, and a check that
        charges for one is a check the owning lane routes around."""
        d = _git("diff", "-U0", "%s...HEAD" % base, "--", name) or ""
        for ln in d.splitlines():
            if ln[:1] in "+-" and not ln.startswith(("+++", "---")):
                body = ln[1:].strip()
                if body and not body.startswith("#"):
                    return True
        return False
    touched = []
    for name in changed.splitlines():
        name = name.strip().replace("\\", "/")
        if not WORKFLOW_FILE.match(name):
            continue
        path = os.path.join(ROOT, name)
        # A DELETED scheduled workflow needs its proof too, and has no working copy
        # left to read - take the blob from the baseline.
        text = read(path) if os.path.exists(path) else (_git("show", "%s:%s" % (base, name)) or "")
        if re.search(r"^\s*schedule:", text, re.M) and _substantive(name):
            touched.append(name)
    if not touched:
        return
    today = _today()
    was = {_row_key(c) for c in (_rows_at(base, "HANDOFF.md") or [])}
    for cells in (_morning_rows("HANDOFF.md") or []):
        # A row due 2099 satisfied "due >= today" and never even warned. Bound it to the
        # window in which its run will actually have happened.
        if (_row_key(cells) not in was and cells[0] >= today
                and _days_between(today, cells[0]) <= UNATTENDED_MAX_DAYS):
            return
    err("unattended", "%s changed on this branch and HANDOFF.md gained no new "
                      "morning-check row due on or after %s. A change to a scheduled step "
                      "is finished when the date its UNATTENDED run will be read is written "
                      "down - dispatching it yourself is not that, and a run that has "
                      "already produced its number is still a row: due today, answered "
                      "today, the id in the verdict (docs/AGENT_BRIEF.md, Definition of "
                      "done)." % (", ".join(touched), today))



# ---------------------------------------------------------------- 6e. no home directories
# The public repo's anonymity rests entirely on the owner's account never being linkable to
# it, and four tracked docs spelled the operator's home directory - one of them beside the
# org's own name. Archives are otherwise never edited; a privacy fix is the exception.
HOME_PATH = re.compile(r"(?:[A-Za-z]:\\Users\\|/Users/|/home/|C--Users-)(?!<home>)[A-Za-z0-9._-]+")


def check_no_home_paths() -> None:
    """A tracked document may not name a real person's home directory.

    Deliberately an ERROR and deliberately over ARCHIVES too - unlike every other archive
    rule, because the cost is not staleness. `<home>` is the placeholder the four redacted
    docs use, and the pattern lets it through."""
    for doc in docs():
        for m in HOME_PATH.finditer(read(doc)):
            err("privacy", "%s names a home directory (%r). The public repo must not be "
                           "linkable to the owner's account (CLAUDE.local.md) - write "
                           "`C:\\<home>\\...` or `~/...` instead."
                % (rel(doc), m.group(0)[:40]))



# ---------------------------------------------------------------- 7. entry points exist
def check_entry_docs() -> None:
    for name in ("CLAUDE.md", "README.md", "ARCHITECTURE.md", "HANDOFF.md",
                 "docs/AGENT_BRIEF.md", "docs/MODULES.md", "docs/BACKLOG.md"):
        if not os.path.exists(os.path.join(ROOT, name)):
            err("entry", "%s is missing - it is one of the seven docs every reader is sent to" % name)


CHECKS = [check_tree_is_current, check_entry_docs, check_paths_exist, check_links, check_section_refs,
          check_module_registry,
          check_schedule_table, check_derived_facts, check_scope_claims, check_handoff,
          check_morning_checks, check_morning_rows_survive, check_session_record_dates,
          check_backlog]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--fix" in argv:
        # EXACT facts only, and never reachable from the no-argument path the test suite
        # invokes.  alone is a dry run;  writes.
        return fix_facts(apply="--apply" in argv)
    if "--tree" in argv:
        # The one path allowed to fetch, and it is never reachable from the no-argument
        # path the test suite and the pre-push contract invoke.
        if "--fetch" in argv:
            _git("fetch", "-q", "--no-tags", "origin", "master")
        state = tree_state()
        if state is None:
            print("tree: nothing to compare against (no origin/master, CI, or not a repo)")
            return 0
        behind, differ, base_age, fetch_age = state
        print("tree: %d behind origin/master | certified docs differing: %s | merge-base "
              "%s | fetched %s"
              % (behind, ", ".join(differ) or "none",
                 "%.0fh old" % base_age if base_age is not None else "unknown",
                 "%.0fh ago" % fetch_age if fetch_age is not None else "unknown"))
        return 0

    if "--facts" in argv:
        # One command instead of an archaeology dig: every registered number, what the
        # code says today, and what each doc claims. Never writes; never exits non-zero
        # on drift alone -- run the check itself for that.
        return report_facts()
    for check in CHECKS:
        check()
    for w in WARNINGS:
        print("WARN  " + w)
    for e in ERRORS:
        print("ERROR " + e)
    print("\ndocs check: %d error(s), %d warning(s) over %d documents"
          % (len(ERRORS), len(WARNINGS), len(docs())))
    if ERRORS:
        print("The docs and the code disagree. Fix the doc, or fix the code - but not by "
              "deleting the check.")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
