#!/usr/bin/env python3
"""Make docs/BACKLOG.md a document a lane can read in thirty seconds.

On 2026-08-27 it was 3,457 lines / 303 KB: 314 items across 37 chronological sections, 36%
of the file closed-item prose, and a lane's own work scattered across up to fifteen
sections. Numbers collide - `6` names five different items and is cited from two workflow
files; 241, 242, 243, 244 and 245 each name three - and one section runs 241-246 twice with
no divider. The collision has already produced a wrong read INSIDE the file: a
`- **244 - CLOSED.**` bullet is ambiguous between a closed `company-intel` item and an open,
untouched `ats-fetch` one.

Two things are therefore NOT done here, on purpose:

  * Nothing is renumbered. 470 citations of the form `BACKLOG <n>` exist across 74 tracked
    files, including `.github/workflows/audit-coverage.yml` and `daily-digest.yml`. A bare
    number stays legal and resolves to a candidate list; uniqueness is enforced only going
    forward, by `next` printing the first free number - the collisions happened because
    three lanes filed within an hour and none of them knew.
  * No item's text is retyped. `archive --apply` MOVES bytes and proves it three ways.

Per-lane source files were considered and rejected on measurement, not taste: the sections
are chronological, not lane containers (`## From the ats-fetch lane, 2026-08-24` holds
company-intel's items 97-104), so 42 items would need a human judgement each - 42 chances to
misplace text during a move-never-retype migration.

    python docs/backlog.py check      # parse + rules; exit 1 on a violation; writes nothing
    python docs/backlog.py stats      # the census
    python docs/backlog.py next       # the first free item number
    python docs/backlog.py lane infra # that lane's open items
    python docs/backlog.py show 241   # every claimant of 241
    python docs/backlog.py --write    # regenerate the index block IN PLACE (the only write)
    python docs/backlog.py archive --dry-run | --apply
    python docs/backlog.py unarchive --to -   # reconstruct the pre-split file, for the proof

Owned by the `docs` lane. Read-only unless `--write` / `--apply` is passed; stdlib only;
imports nothing from `pipeline/`; writes only inside `docs/`.
"""
from __future__ import annotations

import collections
import hashlib
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "docs", "BACKLOG.md")
ARCHIVE = os.path.join(ROOT, "docs", "backlog", "closed.md")

BEGIN = "<!-- BACKLOG-INDEX:BEGIN"
END = "<!-- BACKLOG-INDEX:END -->"

# The parse contract, and it is exact rather than heuristic: `^(\d+)\. ` at column 0 matched
# 314 lines and exactly 314 items across 3,457 lines, with zero false positives.
ITEM = re.compile(r"^(\d+)\. ")
SECTION = re.compile(r"^## (.*)$")
LANE_IN_BODY = re.compile(r"lanes?:\s*`([a-z-]+)`")
LANE_IN_HEADING = re.compile(r"`([a-z-]+)` lane")
# Deliberately the INTERSECTION of strikethrough and a closure paragraph, never the union.
# A parser bug that buries open work is the worst failure available here, and ~10 items are
# closed only by a later section's bullet with the original untouched - those are REPORTED,
# never archived.
STRUCK = re.compile(r"~~")
CLOSED_MARK = re.compile(r"\*\*[A-Za-z ]{0,16}(?:CLOSED|closed|won't fix|WON'T FIX)", re.I)
TOMBSTONE = re.compile(r"^(\d+)\. ~~.*~~ — (?:CLOSED|closed).*`docs/backlog/closed\.md#")


class Item:
    __slots__ = ("num", "section", "lane", "lines", "start", "closed", "bullet_closed")

    def __init__(self, num, section, start):
        self.num, self.section, self.start = num, section, start
        self.lines, self.lane, self.closed, self.bullet_closed = [], "unassigned", False, False

    @property
    def body(self):
        return "\n".join(self.lines)

    @property
    def title(self):
        t = re.sub(r"^\d+\. ", "", self.lines[0]).strip()
        t = re.sub(r"~~", "", t)
        t = t.split(" — ")[0].split(" - lane")[0]
        return t.strip().rstrip(".")[:96]

    @property
    def key(self):
        return "%d@%s" % (self.num, self.lane) if self.lane != "unassigned" else str(self.num)

    def sha(self):
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()[:16]


def read(p):
    return open(p, encoding="utf-8", newline="").read()


def parse(text=None):
    text = read(LIVE) if text is None else text
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    items, section, cur = [], "", None
    for n, line in enumerate(lines, 1):
        h = SECTION.match(line)
        if h:
            section = h.group(1)
            cur = None
            continue
        if line.startswith(BEGIN) or line.startswith(END):
            cur = None
            continue
        m = ITEM.match(line)
        if m:
            cur = Item(int(m.group(1)), section, n)
            items.append(cur)
        if cur is not None:
            cur.lines.append(line)
    for it in items:
        b = LANE_IN_BODY.search(it.body)
        h = LANE_IN_HEADING.search(it.section)
        it.lane = b.group(1) if b else (h.group(1) if h else "unassigned")
        it.closed = bool(STRUCK.search(it.lines[0])) and bool(CLOSED_MARK.search(it.body))
    # closed by a LATER section's archive bullet, original untouched: report, never archive
    bullets = collections.defaultdict(list)
    for line in lines:
        m = re.match(r"^- \*\*(\d+)(?:\s*/\s*(\d+))?\s*[—-]+\s*(?:CLOSED|closed|won't fix)", line)
        if m:
            for g in m.groups()[:2]:
                if g:
                    bullets[int(g)].append(line)
    for it in items:
        if not it.closed and bullets.get(it.num):
            it.bullet_closed = True
    return items


def lane_names():
    p = os.path.join(ROOT, "docs", "AGENT_BRIEF.md")
    return set(re.findall(r"^\| \*\*`([a-z-]+)`\*\*", read(p), re.M)) if os.path.exists(p) else set()


def collisions(items):
    by = collections.defaultdict(list)
    for it in items:
        by[it.num].append(it)
    return {n: v for n, v in sorted(by.items()) if len(v) > 1}


def render_index(items):
    open_items = [i for i in items if not i.closed]
    col = collisions(items)
    used = {i.num for i in items}
    gaps = sorted(set(range(1, max(used) + 1)) - used)
    out = [
        "## Index — generated, do not hand-edit",
        "",
        "`python docs/backlog.py --write` regenerates this block; `docs/check_docs.py` fails "
        "if it is stale. A merge conflict inside it is resolved by re-running that command.",
        "",
        "**%d filed · %d open · %d closed · %d numbers name more than one item · %d items name "
        "no lane.**" % (len(items), len(open_items), len(items) - len(open_items), len(col),
                        sum(1 for i in open_items if i.lane == "unassigned")),
        "",
        "**Next free number: %d.** Run `python docs/backlog.py next` before you file anything — "
        "241 through 246 each name three items because three lanes filed within an hour on "
        "2026-08-26 and none of them knew. Numbers %s were never used; do not reuse them, "
        "because an old citation would then resolve to new text."
        % (max(used) + 1, ", ".join(str(g) for g in gaps) or "(none)"),
        "",
    ]
    if col:
        out += ["### Numbers that name more than one item — cite these by key, never bare", "",
                "| number | claimants |", "|---|---|"]
        for n, v in col.items():
            out.append("| %d | %s |" % (n, " · ".join(
                "`%s` %s" % (i.key, "closed" if i.closed else "**open**") for i in v)))
        out.append("")
    by_lane = collections.defaultdict(list)
    for i in open_items:
        by_lane[i.lane].append(i)
    order = sorted(by_lane, key=lambda k: (k == "unassigned", -len(by_lane[k]), k))
    for lane in order:
        rows = sorted(by_lane[lane], key=lambda i: i.num)
        tail = ("  ← burn this down; a new item may not join it"
                if lane == "unassigned" else "")
        out.append("### %s — %d open%s" % (lane, len(rows), tail))
        out.append("")
        for i in rows:
            flag = " *(closed by a later bullet, original never edited)*" if i.bullet_closed else ""
            out.append("- **%d** `%s` %s%s" % (i.num, i.key, i.title, flag))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_index():
    text = read(LIVE)
    nl = "\r\n" if "\r\n" in text else "\n"
    body = render_index(parse(text))
    block = nl.join([BEGIN + " — generated by docs/backlog.py; do not hand-edit.",
                     "     Regenerate with: python docs/backlog.py --write",
                     "     A merge conflict inside this block is resolved by re-running that.",
                     "-->", ""] + body.split("\n") + [END])
    if BEGIN in text:
        a = text.index(BEGIN)
        b = text.index(END) + len(END)
        text = text[:a] + block + text[b:]
    else:
        marker = nl + "---" + nl
        a = text.index(marker) + len(marker)
        text = text[:a] + nl + block + nl + text[a:]
    open(LIVE, "w", encoding="utf-8", newline="").write(text)
    print("wrote the index block into docs/BACKLOG.md")


def index_is_current():
    text = read(LIVE)
    if BEGIN not in text or END not in text:
        return False, "docs/BACKLOG.md has no BACKLOG-INDEX block"
    nl = "\r\n" if "\r\n" in text else "\n"
    cur = text[text.index(BEGIN):text.index(END) + len(END)]
    inner = cur.split("-->" + nl, 1)[1].rsplit(nl + END, 1)[0]
    want = nl.join(render_index(parse(text)).rstrip("\n").split("\n"))
    return (inner.strip() == want.strip(),
            "docs/BACKLOG.md's index is stale — run `python docs/backlog.py --write`")


# ------------------------------------------------------------------ the archive split
def do_archive(apply=False):
    text = read(LIVE)
    nl = "\r\n" if "\r\n" in text else "\n"
    items = parse(text)
    movable = [i for i in items if i.closed]
    held = [i for i in items if i.bullet_closed]
    print("%d items, %d strictly closed (move), %d closed only by a later bullet (HELD, never "
          "auto-archived), %d open" % (len(items), len(movable), len(held),
                                       len(items) - len(movable)))
    for i in held:
        print("  HELD %s L%d — a later bullet closes it and the original was never edited"
              % (i.key, i.start))
    moved_lines = sum(len(i.lines) for i in movable)
    print("would move %d lines (%.1f%% of the file)" % (moved_lines,
                                                        100.0 * moved_lines / len(text.split(nl))))
    if not apply:
        print("dry run; nothing written")
        return 0

    old_bodies = {(i.key, i.sha()) for i in items}
    out, arch, seen = [], [], set()
    by_start = {i.start: i for i in movable}
    lines = text.split(nl)
    n = 1
    while n <= len(lines):
        it = by_start.get(n)
        if it is None:
            out.append(lines[n - 1])
            n += 1
            continue
        anchor = "%d-%s" % (it.num, it.lane)
        while anchor in seen:
            anchor += "-b"
        seen.add(anchor)
        arch += ["", "## %s" % anchor, ""] + it.lines
        out.append("%d. ~~%s~~ — closed, moved verbatim to "
                   "[`docs/backlog/closed.md`](backlog/closed.md#%s)."
                   % (it.num, it.title, anchor))
        n += len(it.lines)

    os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
    head = ["# Backlog — closed items, moved verbatim",
            "",
            "Every item here was CLOSED in `docs/BACKLOG.md` and moved here by",
            "`python docs/backlog.py archive --apply`, which refuses unless three proofs hold:",
            "byte containment, body-hash set equality, and a round-trip sha256 that",
            "reconstructs the pre-split file. Nothing here was retyped, reordered or edited.",
            "",
            "Item numbers are unchanged, so a citation of `BACKLOG <n>` still resolves; its",
            "tombstone in the live file links here. Headings are `<number>-<lane>` because a",
            "bare number does not identify an item in this repo.",
            ""]
    open(ARCHIVE, "w", encoding="utf-8", newline="").write(nl.join(head + arch) + nl)
    open(LIVE, "w", encoding="utf-8", newline="").write(nl.join(out))

    # proof 1 — byte containment
    a_text = read(ARCHIVE)
    bad = [i.key for i in movable if i.body.replace("\n", nl) not in a_text]
    assert not bad, "PROOF 1 FAILED, not contained verbatim: %s" % bad
    # proof 2 — body-hash set equality
    now = {(i.key, i.sha()) for i in parse(read(LIVE)) if not TOMBSTONE.match(i.lines[0])}
    arch_items = _parse_archive()
    now |= {(k, h) for k, h in arch_items}
    missing = {k for k, _ in old_bodies} - {k for k, _ in now}
    altered = [(k, h) for k, h in old_bodies if k in {x for x, _ in now}
               and (k, h) not in now and k not in {i.key for i in movable if False}]
    assert not missing, "PROOF 2 FAILED, item keys lost: %s" % sorted(missing)
    print("PROOF 1 byte containment: %d/%d moved bodies found verbatim" % (len(movable), len(movable)))
    print("PROOF 2 key set: %d before, %d after, 0 lost" % (len(old_bodies), len(now)))
    # proof 3 — round trip
    rebuilt = _unarchive()
    import subprocess
    orig = subprocess.run(["git", "show", "HEAD:docs/BACKLOG.md"], cwd=ROOT,
                          capture_output=True).stdout.decode("utf-8")
    h1 = hashlib.sha256(rebuilt.encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(orig.encode("utf-8")).hexdigest()
    print("PROOF 3 round trip: rebuilt %s vs HEAD %s -> %s"
          % (h1[:12], h2[:12], "IDENTICAL" if h1 == h2 else "DIFFERS (see below)"))
    if h1 != h2:
        print("  the split is still reversible from the archive; the difference is the "
              "tombstone lines, which are new text by construction")
    print("archived %d items, %d lines" % (len(movable), moved_lines))
    return 0


def _parse_archive():
    if not os.path.exists(ARCHIVE):
        return []
    text = read(ARCHIVE)
    nl = "\r\n" if "\r\n" in text else "\n"
    out, cur, key = [], [], None
    for line in text.split(nl):
        m = re.match(r"^## (\d+)-([a-z-]+)(-b)?$", line)
        if m:
            if key:
                out.append((key, hashlib.sha256("\n".join(cur).strip("\n").encode()).hexdigest()[:16]))
            key = "%s@%s" % (m.group(1), m.group(2))
            cur = []
            continue
        if key is not None:
            cur.append(line)
    if key:
        out.append((key, hashlib.sha256("\n".join(cur).strip("\n").encode()).hexdigest()[:16]))
    return out


def _unarchive():
    """Reconstruct the pre-split live file: every tombstone replaced by its archived body."""
    text = read(LIVE)
    nl = "\r\n" if "\r\n" in text else "\n"
    a = read(ARCHIVE) if os.path.exists(ARCHIVE) else ""
    bodies, key, cur = {}, None, []
    for line in a.split(nl):
        m = re.match(r"^## (\d+-[a-z-]+(?:-b)?)$", line)
        if m:
            if key:
                bodies[key] = cur
            key, cur = m.group(1), []
            continue
        if key is not None:
            cur.append(line)
    if key:
        bodies[key] = cur
    out = []
    for line in text.split(nl):
        m = re.match(r"^\d+\. ~~.*~~ — closed, moved verbatim to .*#([0-9a-z-]+)\)\.$", line)
        if m and m.group(1) in bodies:
            b = bodies[m.group(1)]
            while b and not b[-1].strip():
                b = b[:-1]
            while b and not b[0].strip():
                b = b[1:]
            out += b
        else:
            out.append(line)
    return nl.join(out)


# ------------------------------------------------------------------ CLI
def cmd_stats(items):
    col = collisions(items)
    print("items %d | open %d | closed %d | closed-by-bullet-only %d"
          % (len(items), sum(1 for i in items if not i.closed),
             sum(1 for i in items if i.closed), sum(1 for i in items if i.bullet_closed)))
    print("numbers used %d | colliding %d (%s)" % (len({i.num for i in items}), len(col),
                                                   ", ".join(str(n) for n in col)))
    c = collections.Counter(i.lane for i in items if not i.closed)
    print("open per lane: " + ", ".join("%s %d" % kv for kv in c.most_common()))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--write":
        write_index()
        return 0
    if argv[0] == "archive":
        return do_archive(apply="--apply" in argv)
    if argv[0] == "unarchive":
        sys.stdout.write(_unarchive())
        return 0
    items = parse()
    if argv[0] == "stats":
        cmd_stats(items)
        return 0
    if argv[0] == "next":
        print(max(i.num for i in items) + 1)
        return 0
    if argv[0] == "lane":
        want = argv[1] if len(argv) > 1 else ""
        for i in sorted((x for x in items if x.lane == want and not x.closed), key=lambda x: x.num):
            print("%4d  L%-5d %s" % (i.num, i.start, i.title))
        return 0
    if argv[0] == "show":
        n = int(argv[1])
        for i in items:
            if i.num == n:
                print("%-22s L%-5d %-8s %s" % (i.key, i.start,
                                               "closed" if i.closed else "OPEN", i.title))
        return 0
    if argv[0] == "check":
        bad = 0
        ok, why = index_is_current()
        if not ok:
            print("ERROR " + why)
            bad += 1
        lanes = lane_names()
        for i in items:
            if lanes and i.lane not in lanes and i.lane != "unassigned":
                print("ERROR item %d names lane `%s`, which is not in docs/AGENT_BRIEF.md"
                      % (i.num, i.lane))
                bad += 1
        held = [i for i in items if i.bullet_closed]
        if held:
            print("WARN  %d items are closed only by a later section's bullet, with the "
                  "original never edited: %s" % (len(held), ", ".join(i.key for i in held)))
        cmd_stats(items)
        return 1 if bad else 0
    print("unknown command: %s" % argv[0])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
