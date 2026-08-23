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
from audit_empty_rows import tenant_is_this_company
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


def _unlock(url: str) -> str:
    """Residential fetch of a bot-walled page. Empty string when unavailable."""
    if not os.environ.get("BRIGHTDATA_API_KEY"):
        return ""
    try:
        from bd_rescue import unlock
        return unlock(url) or ""
    except Exception:  # noqa: BLE001
        return ""


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
            if not st and not html:
                continue
            if st in (403, 503):
                # A bot wall means we never saw the page, so try the residential unlocker
                # before giving up on evidence: refusing blind costs real recoveries (24% of
                # legitimate `match` domains in this registry are compound, e.g. ide-tech.com
                # for IDE Technologies, and would be refused on the domain rule alone).
                html = _unlock(u)
                st = 200 if html else st
            if st >= 400 and not html:
                continue
            # ONE rule for both branches. `verdict() == "match"` is NOT sufficient evidence on
            # its own, because it also fires when the domain equals the name with its generic
            # words stripped, and that core can be an acronym: "DiA Imaging Analytics" strips
            # to `dia`, `registrable("www.dia.mil")` is `dia`, and this tool printed
            #   [OK] DiA Imaging Analytics  www.dia-analytics.com -> https://www.dia.mil/...
            # for the US Defense Intelligence Agency. Hardening only the 403 branch left the
            # headline case open on the 200 path: 125 of the 516 rows whose own URL scores
            # `match` (24%) rest on a stripped core, and dia.mil was refused only because it
            # happens to answer 403. Evidence is: the whole name IS the domain, or an ATS host
            # whose tenant slug `verdict` already checked, or the PAGE names the company.
            v = identity_verdict(name, u)
            whole_name = bool(_norm(name)) and registrable(
                urllib.parse.urlparse(u).netloc.lower()) == _norm(name)
            # `verdict` returns "ats" when the tenant slug "matches" the company - but that
            # match is plain CONTAINMENT (`_slug_matches_company`), so tenant
            # `careers-bancorpbank` passes for `Bancor` and the blanket verdict was accepted
            # as evidence with no page read. On an ATS the tenant IS the identity, so it has
            # to be near-equal to the name, not merely to contain it - the same "containment
            # must be TIGHT" lesson `company_identity` already learned for domains
            # (rad.com/RADLogics, nooga.net/Noogata).
            # Use the shared predicate, not a hand-rolled any(). The inline version here
            # was a FLAT any() over `_slug_candidates`, which returns host labels and path
            # segments in one list - the exact shape `tenant_is_this_company`'s docstring
            # names as the bug: `novartis.wd3.myworkdayjobs.com/en-US/riskified` passed for
            # Riskified because the PATH matched while the tenant (the host label) is
            # Novartis. This tool runs at 19:00 immediately before listing_hunt in the same
            # job, so a wrong address here is picked up by the fast path ~30 minutes later.
            # `tenant_is_this_company` returns True when there is NOTHING checkable to
            # match against (`if not labels: return True  # cannot tell`). As the first
            # disjunct that short-circuited the page test below, so "cannot tell" was
            # accepted as positive confirmation and this branch replaced a dead host with
            # a bare ATS front door:
            #
            #   SupPlant  careers.supplant-dead.com -> https://careers.workable.com/
            #     verdict=ats, tenant_ok=True (every label is Workable's own plumbing),
            #     page never says "SupPlant" -> written anyway, keeping `host documented`,
            #     which listing_hunt's fast path picks up ~30 minutes later in the same job.
            #
            # An ATS verdict now needs the page to name us as well - which makes a separate
            # `ats_checked` disjunct redundant, so it is gone rather than left as dead
            # logic: "the page names us" already covers every ATS row it used to admit, and
            # covers it on the evidence that actually discriminates. That is docs/BACKLOG.md
            # 29, which recorded that `_page_names_company` "is the gate that matters" -
            # while this tool never called it.
            #
            # What remains is exactly two ways in: the whole name IS the registrable domain,
            # or the fetched page names the company. `tenant_is_this_company` stays only as
            # a VETO on an explicit ATS tenant mismatch; it is never evidence FOR a write,
            # because it returns True whenever there is nothing checkable to match against.
            # Shared three-valued predicate, not a local `bool(html) and
            # page_mentions_company(...)`: the local copy could not use the unlocker and did
            # not strip generic/geographic words, so `<company> Israel` rows failed it on
            # boards that are titled without the suffix. `html` is already fetched here, so
            # passing it costs no extra request. `is True` keeps "unreadable" (None) out.
            from crack_walled import _page_names_company
            names_us = _page_names_company(name, u, html=html) is True
            if v == "ats" and not tenant_is_this_company(name, u):
                names_us = False
            if (v == "match" and whole_name) or names_us:
                good = u
                break
            print(f"       (rejected {u[:52]}: verdict={v}"
                  f"{' on a stripped core' if v == 'match' else ''}"
                  f"{' and the page does not name the company' if html else ' and no page to read'})",
                  flush=True)
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
                            # Fixed-length and host-free, like every sibling refusal/repair note. This was the
                        # last one in the lane still interpolating a hostname: measured against the real
                        # registry it evicted a pool token from 72 hunt rows, 30 probe rows and 21 crack
                        # rows. The old host is still recoverable from git; the note's job is to say what
                        # happened, and a 220-char cell shared by nine tools cannot afford the detail.
                        f"url-repaired {TODAY}: dead host replaced")
                write_csv_rows("companies.csv", fresh)
        else:
            stuck += 1
            print(f"  [--] {n}/{len(dead)} {name[:26]:26} {host_of(old)}: no live "
                  f"careers page found", flush=True)
    print(f"\n=== url repair: {fixed} repaired, {stuck} still unresolvable ===", flush=True)


if __name__ == "__main__":
    main()
