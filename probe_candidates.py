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
import json
import re
import sys
import urllib.request
from pipeline.atomic import write_csv_rows

STATE = "cloud_state/candidate_probe.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"
_JOB_SIG = re.compile(r"apply now|open position|current opening|we'?re hiring|job opening|"
                      r"משרות|דרושים|careers-position|/job/|jobs/search", re.I)
_IL_SIG = re.compile(r"israel|tel[\s-]?aviv|herzliya|haifa|petah|ramat[\s-]?gan|beer[\s-]?sheva", re.I)


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
    print(f"probing {len(targets)} monitored candidates", flush=True)
    woke = 0
    for i, r in targets:
        name = r[0]
        cur = probe(r[3])
        if cur is None:
            continue
        prev = state.get(name)
        state[name] = cur
        if prev is None:
            continue                      # first observation = baseline, no wake
        if cur["il"] > prev["il"] or (cur["sig"] > 0 and prev["sig"] == 0):
            woke += 1
            print(f"  [WAKE] {name}: signals rose il {prev['il']}->{cur['il']} "
                  f"sig {prev['sig']}->{cur['sig']}", flush=True)
            if apply:
                # clear the hunt verdict -> today's 14:00 hunt cycle re-processes it
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == name:
                        # order matters: stamp the woken state, THEN drop the old verdict
                        # suffix (doing it the other way deleted what the stamp matched,
                        # leaving the woken state unreachable)
                        base = re.sub(r"\s\|\s(listing-hunt|crack-walled) [^|]*", "", fr[5])  # any position, not just trailing
                        fr[5] = (base + " | probe-woken: re-hunt pending")[:220]
                write_csv_rows("companies.csv", fresh)
    if apply:
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    print(f"=== probe: {woke} candidates woke (of {len(targets)}) ===", flush=True)


if __name__ == "__main__":
    main()
