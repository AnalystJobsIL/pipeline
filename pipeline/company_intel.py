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
from .firmographics import (ResearchUnavailable, display_index, identity_key,  # noqa: F401
                            load_shared_status, looks_like_junk, save_shared, sync_store,
                            union_store)


def research_company(*a, **kw):
    """Late-bound so a test can stub `firmographics.research_company` in one place."""
    return _F.research_company(*a, **kw)


# ---- the digest hook: blurbs + facts for one run ----------------------------------- #
# Everything the digest needs from this lane, in one call that never raises, is bounded
# in calls AND minutes, and reports itself (`audit_lines`) into the mail. Env-overridable
# with today's values as defaults; `pipeline/run.py` holds none of these numbers.
FIRMO_MAX_PER_RUN = int(os.environ.get("FIRMO_MAX_PER_RUN", "5"))
FIRMO_TIME_BUDGET_MIN = float(os.environ.get("FIRMO_TIME_BUDGET_MIN", "15"))  # blurbs AND research
BLURB_MAX_PER_RUN = int(os.environ.get("BLURB_MAX_PER_RUN", "30"))
RESEARCH_TIMEOUT_S = 240
BLURB_RETRY_DAYS = 30      # a company the blurb model could not identify is asked again monthly
STRIKE_RETRY_DAYS = 7      # a name research failed on is retried weekly
SOFT_OUTAGE_MIN_FAILS = 3  # this many name-failures and no success in one run = not the names


def _report():
    return {"research_off": False, "board_companies": 0, "candidates": 0, "researched": 0,
            "failed": 0, "skipped_budget": 0, "unavailable_after": None,
            "unavailable_reason": "", "unavailable_in": "", "soft_outage": False,
            "blurb_outage": False, "blurbs_stopped": False,
            "cap": FIRMO_MAX_PER_RUN, "budget_min": FIRMO_TIME_BUDGET_MIN,
            "blurbs_written": 0, "blurbs_asked": 0, "blurbs_empty": 0, "blurbs_missing": 0,
            "blurbs_skipped_budget": 0, "blurbs_derived": 0, "blurbs_waiting": 0,
            "export_status": "ok",
            "export_records": 0, "export_newest": "", "store_records": 0, "synced": 0,
            "published": False, "publish_error": "", "scoped": False, "error": "", "gated": 0}


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
    return next((j.get("description") for j in jobs
                 if j.get("company") == company and j.get("description")), "")


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


def _blurbs(st, board_jobs, run_date, use_llm, rep, profiles_path, clock=None):
    from . import company_info as _ci
    company_info = {**st.load_company_info(), **_load_profiles(profiles_path)}
    board = {j["company"] for j in board_jobs}
    # one blurb per identity: "Meta" and "Meta Israel" are one company (both had paid)
    by_key = {}
    for c, s in company_info.items():
        if s:
            by_key.setdefault(identity_key(c), s)
    for c in board:
        if not company_info.get(c) and by_key.get(identity_key(c)):
            company_info[c] = by_key[identity_key(c)]
    missing = sorted(c for c in board if not company_info.get(c))
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
    todo = todo[:BLURB_MAX_PER_RUN]
    clock = clock or _Clock(rep["budget_min"])
    empties, empty_names = 0, []
    for i, company in enumerate(todo):
        if clock.remaining() < 30:
            rep["blurbs_skipped_budget"] = len(todo) - i
            break
        try:
            rep["blurbs_asked"] += 1
            summ = _ci.summarize_company(company, _context_for(company, board_jobs),
                                         timeout=int(max(10, min(90, clock.remaining()))))
        except ResearchUnavailable as e:
            rep["blurbs_asked"] -= 1
            rep["unavailable_after"] = i
            rep["unavailable_in"] = "blurbs"
            rep["unavailable_reason"] = str(e)
            break
        company_info[company] = summ
        st.save_company_info({company: summ}, run_date)
        if summ:
            rep["blurbs_written"] += 1
            empties, empty_names = 0, []
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
    failures = st.load_firmo_failures()
    cutoff = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=STRIKE_RETRY_DAYS)).isoformat()
    norms = {identity_key(c) for c in firmo}
    failed_norms = {identity_key(c) for c, (_att, last) in failures.items() if last > cutoff}
    out, batch, gated = [], set(), 0
    for c in _research_order(board_jobs, email_jobs):
        k = identity_key(c)
        if c in firmo or k in norms or k in batch:
            continue  # profiled, or "X Israel" beside "X" in one digest: one slot, one record
        if k in failed_norms or looks_like_junk(c):
            gated += 1  # a failed name retries weekly; a leaked job title never
            continue
        batch.add(k)
        out.append(c)
    return out, gated


def _research(st, targets, board_jobs, run_date, rep, clock=None):
    clock = clock or _Clock(rep["budget_min"])
    todo = targets[:rep["cap"]]
    done, failed_names = {}, []
    for i, company in enumerate(todo):
        remaining = clock.remaining()
        if remaining < 60:
            rep["skipped_budget"] = len(todo) - i
            break
        if not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
            # exit-0 prose, a revoked WebSearch grant: every answer so far failed and none
            # succeeded — evidence about the infrastructure, not about three company names
            rep["soft_outage"] = True
            rep["skipped_budget"] = len(todo) - i
            break
        try:
            rec = research_company(company, _context_for(company, board_jobs),
                                   timeout=int(min(RESEARCH_TIMEOUT_S, remaining)))
        except ResearchUnavailable as e:
            # infrastructure outage: don't blame the names, don't burn the budget
            rep["unavailable_after"] = i
            rep["unavailable_in"] = "research"
            rep["unavailable_reason"] = str(e)
            break
        if rec:
            st.save_firmographics({company: rec}, run_date)
            done[company] = rec
        else:
            failed_names.append(company)
    rep["researched"] = len(done)
    rep["failed"] = len(failed_names)
    if failed_names and not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
        rep["soft_outage"] = True
    else:
        for c in failed_names:
            st.record_firmo_failure(c, run_date)
    return done


def enrich_for_run(st, *, board_jobs, email_jobs=(), all_companies=None, run_date,
                   use_llm=True, scoped=False, profiles_path=None):
    """Blurbs + firmographics for one digest run -> (company_info, firmo_display, report).

    The never-raises front door: company intel is best-effort by design and must not cost
    the day's email and board (one locked sqlite `save_firmographics` used to). On an
    unexpected exception the reader still gets whatever was assembled, and the audit line
    says `company intel FAILED: ...`."""
    rep = _report()
    holder = {"company_info": {}, "firmo_display": {}}
    try:
        return _enrich(st, board_jobs=board_jobs, email_jobs=email_jobs,
                       all_companies=all_companies, run_date=run_date, use_llm=use_llm,
                       scoped=scoped, profiles_path=profiles_path, rep=rep, holder=holder)
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {e}"[:160]
        print(f"  [company-intel] FAILED: {rep['error']}", file=sys.stderr, flush=True)
        return holder["company_info"], holder["firmo_display"], rep


def _enrich(st, *, board_jobs, email_jobs, all_companies, run_date, use_llm, scoped,
            profiles_path, rep, holder):
    """The work behind `enrich_for_run`; `holder` carries partial results out on failure.

    Never raises. Spends at most BLURB_MAX_PER_RUN + FIRMO_MAX_PER_RUN `claude` calls and
    FIRMO_TIME_BUDGET_MIN minutes on research; stops at the first infrastructure failure.
    Reads sqlite ∪ the shared export, seeds sqlite from the export, and writes the union
    back — except on a scoped run (`--only`/`--limit`), which must leave the committed
    file alone, and except when the export is corrupt, which must not be replaced by
    the smaller sqlite table. `audit_lines(report)` turns the report into the mail."""
    rep["research_off"] = not use_llm
    rep["scoped"] = bool(scoped)
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
                                          clock)
    holder["company_info"] = company_info

    targets, rep["gated"] = _research_targets(st, board_jobs, email_jobs, firmo, run_date)
    rep["candidates"] = len(targets)
    if use_llm and targets and rep["unavailable_after"] is None and not rep["blurb_outage"]:
        firmo.update(_research(st, targets, board_jobs, run_date, rep, clock))
    # else: the CLI is down or not answering — the outage sentence carries the count

    # every company we have ever matched renders a card (board, email, archive), looked up
    # under the normalized identity so "SolarEdge Technologies" finds the stored "SolarEdge"
    by_key = display_index(firmo)
    wanted = set(all_companies or ()) | board
    firmo_display = {c: (firmo.get(c) or by_key.get(identity_key(c))) for c in wanted}
    firmo_display = {k: chip_safe(v) for k, v in firmo_display.items() if v}
    holder["firmo_display"] = firmo_display

    # a company with facts but no blurb reads its facts as prose — no call, not cached
    from . import company_info as _ci
    for c in still_missing:
        text = _ci.derive_blurb(c, firmo_display.get(c))
        if text:
            company_info[c] = text
            rep["blurbs_derived"] += 1

    if not scoped and rep["export_status"] != "corrupt":
        try:
            rep["published"] = save_shared(firmo)
        except Exception as e:  # noqa: BLE001
            rep["publish_error"] = f"{type(e).__name__}: {e}"[:120]
            print(f"  [company-intel] shared export NOT written: {e}", file=sys.stderr, flush=True)
    return company_info, firmo_display, rep


def _ascii(s, n=80):
    """CLI stderr and exception text carry box-drawing glyphs and Hebrew names; the line
    they land in is printed to a console that may be cp1252 (the laptop's `run_daily.ps1`
    pipe), and `pipeline/run.py` does not reconfigure stdout — so the never-raises guard
    would be undone by the act of reporting. Fold to ASCII before it leaves the report."""
    return " ".join(str(s or "").split()).encode("ascii", "replace").decode()[:n]


def audit_lines(rep):
    """(mail lines, ::warning:: lines) from `enrich_for_run`'s report. Pure; no I/O.

    One line a reader can reconcile: researched + failed + skipped + waiting = candidates."""
    parts, warn = [], []
    n, c = rep["board_companies"], rep["candidates"]
    if rep.get("error"):
        msg = f"company intel FAILED ({_ascii(rep['error'], 160)}) — cards render from whatever was assembled"
        parts.append(msg)
        warn.append(msg)
    gated = (f" ({rep['gated']} more unprofiled: research failed, weekly retry)"
             if rep.get("gated") else "")
    if rep["research_off"]:
        parts.append((f"research off (--no-llm); {c} of {n} board companies unprofiled"
                      if c else f"research off (--no-llm); all {n} board companies profiled") + gated)
    elif c == 0:
        parts.append(f"all {n} board companies profiled" + gated)
    else:
        bits = [f"{rep['researched']} researched", f"{rep['failed']} failed"]
        if rep["skipped_budget"]:
            bits.append(f"{rep['skipped_budget']} skipped (budget {rep['budget_min']:g}m spent)")
        waiting = c - rep["researched"] - rep["failed"] - rep["skipped_budget"]
        if rep["unavailable_after"] is None and waiting > 0:
            bits.append(f"{waiting} over the cap wait for the next run")
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
        msg = (f"claude unavailable after {k} {loop} call{'' if k == 1 else 's'} "
               f"({_ascii(rep['unavailable_reason'])}) — {left} unprofiled board "
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
    if rep["blurbs_derived"]:
        b.append(f"{rep['blurbs_derived']} derived from facts")
    if rep["blurbs_waiting"]:
        b.append(f"{rep['blurbs_waiting']} waiting (monthly retry / same company)")
    parts.append("blurbs: " + ", ".join(b))
    if rep["export_status"] == "ok":
        e = f"export {rep['export_records']} records, newest {rep['export_newest'] or '?'}"
        if rep["synced"]:
            e += f", {rep['synced']} newer than the store"
        parts.append(e)
        if rep.get("publish_error") or (not rep["published"] and not rep.get("scoped")
                                        and not rep.get("error")):
            msg = "export NOT written" + (f" ({_ascii(rep.get('publish_error'), 120)})"
                                          if rep.get("publish_error") else " (nothing to write)")
            parts.append(msg)
            warn.append(msg)
    else:
        e = (f"export {rep['export_status'].upper()} at cloud_state/firmographics.json — cards "
             f"render from sqlite only ({rep['store_records']} records)"
             + ("; file left untouched" if rep["export_status"] == "corrupt" else ""))
        parts.append(e)
        warn.append(e)
    return [" · ".join(parts)], warn
