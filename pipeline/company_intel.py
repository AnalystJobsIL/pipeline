"""The digest hook of the company-intel lane: blurbs + researched facts for one run, and the
one line in the mail's run audit that says what it did (ARCHITECTURE.md §7).

    company_info, firmo_display, report = enrich_for_run(st, board_jobs=..., ...)
    mail_lines, warnings = audit_lines(report)

`enrich_for_run` never raises, spends at most BLURB_MAX_PER_RUN + FIRMO_MAX_PER_RUN `claude`
calls inside FIRMO_TIME_BUDGET_MIN minutes, stops at the first infrastructure failure, and
publishes the union back to the export unless the run is scoped or the export was corrupt.
The record, identity and the export live in `pipeline/firmographics.py`; the blurb prompt in
`pipeline/company_info.py`. Rehearse tomorrow's run without spending anything:
`python tests/rehearse_company_intel.py --case json --hole "X,Y" --only "X,Y,Z"`.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

from . import firmographics as _F
from . import stages as _stages
from .firmographics import (ResearchUnavailable, all_failures, display_index,  # noqa: F401
                            identity_key, load_shared_status, not_a_company, save_shared,
                            sync_store, union_store)


def research_company(*a, **kw):
    """Late-bound so a test can stub `firmographics.research_company` in one place."""
    return _F.research_company(*a, **kw)


def research_company_detail(*a, **kw):
    """Same late binding for the (record, reason) form. The reason is what makes a
    firmo_failed strike explicable: `research_company` collapses three different
    outcomes into None, and the strike is a 7-day gate."""
    return _F.research_company_detail(*a, **kw)


def research_with_evidence(*a, **kw):
    """Same late binding for the evidence-fed form this hook actually calls -- one refusal
    on a name with a live posting buys one more question, asked about the posting."""
    return _F.research_with_evidence(*a, **kw)


# ---- the digest hook: blurbs + facts for one run ----------------------------------- #
# Everything the digest needs from this lane, in one call that never raises, is bounded
# in calls AND minutes, and reports itself (`audit_lines`) into the mail. Env-overridable
# with today's values as defaults; `pipeline/run.py` holds none of these numbers.
# Read at CALL time, not at import. As module constants they froze at first import, so a
# rehearsal that set the env afterwards silently tested the defaults it meant to override.
_DEFAULTS = {"FIRMO_MAX_PER_RUN": 5, "FIRMO_TIME_BUDGET_MIN": 8, "BLURB_MAX_PER_RUN": 30}


def _knob(name, cast=int):
    """Never raises. `_report()` calls this and `_report()` runs OUTSIDE `enrich_for_run`'s
    try, so a bad env value (`FIRMO_TIME_BUDGET_MIN=8m`, or the empty string a GitHub
    `${{ vars.X }}` yields when the variable is unset) took the whole run down at the
    company-intel phase -- after the classifier spend, before rendering. As import-time
    constants the same typo raised before anything was paid for; moving them to call time
    moved the blast radius, so it has to be caught here (wave-1)."""
    try:
        return cast(os.environ.get(name, _DEFAULTS[name]))
    except (TypeError, ValueError):
        return cast(_DEFAULTS[name])


# Kept as module names because tests, mutations and the audit line all read them; the values
# are the defaults, and `_report()` re-reads the env every run.
FIRMO_MAX_PER_RUN = _knob("FIRMO_MAX_PER_RUN")
# 8, not 15. Measured 2026-08-26: the digest ran 05:38:55 -> 06:04:13 (25m18s) and the inbox
# relay polls at 06:17, so there are ~13 minutes of slack before the mail slips a whole hour
# to the 07:17 poll. A 15-minute budget was LARGER than the slack -- safe only because it was
# never spent (this step used 2m22s). The bulk backlog belongs to the 10:00 UTC cron, which
# has its own job and nothing waiting on it.
FIRMO_TIME_BUDGET_MIN = _knob("FIRMO_TIME_BUDGET_MIN", float)
BLURB_MAX_PER_RUN = _knob("BLURB_MAX_PER_RUN")
RESEARCH_TIMEOUT_S = 240
# the floor below which a research call is not worth launching: measured 18-40s per
# call on 2026-08-26, so 120s is ~3x the typical cost and well under the 240s cap.
RESEARCH_MIN_S = 120
_RESEARCH_RESERVE_S = RESEARCH_MIN_S
BLURB_RETRY_DAYS = 30      # a company the blurb model could not identify is asked again monthly
STRIKE_RETRY_DAYS = 7      # a name research failed on is retried weekly
SOFT_OUTAGE_MIN_FAILS = 3  # this many name-failures and no success in one run = not the names
PURGE_MIN, PURGE_SHARE = 3, 0.05   # the purge's ceiling: more than max(3, 5 %) hits is a gate change
# the classifier builds this string at seniority.py:531 as `llm-unavailable(<kind>: ...)`;
# only the kind is load-bearing. Asking `classifier` for a `Classifier.off_kind` would
# retire the regex -- filed, not assumed.
_SHARED_OUTAGE = re.compile(r"llm-unavailable\((auth|missing)\b")


def _report():
    return {"research_off": False, "board_companies": 0, "candidates": 0, "researched": 0,
            "failed": 0, "skipped_budget": 0, "unavailable_after": None,
            "unavailable_reason": "", "unavailable_in": "", "soft_outage": False,
            "blurb_outage": False, "blurbs_stopped": False,
            "blurbs_written": 0, "blurbs_asked": 0, "blurbs_empty": 0, "blurbs_missing": 0,
            "blurbs_skipped_budget": 0, "blurbs_derived": 0, "blurbs_waiting": 0,
            "export_status": "ok",
            "export_records": 0, "export_newest": "", "store_records": 0, "synced": 0,
            "run_date": "",
            "published": False, "publish_error": "", "scoped": False, "error": "", "gated": 0,
            "gated_junk": 0, "blurbs_refused": 0, "blurbs_dropped": 0, "llm": {},
            "unavailable_kind": "",
            "registry_backlog": 0, "llm_off_upstream": "", "failed_reasons": [],
            "cap": _knob("FIRMO_MAX_PER_RUN"), "budget_min": _knob("FIRMO_TIME_BUDGET_MIN", float),
            "blurb_cap": _knob("BLURB_MAX_PER_RUN"),
            # 2026-08-30: the gap with a DIRECTION, and the bulk cron's last stamp
            "stopped_outage": 0, "blurbs_purged": 0,
            # 2026-08-31: one blurb call the MODEL failed, skipped and asked again next run,
            # against the seam being down — which is what it used to be reported as
            "blurbs_transient": 0, "blurbs_transient_reason": "",
            "blurbs_transient_seconds": 0.0,
            "backlog_prev": None, "backlog_prev_date": "", "backlog_delta": None,
            "cron": {}, "direction_unreadable": False}


# ---- the two stamps this lane reads and writes -------------------------------------- #
# `firmo` is written by the 10:00 UTC bulk cron (research_firmographics.py) and READ here;
# `intel` is written here, every unscoped digest, so that tomorrow's digest can say which
# way the gap moved. Both live in cloud_state/pipeline_stages.json, which the digest already
# commits and persist_state merges per key. A `_meta` key in firmographics.json was
# rejected (load_shared_status would flag the file `partial` and every writer would refuse
# it); a new cloud_state file was rejected (it needs a persist_state.STRATEGY entry, which
# is infra's); yesterday's digests/latest.md was rejected (parsing prose is how numbers
# drift). The stamp file is the one place a per-run number already survives its runner.
INTEL_STAGE = "intel"


def _stage_detail(stage):
    """The stamp for `stage` as a dict; {} when the key is absent (a first measurement); None
    when the FILE is unreadable -- never raises. `stages.py` exposes age and alarms but not
    the detail a stamp carries, and this lane needs the numbers. The two empty answers are
    kept apart because they read differently in the mail: an absent key is "first
    measurement", a corrupt file is a direction that cannot be known -- and a corrupt file
    read as "first measurement" every morning would also disarm the one warning (wave-1)."""
    try:
        with open(_stages.PATH, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 — bad JSON, a half-written file, permissions
        return None
    if not isinstance(d, dict):
        return None
    e = d.get(stage)
    return e if isinstance(e, dict) else {}


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _load_profiles(path):
    """`company_profiles.json` — hand-written blurbs that outrank the generated ones. They
    pass the same junk rule as a generated blurb: the file is the one input with no gate,
    and "UNKNOWN" is exactly what a backfill from a failed research pass would carry."""
    from .company_info import _JUNK_OUT
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return {}
    return {k: v for k, v in d.items()
            if isinstance(v, str) and len(v.strip()) >= 15 and not _JUNK_OUT.search(v)}


CHIP_MAX = 48


def chip_safe(rec):
    """The record as the card renders it: `il_center` cut to its first clause and at most
    CHIP_MAX chars. 309 of 940 researched records answer "main Israel site" with a
    paragraph ("Tel Aviv (HQ; registered as Zipher Technologies Ltd, no. 517004768)"), and a
    chip is `white-space: nowrap`. The stored record keeps the full text."""
    if not isinstance(rec, dict):
        return rec
    site = " ".join(str(rec.get("il_center") or "").split())
    if len(site) <= CHIP_MAX:
        return rec
    short = site.split(";")[0].strip()
    if len(short) > CHIP_MAX:
        short = short[:CHIP_MAX]
        if " " in short:
            short = short[:short.rfind(" ")]
    # never leave a parenthesis open: drop the dangling "(" clause instead
    while short.count("(") > short.count(")"):
        short = short[:short.rfind("(")]
    short = short.strip(" ,;(-\u2014\u2013")
    return {**rec, "il_center": short or site[:CHIP_MAX]}


def _context_for(company, jobs):
    """The blurb loop's context: this company's job text, nothing else. `company_info`
    summarises what a company DOES and never has to identify it -- the name is already
    known to be a board company."""
    return next((j.get("description") for j in jobs
                 if j.get("company") == company and j.get("description")), "")


def _evidence_for(company, jobs):
    """This company's live roles as `firmographics.evidence_context` kwargs.

    The research half needs more than the blurb half does, and for one reason: it has to
    IDENTIFY the employer, and a name it cannot place used to come back `known: false` and
    become a 7-day strike -- with the posting that would have answered it sitting in the
    same dict. Everything here is already in `board_jobs`; no store is read."""
    mine = [j for j in jobs if j.get("company") == company]
    titles, postings, jd = [], [], ""
    for j in mine:
        t = " ".join(str(j.get("title") or "").split())
        if t and t not in titles and len(titles) < 3:
            titles.append(t)
        if j.get("url") and len(postings) < 2:
            postings.append((t, j.get("url")))
        if not jd and j.get("description"):
            jd = j["description"]
    return {"postings": tuple(postings), "jd": jd, "board_titles": titles}


def _research_order(board_jobs, email_jobs):
    """Who gets the budget first: the companies in tomorrow's email (48h + first-scan), then
    the board by live-role count, then alphabetical — the reader opens the mail, not the
    archive."""
    live = {}
    for j in board_jobs:
        live[j["company"]] = live.get(j["company"], 0) + 1
    mailed = {j["company"] for j in email_jobs or ()}
    return sorted(live, key=lambda c: (c not in mailed, -live[c], c.lower()))


class _Clock:
    """One wall clock for the whole hook: blurbs and research share FIRMO_TIME_BUDGET_MIN.
    A research-only budget let 30 blurbs at 90 s each run for 45 minutes before the
    'budget' even started (wave 2)."""

    def __init__(self, budget_min, now=None):
        import time
        self.now = now or time.time
        self.t0 = self.now()
        self.budget_s = budget_min * 60

    def remaining(self):
        return self.budget_s - (self.now() - self.t0)


def _blurbs(st, board_jobs, run_date, use_llm, rep, profiles_path, clock=None, scoped=True):
    from . import company_info as _ci
    cached = st.load_company_info()
    company_info = {**cached, **_load_profiles(profiles_path)}
    # A blurb ALREADY CACHED under a name that is not a company still renders: gating the
    # loop only stops us buying another one. cloud_state/seen.db holds
    # company_info['Tel Aviv'] = "Alma, a Sisram Medical company, ..." (cached 2026-08-25,
    # from a secrettelaviv job's text used as context), and that is the text under
    # `### Tel Aviv` on the board. Dropping it at READ time fixes every machine at once and
    # needs no write to seen.db -- which is SINGLE_WRITER: daily-digest, so committing the
    # laptop's copy would clobber the runner's matched/roles/llm_cache tables.
    poisoned = [c for c in company_info if not_a_company(c)]
    for c in poisoned:
        company_info.pop(c, None)
    rep["blurbs_dropped"] = len(poisoned)
    if poisoned:
        # ARCHITECTURE section 1a: "every rejection prints the name, so a wrong one can be
        # appealed from the step log". A count alone makes a false positive unrecoverable --
        # section 8's first failure class, a row quietly leaving a pool on a green run.
        print(f"  [company-intel] blurb dropped, not a company: "
              f"{_ascii(', '.join(sorted(poisoned)), 200)}",
              file=sys.stderr, flush=True)
    # ...and PURGED, once, where the writer is. The read-time drop printed `Tel Aviv` on
    # every digest from 2026-08-25 to 2026-08-30 (a line a reader learns to skim, section
    # 8), because nothing was allowed to delete the row. This hook runs INSIDE daily-digest,
    # which IS seen.db's single writer -- the blurb-outage rollback below already deletes
    # from this table. Only rows the STORE holds (company_profiles.json is not a store and
    # keeps supplying its text either way), and never on a scoped run, which must leave
    # every store alone. CEILING: `not_a_company` is built from two other lanes' lists
    # (`looks_like_junk` is the registry's, `_IL_PLACES` the classifier's), and a widened
    # predicate used to be a read-time drop that reverted with it -- now it is a DELETE
    # of paid text. So the purge refuses a mass hit, like every merge in persist_state
    # refuses a mass key drop, and prints the text it deletes so the step log can restore
    # it (wave-1). One row on 2026-08-30 (`Tel Aviv`, of 121); the ceiling is 3 or 5 %.
    purge = [c for c in poisoned if c in cached]
    if purge and not scoped:
        cap = max(PURGE_MIN, int(PURGE_SHARE * len(cached)))
        if len(purge) > cap or len(purge) >= len(cached):     # never the whole store (wave-2)
            print(f"  [company-intel] blurb purge REFUSED: {len(purge)} of {len(cached)} cached "
                  f"names read as non-companies (ceiling {cap}) -- the gate, not the store, "
                  f"is what changed", file=sys.stderr, flush=True)
        else:
            try:
                for c in sorted(purge):
                    print(f"  [company-intel] blurb purged, not a company: {_ascii(c, 60)} "
                          f"| {_ascii(cached.get(c), 200)}", file=sys.stderr, flush=True)
                st.conn.execute("DELETE FROM company_info WHERE company IN (%s)"
                                % ",".join("?" * len(purge)), purge)
                st.conn.commit()
                rep["blurbs_purged"] = len(purge)
            except Exception as e:  # noqa: BLE001 — a locked store must not cost the digest
                print(f"  [company-intel] blurb purge skipped: {e!r}", file=sys.stderr, flush=True)
    board = {j["company"] for j in board_jobs}
    # one blurb per identity: "Meta" and "Meta Israel" are one company (both had paid)
    by_key = {}
    for c, s in company_info.items():
        if s:
            by_key.setdefault(identity_key(c), s)
    for c in board:
        if not company_info.get(c) and by_key.get(identity_key(c)):
            company_info[c] = by_key[identity_key(c)]
    # THE GATE THAT WAS MISSING. `_research_targets` has always refused a junk name; the
    # blurb loop had no gate at all, so on 2026-08-25 the model was handed the name
    # "Tel Aviv" together with a secrettelaviv job's text as context and profiled a company
    # mentioned INSIDE that context: company_info['Tel Aviv'] came back as Alma/Sisram
    # Medical, was cached, and rendered under `### Tel Aviv` on the board. The research
    # prompt forbids exactly that; the blurb prompt did not. Widening `looks_like_junk`
    # (BACKLOG 11/101) would NOT have prevented it -- this loop never consulted it.
    missing = sorted(c for c in board if not company_info.get(c))
    refused = {c for c in missing if not_a_company(c)}
    rep["blurbs_refused"] = len(refused)
    if refused:
        print(f"  [company-intel] blurb refused, not a company: "
              f"{_ascii(', '.join(sorted(refused)), 200)}",
              file=sys.stderr, flush=True)
    missing = [c for c in missing if c not in refused]
    rep["blurbs_missing"] = len(missing)
    if not use_llm or not missing:
        return company_info, missing
    # '' is a cached answer ("UNKNOWN", junk, a CLI error) — asking again every morning
    # spent a call per run on the same names. Retry monthly, like the employee misses.
    cutoff = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=BLURB_RETRY_DAYS)).isoformat()
    recent = {c for (c,) in st.conn.execute(
        "SELECT company FROM company_info WHERE (summary='' OR summary IS NULL) "
        "AND updated > ?", (cutoff,))}
    todo, batch = [], set()
    for c in missing:
        if c in recent:
            continue
        if identity_key(c) in batch:
            continue
        batch.add(identity_key(c))
        todo.append(c)
    rep["blurbs_waiting"] = len(missing) - len(todo)
    todo = todo[:rep["blurb_cap"]]   # the env-read cap, not the import-time constant
    clock = clock or _Clock(rep["budget_min"])
    # Two counters, because they answer two different questions. `stalls` counts consecutive
    # FAILED CALLS and decides when the seam is down; `empties`/`empty_names` count answers
    # the model DID return and decide when to stop walking the list and what to roll back.
    # An empty answer is a call that SUCCEEDED -- it is evidence about a name, not about the
    # CLI -- and counting it toward the outage latch would re-arm the bug this change
    # removes: `written, empty, empty, transient` is an ordinary morning (2026-08-31 read
    # `14 asked, 11 written, 3 empty`) and it would latch, skip research and print a mail
    # byte-indistinguishable from the broken one (wave 1).
    empties, empty_names, stalls = 0, [], 0
    for i, company in enumerate(todo):
        # RESERVE research's share. Blurbs run first on the same clock, and at 30 board
        # companies x ~15s they can eat 450s of a 480s budget, leaving research 30s and a
        # `0 researched` morning that reads like nothing was wrong (wave-1). The reserve is
        # the research cap's own minimum cost, so the two loops cannot starve each other.
        if clock.remaining() - _RESEARCH_RESERVE_S < 30:
            rep["blurbs_skipped_budget"] = len(todo) - i
            break
        _left = clock.remaining()
        try:
            rep["blurbs_asked"] += 1
            summ = _ci.summarize_company(company, _context_for(company, board_jobs),
                                         meta=rep["llm"],
                                         timeout=int(max(10, min(90, clock.remaining()))))
        except ResearchUnavailable as e:
            rep["blurbs_asked"] -= 1
            # a failed call is spent wall clock that NOTHING counts: `ask` raises before
            # `record_call`, so `seam: N calls, Ns` cannot see it. Skipping instead of
            # breaking made that unbounded -- three clamped-out calls are 270 s of a 480 s
            # budget, after which research reports `4 skipped (budget)`, a sentence that
            # blames work that was never done. Carry the loss into the mail (wave 1).
            # measured on the BUDGET's own clock, which is the quantity that matters here
            rep["blurbs_transient_seconds"] += round(max(0.0, _left - clock.remaining()), 1)
            # the KIND was recorded for the research loop only, so the two consecutive
            # `is_error (api_error_status=None)` mornings (08-28, 08-29) reached the mail
            # with no word on whether the seam thought it was auth, drift or a blip
            kind = getattr(e, "kind", "") or "transient"
            stalls += 1
            # ...and once the kind was IN the report, nothing read it. On 2026-08-31 ONE
            # blurb call came back `error_max_structured_output_retries` -- the model failed
            # to emit `{known, blurb}` for one company -- and this latch reported the whole
            # seam down: the research gate in `_enrich` reads `unavailable_after`, so 6 board
            # companies went unresearched inside a budget that had spent 81s of 480s, and the
            # mail said "claude unavailable" on a morning the same token served 14 blurbs and
            # 192 classifier calls. `auth`/`missing`/`drift` ARE the seam and still latch on
            # the first hit; a `transient` is one call, so skip the name -- nothing is cached,
            # so the next run simply asks again -- and latch only when the seam proves itself
            # down the way the empty-answer rule already defines it: three in a row.
            if kind == "transient" and stalls < SOFT_OUTAGE_MIN_FAILS:
                rep["blurbs_transient"] += 1
                # FIRST-wins: the cause a reader needs is the one that started the trouble,
                # and last-wins printed the newest reason beside a count of all of them
                rep["blurbs_transient_reason"] = rep["blurbs_transient_reason"] or str(e)
                continue
            # the number of calls that CAME BACK before this one, which is what the mail's
            # `after N blurbs calls` says and what `blurbs: N asked` and `seam: N calls`
            # corroborate. `i` is the loop index: identical while every exception broke the
            # loop, and wrong the moment a transient skips a name (wave 1)
            rep["unavailable_after"] = rep["blurbs_asked"]
            rep["unavailable_in"] = "blurbs"
            rep["unavailable_reason"] = str(e)
            rep["unavailable_kind"] = kind
            break
        company_info[company] = summ
        st.save_company_info({company: summ}, run_date)
        if summ:
            rep["blurbs_written"] += 1
            empties, empty_names, stalls = 0, [], 0
            for other in missing:  # the group's other name-forms read the same blurb
                if identity_key(other) == identity_key(company) and not company_info.get(other):
                    company_info[other] = summ
        else:
            rep["blurbs_empty"] += 1
            empties += 1
            empty_names.append(company)
            if empties >= SOFT_OUTAGE_MIN_FAILS:
                # three UNKNOWN/junk answers in a row: the model is not identifying anything
                # this morning — stop walking the list (30 x 90 s). If nothing at all was
                # written it is an outage, and the three '' rows just cached would gate
                # three real companies for a month on the strength of it: take them back.
                rep["blurbs_stopped"] = True
                if not rep["blurbs_written"]:
                    rep["blurb_outage"] = True
                    st.conn.execute(
                        "DELETE FROM company_info WHERE summary='' AND updated=? AND company IN (%s)"
                        % ",".join("?" * len(empty_names)), [run_date, *empty_names])
                    st.conn.commit()
                    for c in empty_names:
                        company_info.pop(c, None)
                break
    return company_info, [c for c in missing if not company_info.get(c)]


def _research_targets(st, board_jobs, email_jobs, firmo, run_date):
    # sqlite UNION the committed ledger. Reading sqlite alone made the two tiers disagree
    # about the same name: the 10:00 cron struck Sivo / ImagineArt / Chalk / Instacart on
    # 2026-08-27 and this hook would re-buy any of them that reached a board the next
    # morning, at up to FIRMO_MAX_PER_RUN calls, because the cron's strikes never landed in
    # a store this side reads (`firmographics.load_failures`).
    failures = all_failures(st, run_date)
    cutoff = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=STRIKE_RETRY_DAYS)).isoformat()
    norms = {identity_key(c) for c in firmo}
    failed_norms = {identity_key(c) for c, (_att, last) in failures.items() if last > cutoff}
    out, batch, gated, gated_junk = [], set(), 0, 0
    for c in _research_order(board_jobs, email_jobs):
        k = identity_key(c)
        if c in firmo or k in norms or k in batch:
            continue  # profiled, or "X Israel" beside "X" in one digest: one slot, one record
        if not_a_company(c):
            gated_junk += 1     # a job title / category word / bare place: never, not weekly
            print(f"  [company-intel] research refused, not a company: {_ascii(c, 60)}",
                  file=sys.stderr, flush=True)
            continue
        if k in failed_norms:
            gated += 1          # research failed on this name: retried weekly
            continue
        batch.add(k)
        out.append(c)
    return out, gated, gated_junk


def _research(st, targets, board_jobs, run_date, rep, clock=None):
    clock = clock or _Clock(rep["budget_min"])
    todo = targets[:rep["cap"]]
    done, failed_names = {}, []
    for i, company in enumerate(todo):
        remaining = clock.remaining()
        if remaining < RESEARCH_MIN_S:
            # 60s was below the real cost of a call (~18-40s measured, 240s worst case), so
            # the loop launched calls it then killed at the clamped timeout -- and
            # `timeout(60s)` arrives as LLMUnavailable, i.e. the mail said
            # `claude unavailable after 0 research calls` when nothing was down and the
            # blurb loop had simply spent the budget (wave-1).
            rep["skipped_budget"] = len(todo) - i
            break
        if not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
            # exit-0 prose, a revoked WebSearch grant: every answer so far failed and none
            # succeeded — evidence about the infrastructure, not about three company names.
            # `stopped_outage`, not `skipped_budget`: the mail read the names this stop
            # left as "skipped (budget 8m spent)" on a morning the budget was untouched,
            # and the key the line was written to read was never written anywhere.
            rep["soft_outage"] = True
            rep["stopped_outage"] = len(todo) - i
            break
        try:
            # The EVIDENCE, not just the job text: a board company always has a live role,
            # so this hook is exactly the caller that must never conclude "cannot identify"
            # (the operator's 2026-08-31 rule). `budget` is the hook's own clock, so the
            # disambiguation call is skipped rather than started-and-clamped -- a clamped
            # call arrives as `ResearchUnavailable` and would read as an outage.
            rec, why = research_with_evidence(
                company, _evidence_for(company, board_jobs),
                timeout=int(min(RESEARCH_TIMEOUT_S, remaining)), meta=rep["llm"],
                budget=clock.remaining)
        except ResearchUnavailable as e:
            if getattr(e, "kind", "") == "transient" and "timeout(" in str(e) \
                    and remaining <= RESEARCH_TIMEOUT_S:
                # our own clamp killed it, not the CLI: that is budget, not an outage
                rep["skipped_budget"] = len(todo) - i
                break
            # infrastructure outage: don't blame the names, don't burn the budget
            rep["unavailable_after"] = i
            rep["unavailable_in"] = "research"
            rep["unavailable_reason"] = str(e)
            rep["unavailable_kind"] = getattr(e, "kind", "")
            break
        if rec:
            st.save_firmographics({company: rec}, run_date)
            done[company] = rec
        else:
            failed_names.append(company)
            # the cause used to exist only in stderr, and the strike is a 7-day gate -- so
            # nobody could tell a hallucinating model from a name that is not a company
            rep["failed_reasons"].append((company, why))
    rep["researched"] = len(done)
    rep["failed"] = len(failed_names)
    if failed_names and not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
        rep["soft_outage"] = True
    else:
        for c in failed_names:
            st.record_firmo_failure(c, run_date)
    return done


def enrich_for_run(st, *, board_jobs, email_jobs=(), all_companies=None, run_date,
                   use_llm=True, scoped=False, profiles_path=None, llm_off_reason=""):
    """Blurbs + firmographics for one digest run -> (company_info, firmo_display, report).

    The never-raises front door: company intel is best-effort by design and must not cost
    the day's email and board (one locked sqlite `save_firmographics` used to). On an
    unexpected exception the reader still gets whatever was assembled, and the audit line
    says `company intel FAILED: ...`."""
    holder = {"company_info": {}, "firmo_display": {}}
    rep = {}
    try:
        rep = _report()
        return _enrich(st, board_jobs=board_jobs, email_jobs=email_jobs,
                       all_companies=all_companies, run_date=run_date, use_llm=use_llm,
                       scoped=scoped, profiles_path=profiles_path, rep=rep, holder=holder,
                       llm_off_reason=llm_off_reason)
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {e}"[:160]
        print(f"  [company-intel] FAILED: {rep['error']}", file=sys.stderr, flush=True)
        return holder["company_info"], holder["firmo_display"], rep


def _enrich(st, *, board_jobs, email_jobs, all_companies, run_date, use_llm, scoped,
            profiles_path, rep, holder, llm_off_reason=""):
    """The work behind `enrich_for_run`; `holder` carries partial results out on failure.

    Never raises. Spends at most BLURB_MAX_PER_RUN + FIRMO_MAX_PER_RUN `claude` calls and
    FIRMO_TIME_BUDGET_MIN minutes on research; stops at the first infrastructure failure.
    Reads sqlite ∪ the shared export, seeds sqlite from the export, and writes the union
    back — except on a scoped run (`--only`/`--limit`), which must leave the committed
    file alone, and except when the export is corrupt or only partly readable — neither may
    be replaced by the smaller sqlite table. `audit_lines(report)` turns the report into the mail."""
    # BACKLOG 120. The classifier reached the same CLI first and its breaker is open; both
    # tiers spend ONE subscription, so an auth/missing failure there is an auth/missing
    # failure here, and rediscovering it costs up to FIRMO_TIME_BUDGET_MIN of the morning at
    # 240 s per timing-out call. Only `auth` and `missing` are shared evidence: `transient`
    # (a 529, one hung call) says nothing about a different process, and `drift` is about the
    # classifier's own flags.
    if use_llm and _SHARED_OUTAGE.search(llm_off_reason or ""):
        use_llm = False
        rep["llm_off_upstream"] = _ascii(llm_off_reason, 80)
    rep["research_off"] = not use_llm and not rep["llm_off_upstream"]
    rep["scoped"] = bool(scoped)
    rep["run_date"] = str(run_date or "")
    shared, rep["export_status"] = load_shared_status()
    rep["export_records"] = len(shared)
    rep["export_newest"] = max((str(r.get("as_of") or "") for r in shared.values()), default="")
    clock = _Clock(rep["budget_min"])
    if not scoped:  # a scoped local run is produce-only: it writes neither store
        try:
            rep["synced"] = sync_store(st, run_date, shared)
        except Exception as e:  # noqa: BLE001 — a locked sqlite must not cost the digest
            print(f"  [company-intel] store sync skipped: {e!r}", file=sys.stderr, flush=True)
    firmo = union_store(st, shared)
    rep["store_records"] = len(firmo)
    board = {j["company"] for j in board_jobs}
    rep["board_companies"] = len(board)

    company_info, still_missing = _blurbs(st, board_jobs, run_date, use_llm, rep, profiles_path,
                                          clock, scoped=scoped)
    holder["company_info"] = company_info

    targets, rep["gated"], rep["gated_junk"] = _research_targets(
        st, board_jobs, email_jobs, firmo, run_date)
    rep["candidates"] = len(targets)
    if use_llm and targets and rep["unavailable_after"] is None and not rep["blurb_outage"]:
        firmo.update(_research(st, targets, board_jobs, run_date, rep, clock))
    # else: the CLI is down or not answering — the outage sentence carries the count

    # every company we have ever matched renders a card (board, email, archive), looked up
    # under the normalized identity so "SolarEdge Technologies" finds the stored "SolarEdge"
    by_key = display_index(firmo)
    wanted = set(all_companies or ()) | board
    firmo_display = {c: (firmo.get(c) or by_key.get(identity_key(c))) for c in wanted}
    # The RECORD may already exist for a name that is not a company -- the bulk researcher
    # reads `SELECT DISTINCT company FROM matched`, which is the table that held `Tel Aviv`.
    # Refusing the blurb is not enough if the facts chips still render under that heading.
    firmo_display = {k: chip_safe(v) for k, v in firmo_display.items()
                     if v and not not_a_company(k)}
    holder["firmo_display"] = firmo_display

    # a company with facts but no blurb reads its facts as prose — no call, not cached
    from . import company_info as _ci
    for c in still_missing:
        text = _ci.derive_blurb(c, firmo_display.get(c))
        if text:
            company_info[c] = text
            rep["blurbs_derived"] += 1

    # How many ACTIVE registry rows would render with no facts at all, counted through
    # identity_key -- the name-match version reports false gaps the index already answers
    # (20 against 4 on 2026-08-28; it was 39 against 29 when this was written),
    # because display_index already answers for "Dell" from "Dell Technologies". This is the
    # number that makes "is every company we know about researched?" answerable each morning
    # instead of re-derived by hand.
    try:
        from .companies import load_companies
        # EVERYTHING THAT CAN RENDER, not just the active registry. A company reaches a card
        # by having a ROLE, and 28 companies with role records are not active registry rows
        # (a parked employer whose roles are still inside the board window, a discovery-only
        # name) -- `Peak Innovation` is one, and the first version of this gauge could not
        # see it. `all_companies` is every company ever matched, which is the render set.
        # The `discovery` pseudo-row is excluded by platform: it is the LinkedIn+Indeed
        # layer, not an employer, and it would otherwise be a permanent backlog of 1 and a
        # research call every week forever.
        rows = load_companies(active_only=True)
        universe = {r["company_name"] for r in rows
                    if str(r.get("ats_platform") or "").strip().lower() != "discovery"}
        universe |= set(all_companies or ()) | board
        rep["registry_backlog"] = sum(
            1 for n in universe
            if not not_a_company(n) and not (firmo.get(n) or by_key.get(identity_key(n))))
    except Exception as e:  # noqa: BLE001 — a gauge must never cost the mail
        rep["registry_backlog"] = -1
        print(f"  [company-intel] registry backlog not counted: {e!r}", file=sys.stderr, flush=True)

    if not scoped and rep["export_status"] not in ("corrupt", "partial"):
        try:
            rep["published"] = save_shared(firmo)
        except Exception as e:  # noqa: BLE001
            rep["publish_error"] = f"{type(e).__name__}: {e}"[:120]
            print(f"  [company-intel] shared export NOT written: {e}", file=sys.stderr, flush=True)
    # The line must describe the file a reader can open NOW, not the one we opened at 05:00.
    # Captured at the top, it reported `export 942 records, newest 2026-08-25` on a morning
    # that went on to write 946 with four records dated 2026-08-26 -- the confidently-stale
    # statement this repo punishes hardest. `synced` keeps its read-time meaning.
    if rep["published"]:
        rep["export_records"] = len(firmo)
        rep["export_newest"] = max((str(r.get("as_of") or "") for r in firmo.values()), default="")
    _direction(rep, scoped)     # last: a stamp that cannot be written must cost nothing above
    return company_info, firmo_display, rep


def _direction(rep, scoped):
    """The gap's DIRECTION, and the bulk cron's last word -- both from the stamp file.

    "84" is a level; "84, +28 since yesterday" is the line that would have caught the
    2026-08-30 morning a week earlier. The registry (`--census`) and jd-text both stamp a
    direction; this lane printed a level. Yesterday's value is this lane's own `intel`
    stamp, written at the end of every unscoped digest, so the comparison is against the
    last DIGEST that counted -- which is what "since yesterday" means to a reader of the
    mail, and survives a morning with no digest (the delta then spans two days and says
    so by its date).

    The `firmo` stamp is read here for its NUMBERS (`todo`/`attempted`/`left`, since
    2026-08-30); its AGE is judged by `stages.alarms("firmo", 2)` in run.py and is not
    re-judged here. Never raises: a gauge must never cost the mail."""
    try:
        prev = _stage_detail(INTEL_STAGE)
        if prev is None:
            # a corrupt stamp file: say so, and write NOTHING over it -- `stages.stamp`
            # rebases on `{}` when it cannot read the file, and a digest writing daily
            # would turn one truncated write into "collect never ran" about every stage
            rep["direction_unreadable"] = True
            return
        cur = rep.get("registry_backlog")
        today = _dt.date.today().isoformat()      # the stamp's own calendar (stages.py)
        if isinstance(cur, int) and cur >= 0:
            p = _int(prev.get("backlog"))
            if p is not None:
                rep["backlog_prev"] = p
                rep["backlog_prev_date"] = str(prev.get("date") or "")
                rep["backlog_delta"] = cur - p
            # The day's FIRST measurement is the baseline; a second digest the same day
            # (08-28 ran at 07:08 and 17:40 with the 10:00 cron between them) must not
            # re-base it, or the next morning reports +27 for a day that moved -11 and
            # arms the warning on a drain (wave-1). The delta still reads `prev`, so the
            # second run reports the whole day's move against the morning.
            if not scoped and str(prev.get("date") or "") != today:
                _stages.stamp(INTEL_STAGE, backlog=cur, board=rep.get("board_companies", 0),
                              researched=rep.get("researched", 0),
                              blurbs=rep.get("blurbs_written", 0))
        f = _stage_detail("firmo") or {}
        if f:
            rep["cron"] = {"age": _stages.age_days("firmo"), "date": str(f.get("date") or ""),
                           "todo": _int(f.get("todo")), "attempted": _int(f.get("attempted")),
                           "left": _int(f.get("left")), "researched": _int(f.get("researched"), 0),
                           "failed": _int(f.get("failed"), 0), "alarm": str(f.get("alarm") or "")}
    except Exception as e:  # noqa: BLE001
        print(f"  [company-intel] gap direction not stamped: {e!r}", file=sys.stderr, flush=True)
        # `stages.stamp` writes PATH + ".tmp" then `os.replace`s it; a replace that fails
        # (Windows, while a reader holds the file) leaves the .tmp in a TRACKED directory
        try:
            if os.path.exists(_stages.PATH + ".tmp"):
                os.remove(_stages.PATH + ".tmp")
        except OSError:
            pass


def _ascii(s, n=80):
    """CLI stderr and exception text carry box-drawing glyphs and Hebrew names; the line
    they land in is printed to a console that may be cp1252 (the laptop's `run_daily.ps1`
    pipe), and `pipeline/run.py` does not reconfigure stdout — so the never-raises guard
    would be undone by the act of reporting. Fold to ASCII before it leaves the report."""
    return " ".join(str(s or "").split()).encode("ascii", "replace").decode()[:n]


def audit_lines(rep):
    """(mail lines, ::warning:: lines) from `enrich_for_run`'s report. Pure; no I/O.

    One line a reader can reconcile: researched + failed + skipped + waiting = candidates.

    This is called from run.py OUTSIDE `enrich_for_run`'s never-raises guard, so a raise here
    kills the run after classification and before rendering. Every key is read with `.get`,
    and the whole body is belt-and-braces: reporting the run must never be what ends it."""
    try:
        return _audit_lines(rep)
    except Exception as e:  # noqa: BLE001
        msg = f"company intel audit unavailable ({_ascii(f'{type(e).__name__}: {e}')})"
        return [msg], [msg]


def _audit_lines(rep):
    parts, warn = [], []
    n, c = rep["board_companies"], rep["candidates"]
    if rep.get("error"):
        msg = f"company intel FAILED ({_ascii(rep['error'], 160)}) — cards render from whatever was assembled"
        parts.append(msg)
        warn.append(msg)
    # One counter used to call every gated name "research failed, weekly retry" -- false for
    # a job title or a bare place, which are never retried at all.
    _g = ([f"{rep['gated']} more: research failed, weekly retry"] if rep.get("gated") else []) + \
         ([f"{rep['gated_junk']} more: not a company"] if rep.get("gated_junk") else [])
    gated = f" ({' + '.join(_g)})" if _g else ""
    if rep["research_off"]:
        parts.append((f"research off (--no-llm); {c} of {n} board companies unprofiled"
                      if c else f"research off (--no-llm); all {n} board companies profiled") + gated)
    elif c == 0:
        parts.append(f"all {n} board companies profiled" + gated)
    else:
        bits = [f"{rep['researched']} researched", f"{rep['failed']} failed"]
        if rep.get("stopped_outage"):
            bits.append(f"{rep['stopped_outage']} not attempted (stopped)")
        if rep["skipped_budget"]:
            bits.append(f"{rep['skipped_budget']} skipped (budget {rep['budget_min']:g}m spent)")
        waiting = (c - rep["researched"] - rep["failed"] - rep["skipped_budget"]
                   - rep.get("stopped_outage", 0))
        if rep["unavailable_after"] is None and waiting > 0:
            over = " over the cap" if waiting > rep["cap"] else ""
            bits.append(f"{waiting}{over} wait for the next run")
        parts.append(f"{c} of {n} board companies unprofiled (cap {rep['cap']}/run, "
                     f"budget {rep['budget_min']:g}m): " + ", ".join(bits) + gated)
    if rep["soft_outage"]:
        msg = ("research soft outage suspected: every answer failed and none succeeded — "
               "stopped, no strikes recorded")
        parts.append(msg)
        warn.append(msg)
    if rep.get("blurb_outage"):
        msg = ("blurb soft outage suspected: three empty answers and none written — stopped, "
               "nothing cached, research skipped")
        parts.append(msg)
        warn.append(msg)
    if rep["unavailable_after"] is not None:
        k = rep["unavailable_after"]
        loop = rep.get("unavailable_in") or "research"
        left = c - rep["researched"] - rep["failed"]
        kind = rep.get("unavailable_kind") or ""
        msg = (f"claude unavailable after {k} {loop} call{'' if k == 1 else 's'} "
               f"({kind + ': ' if kind else ''}{_ascii(rep['unavailable_reason'])}) — {left} unprofiled board "
               f"compan{'y waits' if left == 1 else 'ies wait'} for the next run")
        parts.append(msg)
        warn.append(msg)
    elif rep["failed"] and not rep["researched"] and not rep["soft_outage"]:
        warn.append(f"every research answer failed ({rep['failed']} of {rep['failed']}) — "
                    f"below the {SOFT_OUTAGE_MIN_FAILS}-fail outage rule, so the names were struck")
    b = [f"{rep['blurbs_asked']} asked", f"{rep['blurbs_written']} written"]
    if rep["blurbs_empty"]:
        b.append(f"{rep['blurbs_empty']} empty" + (" — stopped" if rep.get("blurbs_stopped") else ""))
    if rep["blurbs_skipped_budget"]:
        b.append(f"{rep['blurbs_skipped_budget']} skipped (budget)")
    if rep.get("blurbs_transient"):
        # NOT "empty": the model never answered. Named so the mail can tell a company we
        # could not summarise from a call that failed to come back at all (2026-08-31)
        b.append(f"{rep['blurbs_transient']} transient, retried next run"
                 + (f" [{rep['blurbs_transient_seconds']:g}s of budget]"
                    if rep.get("blurbs_transient_seconds") else "")
                 + (f" ({_ascii(rep.get('blurbs_transient_reason') or '', 60)})"
                    if rep.get("blurbs_transient_reason") else ""))
    if rep["blurbs_derived"]:
        b.append(f"{rep['blurbs_derived']} derived from facts")
    if rep["blurbs_waiting"]:
        b.append(f"{rep['blurbs_waiting']} waiting (monthly retry / same company)")
    if rep.get("blurbs_dropped"):
        b.append(f"{rep['blurbs_dropped']} cached under a non-company name, dropped")
    if rep.get("blurbs_refused"):
        b.append(f"{rep['blurbs_refused']} refused (not a company)")
    if rep.get("blurbs_purged"):
        b.append(f"{rep['blurbs_purged']} purged from the store (not a company)")
    parts.append("blurbs: " + ", ".join(b))
    llm = rep.get("llm") or {}
    if llm.get("calls"):
        served = ", ".join(f"{m.replace('claude-', '')}{'' if n == 1 else f' x{n}'}"
                           for m, n in sorted(llm.get("models", {}).items(), key=lambda kv: -kv[1]))
        bits = [f"{llm['calls']} calls", f"{llm.get('seconds', 0):.0f}s",
                f"{llm.get('searches', 0)} searches"]
        if llm.get("searchless"):
            bits.append(f"{llm['searchless']} SEARCHLESS")
        parts.append("seam: " + (served + " · " if served else "") + ", ".join(bits))
        # a research call that never searched is a parametric guess cached until 2027-02
        if llm.get("searchless"):
            warn.append(f"{llm['searchless']} research answer(s) made no web search — those "
                        f"records are parametric guesses, not researched facts")
        asked = {a for a in (llm.get("asked") or set())}
        drift = [m for m in llm.get("models", {}) if asked and not any(
            str(a).lower() in str(m).lower() for a in asked)]
        if drift:
            warn.append(f"model drift: asked {sorted(asked)}, served {_ascii(str(drift))}")
    if rep.get("llm_off_upstream"):
        msg = (f"research and blurbs skipped: the classifier's breaker was already open "
               f"({_ascii(rep['llm_off_upstream'], 80)})")
        parts.append(msg)
        warn.append(msg)
    if rep.get("failed_reasons"):
        # the NAME too: companies.csv has an active row whose name is Hebrew, and
        # run.py prints this line on a console that may be cp1252 -- outside the
        # never-raises guard, so reporting the failure would BE the failure
        why = "; ".join(f"{_ascii(c, 40)}: {_ascii(r, 60)}"
                        for c, r in rep.get("failed_reasons") or [])
        parts.append(f"why failed: {why}")
    if rep["export_status"] == "ok":
        e = f"export {rep['export_records']} records, newest {rep['export_newest'] or '?'}"
        if rep["synced"]:
            e += f", {rep['synced']} newer than the store"
        _rb = rep.get("registry_backlog", 0)
        e += (f", registry backlog {_rb}" if isinstance(_rb, int) and _rb >= 0
              else ", registry backlog not counted")
        # THE DIRECTION. A level is not a measurement: 74 -> 139 (08-28) and 25 -> 84
        # (08-30) each read as a single plausible number on the morning they happened.
        delta = rep.get("backlog_delta")
        if isinstance(_rb, int) and _rb >= 0:
            if isinstance(delta, int):
                e += f" ({delta:+d} since {rep.get('backlog_prev_date') or '?'})"
            elif rep.get("direction_unreadable"):
                e += " (direction unknown: the stage stamp file is unreadable)"
            else:
                e += " (first measurement)"
        parts.append(e)
        # NOT "backlog > 0 and researched == 0": the digest researches BOARD companies, and
        # the registry backlog is drained by the 10:00 UTC cron, so that fired on every
        # healthy morning — and a warning that is always on is a warning nobody reads.
        # ...and not when the names FAILED or the budget ran out: each already has its
        # own warning, and two warnings for one condition is how a reader learns to skim.
        if (rep["candidates"] and not rep["researched"] and not rep["failed"]
                and not rep["research_off"] and not rep["skipped_budget"]
                and rep["unavailable_after"] is None and not rep["soft_outage"]):
            warn.append(f"{rep['candidates']} board companies needed facts and this run "
                        f"attempted none, with no outage or budget reported")
        # An `export_newest`-based stall alarm lived here for one hour and was WRONG.
        # It is blind to the failure it was written for: the digest hook researches board
        # companies too and `_coerce` stamps them with today's date, so this field moves on
        # most mornings whether or not the 10:00 bulk cron ever fired. Measured -- on
        # 2026-08-28, the day that cron did not run, the 08:54 digest added two records
        # dated 08-28 and carried `export_newest` 08-27 -> 08-28. The alarm would have been
        # silent on the exact morning it was built for.
        #
        # "Did the cron run" is a question about the CRON, so it is measured where every
        # other missing-stage question in this repo is: `stages.stamp("firmo", ...)` in
        # `research_firmographics`, read back by `stages.alarms("firmo", 1)` in `run.py`.
        # That also puts it on the mail's `Needs a look` block rather than the run page
        # alone -- and a run page here is deleted on purpose (`CLAUDE.local.md` section 3).
        # `export_newest` stays on this line as a FACT, which is all it can honestly be.
        if rep.get("publish_error") or (not rep["published"] and not rep.get("scoped")
                                        and not rep.get("error")):
            msg = "export NOT written" + (f" ({_ascii(rep.get('publish_error'), 120)})"
                                          if rep.get("publish_error") else " (nothing to write)")
            parts.append(msg)
            warn.append(msg)
    else:
        # `partial` renders from sqlite UNION whatever could be read, so "sqlite only" was
        # false and its own number disproved it (1,128 = 1 sqlite record + 1,127 readable
        # export records). And the reassurance -- that the bad file was not overwritten --
        # was withheld from exactly the reader who needs it.
        e = (f"export {rep['export_status'].upper()} at cloud_state/firmographics.json — cards "
             + (f"render from sqlite only ({rep['store_records']} records)"
                if rep["export_status"] != "partial" else
                f"render from sqlite ∪ what could be read ({rep['store_records']} records)")
             + ("; file left untouched"
                if rep["export_status"] in ("corrupt", "partial") else ""))
        parts.append(e)
        warn.append(e)
    delta = rep.get("backlog_delta")
    _rb = rep.get("registry_backlog", 0)
    cron = rep.get("cron") or {}
    if cron:
        # the bulk cron's last stamp, as FACTS: its age is `stages.alarms("firmo", 2)`'s
        # to judge, but "61 researched of 67 to do, 6 left" is what tells a drained
        # queue from a cap that let 99 names through untouched (run 33210826528)
        age = cron.get("age")
        when = f"{cron.get('date') or '?'} ({'today' if age == 0 else f'{age}d ago' if isinstance(age, int) else 'age unknown'})"
        bits = [f"{cron.get('researched', 0)} researched"]
        if isinstance(cron.get("todo"), int):
            bits[0] += f" of {cron['todo']} to do"
            if isinstance(cron.get("left"), int):
                bits.append(f"{cron['left']} left")
        if cron.get("failed"):
            bits.append(f"{cron['failed']} failed")
        if cron.get("alarm"):
            bits.append(f"alarm {cron['alarm']}")
        parts.append(f"bulk cron: last ran {when}, " + ", ".join(bits))
    # The one warning this direction earns -- OUTSIDE the `export ok` branch: a corrupt
    # export is a bad morning, and a bad morning is when the cron is likeliest to be dead
    # too; wave 2 found the warning silenced by exactly that. The gap GREW and the only
    # thing that drains it has not run since the day before yesterday. Either half alone is routine --
    # every evening's intake grows the gap before the 10:00 cron sees it, and the cron
    # firing eleven hours late is measured normal (+293..+662 min over its whole life).
    # Not an absolute threshold: "backlog > N" was rejected twice as a warning that is
    # always on.
    # 3, to agree with `stages.alarms("firmo", 2)` on what "two consecutive misses"
    # means: the freshest healthy stamp at 05:00 is yesterday's (age 1), one dropped
    # slot is age 2 and routine, two is age 3. An unknown age (a stamp with no date) is
    # not evidence of anything and warns nothing; the sentence above says "age unknown".
    _age = cron.get("age") if cron else None
    if isinstance(delta, int) and delta > 0 and (not cron or (isinstance(_age, int) and _age >= 3)):
        warn.append(f"registry backlog grew {delta:+d} to {_rb} since "
                    f"{rep.get('backlog_prev_date') or '?'} and the bulk cron "
                    + ("has never run" if not cron else f"last ran {_age}d ago")
                    + " — nothing is draining it")
    return [" · ".join(parts)], warn
