#!/usr/bin/env python3
"""Re-verify every inactive 'scanned/empty/unreachable' company row.

Those verdicts are unreliable: entry URLs were often aggregator/secrethunter job links or
JS-rendered careers pages that look blank to a plain scrape (Glassbox: verdict said
'no open Israel roles' while its Greenhouse board had plenty). This audits each parked row
the way a human does: SerpApi-find the real careers page, grep the RAW HTML for ATS embed
signatures (embeds live in the HTML even when the visible page is JS-rendered), construct
the platform endpoint, and verify it through pipeline.fetchers before touching the row.
Only endpoint-verified boards get reactivated; everything else keeps its parked note.

Usage: python audit_empty_rows.py [--apply]   (default is dry-run report)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from bd_rescue import _load_secrets
from pipeline.fetchers import fetch_company
from pipeline.israel import is_israel_job

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
AGG = ("linkedin.", "indeed.", "glassdoor.", "secrethunter.", "t.me")

# signature -> (platform, api_url template)
SIGS = [
    (re.compile(r"greenhouse\.io/embed/job_board/js\?for=([a-z0-9_-]+)", re.I),
     "greenhouse", "https://boards-api.greenhouse.io/v1/boards/{}/jobs"),
    (re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I),
     "greenhouse", "https://boards-api.greenhouse.io/v1/boards/{}/jobs"),
    (re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", re.I),
     "lever", "https://api.lever.co/v0/postings/{}?mode=json"),
    (re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)", re.I),
     "ashby", "https://api.ashbyhq.com/posting-api/job-board/{}"),
    (re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I),
     "recruitee", "https://{}.recruitee.com/api/offers/"),
    (re.compile(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9-]+)", re.I),
     "workable", "https://apply.workable.com/api/v1/widget/accounts/{}?details=true"),
    (re.compile(r"careers\.smartrecruiters\.com/([A-Za-z0-9]+)", re.I),
     "smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{}/postings"),
    (re.compile(r"([a-z0-9-]+)\.breezy\.hr", re.I),
     "breezy", "https://{}.breezy.hr/json"),
    (re.compile(r"([a-z0-9]+)\.bamboohr\.com", re.I),
     "bamboohr", "https://{}.bamboohr.com/careers/list"),
]
_WD = re.compile(r"https?://([a-z0-9]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_]+)")
_COMEET = re.compile(r"comeet", re.I)
_UNSUPPORTED = re.compile(r"(eightfold\.ai|avature\.net|oraclecloud\.com|jobvite\.com|phenom)", re.I)


def _slug_matches(name, token):
    """The slug/tenant must share a word with the company name — rejects boards that belong
    to a different company found on the same page. Comeet uids (e.g. '7A.008') are opaque
    and come from a comeetvar read on the company's own page, so they pass."""
    t = re.sub(r"[^a-z0-9]", "", str(token).lower())
    if re.fullmatch(r"[0-9A-F]{2}\.[0-9A-F]{3}", str(token)):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) >= 3]
    joined = "".join(re.findall(r"[a-z0-9]+", name.lower()))
    return any(w in t for w in words) or (len(t) >= 4 and t in joined) or joined.startswith(t[:5])


def fetch(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(1_500_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


_SERP = {"left": None}


def _serp_budget_ok():
    """Never drain the whole SerpApi month on an audit: keep SERP_RESERVE (default 50)
    searches for the daily discovery/LLM-resolver paths."""
    reserve = int(os.environ.get("SERP_RESERVE", "50"))
    if _SERP["left"] is None:
        key = os.environ.get("SERPAPI_KEY", "")
        try:
            with urllib.request.urlopen(f"https://serpapi.com/account?api_key={key}",
                                        timeout=20) as r:
                _SERP["left"] = int(json.load(r).get("total_searches_left") or 0)
        except Exception:  # noqa: BLE001
            _SERP["left"] = 0
        print(f"(serpapi budget: {_SERP['left']} left, reserving {reserve})", flush=True)
    return _SERP["left"] > reserve


def serp(name, limit=5):
    key = os.environ.get("SERPAPI_KEY")
    if not key or not _serp_budget_ok():
        return []
    _SERP["left"] -= 1
    q = urllib.parse.urlencode({"engine": "google", "q": f'"{name}" careers', "num": "10",
                                "api_key": key})
    try:
        with urllib.request.urlopen(f"https://serpapi.com/search.json?{q}", timeout=30) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    urls = [o.get("link", "") for o in data.get("organic_results", [])]
    return [u for u in urls if u and not any(a in u.lower() for a in AGG)][:limit]


def propose_from_html(html):
    for rx, plat, tmpl in SIGS:
        m = rx.search(html)
        if m:
            return plat, m.group(1), tmpl.format(m.group(1))
    m = _WD.search(html)
    if m:
        tenant, wd, site = m.groups()
        return ("workday", f"{tenant}/{site}",
                f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs")
    return None


def verify(name, plat, tok, api):
    jobs = fetch_company({"company_name": name, "ats_platform": plat,
                          "token": tok, "api_url": api})
    return len(jobs), sum(1 for j in jobs if is_israel_job(j))


def comeet_try(name, page_url):
    try:
        from comeet_resolve import resolve as cr
        r = cr(page_url)
        if r:
            api, uid, _ = r
            return "comeet", uid, api
    except Exception:  # noqa: BLE001
        pass
    return None


def main():
    _load_secrets()
    apply = "--apply" in sys.argv
    os.makedirs("state", exist_ok=True)
    done_path = "state/audit_done.json"
    try:
        done = set(json.load(open(done_path, encoding="utf-8")))
    except Exception:  # noqa: BLE001
        done = set()
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    parked = [(i, r) for i, r in enumerate(rows)
              if r and len(r) >= 6 and r[4] == "false" and r[0] not in done
              and re.search(r"scanned; no open|unreachable; could not|aggregator URL", r[5] or "")]
    print(f"{len(parked)} parked rows to audit ({len(done)} already done); "
          f"SerpApi spent only when needed\n", flush=True)
    def _mark(name):
        done.add(name)
        json.dump(sorted(done), open(done_path, "w", encoding="utf-8"))

    fixed, unsupported, still = [], [], []
    for i, r in parked:
        name, url = r[0], r[3]
        _mark(name)
        # direct careers URL first; SerpApi only as fallback (723-row backlog vs 250/mo budget)
        direct = [] if any(a in (url or "").lower() for a in AGG) else [url]
        got, unsup, used_serp = None, "", False
        for phase in (direct, None):
            cands = phase if phase is not None else [u for u in serp(name) if u not in direct]
            used_serp = used_serp or phase is None
            for u in cands[:3]:
                html = fetch(u, timeout=12)
                if not html:
                    continue
                got = propose_from_html(html)
                if got and not _slug_matches(name, got[1]):
                    # signature belongs to some OTHER company on the page (serp noise like
                    # CyberArk->PANW). Never accept a mismatched slug/tenant.
                    print(f"  [!=] {name}: rejected foreign slug {got[0]}:{got[1]}", flush=True)
                    got = None
                if got:
                    break
                if _UNSUPPORTED.search(html):
                    unsup = _UNSUPPORTED.search(html).group(1)
                if _COMEET.search(html):
                    got = comeet_try(name, u)
                    if got:
                        break
            if got:
                break
        time.sleep(1 if used_serp else 0.2)
        if not got:
            (unsupported if unsup else still).append((name, unsup))
            print(f"  [--] {name}: {'unsupported ATS ' + unsup if unsup else 'no signature found'}",
                  flush=True)
            continue
        plat, tok, api = got
        try:
            n_all, n_il = verify(name, plat, tok, api)
        except Exception as e:  # noqa: BLE001
            still.append((name, ""))
            print(f"  [xx] {name}: {plat}:{tok} found but verify failed: {str(e)[:60]}", flush=True)
            continue
        fixed.append((name, plat, n_all, n_il))
        print(f"  [OK] {name}: {plat} {tok} -> {n_all} jobs / {n_il} IL", flush=True)
        if apply:
            rows[i][1], rows[i][2], rows[i][3] = plat, tok, api
            rows[i][4] = "true"
            rows[i][5] = f"re-audit {__import__('datetime').date.today()}: verified {n_all}/{n_il} IL (was false-empty)"
            # write incrementally so a killed run never loses verified fixes
            csv.writer(open("companies.csv", "w", encoding="utf-8", newline="")).writerows(rows)
    print(f"\n=== recovered {len(fixed)} boards · unsupported-ATS {len(unsupported)} · "
          f"still dark {len(still)} ===")


if __name__ == "__main__":
    main()
