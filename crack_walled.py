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
import sys
import time
import urllib.parse

from deep_validate import Renderer, ddg
from audit_empty_rows import AGG, verify
from pipeline.aggregators import is_aggregator
from pipeline.atomic import write_csv_rows

TODAY = dt.date.today().isoformat()

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


def _platform_of(note):
    m = re.search(r"unsupported ATS ([A-Za-z.]+)", note or "")
    if not m:
        return None
    p = m.group(1).lower()
    return {"eightfold.ai": "eightfold", "phenom": "phenom", "icims.com": "icims",
            "successfactors": "successfactors", "oraclecloud.com": "oraclecloud",
            "avature.net": "avature", "jobvite.com": "jobvite", "taleo.net": "taleo"}.get(p, p)


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
        return [("scrape", f"https://{host}/careers?location=Israel"),
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
        # canonical guess from the company's own domain; verification gates correctness
        d = urllib.parse.urlparse(cands[0]).netloc.replace("www.", "")
        base = ".".join(d.split(".")[-2:])
        captures = [("scrape", f"https://careers.{base}/careers?location=Israel"),
                    ("scrape", f"https://careers.{base}/careers")]
    if not captures:
        return ("nocapture", None, 0, "ATS host not seen in render")
    os.environ["SCRAPE_ASSUME_IL"] = "1"
    from scrape_universal import scrape
    from pipeline.israel import is_israel_job
    for kind, lu in captures[:3]:
        if kind == "oraclehcm":
            try:
                n_all, n_il = verify(name, "oraclehcm", "", lu)
                if n_il or n_all:
                    return ("cracked-api", ("oraclehcm", lu), n_il, f"{n_all} total")
            except Exception:  # noqa: BLE001
                continue
        else:
            try:
                jobs = scrape(name, lu) or []
            except Exception:  # noqa: BLE001
                jobs = []
            il = [j for j in jobs if is_israel_job(j)]
            if il:
                return ("cracked-scrape", ("scrape", lu), len(il), "")
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
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false" and "unsupported ATS" in (r[5] or "")
               and _recrackable(r[5] or "")]
    if limit:
        targets = targets[:limit]
    print(f"cracking {len(targets)} walled-ATS companies\n", flush=True)
    stats = {}
    for n, (i, r) in enumerate(targets, 1):
        if _budget and (time.time() - _t0) / 60 > _budget:
            print(f"time budget {_budget}min reached — stopping cleanly", flush=True)
            break
        name, platform = r[0], _platform_of(r[5])
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
                    if verdict.startswith("cracked"):
                        plat, lu = got
                        fr[1], fr[2], fr[3] = plat, "", lu
                        fr[4] = "true"
                        fr[5] = f"crack-walled {TODAY}: {platform} via {plat}; verified {n_il} IL"
                    elif verdict == "novrfy" and got:
                        fr[3] = got[1]
                        fr[5] = (re.sub(r"\s\|\s?crack-walled [^|]*", "", fr[5])
                                 + f" | crack-walled {TODAY}: host documented, 0 IL now")[:220]
                    else:
                        fr[5] = (re.sub(r"\s\|\s?crack-walled [^|]*", "", fr[5])
                                 + f" | crack-walled {TODAY}: {verdict}")[:220]
            write_csv_rows("companies.csv", fresh)
        time.sleep(0.3)
    print(f"\n=== crack-walled: {stats} ===", flush=True)


if __name__ == "__main__":
    main()
