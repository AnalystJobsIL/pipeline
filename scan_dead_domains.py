#!/usr/bin/env python3
"""Bulk liveness scan over parked companies: DNS/HTTP-check each row's domain so defunct
companies (Myrror-class) stop consuming hunt cycles and Chrome-sweep attention.

Verdicts appended to notes: 'domain-dead <date>' (candidate for defunct research) — never
auto-deletes; a dead domain can also mean a rebrand, so these get one search-side look.
Usage: python scan_dead_domains.py [--apply]
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import socket
import sys
import urllib.parse
import urllib.request

TODAY = dt.date.today().isoformat()


def alive(url):
    host = urllib.parse.urlparse(url).netloc or url
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except Exception:  # noqa: BLE001
        return False, "dns-dead"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as r:
            return True, f"http {r.status}"
    except urllib.error.HTTPError as e:
        return True, f"http {e.code}"          # server answered — site alive
    except Exception as e:  # noqa: BLE001
        return False, f"conn-dead ({type(e).__name__})"


def main():
    apply = "--apply" in sys.argv
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               and re.search(r"no ATS detected|no IL listing|monitored candidate|unsupported ATS",
                             r[5] or "")
               and "domain-dead" not in (r[5] or "") and "defunct" not in (r[5] or "")
               and (r[3] or "").startswith("http")]
    print(f"liveness-checking {len(targets)} parked companies", flush=True)
    dead = 0
    for n, (i, r) in enumerate(targets, 1):
        ok, why = alive(r[3])
        if not ok:
            dead += 1
            print(f"  [DEAD] {r[0][:32]} ({why}) {r[3][:60]}", flush=True)
            if apply:
                rows[i][5] = (r[5] + f" | domain-dead {TODAY} ({why})")[:220]
                csv.writer(open("companies.csv", "w", encoding="utf-8",
                                newline="")).writerows(rows)
    print(f"=== {dead} dead of {len(targets)} checked ===", flush=True)


if __name__ == "__main__":
    main()
