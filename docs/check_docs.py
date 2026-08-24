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
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "out", "node_modules", ".venv"}


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

    importers, runners = import_graph()
    live = {m for m, k in klass_of.items() if k in ("scheduled", "library", "operator")}
    for m, k in sorted(klass_of.items()):
        if m not in roots:
            continue
        if k == "scheduled" and not runners.get(m):
            err("modules", "`%s.py` is classified `scheduled` but no workflow runs it" % m)
        if k == "library" and not importers.get(m):
            err("modules", "`%s.py` is classified `library` but nothing imports it" % m)
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


# ---------------------------------------------------------------- 5. continue-on-error
def check_continue_on_error() -> None:
    steps = coe = 0
    for w in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        txt = read(w)
        steps += len(re.findall(r"^\s*- name:", txt, re.M))
        coe += len(re.findall(r"^\s*continue-on-error:\s*true", txt, re.M))
    claim = re.compile(r"(\d+)\s+of\s+(?:the\s+)?(\d+)\s+workflow steps", re.I)
    seen_any = False
    for doc in docs():
        for m in claim.finditer(read(doc)):
            seen_any = True
            if (int(m.group(1)), int(m.group(2))) != (coe, steps):
                err("continue-on-error",
                    "%s says %s of %s workflow steps are continue-on-error; the workflows say "
                    "%d of %d. Update the sentence (this is the number that tells a reader a "
                    "green run proves nothing)." % (rel(doc), m.group(1), m.group(2), coe, steps))
    if not seen_any:
        warn("continue-on-error",
             "no doc states the continue-on-error ratio (%d of %d). It is the single most "
             "load-bearing fact about reading a green run here." % (coe, steps))


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
          check_schedule_table, check_continue_on_error, check_handoff]


def main() -> int:
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
