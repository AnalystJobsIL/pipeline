"""Per-ATS-platform fetchers that normalize postings into one common shape.

Normalized job dict:
    {
      "company":       str,   # display name from companies.csv
      "title":         str,
      "location":      str,   # human-readable, best effort
      "country_code":  str,   # ISO alpha-2/alpha-3 upper when the feed gives one, else ""
      "url":           str,   # public posting URL
      "posted_date":   str,   # ISO date "YYYY-MM-DD" when parseable, else raw/""
      "ats_platform":  str,
      "job_id":        str,   # stable per-platform id (for dedupe)
    }

Each fetcher takes a company row (dict from companies.csv) and returns a list of
normalized job dicts. Fetchers do NOT filter by location or seniority — that happens
downstream. They only fetch + normalize.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re as _re
from urllib.parse import urlsplit

from . import http

_DESC_MAX = 6000  # chars of plain-text description kept — enough to reach the Requirements
                  # section (often past a long company-jargon intro) for the board's extractor


def _strip_html(s):
    if not s:
        return ""
    # Decode entities FIRST (greenhouse `content` is entity-encoded HTML, sometimes
    # double-encoded), so real tags become literal <...>, THEN strip the tags.
    txt = _html.unescape(_html.unescape(str(s)))
    txt = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", txt)  # drop script/style bodies
    # Preserve list/line structure as a bullet marker BEFORE flattening, so the digest can
    # split a Requirements section back into clean bullets (HTML <li> boundaries are otherwise
    # lost when tags collapse to spaces, mangling "Excel – Must / SQL – Advantage" style lists).
    txt = _re.sub(r"(?is)<li[^>]*>", " • ", txt)
    txt = _re.sub(r"(?is)<br\s*/?>|</(p|div|h[1-6]|tr|ul|ol)\s*>", " • ", txt)
    txt = _re.sub(r"<[^>]+>", " ", txt)                              # strip remaining tags
    txt = txt.replace("\xa0", " ")
    txt = _re.sub(r"\s*•(?:\s*•)+\s*", " • ", txt)    # collapse repeated markers
    return " ".join(txt.split())


# Descriptions occasionally contain pasted web-app markup / CSS soup (e.g. one Taboola
# posting held a ChatGPT-UI fragment). Blank those rather than show garbage in the digest.
_JUNK = _re.compile(
    r"(var\(--|data-turn-id|pointer-events|_threadScroll|token-text-primary|"
    r"\[calc\(|scroll-m[btlr]-\[|class=)", _re.I)


def _snippet(s):
    txt = _strip_html(s)
    if _JUNK.search(txt):
        return ""  # polluted markup, not prose
    return txt[:_DESC_MAX]


# --------------------------------------------------------------------------- #
# date helpers
# --------------------------------------------------------------------------- #
def _iso_date(value):
    """Best-effort convert an ISO-ish datetime string to a YYYY-MM-DD date."""
    if not value:
        return ""
    s = str(value).strip()
    # Common forms: 2026-08-13T08:53:48Z, 2026-08-13T08:53:48.572Z, 2026-08-04 12:39:26 UTC
    s = s.replace("Z", "").replace(" UTC", "").replace("T", " ")
    s = s.split(".")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # Give up gracefully — return the first 10 chars if they look like a date.
    return s[:10] if len(s) >= 10 and s[4:5] == "-" else ""


def _iso_from_epoch_ms(value):
    """Convert epoch milliseconds (Lever's createdAt) to a YYYY-MM-DD date (UTC)."""
    try:
        ms = int(value)
        return _dt.datetime.utcfromtimestamp(ms / 1000.0).date().isoformat()
    except (TypeError, ValueError):
        return ""


# Full country-name -> ISO alpha-2, for feeds that give a name not a code (Ashby).
_COUNTRY_NAME_TO_CODE = {
    "israel": "IL",
    "united states": "US", "usa": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB",
    "germany": "DE", "france": "FR", "spain": "ES", "portugal": "PT",
    "india": "IN", "canada": "CA", "australia": "AU", "ireland": "IE",
    "netherlands": "NL", "poland": "PL", "romania": "RO", "singapore": "SG",
    "japan": "JP", "china": "CN", "brazil": "BR", "mexico": "MX",
    "sweden": "SE", "switzerland": "CH", "italy": "IT", "austria": "AT",
    "czech republic": "CZ", "czechia": "CZ", "bulgaria": "BG", "greece": "GR",
    "hong kong": "HK", "south korea": "KR", "korea": "KR", "taiwan": "TW",
    "united arab emirates": "AE", "uae": "AE",
}


def _country_name_to_code(name):
    if not name:
        return ""
    return _COUNTRY_NAME_TO_CODE.get(str(name).strip().lower(), "")


def _clean(s):
    return " ".join(str(s).split()) if s else ""


# --------------------------------------------------------------------------- #
# per-platform normalizers
# --------------------------------------------------------------------------- #
def _comeet_description(p):
    """Comeet's `details` is a list of {name, value(html)} sections (Description,
    Requirements, ...). Join them into one plain-text snippet, prefixed with the
    experience_level when present (helps the 3+ year check)."""
    parts = []
    lvl = p.get("experience_level")
    if lvl:
        parts.append(f"Experience level: {lvl}.")
    for sec in (p.get("details") or []):
        name, val = sec.get("name"), _strip_html(sec.get("value"))
        if val:
            parts.append(f"{name}: {val}" if name else val)
    return _snippet(" ".join(parts))


def fetch_comeet(row):
    # details=true attaches the JD sections; used for the 3+ yr check and digest UX.
    api = row["api_url"]
    api = api + ("&" if "?" in api else "?") + "details=true"
    data = http.get_json(api)
    jobs = []
    for p in data if isinstance(data, list) else []:
        loc = p.get("location") or {}
        loc_parts = [loc.get("city") or loc.get("name"), loc.get("state"), loc.get("country")]
        loc_str = ", ".join(x for x in loc_parts if x)
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("name")),
            "location": _clean(loc_str),
            "country_code": (loc.get("country") or "").strip().upper(),
            "url": p.get("url_comeet_hosted_page") or p.get("url_active_page") or "",
            "posted_date": _iso_date(p.get("time_updated")),
            "ats_platform": "comeet",
            "job_id": str(p.get("uid") or ""),
            "description": _comeet_description(p),
        })
    return jobs


def fetch_greenhouse(row):
    # content=true so the list carries the job body -> used by the LLM seniority fallback.
    api = row["api_url"]
    api = api + ("&" if "?" in api else "?") + "content=true"
    data = http.get_json(api)
    jobs = []
    for p in data.get("jobs", []):
        loc = (p.get("location") or {}).get("name", "")
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("title")),
            "location": _clean(loc),
            "country_code": "",  # greenhouse list gives no code; rely on text match
            "url": p.get("absolute_url") or "",
            "posted_date": _iso_date(p.get("updated_at") or p.get("first_published")),
            "ats_platform": "greenhouse",
            "job_id": str(p.get("id") or ""),
            "description": _snippet(p.get("content")),
        })
    return jobs


def fetch_lever(row):
    data = http.get_json(row["api_url"])
    jobs = []
    for p in data if isinstance(data, list) else []:
        cats = p.get("categories") or {}
        all_locs = cats.get("allLocations") or ([cats.get("location")] if cats.get("location") else [])
        loc_str = ", ".join(x for x in all_locs if x) or _clean(cats.get("location"))
        # Lever's top-level `country` is an ISO alpha-2 when present.
        code = p.get("country") or ""
        code = code.strip().upper() if isinstance(code, str) and len(code.strip()) in (2, 3) else ""
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("text")),
            "location": _clean(loc_str),
            "country_code": code,
            "url": p.get("hostedUrl") or p.get("applyUrl") or "",
            "posted_date": _iso_from_epoch_ms(p.get("createdAt")),
            "ats_platform": "lever",
            "job_id": str(p.get("id") or ""),
            "description": _snippet(p.get("descriptionPlain") or p.get("description")),
        })
    return jobs


def fetch_smartrecruiters(row):
    """SmartRecruiters paginates (limit<=100). Loop offset until all collected."""
    jobs = []
    offset, limit, total = 0, 100, None
    token = row["token"]
    while True:
        sep = "&" if "?" in row["api_url"] else "?"
        url = f"{row['api_url']}{sep}limit={limit}&offset={offset}"
        data = http.get_json(url)
        total = data.get("totalFound", 0) if total is None else total
        content = data.get("content", [])
        for p in content:
            loc = p.get("location") or {}
            loc_str = loc.get("fullLocation") or ", ".join(
                x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
            job_id = str(p.get("id") or "")
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("name")),
                "location": _clean(loc_str),
                "country_code": (loc.get("country") or "").strip().upper(),
                "url": f"https://jobs.smartrecruiters.com/{token}/{job_id}",
                "posted_date": _iso_date(p.get("releasedDate")),
                "ats_platform": "smartrecruiters",
                "job_id": job_id,
                "description": "",  # not in SR list response
            })
        offset += limit
        if offset >= (total or 0) or not content:
            break
    return jobs


def fetch_recruitee(row):
    data = http.get_json(row["api_url"])
    jobs = []
    for p in data.get("offers", []):
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("title")),
            "location": _clean(p.get("location")),
            "country_code": (p.get("country_code") or "").strip().upper(),
            "url": p.get("careers_url") or p.get("careers_apply_url") or "",
            "posted_date": _iso_date(p.get("published_at")),
            "ats_platform": "recruitee",
            "job_id": str(p.get("id") or ""),
            "description": _snippet(p.get("description")),
        })
    return jobs


def fetch_ashby(row):
    data = http.get_json(row["api_url"])
    jobs = []
    for p in data.get("jobs", []):
        addr = ((p.get("address") or {}).get("postalAddress") or {})
        country_name = addr.get("addressCountry")
        secondary = [s.get("location") for s in (p.get("secondaryLocations") or []) if s.get("location")]
        loc_bits = [p.get("location")] + secondary
        if addr.get("addressRegion"):
            loc_bits.append(addr.get("addressRegion"))
        loc_str = ", ".join(_clean(x) for x in loc_bits if x)
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("title")),
            "location": _clean(loc_str),
            "country_code": _country_name_to_code(country_name),
            "url": p.get("jobUrl") or p.get("applyUrl") or "",
            "posted_date": _iso_date(p.get("publishedAt")),
            "ats_platform": "ashby",
            "job_id": str(p.get("id") or ""),
            "description": _snippet(p.get("descriptionPlain")),
        })
    return jobs


def _wd_date(raw):
    """Workday's 'Posted 4 Days Ago' -> ISO date; '' when unparseable (never the raw text)."""
    t = str(raw or "")
    tl = t.lower()
    today = _dt.date.today()
    if "today" in tl:
        return today.isoformat()
    if "yesterday" in tl:
        return (today - _dt.timedelta(days=1)).isoformat()
    m = _re.search(r"(\d+)\+?\s*day", tl)
    if m:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    m = _re.search(r"(\d+)\+?\s*month", tl)
    if m:
        return (today - _dt.timedelta(days=30 * int(m.group(1)))).isoformat()
    return t[:10] if (len(t) >= 10 and t[4:5] == "-") else ""


def fetch_workday(row):
    """Workday: POST search with searchText=Israel to narrow to Israel-relevant jobs.

    Global board — even with searchText=Israel a few text-matches from other countries
    can slip in; the downstream Israel filter (via the externalPath in `url`) drops them.
    Paginates by offset up to a safety cap.
    """
    api = row["api_url"]
    host = urlsplit(api).netloc
    # api path: /wday/cxs/{tenant}/{site}/jobs  ->  public URL base: https://{host}/{site}
    parts = urlsplit(api).path.strip("/").split("/")
    site = parts[3] if len(parts) >= 4 else ""
    pub_base = f"https://{host}/{site}"

    jobs = []
    offset, limit, cap = 0, 20, 200
    while offset < cap:
        data = http.post_json(api, {"searchText": "Israel", "limit": limit, "offset": offset})
        postings = data.get("jobPostings", [])
        total = data.get("total", 0)
        for p in postings:
            ext = p.get("externalPath") or ""
            bullet = p.get("bulletFields") or []
            job_id = str(bullet[0]) if bullet else ext.rsplit("_", 1)[-1] if "_" in ext else ext
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("title")),
                # locationsText can be "N Locations"; the externalPath slug carries the
                # real place (e.g. /job/Israel-Haifa/...) which the Israel filter reads
                # off the url, so keep both.
                "location": _clean(p.get("locationsText")),
                "country_code": "",
                "url": f"{pub_base}{ext}",
                "posted_date": _wd_date(p.get("postedOn")),
                "ats_platform": "workday",
                "job_id": job_id,
                "description": "",  # not in workday search response
            })
        offset += limit
        if offset >= total or not postings:
            break
    return jobs


def fetch_amazon(row):
    """Amazon custom_json: GET amazon.jobs search.json, paginate by offset."""
    base = row["api_url"]
    jobs = []
    offset, limit, cap = 0, 100, 500
    while offset < cap:
        sep = "&" if "?" in base else "?"
        url = f"{base}{sep}result_limit={limit}&offset={offset}"
        data = http.get_json(url)
        hits = data.get("hits", 0)
        page = data.get("jobs", [])
        for p in page:
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("title")),
                "location": _clean(p.get("normalized_location") or p.get("location")),
                "country_code": (p.get("country_code") or "").strip().upper(),
                "url": "https://www.amazon.jobs" + (p.get("job_path") or ""),
                "posted_date": _iso_date(p.get("posted_date")),
                "ats_platform": "custom_json",
                "job_id": str(p.get("id_icims") or p.get("id") or ""),
                "description": _snippet(p.get("description_short") or p.get("description")),
            })
        offset += limit
        if offset >= hits or not page:
            break
    return jobs


def fetch_custom_json(row):
    """Dispatch custom_json rows by host. Currently only Amazon."""
    host = urlsplit(row["api_url"]).netloc
    if "amazon.jobs" in host:
        return fetch_amazon(row)
    raise ValueError(f"no custom_json handler for host {host!r} (company {row['company_name']})")


def fetch_microsoft(row):
    """Microsoft careers (apply.careers.microsoft.com pcsx API), searched to location=Israel.

    Covers Microsoft's Israel R&D — Herzliya, Haifa, Tel Aviv, Nazareth and Beer-Sheva. GET with
    start/num pagination. Title is in `name`; `locations` is a list of "Israel, District, City".
    """
    base = row["api_url"].split("&query")[0].split("&location")[0]  # keep up to ?domain=...
    if "?" not in base:
        base += "?domain=microsoft.com"
    jobs = []
    start, num, cap = 0, 20, 200
    while start < cap:
        url = f"{base}&query=&location=Israel&start={start}&num={num}"
        data = http.get_json(url)
        d = data.get("data", {}) or {}
        positions = d.get("positions", []) or []
        count = d.get("count", 0)
        for p in positions:
            locs = p.get("locations") or []
            loc = locs[0] if locs else "Israel"
            ts = p.get("postedTs") or p.get("creationTs")
            pdate = ""
            if ts:
                try:
                    ts = int(ts)
                    if ts > 1e11:      # milliseconds vs seconds
                        ts //= 1000
                    pdate = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                except Exception:  # noqa: BLE001
                    pdate = ""
            jid = str(p.get("displayJobId") or p.get("id") or "")
            purl = f"https://jobs.careers.microsoft.com/global/en/job/{jid}"
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("name")),
                "location": _clean(loc),
                "country_code": "IL",
                "url": purl,
                "posted_date": pdate,
                "ats_platform": "microsoft",
                "job_id": jid,
                "description": "",
            })
        start += num
        if start >= count or not positions:
            break
    return jobs


def fetch_workable(row):
    """Workable public widget API: apply.workable.com/api/v1/widget/accounts/{slug}?details=true.
    Returns {name, jobs:[{title, city, state, country, url, shortcode, created_at, ...}]}."""
    data = http.get_json(row["api_url"])
    slug = row.get("token") or ""
    out = []
    for p in (data.get("jobs") or []):
        city = p.get("city") or ""
        country = p.get("country") or ""
        loc = ", ".join(x for x in (city, p.get("state") or "", country) if x) or country
        url = p.get("url") or p.get("application_url")
        if not url and slug and p.get("shortcode"):
            url = f"https://apply.workable.com/{slug}/j/{p['shortcode']}/"
        out.append({
            "company": row["company_name"], "title": _clean(p.get("title")),
            "location": _clean(loc), "country_code": (p.get("country_code") or "").upper(),
            "url": url or "", "posted_date": _clean((p.get("created_at") or "")[:10]),
            "ats_platform": "workable", "job_id": str(p.get("id") or p.get("shortcode") or ""),
            "description": _strip_html(p.get("description") or ""),
        })
    return out


def fetch_breezy(row):
    """Breezy public JSON: {slug}.breezy.hr/json/ -> list of positions. Non-existent slugs return
    the Breezy marketing HTML, so http.get_json raises there and the caller treats it as no-board."""
    data = http.get_json(row["api_url"])
    if not isinstance(data, list):
        return []
    base = row["api_url"].rsplit("/json", 1)[0]
    out = []
    for p in data:
        loc = p.get("location") or {}
        country = loc.get("country") or {}
        country = country.get("name") if isinstance(country, dict) else (country or "")
        city = loc.get("city") or (loc.get("name") if isinstance(loc.get("name"), str) else "")
        friendly = p.get("friendly_id") or p.get("_id") or ""
        out.append({
            "company": row["company_name"], "title": _clean(p.get("name")),
            "location": _clean(", ".join(x for x in (city, country) if x)),
            "country_code": "", "url": p.get("url") or f"{base}/p/{friendly}",
            "posted_date": _clean((p.get("published_date") or p.get("creation_date") or "")[:10]),
            "ats_platform": "breezy", "job_id": str(friendly),
            "description": _strip_html(p.get("description") or ""),
        })
    return out


def fetch_bamboohr(row):
    """BambooHR public API: {slug}.bamboohr.com/careers/list -> {result:[...]}. Non-existent slugs
    return BambooHR marketing HTML (get_json raises), so a real board is one that parses to JSON."""
    data = http.get_json(row["api_url"])
    if not isinstance(data, dict) or "result" not in data:
        return []
    host = urlsplit(row["api_url"]).netloc
    out = []
    for p in data.get("result") or []:
        loc = p.get("location") or {}
        parts = [loc.get("city") or "", loc.get("state") or "", loc.get("addressCountry") or ""]
        out.append({
            "company": row["company_name"], "title": _clean(p.get("jobOpeningName")),
            "location": _clean(", ".join(x for x in parts if x)),
            "country_code": "", "url": f"https://{host}/careers/{p.get('id')}",
            "posted_date": _clean((p.get("datePosted") or "")[:10]),
            "ats_platform": "bamboohr", "job_id": str(p.get("id") or ""),
            "description": "",
        })
    return out


_SCRAPE_CACHE = None


def fetch_scrape(row):
    """Custom / server-rendered career sites with no public API. The heavy Playwright scrape is run
    out-of-band (scrape_batch.py) and cached in scraped_cache.json; here we just read the cache so the
    daily pipeline stays fast. api_url holds the careers URL (used as the cache key fallback)."""
    global _SCRAPE_CACHE
    if _SCRAPE_CACHE is None:
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "scraped_cache.json")
        try:
            with open(path, encoding="utf-8") as f:
                _SCRAPE_CACHE = json.load(f)
        except Exception:  # noqa: BLE001
            _SCRAPE_CACHE = {}
    return _SCRAPE_CACHE.get(row["company_name"], []) or _SCRAPE_CACHE.get(row.get("token", ""), [])


def fetch_discovery(row):
    """LinkedIn/Indeed discovery layer (Bright Data scrapers, run out-of-band by
    discovery_daily.py). Reads discovered_cache.json; each job already carries its real
    employer name + posting URL. One synthetic company row ("Discovery") triggers this."""
    import json as _json
    import os as _os
    path = _os.path.join(_os.path.dirname(__file__), "..", "discovered_cache.json")
    try:
        with open(path, encoding="utf-8") as f:
            jobs = _json.load(f)
    except Exception:  # noqa: BLE001
        return []
    cut = (_dt.date.today() - _dt.timedelta(days=21)).isoformat()
    # run.py filters recruiter ROWS; discovery jobs carry the real employer name and would
    # bypass that check, so agencies re-posting client roles are dropped per-job here.
    from .recruiters import is_recruiter as _is_rec
    return [j for j in jobs
            if (not j.get("posted_date") or str(j["posted_date"])[:10] >= cut)
            and not _is_rec(j.get("company"))]


def fetch_jazzhr(row):
    """JazzHR has no consistent public JSON API. The one row (Questar) points at an
    /apply page, not a JSON endpoint — return empty and let the runner log it as skipped
    rather than crash the whole run."""
    return []


def fetch_oraclehcm(row):
    """Oracle Cloud HCM CandidateExperience public REST (no auth needed).

    api_url: https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=<SITE>
    The finder gains limit/offset/sortBy here; requisitions live in items[0].requisitionList.
    Job page: https://<host>/hcmUI/CandidateExperience/en/sites/<SITE>/job/<Id>
    """
    import re as _re
    base = row["api_url"]
    host = _re.search(r"https://([^/]+)/", base).group(1)
    ms = _re.search(r"siteNumber=([A-Za-z0-9_]+)", base)
    site = ms.group(1) if ms else "CX"
    if "expand=" not in base:
        base = base.replace("?onlyData=true", "?onlyData=true&expand=requisitionList.secondaryLocations")
    jobs, offset, total = [], 0, None
    while offset < 500:
        u = f"{base},limit=100,offset={offset},sortBy=POSTING_DATES_DESC"
        data = http.get_json(u)
        it = (data.get("items") or [{}])[0]
        total = it.get("TotalJobsCount") if total is None else total
        reqs = it.get("requisitionList", []) or []
        for p in reqs:
            locs = [str(p.get("PrimaryLocation") or "")]
            locs += [str(x.get("Name") or "") for x in (p.get("secondaryLocations") or [])]
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("Title")),
                "location": _clean("; ".join(x for x in locs if x)),
                "country_code": "",
                "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{p.get('Id')}",
                "posted_date": _iso_date(p.get("PostedDate")),
                "ats_platform": "oraclehcm",
                "job_id": str(p.get("Id") or ""),
                "description": _snippet(p.get("ExternalDescriptionStr") or p.get("ShortDescriptionStr")),
            })
        offset += 100
        if not reqs or (total is not None and offset >= int(total)):
            break
    return jobs


FETCHERS = {
    "comeet": fetch_comeet,
    "oraclehcm": fetch_oraclehcm,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
    "recruitee": fetch_recruitee,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
    "custom_json": fetch_custom_json,
    "jazzhr": fetch_jazzhr,
    "microsoft": fetch_microsoft,
    "workable": fetch_workable,
    "breezy": fetch_breezy,
    "bamboohr": fetch_bamboohr,
    "scrape": fetch_scrape,
    "discovery": fetch_discovery,
}


def fetch_company(row):
    """Fetch + normalize one company row. Raises on unknown platform."""
    platform = row["ats_platform"].strip().lower()
    fn = FETCHERS.get(platform)
    if fn is None:
        raise ValueError(f"unknown ats_platform {platform!r} for {row['company_name']}")
    return fn(row)
