#!/usr/bin/env python3
"""Put a third-party snapshot behind every posting we have seen (lane: infra, 2026-09-04).

Evidence decays faster than disputes settle: Taboola's Product Analyst posting 404'd on its
own board nine days after we last saw it, no cache held its text, and the wrong-employer and
wrong-location questions of 2026-09-01 would each have been settled by a neutral copy. The
repo already READS the Internet Archive (`pipeline/jdfill.py::wayback_snapshot`, the
`archive` rung of `enrich_matched_jd.py`, `wayback_rescue.py` on Sundays); this is the
writer. Every posting URL in the caches and the role store, plus the careers page of every
active scrape row on rotation, goes to Save Page Now (`https://web.archive.org/save/`)
-- anonymously, one request every few seconds, under a daily cap -- and one tiny line per
attempt lands in `cloud_state/wayback_ledger.jsonl`: url, date, HTTP result, snapshot
timestamp. Never any page text: the text stays in the archive, which is the point.

What the archive answers to an anonymous GET has changed four times since 2020 and there is
no document for it, so the result parser is layered and the ledger says what it SAW: a
capture timestamp when a header or the redirect carried one, `pending` when the archive said
200 and named no capture (looked up on CDX from the next run on), and a class for every
refusal, each with a cooldown -- a failure today is retryable tomorrow, never a verdict.

    python archive_evidence.py --dry-run      # the plan, no network, no ledger write
    python archive_evidence.py --limit 5      # a hand-sized real run
    python archive_evidence.py                # jd-archive.yml, 12:30 UTC, first step

Measured 2026-09-04 from this machine, seven submissions: the page is taken within seconds
of the request (13:14:16Z for a request sent at 13:14:1x) and the answer is a 302 naming the
capture -- after 18 s, or after 90 s and more, or a 520 at 37 s; a client that hung up at
15 s still got its capture, indexed twenty minutes later. So a submission waits 60 s, a
timeout is recorded `pending` rather than failed (the capture very probably exists; the
next run asks the availability API), and the day's captures run on a few threads behind
one pace gate.

Caps are environment variables so the workflow can tune them without a code change:
WAYBACK_DAY_CAP (postings), WAYBACK_BOARD_CAP, WAYBACK_REQ_CAP (requests, retries included),
WAYBACK_VERIFY_CAP, WAYBACK_TIME_BUDGET_MIN, WAYBACK_PACE_S, WAYBACK_TIMEOUT_S. Never raises
out of `main()`.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# The browser UA `pipeline/http.py` sends everywhere, for the reason it states there: no
# self-identifying suffix. SPN re-uses the submitter's User-Agent against the target page,
# so this is also what LinkedIn and Indeed see. Nothing else goes in the request.
from pipeline.http import _UA as UA
from pipeline import stages

ROOT = os.path.dirname(os.path.abspath(__file__))
LEDGER = "cloud_state/wayback_ledger.jsonl"
SAVE = "https://web.archive.org/save/"
AVAILABLE = "https://archive.org/wayback/available"
STAGE = "wayback"

BOARD_DAYS = 7            # a careers page is due again after a week; at 25 a day over ~530 pages the lap is ~3 weeks
DISCOVERY_DAYS = 21       # the same cut `fetchers.fetch_discovery` reads the cache with
PENDING_DAYS = 3          # a 200 with no capture is looked up on CDX for this long
MAX_ATTEMPTS = 4          # past this a URL waits COOLDOWN_TIRED days, and is still retried
COOLDOWN = {"soft": 1, "hard": 7, "excluded": 30}
COOLDOWN_TIRED = 30
TS = re.compile(r"/web/(\d{14})")
# Tracking parameters only. `jk=` (Indeed), `gh_jid=` (Greenhouse embeds) and `token=` are
# the address, and are kept.
TRACKING = re.compile(r"^(utm_.*|_l|refId|trackingId|ref|src|gh_src|lever-source|source)$", re.I)
# A refusal the archive serves as a 200 HTML page (spn.sh, the browser extension, the SPN2
# `status_ext` list). Matched on the body, lower-cased.
BODY_CLASSES = (
    ("daily-limit", re.compile(r"daily not-logged-in captures limit|cannot make more than \d+ captures per day|reached your daily")),
    ("limit-url", re.compile(r"(?:already been|been already) captured \d+ times")),
    ("excluded", re.compile(r"save page now service block list|has been excluded from the wayback machine|url has been excluded|blocked by robots")),
    ("blocked", re.compile(r"crawling this host is paused|http status=999|job failed|cannot start capture|live page is not available|facing some limitations")),
)
SUCCESS = frozenset(["", "cached", "verified"])
SOFT = frozenset(["throttled", "server", "net", "blocked", "unverified", "limit-url", "daily-limit"])


@dataclass
class Caps:
    day: int = 100
    boards: int = 25
    requests: int = 140
    verify: int = 40
    time_min: float = 30.0
    pace_s: float = 6.0
    timeout_s: float = 60.0        # the answer takes 18 s to minutes; a timeout is `pending`
    workers: int = 3               # concurrent captures; the pace gate is shared, so 15/min holds
    host_share: float = 0.6
    host_park_after: int = 5
    throttle_wait_s: float = 300.0     # the archive blocks an IP for five minutes at 15/min

    @classmethod
    def from_env(cls, env=None) -> "Caps":
        env = os.environ if env is None else env
        c = cls()
        for attr, key, cast in (("day", "WAYBACK_DAY_CAP", int), ("boards", "WAYBACK_BOARD_CAP", int),
                                ("requests", "WAYBACK_REQ_CAP", int), ("verify", "WAYBACK_VERIFY_CAP", int),
                                ("time_min", "WAYBACK_TIME_BUDGET_MIN", float),
                                ("pace_s", "WAYBACK_PACE_S", float),
                                ("timeout_s", "WAYBACK_TIMEOUT_S", float),
                                ("workers", "WAYBACK_WORKERS", int)):
            raw = (env.get(key) or "").strip()
            if raw:
                try:
                    setattr(c, attr, cast(raw))
                except ValueError:
                    print(f"[wayback] {key}={raw!r} is not a number; default kept", flush=True)
        return c


@dataclass(frozen=True)
class Target:
    url: str
    kind: str          # posting | board
    tier: int          # 1 the role store, 2 the discovery net, 3 the scrape corpus, 9 boards
    seen: str          # first sighting / posting date, "" when unknown (sorts last)
    open_role: bool = False

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.url).hostname or ""


@dataclass
class Line:
    at: str
    url: str
    kind: str
    tier: int
    attempt: int
    http: int
    snap: str
    err: str

    def dumps(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Result:
    http: int
    snap: str
    err: str
    retry_after: float = 0.0


@dataclass
class Report:
    submitted: int = 0
    failed: int = 0
    backlog: int = 0
    boards: int = 0
    boards_due: int = 0
    verified: int = 0
    throttled: int = 0
    requests: int = 0
    host_parked: int = 0
    alarm: str = ""
    lines: list = field(default_factory=list)

    def counters(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("lines", "alarm")}
        if self.alarm:
            d["alarm"] = self.alarm
        return d

    def line(self) -> str:
        return (f"[wayback] submitted {self.submitted}, failed {self.failed}, backlog {self.backlog}, "
                f"boards {self.boards} (of {self.boards_due} due), verified {self.verified}, "
                f"throttled {self.throttled}, requests {self.requests}"
                + (f", host parked {self.host_parked}" if self.host_parked else "")
                + (f" -- ALARM {self.alarm}" if self.alarm else ""))


# ------------------------------------------------------------------ addresses
def canon(url) -> str:
    """The ledger key: fragment dropped, tracking parameters dropped, scheme and host
    lower-cased, everything else as seen. `il.linkedin.com` and `www.linkedin.com` are
    different pages and stay distinct; the archive keys captures the same way."""
    u = str(url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return ""
    p = urllib.parse.urlsplit(u)
    if not p.hostname:
        return ""
    # the raw pairs, never decoded and re-encoded: `parse_qsl` + `urlencode` turned `%25`
    # into a bare `%` and `%2B` into a space, so the ledger key was not the address seen
    q = [part for part in p.query.split("&") if part and not TRACKING.match(part.split("=", 1)[0])]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", "&".join(q), ""))


def save_url(url: str) -> str:
    """The SPN address: non-ASCII and spaces percent-encoded, `?&=%` left raw so the
    archive sees the query as a query and a slug already encoded is not encoded twice."""
    return SAVE + urllib.parse.quote(url, safe="%:/?#[]@!$&'()*+,;=~-._")


def _copy_url(ident: str) -> str:
    """`linkedin:<id>` / `indeed:<jk>` -> the public address, via the one function that
    already knows both shapes (`jdfill.source_copy_url`); "" otherwise."""
    from pipeline.jdfill import source_copy_url
    return source_copy_url(ident) or ""


# ------------------------------------------------------------------ what we have seen
def collect_targets(root: str = ROOT, today: dt.date | None = None) -> dict:
    """Every address worth a snapshot, keyed by its canonical form, lowest tier wins.

    1 the role store (`cloud_state/roles.jsonl` own urls + every copy in `seen_ids`, and
      `matched.url`) -- what we publish is what gets disputed, open roles first;
    2 the discovery net (`discovered_cache.json`, inside the reader's 21-day cut) -- the
      aggregator copies are exactly the ones that vanish;
    3 the scrape corpus (`scraped_cache.json`, every card; a careers-page url is one target
      however many cards share it);
    boards: the careers page of every active scrape row, companies with an open role first.

    Arithmetic the caps imply (measured 2026-09-04): the discovery net alone adds ~124 new
    addresses a day against a 100-a-day cap, so tiers below it are reached only when the
    cap is raised (`WAYBACK_DAY_CAP`); the stamp's `backlog` is that number."""
    today = today or dt.date.today()
    out: dict = {}

    def add(url, kind, tier, seen="", open_role=False):
        key = canon(url)
        if not key:
            return
        cur = out.get(key)
        t = Target(key, kind, tier, str(seen or "")[:10], open_role)
        if cur is None or (t.tier, not t.open_role) < (cur.tier, not cur.open_role):
            out[key] = t

    open_companies = set()
    try:
        with open(os.path.join(root, "cloud_state", "roles.jsonl"), encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                is_open = rec.get("status") == "open"
                if is_open:
                    open_companies.add((rec.get("company") or "").strip().lower())
                seen = rec.get("first_seen") or ""
                add(rec.get("url"), "posting", 1, seen, is_open)
                for sid in rec.get("seen_ids") or []:
                    if not isinstance(sid, str) or ":" not in sid:
                        continue
                    tail = sid.split(":", 1)[1]
                    add(tail if tail.startswith("http") else _copy_url(tail), "posting", 1, seen, is_open)
    except OSError:
        pass
    db = os.path.join(root, "cloud_state", "seen.db")
    if os.path.exists(db):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(os.path.abspath(db)), uri=True)
            try:
                for url, first_seen in conn.execute("select url, coalesce(first_seen,'') from matched"):
                    add(url, "posting", 1, first_seen)
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"[wayback] matched store unreadable: {e}", flush=True)
    cut = (today - dt.timedelta(days=DISCOVERY_DAYS)).isoformat()
    for j in _load_json(os.path.join(root, "discovered_cache.json"), []):
        if not isinstance(j, dict):
            continue
        posted = str(j.get("posted_date") or "")[:10]
        if posted and posted < cut:            # the reader's rule: an empty date is kept
            continue
        add(j.get("url"), "posting", 2, posted)
    scraped = _load_json(os.path.join(root, "scraped_cache.json"), {})
    for jobs in (scraped.values() if isinstance(scraped, dict) else []):
        for j in (jobs if isinstance(jobs, list) else []):
            if isinstance(j, dict):
                add(j.get("url"), "posting", 3, j.get("posted_date") or "")
    try:
        with open(os.path.join(root, "companies.csv"), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("active") or "").strip().lower() == "true" and \
                        (row.get("ats_platform") or "").strip().lower() == "scrape":
                    name = (row.get("company_name") or "").strip().lower()
                    key = canon(row.get("api_url"))
                    if key and key not in out:      # a careers page already a posting target stays one
                        out[key] = Target(key, "board", 9, "", name in open_companies)
    except OSError:
        pass
    return out


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ the ledger
def read_ledger(path: str) -> dict:
    """url -> the latest state: `attempts`, `last_at`, `last_err`, `ok_at` (the newest
    successful capture's date), `pending_at` (an unverified 200 awaiting CDX)."""
    state: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except OSError:
        return state
    recs = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("url"):
            recs.append(rec)
    recs.sort(key=lambda r: str(r.get("at") or ""))
    for rec in recs:
        s = state.setdefault(rec["url"], {"attempts": 0, "last_at": "", "last_err": "", "ok_at": "",
                                          "pending_at": "", "kind": rec.get("kind") or "posting"})
        err = str(rec.get("err") or "")
        at = str(rec.get("at") or "")[:10]
        if err == "verified":                     # a CDX confirmation, not an attempt
            s["ok_at"], s["pending_at"], s["last_err"] = at, "", ""
            continue
        s["attempts"] += 1
        s["last_at"], s["last_err"] = at, err
        if err in SUCCESS and (rec.get("snap") or err == "cached"):
            s["ok_at"], s["pending_at"] = at, ""
        elif err == "pending":
            s["pending_at"] = at
        else:
            s["pending_at"] = ""
    return state


def cooldown_days(err: str, attempts: int) -> int:
    err = err.split(":", 1)[0]
    if attempts >= MAX_ATTEMPTS:
        return COOLDOWN_TIRED
    if err in SOFT:
        return COOLDOWN["soft"]
    if err == "excluded":
        return COOLDOWN["excluded"]
    return COOLDOWN["hard"]


def eligible(t: Target, s: dict | None, today: dt.date) -> bool:
    """May this address be submitted today? A posting once captured is done; a board is
    done for BOARD_DAYS; a pending 200 waits for CDX; a failure waits its cooldown."""
    if not s or (not s["attempts"] and not s["ok_at"]):
        return True                               # never tried
    if s["pending_at"]:
        return False
    if s["ok_at"]:
        if t.kind != "board":
            return False
        return _days(today, s["ok_at"]) >= BOARD_DAYS and (
            not s["last_at"] or s["last_at"] <= s["ok_at"] or
            _days(today, s["last_at"]) >= cooldown_days(s["last_err"], 0))
    return _days(today, s["last_at"]) >= cooldown_days(s["last_err"], s["attempts"])


def _days(today: dt.date, iso: str) -> int:
    try:
        return (today - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return 10 ** 6


RETRY_SHARE = 0.2         # of the day's postings, reserved for addresses refused before


def plan_batch(targets: dict, ledger: dict, today: dt.date, caps: Caps):
    """(postings, boards, backlog, boards_due). Fresh addresses first, oldest first within a
    tier, up to the day minus a reserved fifth; then every address refused before whose
    cooldown has passed, fewest attempts first; then more fresh ones if room is left. The
    reserve exists because fresh addresses outnumber the cap on every day measured, so
    "retries after every fresh one" was a retry that never came (wave 1). No host takes
    more than `host_share` of the day."""
    fresh, retry, boards = [], [], []
    for t in targets.values():
        s = ledger.get(t.url)
        if not eligible(t, s, today):
            continue
        if t.kind == "board":
            boards.append((not t.open_role, (s or {}).get("ok_at") or "", t.url, t))
        elif s and s["attempts"]:
            retry.append((s["attempts"], s["last_at"], t.url, t))
        else:
            fresh.append((t.tier, not t.open_role, t.seen or "9999", t.url, t))
    fresh.sort()
    retry.sort()
    boards.sort()
    per_host_cap = max(1, int(caps.day * caps.host_share + 0.999999))
    first = max(0, caps.day - max(1, int(caps.day * RETRY_SHARE)))
    chosen, per_host, deferred = [], {}, 0
    for row in fresh[:first] + retry + fresh[first:]:
        t = row[-1]
        if len(chosen) >= caps.day:
            deferred += 1
            continue
        if per_host.get(t.host, 0) >= per_host_cap:
            deferred += 1
            continue
        per_host[t.host] = per_host.get(t.host, 0) + 1
        chosen.append(t)
    return chosen, [b[-1] for b in boards[:caps.boards]], deferred, len(boards)


# ------------------------------------------------------------------ the wire
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx from `/save/` names the capture in `Location`; following it would download the
    playback (megabytes, and the playback rate bucket) for nothing."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _open(req, timeout):
    """The one socket seam; tests replace it. NOT `urllib.request.urlopen`: that would
    follow the redirect."""
    return _OPENER.open(req, timeout=timeout)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _ts(*values) -> str:
    """The capture timestamp a header names: the NEWEST in the first carrier that has one.
    A `Link` header lists every memento it knows, oldest first (wave 1: the first match was
    a 2020 capture recorded as today's)."""
    for v in values:
        found = TS.findall(str(v or ""))
        if found:
            return max(found)
    return ""


def classify(status: int, headers, body: str, final_url: str = "") -> Result:
    """What the archive said, as a ledger class. Pure: tests feed it every observed shape."""
    h = headers or {}
    get = (lambda k: h.get(k) or "") if hasattr(h, "get") else (lambda k: "")
    snap = _ts(get("Location"), get("Content-Location"), get("Link"), get("X-Cache-Key"), final_url)
    if get("X-Archive-Wayback-Runtime-Error") or get("X-Archive-Wayback-Liveweb-Error"):
        return Result(status, snap, "excluded")
    if status == 429:
        ra = get("Retry-After")
        return Result(status, "", "throttled", float(ra) if str(ra).strip().isdigit() else 0.0)
    if status >= 500:
        return Result(status, "", "server")
    if 300 <= status < 400:
        return Result(status, snap, "" if snap else "http")
    if status >= 400:
        return Result(status, "", "http")
    low = (body or "").lower()
    for cls, rx in BODY_CLASSES:
        if rx.search(low):
            return Result(status, "", cls)
    if str(get("X-Page-Cache")).upper().startswith("HIT"):
        return Result(status, snap, "cached")
    return Result(status, snap, "" if snap else "pending")


def submit(url: str, timeout: float = 60.0) -> Result:
    """One GET of `/save/<url>`; never raises. The response arrives a minute or more after
    the capture, so a read timeout is `pending` -- the archive may hold the capture, and the
    next run asks it -- while an error before the request could be sent is `net:<class>`,
    retried."""
    req = urllib.request.Request(save_url(url), headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with _open(req, timeout) as r:
            status = getattr(r, "status", None) or r.getcode()
            body = r.read(1_000_000).decode("utf-8", "replace") if status < 300 else ""
            return classify(int(status), r.headers, body, r.geturl())
    except urllib.error.HTTPError as e:          # every non-2xx, the un-followed 3xx included
        try:
            res = classify(int(e.code), e.headers, "", "")
        finally:
            try:
                e.close()
            except Exception:  # noqa: BLE001
                pass
        return res
    except Exception as e:  # noqa: BLE001 - a network error is a ledger line, not a crash
        if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            return Result(0, "", "pending")
        return Result(0, "", "net:" + type(e).__name__)


def capture_since(url: str, since: str, timeout: float = 30.0):
    """A 200 capture of exactly `url` dated on or after `since` (YYYY-MM-DD), from the
    availability API (`archive.org/wayback/available`, answered in a second where CDX took
    six and once timed out): the 14-digit timestamp, "" when the archive has none that
    recent, None when the lookup itself failed -- the same three-way answer as
    `jdfill.wayback_snapshot`, for the same reason (a blip is not a fact about the world)."""
    day = since.replace("-", "")[:8]
    q = "%s?url=%s&timestamp=%s235959" % (AVAILABLE, urllib.parse.quote(url, safe=""), day)
    req = urllib.request.Request(q, headers={"User-Agent": UA})
    try:
        with _open(req, timeout) as r:
            data = json.loads(r.read(200_000).decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return None
    closest = ((data.get("archived_snapshots") or {}).get("closest") or {}) if isinstance(data, dict) else {}
    ts = str(closest.get("timestamp") or "")
    return ts if ts.isdigit() and len(ts) == 14 and ts[:8] >= day else ""


# ------------------------------------------------------------------ the run
def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Ledger:
    def __init__(self, path, dry_run):
        self.path, self.dry_run, self.f = path, dry_run, None

    def append(self, line: Line, report: Report):
        report.lines.append(line)
        if self.dry_run:
            return
        if self.f is None:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.f = open(self.path, "a", encoding="utf-8")
        self.f.write(line.dumps() + "\n")       # one line, flushed: a SIGTERM keeps what ran
        self.f.flush()

    def close(self):
        if self.f:
            self.f.close()


class _Pool:
    """The day's captures over `caps.workers` threads sharing ONE pace gate, one request
    budget, one clock and one ledger. A capture can hold its connection for a minute or
    more (measured 2026-09-04: 18 s to 90 s+ for the 302 that names it), so one thread
    would land a few dozen a day. The archive allows a few concurrent anonymous captures
    and 15 requests a minute per IP; the gate spaces every send `pace_s` apart whatever
    the thread count."""

    def __init__(self, targets, ledger, out, rep, caps, started, budget_s):
        self.queue = list(targets)
        self.ledger, self.out, self.rep, self.caps = ledger, out, rep, caps
        self.started, self.budget_s = started, budget_s
        self.lock = threading.Lock()
        self.next_send = 0.0
        self.stop = ""
        self.throttle_at = None          # when the day's one throttle episode began
        self.throttle_wait = 0.0
        self.parked, self.streak = set(), {}

    def _exhausted(self) -> bool:
        return bool(self.stop) or time.monotonic() - self.started > self.budget_s \
            or self.rep.requests >= self.caps.requests

    def take(self):
        with self.lock:
            while self.queue:
                if self._exhausted():
                    return None
                t = self.queue.pop(0)
                if t.host in self.parked:
                    self.rep.backlog += 1
                    continue
                return t
            return None

    def slot(self) -> bool:
        """Reserve the next send under the lock, then wait for it outside; False when the
        day is over (stop, clock or budget). Reserving first is what makes `pace_s` hold
        across threads, and sleeping once (not polling) is what makes a stubbed clock in
        a test cost nothing (wave 1: a polled gate spun for 120 s under a no-op sleep)."""
        with self.lock:
            if self._exhausted():
                return False
            now = time.monotonic()
            wait = max(0.0, self.next_send - now)
            self.next_send = max(now, self.next_send) + self.caps.pace_s
            self.rep.requests += 1
        if wait > 0:
            _sleep(wait)
        return True

    def work(self) -> None:
        while True:
            t = self.take()
            if t is None:
                return
            if not self.slot():
                with self.lock:
                    self.rep.backlog += 1
                return
            attempt = (self.ledger.get(t.url) or {}).get("attempts", 0) + 1
            sent = time.monotonic()
            res = submit(t.url, self.caps.timeout_s)
            if res.err == "throttled" or res.err == "server" or res.err.startswith("net:"):
                res = self._retry(t, res, sent)
            self.record(t, attempt, res)

    def _throttled(self, sent: float) -> float:
        """Under the lock. 0.0 when a 429 to a request SENT at `sent` ends the day (it went
        out after the day's one pause had elapsed, so the block is back), else the pause
        every thread now waits. Three in-flight threads all see the same block at once --
        one episode, not two (wave 1: the second thread through the lock ended the day
        before anyone had paused; judged by arrival time, a paused thread's own resend
        looked like a second episode)."""
        self.rep.throttled += 1
        if self.throttle_at is not None and sent >= self.throttle_at + self.throttle_wait:
            self.stop = "throttled"
            return 0.0
        if self.throttle_at is None:
            self.throttle_at = time.monotonic()
            self.throttle_wait = self.caps.throttle_wait_s
            self.next_send = max(self.next_send, self.throttle_at + self.throttle_wait)
        return self.throttle_wait

    def _retry(self, t: Target, res: Result, sent: float) -> Result:
        """Once. A 429 is the archive's five-minute block on this IP (or its Retry-After):
        every thread pauses for it, and a 429 to a request sent after the pause ends the
        day. 5xx / a connection error: this thread waits 15 s."""
        with self.lock:
            if res.err == "throttled":
                if res.retry_after and self.throttle_at is None:
                    self.caps.throttle_wait_s = res.retry_after
                wait = self._throttled(sent)
                if not wait:
                    return res
            else:
                wait = 15.0
            if time.monotonic() - self.started + wait > self.budget_s:
                return res
        if res.err != "throttled":
            _sleep(wait)
        if not self.slot():
            return res
        sent = time.monotonic()
        res2 = submit(t.url, self.caps.timeout_s)
        if res2.err == "throttled":
            with self.lock:
                self._throttled(sent)
        return res2

    def record(self, t: Target, attempt: int, res: Result) -> None:
        with self.lock:
            self.out.append(_line(t, attempt, res), self.rep)
            if res.err in SUCCESS or res.err == "pending":
                if t.kind == "board":
                    self.rep.boards += 1
                else:
                    self.rep.submitted += 1
                self.streak[t.host] = 0
                return
            self.rep.failed += 1
            self.streak[t.host] = self.streak.get(t.host, 0) + 1
            if self.streak[t.host] >= self.caps.host_park_after and t.host not in self.parked:
                self.parked.add(t.host)
                self.rep.host_parked += 1
                print(f"[wayback] {t.host}: {self.streak[t.host]} consecutive refusals, parked for today", flush=True)
            if res.err == "daily-limit":
                self.stop = "daily-limit"
                self.rep.alarm = "daily-limit: the archive refused further anonymous captures today"

    def run(self) -> None:
        n = max(1, min(self.caps.workers, len(self.queue)))
        if n == 1:
            self.work()
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                for f in [ex.submit(self.work) for _ in range(n)]:
                    f.result()                   # a worker's crash is the run's crash
        with self.lock:
            if self.stop:
                print(f"[wayback] stopped: {self.stop}", flush=True)
            self.rep.backlog += len(self.queue)
            self.queue = []


def run(root: str = ROOT, today: dt.date | None = None, caps: Caps | None = None,
        dry_run: bool = False, limit: int = 0) -> Report:
    today = today or dt.date.today()
    caps = caps or Caps.from_env()
    rep = Report()
    started = time.monotonic()
    budget_s = caps.time_min * 60
    path = os.path.join(root, LEDGER)
    ledger = read_ledger(path)
    targets = collect_targets(root, today)
    postings, boards, rep.backlog, rep.boards_due = plan_batch(targets, ledger, today, caps)
    if limit:
        postings, boards = postings[:limit], boards[:max(0, limit - len(postings))]
    pending = sorted(((u, s) for u, s in ledger.items()
                      if s["pending_at"] and _days(today, s["pending_at"]) >= 1),
                     key=lambda us: (us[1]["pending_at"], us[0]))[:caps.verify]   # oldest first
    print(f"[wayback] {len(targets)} addresses known, {len(postings)} postings + {len(boards)} boards "
          f"planned, {rep.backlog} deferred, {len(pending)} pending verification"
          + (" (DRY RUN: no request, no ledger line)" if dry_run else ""), flush=True)
    if dry_run:
        for t in postings[:20] + boards[:5]:
            print(f"  tier {t.tier} {t.kind:7s} {t.seen or '-':10s} {t.url}")
        return rep

    out = _Ledger(path, dry_run)
    try:
        # 1. yesterday's timeouts and bare 200s: does the archive hold the capture? Its own
        #    endpoint, the same pace (the 15/min limit is per IP, not per endpoint), and a
        #    bound: after PENDING_DAYS a line the archive has not confirmed -- or could not
        #    be asked about -- goes back to the queue as `unverified` (wave 1: a failing
        #    lookup left `pending` as the one state nothing could leave).
        for url, s in pending:
            if time.monotonic() - started > budget_s or rep.requests >= caps.requests:
                break
            ts = capture_since(url, s["pending_at"])
            rep.requests += 1
            if ts:
                rep.verified += 1
                out.append(Line(_now(), url, s["kind"], 0, s["attempts"], 200, ts, "verified"), rep)
            elif _days(today, s["pending_at"]) >= PENDING_DAYS:
                out.append(Line(_now(), url, s["kind"], 0, s["attempts"], 200, "", "unverified"), rep)
            _sleep(caps.pace_s)
        # 2. the day's captures
        _Pool(postings + boards, ledger, out, rep, caps, started, budget_s).run()
    finally:
        out.close()
    if not rep.alarm and rep.submitted == 0 and rep.boards == 0 and (postings or boards):
        rep.alarm = f"zero-produce: 0 of {len(postings) + len(boards)} planned captures landed"
    return rep


def _line(t: Target, attempt: int, res: Result) -> Line:
    return Line(_now(), t.url, t.kind, t.tier, attempt, res.http, res.snap, res.err)


def _report(rep: Report, dry_run: bool) -> None:
    print(rep.line(), flush=True)
    if dry_run:
        return
    stages.stamp(STAGE, **rep.counters())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"- wayback: **{rep.submitted} postings** + {rep.boards} boards captured, "
                        f"{rep.failed} refused, {rep.backlog} left for tomorrow, {rep.verified} verified"
                        + (f", **alarm:** {rep.alarm}" if rep.alarm else "") + "\n")
        except OSError:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="plan and print; no request, no ledger line")
    ap.add_argument("--limit", type=int, default=0, help="at most N captures this run")
    ap.add_argument("--root", default=ROOT, help="repo root (the caches and the ledger)")
    a = ap.parse_args(argv)
    try:
        rep = run(a.root, dry_run=a.dry_run, limit=a.limit)
    except Exception as e:  # noqa: BLE001 - a crash is a stamped alarm, never a silent step
        print(f"[wayback] CRASHED: {type(e).__name__}: {str(e)[:200]}", flush=True)
        if not a.dry_run:
            stages.stamp(STAGE, submitted=0, failed=0, backlog=-1, alarm=f"crashed:{type(e).__name__}")
        return 1
    _report(rep, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
