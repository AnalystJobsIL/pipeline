#!/usr/bin/env python3
"""Daily discovery layer: LinkedIn + Indeed jobs scrapers (Bright Data) for Israel analytics roles.

- Triggers small discovery queries (quota-capped), waits, fetches records.
- Jobs are normalized and written to discovered_cache.json -> read by fetch_discovery in the
  pipeline (company shown as the real employer, url = posting link).
- Companies NOT already in companies.csv are written to out/discovered_companies.json — the
  auto-expand loop then resolves their own ATS so they migrate to free direct scanning.

Budget, MEASURED not estimated (2026-08-23, from cloud_state/source_health.json after the
08-23 cloud run): 30 LinkedIn records + 78 linkedin-targeted records = 108 Bright Data
dataset records/day, plus 5 Web Unlocker requests (one per INDEED_QUERIES entry). That is
~3,240 dataset records/month, not the "~40/day = ~1,200/mo" this docstring claimed until
2026-08-23 — the targeted sweep, which did not exist when the line was written, is by
itself two thirds of the spend. Re-derive before adding a query:

    python -c "import json;print(json.load(open('cloud_state/source_health.json')))"
"""
from __future__ import annotations

import sys

import json
import os
import re
import time
import urllib.parse
import urllib.request

from bd_rescue import _load_secrets
from pipeline.companies import load_companies

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# THE BREADTH SWEEP IS THE DISCOVERY SOURCE. Its job is to return employers the registry
# has never heard of; the jobs are the secondary output. Judge any change to it by
# new-companies-per-run, not by records or by jobs.
#
# It was returning ZERO new companies. Measured 2026-08-23 on the day's own run: 29 jobs,
# 27 employers, 25 of them already registry rows and 11 of them staffing agencies we discard
# — 0 new. Two reasons, both fixed here:
#
#   1. `limit_per_input` was 15. LinkedIn ranks by relevance and the head of that ranking is
#      saturated with big employers and agencies; UNKNOWN COMPANIES LIVE IN THE TAIL, and
#      the yield accelerates with depth rather than flattening:
#          first  15 records -> 15 employers,  1 new
#          first  30 records -> 29 employers,  3 new
#          first  50 records -> 46 employers,  3 new
#          first 100 records -> 84 employers, 15 new
#   2. No recency filter, so every run re-ranked the same saturated head. The dataset
#      honours `time_range` — "Past week" overlapped the unfiltered run by only 14/61 —
#      and it is also SELF-LIMITING: it bills what was actually posted in the window
#      (61 records against a limit of 100), so depth costs nothing on a quiet keyword.
#      Recency wins on yield per record too: 10 new companies from 61 records, against
#      15 from an unfiltered 100.
#
# Re-measure with docs/… no: with the snippet in ARCHITECTURE.md section 1a. If new-company
# yield ever reads 0 again, this sweep has re-saturated and depth is the first dial.
# Kept because plan_spend still reports a breadth "limit"; LINKEDIN_LIMIT_MIN and
# LINKEDIN_WINDOW were removed on 2026-08-23 — they were read nowhere after the sweep moved
# off the per-record dataset, and an unused constant that reads like a setting is the trap
# this file's own Indeed note is about. The real dials are LINKEDIN_PAGES, INDEED_DAYS and
# the `days=` argument of linkedin_search.
LINKEDIN_LIMIT_MAX = int(os.environ.get("LINKEDIN_LIMIT_MAX", "100"))
# WIDTH, not depth, is what the Unlocker path buys. LinkedIn's public search runs out at
# ~60-85 jobs per keyword however many pages you ask for, so a deep sweep on four keywords
# hits a ceiling the per-record dataset does not — that is why the dataset found 58 new
# companies to the Unlocker's 35 at first. But a keyword costs only ~2 credits here, so the
# answer is more keywords, and it beats the dataset outright. Measured 2026-08-23, one run,
# each keyword's contribution ON TOP of the ones before it:
#
#   data analyst          64 employers  17 new     analytics          +2   +2
#   business intelligence +6            +4         data scientist     +24  +11
#   product analyst       +14           +5         אנליסט              +19  +5
#   BI developer          +7            +5         growth analyst     +26  +16
#                                                  marketing analyst  +12  +7
#   dropped: "BI analyst" (+1 employer) and "insights analyst" (+0) — saturated
#
#   11 keywords = 25 credits = 175 employers = 73 NEW companies
#   vs the dataset's 391 credits = 147 employers = 58 new
#
# Marginal yield is ORDER-DEPENDENT (a later keyword sees fewer unknowns), so re-measure the
# whole list rather than trusting any single row above. If total new companies falls toward
# zero, add keywords before adding pages — depth is the dial that does not work here.
#
# AND DO NOT COMBINE THEM INTO ONE BOOLEAN QUERY. LinkedIn supports
# `("data analyst" OR "data scientist" OR ...)` in `keywords`, and it is a trap: the ~60-80
# result cap is PER QUERY, not per keyword, so one combined query buys one window instead of
# nine. Measured 2026-08-23, same day, same baseline:
#     one OR query over 7 terms   2 credits   60 jobs   50 employers   10 new companies
#     nine separate queries      18 credits             184 employers  76 new companies
# Sixteen extra credits for 66 extra companies. Each distinct query gets its own window;
# that IS the mechanism, and it is why the keyword list is long and flat rather than clever.
_LI_KEYWORDS = ["data analyst", "business intelligence", "product analyst", "BI developer",
                "analytics", "data scientist", "אנליסט", "growth analyst",
                "marketing analyst"]

# Only the DATASET ID is still used, by the targeted backfill below. The breadth sweep moved
# to the Web Unlocker (see linkedin_search) on 2026-08-23, so the keyword/limit config that
# used to live here is gone rather than left looking live — an unused constant that reads
# like a setting is how the Indeed dataset sat "configured" for five days returning zero.
LINKEDIN_DATASET = "gd_lpfll7v5hcqtkxl6l"

# NOTE: the Bright Data Indeed DATASET (gd_l4dx9j9sscpvs7no2) returned ZERO records on
# every run for five days — every snapshot came back `dataset_size: 0,
# error_codes: {"rate_limit": 15}`, i.e. Indeed rate-limits that collector for all 15
# inputs. It printed "[indeed] 0 records" and nobody noticed. Do not re-enable it; Indeed is
# read through the Web Unlocker instead, below.
#
# Indeed, read directly. il.indeed.com serves its results as one embedded JSON blob, and
# the Web Unlocker renders the page past the bot wall — so this needs no dataset, no
# polling, and one request per query instead of a 90-second snapshot job.
INDEED_QUERIES = ["data analyst", "business intelligence", "BI developer",
                  "product analyst", "אנליסט"]
INDEED_DAYS = 7          # fromage: only postings from the last week are worth discovering

_MOSAIC = re.compile(
    r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});', re.S)


def indeed_search(query, days=INDEED_DAYS, limit=25, tries=2):
    """Return raw Indeed job cards for one Israel query.

    RETRIES, and says WHY it got nothing. Every failure mode here used to collapse to a bare
    `[]` — an unlocker exception, a bot-wall page with no mosaic blob, and a genuinely empty
    result set were indistinguishable, and the caller printed "0 cards" for all three. That
    is `ARCHITECTURE.md` section 8 item 2: a mass zero is a broken run, not a measurement.
    Observed 2026-08-23: "data analyst" returned 15 cards in one run and 0 in the next an
    hour later, and "business intelligence" returned 0 in both — the first is a transient
    fetch failure, the second may be real, and nothing in the log let you tell them apart.
    One retry, because the failure is transient; the reason is printed either way."""
    from bd_rescue import unlock
    url = ("https://il.indeed.com/jobs?q=" + urllib.parse.quote_plus(query)
           + "&l=" + urllib.parse.quote_plus("Israel") + f"&fromage={days}")
    why = "no attempt made"          # tries=0 made the final print raise UnboundLocalError
    for attempt in range(tries):
        html = unlock(url, timeout=100)
        UNLOCKER_CALLS["indeed"] += 1
        if not html:
            why = "unlocker returned nothing"
        elif not _MOSAIC.search(html):
            # a bot wall or an interstitial is a full HTML page with no job blob in it
            why = f"no mosaic blob in {len(html)} bytes (bot wall?)"
        else:
            try:
                data = json.loads(_MOSAIC.search(html).group(1))
            except ValueError:
                why = "mosaic blob is not JSON"
            else:
                res = (data.get("metaData", {}).get("mosaicProviderJobCardsModel", {})
                           .get("results", []) or [])
                cards = [r for r in res if isinstance(r, dict)][:limit]
                if not cards:
                    print(f"  [indeed:{query}] parsed OK, genuinely 0 results in {days}d")
                return cards
        if attempt + 1 < tries:
            print(f"  [indeed:{query}] {why} — retrying")
    print(f"  [indeed:{query}] FAILED after {tries}: {why}")
    return []


def indeed_normalize(r):
    """One Indeed card -> the shared discovered-job shape (or None to drop it)."""
    import datetime as _dt
    title = (r.get("displayTitle") or r.get("title") or "").strip()
    comp = (r.get("company") or "").strip()
    jk = r.get("jobkey") or ""
    if not title or not comp or not jk:
        return None
    date = ""
    ts = r.get("pubDate") or r.get("createDate")
    if isinstance(ts, (int, float)) and ts > 0:
        # epoch MILLIseconds. Indeed also serves a relative "formattedRelativeTime";
        # the epoch is the only one that survives a locale switch.
        date = _dt.datetime.fromtimestamp(ts / 1000, _dt.timezone.utc).date().isoformat()
    date = date or _dt.date.today().isoformat()    # never undated — see linkedin_normalize
    if date < (_dt.date.today() - _dt.timedelta(days=21)).isoformat():
        return None
    desc = ""
    sn = r.get("snippet") or ""
    if sn:
        desc = re.sub(r"<[^>]+>", " ", str(sn))
    junior = any(k in f"{title} {desc}"[:400].lower() for k in _JUNIOR_HE)
    return {"_junior": junior,             # flagged, not dropped — the EMPLOYER still counts
            "company": comp[:80], "title": title[:140],
            "location": (r.get("formattedLocation") or "Israel")[:80],
            "country_code": "", "url": f"https://il.indeed.com/viewjob?jk={jk}",
            "posted_date": date, "ats_platform": "discovery-indeed",
            "job_id": f"indeed:{jk}", "description": desc}


# --------------------------------------------------------------------------------------- #
# LinkedIn, read the cheap way
# --------------------------------------------------------------------------------------- #
# THE TWO BRIGHT DATA PRODUCTS BILL DIFFERENTLY, and the difference is ~55x:
#   * Web Scraper API (the dataset) — 1 credit per RECORD. 391 jobs cost 391 credits, even
#     though it is only ONE trigger. Depth is charged by the row.
#   * Web Unlocker — 1 credit per REQUEST. One rendered page of LinkedIn's PUBLIC job search
#     carries 60 job cards, so 60 jobs cost 1 credit.
# ($1.50/1K records vs $1.00/1K requests, brightdata.com/pricing/web-scraper, 2026-08-23.)
#
# So the breadth sweep — the part that has to go DEEP, because unknown companies live in the
# tail — reads `linkedin.com/jobs/search` through the unlocker instead. Measured 2026-08-23:
# the full 4-keyword past-week sweep costs ~8-12 credits where the dataset cost 391.
#
# What is given up: the dataset carries `job_summary`, this does not. That is acceptable HERE
# because the breadth sweep's product is EMPLOYER NAMES, and the classifier decides the clear
# cases on title alone; a role that survives gets its text from `pipeline/jdfill.py` later.
# The targeted sweep keeps the dataset: it needs the `company` filter, which the public search
# only exposes as a numeric `f_C` id we do not have, and at 67 credits it is cheap anyway.
#
# `f_TPR=r604800` is the past-week window (seconds) and it verifiably filters: past-week and
# past-month results overlapped by only 20 of 60.
# TWO pages, because LinkedIn's public search HARD-CAPS at 80 distinct jobs per keyword and
# two requests reach all 80. Measured 2026-08-23 on "data analyst", Israel, past week:
#   start=0 -> 60 cards, 60 new    start=50  -> 60 cards, 0 new
#   start=25 -> 60 cards, 20 new   start=75/100 -> 60 cards, 0 new
# So a third request is pure waste (~9 credits/day across the keyword list) and there is no
# depth beyond 80 to buy at any price. That cap is the whole reason WIDTH beats DEPTH here:
# the only way to see more of LinkedIn through this door is more keywords.
LINKEDIN_PAGES = int(os.environ.get("LINKEDIN_PAGES", "2"))   # PAID pages per keyword
# How many consecutive empty guest pages before the pool is called finished. Free requests,
# so tolerance is nearly free; one blank is NOT exhaustion (measured: a walk that stopped at
# the first blank saw 55 of 71 reachable jobs).
LINKEDIN_BLANK_TOLERANCE = int(os.environ.get("LINKEDIN_BLANK_TOLERANCE", "3"))
# Credits are the unit that matters and nothing counted them per source. One Unlocker call =
# one credit, so this IS the bill for the sweeps that use it.
import collections as _collections
UNLOCKER_CALLS = _collections.Counter()
# Which PATH served each source — free or paid. A free path that silently starts
# returning nothing looks identical to a dead source unless this is recorded.
SOURCE_PATH = _collections.Counter()
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# The `</li>` in the lookahead is load-bearing. Without it the LAST card on a page runs to
# the end of the document, and any later element carrying these class names is absorbed into
# it — the right-rail "people also viewed" block is built from the same `base-search-card`
# component and has no jobPosting urn, so it is not a boundary. A last card lacking its own
# subtitle then emitted a LONDON "Senior Manager" at "Acme Corp" as a Tel Aviv job dated
# today, carrying the previous card's id. `url_names_other_company` waves it through because
# company and url are wrong together. Every page has a last card.
_LI_CARD = re.compile(
    r'data-entity-urn="urn:li:jobPosting:(?P<id>\d+)"(?P<body>.*?)'
    r'(?=data-entity-urn="urn:li:jobPosting:|</li>|\Z)', re.S)
_LI_URL = re.compile(r'base-card__full-link[^>]*href="([^"?]+)')
_LI_TITLE = re.compile(r'<span class="sr-only">\s*(.*?)\s*</span>', re.S)
_LI_COMPANY = re.compile(
    r'base-search-card__subtitle[^>]*>\s*(?:<a[^>]*>)?\s*([^<]{2,80})', re.S)
# The employer's LinkedIn SLUG sits in the same subtitle block and was stepped over.
# It is worth more than the display name: a stable identifier, the only NON-aggregator
# seed this layer can hand the resolver (a discovered job's own url is the POSTING —
# docs/BACKLOG.md item 2, 206 of 1,233 queue entries), and slugs such as
# `barak-recruitment-and-consultancy` are a free is_recruiter signal. Same bytes,
# already paid for. Verified 2026-08-23: present on 10 of 10 cards.
_LI_SLUG = re.compile(
    r'base-search-card__subtitle.*?linkedin\.com/company/([a-z0-9\-_.%]+)', re.S | re.I)
_LI_LOC = re.compile(r'job-search-card__location[^>]*>\s*([^<]{2,80})', re.S)
_LI_DATE = re.compile(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"')


def _li_urn_ids(html):
    """The DISTINCT job-card ids a page contains, whatever we managed to parse out of them.

    Ids, not a count: pages overlap heavily (start=0 and start=10 share 50 cards), so summing
    per-page counts against a deduped parse total produced a meaningless 43% and would have
    fired the drift warning on every healthy run.
    """
    return set(re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html or ""))


def _li_cards(html):
    """Parse one LinkedIn public-search page into per-card dicts.

    Splits into CARD BLOCKS first and reads each field inside its own block. Do not be
    tempted to run one regex per field over the whole page and zip the lists: a card missing
    a location silently shifts every later pairing by one, and a job attributed to the wrong
    employer is the failure this repo guards hardest against (147 board rows were published
    under the wrong company once already)."""
    out = []
    for m in _LI_CARD.finditer(html or ""):
        b = m.group("body")
        title = _LI_TITLE.search(b)
        comp = _LI_COMPANY.search(b)
        url = _LI_URL.search(b)
        if not (title and comp and url):
            continue                      # a card we cannot attribute is skipped, never guessed
        loc = _LI_LOC.search(b)
        date = _LI_DATE.search(b)
        slug = _LI_SLUG.search(b)
        out.append({"job_id": m.group("id"),
                    "title": _html_unescape(title.group(1)),
                    "company": _html_unescape(comp.group(1)),
                    "location": _html_unescape(loc.group(1)) if loc else "Israel",
                    "posted_date": date.group(1) if date else "",
                    "url": url.group(1),
                    "company_slug": slug.group(1) if slug else ""})
    return out


def _html_unescape(t):
    import html as _h
    return " ".join(_h.unescape(str(t or "")).split())


def _li_guest(keyword, location, days, start):
    """LinkedIn's KEYLESS guest endpoint. Returns (cards, ok); ok=False means blocked.

    Same `base-card` / `urn:li:jobPosting` markup the paid path returns, so `_li_cards`
    parses it unchanged — 10 cards per request instead of 60, and it costs NOTHING.
    Verified 2026-08-23 from this machine: HTTP 200, 28,427 bytes, 10 cards, slug on 10 of
    10. The browser UA + `Accept-Encoding` header set is load-bearing; bare urllib gets 403.
    """
    q = urllib.parse.urlencode({"keywords": keyword, "location": location,
                                "f_TPR": f"r{days * 86400}", "start": start})
    req = urllib.request.Request(
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{q}",
        headers={"User-Agent": _UA_BROWSER, "Accept-Encoding": "gzip, deflate",
                 "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip as _gz
                body = _gz.decompress(body)
        text = body.decode("utf-8", "replace")
        _li_last_present[0] = _li_urn_ids(text)
        return _li_cards(text), True
    except Exception:  # noqa: BLE001 — 403/429/authwall/timeout all mean "use the fallback"
        _li_last_present[0] = set()
        return [], False


# How many cards each keyword's pages CONTAINED, against how many parsed — the denominator
# that makes a silent parser regression visible. Keyed by keyword, drained by main().
LI_CARDS_PRESENT = _collections.defaultdict(set)
_li_last_present = [set()]


def linkedin_search(keyword, pages=None, days=7, location="Israel"):
    """LinkedIn job search: KEYLESS first, Web Unlocker only where that is blocked.

    The guest endpoint returns the same markup for nothing, so the whole sweep is $0 on a
    machine LinkedIn will talk to. It will NOT talk to every machine — GitHub's Azure ranges
    are among the most-blocked — so the paid path stays, and `SOURCE_PATH` records which one
    actually served. Without that record, a silent degradation to a free path returning
    nothing would look exactly like a dead source, which is the failure `pipeline/sources.py`
    exists to catch.

    Walks pages until one yields no card we have not already seen. The pool for one Israel
    keyword in a week is ~80 jobs — a hard per-QUERY cap — so it stops on its own.
    """
    from bd_rescue import unlock
    pages = LINKEDIN_PAGES if pages is None else pages
    seen, out = set(), []
    # guest pages hold 10, unlocked pages hold 60 — same 80-job pool, different step size
    paid_pages, blanks = 0, 0
    for i in range(pages * 6):
        cards, ok = _li_guest(keyword, location, days, i * 10)
        # An HTTP 200 with an empty body IS LinkedIn's soft rate-limit, and treating it as a
        # successful empty result skipped the fallback and killed the keyword with no message
        # — a mass zero read as a measurement (ARCHITECTURE section 8 item 2), re-created in
        # brand-new code. A free page that yields nothing gets the paid path, not a break.
        # THREE states, and conflating any two of them loses jobs. Earlier versions of this
        # loop conflated all three in turn:
        #   ok + cards  -> the good case
        #   ok + blank  -> AMBIGUOUS. The guest endpoint emits intermittent 200-empty pages
        #                  INSIDE the pool, so one blank is not exhaustion — a walk that
        #                  stopped at the first blank saw 55 of 71 reachable jobs, a 23%
        #                  silent loss per keyword. Probing costs nothing, so probe.
        #   not ok      -> blocked. Use the paid path, for EVERY page of the budget, not
        #                  just page 0.
        if ok and cards:
            SOURCE_PATH["linkedin_free"] += 1
            LI_CARDS_PRESENT[keyword] |= _li_last_present[0]
            blanks = 0
        elif ok:
            SOURCE_PATH["linkedin_free"] += 1
            # record the denominator even on a blank, or a page whose urns we FAIL to parse
            # contributes nothing to the drift metric and the regression stays invisible
            LI_CARDS_PRESENT[keyword] |= _li_last_present[0]
            blanks += 1
            if blanks < LINKEDIN_BLANK_TOLERANCE:
                continue              # a hole inside the pool — free to step over
            if out:
                break                 # cards already collected and the tail is quiet: done
            # Nothing at all after LINKEDIN_BLANK_TOLERANCE blank pages. A working endpoint
            # returning consistently nothing is indistinguishable from a soft rate-limit, so
            # buy ONE paid page to tell "this keyword has no results" from "we are throttled".
            # Without this a soft block silently costs the whole keyword.
        if not ok or (blanks >= LINKEDIN_BLANK_TOLERANCE and not out):
            if paid_pages >= pages or not os.environ.get("BRIGHTDATA_API_KEY"):
                break                 # paid budget spent, or there is no paid path at all
            # The paid page index is its OWN counter. Reusing the guest index meant that
            # once the guest endpoint was blocked — the documented GitHub-runner case — only
            # `start=0` was ever fetched, so 60 of the ~80 available cards arrived and the
            # rest were silently dropped (~20 x 9 keywords a day) while the credits-per-card
            # line reported a flattering 60 cards/credit.
            q = urllib.parse.urlencode({"keywords": keyword, "location": location,
                                        "f_TPR": f"r{days * 86400}", "start": paid_pages * 25})
            html = unlock(f"https://www.linkedin.com/jobs/search?{q}", timeout=120)
            UNLOCKER_CALLS["linkedin"] += 1
            SOURCE_PATH["linkedin_paid"] += 1
            paid_pages += 1
            blanks = 0
            LI_CARDS_PRESENT[keyword] |= _li_urn_ids(html)
            cards = _li_cards(html)
            if not cards:
                print(f"  [linkedin:{keyword}] page {i}: no cards from EITHER path "
                      f"({len(html or '')} bytes unlocked) — markup change or hard block")
                break
        if not cards:
            break
        # NOTE: no `elif out: break` here. That is what limited a hard-blocked guest endpoint
        # — the documented GitHub-runner case — to ONE paid page: the second iteration broke
        # before reaching the fallback, so 60 of the ~80 available cards arrived and the rest
        # vanished with the credits-per-card line reporting a flattering 60/credit. The loop
        # is bounded by `paid_pages >= pages` and by the fresh-card check below.
        fresh = [c for c in cards if c["job_id"] not in seen]
        seen.update(c["job_id"] for c in cards)
        out += fresh
        if not fresh:
            break
    return out


def linkedin_normalize(c):
    """One public-search card -> the shared discovered-job shape (or None to drop it)."""
    import datetime as _dt
    title, comp = c["title"], c["company"]
    if not title or not comp:
        return None
    # Stamp today when the card carries no <time datetime> (promoted and reposted cards
    # routinely do not). An undated job is skipped by BOTH the write-side prune
    # (`if d and d < cut`) and the read-side TTL (`not posted_date or ...`), so it never
    # ages out and `_alive()` keeps it on the board forever — and because this run's copy
    # wins the (company,title) merge, one undated card converts a normal job into a
    # permanent one.
    d = c["posted_date"] or _dt.date.today().isoformat()
    if d < (_dt.date.today() - _dt.timedelta(days=21)).isoformat():
        return None
    # A junior posting is not published, but its EMPLOYER still counts: the breadth sweep's
    # product is employer names, and an unknown Israeli company whose only past-week analyst
    # ad happens to say "Junior" was invisible to discovery forever. Flagged, not dropped —
    # the cache write filters it, the names harvest does not.
    junior = any(k in title[:200].lower() for k in _JUNIOR_HE)
    return {"_junior": junior,
            "company": comp[:80], "title": title[:140], "location": c["location"][:80],
            # NOT "IL": every normalizer here used to stamp it because the QUERY asked
            # for Israel, which made `israel.is_israel_job` a no-op for the whole discovery
            # layer — it short-circuits on country_code and never reads the text. Leave it
            # blank and let the location decide; verified that the text scan accepts
            # "Tel Aviv", "Haifa", "Yokneam Illit" and rejects "London, United Kingdom".
            "country_code": "", "url": c["url"], "posted_date": d,
            "ats_platform": "discovery-linkedin", "job_id": f"linkedin:{c['job_id']}",
            "description": "",          # public search carries none; jdfill fills it later
            "company_slug": c.get("company_slug", "")}


# --------------------------------------------------------------------------------------- #
# Workable, read across ALL tenants at once
# --------------------------------------------------------------------------------------- #
# Every other source here is job-search-shaped: ask a keyword, get postings. This one asks an
# ATS for every Israeli job on its whole platform, and it is the only source that hands back
# the employer's OWN WEBSITE.
#
# That last part matters more than the jobs. A discovered job's `url` is always the posting —
# on LinkedIn, Indeed or secrethunter — so the `careers_url` this layer seeds into
# research_companies.json is an aggregator for 206 of 1,233 entries (docs/BACKLOG.md item 2),
# and the resolver cannot do anything with it. A Workable record carries
# `company.website`, which is a real lead.
#
# Verified 2026-08-23, keyless, no Bright Data: HTTP 200, `totalSize: 140` Israeli jobs,
# 20 per page, each with company.title + company.website.
# NOT usable the same way: SmartRecruiters' cross-tenant search ignores every geo filter
# tried (country/countryCode/location all returned the same unfiltered 9,649), and
# Recruitee's `jobs.recruitee.com/api/offers/` ignores `location=` and returns NL/PL/DE only.
# ONE page, because pagination does not work and chasing it was stopped deliberately.
# `totalSize` says 140 Israeli jobs; the response carries a `nextPageToken`, and NONE of
# `page` / `offset` / `start` / `from` / the token itself as a query param advances the
# result set — every variant returns the identical first 20 ids (tested 2026-08-23), and
# POSTing the token 404s. So this reaches 20 of 140 and a second request bills nothing but
# wastes time. Worth keeping anyway: those 20 yielded 7 new companies, all 7 with a real
# careers URL, for zero credits. If someone works out the pagination, raise this.
WORKABLE_PAGES = int(os.environ.get("WORKABLE_PAGES", "1"))


def workable_search(location="Israel", pages=None):
    """Every Israeli job on Workable's public cross-tenant board. Keyless, no credits."""
    pages = WORKABLE_PAGES if pages is None else pages
    out, seen = [], set()
    for i in range(pages):
        q = urllib.parse.urlencode({"query": "", "location": location, "page": i})
        req = urllib.request.Request(f"https://jobs.workable.com/api/v1/jobs?{q}",
                                     headers={"User-Agent": _UA_BROWSER,
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            print(f"  [workable] page {i}: {type(e).__name__} {str(e)[:80]}")
            break
        rows = data.get("jobs") or data.get("results") or []
        fresh = [x for x in rows if isinstance(x, dict) and x.get("id") not in seen]
        seen.update(x.get("id") for x in rows if isinstance(x, dict))
        if not fresh:
            break
        out += fresh
    return out


def workable_normalize(r):
    """One Workable cross-tenant record -> the shared discovered-job shape, or None."""
    import datetime as _dt
    c = r.get("company") or {}
    comp = str(c.get("title") or "").strip()
    title = str(r.get("title") or "").strip()
    if not comp or not title:
        return None
    # `created`, not `published`/`created_at` — those two are not in the payload at all, so
    # every Workable job entered the cache with posted_date "" and became immortal (skipped
    # by BOTH the write-side prune and the read-side TTL while _alive refreshes last_seen).
    # Live keys 2026-08-23: benefitsSection company created department description
    # employmentType id isFeatured language location locations requirementsSection
    # socialSharingDescription state title updated url workplace.
    d = str(r.get("created") or r.get("published") or r.get("created_at") or "")[:10]
    d = d or _dt.date.today().isoformat()          # never undated — see linkedin_normalize
    if d < (_dt.date.today() - _dt.timedelta(days=21)).isoformat():
        return None
    junior = any(k in title[:200].lower() for k in _JUNIOR_HE)
    loc = r.get("location") or {}
    # `subregion`, not `region` — `region` is not a key the API sends, so a city-less row
    # silently fell back to a bare "Israel". Live location keys: city countryName subregion.
    city = str(loc.get("city") or loc.get("subregion") or "").strip()
    url = r.get("url") or r.get("shortlink") or ""
    return {"_junior": junior,             # flagged, not dropped — the EMPLOYER still counts
            "company": comp[:80], "title": title[:140],
            "location": (f"{city}, Israel" if city else "Israel")[:80],
            "country_code": "", "url": url,
            "posted_date": d, "ats_platform": "discovery-workable",
            "job_id": f"workable:{r.get('id') or url}", "description": "",
            # the whole reason this source exists: a REAL careers lead, not a posting
            "careers_hint": str(c.get("website") or "").strip()}


def _req(url, data=None, method="GET", timeout=60):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def run_query_raw(ds, disc, inputs, limit):
    q = urllib.parse.urlencode({"dataset_id": ds, "type": "discover_new", "discover_by": disc,
                                "limit_per_input": str(limit)})
    sid = json.loads(_req(f"https://api.brightdata.com/datasets/v3/trigger?{q}",
                          data=json.dumps(inputs).encode(), method="POST")).get("snapshot_id")
    if not sid:
        return []
    st = None
    for _ in range(60):
        st = json.loads(_req(f"https://api.brightdata.com/datasets/v3/progress/{sid}")).get("status")
        if st == "ready":
            break
        if st in ("failed", "error"):
            return []
        time.sleep(15)
    if st != "ready":
        return []                          # timed out still building — fetching now returns an
                                           # error dict, not records (crashed the whole run once)
    body = _req(f"https://api.brightdata.com/datasets/v3/snapshot/{sid}?format=json", timeout=120)
    try:
        recs = json.loads(body)
    except Exception:  # noqa: BLE001
        recs = [json.loads(l) for l in body.splitlines() if l.strip()]
    # a dict here is an API status/error payload, never records; non-dict rows are noise
    if not isinstance(recs, list):
        return []
    return [r for r in recs if isinstance(r, dict)]


_REL = re.compile(r"(\d+)\+?\s*(?:days?|ימים|ימי)", re.I)
_JUNIOR_HE = ("ללא ניסיון", "סטודנט", "משרת סטודנט", "junior")


def _fix_date(raw):
    """Relative dates ('5 days ago', 'לפני 3 ימים') -> ISO; '30+ days' -> None (stale)."""
    import datetime as dt
    t = str(raw or "")
    if len(t) >= 10 and t[4:5] == "-":
        return t[:10]
    m = _REL.search(t)
    if not m:
        return ""
    days = int(m.group(1))
    if "+" in t or days > 21:
        return None                       # stale — drop the job
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def normalize(name, r):
    title = r.get("job_title") or r.get("title") or ""
    comp = r.get("company_name") or r.get("company") or ""
    loc = r.get("job_location") or r.get("location") or "Israel"
    url = r.get("apply_link") or r.get("url") or r.get("job_url") or ""
    date = _fix_date(r.get("job_posted_date") or r.get("date_posted") or r.get("posted_date") or "")
    if date is None:
        return None                        # 30+ days old — not board-worthy
    desc = (r.get("job_summary") or r.get("job_description") or r.get("description") or "")[:6000]
    if not title or not comp:
        return None
    import datetime as _dt2
    date = date or _dt2.date.today().isoformat()   # never undated — see linkedin_normalize
    tl = (str(title) + " " + str(r.get("job_summary") or ""))[:400].lower()
    junior = any(k in tl for k in _JUNIOR_HE)
    return {"_junior": junior,             # flagged, not dropped — the EMPLOYER still counts
            "company": str(comp)[:80], "title": str(title)[:140], "location": str(loc)[:80],
            "country_code": "", "url": url, "posted_date": date,
            "ats_platform": f"discovery-{name}", "job_id": url or f"{comp}|{title}",
            "description": re.sub(r"<[^>]+>", " ", str(desc))}


# --------------------------------------------------------------------------------------- #
# Bright Data spend, month to date
# --------------------------------------------------------------------------------------- #
# NOBODY COULD READ THIS ACCOUNT'S QUOTA. `/customer/balance` answers 403 ("your API key
# lacks the required permissions"), so the "5k free tier" repeated in every docstring here
# was inherited belief, never a checked number — and this lane raised steady-state spend from
# ~190 to ~455 records/day without being able to see the ceiling.
#
# `datasets/v3/snapshots` needs no extra permission and IS the ledger: one row per trigger
# with the `dataset_size` that was billed. Summing the current month gives the only spend
# number this repo can actually produce. It costs one API call and bills no records.
#
# The ceiling is 5,000 credits/month, VERIFIED against Bright Data's own docs on 2026-08-23
# (docs.brightdata.com/general/account/billing-and-pricing/free-tier): "5,000 free credits
# per month", renewing on the 1st, no rollover, shared by Web Unlocker API + SERP API +
# Web Scraper API at one credit per request or record. It is per MONTH, not per day.
# `/customer/balance` would confirm the account's own figure but answers 403 for this token;
# widening its billing scope at https://brightdata.com/cp/setting/users would let this read
# the real number instead of the documented default.
BD_MONTHLY_BUDGET = int(os.environ.get("BD_MONTHLY_BUDGET", "5000"))


def _bd_get(url):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def bd_spend_this_month(today=None):
    """(credits_used_this_month, breakdown_dict); (None, None) on any failure.

    **All four products share ONE pool of 5,000 credits per month** — Web Unlocker API,
    SERP API and Web Scraper API at one credit per request or record, resetting on the 1st
    with no rollover (docs.brightdata.com/general/account/billing-and-pricing/free-tier,
    read 2026-08-23). So counting dataset records alone understates the bill, and it
    understated it badly: 2,989 records looked like 60% of the month, while adding the 646
    unlocker and 471 SERP requests the same account had already spent made it **4,106, or
    82%**. Discovery is not even the only spender — enrich_scrape_jd, enrich_matched_jd,
    bd_rescue, crack_walled, retry_unreachable and deep_validate.google_via_unlocker all
    draw on the same pool from other workflows.

    Two endpoints, because neither has the whole number and `/customer/balance` is 403 for
    this token:
      * `datasets/v3/snapshots`  -> Web Scraper API records (per trigger, `dataset_size`)
      * `zone/cost`              -> `reqs_unblocker` + `reqs_serp` for the zone
    """
    import datetime as _d
    today = today or _d.date.today()
    out = {}
    try:
        month = today.isoformat()[:7]
        rows = _bd_get("https://api.brightdata.com/datasets/v3/snapshots?status=ready")
        if not isinstance(rows, list):
            return None, None
        out["dataset_records"] = sum(int(x.get("dataset_size") or 0) for x in rows
                                     if str(x.get("created") or "")[:7] == month)
    except Exception:  # noqa: BLE001
        return None, None
    try:
        zone = os.environ.get("BRIGHTDATA_ZONE", "")
        first = today.replace(day=1).isoformat()
        d = _bd_get(f"https://api.brightdata.com/zone/cost?zone={zone}"
                    f"&from={first}&to={today.isoformat()}")
        cost = next(iter(d.values()), {}).get("custom", {}) if isinstance(d, dict) else {}
        # An HTTP 200 in an UNRECOGNISED shape — empty dict, a list, renamed keys, or a
        # wrong/empty BRIGHTDATA_ZONE — used to yield a confident 0 + 0, and the caller then
        # reported 2,989 instead of 4,106 (60% instead of 82%): exactly the under-count this
        # function exists to prevent, with no message. Absent keys mean UNREADABLE, not zero.
        if not isinstance(cost, dict) or "reqs_unblocker" not in cost:
            raise ValueError(f"zone/cost returned an unrecognised shape: {str(d)[:120]}")
        out["unlocker_reqs"] = int(cost.get("reqs_unblocker") or 0)
        out["serp_reqs"] = int(cost.get("reqs_serp") or 0)
    except Exception:  # noqa: BLE001
        # partial is better than nothing, but say so rather than under-report silently
        out["unlocker_reqs"] = out["serp_reqs"] = None
    known = [v for v in out.values() if isinstance(v, int)]
    if len(known) < 3:
        # Returning the partial sum was worse than returning nothing: on 2026-08-23 that is
        # 2,989 (dataset only) instead of 4,106 — 60% instead of 82% — which then drives
        # budget_per_day into over-spending AND keeps the 80% warning from ever firing.
        # `budget_per_day` already treats None correctly: an unreadable ledger does not
        # throttle. Unknown must look unknown.
        print("  [bd-spend] zone/cost unavailable — spend UNKNOWN, not throttling")
        return None, out
    return sum(known), out


def report_bd_spend():
    """Print month-to-date Bright Data credit spend, and warn before the ceiling."""
    mtd, parts = bd_spend_this_month()
    if mtd is None:
        print("[bd-spend] ledger unavailable — spend is UNKNOWN")
        return
    pct = 100.0 * mtd / BD_MONTHLY_BUDGET if BD_MONTHLY_BUDGET else 0.0
    detail = ", ".join(f"{k}={v}" for k, v in parts.items())
    print(f"[bd-spend] {mtd} credits used this month ({pct:.0f}% of {BD_MONTHLY_BUDGET}) "
          f"— {detail}. All products share one pool; this is the WHOLE pipeline, not just "
          f"discovery.")
    # Month-end projection, so "is this sustainable" is a number printed daily rather than a
    # question asked once. Overage is cheap and that is the point: $1.50/1K Web Scraper
    # records, $1.00/1K Unlocker or SERP requests (brightdata.com/pricing/web-scraper, read
    # 2026-08-23), so the honest framing is a few dollars a month, not a hard wall.
    import calendar
    import datetime as _d
    t = _d.date.today()
    days_in = calendar.monthrange(t.year, t.month)[1]
    proj = mtd / max(1, t.day) * days_in
    over = max(0, proj - BD_MONTHLY_BUDGET)
    recs = parts.get("dataset_records") or 0
    rec_share = recs / mtd if mtd else 0            # records cost 1.5x what requests do
    cost = over * (rec_share * 1.50 + (1 - rec_share) * 1.00) / 1000
    print(f"[bd-spend] projected month end {proj:.0f} credits"
          + (f" — {over:.0f} over the free pool, about ${cost:.2f} at PAYG rates"
             if over else " — inside the free pool"))
    if pct >= 80:
        print(f"::warning::Bright Data at {pct:.0f}% of the monthly free pool "
              f"({mtd}/{BD_MONTHLY_BUDGET} credits, shared by every workflow that touches "
              f"BD). plan_spend() has already throttled discovery; if this keeps firing the "
              f"other spenders are the problem — see ARCHITECTURE.md 1a.", flush=True)


def budget_per_day(today=None):
    """Records this run may bill, so the month's remaining budget lasts to month end.

    Deep is better — new-company yield accelerates with depth — but a source that exhausts
    the quota on the 24th returns ZERO for the last week of every month, and a silent zero
    from a source that used to produce is the single worst failure mode in this repo
    (`pipeline/sources.py` exists because of one). Pro-rating gets the most records that can
    be sustained every day rather than the most records today.

    Returns None when the ledger is unreadable — callers then use the configured maximum,
    because throttling on a number we could not fetch would be its own silent failure.
    """
    import calendar
    import datetime as _d
    today = today or _d.date.today()
    mtd, _ever = bd_spend_this_month(today)
    if mtd is None:
        return None
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    return max(0, BD_MONTHLY_BUDGET - mtd) / max(1, days_left)


def plan_spend(today=None):
    """(breadth_limit, targeted_cap, explanation) for this run.

    The BREADTH sweep is served first and the targeted backfill takes what is left: breadth
    is the discovery source (0 -> 58 new companies/day when it was given depth), while
    `linkedin-targeted` only ever asks about companies already in `companies.csv`. When the
    budget is generous both run flat out and this function changes nothing.
    """
    per_day = budget_per_day(today)
    if per_day is None:
        return LINKEDIN_LIMIT_MAX, 100, "ledger unreadable — running at configured maximum"
    n_kw = len(_LI_KEYWORDS)
    # CHARGE BREADTH WHAT IT COSTS, NOT WHAT IT USED TO COST. The breadth sweep is billed
    # per REQUEST now (at most LINKEDIN_PAGES per keyword, and usually 0 because the guest
    # endpoint is free) — not per record. Subtracting `breadth_limit * n_kw` reserved
    # 15 x 9 = 135 credits/day for something that costs 18, and since breadth was itself
    # derived from per_day, `left` came out as `per_day mod n_kw` — a number between 0 and 8
    # NO MATTER HOW LARGE THE BUDGET WAS. The targeted backfill was therefore starved at
    # every budget below ~31,000/month, including the "set BD_MONTHLY_BUDGET and both run
    # flat out" case this function's docstring promised. It printed "budget reserved for the
    # breadth sweep", which reserved nothing.
    breadth = LINKEDIN_LIMIT_MAX
    left = per_day - LINKEDIN_PAGES * n_kw
    # the targeted sweep bills ~0.75 records/company (67 for 88, measured), and only what
    # each employer actually has — so a cap of N costs well under N.
    targeted = int(max(0, min(100, left / 0.75)))
    how = (f"budget {per_day:.0f} credits/day -> breadth {n_kw} keywords x{LINKEDIN_PAGES} "
           f"pages (~{LINKEDIN_PAGES * n_kw} paid worst case) + targeted cap {targeted}")
    return breadth, targeted, how


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# Not every stale.json entry is a broken board. `misconfig-scrape-on-ats` is a shape
# warning about the ROW (a scrape row whose URL is really an ATS endpoint) — the board
# itself answers fine and the digest already reads it, so spending a LinkedIn input on it
# buys nothing. The two reasons worth a targeted search are the "board has moved" set:
# `empty-board` (endpoint answers 200 with []) and `regressed-to-zero` (was producing,
# now zero). `fetch-error` is included too — that one is genuinely unreadable today.
_TARGETABLE = ("empty-board", "regressed-to-zero", "fetch-error")


def _targeted_inputs(cap=100, day=None):
    """LinkedIn queries aimed at the companies whose direct ATS is broken AND that the free
    re-capture couldn't fix — the 'unresolvable remainder' (anti-bot Workday, custom-board
    movers). Discovery is the free safety net for exactly these, so we ask about each BY
    COMPANY. This is the recovery path for the largest open coverage item in the repo: the
    active rows whose all-time-high job count is zero because their board MOVED.

    **The company goes in the `company` field, never in `keyword`.** The dataset takes a
    dedicated `company` input, and until 2026-08-23 this function built
    `keyword: "<name> data analyst"` instead — LinkedIn then ranked on "data analyst" and
    treated the name as spare tokens. A/B tested live that day, 20 stale companies each:

        keyword: "<name> data analyst"    160 records billed,  0 on-target
        company: "<name>", keyword: "..."  25 records billed, 22 on-target (88%)

    Two things follow, and the second is why `cap` could go from 20 to 100. Scoping is not
    just more accurate, it is **6x cheaper**: an unscoped keyword query always returns
    `limit_per_input` records (LinkedIn can always fill 8 slots with SOMETHING), while a
    scoped one returns only what that employer actually has — 13 of the 20 returned nothing
    and billed nothing. Measured cost is ~1.25 records/company, so the whole targetable list
    now fits in one run for less than the old 20 cost. `cap` and the rotation below are kept
    only as a bound in case `stale.json` grows past 100; today it holds 88 targetable rows,
    so nothing rotates.

    ROTATES when it has to. `stale.json` is rebuilt every digest in companies.csv row order
    (pipeline/health.record iterates `results.items()`), so `unresolved[:cap]` was a stable
    prefix, not a sample: the same 20 names went to Bright Data every single day and the
    other 90 of 110 were never searched once. The window advances by day-of-year.
    """
    import datetime as _d
    stale = _load_json("cloud_state/stale.json")
    resolved = _load_json("out/resolved_configs.json")
    unresolved = [n for n, e in stale.items()
                  if n not in resolved
                  and (not isinstance(e, dict) or e.get("reason") in _TARGETABLE)]
    if not unresolved:
        return []
    day = _d.date.today().timetuple().tm_yday if day is None else day
    # Clamp BEFORE slicing the doubled list: with cap(100) > len(88) the wrap-around would
    # hand back 12 duplicate names, and a duplicate input is billed twice for the same rows.
    n = min(cap, len(unresolved))
    start = (day * n) % len(unresolved)
    window = (unresolved + unresolved)[start:start + n]
    return [{"location": "Israel", "keyword": "data analyst", "country": "IL",
             "company": name}
            for name in window]


def main():
    _load_secrets()
    os.makedirs("out", exist_ok=True)      # gitignored — absent on cloud runners
    # NOT an early return. Workable and the LinkedIn guest endpoint need no key, and this
    # gate sat above both of them AND above sources.record() — so a rotated secret took the
    # whole intake layer dark, including the free half, and silenced the mechanism built to
    # notice that. Only the paid paths are skipped.
    have_bd = bool(os.environ.get("BRIGHTDATA_API_KEY"))
    if not have_bd:
        print("::warning::no BRIGHTDATA_API_KEY — running the KEYLESS sources only "
              "(Workable, LinkedIn guest, Telegram); Indeed and the targeted backfill are "
              "skipped.", flush=True)
    jobs, seen = [], set()
    per_source = {}
    # `per_source` feeds pipeline/sources.py, which answers ONE question: is this source
    # still returning anything? That is a property of the source, so every entry here counts
    # RAW RECORDS RECEIVED, before normalize()/dedup. Until 2026-08-23 indeed recorded
    # post-filter unique jobs while the dataset sources recorded raw records, so the same
    # number meant two different things and a fully-rejected Indeed page would have been
    # scored as a dead source. The kept count is printed on the line below each source.
    # Indeed first: it is a single unlocked request per query, so it costs seconds and
    # cannot be starved by the dataset polling below timing out.
    n_indeed_raw = 0
    for q in (INDEED_QUERIES if have_bd else []):
        try:
            cards = indeed_search(q)
        except Exception as e:  # noqa: BLE001
            print(f"[indeed:{q}] ERR {type(e).__name__}: {str(e)[:120]}")
            cards = []
        n_indeed_raw += len(cards)
        print(f"[indeed:{q}] {len(cards)} cards")
        for r in cards:
            j = indeed_normalize(r)
            if not j:
                continue
            k = (j["company"].lower(), j["title"].lower())
            if k in seen:
                continue
            seen.add(k)
            jobs.append(j)
    per_source["indeed"] = n_indeed_raw
    print(f"[indeed] {n_indeed_raw} raw cards -> {len(jobs)} unique jobs kept "
          f"across {len(INDEED_QUERIES)} queries")

    # WORKABLE — one ATS, every tenant, keyless. Cheap in credits (zero) and the only source
    # that yields the employer's own website rather than a posting link.
    try:
        wk = workable_search()
    except Exception as e:  # noqa: BLE001
        print(f"[workable] ERR {type(e).__name__}: {str(e)[:120]}")
        wk = []
    per_source["workable"] = len(wk)
    kept_wk = 0
    for r in wk:
        j = workable_normalize(r)
        if not j:
            continue
        k = (j["company"].lower(), j["title"].lower())
        if k in seen:
            continue
        seen.add(k)
        jobs.append(j)
        kept_wk += 1
    print(f"[workable] {len(wk)} Israel jobs across all tenants -> {kept_wk} new (0 credits)")

    # BREADTH — the discovery source. Keyless guest endpoint first, Web Unlocker only where
    # LinkedIn blocks it (1 credit per PAGE of ~60 cards, never per record).
    n_li_raw = n_li_present = 0
    for kw in _LI_KEYWORDS:
        try:
            cards = linkedin_search(kw)
            n_li_present += len(LI_CARDS_PRESENT.pop(kw, set()))
        except Exception as e:  # noqa: BLE001
            print(f"[linkedin:{kw}] ERR {type(e).__name__}: {str(e)[:120]}")
            cards = []
        n_li_raw += len(cards)
        kept = 0
        for c in cards:
            j = linkedin_normalize(c)
            if not j:
                continue
            k = (j["company"].lower(), j["title"].lower())
            if k in seen:
                continue
            seen.add(k)
            jobs.append(j)
            kept += 1
        print(f"[linkedin:{kw}] {len(cards)} cards -> {kept} new")
    # PRESENT, not parsed. `n_li_raw` counts what _li_cards managed to build; if LinkedIn
    # flips an attribute order or wraps the subtitle, half the cards vanish and the source
    # still reports itself healthy. That is this repo's signature failure applied to its own
    # discovery source, so the liveness number is what the page CONTAINED.
    if n_li_present and n_li_raw < n_li_present * 0.8:
        print(f"::warning::LinkedIn parser recovered only {n_li_raw} of {n_li_present} cards "
              f"present — markup drift, check _li_cards. See ARCHITECTURE.md 1a.", flush=True)
    # cards PRESENT is the source's liveness; a broken PARSER is the ::warning:: above,
    # a different failure with a different owner.
    per_source["linkedin"] = n_li_present
    # SOURCE_PATH existed with three writes and ZERO reads — a guard that was documented and
    # did not exist. Which path served is the difference between "LinkedIn went quiet" and
    # "the free endpoint started refusing us and we are now paying for everything".
    print(f"[linkedin] {n_li_raw} cards across {len(_LI_KEYWORDS)} keywords · "
          f"path free={SOURCE_PATH['linkedin_free']} paid={SOURCE_PATH['linkedin_paid']} "
          f"({UNLOCKER_CALLS['linkedin']} Unlocker credits)")
    if SOURCE_PATH["linkedin_paid"] and not SOURCE_PATH["linkedin_free"]:
        print("::warning::LinkedIn free guest endpoint is refusing every request; the whole "
              "breadth sweep is now billed to Bright Data. See ARCHITECTURE.md 1a.",
              flush=True)

    # TARGETED backfill — keeps the dataset, because it needs the `company` filter the
    # public search only exposes as a numeric f_C id we do not have. ~67 credits.
    _unused_breadth, targeted_cap, how = plan_spend() if have_bd else (0, 0, "no BD key")
    print(f"[budget] {how}")
    runs = []
    targeted = _targeted_inputs(cap=targeted_cap) if targeted_cap else []
    if targeted:
        li_ds = LINKEDIN_DATASET
        runs.append(("linkedin-targeted", li_ds, "keyword", targeted, 8))
        print(f"targeting {len(targeted)} unresolved-broken companies via discovery")
    elif not targeted_cap:
        # Record the zero. When stale.json holds no targetable rows — the HEALTHY state — or
        # the budget skips this sweep, the key simply stopped being written and
        # sources.stale() then reported `linkedin-targeted: nothing for Nd` every morning
        # forever: a death report for a source that was switched off on purpose.
        per_source["linkedin-targeted"] = 0
        print("targeted backfill SKIPPED this run — no budget or nothing to target")
    for n, ds, disc, inputs, limit in runs:
        try:
            recs = run_query_raw(ds, disc, inputs, limit)
        except Exception as e:  # noqa: BLE001
            print(f"[{n}] ERR {type(e).__name__}: {str(e)[:120]}")
            recs = []
        print(f"[{n}] {len(recs)} records")
        per_source[n] = len(recs)
        for r in recs:
            j = normalize(n, r)
            if not j:
                continue
            k = (j["company"].lower(), j["title"].lower())
            if k in seen:
                continue
            seen.add(k)
            jobs.append(j)
    # Junior postings were flagged rather than dropped (see linkedin_normalize) so their
    # EMPLOYER still reaches the names funnel. They must not reach the job cache.
    n_junior = sum(1 for j in jobs if j.get("_junior"))
    cacheable = [j for j in jobs if not j.get("_junior")]
    if n_junior:
        print(f"[names] {n_junior} junior/student postings kept for their employer name "
              f"only — not cached, not published")
    if cacheable:
        # MERGE, never truncate. This file is shared with discovery_telegram.py, which runs
        # AFTER this step; a truncating write here deleted every Telegram-sourced job on
        # 2026-08-21 (79 verified roles lost, unrecoverable because the telegram watermark
        # had already advanced past them). Merge by (company,title), prune past the TTL.
        import datetime as _dtm
        cut = (_dtm.date.today() - _dtm.timedelta(days=21)).isoformat()
        # ABSENT is legitimately empty; CORRUPT is not. This function then writes the merged
        # list back, so collapsing the two deleted every cached job from one half-written
        # file — and this is the process that WRITES that file, first, non-atomically, under
        # `|| echo` + continue-on-error. discovery_telegram then advances its watermark over
        # the wreckage. That is the 2026-08-21 incident, 79 verified roles, exactly.
        prev = []
        if os.path.exists("discovered_cache.json"):
            try:
                with open("discovered_cache.json", encoding="utf-8") as _f:
                    prev = json.load(_f)
                if not isinstance(prev, list):
                    raise ValueError(f"expected a list, got {type(prev).__name__}")
            except ValueError as e:
                print(f"::error::discovered_cache.json exists but will not parse ({e}) — "
                      f"NOT overwriting it with this run's jobs alone. Fix or delete the "
                      f"file and re-run; nothing has been lost yet.", flush=True)
                return
        merged, keys = [], set()
        for j in cacheable + [p for p in prev if isinstance(p, dict)]:
            k = ((j.get("company") or "").lower(), (j.get("title") or "").lower())
            if k in keys:
                continue                       # this run's version wins (it is fresher)
            d = str(j.get("posted_date") or "")[:10]
            if d and d < cut:
                continue                       # prune: the read side drops these anyway
            keys.add(k)
            merged.append(j)
        with open("discovered_cache.json", "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1)
        # `len(cacheable)` is pre-dedup, so "carried" could print NEGATIVE — and that was the
        # only tell that the previous cache had been lost. Report both honestly.
        carried = len(merged) - sum(1 for j in cacheable
                                    if ((j.get("company") or "").lower(),
                                        (j.get("title") or "").lower()) in keys)
        print(f"cache: {len(cacheable)} this run -> {len(merged)} total "
              f"({max(0, carried)} carried from previous runs)")
    else:
        print("no records fetched — keeping yesterday's discovered_cache.json")
    # companies we don't scan directly yet -> hand to the auto-expand resolver.
    # VALIDATE AT THE SOURCE (HANDOFF §4d item 9): the employer field arrives verbatim from
    # the aggregator, and sometimes it is the whole posting headline ("Data researcher -
    # Navina") or a staffing agency. Five such rows were ACTIVE and fetched daily before
    # this filter existed, and every downstream layer had to grow its own guard against
    # them. A non-company also costs the nightly hunt a search: it went looking for
    # "AppSec"'s careers page and came back with remoterocketship.com/company/guildmortgage.
    from pipeline.firmographics import looks_like_junk
    from pipeline.recruiters import is_recruiter as _is_rec
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    new_cos = {}
    n_junk = n_rec = 0
    # NEW COMPANIES PER SOURCE is the number this layer exists to produce, and until
    # 2026-08-23 nothing printed it — only the aggregate. That is how the breadth sweep came
    # to return 0 new companies for an unknown length of time while its record count looked
    # perfectly healthy (29 jobs, 27 employers, 25 of them already rows). A source can be
    # alive, on-budget and completely useless at the same time; this is the line that says so.
    import collections as _c
    yield_by_src = _c.Counter()
    seen_by_src = _c.defaultdict(set)
    for j in jobs:
        c = j["company"].strip()
        src = (j.get("ats_platform") or "discovery-?").replace("discovery-", "")
        seen_by_src[src].add(c.lower())
        if c.lower() in have or c.lower() in new_cos:
            continue
        if looks_like_junk(c):
            n_junk += 1
            continue
        if _is_rec(c):
            n_rec += 1
            continue
        # Seed the resolver with a REAL careers lead where the source gave us one
        # (Workable hands back company.website). Otherwise all we have is the posting,
        # which is an aggregator URL — docs/BACKLOG.md item 2.
        new_cos[c.lower()] = {"name": c, "careers_url": j.get("careers_hint") or j["url"],
                              "ats": "unknown", "slug": j.get("company_slug", "")}
        yield_by_src[src] += 1
    if n_junk or n_rec:
        print(f"discovery: rejected {n_junk} job-title-shaped names and {n_rec} agencies "
              f"before they could become rows")
    for src in sorted(seen_by_src):
        n = yield_by_src[src]
        print(f"[yield] {src}: {len(seen_by_src[src])} employers -> {n} NEW companies"
              + ("   <-- discovering nothing" if n == 0 and src.startswith("linkedin") else ""))
    with open("out/discovered_companies.json", "w", encoding="utf-8") as f:
        json.dump(list(new_cos.values()), f, ensure_ascii=False, indent=1)
    # Bridge to auto-expand: out/ is gitignored (ephemeral on cloud runners), so the queue
    # auto_expand.py actually drains is the committed research_companies.json — merge into it.
    if new_cos:
        try:
            research = json.load(open("research_companies.json", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            research = []
        known = {(e.get("name") or "").strip().lower() for e in research}
        added = [v for k, v in new_cos.items() if k not in known]
        if added:
            research.extend(added)
            with open("research_companies.json", "w", encoding="utf-8") as f:
                json.dump(research, f, ensure_ascii=False, indent=1)
            print(f"queued {len(added)} new companies into research_companies.json")
    # A source returning zero is the signal, not the absence of one: the Indeed dataset
    # printed "0 records" every day for five days and nothing ever said a source had died.
    try:
        from pipeline import sources
        sources.record(per_source)
        for line in sources.stale():
            print(f"::warning::discovery source {line}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[source-health] skipped: {e}")
    report_bd_spend()
    print(f"=== {len(jobs)} discovered jobs cached · {len(new_cos)} new companies for migration ===")


if __name__ == "__main__":
    main()
