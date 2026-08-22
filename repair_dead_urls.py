#!/usr/bin/env python3
"""Replace stored careers URLs whose HOSTNAME does not resolve with a real, verified one.

43 rows point at a hostname that has no DNS record at all. Most were fabricated by
crack_walled's `careers.<domain>` template guess, which was persisted even though it failed
verification (fixed at source); every later tool then faithfully re-tested the fabrication
and recorded another honest-looking "unreachable" verdict against it.

A dead hostname is unrecoverable by rendering, unlocking or cracking — there is nothing to
render. It can only be fixed by SEARCHING for the company's real careers page. So:

    NXDOMAIN -> search (Bright Data Google; DDG is blocked from some networks)
             -> keep candidates that resolve AND are not aggregators AND pass the
                company-identity check
             -> verify by fetching; persist the first that returns a real page

The row keeps its parked state and its triage mode: this repairs the ADDRESS, not the
verdict. The next hunt/crack pass then has something real to work with.

Usage: python repair_dead_urls.py [--apply] [--limit N]
Env:   REPAIR_URL_TIME_BUDGET_MIN
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import socket
import sys
import time
import urllib.parse
import urllib.request

from pipeline.aggregators import is_aggregator
from pipeline.company_identity import (verdict as identity_verdict,
                                       page_mentions_company)
from pipeline.atomic import write_csv_rows

TODAY = dt.date.today().isoformat()
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def resolves(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc


def fetch(url: str):
    """(status, html). A 403/503 still means the HOST is real — a bot wall the unlocker can
    crack later, categorically different from NXDOMAIN."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(400000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:  # noqa: BLE001
        return 0, ""


def reachable(url: str) -> int:
    """HTTP status, or 0. A 403/503 still means the HOST is real — that is a bot wall the
    unlocker can crack later, which is categorically different from NXDOMAIN."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def candidates(name: str, dead_url: str):
    """Search first; then the obvious patterns on the company's registrable domain."""
    from deep_validate import ddg, google_via_unlocker
    out = []
    for q in (f"{name} careers Israel", f"{name} jobs"):
        try:
            out += ddg(q) or []
        except Exception:  # noqa: BLE001
            pass
        if len(out) < 3:
            try:
                out += google_via_unlocker(q) or []
            except Exception:  # noqa: BLE001
                pass
        if len(out) >= 5:
            break
    # the dead host usually embeds the real domain: careers.pliops.com -> pliops.com
    h = host_of(dead_url)
    parts = [p for p in h.split(".") if p not in ("www", "careers", "jobs", "apply")]
    if len(parts) >= 2:
        base = ".".join(parts[-2:])
        if resolves(base) or resolves("www." + base):
            out += [f"https://{base}/careers", f"https://{base}/careers/",
                    f"https://www.{base}/careers", f"https://www.{base}/jobs"]
    seen, uniq = set(), []
    for u in out:
        if not u or not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        if is_aggregator(u):
            continue
        if identity_verdict(name, u) == "mismatch":
            continue                       # another company's careers page
        if not resolves(host_of(u)):
            continue
        uniq.append(u)
    return uniq[:6]


def main():
    from bd_rescue import _load_secrets
    _load_secrets()
    apply = "--apply" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    budget = int(os.environ.get("REPAIR_URL_TIME_BUDGET_MIN", "0"))

    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    dead = [r for r in rows if r and len(r) >= 6 and (r[3] or "").startswith("http")
            and host_of(r[3]) and not resolves(host_of(r[3]))]
    if limit:
        dead = dead[:limit]
    print(f"{len(dead)} rows whose stored hostname does not resolve\n", flush=True)

    fixed = stuck = 0
    t0 = time.time()
    for n, r in enumerate(dead, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print("time budget reached — stopping cleanly", flush=True)
            break
        name, old = r[0], r[3]
        good = ""
        for u in candidates(name, old):
            st, html = fetch(u)
            if not st:
                continue
            if st in (403, 503):
                good = u        # bot wall: host is real, unlocker cracks it downstream
                break
            if st >= 400:
                continue
            # A reachable page is not enough — it must be THIS company's. A `weak` domain
            # verdict (phoenix -> phoenixtma.com) is confirmed only by page content.
            v = identity_verdict(name, u)
            if v in ("match", "ats") or page_mentions_company(name, html):
                good = u
                break
            print(f"       (rejected {u[:52]}: page does not name the company)", flush=True)
        if good:
            fixed += 1
            print(f"  [OK] {n}/{len(dead)} {name[:26]:26} {host_of(old)} -> {good[:56]}",
                  flush=True)
            if apply:
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if fr and fr[0] == name and len(fr) >= 6:
                        fr[3] = good
                        seg = f"url-repaired {TODAY}: dead host {host_of(old)} replaced"
                        room = 220 - len(seg) - 3
                        fr[5] = (f"{(fr[5] or '')[:room]} | {seg}" if room > 20 else seg)
                write_csv_rows("companies.csv", fresh)
        else:
            stuck += 1
            print(f"  [--] {n}/{len(dead)} {name[:26]:26} {host_of(old)}: no live "
                  f"careers page found", flush=True)
    print(f"\n=== url repair: {fixed} repaired, {stuck} still unresolvable ===", flush=True)


if __name__ == "__main__":
    main()
