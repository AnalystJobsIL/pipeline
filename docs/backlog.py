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
    three lanes filed within an hour and none of them knew.
  * Nothing is archived. The closed-item split is designed and measured in item 291; the
    code that did it was deleted after an adversarial pass found its proofs decorative.

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


class Item:
    __slots__ = ("num", "section", "lane", "lines", "start", "closed", "bullet_closed",
                 "half")

    def __init__(self, num, section, start):
        self.num, self.section, self.start = num, section, start
        self.lines, self.lane = [], "unassigned"
        self.closed = self.bullet_closed = self.half = False

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
        b = LANE_IN_BODY.search(it.body)
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
    open_items = [i for i in items if not i.closed]      # `half` counts as open
    col = collisions(items)
    used = {i.num for i in items}
    gaps = sorted(set(range(1, max(used) + 1)) - used)
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
    nl = "\r\n" if "\r\n" in text else "\n"
    cur = text[text.index(BEGIN):text.index(END) + len(END)]
    inner = cur.split("-->" + nl, 1)[1].rsplit(nl + END, 1)[0]
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
        print(max(i.num for i in items) + 1)
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
        cmd_stats(items)
        return 1 if bad else 0
    print("unknown command: %s" % argv[0])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
