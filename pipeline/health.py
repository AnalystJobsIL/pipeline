"""Shared ATS-health recording.

Turns per-company fetch outcomes into a stale-board list + a persistent baseline. Called
INLINE by the daily run (pipeline.run) so detection is a free byproduct of the fetch that
already happens every morning — a broken board is noticed within a day, not a week. The
standalone weekly sweep (health_check.py) reuses the same logic as a backstop.

Stale reasons, in the order they are decided:
  misconfig-scrape-on-ats — set to `scrape` while the URL is a real ATS host
  fetch-error             — the fetch raised: the endpoint 404s / 422s / times out, or the
                            fetcher itself said the board is empty worldwide
                            (`fetchers.BoardEmpty`) or mis-pointed (ValueError)
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
`refresh_scrape_cache.py`'s business — and for `jazzhr`, whose fetcher returns [] by
design; a scrape row that had postings and now has none stays `regressed-to-zero` (25 rows
on 2026-08-24), because the self-heal pool and the targeted discovery sweep read that flag.

The mail line (`mail_lines`) is what makes any of this visible: `stale.json` is read by the
self-heal job, not by a person.
"""
from __future__ import annotations

import json
import os
import re

ATS_HOST = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
                      r"comeet\.co|workable\.com|recruitee\.com|myworkdayjobs|"
                      # added 2026-08-22 after pipeline/platform_check.py showed 6 native
                      # platforms missing here — a row misconfigured as `scrape` on one of
                      # these hosts was never flagged misconfig-scrape-on-ats
                      r"breezy\.hr|bamboohr\.com|oraclecloud\.com|applytojob\.com|"
                      r"jazz\.co|amazon\.jobs|careers\.microsoft\.com", re.I)
BASELINE = "cloud_state/health_baseline.json"   # committed, so it persists across cloud runs
STALE = "cloud_state/stale.json"                # committed, so the self-heal job can read it

# platforms whose zero is never evidence about the board itself
_PSEUDO_OR_BY_DESIGN = ("scrape", "discovery", "jazzhr")

_MAIL_MAX_NAMES = 6


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def israel_scoped(platform):
    """The fetcher for this platform narrows to Israel itself (`fetch_x.israel_scoped`),
    so neither its zero nor its baseline says anything about the board. Read off the
    fetcher, so a new scoped fetcher cannot be forgotten here."""
    from .fetchers import FETCHERS   # lazy: health is imported inside the run, never by fetchers
    return bool(getattr(FETCHERS.get((platform or "").strip().lower()), "israel_scoped", False))


def zero_is_a_measurement(platform):
    """True when an empty fetch from this platform is not evidence of a broken board: an
    `israel_scoped` fetcher, a pseudo-platform (a scrape row's emptiness is
    refresh_scrape_cache's business) or a by-design-empty one."""
    plat = (platform or "").strip().lower()
    return plat in _PSEUDO_OR_BY_DESIGN or israel_scoped(plat)


def stale_reason(platform, api_url, n, status, baseline_best):
    plat = (platform or "").strip()
    if plat == "scrape" and ATS_HOST.search(api_url or ""):
        return "misconfig-scrape-on-ats"
    if status == "error":
        return "fetch-error"
    # An Israel-scoped fetcher answers "is the board dead?" itself (`BoardEmpty`), and its
    # baseline is a search-hit count, so "had 1, now 0" is noise for it — and ONLY for it:
    # a scrape row that had postings and now has none stays `regressed-to-zero` (the
    # self-heal and the targeted discovery sweep both read that; 25 rows on 2026-08-24).
    if status == "empty" and baseline_best > 0 and not israel_scoped(plat):
        return "regressed-to-zero"
    if n == 0 and not zero_is_a_measurement(plat):
        return "empty-board"
    return None


def record(results, baseline_path=BASELINE, stale_path=STALE, *, write=True):
    """results: {company: {'platform','api','n','status'[,'error']}}. Update baseline + write
    stale list. Returns the stale dict. Never raises on IO — health must never break the
    digest. `write=False` judges against the committed baseline without touching either
    file — a scoped run (--only/--limit) must not replace stale.json with its handful of
    outcomes, but its audit line should still say what it saw."""
    baseline = _load(baseline_path)
    stale = {}
    for name, r in results.items():
        n = int(r.get("n", 0))
        best = max(int(baseline.get(name, 0)), n)
        baseline[name] = best
        reason = stale_reason(r.get("platform", ""), r.get("api", ""), n,
                              r.get("status", "ok"), best)
        if reason:
            stale[name] = {"careers_url": r.get("api", ""),
                           "platform": (r.get("platform") or "").strip(), "reason": reason}
            if r.get("error"):
                stale[name]["error"] = str(r["error"])[:120]
    if not write:
        return stale
    try:
        for path, data in ((baseline_path, baseline), (stale_path, stale)):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass
    return stale


def _names(items, with_reason=False):
    shown = items[:_MAIL_MAX_NAMES]
    txt = "; ".join((f"{n}: {e}" if with_reason and e else n) for n, e in shown)
    if len(items) > _MAIL_MAX_NAMES:
        txt += f"; +{len(items) - _MAIL_MAX_NAMES} more"
    return txt


def mail_lines(stale, previous=None, scanned=None):
    """Up to two lines for the digest's audit block, from `record()`'s return value:

        changed today: new: Decart: fetch-error · cleared: Guardz
        standing: 3 fetch errors (Decart: HttpError: HTTP 404 …) · 2 regressed to zero (X; Y)
                  · 4 empty (…) · 25 scrape rows on an ATS host

    The delta is its own line because the standing counts read the same every morning and
    a new fetch error inside an unchanging 500-character line is invisible by day three.
    Either line is omitted when it has nothing to say; an empty list means every board was
    healthy and nothing changed, so the mail says nothing rather than "0 problems".
    "cleared" means recovered: only rows this run scanned, never an Israel-scoped fetcher's
    measurement zero (§5a).
    """
    stale = stale or {}
    delta, parts = [], []
    if previous is not None:
        previous = {n: v for n, v in previous.items() if isinstance(v, dict)}
        new = sorted(n for n in stale if n not in previous or previous[n].get("reason") != stale[n].get("reason"))
        # "cleared" must mean the board recovered. Two things that are not that: a row this
        # run did not scan at all (deactivated overnight — it would read as cleared forever),
        # and an `empty-board` on a platform whose zero is a measurement (it was never
        # broken; 26 Workday rows left the file the day that rule landed).
        gone = sorted(n for n, v in previous.items() if n not in stale
                      and (scanned is None or n in scanned)
                      and not (v.get("reason") in ("empty-board", "regressed-to-zero")
                               and israel_scoped(v.get("platform"))))
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
