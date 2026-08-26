"""Per-ATS-platform fetchers that normalize postings into one common shape.

Normalized job dict:
    {
      "company":       str,   # display name from companies.csv
      "title":         str,
      "location":      str,   # human-readable, best effort
      "country_code":  str,   # ISO alpha-2/alpha-3 upper when the feed gives one, else ""
      "url":           str,   # public posting URL
      "posted_date":   str,   # ISO date "YYYY-MM-DD" when parseable, else raw/""
      "ats_platform":  str,   # the row's platform, verbatim: the store keys on "{ats_platform}:{job_id}"
      "job_id":        str,   # stable per-platform id (for dedupe)
      "description":   str,   # plain text, <= _DESC_MAX chars, "" when the list response has none
    }

Each fetcher takes a company row (dict from companies.csv) and returns a list of
normalized job dicts. Fetchers do NOT filter by location or seniority — that happens
downstream. They only fetch + normalize.

Two exceptions to "they only fetch":

* A fetcher marked `israel_scoped = True` asks the BOARD for Israel (Workday's searchText,
  Eightfold's location=, Phenom's country facet, amazon.jobs' country=ISR), so an empty
  list from it is a measurement — "no Israel roles today" — not evidence of a broken
  board. `pipeline/health.py` reads that attribute and does not raise `empty-board` for
  them; 25 healthy Workday tenants were in the self-heal queue on 2026-08-24 because it
  did not.
* `BoardEmpty` is raised (never returned) when a scoped fetcher can tell the whole board
  is empty, so the row reaches the failed list in the mail and the self-heal queue with a
  reason instead of a silent zero.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re as _re
from urllib.parse import urlsplit

from . import http
from .israel import text_mentions_israel

_DESC_MAX = 6000  # chars of plain-text description kept — enough to reach the Requirements
                  # section (often past a long company-jargon intro) for the board's extractor


class BoardEmpty(Exception):
    """The board answered, and reports zero postings WORLDWIDE. Distinct from `http.HttpError`
    (the endpoint is dead) and from an empty Israel-scoped result (a measurement): a live
    tenant with nothing on it has almost always moved (Moon Active's Comeet sat at 0 for
    weeks while 33 jobs were on Ashby). Raised so the row is treated as a fetch failure —
    named in the mail, queued for the 06:00 self-heal — rather than counted as healthy."""


# 4xx = the endpoint itself is dead — except the four that mean "not now": 401 / 403
# (anti-bot: Dolby answers 401 "Please try again later" mid-sequence), 408 (timeout), 429
# (rate limit — the probe is an extra request aimed at the rows that returned nothing, so it
# is the request most likely to trip one). A real auth wall 401s the FIRST request, which
# propagates as a fetch-error regardless of this regex.
_CLIENT_ERROR = _re.compile(r"\bHTTP 4(?!01\b|03\b|08\b|29\b)\d\d\b")


def _served_none_or_raise(where, scoped_total):
    """The scoped request reported hits and served an empty first page. That is not a
    measurement and not an empty board — it is a board we cannot read (a moved `site`
    keeping its facet counts, id-less positions, an aggregations-only answer)."""
    if scoped_total:
        raise ValueError(f"{where}: reports {scoped_total} Israel hits but served none")


def _whole_board_or_raise(where, probe):
    """The Israel-scoped request came back empty; ask the board how many postings it has AT
    ALL. `probe()` returns that count (or None when the answer has no count). Three outcomes:

      0            -> raise BoardEmpty      (a live tenant with nothing on it has moved)
      > 0 / None   -> return                (a measurement: no Israel roles today)
      4xx          -> re-raise              (the endpoint itself is dead: that IS the finding,
                                             and swallowing it would hide a moved tenant;
                                             401 / 403 / 408 / 429 are "not now", not "dead")
      5xx/network  -> return                ("could not tell" must stay an empty list,
                                             never a failure)

    One extra request, only for rows that returned nothing. The first version swallowed
    every probe error, which failed open on exactly the condition it was there to detect.
    """
    try:
        total = probe()
    except http.HttpError as e:
        if _CLIENT_ERROR.search(str(e)):
            raise
        return
    except Exception:  # noqa: BLE001 — a malformed answer is "could not tell"
        return
    if total == 0:
        raise BoardEmpty(f"{where}: 0 postings worldwide — moved tenant?")


def _count(d, key):
    """A count field that may be missing, None or a string; None when absent."""
    v = (d or {}).get(key) if isinstance(d, dict) else None
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


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


def _greenhouse_location(name, offices):
    """A posting's `location.name` is free text a tenant may fill with a work mode ("Hybrid",
    "IL", "Remote"); the office sits in `offices[]` (present only with content=true). The
    office is read when it is unambiguous — exactly ONE office, and one that carries a
    `location` (a parent node of the tenant's office tree has none: SentinelOne's country
    node sat under a United Kingdom posting) — and only when the location names no IL place
    already, so an already-matched posting is left byte-identical:

        "Hybrid",  office Tel Aviv Office / Tel Aviv-Yafo, …  -> "Hybrid (Tel Aviv Office Tel Aviv-Yafo, …)"
        "",        office Tel Aviv Office / …                  -> "Tel Aviv Office Tel Aviv-Yafo, …"
        "Berlin",  office Berlin / Berlin, Germany             -> "Berlin, Germany"      (the fuller form)
        "Berlin, Germany", office Berlin / Berlin, Germany     -> "Berlin, Germany"      (already said)
        "Tel Aviv, Israel", any office                         -> "Tel Aviv, Israel"     (untouched)
        "United Kingdom", office Israel / location None        -> "United Kingdom"       (a parent node)
        "Paris, France", two offices                           -> "Paris, France"        (ambiguous)

    Census 2026-08-26 over all 103 active boards (7,870 postings): +5 IL matches (Eleos
    Health "IL" x2, Electreon "Remote"/"HQ Beit Yanni"/"Beit Yanai"), 0 lost; reading EVERY
    office would have added 14 false positives (10 Datadog EMEA jobs listing a global office
    set, Forter 2, Fireblocks 1, BigID 1). The request itself is unscoped (declared below
    `fetch_greenhouse`)."""
    loc = _clean(name)
    if not (isinstance(offices, list) and len(offices) == 1 and isinstance(offices[0], dict)
            and offices[0].get("location")) or text_mentions_israel(loc):
        return loc
    oname, where = _clean(str(offices[0].get("name") or "")), _clean(str(offices[0]["location"]))
    off = where if oname.lower() in where.lower() else f"{oname} {where}"
    if off.lower() in loc.lower():
        return loc                                     # the location already says it
    if loc.lower() in off.lower():
        return off                                     # the office is the fuller form
    return f"{loc} ({off})" if loc else off


def fetch_greenhouse(row):
    # content=true so the list carries the job body -> used by the LLM seniority fallback.
    api = row["api_url"]
    api = api + ("&" if "?" in api else "?") + "content=true"
    data = http.get_json(api)
    jobs = []
    for p in data.get("jobs", []):
        jobs.append({
            "company": row["company_name"],
            "title": _clean(p.get("title")),
            "location": _greenhouse_location((p.get("location") or {}).get("name", ""), p.get("offices")),
            "country_code": "",  # greenhouse list gives no code; rely on text match
            "url": p.get("absolute_url") or "",
            "posted_date": _iso_date(p.get("updated_at") or p.get("first_published")),
            "ats_platform": "greenhouse",
            "job_id": str(p.get("id") or ""),
            "description": _snippet(p.get("content")),
        })
    return jobs


# Declared, not scoped: the request is the whole board (the offices[] read above only
# normalises a location), so an empty list IS evidence.
fetch_greenhouse.israel_scoped = False


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

    Zero Israel hits is the common case (25 of the 26 Workday rows flagged `empty-board`
    on 2026-08-24 were live tenants with 2 to ~2,726 postings and none in Israel), so it is a
    measurement, not a fault. The one case that IS a fault — a tenant with no postings at
    all (Dell Technologies that day) — is told apart by one unscoped probe
    (`_whole_board_or_raise`) and raised as `BoardEmpty`.
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
        if offset == 0 and not postings:
            # an empty first page: one unscoped probe decides whether the board is empty
            # worldwide; if it is not, a `total` that claimed hits is a contradiction
            _whole_board_or_raise(f"{host}/{site}", lambda: _count(
                http.post_json(api, {"searchText": "", "limit": 1, "offset": 0}, retries=1), "total"))
            _served_none_or_raise(f"{host}/{site}", _count(data, "total"))
            break
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


fetch_workday.israel_scoped = True


def fetch_amazon(row):
    """Amazon custom_json: GET amazon.jobs search.json (the row's URL carries country=ISR),
    paginate by offset."""
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
    """Dispatch custom_json rows by host. Currently only Amazon, whose URL is a search
    scoped to country=ISR (which is why this dispatcher is `israel_scoped`; a second
    handler that is not scoped to Israel must not live under this platform name)."""
    host = urlsplit(row["api_url"]).netloc
    if "amazon.jobs" in host:
        return fetch_amazon(row)
    raise ValueError(f"no custom_json handler for host {host!r} (company {row['company_name']})")


fetch_custom_json.israel_scoped = True   # its one handler searches country=ISR


def fetch_eightfold(row):
    """Eightfold AI careers sites (Microsoft, Qualcomm, PayPal, Dolby, Lam Research, ...):
    the unauthenticated search behind the site's own results page,

        GET https://<host>/api/pcsx/search?domain=<domain>&query=&location=Israel&start=<n>&num=20

    `api_url` pins host and `?domain=` per row (the shared app.eightfold.ai host serves
    only a few tenants; most boards live on a tenant host such as careers.qualcomm.com).
    The `/api/apply/v2/jobs` path documented on eightfold.ai answers 403 "Not authorized
    for PCSX" on every real tenant from a plain client (2026-08-24) — do not use it.

    Validated 2026-08-24: careers.qualcomm.com → count=36 Israel positions, paged 10+10+10+6;
    apply.careers.microsoft.com → count=14, of which the old `fetch_microsoft` returned 10
    (see the paging note below). A tenant with no Israel roles answers count=0 with a
    non-zero worldwide count (paypal.eightfold.ai: 0 of 75) — a measurement, hence
    `israel_scoped`. Positions carry `standardizedLocations` ("Haifa, Haifa District, IL"),
    which is the explicit country signal the Israel filter prefers over text.

    The `microsoft` platform is this fetcher under its original name: rows keep that
    platform string because the store keys every role on "{ats_platform}:{job_id}", and
    Microsoft's public job page lives on jobs.careers.microsoft.com, not on the API host.
    """
    api = row["api_url"]
    host = urlsplit(api).netloc
    base = api.split("&query")[0].split("&location")[0]  # keep host/path + ?domain=...
    if "domain=" not in base:
        domain = (row.get("token") or "").strip()
        if not domain:
            raise ValueError(f"eightfold row needs ?domain= in api_url or the token column "
                             f"({row['company_name']})")
        base += ("&" if "?" in base else "?") + f"domain={domain}"
    jobs, seen_ids, start, num = [], set(), 0, 20
    for _ in range(40):                      # hard stop: 40 calls (the server pages at 10)
        data = http.get_json(f"{base}&query=&location=Israel&start={start}&num={num}")
        d = data.get("data") if isinstance(data, dict) else None
        if not isinstance(d, dict) or "positions" not in d:
            if start:
                break                          # an exhausted page with no envelope: done
            # Phenom hosts and mis-pointed rows answer 200 with an error envelope; a
            # confident zero here would look like an empty board forever.
            raise ValueError(f"not an Eightfold pcsx response for {host}: "
                             f"{str(data.get('errorMsg') if isinstance(data, dict) else data)[:80]}")
        positions = d.get("positions") or []
        count = _count(d, "count")
        if start == 0 and not positions:
            # 0 Israel positions: a measurement (paypal.eightfold.ai: 0 of 75) unless the
            # tenant has 0 positions at all — a wrong ?domain= or a moved board
            _whole_board_or_raise(host, lambda: _count(
                (http.get_json(f"{base}&query=&location=&start=0&num=1", retries=1) or {}).get("data"),
                "count"))
            _served_none_or_raise(host, count)
            break
        for p in positions:
            jid = str(p.get("displayJobId") or p.get("id") or "")
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            locs = [str(x) for x in (p.get("locations") or []) if x]
            std = [str(x) for x in (p.get("standardizedLocations") or []) if x]
            code = "IL" if any(x == "IL" or x.endswith(", IL") for x in std) else ""
            ts = p.get("postedTs") or p.get("creationTs")
            pdate = ""
            if ts:
                try:
                    ts = int(ts)
                    if ts > 1e11:      # milliseconds vs seconds
                        ts //= 1000
                    pdate = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                except (TypeError, ValueError, OverflowError, OSError):
                    pdate = ""
            if host.endswith("careers.microsoft.com"):
                purl = f"https://jobs.careers.microsoft.com/global/en/job/{jid}"
            else:
                purl = p.get("positionUrl") or ""
                if purl.startswith("/"):
                    purl = f"https://{host}{purl}"
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("name")),
                # the search was location=Israel, so a position with no location field at
                # all is still an Israel hit (the old Microsoft fetcher defaulted the same)
                "location": _clean("; ".join(locs)) or "Israel",
                "country_code": code,
                "url": purl,
                "posted_date": pdate,
                "ats_platform": row["ats_platform"].strip().lower(),
                "job_id": jid,
                "description": "",       # the search response carries no JD (jdfill fetches it)
            })
        # The server pages at 10 whatever `num` says (Qualcomm: count=36 came back as
        # 10+10+10+6). Advancing by `num` skipped positions 10-19 of every page: Microsoft
        # had count=14 on 2026-08-24 and the old fetcher returned 10 of them, every day.
        start += len(positions)
        if not positions or (count is not None and start >= count):
            break                              # no `count`: page until the server runs dry
    return jobs


fetch_eightfold.israel_scoped = True


_PHENOM_BODY = {
    "lang": "en_us", "deviceType": "desktop", "country": "us", "pageName": "search-results",
    "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "jobs": True, "counts": True,
    "all_fields": ["category", "country", "state", "city"], "clearAll": False,
    "jdsource": "facets", "isSliderEnable": False, "pageId": "page12", "siteType": "external",
    "keywords": "", "global": True, "selected_fields": {"country": ["Israel"]},
}


def fetch_phenom(row):
    """Phenom People careers sites (GE HealthCare, P&G, eBay, OpenText, ...): the widget
    search their results page calls,

        POST https://<host>/widgets   body: _PHENOM_BODY + {"from": n, "size": 100}

    `api_url` is the /widgets URL on the tenant host. The response is
    {"refineSearch": {"totalHits", "data": {"jobs": [...]}}}; anything else (Dolby answers
    401 "Please try again later"; a non-Phenom host answers something without
    `refineSearch`) raises so the row is a visible failure, not a zero.

    Validated 2026-08-24: careers.gehealthcare.com → totalHits=20, and an unfiltered walk
    (963 of 985 reachable) found no Israel-located job outside the facet — the country
    facet is exact, hence `israel_scoped`. pgcareers.com / jobs.ebayinc.com /
    careers.opentext.com answered 0 of 172 / 472 / 317, also exact. Known limit: the
    server's sort is unstable, so on a tenant with more than one page (100) of Israel hits
    ~9 postings per page boundary can be missed (measured on GE's unfiltered walk); no
    tenant today comes close.
    """
    api = row["api_url"]
    jobs, seen_ids, start, size = [], set(), 0, 100
    for _ in range(30):                       # hard stop: 3,000 postings
        data = http.post_json(api, {**_PHENOM_BODY, "from": start, "size": size})
        rs = data.get("refineSearch") if isinstance(data, dict) else None
        if not isinstance(rs, dict):
            raise ValueError(f"not a Phenom widgets response for {urlsplit(api).netloc}: "
                             f"{str(data.get('errorMsg') if isinstance(data, dict) else data)[:80]}")
        page = ((rs.get("data") or {}).get("jobs")) or []
        total = _count(rs, "totalHits")
        if start == 0 and not page:
            # 0 Israel hits is a measurement (eBay: 0 of 472) unless the site has 0 hits at all
            def _whole():
                w = http.post_json(api, {**_PHENOM_BODY, "selected_fields": {}, "from": 0, "size": 1},
                                   retries=1)
                return _count((w or {}).get("refineSearch"), "totalHits")
            _whole_board_or_raise(urlsplit(api).netloc, _whole)
            _served_none_or_raise(urlsplit(api).netloc, total or 0)
            break
        for p in page:
            jid = str(p.get("jobSeqNo") or p.get("reqId") or p.get("jobId") or "")
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            loc = p.get("cityStateCountry") or ", ".join(
                x for x in (p.get("city"), p.get("state"), p.get("country")) if x)
            jobs.append({
                "company": row["company_name"],
                "title": _clean(p.get("title")),
                "location": _clean(loc),
                "country_code": "IL" if str(p.get("country") or "").strip().lower() == "israel" else "",
                "url": p.get("applyUrl") or "",
                "posted_date": _iso_date(p.get("postedDate") or p.get("dateCreated")),
                "ats_platform": "phenom",
                "job_id": jid,
                # `descriptionTeaser` is a ~350-char search-page blurb that never states
                # years of experience; storing it would clear jdfill's "missing JD" bar
                # (300 chars) and the classifier would judge on a teaser. Leave it empty
                # so the real posting is fetched, like workday/bamboohr.
                "description": "",
            })
        start += len(page)                    # by what came back, never by `size`
        if not page or (total is not None and start >= total):
            break                              # no `totalHits`: page until the server runs dry
    return jobs


fetch_phenom.israel_scoped = True


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
            "url": url or "", "posted_date": _iso_date(p.get("created_at")),
            "ats_platform": "workable", "job_id": str(p.get("id") or p.get("shortcode") or ""),
            "description": _snippet(p.get("description")),
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
            "posted_date": _iso_date(p.get("published_date") or p.get("creation_date")),
            "ats_platform": "breezy", "job_id": str(friendly),
            "description": _snippet(p.get("description")),
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
            "posted_date": _iso_date(p.get("datePosted")),
            "ats_platform": "bamboohr", "job_id": str(p.get("id") or ""),
            "description": "",
        })
    return out


_SCRAPE_CACHE = None

# A page's consent banner and its nav are not openings. The universal scraper reads whatever
# card-shaped text a careers page offers, and on ten companies that included "Strictly
# necessary cookies", "Manage Consent Preferences" and "Heading 4" — one of which
# ("Analytics Cookies") carries an analytics signal and reached the LLM tier as a candidate
# role. Filtered on READ, so it applies to everything already cached.
_JUNK_TITLE = _re.compile(
    "|".join((
        # a consent banner's own row labels, which is the whole of the card's text
        r"^\W*(strictly necessary|performance|analytics|marketing|functional|"
        r"targeting)?\s*cookies?\W*$",
        r"^\W*(manage\s+)?consent(\s+preferences)?\W*$",
        r"^\W*cookie\s+(list|policy|notice|consent|preferences|settings)\W*$",
        r"^\W*consent and data privacy\W*$",
        r"^\W*privacy (policy|notice)\W*$",
        # page chrome that a card-shaped selector picks up
        r"^\W*heading \d+\W*$",
        r"^\W*(read|learn) more\W*$",
        r"^\W*(about|contact) us\W*$",
        r"^\W*press releases?\W*$",
        r"^\W*(sign|log) ?in\W*$",
        r"^\W*newsletter\W*$",
    )),
    _re.I)
# ...and a card whose text ran together with its own call-to-action keeps the role, loses
# the tail ("Mumbai, IN Customer Success Specialist - APAC Read more").
_TITLE_TAIL = _re.compile(r"\s*[-–—|·]?\s*(read more|learn more|apply now|view (job|role)|"
                          r"see (job|details))\W*$", _re.I)


def clean_scraped(jobs):
    """Drop chrome-only cards and trim a trailing call-to-action from the rest."""
    out = []
    for j in jobs or []:
        if not isinstance(j, dict):
            continue
        t = (j.get("title") or "").strip()
        if not t or _JUNK_TITLE.search(t):
            continue
        cleaned = _TITLE_TAIL.sub("", t).strip()
        if cleaned and cleaned != t:
            j = {**j, "title": cleaned}
        out.append(j)
    return out


def fetch_scrape(row):
    """Custom / server-rendered career sites with no public API. The heavy Playwright scrape is run
    out-of-band (refresh_scrape_cache.py, 00:00 UTC) and cached in scraped_cache.json; here we just
    read the cache so the daily pipeline stays fast. api_url holds the careers URL (used as the
    cache key fallback). `SCRAPE_CACHE_IN=<file>` points a rehearsal at a scratch cache (the
    scraper's `SCRAPE_CACHE_OUT` is the writer's half of the same seam); read once per process."""
    global _SCRAPE_CACHE
    if _SCRAPE_CACHE is None:
        import json
        import os
        path = (os.environ.get("SCRAPE_CACHE_IN")
                or os.path.join(os.path.dirname(__file__), "..", "scraped_cache.json"))
        try:
            with open(path, encoding="utf-8") as f:
                _SCRAPE_CACHE = json.load(f)
        except Exception:  # noqa: BLE001
            _SCRAPE_CACHE = {}
    return clean_scraped(_SCRAPE_CACHE.get(row["company_name"], [])
                         or _SCRAPE_CACHE.get(row.get("token", ""), []))


_GENERIC_LABELS = {"jobs", "careers", "apply", "boards", "www"}
_LINKEDIN_EMPLOYER = _re.compile(r"/jobs/view/.*?-at-([a-z0-9-]+?)-\d{6,}(?:[/?#]|$)")


def slug_names_declared_identity(company, url):
    """Does the LinkedIn slug's employer half name a DECLARED identity of `company`?

    The slug guard (`company_identity.url_names_other_company`) drops a card whose
    "<title>-at-<employer>-<id>" names someone else — which is also what an acquisition
    looks like. The one exemption is a declaration in `pipeline/identity_facts.py`
    (tenants and domain labels), matched against a whole leading run of the employer's
    slug words, exactly:

        "Merck (MSD)"   tenant `msd`      …/x-at-msd-4454120001          -> True
        "Merck (MSD)"                     …/x-at-msdelivery-4454120001   -> False (not a whole word)
        "SentinelOne"   `sentinellabs`    …/x-at-sentinel-labs-4454…     -> True  (words joined)
        "Itamar Medical" `zoll`           …/x-at-zollinger-corp-4454…    -> False
        "AWS"           domain `amazon`   …/amazon-consultant-at-acme-…  -> False (title half)
        "Siemens EDA"   `sw`              anything                       -> False (2 chars)

    A blanket "never drop a registry name" is deliberately NOT done: the 147 rows once
    published under the wrong employer carried registry names too (docs/BACKLOG.md 9).
    """
    from .identity_facts import domains, normalize, tenants
    m = _LINKEDIN_EMPLOYER.search((url or "").lower())
    words = m.group(1).split("-") if m else []
    prefixes = {"".join(words[:i]) for i in range(1, len(words) + 1)}
    toks = set(tenants(company))
    for d in domains(company):
        toks |= {normalize(lbl) for lbl in d.lower().split(".") if lbl not in _GENERIC_LABELS}
    return any(len(t) >= 3 and t in prefixes for t in toks)


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
    from .company_identity import url_names_other_company
    from .recruiters import is_recruiter as _is_rec
    # ...and a LinkedIn card whose URL slug names a DIFFERENT employer is mis-attributed at
    # the source: 147 board rows were once published under the wrong company this way.
    # Dropped HERE rather than caught by check_invariants, so one bad card cannot withhold
    # a whole day's digest at the commit gate.
    #
    # Every drop is COUNTED and printed: the three filters used to be one silent list
    # comprehension, and the slug guard also drops an acquired employer whose LinkedIn slug
    # still carries the old name (NVIDIA / at-mellanox) — the same shape as a mis-attributed
    # card (docs/BACKLOG.md 9). `check_invariants` runs the same predicate over the board
    # as a WARNING, so a card kept here can only ever be a warning line there.
    kept, dropped = [], {"expired": 0, "recruiter": 0, "slug-mismatch": 0}
    for j in jobs:
        if j.get("posted_date") and str(j["posted_date"])[:10] < cut:
            dropped["expired"] += 1
        elif _is_rec(j.get("company"), j.get("company_slug") or ""):   # the slug says "recruiting" when the name hides it
            dropped["recruiter"] += 1
        elif (url_names_other_company(j.get("company"), j.get("url"))
              and not slug_names_declared_identity(j.get("company"), j.get("url"))):
            dropped["slug-mismatch"] += 1
        else:
            kept.append(j)
    if any(dropped.values()):
        print(f"  [discovery] kept {len(kept)} of {len(jobs)} cached jobs (dropped: "
              + ", ".join(f"{k} {v}" for k, v in dropped.items() if v) + ")", flush=True)
    return kept


def fetch_oraclehcm(row):
    """Oracle Cloud HCM CandidateExperience public REST (no auth needed).

    api_url: https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=<SITE>
    The finder gains limit/offset/sortBy here; requisitions live in items[0].requisitionList.
    Job page: https://<host>/hcmUI/CandidateExperience/en/sites/<SITE>/job/<Id>

    **The board is READ WHOLE when it is not enormous, because Oracle CE has no location
    filter that can be trusted.** Measured 2026-08-26 against all five active tenants:

      keyword=Israel          under-reports badly -- Fortinet 7 hits against 19 real Israel
                              roles, JPMorganChase 0 against 4
      workLocationCountryCode=IL   SILENTLY IGNORED: returns the whole board (onsemi 685,
                              Fortinet 911, Dell 445, JPMorganChase 7,305)
      locationCountryCode=IL  HTTP 400
      selectedLocationsFacet=IL    returns 0 -- kills the query
      locationId=<numeric>    works ONLY where the tenant's own `locationsFacet` advertises
                              that id (Verint: exactly 4). Elsewhere it is silently ignored
                              and the whole board comes back looking like Israel -- which
                              would publish Texas jobs under an Israeli employer, so this
                              fetcher never sends an id the tenant did not advertise.

    So the honest method is to read every requisition and let `pipeline.israel` decide, which
    is what already happens to the newest-500 pass. The cost is bounded by ORACLE_FULL_WALK_MAX
    (2,000 requisitions = 20 requests): onsemi 684 in 12.4 s, Fortinet 911 in 16.2 s, Dell 445
    in 13.3 s, Verint 49 in 1.5 s. It recovered **4 Israel roles at Fortinet on the first
    run** (15 -> 19), which the newest-500 + keyword design had never seen.

    A board ABOVE the bound keeps the old two passes and is a KNOWN BLIND SPOT: JPMorganChase
    posts 7,303 requisitions and hides 4 Israel roles behind them, which a full walk finds in
    196 s -- three and a half minutes on a fetch loop of five, for four roles no classifier
    would accept. Raise `ORACLE_FULL_WALK_MAX` to include it (`docs/BACKLOG.md` 241).
    """
    import os as _os
    import re as _re
    base = row["api_url"]
    host = _re.search(r"https://([^/]+)/", base).group(1)
    ms = _re.search(r"siteNumber=([A-Za-z0-9_]+)", base)
    site = ms.group(1) if ms else "CX"
    if "expand=" not in base:
        base = base.replace("?onlyData=true", "?onlyData=true&expand=requisitionList.secondaryLocations")
    try:
        full_max = int(_os.environ.get("ORACLE_FULL_WALK_MAX", "2000"))
    except ValueError:
        full_max = 2000
    jobs, seen_ids, total = [], set(), None

    def _page(url):
        """One page -> (requisitions, TotalJobsCount or None). Never raises on shape."""
        data = http.get_json(url)
        it = (data.get("items") or [{}])[0] if isinstance(data, dict) else {}
        it = it if isinstance(it, dict) else {}
        return (it.get("requisitionList") or []), _count(it, "TotalJobsCount")

    first, total = _page(f"{base},limit=100,offset=0,sortBy=POSTING_DATES_DESC")
    # Read the whole board when it fits the bound; otherwise the old newest-500 pass plus the
    # keyword pass, which is a supplement and not a filter (it misses more than it finds).
    walk_to = min(total, full_max) if isinstance(total, int) and total <= full_max else 500
    pages = [(first, None)] + [(None, f"{base},limit=100,offset={o},sortBy=POSTING_DATES_DESC")
                               for o in range(100, walk_to, 100)]
    if not (isinstance(total, int) and total <= full_max):
        pages += [(None, f"{base},keyword=Israel,limit=100,offset={o},sortBy=POSTING_DATES_DESC")
                  for o in range(0, 300, 100)]
    for reqs, u in pages:
        if reqs is None:
            reqs, _t = _page(u)
        if not reqs:
            continue
        for p in reqs:
            if str(p.get("Id") or "") in seen_ids:
                continue
            seen_ids.add(str(p.get("Id") or ""))
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
    return jobs


# Declared, not scoped: the walk is unscoped, so an empty list means the board has no
# postings at all — a zero IS evidence here. (Every server-side Israel filter this API
# offers is either ignored or wrong; see the docstring.)
fetch_oraclehcm.israel_scoped = False


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
    "workable": fetch_workable,
    "breezy": fetch_breezy,
    "bamboohr": fetch_bamboohr,
    "eightfold": fetch_eightfold,
    "microsoft": fetch_eightfold,   # Microsoft's site IS Eightfold; the name is the store key
    "phenom": fetch_phenom,
    "scrape": fetch_scrape,         # pseudo-platform: reads scraped_cache.json
    "discovery": fetch_discovery,   # pseudo-platform: reads discovered_cache.json
}


def fetch_company(row):
    """Fetch + normalize one company row. Raises on unknown platform."""
    platform = row["ats_platform"].strip().lower()
    fn = FETCHERS.get(platform)
    if fn is None:
        raise ValueError(f"unknown ats_platform {platform!r} for {row['company_name']}")
    return fn(row)
