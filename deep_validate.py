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
Usage: python deep_validate.py [--apply] [--only "A,B"]   # on demand; the Sunday audit runs
       the same validator as its Chromium rung (audit_empty_rows, BACKLOG 6)
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

from audit_empty_rows import SIGS, _WD, _slug_matches, active_twin, fetch, verify, AGG
import check_invariants as _INV      # the platform<->host table, imported not retyped
from pipeline.aggregators import is_aggregator
from bd_rescue import _load_secrets, unlock
from pipeline.recruiters import is_recruiter
from resolve_llm import _ATS_HINT, _PROMPT, _SCHEMA, _SYSTEM, _ask_claude
# One seam, called through the MODULE, never bound with `from ... import x as y`. A
# `from` binding is a separate module global, so patching the gate would not reach it -
# which is how two fixtures silently started hitting the live network instead of their
# stub. Attribute access resolves at call time, so there is exactly one place to patch.
from pipeline import identity_gate as _gate
from pipeline.atomic import write_csv_rows
from pipeline.notes import append as _note_append, replace_own as _note_replace
from pipeline.company_identity import is_foreign
from audit_empty_rows import tenant_is_this_company
from pipeline.company_identity import looks_like_a_job_listing_page
from pipeline.verdicts import in_pool

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


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
        if u.startswith("http") and not is_aggregator(u):
            urls.append(u)
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
        u = m.group(1)
        if "duckduckgo" not in u and not is_aggregator(u):
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


_BD = {"used": 0}


# Hosts that are Google's own furniture or a standards namespace, never a result.
_G_NOISE = ("google", "gstatic", "googleusercontent", "googleapis", "ggpht", "w3.org",
            "schema.org", "youtube", "blogger", "chrome", "android")
# A path that says "this is where the jobs are". One host can appear in the result page a
# dozen times -- as a bare homepage, a logo link, a breadcrumb and the actual result -- and
# the bare form always comes FIRST, so keeping the first URL per host keeps the useless one.
_G_JOBS_PATH = re.compile(r"(job|career|position|opening|vacanc|role|hiring|apply|greenhouse|"
                          r"lever|ashby|comeet|smartrecruiters|recruitee|workable|breezy)", re.I)
_G_URL = re.compile(r'https?://[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?:/[^\s"\'<>]*)?')


def google_via_unlocker(name, limit=4):
    """Search Google through the unlocker. The ONE search rung that still works.

    **This returned `[]` for every query until 2026-08-27 and nothing noticed**, which is the
    failure ARCHITECTURE section 3 warns about in its own words: a run of "found nothing" is
    indistinguishable from "cannot search". Two causes, both fixed here.

    1. **The parse.** It looked for `href="/url?q=..."` or `href="https://..."`. Modern Google
       serves the no-JS variant with zero result `href`s -- measured on a live 330 KB response
       for `Maytronics careers`: `/url?q=` appeared **0** times and only 7 bare `href="http`
       existed, all of them Google's own chrome. The result URLs are in the document as plain
       text. Scanning for URLs and dropping Google's furniture recovers them.

    2. **The locale.** The unlocker's exit node is wherever Bright Data puts it -- on
       2026-08-27 it was Kazakhstan, and the page came back `hl=en-KZ` off `google.kz` with
       results dominated by job-aggregator spam (vaia, bebee, trabajo, learn4good, tealhq).
       `gl=il&hl=en` asks for the Israeli index, which is where an Israeli employer's own site
       ranks. Measured, same three names, plain vs `gl=il`:

           Maytronics  plain -> comeet.com, maytronics.com, tealhq.com, vaia.com, ...
           Maytronics  gl=il -> maytronics.com, comeet.com, careers.maytronics.co.il

       The second row is the company's site, its ATS board and its careers page; the first is
       two of those plus noise.

    3. **Which URL per host.** One host appears many times in a result page -- bare homepage,
       logo link, breadcrumb, then the actual result -- and **the bare form always comes
       first**, so keeping the first URL per host keeps the least useful one. Measured on a
       live `Exodigo careers` response, Google returned BOTH
       `https://www.comeet.com/jobs/exodigo/89.005` (the company's actual Comeet board, i.e. a
       direct resolution) and `https://www.exodigo.com/open-roles` (its real listings page) --
       and first-per-host discarded both in favour of `comeet.com` and `exodigo.com`. The
       operator caught this: the hunt had settled on `exodigo.com/careers`, a real 200 page
       that is not the listings page. Ranked per host now: a jobs-ish path beats any other
       path beats a bare host.

    Dedupe is by HOST so `limit` buys distinct candidates instead of four pages of one site --
    the caller renders `cands[:2]`, so a duplicated host wastes the whole budget. This is
    cloud-portable by construction: the exit is Bright Data's, not the caller's, so a runner
    and a dev machine get the same answer.
    """
    cap = int(os.environ.get("DEEP_BD_SEARCH_CAP", "150"))
    if _BD["used"] >= cap or not os.environ.get("BRIGHTDATA_API_KEY"):
        return []
    _BD["used"] += 1
    q = urllib.parse.quote_plus(f"{name} careers")
    html = unlock(f"https://www.google.com/search?q={q}&num=20&gl=il&hl=en") or ""
    order, best = [], {}
    for m in _G_URL.finditer(html):
        u = urllib.parse.unquote(m.group(0).rstrip(".,)&"))
        parts = u.split("/", 3)
        if len(parts) < 3:
            continue
        host = parts[2].lower()
        if any(b in host for b in _G_NOISE) or is_aggregator(u):
            continue
        path = parts[3] if len(parts) > 3 else ""
        # rank: a jobs-ish path beats any other path, which beats a bare host -- and among
        # equals the SHORTEST path wins, because that is the index. `/open-roles` is the
        # listings page and `/open-positions/field-operator-d0d83` is one posting on it;
        # `comeet.com/jobs/silk/F6.00C` is the board and `.../F6.00C/core-python-engineer`
        # is one row of it. Preferring length picked the leaf every time.
        rank = (2 if _G_JOBS_PATH.search(path) else (1 if path.strip("/") else 0), -len(path))
        if host not in best:
            order.append(host)
            best[host] = (rank, u)
        elif rank > best[host][0]:
            best[host] = (rank, u)
    return [best[h][1] for h in order][:limit]


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
    cands = [] if not seed_url or is_aggregator(seed_url) else [seed_url]
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
        if got and not _slug_matches(name, got[1], got[2]):
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
            # the ATS resolver's contract, stated rather than inherited by default
            p = _ask_claude(_PROMPT.format(name=name, evidence="\n".join(evid)[:8000],
                                           feedback=feedback), system=_SYSTEM, schema=_SCHEMA)
            if not p or p.get("platform") in (None, "", "unknown"):
                print(f"       (llm: {'no answer' if not p else 'unknown'} for {name})", flush=True)
                break
            plat = str(p.get("platform", "")).lower().strip()
            tok = str(p.get("token", "")).strip()
            api = str(p.get("api_url", "")).strip()
            print(f"       (llm proposes {plat}:{tok} for {name})", flush=True)
            if not _slug_matches(name, tok, api):
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


def _revalidatable(note, days=None):
    """True if never deep-validated, or validated longer ago than DEEP_REVALIDATE_DAYS (30)."""
    days = days if days is not None else int(os.environ.get("DEEP_REVALIDATE_DAYS", "30"))
    m = re.search(r"deep-validated (\d{4}-\d{2}-\d{2})", note or "")
    if not m:
        return True
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days >= days


def _canonical_endpoint(plat, tok):
    """That platform's own API endpoint for `tok`, or "" when there is no template.

    `SIGS` already carries one template per guessable platform and `audit_empty_rows`
    builds every endpoint it writes from them; this is the same table read backwards, so
    a platform added there is canonicalised here without a second edit."""
    for _rx, p, tmpl in SIGS:
        if p == plat and tok:
            return tmpl.format(tok)
    return ""


def apply_verdict(fr, name, verdict, plat, tok, api, n_all, n_il, detail, rows=None):
    """Fold one `validate_one` verdict into the row `fr` (in place). The gates and the
    fixed-length notes below are the whole reason this is one function: `audit_empty_rows`
    runs it as its Chromium rung on Sunday (BACKLOG 6, 2026-08-26) and `main()` runs it for
    an on-demand `--only` pass -- one implementation, one set of guards."""
    # Tenant test FIRST, page test only as a second chance - the shape
    # `audit_empty_rows` already uses, and for the reason wave 8 measured.
    #
    # Gating directly on `_gate.ok_to_write(api)` looked stricter and was simply
    # broken: `api` here is a MACHINE endpoint. All 66 active Workday rows
    # are `/wday/cxs/<tenant>/<site>/jobs`, which answers a GET with 400, so
    # `_page_names_company` returns None ("could not read") and the row was
    # refused - with a false `not this company's board` stamped on it. Live
    # sample of 72 currently-active rows: True 47 / None 19 / False 6, i.e.
    # 35% would have been refused on re-examination, including six false
    # negatives on companies' OWN boards (one zero, Matrix IT, Valens
    # Semiconductor, Grip Security, Verint). That made Saturday stricter than
    # Sunday in the commit whose whole point was to stop them disagreeing.
    #
    # The earlier `api or r[3] or ""` was worse in the other direction: when
    # the LLM tier proposes `platform: "scrape"` with no api_url (and
    # `fetch_scrape` keys on company_name, so `verify()` succeeds), the gate
    # fell through to the ROW'S OWN careers page - re-creating in this file
    # the precise bug the same commit deleted from `audit_empty_rows`.
    # `_cand` is the candidate and only the candidate; an empty one is no
    # evidence and is refused by `not _cand`.
    _cand = api or ""
    # `activation_verdict` (2026-08-26): a held page is not in hand here, so the board's
    # tenant vouches (declared / near-equal), a declared negative or a subdomain mismatch
    # refuses, and "cannot tell" is settled by ONE read of the platform's HUMAN board page
    # -- never the API endpoint (0-28 bytes; refused 358 rows when tried) -- or deferred
    # as `unverified`, which stamps no claim and keeps the row's tokens.
    _av = (_gate.activation_verdict(name, _cand, n_all, token=tok or "")
           if verdict == "recovered" and _cand else "empty")
    _ident = _av == "ok"
    # Clause 3 of the activation rule (ARCHITECTURE.md section 2) is
    # `looks_like_a_job_listing_page`, and the wave-8 rewrite dropped it —
    # the import stayed, nothing called it. Restored SCOPED TO `scrape`,
    # which is where the original had it: an API endpoint like
    # `/wday/cxs/<tenant>/<site>/jobs` or `boards-api.greenhouse.io/...` is
    # not shaped like a listings page and never will be, so applying it to
    # every platform would refuse every native-ATS recovery. Without it a
    # `scrape` proposal from the LLM tier could activate a row pointing at
    # `.../about-us/leadership`.
    if verdict == "recovered" and not (
            n_all and not is_foreign(name, _cand) and _ident
            and (plat != "scrape"
                 or looks_like_a_job_listing_page(_cand))):
        # Identity gate: rendering the STORED url and finding roles proves
        # roles exist there, not that they are this company's. The stored
        # url of a dark row is often the hunt's best GUESS.
        #
        # Until 2026-08-24 this was `is_foreign(...) or not
        # looks_like_a_job_listing_page(...)` and nothing else - i.e. no gate
        # at all on an ATS host, because `is_foreign` returns False for every
        # one of them by design (section 2, docs/BACKLOG.md 21). Driven with
        # a stubbed `validate_one`, this branch activated
        # `novartis...myworkdayjobs.com/riskified` for Riskified,
        # `careers-bancorpbank.icims.com` for Bancor, and a 0-jobs board -
        # the same three shapes `audit_empty_rows` refuses. The two tools
        # select the IDENTICAL 255 rows (docs/BACKLOG.md 6) and run 24h
        # apart, so Saturday silently re-opened what Sunday had closed.
        #
        # `n_all` first: a board that verifies with zero jobs is the
        # `empty-board` shape, not a recovery.
        #
        # The note is fixed-length and carries NO url. At 103 chars the old
        # form evicted a pool token from 216 of the 255 rows in this tool's
        # own pool and pushed 31 of them out of `in_pool` entirely - and
        # since this tool's own filter IS `in_pool`, a row it refused could
        # never be re-examined by it again. Measured against the segment it
        # replaces: 103 chars -> 216/31, this form -> 198/7.
        fr[5] = _note_replace(
            fr[5], "deep-validated",
            f"deep-validated {TODAY}: " + {
                "not-ours": "not this company's board",
                "empty": "verified 0 jobs (empty board)",
                "not-listing": "not a listings page",
            }.get(_av, "unverified (no readable page)"))
    elif verdict == "recovered":
        # Two things every gate above this one leaves unasked, both of which put a row on
        # master's red list on 2026-08-30 (`7319f85`).
        #
        # 1. Is another ACTIVE row already reading this board? Identity says yes to both
        #    halves of a twin, because the board is genuinely the company's under either
        #    spelling.
        # 2. Is `api` actually THAT PLATFORM'S endpoint? The LLM tier proposes a platform,
        #    a token and a url independently, and `verify()` does not object: Renesas
        #    landed as `smartrecruiters` with `https://jobs.renesas.com/` in column 3
        #    because `fetch_smartrecruiters` appends its query to whatever it is handed.
        #    The row scanned, so nothing downstream noticed either.
        # ORDER MATTERS, and both orderings were wrong once. Repair FIRST, then gate and
        # twin-check THE ADDRESS THAT WILL BE WRITTEN: a repair that runs after the gate
        # activates on a url identity never saw (the `CyberArk -> paloaltonetworks` shape),
        # and a twin check that runs before the repair cannot see the twin the repair
        # itself creates. Both were live in the first draft of this change.
        _ph = _INV.PLATFORM_HOST.get((plat or "").strip().lower())
        if _ph and not re.search(_ph, api or "", re.I):
            # Repair to the platform's canonical endpoint if that VERIFIES -- never persist
            # an address nothing fetched (`test_the_hunt_never_stores_another_company_s_
            # page_as_the_row_address`). Otherwise the row stays dark and this tool tries
            # again after `_revalidatable` (30 days, not next Sunday). Four of the eleven
            # PLATFORM_HOST platforms (comeet, microsoft, oraclehcm, workday) have no SIGS
            # template, so on those a mismatch can only ever be refused, never repaired.
            cand = _canonical_endpoint(plat, tok)
            ok = False
            if cand:
                try:
                    _n_all, _n_il = verify(name, plat, tok, cand)
                    ok = bool(_n_all)
                except Exception:                                  # noqa: BLE001
                    ok = False
            # the repaired address is a DIFFERENT address, so it faces the same gate the
            # original faced -- `_av` above was computed against the url the LLM proposed
            if ok and _gate.activation_verdict(name, cand, _n_all, token=tok or "") != "ok":
                ok = False
            if not ok:
                fr[5] = _note_replace(
                    fr[5], "deep-validated",
                    f"deep-validated {TODAY}: endpoint off-host; unverified")
                return
            api, n_all, n_il = cand, _n_all, _n_il
        _rows = rows
        if _rows is None:                       # never activate against a snapshot: re-read
            _rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
        if active_twin(name, plat, tok, api, _rows):
            fr[5] = _note_replace(fr[5], "deep-validated",
                                  f"deep-validated {TODAY}: twin-board; not activated")
            return
        fr[1], fr[2], fr[3] = plat, tok, api
        fr[4] = "true"
        # Append-log, not a rewrite (ARCHITECTURE.md section 2). The two
        # branches around this one already use replace_own; this one
        # overwrote the cell, discarding the `dark-triage` mode that had
        # routed the row here and every other tool's verdict with it.
        fr[5] = _note_replace(
            fr[5], "re-audit",
            f"re-audit {TODAY}: deep-verified {n_all}/{n_il} IL (was dark)")
    else:
        note = {"unsupported": f"unsupported ATS {detail}",
                "dark": "no ATS detected (rendered)",
                "unreachable": "unreachable"}[verdict]
        # preserve other tools' verdicts (and the monitored-candidate /
        # host-documented tokens listing_hunt's fast-path keys on) — only
        # replace our own previous stamp
        fr[5] = _note_replace(fr[5], "deep-validated",
                              f"deep-validated {TODAY}: {note}")


def _apply_verdict_to_file(name, verdict, plat, tok, api, n_all, n_il, detail):
    """Re-read + match by NAME before every write (single-writer discipline: a held
    snapshot + row-index writes silently revert other writers)."""
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for fr in fresh:
        if fr and fr[0] == name and len(fr) >= 6:
            apply_verdict(fr, name, verdict, plat, tok, api, n_all, n_il, detail, rows=fresh)
    write_csv_rows("companies.csv", fresh)


def main():
    _load_secrets()
    apply = "--apply" in sys.argv
    limit = int(os.environ.get("DEEP_LIMIT", "0"))
    only = set()
    if "--only" in sys.argv:
        only = {x.strip() for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x.strip()}
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               # in_pool already excludes EVERY terminal state (pipeline.verdicts.TERM_RX,
               # alias-of included) -- a private 3-token copy here was redundant by
               # construction and one more spelling for an agent to reconcile
               and in_pool(r[5] or "")
               # re-validate after DEEP_REVALIDATE_DAYS instead of never: excluding every
               # already-stamped row made deep validation a once-ever terminal state
               and _revalidatable(r[5] or "")
               and not is_recruiter(r[0])
               and (not only or r[0] in only)]
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
                try:
                    _apply_verdict_to_file(name, verdict, plat, tok, api, n_all, n_il, detail)
                except Exception as e:  # noqa: BLE001
                    # one row's write must not end the night (the step is continue-on-error)
                    print(f"::warning::deep_validate: write failed for {name}: {str(e)[:80]}", flush=True)
            time.sleep(0.3)
    print(f"\n=== deep validation: {stats} · BD searches used: {_BD['used']} ===", flush=True)


if __name__ == "__main__":
    main()
