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
LINKEDIN_LIMIT_MAX = int(os.environ.get("LINKEDIN_LIMIT_MAX", "100"))
LINKEDIN_LIMIT_MIN = int(os.environ.get("LINKEDIN_LIMIT_MIN", "15"))
LINKEDIN_WINDOW = os.environ.get("LINKEDIN_WINDOW", "Past week")
_LI_KEYWORDS = ["data analyst", "business intelligence", "product analyst", "BI developer"]

QUERIES = {
    "linkedin": ("gd_lpfll7v5hcqtkxl6l", "keyword", [
        {"location": "Israel", "keyword": k, "country": "IL", "time_range": LINKEDIN_WINDOW}
        for k in _LI_KEYWORDS
    ], LINKEDIN_LIMIT_MAX),
    # NOTE: the Bright Data Indeed dataset (gd_l4dx9j9sscpvs7no2) has returned ZERO records
    # every single run since it was wired up — every snapshot comes back
    # `dataset_size: 0, error_codes: {"rate_limit": 15}`, i.e. Indeed rate-limits that
    # collector for all 15 inputs. It printed "[indeed] 0 records" and nobody noticed for
    # five days. Indeed is fetched through the Web Unlocker instead — see indeed_search().
}

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
    for attempt in range(tries):
        html = unlock(url, timeout=100)
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
    if date and date < (_dt.date.today() - _dt.timedelta(days=21)).isoformat():
        return None
    desc = ""
    sn = r.get("snippet") or ""
    if sn:
        desc = re.sub(r"<[^>]+>", " ", str(sn))
    if any(k in f"{title} {desc}"[:400].lower() for k in _JUNIOR_HE):
        return None                        # same junior/student cut as the dataset path
    return {"company": comp[:80], "title": title[:140],
            "location": (r.get("formattedLocation") or "Israel")[:80],
            "country_code": "IL", "url": f"https://il.indeed.com/viewjob?jk={jk}",
            "posted_date": date, "ats_platform": "discovery-indeed",
            "job_id": f"indeed:{jk}", "description": desc}


def _req(url, data=None, method="GET", timeout=60):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def run_query(name):
    ds, disc, inputs, limit = QUERIES[name]
    return run_query_raw(ds, disc, inputs, limit)


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
    tl = (str(title) + " " + str(r.get("job_summary") or ""))[:400].lower()
    if any(k in tl for k in _JUNIOR_HE):
        return None                        # junior/student postings out
    return {"company": str(comp)[:80], "title": str(title)[:140], "location": str(loc)[:80],
            "country_code": "IL", "url": url, "posted_date": date,
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
        out["unlocker_reqs"] = int(cost.get("reqs_unblocker") or 0)
        out["serp_reqs"] = int(cost.get("reqs_serp") or 0)
    except Exception:  # noqa: BLE001
        # partial is better than nothing, but say so rather than under-report silently
        out["unlocker_reqs"] = out["serp_reqs"] = None
    known = [v for v in out.values() if isinstance(v, int)]
    if len(known) < 3:
        print("  [bd-spend] zone/cost unavailable — unlocker+SERP credits NOT counted")
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
    breadth = int(min(LINKEDIN_LIMIT_MAX, max(LINKEDIN_LIMIT_MIN, per_day // n_kw)))
    left = per_day - breadth * n_kw
    # the targeted sweep bills ~0.75 records/company (67 for 88, measured), and only what
    # each employer actually has — so a cap of N costs well under N.
    targeted = int(max(0, min(100, left / 0.75)))
    how = (f"budget {per_day:.0f} rec/day -> breadth limit {breadth} x{n_kw} keywords"
           f" + targeted cap {targeted}")
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
    if not os.environ.get("BRIGHTDATA_API_KEY"):
        print("no BRIGHTDATA_API_KEY; skipping discovery")
        return
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
    for q in INDEED_QUERIES:
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

    breadth_limit, targeted_cap, how = plan_spend()
    print(f"[budget] {how}")
    runs = [(n, ds, disc, inputs, breadth_limit if n == "linkedin" else lim)
            for n, (ds, disc, inputs, lim) in ((k, QUERIES[k]) for k in QUERIES)]
    targeted = _targeted_inputs(cap=targeted_cap) if targeted_cap else []
    if targeted:
        li_ds = QUERIES["linkedin"][0]
        runs.append(("linkedin-targeted", li_ds, "keyword", targeted, 8))
        print(f"targeting {len(targeted)} unresolved-broken companies via discovery")
    elif not targeted_cap:
        print("targeted backfill SKIPPED this run — budget reserved for the breadth sweep")
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
    if jobs:
        # MERGE, never truncate. This file is shared with discovery_telegram.py, which runs
        # AFTER this step; a truncating write here deleted every Telegram-sourced job on
        # 2026-08-21 (79 verified roles lost, unrecoverable because the telegram watermark
        # had already advanced past them). Merge by (company,title), prune past the TTL.
        import datetime as _dtm
        cut = (_dtm.date.today() - _dtm.timedelta(days=21)).isoformat()
        try:
            prev = json.load(open("discovered_cache.json", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev = []
        merged, keys = [], set()
        for j in jobs + [p for p in prev if isinstance(p, dict)]:
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
        print(f"cache: {len(jobs)} this run + {len(merged) - len(jobs)} carried = {len(merged)}")
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
        new_cos[c.lower()] = {"name": c, "careers_url": j["url"], "ats": "unknown", "slug": ""}
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
