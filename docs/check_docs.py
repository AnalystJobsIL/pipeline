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
        txt = read(w)
        for m in names:
            if re.search(r"python3?\s+(?:-u\s+)?" + re.escape(m) + r"\.py\b", txt):
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
    """FETCHERS keys by AST, never by import. Importing from a linter is a side effect
    waiting to happen - several modules in this repo execute on import."""
    tree = ast.parse(read(os.path.join(ROOT, "pipeline", "fetchers.py")))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "FETCHERS" for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise RuntimeError("pipeline/fetchers.py has no top-level FETCHERS dict literal")


def _real_platforms() -> int:
    return len([k for k in _fetcher_keys() if k not in ("scrape", "discovery")])


def _no_main_guard() -> int:
    return sum(1 for p in sorted(glob.glob(os.path.join(ROOT, "*.py")))
               if "__main__" not in read(p))


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
_CENSUS = r"(~?[\d,]+(?:[-–][\d,]+)?)"

FACTS = [
    Fact("coe_ratio", "exact", _coe_ratio, "continue-on-error of workflow steps",
         [("CLAUDE.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+workflow steps"),
          ("ARCHITECTURE.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+workflow steps"),
          ("docs/AGENT_BRIEF.md", r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+workflow steps")],
         "this is the number that tells a reader a green run proves nothing"),

    Fact("fetcher_platforms", "exact", lambda: (_real_platforms(),),
         "real ATS platforms in FETCHERS",
         [("ARCHITECTURE.md", r"pipeline/fetchers\.py\s+(\d+) platforms"),
          ("docs/AGENT_BRIEF.md", r"\((\d+) platforms[,)]"),
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
          ("docs/AGENT_BRIEF.md", r"the (\d+) unreferenced root modules")],
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
_VETO_RE = re.compile(r"https?://\S+|\]\([^)]*\)|<!--.*?-->", re.S)


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
    return _round_half_up(true_value, precision(tok)) == _int(tok)


def census_span(tok: str):
    """The closed interval a census token claims, or None if it claims a bare point value.
    A bare number is the one form that is always wrong here, so it gets no interval."""
    parts = re.split(r"[-–]", tok)
    if len(parts) == 2 and parts[0] and parts[1]:
        lo, hi = _int(parts[0]), _int(parts[1])
        return (lo, hi) if lo <= hi else (hi, lo)
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
                    span = census_span(toks[0])
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
                warn("facts", "%s: a site registered for %s matches nothing now (%s). If the "
                              "sentence was rewritten for the better, drop the site."
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


# ---------------------------------------------------------------- 6. HANDOFF shape
HANDOFF_MAX_LINES = 250
HANDOFF_REQUIRED = ["## State at handoff", "## Watch list", "## Open items"]


def check_handoff() -> None:
    path = os.path.join(ROOT, "HANDOFF.md")
    if not os.path.exists(path):
        err("handoff", "HANDOFF.md is missing")
        return
    text = read(path)
    n = len(text.splitlines())
    if n > HANDOFF_MAX_LINES:
        err("handoff", "HANDOFF.md is %d lines (cap %d). It is the CURRENT-STATE file: move "
                       "dated narrative to docs/sessions/<date>.md, durable rules to "
                       "ARCHITECTURE.md, and known gaps to docs/BACKLOG.md."
            % (n, HANDOFF_MAX_LINES))
    for required in HANDOFF_REQUIRED:
        if required not in text:
            err("handoff", "HANDOFF.md has no `%s` section" % required)


# ---------------------------------------------------------------- 7. entry points exist
def check_entry_docs() -> None:
    for name in ("CLAUDE.md", "README.md", "ARCHITECTURE.md", "HANDOFF.md",
                 "docs/AGENT_BRIEF.md", "docs/MODULES.md", "docs/BACKLOG.md"):
        if not os.path.exists(os.path.join(ROOT, name)):
            err("entry", "%s is missing - it is one of the seven docs every reader is sent to" % name)


CHECKS = [check_entry_docs, check_paths_exist, check_links, check_section_refs,
          check_module_registry,
          check_schedule_table, check_derived_facts, check_handoff]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
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
