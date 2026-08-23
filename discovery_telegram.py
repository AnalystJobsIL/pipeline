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
]
# Evaluated and rejected 2026-08-21: israjobs (RU vacancies+resumes, unstructured),
# hightechforolims (free-text olim/entry-level), jobs_SQL (India-based).
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


def parse_post(lines, msg_date):
    """secrethunter format -> normalized job dict, or None if it doesn't fit."""
    # cut the footer ("--" + promo links)
    if "--" in lines:
        lines = lines[:lines.index("--")]
    if len(lines) < 4:
        return None
    title, company, city = lines[0], lines[1], lines[2]
    company = company.replace("(.)", ".").strip()          # "Placer(.)ai" -> "Placer.ai"
    rest = lines[4:] if re.match(r"\d{1,2}/\d{1,2}/\d{2}", lines[3]) else lines[3:]
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
            "location": f"{city}, Israel"[:80], "country_code": "IL",
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
    except Exception:  # noqa: BLE001
        return default


def main():
    state = _load_json(STATE_PATH, {})
    new_jobs = []
    for chan in CHANNELS:
        got, skipped = scan_channel(chan, int(state.get(chan, 0)))
        if got:
            state[chan] = max(mid for mid, _ in got)
        new_jobs += [j for _, j in got]
        print(f"[{chan}] {len(got)} job posts parsed, {skipped} non-job/unparsed skipped")
    if not new_jobs:
        print("no new telegram posts")
        return
    # merge into discovered_cache.json (discovery_daily may have just rewritten it)
    cache = _load_json("discovered_cache.json", [])
    seen = {(j.get("company", "").lower(), j.get("title", "").lower()) for j in cache}
    added = [j for j in new_jobs
             if (j["company"].lower(), j["title"].lower()) not in seen]
    cache += added
    with open("discovered_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    # bridge new companies into the auto-expand queue (same as discovery_daily)
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
        # likely of all the sources to be a job title or a team name
        if (c.lower() not in have and c.lower() not in known
                and not is_recruiter(c) and not looks_like_junk(c)):
            research.append({"name": c, "careers_url": j["url"], "ats": "unknown", "slug": ""})
            known.add(c.lower())
            queued += 1
    if queued:
        with open("research_companies.json", "w", encoding="utf-8") as f:
            json.dump(research, f, ensure_ascii=False, indent=1)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    try:
        from pipeline import sources
        sources.record({"telegram": len(added)})
    except Exception as e:  # noqa: BLE001
        print(f"[source-health] skipped: {e}")
    print(f"=== telegram: {len(added)} jobs merged · {queued} new companies queued ===")


if __name__ == "__main__":
    main()
