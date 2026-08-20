#!/usr/bin/env python3
"""Re-resolve companies whose ATS config went stale.

A company set to `scrape` while its URL points at a real ATS (Workday/Greenhouse/Ashby/
Lever/Recruitee), or an ATS entry that now 404s / returns 0, is a config that rotted (the
tenant moved, the board slug changed, the site was never resolved). For each such company we
render the careers page, watch the network for the REAL ATS API call (e.g. Workday's
/wday/cxs/<tenant>/<site>/jobs), verify it returns jobs, and record the corrected config.

Writes out/resolved_configs.json: {company_name: [platform, token, api_url, n, il]} for the
ones that now work. `apply_resolved.py` merges those into companies.csv. Also used by the
weekly self-heal workflow to keep coverage from silently rotting.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import re
import sys

from pipeline import fetchers, israel
from resolve_deep import _capture, _detect_ats

ATS_HOST = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
                      r"comeet\.co|workable\.com|recruitee\.com|myworkdayjobs", re.I)

# ATS endpoints discoverable straight from a page's HTML/JS (used on the Bright Data path,
# for anti-bot sites like Workday where a headless browser gets a maintenance page).
_HTML_ATS = [
    ("workday", re.compile(r"([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/wday/cxs/([^/\"]+)/([^/\"]+)/"),
     lambda m: (f"{m.group(3)}/{m.group(4)}",
                f"https://{m.group(1)}.wd{m.group(2)}.myworkdayjobs.com/wday/cxs/{m.group(3)}/{m.group(4)}/jobs")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([^/\"?]+)"),
     lambda m: (m.group(1), f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs")),
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([^/\"?&]+)"),
     lambda m: (m.group(1), f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs")),
    ("lever", re.compile(r"(?:api|jobs)\.lever\.co/(?:v0/postings/)?([^/\"?]+)"),
     lambda m: (m.group(1), f"https://api.lever.co/v0/postings/{m.group(1)}?mode=json")),
    ("ashby", re.compile(r"(?:api|jobs)\.ashbyhq\.com/(?:posting-api/job-board/)?([^/\"?#]+)"),
     lambda m: (m.group(1), f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")),
]


def _resolve_via_bd(name, careers_url):
    """Anti-bot fallback: fetch the careers page through the Bright Data unlocker (residential
    IP) and read the real ATS endpoint out of the returned HTML/JS. Returns (plat,tok,api) or None."""
    try:
        import bd_rescue
        bd_rescue._load_secrets()
        if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE")):
            return None
        html = bd_rescue.unlock(careers_url)
    except Exception:  # noqa: BLE001
        return None
    if not html or "myworkdayjobs.com/wday/cxs" not in html and "greenhouse" not in html \
            and "lever.co" not in html and "ashbyhq" not in html:
        return None
    for plat, rx, build in _HTML_ATS:
        m = rx.search(html)
        if m:
            tok, api = build(m)
            if tok not in ("www", "api", "jobs", "boards", "embed"):
                return (plat, tok, api)
    return None


def _public_url(platform, token, api_url):
    """Best careers URL to render for capture."""
    if api_url and api_url.startswith("http"):
        # a cxs api_url isn't renderable; fall back to the public host root
        m = re.match(r"(https://[^/]+\.myworkdayjobs\.com)/wday/cxs/[^/]+/([^/]+)/", api_url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
        return api_url
    return api_url


def _works(name, plat, tok, api):
    try:
        jobs = fetchers.fetch_company({"company_name": name, "ats_platform": plat,
                                       "token": tok, "api_url": api})
    except Exception:  # noqa: BLE001
        return None
    il = sum(1 for j in jobs if israel.is_israel_job(j))
    return (len(jobs), il) if jobs else None


def _careers_url_via_serp(name):
    """Find a company's real careers page via a SerpApi Google search — needed when what we
    stored is a dead ATS *API* URL (comeet/ashby endpoint), not a renderable careers page."""
    key = os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI_API_KEY")
    if not key:
        return None
    from urllib.parse import quote
    from pipeline import http
    try:
        d = http.get_json(f"https://serpapi.com/search?engine=google&num=6&gl=il&"
                          f"q={quote(name + ' careers israel')}&api_key={key}")
    except Exception:  # noqa: BLE001
        return None
    ats = re.compile(r"greenhouse|lever\.co|ashbyhq|comeet|myworkdayjobs|recruitee|workable|"
                     r"smartrecruiters|career|/jobs", re.I)
    for r in (d.get("organic_results") or []):
        link = r.get("link", "")
        if link and ats.search(link):
            return link
    return None


def resolve_one(name, careers_url):
    """Resolve the real ATS endpoint via a ladder: headless network-capture of the stored URL,
    then the Bright Data unlocker (anti-bot), then find the real careers page via SerpApi and
    capture THAT (for stored URLs that are dead API endpoints, not pages). (plat,tok,api,n,il)|None."""
    def _try(u):
        try:
            urls, comeet, links = _capture(u)
            d = _detect_ats(urls, comeet)
        except Exception:  # noqa: BLE001
            d = None
        return d or _resolve_via_bd(name, u)

    det = _try(careers_url)
    if not det:                                    # stored URL was a dead API / blocked -> find
        page = _careers_url_via_serp(name)         # the real careers page and capture that
        if page and page.rstrip("/") != (careers_url or "").rstrip("/"):
            det = _try(page)
    if not det:
        return None
    plat, tok, api = det
    v = _works(name, plat, tok, api)               # a resolved Workday API may itself be IP-blocked;
    if not v and plat == "workday":                # skip (fetcher would need a BD-routed mode)
        return None
    return (plat, tok, api, v[0], v[1]) if v else None


def candidates():
    """Rows to (re)resolve. Prefer the health module's stale list (error/regressed/misconfig/
    empty-board); fall back to scanning companies.csv for scrape-on-a-real-ATS-host."""
    for stale_path in ("cloud_state/stale.json", "out/stale.json"):
        if os.path.exists(stale_path):
            try:
                stale = json.load(open(stale_path, encoding="utf-8"))
                return [(name, _public_url(v.get("platform", ""), "", v.get("careers_url", "")))
                        for name, v in stale.items() if v.get("careers_url")]
            except ValueError:
                pass
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    out = []
    for r in rows[1:]:
        if len(r) < 4:
            continue
        name, plat, tok, api = r[0], r[1], r[2], r[3]
        if plat.strip() == "scrape" and ATS_HOST.search(api or ""):
            out.append((name, _public_url(plat, tok, api)))
    return out


# attempt log — so we don't re-render + BD-hit a permanently-broken board (anti-bot Workday)
# every single day. A failing company is retried at most weekly, then left to discovery.
ATTEMPTS = "cloud_state/resolve_attempts.json"


def _skip(name, attempts, retry_days=7, give_up_after=5):
    a = attempts.get(name)
    if not a:
        return False
    if a.get("fails", 0) >= give_up_after:
        return True                                # abandoned — discovery covers it
    last = a.get("last", "")
    try:
        gap = (_dt.date.today() - _dt.date.fromisoformat(last)).days
        return gap < retry_days                    # tried recently — wait
    except (ValueError, TypeError):
        return False


def main():
    try:                                           # load SERPAPI_KEY + BRIGHTDATA_* from secrets.env
        import bd_rescue
        bd_rescue._load_secrets()
    except Exception:  # noqa: BLE001
        pass
    todo = candidates()
    if "--only" in sys.argv:                       # --only "Dell,Qualcomm" for a focused run
        names = {n.strip().lower() for n in sys.argv[sys.argv.index("--only") + 1].split(",")}
        todo = [(n, u) for n, u in todo if n.lower() in names]
    if "--shard" in sys.argv:
        i, n = int(sys.argv[sys.argv.index("--shard") + 1]), int(sys.argv[sys.argv.index("--shard") + 2])
        todo = todo[i::n]
    attempts = {}
    if os.path.exists(ATTEMPTS):
        try:
            attempts = json.load(open(ATTEMPTS, encoding="utf-8"))
        except ValueError:
            attempts = {}
    force = "--force" in sys.argv or "--only" in sys.argv
    pending = [(n, u) for n, u in todo if force or not _skip(n, attempts)]
    print(f"{len(todo)} stale · resolving {len(pending)} this run "
          f"({len(todo) - len(pending)} throttled/abandoned)", flush=True)
    resolved = {}
    today = _dt.date.today().isoformat()
    for name, url in pending:
        r = resolve_one(name, url)
        if r:
            resolved[name] = list(r)
            attempts.pop(name, None)               # fixed — clear its attempt record
            print(f"  [OK]   {name[:24]:25} {r[0]:11} {r[3]:>4} jobs / {r[4]:>3} IL", flush=True)
        else:
            a = attempts.setdefault(name, {"fails": 0})
            a["fails"] = a.get("fails", 0) + 1
            a["last"] = today
            print(f"  [fail] {name[:24]:25} attempt {a['fails']} — no working ATS", flush=True)
    try:
        json.dump(attempts, open(ATTEMPTS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass
    os.makedirs("out", exist_ok=True)
    out = os.environ.get("RESOLVED_OUT", "out/resolved_configs.json")
    prev = {}
    if os.path.exists(out):
        try:
            prev = json.load(open(out, encoding="utf-8"))
        except ValueError:
            prev = {}
    prev.update(resolved)
    json.dump(prev, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"=== resolved {len(resolved)} this run; {len(prev)} total in {out} ===", flush=True)


if __name__ == "__main__":
    main()
