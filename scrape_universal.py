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
# Israel location matcher — derived from pipeline/israel.py so there is ONE city list.
# (A separate hand-maintained copy here silently dropped Sderot, Yoqneam, Nes Ziona,
# Ramat-Gan and 23 other spellings — real roles were extracted then filtered away.)
def _build_israel_loc():
    from pipeline.israel import _IL_PLACES
    alts = sorted((re.escape(p).replace(r"\ ", r"[\s-]?") for p in _IL_PLACES),
                  key=len, reverse=True)
    hebrew = ["ישראל", "תל[\s-]?אביב",
              "חיפה", "באר[\s-]?שבע",
              "רעננה", "הרצליה",
              "ירושלים", "פתח[\s-]?תקווה"]
    return re.compile("|".join(alts + hebrew), re.I)


ISRAEL_LOC = _build_israel_loc()


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
        # stealth: several real careers pages (Entro, Legit) serve a stripped page to
        # detectable headless automation — mask the fingerprint
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
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
            page_html = pg.content()
        except Exception:
            blobs, dom, page_html = [], [], ""
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
                     "job_id": jid or url_ or title, "description": (desc or "")[:6000]})

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

    # 3) repeated heading-group fallback (Radancy/Google-style server-rendered listings):
    # job cards as N same-class <h2>/<h3> siblings. Only when the earlier passes found
    # nothing, and only trust a missing per-card location if the LISTING URL itself is
    # already Israel-filtered (…?location=Israel, /search-jobs/…Israel…).
    if not jobs:
        # headless Chromium sometimes gets a bot-stripped page while plain HTTP gets the
        # real server-rendered cards (Legit Security) — try both HTML sources
        try:
            import urllib.request as _ur2
            _req2 = _ur2.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"})
            plain_html = _ur2.urlopen(_req2, timeout=15).read(1_500_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            plain_html = ""
        if len(plain_html) > len(page_html or ""):
            page_html = plain_html if not page_html else page_html + "\n" + plain_html

    if not jobs and page_html:
        url_is_il = bool(ISRAEL_LOC.search(url))
        # listing_hunt sets SCRAPE_ASSUME_IL=1 for pre-vetted Israeli companies whose own
        # careers pages omit per-card locations (implicitly local): accept the page-level
        # Israel signal (footer address, office name, Hebrew) instead of per-card text.
        import os as _os
        if _os.environ.get("SCRAPE_ASSUME_IL") and ISRAEL_LOC.search(page_html):
            url_is_il = True
        groups = {}
        _CARD_PATTERNS = (
            r"<(h[1-4])([^>]*)>([^<]{5,90})</\1>",
            # non-heading job cards: any tag whose class names it a job/position title
            # (e.g. Legit Security's <p class="job-post-title">)
            r'<(p|div|span|a)([^>]*class=["\'][^"\']*(?:job|position|role|opening)[^"\']*'
            r'(?:title|name|copy)[^"\']*["\'][^>]*)>([^<]{5,90})</\1>',
        )
        for pat in _CARD_PATTERNS:
            for m in re.finditer(pat, page_html, re.I):
                tag, attrs, text = m.group(1).lower(), m.group(2), m.group(3).strip()
                cls = (re.search(r'class=["\']([^"\']+)', attrs) or [None, ""])[1] if "class=" in attrs else ""
                groups.setdefault((tag, cls), []).append((m.start(), text))
        for (tag, cls), items in groups.items():
            if len(items) < 3:
                continue
            titles = [t for _, t in items]
            junk = sum(1 for t in titles if BAD_TITLE.match(t) or not re.search(r"[a-zא-ת]", t, re.I))
            rolish = sum(1 for t in titles if ROLE.search(t))
            senty = sum(1 for t in titles
                        if re.match(r"(we|our|join|about|why|what|how|let)\b", t, re.I))
            oneword = sum(1 for t in titles if len(t.split()) < 2)   # department labels
            if junk > len(titles) // 3 or rolish < max(2, len(titles) // 3) \
                    or senty > len(titles) // 3 or oneword > len(titles) // 3:
                continue
            positions = [p for p, _ in items]
            for idx, (pos, t) in enumerate(items):
                nxt = positions[idx + 1] if idx + 1 < len(positions) else pos + 1600
                end = min(pos + 1600, nxt)          # never read the NEXT card's location
                ctx = re.sub(r"<[^>]+>", " ", page_html[pos:end])
                mloc = ISRAEL_LOC.search(ctx)
                loc = _loc_from_ctx(ctx[max(0, mloc.start() - 40):mloc.end() + 40]) if mloc else ""
                if not loc and not url_is_il:
                    continue
                mhref = re.search(r'href=["\']([^"\']+)["\']',
                                  page_html[max(0, pos - 600):pos + 1600])
                add(t, loc or "Israel", mhref.group(1) if mhref else "")

    # 4) position-links fallback (SuperPlay-style custom skins over an ATS): the listing
    # page is just N links sharing a /careers-position/-like path prefix; each target page
    # is server-rendered with title + location. Fetch them plainly and read the pages.
    if not jobs and page_html:
        from urllib.parse import urljoin as _uj
        import urllib.request as _ur
        prefixes = {}
        for m in re.finditer(r'href=["\']([^"\']+)["\']', page_html):
            u2 = _uj(url, m.group(1))
            pref = re.sub(r"[^/]+/?$", "", u2)
            if re.search(r"(job|position|opening|vacanc|career|role)[^/]*/$", pref, re.I):
                prefixes.setdefault(pref, set()).add(u2)
        for pref, links in sorted(prefixes.items(), key=lambda kv: -len(kv[1])):
            if len(links) < 3:
                continue
            for u2 in sorted(links)[:25]:
                try:
                    req = _ur.Request(u2, headers={"User-Agent": "Mozilla/5.0"})
                    ph = _ur.urlopen(req, timeout=12).read(400_000).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                mt = (re.search(r"<h1[^>]*>\s*([^<]{3,90})\s*</h1>", ph, re.S)
                      or re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']{3,90})', ph))
                if not mt:
                    continue
                txt = re.sub(r"<[^>]+>", " ", ph)
                mloc = ISRAEL_LOC.search(txt)
                loc = _loc_from_ctx(txt[max(0, mloc.start() - 40):mloc.end() + 40]) if mloc else ""
                add(mt.group(1).strip(), loc, u2,
                    desc=re.sub(r"\s+", " ", txt)[:4000])
            if jobs:
                break

    # 5) LLM extraction fallback (env SCRAPE_LLM=1): Elementor/Wix/arbitrary layouts where
    # nothing above matches but the page clearly lists positions — Claude reads the rendered
    # text and returns JSON. Gated on jobs-signals so it never fires on marketing pages.
    if not jobs and page_html and os.environ.get("SCRAPE_LLM"):
        stripped = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ",
                          page_html, flags=re.S | re.I)
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "\n", stripped))
        sig = re.search(r"open positions|current openings|apply now|we'?re hiring|משרות", txt, re.I)
        if sig:
            # center the excerpt on the jobs section, not the page top
            txt = txt[max(0, sig.start() - 1500):sig.start() + 8000]
            import shutil as _sh
            import subprocess as _sp
            import json as _json
            if _sh.which("claude"):
                prompt = (
                    "Below is the visible text of a company careers page. Extract the OPEN "
                    "POSITIONS as a JSON array [{\"title\": ..., \"location\": ...}] — titles "
                    "exactly as written, location as written or \"\" if absent. Exclude "
                    "benefits/values/testimonials. Respond ONLY the JSON array (or []).\n\n"
                    + txt[:7000])
                try:
                    proc = _sp.run(["claude", "-p"], input=prompt, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=120, shell=(os.name == "nt"))
                    m = re.search(r"\[.*\]", proc.stdout or "", re.S)
                    for o in (_json.loads(m.group(0)) if m else []):
                        t, loc = str(o.get("title", "")).strip(), str(o.get("location", "")).strip()
                        if not loc and (url_is_il if 'url_is_il' in dir() else False):
                            loc = "Israel"
                        if not loc and os.environ.get("SCRAPE_ASSUME_IL") \
                                and ISRAEL_LOC.search(page_html):
                            loc = "Israel"
                        add(t, loc, url)
                except Exception:  # noqa: BLE001
                    pass
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
