"""Single source of truth for companies.csv verdict tokens and re-check pools.

Six tools each decide "is this row still worth re-checking?" by matching substrings in the
notes column. They were maintained by hand and drifted: `listing_hunt` knew 15 tokens while
`audit_empty_rows` and `deep_validate` knew 7, so **64 parked companies were invisible to
two of the six pools** — no error, just coverage that quietly never happened.

Rule (also in ARCHITECTURE.md): a new verdict string MUST be added to TOKENS here. Tools
narrow this pool when they legitimately want a subset (crack_walled only wants walled ATSes),
but nobody re-implements it.
"""
from __future__ import annotations

import datetime as dt
import re

# every token a tool may write into companies.csv col 5 -> who owns it
TOKENS = {
    "scanned; no open":        "auto_expand / recheck_suspects",
    "unreachable":             "auto_expand / retry_unreachable / bd_rescue",
    "aggregator URL":          "auto_expand",
    "no ATS detected":         "deep_validate",
    "unsupported ATS":         "deep_validate / crack_walled",
    "scanned via brightdata":  "bd_rescue",
    "url-cleared":             "auto_expand --clear-agg-urls / cleanup_after_hunt",
    "url-flagged":             "cleanup_after_hunt",
    "roles-text present":      "bd_rescue",
    "empty-but-suspect":       "validate_empty",
    "no listing found":        "listing_hunt",
    "no IL listing":           "listing_hunt",
    "monitored candidate":     "listing_hunt / bd_rescue",
    "host documented":         "crack_walled",
    "probe-woken":             "probe_candidates",
    "scrape rotted":           "refresh_scrape_cache",
    "redirects to":            "listing_hunt",
    "needs re-resolution":     "manual",
    "needs manual resolution": "manual",
    "dark-triage":             "triage_dark",
    # the board answered and its newest posting is a year old (`pipeline.health.abandoned`,
    # `fetchers.BoardAbandoned`): an abandoned tenant, parked so a re-check pool owns it
    "abandoned-board":         "ats-fetch / health.abandoned",
}

# states that are deliberately final — never re-checked. THE one list: audit_empty_rows,
# crack_walled, probe_candidates and triage_dark all derive from TERM_RX below. The one
# deliberate divergence is scan_dead_domains, which excludes ONLY `defunct` — re-testing
# `domain-dead` rows is its purpose (a revived domain must be cleared), and that is
# documented at its selector. `alias-of` was missing here for a wave while two tools
# spelled their own copies "TERMINAL plus alias-of" (docs/BACKLOG.md 47).
TERMINAL = ("defunct", "domain-dead", "duplicate of", "redundant", "recruiter", "alias-of")

POOL_RX = re.compile("|".join(re.escape(t) for t in TOKENS), re.I)
# `recruiter` is WORD-bounded: `SmartRecruiters` in a note carried it into five rows, two of
# them parked and thereby terminal-by-substring in NO pool (Bosch Israel, Wix (Wixpress);
# docs/BACKLOG.md 72). Agency-hood is decided by the NAME -- `is_terminal_row` below.
TERM_RX = re.compile("|".join(r"\b" + t + r"\b" if t == "recruiter" else re.escape(t)
                              for t in TERMINAL), re.I)


# `alias-of <canonical name> <date>: <evidence>` -- the shape 61 of the 64 alias-of rows
# use. The name is captured so a reader (`roles._alias_fold_target`) can ask WHICH row this
# one duplicates, instead of only "is this note terminal". Anchored at a segment start
# because `alias-of` also appears inside prose. Three rows predate the dated form and write
# `alias-of <name>: ...` or `alias-of <name> (<evidence>)` -- JPMorgan Chase, Unframe AI,
# Agency -- so the undated spelling is read too, second and only when the first misses.
ALIAS_OF_RX = re.compile(r"^alias-of\s+(.+?)\s+\d{4}-\d{2}-\d{2}(?=\s*[:|]|\s*$)")
ALIAS_OF_UNDATED_RX = re.compile(r"^alias-of\s+(.+?)\s*(?::|\s\(|$)")


def alias_target(note: str) -> str | None:
    """The canonical company this row was parked as a duplicate OF, or None.

    Reads the row's own dated verdict -- the string a human wrote when they parked it -- so
    the registry's ruling is available to code and not only to a reader. Only an `alias-of`
    segment answers: `duplicate of` / `redundant` / `defunct` are terminal too but name no
    survivor. A note is an append-log, so the FIRST alias-of wins and a later one is ignored
    rather than silently merged.

    It is a READING of prose, never an authority on its own: the undated fallback cuts a
    target at ` (`, so a survivor whose own name contains a parenthesis (`Wix (Wixpress)`,
    `Habana Labs (Intel)`) would come back truncated. Every caller must therefore treat the
    answer as one of TWO agreeing declarations -- `roles._alias_fold_target` accepts it only
    when `firmographics.ALIASES` independently names the same row -- and a truncated read
    then simply refuses to fold. New verdicts get the dated form.
    """
    for seg in str(note or "").split("|"):
        seg = seg.strip()
        m = ALIAS_OF_RX.match(seg) or ALIAS_OF_UNDATED_RX.match(seg)
        if m:
            t = m.group(1).strip()
            if t:
                return t
    return None


def in_pool(note: str) -> bool:
    """True if this row is still eligible for some re-check."""
    n = note or ""
    return bool(POOL_RX.search(n)) and not TERM_RX.search(n)


def is_terminal(note: str) -> bool:
    return bool(TERM_RX.search(note or ""))


def is_terminal_row(r) -> bool:
    """THE terminal test for a pool predicate: a terminal note token OR an agency NAME.
    Every `in_*_pool` calls this rather than pairing `TERM_RX` with its own `is_recruiter`
    (2026-08-26): one rule, and the nine agency-named parked rows that had no token stop
    counting as coverage anyone owes."""
    from pipeline.recruiters import is_recruiter
    return is_terminal(r[5] if len(r) > 5 else "") or is_recruiter(r[0] if r else "")


def stale(note: str, tool: str, days: int) -> bool:
    """True if `tool` has not stamped this row within `days` (or never has).

    Every re-check filter needs one of these: a `"tool" not in note` test freezes the row
    forever, which has been introduced and removed three times in this repo.
    """
    m = re.search(rf"{tool} (\d{{4}}-\d{{2}}-\d{{2}})", note or "")
    if not m:
        return True
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days >= days
