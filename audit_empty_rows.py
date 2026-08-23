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
Env:   AUDIT_TIME_BUDGET_MIN (default 90) · SERP_RESERVE · DEEP_BD_SEARCH_CAP
       (named DEEP_ because the unlocker cap is read from the same variable
       `deep_validate` uses; there is no AUDIT_BD_SEARCH_CAP and setting one does
       nothing - the docstring advertised it for a day)
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

from bd_rescue import _load_secrets
from pipeline.fetchers import fetch_company
from pipeline.israel import is_israel_job

TODAY = dt.date.today().isoformat()
# a "0 openings" verdict is a snapshot, not a property of the company
AUDIT_TTL_DAYS = 30

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
from pipeline.aggregators import HOSTS as AGG, is_aggregator   # single source of truth
from pipeline.atomic import write_csv_rows, write_json
from pipeline.company_identity import is_foreign, page_mentions_company
from pipeline.notes import replace_own as _note_replace
from pipeline.recruiters import is_recruiter
from pipeline.verdicts import in_pool

# States no re-check pool may re-open. This is `pipeline.verdicts.TERMINAL` PLUS `alias-of`,
# which belongs there and is not (docs/BACKLOG.md, "One terminal-state list"). Until that
# lands, every registry tool spells it out — listing_hunt.py and deep_validate.py already do.
TERMINAL = re.compile(r"defunct|domain-dead|alias-of", re.I)

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


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


# Host labels that are the ATS's own plumbing, never a tenant name.
_GENERIC_HOST_LABEL = {"www", "jobs", "job", "boards", "board", "careers", "career", "api",
                       "apply", "hire", "hiring", "recruiting", "recruiting2", "app", "my",
                       "en", "secure", "talent", "people", "work", "join", "embed", "static"}
# Platforms whose TENANT lives in the subdomain - the blind spot `is_foreign` cannot see.
_SUBDOMAIN_TENANT_HOST = re.compile(
    r"(icims\.com|myworkdayjobs\.com|eightfold\.ai|avature\.net|oraclecloud\.com|"
    r"hibob\.com|ultipro\.com|phenompeople\.com|jobvite\.com|taleo\.net|workable\.com|"
    r"applytojob\.com|successfactors)", re.I)
# words that are in a registry name but never in a tenant slug
_NAME_FILLER = {"israel", "israeli", "ltd", "inc", "the", "group", "technologies", "technology",
                "labs", "systems", "solutions", "company", "companies", "corp", "corporation",
                "holdings", "international", "global", "studios", "water", "intelligence",
                "security", "medical", "digital", "software", "sciences", "health"}


def tenant_is_this_company(name, url):
    """Does an ATS URL's TENANT really belong to `name`? Use INSTEAD of `is_foreign` here.

    `pipeline.company_identity.is_foreign` early-returns **False for every ATS host** — by
    design, because a rebrand or acquisition looks identical to a mis-resolution and blocking
    outright costs real coverage (Momentis really does post under `memic`). The cost is that
    clauses 2 and 3 of the activation rule are inert on 432 of the 1,199 rows, and it even
    overrides an explicit `mismatch`:

        NanoLock Security -> gen.wd1.myworkdayjobs.com   verdict=mismatch  is_foreign=False
                                                          (that is Gen Digital's tenant)

    So, for the paths that ACTIVATE or PERSIST an address:

    * an explicit `mismatch` is honoured even on an ATS host — `verdict` only says that when
      it found a tenant belonging to someone else;
    * **where the tenant lives differs by platform**, and `_slug_candidates` returns host
      labels and path segments in ONE flat list, so an `any()` over it accepts a foreign
      tenant whenever the PATH happens to match. `novartis.wd3.myworkdayjobs.com/riskified`
      is Novartis's Workday with a site named `riskified`. If the host carries a
      non-generic label, THAT is the tenant and the path is only a site name;
    * the tenant must be NEAR-EQUAL to the name, not merely contain it. `_slug_matches`
      passes `Bancor`/`careers-bancorpbank` and `Bit`/`careers-bitdefender` on plain
      containment — the same "containment must be TIGHT" lesson `company_identity` already
      learned for domains (rad.com/RADLogics);
    * a Comeet uid (`60.002`) is opaque and comes from the company's own page — exempt.

    Non-ATS URLs return True: `is_foreign` is the right gate there and works correctly.
    """
    import urllib.parse as _up
    from pipeline.company_identity import (ATS_HOST, verdict as _verdict,
                                           _slug_candidates, _norm)
    host = (_up.urlparse(url or "").netloc or "").lower()
    if not host or not ATS_HOST.search(host):
        return True
    # SCOPE FIRST. The `mismatch` test below must not run on a path-tenant platform: on
    # greenhouse, `Momentis Surgical` -> `memic` scores `mismatch` and is a LEGITIMATE
    # acquirer board (ARCHITECTURE section 2 cites it by name). Scoping after the mismatch
    # test blocked it, which is the 36-row regression docs/BACKLOG.md 21 measured and
    # rejected. Only the subdomain-tenant platforms below are in scope.
    if not _SUBDOMAIN_TENANT_HOST.search(host):
        return True
    if _verdict(name, url) == "mismatch":
        return False

    cn = _norm(name)
    core = _norm("".join(w for w in re.findall(r"[A-Za-z0-9]+", name or "")
                         if w.lower() not in _NAME_FILLER))
    targets = {t for t in (cn, core) if t}
    if not targets:
        return True

    # A tenant slug routinely carries a legal or numeric suffix the registry name omits:
    # wizinc/Wiz, gongio/Gong, outbraininc/Outbrain, playtikaltd/Playtika, hippo70/Hippo
    # Insurance, tipaltisolutions/Tipalti. Requiring near-equality without stripping these
    # rejected 99 of the 460 active ATS rows. Stripping is safe in the direction that
    # matters: `bancorpbank` and `bitdefender` carry no such suffix, so they still fail.
    _TENANT_SUFFIX = re.compile(
        r"(inc|ltd|llc|plc|corp|co|io|ai|hq|com|group|holdings|solutions|technologies|"
        r"labs|global|international|\d+)+$")

    def near(c):
        nc = _norm(c)
        if not nc:
            return False
        forms = {nc, _TENANT_SUFFIX.sub("", nc)}
        return any(f and abs(len(f) - len(t)) <= 1 and (f in t or t in f)
                   for f in forms for t in targets)

    def _plumbing(label):
        """A host label is the ATS's own plumbing when EVERY hyphen-part of it is generic.

        `boards-api.greenhouse.io` and `job-boards.greenhouse.io` are Greenhouse's own
        hostnames, not a tenant - matching them against the company name rejected 173 of the
        460 active ATS rows on the first attempt. `careers-bancorpbank` splits to
        {careers, bancorpbank}, and `bancorpbank` is not generic, so it stays a tenant.
        """
        parts = [x for x in re.split(r"[-_]", label) if x]
        return bool(parts) and all(
            x in _GENERIC_HOST_LABEL or re.fullmatch(r"wd\d+|v\d+|\d+", x) for x in parts)

    # SCOPE: only the platforms that put the tenant in the SUBDOMAIN. That is the class
    # `company_identity` cannot see and the class that produced every demonstrated failure -
    # Bancor/careers-bancorpbank.icims.com, NanoLock Security/gen.wd1.myworkdayjobs.com
    # (Gen Digital's), Riskified/novartis.wd3.myworkdayjobs.com, SupPlant/careers.workable.com.
    # Path-tenant platforms (greenhouse, lever, ashby, comeet, recruitee) are left to
    # `_slug_matches` and the existing gates: applying near-equality there rejected 81 of the
    # 460 active ATS rows, nearly all of them legitimate (Mobileye, Applied Materials/amat,
    # SentinelOne/sentinellabs), and a gate with that false-negative rate costs more coverage
    # than the mis-attribution it prevents. Widening it is BACKLOG 21, in company_identity,
    # where the per-platform table already lives.
    labels = [l for l in host.split(".")[:-2] if not _plumbing(l)]
    if not labels:
        return True                                    # no checkable tenant: cannot tell
    return any(near(l) for l in labels)


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


def _serpapi(name, limit=5):
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
    return [u for u in urls if u and not is_aggregator(u)][:limit]


_SEARCH = {"tried": 0, "produced": 0, "warned": False, "recent": []}
_SEARCH_MIN = 10   # below this, "found nothing" is about the companies, not the ladder


def serp(name, limit=5):
    """Find a company's careers page by SEARCHING. Three rungs, in cost order.

    This was SerpApi-ONLY, with no fallback, and the free quota has been exhausted since
    mid-August (checked 2026-08-23: `total_searches_left: 0`, `this_month_usage: 250`,
    resets 2026-09-01). `_serpapi` therefore returns [] *before it makes a request*, which
    means phase 2 of the Sunday audit — the search that finds boards which MOVED rather than
    broke — has been a silent no-op over the whole ~255-row parked pool. `resolve_broken`
    got exactly this fallback on 2026-08-23 and it was never propagated here.

    DuckDuckGo is free and works from the runners; it is rate-limited from the dev machine
    and returns 0 intermittently (measured 2026-08-23: 4 results, then 0, for the same
    query), which is why it can never be the only rung either. The unlocker is capped by
    DEEP_BD_SEARCH_CAP.

    That cap is **per process, not shared with `deep_validate`** - the counter is a module
    global, and the two tools run in separate processes (and on different days). Two places
    said "shares its counter with deep_validate"; nothing enforces that, and believing it
    means believing a Sunday audit and a Saturday deep-validate cannot together exceed the
    cap. They can, by exactly 2x. docs/BACKLOG.md 10 and 20 both record this.
    """
    _SEARCH["tried"] += 1
    urls = _serpapi(name, limit)
    if urls:
        _SEARCH["produced"] += 1
        return urls
    try:
        from deep_validate import ddg
        urls = [u for u in (ddg(name) or []) if not is_aggregator(u)][:limit]
    except Exception:  # noqa: BLE001
        urls = []
    if urls:
        _SEARCH["produced"] += 1
        return urls
    try:
        from deep_validate import google_via_unlocker
        urls = [u for u in (google_via_unlocker(name) or []) if not is_aggregator(u)][:limit]
    except Exception:  # noqa: BLE001
        urls = []
    if urls:
        _SEARCH["produced"] += 1
    _SEARCH["recent"].append(bool(urls))
    del _SEARCH["recent"][:-_SEARCH_MIN]
    if (not _SEARCH["warned"] and len(_SEARCH["recent"]) >= _SEARCH_MIN
            and not any(_SEARCH["recent"])):
        # Every rung fails by returning [], so "no company matched" and "we cannot search at
        # all" look identical in the log. But ONE empty result is about that company, not
        # about the ladder — warn on the RATE. On a TRAILING window, not the whole run: the
        # first version gated on `produced == 0` for the run, so a single productive search
        # anywhere permanently disarmed it and a ladder that died at row 40 of 255 was never
        # reported. A whole audit that found nothing is a broken run, not a measurement (§8).
        _SEARCH["warned"] = True
        _left = "exhausted" if _SERP["left"] == 0 else (
            "no key" if _SERP["left"] is None else _SERP["left"])
        print(f"::warning::audit_empty_rows: {_SEARCH_MIN} consecutive searches produced no "
              f"URL ({_SEARCH['produced']}/{_SEARCH['tried']} productive so far; "
              f"serpapi={_left}, brightdata="
              f"{'set' if os.environ.get('BRIGHTDATA_API_KEY') else 'MISSING'}) — the search "
              "ladder is down; recovered-board counts from this run are not a measurement",
              flush=True)
    return urls


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


def comeet_static_try(name, html):
    """COMEET.init widgets don't expose window.comeetvar — but the page HTML carries the
    long hex token plus a handful of hex uid candidates. Probe uid×token combinations
    against the careers-api (QA-discovered on KELA: 'dark' verdict, live 8-job board)."""
    mtok = re.search(r'"token"[: ]+"([A-F0-9]{20,})"', html or "")
    if not mtok:
        return None
    token = mtok.group(1)
    uids = list(dict.fromkeys(re.findall(r"\b[0-9A-F]{2}\.[0-9A-F]{3}\b", html)))[:6]
    for uid in uids:
        api = f"https://www.comeet.com/careers-api/2.0/company/{uid}/positions?token={token}"
        try:
            n_all, n_il = verify(name, "comeet", uid, api)
            return ("comeet", uid, api)
        except Exception:  # noqa: BLE001
            continue
    return None


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
    # {name: last-audited ISO date}. This was a bare append-only LIST, i.e. a once-EVER gate:
    # 721 names had accumulated and 130 currently-parked rows could never be re-audited, no
    # matter how stale their verdict. A company with no roles in March may have ten in August.
    try:
        raw = json.load(open(done_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raw = {}
    if isinstance(raw, list):        # migrate: age the backlog out over AUDIT_TTL_DAYS
        raw = {n: TODAY for n in raw}   # rather than re-opening all 721 in one run
    done = raw

    def _fresh(name):
        d = done.get(name)
        if not d:
            return False
        try:
            return (dt.date.today() - dt.date.fromisoformat(d)).days < AUDIT_TTL_DAYS
        except Exception:  # noqa: BLE001
            return False

    budget = float(os.environ.get("AUDIT_TIME_BUDGET_MIN", "90") or 0)
    t_start = time.time()
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    parked = [(i, r) for i, r in enumerate(rows)
              if r and len(r) >= 6 and r[4] == "false" and not _fresh(r[0])
              and in_pool(r[5] or "")
              # `in_pool` treats only defunct/domain-dead/duplicate/redundant/recruiter as
              # terminal — `alias-of` is NOT in pipeline/verdicts.TERMINAL (see
              # docs/BACKLOG.md). An alias row is the SECOND row for a company we already
              # scan at the same board, so this tool would search, find that same working
              # board, verify it with real Israel jobs and re-activate the duplicate —
              # publishing every eBay role twice. `listing_hunt` and `deep_validate` both
              # spell the exclusion out; this one relied on `in_pool` and did not.
              # Measured 2026-08-23: 2 rows in the pool (GE HealthCare Israel, eBay Israel).
              and not TERMINAL.search(r[5] or "")
              # and an agency is never activated by any other path either (3 rows)
              and not is_recruiter(r[0])]
    # oldest first, so a quota- or time-capped run still walks the whole backlog over weeks
    parked.sort(key=lambda ir: done.get(ir[1][0], ""))
    print(f"{len(parked)} parked rows to audit ({len(done)} audited before, "
          f"{sum(1 for n in done if _fresh(n))} still fresh); "
          f"SerpApi spent only when needed\n", flush=True)

    def _mark(name):
        # atomic, like every other state write in this lane: `open(...,"w")` truncates
        # immediately, so a kill mid-write leaves a short file that parses as "audited
        # nothing" and silently re-audits the whole backlog
        done[name] = TODAY
        write_json(done_path, done, indent=0, sort_keys=True)

    fixed, unsupported, still = [], [], []
    for _n, (i, r) in enumerate(parked, 1):
        if budget and (time.time() - t_start) / 60 > budget:
            # This tool had no budget at all. Locally that looked fine because
            # `state/audit_done.json` holds hundreds of TTL-fresh entries — but `state/` is
            # gitignored, so in Actions `done` is EMPTY and the run walks all ~255 rows, each
            # now costing up to two 15s DuckDuckGo timeouts on top of the fetches. It shares
            # audit-coverage.yml's 330-minute job with five other steps, and the commit runs
            # last: overrun discards the whole Sunday, wayback_rescue and validate_empty
            # included. Rows not reached keep their notes; `parked` is sorted oldest-first,
            # so the next run starts where this one stopped.
            print(f"time budget {budget}min reached at {_n}/{len(parked)} — stopping cleanly",
                  flush=True)
            break
        name, url = r[0], r[3]
        _mark(name)
        # direct careers URL first; SerpApi only as fallback (723-row backlog vs 250/mo budget)
        direct = [] if is_aggregator(url or "") else [url]
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
        if not n_all:
            # `verify()` returning (0, 0) is not a recovery. This branch ACTIVATES, and
            # `n_all == 0` is exactly the `empty-board` shape section 2 warns about: a dead
            # token and a live-but-empty board are indistinguishable from here. Activating on
            # it re-creates the 0/0 rows the self-heal exists to clean up.
            still.append((name, ""))
            print(f"  [--] {name}: {plat}:{tok} verified but returned 0 jobs - not a recovery",
                  flush=True)
            continue
        # An acquirer's tenant is indistinguishable from theft by string alone - on the
        # subdomain platforms `Habana Labs (Intel)` really does post under `intel`, and 31
        # active rows are in that shape - so a tenant mismatch gets a SECOND chance from page
        # content, the same discriminator crack_walled uses. Only a row that fails both is
        # refused. (docs/BACKLOG.md 21 is why a bare tenant block is not acceptable here.)
        # NOTE: `tenant_is_this_company` returns True in two different situations -
        # "the tenant is near-equal to the name" and "there is nothing here to check" - and
        # accepting the second as confirmation skips the page read below on 382 of the 460
        # active ATS rows (358 path-tenant platforms it does not scope, 24 with no checkable
        # subdomain label), leaving plain containment (`_slug_matches`) deciding them.
        #
        # The obvious fix - require a POSITIVE near-equality match, else fall through to the
        # page read - was built, measured and REVERTED on 2026-08-24. On exactly the
        # platforms it would newly gate, there is no page to read:
        #
        #   fetch("https://boards-api.greenhouse.io/v1/boards/fiverr/jobs")        -> 0 bytes
        #   fetch("https://www.comeet.co/careers-api/2.0/company/60.002/positions")-> 0 bytes
        #   fetch("https://api.ashbyhq.com/posting-api/job-board/deel")            -> 28 bytes
        #
        # `_page_names_company` needs 2000 chars to answer anything but `None`, so the
        # "fall through" refuses all 358 rows and stamps a false verdict on each - the same
        # over-block wave 8 caught in `deep_validate`, one tool over. docs/BACKLOG.md 33
        # carries the measurement and the two fixes that would actually work.
        _tenant_ok = tenant_is_this_company(name, api or "")
        if not _tenant_ok:
            # SECOND CHANCE - from the CANDIDATE page, and only from it.
            #
            # This read `fetch(r[3])` as a fallback until 2026-08-24. `r[3]` is the row's
            # OWN stored careers url, so the check found the company's name on the company's
            # own website and accepted that as proof that a THIRD PARTY's board belongs to
            # it. It rubber-stamped every mismatch this gate exists to catch:
            #
            #   Riskified -> novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/riskified/jobs
            #     tenant_is_this_company -> False   (the gate worked)
            #     page_mentions_company("Riskified", <riskified.com>) -> True  (override)
            #
            # and it was not a corner case but the default path: a plain GET of the
            # endpoints this tool proposes returns "" (Workday `/wday/cxs/...` is POST-only,
            # Greenhouse blocks the UA), and 236 of the 255 rows in the Sunday pool carry an
            # http url for it to fall back to. Unreadable candidate == no evidence == refuse.
            # Use `crack_walled._page_names_company`, not a local
            # `bool(fetch(...)) and page_mentions_company(...)`. The local form was a
            # two-valued copy of a three-valued predicate: it folds "could not read the
            # page" into "the page names someone else", and - more to the point - it skips
            # the residential-unlocker fallback and the retry that strips generic and
            # geographic words from the company name. That retry is not decoration: 46 rows
            # are named `<something> Israel`, and their boards are titled without it.
            #
            # ARCHITECTURE.md section 2 claimed all five write paths ran through the shared
            # predicate while this tool and `repair_dead_urls` each carried their own. A
            # doc-level claim of shared behaviour over two silently diverging copies is the
            # bug class this lane exists to remove, so the copies go rather than the claim.
            #
            # Lazy import: `crack_walled` imports this module, so a module-level import is a
            # cycle. docs/BACKLOG.md 30 proposes lifting the gate into `pipeline/`.
            from crack_walled import _page_names_company
            _tenant_ok = _page_names_company(name, api or "") is True
        if is_foreign(name, api or "") or not _tenant_ok:
            # Identity gate: this tool SEARCHES for a board, which is exactly how you end up
            # holding another company's — and it verifies, with real jobs. Refuse it.
            #
            # `is_foreign` alone is not that gate: it returns False for EVERY ATS host, which
            # is 460 of the 846 active rows. This file DEFINES `tenant_is_this_company` for
            # precisely this case and `main()` never called it - so a search that proposed
            # `novartis.wd3.myworkdayjobs.com/riskified` for Riskified passed both
            # `_slug_matches` (containment) and `is_foreign` (constant False) and activated.
            # Scoped to subdomain-tenant platforms, so the 36 legitimate acquirer boards
            # (Momentis/memic, Habana/intel) are untouched - see docs/BACKLOG.md 21.
            still.append((name, ""))
            print(f"  [XX] {name}: {plat} {tok} verified {n_il} IL but the board belongs to "
                  f"another company ({(api or '')[:44]})", flush=True)
            continue
        fixed.append((name, plat, n_all, n_il))
        print(f"  [OK] {name}: {plat} {tok} -> {n_all} jobs / {n_il} IL", flush=True)
        if apply:
            # re-read before every write (single-writer discipline) AND write incrementally
            # so a killed run never loses verified fixes
            fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
            for fr in fresh:
                if fr and fr[0] == name and len(fr) >= 6:
                    fr[1], fr[2], fr[3] = plat, tok, api
                    fr[4] = "true"
                    # Append-log, not a rewrite (ARCHITECTURE.md section 2). This branch
                    # overwrote the WHOLE cell, which is how an activation silently deleted
                    # `alias-of` / `domain-dead` / the `dark-triage` mode and every other
                    # tool's verdict — the row then matched no pool if it was ever parked
                    # again. `replace_own` re-stamps only this tool's own segment.
                    fr[5] = _note_replace(
                        fr[5], "re-audit",
                        f"re-audit {TODAY}: verified {n_all}/{n_il} IL (was false-empty)")
            write_csv_rows("companies.csv", fresh)
    print(f"\n=== recovered {len(fixed)} boards · unsupported-ATS {len(unsupported)} · "
          f"still dark {len(still)} ===")


if __name__ == "__main__":
    main()
