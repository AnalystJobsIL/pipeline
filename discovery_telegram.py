#!/usr/bin/env python3
"""Telegram-channel discovery source (keyless, like the GitHub-issue email trick).

Public channels expose an HTML preview at https://t.me/s/<channel> — no bot, no account,
no API key. The channels below are structured job feeds (secrethunter.io format: title /
company / city / date / skills / seniority / link), so parsing is deterministic; posts the
parser can't structure are skipped and counted, never guessed.

Output feeds the same funnels as Bright Data discovery:
  - jobs merge into discovered_cache.json  (read by fetch_discovery -> classifier -> digest)
  - companies not in companies.csv merge into research_companies.json (auto-expand queue,
    where the deterministic + LLM resolver tiers crack their own ATS board)
State (last message id per channel) lives in cloud_state/telegram_seen.json, committed back
by the daily-digest persist step.
"""
from __future__ import annotations

import sys

import html as _html
import json
import os
import re
import urllib.request

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


CHANNELS = [
    "secretdatajobs",        # data/analytics roles — the core feed
    "secretmarketingjobs",   # marketing/growth analyst roles surface here
    "secretproductjobs",     # mostly PM (classifier drops free) — kept for company discovery
    # Added 2026-08-23. All three carry analyst-shaped roles AND — the larger reason —
    # Israeli employers the registry has never seen; the auto-expand queue was measured at
    # only 77 entries against a 200/run limit, so widening intake costs nothing downstream.
    # Each was probed the same day for the secrethunter layout the parser needs
    # (parsed/20 messages on the front page):
    "secretcyberjobs",       # 16/20 — cyber is the deepest Israeli employer pool
    "secretfinancejobs",     # 18/20 — business/fintech analysts (FP&A is dropped by the classifier)
    "secretsalesjobs",       # 18/20 — revenue/sales-ops analytics
]
# Evaluated and rejected 2026-08-21: israjobs (RU vacancies+resumes, unstructured),
# hightechforolims (free-text olim/entry-level), jobs_SQL (India-based).
# Evaluated and rejected 2026-08-23, same probe: secrethrjobs (17/20) and secretqajobs
# (15/20) parse fine but are the two feeds with essentially no analyst yield — they were
# left out on relevance, not on capability. secretbizdevjobs / secretanalystjobs /
# secretdesignjobs / secretstudentjobs / secretjobs resolve to a Telegram contact page with
# no public t.me/s preview (0 messages), so the parser can never see them.
STATE_PATH = "cloud_state/telegram_seen.json"
MAX_PAGES = 5           # first-run backfill depth (~20 msgs/page)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

_MSG = re.compile(
    r'data-post="(?P<chan>[^"/]+)/(?P<id>\d+)".*?'
    r'tgme_widget_message_text[^>]*>(?P<body>.*?)</div>.*?'
    r'<time datetime="(?P<dt>[^"]+)"', re.S)
_URL = re.compile(r"https?://[^\s\"'<>]+")
_INVIS = "ㅤ​﻿"


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _clean_text(body_html):
    t = re.sub(r"<br\s*/?>", "\n", body_html)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    lines = []
    for ln in t.split("\n"):
        ln = ln.strip().strip(_INVIS).strip()
        if ln:
            lines.append(ln)
    return lines


_TITLEISH = re.compile(r"[A-Za-z\u0590-\u05FF]")
_DATE_LINE = re.compile(r"\d{1,2}/\d{1,2}/\d{2}")      # the format's "20/8/26" line


def parse_post(lines, msg_date):
    """secrethunter format -> normalized job dict, or None if it doesn't fit."""
    # cut the footer ("--" + promo links)
    if "--" in lines:
        lines = lines[:lines.index("--")]
    # Drop leading decoration. The format is positional — lines[0..2] are title / company /
    # city — so a single "🔥🔥🔥" header line shifts everything by one and the JOB TITLE is
    # emitted as the company name, which passes both is_recruiter and looks_like_junk and is
    # queued as a new Israeli employer. Latent today (no channel currently decorates), and it
    # fires the first time one does.
    while lines and not _TITLEISH.search(lines[0]):
        lines = lines[1:]
    if len(lines) < 4:
        return None
    title, company, city = lines[0], lines[1], lines[2]
    # NO company line at all — title / city / date / skills / seniority / url. Positional
    # parsing then emits the CITY as the employer and the DATE as the city: shipped
    # 2026-08-20 as {"company": "Tel Aviv", "location": "20/8/26, Israel"} and became a
    # registry row (BACKLOG 167). 2 of 320 live posts on 2026-08-25; skipped and counted,
    # never guessed — the secrethunter link is a JS shell, so there is no employer to
    # recover from it.
    if _DATE_LINE.match(city):
        return None
    if not _TITLEISH.search(company):
        return None                                        # company must contain a letter
    company = company.replace("(.)", ".").strip()          # "Placer(.)ai" -> "Placer.ai"
    rest = lines[4:] if _DATE_LINE.match(lines[3]) else lines[3:]
    url = ""
    skills = seniority = ""
    for ln in rest:
        m = _URL.search(ln)
        if m and not url:
            url = m.group(0)
        elif "," in ln and not skills:
            skills = ln
        elif len(ln.split()) <= 3 and not seniority and not _URL.search(ln):
            seniority = ln
    if not url or len(title) > 120 or len(company) > 60:
        return None                                        # promo / unstructured post
    if title.rstrip().endswith(":") or re.search(r"jobs posted|weekly digest", title, re.I):
        return None                                        # channel's own summary posts
    return {"company": company[:80], "title": title[:140],
            # blank, not "IL": israel.is_israel_job short-circuits on country_code before
            # it reads any text, so asserting it here makes the geo gate a no-op for every
            # Telegram job — 104 of the 205 cached jobs on 2026-08-23. The location this
            # builds always ends ", Israel", so the text scan reaches the same answer
            # honestly.
            "location": f"{city}, Israel"[:80], "country_code": "",
            "url": url.split("?")[0], "posted_date": msg_date[:10],
            "ats_platform": "discovery-telegram", "job_id": url.split("?")[0],
            "description": f"Skills: {skills}. Seniority: {seniority}."}


def scan_channel(chan, last_id):
    """Yield (msg_id, job) for messages newer than last_id, walking back MAX_PAGES."""
    out, skipped, before = [], 0, None
    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{chan}" + (f"?before={before}" if before else "")
        try:
            page = _fetch(url)
        except Exception:  # noqa: BLE001
            break
        msgs = list(_MSG.finditer(page))
        if not msgs:
            break
        ids = [int(m.group("id")) for m in msgs]
        for m in msgs:
            mid = int(m.group("id"))
            if mid <= last_id:
                continue
            job = parse_post(_clean_text(m.group("body")), m.group("dt"))
            if job:
                out.append((mid, job))
            else:
                skipped += 1
        before = min(ids)
        if min(ids) <= last_id:
            break
    return out, skipped


def _load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:  # noqa: BLE001
        return default


class CacheUnreadable(Exception):
    """discovered_cache.json exists but will not parse — never treat that as 'empty'."""


def _load_cache(path="discovered_cache.json"):
    """Load the shared job cache, distinguishing ABSENT from CORRUPT.

    `_load_json(path, [])` collapsed both into an empty list, and this function merges into
    that list and then writes it back — so one half-written file (the preceding
    discovery_daily step writes it with a plain open(), both steps are continue-on-error,
    and operators do cancel digest runs) silently deletes every job in the cache. The
    watermark in cloud_state/telegram_seen.json is advanced in the SAME run, which is what
    makes the loss unrecoverable: exactly the mechanism that cost 79 verified roles on
    2026-08-21.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise CacheUnreadable(f"{path} exists but is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise CacheUnreadable(f"{path} is {type(data).__name__}, expected a list")
    return data


def _health(n_parsed):
    """Report this run's Telegram yield to the shared source-liveness store.

    Counts POSTS PARSED, not posts merged: `added` is post-dedup against
    discovered_cache.json, so a channel that is producing normally but repeating a role we
    already hold would have recorded a 0 and looked dead. One aggregate `telegram` key, not
    one per channel — `sources.stale()` has a single 2-day threshold for every key, which a
    niche channel trips on a normal quiet weekend. Per-channel liveness needs a per-key
    threshold in pipeline/sources.py (shared plumbing); it is filed in docs/BACKLOG.md.
    Per-channel counts are printed above for the operator reading the step log."""
    try:
        from pipeline import sources
        sources.record({"telegram": int(n_parsed)})
    except Exception as e:  # noqa: BLE001
        print(f"[source-health] skipped: {e}")


def main():
    state = _load_json(STATE_PATH, {})
    new_jobs = []
    for chan in CHANNELS:
        got, skipped = scan_channel(chan, int(state.get(chan, 0)))
        if got:
            state[chan] = max(mid for mid, _ in got)
        new_jobs += [j for _, j in got]
        print(f"[{chan}] {len(got)} job posts parsed, {skipped} non-job/unparsed skipped")
    # Record liveness BEFORE the early return. This used to sit at the end of main(), after
    # a `return` taken whenever a scan produced nothing — so the one mechanism built to
    # notice a dead source (pipeline/sources.py, written because the Indeed dataset returned
    # zero for five days unseen) could never see Telegram at all. Proof it never ran: on
    # 2026-08-23 `cloud_state/source_health.json` had keys for indeed / linkedin /
    # linkedin-targeted and NO `telegram` key, while `discovered_cache.json` held 104
    # telegram-sourced jobs. A zero here is now recorded as a zero, which is what makes
    # `sources.stale()` able to say the feed died.
    _health(len(new_jobs))
    if not new_jobs:
        print("no new telegram posts")
        return
    # merge into discovered_cache.json (discovery_daily may have just rewritten it)
    try:
        cache = _load_cache()
    except CacheUnreadable as e:
        # Abort BEFORE the watermark advances. Losing today's Telegram posts is recoverable
        # on the next run; advancing the watermark past them is not.
        print(f"::error::{e} — aborting the telegram merge WITHOUT advancing the watermark, "
              f"so nothing is lost. Fix or delete the file and re-run.", flush=True)
        return
    seen = {(j.get("company", "").lower(), j.get("title", "").lower()) for j in cache}
    added = [j for j in new_jobs
             if (j["company"].lower(), j["title"].lower()) not in seen]
    cache += added
    with open("discovered_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    # bridge new companies into the auto-expand queue (same as discovery_daily)
    from discovery_daily import is_place_name
    from pipeline.companies import load_companies
    from pipeline.firmographics import looks_like_junk
    from pipeline.recruiters import is_recruiter
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    research = _load_json("research_companies.json", [])
    known = {(e.get("name") or "").strip().lower() for e in research}
    queued = 0
    for j in added:
        c = j["company"].strip()
        # a Telegram post's "company" is whatever the poster typed, so it is the most
        # likely of all the sources to be a job title, a team name — or a city
        if (c.lower() not in have and c.lower() not in known
                and not is_recruiter(c) and not looks_like_junk(c) and not is_place_name(c)):
            research.append({"name": c, "careers_url": j["url"], "ats": "unknown", "slug": ""})
            known.add(c.lower())
            queued += 1
    if queued:
        with open("research_companies.json", "w", encoding="utf-8") as f:
            json.dump(research, f, ensure_ascii=False, indent=1)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    print(f"=== telegram: {len(added)} jobs merged · {queued} new companies queued ===")


if __name__ == "__main__":
    main()
