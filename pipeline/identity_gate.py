"""The one identity gate every registry writer consults before writing `api_url`/`active`.

**Why this module exists.** These predicates lived in `crack_walled.py` — a leaf tool — and
four other modules imported them, three of them *lazily from inside a function* to dodge an
import cycle (`crack_walled` imports `deep_validate` and `audit_empty_rows` at module level;
both imported back from `crack_walled` inside `main()`). A gate reachable only through a lazy
import is invisible to any static check of "does this tool gate its writes", which is exactly
the check the registry needs most. `docs/BACKLOG.md` 30.

**What it is for.** "There are Israel jobs on this page" is not "these are THIS company's
jobs". Activating a row onto another company's board publishes one company's roles under
another's name, on a public board and in an email. That has happened repeatedly: FairFly off
`fireflyspace.com` (25 Firefly Aerospace roles), SimilarTech off Similarweb's Greenhouse,
Bancor onto The Bancorp Bank's iCIMS, DiA Imaging Analytics onto `dia.mil`.

**The measurements that shaped it — do not re-litigate these** (`docs/BACKLOG.md` 21 and 33):

* `company_identity.is_foreign` returns `False` for **every** ATS host by design, because an
  acquirer's tenant is legitimate — Momentis Surgical really does post under `memic`. So on
  the ~461 active ATS rows, `is_foreign` is not a gate at all.
* A blanket tenant-mismatch veto refuses **36 legitimate acquisitions** (Momentis→memic,
  Habana Labs→intel, VMware→broadcom, Splunk→cisco) and 7 of the 9 active rows on
  `crack_walled`'s own target platforms — Oracle CX pod ids (`hctz`, `edel`, `iawmqy`) are
  opaque and can never near-match a name. Proposed and rejected three times.
* `company_identity.verdict()` is wrong in **both** directions: `mismatch` for correct rows
  (onsemi, Fortinet, Verint, Dell) and a plain `ats` for the two boards most needing refusal
  (Riskified→`novartis.wd3.myworkdayjobs.com`, Bancor→`careers-bancorpbank.icims.com`).
  **The tenant string is not evidence in either direction.**
* Requiring a page read where the tenant is undecidable refuses **358 path-tenant rows**:
  `boards-api.greenhouse.io/.../jobs` returns 0 bytes, `comeet.co/careers-api/...` 0 bytes,
  `api.ashbyhq.com/posting-api/...` 28 bytes, and `_page_names_company` needs 2000 chars to
  answer anything but `None`. Machine API endpoints are not readable pages — all 66 active
  Workday rows are `/wday/cxs/<tenant>/<site>/jobs`, which returns HTTP 400 on GET.

So: **page content is the only discriminator that works in both directions**, and the page
test is scoped to candidates that could plausibly BE a page.

lane: `registry` owns the behaviour; the module is `pipeline/` because five root tools import
it. Changing it affects `ats-fetch`, `scraper` and `infra`, which all read the registry.
"""
from __future__ import annotations

import os
import re
import ssl
import urllib.parse
import urllib.request

from pipeline.company_identity import (ATS_HOST, is_foreign,
                                       looks_like_a_job_listing_page, page_mentions_company)

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

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# The walled / multi-tenant ATS hosts. Kept as HOSTS on purpose — see `is_walled`.
_WALLED_HOST = re.compile(
    r"(icims\.com|myworkdayjobs\.com|eightfold\.ai|avature\.net|oraclecloud\.com|"
    r"ultipro\.com|phenompeople\.com|phenom|jobvite\.com|taleo\.net|successfactors|"
    r"hibob\.com|applytojob\.com)", re.I)

_PLATFORM_ALIAS = {"eightfold.ai": "eightfold", "phenom": "phenom", "icims.com": "icims",
                   "successfactors": "successfactors", "oraclecloud.com": "oraclecloud",
                   "avature.net": "avature", "jobvite.com": "jobvite", "taleo.net": "taleo",
                   "phenompeople.com": "phenom", "ultipro.com": "ultipro",
                   "myworkdayjobs.com": "workday", "hibob.com": "hibob",
                   "applytojob.com": "applytojob"}

# Hosts that ARE a multi-tenant ATS but are missing from `company_identity.ATS_HOST`, so
# `verdict()` compares the company against the ATS VENDOR's domain, returns `mismatch`, and
# `is_foreign` refuses a correct board outright — `Varonis -> jobs.jobvite.com/varonis` and
# `Radware -> radware.taleo.net/...`, URLs `crack_walled.listing_urls()` builds itself.
# Adding them to `ATS_HOST` is the proper fix: `docs/BACKLOG.md` 42. Delete this when it lands.
_ATS_NOT_IN_ATS_HOST = re.compile(r"(jobvite\.com|taleo\.net)", re.I)


def host_platform(url):
    """Platform name from the row's stored URL — durable data, unlike a note segment."""
    host = (urllib.parse.urlparse(url or "").netloc or "").lower()
    m = _WALLED_HOST.search(host)
    if not m:
        return None
    return _PLATFORM_ALIAS.get(m.group(1).lower(), m.group(1).lower())


def is_walled(row):
    """Is this row in the walled-ATS pool? DURABLE data first, note token second.

    The pool used to be the literal string `unsupported ATS` in the note and nothing else.
    That string is written by `deep_validate` inside ITS OWN segment
    (`deep-validated <date>: unsupported ATS icims.com`), and `pipeline.notes.replace_own`
    deletes a tool's previous segment when it writes a new one — by design. So every
    `deep_validate` verdict that is not `unsupported` silently removed the row from
    `crack_walled`'s pool, permanently.

    Measured on the real registry 2026-08-24: the token lived only inside `deep_validate`'s
    own segment on **24 of the 25** pool rows, and one simulated all-dark Saturday took the
    pool 25 -> **0**, with pytest, `check_invariants` and `registry_health` all green —
    no guard has a per-tool floor (`docs/BACKLOG.md` 34).

    A pool predicate must not be a string another tool owns and rewrites.
    """
    note = row[5] if len(row) > 5 else ""
    return ("unsupported ATS" in (note or "")
            or host_platform(row[3] if len(row) > 3 else "") is not None)


def page_names_company(name, url, html=""):
    """Three-valued: True = the page names this company, False = it names someone else,
    None = we could not read it, which is NO EVIDENCE and must not read as either.

    On a walled ATS the tenant lives in the SUBDOMAIN (`careers-bancorpbank.icims.com`), and
    `company_identity.verdict` only checks a tenant in the PATH — so it returns the blanket
    `"ats"`, which its own docstring defines as "we cannot tell", and `is_foreign` reads that
    as False. `_slug_matches("Bancor", "bancorpbank")` passes too, on plain containment. Both
    were true on 2026-08-23 and one `--apply` would have moved Bancor (Israeli crypto,
    ex-Bprotocol) onto The Bancorp Bank's iCIMS board: that page says "Bancorp" 18 times and
    Bancor-as-a-word zero times.

    The first version of this gate was a plain strict-TLS urllib fetch returning a bare bool,
    and review measured it False on **12 of 60 rows the pipeline had already verified as that
    company's own board** (Meta, Akamai, Ford, Microsoft Israel, ...). Three causes, each a
    paid-for lesson:

    1. **403 to a plain fetch** — `Bit`'s own careers page. The crack loop reaches these with
       Playwright, so re-fetching with urllib is strictly weaker evidence than the evidence
       that produced the candidate; prefer HTML the caller already has, via `html=`.
    2. **Strict TLS** — see `_LENIENT`.
    3. **`strict=True` wants the name's words consecutively**, so any row whose registry name
       carries a suffix the page omits fails structurally: 46 rows contain "Israel". Retry
       against the name with the generic/geographic words stripped.
    """
    if not html:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            html = urllib.request.urlopen(req, timeout=25, context=_LENIENT).read(
                400000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            html = ""
    if len(html) < 2000 and os.environ.get("BRIGHTDATA_API_KEY"):
        # A bot wall renders nearly empty; the residential unlocker sees what a browser sees.
        # Gate on the KEY, not on SCRAPE_VIA_UNLOCKER: audit-coverage.yml runs the crack tool
        # without that flag, and a missing flag must not silently downgrade the gate.
        #
        # `bd_rescue` is a ROOT module, so this is the one layering wart in this file. It is
        # deliberately lazy and inside try/except so importing this module never drags a root
        # module in. Moving `unlock` into `pipeline/` is filed as plumbing work.
        try:
            from bd_rescue import unlock
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
    """May this url be written into the row's `api_url`? Positive confirmation only.

    A tool has several exits and gating them individually is how two 0-Israel-jobs paths were
    missed: `crack_walled`'s `cracked-api` never called the gate at all, and `novrfy`
    persisted on an UNREADABLE page. This is the one check a write block runs regardless of
    which branch produced the candidate, so a future `return` that forgets the gate cannot
    re-open the hole. Unreadable (`None`) is refused: a persisted ADDRESS is what
    `listing_hunt`'s fast path later activates on, and "we could not look" is not evidence.

    **The tenant string is deliberately NOT a veto here** — see this module's docstring. It
    reads like the obvious extra safety net and it is wrong in both directions at once, so
    stacking it on top of a mandatory page test buys nothing and costs silent exclusion
    (ARCHITECTURE.md section 8's first bug class). Each false refusal also stamped a *wrong*
    `not this company's board` verdict into the row's note.

    Pass `html=` when the caller already has the page; it avoids a second fetch and is
    stronger evidence than a re-fetch (see `page_names_company` cause 1).
    """
    if is_foreign(name, url) or not looks_like_a_job_listing_page(url):
        return False
    return page_names_company(name, url, html=html) is True


def identity_ok(name, url, html=""):
    """The gate for tools that hunt or repair an ordinary careers page, not just an ATS.

    Scoped deliberately: the page test runs **only** on ATS hosts, where `is_foreign` is
    inert by design. On an ordinary careers domain `is_foreign` works and nothing changes,
    because `page_names_company` answers `None` for any page under 2000 chars and a great
    many legitimate company careers pages are JS-rendered — routing those through it would
    trade a real hole for silent exclusion, which is the mistake this lane has already made
    once and measured at 358 rows.
    """
    host = (urllib.parse.urlparse(url or "").netloc or "").lower()
    if host and _ATS_NOT_IN_ATS_HOST.search(host):
        # `is_foreign` is meaningless here (see `_ATS_NOT_IN_ATS_HOST`), so skip it for the
        # same reason it is skipped on every other ATS host, and let the page test decide.
        return (looks_like_a_job_listing_page(url)
                and page_names_company(name, url, html=html) is True)
    if is_foreign(name, url):
        return False
    if host and ATS_HOST.search(host):
        return ok_to_write(name, url, html=html)
    return True
