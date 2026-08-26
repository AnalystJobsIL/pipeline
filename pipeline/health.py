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

# Fetch errors get their own group and a far larger cap, because the bug this fixes was three
# new ones hidden behind thirty REGRESSIONS, not behind other fetch errors. It is not
# unlimited: each name carries up to 120 characters of exception text, the line is copied
# verbatim into `digests/latest.md`, `docs/index.html` and the GitHub issue the inbox relay
# turns into the email — and an issue body is capped at 65,536 bytes, so an uncapped line on a
# runner-wide network failure (846 rows × ~135 chars ≈ 114 KB) would silence the very mail that
# was supposed to report it. 25 names ≈ 3 KB, and the largest real morning on record is 3.
_MAIL_MAX_ERRORS = 25


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


def _int(value, default):
    """A count field that may be missing, None or a string."""
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _scrape_with_empty_cache(r):
    """The one kind of row the rot file has anything to say about."""
    return (r.get("platform") or "").strip().lower() == "scrape" and r.get("status") == "empty"


def _public(api_url):
    """A row's address with its query string cut — what `stale.json` records as `careers_url`.

    **This is hygiene, not a redaction, and calling it one would be false.** The queue used to
    copy the row's `api_url` verbatim, so the committed file carried 36 query strings, 9 of
    them Comeet `?token=` values — but the same tokens sit in `companies.csv` (128 rows carry
    a `token=`) in the same public repo, and a Comeet read token is public anyway: the widget
    hands it to every visitor. Nothing is hidden by this and nothing needed to be.

    What it does buy is that the field means what it is called. `stale.json` is a queue of
    ADDRESSES to go and look at, its only consumer renders the page
    (`resolve_broken.candidates()` -> `_public_url` -> `_capture`, a browser visit, or the
    unlocker), and no consumer anywhere parses or re-requests the query — verified across
    `resolve_broken`, `resolve_deep`, `discovery_daily._targeted_inputs` and `health_check`.
    An `api_url` with `?details=true` or `?mode=json` on it was an API endpoint pretending to
    be a careers page."""
    return re.sub(r"\?\S*", "", str(api_url or ""))


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
        n = _int(entry.get("n"), 1)
        return ("error", f"scrape: {entry.get('error') or 'error'} ({n} night{'s' if n != 1 else ''})")
    if why == "empty" and _int(entry.get("found"), 0) > 0:
        return ("measurement", f"scrape: {_int(entry.get('found'), 0)} roles, none in Israel")
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
    rot = _load(rot_path) if any(_scrape_with_empty_cache(r) for r in results.values()) else {}
    stale = {}
    for name, r in results.items():
        n = int(r.get("n", 0))
        best = max(int(baseline.get(name, 0)), n)
        baseline[name] = best
        plat = (r.get("platform") or "").strip()
        verdict = overnight_verdict(rot.get(name), today) if _scrape_with_empty_cache(r) else None
        # decide AND store on the same string: `mail_lines` re-tests the stored URL against
        # `ATS_HOST` to tell "the host list shrank" from a real recovery (BACKLOG 214), so a
        # verdict reached on a URL the file does not keep would suppress that row's recovery
        # for ever. Judging on the public form is also the better rule: an ATS host that
        # appears only inside a query string (`?redirect=…jobs.lever.co/x`) is not this row's
        # board. No registry row has one today (0 of 1,245) — this keeps it that way.
        api = _public(r.get("api", ""))
        reason = stale_reason(plat, api, n, r.get("status", "ok"), best,
                              overnight=verdict[0] if verdict else None)
        if reason:
            stale[name] = {"careers_url": api, "platform": plat, "reason": reason}
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


def rebase(names, baseline_path=BASELINE, stale_path=STALE, *, write=False):
    """Lower the all-time-high baseline of `names` to 0 and drop the `regressed-to-zero` rows
    it was holding up — the ONE place in the repo where a baseline decreases, and an
    operator's call, never a run's.

    A cached posting cannot be re-extracted, so when a change in what the scraper can extract
    makes a page yield nothing, no rule can tell a lost role from lost page chrome: on
    2026-08-26 thirty scrape rows regressed at once because `74570c6` stopped emitting cards
    that were a page's own title with the footer's "Israel" as their location — and all 52 of
    those old postings still pass today's `clean_scraped` and `is_israel_job`, so a replay
    cannot separate them either. Twenty-six of the thirty were chrome; four had lost a real
    opening and keep their flag, which is what the flag is for.
    `health_check.py --rebase-scrape <rev>` prints the postings each baseline was built from
    so a person can make that call.

    A name is accepted only when `stale[name]["reason"] == "regressed-to-zero"` and its
    baseline is > 0: a fetch error, a misconfiguration or a row nobody flagged is never
    silently zeroed. Both files are written in one call, each atomically — but
    `atomic.write_json` is atomic per FILE and not across the pair, so a kill between the two
    can leave a lowered baseline beside a stale row that still names it; the next 05:00 run
    rebuilds `stale.json` from scratch and repairs it. What makes the correction safe is NOT
    this ordering: `mail_lines` judges `cleared` on whether the row produced anything this run
    (`_fetched_none`), so a row that leaves the queue without producing is never announced as
    a recovery however it left — including when a merge puts it back and the next run drops it
    again (`docs/BACKLOG.md` 238).

    `write=False` returns the plan and touches nothing.
    Returns {"rebased": {name: old_baseline}, "refused": {name: why}}.
    """
    baseline, stale = _load(baseline_path), _load(stale_path)
    rebased, refused = {}, {}
    for name in dict.fromkeys(names or ()):          # de-duplicated, order kept
        entry = stale.get(name)
        old = _int(baseline.get(name), 0)
        if not isinstance(entry, dict) or entry.get("reason") != "regressed-to-zero":
            refused[name] = f"not flagged regressed-to-zero ({(entry or {}).get('reason') or 'absent'})"
        elif old <= 0:
            refused[name] = "no baseline to lower" if name in baseline else "no baseline"
        else:
            rebased[name] = old
    if write and rebased:
        for name in rebased:
            baseline[name] = 0
            stale.pop(name, None)
        try:
            for path, data in ((baseline_path, baseline), (stale_path, stale)):
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                write_json(path, data)
        except OSError as e:                          # an operator tool may say so out loud
            refused["<write>"] = str(e)
    return {"rebased": rebased, "refused": refused}


def _names(items, cap=_MAIL_MAX_NAMES):
    """`[(name, error)]` -> `A: why; B; +k more`. `cap=None` never truncates."""
    shown = items if cap is None else items[:cap]
    txt = "; ".join(f"{n}: {e}" if e else n for n, e in shown)
    if cap is not None and len(items) > cap:
        txt += f"; +{len(items) - cap} more"
    return txt


# The stale reasons in the order the mail meets them, the noun it uses, and how many names
# it may print. `None` = every name, always: for a fetch error the NAME is the message, and
# on 2026-08-26 two of three new ones (Greeneye Technology `http:404`, Mobileye) sat inside
# `+30 more` behind 30 scrape rows an extractor change had flipped overnight.
_REASONS = (
    ("fetch-error", "fetch error{s}", _MAIL_MAX_ERRORS),
    ("regressed-to-zero", "regressed to zero", _MAIL_MAX_NAMES),
    ("empty-board", "empty", _MAIL_MAX_NAMES),
    ("misconfig-scrape-on-ats", "scrape row{s} on an ATS host", _MAIL_MAX_NAMES),
)


def _fetched_none(scanned, name):
    """Did this run fetch `name` and get nothing? False when the caller passed only names
    (a set), or no entry, or an entry without a usable count — "we cannot tell" must never
    suppress a real recovery.

    Not `_int`: that helper reads `value or default`, so it answers 1 for a real 0, and 0 is
    the whole question here."""
    entry = scanned.get(name) if hasattr(scanned, "get") else None
    if not isinstance(entry, dict) or entry.get("n") is None:
        return False
    try:
        return int(entry["n"]) == 0
    except (TypeError, ValueError):
        return False


def _by_reason(rows, quiet=()):
    """`{name: entry}` -> one `N label (names)` part per reason, in `_REASONS` order. A reason
    in `quiet` prints its count only (25 unchanging misconfig names every morning is the
    noise the delta line exists to escape). A reason the table does not know still gets a
    part under its own name — the delta must never lose a row."""
    by = {}
    for name, v in (rows or {}).items():
        v = v if isinstance(v, dict) else {}
        by.setdefault(v.get("reason") or "", []).append((name, v.get("error") or ""))
    known = {r for r, _, _ in _REASONS}
    table = _REASONS + tuple((r, r or "unclassified", _MAIL_MAX_NAMES)
                             for r in sorted(set(by) - known))
    parts = []
    for reason, label, cap in table:
        xs = sorted(by.get(reason) or [])
        if not xs:
            continue
        label = label.format(s="s" if len(xs) != 1 else "")
        parts.append(f"{len(xs)} {label}" if reason in quiet
                     else f"{len(xs)} {label} ({_names(xs, cap)})")
    return parts


def mail_lines(stale, previous=None, scanned=None, rot_path=ROT, today=None):
    """Up to two lines for the digest's audit block, from `record()`'s return value:

        changed today: new: 1 fetch error (Decart: HttpError: HTTP 404 …) · 2 regressed to
                  zero (X; Y) · cleared: Guardz
        standing: 3 fetch errors (Decart: HttpError: HTTP 404 …) · 2 regressed to zero (X; Y)
                  · 4 empty (…) · 25 scrape rows on an ATS host

    The delta is its own line because the standing counts read the same every morning and
    a new fetch error inside an unchanging 500-character line is invisible by day three.
    **Both lines group by reason through `_by_reason`, in one order, and a fetch error is
    never truncated**: until 2026-08-26 the delta was one alphabetical list cut at six names,
    and on the morning 30 scrape rows regressed at once (an extractor change, not 30 broken
    boards) two of the three NEW fetch errors — Greeneye Technology `http:404` and Mobileye's
    Lever timeout — sat inside `+30 more`.
    Either line is omitted when it has nothing to say; an empty list means every board was
    healthy and nothing changed, so the mail says nothing rather than "0 problems".
    "cleared" means the row left `stale.json`, which is not always a recovery — four things
    it never announces are listed inline below.
    """
    stale = stale or {}
    delta = []
    if previous is not None:
        previous = {n: v for n, v in previous.items() if isinstance(v, dict)}
        stale = {n: v for n, v in stale.items() if isinstance(v, dict)}
        new = sorted(n for n in stale if n not in previous or previous[n].get("reason") != stale[n].get("reason"))
        # "cleared" must mean the board recovered. Four things that are not that: a row this
        # run did not scan at all (deactivated overnight — it would read as cleared forever),
        # a row that left because `ATS_HOST` shrank under it (below), an `empty-board` on a
        # platform whose zero is a measurement (it was never broken; 26 Workday rows left the
        # file the day that rule landed), and a scrape row whose zero the scraper measured
        # (roles found, none in Israel).
        rot = None
        gone = []
        for n, v in previous.items():
            if n in stale or (scanned is not None and n not in scanned):
                continue
            # THE GENERAL RULE, when the caller passed this run's outcomes and not just names
            # (`run.py` and `health_check.py` both pass the results dict): a row flagged for
            # having no postings "recovered" only if it HAS postings now. Anything else that
            # took it out of the file — an operator re-basing a latched baseline (`rebase`),
            # a rule change, a merge that restored a row we had removed — is not a recovery,
            # and this catches all of them without knowing which one happened.
            #
            # **In production this rule fires FIRST and the three below are its fallback** —
            # `run.py` and `health_check.py` both pass the results dict, so the scrape-rot read
            # in particular is now reached only by a caller that passes a bare set of names
            # (the tests do). They are kept because that caller is legitimate and because each
            # one states a rule this file would otherwise only imply; they are not dead, but
            # they are no longer what does the work.
            if v.get("reason") in ("empty-board", "regressed-to-zero") and _fetched_none(scanned, n):
                continue
            # ...and a `misconfig-scrape-on-ats` row that is absent because ATS_HOST itself
            # lost a host. The row was flagged yesterday, so the pattern matched yesterday's
            # URL — and `previous` holds that same URL — so a non-match today can only mean
            # the pattern shrank: a rule change, not a recovery (myInterview on 2026-08-26,
            # when `applytojob.com|jazz.co` left with the `jazzhr` platform, BACKLOG 214).
            # Pure (no fetcher import, no file IO), so it runs before the two that are not.
            if v.get("reason") == "misconfig-scrape-on-ats" and not ATS_HOST.search(v.get("careers_url") or ""):
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
            delta.append("new: " + " · ".join(_by_reason({n: stale[n] for n in new})))
        if gone:
            delta.append("cleared: " + _names([(n, "") for n in gone]))
    # the standing line names the misconfig rows by count only: 25 of them, the same 25 every
    # morning, is exactly the noise the delta line exists to escape
    parts = _by_reason(stale, quiet=("misconfig-scrape-on-ats",))
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
