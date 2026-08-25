"""Shared ATS-health recording.

Turns per-company fetch outcomes into a stale-board list + a persistent baseline. Called
INLINE by the daily run (pipeline.run) so detection is a free byproduct of the fetch that
already happens every morning — a broken board is noticed within a day, not a week. The
standalone weekly sweep (health_check.py) reuses the same logic as a backstop.

Stale reasons, in the order they are decided:
  misconfig-scrape-on-ats — set to `scrape` while the URL is a real ATS host
  fetch-error             — the fetch raised: the endpoint 404s / 422s / times out, or the
                            fetcher itself said the board is empty worldwide
                            (`fetchers.BoardEmpty`) or mis-pointed (ValueError) — or, for a
                            scrape row that HAD postings, last night's scraper could not read
                            the page (`cloud_state/scrape_rot.json` says `why: error`)
  regressed-to-zero       — had postings before (baseline > 0), now 0
  empty-board             — a real ATS returning literally 0 postings (moved board /
                            stale token / anti-bot) — flagged even with no baseline

Neither `empty-board` nor `regressed-to-zero` is raised for a fetcher that already asks the
board for Israel (`fetch_x.israel_scoped = True` in pipeline/fetchers.py): its zero means
"no Israel roles" and its baseline is a search-hit count (Workday's `searchText=Israel`
matches text anywhere), so "had 1, now 0" is noise; the fetcher itself raises `BoardEmpty`
when the board is empty worldwide, which is the question a regression flag was asking.
"No Israel roles" is what most global tenants say every day — 25 healthy Workday boards sat
in the self-heal queue on 2026-08-24 for exactly this. `empty-board` (ONLY that one) is
also skipped for the two pseudo-platforms — a scrape row's emptiness is
`refresh_scrape_cache.py`'s business; a scrape row that had postings and now has none stays
`regressed-to-zero` (25 rows on 2026-08-24), because the self-heal pool and the targeted
discovery sweep read that flag.

A scrape row's zero is read together with what the scraper recorded about it overnight
(`overnight_verdict`, from `cloud_state/scrape_rot.json`): a page that could not be read is
a `fetch-error` with the scraper's reason, and a page where roles were found but none in
Israel is a measurement — neither is a "regression". Until 2026-08-26 both read as
`regressed-to-zero` (34 rows that morning: 2 walls/timeouts, Wiliot with 8 roles and none
in Israel, 31 honest zeros), because the rot file had no reader.

The mail line (`mail_lines`) is what makes any of this visible: `stale.json` is read by the
self-heal job, not by a person.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re

from .atomic import write_json

ATS_HOST = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
                      r"comeet\.co|workable\.com|recruitee\.com|myworkdayjobs|"
                      # added 2026-08-22 after pipeline/platform_check.py showed native
                      # platforms missing here — a row misconfigured as `scrape` on one of
                      # these hosts was never flagged misconfig-scrape-on-ats.
                      # `applytojob.com|jazz.co` left 2026-08-26 with the `jazzhr` platform:
                      # JazzHR has no public JSON, so a scrape row on that host is the RIGHT
                      # configuration (Questar, 4 Herzliya roles), not a misconfiguration.
                      r"breezy\.hr|bamboohr\.com|oraclecloud\.com|"
                      r"amazon\.jobs|careers\.microsoft\.com", re.I)
BASELINE = "cloud_state/health_baseline.json"   # committed, so it persists across cloud runs
STALE = "cloud_state/stale.json"                # committed, so the self-heal job can read it
ROT = "cloud_state/scrape_rot.json"             # written by refresh_scrape_cache.py (scraper lane), read here

# platforms whose zero is never evidence about the board itself
_PSEUDO_OR_BY_DESIGN = ("scrape", "discovery")

# a rot entry is last night's verdict: committed 00:00 UTC, read at 05:00. Older than this
# and the refresh did not run (or a mass-failure night wrote nothing) — fall back to the
# baseline rule rather than trust a verdict about a page nobody looked at since.
_ROT_FRESH_DAYS = 2

_MAIL_MAX_NAMES = 6


def _load(path):
    """A state file, or {} — for a missing file, unreadable JSON, or valid JSON that is not
    an object (a `[...]`/`null` rot file must not crash the digest that `record` promises
    never to break)."""
    if os.path.exists(path):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return d if isinstance(d, dict) else {}
    return {}


def israel_scoped(platform):
    """The fetcher for this platform narrows to Israel itself (`fetch_x.israel_scoped`),
    so neither its zero nor its baseline says anything about the board. Read off the
    fetcher, so a new scoped fetcher cannot be forgotten here."""
    from .fetchers import FETCHERS   # lazy: health is imported inside the run, never by fetchers
    return bool(getattr(FETCHERS.get((platform or "").strip().lower()), "israel_scoped", False))


def zero_is_a_measurement(platform):
    """True when an empty fetch from this platform is not evidence of a broken board: an
    `israel_scoped` fetcher or a pseudo-platform (a scrape row's emptiness is
    refresh_scrape_cache's business)."""
    plat = (platform or "").strip().lower()
    return plat in _PSEUDO_OR_BY_DESIGN or israel_scoped(plat)


def overnight_verdict(entry, today=None):
    """What last night's scraper recorded about a scrape row whose cache is empty this
    morning — one `cloud_state/scrape_rot.json` entry ({why, n, last, error, found, http}).

        ("error", "scrape: http:403 (1 night)")             the page could not be read
        ("measurement", "scrape: 8 roles, none in Israel")  roles found, none in Israel
        None                                                 no entry, an entry older than
                                                             _ROT_FRESH_DAYS, a malformed one,
                                                             or an honestly empty page (found 0)

    Pure: the file IO is `record`'s and `mail_lines`'. `today` is a parameter so a replay of
    committed files is date-independent."""
    if not isinstance(entry, dict):
        return None
    try:
        last = _dt.date.fromisoformat(str(entry.get("last") or ""))
    except ValueError:
        return None
    today = today or _dt.date.today()
    if not (0 <= (today - last).days <= _ROT_FRESH_DAYS):
        return None
    why = entry.get("why")
    if why == "error":
        try:
            n = int(entry.get("n") or 1)
        except (TypeError, ValueError):
            n = 1
        return ("error", f"scrape: {entry.get('error') or 'error'} ({n} night{'s' if n != 1 else ''})")
    if why == "empty":
        try:
            found = int(entry.get("found") or 0)
        except (TypeError, ValueError):
            found = 0
        if found > 0:
            return ("measurement", f"scrape: {found} roles, none in Israel")
    return None


def stale_reason(platform, api_url, n, status, baseline_best, overnight=None):
    """`overnight` is `overnight_verdict(...)[0]` for a scrape row with an empty cache
    (None for everything else). It only ever REPLACES a `regressed-to-zero`: an overnight
    error names the failure, an overnight measurement withdraws the flag. A row that never
    produced (baseline 0) gets no flag from it — the scraper's own rot parking owns that
    row after 7 error nights, and 18 such rows on 2026-08-26 would otherwise have entered
    the weekly self-heal and the targeted LinkedIn rotation for nothing."""
    plat = (platform or "").strip().lower()
    if plat == "scrape" and ATS_HOST.search(api_url or ""):
        return "misconfig-scrape-on-ats"
    if status == "error":
        return "fetch-error"
    # An Israel-scoped fetcher answers "is the board dead?" itself (`BoardEmpty`), and its
    # baseline is a search-hit count, so "had 1, now 0" is noise for it — and ONLY for it:
    # a scrape row that had postings and now has none stays `regressed-to-zero` (the
    # self-heal and the targeted discovery sweep both read that; 25 rows on 2026-08-24).
    if status == "empty" and baseline_best > 0 and not israel_scoped(plat):
        if plat == "scrape" and overnight == "error":
            return "fetch-error"
        if plat == "scrape" and overnight == "measurement":
            return None
        return "regressed-to-zero"
    if n == 0 and not zero_is_a_measurement(plat):
        return "empty-board"
    return None


def record(results, baseline_path=BASELINE, stale_path=STALE, rot_path=ROT, *, write=True,
           today=None):
    """results: {company: {'platform','api','n','status'[,'error']}}. Update baseline + write
    stale list. Returns the stale dict. Never raises on IO — health must never break the
    digest. `write=False` judges against the committed baseline without touching either
    file — a scoped run (--only/--limit) must not replace stale.json with its handful of
    outcomes, but its audit line should still say what it saw. `rot_path` is consulted only
    for scrape rows whose cache is empty (`overnight_verdict`); both files are written
    atomically (a kill mid-write used to leave a truncated baseline, which `_load` read as
    `{}` — every high-water mark reset to 0 and `regressed-to-zero` could never fire again).
    `today` pins the rot freshness clock so a replay of committed files is date-independent."""
    baseline = _load(baseline_path)
    rot = _load(rot_path) if any(
        (r.get("platform") or "").strip().lower() == "scrape" and r.get("status") == "empty"
        for r in results.values()) else {}
    stale = {}
    for name, r in results.items():
        n = int(r.get("n", 0))
        best = max(int(baseline.get(name, 0)), n)
        baseline[name] = best
        plat = (r.get("platform") or "").strip()
        verdict = (overnight_verdict(rot.get(name), today)
                   if plat.lower() == "scrape" and r.get("status") == "empty" else None)
        reason = stale_reason(plat, r.get("api", ""), n, r.get("status", "ok"), best,
                              overnight=verdict[0] if verdict else None)
        if reason:
            stale[name] = {"careers_url": r.get("api", ""), "platform": plat, "reason": reason}
            error = r.get("error") or (verdict[1] if verdict and reason == "fetch-error" else "")
            if error:
                stale[name]["error"] = str(error)[:120]
    if not write:
        return stale
    try:
        for path, data in ((baseline_path, baseline), (stale_path, stale)):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            write_json(path, data)
    except OSError:
        pass
    return stale


def _names(items, with_reason=False):
    shown = items[:_MAIL_MAX_NAMES]
    txt = "; ".join((f"{n}: {e}" if with_reason and e else n) for n, e in shown)
    if len(items) > _MAIL_MAX_NAMES:
        txt += f"; +{len(items) - _MAIL_MAX_NAMES} more"
    return txt


def mail_lines(stale, previous=None, scanned=None, rot_path=ROT, today=None):
    """Up to two lines for the digest's audit block, from `record()`'s return value:

        changed today: new: Decart: fetch-error · cleared: Guardz
        standing: 3 fetch errors (Decart: HttpError: HTTP 404 …) · 2 regressed to zero (X; Y)
                  · 4 empty (…) · 25 scrape rows on an ATS host

    The delta is its own line because the standing counts read the same every morning and
    a new fetch error inside an unchanging 500-character line is invisible by day three.
    Either line is omitted when it has nothing to say; an empty list means every board was
    healthy and nothing changed, so the mail says nothing rather than "0 problems".
    "cleared" means recovered: only rows this run scanned, never an Israel-scoped fetcher's
    measurement zero (§5a), and never a scrape regression that last night's scraper explained
    as "roles found, none in Israel" (`rot_path`, read only when such a row exists).
    """
    stale = stale or {}
    delta, parts = [], []
    if previous is not None:
        previous = {n: v for n, v in previous.items() if isinstance(v, dict)}
        new = sorted(n for n in stale if n not in previous or previous[n].get("reason") != stale[n].get("reason"))
        # "cleared" must mean the board recovered. Three things that are not that: a row this
        # run did not scan at all (deactivated overnight — it would read as cleared forever),
        # an `empty-board` on a platform whose zero is a measurement (it was never broken;
        # 26 Workday rows left the file the day that rule landed), and a scrape row whose
        # zero the scraper measured (roles found, none in Israel).
        rot = None
        gone = []
        for n, v in previous.items():
            if n in stale or (scanned is not None and n not in scanned):
                continue
            if v.get("reason") in ("empty-board", "regressed-to-zero") and israel_scoped(v.get("platform")):
                continue
            if v.get("reason") == "regressed-to-zero" and (v.get("platform") or "").strip().lower() == "scrape":
                rot = _load(rot_path) if rot is None else rot
                verdict = overnight_verdict(rot.get(n), today)
                if verdict and verdict[0] == "measurement":
                    continue
            gone.append(n)
        gone.sort()
        if new:
            delta.append("new: " + _names([(n, stale[n].get("reason", "")) for n in new], with_reason=True))
        if gone:
            delta.append("cleared: " + _names([(n, "") for n in gone]))
    by = {}
    for name, v in stale.items():
        by.setdefault(v.get("reason", ""), []).append((name, v.get("error", "")))
    if by.get("fetch-error"):
        xs = sorted(by["fetch-error"])
        parts.append(f"{len(xs)} fetch error{'s' if len(xs) != 1 else ''} "
                     f"({_names(xs, with_reason=True)})")
    if by.get("regressed-to-zero"):
        xs = sorted(by["regressed-to-zero"])
        parts.append(f"{len(xs)} regressed to zero ({_names(xs)})")
    if by.get("empty-board"):
        xs = sorted(by["empty-board"])
        parts.append(f"{len(xs)} empty ({_names(xs)})")
    if by.get("misconfig-scrape-on-ats"):
        parts.append(f"{len(by['misconfig-scrape-on-ats'])} scrape rows on an ATS host")
    out = []
    if delta:
        out.append("changed today: " + " · ".join(delta))
    if parts:
        out.append("standing: " + " · ".join(parts))
    return out


def previous(stale_path=STALE):
    """Yesterday's verdicts, for the delta in `mail_lines` — read BEFORE `record` rewrites."""
    p = _load(stale_path)
    return p if isinstance(p, dict) else {}
