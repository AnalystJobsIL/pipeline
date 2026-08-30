#!/usr/bin/env python3
"""Make docs/BACKLOG.md a document a lane can read in thirty seconds.

On the morning of 2026-08-27 it was 3,457 lines / 303 KB with 314 items across 37
chronological sections, a lane's own work scattered across up to fifteen of them, and
roughly a third of the file closed-item prose. By the evening of the same day it was
4,474 lines / 383 KB / 344 items - which is the point, and why the header of this file
quotes no live number: run `python docs/backlog.py stats`. Numbers collide - `6` names five different items and is cited from two workflow
files; 241, 242, 243, 244 and 245 each name three - and one section runs 241-246 twice with
no divider. The collision has already produced a wrong read INSIDE the file: a
`- **244 - CLOSED.**` bullet is ambiguous between a closed `company-intel` item and an open,
untouched `ats-fetch` one.

Two things are therefore NOT done here, on purpose:

  * Nothing is renumbered. 470 citations of the form `BACKLOG <n>` exist across 74 tracked
    files, including `.github/workflows/audit-coverage.yml` and `daily-digest.yml`. A bare
    number stays legal and resolves to a candidate list; uniqueness is enforced only going
    forward, by `next` printing the first free number - the collisions happened because
    three lanes filed within an hour and none of them knew. `next` reading only the local
    file did not stop it: on 2026-08-30 four more numbers (445, 446, 461, 462) came to name
    two items each, because two branches cut from the same base computed the same `max+1`
    and both landed. So `next` now reads `origin/master`'s file too (as last fetched - it
    never fetches, for the reason `docs/check_docs.py` never does), and `check` REFUSES a
    collision this branch introduces: run `next` after `git pull --rebase`, right before the
    push, and a number that was taken in the meantime is yours to renumber - nothing cites
    it yet. The 38 collisions that already exist are grandfathered and cited by key.
  * Nothing is archived. The closed-item split is designed and measured in item 291; the
    code that did it was deleted after an adversarial pass found its proofs decorative.

Per-lane source files were considered and rejected on measurement, not taste: the sections
are chronological, not lane containers (`## From the ats-fetch lane, 2026-08-24` holds
company-intel's items 97-104), so 42 items would need a human judgement each - 42 chances to
misplace text during a move-never-retype migration.

    python docs/backlog.py check      # parse + rules; exit 1 on a violation; writes nothing
    python docs/backlog.py stats      # the census
    python docs/backlog.py next       # the first free number on THIS tree AND origin/master
    python docs/backlog.py lane infra # that lane's open items
    python docs/backlog.py show 241   # every claimant of 241
    python docs/backlog.py --write    # regenerate the index block IN PLACE (the only write)

Owned by the `docs` lane. Read-only unless `--write` is passed; stdlib only;
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

BEGIN = "<!-- BACKLOG-INDEX:BEGIN"
END = "<!-- BACKLOG-INDEX:END -->"

# The parse contract, and it is exact rather than heuristic: `^(\d+)\. ` at column 0 matched
# 314 lines and exactly 314 items across 3,457 lines, with zero false positives.
# No leading zeros: `007. ` parsed as item 7 and silently joined its collision.
ITEM = re.compile(r"^([1-9]\d*)\. ")
SECTION = re.compile(r"^## (.*)$")
LANE_IN_BODY = re.compile(r"lanes?:\s*`([a-z-]+)`")
# Backticks optional, `'s` allowed: six real headings write `From the registry lane` and
# `From the registry lane's wave-8 review`, and every item under them without an inline
# `lane:` fell to `unassigned` - 12 of the 39 the index tells the reader to burn down.
LANE_IN_HEADING = re.compile(r"`?([a-z][a-z-]+)`?(?:'s)? lane")
# Closed = a DATED closure marker in the item's own first two lines, with or without the
# strikethrough. The first version demanded both, and 51 items - 17% of the file - announce
# an unambiguous dated closure and never struck their title, so the tool's headline number
# was wrong by 22 items for `registry` alone.
#
# `half`/`partly` closed is a THIRD state, reported and never treated as either. It has to
# be explicit rather than incidental: the old marker allowed up to 16 arbitrary letters
# before the word, so `**half closed 2026-08-25**` counted as closed (5 characters) while
# `**the restore half closed 2026-08-25**` did not (17), and two items of identical shape
# landed on opposite sides on a character count.
STRUCK = re.compile(r"~~")
_HALF = r"(?:half|partly|part|partial(?:ly)?|module|code|row)\s+"
CLOSED_MARK = re.compile(
    r"\*\*(?:%s)?(?:CLOSED|closed|WON'T FIX|won't fix)\b[^*]{0,40}?\d{4}-\d\d-\d\d" % _HALF,
    re.I)
HALF_MARK = re.compile(r"\*\*(?:%s)(?:CLOSED|closed)" % _HALF, re.I)

# A closure bullet in an archive section: `- **244 - CLOSED.** ...`, `- **11 / 101 - CLOSED.**`
BULLET_CLOSES = re.compile(r"^- \*\*(\d+)(?:\s*/\s*(\d+))?\s*[\u2014-]*\s*(?:CLOSED|closed|won't fix)", re.I)   # the dash is OPTIONAL: `- **505 CLOSED.**` closed nothing


class Item:
    __slots__ = ("num", "section", "lane", "lines", "start", "closed", "bullet_closed",
                 "half")

    def __init__(self, num, section, start):
        self.num, self.section, self.start = num, section, start
        self.lines, self.lane = [], "unassigned"
        self.closed = self.bullet_closed = self.half = False

    @property
    def unfenced(self):
        """The body minus fenced blocks."""
        out, fenced = [], False
        for line in self.lines:
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if not fenced:
                out.append(line)
        return "\n".join(out)

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
    """Newline-agnostic on purpose. `text.split(nl)` with nl sniffed from the file deleted
    an item outright when ONE line boundary disagreed with the rest of the file - and
    `--write` then regenerated a green index without it, so the fix the error message
    prescribed was the thing that buried the item. In the other direction a single stray
    \r in an LF file made nl CRLF and the parse returned zero items."""
    text = read(LIVE) if text is None else text
    lines = text.splitlines()
    items, section, cur, fenced = [], "", None, False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            if cur is not None:
                cur.lines.append(line)
            continue
        if fenced:
            if cur is not None:
                cur.lines.append(line)
            continue
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
        # A fenced example writing `lane: `infra`` assigned a real item, and a genuine
        # example could silently re-home another lane's work.
        b = LANE_IN_BODY.search(it.unfenced)
        h = LANE_IN_HEADING.search(it.section)
        known = lane_names()
        it.lane = "unassigned"
        for cand in (b.group(1) if b else None, h.group(1) if h else None):
            if cand and (not known or cand in known):
                it.lane = cand
                break
        head = "\n".join(it.lines[:2])
        body = it.body
        it.half = bool(HALF_MARK.search(head)) or bool(HALF_MARK.search(body))
        # The UNION of the two conventions this file actually uses. Demanding BOTH a struck
        # title and a closure paragraph counted 51 already-closed items as open - 22 of them
        # registry's - so the tool's headline number was wrong by 17%. Either a struck title
        # with a dated closure anywhere in the body, or a dated closure announced in the
        # item's own first two lines, counts.
        it.closed = (not it.half) and (
            (bool(STRUCK.search(it.lines[0])) and bool(CLOSED_MARK.search(body)))
            or bool(CLOSED_MARK.search(head)))
    # Closed by a LATER section's archive bullet, original untouched: report, never archive.
    # The bullet is attributed to a SECTION, not just to a number. 28 numbers name more than
    # one item, so keying on the number alone made a bullet closing `company-intel`'s 244
    # also flag `scraper`'s - 20 flags for 12 real originals, and 8 of them told a lane its
    # open work was already done. A bullet closes a claimant when the number is unique, when
    # the bullet spells `<n>@<lane>`, or when the claimant's lane is the one its own section
    # heading names.
    bullets = collections.defaultdict(list)
    section = ""
    for line in lines:
        h = SECTION.match(line)
        if h:
            section = h.group(1)
            continue
        m = BULLET_CLOSES.match(line)
        if not m:
            continue
        lane_h = bullet_lanes(section)
        for g in m.groups()[:2]:
            if g:
                bullets[int(g)].append((line, lane_h))
    claimants = collections.Counter(it.num for it in items)
    for it in items:
        if it.closed:
            continue
        for line, lane in bullets.get(it.num, ()):
            explicit = re.search(r"%d@([a-z-]+)" % it.num, line)
            if explicit:
                if explicit.group(1) == it.lane:
                    it.bullet_closed = True
            # A bullet whose section names no lane closed NOBODY, so planting a decoy
            # item under another lane turned the error off. Unresolvable falls back to
            # the pre-change behaviour - flag every claimant - which over-reports rather
            # than under-reports, and that is the right direction for this check.
            elif claimants[it.num] == 1 or not lane or it.lane in lane:
                it.bullet_closed = True
    return items


def lane_names():
    p = os.path.join(ROOT, "docs", "AGENT_BRIEF.md")
    return set(re.findall(r"^\| \*\*`([a-z-]+)`\*\*", read(p), re.M)) if os.path.exists(p) else set()


def bullet_lanes(section):
    """Every lane a closure-bullet section speaks for.

    It returned the FIRST backticked lane, so renaming a heading to "`docs` and
    `registry` closures" turned the error off in two words. `LANE_IN_HEADING` wants
    "<name> lane" and no closures heading has it, which is why this resolver exists at
    all: the first version resolved nothing for every bullet in the file and went green
    by checking nothing."""
    known = lane_names()
    out = [t for t in re.findall(r"`([a-z][a-z-]+)`", section or "") if t in known]
    m = LANE_IN_HEADING.search(section or "")
    if m and (not known or m.group(1) in known) and m.group(1) not in out:
        out.append(m.group(1))
    return out



def collisions(items):
    by = collections.defaultdict(list)
    for it in items:
        by[it.num].append(it)
    return {n: v for n, v in sorted(by.items()) if len(v) > 1}


def _git_show(ref, rel="docs/BACKLOG.md"):
    """The file at `ref`, or None. Never fetches, never raises: no git, no remote, a ref
    that does not exist - all mean "nothing to compare against"."""
    import subprocess
    try:
        out = subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
    except Exception:                                             # noqa: BLE001
        return None
    return out.stdout if out.returncode == 0 else None


def next_free(items, ref="origin/master"):
    """max+1 over THIS tree and over `ref`'s file, whichever is higher. A branch that
    reads only its own file cannot know what landed on master since it was cut, which is
    exactly how 445/446/461/462 each came to name two items on 2026-08-30."""
    high = max((i.num for i in items), default=0)
    other = _git_show(ref)
    if other is not None:
        try:
            high = max(high, max((i.num for i in parse(other)), default=0))
        except Exception:                                         # noqa: BLE001
            pass
    return high + 1


def _merge_base():
    """The commit this branch is judged against: `AJIL_PUSH_BASE` on a runner (the tip
    master had before the push), else the merge-base with origin/master, else None."""
    import subprocess
    push_base = (os.environ.get("AJIL_PUSH_BASE") or "").strip()
    if push_base and set(push_base) != {"0"}:
        return push_base
    if push_base:
        return None                                   # all-zero sha: branch creation
    try:
        out = subprocess.run(["git", "merge-base", "HEAD", "origin/master"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
    except Exception:                                             # noqa: BLE001
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def new_collisions(items, base_text):
    """Numbers that name more than one item HERE where at least one claimant is not in
    `base_text` (the file at the merge-base): the collisions THIS branch introduces. An
    item is "the same" as a base item when its number and title agree, so re-wording a
    body or closing an item never reads as a new claimant. None when there is no base."""
    if base_text is None:
        return {}
    try:
        base = {(i.num, i.title) for i in parse(base_text)}
    except Exception:                                             # noqa: BLE001
        return {}
    out = {}
    for n, claimants in collisions(items).items():
        fresh = [i for i in claimants if (i.num, i.title) not in base]
        if fresh:
            out[n] = claimants
    return out


def render_index(items):
    open_items = [i for i in items if not i.closed]      # `half` counts as open
    col = collisions(items)
    used = {i.num for i in items}
    # `max()` of an empty sequence is a ValueError, and `check_backlog` wraps `parse()`
    # in try/except but not `index_is_current()`, which calls this.
    gaps = sorted(set(range(1, max(used) + 1)) - used) if used else []
    out = [
        "## Index — generated, do not hand-edit",
        "",
        "`python docs/backlog.py --write` regenerates this block; `docs/check_docs.py` fails "
        "if it is stale. A merge conflict inside it is resolved by re-running that command.",
        "",
        "**%d filed · %d open · %d closed · %d half · %d numbers name more than one item · "
        "%d items name no lane.**" % (len(items), len(open_items),
                                      sum(1 for i in items if i.closed),
                                      sum(1 for i in items if i.half), len(col),
                                      sum(1 for i in open_items if i.lane == "unassigned")),
        "",
        "*\"Open\" is an upper bound on work remaining, not a count of it.* A confirmer reading",
        "ten of them by hand on 2026-08-27 found several that are resolved in their own body and",
        "never stamped, plus the items below that a later section closed by bullet with the",
        "original untouched. The parse is exact; the state it reports is only as good as the",
        "closure convention in the header.",
        "",
        "**Next free number: %d.** Run `python docs/backlog.py next` after `git pull --rebase`, "
        "right before you push — it reads origin/master's file too, and `check` refuses a "
        "collision your branch introduces. 241 through 246 each name three items because three "
        "lanes filed within an hour on 2026-08-26 and none of them knew, and 445, 446, 461 and "
        "462 each name two because `next` read only the local file until 2026-08-30. Numbers %s "
        "were never used; do not reuse them, because an old citation would then resolve to new "
        "text."
        % ((max(used) + 1 if used else 1), ", ".join(str(g) for g in gaps) or "(none)"),
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
            flag += " *(half closed)*" if i.half else ""
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
    if text.index(END) < text.index(BEGIN):
        # A conflict resolution that reorders the markers made `text[a:b]` empty and
        # the split below raise IndexError.
        return False, "docs/BACKLOG.md's index markers are out of order - run `python docs/backlog.py --write`"
    nl = "\r\n" if "\r\n" in text else "\n"
    cur = text[text.index(BEGIN):text.index(END) + len(END)]
    parts = cur.split("-->" + nl, 1)
    if len(parts) < 2:
        # A BEGIN marker with no closing `-->` line: IndexError, from a file state a
        # merge conflict produces.
        return False, "docs/BACKLOG.md's index block is malformed - run `python docs/backlog.py --write`"
    inner = parts[1].rsplit(nl + END, 1)[0]
    want = nl.join(render_index(parse(text)).rstrip("\n").split("\n"))
    return (inner.strip() == want.strip(),
            "docs/BACKLOG.md's index is stale — run `python docs/backlog.py --write`")


# ---------------------------------------------- the archive split, and why it is not here
# `archive --apply` / `unarchive` were written, and are deleted. Not because the design is
# wrong - `docs/BACKLOG.md` 291 keeps it, with the measurement that says when to run it -
# but because an adversarial pass found its three advertised proofs to be decorative, and a
# destructive command with a guard rail that cannot fail is worse than no command:
#
#   * both `open(..., "w")` calls executed BEFORE the first assert, so a failed proof left
#     two half-written files on disk with no rollback;
#   * `TOMBSTONE` never matched the link the writer actually emitted, so the proof-2 filter
#     removed nothing and key-set equality held trivially;
#   * the `altered` list - the body-hash comparison the docstring and the generated archive
#     header both promised - was computed and never asserted. 15 real mismatches;
#   * proof 3 only printed, and its message explained the difference away with a reason
#     that was false (14 dropped blank separators, not just the new tombstone lines).
#
# When it comes back it needs the writes after the proofs (temp file, rename on success),
# `altered` asserted, and a round trip that is byte-identical rather than nearly so.

# ------------------------------------------------------------------ CLI
def cmd_stats(items):
    col = collisions(items)
    print("items %d | open %d | closed %d | half-closed %d | closed-by-bullet-only %d"
          % (len(items), sum(1 for i in items if not i.closed and not i.half),
             sum(1 for i in items if i.closed), sum(1 for i in items if i.half),
             sum(1 for i in items if i.bullet_closed)))
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
    items = parse()
    if argv[0] == "stats":
        cmd_stats(items)
        return 0
    if argv[0] == "next":
        print(next_free(items))
        return 0
    if argv[0] == "lane":
        want = argv[1] if len(argv) > 1 else ""
        known = lane_names() | {"unassigned"}
        if want not in known:
            print("unknown lane %r. For a tool whose job is 'a lane sees its own list in "
                  "thirty seconds', a typo and an empty list must not look the same.\n"
                  "known: %s" % (want, ", ".join(sorted(known))))
            return 2
        rows = sorted((x for x in items if x.lane == want and not x.closed),
                      key=lambda x: x.num)
        for i in rows:
            print("%4d  L%-5d %s%s" % (i.num, i.start, "[half] " if i.half else "", i.title))
        if not rows:
            print("no open items for `%s`" % want)
        return 0
    if argv[0] == "show":
        if len(argv) < 2 or not argv[1].isdigit():
            print("usage: backlog.py show <number>")
            return 2
        n = int(argv[1])
        hits = [i for i in items if i.num == n]
        for i in hits:
            state = "half" if i.half else ("closed" if i.closed else "OPEN")
            print("%-22s L%-5d %-8s %s" % (i.key, i.start, state, i.title))
        if not hits:
            print("no item numbered %d" % n)
            return 1
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
        for n, v in new_collisions(items, _git_show(_merge_base())).items():
            print("ERROR %d names %d items and this branch added one of them (%s): renumber "
                  "YOUR item to `next` - nothing cites it yet - and re-run --write"
                  % (n, len(v), ", ".join(i.key for i in v)))
            bad += 1
        cmd_stats(items)
        return 1 if bad else 0
    print("unknown command: %s" % argv[0])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
