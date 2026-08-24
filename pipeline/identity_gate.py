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
# wizinc/Wiz, gongio/Gong, outbraininc/Outbrain, playtikaltd/Playtika, hippo70/Hippo
# Insurance, tipaltisolutions/Tipalti. Requiring near-equality without stripping these
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
    """The normalized forms of a registry name a tenant token may near-equal.

    A parenthetical is an ALIAS, not a suffix: 21 registry rows are named `A (B)` --
    `Merck (MSD)`, `VMware (Broadcom)`, `Habana Labs (Intel)` -- and concatenating both
    halves (`merckmsd`) produces a form no real tenant can near-equal, so every one of
    those rows refused its OWN board (wave-5 R2). Each half is its own target; the name
    itself declares the entity, so a tenant matching either half is that row's evidence.
    """
    from pipeline.company_identity import _norm
    variants = [name or ""]
    m = re.match(r"^(.*?)\((.*?)\)\s*(.*)$", name or "")
    if m:
        variants += [(m.group(1) + " " + m.group(3)).strip(), m.group(2).strip()]
    out = set()
    for v in variants:
        cn = _norm(v)
        core = _norm("".join(w for w in re.findall(r"[A-Za-z0-9]+", v)
                             if w.lower() not in _NAME_FILLER))
        out |= {t for t in (cn, core) if t and len(t) >= 2}
    return out


def _tenant_near(candidate, targets):
    """Tight near-equality between one tenant token and the name forms. NOT containment:
    `Bancor`/`bancorpbank` and `Bit`/`bitdefender` must fail -- the same lesson
    `company_identity` learned for domains (rad.com/RADLogics)."""
    from pipeline.company_identity import _norm
    nc = _norm(candidate)
    if not nc:
        return False
    forms = {nc, _TENANT_SUFFIX.sub("", nc)}
    return any(f and abs(len(f) - len(t)) <= 1 and (f in t or t in f)
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

    The callers that hold a page (`validate_empty`, `bd_rescue`) fetch the row's CAREERS
    page and run `extract_ats` on it -- so their `api_url` is whatever board that page
    EMBEDS, while their `html` is the page itself. `page_names_company`'s affirmative
    answer is about the page, and `activation_ok` treating it as evidence about the board
    promoted Riskified's Greenhouse onto Cogniteam's row off Cogniteam's OWN page carrying
    a stale shared-template embed (wave-4 R1, reproduced on the scheduled Sunday path;
    the SimilarTech-off-Similarweb incident is the same shape). A held page can REFUSE a
    board -- it names someone else -- but it can never ADMIT one.

    So the board must vouch for itself: an explicit subdomain-tenant mismatch refuses
    (Bancor / careers-bancorpbank.icims.com), and otherwise the extracted tenant token
    must near-equal the company name, by the same `_tenant_near` rule the subdomain check
    uses. "Cannot tell" (opaque Comeet uid, an acquirer's slug like Momentis->memic)
    REFUSES here, unlike in `tenant_is_this_company` -- because both callers surface the
    refusal visibly (a `suspect` line, a bd refusal print) on rows that stay parked with
    their re-check tokens, while a wrong acceptance ships another company's jobs. That is
    the census resolution's direction, applied to the same bar. Cost filed with the
    derivation: docs/BACKLOG.md 61.
    """
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
    return any(_tenant_near(c, targets) for c in _embed_token_forms(token))


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

    The signature deliberately has no `platform` parameter. It used to, the body read
    it nowhere, and a reviewer transposed `(name, platform)` at four call sites with
    the whole suite green -- `platform` absorbed the name and the identity decision
    silently ran on the platform string. A parameter that gates nothing is a slot for
    a transposition to hide in. (Transposing the two that remain is caught: a URL in
    the name slot fails every predicate and the positive controls go red.)

    Pass `html=` when the caller already has the page; it avoids a second fetch and is
    stronger evidence than a re-fetch (see `page_names_company` cause 1).
    """
    if is_foreign(name, url) or not looks_like_a_job_listing_page(url):
        return False
    return page_names_company(name, url, html=html) is True


def activation_ok(name, api_url, n_jobs=0, html=""):
    """May this row be ACTIVATED onto `api_url`? For tools that verified jobs first.

    The five schedule-driven tools that build a whole row literal
    `[name, plat, tok, api, "true", note]` -- `bd_rescue` and `retry_unreachable` (02:30
    daily), `wayback_rescue` and `validate_empty` (Sun 04:00), `auto_expand` (08:00/20:00) --
    had NO identity check of any kind until 2026-08-24. They were invisible to the guard in
    `tests/test_units.py`, which finds writers by looking for a subscript assignment to
    index 4 and therefore cannot see a list literal. Fourteen of the repo's 22 registry
    writers are that shape.

    The clauses, and why each is the one it is:

    * **`n_jobs`** -- a board that verifies with zero jobs is the `empty-board` shape, not a
      recovery. Callers pass whatever they actually counted (Israel jobs for a scrape row,
      total for an API row); zero from either is refused.
    * **`is_foreign`** -- the right gate on an ordinary domain, and inert on an ATS host,
      where it returns False by design for all ~461 active ATS rows.
    * **`looks_like_a_job_listing_page`** -- clause 3 of the activation rule
      (ARCHITECTURE.md section 2). Measured 2026-08-24: all 861 active rows pass it,
      including every machine API endpoint, so it costs nothing and catches a nav menu.
    * **the identity evidence** -- `html` if the caller already fetched the page (strictly
      stronger than a re-fetch, and free), else tenant-or-page.

    **Why tenant-OR-page and not tenant-AND-page.** `tenant_is_this_company` answers True
    when there is nothing checkable -- a path-tenant platform, an opaque Comeet uid. If a
    failure there fell through to a mandatory page read, the gate would refuse the 358
    path-tenant rows whose endpoints return 0-28 bytes (`boards-api.greenhouse.io` 0,
    `comeet.co/careers-api` 0, `api.ashbyhq.com/posting-api` 28) because
    `page_names_company` needs 2000 chars to answer anything but `None`. That was built,
    measured and reverted: `docs/BACKLOG.md` 33. And a tenant MISMATCH cannot be a veto on
    its own either -- it costs 36 legitimate acquisitions (item 21). So the tenant string
    admits; refusal needs page evidence.

    **What that costs, stated rather than implied.** `page_names_company` returns `None` for
    a page it could not read, and `is True` refuses `None` -- so on a subdomain-tenant host
    whose endpoint is a machine API (`/wday/cxs/<tenant>/<site>/jobs`, HTTP 400 on GET) a
    failed tenant near-match IS the refusal, because no page can ever be read there:

        activation_ok("Habana Labs (Intel)",
                      "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/x/jobs", 12)
        -> False        # a real acquisition, refused

    That is item 21's shape re-entering through the `None` branch rather than through a
    `mismatch` veto. It is accepted here deliberately and for a narrower reason than item 21
    covers: these five callers ACTIVATE a currently-parked row, so a wrong refusal leaves the
    row parked, visible and recoverable, while a wrong acceptance publishes another company's
    jobs under this company's name. Item 21 measured the cost of vetoing rows that were
    already ACTIVE, which is not this. `docs/BACKLOG.md` 49 carries the measurement; the fix
    is an `acquired-by` column, not a cleverer string test.
    """
    if not n_jobs:
        return False
    if is_foreign(name, api_url) or not looks_like_a_job_listing_page(api_url):
        return False
    # A page the CALLER already holds is decisive when it is readable -- in either
    # direction. This ordering is the resolution of a measured calibration dispute in which
    # both error cells were non-empty, and it has flipped once already, so the census is
    # recorded here rather than re-derived a third time:
    #
    #   * page-first, page-only (the first form): refused `Siemens Healthineers` on its own
    #     page (readable, says only "Siemens" -- `strict=True` wants the registry name's
    #     words consecutively), and the refusal was SILENT. That silence, not the refusal,
    #     was the blocking finding; the refusal path is visible now (`validate_empty`
    #     returns `suspect` and writes a note).
    #   * tenant-first (the second form): `tenant_is_this_company` answers True by VACUITY
    #     on every path-tenant platform (greenhouse/lever/ashby/comeet -- 6 of the 7
    #     platforms `extract_ats` can return), so the page in hand was never consulted and
    #     `Cogniteam` was activated onto Riskified's greenhouse board off a careers URL
    #     that no longer serves Cogniteam's page. A proven wrong write, on a schedule.
    #
    # No string predicate separates every wrong-page case from every name-shape mismatch
    # (`Sight` matches Sight Sciences' page and Sight Diagnostics is a different company on
    # that same board -- head-token matching is measured unsafe). So the rule follows the
    # bar: these callers ACTIVATE a parked row, where a wrong refusal is parked, visible
    # and recoverable, and a wrong acceptance ships another company's jobs. Readable page
    # evidence decides; only an UNREADABLE page (None -- machine endpoints, bot walls)
    # falls through to the tenant clause, which keeps the 358 path-tenant rows and the
    # filler-stripped-core rows activatable. The name-shape cost this accepts is filed
    # with the row names in docs/BACKLOG.md.
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
    """The gate for tools that hunt or repair an ordinary careers page, not just an ATS.

    Scoped deliberately: the page test runs **only** on ATS hosts, where `is_foreign` is
    inert by design. On an ordinary careers domain `is_foreign` works and nothing changes,
    because `page_names_company` answers `None` for any page under 2000 chars and a great
    many legitimate company careers pages are JS-rendered — routing those through it would
    trade a real hole for silent exclusion, which is the mistake this lane has already made
    once and measured at 358 rows.
    """
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
