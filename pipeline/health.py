"""Shared ATS-health recording.

Turns per-company fetch outcomes into a stale-board list + a persistent baseline. Called
INLINE by the daily run (pipeline.run) so detection is a free byproduct of the fetch that
already happens every morning — a broken board is noticed within a day, not a week. The
standalone weekly sweep (health_check.py) reuses the same logic as a backstop.

Stale reasons, in the order they are decided:
  misconfig-scrape-on-ats — set to `scrape` while the URL is a real ATS host
  abandoned-board         — the board answered, and its NEWEST posting is `STALE_BOARD_DAYS`
                            old or older: an abandoned tenant that keeps answering
                            (`fetchers.BoardAbandoned`, judged here by `abandoned()`; the
                            fetch refuses the postings, so nothing from it can publish)
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

**A board is judged on its own freshness, never a role on its age (2026-08-30).** Seventeen
ACTIVE native rows pointed at tenants that answer HTTP 200 with one to seven postings whose
newest date was one to twelve years old (11 SmartRecruiters, 3 Recruitee, 2 Lever, 1 Comeet
on 2026-08-30; `docs/BACKLOG.md` 406 counted 18 with HiBob, since repaired), and
`TLVTech`'s *Data Analyst*, posted 2024-10-22, was emailed as a new role on 2026-08-28.
Every predicate here saw `n > 0` and called that healthy. The operator rejected a maximum
age on ROLES ("if we saw honeybook still posted then its still relevant even if old" —
HoneyBook's 233-day-old role sits on a board that posts every month), so the verdict is the
BOARD's: `abandoned()` says a board whose newest posting is `STALE_BOARD_DAYS` old is an
abandoned tenant whatever its HTTP status, and `fetchers.fetch_company` RAISES
`BoardAbandoned` on it — the `BoardEmpty` precedent — so the run records it as a failed
fetch with this reason, the mail names it, the self-heal re-resolves it, and no posting from
it reaches the classifier. It is a raise and not a stale reason alone because
`resolve_broken._works` reads a board with postings as a SUCCESSFUL re-resolution: a
reason-only verdict would be laundered back onto the row every morning. The company's
already-matched roles survive `run.py`'s seven-day `fail_grace` (that rule is `run.py`'s), so
the mail says it on day one and the board forgets the roles on day eight — which is also the
window a human has if the verdict is wrong for a whole platform (`MASS_ABANDONED_MIN`).

The judgement is STRICT: every posting must carry a parseable date, and an Israel-scoped
fetch (`israel_scoped`, or a row whose own URL asks the board for a place or a keyword) is
never judged, because its postings are a filtered subset whose dates say nothing about the
board. A false positive here is sticky — a live board refused every morning until a person
acts — while the false negative is the status quo this rule replaces. The date's MEANING is
the platform's: comeet and greenhouse hand back an update stamp (a dead board stops being
updated — safe), smartrecruiters a release date it never bumps, lever a creation date it
never bumps. The one live board among the 17 (Tonkean, lever, two Tel Aviv roles created
2024-02 and still open) is why a creation-dated platform gets a second look before the
raise — `fetchers._hosted_board_alive` — and why bamboohr's and successfactors' tenants,
which fill no date at all (0 dated of 82 and of 28 postings), can never be judged: the
verdict is blind to those three platforms and `platform_check` can only show the declared
one (jobvite), not the ones that go blank at runtime.
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
                      # added 2026-08-26 with `fetch_jobvite`: a scrape row on the Jobvite
                      # board host is now convertible, so flagging it is actionable (the
                      # BACKLOG 78 rule — never flag what no fetcher can take over).
                      # SAP's career-site-builder platform cannot be listed here at all: those
                      # sites live on the tenant's own domain (jobs.sap.com,
                      # careers.stratasys.com), so there is no host to match and
                      # `platform_check` shows that cell MISSING on purpose. (Its name is
                      # spelled around deliberately: that check greps THIS source, so writing
                      # the platform's name in a comment would report a wiring that is not
                      # here -- it did, until this comment was reworded.)
                      r"jobs\.jobvite\.com|"
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

# A board whose newest posting is this old is an abandoned tenant. A plain constant, not an
# environment knob: flipping it for one run would take every abandoned row out of
# `stale.json` and announce them all as `cleared`. Tests pin it with monkeypatch.
# `registry_health.STALE_BOARD_DAYS` is the same number for the same reason.
STALE_BOARD_DAYS = 365

# `fetch_company` judges one row at a time, so CLAUDE.md rule 2 (a mass verdict is a broken
# run) can only be applied where every judged row is visible at once: `mail_lines`, over the
# rows refused TODAY (a standing count would print the line every morning for ever). Two
# floors, because a date field breaks per PLATFORM and smartrecruiters has 20 judgeable rows
# against a fleet of ~450: the whole fleet at MIN / PCT, or one platform at PLATFORM_MIN
# rows and PLATFORM_PCT of that platform's judged rows.
MASS_ABANDONED_MIN = 45
MASS_ABANDONED_PCT = 10
MASS_ABANDONED_PLATFORM_MIN = 5
MASS_ABANDONED_PLATFORM_PCT = 50

# The message `fetchers.BoardAbandoned` carries and `run.py` records as
# `BoardAbandoned: <message>[:70]` — built AND parsed here, so the string is a contract.
_ABANDONED_MSG = "newest posting {newest} ({age} days old), {n} posting{s}"
_ABANDONED_RX = re.compile(r"^BoardAbandoned: newest posting (\d{4}-\d{2}-\d{2}) \((\d+) days old\)")

# A query parameter that asks the board for a place or a keyword: that row's fetch is scoped
# by its URL (`jobs.sap.com/...?q=&locationsearch=Israel`) even when the platform is not.
_SCOPED_PARAM = re.compile(r"(?i)^(?:.*(?:location|country|keyword|searchtext).*|q)$")


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
    # lazy, and it must stay lazy: `fetchers.fetch_company` imports this module (lazily too)
    # for `abandoned()`, so a module-level import in either direction is a cycle
    from .fetchers import FETCHERS
    return bool(getattr(FETCHERS.get((platform or "").strip().lower()), "israel_scoped", False))


def zero_is_a_measurement(platform):
    """True when an empty fetch from this platform is not evidence of a broken board: an
    `israel_scoped` fetcher or a pseudo-platform (a scrape row's emptiness is
    refresh_scrape_cache's business)."""
    plat = (platform or "").strip().lower()
    return plat in _PSEUDO_OR_BY_DESIGN or israel_scoped(plat)


def url_scoped(api_url):
    """Does this row's own address ask the board for a place or a keyword? Then its postings
    are a filtered subset whatever the platform declares, and their dates say nothing about
    the board. Reads parameter NAMES in the query string only: a Comeet `?token=` or a
    Greenhouse `?content=true` is not a scope."""
    query = str(api_url or "").partition("?")[2]
    return any(_SCOPED_PARAM.match(part.partition("=")[0].strip())
               for part in re.split(r"[&;]", query) if part.strip())


def board_freshness(jobs):
    """(newest date or None, dated, undated) over a fetcher's postings. A `posted_date` that
    is empty or not a `YYYY-MM-DD` prefix (`fetchers._iso_date` may hand back raw text) is
    UNDATED — counted, never skipped, because `abandoned()` is strict about it."""
    dated, undated = [], 0
    for j in jobs or ():
        d = str((j or {}).get("posted_date") or "").strip()[:10] if isinstance(j, dict) else ""
        # the shape first: `date.fromisoformat` also accepts `20240101`, and an epoch or a
        # job id that happens to be eight digits must not become a date
        try:
            ok = len(d) == 10 and d[4] == "-" and d[7] == "-"
            dated.append(_dt.date.fromisoformat(d) if ok else None)
        except ValueError:
            dated.append(None)
        if dated[-1] is None:
            dated.pop()
            undated += 1
    return (max(dated) if dated else None), len(dated), undated


def abandoned(platform, api_url, jobs, today=None):
    """The board-freshness verdict: `{"newest", "age_days", "n"}` when this board is an
    abandoned tenant, else None. None — never a verdict — when:

      * the platform's zero is a measurement (`israel_scoped`, `scrape`, `discovery`): the
        postings are Israel hits, not the board (a stale Israel role on a live 2,700-posting
        Workday tenant would otherwise condemn the tenant), or a scrape row, whose dates are
        the scraper's to judge (4.8 % of cached postings carry one);
      * the row's own URL scopes the fetch (`url_scoped`);
      * there are no postings (that is `empty-board`'s question);
      * ANY posting is undated — cannot tell. Strict on purpose: a false positive is sticky.

    `today` is injectable so a replay is date-independent; a future-dated posting can never
    be abandoned (negative age)."""
    plat = (platform or "").strip().lower()
    if not jobs or zero_is_a_measurement(plat) or url_scoped(api_url):
        return None
    newest, dated, undated = board_freshness(jobs)     # counts, so a generator is never len()'d
    if newest is None or undated:
        return None
    age = ((today or _dt.date.today()) - newest).days
    if age < STALE_BOARD_DAYS:
        return None
    return {"newest": newest.isoformat(), "age_days": age, "n": dated}


def abandoned_message(verdict):
    """The text `fetchers.BoardAbandoned` carries: `newest posting 2024-10-22 (677 days old),
    1 posting`. Under 70 characters with no `?`, so `run.py`'s cut keeps the date and the age."""
    n = int(verdict.get("n") or 0)
    return _ABANDONED_MSG.format(newest=verdict["newest"], age=verdict["age_days"], n=n,
                                 s="" if n == 1 else "s")


def abandoned_from_error(error):
    """`(newest, age_days)` from a recorded `BoardAbandoned: …` error text, else None."""
    m = _ABANDONED_RX.match(str(error or ""))
    return (m.group(1), int(m.group(2))) if m else None


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


def stale_reason(platform, api_url, n, status, baseline_best, overnight=None, *, error=None):
    """`overnight` is `overnight_verdict(...)[0]` for a scrape row with an empty cache
    (None for everything else). It only ever REPLACES a `regressed-to-zero`: an overnight
    error names the failure, an overnight measurement withdraws the flag. A row that never
    produced (baseline 0) gets no flag from it — the scraper's own rot parking owns that
    row after 7 error nights, and 18 such rows on 2026-08-26 would otherwise have entered
    the weekly self-heal and the targeted LinkedIn rotation for nothing.

    `error` is the recorded exception text (`Class: message`, as `run.py` and
    `health_check.py` both write it): a `BoardAbandoned:` prefix is the freshness verdict
    the fetch already reached, and it is its own reason — a fetch error is repaired by
    re-resolving the address, an abandoned tenant by finding where the company posts now."""
    plat = (platform or "").strip().lower()
    if plat == "scrape" and ATS_HOST.search(api_url or ""):
        return "misconfig-scrape-on-ats"
    if status == "error" and abandoned_from_error(error):
        return "abandoned-board"
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
                              overnight=verdict[0] if verdict else None, error=r.get("error"))
        if reason:
            stale[name] = {"careers_url": api, "platform": plat, "reason": reason}
            error = r.get("error") or (verdict[1] if verdict and reason == "fetch-error" else "")
            if error:
                stale[name]["error"] = str(error)[:120]
            if reason == "abandoned-board":
                # kept on the row so `mail_lines` can tell "the tenant posted again" from
                # "the threshold moved under it" the morning the row leaves this file
                stale[name]["newest"], stale[name]["age_days"] = abandoned_from_error(error)
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
    # last, so the standing line the tests pin for the four above reads the same; the name
    # carries the recorded text (`BoardAbandoned: newest posting 2024-10-22 (677 days old) …`)
    # and the delta is the ONLY line that ever names one (quiet standing), so it gets the
    # fetch-error cap: 15 names on the morning they enter, never `+9 more`. (The names are
    # public either way: `run.py`'s `Failed companies:` line carries every refused row with
    # this same text.)
    ("abandoned-board", "abandoned board{s}", _MAIL_MAX_ERRORS),
)

# reasons the standing line counts without naming: the same names every morning is the
# noise the delta line exists to escape (25 misconfig rows; 15 abandoned tenants)
_QUIET_STANDING = ("misconfig-scrape-on-ats", "abandoned-board")


def _judged_by_platform(scanned):
    """`{platform: rows}` this run's freshness verdict could have judged — rows on a platform
    whose zero is evidence, at an address that does not scope the fetch. The denominators
    of the mass-verdict floors; `{}` for a caller that passed only names."""
    out = {}
    if not hasattr(scanned, "items"):
        return out
    for v in scanned.values():
        if not isinstance(v, dict):
            continue
        plat = (v.get("platform") or "").strip().lower()
        if zero_is_a_measurement(plat) or url_scoped(v.get("api")):
            continue
        out[plat] = out.get(plat, 0) + 1
    return out


def _mass_verdict(new_abandoned, stale, scanned):
    """The rule-2 line, or None. `new_abandoned` are the rows refused as abandoned TODAY."""
    judged = _judged_by_platform(scanned)
    total = sum(judged.values())
    if not total or not new_abandoned:
        return None
    by_plat = {}
    for n in new_abandoned:
        plat = ((stale.get(n) or {}).get("platform") or "").strip().lower()
        by_plat[plat] = by_plat.get(plat, 0) + 1
    fleet = len(new_abandoned) >= max(MASS_ABANDONED_MIN, total * MASS_ABANDONED_PCT // 100)
    plat_hits = sorted((p, k) for p, k in by_plat.items()
                       if judged.get(p) and k >= max(MASS_ABANDONED_PLATFORM_MIN,
                                                     judged[p] * MASS_ABANDONED_PLATFORM_PCT // 100))
    if not fleet and not plat_hits:
        return None
    where = "; ".join(f"{k} of the {judged[p]} {p} rows judged" for p, k in plat_hits) or \
            f"{len(new_abandoned)} of the {total} rows judged"
    return (f"mass verdict: {len(new_abandoned)} board{'s' if len(new_abandoned) != 1 else ''} newly "
            f"refused as abandoned this morning ({where}) — a platform-wide date change reads exactly "
            f"like this; check two by hand before believing {len(new_abandoned)} dead tenants. Their "
            f"roles leave the board in 7 days")


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
        gone, unrefused = [], []
        for n, v in previous.items():
            if n in stale or (scanned is not None and n not in scanned):
                continue
            # An `abandoned-board` row that left is NEVER "cleared": the general rule below
            # cannot see it (an abandoned board returns postings, so `_fetched_none` is
            # False), and the run's outcome cannot tell a tenant that posted again from a
            # date field that went blank — both make `abandoned()` return None. So they are
            # listed under their own word, and several at once are called what they are.
            # The one exception: a recorded age below today's threshold left because the
            # rule moved (a commit), not the board — not announced at all.
            if v.get("reason") == "abandoned-board":
                if _int(v.get("age_days"), STALE_BOARD_DAYS) >= STALE_BOARD_DAYS:
                    unrefused.append(n)
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
        unrefused.sort()
        if new:
            delta.append("new: " + " · ".join(_by_reason({n: stale[n] for n in new})))
        if gone:
            delta.append("cleared: " + _names([(n, "") for n in gone]))
        if unrefused:
            delta.append("no longer refused as abandoned: " + _names([(n, "") for n in unrefused], _MAIL_MAX_ERRORS)
                         + (f" ({len(unrefused)} at once — a tenant posts again one at a time; a "
                            f"fetcher's dates going blank reads the same)" if len(unrefused) >= 3 else ""))
        # CLAUDE.md rule 2, applied at the only point that sees every judged row: a morning
        # on which a platform's dates read as years old is a date-field change, not N dead
        # tenants. The fetch has already refused them (it cannot be un-raised from here);
        # `run.py`'s seven-day `fail_grace` is the window this line has to reach a person.
        mass = _mass_verdict([n for n in new if stale[n].get("reason") == "abandoned-board"], stale, scanned)
    else:
        mass = None
    # the standing line names the misconfig rows by count only: 25 of them, the same 25 every
    # morning, is exactly the noise the delta line exists to escape
    parts = _by_reason(stale, quiet=_QUIET_STANDING)
    out = []
    if mass:
        out.append(mass)
    if delta:
        out.append("changed today: " + " · ".join(delta))
    if parts:
        out.append("standing: " + " · ".join(parts))
    return out


def previous(stale_path=STALE):
    """Yesterday's verdicts, for the delta in `mail_lines` — read BEFORE `record` rewrites."""
    p = _load(stale_path)
    return p if isinstance(p, dict) else {}
