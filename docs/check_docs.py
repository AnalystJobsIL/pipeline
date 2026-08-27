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
#   CENSUS  moves because eight cron jobs ran (active rows, scrape rows, profiles). No
#           session causes the move, so equality punishes the innocent. Measured from git,
#           one snapshot per day, active went 530 -> 754 -> 862 -> 877 -> 870 -> 875: an
#           equality check seeded on the day the docs were written would have been RED ON
#           3 OF THE NEXT 3 DAYS, and a linter that cries wolf gets `# noqa`'d.
#           A census site therefore may not carry a bare point number at all. It carries a
#           BRACKET, and the precision the author writes IS the tolerance they are claiming:
#           `~1,200` claims "round to the nearest hundred", `~870` claims "to the nearest
#           ten". No tolerance number lives in this file - the notation English already uses
#           is the machine-readable contract. Over the same six days, precision-100
#           brackets are green on every census fact on every day, including the +108 one.
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


def _firmographics() -> int:
    import json as _json
    return len(_json.loads(read(os.path.join(ROOT, "cloud_state", "firmographics.json"))))


# The one shape a census claim may take. Three readings, checked differently:
#   `875`            BARE   - always an error; it will be wrong within a day
#   `~900`           BRACKET - true if rounding today's value to the precision the author
#                    wrote lands on it. `~1,200` claims hundreds, `~870` claims tens.
#   `850-950`        RANGE  - true if today's value is inside it, ends included.
# The range exists because a bracket's headroom depends on where in the bracket you sit,
# and two of the five census facts measured on 2026-08-27 were within 5 of an edge
# (registry 1,244 against `~1,200`; API rows 451 against `~500`). A range lets the author
# state the headroom they want instead of inheriting whatever the boundary gives them.
# The lookaround is load-bearing: without it `the 2026-08-27 company profiles pass`
# captured `08-27` as the range 8-27, and `registry of 2026-08 rows` as a 2,000-wide
# bracket that would pass anything.
_CENSUS = r"(?<![\d,\-–])(~?\d[\d,]*(?:[-–]\d[\d,]*)?)(?![\d\-–])"

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

    Fact("firmographics_profiles", "census", lambda: (_firmographics(),),
         "company profiles in cloud_state/firmographics.json",
         [("docs/AGENT_BRIEF.md", _CENSUS + r" company profiles")],
         "the company-intel lane's coverage - the brief said 926 while the file held 973"),
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
    return int(tok.replace(",", "").lstrip("~"))


def precision(tok: str) -> int:
    """The tolerance the author claimed, read off the trailing zeros they wrote:
    `~1,200` -> 100, `~870` -> 10, `~875` -> 1. That is the entire tolerance model, and it
    lives in the notation the reader can already see rather than in a config in this file."""
    digits = tok.replace(",", "").lstrip("~")
    if not digits.isdigit() or not digits:
        return 1
    zeros = len(digits) - len(digits.rstrip("0"))
    # A number can never claim a tolerance wider than its own leading digit: `~1,000`
    # claims thousands, not ten-thousands.
    return min(10 ** zeros, 10 ** (len(digits) - 1))


def _round_half_up(n: int, prec: int) -> int:
    """Explicit half-up. Python's round() is banker's - round(850, -2) is 800 - so `~900`
    would be wrong for 850 and right for 851. A doc contract must not hinge on that."""
    return ((n + prec // 2) // prec) * prec


def bracket_holds(true_value: int, tok: str) -> bool:
    """Defined in terms of census_span so the tested function IS the running one. It used to
    be an independent implementation reached only from the test suite, and the two disagreed
    on the form that matters: `bracket_holds(875, "875")` was True while `census_span("875")`
    is None, which is the bare-number error."""
    span = census_span(tok)
    return span is not None and span[0] <= true_value <= span[1]


def census_span(tok: str):
    """The closed interval a census token claims, or None if it claims a bare point value.
    A bare number is the one form that is always wrong here, so it gets no interval."""
    parts = re.split(r"[-–]", tok)
    if len(parts) == 2 and parts[0].strip("~") and parts[1]:
        lo, hi = _int(parts[0]), _int(parts[1])
        if lo > hi:
            raise ValueError("range is written backwards: %s" % tok)
        return (lo, hi)
    if len(parts) > 2:
        raise ValueError("a census range has two ends, not %d: %s" % (len(parts), tok))
    if not tok.startswith("~"):
        return None
    p, n = precision(tok), _int(tok)
    return (n - p // 2, n + (p - p // 2) - 1)


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
                    try:
                        span = census_span(toks[0])
                    except ValueError as e:                       # noqa: PERF203
                        rows.append((doc_rel, line, ", ".join(toks), False,
                                     "unreadable: %s" % e))
                        continue
                    if span is None:
                        ok, note = False, "bare"
                    else:
                        ok = span[0] <= got[0] <= span[1]
                        note = "" if ok else "today %d, outside %d-%d" % (got[0], *span)
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
            elif note == "bare":
                err("facts", "%s:%d states %s (%s) as the bare number %s. This one moves "
                             "because the crons ran, not because anyone pushed, so it cannot "
                             "be held to equality and will be wrong within a day. Write the "
                             "range you are willing to stand behind - `%s` is true today - "
                             "or replace it with the command that prints it."
                    % (doc_rel, line, f.name, f.unit, tok,
                       "{:,}-{:,}".format(_round_half_up(got[0], 100) - 50,
                                          _round_half_up(got[0], 100) + 50)))
            elif not ok and f.kind == "exact":
                err("facts", "%s:%d says %s for %s (%s); the code says %s. %s."
                    % (doc_rel, line, tok, f.name, f.unit,
                       ", ".join(str(g) for g in got), f.why))
            elif note.startswith("unreadable"):
                err("facts", "%s:%d states %s for %s as a token this check cannot read (%s). "
                             "Write `~N`, or `N-M`, or the command that prints it."
                    % (doc_rel, line, tok, f.name, note))
            elif not ok:
                lo, hi = census_span(tok)
                err("facts", "%s:%d writes %s for %s (%s), which claims %d-%d; today it is "
                             "%d. Widen it or move it."
                    % (doc_rel, line, tok, f.name, f.unit, lo, hi, got[0]))
            elif f.kind == "census":
                lo, hi = census_span(tok)
                edge = min(got[0] - lo, hi - got[0])
                width = hi - lo + 1
                if width > 1 and edge <= max(1, width // 10):
                    warn("facts", "%s:%d writes %s for %s (holds for %d-%d); today %d, %d "
                                  "from the edge. It will go red on its own soon - widen it "
                                  "now, while you are here and it is still true."
                         % (doc_rel, line, tok, f.name, lo, hi, got[0], edge))
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
    r"^(?:PASS|FAIL|N/A|PARTIAL|INCONCLUSIVE|SKIPPED)\b[^:,\u2013\u2014-]*"
    r"[:,\u2013\u2014-]\s*\S.{9,}$|^not yet due\b.*$", re.I)
_LOOSE_CHECK = re.compile(r"morning check\s+\d{4}-\d\d-\d\d", re.I)
NL_SAFE = "\n"


def check_morning_checks() -> None:
    """A prediction about tomorrow's mail is not finished until it has an answer.

    Fourteen `Morning check <date>:` sentences were buried in HANDOFF.md's prose and NOT ONE
    had ever been answered. Two had already failed in public twice: `### Tel Aviv` and
    `### Jobgether` both shipped as employer headings in the 2026-08-26 mail against checks
    that said neither would.

    An unanswered check is a WARNING, deliberately, and this is the reasoning a future
    session should read before 'tightening' it: `discovery` writes the check on Tuesday and
    it comes due while `jd-text` is pushing on Wednesday. An ERROR would punish the wrong
    agent, and the cheapest way for that agent to go green would be to DELETE the check —
    the linter would then destroy the mechanism it exists to protect. The shape of a row IS
    an error, because that is the pushing session's own work."""
    path = os.path.join(ROOT, "HANDOFF.md")
    if not os.path.exists(path):
        return
    text = read(path)
    # Collect every pipe row from the table header to the next `## ` heading. Stopping at
    # the first non-pipe line meant ONE blank line - or an HTML comment between rows -
    # silently dropped every row below it, and the check only complained when zero rows
    # survived. In the live table that is 20 of 21 predictions, with a green build.
    rows, in_table = [], False
    for line in text.splitlines():
        if line.startswith("| due | lane |"):
            in_table = True
            continue
        if in_table:
            if line.startswith("## "):
                in_table = False
                continue
            if not line.startswith("|"):
                continue
            # split on the pipes, never strip them: an EMPTY last cell - which is exactly
            # what an unanswered check looks like - is swallowed by strip("|") and the
            # row then fails the len() test and is silently dropped. Found by break-test.
            cells = [c.strip() for c in line.strip().split("|")[1:-1]]
            if set(cells[0]) <= set("-: "):
                continue
            if len(cells) != 5:
                # A `|` inside a cell shifts every column right, so the verdict is read from
                # the wrong one and a real verdict is never validated. The `must be true`
                # column is full of backticked shell text, so this is one `| wc -l` away.
                err("morning-checks", "a morning-check row has %d cells, not 5 - a `|` inside "
                                      "a cell shifts the verdict column: %s"
                    % (len(cells), line.strip()[:80]))
                continue
            rows.append(cells)
    if not rows:
        warn("morning-checks", "HANDOFF.md has no `## Morning checks` table. A prediction "
                               "with nowhere to be answered is how `### Tel Aviv` shipped "
                               "twice against a check that said it would not.")
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
        if verdict in ("", "—", "-"):
            if due <= today:
                warn("morning-checks", "morning check due %s (`%s`) has no verdict: %s"
                     % (due, lane, must[:70]))
        elif verdict.lower().startswith("not yet due") and due <= today:
            warn("morning-checks", "morning check %s (`%s`) still says `not yet due`, and %s "
                                   "has passed. It is a supported way to answer a check by "
                                   "never answering it." % (due, lane, due))
        elif not _VERDICT_OK.match(verdict):
            err("morning-checks", "morning check %s (`%s`) has a verdict the reader cannot "
                                  "check: %r. Use PASS / FAIL - <what happened> / N/A - "
                                  "<why>, and quote a grep-able string, not an adjective."
                % (due, lane, verdict[:60]))
    # Scan the WHOLE file, minus the table's own rows. The first version stopped at the
    # table header, so a session appending a prose check BELOW the table - which is where
    # a session appends things - was invisible to the check written to catch exactly that.
    body = NL_SAFE.join(l for l in text.splitlines() if not l.startswith("| "))
    for m in _LOOSE_CHECK.finditer(body):
        err("morning-checks", "HANDOFF.md states a morning check in prose (%r). Fourteen of "
                              "those existed and none was ever answered - put it in the "
                              "table, with the date you will answer it."
            % body[m.start():m.start() + 40])


def _lane_names() -> set:
    path = os.path.join(ROOT, "docs", "AGENT_BRIEF.md")
    if not os.path.exists(path):
        return set()
    return set(re.findall(r"^\| \*\*`([a-z-]+)`\*\*", read(path), re.M))


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
        warn("backlog", "%d items are closed by a later section's bullet with the ORIGINAL NEVER EDITED, so a reader going top-down still files work against them: %s"
             % (len(held), ", ".join(i.key for i in held[:8])))
    unlaned = [i for i in items if not i.closed and i.lane == "unassigned"]
    if unlaned:
        warn("backlog", "%d open items name no lane. A new item may not join them - `python docs/backlog.py next` prints the number to use." % len(unlaned))


# ---------------------------------------------------------------- 7. entry points exist
def check_entry_docs() -> None:
    for name in ("CLAUDE.md", "README.md", "ARCHITECTURE.md", "HANDOFF.md",
                 "docs/AGENT_BRIEF.md", "docs/MODULES.md", "docs/BACKLOG.md"):
        if not os.path.exists(os.path.join(ROOT, name)):
            err("entry", "%s is missing - it is one of the seven docs every reader is sent to" % name)


CHECKS = [check_entry_docs, check_paths_exist, check_links, check_section_refs,
          check_module_registry,
          check_schedule_table, check_derived_facts, check_handoff,
          check_morning_checks, check_session_record_dates,
          check_backlog]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--fix" in argv:
        # EXACT facts only, and never reachable from the no-argument path the test suite
        # invokes.  alone is a dry run;  writes.
        return fix_facts(apply="--apply" in argv)
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
