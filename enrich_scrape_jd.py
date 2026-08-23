#!/usr/bin/env python3
"""Backfill job-description text for scrape-source jobs in scraped_cache.json.

Scrape-source cards carry title/url/location but no JD, which starves the board's
requirements/skills/experience rendering (every API source stores full JDs). This fetches
each described-less job's detail page — plain HTTP first, Bright Data Web Unlocker as a
budget-capped fallback for bot-walled pages — extracts readable text, and persists it into
the cache's `description` field. store.py already refreshes `matched.description` on merge,
so existing board rows light up on the next pipeline run with no DB surgery.

Notes:
- Runs daily in the digest workflow, before pipeline.run. Idempotent: only touches jobs with
  an empty description; failed URLs are stamped (`_jd_attempted`) and retried after 7 days.
- The daily 00:00 scrape-refresh rebuilds the cache but CARRIES FORWARD descriptions by
  url/job_id (refresh_scrape_cache.py), so enrichment is not wiped and the Unlocker budget
  is not re-burned. Only genuinely new cards arrive empty and get enriched here.

Env: JD_ENRICH_TIME_BUDGET_MIN (default 25) is the real limit — the count caps
     JD_ENRICH_CAP (2000) / JD_ENRICH_BD_CAP (400) are only runaway backstops.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import re
import urllib.request

from bd_rescue import _load_secrets, unlock
from pipeline.fetchers import clean_scraped as _clean_scraped
from pipeline.seniority import _ROLE_START, _relevance

# A real JD names its sections; a JS-shell / cookie-wall / "no jobs found" page doesn't.
# Require two distinct markers so boilerplate like "innovative benefits" can't pass alone.
_JD_MARKERS = re.compile(
    r"(requirements?|responsibilit|qualifications?|experience|what you.?ll|"
    r"we.?re looking|about the (role|job|position)|skills|full[- ]time|"
    r"דרישות|אחריות|ניסיון|תיאור (ה)?משרה|כישורים)", re.I)

CACHE = "scraped_cache.json"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_DESC_MAX = 6000          # matches fetchers._DESC_MAX / store cap
_MIN_TEXT = 300           # below this the page was a shell/cookie-wall — don't store
_RETRY_DAYS = 7


def _plain_fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept-Language": "en,he;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def html_to_text(html):
    h = re.sub(r"<(script|style|noscript|svg|header|nav|footer)[^>]*>.*?</\1>", " ",
               html, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in h.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_jd(html):
    """Readable JD text; starts at the role section when the boilerplate marker is found."""
    text = html_to_text(html)
    if len(text) < _MIN_TEXT or len(set(_JD_MARKERS.findall(text.lower()))) < 2:
        return ""
    rs = _ROLE_START.search(text)
    if rs and len(text) - rs.start() >= _MIN_TEXT:
        text = text[rs.start():]
    return text[:_DESC_MAX]


def main():
    _load_secrets()
    # Count caps were the binding constraint and left old roles permanently un-enriched: the
    # backlog is walked in cache order, so the same head got re-attempted while the tail was
    # never reached. Budget by TIME instead — do as much as fits, bounded by the digest's
    # own timeout — and keep the count caps only as a runaway backstop.
    cap = int(os.environ.get("JD_ENRICH_CAP", "2000"))
    bd_cap = int(os.environ.get("JD_ENRICH_BD_CAP", "400"))
    budget_min = int(os.environ.get("JD_ENRICH_TIME_BUDGET_MIN", "25"))
    t0 = time.time()
    bd_ok = bool(os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE"))
    today = dt.date.today().isoformat()
    retry_before = (dt.date.today() - dt.timedelta(days=_RETRY_DAYS)).isoformat()

    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("no scraped_cache.json; nothing to enrich")
        return

    n_done = n_bd = n_fail = n_skip = 0
    def _spent():
        return n_done + n_fail >= cap or (budget_min and (time.time()-t0)/60 > budget_min)
    for comp, jobs in cache.items():
        if _spent():
            break
        for j in jobs or []:
            if n_done + n_fail >= cap or (budget_min and (time.time()-t0)/60 > budget_min):
                break
            if not isinstance(j, dict) or (j.get("description") or "").strip():
                continue
            url = j.get("url") or ""
            if not url.startswith("http"):
                continue
            # spend the fetch budget only on titles the classifier could ever accept
            if _relevance((j.get("title") or "").lower()) in ("excluded", "none"):
                continue
            # ...and never on page chrome. "Analytics Cookies" passes the relevance gate.
            if not _clean_scraped([j]):
                continue
            if (j.get("_jd_attempted") or "") > retry_before:
                n_skip += 1
                continue
            html = _plain_fetch(url)
            jd = extract_jd(html) if html else ""
            if not jd and bd_ok and n_bd < bd_cap:
                n_bd += 1
                jd = extract_jd(unlock(url))
            j["_jd_attempted"] = today
            if jd:
                j["description"] = jd
                n_done += 1
            else:
                n_fail += 1

    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"=== JD enrichment: {n_done} filled ({n_bd} via Bright Data), "
          f"{n_fail} unfetchable (retry in {_RETRY_DAYS}d), {n_skip} in cooldown ===")


if __name__ == "__main__":
    main()
