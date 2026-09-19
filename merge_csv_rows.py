#!/usr/bin/env python3
"""Git-layer single-writer merge for companies.csv.

The in-process discipline (re-read before every write) protects concurrent writers inside
one machine. It does NOT protect against the git layer: a long cloud run commits a whole
file whose baseline is hours old, and `git pull --rebase` then hits a CONTENT CONFLICT and
the workflow's retry loop gives up — silently discarding the entire run (a 3.5-hour
listing-hunt cycle was lost this way on 2026-08-22).

This applies a run's OWN row changes onto whatever master looks like now:

    cp companies.csv /tmp/base.csv          # BEFORE the tool runs
    python <tool>.py --apply                # tool rewrites companies.csv
    cp companies.csv /tmp/ours.csv          # AFTER
    git checkout --theirs companies.csv     # or: fetch+reset to origin's version
    python merge_csv_rows.py /tmp/base.csv /tmp/ours.csv companies.csv

Rows are matched by company_name. A row is applied only when ours differs from base, so
untouched rows never clobber what another writer changed in the meantime. Rows the run
ADDED (absent from base) are appended if still missing.

The base is used on BOTH sides (2026-09-19, docs/BACKLOG.md 644). Until then it answered
only "what did OURS change", and a row ours changed was written wholesale: a three-hour
cron's start-of-run snapshot therefore beat a session's newer push, and on 2026-09-18 it
did -- `7f960cd` copied `scrape,,www.harel-group.co.il/careers,false` over the activation
`91b9676` had pushed 17 minutes earlier (83 postings, 83 Israel), and nothing said so.
Now every column and every note segment asks what BOTH sides did to it:

    neither changed it            -> base's value
    only ours changed it          -> ours (this run is the newer knowledge)
    only origin changed it        -> ORIGIN's (its knowledge is newer than our snapshot)
    both, to different values     -> ORIGIN's, with a `::warning::merge-conflict` line that
                                     names the row and the column, collected for the caller
                                     so `persist_state` can put it in the morning mail

A session writes with the later and fuller knowledge and a cron re-stamps every night, so
origin winning a genuine conflict is the cheap direction. Nothing is REFUSED here: a
conflict is resolved and reported, never left for a human to merge by hand.
"""
from __future__ import annotations

import csv
import re
import sys

from pipeline.atomic import write_csv_rows

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



_TOOL = re.compile(r"^\s*(dark-triage|listing-hunt|deep-validated|crack-walled|domain-dead|"
                   r"re-audit|repair|probe-woken|bd-tried|scanned via brightdata|"
                   # empty-but-suspect joined in wave 7: its varying `N IL` count sat
                   # inside the seg[:28] fallback key, so a conflict Sunday carried TWO
                   # suspect segments per row (bounded, but 23 wasted segments measured;
                   # docs/BACKLOG.md 67)
                   # `scrape rotted (error 7d) <date>` (refresh_scrape_cache): the day count and
                   # date sat inside the seg[:28] key, so two nights' segments both survived a
                   # conflict merge (scraper lane, 2026-08-24)
                   # 2026-08-25 (infra): every dated tool prefix found in the live registry, so
                   # a conflict day cannot carry two of any tool's segment -- `url-repaired`
                   # (12 live rows) and `self-heal` (4) were keyed by seg[:28] (BACKLOG 35/67)
                   r"empty-but-suspect|scrape rotted|url-repaired|url-cleared|url-flagged|"
                   # `abandoned-board <date>: newest <d>, N postings; needs re-resolution`
                   # (ats-fetch 2026-09-11): its date and counts vary, so without a key here
                   # two nights' segments would both survive a conflict merge under seg[:28]
                   r"self-heal|activated|platform-fix|identity|chrome-verified|abandoned-board)\b")


def _seg_key(seg):
    m = _TOOL.match(seg)
    return m.group(1) if m else seg[:28]


# The four columns a row's IDENTITY lives in. `notes` (5) is the append-log and is merged
# per segment; `company_name` (0) is the key rows are matched by, so it cannot differ.
COLS = {1: "ats_platform", 2: "token", 3: "api_url", 4: "active"}

# Verdicts that are about the row's ADDRESS. When origin has moved `api_url` since our
# checkout, our stamp was made against a page this row no longer points at -- the hunt read
# `www.harel-group.co.il/careers` (0 cards, honestly) while the session was activating the
# adamtotal board -- so the stamp is dropped rather than carried onto the new address.
# A ledger read is keyed by url (the 2026-09-13/18 lesson, `jd-text`); a verdict is too.
# Decided for `registry` by the orchestrator, 2026-09-19 (plan question 7).
_ADDRESS_VERDICTS = frozenset(["listing-hunt", "dark-triage", "queue-hunt", "wrong-url"])


def _split(note):
    return [s.strip() for s in (note or "").split("|") if s.strip()]


def _keyed(note):
    """`{tool key: segment}` for one cell, first spelling of a key winning (a cell with two
    segments of one tool is what `_TOOL` exists to prevent, and it is not this merge's to
    repair)."""
    out = {}
    for seg in _split(note):
        out.setdefault(_seg_key(seg), seg)
    return out


def _conflict(conflicts, name, col, ours, theirs, why=""):
    """Both sides changed one column or one segment, differently: ORIGIN is kept and the row
    is named on the run page AND collected, so `persist_state` can carry it into the mail.
    A run-page line alone is not a channel: this repo deletes run records (CLAUDE.local.md)."""
    print(f"::warning::merge_csv_rows: merge-conflict {name} {col}"
          f"{' ' + why if why else ''} -- ours={ours!r} origin={theirs!r} -- origin kept",
          flush=True)
    if conflicts is not None:
        conflicts.append({"row": name, "col": col, "ours": str(ours)[:80],
                          "origin": str(theirs)[:80], "why": why})


def _merge_cols(name, b, o, t, conflicts=None):
    """Ours' row with columns 1-4 resolved three ways against `b` (our checkout) and `t`
    (origin now). A row absent from base is ours wholesale -- both sides ADDED it and
    neither's value is a change, so there is nothing to compare."""
    row = list(o)
    if b is None:
        return row
    for i, col in sorted(COLS.items()):
        if i >= len(o) or i >= len(t) or i >= len(b):
            continue
        bv, ov, tv = b[i], o[i], t[i]
        if ov == tv:
            continue                       # nobody moved it, or both moved it the same way
            # (`ov == bv and tv == bv` needs no clause of its own: it implies `ov == tv`)
        if ov == bv:
            row[i] = tv                    # only ORIGIN moved: its knowledge is newer
        elif tv != bv:
            row[i] = tv                    # both moved, differently
            _conflict(conflicts, name, col, ov, tv)
    return row


def _merge_notes(theirs: str, ours: str, cap: int = 220, base: str | None = None,
                 address_moved: bool = False, conflicts=None, name: str = "") -> str:
    """Union the ` | `-separated verdict segments of two notes, ours winning per tool.

    Each tool owns a segment (`dark-triage <date>: …`, `listing-hunt <date>: …`). Two
    writers touching the same row must not delete each other's segments — that is how 351
    triage modes were lost. Segments are keyed by tool name; untagged prose is kept once.

    With `base` (the row's note at checkout) this is a THREE-WAY merge per segment, and
    origin's cell is what it starts from (644):

      * a segment ours ADDED or CHANGED is written onto origin's cell through
        `pipeline.notes.replace_own`, so it makes room the way an in-process append does --
        oldest UNPROTECTED segment first, never a slice, a terminal fact never evicted;
      * a segment that was in base and that ours DROPPED is a deliberate deletion --
        `probe_candidates._wake_note` strips the `listing-hunt` / `dark-triage` segments so
        the hunt re-selects the row -- and it is removed, unless theirs rewrote it since
        (BACKLOG 15/60: 47 of 152 wakes were being spent by the conflict merge);
      * a segment BOTH sides rewrote differently keeps ORIGIN's and is reported;
      * with `address_moved` (origin changed `api_url` since our checkout), a verdict of
        ours ABOUT that address is dropped and reported -- see `_ADDRESS_VERDICTS`.

    Without `base` the old ours-first union stands: the five `_merge_notes(theirs, ours,
    cap=...)` call sites in the suite pin the eviction rules on it, and `merge()` reaches it
    for a row BOTH sides added (no base row exists to compare either side against). The
    production path always has a base -- `s_csv_rows` cannot call `merge` without one.
    """
    if base is not None:
        return _merge_notes_threeway(theirs, ours, base, cap, address_moved, conflicts, name)

    seen, out = {}, []
    for seg in _split(ours) + _split(theirs):     # ours first: it wins its own tool key
        key = _seg_key(seg)
        if key in seen:
            continue
        seen[key] = True
        out.append(seg)
    joined = " | ".join(out)
    if len(joined) <= cap:
        return joined
    # `out` is ours-first then theirs-unique, so pop() trims from the THEIRS tail --
    # the stale duplicates -- and ours' own segments survive. Measured on the real
    # registry: 0 of 1210 rows lose their own pool selector this way.
    # ...but never a terminal segment (2026-08-26, the same protection `notes.append` has):
    # a conflict day must not evict the `alias-of` that keeps a row out of every pool
    # ...and never a SLICE (2026-08-26, attacker 2): when only protected segments remained
    # the old `[:cap]` cut one mid-word (`dark-triage 2026-09-01: page-empt` -- the 87-row
    # bug, back through the conflict path). From the theirs tail: an unprotected segment,
    # else the tail itself -- `ours` is already within the cap, so the tail is always one of
    # theirs' stale duplicates, dropped whole.
    from pipeline.notes import has_terminal
    while out and len(" | ".join(out)) > cap:
        victims = [i for i in range(len(out) - 1, -1, -1) if not has_terminal(out[i])] or [len(out) - 1]
        out.pop(victims[0])
    return " | ".join(out)


def _merge_notes_threeway(theirs, ours, base, cap, address_moved, conflicts, name):
    """The append-log merged per segment against the checkout cell. ORIGIN's cell is the
    starting point and `notes.replace_own` does every write, so the cap is spent by the same
    rule an in-process stamp spends it -- rather than by trimming origin's newest segment off
    the tail, which is what the union did (it evicted the ONE thing `5dbec81` had added)."""
    from pipeline import notes as N
    b, o, t = _keyed(base), _keyed(ours), _keyed(theirs)
    cell = str(theirs or "")
    # DELETIONS FIRST, and the golden replay is why (2026-09-19): a wake consumed by the hunt
    # (`probe-woken` out, `listing-hunt` in) is a swap, and applying the addition to a cell
    # that still held the deleted segment spent the 220-char cap -- `notes.append` evicted
    # `Octup`'s oldest unprotected segment (`queue-hunt 2026-09-15`, its queue receipt) to
    # make room the deletion was about to free. One row of the 76 in the real replay.
    for key, seg in b.items():
        if key not in o and t.get(key) == seg:
            # ours deleted it on purpose and origin left it alone: the deletion stands
            cell = " | ".join(s for s in _split(cell) if _seg_key(s) != key)
    for key, seg in o.items():
        if b.get(key) == seg:
            continue                                   # ours did not touch this tool's key
        if key in t and t[key] != b.get(key) and t[key] != seg:
            _conflict(conflicts, name, f"notes/{key}", seg, t[key])
            continue                                   # both rewrote it: origin's stands
        if address_moved and key in _ADDRESS_VERDICTS:
            _conflict(conflicts, name, f"notes/{key}", seg, t.get(key, ""), why="(address moved)")
            continue
        cell = N.replace_own(cell, key, seg, cap)
    return cell


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def merge(base_path, ours_path, target_path):
    base = {r[0]: r for r in _read(base_path) if r}
    ours = _read(ours_path)
    target = _read(target_path)
    tgt_idx = {r[0]: i for i, r in enumerate(target) if r}

    changed = [r for r in ours if r and (r[0] not in base or base[r[0]] != r)]
    applied = added = merged_notes = origin_moved = 0
    conflicts = []
    for r in changed:
        if r[0] in tgt_idx:
            cur = target[tgt_idx[r[0]]]
            if cur != r:
                _b = base.get(r[0])
                if _b is not None and cur != _b:
                    origin_moved += 1
                # The four identity columns, three ways: origin's newer verdict about the
                # board is kept where our snapshot merely carried the old one. Before 644
                # ours' columns were copied wholesale and a stale `scrape,,<dead url>,false`
                # beat an activation pushed 17 minutes earlier.
                ours_note = r[5] if len(r) > 5 else ""     # BEFORE the merge below
                r = _merge_cols(r[0], _b, r, cur, conflicts)
                # The notes column is an APPEND-LOG of per-tool segments, so replacing the
                # whole row drops segments another tool wrote while this run was going.
                # (A 7-hour hunt did exactly that to 351 freshly-written triage modes.)
                if len(r) > 5 and len(cur) > 5:
                    # `api_url` moved under our feet -> our verdicts about the OLD address
                    # are dropped rather than carried onto the new one. This subsumes the
                    # `url-repaired` special case: origin wins EVERY column it moved, not
                    # only a repaired one, so no segment has to name itself to be believed.
                    moved = bool(_b is not None and len(_b) > 3 and len(cur) > 3
                                 and cur[3] != _b[3])
                    r[5] = _merge_notes(cur[5], ours_note,
                                        base=_b[5] if _b is not None and len(_b) > 5 else None,
                                        address_moved=moved, conflicts=conflicts, name=r[0])
                    merged_notes += 1
                target[tgt_idx[r[0]]] = r
                applied += 1
        else:
            target.append(r)
            added += 1

    # ATOMIC, like every other companies.csv truncating writer. This was the ONE that
    # wrote in place: a runner eviction mid-write left a 400-line registry behind `|| true`
    # on the digest's conflict path, and the invariant gate there could only catch it
    # after the fact (wave-6 R2, B4). `os.replace` makes the kill window leave the OLD
    # file, which is always a valid registry.
    write_csv_rows(target_path, target)
    print(f"merge_csv_rows: {len(changed)} rows changed by this run "
          f"→ {applied} applied, {added} appended, "
          f"{len(changed) - applied - added} already identical"
          f", {origin_moved} origin-moved, {len(conflicts)} conflicts")
    return applied + added, conflicts


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
