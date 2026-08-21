#!/usr/bin/env python3
"""LLM fallback tier for ATS resolution (needs the claude CLI; cloud runs authenticate it
with the CLAUDE_CODE_OAUTH_TOKEN subscription secret).

When resolve_deep's deterministic heuristics give up — or land on an aggregator page the
auto-expand guard refuses to scrape — this tier does what a human resolver does: find the
company's real careers page (SerpApi web search when the input URL is an aggregator link),
read the evidence (iframes / scripts / links / ATS-domain strings), let Claude name the
platform and construct the public JSON endpoint, then VERIFY by actually fetching jobs
through pipeline.fetchers. A proposal that doesn't fetch real jobs is discarded — a
hallucinated endpoint can never become an active row. One shot per attempt (evidence in,
strict JSON out), one retry carrying the verification error.

CLI test:  python resolve_llm.py "Company Name" "https://careers.example.com"
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from pipeline.fetchers import FETCHERS, fetch_company
from pipeline.israel import is_israel_job

AGGREGATORS = ("linkedin.", "indeed.", "glassdoor.")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# high-signal strings worth surfacing verbatim to the model
_ATS_HINT = re.compile(
    r"https?://[^\s\"'<>]*?("
    r"comeet\.com|greenhouse\.io|lever\.co|smartrecruiters\.com|recruitee\.com|"
    r"ashbyhq\.com|myworkdayjobs\.com|jazzhr\.com|applytojob\.com|workable\.com|"
    r"breezy\.hr|bamboohr\.com|eightfold\.ai|avature\.net|oraclecloud\.com|jobvite\.com|"
    r"careers-page|jobs?\.[a-z0-9-]+\.[a-z]{2,}"
    r")[^\s\"'<>]*", re.I)

_PROMPT = """You resolve which ATS (applicant tracking system) hosts a company's job board, and
construct its PUBLIC JSON API endpoint from evidence scraped off its careers page(s).

Known endpoint patterns (platform -> api_url):
- comeet: https://www.comeet.com/careers-api/2.0/company/{{uid}}/positions?token={{token}}
  (uid like "7A.00A"; the long hex token is embedded in the careers page JS — only output
  comeet api_url if BOTH appear in the evidence; else platform "comeet" with api_url "")
- greenhouse: https://boards-api.greenhouse.io/v1/boards/{{slug}}/jobs
- lever: https://api.lever.co/v0/postings/{{slug}}?mode=json  (or api.eu.lever.co)
- smartrecruiters: https://api.smartrecruiters.com/v1/companies/{{slug}}/postings
- recruitee: https://{{slug}}.recruitee.com/api/offers/
- ashby: https://api.ashbyhq.com/posting-api/job-board/{{slug}}
- workday: https://{{tenant}}.wd{{N}}.myworkdayjobs.com/wday/cxs/{{tenant}}/{{site}}/jobs
  (POST endpoint; tenant, wdN and site all appear inside myworkdayjobs.com URLs in evidence)
- workable: https://apply.workable.com/api/v1/widget/accounts/{{slug}}?details=true
- breezy: https://{{slug}}.breezy.hr/json
- bamboohr: https://{{slug}}.bamboohr.com/careers/list

Company: {name}
Evidence:
{evidence}
{feedback}
Respond with ONLY one JSON object, no prose:
{{"platform": "<comeet|greenhouse|lever|smartrecruiters|recruitee|ashby|workday|workable|breezy|bamboohr|unknown>",
 "token": "<the slug/uid/tenant-site token for that platform, or empty>",
 "api_url": "<the exact endpoint URL, or empty>",
 "careers_url": "<the company's real careers page found in evidence, or empty>",
 "reason": "<one short sentence>"}}
Use platform "unknown" when the evidence is insufficient — do NOT invent slugs or tenants
that don't appear in the evidence."""


def _fetch_html(url, timeout=25, cap=300_000):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.geturl(), r.read(cap).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return url, ""


def _is_aggregator(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return any(a in host for a in AGGREGATORS)


def _serp_candidates(name, limit=5):
    """Real careers-page candidates via SerpApi general web search (key optional)."""
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"engine": "google", "q": f'"{name}" careers jobs',
                                "num": "10", "api_key": key})
    try:
        with urllib.request.urlopen(f"https://serpapi.com/search.json?{q}", timeout=30) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    urls = [o.get("link", "") for o in data.get("organic_results", [])]
    return [u for u in urls if u and not _is_aggregator(u)][:limit]


def _extract_evidence(html):
    out = []
    for pat, label in ((r'<iframe[^>]+src=["\']([^"\']+)', "iframe"),
                       (r'<script[^>]+src=["\']([^"\']+)', "script"),
                       (r'<a[^>]+href=["\']([^"\']+)', "link")):
        for m in re.findall(pat, html, re.I)[:80]:
            if label == "link" and not re.search(r"career|job|position|join|talent", m, re.I) \
                    and not _ATS_HINT.search(m):
                continue
            out.append(f"{label}: {m}")
    out += [f"ats-url: {m.group(0)}" for m in _ATS_HINT.finditer(html)]
    # dedupe preserving order; keep the evidence bundle small
    seen, uniq = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            uniq.append(line)
    return uniq[:60]


def _gather(name, url):
    lines = []
    candidates = []
    if url and not _is_aggregator(url):
        candidates.append(url)
    candidates += [u for u in _serp_candidates(name) if u not in candidates]
    for u in candidates[:3]:
        final, html = _fetch_html(u)
        if not html:
            lines.append(f"page: {u} -> unreachable")
            continue
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        lines.append(f"page: {u} (final: {final}) title: "
                     f"{(title.group(1).strip()[:120] if title else '?')}")
        lines += _extract_evidence(html)
    return "\n".join(lines) if lines else "(no pages reachable)"


def _ask_claude(prompt, timeout=120):
    if not shutil.which("claude"):
        return None
    try:
        proc = subprocess.run(["claude", "-p"], input=prompt, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, shell=(os.name == "nt"))
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"\{.*\}", proc.stdout or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def _verify(name, platform, token, api_url):
    """Fetch through the production fetcher; returns (n_all, n_il) or raises."""
    if platform not in FETCHERS or platform in ("scrape", "discovery"):
        raise ValueError(f"unsupported platform {platform!r}")
    if not api_url.startswith("http") or _is_aggregator(api_url):
        raise ValueError("bad api_url")
    jobs = fetch_company({"company_name": name, "ats_platform": platform,
                          "token": token, "api_url": api_url})
    if not jobs:
        raise ValueError("endpoint returned 0 jobs")
    return len(jobs), sum(1 for j in jobs if is_israel_job(j))


def _try_comeet_via_page(name, careers_url):
    """Comeet tokens are page-embedded; reuse the Playwright comeetvar reader."""
    try:
        from comeet_resolve import resolve as comeet_page_resolve
        r = comeet_page_resolve(careers_url)
    except Exception:  # noqa: BLE001
        return None
    if not r:
        return None
    api_url, uid, _tok = r
    return ("comeet", uid, api_url)


def resolve_llm(name, url):
    """Full fallback attempt. Returns ('ats', (name, platform, token, api_url, n_all, n_il))
    or None. Never raises."""
    try:
        evidence = _gather(name, url)
        feedback = ""
        for _attempt in range(2):
            p = _ask_claude(_PROMPT.format(name=name, evidence=evidence[:8000],
                                           feedback=feedback))
            if not p or p.get("platform") in (None, "", "unknown"):
                return None
            plat = str(p.get("platform", "")).lower().strip()
            tok = str(p.get("token", "")).strip()
            api = str(p.get("api_url", "")).strip()
            if plat == "comeet" and not api and p.get("careers_url"):
                got = _try_comeet_via_page(name, p["careers_url"])
                if got:
                    plat, tok, api = got[0], got[1], got[2]
            try:
                n_all, n_il = _verify(name, plat, tok, api)
                return ("ats", (name, plat, tok, api, n_all, n_il))
            except Exception as e:  # noqa: BLE001
                feedback = (f"\nA previous attempt proposed platform={plat!r} "
                            f"api_url={api!r} and verification FAILED: {e}. "
                            f"Propose a different endpoint or answer unknown.\n")
        return None
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    import sys
    nm = sys.argv[1] if len(sys.argv) > 1 else "Huuuge Games"
    u = sys.argv[2] if len(sys.argv) > 2 else ""
    print(json.dumps(resolve_llm(nm, u), ensure_ascii=False, indent=1))
