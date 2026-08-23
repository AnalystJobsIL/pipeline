#!/usr/bin/env python3
"""Bulk liveness scan over parked companies: DNS/HTTP-check each row's domain so defunct
companies (Myrror-class) stop consuming hunt cycles and Chrome-sweep attention.

Verdicts appended to notes: 'domain-dead <date>' (candidate for defunct research) — never
auto-deletes; a dead domain can also mean a rebrand, so these get one search-side look.
Usage: python scan_dead_domains.py [--apply] ; env SCAN_TIME_BUDGET_MIN (default 10)
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import ssl
import urllib.request
from pipeline.atomic import write_csv_rows, write_json
from pipeline.notes import replace_own as _note_replace

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

TODAY = dt.date.today().isoformat()
# Rotation state for the time budget. A row found ALIVE writes nothing to companies.csv (only
# the dead/revived branches do), and the target filter carries no date term - so with a budget
# and file-order targets the run re-walks the same prefix every night and the tail is NEVER
# reached. Measured 2026-08-23: 211 of 211 current targets are in exactly that state, which
# made the "re-tested tomorrow" comment on the budget false. One date per company, oldest
# first; `cloud_state/` is committed wholesale by daily-digest.yml so this travels.
SEEN = os.path.join("cloud_state", "scan_seen.json")


def alive(url):
    host = urllib.parse.urlparse(url).netloc or url
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except Exception:  # noqa: BLE001
        return False, "dns-dead"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # GET: HEAD 405s
        # lenient TLS: cert-verify failures are usually the scanning machine, not a dead site
        with urllib.request.urlopen(req, timeout=12, context=_CTX) as r:
            return True, f"http {r.status}"
    except urllib.error.HTTPError as e:
        return True, f"http {e.code}"          # server answered — site alive
    except Exception as e:  # noqa: BLE001
        return False, f"conn-dead ({type(e).__name__})"


def _rescannable(note, days=1):
    """Re-test a dead domain after `days` (default DAILY — a GET costs milliseconds,
    and a revived domain shouldn't wait a month). Domains come back, and TLS/network
    artifacts on the scanning machine produce false positives."""
    m = re.search(r"domain-dead (\d{4}-\d{2}-\d{2})", note or "")
    if not m:
        return True
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days >= days


def main():
    apply = "--apply" in sys.argv
    # This runs INSIDE the digest, in front of the email. Every other tool in this lane is
    # time-budgeted; these two were not. 12s timeout x 211 targets is a 42-minute worst case
    # for a step whose normal cost is ~3.3 min (measured 2026-08-23: 8 rows in 7.5s), and a
    # handful of hosts that black-hole packets is all it takes. Stop cleanly instead: the
    # rows not reached keep their notes and are re-tested tomorrow (_rescannable is daily).
    budget = float(os.environ.get("SCAN_TIME_BUDGET_MIN", "10") or 0)
    t0 = time.time()
    try:
        seen = json.load(open(SEEN, encoding="utf-8"))
        seen = seen if isinstance(seen, dict) else {}
    except Exception:  # noqa: BLE001
        seen = {}
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               and re.search(r"no ATS detected|no IL listing|no listing found|monitored candidate|unsupported ATS",
                             r[5] or "")
               and _rescannable(r[5] or "") and "defunct" not in (r[5] or "")
               # (already-dead rows are re-tested after 30d so a revived domain is cleared)
               and (r[3] or "").startswith("http")]
    # least-recently-scanned first, so a budget-truncated run resumes where it stopped
    targets.sort(key=lambda ir: seen.get(ir[1][0], ""))
    print(f"liveness-checking {len(targets)} parked companies "
          f"({sum(1 for _, r in targets if r[0] not in seen)} never scanned)", flush=True)
    dead = revived = 0
    for n, (i, r) in enumerate(targets, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print(f"time budget {budget}min reached at {n}/{len(targets)} - stopping "
                  f"cleanly; the unscanned tail sorts FIRST tomorrow ({SEEN})", flush=True)
            break
        seen[r[0]] = TODAY                 # scanned, whatever the outcome
        ok, why = alive(r[3])
        if ok and "domain-dead" in (r[5] or ""):
            # revived: clear the flag, otherwise it is a one-way exclusion from
            # listing_hunt / deep_validate / probe_candidates forever
            if apply:
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == r[0] and len(fr) > 5:
                        fr[5] = re.sub(r"\s\|\s?domain-dead [^|]*", "", fr[5]).strip(" |")
                write_csv_rows("companies.csv", fresh)
            revived += 1
            print(f"  [ALIVE] {r[0][:32]} — domain-dead cleared ({why})", flush=True)
            continue
        if not ok:
            dead += 1
            print(f"  [DEAD] {r[0][:32]} ({why}) {r[3][:60]}", flush=True)
            if apply:
                # single-writer discipline: re-read + match by name. Writing the
                # start-of-run snapshot here silently REVERTED revivals cleared earlier
                # in the same run, while still logging them as successful.
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == r[0] and len(fr) > 5:
                        fr[5] = _note_replace(fr[5], "domain-dead",
                                              f"domain-dead {TODAY} ({why})")
                write_csv_rows("companies.csv", fresh)
    if apply:
        os.makedirs(os.path.dirname(SEEN) or ".", exist_ok=True)
        write_json(SEEN, seen, indent=0, sort_keys=True)
    print(f"=== {dead} dead, {revived} revived of {len(targets)} checked ===", flush=True)


if __name__ == "__main__":
    main()
