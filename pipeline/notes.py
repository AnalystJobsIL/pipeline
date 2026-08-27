"""The notes column is an append-log. Append to it without eating what is already there.

Every tool stamps its verdict into `companies.csv`'s 220-char notes cell, and every tool
made room the same way: `(base + " | " + segment)[:220]`, or `base[:220 - len(segment) - 3]`.
Both slice the base MID-SEGMENT, and the newest segment lives at the end of the base — which
is how 87 rows ended up saying `dark-triage 2026-08-22: page-emp` (also `page-e`, and on one
row `pa`), and how Somatix ended up with `dark-triage 2026-08-22:` and no mode at all. A mode
no downstream filter matches silently drops the row out of whichever pool keys on it: the
documented #1 bug class here.

So drop whole segments, oldest first, and never cut one in half. What survives is the most
recent knowledge, which is the knowledge worth keeping.
"""
from __future__ import annotations

CAP = 220
SEP = " | "


def split(note: str) -> list:
    return [p for p in (s.strip() for s in str(note or "").split("|")) if p]


import re as _re

# Segments eviction may never take. The rule: a segment ONE tool owns that is another
# pool's membership FACT -- the terminal tokens (the only thing keeping a row out of every
# activating pool), `unsupported ATS <x>` (deep_validate's; the crack pool's fact for a row
# whose address is not on a walled host), `dark-triage <date>: <mode>` (triage's; the
# extract-gap pool's fact and triage's own) and `scanned; no open` (the resolvers'; the
# Sunday cross-validation's fact). Each owner still rewrites its own segment through
# `replace_own`; only OTHER tools' stamps can no longer push these out. The 14-night
# rehearsal (tests/rehearse_registry.py) took the crack pool 14 -> 9 on night one and the
# extract-gap / validate_empty pools by 3 and 6 rows on the first Sunday before this
# (docs/BACKLOG.md 27, 197).
# (`no open Israel roles` rather than `scanned; no open`: older rows carry that segment as a
# head-cut fragment -- `a; no open Israel roles now` -- and the pool matches the substring)
# `empty-but-suspect <date>` / `cross-validated` are validate_empty's own facts and its
# token arm (the shipped configuration -- the signals arm is staged): the Sunday deep stamp
# evicted Enzymit's and the row left the ONE pool that could re-check it (wave-1 attacker 2).
# `probe-woken` is protected for a different reason from the rest: not because it is a
# durable fact, but because it is TRANSIENT and has exactly one legitimate consumer. It is
# the only route back into the hunt for a row triage stamped `page-empty`
# (`listing_hunt._triaged_page_empty` skips such a row unless a wake at least as new as the
# triage stamp says its signals rose), and on a saturated note it is the oldest UNPROTECTED
# segment -- so an unrelated tool's stamp evicted it before its receiver ever ran.
# ARCHITECTURE.md section 2 states the rule and nothing enforced the second half: "A wake
# must clear every stamp any downstream filter excludes on, AND SURVIVE TO ITS RECEIVER".
# The wake was made dated and consumable (`listing_hunt._consume_wake`) so it could not
# LINGER; nothing stopped it vanishing early. `tests/rehearse_registry.py --nights 14
# --policy worst` failed on exactly this until 2026-08-27 (`night 4: pool listing_hunt lost
# 1 rows it should keep: ['NeoGames']`), which blocked tests.yml for every lane. Protection
# cannot accumulate here: the hunt strips the wake the same night it acts on it, and the
# measured cost of adding it was 0 rows (rows whose every segment is protected: 47 -> 47).
_PROTECTED_EXTRA = _re.compile(r"unsupported ATS|dark-triage \d{4}-\d{2}-\d{2}: [a-z-]+|no open israel roles|"
                               r"empty-but-suspect|cross-validated|probe-woken", _re.I)   # dated or not: older rows carry it bare


def _terminal_rx():
    from pipeline.verdicts import TERM_RX      # lazy: verdicts imports nothing of ours
    return TERM_RX


def _protected(seg):
    return bool(_terminal_rx().search(seg) or _PROTECTED_EXTRA.search(seg))


def append(base: str, segment: str, cap: int = CAP, keep=None) -> str:
    """`base` with `segment` appended, trimmed to `cap` by dropping OLD whole segments --
    never a TERMINAL one. An `alias-of` / `defunct` / `domain-dead` segment is the only
    thing keeping a row out of every ACTIVATING pool, and by construction it is the oldest
    segment on the row (2026-08-26: 19 parked rows carried a terminal token that was not the
    newest segment on a note > 150 chars -- one or two more stamps evicted it). `keep` is
    the protecting regex (default: the shared terminal list). ONE rule: a protected segment
    is never evicted, and nothing is ever sliced -- when only protected segments remain and
    the newcomer does not fit, the newcomer is DROPPED whole. A wave-1 attacker (2026-08-26)
    drove the old `room <= 0` branch to cut a protected `dark-triage` segment mid-word and
    the `room > 0` branch to leave `crack-walled <date>: ` (check_invariants F then blocked
    the digest); letting the oldest protected fact yield instead cost 12 rows their
    `no open Israel roles` selector. Dropping the newcomer costs that tool tonight's date on
    a saturated row (it re-does the row tomorrow), never a pool (docs/BACKLOG.md 205)."""
    seg = " ".join(str(segment or "").split())
    if not seg:
        return str(base or "")[:cap]
    protected = _protected if keep is None else (lambda p: bool(keep.search(p)))
    parts = split(base)
    while parts and len(SEP.join(parts + [seg])) > cap:
        victims = [i for i, p in enumerate(parts) if not protected(p)]
        if not victims:
            break
        parts.pop(victims[0])            # oldest UNPROTECTED first
    out = SEP.join(parts + [seg])
    if len(out) <= cap:
        return out
    if parts:                            # only protected segments left: the newcomer is dropped
        return SEP.join(parts)           # (a base already over the cap is left as it was: no slice)
    # a single segment longer than the cap is the caller's problem, not the log's: keep the
    # verdict and lose its tail rather than emit something that parses as a different verdict
    return seg[:cap]


def replace_own(base: str, marker: str, segment: str, cap: int = CAP) -> str:
    """Append `segment`, first removing this tool's own previous segment(s).

    `marker` is the tool's prefix, e.g. "listing-hunt". Other tools' segments are untouched —
    a wholesale rewrite of the cell is what deleted `dark-triage` from 351 of 352 rows.
    """
    kept = [p for p in split(base) if not p.lower().startswith(str(marker).lower())]
    return append(SEP.join(kept), segment, cap)


def has_terminal(note: str) -> bool:
    """Is this segment protected (terminal, or another pool's membership fact)? The merge
    asks before trimming."""
    return _protected(note or "")
