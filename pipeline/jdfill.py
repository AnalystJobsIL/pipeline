"""The jd-text layer: a job description for every relevant role, whatever its age.

Six list endpoints carry no description at all — `workday` (62 active rows), `smartrecruiters`
(16), `bamboohr` (9), `microsoft` (1), `eightfold` (1) and `phenom` (1) (re-derived from
`companies.csv` 2026-08-26; the 08-24 docstring said workday 66 / bamboohr 11 and "eightfold
and phenom have 0 rows" — the registry lane converted Qualcomm and GE HealthCare on 08-25) —
so their roles used to reach the classifier as a bare title and the board with no requirements,
skills or tags. Scrape cards and discovery cards arrive without text as well.

Three callers, one ladder (`fetch_jd`):

    native JSON  ->  plain HTML  ->  Bright Data Web Unlocker (backfill scripts only)

* `JDFiller` fills a role INLINE, before classification, inside the digest — title-gated and
  wall-clock budgeted, never Bright Data.
* `enrich_scrape_jd.py` / `enrich_matched_jd.py` are ~60-line drivers around `run_backfill`,
  which walks a todo list with a time budget, a cooldown and the Unlocker as last resort, and
  records what it did in the `enrich` stage stamp (`record_enrich`) so the daily mail can say
  when this layer failed.

Every outcome has a REASON (`JD.reason`): a page that was read and carried no JD is stamped
for 7 days; a timeout, a 5xx or an unavailable Unlocker is `transient` and retried tomorrow —
before this, an exhausted Bright Data pool parked every relevant role for a week, silently.

The native rung matters most inline: to a plain GET the Workday job page is a 17 KB script
shell that yields 0 characters of text, and Bright Data refuses the host outright
(`policy_20140`, robots.txt) — so the JSON detail endpoint is the only rung that can ever fill
those roles. Measured 2026-08-24: 93 of 153 inline attempts succeeded before it existed.

Deliberately dependency-free (bare `urllib`, no retries, short timeouts): `pipeline/http.py`
retries 30 s x 3 on a miss, and 60 misses at that price would eat the inline budget.
"""
from __future__ import annotations

import datetime as dt
import html as _html_mod
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

MIN_DESC = 300              # below this a description is a stub, not a job description
_MIN_DESC = MIN_DESC        # legacy alias
DESC_MAX = 6000             # == fetchers._DESC_MAX and the store cap (pinned by a test)
RETRY_DAYS = 7              # a page that was read and carried no JD
TRANSIENT_RETRY_DAYS = 1    # a timeout, a 5xx, an unavailable Unlocker
TRANSIENT_MARK = " transient"
MASSFAIL_MIN_TRIED = 10     # rule 2 of CLAUDE.md, applied to this layer: N tried, 0 filled
FAILING_STREAK_FACTOR = 4   # breaker x this = a run that HAS worked but has stopped working
# outcomes that are nobody's failure: there is nothing at this address to fetch, and no
# rung we own could read it if there were
UNFILLABLE_REASONS = ("not-a-job-url", "auth-walled", "js-shell")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# A real JD names its sections; a JS-shell / cookie-wall / "no jobs found" page doesn't.
# Require two distinct markers so boilerplate like "innovative benefits" can't pass alone.
_JD_MARKERS = re.compile(
    r"(requirements?|responsibilit|qualifications?|experience|what you.?ll|"
    r"we.?re looking|about the (role|job|position)|skills|full[- ]time|"
    r"דרישות|אחריות|ניסיון|תיאור (ה)?משרה|כישורים)", re.I)


def load_secrets():
    """KEY=VALUE lines of the gitignored secrets.env into the environment (local runs only;
    in Actions the same names are repo secrets and the file is absent). Environment wins."""
    path = os.path.join(_REPO_ROOT, "secrets.env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# --------------------------------------------------------------------------- text
# Every `[^>]` run here is LENGTH-BOUNDED, for the same reason the ld+json scanner's is: on a
# body with no `>` to cap it, an unbounded run restarts at each `<` and scans to the end, which
# is quadratic. Bounding `jsonld_jd` alone closed one of two doors — measured on the same
# 980 KB input, `_from_body` still took 92 s and one inline role 187 s, because `extract_jd`
# reaches `html_to_text` first and `fetch_jd` runs it a second time for the shell/no-markers
# decision. `plain_fetch` reads up to 2 MB, so the original ~528 s was still reachable through
# this function. A real tag never approaches 4,000 characters; one that does is left in place
# rather than paid for.
# Bounds the attribute run of a BLOCK tag, the one regex here that still restarts at every
# `<script`. Measured on the 62 captured bodies: 645 block tags, longest run 617 chars
# (a `<header>`), 95th percentile 176 — so 1,000 leaves every real page untouched while
# costing 0.9 s on the 980 KB pathological body instead of 187 s. (300 costs 0.28 s but
# lets a long `<header>` leak its nav text into the extracted page text.)
_TAG_ATTRS = "{0,1000}?"


def _strip_tags(h):
    """Remove every `<...>` in ONE forward pass — exactly what `re.sub(r"<[^>]+>", " ", h)`
    did, without its cost.

    That regex restarts at each `<` and, on a body with no `>` to stop it, scans to the end
    from every one of them: the same quadratic shape as the ld+json scanner, and bounding it
    only trades the exponent for a large constant (4,000 was still 7 s on 980 KB). The two
    cases below are the regex's own semantics, kept deliberately: `<>` is NOT `<[^>]+>` and
    survives, and an unterminated `<` is left verbatim rather than swallowing the rest of the
    page — a stray `<` in prose ("salary < 100k") must not truncate a job description.
    Verified byte-identical to the regex on all 62 captured bodies.
    """
    out, i = [], 0
    while True:
        j = h.find("<", i)
        if j < 0:
            out.append(h[i:])
            return "".join(out)
        out.append(h[i:j])
        k = h.find(">", j + 1)
        if k < 0:
            out.append(h[j:])          # unterminated: the regex left it, so we leave it
            return "".join(out)
        if k == j + 1:
            out.append("<>")           # `<>` has no attribute run: not a tag by that rule
        else:
            out.append(" ")
        i = k + 1


def html_to_text(html):
    h = re.sub(r"<(script|style|noscript|svg|header|nav|footer)[^>]" + _TAG_ATTRS + r">.*?</\1>",
               " ", html, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", h, flags=re.I)
    h = _strip_tags(h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in h.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_jd(html):
    """Readable JD text; starts at the role section when the boilerplate marker is found."""
    from .seniority import _ROLE_START
    text = html_to_text(html)
    if len(text) < MIN_DESC or len(_marker_families(text)) < 2:
        return ""
    rs = _ROLE_START.search(text)
    if rs and len(text) - rs.start() >= MIN_DESC:
        text = text[rs.start():]
    return text[:DESC_MAX]


def _marker_families(text):
    """Distinct section markers, singular and plural folded ("requirement"/"requirements" is one)."""
    return {m[0].rstrip("s") for m in _JD_MARKERS.findall(text.lower())}


def _text_or_empty(html):
    """A native payload is trusted for what it is, but still has to be a description.

    The surrogate scrub is not decoration: `json.loads` accepts an unpaired high surrogate and
    keeps it in the str, and every `ensure_ascii=False` writer in this repo — the role ledger,
    `pipeline.atomic.write_json`, `persist_state` — then raises `UnicodeEncodeError` in the
    PERSISTENCE step, after the run's LLM verdicts have already been paid for."""
    text = html_to_text(html or "")
    text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    return text[:DESC_MAX] if len(text) >= MIN_DESC else ""


# A page that declares `{"@type": "JobPosting", "description": ...}` in an ld+json script is
# SELF-LABELLING: it says the text is a job description, so unlike a raw page it needs no
# marker heuristic — it is trusted like a native payload, through `_text_or_empty`.
#
# This is a second PARSER, not a rung: it reads the body `plain_fetch` already returned, and
# the body Bright Data has already been charged for. Measured 2026-08-26: it rescues the
# `no-markers` class (1 of 27 sampled LinkedIn pages carried its JD only here — Mobileye,
# 9,833 characters of page text with a single marker family), and two of the three credits
# this lane spent that day ended in `bd-no-markers`.
#
# A body is arbitrary bytes from the internet, and wave 1 turned every one of these bounds
# into a measured number rather than a hope:
#   * the attribute runs are LENGTH-BOUNDED. `<script[^>]*type=...` restarts at every literal
#     `<script`, and each start lets `[^>]*` run to the end of the `>`-free region before
#     failing: `"<script" * 140_000` (980 KB, inside the scan budget) took **528 seconds**,
#     and an ordinary 34 KB page of `<script type="application/ld+json"` prefixes took 4.5 s.
#     Well-formed pages were never affected (800 KB of `<script>` = 6 ms) — the cost is
#     unbounded only where no `>` caps the run.
#   * `RecursionError` is caught. CPython's JSON scanner raises it (a RuntimeError, NOT a
#     ValueError) on deeply nested arrays, and 2 KB of `[[[[...` was enough. `maybe_fill` has
#     no try/except and runs inside the digest step, so that body meant no board, no email.
#   * the scan window and the per-block size are the real bounds; the block COUNT is a
#     backstop only. It counts matched blocks rather than useful ones, so a low cap hid a real
#     posting behind decoy `WebPage` blocks while protecting nothing: 500 blocks cost 0.24 ms,
#     and at most ~5 blocks of the 200 KB maximum fit inside the 1 MB window anyway.
LD_SCAN_BYTES = 1_000_000
LD_MAX_BLOCKS = 200
LD_MAX_BLOCK = 200_000
_LD_SCRIPT = re.compile(
    r"<script[^>]{0,300}?type\s*=\s*[\"']?application/ld\+json[\"']?[^>]{0,300}?>(.*?)</script>",
    re.S | re.I)


def _ld_nodes(data):
    """Every candidate node: the value itself, a top-level array, and one level of @graph.
    Deliberately not a full recursive walk — a JobPosting nested arbitrarily deep inside
    another entity (a "similar jobs" widget hanging off `WebPage.mainEntity`) is not this
    page's own posting."""
    for node in (data if isinstance(data, list) else [data]):
        if not isinstance(node, dict):
            continue
        yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for g in graph:
                if isinstance(g, dict):
                    yield g


def _is_jobposting(t):
    """`@type` may be a list, and may be written as a full IRI or a prefixed name:
    `JobPosting`, `["JobPosting","Thing"]`, `http://schema.org/JobPosting`, `schema:JobPosting`."""
    for x in (t if isinstance(t, list) else [t]):
        if str(x or "").rsplit("/", 1)[-1].rsplit(":", 1)[-1].strip().lower() == "jobposting":
            return True
    return False


def jsonld_jd(body):
    """The page's own `JobPosting.description`, or "".

    Reads the RAW body: `html_to_text` strips `<script>` first, so piping this through it
    would silently return "" for ever (pinned by a test). Only `JobPosting` nodes are read —
    never `Organization` or `WebPage`, whose `description` is the company blurb.

    Takes the FIRST JobPosting that renders to a real description, not the longest.
    schema.org convention puts the page's own entity first, and "longest wins" handed the
    board another job's text whenever a page carried a similar-jobs rail — with this row's
    title, company and apply link still attached.

    The description is HTML *inside* JSON, so it arrives DOUBLE-escaped and must be unescaped
    before the text pass: all 23 real ld+json descriptions in the 2026-08-26 corpus carried
    84-265 undecoded entities each and **not one newline**, because `html_to_text` stripped
    tags before it could ever see a `&lt;br&gt;`. Unescaping the Mobileye page turns 2,634
    characters of entity noise into 2,115 characters with 21 line breaks — and line structure
    is what `seniority._ROLE_START` and every requirements rule read."""
    if not body:
        return ""
    window = body[:LD_SCAN_BYTES]
    for n, m in enumerate(_LD_SCRIPT.finditer(window)):
        if n >= LD_MAX_BLOCKS:
            break
        # a block inside an HTML comment is a staging leftover, not this page's posting
        if window.rfind("<!--", 0, m.start()) > window.rfind("-->", 0, m.start()):
            continue
        raw = m.group(1).strip()
        if len(raw) > LD_MAX_BLOCK:
            continue
        for candidate in (raw, _html_mod.unescape(raw)):
            try:
                data = json.loads(candidate)
            except (ValueError, RecursionError):
                continue
            for node in _ld_nodes(data):
                if not _is_jobposting(node.get("@type")):
                    continue
                desc = node.get("description")
                if not isinstance(desc, str):
                    continue
                text = _text_or_empty(_html_mod.unescape(desc))
                if text:
                    return text
            break
    return ""

# --------------------------------------------------------------------------- fetch
def plain_fetch(url, timeout=15, accept="text/html,*/*;q=0.8"):
    """One GET, no retries. Returns (status, body): status None on timeout/network error."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept,
                                               "Accept-Language": "en,he;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:  # noqa: BLE001 - timeout, DNS, TLS, reset
        return None, ""


# --------------------------------------------------------------------------- native rungs
# Each reader: raw body -> description html/text. `native_url` decides which applies from the
# public URL ALONE (host + path): the `matched` table has no platform column and a job dict
# carries no api_url, so anything needing the registry row would not work for two of the
# three callers. Verified with plain GETs on 2026-08-24 (see the session record).
_WD_HOST = re.compile(r"^([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", re.I)
_BH_HOST = re.compile(r"^([a-z0-9-]+)\.bamboohr\.com$", re.I)


def _wd_read(body):
    d = json.loads(body)
    return (d.get("jobPostingInfo") or {}).get("jobDescription") or ""


def _sr_read(body):
    d = json.loads(body)
    secs = (d.get("jobAd") or {}).get("sections") or {}
    return "\n".join(f"<h3>{s.get('title') or k}</h3>{s.get('text') or ''}"
                     for k, s in secs.items() if isinstance(s, dict))


def _bh_read(body):
    d = json.loads(body)
    return ((d.get("result") or {}).get("jobOpening") or {}).get("description") or ""


def _gh_read(body):
    import html as _html
    return _html.unescape(json.loads(body).get("content") or "")


def _comeet_read(body):
    """comeet.com job pages embed the posting as JSON: {"name": "Requirements", "value": "<ul>..."}"""
    out, dec = [], json.JSONDecoder()
    for m in re.finditer(r'\{"name":\s*"([^"]{1,60})",\s*"value":\s*(?=")', body):
        try:
            value, _ = dec.raw_decode(body, m.end())
        except ValueError:
            continue
        if isinstance(value, str) and value.strip():
            out.append(f"<h3>{m.group(1)}</h3>{value}")
    return "\n".join(out)


_READERS = {"workday": _wd_read, "smartrecruiters": _sr_read, "bamboohr": _bh_read,
            "greenhouse": _gh_read, "comeet": _comeet_read}
_greenhouse_slugs = None


def _registry_greenhouse_slugs():
    """company name (lower) -> greenhouse board slug, from companies.csv; empty if unreadable."""
    global _greenhouse_slugs
    if _greenhouse_slugs is None:
        _greenhouse_slugs = {}
        try:
            from .companies import load_companies
            for r in load_companies():
                if (r.get("ats_platform") or "") == "greenhouse" and r.get("token"):
                    _greenhouse_slugs[r["company_name"].strip().lower()] = r["token"].strip()
        except Exception:  # noqa: BLE001 - a scratch run without the registry still works
            pass
    return _greenhouse_slugs


def native_url(url, company=""):
    """(platform, [candidate api urls]) for a public job URL, or None when no native rung applies."""
    u = urlsplit(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    m = _WD_HOST.match(host)
    # An "apply link" is the same posting: fetch_phenom hands us Workday URLs of the form
    # .../job/Haifa/Verification-Lead_R4041410-1/apply, and the cxs endpoint 404s on the
    # trailing segment (measured 2026-08-26: 404 with it, 200 and 2,865 chars without).
    if m and parts and parts[-1].lower() == "apply":
        parts = parts[:-1]
    if m and "job" in parts and parts.index("job") >= 1:
        i = parts.index("job")
        return "workday", [f"https://{host}/wday/cxs/{m.group(1)}/{parts[i-1]}/job/" + "/".join(parts[i+1:])]
    if host == "jobs.smartrecruiters.com" and len(parts) >= 2 and re.match(r"^\d{6,}", parts[1]):
        return "smartrecruiters", [f"https://api.smartrecruiters.com/v1/companies/{parts[0]}/postings/"
                                   + re.match(r"^\d+", parts[1]).group(0)]
    if _BH_HOST.match(host) and len(parts) >= 2 and parts[0] == "careers" and parts[1].isdigit():
        return "bamboohr", [f"https://{host}/careers/{parts[1]}/detail"]
    if host == "www.comeet.com" and parts[:1] == ["jobs"] and len(parts) >= 4:
        return "comeet", [url]
    jid = (parse_qs(u.query).get("gh_jid") or [""])[0]
    if host.endswith("greenhouse.io") and "jobs" in parts and parts[-1].isdigit():
        jid, slugs = parts[-1], [parts[0]] if parts[0] != "embed" else []
    elif jid.isdigit():
        slugs = []
        reg = _registry_greenhouse_slugs().get((company or "").strip().lower())
        labels = host.split(".")
        for s in (reg, re.sub(r"[^a-z0-9]", "", (company or "").lower()),
                  labels[-2] if len(labels) >= 2 else ""):
            if s and s not in slugs:
                slugs.append(s)
    else:
        return None
    return ("greenhouse", [f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs/{jid}" for s in slugs]) if slugs else None


def native_jd(url, company=""):
    """(text, reason) via the platform's own detail endpoint; ("", "not-native") when none applies."""
    nat = native_url(url, company)
    if not nat:
        return "", "not-native"
    platform, candidates = nat
    read, why = _READERS[platform], f"{platform}-http"
    for api in candidates:
        status, body = plain_fetch(api, timeout=10, accept="application/json, text/html;q=0.9")
        if status != 200 or not body:
            continue
        try:
            text = _text_or_empty(read(body))
        except (ValueError, TypeError, AttributeError):
            why = f"{platform}-no-json"          # a wrong slug's 200 error page: next candidate
            continue
        if text:
            return text, "ok"
        why = f"{platform}-short"
    return "", why


# --------------------------------------------------------------------------- Bright Data
class Unlocker:
    """Web Unlocker, status-aware. `/request` answers HTTP 200 even when it failed and says so
    in `x-brd-error-code` (target 403 -> `reject_block`; Workday -> `policy_20140`, the host is
    closed to no-KYC residential access); a bad token is a real 401 (measured 2026-08-24).
    401/402/403 from the API itself, or no key, means the ACCOUNT is unusable: stop spending and
    say why. Anything else is one URL's failure. A breaker stops a run that never succeeds."""

    def __init__(self, cap=250, breaker=5):
        self.cap, self.breaker = cap, breaker
        self.key = os.environ.get("BRIGHTDATA_API_KEY", "")
        self.zone = os.environ.get("BRIGHTDATA_ZONE", "")
        self.used = self.ok = self.streak = 0
        # A run that HAS worked is not an account problem, but it is also not getting value any
        # more — and the threshold has to sit INSIDE the day's allowance to save anything. At
        # the caps set on 2026-08-26 (25 and 40) a flat `breaker x 4` tripped at 20, i.e. after
        # 80 % of the matched driver's whole allowance had gone.
        self._failing_at = max(breaker * 2,
                               min(breaker * FAILING_STREAK_FACTOR, max(3, cap // 2)))
        self.capped = False                       # the cap was reached: spend stopped, and
        self.unavailable = "" if (self.key and self.zone) else "no-key"   # `alarm_for` says so
        if os.environ.get("JD_BD", "1") == "0":
            self.unavailable = "disabled"         # JD_BD=0: a local run that must spend nothing

    def __call__(self, url, timeout=90):
        """(status, body, reason). reason is "" on success."""
        if self.unavailable:
            return None, "", "bd-unavailable"
        if self.used >= self.cap:
            self.capped = True                    # not `unavailable`: the account is fine and
            return None, "", "bd-capped"          # the reason string stays honest
        self.used += 1
        body = json.dumps({"zone": self.zone, "url": url, "format": "raw"}).encode()
        req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, text = r.status, r.read(2_000_000).decode("utf-8", "replace")
                err = r.headers.get("x-brd-error-code") or ""
        except urllib.error.HTTPError as e:
            if e.code in (401, 402, 403):
                self.unavailable = f"http-{e.code}"
                return e.code, "", "bd-unavailable"
            status, text, err = e.code, "", f"http-{e.code}"
        except Exception:  # noqa: BLE001
            status, text, err = None, "", "timeout"
        if err or not text:
            self.streak += 1
            if self.ok == 0 and self.streak >= self.breaker:
                self.unavailable = f"no-success-after-{self.streak}"
            elif self.streak >= self._failing_at:
                # One success used to disarm the breaker for the whole run, so a pass that
                # filled a single role and then failed could spend the entire cap. A run that
                # HAS worked is not an account problem (that is `no-success-after-N`, and it
                # stays exactly as it was) -- but it is also not getting value any more.
                self.unavailable = f"failing-after-{self.streak}"
            return status, "", f"bd-{err or 'empty'}"
        self.ok, self.streak = self.ok + 1, 0
        return status, text, ""


# A path segment that names a LIST, not a posting. Compared by EQUALITY, and only against the
# last segment: a real slug can end in one of these words (".../senior-data-analyst-jobs").
# `company_identity._NOT_A_SLUG` holds a similar vocabulary for a different question ("could
# this segment be a tenant name?") and is deliberately not imported — it also contains
# `positions` and `apply`, which are real job-URL segments here.
_LIST_SEGMENT = {"search-results", "search", "results", "jobs", "job", "careers", "career",
                 "openings", "open-positions", "vacancies", "programs", "requisitions",
                 "opportunities", "all-jobs", "job-search"}
# a filter query carrying no posting id. `location=` is NOT here: real job URLs carry it.
_LIST_QUERY = re.compile(r"(^|&)(keywords?|q|query|search|offices(\[|%5[Bb])[^=]*)=", re.I)


def is_job_url(url):
    """Could this URL identify ONE posting? A search/list page can never carry a JD, and must
    never be paid for (4 credits went to search pages on 2026-08-24, 1 more on 2026-08-26).

    The old `>= 3 path segments` fallback was too generous: every locale-prefixed careers site
    (`/global/en/...`, `/us/en/...`) reaches three segments for free, which is how
    `careers.dhl.com/global/en/search-results?keywords=Israel` was charged. Measured against
    `scraped_cache.json` on 2026-08-26: **30 distinct URLs on 78 cards** passed ONLY via that
    fallback, among them a cookies policy and a legal notice."""
    u = urlsplit(url)
    parts = [p for p in u.path.split("/") if p]
    if "gh_jid" in u.query or re.search(r"(^|&)(jk|jobid|job_id|id|req)=[\w.-]+", u.query, re.I):
        return True
    if any(re.search(r"\d", p) for p in parts):
        return True                      # a digit anywhere in the path can identify a posting
    last = parts[-1].lower() if parts else ""
    if last in _LIST_SEGMENT or last.endswith((".html", ".htm")) or _LIST_QUERY.search(u.query):
        return False
    return len(parts) >= 3


# Host families no rung we own can read. Every entry carries its measurement, because this
# list can only ever COST coverage:
#   indeed.com       every job page answers 401 or 403 to a plain GET (22 of 22 sampled
#                    2026-08-26) and `reject_authwall` to the Unlocker. The card snippet the
#                    discovery source already stored is the best text obtainable.
#   secrethunter.io  every discovery-telegram URL. A JS shell that returns the SAME
#                    776-character body for every job id (5 of 5 sampled 2026-08-26).
# This is NOT `pipeline.aggregators.is_aggregator`, which answers "whose board is this?" and
# lists `linkedin.` — LinkedIn guest pages are this layer's biggest source of fills (91 of 110
# on 2026-08-26). Its regex also matches `indeed.com.evil.co`: fail-safe for a blocklist,
# wrong for a list that decides what we refuse to read.
_UNFILLABLE = (
    ("indeed.com", None, "auth-walled"),
    ("secrethunter.io", None, "js-shell"),
)


def _host_of(url):
    """The authority's host: lowercased, without userinfo, port or a trailing dot."""
    host = urlsplit(url).netloc.lower().rsplit("@", 1)[-1]
    if host.startswith("["):                                  # IPv6 literal
        return host.split("]")[0] + "]"
    return host.split(":")[0].rstrip(".")


def unfillable(url):
    """Why no rung we own can read this URL, or "" when one of them might.

    Exact host or subdomain, never a substring: `notindeed.com` and `indeed.com.evil.co` are
    other people's hosts and must still be fetched."""
    host, path = _host_of(url), urlsplit(url).path
    for suffix, pred, why in _UNFILLABLE:
        if (host == suffix or host.endswith("." + suffix)) and (pred is None or pred(path)):
            return why
    return ""


# --------------------------------------------------------------------------- the ladder
class JD(NamedTuple):
    text: str
    via: str         # native | html | bd | none      -- which FETCH produced the body
    reason: str      # ok | ok-jsonld | no-url | not-a-job-url | auth-walled | js-shell |
                     # shell | no-markers | http-NNN | timeout | bd-...
    transient: bool  # retry tomorrow rather than in RETRY_DAYS
    native: str = "" # why the native rung failed, when one applied ("" if none did / it won)
    pre: str = ""    # what the PLAIN rung found, when the Bright Data rung never ran at all


def _from_body(body):
    """The two parsers over one body, in order: the marker heuristic, then the page's own
    schema.org declaration. Returns (text, reason) with reason "" when neither found a JD."""
    jd = extract_jd(body)
    if jd:
        return jd, "ok"
    jd = jsonld_jd(body)
    if jd:
        return jd, "ok-jsonld"
    return "", ""


def fetch_jd(url, *, bd=None, company="", timeout=15, probe=False):
    """native JSON -> plain HTML (+ schema.org) -> Bright Data (only when `bd` is given).

    The gate runs BEFORE the plain GET, not only before Bright Data. A search page and an
    auth-walled host used to cost a 15-second fetch every morning and were booked as failed
    fetches: on 2026-08-26 that was Meta's search URL, 17 Indeed pages and 5 secrethunter
    shells, 22 of the 38 inline failures. `probe=True` fetches an unfillable host anyway —
    the once-a-run canary that keeps the refusal falsifiable."""
    if not (url or "").startswith("http"):
        return JD("", "none", "no-url", False)
    text, native_why = native_jd(url, company)
    if text:
        return JD(text, "native", "ok", False)
    native_why = "" if native_why == "not-native" else native_why
    # after the native rung, never before: if a reader is ever written for a blocked host, the
    # native rung wins by construction and the `_UNFILLABLE` entry simply goes dead
    blocked = unfillable(url)
    if blocked:
        bd = None            # the credit safety belongs to the function that owns the claim
        if not probe:
            # a native rung that APPLIED and failed keeps its own reason: `gh_jid` is
            # host-agnostic, so it can apply on a refused host, and reporting `auth-walled`
            # would claim a wall we never observed
            return JD("", "none", native_why or blocked, False, native_why)
    if not is_job_url(url):
        return JD("", "none", "not-a-job-url", False, native_why)
    status, body = plain_fetch(url, timeout=timeout)
    if body:
        jd, why = _from_body(body)
        if jd:
            return JD(jd, "html", why, False, native_why)
        reason, transient = ("shell" if len(html_to_text(body)) < MIN_DESC else "no-markers"), False
    else:
        reason, transient = (f"http-{status}" if status else "timeout"), (status is None or status >= 500)
    if bd is None:
        return JD("", "none", reason, transient, native_why)
    status, body, bd_reason = bd(url)
    if body:
        jd, why = _from_body(body)          # the credit is spent either way: read it twice
        if jd:
            return JD(jd, "bd", why, False, native_why)
        return JD("", "bd", "bd-" + ("shell" if len(html_to_text(body)) < MIN_DESC else "no-markers"),
                  False, native_why)
    # when the Unlocker is unavailable or capped it never sent a request, so `reason` is a
    # statement about the ACCOUNT and says nothing about the page. Carrying the plain rung's
    # verdict alongside it stops `scrape_fail=0` from being the whole story on an outage
    # morning: five pages that timed out used to be re-booked as `bd_unavailable` and the
    # failure histogram lost them entirely.
    never_sent = bd_reason in ("bd-unavailable", "bd-capped")
    return JD("", "bd", bd_reason, bd_reason in ("bd-unavailable", "bd-capped", "bd-timeout")
              or bool(re.match(r"bd-http-5[0-9][0-9]$", bd_reason)), native_why,
              reason if never_sent else "")


# --------------------------------------------------------------------------- cooldown
def due(attempted, today=None, definitive=RETRY_DAYS, transient=TRANSIENT_RETRY_DAYS):
    """Is a stamped URL due for another attempt? Stamps are "YYYY-MM-DD" (legacy) or
    "YYYY-MM-DD transient"; the date is the first 10 characters either way."""
    if not attempted:
        return True
    today = today or dt.date.today()
    days = transient if attempted.endswith(TRANSIENT_MARK) else definitive
    return attempted[:10] <= (today - dt.timedelta(days=days)).isoformat()


def stamp_value(today, transient):
    return today.isoformat() + (TRANSIENT_MARK if transient else "")


def stamp_path_for(target, default):
    """Where a driver run against `target` should write its `enrich` stamp: None (the repo's
    real `cloud_state/pipeline_stages.json`) when `target` IS the default file, else an
    absolute sidecar beside the copy.

    Compared by `os.path.realpath`, not by string: `--cache ./scraped_cache.json` names the
    real cache and used to divert the stamp, so the mail said `no-report(scrape)` about a
    driver that had run perfectly. Built with `abspath` because a bare relative target
    (`--cache c.json`) yields a sidecar whose dirname is `""`, and `stages.stamp` then dies in
    `os.makedirs("")` — after the credits have been spent."""
    try:
        same = os.path.realpath(target) == os.path.realpath(default)
    except (OSError, ValueError):  # noqa: BLE001 - an unresolvable path is not the default
        same = False
    return None if same else os.path.abspath(target) + ".stages.json"


# --------------------------------------------------------------------------- the shared loop
class Item(NamedTuple):
    key: object          # opaque; handed straight back to save()
    url: str
    label: str           # "Company | Title" for the progress line
    attempted: str = ""  # raw stamp value, "" if never tried
    company: str = ""


def run_backfill(items, *, save, minutes, count_cap=0, bd=None, dry_run=False, today=None,
                 retry_days=RETRY_DAYS, timeout=25, log=print, probe_cell=None):
    """Walk `items` (already gated by the driver's own relevance/url rules) through `fetch_jd`
    inside a wall-clock budget (`minutes=None` for none; 0 attempts nothing).
    `save(item, text_or_None, stamp)` is the driver's one
    persistence callback. Returns a Counter: todo, filled, bd, fail, bd_unavailable, cooldown,
    unfillable, skipped_budget (= skipped_cap + skipped_clock), tried, probe, probe_ok,
    jsonld, via:<v>, reason:<r>, native:<why>.

    `todo` and the split skip counters exist because a partially-walked list used to be
    arithmetically identical to a fully-walked one, and an empty todo identical to a healthy
    quiet morning (2026-08-26: neither driver stamped either number).

    `probe_cell` is a one-element list shared across calls so that ONE process probes once —
    the matched driver walks this loop twice (canonical, then siblings) and was probing twice.
    """
    today = today or dt.date.today()
    items = list(items)
    t0, c = time.time(), Counter()
    c["todo"] = len(items)
    # a SET of host families, not a boolean: with Indeed rows sorting first, secrethunter.io
    # was never once probed, so half the refusal list stayed unfalsifiable for ever
    probed = probe_cell if probe_cell is not None else set()
    for item in items:
        # A refused address is decided BEFORE the cooldown, the cap and the clock: it is not an
        # attempt, so it must not burn a `--limit` slot (5 refusals used to defer 5 readable
        # rows to tomorrow), must not count toward the mass-failure rule (a morning of nothing
        # but Indeed rows raised a bold `jd-massfail` while behaving perfectly), and must not be
        # stamped — a stamp would put the canary below into a 7-day cooldown and make the
        # refusal unfalsifiable.
        blocked = unfillable(item.url)
        if blocked:
            c["unfillable"] += 1
            c[f"reason:{blocked}"] += 1
            # the canary: one refused address per process is fetched anyway, never through
            # Bright Data, so "no rung we own can read this host" stays a claim that can fail
            if blocked in probed:
                continue
            probed.add(blocked)
            c["probe"] += 1
            jd = fetch_jd(item.url, bd=None, company=item.company, timeout=timeout, probe=True)
            c["tried"] += 1                      # it really was fetched: `filled` needs a denominator
            if jd.text:
                c["probe_ok"] += 1               # the refusal is WRONG -- alarm_for says so
                c["filled"] += 1
                if not dry_run:
                    save(item, jd.text, stamp_value(today, False))
            else:
                c["fail"] += 1
            log(f"  [{'OK!' if jd.text else '-- '}] {item.label[:60]:<60} canary {blocked} {len(jd.text)}")
            continue
        # the cooldown protects an expensive rung; a native JSON GET is cheap and new (rows
        # stamped before the rung existed would otherwise wait a week for a 1 s call)
        if not due(item.attempted, today, definitive=retry_days) and not native_url(item.url, item.company):
            c["cooldown"] += 1
            continue
        if count_cap and c["tried"] - c["probe"] >= count_cap:
            c["skipped_cap"] += 1
            c["skipped_budget"] += 1
            continue
        if minutes is not None and (minutes <= 0 or (time.time() - t0) / 60 > minutes):
            c["skipped_clock"] += 1
            c["skipped_budget"] += 1
            continue
        c["tried"] += 1
        jd = fetch_jd(item.url, bd=bd, company=item.company, timeout=timeout)
        c[f"via:{jd.via}"] += 1
        c[f"reason:{jd.reason}"] += 1
        if jd.native:
            c[f"native:{jd.native}"] += 1
        if jd.pre:
            # `*_why` is a histogram of what was OBSERVED, not a partition of `tried`: on an
            # outage morning one item legitimately reports both what the page did and that the
            # last rung never ran.
            c[f"reason:{jd.pre}"] += 1
        if jd.text:
            c["filled"] += 1
            c["bd"] += jd.via == "bd"
            c["jsonld"] += jd.reason == "ok-jsonld"
        elif jd.reason in ("bd-unavailable", "bd-capped"):
            c["bd_unavailable"] += 1
        elif jd.reason in UNFILLABLE_REASONS:
            c["unfillable"] += 1        # a search page: nothing to fetch, nobody's failure
        else:
            c["fail"] += 1
        log(f"  [{'OK ' if jd.text else '-- '}] {item.label[:64]:<64} {jd.via}/{jd.reason} {len(jd.text)}")
        if not dry_run:
            save(item, jd.text or None, stamp_value(today, jd.transient))
    return c

def why_string(c, n=4):
    """The failure histogram `run_backfill` builds, as one short string for the stamp — the
    shape the `collect` stamp already uses (`no-markers2+timeout1`). Without it the mail's
    `scrape_fail=6` cannot tell a WAF from a 404 from a parser regression."""
    bad = sorted(((k[7:], v) for k, v in c.items()
                  if k.startswith("reason:") and k[7:] not in ("ok", "ok-jsonld")),
                 key=lambda kv: (-kv[1], kv[0]))
    return "+".join(f"{r}{v}" for r, v in bad[:n])


def alarm_for(c, bd=None, driver="", operator_cap=False):
    """Everything the mail must say about a backfill run, joined with "; ".

    It returned ONE string until 2026-08-26 wave 1, so the LAST rule — a spent budget, which
    `enrich_scrape_jd`'s own docstring calls "the real limit" — was invisible on any morning
    where a Bright Data state also fired, i.e. exactly the mornings with a real backlog.

    Two of the three 08-24 rules could not fire on the day they were written for.
    `bd-unavailable` needed the ACCOUNT to be dead. `jd-massfail` needed 10 attempts, which
    the matched driver at 130-of-135 coverage will never reach again. And the credit rule is
    `not c["bd"]`, NOT `c["filled"] == 0`: `filled` counts the free rungs too, so one role
    filled over plain HTTP masked any amount of Bright Data waste — which is precisely the
    2026-08-26 morning (6 html fills, 1 credit burnt on a search page, mail silent)."""
    out = []
    used = getattr(bd, "used", 0) if bd is not None else 0
    if bd is not None and bd.unavailable and (c["bd_unavailable"] or used):
        # `or used`: the breaker can open ON the last item, leaving nothing behind it to be
        # refused, so `c["bd_unavailable"]` stays 0 while five credits have already gone
        out.append(f"bd-unavailable({bd.unavailable})")
    if bd is not None and getattr(bd, "capped", False):
        out.append(f"bd-capped({used} spent, {c['bd_unavailable']} roles waiting)")
    # not beside `bd-unavailable`: `used` increments BEFORE the request, so a 401 counts one
    # call the account was never billed for, and the outage clause already says what happened
    if used and not c["bd"] and not out:
        why = why_string(c, 3)
        out.append(f"bd-spent({used} call{'' if used == 1 else 's'}, 0 filled"
                   f"{': ' + why if why else ''})")
    if c["probe_ok"]:
        # the canary read a page we refuse by policy: the `_UNFILLABLE` entry is now wrong and
        # is costing coverage every day until someone deletes it
        out.append(f"jd-refusal-falsified({c['probe_ok']} — a refused host answered with a JD)")
    # `bd-unavailable` still OUTRANKS `jd-massfail` (the 2026-08-24 rule): when the account is
    # dead, "10 tried, 0 filled" is the same news said twice, and its top reason IS the
    # outage. Every other clause stacks; this one is the exception, and only this one.
    # ONLY `bd-unavailable`, as the comment says: with `CAP=0` the Unlocker reports `capped`
    # having spent nothing, and suppressing the mass-failure rule there left a morning of 30
    # failed fetches saying only `bd-capped(0 spent, 0 roles waiting)`.
    if (not any(a.startswith("bd-unavailable") for a in out)
            and c["tried"] >= MASSFAIL_MIN_TRIED and c["filled"] == 0):
        real = [k for k in c if k.startswith("reason:") and k[7:] not in UNFILLABLE_REASONS and c[k]]
        if real:
            top = max(real, key=c.__getitem__)
            out.append(f"jd-massfail({top[7:]} x{c[top]})")
    # `--limit 20` is an operator saying "do twenty": the rows it did not reach are not a
    # budget the morning ran out of, and reporting them as one makes a bounded rehearsal read
    # in the mail exactly like a morning that was cut short.
    if c["skipped_clock"] or (c["skipped_cap"] and not operator_cap):
        out.append(f"jd-budget-spent({c['skipped_budget']} left for tomorrow"
                   f"{', cap' if c['skipped_cap'] else ''}{', clock' if c['skipped_clock'] else ''})")
    elif c["todo"] and not c["tried"] and not c["cooldown"] and not c["unfillable"]:
        # there was work and none of it was attempted -- but NOT when the budget explains it
        # (that says `jd-budget-spent`), NOT when everything is legitimately cooling, NOT when
        # every row was a refused address, and NOT when the todo is empty: a driver with
        # nothing to do is a healthy driver, and an alarm that fires every morning is one that
        # gets trained away.
        out.append(f"jd-nothing-attempted({c['todo']} due)")
    if not out:
        return ""
    return "; ".join(f"{driver}:{a}" if driver else a for a in out)


# --------------------------------------------------------------------------- inline
class JDFiller:
    """Fill a role's description before it is classified. Only for jobs that could plausibly
    be accepted (the cheap title gate first — never spend a fetch on a role we would reject on
    the title anyway), only for addresses some rung of ours can actually read, only within a
    budget, and never through Bright Data (the backfills own that).

    The budget counts SECONDS SPENT FETCHING, not wall clock since construction — the shape
    `seniority.Classifier` uses one line away in `run.py`. It used to start at construction,
    which is before the 870-board fetch loop: 5.7 of the 25 minutes were gone on 2026-08-26
    before a single fill was attempted, and the LLM time interleaved between fills counted too.
    """

    def __init__(self, budget_min=None, enabled=None):
        env_budget = os.environ.get("JDFILL_TIME_BUDGET_MIN")
        # zero has ONE meaning here, the same as `run_backfill`'s: attempt nothing. It used to
        # mean "unbounded" (`self.budget and ...` with a falsy 0.0) on the digest's critical
        # path, and `JDFiller(budget_min=0)` silently became 20.
        raw = env_budget if env_budget not in (None, "") else (20 if budget_min is None else budget_min)
        self.budget = float(raw)
        env = os.environ.get("JDFILL", "")
        self.enabled = (env == "1") if env else (True if enabled is None else enabled)
        self.seconds = 0.0
        self.filled = self.tried = self.skipped_budget = self.unfillable = 0
        self.probe = self.probe_ok = 0
        self.probed = False
        self.by_platform = Counter()        # (platform, reason) -> n, for fetches we made
        self.refused = Counter()            # (platform, reason) -> n, for fetches we did not
        self.via = Counter()

    def spent(self):
        return self.budget <= 0 or self.seconds / 60 > self.budget

    def maybe_fill(self, job):
        """Fill job['description'] in place when it is missing. Returns True if filled."""
        if not self.enabled:
            return False
        if len(str(job.get("description") or "").strip()) >= MIN_DESC:
            return False
        url = str(job.get("url") or "")
        if not url.startswith("http"):
            return False
        from .seniority import _relevance
        if _relevance(str(job.get("title") or "").lower()) in ("excluded", "none"):
            return False
        # the gate BEFORE the clock and the counter: an auth-walled host and a search page cost
        # a 15-second fetch every morning and were booked as failed fetches, which is how
        # `jd-fill: 110/148` hid 22 addresses nothing could ever have read (2026-08-26)
        platform = str(job.get("ats_platform") or "?")   # a list here used to kill the digest
        why = unfillable(url) or ("" if is_job_url(url) else "not-a-job-url")
        if why:
            self.unfillable += 1
            self.refused[(platform, why)] += 1
            # the canary, and this is where it matters: 257 of the 260 refused addresses in the
            # state files are the inline filler's, so a canary that lived only in the backfills
            # was testing a population of three. One per run, never through Bright Data.
            if unfillable(url) and not self.probed and not self.spent():
                self.probed = True
                self.probe += 1
                self.tried += 1              # fetched like any other: `filled` needs a denominator
                jd = fetch_jd(url, company=str(job.get("company") or ""), probe=True)
                if jd.text:
                    self.probe_ok += 1
                    job["description"] = jd.text
                    self.filled += 1
                    return True
            return False
        if self.spent():
            self.skipped_budget += 1
            return False
        self.tried += 1
        _t = time.time()
        jd = fetch_jd(url, company=job.get("company") or "")
        self.seconds += time.time() - _t
        self.by_platform[(platform, jd.reason + (f"/{jd.native}" if jd.native else ""))] += 1
        if jd.text:
            job["description"] = jd.text
            self.filled += 1
            self.via[jd.via] += 1
            return True
        return False

    def failures(self, n=6):
        worst = sorted(((k, v) for k, v in self.by_platform.items()
                        if not k[1].startswith(("ok", "ok-jsonld"))),
                       key=lambda kv: -kv[1])[:n]
        return ", ".join(f"{p} {r} {v}" for (p, r), v in worst)

    def refusals(self, n=6):
        worst = sorted(self.refused.items(), key=lambda kv: -kv[1])[:n]
        return ", ".join(f"{p} {r} {v}" for (p, r), v in worst)

    def summary(self):
        out = f"jd-fill: {self.filled}/{self.tried} descriptions fetched inline"
        if self.via:
            out += " (" + ", ".join(f"{k} {v}" for k, v in self.via.most_common()) + ")"
        if self.tried > self.filled:
            out += "; failed: " + self.failures()
        if self.unfillable:
            out += f"; {self.unfillable} unfillable ({self.refusals(4)})"
        if self.skipped_budget:
            out += f", {self.skipped_budget} skipped (budget {self.budget:g}m spent)"
        return out

    def alarms(self):
        """Lines for the mail's bold `Stages:` line. A spent budget used to live in the step
        log only, so a morning that judged hundreds of roles with no text read as a normal one."""
        out = []
        if self.probe_ok:
            out.append(f"inline jd-fill: a refused host answered with a JD ({self.probe_ok}) — "
                       f"the `_UNFILLABLE` entry is costing coverage")
        # `+ self.unfillable`: refusing before `tried` shrank the denominator under a fixed
        # threshold, so a morning where 22 addresses were refused AND all 8 readable fetches
        # failed went from a bold alarm to complete silence (wave 1).
        if self.tried and self.filled == 0 and self.tried + self.unfillable >= MASSFAIL_MIN_TRIED:
            out.append(f"inline jd-fill {self.filled}/{self.tried} — every fetch failed ({self.failures(3)})")
        if self.skipped_budget:
            out.append(f"inline jd-fill budget spent ({self.budget:g}m) — {self.skipped_budget} "
                       f"roles judged with no text")
        return out


# --------------------------------------------------------------------------- the stamp
DRIVERS = ("scrape", "matched")      # each stamps `<name>_ran=1`; the gap-filler names the absent one


# A COUNT of what this run DID — two runs in one day add up. Everything else is a GAUGE: a
# measurement of the world at one moment (how many roles are still short, how many cards the
# title gate dropped, how big the todo was), and a second run REPLACES it. Summing gauges put
# `matched_short=258` and `scrape_dropped_title=1868` — larger than the whole cache — into the
# stamp on a re-dispatch (found by wave 1).
_FLOW_SUFFIXES = ("_filled", "_bd", "_bd_calls", "_bd_ok", "_fail", "_cooldown", "_unfillable",
                  "_skipped", "_from_cache", "_via_sibling", "_bd_unavailable", "_probe",
                  "_foreign_sibling")


STAMP_FRESH_HOURS = 12      # a crash report and the driver that follows it are minutes apart


def _within_hours(iso, hours):
    """Was this timestamp written in the last `hours`? False for anything unparseable."""
    try:
        when = dt.datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - when) <= dt.timedelta(hours=hours)


def _join_alarms(*parts):
    """One line, each clause once, order preserved."""
    out = []
    for p in parts:
        for a in str(p or "").split("; "):
            if a and a not in out:
                out.append(a)
    return "; ".join(out)


def _prune_stale(alarm, counts):
    """Drop the clauses a re-running driver is about to re-derive, and keep everyone else's.

    A driver that reports again OWNS its own verdict: on a re-dispatch that cleared the
    backlog the mail still said `scrape:jd-budget-spent(3 left for tomorrow)` about a run that
    had just finished with nothing left, and `matched:jd-refusal-falsified` about a canary that
    did not fire that time — a healthy layer reading as a broken one. So `<driver>:` clauses
    are dropped when `<driver>_ran` is in this call's counts, and the fresh ones replace them.

    `no-report(...)` goes whenever ANY driver reports: the gap-filler is the workflow's last
    `if: always()` step and re-derives it from `<driver>_ran`, so a partial clause here would
    announce `no-report(matched)` at the moment the scrape driver stamps — which is simply
    before the matched driver has run."""
    reporting = {k[:-len("_ran")] for k in counts if k.endswith("_ran")}
    if not reporting:
        return str(alarm or "")
    out = []
    for a in str(alarm or "").split("; "):
        if not a or a.startswith("no-report("):
            continue
        if any(a.startswith(f"{d}:") for d in reporting):
            continue                      # this driver is restating its own verdict below
        out.append(a)
    return "; ".join(out)


def _loaded_enrich(stages):
    """The enrich entry, or {} for any stamp file we cannot read as a stage map."""
    d = stages._load()
    return (d.get("enrich") or {}) if isinstance(d, dict) else {}


def _stamp(stages, detail):
    """`stages.stamp` reads the file itself and assumes a dict; a stamp file that is a JSON
    list parses fine and then raises TypeError. That landed inside the drivers' crash handler,
    re-raising the wrong exception and stamping nothing at all. Report and carry on: the file
    belongs to shared plumbing and we do not overwrite what we could not understand."""
    try:
        stages.stamp("enrich", **detail)
    except (TypeError, AttributeError) as e:  # noqa: BLE001
        print(f"::error::cannot stamp the enrich stage: {stages.PATH} is not a stage map "
              f"({type(e).__name__}); the mail will say `no-report`", flush=True)


def record_enrich(alarm="", path=None, **counts):
    """Merge counts into TODAY's `enrich` stage stamp — two scripts, one stamp — replacing a
    stamp from another day. Called with no counts at all (the workflow's `if: always()` step)
    it only fills the gap: a driver that never stamped today => `alarm=no-report(<name>)`, and
    the stamp's `date` is NOT moved, so `Stage order:` still says when the layer last really
    ran. A bare `stages.stamp("enrich")` would erase the counts; that is why the workflow step
    calls this. `path` (or env `JD_STAGES_OUT`) redirects the stamp file — a rehearsal against
    a copy must not write the real one."""
    from . import stages
    path = path or os.environ.get("JD_STAGES_OUT")
    saved = stages.PATH
    if path:
        stages.PATH = path
    try:
        loaded = stages._load()
        prev = (loaded if isinstance(loaded, dict) else {}).get("enrich") or {}
        if not isinstance(prev, dict):
            prev = {}                            # a stamp file that is a list is not a crash
        today = dt.date.today().isoformat()
        fresh = prev.get("date") == today
        # A crash report deliberately leaves the date where it was, so `fresh` is False for the
        # rest of the day and the FIRST driver's `crash:...` used to be thrown away by the
        # second driver's stamp — the mail then said `no-report(scrape)`, which is also what a
        # skipped step and a runner timeout look like. The ALARM is carried on "written today";
        # the COUNTS are still only carried on "dated today", so yesterday's numbers can never
        # be re-presented under today's date.
        # `stages.stamp` writes `date` from the LOCAL clock and `finished_at` from UTC, so
        # comparing them by CALENDAR is wrong twice over: one way it drops a crash alarm the
        # moment the local date rolls over, the other way (accepting either date) it makes the
        # window two days wide and resurrects a genuinely stale alarm — which it did, on this
        # machine, in the same session. The question is only "was this written in the last few
        # hours", so ask that directly and let the calendars disagree.
        wrote_today = _within_hours(prev.get("finished_at"), STAMP_FRESH_HOURS)
        prior_alarm = prev.get("alarm") if (fresh or wrote_today) else ""
        if not counts:
            missing = [d for d in DRIVERS if not (fresh and prev.get(f"{d}_ran"))]
            if not missing and not alarm:
                return prev
            keep = {k: v for k, v in prev.items() if k != "finished_at"}
            gap = f"no-report({','.join(missing)})" if missing and not alarm else ""
            keep["alarm"] = _join_alarms(prior_alarm, alarm, gap)
            _stamp(stages, keep)
            return _loaded_enrich(stages)
        merged = {k: v for k, v in prev.items()
                  if fresh and k not in ("finished_at", "date", "alarm")}
        for k, v in counts.items():
            old = merged.get(k)
            if isinstance(v, str) and not v and old:
                continue                         # a quiet re-run must not erase the histogram
            merged[k] = (old + v if (fresh and isinstance(v, int) and isinstance(old, int)
                                     and k.endswith(_FLOW_SUFFIXES)) else v)
        for d in DRIVERS:
            if fresh and f"{d}_ran" in counts and prev.get(f"{d}_ran"):
                merged[f"{d}_runs"] = (prev.get(f"{d}_runs") or 1) + 1
        alarms = _join_alarms(_prune_stale(prior_alarm, counts), alarm)
        merged.pop("alarm", None)
        if alarms:
            merged["alarm"] = alarms
        _stamp(stages, merged)
        return _loaded_enrich(stages)
    finally:
        stages.PATH = saved
