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


def append(base: str, segment: str, cap: int = CAP) -> str:
    """`base` with `segment` appended, trimmed to `cap` by dropping OLD whole segments."""
    seg = " ".join(str(segment or "").split())
    if not seg:
        return str(base or "")[:cap]
    parts = split(base)
    while parts and len(SEP.join(parts + [seg])) > cap:
        parts.pop(0)                     # oldest first
    out = SEP.join(parts + [seg])
    # a single segment longer than the cap is the caller's problem, not the log's: keep the
    # verdict and lose its tail rather than emit something that parses as a different verdict
    return out if len(out) <= cap else seg[:cap]


def replace_own(base: str, marker: str, segment: str, cap: int = CAP) -> str:
    """Append `segment`, first removing this tool's own previous segment(s).

    `marker` is the tool's prefix, e.g. "listing-hunt". Other tools' segments are untouched —
    a wholesale rewrite of the cell is what deleted `dark-triage` from 351 of 352 rows.
    """
    kept = [p for p in split(base) if not p.lower().startswith(str(marker).lower())]
    return append(SEP.join(kept), segment, cap)
