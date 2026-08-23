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
                                       page_mentions_company, registrable, _norm)
from pipeline.atomic import write_csv_rows
from pipeline.notes import append as _note_append, replace_own as _note_replace

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
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


_DNS_CACHE: dict[str, bool] = {}


def resolves(host: str, tries: int = 3) -> bool:
    """DNS with retries, because a TRANSIENT failure must not retire a live company.

    Windows reports errno 11002 (TRY_AGAIN) as well as 11001 (HOST_NOT_FOUND), and a single
    lookup conflates them — declaring a company defunct on a momentary resolver hiccup is
    exactly the kind of silent coverage loss this repo keeps producing. Only a repeated
    failure counts as dead. Results are cached per run; hosts are checked many times.
    """
    if host in _DNS_CACHE:
        return _DNS_CACHE[host]
    ok = False
    for attempt in range(tries):
        try:
            socket.gethostbyname(host)
            ok = True
            break
        except OSError:
            if attempt < tries - 1:
                time.sleep(1.0)
    _DNS_CACHE[host] = ok
    return ok


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
                # bot wall: the host is real and the unlocker cracks it downstream — but a
                # wall means we never saw the page, so identity rests on the domain alone.
                # `match` is NOT strong enough on its own. `company_identity.verdict` also
                # returns `match` when the domain equals the name with its generic words
                # stripped, and that core can be an acronym: "DiA Imaging Analytics" strips
                # to `dia`, `registrable("www.dia.mil")` is `dia`, and this branch was one
                # dry-run away from repairing an Israeli medical-imaging company to the US
                # Defense Intelligence Agency's careers page — on a 403 with zero bytes of
                # HTML read. (Same shape as "Time To Know" -> time.com, one layer along.)
                # With no page to confirm against, the only domain evidence worth having is
                # the WHOLE name: registrable(host) == _norm(company). An ATS host is fine
                # too — there identity is the tenant slug and `verdict` has already checked
                # it. See docs/BACKLOG.md, "A stripped core is not identity".
                v_wall = identity_verdict(name, u)
                whole_name = _norm(name) and registrable(
                    urllib.parse.urlparse(u).netloc.lower()) == _norm(name)
                if v_wall == "ats" or (v_wall == "match" and whole_name):
                    good = u
                    break
                print(f"       (bot-walled {u[:46]}: verdict={v_wall} rests on a stripped "
                      f"core, not the full name — cannot confirm without the page)",
                      flush=True)
                continue
                print(f"       (bot-walled {u[:46]}: cannot confirm it is this company)",
                      flush=True)
                continue
            if st >= 400:
                continue
            # A reachable page is not enough — it must be THIS company's. A `weak` domain
            # verdict (phoenix -> phoenixtma.com) is confirmed only by page content.
            v = identity_verdict(name, u)
            # A `weak` domain verdict needs the page to name the company as a PHRASE, not
            # to merely contain its words: "Time To Know" was repaired to time.com's own
            # careers page, which of course says both "time" and "know".
            if v in ("match", "ats") or page_mentions_company(name, html, strict=(v == "weak")):
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
                        fr[5] = _note_replace(
                            fr[5], "url-repaired",
                            f"url-repaired {TODAY}: dead host {host_of(old)} replaced")
                write_csv_rows("companies.csv", fresh)
        else:
            stuck += 1
            print(f"  [--] {n}/{len(dead)} {name[:26]:26} {host_of(old)}: no live "
                  f"careers page found", flush=True)
    print(f"\n=== url repair: {fixed} repaired, {stuck} still unresolvable ===", flush=True)


if __name__ == "__main__":
    main()
