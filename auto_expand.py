#!/usr/bin/env python3
"""Resolver for the names discovery finds. Each run takes the next batch of companies that are
researched but not yet in companies.csv, resolves them (iframe-ATS / scrape / follow-jobs-link
via resolve_deep), and writes results DIRECTLY into companies.csv + scraped_cache.json.

**It does NOT drain.** This docstring claimed until 2026-08-27 that it "keeps shrinking the
unresolved set every run until it reaches zero". Measured across one full day (2026-08-26):
414 -> 411 -> 408. The queue is 400 aggregator seeds out of 403 unmatched names, and every
aggregator seed needs the LLM tier, which is capped at LLM_RESOLVE_CAP (10) calls a run: the
08:00 run resolved 3 of 7 asked, the 20:00 run 0 of 9, and 241-243 names a run were deferred
at `cap` without being looked at. Normalising names against the registry does not help either
-- exact-name matching leaves 408 and `store._norm_company` leaves 403 (measured 2026-08-27).
So the drain rate is the tier's hit rate times its cap, and nothing else. The summary line
now reports `asked N (hopeless M)` so the two runs a day measure whether those calls could
have succeeded at all -- see `resolve_llm.own_pages_in_evidence` and docs/BACKLOG.md.

Env:  AUTO_EXPAND_LIMIT (default 200) companies per run; LLM_RESOLVE_CAP (default 10)
`claude -p` calls per run; AUTO_EXPAND_SEARCH_CAP (default 40) names that may enter the
LLM tier per run (each costs a free search and at most one capped unlock; a call is
charged only when a page was read, so the search cap is the one that paces the queue).
Prints the remaining-unresolved count so the workflow / log shows progress.

An AGGREGATOR seed (a LinkedIn / Indeed / secrethunter posting -- 338 of the 342 queued
names on 2026-08-25) never goes through `resolve_deep`: rendering that page can only yield
a refusal, `empty` or `unreachable` (its jobs are other employers'), and it used to cost
17-25 s of Playwright per name AFTER the LLM cap was spent -- 76 wasted minutes a run,
twice a day, with the 10 names that did get a shot buried as `scanned; no open Israel
roles now` with the aggregator shell as their address (docs/BACKLOG.md 177). Such a name
is now DEFERRED, never parked, and the tier walks the queue least-recently-tried first
(`cloud_state/auto_expand_seen.json` is the rotation key -- ARCHITECTURE.md section 2:
a budget without a rotation key re-walks the same prefix forever).

**This tool WRITES BY DEFAULT**, unlike every other registry tool, which is dry-run until
`--apply`. The auto-expand workflow invokes it with no flags, so the default cannot be
flipped from here without silently disabling the 08:00/20:00 cron (that is a workflow
change: docs/BACKLOG.md, "auto_expand writes by default"). Until then it says so on
startup, and `--dry-run` gives an agent a safe way to inspect the batch — added 2026-08-23
after a routine dry-run of the nightly chain appended two junk rows ("Qualitest acq",
"Keter", both on secrethunter.io aggregator URLs) to the live registry.

Usage: python auto_expand.py [--dry-run]
       python auto_expand.py --clear-agg-urls [--apply]   # un-bury rows parked on an
                                                          # aggregator seed (dry-run default)
"""
from __future__ import annotations

import sys

import csv
import json
import os
import re
import time
from urllib.parse import urlparse

from pipeline.aggregators import is_aggregator as _is_agg_url
from pipeline import identity_gate as _gate
from pipeline.companies import CSV_PATH, load_companies
from pipeline.company_identity import registrable
from pipeline.notes import append as _note_append
from resolve_deep import resolve

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



# ONE place, so BACKLOG 316's three disagreeing defaults become one. `auto-expand.yml` may
# still override it with AUTO_EXPAND_LIMIT; what it may not do any more is disagree silently.
AUTO_EXPAND_LIMIT_DEFAULT = 250

DRY_RUN = "--dry-run" in sys.argv
SEEN_PATH = os.path.join("cloud_state", "auto_expand_seen.json")

# The free rung's bounds. The 1,200 s that shipped on 2026-08-27 was reasoned from an
# 8-THREAD local sweep (5,212 requests, 293 s over 498 names) and production is
# single-threaded, so the clock bound the run instead of the batch: `cloud_state/
# auto_expand_seen.json` carries 238 stamps dated 2026-08-27 against a batch of 250, and the
# step log could not say so. A budget that decides coverage is a budget nobody asked for.
#
# So it is DERIVED from `limit`, the one knob `auto-expand.yml` already exposes: ask for 250
# names and the clock cannot stop you at 238; ask for 600 and one run drains the queue. The
# per-name pace is the measured single-threaded mean (4.7 s) with ~1.7x of headroom. The
# ceiling is not about this rung at all -- it is `concurrency: repo-state`, shared by eight
# workflows, whose smallest gap is 08:00 -> 10:00 firmographics.
PROBE_PACE_S = 8
RUN_CEILING_S_DEFAULT = 6600        # 110 min of the smallest `repo-state` gap (08:00 -> 10:00)
# One `resolve_deep` call's share of the run. It had NO bound: 35 s of Playwright plus
# `scrape_universal` at COMPANY_BUDGET_S=150, possibly twice, is ~342 s per name, and at
# LIMIT=250 an attacker computed the uncapped shape back at 4.4 h against a 330-minute job
# timeout. `resolve(..., budget_s=)` is the bound; this is what auto-expand asks for.
RESOLVE_BUDGET_S_DEFAULT = 180

# Every one of these is read INSIDE `main()`, never here. `DRY_RUN` below is bound from
# `sys.argv` at import and the module's own comment calls that out as the reason it cannot be
# tested; a budget read at module scope has exactly the same defect, and two guards written to
# prove the run deadline works passed against a 6,600 s ceiling the test had just set to 0.
PROBE_NAME_S = 12          # per name; the measured per-name maximum was 7.7 s
PROBE_NAME_REQ = 18        # 3 slugs x 6 platforms: the arithmetic ceiling of the policy
_SLUG_OK = re.compile(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]")



def _get_page(url, deadline, timeout=5, cap=400_000):
    """One GET, bounded in TIME as well as in bytes. Returns (final_url, html) or ("", "").

    `urlopen(timeout=)` is a per-operation timeout, not a total one, and `read(n)` caps
    BYTES. A server that dribbles slower than the timeout resets it on every recv: measured
    by an attacker on 2026-08-27, 10 bytes every 3 s against `timeout=5` ran 30 s for ten
    chunks, and at 400 KB that shape is ~33 HOURS for one TLD of one name. The host here is
    an arbitrary third-party domain reached from discovery intake, so this is not a
    hypothetical -- a CDN under load or a captive portal produces the same shape.
    """
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=timeout)
    except Exception:  # noqa: BLE001
        return "", ""
    buf, n = [], 0
    try:
        with resp:
            while n < cap:
                if time.time() > deadline:
                    break                      # the byte cap is not a time bound; this is
                chunk = resp.read(min(65536, cap - n))
                if not chunk:
                    break
                buf.append(chunk)
                n += len(chunk)
            return resp.geturl() or url, b"".join(buf).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return "", ""

def _lossless_slugs(name, li_slug=""):
    """Slug candidates that DROP NO WORD of the name, plus LinkedIn's own handle.

    `probe_ats.slug_variants` also offers `n.split()[0]`, `base+"inc"` and `base+"hq"`. The
    first-word variant is a NAME TRUNCATION, and it is not offered here, because the identity
    gate CANNOT catch what it produces. Measured 2026-08-27:

        Trigo Retail          -> smartrecruiters/trigo   149 jobs, every one in France
        Horizon Technologies  -> lever/horizon           "Horizon Robotics", Cupertino
        Ashley Digital        -> recruitee/ashley        New York

    and `activation_ok` returned True for 9 of 12 such hits. The reason is mechanical:
    `identity_gate._name_targets` pre-strips `_NAME_FILLER`, so `Horizon Technologies` yields
    the target `horizon` and `_tenant_near("horizon", ...)` is True -- while `Trigo Retail`
    yields only `trigoretail`, so the tenant test rates the IMPOSTOR above the real
    candidate. A page read does not rescue it either: `jobs.lever.co/horizon` is titled
    "Horizon Robotics" and `page_names_company("Horizon Technologies", ...)` still returns
    True, because it retries with the `_NAME_STOP`-stripped core -- the same truncation that
    produced the slug. Two independent-looking tests, one shared truncation (BACKLOG 317).

    The LinkedIn handle is the only identity a queue entry carries that is NOT name-derived
    (`Bond` -> `bondpersonalsecurity`), which is why it earns a slot of its own.
    """
    n = (name or "").lower().strip()
    base = n
    for junk in (" ", ".", ",", "’", "'", "-", "&", "(", ")", "|"):
        base = base.replace(junk, "")
    out, seen = [], set()
    for cand in (base, re.sub(r"[^a-z0-9]+", "-", n).strip("-"), (li_slug or "").lower().strip()):
        if cand and cand not in seen and _SLUG_OK.fullmatch(cand):
            seen.add(cand)
            out.append(cand)
    return out[:3]


# A posting that is a PLACEHOLDER, not an opening (BACKLOG 322). `il >= 1` is the rule that
# separates a real tenant from an impostor, and `israel.is_israel_job` reads only
# country_code/location/url -- never the title -- so `Ness Technologies` activated on
# smartrecruiters/`nesstechnologies` whose ONLY posting is titled "Test Job" at
# `Tel Aviv, , Israel`. The board is real and the tenant is right; the company simply is not
# using it. The row then removes the name from `_names_now()` and the queue never retries it:
# the cost is not the junk row, it is the company.
#
# Two rules, and the SECOND one is why this is not a keyword filter. Measured 2026-08-27 over
# the 1,175 postings in `scraped_cache.json`: 15 titles contain "test" and 13 of them are real
# engineering roles (`Experienced Test Engineer`, `CPU Design for Test Engineer, Google
# Cloud`, `Flight Tests Manager (ALPHA Team)`). All 13 are ADMITTED here, and the 2 that are
# not are `Testing JazzHR` and `Krume JazzHR Demo AS Omri Testing` -- both live, both on
# `myInterview`, an ACTIVE row that `listing_hunt` verified as "2 IL" on 2026-08-22.
_PH_MARK = frozenset("test testing tests demo dummy placeholder untitled asdf xxx qqq zzz "
                     "sample example ignore delete".split())
# generic words and ATS vendor names: what is left over in a placeholder title, and nothing
# a real role is named after. `Analyst`, `Engineer`, `Manager` are deliberately absent.
_PH_FILLER = frozenset((
    "job jobs position positions role roles posting postings vacancy vacancies opening "
    "openings new open my your first a an the of and or at to for in on do not apply please "
    "entry x 1 2 3 "
    "jazzhr greenhouse lever ashby ashbyhq comeet workable smartrecruiters recruitee breezy "
    "bamboohr applytojob teamtailor workday taleo icims jobvite phenom eightfold successfactors "
    "avature ultipro oraclecloud").split())
# letters and digits split, so `Test1` and `Test 1` cannot disagree about the same content
_PH_WORD = re.compile(r"[a-z]+|[0-9]+")


def is_placeholder_title(title):
    """True for a title that is an ATS test record rather than an opening.

    ONE rule: every word is either a marker or generic. `Test Job`, `Testing JazzHR`, `Job`,
    `New Position`, `Your first job` (Workable's shipped default), `Position 1`. A title with
    no ASCII words at all is NOT a placeholder -- a board that does not expose readable titles
    is unreadable, which is a different verdict from unreal.

    **There was a second rule and an adversarial pass killed it.** "Two markers anywhere" read
    as a strong signal and is not: `QA Test Engineer (Manual Testing)`,
    `Design for Test (DFT) Engineer - Silicon Test` and `Data Analyst, A/B Testing - Test &
    Learn Platform` all carry two, and all three are real roles this product exists to find.
    Worse, the calibration corpus could not catch it -- all 12 marker-bearing titles in
    `scraped_cache.json` carry exactly ONE marker, so every one of them is a single word away
    from being refused. The asymmetry decides it: a false refusal costs a COMPANY (BACKLOG
    322's whole point is that the cost is not the junk row), a false acceptance costs a junk
    row that four re-check pools will re-examine.

    The accepted cost of dropping it, stated rather than hidden: `Krume JazzHR Demo AS Omri
    Testing` is admitted, because `krume` and `omri` are neither markers nor generic. Its
    sibling on the same board, `Testing JazzHR`, is still refused -- and since the board-level
    rule needs EVERY Israel posting to be placeholder-like, `myInterview` is admitted. That
    row is named in the backlog instead.
    """
    words = _PH_WORD.findall((title or "").lower())
    if not words:
        return False
    return all(w in _PH_MARK or w in _PH_FILLER or w.isdigit() for w in words)


# The six guessable platforms as they appear in a stored URL, so a board held by a `scrape`
# row is still recognised as that board. Keep in step with `probe_ats._PLATFORMS`.
_ATS_PLAT = {"boards-api.greenhouse.io": "greenhouse", "boards.greenhouse.io": "greenhouse",
             "job-boards.greenhouse.io": "greenhouse", "api.lever.co": "lever",
             "api.eu.lever.co": "lever", "jobs.lever.co": "lever",
             "jobs.eu.lever.co": "lever", "api.ashbyhq.com": "ashby",
             "jobs.ashbyhq.com": "ashby", "api.smartrecruiters.com": "smartrecruiters",
             "careers.smartrecruiters.com": "smartrecruiters"}
_RECRUITEE_IN_URL = re.compile(r"https?://([A-Za-z0-9_-]+)\.recruitee\.com")
_ATS_IN_URL = re.compile(
    r"https?://(" + "|".join(re.escape(h) for h in _ATS_PLAT) +
    r")/(?:v1/boards/|v0/postings/|posting-api/job-board/|v1/companies/)?([A-Za-z0-9_-]+)")


def _boards_now():
    """Every (platform, token) the registry already reads. An exact key, not a name match.

    The probe rediscovers boards we ALREADY HAVE under a different company name -- 7 of the
    29 candidates on 2026-08-27, and in ALL SEVEN the platform and token were identical to
    the existing row's:

        Gong.io / Gong . Playtika Ltd / Playtika . Glassbox Ltd. / Glassbox . Nexar Inc. /
        Nexar . Unframe / Unframe AI . Oak / Oak - Identity Security OS . AutoDS - Automatic
        Dropshipping Tools / autods

    `_names_now()` cannot see this: it matches the name exactly and these differ by a legal
    suffix. A second ACTIVE row on one board republishes every role under two employer names
    -- what `ARCHITECTURE.md` section 2 calls `alias-of` and treats as terminal -- and
    `check_invariants` check B cannot catch it precisely BECAUSE the names differ.
    """
    out = set()
    for r in load_companies(CSV_PATH, active_only=False):
        plat = (r.get("ats_platform") or "").strip().lower()
        out.add((plat, (r.get("token") or "").strip().lower()))
        # ...and the board a `scrape` row is really reading. 7 rows sit on a guessable ATS
        # board while their platform column says `scrape` (Stigg -> jobs.ashbyhq.com/stigg,
        # Nuvo -> recruitee, Unity -> greenhouse). Keyed only on the column, those boards are
        # invisible to the duplicate check and the rung would open a SECOND active row on
        # them under a second employer name (attacker, 2026-08-27).
        for u in ((r.get("api_url") or ""), (r.get("token") or "")):
            m = _ATS_IN_URL.search(u or "")
            if m:
                out.add((_ATS_PLAT[m.group(1).lower()], m.group(2).lower()))
            m2 = _RECRUITEE_IN_URL.search(u or "")     # subdomain tenant, not a path one
            if m2:
                out.add(("recruitee", m2.group(1).lower()))
        # ...and the ADDRESS itself, keyed the way `check_invariants.shared_boards` keys it.
        # A token is one writer's SPELLING of a board, and two writers spell one board two
        # ways: `resolve_llm` returned the Workday site alone (`AristocratExternalCareersSite`)
        # where the registry stores the composite `tenant/site`, so the 12:53 run of
        # 2026-09-04 opened `Aristocrat` beside `Aristocrat (Product Madness)` on ONE
        # `api_url` with both (platform, token) lookups green, and only the suite's
        # `test_no_two_active_rows_share_a_board` noticed (BACKLOG 576). The url is what
        # both rows READ, so it is the key no spelling can dodge.
        k = _url_key(r.get("api_url"))
        if k:
            out.add(k)
    return out


def _url_key(api):
    """`("url", netloc, path)` of a board address, case- and slash-blind -- the same
    normalisation as `check_invariants.shared_boards`, so the gate and this guard agree."""
    u = urlparse((api or "").strip().lower().rstrip("/"))
    return ("url", u.netloc, u.path) if u.netloc else None


def _board_taken(plat, tok, api, boards):
    """Does the registry already read this board? By `(platform, token)` -- lower-cased on
    BOTH sides (the Comeet uid miss of 2026-08-27) -- or by the address itself."""
    if ((plat or "").lower(), (tok or "").lower()) in boards:
        return True
    k = _url_key(api)
    return bool(k) and k in boards


def _probe_resolve(name, li_slug, boards, deadline):
    """The free rung: an `_row_for_ats` payload, or (None, reason). Plain HTTP, no credits.

    Refusals in order, each measured rather than assumed:
      * no guessable board at all;
      * NO ISRAEL JOB on it -- the only discriminator that tracks truth here, and the rule
        that caught Lili -> Eli Lilly (`ARCHITECTURE.md` section 3). In the 2026-08-27 sweep
        it refused Agoda's 282 Bangkok roles, Armory, REAL, Clinch (Dublin) and Horizon
        (Cupertino), every one of which `activation_ok` was willing to admit;
      * TWO il-positive boards for one name -> defer, never choose. `Wayve` answers on
        greenhouse (4 IL) and ashby (3 IL); picking one would be picking by table order;
      * a board the registry already reads -> defer (see `_boards_now`).
    """
    slugs = _lossless_slugs(name, li_slug)
    if not slugs:
        return None, "probe-noslug"
    import probe_ats as _pa
    with _pa.bounded_http():
        hits = _pa.probe_bounded(name, slugs, deadline=deadline, budget=PROBE_NAME_REQ)
    live = [h for h in hits if h["il"] >= 1]
    if not live:
        # `probe-noboard` used to be `""`, which `main`'s `elif why:` dropped -- so the
        # `probe:` line reported refusals but never how many names the rung had WALKED, and
        # a reader could not tell 238 probed names from 31. That silence is what made the
        # 2026-08-27 run's coverage unreadable from its own log (BACKLOG 324).
        return None, ("probe-no-il" if hits else "probe-noboard")
    # `h["il_titles"]` must be NON-EMPTY for this to fire. `all()` over an empty list is
    # vacuously True, so without that clause a board reporting Israel jobs whose postings
    # carry no title at all was refused as a placeholder -- and "no titles" means the board
    # is unreadable, which is a different verdict from unreal. Caught by three existing
    # guards whose `probe_bounded` stubs predate the `il_titles` key.
    real = [h for h in live
            if not (h.get("il_titles") and all(is_placeholder_title(t) for t in h["il_titles"]))]
    if not real:
        # every Israel posting on every candidate board is an ATS test record. Counted and
        # NOT deferred (same shape as `probe-no-il`), so the name flows on to the rest of the
        # ladder and is re-probed tomorrow -- a placeholder is not a verdict on the company.
        return None, "probe-placeholder"
    live = real
    if len({(h["plat"], h["slug"]) for h in live}) > 1:
        return None, "probe-ambiguous"
    h = live[0]
    if _board_taken(h["plat"], h["slug"], h["url"], boards):
        return None, "probe-dup-board"
    # READ THE PAGE OURSELVES. `_row_for_ats` calls `activation_ok(nm, api, n_all)` with NO
    # html, so `board_vouches` -> None sends the gate to fetch `human_board_url` itself --
    # and when that fetch 404s or returns a JS shell, `page_names_company` falls through to
    # the PAID `bd_rescue.unlock` (`PAGE_UNLOCK_BUDGET` = 100 per process, and
    # `auto-expand.yml` sets BRIGHTDATA_API_KEY). An attacker demonstrated 5 paid calls from
    # 5 probe hits on 2026-08-27, and measured that 95 of the 498 queue names -- 19%, mostly
    # the LinkedIn-handle slugs this rung deliberately adds -- take that path. So the claim
    # "this rung is free" was FALSE, and it is made true here rather than asserted: we hold
    # a page of >= 2000 chars before the gate is asked, which is exactly the condition under
    # which it does not fetch and cannot unlock.
    human = _gate.human_board_url(h["url"]) or h["url"]
    _final, html = _get_page(human, deadline)
    if len(html) < 2000:
        return None, "probe-unread"
    return (h["plat"], h["slug"], h["url"], h["jobs"], h["il"], html), ""



def _today():
    import datetime as _dtm
    return _dtm.date.today().isoformat()


def _load_seen():
    """{name: date last given an LLM-tier shot}. Absent or unreadable -> {} (a rotation
    key, not a verdict: losing it costs order, never a row)."""
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            d = json.load(f)
        # only str dates sort against str; a hand-edited or merged value of another type
        # would TypeError the whole (non-continue-on-error) expand step (wave-1 F7)
        return {k: v for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


_LI_SITE = re.compile(r'data-tracking-control-name="about_website"[^>]+href="([^"?]+)', re.I)



SITE_BUDGET_S = int(os.environ.get("AUTO_EXPAND_SITE_BUDGET_S", "600"))
SITE_MAX = int(os.environ.get("AUTO_EXPAND_SITE_MAX", "25"))
_SITE_TLDS = ("com", "co.il", "ai", "io")


def _site_from_guess(name, handle, timeout=5, stats=None):
    """The company's own site, guessed from LinkedIn's handle and made to PROVE ITSELF.

    `_site_from_slug` below asks LinkedIn for the `about_website` link and got 0 of 3
    (BACKLOG 178), which is why it is off. This asks the INVERSE question, of the site rather
    than of LinkedIn: LinkedIn says this employer's handle is S -- does the page at
    `S.<tld>` link BACK to `linkedin.com/company/S`? That is a two-way binding neither side
    can fake alone, and it costs no LinkedIn budget at all.

    Measured 2026-08-27 over the 364 drainable names carrying a valid handle: 119 domains
    answered, 104 named the company, 53 carried the linkback, and 49 satisfied ALL THREE
    (the third being `not is_foreign`). The linkback is what makes it safe to use: the
    looser rule (name-on-page only) admits `agoda.com` and `iai.co.il`, and a WRONG
    own-domain page is worse than none, because it is exactly the evidence
    `resolve_llm._own_page_names_token` reads -- it would corrupt the one check the paid
    tier has. Evidence that can corrupt a verifier is held to the higher bar; relaxing it
    later is a measurement, not a guess.

    Returns (url, html) or None. `html` is >= 2000 chars by construction, which is also what
    keeps this rung FREE: `identity_gate.page_names_company` reaches the paid Bright Data
    unlocker only when the page it holds is under 2000 chars.

    `stats` is an optional Counter the rung STAMPS AS IT GOES, so a sweep can report the four
    numbers of 2026-08-27 (answered / named / linkback / all three) without a private mirror of
    this function's stages. Every early `return None` here is a real per-name outcome, and a
    rung that only reports its hits cannot be compared with itself a fortnight later.
    """
    def _no(why):
        if stats is not None:
            stats[why] += 1
        return None

    if not handle or not _SLUG_OK.fullmatch(handle):
        return _no("bad-handle")
    if stats is not None:
        stats["tried"] += 1
    deadline = time.time() + 4 * timeout       # a TOTAL bound across all four TLDs
    for tld in _SITE_TLDS:
        u = "https://%s.%s" % (handle, tld)
        final, html = _get_page(u, deadline, timeout=timeout)
        if not final:
            continue
        if len(html) < 2000:
            continue                       # under the gate's own evidence floor: not a page
        # THE FULL NAME, never the truncated core. `page_names_company` retries with the
        # `_NAME_STOP`-stripped core, which is the same truncation `_lossless_slugs` refuses
        # -- and it fired here: `PCB Technologies Ltd.` was "named" by pcb.com, the site of
        # PCB PIEZOTRONICS, because the core `PCB` appears on it (attacker, 2026-08-27).
        if stats is not None:
            stats["answered"] += 1
        # A PARKED DOMAIN NAMES THE COMPANY BY CONSTRUCTION -- a HugeDomains or GoDaddy
        # sale page displays the domain it is selling, and the domain is the company's name,
        # so `page_mentions_company` says yes and only the linkback stops it. Measured
        # 2026-08-29 over the 136 re-readable `no-linkback` names: **18 (13%) are parking
        # pages**, and 5 of the 9 false positives in the linkback-relaxation test were this
        # one class (`Gong.io` -> HugeDomains, `Mashbir` -> ExpiredDomains, `Monogoto` ->
        # Spaceship). Refused BEFORE the name test, because a page that is for sale is not
        # evidence about anybody. `confirm_zero._PARKED` is the shared pattern; this rung had
        # no reason to grow its own.
        from confirm_zero import _PARKED, _visible
        if _PARKED.search(_visible(html)[:4000]):
            return _no("parked-domain")
        if _gate.page_mentions_company(name, html, strict=True) is not True:
            return _no("not-named")        # a domain that answers but is not theirs: stop
        if stats is not None:
            stats["named"] += 1
        # ...and the linkback must be the WHOLE handle. `\b` fires on a hyphen, so `pcb` was
        # "proved" by `linkedin.com/company/pcb-piezotronics` and `ceva` by
        # `linkedin.com/company/ceva-sante-animale`: a PREFIX match, which is exactly the
        # truncation this rung exists to avoid, arriving through the other half of the same
        # test. Two independent-looking halves, one shared weakness -- the same shape as the
        # gate's own (BACKLOG 317), which is the thing to remember rather than the two fixes.
        if not re.search(r"linkedin\.com/company/" + re.escape(handle) + r"(?![a-z0-9-])",
                         html, re.I):
            return _no("no-linkback")      # no linkback: unproven, and unproven is refused
        # The address we keep is the REDIRECT TARGET, and nothing bound it to the domain we
        # guessed: an adversarial pass redirected a guess onto `comeet.com/jobs/<someone
        # else>/...` and onto `phoenixtma.com` (`company_identity`'s own example of a real
        # company that is not the right one), and `is_foreign` refused neither -- it is False
        # on every ATS host by design, and False for a `weak` verdict. `registrable` is the
        # binding: a legitimate `x.com -> www.x.com` keeps its registrable domain, a hop onto
        # somebody else's does not.
        if stats is not None:
            stats["linkback"] += 1
        if registrable(urlparse(final or u).netloc) != registrable(urlparse(u).netloc):
            return _no("redirected-off-domain")
        if _gate.is_foreign(name, final or u):
            return _no("foreign")
        if stats is not None:
            stats["kept"] += 1
        return (final or u), html
    return _no("no-domain-answered")

def _site_from_slug(slug, timeout=8):
    """The company's own website from its public LinkedIn company page -- the one
    non-aggregator seed intake can produce (BACKLOG 178; 399 of 1,544 queue entries carry
    a slug). One bounded GET; "" on anything but a clear `about_website` link."""
    if not slug or not re.fullmatch(r"[a-z0-9-]+", str(slug)):
        return ""
    try:
        import urllib.request
        req = urllib.request.Request(f"https://www.linkedin.com/company/{slug}/about/",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(400_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    m = _LI_SITE.search(html)
    site = (m.group(1) if m else "").strip()
    return site if site.startswith("http") and not _is_agg_url(site) else ""


def _names_now():
    """The registry's names RIGHT NOW -- re-read before every append (rule 4): a
    concurrent writer that added the same company mid-run would otherwise get a twin."""
    return {r["company_name"].strip().lower() for r in load_companies(CSV_PATH, active_only=False)}


_CACHE_OK = {"readable": True}


def _load_cache():
    """ABSENT is {}; CORRUPT is reported and the run's cache write is SKIPPED -- writing
    `{}` over a momentarily unreadable file deleted every company's cards (BACKLOG 156;
    the guard discovery_daily already has)."""
    _CACHE_OK["readable"] = True
    if not os.path.exists("scraped_cache.json"):
        return {}
    try:
        with open("scraped_cache.json", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("not an object")
        return d
    except Exception as e:  # noqa: BLE001
        print(f"::error::scraped_cache.json is unreadable ({str(e)[:60]}) -- this run will NOT "
              f"write it; cards resolved tonight are kept in the registry only", flush=True)
        _CACHE_OK["readable"] = False
        return {}


def _row_for_scrape(name, jobs2, good_url, seed_url, cache):
    """The scrape row builder — the seam a test can reach, like `_row_for_ats` below.

    This branch lived inline in `main()`, and `main()` writes through the ABSOLUTE
    `CSV_PATH`, so no fixture could drive it without touching the real registry. The
    mutation catalogue carried M1/M2/M3 for this gate and all three SURVIVED a full sweep:
    the gate existed, and nothing could prove it did anything.

    Order matters and is preserved: `is_aggregator` first (a "similar jobs" sidebar is
    OTHER companies' postings — the Telegram bridge seeds job-post links as careers_url),
    then the identity gate, because `is_aggregator` asks "is this a job board for many
    employers", NOT "is this THIS company's page" — FairFly was activated off
    fireflyspace.com by a path with exactly this shape. `cache` is written only on accept.
    """
    from pipeline.aggregators import is_aggregator
    if is_aggregator(good_url):
        return [name, "scrape", good_url, good_url, "false",
                "aggregator URL; resolve real careers page before activating"]
    if not _gate.activation_ok(name, good_url, len(jobs2)):
        # SEED url, not the refused page -- the same rule `_row_for_ats` and
        # `retry_unreachable._row_for` follow (docs/BACKLOG.md 54): `good_url` is a
        # FOLLOWED link that routinely leaves the company's own host, and a refused
        # ATS-hosted page persisted into cols 2-3 puts a foreign host into the row's
        # address, which `identity_gate.is_walled` reads as crack-pool membership.
        return [name, "scrape", seed_url, seed_url, "false",
                "scraped page is not this company's; no listing found"]
    cache[name] = jobs2
    return [name, "scrape", good_url, good_url, "true",
            f"auto-expand scrape; {len(jobs2)} IL"]


def _row_for_ats(payload, seed_url, via="", html=""):
    """The `ats` row builder, extracted so the gate has a seam a test can reach.

    `main()` writes through `pipeline.companies.CSV_PATH`, which is an ABSOLUTE path fixed
    at import time from the repo root — a `chdir` fixture does not redirect it, so driving
    `main()` in a test would append to the real registry. The row builder is the honest unit
    to test, and `retry_unreachable._row_for` is the same shape for the same reason.
    """
    nm, plat, tok, api, n_all, il = payload
    # `_row_for_scrape` runs `is_aggregator` before its gate and says why; this builder ran
    # neither. An ATS endpoint should never BE an aggregator, so this is cheap insurance on
    # the class rather than a measured save (attacker, 2026-08-27).
    if _is_agg_url(api or ""):
        return [nm, "scrape", seed_url, seed_url, "false",
                "auto-expand: aggregator URL; no listing found"]
    if not _gate.activation_ok(nm, api, n_all, html=html):
        # SEED url in cols 2-3, never the refused board. Persisting the refused `api` put
        # a FOREIGN host into the row's address, and `identity_gate.is_walled` derives
        # crack_walled's pool membership from that host -- so a row parked this way joined
        # the crack pool pointing at Novartis's Workday (docs/BACKLOG.md 54). The sibling
        # `retry_unreachable._row_for` already reset to the row's own URL; now both do.
        # And the note carries `no listing found` -- the hand-off token -- for the same
        # reason as retry's: a token-free refusal orphans the row out of every pool.
        return [nm, "scrape", seed_url, seed_url, "false",
                "auto-expand: another company's board; no listing found"]
    # `via` names the RUNG, so a class of rows can be audited and rolled back as a
    # class. Without it a slug-probe row is indistinguishable from an LLM-resolved
    # one, and the rollback this rung shipped with -- "if any such row is ever found
    # to be another employer's board, disarm the rung in the same commit that parks
    # it" -- has no way to find them. `grep slug-probe companies.csv` is the audit.
    return [nm, plat, tok, api, "true",
            f"auto-expand{' ' + via if via else ''}; {n_all}/{il} IL"]


def main():
    print("auto_expand: " + ("DRY RUN — nothing will be written"
                             if DRY_RUN else
                             "WRITING to companies.csv + scraped_cache.json "
                             "(pass --dry-run to inspect without writing)"), flush=True)
    t_run = time.time()
    # ONE default, and the module is where it lives (BACKLOG 316: the docstring said 200, this
    # line said 200, `auto-expand.yml`'s input default says 200 and its cron fallback says
    # 250, so no reader could say what a scheduled run processes).
    limit = int(os.environ.get("AUTO_EXPAND_LIMIT") or AUTO_EXPAND_LIMIT_DEFAULT)
    run_ceiling = int(os.environ.get("AUTO_EXPAND_RUN_S") or RUN_CEILING_S_DEFAULT)
    resolve_budget = int(os.environ.get("AUTO_EXPAND_RESOLVE_S") or RESOLVE_BUDGET_S_DEFAULT)
    run_deadline = t_run + run_ceiling
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    from pipeline.recruiters import is_recruiter
    have = _names_now()
    todo = [e for e in entries if e.get("careers_url")
            and (e.get("name") or "").strip().lower() not in have
            and not is_recruiter(e.get("name"))]      # never migrate recruiting/staffing agencies
    # least-recently-tried first, file order within a day (stable sort): deferred names
    # are never parked, so without this the same prefix would get every run's shots
    seen = _load_seen()
    todo.sort(key=lambda e: seen.get((e.get("name") or "").strip(), ""))
    batch = todo[:limit]
    print(f"unresolved: {len(todo)} · processing {len(batch)} this run", flush=True)

    cache = _load_cache()
    # Every company gets a row so it leaves the unresolved set — the loop converges to zero:
    #   resolved -> active row with jobs; empty/unreachable -> inactive row (validated scan).
    # Exceptions, both DEFERRED (no row, retried on rotation): an aggregator seed the LLM
    # tier could not crack this run, and any name whose tier-2 shot is capped out.
    import shutil as _shutil
    from collections import Counter
    llm_available = bool(_shutil.which("claude"))
    llm_budget = int(os.environ.get("LLM_RESOLVE_CAP", "10")) if llm_available else 0
    search_budget = int(os.environ.get("AUTO_EXPAND_SEARCH_CAP", "40"))
    n_resolved = n_empty = n_unreach = n_llm = n_dupe = 0
    n_asked = n_hopeless = 0        # report-only: see the module docstring
    n_probed = 0
    probe_refused = Counter()
    # The free rung is ON by default and needs no workflow change -- deliberately: arming it
    # from `auto-expand.yml` would be an `infra` edit, and this rung costs nothing but HTTP.
    # `AUTO_EXPAND_PROBE=0` disarms it. Read INSIDE main(), never at module scope like
    # DRY_RUN, which is bound from sys.argv at import and is why it cannot be tested.
    n_sited = 0
    site_on = os.environ.get("AUTO_EXPAND_SITE", "1") == "1"
    site_deadline = time.time() + SITE_BUDGET_S
    probe_on = os.environ.get("AUTO_EXPAND_PROBE", "1") == "1"
    # the batch decides coverage, not the clock -- and never past the shared-runner ceiling
    probe_budget = (int(os.environ.get("AUTO_EXPAND_PROBE_BUDGET_S") or 0)
                    or min(limit * PROBE_PACE_S, run_ceiling))
    probe_deadline = time.time() + probe_budget
    # what BOUND the run. Reported, because "resolved 11 ... ~486 still to scan" is readable
    # as three different runs and on 2026-08-27 it was read as the wrong one.
    n_seen = n_probe_walked = 0
    t_probe = t_site = t_resolve = 0.0
    n_resolve_calls = 0
    first_exhausted = ""
    llm_cap0, search_cap0 = llm_budget, search_budget
    boards_now = _boards_now() if probe_on else set()
    deferred = Counter()
    for e in batch:
        # ONE deadline, checked where names are CONSUMED. Every other gate in this loop is
        # per-rung and checked before entry, so each rung could overrun by a full name and
        # none of them composed: the four together came to ~6 h 15 m at limit=600 against
        # `timeout-minutes: 330` (measured from the code, 2026-08-27).
        if time.time() >= run_deadline:
            first_exhausted = "run"
            break
        n_seen += 1
        name, url = e["name"].strip(), e["careers_url"]
        agg_seed = _is_agg_url(url)
        # Set ONLY by `_site_from_guess`, which is the one rung here that proves an address:
        # the full name on the page (strict, no `_NAME_STOP` core), an exact linkback to
        # `linkedin.com/company/<handle>`, and `not is_foreign`. `not agg_seed` is NOT the
        # same claim -- `_is_agg_url` is a 60-host blocklist, so a Telegram-seeded
        # `comeet.com/jobs/<someone-else>/...` link clears it while being another employer's
        # board. Parking on that would write their address into this row's cols 2-3 forever.
        site_seeded, site_html, resolve_crashed = False, "", False
        # SUB-RUNG B, free: turn an aggregator seed into the company's OWN address. This is
        # the larger of the two levers, because an own-domain page is precisely what
        # `resolve_llm._verify` requires and cannot get from a LinkedIn permalink -- so it
        # both lets tier-1 `resolve_deep` run at all and stops the paid tier being
        # structurally hopeless on this name (BACKLOG 278).
        if (agg_seed and site_on and n_sited < SITE_MAX
                and time.time() < site_deadline):
            # `n_sited < SITE_MAX` is the important half. A successful guess clears
            # `agg_seed`, and the very next statement calls `resolve()` -- full
            # `resolve_deep`: a 35 s Playwright goto plus `scrape_universal` at
            # COMPANY_BUDGET_S=150, possibly twice. ~342 s per name with NO deadline check
            # anywhere on that path. That is the cost the module docstring says was
            # deliberately removed ("76 wasted minutes a run"), and at LIMIT=250 an
            # attacker computed the uncapped version back at 4.4 HOURS against a 330-minute
            # job timeout, holding `concurrency: repo-state` for all of it. SITE_BUDGET_S
            # bounds the guessing GETs; only this bounds what a guess unlocks.
            _t = time.time()
            _site = _site_from_guess(name, (e.get("slug") or "").strip().lower())
            t_site += time.time() - _t
            if _site:
                # The page is kept for `resolve_llm`'s evidence bundle ONLY. It must
                # NEVER reach `activation_ok`: that is a page on OUR domain, and the gate
                # would be asked whether it vouches for a THIRD PARTY's ATS endpoint.
                # `activation_verdict` short-circuits on any readable held page --
                # `page_names_company(name, api_url, html=html)` never reads `api_url` -- and
                # `_site_from_guess` GUARANTEES this page names the company, because that is
                # proof #1 of the rung. So the gate returns `ok` unconditionally: an
                # adversarial pass drove `Acme Robotics` onto `lever/monday` as an ACTIVE
                # row, which is the `alias-of` shape section 2 calls terminal and is strictly
                # worse than the burial this change exists to fix. It is the same rule
                # section 2 already states for `embedded_board_ok`: a held page may REFUSE a
                # board, never ADMIT one.
                url, agg_seed = _site[0], False
                site_seeded, site_html = True, _site[1]
                n_sited += 1
                print("  site %s: %s" % (name, url[:60]), flush=True)
        if (agg_seed and e.get("slug") and search_budget > 0
                and os.environ.get("AUTO_EXPAND_SLUG_SEED", "0") == "1"):
            # OFF by default (2026-08-26): a guest GET of the LinkedIn company page carried
            # no `about_website` link for fiverr / riskified / upwind-security, and every
            # GET competes with discovery's LinkedIn budget on the runner. Built, measured,
            # inert until the page shape (or a logged-in fetch) makes it worth a credit.
            # the slug can turn an aggregator seed into the company's OWN site (BACKLOG 178):
            # one GET, bounded by the same search cap as the LLM tier; a real site is a
            # tier-1 seed like any other, and the LLM tier then reads a real page too
            site = _site_from_slug(e.get("slug"))
            if site:
                search_budget -= 1
                url, agg_seed = site, False
                print(f"  slug {name}: {e.get('slug')} -> {site[:60]}", flush=True)
        if agg_seed:
            # never rendered: the page is a posting on someone else's board (see module doc)
            r, kind = None, "unreachable"
        else:
            _budget = min(resolve_budget, int(run_deadline - time.time()))
            if _budget < 10:
                # Not enough time left to reach a verdict. Starvation is not a fact about the
                # company: `_left()` floors at 1 s, so `resolve` would run every rung at one
                # second and return `unreachable`, which the park below writes as a permanent
                # row. Defer instead -- exactly as a crash does.
                r, resolve_crashed = ("unreachable", None), True
                first_exhausted = first_exhausted or "run"
            else:
                try:
                    _t = time.time()
                    n_resolve_calls += 1
                    r = resolve(name, url, budget_s=_budget)
                except TypeError:
                    # NEVER swallowed. A TypeError here can only be a programming error --
                    # a signature drift on `resolve` -- and the bare `except Exception` below
                    # reported it as `unreachable; could not scan`, i.e. as a fact about the
                    # company's website. An adversarial pass found three tests in this repo
                    # mis-resolving for exactly that reason on 2026-08-27, and in production
                    # the same drift would have parked every name in the batch.
                    raise
                except Exception:  # noqa: BLE001
                    # A CRASH is not a scan. `resolve` wraps every failure into `unreachable`,
                    # and once a site-seeded name parks on that verdict, one missing Chromium
                    # on the runner turns every name in the batch into a permanent row -- a
                    # mass-zero result committing itself, which section 8 calls a broken run
                    # and not a measurement. Deferring is what the docstring already promises.
                    r, resolve_crashed = ("unreachable", None), True
                finally:
                    t_resolve += time.time() - _t
            kind = r[0] if r else "unreachable"

        # LLM fallback: deterministic resolution failed outright, or "succeeded" only by
        # scraping an aggregator page (which the guard below refuses to activate anyway).
        _scrape_url = ""
        if kind == "scrape":
            _j2, _scrape_url = r[1] if isinstance(r[1], tuple) else (r[1], url)
        needs_llm = (agg_seed or kind in ("empty", "unreachable")
                     or (kind == "scrape" and _is_agg_url(_scrape_url)))
        defer, via, probe_html = "", "", ""
        # THE FREE RUNG -- before the capped tier, never after. It costs plain HTTP; the
        # tier costs a `claude -p` call. An aggregator seed reaches here having done NO HTTP
        # at all, and `resolve_llm._verify` cannot accept any answer for it without a page on
        # the company's own domain -- so on these names the paid tier is not budget-bound, it
        # is EVIDENCE-bound (BACKLOG 278). This rung is the evidence, for free.
        if needs_llm and probe_on and time.time() < probe_deadline:
            # Rotation: a probe IS an attempt. `todo` is ~498 against AUTO_EXPAND_LIMIT=250,
            # and until now only LLM-tier entrants were stamped -- so without this line the
            # run re-walks the same prefix every time and 248 names are never probed at all.
            # Every time budget in this repo needs a rotation key in the same commit (s2).
            seen[name] = _today()
            # Flush periodically: rows are appended immediately but `seen` was written only
            # after the whole loop, and this rung stamps up to 250 names a run instead of
            # ~10. A timeout or crash -- which the unbounded paths above make likelier --
            # threw ALL of them away, so the next run re-walked the same prefix, which is
            # precisely what the rotation key exists to prevent. Atomic, so a partial write
            # is not a corrupt file (attacker, 2026-08-27).
            if not DRY_RUN and len(seen) % 25 == 0:
                try:
                    from pipeline.atomic import write_json as _wj
                    os.makedirs(os.path.dirname(SEEN_PATH) or ".", exist_ok=True)
                    _wj(SEEN_PATH, seen)
                except Exception:  # noqa: BLE001
                    pass          # a rotation key is order, never a verdict: never fatal
            n_probe_walked += 1
            _t = time.time()
            hit, why = _probe_resolve(name, e.get("slug"), boards_now,
                                      time.time() + PROBE_NAME_S)
            t_probe += time.time() - _t
            if hit:
                plat, tok, api, n_all, n_il, page = hit
                # `_row_for_ats` unpacks (nm, plat, tok, api, n_all, il) -- the NAME first.
                r, kind, needs_llm = ("ats", (name, plat, tok, api, n_all, n_il)), "ats", False
                n_probed += 1
                via, probe_html = "slug-probe", page
                print("  probe %s: %s/%s %d jobs, %d IL" % (name, plat, tok, n_all, n_il),
                      flush=True)
            elif why:
                # COUNTED, NEVER DEFERRED. A probe refusal means the free rung could not
                # help; it is not a verdict on the company. Setting `defer` here cancelled
                # the paid tier AND the park below, so a name the probe declined got NO ROW
                # where it would previously have been parked `unreachable; could not scan`
                # -- a row that sits in three re-check pools. The company would have existed
                # only in the queue, and the drain never removes an unresolved name, so it
                # would be re-probed twice a day forever, invisibly. Found by an attacker,
                # 2026-08-27.
                probe_refused[why] += 1
        if needs_llm and llm_available:
            if llm_budget <= 0 or search_budget <= 0:
                # A `cap` means WE RAN OUT OF BUDGET, not "we learned nothing" -- and the
                # other two defer branches below already know the difference (`llm-none` and
                # `no-llm` are both guarded on `agg_seed`). This one was not, so a name whose
                # address the own-site rung had PROVED and `resolve` had already scanned was
                # dropped on the floor: nine of eleven verified domains on 2026-08-27, twice
                # a day, re-derived from scratch the next run (BACKLOG 323).
                #
                # `site_seeded`, never `not agg_seed`: see the flag's definition above. Both
                # `empty` and `unreachable` park, because the pools say so rather than the
                # epistemics -- `unreachable; could not scan` is the ONLY one of the two that
                # `retry_unreachable`/`bd_rescue` claim (02:30 daily, and they activate),
                # while `scanned; no open Israel roles now` is the only one `validate_empty`
                # claims. Deferring instead returns the name to the rung that just refused it
                # for budget reasons, which at LLM_RESOLVE_CAP=10 against 231 cap-deferrals a
                # run is a ~0.96 chance of the identical refusal tomorrow.
                defer = "" if site_seeded and not resolve_crashed else "cap"
            else:
                search_budget -= 1
                seen[name] = _today()
                import resolve_llm as _llm
                lr = _llm.resolve_llm(name, url)
                llm_budget -= _llm.LAST["calls"]   # charge CALLS (retries included), not attempts
                if _llm.LAST["asked"]:
                    n_asked += 1
                    # zero own-domain pages in the evidence means `_verify` could not have
                    # accepted ANY answer -- the token has to appear on the company's own
                    # page. Counted, not refused, until the number is real (2026-08-27).
                    n_hopeless += 1 if not _llm.LAST["own_pages"] else 0
                if lr:
                    r, kind = lr, "ats"
                    n_llm += 1
                elif agg_seed:
                    defer = "llm-none" if _llm.LAST["asked"] else "no-candidates"
        elif needs_llm and agg_seed and not defer:
            # `not defer`: this arm runs whenever the branch above is skipped, INCLUDING
            # when the probe already declined this name -- without the guard a Hebrew name
            # refused as `probe-noslug` was relabelled `no-llm`, which names the wrong
            # subsystem in the one line an operator reads to find out why.
            defer = "no-llm"
        if defer:
            deferred[defer] += 1
            print(f"  dfer {name} ({defer}; retried on rotation)", flush=True)
            continue
        if kind == "ats":
            row = _row_for_ats(r[1], url, via=via, html=probe_html)
            if row[4] != "true" and _is_agg_url(url):
                # An aggregator seed is DEFERRED, never parked (module docstring; BACKLOG
                # 177). `_row_for_ats`'s refusal branch writes the SEED into cols 2-3, and
                # for an agg seed that seed is the LinkedIn/secrethunter shell -- so parking
                # here puts `il.linkedin.com/jobs/view/...` in `api_url`, which is the exact
                # 28-row shape `--clear-agg-urls` exists to undo, and which
                # `identity_gate.is_walled` then reads as this row's address.
                # This guard covers the LLM path too, where it was already reachable and
                # rare only because resolutions are rare.
                deferred["gate"] += 1
                print("  dfer %s (gate; retried on rotation)" % name, flush=True)
                continue
            n_resolved += 1 if row[4] == "true" else 0
            n_unreach += 0 if row[4] == "true" else 1
        elif kind == "scrape":
            jobs2, good_url = r[1] if isinstance(r[1], tuple) else (r[1], url)
            row = _row_for_scrape(name, jobs2, good_url, url, cache)
            if row[4] != "true" and _is_agg_url(good_url):
                # The same guard the `ats` branch above carries, and the `cap` fix of BACKLOG
                # 323 is what made it reachable: with `defer` cleared, a refused scrape OF AN
                # AGGREGATOR PAGE now falls through to here instead of being deferred, and
                # `_row_for_scrape`'s refusal branch writes that page into cols 2-3 -- the
                # 28-row `--clear-agg-urls` shape, which `identity_gate.is_walled` then reads
                # as this row's own address.
                deferred["gate"] += 1
                print("  dfer %s (gate; retried on rotation)" % name, flush=True)
                continue
            n_resolved += 1 if row[4] == "true" else 0
            n_unreach += 0 if row[4] == "true" else 1
        elif kind == "empty":
            row = [name, "scrape", url, url, "false", "scanned; no open Israel roles now"]
            n_empty += 1
        else:
            row = [name, "scrape", url, url, "false", "unreachable; could not scan"]
            n_unreach += 1
        if site_seeded and row[4] != "true":
            # PROVENANCE, not a pool selector -- which is why `pipeline/verdicts.py` needs no
            # new token and this stays out of shared plumbing. The row keeps whichever of the
            # two existing verdicts is TRUE (both are already in `TOKENS`); this segment only
            # records HOW the address was obtained, so a class of rows stays auditable and
            # revertable in one line, the way `via`/`slug-probe` already is:
            #     grep 'own-site' companies.csv
            # Deleting such a row returns the name to `todo` automatically, because `todo` is
            # recomputed from `_names_now()` every run and this tool never drains the queue.
            row[5] = _note_append(row[5], "own-site %s: %s linkback"
                                  % (_today(), urlparse(url).netloc[:40]))
        if not DRY_RUN:
            if name.lower() in _names_now():      # re-read before the append (rule 4)
                n_dupe += 1
                print(f"  dupe {name} (already in the registry; not appended)", flush=True)
                continue
            # ...and the same discipline for the BOARD, which `_names_now` cannot see: these
            # names differ by a legal suffix, which is the whole reason the board key exists.
            # `_probe_resolve`'s check uses a snapshot taken before the loop, so it cannot
            # see a row THIS RUN just appended -- two attackers independently demonstrated
            # one run writing two ACTIVE rows on one board, with `check_invariants` exit 0,
            # and a live candidate for tonight (`Ness Technologies` and `Ness Technologies |
            # <hebrew>` both yield the slug `ness-technologies`). That is the `alias-of`
            # shape section 2 calls terminal: every role published twice under two employer
            # names, which check B cannot catch BECAUSE the names differ. Re-read, like
            # rule 4, so it covers the probe path, the LLM path and the intra-run case.
            # LOWERCASED on BOTH sides. `_boards_now()` lowercases what it stores and this
            # lookup did not, so the guard was blind to every platform whose tokens are not
            # already lower-case -- which is exactly one, and it is Comeet, whose token is an
            # uppercase uid. Demonstrated in production by the 19:18 run of 2026-08-27, which
            # wrote `Imagry | Autonomous Driving` as a SECOND ACTIVE ROW on `comeet/B7.00F`
            # beside the existing `Imagry`: the `alias-of` shape section 2 calls terminal,
            # every role republished under two employer names, and `check_invariants` check B
            # cannot catch it BECAUSE the names differ. The guard was written for this and
            # missed it by a `.lower()`.
            if row[4] == "true" and _board_taken(row[1], row[2], row[3], _boards_now()):
                n_dupe += 1
                print(f"  dupe {name} ({row[1]}/{row[2]} is already read by another row; "
                      f"not appended)", flush=True)
                continue
            with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        print(f"  {'[dry] ' if DRY_RUN else ''}{kind[:4]:4} {name}", flush=True)

    if not DRY_RUN:
        if _CACHE_OK["readable"]:
            with open("scraped_cache.json", "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.makedirs(os.path.dirname(SEEN_PATH) or ".", exist_ok=True)
        from pipeline.atomic import write_json
        write_json(SEEN_PATH, seen)
    n_defer = sum(deferred.values())
    # `len(batch) - n_seen` is the tail the run deadline skipped. Without it the 2026-08-27
    # run's `~486 still to scan` was 12 names short of the truth, and that number is the one
    # an operator reads (adversarial pass, 2026-08-27).
    remaining = len(todo) - len(batch) + n_defer + (len(batch) - n_seen)
    why = ", ".join(f"{k} {v}" for k, v in sorted(deferred.items())) or "-"
    # The rung's REFUSALS, named and counted separately from its hits. A rung that reports
    # only what it shipped cannot be audited: `probe-dup-board` climbing means the queue is
    # full of companies we already read under another name, `probe-no-il` is the ordinary
    # case, and `probe-ambiguous` climbing means one name is answering on two boards.
    probe_why = ", ".join(f"{k} {v}" for k, v in sorted(probe_refused.items())) or "-"
    print(f"=== resolved {n_resolved} (LLM-cracked {n_llm}, probe {n_probed}), empty {n_empty}, "
          f"unreachable {n_unreach}, deferred {n_defer} ({why}), dupes {n_dupe}; "
          f"asked {n_asked} (hopeless {n_hopeless}); "
          f"~{remaining} still to scan ===", flush=True)
    print(f"probe: {n_probed} resolved, refused {sum(probe_refused.values())} ({probe_why}); "
          f"walked {n_probe_walked} of {n_seen}; own-site seeds {n_sited}", flush=True)
    # WHICH GATE BOUND THE RUN, in one token, with the evidence for it on the same line. On
    # 2026-08-27 the summary said `resolved 11 ... ~486 still to scan`, which is readable as
    # "31 names were scanned" and was read that way -- while the rotation key says 238. A run
    # that cannot say what stopped it cannot be audited, and its coverage is not a number.
    # Derived, in this order, because only the first one is a fact about the RUN: the clock
    # stopped it, or the batch did, or nothing was left to do. `queue` requires that every
    # name in `todo` was walked AND that none is still unresolved -- this tool does not drain
    # the queue (`research_companies.json` is not in `auto-expand.yml`'s `--own` list), so
    # deferrals leave names behind and an earlier version printed `bound=queue` on the same
    # screen as `~5 still to scan`. An adversarial pass, 2026-08-27.
    if n_seen < len(batch) or first_exhausted:
        bound = "clock:" + (first_exhausted or "probe")
    elif len(batch) < len(todo):
        bound = "batch"
    elif n_defer:
        bound = "batch"          # everything was walked and some of it did not resolve
    else:
        bound = "queue"
    print(f"bound={bound} · names {n_seen}/{len(batch)} of batch (limit {limit}, "
          f"queue {len(todo)}, skipped {len(batch) - n_seen}) · elapsed "
          f"{int(time.time() - t_run)}s of {run_ceiling}s · probe {int(t_probe)}/"
          f"{probe_budget}s · site {n_sited}/{SITE_MAX} in {int(t_site)}/{SITE_BUDGET_S}s · "
          f"resolve {n_resolve_calls} calls {int(t_resolve)}s · llm "
          f"{llm_cap0 - llm_budget}/{llm_cap0} calls, entrants "
          f"{search_cap0 - search_budget}/{search_cap0}", flush=True)


# Verdicts this tool writes on a parked row (its own, per pipeline.verdicts.TOKENS) --
# the rows `--clear-agg-urls` may touch.
_OWN_PARKED = ("scanned; no open", "unreachable", "aggregator URL")


def clear_agg_urls(apply=False, path=None):
    """Un-bury rows this tool parked with an aggregator shell as their address.

    Until 2026-08-25 an aggregator-seeded name that the LLM tier could not crack was
    written as `scanned; no open Israel roles now` with the LinkedIn / secrethunter URL in
    cols 2-3 -- 28 real employers on that day (ctera, Houzz, yad2, Upwind Security ...),
    each re-tested against a JS shell by every re-check. The address is blanked and the
    row stamped `url-cleared <date>: <host> aggregator seed`, the shape
    `state/sess/cleanup_after_hunt.py` already gave 23 rows: `url-cleared` is in
    `listing_hunt.HUNT_POOL`, so the row stays the hunt's, which searches by NAME when the
    seed is empty. Dry-run unless `apply`. Re-reads immediately before the one write.
    """
    from pipeline.atomic import write_csv_rows
    path = path or CSV_PATH
    rows = list(csv.reader(open(path, encoding="utf-8")))
    changed = []
    for r in rows[1:]:
        if len(r) < 6 or r[4] != "false" or not _is_agg_url(r[3] or ""):
            continue
        note = r[5] or ""
        from pipeline.notes import split as _segments
        if not any(seg.startswith(t) for seg in _segments(note) for t in _OWN_PARKED):
            continue                     # any SEGMENT, not only the first
        host = urlparse(r[3]).netloc
        r[2] = r[3] = ""
        r[5] = _note_append(note, f"url-cleared {_today()}: {host} aggregator seed")
        changed.append(r[0])
        print(f"  {'' if apply else '[dry] '}clear {r[0]}: {host}", flush=True)
    if apply and changed:
        write_csv_rows(path, rows)
    print(f"=== cleared {len(changed)} aggregator-seeded rows"
          f"{'' if apply else ' (dry run; pass --apply)'} ===", flush=True)
    return changed


if __name__ == "__main__":
    if "--clear-agg-urls" in sys.argv:
        clear_agg_urls(apply="--apply" in sys.argv)
    else:
        main()
