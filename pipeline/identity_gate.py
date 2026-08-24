"""The one identity gate every registry writer consults before writing `api_url`/`active`.

"There are Israel jobs on this page" is not "these are THIS company's jobs": activating a
row onto another company's board publishes one company's roles under another's name (FairFly
off fireflyspace.com, SimilarTech off Similarweb, Bancor onto The Bancorp Bank, Lili onto Eli
Lilly). The rules, each with its one-line reason, are on the functions below; the
measurements behind them -- do not re-litigate -- are in
docs/decisions/2026-08-24-identity-gate-calibration.md. The short version:

* `company_identity.is_foreign` is False on EVERY ATS host by design (an acquirer's tenant
  is legitimate), so on ATS rows it is not a gate at all.
* the tenant string is evidence in neither direction (a veto costs 24 real acquisitions;
  `verdict()` is wrong both ways); a mandatory page read costs 358 path-tenant rows whose
  endpoints return 0-28 bytes. So: a readable page decides both ways; the tenant admits
  only where nothing is readable; a board found INSIDE a held page must vouch for itself.
* DECLARED identity (`pipeline/identity_facts.py`) is consulted before any of this and is
  authoritative for declared rows.

lane: `registry` owns the behaviour; the module is `pipeline/` because the root tools import
it at module level (a gate reachable only through a lazy import is invisible to static
checks -- docs/BACKLOG.md 30). Changing it affects `ats-fetch`, `scraper` and `infra`.
"""
from __future__ import annotations

import os
import re
import ssl
import urllib.parse
import urllib.request

from pipeline import identity_facts
from pipeline.company_identity import (ATS_HOST, is_foreign,
                                       looks_like_a_job_listing_page, page_mentions_company)

# ---------------------------------------------------------------------------------------
# WHICH GATE DOES MY TOOL CALL?  Four public gates; picking the wrong one is how a held page
# came to ADMIT a board it merely embedded (wave-4 R1).
#
#   your tool holds a PAGE and found a board embedded in it -> embedded_board_ok  (+ activation_ok)
#   your tool built a whole row from VERIFIED job counts    -> activation_ok
#   your tool wants to PERSIST an address, no job counts    -> ok_to_write
#   your tool hunts/repairs an ORDINARY careers page        -> identity_ok
#
# The caller lists below are DERIVED over the registry WRITERS (tests/test_registry.py
# scans them with tools/mutate.py's call-site detector and compares); edit a caller and
# this goes red. Read-only tools that call a gate to REPORT it (registry_health --explain)
# are not callers in this sense.
# ---------------------------------------------------------------------------------------
GATE_CALLERS = {
    "activation_ok": ("auto_expand.py", "bd_rescue.py", "retry_unreachable.py",
                      "validate_empty.py", "wayback_rescue.py"),
    "ok_to_write": ("crack_walled.py",),
    "identity_ok": ("listing_hunt.py", "repair_extract_gap.py"),
    "embedded_board_ok": ("bd_rescue.py", "validate_empty.py", "wayback_rescue.py"),
}

# `scan_dead_domains.alive()` uses a lenient context on purpose — ARCHITECTURE.md section 2:
# "strict TLS on the scanning machine produced 6 false positives". A gate that re-introduces
# strict TLS re-introduces those.
_LENIENT = ssl.create_default_context()
_LENIENT.check_hostname = False
_LENIENT.verify_mode = ssl.CERT_NONE

# "Microsoft Israel" on a page that only ever says "Microsoft" is still Microsoft's page.
_NAME_STOP = {"israel", "israeli", "ltd", "ltd.", "inc", "inc.", "the", "group",
              "technologies", "technology", "labs", "systems", "solutions", "company",
              "companies", "corp", "corporation", "holdings", "international", "global",
              "studios"}

# Paid-call budget for the unlocker rung below. BACKLOG 36 filed the rung as uncapped
# spend; closing BACKLOG 59 put the key on two Sunday cron steps, which armed it (wave-6
# R3: ceiling 69+9 calls/Sunday, growing with the pool, vs bd_rescue's own triple-capped
# <=600/night). One process = one workflow step, so a per-process counter IS the per-step
# cap. Exhausted, the rung is skipped and the page honestly reads None -- identical to the
# key being absent for that row.
_UNLOCK_BUDGET = int(os.environ.get("PAGE_UNLOCK_BUDGET", "100") or 0)
_UNLOCK_SPENT = 0

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# The walled / multi-tenant ATS hosts. Kept as HOSTS on purpose — see `is_walled`.
_WALLED_HOST = re.compile(
    r"(icims\.com|myworkdayjobs\.com|eightfold\.ai|avature\.net|oraclecloud\.com|"
    r"ultipro\.com|phenompeople\.com|phenom|jobvite\.com|taleo\.net|successfactors|"
    r"hibob\.com|applytojob\.com)", re.I)

# WALL names, not fetcher names. `host_platform` answers "which walled ATS is this row
# stuck behind" and its names key `crack_walled._HOST_PATTERNS`. The registry's col-1
# holds FETCHER names -- what fetches the board once cracked -- and for Oracle the two
# legitimately differ: the wall is `oraclecloud`, the fetcher is `oraclehcm`
# (`registry_health._FETCHER_ALIAS` owns that mapping). Two questions, two tables;
# "unifying" them re-introduces the mis-join it looks like it fixes.
_PLATFORM_ALIAS = {"eightfold.ai": "eightfold", "phenom": "phenom", "icims.com": "icims",
                   "successfactors": "successfactors", "oraclecloud.com": "oraclecloud",
                   "avature.net": "avature", "jobvite.com": "jobvite", "taleo.net": "taleo",
                   "phenompeople.com": "phenom", "ultipro.com": "ultipro",
                   "myworkdayjobs.com": "workday", "hibob.com": "hibob",
                   "applytojob.com": "applytojob"}

def host_platform(url):
    """Platform name from the row's stored URL — durable data, unlike a note segment."""
    host = (urllib.parse.urlparse(url or "").netloc or "").lower()
    m = _WALLED_HOST.search(host)
    if not m:
        return None
    return _PLATFORM_ALIAS.get(m.group(1).lower(), m.group(1).lower())


def is_walled(row):
    """Is this row in the walled-ATS pool? DURABLE data (the stored host) first, the
    `unsupported ATS` note token second -- that token lives inside deep_validate's own
    segment, which `notes.replace_own` rewrites, and a pool that is another tool's string
    went 25 -> 0 in one simulated night with every guard green. See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    note = row[5] if len(row) > 5 else ""
    return ("unsupported ATS" in (note or "")
            or host_platform(row[3] if len(row) > 3 else "") is not None)


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


# A tenant slug routinely carries a legal or numeric suffix the registry name omits:
# wizinc/Wiz, gongio/Gong, outbraininc/Outbrain, playtikaltd/Playtika,
# tipaltisolutions/Tipalti (hippo70/Hippo Insurance is NOT handled: measured wave 5). Requiring near-equality without stripping these
# rejected 99 of the 460 active ATS rows. Stripping is safe in the direction that
# matters: `bancorpbank` and `bitdefender` carry no such suffix, so they still fail.
_TENANT_SUFFIX = re.compile(
    r"(inc|ltd|llc|plc|corp|co|io|ai|hq|com|group|holdings|solutions|technologies|"
    r"labs|global|international|\d+)+$")


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


def _name_targets(name):
    """The normalized forms of a registry name a tenant token may near-equal: the whole
    name and its filler-stripped core. NOTHING else. An `A (B)` parenthetical is no longer
    split into an alias: that heuristic admitted exactly the seven acquisitions it was
    built for (now DECLARED in pipeline/identity_facts.py -- measured, no other row
    depended on it) and, on `Dun & Bradstreet (Israel) Ltd.`, made bare `israel` an
    identity target (wave-6 R1, B1). A declared row never reaches this function; an
    undeclared one gets exactly its own name. To make an acquisition legitimate, declare
    it -- do not teach this function another string trick."""
    from pipeline.company_identity import _norm
    v = name or ""
    core = _norm("".join(w for w in re.findall(r"[A-Za-z0-9]+", v)
                         if w.lower() not in _NAME_FILLER))
    return {t for t in (_norm(v), core) if t and len(t) >= 2}


def _tenant_near(candidate, targets):
    """Tight near-equality between one tenant token and the name forms. NOT containment:
    `Bancor`/`bancorpbank` and `Bit`/`bitdefender` must fail -- the same lesson
    `company_identity` learned for domains (rad.com/RADLogics)."""
    from pipeline.company_identity import _norm
    nc = _norm(candidate)
    if not nc:
        return False
    forms = {nc, _TENANT_SUFFIX.sub("", nc)}
    # A form or target under 3 chars must match EXACTLY: the +-1-with-containment window
    # collapses at that length -- `_TENANT_SUFFIX` digit-stripping turns the Comeet uid
    # `F2.004` into `f`, which is contained in `f5`, and `hp` admits `hpe` (wave-6 R3's
    # cross-accept inventory). `hp`'s own tenant `hp` still matches by equality.
    return any(f and (f == t if min(len(f), len(t)) < 3
                      else abs(len(f) - len(t)) <= 1 and (f in t or t in f))
               for f in forms for t in targets)


# Words a PATH-tenant slug appends that a registry name omits. `_TENANT_SUFFIX` (legal/
# geographic ABBREVIATIONS, calibrated on subdomain labels) misses whole words: real
# own-board slugs `armissecurity`, `khealthcareers`, `bluevineisrael`, `venncity` were all
# refused -- 44 rows on the wave-5 sweep. Words only, stripped from the END, so
# `bancorpbank` (bank deliberately absent) and `elililly` are untouched and the recorded
# incidents stay refused.
_EMBED_TOKEN_WORDS = re.compile(
    r"(careers|career|jobs|job|security|israel|tech|technologies|technology|labs|"
    r"networks|network|city|medical|global|digital)$")


def _embed_token_forms(token):
    """The candidate forms of an extracted tenant token: as-is, then generic tail words
    stripped one at a time. Each form still goes through `_tenant_near`'s tight rule."""
    forms, t = [], (token or "")
    while t and t not in forms:
        forms.append(t)
        t = _EMBED_TOKEN_WORDS.sub("", t)
    return forms


def embedded_board_ok(name, token, api_url):
    """May a board found INSIDE a held page be written onto this row?

    The callers that hold a page (`validate_empty`, `bd_rescue`, `wayback_rescue`) run
    `extract_ats` on the row's careers page, so `api_url` is whatever board the page EMBEDS
    and the page's affirmative answer is about the page, not the board -- a held page can
    REFUSE a board, never ADMIT one (Cogniteam's own page promoted Riskified's board). So the
    board vouches for itself: subdomain mismatch refuses; a DECLARED row's own token decides;
    otherwise the token must near-equal the name. "Cannot tell" REFUSES here (visibly: the
    callers write a suspect note) -- Comeet uids and undeclared acquirer slugs are that
    class, docs/BACKLOG.md 61. See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    if not tenant_is_this_company(name, api_url):
        return False
    targets = _name_targets(name)
    if not targets:
        return False
    host = (urllib.parse.urlparse(api_url or "").netloc or "").lower()
    if _SUBDOMAIN_TENANT_HOST.search(host):
        # A checkable subdomain label already decided in the conjunct above -- the token
        # here would be DOUBLE jeopardy, and for Workday it is the composite
        # `tenant/site` string `extract_ats` returns, which `_norm` concatenates into
        # something no name can near-equal: 83 of 83 Workday rows refused their own
        # board, Intel included (wave-5 R1/R2). Only a host whose labels are all
        # plumbing (apply.workable.com) still needs the token to vouch.
        if [l for l in host.split(".")[:-2] if not _plumbing(l)]:
            return True
    # DECLARED identity decides first, both directions: the row's own token (registry
    # column 2 -- authoritative data, never a URL path) must be a declared tenant. This is
    # the path-tenant half of the declaration (subdomain hosts already returned above).
    # `.split("/")[0]` is defensive against Workday's composite `tenant/site` tokens, which
    # never reach here; no test may claim it is what makes Workday work.
    declared = identity_facts.tenants(name)
    if declared:
        return identity_facts.normalize((token or "").split("/")[0]) in declared
    return any(_tenant_near(c, targets) for c in _embed_token_forms(token))


def tenant_is_this_company(name, url):
    """Does an ATS URL's TENANT belong to `name`? Use INSTEAD of `is_foreign` on ATS hosts.

    Order: not an ATS host -> True (`is_foreign` is the right gate there); a path-tenant
    platform -> True (the tenant is the row's own token, checked by `embedded_board_ok`);
    a DECLARED row -> its declaration decides, both ways, against the host's non-plumbing
    subdomain labels only (never a path: novartis.wd3.../riskified is Novartis's); an
    explicit `verdict()` mismatch -> False; otherwise a subdomain label must NEAR-EQUAL the
    name (tight: `bancorpbank` is not `Bancor`), and a host whose labels are all plumbing
    cannot tell -> True. See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    import urllib.parse as _up
    from pipeline.company_identity import (ATS_HOST, verdict as _verdict,
                                           _slug_candidates, _norm)
    host = (_up.urlparse(url or "").netloc or "").lower()
    if not host or not ATS_HOST.search(host):
        return True
    # SCOPE FIRST. The `mismatch` test below must not run on a path-tenant platform: on
    # greenhouse, `Momentis Surgical` -> `memic` scores `mismatch` and is a LEGITIMATE
    # acquirer board (ARCHITECTURE section 2 cites it by name). Scoping after the mismatch
    # test blocked it, which is the 36-row (24 today) regression docs/BACKLOG.md 21 measured and
    # rejected. Only the subdomain-tenant platforms below are in scope.
    if not _SUBDOMAIN_TENANT_HOST.search(host):
        return True
    # DECLARED identity decides first, in BOTH directions, and before the string verdict
    # below can veto it: `Itamar Medical` -> zoll.wd5 scores `mismatch` and a declaration
    # must be able to override a string. Matched against the host's non-plumbing SUBDOMAIN
    # labels only -- never the path: `_slug_candidates` returns path segments in the same
    # list, and `novartis.wd3.myworkdayjobs.com/en-US/riskified` must stay Novartis's.
    declared = identity_facts.tenants(name)
    if declared:
        labels = [l for l in host.split(".")[:-2] if not _plumbing(l)]
        if not labels:
            return True                        # nothing checkable: unchanged
        return any(identity_facts.normalize(l) in declared for l in labels)
    if _verdict(name, url) == "mismatch":
        return False

    targets = _name_targets(name)
    if not targets:
        return True

    def near(c):
        return _tenant_near(c, targets)

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


def page_names_company(name, url, html=""):
    """Three-valued: True = the page names this company, False = it names someone else,
    None = could not read it, which is NO EVIDENCE and must not read as either.

    Prefer `html=` the caller already holds (a re-fetch is weaker evidence than what produced
    the candidate); lenient TLS on purpose; bot walls are retried through the unlocker under
    a per-process paid-call budget; `strict=True` needs the name's words consecutively, so a
    `_NAME_STOP`-stripped core is retried. Under 2000 chars nothing is evidence. See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    if not html:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            html = urllib.request.urlopen(req, timeout=25, context=_LENIENT).read(
                400000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            html = ""
    global _UNLOCK_SPENT
    if (len(html) < 2000 and os.environ.get("BRIGHTDATA_API_KEY")
            and _UNLOCK_SPENT < _UNLOCK_BUDGET):
        # A bot wall renders nearly empty; the residential unlocker sees what a browser sees.
        # Gate on the KEY, not on SCRAPE_VIA_UNLOCKER: audit-coverage.yml runs the crack tool
        # without that flag, and a missing flag must not silently downgrade the gate.
        #
        # `bd_rescue` is a ROOT module, so this is the one layering wart in this file. It is
        # deliberately lazy and inside try/except so importing this module never drags a root
        # module in. Moving `unlock` into `pipeline/` is filed as plumbing work.
        try:
            from bd_rescue import unlock
            _UNLOCK_SPENT += 1
            html = (html or "") + chr(10) + (unlock(url) or "")
        except Exception:  # noqa: BLE001
            pass
    if len(html) < 2000:
        return None                        # unreadable: no evidence either way
    if page_mentions_company(name, html, strict=True):
        return True
    core = " ".join(w for w in re.findall(r"[A-Za-z0-9]+", name or "")
                    if w.lower() not in _NAME_STOP)
    if core and core.lower() != (name or "").lower() and page_mentions_company(
            core, html, strict=True):
        return True
    return False


def ok_to_write(name, url, html=""):
    """May this url be written into the row's `api_url`? Positive confirmation only: a
    readable page that names the company, on something that looks like a listing page, on a
    host `is_foreign` does not reject. Unreadable (`None`) is refused -- a persisted address
    is what the hunt's fast path later activates on, and "we could not look" is not
    evidence. The tenant string is deliberately NOT a veto here, and the signature
    deliberately has no `platform` parameter (a parameter the body never reads is a slot for
    a transposition to hide in). See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    if is_foreign(name, url) or not looks_like_a_job_listing_page(url):
        return False
    return page_names_company(name, url, html=html) is True


def activation_ok(name, api_url, n_jobs=0, html=""):
    """May this row be ACTIVATED onto `api_url`? For tools that verified jobs first.

    Clauses, in order: zero `n_jobs` is the empty-board shape, refused; `is_foreign` (inert
    on ATS hosts) and `looks_like_a_job_listing_page` (a nav menu scores like a board under
    SCRAPE_ASSUME_IL); then a READABLE page the caller holds decides in BOTH directions; an
    unreadable one (machine endpoints, bot walls) falls through to `tenant_is_this_company`;
    a page FETCH is the last resort. Tenant-OR-page, not AND: requiring a page read where
    the tenant is undecidable refuses the 358 path-tenant rows whose endpoints return 0-28
    bytes. The ordering is the adjudication of a calibration dispute with both error cells
    non-empty -- do not tune it, declare the row instead (`pipeline/identity_facts.py`).
    See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    if not n_jobs:
        return False
    if is_foreign(name, api_url) or not looks_like_a_job_listing_page(api_url):
        return False
    # A page the CALLER holds decides in BOTH directions when readable; an unreadable one
    # falls through to the tenant clause. This ordering flipped once (page-first refused
    # Siemens Healthineers silently; tenant-first activated Cogniteam onto Riskified's
    # board) and is the adjudicated resolution of a both-cells-non-empty dispute -- see
    # docs/decisions/2026-08-24-identity-gate-calibration.md. Do not tune; declare.
    if html:
        v = page_names_company(name, api_url, html=html)
        if v is not None:
            return v is True
        # unreadable in hand: no evidence either way -- fall through to the tenant clause
    if tenant_is_this_company(name, api_url):
        return True
    if html:
        # page unreadable AND tenant mismatch/undecidable: nothing affirms this board.
        # (A re-fetch of `api_url` here would re-run the unlocker attempt the first call
        # already made; it cannot say more than that call did.)
        return False
    return page_names_company(name, api_url) is True


def identity_ok(name, url, html=""):
    """The gate for tools that hunt or repair an ordinary careers page, not just an ATS:
    `is_foreign` decides on ordinary domains (routing them through the page test would trade
    a real hole for silent exclusion -- measured at 358 rows); on an ATS host, `ok_to_write`.
    See docs/decisions/2026-08-24-identity-gate-calibration.md for the measurements."""
    host = (urllib.parse.urlparse(url or "").netloc or "").lower()
    # jobvite/taleo used to need their own branch here because `ATS_HOST` omitted them and
    # `is_foreign` refused their correct boards outright. `ATS_HOST` now names them
    # (docs/BACKLOG.md 42, closed), so they flow through the ordinary ATS path below --
    # `ok_to_write` is the identical expression the special branch carried.
    if is_foreign(name, url):
        return False
    if host and ATS_HOST.search(host):
        return ok_to_write(name, url, html=html)
    return True
