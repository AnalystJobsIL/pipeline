#!/usr/bin/env python3
"""Universal careers scraper. Renders the page, then harvests job objects from EVERY place a modern
site might keep them and parses them with one heuristic:

  sources:  JSON-LD JobPosting  +  embedded page state (__NEXT_DATA__ / Apollo / Relay / Redux)
            +  every XHR/fetch JSON response body captured during load
  parser:   recursively find arrays whose elements are objects carrying a title-like field
            (plus a location/url/id field), from any of those sources.

No per-site code. Works for Next.js/React/GraphQL career sites (Google, Meta, Shopify, Booking, and
the custom Israeli SPAs) that expose no simple public API.
"""
from __future__ import annotations

import json
import re
import sys

from pipeline import israel

TITLE_KEYS = {"title", "jobtitle", "positiontitle", "position_title", "name", "role", "rolename",
              "postingtitle", "posting_title", "displayname", "display_name", "jobname"}
LOC_KEYS = {"location", "locations", "office", "offices", "city", "joblocation", "job_location",
            "location_display_name", "locationname", "primarylocation", "locationstext",
            "addresslocality", "location_name", "officelocation", "cities"}
URL_KEYS = {"url", "absolute_url", "joburl", "job_url", "apply_url", "applyurl", "link", "href",
            "canonicalurl", "externalpath", "positionurl", "detailurl", "landing_page", "hitlink"}
ID_KEYS = {"id", "jobid", "job_id", "reqid", "req_id", "requisitionid", "shortcode", "displayjobid",
           "ffid", "slug", "pid", "gh_id"}
DATE_KEYS = {"dateposted", "date_posted", "postedon", "posted_on", "publisheddate", "created_at",
             "postedts", "creationts", "updated_at", "firstpublished", "posting_date"}
BAD_TITLE = re.compile(r"^(home|careers?|jobs?|about|search|apply|menu|cookie|privacy|all|view|"
                       r"open positions|see all|load more|next|previous)$", re.I)
# a real title never carries breadcrumb separators, an embedded location, or a leaked
# sentence — these mark a run-together card blob ("…Product AnalyticsTel Aviv, Israel⋅Data…")
TITLE_JUNK = re.compile(
    r"[⋅•·|►▸]|,\s*israel\b|tel[\s-]?aviv,|\bis looking for\b|"
    r"\bwe(?:'re| are) looking\b|\bwe are seeking\b|posted\s+\d|"
    # run-together card text: a place/CTA fused onto the end of the title with no space
    # ("Data ScientistTel Aviv", "…IsraelApply") — a lowercase letter butting one of these words
    r"(?<=[a-z])(?:Tel Aviv|Israel|Herzliya|Haifa|Ra'?anana|Petah|Apply|Remote|Hybrid|"
    r"Full[\s-]?time|View job|Learn more)|israel(?=[A-Za-z])",
    re.I)
ROLE = re.compile(r"engineer|developer|manager|analyst|scientist|designer|\blead\b|architect|"
                  r"specialist|director|\bhead\b|officer|consultant|researcher|marketing|sales|"
                  r"product|\bdata\b|devops|\bqa\b|account|recruit|finance|legal|operations|"
                  r"support|success|counsel|controller|analytics|intern|associate|representative|"
                  r"coordinator|administrator|strategist|writer|editor|producer|planner|buyer|"
                  r"technician|expert|advisor|\bpartner\b|evangelist|advocate|programmer|"
                  r"\bsre\b|\bux\b|\bui\b|scrum|agile|automation|solution|business|operation|"
                  r"team\s+lead|full[\s-]?stack|back[\s-]?end|front[\s-]?end|principal|staff|"
                  r"vp\b|chief|president|counsel|paralegal|accountant|bookkeeper|generalist", re.I)
ISRAEL_LOC = re.compile(r"israel|tel[\s-]?aviv|herzliya|haifa|yokneam|ra.?anana|petah|"
                        r"bnei[\s-]?brak|lod\b|ashdod|ashkelon|ness[\s-]?ziona|rishon|kfar[\s-]?saba|"
                        r"\u05d9\u05e9\u05e8\u05d0\u05dc|\u05ea\u05dc[\s-]?\u05d0\u05d1\u05d9\u05d1|\u05d7\u05d9\u05e4\u05d4|\u05d1\u05d0\u05e8[\s-]?\u05e9\u05d1\u05e2|\u05e8\u05e2\u05e0\u05e0\u05d4|\u05d4\u05e8\u05e6\u05dc\u05d9\u05d4|"
                        r"beer[\s-]?sheva|netanya|rehovot|caesarea|yakum|kiryat|nazareth|"
                        r"jerusalem|modiin|hod\s+hasharon|airport\s+city|or\s+yehuda|"
                        r"givatayim|ramat\s+gan|holon|rosh\s+ha|karmiel|migdal", re.I)


def _s(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("name", "text", "label", "value", "location_display_name", "display_name",
                  "addressLocality", "title"):
            if isinstance(v.get(k), str):
                return v[k]
    if isinstance(v, list):
        return ", ".join(x for x in (_s(e) for e in v[:3]) if x)
    return ""


def _get(o, keys):
    for k, v in o.items():
        if k.lower() in keys:
            s = _s(v)
            if s:
                return s
    return ""


def _title_of(o):
    for k, v in o.items():
        if k.lower() in TITLE_KEYS and isinstance(v, str):
            t = v.strip()
            if (4 <= len(t) <= 90 and not BAD_TITLE.match(t) and not t.startswith("http")
                    and ROLE.search(t) and not TITLE_JUNK.search(t)):  # a real job title
                return t
    return ""


def _find(node, out, depth=0):
    if depth > 14:
        return
    if isinstance(node, list):
        objs = [x for x in node if isinstance(x, dict)]
        titled = [o for o in objs if _title_of(o)]
        if len(titled) >= 2 and len(titled) >= len(objs) * 0.4:
            for o in titled:
                if _get(o, LOC_KEYS) or _get(o, URL_KEYS) or _get(o, ID_KEYS):
                    out.append(o)
        for x in node:
            _find(x, out, depth + 1)
    elif isinstance(node, dict):
        for v in node.values():
            _find(v, out, depth + 1)


_STATE_JS = r"""() => {
  const blobs = [];
  const push = (v) => { try { blobs.push(JSON.stringify(v)); } catch (e) {} };
  const names = ['__NEXT_DATA__','__APOLLO_STATE__','__APOLLO_CLIENT__','__INITIAL_STATE__',
    '__PRELOADED_STATE__','__REDUX_STATE__','__NUXT__','__data','__remixContext','_sharedData'];
  names.forEach(n => { if (window[n]) push(window[n]); });
  for (const k in window) { if (/relay|apollo|store|state|jobs|careers/i.test(k)) {
    try { const v = window[k]; if (v && typeof v === 'object') push(v); } catch (e) {} } }
  document.querySelectorAll('script[type="application/ld+json"],script[type="application/json"],'
    + 'script#__NEXT_DATA__').forEach(s => { if (s.textContent && s.textContent.length > 80) blobs.push(s.textContent); });
  return blobs;
}"""


_DOM_JS = r"""() => {
  const out = [], seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    let title = (a.textContent || '').trim().replace(/\s+/g, ' ');
    if (title.length < 5 || title.length > 140) return;
    const k = title + '|' + a.href;
    if (seen.has(k)) return; seen.add(k);
    let node = a, ctx = '';
    for (let d = 0; d < 4 && node; d++) { ctx += ' ' + (node.textContent || ''); node = node.parentElement; }
    out.push({title: title, url: a.href, ctx: ctx.replace(/\s+/g, ' ').slice(0, 500)});
  });
  return out.slice(0, 500);
}"""


import datetime as _dt

_REL_D = re.compile(r"(\d+)\+?\s*day", re.I)
_REL_M = re.compile(r"(\d+)\+?\s*month", re.I)


def _norm_date(raw):
    """Return an ISO date. Recovers relative strings ('Posted 4 Days Ago'); '' if unknown.
    Never returns raw junk — the digest would otherwise show 'Posted 2 D' (10-char cut)."""
    s = str(raw or "").strip()
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return s[:10]
    sl = s.lower()
    today = _dt.date.today()
    if "today" in sl or "just posted" in sl or "just now" in sl:
        return today.isoformat()
    if "yesterday" in sl:
        return (today - _dt.timedelta(days=1)).isoformat()
    m = _REL_D.search(sl)
    if m:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    m = _REL_M.search(sl)
    if m:
        return (today - _dt.timedelta(days=30 * int(m.group(1)))).isoformat()
    m = re.match(r"posted\s+(\d+)", sl)          # 'Posted 4 [Days Ago]' truncations
    if m and int(m.group(1)) <= 365:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    return ""


def _loc_from_ctx(ctx):
    m = re.search(r"([A-Za-z][\w.\-' ]{1,28},?\s*Israel)", ctx)
    if m:
        return m.group(1).strip()
    m = ISRAEL_LOC.search(ctx)
    return ctx[max(0, m.start() - 12):m.end() + 8].strip() if m else "Israel"


def scrape(company, url, timeout_ms=45000):
    from playwright.sync_api import sync_playwright
    bodies = []

    def on_resp(resp):
        if resp.request.resource_type in ("xhr", "fetch", "document"):
            try:
                t = resp.text()
                if 120 < len(t) < 4_000_000 and (t.lstrip()[:1] in "{[" or "JobPosting" in t):
                    bodies.append(t)
            except Exception:
                pass

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        pg.on("response", on_resp)
        import os
        fast = os.environ.get("FAST_SCRAPE")
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                pg.wait_for_load_state("networkidle", timeout=6000 if fast else 12000)
            except Exception:
                pass
            for _ in range(2 if fast else 3):
                pg.mouse.wheel(0, 3000)
                pg.wait_for_timeout(1000 if fast else 1800)
            blobs = pg.evaluate(_STATE_JS)
            dom = pg.evaluate(_DOM_JS)
        except Exception:
            blobs, dom = [], []
        finally:
            b.close()

    raw = []
    for txt in blobs + bodies:
        try:
            _find(json.loads(txt), raw)
        except Exception:
            for m in re.finditer(r"\{[^{}]{0,4000}\}", txt):   # last-ditch: scan embedded objects
                try:
                    o = json.loads(m.group(0))
                    if _title_of(o):
                        raw.append(o)
                except Exception:
                    pass

    from urllib.parse import urljoin
    seen, jobs = set(), []

    def add(title, loc, url_, date="", desc="", jid=""):
        title = (title or "").strip()
        # drop run-together card blobs (breadcrumb/location/sentence leaked into the title)
        if not title or len(title) > 90 or TITLE_JUNK.search(title) or BAD_TITLE.match(title):
            return
        if not ISRAEL_LOC.search(loc or ""):
            return
        if url_ and url_.startswith("/"):
            url_ = urljoin(url, url_)
        key = (title.lower(), (loc or "").lower())
        if key in seen:
            return
        seen.add(key)
        jobs.append({"company": company, "title": title[:90], "location": loc, "country_code": "IL",
                     "url": url_ or url, "posted_date": _norm_date(date), "ats_platform": "scrape",
                     "job_id": jid or url_ or title, "description": (desc or "")[:1500]})

    for o in raw:                                  # 1) structured JSON (state / XHR / JSON-LD)
        add(_title_of(o), _get(o, LOC_KEYS), _get(o, URL_KEYS), _get(o, DATE_KEYS),
            _get(o, {"description", "jobdescription", "summary"}), _get(o, ID_KEYS))
    _POSTING_HREF = re.compile(r"/(job|jobs|position|opening|vacancy|role)s?[/\-_=?]|gh_jid=|/apply\b", re.I)
    for d in dom:                                  # 2) rendered DOM job-card links
        t = d.get("title", "")
        u2 = d.get("url", "")
        ctx = d.get("ctx", "")
        m = ISRAEL_LOC.search(ctx)
        near = bool(m and (t in ctx) and abs(ctx.find(t) - m.start()) < 220)
        if (ROLE.search(t) and not BAD_TITLE.match(t) and _POSTING_HREF.search(u2)
                and (near or ISRAEL_LOC.search(t))):
            add(t, _loc_from_ctx(ctx), u2)
    return jobs


if __name__ == "__main__":
    tests = [
        ("Google", "https://www.google.com/about/careers/applications/jobs/results/?location=Israel"),
        ("Meta", "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel"),
        ("Shopify", "https://www.shopify.com/careers/search?location=Israel"),
        ("Booking.com", "https://jobs.booking.com/booking/jobs?location=Israel"),
        ("Snyk", "https://snyk.io/careers/"),
        ("Coralogix", "https://coralogix.com/careers/"),
        ("Cato Networks", "https://www.catonetworks.com/careers/"),
    ]
    if len(sys.argv) >= 3:
        tests = [(sys.argv[1], sys.argv[2])]
    for name, url in tests:
        try:
            js = scrape(name, url)
            il = sum(1 for j in js if israel.is_israel_job(j))
            print(f"{name:16} jobs={len(js):4} israel={il}")
            for j in [x for x in js if israel.is_israel_job(x)][:3]:
                print(f"     - {j['title'][:52]} | {j['location'][:30]} | {j['posted_date']}")
        except Exception as e:  # noqa: BLE001
            print(f"{name:16} ERR {type(e).__name__}: {str(e)[:70]}")
