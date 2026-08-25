#!/usr/bin/env python3
"""Crack the 'unsupported ATS' companies (Phenom / Eightfold / iCIMS / SuccessFactors /
Oracle HCM / Avature / Jobvite / Taleo).

Two proven levers:
  - oraclehcm has a native fetcher (plain REST) — we just need host+site, sniffed from the
    company's careers pages (the SPA's own hcmRestApi calls betray them).
  - Everything else falls to the 4-strategy scraper ONCE pointed at the ATS-hosted search/
    listing URL (Qualcomm/Eightfold proven via XHR capture). So: sniff the careers page,
    capture the ATS host from network requests / HTML, construct the platform's canonical
    listing URL, then verify with scrape_universal (>=1 IL job) or the oracle fetcher.

Playwright discipline: short-lived Renderer per company, CLOSED before scrape() runs.
Usage: python crack_walled.py [--apply] ; env CRACK_LIMIT
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

from deep_validate import Renderer, ddg
from audit_empty_rows import AGG, verify
from pipeline.aggregators import is_aggregator
# One seam, called through the MODULE, never bound with `from ... import x as y`. A
# `from` binding is a separate module global, so patching the gate would not reach it -
# which is how two fixtures silently started hitting the live network instead of their
# stub. Attribute access resolves at call time, so there is exactly one place to patch.
from pipeline import identity_gate as _gate
from pipeline.atomic import write_csv_rows
from pipeline.notes import append as _note_append, replace_own as _note_replace
from pipeline.company_identity import is_foreign
# The identity gate is `pipeline/` because five root tools consult it and it used to live
# here, in a leaf, reachable from two of them only through a lazy in-function import that
# existed to dodge an import cycle. docs/BACKLOG.md 30. These names are re-exported under
# their old private spellings so nothing outside has to care where they moved.
from pipeline.company_identity import looks_like_a_job_listing_page, page_mentions_company
from pipeline.recruiters import is_recruiter

# States no re-check pool may re-open — THE shared list (docs/BACKLOG.md 47, closed).
# This copy used to spell 3 of the 6 tokens; deriving it moves exactly ONE row out of
# this pool (`Marvell Israel`, note `redundant scrape dup of working ATS twin`, whose
# active twin is scanned) — wave-6 R1 measured it; the wider 9-row figure in an earlier
# version of this comment was the parked-row census, not this pool.
from pipeline.verdicts import TERM_RX as TERMINAL

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
# lenient TLS for the identity re-fetch: a cert-verify failure is the scanning machine,
# not evidence about who owns the page (ARCHITECTURE section 2 - it cost 6 false positives)
_LENIENT = ssl.create_default_context()
_LENIENT.check_hostname = False
_LENIENT.verify_mode = ssl.CERT_NONE
# "Microsoft Israel" on a page that only ever says "Microsoft" is still Microsoft's page
_NAME_STOP = {"israel", "israeli", "ltd", "ltd.", "inc", "inc.", "the", "group",
              "technologies", "technology", "labs", "systems", "solutions", "company",
              "companies", "corp", "corporation", "holdings", "international", "global",
              "studios"}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_HOST_PATTERNS = {
    "eightfold": re.compile(r"https://([a-z0-9.-]+?)(?:\.eightfold\.ai|/api/pcsx|/api/apply/v2)", re.I),
    "phenom": re.compile(r"https://([a-z0-9.-]+)/(?:widgets|api/apply/v2|api/pcsx)", re.I),
    "icims": re.compile(r"https://([a-z0-9-]+)\.icims\.com", re.I),
    "successfactors": re.compile(r"https://([a-z0-9.-]+)\.(?:successfactors|sapsf)\.[a-z.]+", re.I),
    "oraclecloud": re.compile(r"https://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_]+)", re.I),
    "avature": re.compile(r"https://([a-z0-9.-]+\.avature\.net)(/[a-z0-9_-]*)?", re.I),
    "jobvite": re.compile(r"https://jobs\.jobvite\.com/([a-z0-9-]+)", re.I),
    "taleo": re.compile(r"https://([a-z0-9.-]+)\.taleo\.net", re.I),
}


def _platform_of(note, url=""):
    m = re.search(r"unsupported ATS ([A-Za-z.]+)", note or "")
    if not m:
        return _gate.host_platform(url)          # note token gone (or never written): use the host
    p = m.group(1).lower()
    return _gate._PLATFORM_ALIAS.get(p, p)


def in_crack_pool(r):
    """The crack pool's OWN membership rule (dateless -- `main()` adds `_recrackable`,
    the rotation cooldown). `registry_health` imports this instead of re-spelling
    `is_walled + terminal + recruiter`, and the behavioural cells pin each exclusion:
    a `redundant`-noted walled twin (Marvell Israel) must never re-enter -- dropping
    that token from the shared TERMINAL went suite-green until this existed (wave-6 R2).
    """
    from pipeline.verdicts import is_terminal_row
    return (len(r) >= 6 and r[4] == "false" and _gate.is_walled(r)
            and not is_terminal_row(r))


def listing_urls(platform, m, page_url):
    """Canonical Israel-friendly listing/API URLs for a captured host match."""
    if platform == "oraclecloud":
        host, site = m.group(1), m.group(2)
        return [("oraclehcm",
                 f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                 f"?onlyData=true&finder=findReqs;siteNumber={site}")]
    if platform == "icims":
        t = m.group(1)
        return [("scrape", f"https://{t}.icims.com/jobs/search?ss=1&searchLocation=Israel"),
                ("scrape", f"https://{t}.icims.com/jobs/search?ss=1")]
    if platform in ("eightfold", "phenom"):
        host = m.group(1)
        host = host if "." in host else f"{host}.eightfold.ai"
        # The native fetchers exist (2026-08-24, `fetch_eightfold` / `fetch_phenom`): a
        # cracked tenant becomes an API row, verified through `verify()` like oraclehcm,
        # instead of a nightly browser render (BACKLOG 77). Eightfold's `?domain=` is the
        # COMPANY's domain (careers.qualcomm.com -> qualcomm.com); on the shared
        # app.eightfold.ai host it is the careers page's own host.
        page_host = urllib.parse.urlparse(page_url or "").netloc.lower().replace("www.", "")
        dom = (host.split(".", 1)[1] if host.count(".") > 1 and "eightfold.ai" not in host
               else (page_host if page_host and "eightfold.ai" not in page_host else ""))
        api = ([("eightfold", f"https://{host}/api/pcsx/search?domain={dom}")] if dom
               else []) if platform == "eightfold" else [("phenom", f"https://{host}/widgets")]
        return api + [("scrape", f"https://{host}/careers?location=Israel"),
                      ("scrape", f"https://{host}/careers")]
    if platform == "successfactors":
        return [("scrape", page_url)]           # RMK career sites: scrape the site itself
    if platform == "avature":
        return [("scrape", f"https://{m.group(1)}{m.group(2) or ''}")]
    if platform == "jobvite":
        return [("scrape", f"https://jobs.jobvite.com/{m.group(1)}/search?l=Israel"),
                ("scrape", f"https://jobs.jobvite.com/{m.group(1)}")]
    if platform == "taleo":
        return [("scrape", page_url)]
    return []


def crack_one(name, seed, platform):
    cands = [] if not seed or is_aggregator(seed) else [seed]
    cands += [u for u in ddg(f"{name} careers") if u not in cands]
    if len(cands) < 2:
        # DuckDuckGo returns nothing from datacenter/blocked networks, and with no fallback
        # this only ever tried the stored seed — which for these rows is the MARKETING
        # careers page, not the ATS. listing_hunt has had this fallback all along; crack did
        # not, which is much of why 29 of 39 came back "nocapture" on its first real run.
        from deep_validate import google_via_unlocker
        try:
            cands += [u for u in google_via_unlocker(f"{name} careers")
                      if u not in cands and not is_aggregator(u)]
        except Exception:  # noqa: BLE001
            pass
    captures = []
    rx = _HOST_PATTERNS.get(platform)
    if not rx:
        return ("skip", None, 0, f"no pattern for {platform}")
    with Renderer() as rend:
        queue = list(cands[:2])
        visited = set()
        while queue and not captures and len(visited) < 5:
            u = queue.pop(0)
            if u in visited:
                continue
            visited.add(u)
            html, reqs, _ = rend.sniff(u)
            # A bot-walled page renders nearly empty, so the ATS embed signature is never
            # seen and the company is written off as "ATS host not seen in render".
            # Residential-unlocker HTML carries the same embed — scan it too.
            if len(html or "") < 2000 and os.environ.get("SCRAPE_VIA_UNLOCKER"):
                try:
                    from bd_rescue import unlock
                    html = (html or "") + "\n" + (unlock(u) or "")
                except Exception:  # noqa: BLE001
                    pass
            blob = (html or "") + "\n" + "\n".join(reqs)
            from audit_empty_rows import _slug_matches
            for m in rx.finditer(blob):
                # host/tenant must resemble the company name — DDG once offered Eli Lilly's
                # careers site for "Lili"; only the 0-IL verify blocked it
                if not _slug_matches(name, m.group(1)) and u not in (seed or ""):
                    continue
                for kind, lu in listing_urls(platform, m, u):
                    if (kind, lu) not in captures:
                        captures.append((kind, lu))
            if captures:
                break
            # marketing /careers pages often LINK to the ATS-hosted site instead of
            # embedding it — follow the most careers-ish links one hop deep
            for lm in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html or ""):
                lu = urllib.parse.urljoin(u, lm.group(1))
                if (re.search(r"career|job|position|opening|apply", lu, re.I)
                        and not is_aggregator(lu) and lu not in visited):
                    queue.append(lu)
    if not captures and platform in ("phenom", "eightfold") and cands:
        # Canonical guess from the company's own domain. "Verification gates correctness"
        # was only half true: the guess failed verification but was still PERSISTED as the
        # row's api_url, so 34 companies ended up pointing at a hostname that does not
        # exist (careers.pliops.com, careers.tevapharm.com, careers.lili.co — all NXDOMAIN)
        # and every later tool faithfully re-tested the fabrication. Resolve DNS first.
        import socket
        d = urllib.parse.urlparse(cands[0]).netloc.replace("www.", "")
        base = ".".join(d.split(".")[-2:])
        for h in (f"careers.{base}", f"jobs.{base}"):
            try:
                socket.gethostbyname(h)
            except OSError:
                continue
            captures += [("scrape", f"https://{h}/careers?location=Israel"),
                         ("scrape", f"https://{h}/careers")]
    if not captures:
        return ("nocapture", None, 0, "ATS host not seen in render")
    os.environ["SCRAPE_ASSUME_IL"] = "1"
    from scrape_universal import scrape
    from pipeline.israel import is_israel_job
    foreign = None
    for kind, lu in captures[:3]:
        if kind in ("oraclehcm", "eightfold", "phenom"):
            # a native API candidate: verified through the production fetcher, and the
            # write is gated exactly like every other `cracked-*` verdict in main()
            try:
                n_all, n_il = verify(name, kind, "", lu)
                if n_il or n_all:
                    return ("cracked-api", (kind, lu), n_il, f"{n_all} total")
            except Exception:  # noqa: BLE001
                continue
        else:
            try:
                jobs = scrape(name, lu) or []
            except Exception:  # noqa: BLE001
                jobs = []
            il = [j for j in jobs if is_israel_job(j)]
            if il:
                names_us = _gate.page_names_company(name, lu)
                if names_us is False:
                    # Real Israel roles on a real listings page belonging to SOMEONE ELSE.
                    # This must NOT return `novrfy`: that branch does `fr[3] = got[1]`, i.e.
                    # it writes the proven-foreign URL in as this row's address and stamps
                    # `host documented` - which is a probe_candidates pool token AND
                    # listing_hunt's documented fast-path token. An adversarial review traced
                    # the whole chain: 19:00 crack documents Bancor -> The Bancorp Bank,
                    # 05:00 probe polls it, 19:00 hunt fast-paths it and ACTIVATES, because
                    # `is_foreign` is blind to an ATS subdomain tenant. Same wrong outcome,
                    # 24h later, under another tool's name. `listing_hunt` refuses to persist
                    # a foreign URL for exactly this reason; so do we.
                    foreign = (kind, lu)
                    continue                # try the next capture; don't abandon the company
                if names_us is None:
                    continue                # unreadable: no evidence, try the next capture
                return ("cracked-scrape", ("scrape", lu), len(il), "")
    if foreign:
        # Note-only verdict: the URL is PROVEN to belong to another company, so it is named
        # in the note (which is text) and never written into api_url (which is an address
        # every later tool honestly re-tests, and which listing_hunt's fast-path activates on).
        return ("notours", foreign, 0,
                # FIXED LENGTH and SHORT on purpose: this segment shares a 220-char cell
                # with every other tool's verdict, and `notes.append` evicts whole OLD
                # segments to make room. Measured 2026-08-23 over the 30 `unsupported ATS`
                # parked rows (mean note 199/220): the 74-char first draft pushed
                # `unsupported ATS` out of 24 of them - retiring those rows from
                # crack_walled's OWN pool - a netloc-bearing version cost 17-20 depending on
                # the host's length, and this fixed 49-char form costs 14, which is BETTER
                # than the `novrfy` note it replaces (17). The address is already in column
                # 3; repeating it in the note buys nothing and evicts a pool token.
                "not this company's board")
    # `novrfy` writes `fr[3] = got[1]` and stamps `host documented`, which is a
    # probe_candidates pool token AND listing_hunt's documented fast-path token. Closing that
    # door only for boards that HAPPEN to return Israel jobs left it open on the branch that
    # fires most often - a walled board returning 0 IL is exactly what `host documented,
    # 0 IL now` means, and identity was never tested at all on that path. A live row was
    # already in that state in master: SupPlant (Israeli agri-tech) pointed at
    # careers.workable.com, i.e. Workable's OWN corporate careers site. Test identity before
    # persisting an address, not only before activating one.
    kind0, lu0 = captures[0]
    if _gate.page_names_company(name, lu0) is False:
        return ("notours", captures[0], 0,
                # SHORT on purpose: this segment shares a 220-char cell with every other
                # tool's verdict, and `notes.append` evicts whole OLD segments to make room.
                # The first draft was 74 chars and pushed `unsupported ATS` out of 24 of the
                # 30 crack-pool rows (the old 35-char note loses 17) - i.e. it retired those
                # rows from crack_walled's OWN pool. Measured 2026-08-23; mean note is
                # 199/220 here, so every character is a row's coverage.
                "not this company's board")
    return ("novrfy", captures[0], 0, f"host found ({captures[0][1][:60]}) but 0 IL extracted")


def _recrackable(note, days=1):
    """Re-crack after `days` — DAILY by default: the ATS host is already documented,
    so a re-check is one fetch of a known endpoint, not a rediscovery.
    (Once-ever filters silently freeze
    coverage — same bug class fixed in listing_hunt/_stale_hunt and deep_validate)."""
    m = re.search(r"crack-walled (\d{4}-\d{2}-\d{2})", note or "")
    if not m:
        return True
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days >= days


def main():
    from bd_rescue import _load_secrets
    _load_secrets()
    apply = "--apply" in sys.argv
    limit = int(os.environ.get("CRACK_LIMIT", "0"))
    # These were REFERENCED in the loop below but never defined — every run raised
    # NameError on the first target, behind `continue-on-error` in the workflow, so the
    # walled-ATS crack (Eightfold/Phenom/Avature/iCIMS/Oracle) has never actually run.
    _budget = int(os.environ.get("CRACK_TIME_BUDGET_MIN", "0"))
    _t0 = time.time()
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    # The terminal/recruiter exclusions live in `in_crack_pool` above -- this pool had
    # NO terminal exclusion at all while the cracked branch activates; an `alias-of` twin
    # already scans at the same board, so cracking it re-creates the duplicate the parking
    # exists to remove, and a `domain-dead` host cannot be cracked by anything. Measured
    # 2026-08-23: 5 of the 33 eligible rows were terminal (15% of a 60-minute budget).
    targets = [(i, r) for i, r in enumerate(rows)
               if r and in_crack_pool(r)
               and _recrackable(r[5] or "")]
    # ROTATE: least-recently-cracked first. `_budget` below simply breaks out of the loop,
    # and this tool had no ordering at all, so on any night the budget bit the tail of the
    # list was never reached - "a time budget without rotation is permanent tail blindness",
    # which this lane fixed in `scan_dead_domains` and `probe_candidates` and left standing
    # here. It matters more now that `_is_walled` derives membership from the row's HOST as
    # well as its note, because that is a larger pool.
    def _last_crack(ir):
        m = re.search(r"crack-walled (\d{4}-\d{2}-\d{2})", ir[1][5] or "")
        return m.group(1) if m else ""        # never cracked sorts first
    targets.sort(key=_last_crack)
    if limit:
        targets = targets[:limit]
    print(f"cracking {len(targets)} walled-ATS companies\n", flush=True)
    stats = {}
    for n, (i, r) in enumerate(targets, 1):
        if _budget and (time.time() - _t0) / 60 > _budget:
            print(f"time budget {_budget}min reached — stopping cleanly", flush=True)
            break
        name, platform = r[0], _platform_of(r[5], r[3])
        try:
            verdict, got, n_il, detail = crack_one(name, r[3], platform)
        except Exception as e:  # noqa: BLE001
            verdict, got, n_il, detail = "error", None, 0, str(e)[:60]
        stats[verdict] = stats.get(verdict, 0) + 1
        print(f"  [{'OK' if verdict.startswith('cracked') else '--'}] {n}/{len(targets)} "
              f"{name} ({platform}): {detail or (got[1][:60] if got else '')}"
              f"{f' -> {n_il} IL' if n_il else ''}", flush=True)
        if apply:
            # single-writer discipline: RE-READ the csv before every write — a held snapshot
            # clobbers concurrent edits (lost-update incident 2026-08-22)
            fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
            for fr in fresh:
                if fr and fr[0] == name:
                    _wv = _gate.write_verdict(name, got[1]) if verdict.startswith("cracked") else "ok"
                    if verdict.startswith("cracked") and _wv != "ok":
                        # Identity gate: a cracked page with real Israel roles is still the
                        # WRONG page if it belongs to someone else (FairFly/fireflyspace,
                        # COTI/jobs.citi.com). Document where we looked; do not activate.
                        #
                        # FIXED LENGTH, like its two siblings below. This is the PRIMARY
                        # refusal path - every `cracked-api`/oraclehcm case and every
                        # loose-tenant iCIMS case lands here - and it was left at 101 chars
                        # while the others were cut to 49. Measured over the real 25-row
                        # crack pool (mean note 203/220): the long form evicts another
                        # tool's `unsupported ATS` token from 22 of 25 rows against 13 for
                        # the short one, and one all-refusing night collapses this tool's
                        # own pool from 25 to 3. The URL is already in column 3.
                        # ...and only a PROVEN refusal says so (docs/BACKLOG.md 37): an
                        # unreadable page is `unverified` -- the row keeps its tokens and
                        # tomorrow's crack tries again; the walled host is the pool fact.
                        fr[5] = _note_replace(
                            fr[5], "crack-walled",
                            f"crack-walled {TODAY}: " + ("not this company's board" if _wv == "not-ours"
                                                         else "unverified (page unreadable)"))
                    elif verdict.startswith("cracked"):
                        plat, lu = got
                        fr[1], fr[2], fr[3] = plat, "", lu
                        fr[4] = "true"
                        # Append-log, not a rewrite (ARCHITECTURE.md section 2). Overwriting
                        # the cell on activation deletes every other tool's verdict — and
                        # the terminal tokens that keep a row out of the wrong pool.
                        fr[5] = _note_replace(
                            fr[5], "crack-walled",
                            f"crack-walled {TODAY}: {platform} via {plat}; "
                            f"verified {n_il} IL")
                    elif verdict == "notours":
                        # note only - never fr[3]. See crack_one's comment.
                        fr[5] = _note_replace(fr[5], "crack-walled",
                                              f"crack-walled {TODAY}: {detail}")
                    elif verdict == "novrfy" and got:
                        # Gate the WRITE, not the return. `crack_one` has four `cracked`/
                        # `novrfy` exits and gating them one by one is how the 0-IL paths
                        # were missed twice: `cracked-api` (oraclehcm) returns on
                        # `if n_il or n_all` and never consulted the identity gate at all,
                        # so a row could be ACTIVATED with zero verified Israel jobs and a
                        # note reading "verified 0 IL"; and `novrfy` persisted the address
                        # whenever the page was merely UNREADABLE. Both are re-checked below
                        # by `_ok_to_write`, which no future `return` can bypass.
                        _wv = _gate.write_verdict(name, got[1])
                        if _wv == "ok":
                            fr[3] = got[1]
                            fr[5] = _note_replace(
                                fr[5], "crack-walled",
                                f"crack-walled {TODAY}: host documented, 0 IL now")
                        else:
                            fr[5] = _note_replace(
                                fr[5], "crack-walled",
                                f"crack-walled {TODAY}: " + ("not this company's board" if _wv == "not-ours"
                                                             else "unverified (page unreadable)"))
                    else:
                        fr[5] = _note_replace(fr[5], "crack-walled",
                                              f"crack-walled {TODAY}: {verdict}")
            write_csv_rows("companies.csv", fresh)
        time.sleep(0.3)
    print(f"\n=== crack-walled: {stats} ===", flush=True)


if __name__ == "__main__":
    main()
