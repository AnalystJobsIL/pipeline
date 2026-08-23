#!/usr/bin/env python3
"""Daily discovery layer: LinkedIn + Indeed jobs scrapers (Bright Data) for Israel analytics roles.

- Triggers small discovery queries (quota-capped), waits, fetches records.
- Jobs are normalized and written to discovered_cache.json -> read by fetch_discovery in the
  pipeline (company shown as the real employer, url = posting link).
- Companies NOT already in companies.csv are written to out/discovered_companies.json — the
  auto-expand loop then resolves their own ATS so they migrate to free direct scanning.

Budget: ~40 records/day * 30 = ~1200/mo of the 5k free tier, split LinkedIn/Indeed.
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


QUERIES = {
    "linkedin": ("gd_lpfll7v5hcqtkxl6l", "keyword", [
        {"location": "Israel", "keyword": "data analyst", "country": "IL"},
        {"location": "Israel", "keyword": "business intelligence", "country": "IL"},
    ], 15),
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


def indeed_search(query, days=INDEED_DAYS, limit=25):
    """Return raw Indeed job cards for one Israel query (empty list on any failure)."""
    from bd_rescue import unlock
    url = ("https://il.indeed.com/jobs?q=" + urllib.parse.quote_plus(query)
           + "&l=" + urllib.parse.quote_plus("Israel") + f"&fromage={days}")
    html = unlock(url, timeout=100)
    m = _MOSAIC.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    res = (data.get("metaData", {}).get("mosaicProviderJobCardsModel", {})
               .get("results", []) or [])
    return [r for r in res if isinstance(r, dict)][:limit]


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


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _targeted_inputs(cap=20):
    """LinkedIn queries aimed at the companies whose direct ATS is broken AND that the free
    re-capture couldn't fix — the 'unresolvable remainder' (anti-bot Workday, custom-board
    movers). Discovery is the free safety net for exactly these, so we search each by name."""
    stale = _load_json("cloud_state/stale.json")
    resolved = _load_json("out/resolved_configs.json")
    unresolved = [n for n in stale if n not in resolved]
    return [{"location": "Israel", "keyword": f"{name} data analyst", "country": "IL"}
            for name in unresolved[:cap]]


def main():
    _load_secrets()
    os.makedirs("out", exist_ok=True)      # gitignored — absent on cloud runners
    if not os.environ.get("BRIGHTDATA_API_KEY"):
        print("no BRIGHTDATA_API_KEY; skipping discovery")
        return
    jobs, seen = [], set()
    per_source = {}
    # Indeed first: it is a single unlocked request per query, so it costs seconds and
    # cannot be starved by the dataset polling below timing out.
    for q in INDEED_QUERIES:
        try:
            cards = indeed_search(q)
        except Exception as e:  # noqa: BLE001
            print(f"[indeed:{q}] ERR {type(e).__name__}: {str(e)[:120]}")
            cards = []
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
    per_source["indeed"] = len(jobs)
    print(f"[indeed] {len(jobs)} unique jobs across {len(INDEED_QUERIES)} queries")

    runs = [(n, *QUERIES[n]) for n in QUERIES]
    targeted = _targeted_inputs()
    if targeted:
        li_ds = QUERIES["linkedin"][0]
        runs.append(("linkedin-targeted", li_ds, "keyword", targeted, 8))
        print(f"targeting {len(targeted)} unresolved-broken companies via discovery")
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
    # companies we don't scan directly yet -> hand to the auto-expand resolver
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    new_cos = {}
    for j in jobs:
        c = j["company"].strip()
        if c.lower() not in have and c.lower() not in new_cos:
            new_cos[c.lower()] = {"name": c, "careers_url": j["url"], "ats": "unknown", "slug": ""}
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
    print(f"=== {len(jobs)} discovered jobs cached · {len(new_cos)} new companies for migration ===")


if __name__ == "__main__":
    main()
