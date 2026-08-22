#!/usr/bin/env python3
"""Deep individual validation of every parked '0 openings' company.

The weekly re-audit (audit_empty_rows.py) works on RAW HTML — it recovers boards whose ATS
embed is server-rendered. This goes one level deeper for everything still dark: render the
careers page in headless Chromium and sniff the NETWORK REQUESTS, where a JS-rendered board
always reveals its ATS API (comeet careers-api, greenhouse boards-api, lever, ashby,
workday /wday/cxs/, recruitee, workable...), plus read window.comeetvar directly. Search
fallback is DuckDuckGo HTML (free) then Bright Data Web Unlocker on Google (capped) since
SerpApi may be exhausted. Every proposal is verified through pipeline.fetchers and the
foreign-slug guard before a row is activated.

Verdicts are PERSISTED into the row note so no company is re-ground pointlessly:
  - active row + 're-audit ... deep-verified N/M IL'      (recovered)
  - 'deep-validated <date>: unsupported ATS <name>'       (needs a new fetcher)
  - 'deep-validated <date>: no ATS detected (rendered)'   (genuinely custom/no careers)
  - 'deep-validated <date>: unreachable'                  (nothing to render)

Env: DEEP_LIMIT (0=all) · DEEP_BD_SEARCH_CAP (default 150 Unlocker google searches)
Usage: python deep_validate.py [--apply]
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from audit_empty_rows import SIGS, _WD, _slug_matches, fetch, verify, AGG
from bd_rescue import _load_secrets, unlock
from pipeline.recruiters import is_recruiter
from resolve_llm import _ATS_HINT, _PROMPT, _ask_claude

_LLM = {"used": 0}


def _llm_ok():
    import shutil
    return _LLM["used"] < int(os.environ.get("DEEP_LLM_CAP", "150")) and shutil.which("claude")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_UNSUP = re.compile(r"(eightfold\.ai|avature\.net|oraclecloud\.com|jobvite\.com|phenom|"
                    r"successfactors|taleo\.net|icims\.com)", re.I)
_CAREER_LINK = re.compile(r'href=["\']([^"\']*(?:career|jobs|join-us|joinus|positions)[^"\']*)["\']', re.I)
_WD_CXS = re.compile(r"https://([a-z0-9]+)\.(wd\d+)\.myworkdayjobs\.com/wday/cxs/([^/]+)/([^/]+)/")
TODAY = dt.date.today().isoformat()


def ddg(name, limit=4):
    q = urllib.parse.quote_plus(f"{name} careers")
    html = fetch(f"https://html.duckduckgo.com/html/?q={q}", timeout=15)
    if not html:
        html = fetch(f"https://lite.duckduckgo.com/lite/?q={q}", timeout=15)
    urls = []
    for m in re.finditer(r"uddg=([^&\"']+)", html):
        u = urllib.parse.unquote(m.group(1))
        if u.startswith("http") and not any(a in u.lower() for a in AGG):
            urls.append(u)
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
        u = m.group(1)
        if "duckduckgo" not in u and not any(a in u.lower() for a in AGG):
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


_BD = {"used": 0}


def google_via_unlocker(name, limit=4):
    cap = int(os.environ.get("DEEP_BD_SEARCH_CAP", "150"))
    if _BD["used"] >= cap or not os.environ.get("BRIGHTDATA_API_KEY"):
        return []
    _BD["used"] += 1
    q = urllib.parse.quote_plus(f"{name} careers")
    html = unlock(f"https://www.google.com/search?q={q}&num=10")
    out = []
    for m in re.finditer(r'href="(?:/url\?q=)?(https?://[^"&]+)', html or ""):
        u = urllib.parse.unquote(m.group(1))
        if ("google." not in u and "gstatic" not in u
                and not any(a in u.lower() for a in AGG) and u not in out):
            out.append(u)
    return out[:limit]


def propose_from_text(text):
    """ATS signature scan over any text (rendered HTML or a network-request URL list)."""
    m = _WD_CXS.search(text)
    if m:
        tenant, wd, t2, site = m.groups()
        return ("workday", f"{tenant}/{site}",
                f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs")
    for rx, plat, tmpl in SIGS:
        m = rx.search(text)
        if m:
            return plat, m.group(1), tmpl.format(m.group(1))
    m = _WD.search(text)
    if m:
        tenant, wd, site = m.groups()
        return ("workday", f"{tenant}/{site}",
                f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs")
    return None


class Renderer:
    """One Chromium for the whole run; a fresh page per company."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self._b = self._p.chromium.launch(headless=True)
        return self

    def __exit__(self, *a):
        try:
            self._b.close()
            self._p.stop()
        except Exception:  # noqa: BLE001
            pass

    def sniff(self, url, timeout_ms=22000):
        reqs = []
        pg = self._b.new_page(user_agent=_UA)
        pg.route("**/*", lambda route: route.abort()
                 if route.request.resource_type in ("image", "media", "font")
                 else route.continue_())
        pg.on("request", lambda r: reqs.append(r.url))
        html, cv = "", None
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            pg.wait_for_timeout(6000)
            html = pg.content()
            cv = pg.evaluate("()=>window.comeetvar?{uid:window.comeetvar.comeet_uid,"
                             "token:window.comeetvar.comeet_token}:null")
        except Exception:  # noqa: BLE001
            pass
        finally:
            pg.close()
        return html, reqs, cv


def validate_one(rend, name, seed_url):
    """Returns (verdict, platform, token, api_url, n_all, n_il, detail)."""
    cands = [] if not seed_url or any(a in seed_url.lower() for a in AGG) else [seed_url]
    for u in ddg(name) + (google_via_unlocker(name) if len(cands) < 2 else []):
        if u not in cands:
            cands.append(u)
    if not cands:
        return ("unreachable", None, None, None, 0, 0, "no candidate URLs")
    unsup = ""
    tried = 0
    evid = []
    for u in cands[:3]:
        html, reqs, cv = rend.sniff(u)
        blob = html + "\n" + "\n".join(reqs)
        if not html and not reqs:
            evid.append(f"page: {u} -> unreachable")
            continue
        tried += 1
        title = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
        evid.append(f"page: {u} title: {(title.group(1).strip()[:100] if title else '?')}")
        evid += [f"net: {q}" for q in reqs
                 if re.search(r"api|jobs|career|position|graphql|comeet|greenhouse|lever|"
                              r"ashby|workday|recruitee|smartrecruiters|workable|eightfold|"
                              r"phenom|successfactors|oraclecloud", q, re.I)][:25]
        evid += [f"ats-url: {m.group(0)}" for m in _ATS_HINT.finditer(blob)][:15]
        if cv and cv.get("uid") and cv.get("token"):
            api = (f"https://www.comeet.com/careers-api/2.0/company/{cv['uid']}"
                   f"/positions?token={cv['token']}")
            got = ("comeet", cv["uid"], api)
        else:
            got = propose_from_text(blob)
        if not got and re.search(r"comeet", blob, re.I):
            # comeet widget present but comeetvar not caught by the quick sniff — static
            # COMEET.init extraction first (token+uid probe), then the slow reader
            from audit_empty_rows import comeet_static_try, comeet_try
            got = comeet_static_try(name, html) or comeet_try(name, u)
        if got and not _slug_matches(name, got[1]):
            got = None
        if not got:
            m = _UNSUP.search(blob)
            if m:
                unsup = m.group(1)
            # homepage? follow one careers link and retry once
            link = _CAREER_LINK.search(html or "")
            if link and tried < 3:
                nxt = urllib.parse.urljoin(u, link.group(1))
                if nxt not in cands:
                    cands.append(nxt)
            continue
        plat, tok, api = got
        try:
            n_all, n_il = verify(name, plat, tok, api)
            return ("recovered", plat, tok, api, n_all, n_il, "")
        except Exception as e:  # noqa: BLE001
            unsup = unsup or f"verify-failed {plat}:{tok} ({str(e)[:40]})"
            evid.append(f"FAILED-ATTEMPT: {plat} slug={tok} -> {str(e)[:60]}")

    # LLM judgment tier: regexes are out of ideas — let Claude read the evidence
    # (network calls, ATS hints, failed guesses) and propose. Verified + slug-guarded.
    if evid and _llm_ok():
        feedback = ""
        for _ in range(2):
            _LLM["used"] += 1
            p = _ask_claude(_PROMPT.format(name=name, evidence="\n".join(evid)[:8000],
                                           feedback=feedback))
            if not p or p.get("platform") in (None, "", "unknown"):
                print(f"       (llm: {'no answer' if not p else 'unknown'} for {name})", flush=True)
                break
            plat = str(p.get("platform", "")).lower().strip()
            tok = str(p.get("token", "")).strip()
            api = str(p.get("api_url", "")).strip()
            print(f"       (llm proposes {plat}:{tok} for {name})", flush=True)
            if not _slug_matches(name, tok):
                print(f"       (llm proposal rejected: foreign slug)", flush=True)
                break
            try:
                n_all, n_il = verify(name, plat, tok, api)
                return ("recovered", plat, tok, api, n_all, n_il, "llm")
            except Exception as e:  # noqa: BLE001
                feedback = (f"\nA previous attempt proposed platform={plat!r} api_url={api!r} "
                            f"and verification FAILED: {e}. Try another or answer unknown.\n")
    if unsup and _UNSUP.search(unsup):
        return ("unsupported", None, None, None, 0, 0, unsup)
    if tried == 0:
        return ("unreachable", None, None, None, 0, 0, "all candidates dead")
    return ("dark", None, None, None, 0, 0, unsup or "no ATS detected in rendered DOM/network")


def main():
    _load_secrets()
    apply = "--apply" in sys.argv
    limit = int(os.environ.get("DEEP_LIMIT", "0"))
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               and re.search(r"scanned; no open|unreachable; could not|aggregator URL", r[5] or "")
               and "deep-validated" not in (r[5] or "")
               and not is_recruiter(r[0])]
    if limit:
        targets = targets[:limit]
    print(f"deep-validating {len(targets)} parked companies "
          f"(BD search cap {os.environ.get('DEEP_BD_SEARCH_CAP', '150')})\n", flush=True)
    stats = {"recovered": 0, "unsupported": 0, "dark": 0, "unreachable": 0}
    t0 = time.time()
    budget_min = int(os.environ.get("DEEP_TIME_BUDGET_MIN", "0"))
    with Renderer() as rend:
        for n, (i, r) in enumerate(targets, 1):
            if budget_min and (time.time() - t0) / 60 > budget_min:
                print(f"time budget {budget_min}min reached — stopping cleanly; "
                      f"remaining rows keep their notes for the next run", flush=True)
                break
            name = r[0]
            try:
                verdict, plat, tok, api, n_all, n_il, detail = validate_one(rend, name, r[3])
            except Exception as e:  # noqa: BLE001
                verdict, detail = "unreachable", f"error {str(e)[:50]}"
                plat = tok = api = None
                n_all = n_il = 0
            stats[verdict] += 1
            tag = {"recovered": "OK", "unsupported": "UN", "dark": "--", "unreachable": "xx"}[verdict]
            print(f"  [{tag}] {n}/{len(targets)} {name}: "
                  f"{(plat + ':' + str(tok) + f' -> {n_all}/{n_il} IL') if plat else detail}",
                  flush=True)
            if apply:
                if verdict == "recovered":
                    rows[i][1], rows[i][2], rows[i][3] = plat, tok, api
                    rows[i][4] = "true"
                    rows[i][5] = f"re-audit {TODAY}: deep-verified {n_all}/{n_il} IL (was dark)"
                else:
                    note = {"unsupported": f"unsupported ATS {detail}",
                            "dark": "no ATS detected (rendered)",
                            "unreachable": "unreachable"}[verdict]
                    rows[i][5] = f"deep-validated {TODAY}: {note}"
                csv.writer(open("companies.csv", "w", encoding="utf-8",
                                newline="")).writerows(rows)
            time.sleep(0.3)
    print(f"\n=== deep validation: {stats} · BD searches used: {_BD['used']} ===", flush=True)


if __name__ == "__main__":
    main()
