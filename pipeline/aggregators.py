"""Aggregator breadth source.

SerpApi's `google_jobs` engine — real Google for Jobs with `gl=il`, which aggregates
LinkedIn / company career pages / job boards in Israel, so it reaches postings the
direct-ATS fetchers can't (including the anti-bot giants Google indexes). Free tier is
100 searches/month, no credit card — enough for a once-daily run with a few queries.

Set SERPAPI_KEY (env or the gitignored secrets.env). Without it, this source is skipped.

(JSearch on RapidAPI was tried first but is US-ONLY — it returns 0 for Israel — so it is
not used.)
"""
from __future__ import annotations

import os
from urllib.parse import quote

from . import http

# One SerpApi search per query, page 1 only, to stay within the free 100/month tier.
# Location goes IN the query (+ gl=il) — the separate `location` param returned 0 for Israel.
SERPAPI_QUERIES = [
    "data analyst in Israel",
    "business intelligence analyst in Israel",
    "business analyst OR product analyst in Israel",
]


def _agg_snippet(s, n=1400):
    return " ".join(str(s or "").split())[:n]


def fetch_serpapi_google_jobs(queries=None, api_key=None, location=""):
    """Return normalized jobs from Google-for-Jobs via SerpApi, or [] if no key/failure.

    `gl=il` sets the search to Israel and the location is baked into each query; the separate
    `location` param is left off by default because it returned 0 results for Israel.
    """
    api_key = api_key or os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        return []
    queries = queries or SERPAPI_QUERIES
    out, seen = [], set()
    for q in queries:
        url = (f"https://serpapi.com/search?engine=google_jobs&q={quote(q)}"
               f"&gl=il&hl=en&api_key={api_key}")
        if location:
            url += f"&location={quote(location)}"
        try:
            data = http.get_json(url, timeout=40)
        except http.HttpError:
            continue
        for p in data.get("jobs_results", []) or []:
            jid = p.get("job_id") or (p.get("apply_options") or [{}])[0].get("link")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            ext = p.get("detected_extensions") or {}
            apply_link = ""
            for opt in (p.get("apply_options") or []):
                if opt.get("link"):
                    apply_link = opt["link"]
                    break
            out.append({
                "company": (p.get("company_name") or "").strip(),
                "title": (p.get("title") or "").strip(),
                "location": (p.get("location") or "").strip(),
                "country_code": "",  # rely on the Israel text filter (location says Israel/city)
                "url": apply_link or p.get("share_link") or "",
                "posted_date": (ext.get("posted_at") or ""),   # relative, e.g. "2 days ago"
                "ats_platform": "google_jobs",
                "job_id": str(jid),
                "description": _agg_snippet(p.get("description")),
            })
    return out


# --------------------------------------------------------------------------- #
# Aggregator-HOST blocklist (single source of truth)
# --------------------------------------------------------------------------- #
# A scrape row pointing at an aggregator ingests that site's global / "similar jobs"
# listing — other companies' postings attributed to this company. Every layer
# (resolution, activation, runtime) must consult THIS list, not a local copy:
# builtin.com was missing from three separate hand-maintained tuples and 13 rows were
# activated on the same global listing (2026-08-22). Add new hosts here only.
import re as _re

HOSTS = (
    "linkedin.", "indeed.", "glassdoor.", "secrethunter.", "t.me/",
    "builtin.com", "ziprecruiter.", "monster.", "dice.com", "simplyhired.",
    "careerbuilder.", "wellfound.com", "angel.co", "startup.jobs", "themuse.com",
    "jobvite.com/search", "talent.com", "jooble.", "neuvoo.", "adzuna.",
    "drushim.co.il", "alljobs.co.il", "jobmaster.co.il", "ethosia.", "gotfriends.",
)

# host-anchored: "t.me/" must not match supplant.me / supersmart.me
_AGG_RX = _re.compile(
    r"(?://|^)([^/]*\.)?(" + "|".join(h.rstrip("/").replace(".", r"\.") for h in HOSTS) + r")",
    _re.I)


def is_aggregator(url: str) -> bool:
    """True if the URL points at a job aggregator rather than a company's own board."""
    return bool(_AGG_RX.search(url or ""))
