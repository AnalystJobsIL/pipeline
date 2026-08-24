"""The jd-text layer: a job description for every relevant role, whatever its age.

Four list endpoints carry no description at all — `workday` (66 active rows), `smartrecruiters`
(16), `bamboohr` (11) and Microsoft's Eightfold search (1) (re-derived from `companies.csv`
2026-08-24; `eightfold`/`phenom` fetchers return "" too but have 0 rows) — so their roles used
to reach the classifier as a bare title and the board with no requirements, skills or tags.
Scrape cards and discovery cards arrive without text as well.

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
    """A native payload is trusted for what it is, but still has to be a description."""
    text = html_to_text(html or "")
    return text[:DESC_MAX] if len(text) >= MIN_DESC else ""


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
        self.unavailable = "" if (self.key and self.zone) else "no-key"
        if os.environ.get("JD_BD", "1") == "0":
            self.unavailable = "disabled"         # JD_BD=0: a local run that must spend nothing

    def __call__(self, url, timeout=90):
        """(status, body, reason). reason is "" on success."""
        if self.unavailable:
            return None, "", "bd-unavailable"
        if self.used >= self.cap:
            return None, "", "bd-capped"
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
            return status, "", f"bd-{err or 'empty'}"
        self.ok, self.streak = self.ok + 1, 0
        return status, text, ""


def is_job_url(url):
    """A search/list page (query-only, no segment that could identify one posting) can never
    carry a JD — never spend an Unlocker credit on it (4 were, on 2026-08-24)."""
    u = urlsplit(url)
    parts = [p for p in u.path.split("/") if p]
    if "gh_jid" in u.query or re.search(r"(^|&)(jk|jobid|job_id|id|req)=[\w.-]+", u.query, re.I):
        return True
    return any(re.search(r"\d", p) for p in parts) or len(parts) >= 3


# --------------------------------------------------------------------------- the ladder
class JD(NamedTuple):
    text: str
    via: str         # native | html | bd | none
    reason: str      # ok | no-url | not-a-job-url | shell | no-markers | http-NNN | timeout | bd-...
    transient: bool  # retry tomorrow rather than in RETRY_DAYS


def fetch_jd(url, *, bd=None, company="", timeout=15):
    """native JSON -> plain HTML -> Bright Data (only when `bd` is given AND the URL is a job page)."""
    if not (url or "").startswith("http"):
        return JD("", "none", "no-url", False)
    text, _ = native_jd(url, company)
    if text:
        return JD(text, "native", "ok", False)
    status, body = plain_fetch(url, timeout=timeout)
    if body:
        jd = extract_jd(body)
        if jd:
            return JD(jd, "html", "ok", False)
        reason, transient = ("shell" if len(html_to_text(body)) < MIN_DESC else "no-markers"), False
    else:
        reason, transient = (f"http-{status}" if status else "timeout"), (status is None or status >= 500)
    if bd is None:
        return JD("", "none", reason, transient)
    if not is_job_url(url):
        return JD("", "none", reason if transient else "not-a-job-url", transient)
    status, body, bd_reason = bd(url)
    if body:
        jd = extract_jd(body)
        if jd:
            return JD(jd, "bd", "ok", False)
        return JD("", "bd", "bd-" + ("shell" if len(html_to_text(body)) < MIN_DESC else "no-markers"), False)
    return JD("", "bd", bd_reason, bd_reason in ("bd-unavailable", "bd-capped", "bd-timeout")
              or bool(re.match(r"bd-http-5\d\d$", bd_reason)))


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


# --------------------------------------------------------------------------- the shared loop
class Item(NamedTuple):
    key: object          # opaque; handed straight back to save()
    url: str
    label: str           # "Company | Title" for the progress line
    attempted: str = ""  # raw stamp value, "" if never tried
    company: str = ""


def run_backfill(items, *, save, minutes, count_cap=0, bd=None, dry_run=False, today=None,
                 retry_days=RETRY_DAYS, timeout=25, log=print):
    """Walk `items` (already gated by the driver's own relevance/url rules) through `fetch_jd`
    inside a wall-clock budget (`minutes=None` for none; 0 attempts nothing).
    `save(item, text_or_None, stamp)` is the driver's one
    persistence callback. Returns a Counter: filled, bd, fail, bd_unavailable, cooldown,
    skipped_budget, tried, via:<v>, reason:<r>."""
    today = today or dt.date.today()
    t0, c = time.time(), Counter()
    for item in items:
        # the cooldown protects an expensive rung; a native JSON GET is cheap and new (rows
        # stamped before the rung existed would otherwise wait a week for a 1 s call)
        if not due(item.attempted, today, definitive=retry_days) and not native_url(item.url, item.company):
            c["cooldown"] += 1
            continue
        if (count_cap and c["tried"] >= count_cap) or \
                (minutes is not None and (minutes <= 0 or (time.time() - t0) / 60 > minutes)):
            c["skipped_budget"] += 1
            continue
        c["tried"] += 1
        jd = fetch_jd(item.url, bd=bd, company=item.company, timeout=timeout)
        c[f"via:{jd.via}"] += 1
        c[f"reason:{jd.reason}"] += 1
        if jd.text:
            c["filled"] += 1
            c["bd"] += jd.via == "bd"
        elif jd.reason in ("bd-unavailable", "bd-capped"):
            c["bd_unavailable"] += 1
        elif jd.reason == "not-a-job-url":
            c["unfillable"] += 1          # a search page: nothing to fetch, nobody's failure
        else:
            c["fail"] += 1
        log(f"  [{'OK ' if jd.text else '-- '}] {item.label[:64]:<64} {jd.via}/{jd.reason} {len(jd.text)}")
        if not dry_run:
            save(item, jd.text or None, stamp_value(today, jd.transient))
    return c


def alarm_for(c, bd=None):
    """What the mail must say about a backfill run: nothing, or one short reason."""
    if bd is not None and bd.unavailable and c["bd_unavailable"]:
        return f"bd-unavailable({bd.unavailable})"
    if c["tried"] >= MASSFAIL_MIN_TRIED and c["filled"] == 0:
        top = max((k for k in c if k.startswith("reason:")), key=c.__getitem__, default="reason:?")
        return f"jd-massfail({top[7:]} x{c[top]})"
    return ""


# --------------------------------------------------------------------------- inline
class JDFiller:
    """Fill a role's description before it is classified. Only for jobs that could plausibly
    be accepted (the cheap title gate first — never spend a fetch on a role we would reject on
    the title anyway), only within a wall-clock budget so a slow ATS cannot eat the digest's
    timeout, and never through Bright Data (the backfills own that)."""

    def __init__(self, budget_min=None, enabled=None):
        self.budget = float(os.environ.get("JDFILL_TIME_BUDGET_MIN", budget_min or 20))
        env = os.environ.get("JDFILL", "")
        self.enabled = (env == "1") if env else (True if enabled is None else enabled)
        self.t0 = time.time()
        self.filled = self.tried = self.skipped_budget = 0
        self.by_platform = Counter()        # (platform, reason) -> n
        self.via = Counter()

    def spent(self):
        return self.budget and (time.time() - self.t0) / 60 > self.budget

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
        if self.spent():
            self.skipped_budget += 1
            return False
        self.tried += 1
        jd = fetch_jd(url, company=job.get("company") or "")
        self.by_platform[(job.get("ats_platform") or "?", jd.reason)] += 1
        if jd.text:
            job["description"] = jd.text
            self.filled += 1
            self.via[jd.via] += 1
            return True
        return False

    def failures(self, n=6):
        worst = sorted(((k, v) for k, v in self.by_platform.items() if k[1] != "ok"),
                       key=lambda kv: -kv[1])[:n]
        return ", ".join(f"{p} {r} {v}" for (p, r), v in worst)

    def summary(self):
        out = f"jd-fill: {self.filled}/{self.tried} descriptions fetched inline"
        if self.via:
            out += " (" + ", ".join(f"{k} {v}" for k, v in self.via.most_common()) + ")"
        if self.tried > self.filled:
            out += "; failed: " + self.failures()
        if self.skipped_budget:
            out += f", {self.skipped_budget} skipped (budget {self.budget:g}m spent)"
        return out

    def alarms(self):
        """One line for the mail's bold `Stages:` line when the inline fill failed wholesale."""
        if self.tried >= MASSFAIL_MIN_TRIED and self.filled == 0:
            return [f"inline jd-fill {self.filled}/{self.tried} — every fetch failed ({self.failures(3)})"]
        return []


# --------------------------------------------------------------------------- the stamp
DRIVERS = ("scrape", "matched")      # each stamps `<name>_ran=1`; the gap-filler names the absent one


def record_enrich(alarm="", path=None, **counts):
    """Union-merge counts into TODAY's `enrich` stage stamp — two scripts, one stamp — replacing
    a stamp from another day. Called with no counts at all (the workflow's `if: always()`
    step) it only fills the gap: a driver that never stamped today => `alarm=no-report(<name>)`,
    and the stamp's `date` is NOT moved, so `Stage order:` still says when the layer last
    really ran. A bare `stages.stamp("enrich")` would erase the counts; that is why the
    workflow step calls this. `path` (or env `JD_STAGES_OUT`) redirects the stamp file — a
    rehearsal against a copy must not write the real one."""
    from . import stages
    path = path or os.environ.get("JD_STAGES_OUT")
    saved = stages.PATH
    if path:
        stages.PATH = path
    try:
        prev = stages._load().get("enrich") or {}
        today = dt.date.today().isoformat()
        fresh = prev.get("date") == today
        if not counts:
            missing = [d for d in DRIVERS if not (fresh and prev.get(f"{d}_ran"))]
            if not missing and not alarm:
                return prev
            keep = {k: v for k, v in prev.items() if k != "finished_at"} if fresh else {}
            if not fresh and prev.get("date"):
                keep["date"] = prev["date"]
            gap = f"no-report({','.join(missing)})" if missing and not alarm else ""
            alarms = [a for a in (keep.get("alarm"), alarm, gap) if a]
            keep["alarm"] = "; ".join(dict.fromkeys(alarms))
            stages.stamp("enrich", **keep)
            return stages._load().get("enrich") or {}
        merged = {k: v for k, v in prev.items() if fresh and k not in ("finished_at", "date")}
        merged.update(counts)
        # a real report supersedes the gap-filler's "no-report(...)"
        alarms = [a for a in (merged.get("alarm"), alarm) if a and not a.startswith("no-report")]
        merged.pop("alarm", None)
        if alarms:
            merged["alarm"] = "; ".join(dict.fromkeys(alarms))
        stages.stamp("enrich", **merged)
        return stages._load().get("enrich") or {}
    finally:
        stages.PATH = saved
