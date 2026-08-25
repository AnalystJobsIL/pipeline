#!/usr/bin/env python3
"""One command that answers "is the registry still whole, and can it still crack anything?"

Read-only. It never writes `companies.csv`; the only file it may write is its own census.
It exists because three questions had no answer anywhere in this repo:

1. **Did a company DISAPPEAR from `companies.csv`, and why?**
   No tool deletes rows — every writer is re-read-modify-write or append-only. But a HUMAN
   commit does, and the git layer makes that non-durable: `Time To Know` was deleted on
   purpose (`9c4372ef`, "time.com is Time To Know"), **resurrected** by a concurrent cloud
   run's conflict merge (`8644d8fd`, `row-merged state`, 1190 -> 1191 rows), and then
   re-deleted as a silent side effect of a commit about Oracle HCM (`0180e755`). Fifteen
   name-deletions exist in the whole history of the file and nothing anywhere reports one.
   `check_invariants.py` checks the SHAPE of the registry, never its SIZE.

2. **Is every parked row still owned by a recurring job?** ARCHITECTURE.md section 2 has an
   ownership matrix that was typed by hand. `pools()` below computes it from the same
   predicates the tools use, so the doc can be re-derived instead of trusted.

3. **Can the resolution ladder still do anything?** Every rung fails by returning an empty
   list: no SerpApi quota, no Bright Data key, no `claude` binary, no Playwright. That is
   the documented #1 bug class (silent exclusion) sitting under the most expensive job in
   the system - the 200-minute nightly hunt.

`alarms()` turns all three into short lines meant for the digest's run-audit block, and
`--census` records them in `cloud_state/registry_alarms.json` as an audit trail; the digest
calls `alarms_state()` directly and never reads that file.
See docs/BACKLOG.md ("Registry alarms in the daily mail") for the four-line hook that is
NOT in this lane to make.

Usage:
  python registry_health.py               # full report, no writes, no network
  python registry_health.py --resources   # also probe every rung live (spends <=1 BD credit)
  python registry_health.py --ats         # the unsupported-ATS inventory (what to build next)
  python registry_health.py --census      # update cloud_state/registry_census.json + alarms
  python registry_health.py --json        # machine-readable everything
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys

from pipeline.aggregators import is_aggregator
from pipeline.atomic import write_json
from pipeline.recruiters import is_recruiter
from pipeline import identity_gate as _gate
from pipeline.verdicts import in_pool, is_terminal as _verdicts_terminal

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). Company names here
# are Hebrew as often as not, and an UnicodeEncodeError in the REPORT would kill the process
# that is reporting. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CSV_PATH = "companies.csv"
CENSUS = os.path.join("cloud_state", "registry_census.json")
# sentinel side-car key. `__notes__` would be silently absorbed by a company literally so
# named; a slash cannot appear in a company_name that also has to be a csv field we match on.
_NOTES_KEY = "//notes//"
ALARMS = os.path.join("cloud_state", "registry_alarms.json")
# The resolution ladder lives in ITS OWN file, written only by the job that can honestly
# probe it (listing-hunt.yml: Playwright + Bright Data). `alarms_state` READS this file and
# never writes it, so a re-emission can never feed back into what it re-emits.
LADDER = os.path.join("cloud_state", "registry_ladder.json")
_POOLS_KEY = "//pools//"        # per-tool pool sizes in the census, for pool_floor
TODAY = dt.date.today().isoformat()

# A row may leave the registry only for one of these reasons, and the reason must LEAD one
# of the note's ` | `-separated segments. A bare substring search over the whole note was
# wrong in both directions and was measured on 2026-08-23: 45 rows (7 of them ACTIVE) would
# have had their deletion filed under "removed (explained)" — the line a reader skips —
# because `SmartRecruiters` contains "recruiter" (Armis, HiBob, kueez and the other 12
# smartrecruiters rows) and the TO-DO note `aggregator URL; resolve real careers page before
# activating` contains "aggregator" (Chunk Foods, StarkWare, Zipher, vi). An aggregator URL
# is a to-do, never a tombstone, so it is gone from this list entirely; agency-hood is
# decided by the company NAME via is_recruiter, never by text found in the note.
_REASON = re.compile(r"^(defunct|domain-dead|alias-of|duplicate of|redundant|"
                     r"sidebar-poisoned|removed \d{4}-\d{2}-\d{2})(?=\W|$)", re.I)


def explained(company: str, note: str) -> bool:
    """Is this row's disappearance accounted for by its own last note?"""
    if is_recruiter(company or ""):
        return True                       # agencies are excluded by policy, not by verdict
    return any(_REASON.match(seg.strip()) for seg in str(note or "").split("|"))


def is_terminal_note(note: str) -> bool:
    """THE shared terminal list (`pipeline.verdicts.TERM_RX`). A private copy here once
    omitted `duplicate of`/`redundant` and made 4 of the 5 rows this tool reported as
    "OWNED BY NOTHING" false positives (NICE, Via Transportation, Marvell Israel, Google)."""
    return _verdicts_terminal(note or "")


# Every pool mirror below IMPORTS the tool's own `in_*_pool` predicate. A retyped mirror
# reported rows as hunt-owned after a selector edit removed them from the actual hunt
# (wave-4 R3: one dropped alternative, 27 rows gone, this matrix still green).
# the tool's own constant (probe_candidates imports only stdlib + pipeline.atomic, so
# unlike repair_extract_gap it is safe at module level). The old copy here was re.I where
# the tool is case-sensitive -- measured 136 -> 136 on the real registry, zero rows moved.
# _EXTRACT_GAP, the looser retyped extract-gap mirror, is deleted: `_extract_gap_mode()`
# below has imported the tool's own MODE since the rebuild and nothing else read the copy.
from probe_candidates import PROBE_POOL as _PROBE_SHAPE


def read_rows(path=CSV_PATH):
    """Body rows only (header dropped), each a 6-field list."""
    rows = [r for r in csv.reader(open(path, encoding="utf-8")) if r and len(r) >= 6]
    return rows[1:] if rows and rows[0][0] == "company_name" else rows


# ---------------------------------------------------------------- census / deletion guard

def census(rows):
    """{company_name: "true"/"false"} — the smallest thing that detects a vanished row.

    Tolerates a malformed (short) row: `census_diff` is public and BACKLOG item 3 invites
    external callers, so it must not raise IndexError on rows that did not come through
    `read_rows()`.
    """
    return {r[0]: (r[4] if len(r) > 4 else "") for r in rows if r}


def load_census(path=CENSUS):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def census_diff(rows, prev=None):
    """What changed since the last census: gone / added / deactivated / reactivated.

    `gone` carries the LAST KNOWN NOTE for each vanished row, because "why was this deleted"
    is otherwise only answerable by `git log -S`. A vanished row whose last note gives no
    GOOD_REMOVAL reason is the thing this whole module exists to shout about.
    """
    prev = load_census() if prev is None else prev
    now = census(rows)
    notes = {r[0]: (r[5] if len(r) > 5 else "") or "" for r in rows if r}
    _nk = _NOTES_KEY if _NOTES_KEY in prev else "__notes__"      # read the older format too
    prev_notes = (prev.get(_nk) or {}) if isinstance(prev.get(_nk), dict) else {}
    prev_active = {k: v for k, v in prev.items()
                   if k not in (_NOTES_KEY, "__notes__", _POOLS_KEY)}
    gone, unexplained = [], []
    for name in prev_active:
        if name in now:
            continue
        why = prev_notes.get(name, "")
        ok = explained(name, why)
        gone.append({"company": name, "last_note": why[:160], "explained": ok})
        if not ok:
            unexplained.append(name)
    added = [n for n in now if n not in prev_active]
    flipped_off = [n for n in now if prev_active.get(n) == "true" and now[n] == "false"]
    flipped_on = [n for n in now if prev_active.get(n) == "false" and now[n] == "true"]
    return {"rows": len(now), "active": sum(1 for v in now.values() if v == "true"),
            "prev_rows": len(prev_active), "gone": gone, "unexplained": unexplained,
            "added": added, "deactivated": flipped_off, "reactivated": flipped_on,
            "first_census": not prev_active, "_now": now, "_notes": notes}


def _reason_tail(note, cap=200):
    """The note's NEWEST whole segments, up to `cap`.

    `note[:cap]` keeps the OLDEST text — and the newest segment lives at the END, which is
    the exact trim bug ARCHITECTURE section 2 documents for the notes cell and which this
    function shipped anyway. A removal reason is written just before the row goes, so
    truncating the tail throws away the only thing the census needs.
    """
    parts = [p.strip() for p in str(note or "").split("|") if p.strip()]
    out = []
    for p in reversed(parts):
        if out and len(" | ".join([p] + out)) > cap:
            break
        out.insert(0, p)
    return " | ".join(out) if out else str(note or "")[-cap:]


def save_census(rows, path=CENSUS):
    d = census(rows)
    d[_NOTES_KEY] = {r[0]: _reason_tail(r[5]) for r in rows}
    # per-tool pool sizes, so tomorrow's `pool_floor` has a baseline. Keyed by the tool
    # name (`label.split(" (")[0]`), not the label: a cron edit must not reset the baseline.
    d[_POOLS_KEY] = {label.split(" (")[0]: len(m) for label, m in pools(rows).items()}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write_json(path, d, indent=0, sort_keys=True)
    return len(d) - 2


# ---------------------------------------------------------------- the ownership matrix

def _extract_gap_pool():
    """The tool's OWN predicate, imported (`_EXTRACT_GAP` was a retyped mirror, LOOSER than
    the tool -- the direction that hides orphans; then `MODE` alone, which lacked the
    terminal exclusion the tool itself lacked until 2026-08-25). Lazy because
    `repair_extract_gap` pulls in the scraper stack at import."""
    from repair_extract_gap import in_extract_gap_pool
    return in_extract_gap_pool


def pools(rows):
    """Recompute ARCHITECTURE.md section 2's ownership matrix from the tools' own predicates.

    **Import the predicate, never retype it.** The first version of this function retyped
    each tool's filter, which made it the SIXTH hand-maintained copy of the pool definitions
    in a repo whose worst documented bug was three copies drifting — and it had already
    drifted on the day it shipped (measured 2026-08-23):

      * `triage_dark` mirror 270 vs real 242 — the copy omitted `SKIP_NOTES`
        (`defunct|domain-dead|recruiter|duplicate|redundant|alias-of`), over-counting 28 rows
        and publishing 270 into ARCHITECTURE section 2.
      * `listing_hunt` mirror 244 vs real 243 — the copy omitted `looks_like_junk`, so the
        discovery-leaked "company" `AppSec` was reported as owned by the hunt.

    Because `orphans()` subtracts this membership, every such row is falsely marked owned:
    a mirror that over-counts can only ever UNDER-report orphans, which is the one direction
    that loses coverage silently. So each entry below is built from the tool's own imported
    constants. Where a tool still inlines its filter in `main()`, that is noted — extracting
    a `targets(rows)` from each is docs/BACKLOG.md, "One pool predicate per tool".

    Staleness cooldowns are deliberately NOT applied: a cooldown delays a re-check, it does
    not remove ownership.
    """
    import triage_dark as _triage
    import crack_walled as _crack
    import probe_candidates as _probe
    import listing_hunt as _hunt
    from pipeline.firmographics import looks_like_junk

    parked = [r for r in rows if r[4] == "false"]

    def sel(pred):
        return [r for r in parked if pred(r[5] or "", r)]

    return {
        "triage_dark (18:00 daily)":
            sel(lambda n, r: _triage.in_triage_pool(r)),
        "listing_hunt (19:00 daily)": sel(lambda n, r: _hunt.in_hunt_pool(r)),
        "repair_extract_gap (19:00 daily)":
            sel(lambda n, r: _extract_gap_pool()(r)),
        # IMPORT the tool's own predicate, do not retype it. The retyped version was
        # `"unsupported ATS" in n`, which is only half of `is_walled` -- it missed the
        # host-derived half and under-counted this pool by 7 rows, and `orphans()` subtracts
        # this membership, so it under-reported orphans by the same rows.
        "crack_walled (19:00 daily + Sun)":
            sel(lambda n, r: _crack.in_crack_pool(r)),
        "probe_candidates (05:00 daily)":
            sel(lambda n, r: _probe.in_probe_pool(r)),
        "audit_empty_rows (Sun 04:00)":
            sel(lambda n, r: in_pool(n) and not is_terminal_note(n) and not is_recruiter(r[0])),
        "deep_validate (Sat 04:00)":
            sel(lambda n, r: in_pool(n) and not is_terminal_note(n) and not is_recruiter(r[0])),
    }


def orphans(rows):
    """Parked rows owned by NO recurring job — permanently dark coverage."""
    owned = set()
    for members in pools(rows).values():
        owned.update(r[0] for r in members)
    return [r[0] for r in rows
            if r[4] == "false" and not is_terminal_note(r[5] or "")
            and not is_recruiter(r[0]) and r[0] not in owned]


# ---------------------------------------------------------------- what can still crack

# `unsupported ATS <x>` means "deep_validate recognised the platform and stamped it", NOT
# "no fetcher exists" - so a BUILD queue that does not check hands the ats-fetch lane work it
# has already done. What those rows actually need is WIRING: crack_walled sniffing the tenant
# endpoint and the row moving to that platform.
#
# Deliberately no count in this comment. It said "34 of 57", then "32 rows, all 8 wired" -
# and every one of those numbers was wrong. `--ats` on 2026-08-24 reports 3 WIRE / 5 BUILD
# over 54 rows, and it reported the same at the commit that wrote the second claim. The point
# of this function is that the count is derived; typing one into a comment beside it has now
# produced two false statements in two days. Run `--ats`.
# FETCHER names (the registry's col-1 vocabulary), NOT wall names -- the deliberate
# counterpart of `identity_gate._PLATFORM_ALIAS`; see the note there. oraclecloud (wall)
# is fetched by oraclehcm once cracked.
_FETCHER_ALIAS = {"eightfold.ai": "eightfold", "oraclecloud.com": "oraclehcm",
                  "icims.com": "icims", "jobvite.com": "jobvite", "taleo.net": "taleo",
                  "avature.net": "avature"}


def _fetcher_for(plat):
    """The native fetcher that already reads this platform, or "" if there is none."""
    try:
        from pipeline.fetchers import FETCHERS
    except Exception:  # noqa: BLE001
        return ""
    key = _FETCHER_ALIAS.get(plat, plat)
    return key if key in FETCHERS else ""


def unsupported_ats(rows):
    """Every ATS the resolvers recognised but cannot READ, with the rows waiting on it.

    This is the hand-off to the `ats-fetch` lane: ARCHITECTURE.md section 1's support policy
    is "a platform seen 3+ times gets a native fetcher", and until now nothing counted.
    """
    # `( +)` not `( *)` on purpose, but the platform name is OPTIONAL in the wild: the
    # row `Bit` carries a bare `unsupported ATS` with nothing after it, so this regex
    # matched 54 of the 55 rows and the 55th vanished from the build queue with no
    # message. A row that says "unsupported ATS" and never appears in the queue built to
    # find it is section 8's first bug class, inside the tool written to detect it.
    rx = re.compile(r"unsupported ATS ?([A-Za-z0-9_.\- ]*)")
    out = {}
    for r in rows:
        m = rx.search(r[5] or "")
        if not m:
            continue
        plat = m.group(1).strip().lower().split(";")[0].strip()
        if not plat:
            # A bare `unsupported ATS` with no platform after it. `continue` here dropped
            # the row from the queue silently - 54 reported against 55 carrying the token.
            # It is still a row somebody has to look at, so it gets a bucket that says so
            # rather than disappearing.
            plat = "(unnamed platform)"
        e = out.setdefault(plat, {"rows": 0, "active": 0, "companies": [],
                                  "fetcher": _fetcher_for(plat)})
        e["rows"] += 1
        e["active"] += (r[4] == "true")
        if len(e["companies"]) < 12:
            e["companies"].append(r[0])
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["rows"]))


def resources(live=False):
    """Every rung of the resolution ladder, and whether it can do anything right now.

    Each of these fails by returning an empty list, never by raising, so an expired token
    looks exactly like "no company matched today". `live=True` costs at most one Bright Data
    credit and one SerpApi *account* call (which does not consume a search).
    """
    import shutil
    # Local runs keep their keys in the gitignored secrets.env; in Actions the same names
    # arrive as repo secrets. Without this the probe reports every paid rung DOWN on the dev
    # machine — a health check that cries wolf is a health check nobody reads.
    try:
        from bd_rescue import _load_secrets
        _load_secrets()
    except Exception:  # noqa: BLE001
        pass
    out = {}

    def add(key, ok, detail):
        out[key] = {"ok": bool(ok), "detail": detail}

    add("claude CLI (role judgments, listing pick, LLM resolve)",
        shutil.which("claude"), shutil.which("claude") or "not on PATH")
    add("CLAUDE_CODE_OAUTH_TOKEN",
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        "set" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else
        "unset (fine locally: the CLI has its own login; REQUIRED in Actions)")
    bd = bool(os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE"))
    add("Bright Data unlocker (google_via_unlocker, blocked-page fetch)", bd,
        "key+zone set" if bd else "missing key or zone — the ONLY working search rung is off")
    try:
        import playwright  # noqa: F401
        add("Playwright/Chromium (render, XHR sniff, crack_walled)", True, "importable")
    except Exception as e:  # noqa: BLE001
        add("Playwright/Chromium (render, XHR sniff, crack_walled)", False, str(e)[:60])

    if not live:
        add("SerpApi", bool(os.environ.get("SERPAPI_KEY")),
            "key present; quota NOT checked (use --resources)"
            if os.environ.get("SERPAPI_KEY") else "no SERPAPI_KEY")
        return out

    key = os.environ.get("SERPAPI_KEY", "")
    left = None
    if key:
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"https://serpapi.com/account?api_key={key}", timeout=20) as r:
                left = int(json.load(r).get("total_searches_left") or 0)
        except Exception as e:  # noqa: BLE001
            left = None
            add("SerpApi", False, f"account check failed: {str(e)[:50]}")
    if left is not None:
        add("SerpApi", left > 0, f"{left} searches left this month")
    elif not key:
        add("SerpApi", False, "no SERPAPI_KEY")
    try:
        from deep_validate import ddg
        n = len(ddg("Wix") or [])
        add("DuckDuckGo HTML (free search rung)", n > 0,
            f"{n} results" if n else "0 results — blocked from this machine (works on runners)")
    except Exception as e:  # noqa: BLE001
        add("DuckDuckGo HTML (free search rung)", False, str(e)[:60])
    if bd:
        try:
            from deep_validate import google_via_unlocker
            n = len(google_via_unlocker("Wix") or [])
            add("Bright Data Google (paid search rung)", n > 0, f"{n} results (1 credit spent)")
        except Exception as e:  # noqa: BLE001
            add("Bright Data Google (paid search rung)", False, str(e)[:60])
    return out


# ---------------------------------------------------------------- the mail lines

def alarms_state(rows=None, prev=None):
    """The alarms that belong in the DAILY MAIL: registry facts only, no env, no network.

    `alarms()` also reports the resolution ladder, and the ladder is a property of the JOB
    that runs it, not of the digest. `daily-digest.yml` installs no Playwright and sets
    BRIGHTDATA_* only on three unrelated steps, so calling the full `alarms()` from
    `pipeline/run.py` — which is what docs/BACKLOG.md item 3 used to prescribe — puts two
    PERMANENTLY FALSE lines in the email every single day:

        resolution rung DOWN: Bright Data unlocker ... missing key or zone
        resolution rung DOWN: Playwright/Chromium ... No module named 'playwright'

    (Reproduced 2026-08-23 by running `alarms()` with those three names unset and playwright
    unimportable.) A daily audit block nobody reads is the thing this module exists to avoid,
    so the mail hook calls THIS function. Ladder status reaches the mail the honest way: the
    one job that can probe the ladder (listing-hunt.yml) writes `cloud_state/
    registry_ladder.json` via `--ladder`, and this function re-emits its rungs and reports
    the file's DATE when it goes stale — which is also how a workflow that stopped running
    becomes visible.

    Every line here must be STABLE while the underlying state is stable: the inbox relay
    dedups the digest on a content hash, so a line carrying "Nd old" or "as of <today>"
    would re-email the whole digest every day, forever. Dates in this output are always
    the date something last HAPPENED, never today's.
    """
    rows = read_rows() if rows is None else rows
    out = []
    d = census_diff(rows, prev=prev)
    if not d["first_census"]:
        if d["unexplained"]:
            out.append(f"{len(d['unexplained'])} companies REMOVED from the registry with no "
                       f"reason in their note: {', '.join(d['unexplained'][:5])}")
        explained_names = [g["company"] for g in d["gone"] if g["explained"]]
        if explained_names:
            out.append(f"{len(explained_names)} companies removed (explained): "
                       f"{', '.join(explained_names[:5])}")
        if d["prev_rows"] and d["rows"] < d["prev_rows"] * 0.98:
            out.append(f"registry shrank {d['prev_rows']} -> {d['rows']} rows (>2%) — "
                       f"suspect a truncated write or a bad merge")
    orph = orphans(rows)
    if orph:
        # every orphan is permanently dark coverage, so report from the first one. The old
        # threshold of >10 hid the single real orphan behind four false positives that came
        # from a private TERMINAL list narrower than pipeline.verdicts'.
        out.append(f"{len(orph)} parked rows owned by NO recurring job (retired coverage): "
                   f"{', '.join(orph[:5])}")
    for label, members in pools(rows).items():
        if not members and label.startswith(("triage_dark", "listing_hunt", "probe_candidates")):
            out.append(f"re-check pool EMPTY: {label} — a predicate inverted, or the notes "
                       f"column was clobbered")
    out += pool_floor(rows, prev=prev)
    try:
        stamp = json.load(open(LADDER, encoding="utf-8"))
        when = stamp.get("date") or "1970-01-01"
        age = (dt.date.today() - dt.date.fromisoformat(when)).days
        if age > 2:
            # the file's date, not an age: stable while stale, changes only when the
            # refreshing workflow actually runs (see the docstring on dedup)
            out.append(f"registry ladder last refreshed {when} ({LADDER}) — the workflow "
                       f"that refreshes it has not run")
        # `--ladder` writes rung lines only, from the job that can probe them; this file is
        # never written by anything that reads it, so no re-emission can loop back.
        out += [f"(ladder) {x}" for x in (stamp.get("rungs") or []) if "rung DOWN" in x]
    except Exception:  # noqa: BLE001
        pass
    return out


def pool_floor(rows, prev=None):
    """Per-tool pool floors (docs/BACKLOG.md 34). `check_invariants` check E has ONE
    aggregate floor (`pool_n < 50`) and wave 8 watched `crack_walled` go 25 -> 2 -> 0
    under it, green every night. This compares each tool's pool to the size the last
    census recorded. Thresholds are literal on purpose: `alarms_state` is pinned against
    reading env. The first census after deploy has no `//pools//` and never alarms."""
    prev = load_census() if prev is None else prev
    was = prev.get(_POOLS_KEY) or {}
    if not was:
        return []
    out = []
    for label, members in pools(rows).items():
        tool = label.split(" (")[0]
        before, now = was.get(tool), len(members)
        if before is None:
            continue
        if before > 0 and now == 0:
            out.append(f"re-check pool COLLAPSED to zero: {tool} was {before} — a predicate "
                       f"inverted or the notes column was clobbered")
        elif before >= 8 and now < before * 0.5:
            out.append(f"re-check pool halved: {tool} {before} -> {now}")
    return out


def alarms(rows=None, live=False, res=None, prev=None):
    """Short lines for the digest run-audit. Empty list = the registry is healthy.

    Deliberately terse and deliberately few: a daily audit block nobody reads is a daily
    audit block nobody reads. Only conditions that mean COVERAGE IS BEING LOST appear here.

    `res` takes an already-probed `resources()` result. Pass it: a live probe spends a Bright
    Data credit and a second DuckDuckGo request, and calling this after `_report` used to
    run the whole ladder twice — the second unlocker call came back empty and the report
    contradicted itself in adjacent lines. `prev` overrides the on-disk census, for tests
    and for asking "what would this say against last week's baseline".
    """
    rows = read_rows() if rows is None else rows
    out = alarms_state(rows, prev=prev)
    for key, st in (res if res is not None else resources(live=live)).items():
        if not st["ok"] and not key.startswith(("SerpApi", "CLAUDE_CODE_OAUTH_TOKEN",
                                                "DuckDuckGo")):
            out.append(f"resolution rung DOWN: {key} — {st['detail']}")
    return out


# ---------------------------------------------------------------- report

def _report(rows, live=False, want_ats=False, ladder=True):
    from collections import Counter
    act = [r for r in rows if r[4] == "true"]
    print(f"registry: {len(rows)} rows · {len(act)} active · {len(rows) - len(act)} parked")
    plat = Counter(r[1] for r in act)
    print("  active by platform: " + ", ".join(f"{k}={v}" for k, v in plat.most_common()))
    api = sum(v for k, v in plat.items() if k not in ("scrape", "discovery"))
    print(f"  native-ATS rows {api} · scrape rows {plat.get('scrape', 0)} · "
          f"discovery rows {plat.get('discovery', 0)}")

    d = census_diff(rows)
    print(f"\ncensus (vs {CENSUS}):")
    if d["first_census"]:
        print("  no previous census — run --census to establish the baseline")
    else:
        print(f"  {d['prev_rows']} -> {d['rows']} rows · +{len(d['added'])} added · "
              f"-{len(d['gone'])} gone · {len(d['deactivated'])} parked · "
              f"{len(d['reactivated'])} re-activated")
        for g in d["gone"]:
            print(f"  {'[ok]' if g['explained'] else '[??]'} GONE {g['company']}: "
                  f"{g['last_note'][:90] or '(no note)'}")

    print("\nre-check ownership (recomputed from each tool's own filter):")
    for label, members in pools(rows).items():
        print(f"  {len(members):4}  {label}")
    orph = orphans(rows)
    print(f"  {len(orph):4}  OWNED BY NOTHING" + (f": {orph[:6]}" if orph else ""))

    res = None
    if ladder:
        print("\nresolution ladder:")
        res = resources(live=live)      # bind it: `alarms(..., res=res)` below needs it,
        for key, st in res.items():     # and probing twice costs a Bright Data credit
            print(f"  [{'OK' if st['ok'] else '--'}] {key}: {st['detail']}")

    if want_ats:
        print("\nunsupported ATS platforms — rows waiting on a native fetcher")
        print("  (ARCHITECTURE.md section 1: 3+ rows earns one; recipe in section 6)")
        for plat_name, e in unsupported_ats(rows).items():
            flag = ("WIRE " if e["fetcher"] else "BUILD" if e["rows"] >= 3 else "     ")
            note = f" [fetcher `{e['fetcher']}` EXISTS — crack the tenant, don't build]" \
                if e["fetcher"] else ""
            print(f"  {flag} {plat_name:18} {e['rows']:3} rows ({e['active']} active): "
                  f"{', '.join(e['companies'][:6])}{note}")

    a = (alarms(rows, live=live, res=res) if ladder else alarms_state(rows))
    print(f"\nalarms for the daily mail: {len(a)}")
    for line in a:
        print(f"  ! {line}")
    return a


def explain(name, rows=None, fetch=False, out=print):
    """`python registry_health.py --explain "<name>" [--fetch]` -- why was this row
    activated or refused? Every predicate the gates use, with its REAL return value and
    the inputs it compared, in the order the gates consult them.

    OFFLINE by default, absolutely: `page_names_company` is a 25s GET plus, when the page
    is short and BRIGHTDATA_API_KEY is set, a paid Bright Data unlock; `ok_to_write`,
    `activation_ok` and `identity_ok` all reach it. So without `--fetch` none of those four
    is called and `resources()` is never called (it loads secrets.env into os.environ and
    would arm the unlocker for the rest of the process). Pinned by a test that makes any
    network call raise.
    """
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    from pipeline import company_identity as C
    from pipeline.aggregators import is_aggregator
    from pipeline.firmographics import looks_like_junk
    from pipeline.verdicts import in_pool
    import listing_hunt as _hunt
    import probe_candidates as _probe
    import triage_dark as _triage
    import crack_walled as _crack
    from merge_csv_rows import _TOOL
    rows = read_rows() if rows is None else rows
    key = " ".join((name or "").strip().lower().split())
    row = next((r for r in rows if " ".join(r[0].strip().lower().split()) == key), None)
    if row is None:
        out(f"no registry row named {name!r} (match is case-insensitive, exact otherwise)")
        return 1
    name, plat, tok, api, active, note = row[:6]
    out(f"== row ==\n  {name} | {plat} | token={tok!r} | active={active}\n  {api}")
    for seg in [x.strip() for x in (note or "").split("|") if x.strip()]:
        out(f"  note | {seg}")

    out("== exclusions (any True parks the row before identity is even asked) ==")
    out(f"  is_recruiter          = {is_recruiter(name)}")
    out(f"  is_aggregator(api)    = {is_aggregator(api)}")
    out(f"  looks_like_junk       = {looks_like_junk(name)}")

    out("== declared identity (pipeline/identity_facts.py -- consulted before any heuristic) ==")
    fx = F.facts(name)
    if fx:
        out(f"  DECLARED tenants={sorted(F.tenants(name))} domains={list(F.domains(name))}")
        out(f"  why: {fx.get('why', '')}")
    else:
        out("  none declared -- to make an acquired company's board legitimate, add a row to "
            "pipeline/identity_facts.DECLARED (never a note token, never a rename)")

    out("== identity, offline ==")
    out(f"  looks_like_a_job_listing_page = {C.looks_like_a_job_listing_page(api)}")
    out(f"  verdict                       = {C.verdict(name, api)!r}")
    out(f"  is_foreign                    = {C.is_foreign(name, api)}  (False on EVERY ATS host by design)")

    out("== platform ==")
    out(f"  host_platform = {G.host_platform(api)!r}   is_walled = {G.is_walled(row)}")

    out("== tenant (subdomain-tenant platforms only; True means 'not refused', incl. vacuously) ==")
    import urllib.parse as _up
    host = (_up.urlparse(api or "").netloc or "").lower()
    # reads two privates of identity_gate on purpose: re-implementing the comparison here
    # is how a mirror is born. A public `tenant_evidence()` is filed as follow-up.
    labels = [l for l in host.split(".")[:-2] if not G._plumbing(l)] if host else []
    out(f"  subdomain platform = {bool(G._SUBDOMAIN_TENANT_HOST.search(host))}   "
        f"checkable labels = {labels}   name targets = {sorted(G._name_targets(name))}")
    out(f"  tenant_is_this_company = {G.tenant_is_this_company(name, api)}")
    if tok:
        out(f"  embedded_board_ok(token={tok!r}) = {G.embedded_board_ok(name, tok, api)}")

    out("== page test ==")
    if fetch:
        v = G.page_names_company(name, api)
        out(f"  page_names_company = {v!r}" + ("  (None = could not read -- NO EVIDENCE; "
                                              "ok_to_write refuses on None)" if v is None else ""))
    else:
        out("  not fetched; pass --fetch (1 GET, and up to 1 Bright Data unlock if the page is short)")

    out("== pools (who re-checks this row if it is parked) ==")
    for label, pred in (("triage_dark (18:00 daily)", _triage.in_triage_pool),
                        ("listing_hunt (19:00 daily)", _hunt.in_hunt_pool),
                        ("crack_walled (19:00 daily + Sun)", _crack.in_crack_pool),
                        ("probe_candidates (05:00 daily)", _probe.in_probe_pool)):
        out(f"  {label:34} {bool(pred(row))}")
    out(f"  {'audit_empty_rows / deep_validate':34} {bool(active == 'false' and in_pool(note or '') and not is_terminal_note(note or ''))}")
    out(f"  {'terminal (no pool may re-open)':34} {is_terminal_note(note or '')}")

    out("== last stamp -> tool -> gate ==")
    segs = [x.strip() for x in (note or "").split("|") if x.strip()]
    last = segs[-1] if segs else ""
    m = _TOOL.match(last)
    tool = m.group(1) if m else "(untagged prose)"
    tool_file = {"listing-hunt": "listing_hunt.py", "crack-walled": "crack_walled.py",
                 "dark-triage": "triage_dark.py", "deep-validated": "deep_validate.py",
                 "re-audit": "audit_empty_rows.py", "repair": "repair_dead_urls.py",
                 "probe-woken": "probe_candidates.py", "bd-tried": "bd_rescue.py",
                 "scanned via brightdata": "bd_rescue.py"}.get(tool, "")
    gates = [g for g, files in G.GATE_CALLERS.items() if tool_file in files]
    out(f"  last segment: {last!r}\n  stamped by: {tool}  ({tool_file or 'n/a'})\n"
        f"  that tool's gate(s): {gates or ['none -- it does not activate']}")
    return 0


_FLAGS = ("--explain", "--fetch", "--resources", "--ats", "--census", "--ladder", "--json")


def main():
    argv = sys.argv[1:]
    unknown = [a for a in argv if a.startswith("--") and a not in _FLAGS]
    if unknown:
        # an unknown flag used to print the default report and exit 0 -- `--pools` looked
        # like it had answered (docs/BACKLOG.md 44)
        print(f"registry_health: unknown flag(s) {unknown}; known: {', '.join(_FLAGS)}")
        return 2
    live = "--resources" in argv
    rows = read_rows()
    if "--explain" in argv:
        i = argv.index("--explain")
        who = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
        return explain(who, rows, fetch="--fetch" in argv)
    if "--json" in argv:
        _res = resources(live=live)
        print(json.dumps({"census": {k: v for k, v in census_diff(rows).items()
                                     if not k.startswith("_")},
                          "pools": {k: len(v) for k, v in pools(rows).items()},
                          "orphans": orphans(rows),
                          "unsupported_ats": unsupported_ats(rows),
                          "resources": _res,
                          "alarms": alarms(rows, live=live, res=_res)}, indent=1,
                         ensure_ascii=False))
        return 0
    if "--ats" in argv and len(argv) == 1:
        for plat_name, e in unsupported_ats(rows).items():
            # SAME ladder as the report path above, which labels BUILD only at 3+ rows
            # (ARCHITECTURE.md section 1's support policy). These two paths of one tool
            # printed different verdicts for the same platform: `jobvite` (1 row) was
            # `BUILD` here and blank there.
            flag = ("WIRE " if e["fetcher"] else "BUILD" if e["rows"] >= 3 else "below")
            print(f"{flag} {plat_name:18} {e['rows']:3} rows "
                  f"({e['active']} active): {', '.join(e['companies'])}")
        return 0
    if "--ladder" in argv:
        # the ladder file: rung lines ONLY, from the one job that can honestly probe them.
        # live=False: reads keys/imports, spends nothing.
        rungs = [f"resolution rung DOWN: {k} — {st['detail']}"
                 for k, st in resources(live=False).items()
                 if not st["ok"] and not k.startswith(("SerpApi", "CLAUDE_CODE_OAUTH_TOKEN",
                                                       "DuckDuckGo"))]
        os.makedirs(os.path.dirname(LADDER) or ".", exist_ok=True)
        write_json(LADDER, {"date": TODAY, "rungs": rungs})
        print(f"ladder written: {len(rungs)} rung(s) down -> {LADDER}")
        return 0
    # `--census` runs inside the digest's census step, which has no Bright Data env and
    # no Playwright: probing the ladder THERE printed two permanently false `rung DOWN`
    # lines at the top of the operator's report every morning (2026-08-25). The ladder
    # belongs to `--ladder` in listing-hunt.yml, the one job that can honestly probe it.
    a = _report(rows, live=live, want_ats=("--ats" in argv or "--census" in argv),
                ladder="--census" not in argv)
    if "--census" in argv:
        # The MAIL alarms (alarms_state, no ladder) are what this file records: writing the
        # full `alarms()` here put two permanently-false `rung DOWN` lines into a file the
        # mail hook re-emits (docs/BACKLOG.md 13, the second time). Computed BEFORE the
        # census is saved, so it is judged against the previous baseline.
        a_mail = alarms_state(rows)
        n = save_census(rows)
        os.makedirs(os.path.dirname(ALARMS) or ".", exist_ok=True)
        write_json(ALARMS, {"date": TODAY, "alarms": a_mail})
        print(f"\ncensus written: {n} companies -> {CENSUS}; {len(a_mail)} mail alarms -> "
              f"{ALARMS} (full report above: {len(a)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
