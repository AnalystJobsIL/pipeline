#!/usr/bin/env python3
"""Deep resolver for the edge cases a plain scrape misses. Per company, in order:

  1. Render the careers page and watch EVERY network request + iframe src for a known ATS
     (greenhouse/lever/ashby/smartrecruiters/recruitee/workable/workday/comeet). If found,
     resolve it through its real API (clean data) — this catches iframe-embedded boards.
  2. Universal scrape (JSON + DOM) of the careers page.
  3. If still nothing, find a "jobs / open positions / openings" link on the page, follow it once,
     and scrape THAT page.

Emits `scrape` cache entries + CSV rows (for 2/3) or a native-ATS CSV row (for 1). Shardable.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

from pipeline import fetchers, israel
from pipeline.companies import load_companies
from scrape_universal import ISRAEL_LOC, ROLE, scrape

ATS_PATTERNS = [
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/?]+)"),
     lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs"),
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([^/?&]+)"),
     lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs"),
    ("lever", re.compile(r"(?:api|jobs)\.(?:eu\.)?lever\.co/(?:v0/postings/)?([^/?]+)"),
     lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json"),
    ("ashby", re.compile(r"(?:api|jobs)\.ashbyhq\.com/(?:posting-api/job-board/)?([^/?#]+)"),
     lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}"),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com/(?:v1/companies/)?([^/?]+)"),
     lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings"),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com"),
     lambda s: f"https://{s}.recruitee.com/api/offers/"),
    ("workable", re.compile(r"(?:apply\.)?workable\.com/(?:api/[^/]+/(?:widget/)?accounts/)?([^/?]+)"),
     lambda s: f"https://apply.workable.com/api/v1/widget/accounts/{s}?details=true"),
]
NAV_SKIP = re.compile(r"ashbyhq|greenhouse|lever|workable|smartrecruiters|recruitee|comeet", re.I)
JOBS_LINK = re.compile(r"(open\s*positions|open\s*roles|view\s*(all\s*)?jobs|see\s*(all\s*)?"
                       r"(open\s*)?(positions|roles|jobs)|current\s*openings|join\s*(us|the\s*team)|"
                       r"we'?re\s*hiring|all\s*jobs|browse\s*jobs|explore\s*(jobs|roles|opportunities))", re.I)


def _capture(url, timeout_ms=35000):
    """Render; return (set of ATS request/iframe urls, comeetvar cfg, list of candidate jobs-links)."""
    from playwright.sync_api import sync_playwright
    urls, links = [], []
    comeet = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        pg.on("request", lambda r: urls.append(r.url))
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            pg.wait_for_timeout(4500)
            pg.mouse.wheel(0, 2500)
            pg.wait_for_timeout(2500)
            for fr in pg.frames:                              # iframe srcs
                if fr.url and fr.url != "about:blank":
                    urls.append(fr.url)
            cfg = pg.evaluate("()=>window.comeetvar?{u:window.comeetvar.comeet_uid,"
                              "t:window.comeetvar.comeet_token}:null")
            if cfg:
                comeet = cfg
            links = pg.evaluate("""()=>[...document.querySelectorAll('a[href]')].map(a=>({t:(a.textContent||'').trim(),h:a.href})).slice(0,300)""")
        except Exception:
            pass
        finally:
            b.close()
    return urls, comeet, links


def _detect_ats(urls, comeet):
    if comeet.get("u") and comeet.get("t"):
        return ("comeet", comeet["u"],
                f"https://www.comeet.com/careers-api/2.0/company/{comeet['u']}/positions?token={comeet['t']}")
    for u in urls:
        m = re.search(r"([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/wday/cxs/([^/]+)/([^/]+)/", u)
        if m:
            return ("workday", f"{m.group(1)}/{m.group(4)}",
                    f"https://{m.group(1)}.wd{m.group(2)}.myworkdayjobs.com/wday/cxs/"
                    f"{m.group(3)}/{m.group(4)}/jobs")
    for plat, rx, build in ATS_PATTERNS:
        for u in urls:
            m = rx.search(u)
            if m and m.group(1) not in ("www", "api", "jobs", "boards", "job-boards", "apply"):
                return (plat, m.group(1), build(m.group(1)))
    return None


def _verify(name, plat, tok, api):
    row = {"company_name": name, "ats_platform": plat, "token": tok, "api_url": api}
    try:
        jobs = fetchers.fetch_company(row)
    except Exception:  # noqa: BLE001
        return None
    il = sum(1 for j in jobs if israel.is_israel_job(j))
    return (len(jobs), il) if jobs else None


def resolve(name, careers_url):
    """Return ('ats', row_tuple) | ('scrape', jobs) | ('empty', None) | ('unreachable', None).

    'empty'       = the careers page loaded and parsed, but has no open Israel role right now
                    (a validated scan — NOT a failure).
    'unreachable' = the page failed to load / returned nothing to parse (the only real gap).
    """
    urls, comeet, links = _capture(careers_url)
    reachable = len(links) > 3 or len(urls) > 8
    det = _detect_ats(urls, comeet)
    if det:
        plat, tok, api = det
        v = _verify(name, plat, tok, api)
        if v and v[0]:
            return ("ats", (name, plat, tok, api, v[0], v[1]))
        reachable = True                     # a real ATS board (even if 0 Israel) = reached
    jobs = scrape(name, careers_url)
    if jobs:
        reachable = True
    il = [j for j in jobs if israel.is_israel_job(j)]
    if il:
        return ("scrape", il)
    for l in links:                          # follow a "view jobs / open positions" link once
        t, h = l.get("t", ""), l.get("h", "")
        if h and JOBS_LINK.search(t) and not NAV_SKIP.search(h) and h.rstrip("/") != careers_url.rstrip("/"):
            try:
                jobs = scrape(name, h)
            except Exception:  # noqa: BLE001
                jobs = []
            if jobs:
                reachable = True
            il = [j for j in jobs if israel.is_israel_job(j)]
            if il:
                return ("scrape", (il, h))              # keep the followed URL that worked
            break
    return ("empty", None) if reachable else ("unreachable", None)


def main():
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have]
    if "--shard" in sys.argv:
        i, n = int(sys.argv[sys.argv.index("--shard") + 1]), int(sys.argv[sys.argv.index("--shard") + 2])
        todo = todo[i::n]
    cache_out = os.environ.get("SCRAPE_CACHE_OUT", "out/deep_cache.json")
    csv_out = os.environ.get("SCRAPE_CSV_OUT", "out/deep_rows.csv")
    cache = {}
    n_res = n_empty = n_unreach = 0
    for e in todo:
        name, url = e["name"].strip(), e["careers_url"]
        try:
            r = resolve(name, url)
        except Exception:  # noqa: BLE001
            r = ("unreachable", None)
        kind = r[0]
        if kind == "ats":
            nm, plat, tok, api, n_all, il = r[1]
            row = [nm, plat, tok, api, "true", f"deep-resolved; {n_all}/{il} IL"]
            n_res += 1
            print(f"  [ATS] {name}: {plat} ({il} IL)", flush=True)
        elif kind == "scrape":
            cache[name] = r[1]
            row = [name, "scrape", url, url, "true", f"deep-scrape; {len(r[1])} Israel jobs"]
            n_res += 1
            print(f"  [SCR] {name}: {len(r[1])} IL", flush=True)
        elif kind == "empty":
            row = [name, "scrape", url, url, "false", "scanned; no open Israel roles now"]
            n_empty += 1
        else:
            row = [name, "scrape", url, url, "false", "unreachable; could not scan"]
            n_unreach += 1
        with open(csv_out, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
    with open(cache_out, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"=== resolved {n_res}, empty {n_empty}, unreachable {n_unreach} ===", flush=True)


if __name__ == "__main__":
    main()
