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



DRY_RUN = "--dry-run" in sys.argv
SEEN_PATH = os.path.join("cloud_state", "auto_expand_seen.json")

# The free rung's bounds. Measured 2026-08-27 over all 498 drainable names: 5,212 requests,
# 293 s, 0.59 s/name -- so 1,200 s is ~4x the whole queue and will not bind at
# AUTO_EXPAND_LIMIT=250. It exists because the binding cost is not the 330-minute job
# timeout, it is `concurrency: group: repo-state`, which five workflows share.
PROBE_BUDGET_S = int(os.environ.get("AUTO_EXPAND_PROBE_BUDGET_S", "1200"))
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
    return out


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
        return None, ("probe-no-il" if hits else "")
    if len({(h["plat"], h["slug"]) for h in live}) > 1:
        return None, "probe-ambiguous"
    h = live[0]
    if (h["plat"], h["slug"]) in boards:
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


def _site_from_guess(name, handle, timeout=5):
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
    """
    if not handle or not _SLUG_OK.fullmatch(handle):
        return None
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
        if _gate.page_mentions_company(name, html, strict=True) is not True:
            return None                    # a domain that answers but is not theirs: stop
        # ...and the linkback must be the WHOLE handle. `\b` fires on a hyphen, so `pcb` was
        # "proved" by `linkedin.com/company/pcb-piezotronics` and `ceva` by
        # `linkedin.com/company/ceva-sante-animale`: a PREFIX match, which is exactly the
        # truncation this rung exists to avoid, arriving through the other half of the same
        # test. Two independent-looking halves, one shared weakness -- the same shape as the
        # gate's own (BACKLOG 317), which is the thing to remember rather than the two fixes.
        if not re.search(r"linkedin\.com/company/" + re.escape(handle) + r"(?![a-z0-9-])",
                         html, re.I):
            return None                    # no linkback: unproven, and unproven is refused
        if _gate.is_foreign(name, final or u):
            return None
        return (final or u), html
    return None

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
    limit = int(os.environ.get("AUTO_EXPAND_LIMIT", "200"))
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
    probe_deadline = time.time() + PROBE_BUDGET_S
    boards_now = _boards_now() if probe_on else set()
    deferred = Counter()
    for e in batch:
        name, url = e["name"].strip(), e["careers_url"]
        agg_seed = _is_agg_url(url)
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
            _site = _site_from_guess(name, (e.get("slug") or "").strip().lower())
            if _site:
                url, agg_seed = _site[0], False
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
            try:
                r = resolve(name, url)
            except Exception:  # noqa: BLE001
                r = ("unreachable", None)
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
            hit, why = _probe_resolve(name, e.get("slug"), boards_now,
                                      time.time() + PROBE_NAME_S)
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
                defer = "cap"
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
            n_resolved += 1 if row[4] == "true" else 0
            n_unreach += 0 if row[4] == "true" else 1
        elif kind == "empty":
            row = [name, "scrape", url, url, "false", "scanned; no open Israel roles now"]
            n_empty += 1
        else:
            row = [name, "scrape", url, url, "false", "unreachable; could not scan"]
            n_unreach += 1
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
            if row[4] == "true" and (row[1] or "", row[2] or "") in _boards_now():
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
    remaining = len(todo) - len(batch) + n_defer
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
          f"own-site seeds {n_sited}", flush=True)


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
    from pipeline.notes import append as _note_append
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
