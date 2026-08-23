#!/usr/bin/env python3
"""Daily cheap probe of monitored-candidate pages (inactive rows with a documented URL).

The 14-day re-hunt cadence would miss a role posted tomorrow. This closes the gap: plain
HTTP fetch (no browser) of every documented candidate URL each morning, counting job-signal
and Israel-signal occurrences. When a page's signals RISE versus the stored baseline, the
row's hunt verdict is cleared — so the same day's 14:00 listing-hunt cycle re-processes it
with full rendering + verification. Detection latency: ~1 day for the whole monitored pool.

State: cloud_state/candidate_probe.json (committed by the digest persist step).
Usage: python probe_candidates.py [--apply]
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from pipeline.atomic import write_csv_rows

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


TODAY = dt.date.today().isoformat()
STATE = "cloud_state/candidate_probe.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"
_JOB_SIG = re.compile(r"apply now|open position|current opening|we'?re hiring|job opening|"
                      r"משרות|דרושים|careers-position|/job/|jobs/search", re.I)
_IL_SIG = re.compile(r"israel|tel[\s-]?aviv|herzliya|haifa|petah|ramat[\s-]?gan|beer[\s-]?sheva", re.I)


WAKE_STAMP = "probe-woken: re-hunt pending"
# Verdicts that mean "already decided, don't hunt". A wake must clear ALL of them or the
# row stays excluded from the very hunt the probe exists to trigger.
_STALE_SEGMENT = re.compile(r"^(listing-hunt|crack-walled|dark-triage)\b")


def _wake_note(note: str, cap: int = 220) -> str:
    """Drop every stale verdict segment and stamp the woken state.

    Was a single `re.sub(r"\\s\\|\\s?(listing-hunt|crack-walled) [^|]*", ...)`, which had two
    defects: it never mentioned `dark-triage`, so `listing_hunt._triaged_page_empty` kept
    excluding woken page-empty rows (105/105 wakes swallowed); and after removing one segment
    the separator became "|" with no leading space, so the pattern could not match the next
    one — only the first stale segment was ever stripped. Splitting on "|" avoids both.
    """
    kept = [s.strip() for s in (note or "").split("|")
            if s.strip() and not _STALE_SEGMENT.match(s.strip())]
    # `pipeline.notes.append` drops OLD WHOLE segments to make room. Slicing the base
    # instead cut the newest surviving verdict in half — that is where 87 rows saying
    # `dark-triage 2026-08-22: page-emp` came from, a mode no downstream filter matches.
    from pipeline.notes import append as _append
    return _append(" | ".join(kept), WAKE_STAMP, cap)


def probe(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read(600_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return {"sig": len(_JOB_SIG.findall(body)), "il": len(_IL_SIG.findall(body))}


def main():
    apply = "--apply" in sys.argv
    # Runs INSIDE the digest, in front of the email — same reasoning as scan_dead_domains:
    # a 12s timeout x ~180 targets is a ~36-minute worst case for a step nothing bounds, and
    # the 05:45 relay does not wait. A row not probed today keeps its baseline and is probed
    # tomorrow: the wake is delayed, never lost, because candidate_probe.json only advances
    # for rows this run actually read.
    budget = float(os.environ.get("PROBE_TIME_BUDGET_MIN", "10") or 0)
    t0 = time.time()
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               and re.search(r"monitored candidate|host documented|no IL listing", r[5] or "")
               and "domain-dead" not in r[5] and "defunct" not in r[5]
               and (r[3] or "").startswith("http")]
    # Least-recently-probed first. The target filter has no date term, so with a budget and
    # file-order targets the same prefix is probed every day and the tail never is - and a row
    # past the cut can NEVER wake, because a wake needs two observations and the first one it
    # never gets. Measured 2026-08-23: 64 of 181 targets had no baseline at all.
    targets.sort(key=lambda ir: (state.get(ir[1][0]) or {}).get("last", ""))
    print(f"probing {len(targets)} monitored candidates "
          f"({sum(1 for _, r in targets if r[0] not in state)} without a baseline)", flush=True)
    woke = 0
    for n, (i, r) in enumerate(targets, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print(f"time budget {budget}min reached at {n}/{len(targets)} — stopping "
                  f"cleanly; unprobed rows keep their baseline for tomorrow", flush=True)
            break
        name = r[0]
        cur = probe(r[3])
        if cur is None:
            # a fetch error must still advance the rotation key, or the erroring rows
            # re-consume the head of the budget every night - the same starvation the
            # rotation fixed, for the error subset
            e = state.get(name) or {}
            e["last"] = TODAY
            state[name] = e
            continue
        prev = state.get(name)
        # A rotation-only entry (written by the error path below) has `last` but no
        # sig/il. Treating it as a baseline raises KeyError on `prev["il"]` at the very
        # next SUCCESSFUL probe - before `json.dump`, so the state never advances again
        # and, behind the workflow's `|| echo "probe skipped"`, no candidate ever wakes
        # again. Measured 2026-08-23: 61 of the 153 targets have no baseline and 39 of a
        # 40-row sample error, so the first --apply run would poison ~59 rows and the
        # second would kill the step. An incomplete entry is NOT a baseline.
        if not (isinstance(prev, dict) and "il" in prev and "sig" in prev):
            prev = None
        cur["last"] = TODAY                # rotation key; see the sort above
        state[name] = cur
        if prev is None:
            continue                      # first observation = baseline, no wake
        if cur["il"] > prev["il"] or (cur["sig"] > 0 and prev["sig"] == 0):
            woke += 1
            print(f"  [WAKE] {name}: signals rose il {prev['il']}->{cur['il']} "
                  f"sig {prev['sig']}->{cur['sig']}", flush=True)
            if apply:
                # clear the hunt verdict -> tonight's 19:00 hunt re-processes it
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == name:
                        # order matters: stamp the woken state, THEN drop the old verdict
                        # suffix (doing it the other way deleted what the stamp matched,
                        # leaving the woken state unreachable)
                        fr[5] = _wake_note(fr[5])
                write_csv_rows("companies.csv", fresh)
    if apply:
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    print(f"=== probe: {woke} candidates woke (of {len(targets)}) ===", flush=True)


if __name__ == "__main__":
    main()
