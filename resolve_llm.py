#!/usr/bin/env python3
"""LLM fallback tier for ATS resolution (needs the claude CLI; cloud runs authenticate it
with the CLAUDE_CODE_OAUTH_TOKEN subscription secret).

When resolve_deep's deterministic heuristics give up — or land on an aggregator page the
auto-expand guard refuses to scrape — this tier does what a human resolver does: find the
company's real careers page (a SEARCH when the input URL is an aggregator link -- SerpApi,
then DuckDuckGo, then Google through the Bright Data unlocker, capped by LLM_BD_SEARCH_CAP),
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

from pipeline.aggregators import is_aggregator as _is_agg
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

_SYSTEM = """You resolve which ATS (applicant tracking system) hosts a company's job board, and
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
- bamboohr: https://{slug}.bamboohr.com/careers/list

Answer in the JSON schema you are given: platform (one of the listed platforms, or
"unknown"), token (the slug/uid/tenant-site token for that platform, or empty), api_url (the
exact endpoint URL, or empty), careers_url (the company's real careers page found in the
evidence, or empty), reason (one short sentence). Use platform "unknown" when the evidence
is insufficient — do NOT invent slugs or tenants that don't appear in the evidence."""

_PROMPT = """Company: {name}
Evidence:
{evidence}
{feedback}"""

_PLATFORMS = ["comeet", "greenhouse", "lever", "smartrecruiters", "recruitee", "ashby",
              "workday", "workable", "breezy", "bamboohr", "unknown"]
_SCHEMA = json.dumps({"type": "object",
                      "properties": {"platform": {"type": "string", "enum": _PLATFORMS},
                                     "token": {"type": "string"},
                                     "api_url": {"type": "string"},
                                     "careers_url": {"type": "string"},
                                     "reason": {"type": "string"}},
                      "required": ["platform", "token", "api_url", "careers_url", "reason"],
                      "additionalProperties": False})


def _fetch_html(url, timeout=25, cap=300_000):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.geturl(), r.read(cap).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return url, ""


def _is_aggregator(url):
    return _is_agg(url)   # shared blocklist (pipeline/aggregators.py)


# What the LAST call did, for the caller's budget: `auto_expand` charges its `claude -p`
# cap only when a call was actually made (`asked`), and prints why a name was deferred.
LAST = {"asked": False, "pages": 0, "candidates": 0, "error": "", "calls": 0}
# (page url, html) of every page the LAST call read: the evidence a proposal must be
# grounded in (see `_verify`)
_PAGES = []
# Own counter for the paid rung. `deep_validate._BD` is per PROCESS with a 150 default
# (docs/BACKLOG.md 10/20), so borrowing it would let one auto-expand run spend 150 credits.
_BD_OWN = {"used": 0}


def _search_candidates(name, limit=5):
    """Careers-page candidates by SEARCHING, three rungs in cost order -- the same ladder
    `audit_empty_rows.serp` got on 2026-08-23 and this tier did not.

    Until 2026-08-25 this was SerpApi only. With that quota at 0 (resets 2026-09-01) and an
    aggregator seed contributing no page, `_gather` produced the literal
    `(no pages reachable)` and `claude -p` was still asked -- 20 evidence-free calls a day
    that returned `unknown` every time (docs/BACKLOG.md 177). DuckDuckGo is free and works
    on the runners; the unlocker rung is capped per run by LLM_BD_SEARCH_CAP (default 5:
    the project ceiling is 4,500 credits/month from 2026-09 and two runs a day at 5 is ~7%
    of it). Lazy imports: `deep_validate` imports this module at top level.
    """
    urls = _serp_candidates(name, limit)
    if urls:
        return urls
    try:
        from deep_validate import ddg
        urls = [u for u in (ddg(name) or []) if not _is_aggregator(u)][:limit]
    except Exception:  # noqa: BLE001
        urls = []
    if urls:
        return urls
    cap = int(os.environ.get("LLM_BD_SEARCH_CAP", "5"))
    if _BD_OWN["used"] >= cap or not os.environ.get("BRIGHTDATA_API_KEY"):
        return []
    _BD_OWN["used"] += 1
    try:
        from deep_validate import google_via_unlocker
        return [u for u in (google_via_unlocker(name) or []) if not _is_aggregator(u)][:limit]
    except Exception:  # noqa: BLE001
        return []


def _serp_candidates(name, limit=5):
    """Rung 1 only: SerpApi general web search (key optional)."""
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
    """(evidence text, number of pages actually read). Zero pages is NO evidence."""
    lines = []
    candidates = []
    if url and not _is_aggregator(url):
        candidates.append(url)
    candidates += [u for u in _search_candidates(name) if u not in candidates]
    LAST["candidates"] = len(candidates)
    n_pages = 0
    del _PAGES[:]
    for u in candidates[:3]:
        final, html = _fetch_html(u)
        if not html:
            lines.append(f"page: {u} -> unreachable")
            continue
        n_pages += 1
        _PAGES.append((final or u, html))
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        lines.append(f"page: {u} (final: {final}) title: "
                     f"{(title.group(1).strip()[:120] if title else '?')}")
        lines += _extract_evidence(html)
    LAST["pages"] = n_pages
    return ("\n".join(lines) if lines else "(no pages reachable)"), n_pages


def _ask_claude(prompt, timeout=120, *, system=None, schema=None):
    """One structured call through the shared seam (`pipeline/llm.py`): `--model sonnet`
    (`LLM_RESOLVE_MODEL`), `--tools ""`, a JSON schema, a scratch cwd, no shell. The ATS
    resolver's `_SYSTEM`/`_SCHEMA` are the defaults; `listing_hunt` (a `{"url"}` pick) and
    `deep_validate` pass their own -- the first version hard-wired the ATS schema and the
    hunt's picker silently returned "" every night (wave-2 confirmation, I1). Until
    2026-08-25 this was a bare `claude -p` -- the default model with every tool enabled,
    the repo (and CLAUDE.md) as cwd, and the object regex-extracted from prose: the shape
    the classifier lane measured at ~10x the cost per call and retired on 2026-08-24.
    Infrastructure failures (no CLI, bad token, timeout) read as `None` here and are
    recorded in `LAST["error"]` for the caller's log."""
    from pipeline import llm
    try:
        return llm.call_json(prompt, system=system or _SYSTEM, schema=schema or _SCHEMA,
                             model=os.environ.get("LLM_RESOLVE_MODEL", "sonnet"),
                             timeout=timeout)
    except llm.LLMUnavailable as e:
        LAST["error"] = f"{e.kind}: {e}"
        return None


def _own_page_names_token(name, token, api_url, pages=None, platform=""):
    """Is the proposed board GROUNDED on a page that is the company's own?

    The search ladder (2026-08-25) puts pages from a plain web search into the evidence,
    and `_slug_matches` is a five-character prefix (plus an unconditional pass for any
    Comeet uid): `Similarweb` -> greenhouse `similartech`, `Sunflower Sustainable
    Investments` -> Claroty's Comeet `F2.004` both verify with real jobs (wave-1 write-path
    attacker, 1,303 cross-accepts measured over the active tokens). So the token must
    appear in the HTML of a page on the company's OWN domain: `is_foreign` decides
    ordinary domains, and a page on an ATS vendor host (`boards.greenhouse.io/<other>`) is
    "cannot tell" and does not count. A held page can REFUSE a board it merely embeds --
    `embedded_board_ok` -- but for Comeet uids that rule cannot near-match (BACKLOG 61), so
    the own-page requirement is the whole gate there, which is exactly the
    "uids come from the company's own page" premise `_slug_matches` assumed and the ladder
    broke."""
    from pipeline.company_identity import ATS_HOST, is_foreign
    from urllib.parse import urlparse
    needle = str(token or "").lower()
    if not needle:
        return False
    own = []
    for url, html in (pages if pages is not None else _PAGES):
        host = urlparse(url).netloc.lower()
        if not host or ATS_HOST.search(host) or _is_aggregator(url) or is_foreign(name, url):
            continue                                   # not the company's own page
        own.append(url)
        if needle in (html or "").lower():
            return True
    if platform == "comeet":
        # Comeet loads the uid at runtime, so the company's own static HTML rarely carries
        # it (Upwind Security, live 2026-08-25: uid 49.004 seen only on comeet.com). Read
        # the own page the way the premise says -- a comeetvar read in a real browser --
        # and require the SAME uid.
        for url in own[:2]:
            got = _try_comeet_via_page(name, url)
            if got and str(got[1]).lower() == needle:
                return True
    return False


def _verify(name, platform, token, api_url, pages=None):
    """Fetch through the production fetcher; returns (n_all, n_il) or raises."""
    if platform not in FETCHERS or platform in ("scrape", "discovery"):
        raise ValueError(f"unsupported platform {platform!r}")
    if not api_url.startswith("http") or _is_aggregator(api_url):
        raise ValueError("bad api_url")
    # slug/tenant must resemble the company: search fallbacks WILL offer another company's
    # board that verifies with real jobs (CyberArk->PANW, Imperva->Thales, Lili->Eli Lilly).
    # This tier previously relied on prompt-grounding alone — the one unguarded path.
    from pipeline import identity_gate as _gate
    if _gate.board_vouches(name, token, api_url) is False:
        raise ValueError(f"board {token!r} is declared or proven not {name!r}'s")
    # ...and resemblance is not evidence: the board must be GROUNDED on the company's own
    # page (2026-08-25), and a held page may refuse a board it merely embeds
    if not _own_page_names_token(name, token, api_url, pages, platform):
        raise ValueError(f"board {token!r} was not found on {name!r}'s own page")
    if platform != "comeet" and not _gate.embedded_board_ok(name, token, api_url):
        raise ValueError(f"board {token!r} does not vouch for {name!r}")
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
    LAST.update(asked=False, pages=0, candidates=0, error="", calls=0)
    try:
        evidence, n_pages = _gather(name, url)
        if n_pages == 0:
            # No page was read, so there is nothing for the model to reason FROM; a call
            # here is a paid coin flip that always lands on `unknown` (measured 0/50 over
            # five runs). The caller sees LAST["asked"] is False and does not charge it.
            return None
        feedback = ""
        for _attempt in range(2):
            LAST["asked"] = True
            LAST["calls"] += 1              # the caller's budget counts CALLS, retries included
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
