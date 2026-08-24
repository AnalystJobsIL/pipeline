#!/usr/bin/env python3
"""Universal careers scraper: render a listings page, then harvest job objects from EVERY place
a modern site might keep them.

Two halves, deliberately separable (`docs/sessions/2026-08-24-scraper.md`):

  RENDER  `_render(url)` — the only function that touches Playwright. Returns a `Rendered`
          bundle: embedded page state, captured XHR/fetch bodies, the rendered link list, the
          HTML, the main document's HTTP status, and an error code if navigation failed.
  PARSE   `_extract(company, url, rendered)` — a pure function of that bundle (plus env), so it
          can be tested offline and diffed against captured payloads. Five strategies, each only
          when the previous found nothing (one exception: fewer than 3 structured hits also
          run the DOM pass, unioned):
            1 structured JSON (JSON-LD JobPosting, __NEXT_DATA__/Apollo/Redux state, XHR bodies)
            2 rendered-DOM job links with an Israel token near the title
            3 repeated heading / class-hinted card groups in the HTML
            4 position links: N same-prefix links, each target page fetched and read
            5 LLM extraction (`SCRAPE_LLM=1`): Claude reads the visible text, returns JSON

Public surface other lanes import — signatures and meaning are frozen:
  `scrape(company, url, timeout_ms=45000) -> list[dict]`   NEVER raises; [] on any failure.
  `scrape_result(company, url, ...) -> ScrapeResult`        the same, plus whether [] means
                                                           "no roles" (`empty`) or "could not
                                                           read the page" (`error`).
  `ISRAEL_LOC`, `ROLE`, `BAD_TITLE`, `_find`, `_loc_from_ctx`.

Every job dict has the common shape in ARCHITECTURE.md §0. `country_code` is deliberately ""
so `pipeline.israel` re-checks the location text instead of trusting the scraper's guess.
"""
from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------------------------
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
_DESC_KEYS = {"description", "jobdescription", "summary"}
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


def _build_israel_loc():
    """Derived from pipeline.israel, BOTH lists — never hand-maintained here.

    The Hebrew names used to be a short hard-coded list in this file while
    `pipeline.israel` had none, so the scraper would recognise "תל אביב" on a page, stamp it
    as the role's location, and the Israel filter would then drop the role it had just
    found. check_invariants check G fails if these drift apart again.
    """
    from pipeline.israel import _IL_PLACES, _IL_PLACES_HE
    alts = sorted((re.escape(p).replace(r"\ ", r"[\s-]?")
                   for p in _IL_PLACES + _IL_PLACES_HE), key=len, reverse=True)
    return re.compile("|".join(alts), re.I)


ISRAEL_LOC = _build_israel_loc()

# a posting link says so in its path
_POSTING_HREF = re.compile(r"/(job|jobs|position|opening|vacancy|role)s?[/\-_=?]|gh_jid=|/apply\b", re.I)
# strategy 3: job cards as N same-class siblings
_CARD_PATTERNS = (
    r"<(h[1-4])([^>]*)>([^<]{5,90})</\1>",
    # non-heading job cards: any tag whose class names it a job/position title
    # (e.g. Legit Security's <p class="job-post-title">)
    r'<(p|div|span|a)([^>]*class=["\'][^"\']*(?:job|position|role|opening)[^"\']*'
    r'(?:title|name|copy)[^"\']*["\'][^>]*)>([^<]{5,90})</\1>',
)
_CARD_SENTENCE = re.compile(r"(we|our|join|about|why|what|how|let)\b", re.I)
# strategy 4: a link prefix that names positions
_LINK_PREFIX = re.compile(r"(job|position|opening|vacanc|career|role)[^/]*/$", re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']')
# strategy 5 fires only on a page that announces openings — never on a marketing page
_JOBS_SIGNAL = re.compile(r"open positions|current openings|apply now|we'?re hiring|משרות", re.I)
# a posting date written on the card: "Posted 3 days ago", "Published: 2026-08-20", "2 weeks ago"
_CARD_DATE = re.compile(r"\b(?:posted|published|date posted|posting date)\b[:\s]{0,3}[^|•·<]{0,24}?"
                        r"(\d{4}-\d{2}-\d{2}|\d+\+?\s*(?:day|week|month)s?\s*ago|today|yesterday|"
                        r"just (?:posted|now))", re.I)
# a card ends where its call-to-action starts; text after that belongs to the next card
_CARD_END = re.compile(r"\b(?:apply(?: now)?|view (?:job|details|more)|read more|learn more|see details)\b", re.I)
_LLM_PROMPT = (
    "Below is the visible text of a company careers page. Extract the OPEN "
    "POSITIONS as a JSON array [{\"title\": ..., \"location\": ...}] — titles "
    "exactly as written, location as written or \"\" if absent. Exclude "
    "benefits/values/testimonials. Respond ONLY the JSON array (or []).\n\n")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_UA_PLAIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"

# per-page work caps (strategy 4 fetches each position page plainly)
_LINK_PAGES_PER_PREFIX = 25
_LINK_PAGE_TIMEOUT_S = 8
_PLAIN_TIMEOUT_S = 15
_LLM_TIMEOUT_S = 120
_UNLOCK_TIMEOUT_S = 90
# one company may not hold the nightly refresh hostage: Ford once took 368 s (a 45 s goto,
# 12 s network-idle, then 25 position pages at 12 s each). Every network wait below is
# clamped to what is left of this budget.
COMPANY_BUDGET_S = int(os.environ.get("SCRAPE_COMPANY_BUDGET_S", "150"))

_STATE_JS = r"""() => {
  const blobs = [];
  const push = (v) => { try { blobs.push(JSON.stringify(v)); } catch (e) {} };
  const names = ['__NEXT_DATA__','__APOLLO_STATE__','__APOLLO_CLIENT__','__INITIAL_STATE__',
    '__PRELOADED_STATE__','__REDUX_STATE__','__NUXT__','__data','__remixContext','_sharedData'];
  names.forEach(n => { const v = window[n]; if (v && typeof v === 'object') push(v); });
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


# ---------------------------------------------------------------------------------------------
# small parsers shared by the strategies
# ---------------------------------------------------------------------------------------------
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
    name = o.get("name") if isinstance(o.get("name"), str) else ""
    if name and not ROLE.search(name) and any(
            isinstance(o.get(k), str) and ROLE.search(o[k]) for k in ("role", "title", "position")):
        return ""                                   # a person with a job title, not a job
    for k, v in o.items():
        if k.lower() in TITLE_KEYS and isinstance(v, str):
            t = v.strip()
            if (4 <= len(t) <= 90 and not BAD_TITLE.match(t) and not t.startswith("http")
                    and ROLE.search(t) and not TITLE_JUNK.search(t)):  # a real job title
                return t
    return ""


def _find(node, out, depth=0):
    """Recursively collect arrays of objects that carry a title-like field (plus a location,
    url or id field) — the one heuristic that reads Next.js state, GraphQL bodies and JSON-LD."""
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


_REL_W = re.compile(r"(\d+)\+?\s*week", re.I)


def _date_from_card(text):
    """The posting date written on a card, as ISO, or ''. Reads only the text handed in —
    the caller bounds it to the card, so a page footer's date can never become a role's."""
    text = text or ""
    cut = _CARD_END.search(text)
    if cut:
        text = text[:cut.end()]              # never read past this card's Apply button
    m = _CARD_DATE.search(text)
    if not m:
        return ""
    raw = m.group(1)
    w = _REL_W.search(raw)
    if w:
        return (_dt.date.today() - _dt.timedelta(days=7 * int(w.group(1)))).isoformat()
    return _norm_date(raw)


# Words that sit next to a location on a careers card without being part of it. The
# window fallback below takes 12 characters either side of the match, so a card reading
# "Data Analyst  Apply  Tel Aviv" produced the location "Apply       Tel Av".
_LOC_CHROME = re.compile(
    "(?<![a-z])(apply now|apply|view|read more|learn more|full[- ]time|part[- ]time|"
    "hybrid|on-?site|posted|share)(?![a-z])", re.I)


def _clean_loc(t):
    t = _LOC_CHROME.sub(" ", t or "").replace("\xa0", " ")
    return " ".join(t.split()).strip(" ,;|-()[]·–—") or "Israel"


def _loc_from_ctx(ctx):
    m = re.search(r"([A-Za-z][\w.\-' ]{1,28},?\s*Israel)", ctx)
    if m:
        return _clean_loc(m.group(1))
    m = ISRAEL_LOC.search(ctx)
    if not m:
        return "Israel"
    # Start AT the place name, not 12 characters before it. What precedes a location on
    # a card is the title or a button, and the old fixed window dragged it in mid-word:
    # "Applied Scientist Haifa" became the location "d Scientist Haifa". Every
    # multi-word Israeli place we know is in _IL_PLACES, so the match already spans it.
    hi = m.end() + 8
    if hi < len(ctx) and ctx[hi - 1].isalnum() and ctx[hi].isalnum():
        sp = ctx.rfind(" ", m.end(), hi)          # ...and never end mid-word either
        hi = sp if sp > m.end() else m.end()
    return _clean_loc(ctx[m.start():hi])


# ---------------------------------------------------------------------------------------------
# the bundles
# ---------------------------------------------------------------------------------------------
@dataclass
class Deadline:
    """Wall-clock budget for one company. `remaining()` clamps every network wait."""
    t_end: float

    @classmethod
    def start(cls, seconds):
        return cls(time.monotonic() + max(1, seconds))

    def remaining(self):
        return max(0.0, self.t_end - time.monotonic())

    def expired(self):
        return self.remaining() <= 0


@dataclass
class Rendered:
    """Everything the parse needs, captured from one browser visit (plus lazy plain fetches)."""
    url: str
    blobs: list = field(default_factory=list)      # embedded page state, JSON-LD
    bodies: list = field(default_factory=list)     # XHR/fetch/document JSON bodies
    dom: list = field(default_factory=list)        # rendered a[href] with surrounding text
    page_html: str = ""
    http_status: int | None = None                 # the main document's status
    error: str = ""                                # "" | launch:<Exc> | goto:<Exc> | render:<Exc>
    plain_html: str = ""                           # filled by _extract when strategies 1-2 miss
    plain_status: int | None = None
    unlocker_ok: bool | None = None
    elapsed_s: float = 0.0
    truncated: bool = False                        # a strategy stopped early on the deadline


@dataclass
class ScrapeResult:
    """`jobs` plus whether an empty list means "no roles" or "could not read the page"."""
    jobs: list
    status: str                # "ok" | "empty" | "error"
    error: str = ""            # machine code, e.g. "goto:TimeoutError", "http:403"
    http_status: int | None = None
    strategy: str = ""         # first strategy that produced jobs
    elapsed_s: float = 0.0
    rescued: bool = False      # jobs came from plain/unlocker HTML after a failed render


# ---------------------------------------------------------------------------------------------
# RENDER — the only Playwright touchpoint
# ---------------------------------------------------------------------------------------------
def _render(url, timeout_ms=45000, deadline=None):
    """Visit the page headlessly and bundle what it exposed. Never raises: a navigation or
    launch failure is recorded in `Rendered.error` so the caller can tell it from an empty
    board (until 2026-08-24 both came back as an empty list, and the nightly refresh recorded
    0 errors across 428 sites — every 403 and timeout scored as "no roles")."""
    t0 = time.monotonic()
    r = Rendered(url=url)
    fast = os.environ.get("FAST_SCRAPE")
    goto_ms = timeout_ms if deadline is None else min(timeout_ms, int(deadline.remaining() * 1000))

    def on_resp(resp):
        if resp.request.resource_type in ("xhr", "fetch", "document"):
            try:
                t = resp.text()
                if 120 < len(t) < 4_000_000 and (t.lstrip()[:1] in "{[" or "JobPosting" in t):
                    r.bodies.append(t)
            except Exception:  # noqa: BLE001
                pass

    b = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                # stealth: several real careers pages (Entro, Legit) serve a stripped page to
                # detectable headless automation — mask the fingerprint
                b = p.chromium.launch(headless=True,
                                      args=["--disable-blink-features=AutomationControlled"])
                pg = b.new_page(user_agent=_UA)
                pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                pg.on("response", on_resp)
            except Exception as e:  # noqa: BLE001
                r.error = f"launch:{type(e).__name__}"
                return r
            try:
                resp = pg.goto(url, wait_until="domcontentloaded", timeout=max(1000, goto_ms))
                r.http_status = resp.status if resp is not None else None
            except Exception as e:  # noqa: BLE001
                r.error = f"goto:{type(e).__name__}"
                return r
            try:
                try:
                    pg.wait_for_load_state("networkidle", timeout=6000 if fast else 12000)
                except Exception:  # noqa: BLE001
                    pass
                for _ in range(2 if fast else 3):
                    pg.mouse.wheel(0, 3000)
                    pg.wait_for_timeout(1000 if fast else 1800)
                r.blobs = pg.evaluate(_STATE_JS)
                r.dom = pg.evaluate(_DOM_JS)
                r.page_html = pg.content()
            except Exception as e:  # noqa: BLE001
                r.error = f"render:{type(e).__name__}"
    except Exception as e:  # noqa: BLE001 — playwright missing, driver died
        r.error = r.error or f"launch:{type(e).__name__}"
    finally:
        try:
            if b is not None:
                b.close()
        except Exception:  # noqa: BLE001
            pass
        r.elapsed_s = time.monotonic() - t0
    return r


def _fetch_url(url, timeout_s, ua=_UA_PLAIN, limit=1_500_000):
    """Plain GET → (html, status). html is None when the request itself failed."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read(limit).decode("utf-8", "replace"), getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:  # noqa: BLE001
        return None, None


def _fetch_unlocked_html(url, timeout_s):
    """Bright Data residential unlocker (`SCRAPE_VIA_UNLOCKER=1`); '' on failure or when off."""
    if not os.environ.get("SCRAPE_VIA_UNLOCKER"):
        return ""
    try:
        from bd_rescue import unlock, _load_secrets
        _load_secrets()
        return unlock(url, timeout=int(timeout_s)) or ""
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------------------------
# PARSE — pure functions of a Rendered bundle
# ---------------------------------------------------------------------------------------------
def _structured_objects(blobs, bodies):
    raw = []
    for txt in blobs + bodies:
        if not isinstance(txt, str):          # Playwright marshals `undefined` as None
            continue
        try:
            _find(json.loads(txt), raw)
        except Exception:  # noqa: BLE001
            for m in re.finditer(r"\{[^{}]{0,4000}\}", txt):   # last-ditch: scan embedded objects
                try:
                    o = json.loads(m.group(0))
                    if _title_of(o):
                        raw.append(o)
                except Exception:  # noqa: BLE001
                    pass
    return raw


def _make_adder(company, url):
    """The one write path. Returns (add, jobs): `add` applies the title/location filters and
    the dedupe key, appends the common job shape to `jobs`, and returns True when it did."""
    seen, jobs = set(), []

    def add(title, loc, url_, date="", desc="", jid=""):
        title = (title or "").strip()
        # drop run-together card blobs (breadcrumb/location/sentence leaked into the title)
        if not title or len(title) > 90 or TITLE_JUNK.search(title) or BAD_TITLE.match(title):
            return False
        if not ISRAEL_LOC.search(loc or ""):
            return False
        if url_ and url_.startswith("/"):
            url_ = urllib.parse.urljoin(url, url_)
        key = (title.lower(), (loc or "").lower())
        if key in seen:
            return False
        seen.add(key)
        jobs.append({"company": company, "title": title[:90], "location": loc,
                     # NOT "IL": israel.is_israel_job treats a country_code as
                     # authoritative and skips its text check, so hardcoding it made
                     # the scraper rubber-stamp its own guess (Wiliot shipped 8 jobs
                     # in Kyiv/Dallas/Portugal as Israeli). "" forces the real check.
                     "country_code": "",
                     "url": url_ or url, "posted_date": _norm_date(date), "ats_platform": "scrape",
                     "job_id": (jid or (url_ if url_ and url_ != url else "")
                                or _hashlib.sha1(f"{company}|{title}|{loc}".encode("utf-8")
                                                 ).hexdigest()[:16]), "description": (desc or "")[:6000]})
        return True
    return add, jobs


def _from_structured(raw, add):
    """1) structured JSON (state / XHR / JSON-LD)."""
    for o in raw:
        add(_title_of(o), _get(o, LOC_KEYS), _get(o, URL_KEYS), _get(o, DATE_KEYS),
            _get(o, _DESC_KEYS), _get(o, ID_KEYS))


def _from_dom(dom, add):
    """2) rendered DOM job-card links: a role-like title, a posting-like href, an Israel token
    within 220 chars of the title (or in the title itself)."""
    for d in dom:
        t = d.get("title", "")
        u2 = d.get("url", "")
        ctx = d.get("ctx", "")
        m = ISRAEL_LOC.search(ctx)
        near = bool(m and (t in ctx) and abs(ctx.find(t) - m.start()) < 220)
        if (ROLE.search(t) and not BAD_TITLE.match(t) and _POSTING_HREF.search(u2)
                and (near or ISRAEL_LOC.search(t))):
            # no date from here: `ctx` is four ancestors' text run together, so a "Posted …"
            # in it belongs to whichever card is nearest, not provably to this one
            add(t, _loc_from_ctx(ctx), u2)


def _page_is_il(url, page_html):
    """Is a card with no location of its own implicitly Israeli? Yes when the LISTING URL is
    already Israel-filtered (…?location=Israel). `SCRAPE_ASSUME_IL=1` (set by listing_hunt,
    crack_walled, repair_extract_gap for pre-vetted Israeli companies) widens that to a
    page-level Israel signal — which is why `pipeline.company_identity.
    looks_like_a_job_listing_page` gates activation: under that flag a nav menu with an Israeli
    footer scores like a board. This function must never widen further."""
    if ISRAEL_LOC.search(url):
        return True
    return bool(os.environ.get("SCRAPE_ASSUME_IL") and ISRAEL_LOC.search(page_html or ""))


def _from_cards(page_html, url_is_il, add):
    """3) repeated heading-group fallback (Radancy/Google-style server-rendered listings):
    job cards as N same-class <h2>/<h3> siblings. A card with no location is kept only when
    the page itself is Israel-scoped (`url_is_il`)."""
    groups = {}
    for pat in _CARD_PATTERNS:
        for m in re.finditer(pat, page_html, re.I):
            tag, attrs, text = m.group(1).lower(), m.group(2), m.group(3).strip()
            cm = re.search(r'class=["\']([^"\']+)', attrs) if "class=" in attrs else None
            cls = cm.group(1) if cm else ""
            groups.setdefault((tag, cls), []).append((m.start(), text))
    for (tag, cls), items in groups.items():
        if len(items) < 3:
            continue
        titles = [t for _, t in items]
        junk = sum(1 for t in titles if BAD_TITLE.match(t) or not re.search(r"[a-zא-ת]", t, re.I))
        rolish = sum(1 for t in titles if ROLE.search(t))
        senty = sum(1 for t in titles if _CARD_SENTENCE.match(t))
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
            mhref = _HREF.search(page_html[max(0, pos - 600):pos + 1600])
            add(t, loc or "Israel", mhref.group(1) if mhref else "", date=_date_from_card(ctx[:400]))


def _from_position_links(page_html, url, add, fetch=_fetch_url, deadline=None,
                         pages_per_prefix=None, page_timeout_s=None):
    """4) position-links fallback (SuperPlay-style custom skins over an ATS): the listing page
    is just N links sharing a /careers-position/-like prefix; each target page is
    server-rendered with title + location. Fetch them plainly and read the pages."""
    pages_per_prefix = pages_per_prefix or _LINK_PAGES_PER_PREFIX
    page_timeout_s = page_timeout_s or _LINK_PAGE_TIMEOUT_S
    prefixes = {}
    for m in _HREF.finditer(page_html):
        u2 = urllib.parse.urljoin(url, m.group(1))
        pref = re.sub(r"[^/]+/?$", "", u2)
        if _LINK_PREFIX.search(pref):
            prefixes.setdefault(pref, set()).add(u2)
    found_any = False
    for pref, links in sorted(prefixes.items(), key=lambda kv: -len(kv[1])):
        if len(links) < 3:
            continue
        for u2 in sorted(links)[:pages_per_prefix]:
            if deadline is not None and deadline.expired():
                return True                        # truncated: the caller must not trust the count
            tmo = page_timeout_s if deadline is None else min(page_timeout_s, deadline.remaining())
            ph, _st = fetch(u2, tmo)
            if not ph:
                continue
            mt = (re.search(r"<h1[^>]*>\s*([^<]{3,90})\s*</h1>", ph, re.S)
                  or re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']{3,90})', ph))
            if not mt:
                continue
            txt = re.sub(r"<[^>]+>", " ", ph)
            mloc = ISRAEL_LOC.search(txt)
            loc = _loc_from_ctx(txt[max(0, mloc.start() - 40):mloc.end() + 40]) if mloc else ""
            if add(mt.group(1).strip(), loc, u2, desc=re.sub(r"\s+", " ", txt)[:4000]):
                found_any = True
        if found_any:
            break
    return False


def _run_claude(prompt, timeout_s):
    """Default LLM runner: `claude -p` on the subscription token. '' when the CLI is absent."""
    if not shutil.which("claude"):
        return ""
    proc = subprocess.run(["claude", "-p"], input=prompt, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout_s, shell=(os.name == "nt"))
    return proc.stdout or ""


def _from_llm(page_html, url, url_is_il, add, runner=None, deadline=None):
    """5) LLM extraction (`SCRAPE_LLM=1`): Elementor/Wix/arbitrary layouts where nothing above
    matches but the page clearly lists positions. Gated on jobs-signals so it never fires on
    marketing pages."""
    if not os.environ.get("SCRAPE_LLM"):
        return
    stripped = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ",
                      page_html, flags=re.S | re.I)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "\n", stripped))
    sig = _JOBS_SIGNAL.search(txt)
    if not sig:
        return
    # center the excerpt on the jobs section, not the page top
    txt = txt[max(0, sig.start() - 1500):sig.start() + 8000]
    tmo = _LLM_TIMEOUT_S if deadline is None else min(_LLM_TIMEOUT_S, deadline.remaining())
    if deadline is not None and tmo < 30:
        return
    try:
        out = (runner or _run_claude)(_LLM_PROMPT + txt[:7000], tmo)
        m = re.search(r"\[.*\]", out or "", re.S)
        for o in (json.loads(m.group(0)) if m else []):
            t, loc = str(o.get("title", "")).strip(), str(o.get("location", "")).strip()
            if not loc and url_is_il:
                loc = "Israel"
            add(t, loc, url)
    except Exception:  # noqa: BLE001
        pass


def _extract(company, url, r: Rendered, deadline=None, fetch=_fetch_url, llm=None):
    """Run the five strategies over a Rendered bundle. Pure apart from `fetch`/`llm` (which are
    injectable) and the SCRAPE_* env flags. Returns (jobs, winning_strategy)."""
    add, jobs = _make_adder(company, url)
    _from_structured(_structured_objects(r.blobs, r.bodies), add)
    if len(jobs) >= 3:
        return jobs, "structured"
    # one or two structured hits may be a "featured posting" widget beside a DOM-rendered
    # board: let the DOM pass add to them. Three or more is the board itself, and the DOM
    # pass would only add run-together duplicates (Port.io: 16 of them).
    n_structured = len(jobs)
    _from_dom(r.dom, add)
    if jobs:
        return jobs, ("structured+dom" if n_structured and len(jobs) > n_structured
                      else "structured" if n_structured else "dom")
    # headless Chromium sometimes gets a bot-stripped page while plain HTTP gets the real
    # server-rendered cards (Legit Security) — try both HTML sources
    if deadline is None or deadline.remaining() >= 3:
        tmo = _PLAIN_TIMEOUT_S if deadline is None else min(_PLAIN_TIMEOUT_S, deadline.remaining())
        r.plain_html, r.plain_status = fetch(url, tmo)
        r.plain_html = r.plain_html or ""
    if not r.plain_html and (deadline is None or deadline.remaining() >= 10):
        # 403/anti-bot: residential unlocker gets the HTML the LLM tier then parses
        tmo = _UNLOCK_TIMEOUT_S if deadline is None else min(_UNLOCK_TIMEOUT_S, deadline.remaining())
        r.plain_html = _fetch_unlocked_html(url, tmo)
        r.unlocker_ok = bool(r.plain_html) if os.environ.get("SCRAPE_VIA_UNLOCKER") else None
    page_html = r.page_html
    if len(r.plain_html) > len(page_html or ""):
        page_html = r.plain_html if not page_html else page_html + "\n" + r.plain_html
    if not page_html:
        return jobs, ""
    url_is_il = _page_is_il(url, page_html)
    _from_cards(page_html, url_is_il, add)
    if jobs:
        return jobs, "cards"
    if _from_position_links(page_html, url, add, fetch=fetch, deadline=deadline):
        r.truncated = True
        if jobs:                                   # a partial list: flagged like a failed render
            r.error = r.error or "deadline:links"
    if jobs:
        return jobs, "links"
    _from_llm(page_html, url, url_is_il, add, runner=llm, deadline=deadline)
    return jobs, ("llm" if jobs else "")


# An HTTP 200 that is really a wall. Akamai answers "Access Denied" with a 200 (Nokia's and
# Akamai's own careers pages, captured 2026-08-24); Cloudflare/PerimeterX/Incapsula/DataDome
# serve a challenge page. None of them is "this company has no openings".
_BLOCK_MARKERS = re.compile(
    r"<title>\s*Access Denied\s*</title>|<h1>\s*Access Denied\s*</h1>|errors\.edgesuite\.net|"
    r"cf-browser-verification|<title>[^<]{0,40}Just a moment|<title>[^<]{0,40}Attention Required|"
    r"<title>[^<]{0,40}Pardon Our Interruption|px-captcha|Request unsuccessful\. Incapsula|"
    r"captcha-delivery\.com|<title>[^<]{0,40}Access to this page has been denied", re.I)
# NOT a marker: Cloudflare's `/cdn-cgi/challenge-platform/scripts/jsd/main.js` is injected into
# ordinary 200 pages when JS detections are on; `_Incapsula_Resource` likewise (wave 2)


_BLOCK_VENDOR = (("access denied", "access-denied"), ("edgesuite", "access-denied"),
                 ("cf-", "cloudflare"), ("challenge-platform", "cloudflare"),
                 ("just a moment", "cloudflare"), ("attention required", "cloudflare"),
                 ("px-captcha", "perimeterx"), ("access to this page", "perimeterx"),
                 ("incapsula", "incapsula"), ("captcha-delivery", "datadome"),
                 ("pardon our", "distil"))


def _blocked_by(html):
    """'' or the wall vendor ('access-denied', 'cloudflare', ...) a 200 page is really from."""
    m = _BLOCK_MARKERS.search(html or "")
    if not m:
        return ""
    hit = m.group(0).lower()
    return next((v for k, v in _BLOCK_VENDOR if k in hit), "wall")


def _readable(html):
    """Plain HTML that is a real page (long enough) and not a wall."""
    return len(html or "") >= 2000 and not _blocked_by(html)


def _classify(r: Rendered, jobs):
    """(status, error) for a finished bundle — see the table in ARCHITECTURE.md §5a."""
    if jobs:
        return "ok", r.error
    if r.error.startswith("launch:"):
        return "error", r.error
    if r.error or (r.http_status is not None and r.http_status >= 400):
        code = r.error or f"http:{r.http_status}"
        # the render failed but the un-rendered server answered 200 with a real page: the page
        # is reachable and (as far as plain HTML can tell) has no roles. A JS shell that needs
        # the failed browser is still possible; documented as the one judgement call.
        if r.plain_status == 200 and _readable(r.plain_html) and not r.unlocker_ok:
            return "empty", code
        return "error", code
    wall = _blocked_by(r.page_html)
    if wall and not (r.plain_status == 200 and _readable(r.plain_html)):
        return "error", f"block:{wall}"
    if not (r.page_html or r.blobs or r.bodies or r.dom or r.plain_html):
        return "error", "render:blank"          # a 200 with nothing in it is not a page we read
    return "empty", ""


# ---------------------------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------------------------
def scrape_result(company, url, timeout_ms=45000, *, budget_s=None, render=None, fetch=None,
                  llm=None):
    """Render + parse one listings page. Never raises. `status` says what an empty `jobs`
    means: "empty" (the page answered, no Israel roles) or "error" (could not read it)."""
    t0 = time.monotonic()
    deadline = Deadline.start(COMPANY_BUDGET_S if budget_s is None else budget_s)
    try:
        r = (render or _render)(url, timeout_ms, deadline)
        jobs, strategy = _extract(company, url, r, deadline=deadline,
                                  fetch=fetch or _fetch_url, llm=llm)
        status, error = _classify(r, jobs)
        rescued = bool(jobs) and (r.error != "" or (r.http_status or 0) >= 400)
        return ScrapeResult(jobs=jobs, status=status, error=error, http_status=r.http_status,
                            strategy=strategy, elapsed_s=time.monotonic() - t0, rescued=rescued)
    except Exception as e:  # noqa: BLE001 — belt and braces: this function must not raise
        return ScrapeResult(jobs=[], status="error", error=f"internal:{type(e).__name__}",
                            elapsed_s=time.monotonic() - t0)


def scrape(company, url, timeout_ms=45000):
    """The list-only contract every lane calls. Never raises; [] on any failure — callers that
    need to tell an error from an empty board use `scrape_result`."""
    try:
        return scrape_result(company, url, timeout_ms).jobs
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    from pipeline import israel
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
        res = scrape_result(name, url)
        il = sum(1 for j in res.jobs if israel.is_israel_job(j))
        print(f"{name:16} jobs={len(res.jobs):4} israel={il} status={res.status} "
              f"{res.error} http={res.http_status} via={res.strategy or '-'} {res.elapsed_s:.0f}s")
        for j in [x for x in res.jobs if israel.is_israel_job(x)][:3]:
            print(f"     - {j['title'][:52]} | {j['location'][:30]} | {j['posted_date']}")
