"""Aggregator breadth source, plus the aggregator-HOST blocklist.

**`fetch_serpapi_google_jobs` HAS NEVER RUN IN THE CLOUD.** `pipeline/run.py` gates it on
`AGGREGATOR_ENABLED == "1"`, and that variable is set in no workflow, no test and no script
(`grep -rn AGGREGATOR_ENABLED .github/ *.py pipeline/` → one gate in run.py and one comment
in daily-digest.yml saying it is deliberately left off). Only the blocklist below is live;
every other module in the repo imports this file for `is_aggregator`, not for the fetcher.

Two conflicting reasons are on record for it being off, and they cannot both be tested
today:
  * `daily-digest.yml` says "SerpApi & JSearch both verified to NOT cover Israel
    (google_jobs rejects gl=il, location=Israel returns 0)".
  * `CLAUDE.md`/`AGENT_BRIEF` say the SerpApi quota is exhausted until 2026-09-01.
**UNVERIFIED 2026-08-23:** the key in `secrets.env` answers HTTP 429 to
`engine=google_jobs&gl=il`, so the "does not cover Israel" claim cannot be re-tested before
the quota resets. Do not delete the function on the strength of either sentence — settle it
with one search after 2026-09-01. The removal proposal is in `docs/BACKLOG.md`.

**Google for Jobs is NOT reachable through the Bright Data unlocker** (tested 2026-08-23,
3 credits): `google.com/search?q=…&ibp=htl;jobs` returns HTTP 200 with a ZERO-BYTE body —
the jobs widget is client-rendered and raw mode gets none of it. The same request without
`ibp=htl;jobs` returns 440,906 bytes of ordinary SERP, which is why
`deep_validate.google_via_unlocker` (organic links, per company) works and a jobs-widget
version of it cannot. Anyone tempted to "just swap SerpApi for the unlocker": that is the
experiment, and it fails.

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
    # secrethunter's per-city board. Missing here, listing_hunt "verified 145 IL via
    # jobs.secrettelaviv.com" and activated a row named "Tel Aviv" (2026-08-24); 7 of the
    # 81 roles on the 2026-08-25 board and 2 in that day's mail were other companies'
    # postings under it. A literal, NOT a `secret*` pattern: Secret Double Octopus
    # (secretdoubleoctopus.com) is a real active employer.
    "secrettelaviv.",
    # builtin runs a domain PER CITY — builtinnyc.com, builtinchicago.org, builtinla.com,
    # builtinaustin.com, builtinboston.com, builtinseattle.com, builtinsf.com, builtincolorado.com
    "builtin.com", "builtinnyc.", "builtinchicago.", "builtinla.", "builtinaustin.",
    "builtinboston.", "builtinseattle.", "builtinsf.", "builtincolorado.",
    "ziprecruiter.", "monster.", "dice.com", "simplyhired.",
    "careerbuilder.", "wellfound.com", "angel.co", "startup.jobs", "themuse.com",
    "jobvite.com/search", "talent.com", "jooble.", "neuvoo.", "adzuna.",
    "getclera.com", "welcometothejungle.com", "techaviv.com", "secretjobs.ai", "jobs.techaviv", "drushim.co.il", "alljobs.co.il", "jobmaster.co.il", "ethosia.", "gotfriends.",
    # Niche/vertical boards and VC portfolio pages. Each of these verified with real Israel
    # jobs and so ACTIVATED a company against another employer's listings: WINT got 20 roles
    # from climatetechlist, Zipher 5 from a VC page, factify 1 from a DuckDuckGo results page.
    "climatetechlist.", "foodimpactcareers.", "infosecjobboard.", "web3.career",
    "embedded.jobs", "myjobmag.", "devjobs.co.il", "jobify360.", "tlv.partners",
    "insightpartners.com", "seedcamp.com", "getro.", "consider.vc", "jobs.ashbyhq.com/vc",
    "duckduckgo.", "google.com/search", "bing.com/search", "levels.fyi",
    "simplify.jobs", "peopleopsjobs.", "igamingcareers.", "43north.org",
    # seen being tried by the 2026-08-23 hunt: aggregators, a PE portfolio board, and a
    # company-data site that is not a careers page at all
    "bebee.com", "djinni.co", "craft.co", "franciscopartners.com", "himalayas.app",
    "remoteok.", "weworkremotely.", "jobgether.", "startupnationcentral.org",
)

# host-anchored: "t.me/" must not match supplant.me / supersmart.me
_AGG_RX = _re.compile(
    r"(?://|^)([^/]*\.)?(" + "|".join(h.rstrip("/").replace(".", r"\.") for h in HOSTS) + r")",
    _re.I)


def is_aggregator(url: str) -> bool:
    """True if the URL points at a job aggregator rather than a company's own board."""
    return bool(_AGG_RX.search(url or ""))
