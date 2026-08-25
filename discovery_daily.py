#!/usr/bin/env python3
"""Daily discovery layer: LinkedIn, Indeed and Workable sweeps for Israel analytics roles.

- Jobs are normalized and merged into discovered_cache.json -> read by fetch_discovery in
  the pipeline (company shown as the real employer, url = posting link).
- Companies NOT already in companies.csv are queued into research_companies.json — the
  auto-expand loop then resolves their own ATS so they migrate to free direct scanning.
- The LinkedIn breadth sweep is keyless (guest endpoint) with a per-page Web Unlocker
  fallback; Workable is keyless; Indeed and the targeted backfill bill Bright Data.

Re-derive the spend before adding a query — never estimate it:

    python -c "import json;print(json.load(open('cloud_state/source_health.json')))"

The measurements behind every dial in this file: docs/sessions/2026-08-24-discovery.md.
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
# new-companies-per-run, not by records or by jobs. LinkedIn ranks by relevance and the
# head of that ranking is saturated with registry rows and agencies — UNKNOWN COMPANIES
# LIVE IN THE TAIL (measured: first 15 records -> 1 new company, first 100 -> 15), so if
# new-company yield ever reads 0, depth and recency (`f_TPR`) are the first dials.
# Kept only because plan_spend still reports a breadth "limit"; the real dials are
# LINKEDIN_PAGES, LINKEDIN_GUEST_PAGES, INDEED_DAYS and linkedin_search's `days=`.
LINKEDIN_LIMIT_MAX = int(os.environ.get("LINKEDIN_LIMIT_MAX", "100"))
# WIDTH beats depth: LinkedIn's PAID search runs out at ~60-85 jobs per keyword however
# many pages you ask for, and a keyword costs ~2 credits, so the answer to a falling yield
# is more keywords. Marginal contribution per keyword, measured 2026-08-23 (order-dependent
# — a later keyword sees fewer unknowns — so re-measure the whole list, not one row):
#
#   data analyst          64 employers  17 new     analytics          +2   +2
#   business intelligence +6            +4         data scientist     +24  +11
#   product analyst       +14           +5         אנליסט              +19  +5
#   BI developer          +7            +5         growth analyst     +26  +16
#                                                  marketing analyst  +12  +7
#   dropped: "BI analyst" (+1 employer) and "insights analyst" (+0) — saturated
#
# DO NOT COMBINE THEM INTO ONE BOOLEAN OR QUERY. The result cap is PER QUERY, not per
# keyword, so one combined query buys ONE window: measured, 10 new companies against 76
# from nine separate queries. That window mechanism is why this list is long and flat.
_LI_KEYWORDS = ["data analyst", "business intelligence", "product analyst", "BI developer",
                "analytics", "data scientist", "אנליסט", "growth analyst",
                "marketing analyst"]

# The same window mechanism, applied to GEOGRAPHY: a city location is its own query, so it
# opens its own ~10-cards-a-page window centred on that city (verified 2026-08-24: both
# strings below return a radius around the named city, not a global fallback). Measured
# 2026-08-23 against the national window: Be'er Sheva 14 of 20 jobs unseen nationally,
# Haifa 11 of 20 — Jerusalem 3 of 31 and Herzliya 0 of 20 are inside the Tel Aviv-weighted
# national window already, so metro cities buy nothing and stay OUT of this list.
_LI_CITIES = ["Be'er Sheva, Israel", "Haifa, Israel"]


def _li_queries():
    """Every breadth query as (keyword, location, pages): national queries keep the paid
    Unlocker fallback (pages=None -> LINKEDIN_PAGES); city queries pass pages=0, which the
    fallback gate reads as 'no paid budget' — they are free-only BY CONSTRUCTION, so a
    blocked runner can never make the city product bill."""
    return ([(kw, "Israel", None) for kw in _LI_KEYWORDS]
            + [(kw, city, 0) for city in _LI_CITIES for kw in _LI_KEYWORDS])

# Used only by the targeted backfill. The breadth sweep's old dataset config is deleted,
# not parked — an unused constant that reads like a setting is a trap (see the Indeed note).
LINKEDIN_DATASET = "gd_lpfll7v5hcqtkxl6l"

# DEAD END: the Bright Data Indeed DATASET (gd_l4dx9j9sscpvs7no2) is rate-limited by Indeed
# on every input — five straight days of `dataset_size: 0`, printed "[indeed] 0 records",
# nobody noticed. Do not re-enable it. Indeed is read through the Web Unlocker instead:
# il.indeed.com embeds its results as one JSON blob, so one rendered request per query
# replaces a 90-second snapshot job.
INDEED_QUERIES = ["data analyst", "business intelligence", "BI developer",
                  "product analyst", "אנליסט"]
INDEED_DAYS = 7          # fromage: only postings from the last week are worth discovering

_MOSAIC = re.compile(
    r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});', re.S)


def indeed_search(query, days=INDEED_DAYS, limit=25, tries=2):
    """Return raw Indeed job cards for one Israel query.

    Retries once (the fetch failure mode is transient) and always prints WHY it got
    nothing: an unlocker failure, a bot wall with no mosaic blob, and a genuinely empty
    result set must never collapse into the same bare "0 cards" (ARCHITECTURE.md §8.2)."""
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
# THE TWO BRIGHT DATA PRODUCTS BILL DIFFERENTLY, and the difference is ~55x: the dataset
# charges 1 credit per RECORD (391 jobs = 391 credits from one trigger), the Web Unlocker
# 1 credit per REQUEST (one rendered public-search page = 60 cards = 1 credit). So the
# breadth sweep reads `linkedin.com/jobs/search` and gives up the dataset's `job_summary`
# — acceptable because its product is EMPLOYER NAMES; a surviving role gets its text from
# `pipeline/jdfill.py` later. The targeted sweep keeps the dataset: it needs the `company`
# filter, which the public search only exposes as a numeric `f_C` id we do not have.
#
# `f_TPR=r604800` is the past-week window (seconds) and it verifiably filters (past-week
# and past-month overlapped by only 20 of 60).
# TWO paid pages, because the PAID search hard-caps at ~80 distinct jobs per keyword and
# two requests reach all 80 (measured: start=50/75/100 all returned 0 new cards) — a third
# is pure waste, and depth beyond 80 is not for sale on this endpoint at any price.
LINKEDIN_PAGES = int(os.environ.get("LINKEDIN_PAGES", "2"))   # PAID pages per keyword
# How many consecutive empty guest pages before the pool is called finished. Free requests,
# so tolerance is nearly free; one blank is NOT exhaustion (measured: a walk that stopped at
# the first blank saw 55 of 71 reachable jobs).
LINKEDIN_BLANK_TOLERANCE = int(os.environ.get("LINKEDIN_BLANK_TOLERANCE", "3"))
# The FREE walk's own bound, deliberately NOT derived from LINKEDIN_PAGES (the paid dial).
# Tying them together silently zeroed the free walk when the paid dial was zeroed. And the
# paid page's ~80-job cap does NOT apply here: the guest endpoint goes 200+ deep (measured:
# `analytics` 201 jobs / 148 employers). 50, not 30: the 2026-08-24 run ended FOUR keywords
# on the 30-page cap with pools not exhausted (208/206/226/269 jobs) — 500 card slots is
# ~1.9x the deepest pool seen. Free requests; the cost is seconds.
LINKEDIN_GUEST_PAGES = int(os.environ.get("LINKEDIN_GUEST_PAGES", "50"))
# Credits are the unit that matters and nothing counted them per source. One Unlocker call =
# one credit, so this IS the bill for the sweeps that use it.
import collections as _collections
UNLOCKER_CALLS = _collections.Counter()
# Which PATH served each source — free or paid. A free path that silently starts
# returning nothing looks identical to a dead source unless this is recorded.
SOURCE_PATH = _collections.Counter()
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# The `</li>` in the lookahead is load-bearing: without it the LAST card on a page runs to
# the end of the document and absorbs the right-rail "people also viewed" block (same
# `base-search-card` classes, no jobPosting urn, so no boundary) — which once emitted a
# London job as a Tel Aviv one under the previous card's id. Every page has a last card.
_LI_CARD = re.compile(
    r'data-entity-urn="urn:li:jobPosting:(?P<id>\d+)"(?P<body>.*?)'
    r'(?=data-entity-urn="urn:li:jobPosting:|</li>|\Z)', re.S)
_LI_URL = re.compile(r'base-card__full-link[^>]*href="([^"?]+)')
_LI_TITLE = re.compile(r'<span class="sr-only">\s*(.*?)\s*</span>', re.S)
_LI_COMPANY = re.compile(
    r'base-search-card__subtitle[^>]*>\s*(?:<a[^>]*>)?\s*([^<]{2,80})', re.S)
# The employer's LinkedIn SLUG (same subtitle block, same bytes) is worth more than the
# display name: a stable identifier, the only NON-aggregator seed this layer can hand the
# resolver (docs/BACKLOG.md item 2), and a free is_recruiter signal
# (`barak-recruitment-and-consultancy`).
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
    """LinkedIn job search: KEYLESS guest endpoint first, Web Unlocker only where blocked.

    LinkedIn does not talk to every machine (GitHub's Azure ranges are among the
    most-blocked), so the paid path stays, and `SOURCE_PATH` records which path actually
    served — without that record a free path silently returning nothing looks exactly like
    a dead source. Walks until the pool is exhausted or the page cap trips (and says which).
    `pages` is the PAID budget; 0 makes the query free-only (the city windows rely on it).
    """
    from bd_rescue import unlock
    pages = LINKEDIN_PAGES if pages is None else pages
    # A query is (keyword, location) — the city windows re-run the same keywords, so both
    # the drift denominator and the log label must carry the location or they collide.
    qkey = (keyword, location)
    qlabel = keyword if location == "Israel" else f"{keyword} @ {location}"
    seen, out = set(), []
    # guest pages hold 10, unlocked pages hold 60 — same 80-job pool, different step size
    paid_pages, blanks, repeats = 0, 0, 0
    ended_on_cap = True
    for i in range(LINKEDIN_GUEST_PAGES):
        cards, ok = _li_guest(keyword, location, days, i * 10)
        # THREE states, and conflating any two loses jobs:
        #   ok + cards  -> the good case
        #   ok + blank  -> AMBIGUOUS: the endpoint emits intermittent 200-empty pages INSIDE
        #                  the pool (an HTTP 200 empty body is also its soft rate-limit), so
        #                  one blank is not exhaustion — probing is free, so probe.
        #   not ok      -> blocked: use the paid path, for EVERY page of the budget.
        if ok and cards:
            SOURCE_PATH["linkedin_free"] += 1
            LI_CARDS_PRESENT[qkey] |= _li_last_present[0]
            blanks = 0
        elif ok:
            # `linkedin_blank`, never the free counter: a blank is a request MADE, not one
            # that PRODUCED, and bumping free here disarms the `paid and not free` soft-block
            # alarm at the end of the sweep — the exact case that alarm exists for.
            SOURCE_PATH["linkedin_blank"] += 1
            # record the denominator even on a blank, or a page whose urns we fail to parse
            # contributes nothing to the drift metric and the regression stays invisible
            LI_CARDS_PRESENT[qkey] |= _li_last_present[0]
            blanks += 1
            if blanks < LINKEDIN_BLANK_TOLERANCE:
                continue              # a hole inside the pool — free to step over
            if out:
                ended_on_cap = False
                break                 # cards already collected and the tail is quiet: done
            # Nothing at all after the tolerance: a working-but-empty keyword and a soft
            # rate-limit are indistinguishable — buy ONE paid page to tell them apart.
        if not ok or (blanks >= LINKEDIN_BLANK_TOLERANCE and not out):
            if paid_pages >= pages or not os.environ.get("BRIGHTDATA_API_KEY"):
                break                 # paid budget spent, or there is no paid path at all
            # The paid page index is its OWN counter: reusing the guest index under a hard
            # block only ever fetched start=0, silently dropping ~20 of ~80 cards a keyword.
            q = urllib.parse.urlencode({"keywords": keyword, "location": location,
                                        "f_TPR": f"r{days * 86400}", "start": paid_pages * 25})
            html = unlock(f"https://www.linkedin.com/jobs/search?{q}", timeout=120)
            UNLOCKER_CALLS["linkedin"] += 1
            SOURCE_PATH["linkedin_paid"] += 1
            paid_pages += 1
            blanks = 0
            LI_CARDS_PRESENT[qkey] |= _li_urn_ids(html)
            cards = _li_cards(html)
            if not cards:
                print(f"  [linkedin:{qlabel}] page {i}: no cards from EITHER path "
                      f"({len(html or '')} bytes unlocked) — markup change or hard block")
                break
        if not cards:
            break
        # Deliberately NO `elif out: break` here — that limited a hard-blocked guest endpoint
        # to ONE paid page. The loop is bounded by `paid_pages >= pages` and by freshness.
        fresh = [c for c in cards if c["job_id"] not in seen]
        seen.update(c["job_id"] for c in cards)
        out += fresh
        if fresh:
            repeats = 0
            continue
        # A page of entirely-repeated cards is NOT proof the pool is finished: the guest
        # paging is unstable and re-serves windows (breaking on the first repeat made the
        # same keyword yield 16 jobs or 100 depending on the minute). Tolerate a few.
        repeats += 1
        if repeats >= LINKEDIN_BLANK_TOLERANCE:
            ended_on_cap = False
            break
    else:
        ended_on_cap = True
    if ended_on_cap and out:
        # Ending on the iteration cap means there was more to read. Never silent: a walk that
        # stopped because it ran out of iterations must not look like one that ran out of jobs.
        print(f"  [linkedin:{qlabel}] stopped at the {LINKEDIN_GUEST_PAGES}-page cap with "
              f"{len(out)} jobs — raise LINKEDIN_GUEST_PAGES, the pool was not exhausted")
    return out


def linkedin_normalize(c):
    """One public-search card -> the shared discovered-job shape (or None to drop it)."""
    import datetime as _dt
    title, comp = c["title"], c["company"]
    if not title or not comp:
        return None
    # Stamp today when the card carries no <time datetime> (promoted/reposted cards often
    # do not): an undated job is skipped by BOTH the write-side prune and the read-side
    # TTL, so it never ages out and sits on the board forever.
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
# Asks one ATS for every Israeli job on its whole platform, keyless — and it is the ONLY
# source that hands back the employer's own website (`company.website`): every other
# source's url is a POSTING, which is why 206 of 1,233 research-queue seeds are aggregators
# (docs/BACKLOG.md item 2). DEAD ENDS, do not re-try: SmartRecruiters' cross-tenant search
# ignores every geo filter (country/countryCode/location all return the same 9,649), and
# Recruitee's cross-tenant API ignores `location=` (NL/PL/DE only).
#
# ONE page, a dead end chased to the wall (2026-08-23): `totalSize` says 140 Israeli jobs,
# but NONE of `page` / `offset` / `start` / `from` / the response's own `nextPageToken` as
# a query param advances past the identical first 20 ids, and POSTing the token 404s.
# Still worth keeping: those 20 yielded 7 new companies, all with a real careers URL, for
# zero credits. If someone works out the pagination, raise this.
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
    # `created` is the key the payload actually carries — `published`/`created_at` are not
    # in it, and an empty posted_date makes a job immortal (see linkedin_normalize).
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
# `/customer/balance` answers 403 for this token, so the account's own ceiling is
# unreadable; `datasets/v3/snapshots` + `zone/cost` need no extra permission and ARE the
# ledger. The ceiling used is 5,000 credits/month — verified against Bright Data's docs
# (docs.brightdata.com/general/account/billing-and-pricing/free-tier): renews on the 1st,
# no rollover, shared by Web Unlocker + SERP + Web Scraper at 1 credit/request-or-record.
# Per MONTH, not per day.
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

    All products share ONE monthly pool, so counting dataset records alone understates the
    bill badly (measured: 60% reported at a true 82%) — and discovery is not the only
    spender: six other scripts draw on the same pool from other workflows. Two endpoints,
    because neither has the whole number and `/customer/balance` is 403 for this token:
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
        # An HTTP 200 in an unrecognised shape must read as UNREADABLE, never as zero —
        # and validate the VALUE, not key presence (a JSON null passes `in` and int()s to a
        # confident 0). Pin the zone: next(iter(...)) reads an arbitrary one.
        if isinstance(d, dict) and zone and zone in d:
            cost = d[zone].get("custom", {}) if isinstance(d.get(zone), dict) else {}
        if not isinstance(cost, dict) or not isinstance(cost.get("reqs_unblocker"),
                                                        (int, float)):
            raise ValueError(f"zone/cost returned an unrecognised shape: {str(d)[:120]}")
        out["unlocker_reqs"] = int(cost.get("reqs_unblocker") or 0)
        out["serp_reqs"] = int(cost.get("reqs_serp") or 0)
    except Exception:  # noqa: BLE001
        # partial is better than nothing, but say so rather than under-report silently
        out["unlocker_reqs"] = out["serp_reqs"] = None
    known = [v for v in out.values() if isinstance(v, int)]
    if len(known) < 3:
        # A partial sum is worse than nothing: it under-reports, over-spends AND silences
        # the 80% warning. budget_per_day treats None correctly — unknown must look unknown.
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
    # Deliberately NOT len(_li_queries()): the city windows pass pages=0 and structurally
    # cannot reach the paid path, so only the national keywords can bill.
    n_kw = len(_LI_KEYWORDS)
    # CHARGE BREADTH WHAT IT COSTS: per REQUEST (at most LINKEDIN_PAGES per keyword, and
    # usually 0 — the guest endpoint is free), never per record. Reserving the per-record
    # figure starved the targeted backfill at every realistic budget.
    breadth = LINKEDIN_LIMIT_MAX
    left = per_day - LINKEDIN_PAGES * n_kw
    # the targeted sweep bills ~0.75 records/company (67 for 88, measured), and only what
    # each employer actually has — so a cap of N costs well under N.
    targeted = int(max(0, min(100, left / 0.75)))
    how = (f"budget {per_day:.0f} credits/day -> breadth {n_kw} keywords x{LINKEDIN_PAGES} "
           f"pages (~{LINKEDIN_PAGES * n_kw} paid worst case) + targeted cap {targeted}")
    return breadth, targeted, how


# Below this, a targeted run is waste: the 2026-08-24 run's cap of 4 (Bright Data pool at
# 97%) still triggered a dataset snapshot and up to 15 min of polling, burned a slot in the
# 22-day rotation over the ~88 targetable rows, and returned ZERO records. Ten covers the
# rotation in ~9 days for well under 10 credits; anything smaller degenerates.
TARGETED_MIN_CAP = int(os.environ.get("TARGETED_MIN_CAP", "10"))


def _targeted_cap_or_zero(cap):
    """A starved targeted cap becomes an explicit skip, never a doomed trigger. BACKLOG
    item 8: the targeted sweep is the first thing cut when the budget binds."""
    if 0 < cap < TARGETED_MIN_CAP:
        print(f"[linkedin-targeted] cap {cap} below useful minimum {TARGETED_MIN_CAP} — "
              f"dataset trigger skipped, the budget recovers it automatically")
        return 0
    return cap


def is_place_name(name):
    """True when a 'company name' is a city / region / country. A Telegram post with no
    company line put its CITY in the employer slot (2026-08-20, "Director of finance" at
    "Tel Aviv"); the name passed is_recruiter and looks_like_junk, was queued, resolved by
    listing_hunt onto secrethunter's Tel Aviv city board and ACTIVATED — 145 cards of other
    companies' jobs, 7 on the board, 2 in the 2026-08-25 mail. No downstream identity check
    can refuse a company named after the city its host is named after
    (`registry_health --explain "Tel Aviv"` -> tenant_is_this_company = True), so intake is
    the one gate that can say no. Exact match on the whole name — "Jerusalem Venture
    Partners" is an employer, "Jerusalem" is not."""
    from pipeline import israel as _il
    n = " ".join(str(name or "").strip().lower().replace("-", " ").split())
    return bool(n) and n in {p.lower().replace("-", " ") for p in _il._IL_PLACES + _il._IL_PLACES_HE}


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

    **The company goes in the `company` field, never in `keyword`** — concatenated into the
    keyword, LinkedIn ranks on the keyword and treats the name as spare tokens. A/B, 20
    stale companies each:

        keyword: "<name> data analyst"    160 records billed,  0 on-target
        company: "<name>", keyword: "..."  25 records billed, 22 on-target (88%)

    Scoping is also ~6x cheaper: a scoped query bills only what that employer actually has
    (~1.25 records/company). ROTATES by day-of-year: `stale.json` is rebuilt in stable row
    order, so a fixed `[:cap]` prefix is not a sample — it re-searches the same names daily
    and never reaches the rest.
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
    # still returning anything? That is a property of the SOURCE, so every entry counts RAW
    # RECORDS RECEIVED, before normalize()/dedup — a fully-rejected page is not a dead
    # source. Indeed first: one unlocked request per query, so it cannot be starved by the
    # dataset polling below timing out.
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
    # LinkedIn blocks it (1 credit per PAGE of ~60 cards, never per record). National queries
    # first, then the free-only city windows (see _li_queries).
    n_li_raw = n_li_present = 0
    queries = _li_queries()
    for kw, loc, pg in queries:
        label = kw if loc == "Israel" else f"{kw} @ {loc}"
        try:
            cards = linkedin_search(kw, pages=pg, location=loc)
            n_li_present += len(LI_CARDS_PRESENT.pop((kw, loc), set()))
        except Exception as e:  # noqa: BLE001
            print(f"[linkedin:{label}] ERR {type(e).__name__}: {str(e)[:120]}")
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
        print(f"[linkedin:{label}] {len(cards)} cards -> {kept} new")
    # PRESENT, not parsed: if LinkedIn changes its markup, half the cards vanish from the
    # parse while the source still looks healthy — liveness is what the page CONTAINED.
    if n_li_present and n_li_raw < n_li_present * 0.8:
        print(f"::warning::LinkedIn parser recovered only {n_li_raw} of {n_li_present} cards "
              f"present — markup drift, check _li_cards. See ARCHITECTURE.md 1a.", flush=True)
    per_source["linkedin"] = n_li_present
    # Which path served is the difference between "LinkedIn went quiet" and "the free
    # endpoint started refusing us and we are now paying for everything".
    print(f"[linkedin] {n_li_raw} cards across {len(queries)} queries "
          f"({len(_LI_KEYWORDS)} national + {len(queries) - len(_LI_KEYWORDS)} city, free-only) · "
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
    # AFTER the [budget] line, so the budget stays a truthful record of what plan_spend said.
    targeted_cap = _targeted_cap_or_zero(targeted_cap)
    runs = []
    targeted = _targeted_inputs(cap=targeted_cap) if targeted_cap else []
    if targeted:
        li_ds = LINKEDIN_DATASET
        # Cap by RECORDS against the trigger's own limit, not against the empirical 0.75
        # records/company: the API's worst case is limit_per_input * inputs = 800 records
        # in one morning if the `company` scoping ever stops working.
        per_input = max(1, min(8, int(targeted_cap / max(1, len(targeted)))))
        runs.append(("linkedin-targeted", li_ds, "keyword", targeted, per_input))
        print(f"targeting {len(targeted)} unresolved-broken companies via discovery")
    else:
        # Record the zero whenever the sweep does not run, for EITHER reason (no budget OR
        # nothing to target) — an unwritten key freezes `last_run` and reads as a death
        # report for a source that was working perfectly.
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
        # MERGE, never truncate: discovery_telegram.py shares this file and runs AFTER this
        # step — a truncating write here cost 79 verified Telegram roles once (2026-08-21),
        # unrecoverable because the telegram watermark had advanced past them. And ABSENT is
        # legitimately empty while CORRUPT is not: overwriting a half-written file with this
        # run's jobs alone is the same incident by another door.
        import datetime as _dtm
        cut = (_dtm.date.today() - _dtm.timedelta(days=21)).isoformat()
        prev = []
        if os.path.exists("discovered_cache.json"):
            try:
                with open("discovered_cache.json", encoding="utf-8") as _f:
                    prev = json.load(_f)
                if not isinstance(prev, list):
                    raise ValueError(f"expected a list, got {type(prev).__name__}")
                if prev and not any(isinstance(x, dict) for x in prev):
                    # a valid list of non-dicts passes the type check and is then silently
                    # emptied by the `isinstance(p, dict)` filter below — the one corrupt
                    # shape that still destroyed the cache
                    raise ValueError(f"list of {type(prev[0]).__name__}, not job dicts")
            except ValueError as e:
                # Skip the CACHE WRITE only, never `return`: main() must always reach
                # sources.record(), the spend report and the names bridge (see the no-return
                # test). Fail safe on the file; keep reporting.
                print(f"::error::discovered_cache.json exists but will not parse ({e}) — "
                      f"NOT overwriting it with this run's jobs alone. Fix or delete the "
                      f"file and re-run; nothing has been lost yet.", flush=True)
                cacheable = []
        merged, keys = [], set()
        for j in (cacheable + [p for p in prev if isinstance(p, dict)]) if cacheable else []:
            k = ((j.get("company") or "").lower(), (j.get("title") or "").lower())
            if k in keys:
                continue                       # this run's version wins (it is fresher)
            d = str(j.get("posted_date") or "")[:10]
            if d and d < cut:
                continue                       # prune: the read side drops these anyway
            keys.add(k)
            merged.append(j)
        if cacheable:
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
    # VALIDATE AT THE SOURCE: the employer field arrives verbatim from the aggregator and is
    # sometimes a posting headline ("Data researcher - Navina") or a staffing agency —
    # unfiltered, such rows went ACTIVE and every downstream layer grew its own guard.
    from pipeline.firmographics import looks_like_junk
    from pipeline.recruiters import is_recruiter as _is_rec
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    new_cos = {}
    n_junk = n_rec = n_place = 0
    # NEW COMPANIES PER SOURCE is the number this layer exists to produce — a source can be
    # alive, on-budget and completely useless at the same time (a healthy-looking record
    # count once hid a 0-new-companies breadth sweep), and this is the line that says so.
    import collections as _c
    yield_by_src = _c.Counter()
    seen_by_src = _c.defaultdict(set)
    for j in jobs:
        c = j["company"].strip()
        src = (j.get("ats_platform") or "discovery-?").replace("discovery-", "")
        seen_by_src[src].add(c.lower())
        if c.lower() in have:
            continue
        if c.lower() in new_cos:
            # Already queued from an earlier source — but UPGRADE the seed if this one is
            # better. Sources run Indeed-first, so a company appearing in both Indeed and
            # Workable kept Indeed's POSTING url and threw away Workable's company.website,
            # degrading the single thing that source exists to provide.
            if j.get("careers_hint") and not new_cos[c.lower()].get("_real_lead"):
                new_cos[c.lower()]["careers_url"] = j["careers_hint"]
                new_cos[c.lower()]["_real_lead"] = True
            continue
        if looks_like_junk(c):
            n_junk += 1
            continue
        if is_place_name(c):
            n_place += 1
            continue
        # the slug is free evidence the display name hides ("Dialog" / dialog-recruiting)
        if _is_rec(c, j.get("company_slug", "")):
            n_rec += 1
            continue
        # Seed the resolver with a REAL careers lead where the source gave us one
        # (Workable hands back company.website). Otherwise all we have is the posting,
        # which is an aggregator URL — docs/BACKLOG.md item 2.
        new_cos[c.lower()] = {"name": c, "careers_url": j.get("careers_hint") or j["url"],
                              "ats": "unknown", "slug": j.get("company_slug", ""),
                              "_real_lead": bool(j.get("careers_hint"))}
        yield_by_src[src] += 1
    if n_junk or n_rec or n_place:
        print(f"discovery: rejected {n_junk} job-title-shaped names, {n_place} place names "
              f"and {n_rec} agencies before they could become rows")
    for src in sorted(seen_by_src):
        n = yield_by_src[src]
        print(f"[yield] {src}: {len(seen_by_src[src])} employers -> {n} NEW companies"
              + ("   <-- discovering nothing" if n == 0 and src.startswith("linkedin") else ""))
    for _v in new_cos.values():
        _v.pop("_real_lead", None)          # internal, never written to the shared queue
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
