#!/usr/bin/env python3
"""Put a third-party snapshot behind every posting we have seen (lane: infra, 2026-09-04).

Evidence decays faster than disputes settle: Taboola's Product Analyst posting 404'd on its
own board nine days after we last saw it, no cache held its text, and the wrong-employer and
wrong-location questions of 2026-09-01 would each have been settled by a neutral copy. The
repo already READS the Internet Archive (`pipeline/jdfill.py::wayback_snapshot`, the
`archive` rung of `enrich_matched_jd.py`, `wayback_rescue.py` on Sundays); this is the
writer. Every posting URL in the caches and the role store, plus the careers page of every
active scrape row on rotation, goes to Save Page Now -- one request every few seconds, under
a daily cap -- and one tiny line per attempt lands in `cloud_state/wayback_ledger.jsonl`: url,
date, HTTP result, snapshot timestamp. Never any page text: the text stays in the archive,
which is the point.

Two rungs (2026-09-16). AUTHENTICATED, the production one: `ARCHIVE_ORG_ACCESS_KEY` /
`ARCHIVE_ORG_SECRET_KEY` (repo secrets; `secrets.env` locally) open the SPN2 API --
`POST /save` answers a `job_id` in a second, `GET /save/status/<job_id>` ends in `success`
(the capture timestamp) or `error` (a `status_ext` word, kept in the ledger), so every job
has an end and `captured` is exact. The archive's own limits for an account (its document,
2026-09-16): 7 captures a minute, 3 concurrent jobs (`available` from `/save/status/user`,
read every run and never hard-coded), 30,000 a day, 5 a day per url, 2 minutes per capture.
ANONYMOUS, the fallback when the keys are absent or refused: a GET of `/save/<url>` whose
answer shape has changed four times since 2020 with no document, so that parser is layered
and the ledger says what it SAW -- a capture timestamp when a header or the redirect carried
one, `pending` when the archive said 200 and named no capture (looked up on CDX from the next
run on), and a class for every refusal. A run on this rung is never silent: the stamp's
alarm carries `unauthenticated: <why>` into the morning mail. Either way a failure today is
retryable tomorrow, never a verdict.

Two families of failure, and they mean different things (2026-09-15, over 768 ledger lines:
0 lines of the second family, and every "5 consecutive refusals" host park was the first).
ARCHIVE-SIDE is the archive failing to answer -- a connection error, a 5xx, a 429 -- and says
nothing about the address; a HOST REFUSAL is the archive answering that it will not take
THIS address. Only a refusal parks a host. An archive-side streak is the archive being down:
the day pauses for it (`OUTAGE_AFTER`, `OUTAGE_WAIT_S`), twice, then ends (`archive-down`),
and the stamp's `net` / `server` / `refused` say which of the two it was. A 429 gets the same
two pauses (its Retry-After, else five minutes). On the anonymous rung `pending` was a timeout
(271 of 271 lines by 09-15): neither family, and a night that names no capture is
`zero-produce` however many timeouts it "accepted". On the authenticated rung `pending` is a
job whose END this run could not read (the status endpoint failing for the whole ceiling) and
it carries its `job_id`, so the next run asks `/save/status/<job_id>` and gets the exact answer.

    python archive_evidence.py --dry-run      # the plan, no network, no ledger write
    python archive_evidence.py --limit 5      # a hand-sized real run
    python archive_evidence.py                # jd-archive.yml, 12:30 UTC, first step

Measured 2026-09-04 from this machine on the anonymous rung, seven submissions: the page is
taken within seconds of the request (13:14:16Z for a request sent at 13:14:1x) and the answer
is a 302 naming the capture -- after 18 s, or after 90 s and more, or a 520 at 37 s; a client
that hung up at 15 s still got its capture, indexed twenty minutes later. So on that rung a
submission waits `WAYBACK_TIMEOUT_S`, a timeout is recorded `pending` rather than failed (the
capture very probably exists; the next run asks the availability API). On the authenticated
rung the same seconds are the ceiling on polling one job (`POLL_S` apart; the archive's own
maximum is 2 minutes). Either way the day's captures run on a few threads behind one pace
gate, and the pace is 9 s because the archive allows an account 7 captures a minute.

Caps are environment variables so the workflow can tune them without a code change:
WAYBACK_DAY_CAP (postings), WAYBACK_BOARD_CAP, WAYBACK_REQ_CAP (requests, retries included,
status polls excluded), WAYBACK_VERIFY_CAP, WAYBACK_TIME_BUDGET_MIN, WAYBACK_PACE_S,
WAYBACK_TIMEOUT_S, WAYBACK_WORKERS (a ceiling: the account's `available` slots bind below it).
Never raises out of `main()`. Never prints a key: `_auth_headers` is the only place one is
read, and `_redact` runs over the crash line.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import dataclasses
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
SAVE = "https://web.archive.org/save/"           # the anonymous rung: GET /save/<url>
SAVE_API = "https://web.archive.org/save"        # the authenticated rung: POST, form body `url=` (the API document's form)
STATUS_URL = "https://web.archive.org/save/status/"   # + <job_id>, or `user` for the account's slots and daily count
AVAILABLE = "https://archive.org/wayback/available"
STAGE = "wayback"
ACCESS_KEY, SECRET_KEY = "ARCHIVE_ORG_ACCESS_KEY", "ARCHIVE_ORG_SECRET_KEY"
POLL_S = 10.0             # between two reads of one job's status; a capture takes 20-60 s, the archive's maximum is 2 min
# The archive's `status_ext` words (its SPN2 API document, read 2026-09-16) onto this ledger's
# classes. The two families of the docstring decide the side: a word about the ARCHIVE (its
# browser, its queue, its proxy) is `server` and feeds the outage streak; a word about the
# TARGET (what the page answered the archive's crawler) is the address's refusal. A word not
# in this table is `server`: a host is never parked on a word we do not know. Two corrections
# to what the words sound like: `too-many-daily-captures` is "this URL was captured 10 times
# today" (per url, `limit-url`), not the account's day; `no-access` is the target's 403, not
# our keys -- the keys being refused is an HTTP 401/403 to the POST itself.
STATUS_EXT = {
    "internal-server-error": "server", "celery": "server", "capture-location-error": "server",
    "no-browsers-available": "server", "job-failed": "server", "proxy-error": "server",
    "soft-time-limit-exceeded": "server", "cannot-fetch": "server", "max-daily-bandwidth-host": "server",
    "blocked-client-ip": "server",
    "user-session-limit": "throttled",
    "max-daily-bandwidth": "daily-limit", "max-daily-bandwidth-from-ip": "daily-limit",
    "too-many-daily-captures": "limit-url",
    "blocked-url": "excluded",
    "blocked": "blocked", "too-many-requests": "blocked",
    "not-found": "http", "no-access": "http", "unauthorized": "http", "bad-request": "http",
    "bad-gateway": "http", "service-unavailable": "http", "gateway-timeout": "http", "read-timeout": "http",
    "invalid-host-resolution": "http", "invalid-server-response": "http", "protocol-error": "http",
    "too-many-redirects": "http", "browsing-timeout": "http", "filesize-limit": "http",
    "invalid-url-syntax": "http", "bandwidth-limit-exceeded": "http", "method-not-allowed": "http",
    "not-implemented": "http", "http-version-not-supported": "http", "network-authentication-required": "http",
    "ftp-access-denied": "http",
}

BOARD_DAYS = 7            # a careers page is due again after a week; at 25 a day over ~530 pages the lap is ~3 weeks
DISCOVERY_DAYS = 21       # the same cut `fetchers.fetch_discovery` reads the cache with
PENDING_DAYS = 3          # a 200 with no capture is looked up on CDX for this long
MAX_ATTEMPTS = 4          # past this a URL waits COOLDOWN_TIRED days, and is still retried
COOLDOWN = {"soft": 1, "hard": 7, "excluded": 30}
COOLDOWN_TIRED = 30
# The two families (module docstring). A `throttled` line is the archive's per-IP block, so it
# is the archive's, not the host's; `pending` (a timeout) and `unverified` are in neither set:
# a timeout is unread, and an unverified capture is the target refusing the archive's crawler
# (149 of 206 by 09-15 were LinkedIn / Indeed / Comeet), which `read_ledger` counts as a
# refusal of that address.
ARCHIVE_SIDE = frozenset(["net", "server", "throttled"])
HOST_REFUSAL = frozenset(["http", "blocked", "excluded", "limit-url"])
OUTAGE_AFTER = 8          # consecutive archive-side REQUESTS that open a pause: fires on the five
#                           degraded nights of 09-04..09-15 (14, 19, 12, 50, 33 in a row) and on
#                           none of the seven others (max 5)
OUTAGE_WAIT_S = 90.0      # the pause; the third trigger of any kind ends the day
PAUSE_EPISODES = 2        # pauses a day, a 429 or an outage streak alike
SLOT_WAIT_S = 20.0        # keyed rung: a 429 with no Retry-After is "no free slot" (the archive's own words for a
#                           429: "delay any subsequent captures for 10 to 20 sec"); this thread waits, the day does not
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
    # the SPN2 POST's answer when the url was captured minutes ago: a `message`, no `job_id`,
    # and a capture that exists -- `cached`, the class the anonymous rung gives an
    # `X-Page-Cache: HIT`. Last, so a limit or a block in the same text wins.
    ("cached", re.compile(r"same snapshot had been made|captured \d+ (?:seconds?|minutes?) ago")),
)
SUCCESS = frozenset(["", "cached", "verified"])
SOFT = frozenset(["throttled", "server", "net", "blocked", "unverified", "limit-url", "daily-limit"])


def _family(err: str) -> str:
    return str(err or "").split(":", 1)[0]


@dataclass
class Caps:
    day: int = 100
    boards: int = 25
    requests: int = 140
    verify: int = 40
    time_min: float = 30.0
    pace_s: float = 9.0            # 60 / 7: the archive allows an account 7 captures a minute (its document, 2026-09-16)
    timeout_s: float = 150.0       # keyed: the ceiling on polling one job (the archive's maximum is 2 min); anon: the read timeout, a timeout is `pending`
    workers: int = 6               # a CEILING; the account's `available` slots (3 on 2026-09-16) bind below it. The pace gate is shared, so 7/min holds whatever the count
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
    job_id: str = ""       # the SPN2 job (authenticated rung); written only when set
    status_ext: str = ""   # the archive's own word for an `error` end; written only when set

    def dumps(self) -> str:
        # the two optional fields are omitted when empty: an anonymous-rung line is byte for
        # byte the 2026-09-04 shape, and every reader uses `.get`
        d = {k: v for k, v in self.__dict__.items() if v or k not in ("job_id", "status_ext")}
        return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Result:
    http: int
    snap: str
    err: str
    retry_after: float = 0.0
    job_id: str = ""
    status_ext: str = ""
    polls: int = 0             # status reads this result cost (authenticated rung); not requests


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
    captured: int = 0          # the archive NAMED a capture (a 302 / header, or `cached`); `submitted` also counts timeouts
    net: int = 0               # recorded lines by family -- the split the mail needs to tell "archive down" from "we are blocked"
    server: int = 0
    refused: int = 0
    stop: str = ""             # why the day ended early: throttled | archive-down | daily-limit | unauthenticated
    alarm: str = ""
    auth: str = "anon"         # `keyed` (the SPN2 API) or `anon` (the GET fallback) -- rendered in `Stage order:`
    jobs: int = 0              # SPN2 jobs the archive opened for us
    polls: int = 0             # status reads; never in `requests`, which bounds captures + verifications
    lines: list = field(default_factory=list)

    def counters(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("lines", "alarm", "stop")}
        if self.stop:
            d["stop"] = self.stop
        if self.alarm:
            d["alarm"] = self.alarm
        return d

    def add_alarm(self, clause: str) -> None:
        """Clauses compose, `; `-joined and deduplicated: an unauthenticated zero night reads
        `unauthenticated: ...; zero-produce: ...` in the mail, not whichever was set first
        (three workers can each hit the daily limit; the mail must not say it three times)."""
        clause = (clause or "").strip()
        if clause and clause not in self.alarm.split("; "):
            self.alarm = (self.alarm + "; " + clause) if self.alarm else clause

    def tally(self, err: str) -> None:
        """One failed line's family into the split the mail reads."""
        fam = _family(err)
        if fam == "net":
            self.net += 1
        elif fam == "server":
            self.server += 1
        elif fam in HOST_REFUSAL:
            self.refused += 1

    def split(self) -> str:
        return (f"net {self.net}, server {self.server}, refused {self.refused}"
                + (f", stopped {self.stop}" if self.stop else ""))

    def line(self) -> str:
        return (f"[wayback] submitted {self.submitted}, failed {self.failed}, backlog {self.backlog}, "
                f"boards {self.boards} (of {self.boards_due} due), verified {self.verified}, "
                f"throttled {self.throttled}, requests {self.requests}, captured {self.captured}, "
                + self.split()
                + (f", host parked {self.host_parked}" if self.host_parked else "")
                + (f", jobs {self.jobs}, polls {self.polls}" if self.auth == "keyed" else "")
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
    """url -> the latest state: `attempts` (every line but a `verified`), `refusals` (the
    attempts the archive answered about THIS address: a host refusal or `unverified` --
    never a connection error, a 5xx, a 429 or a timeout, which are the archive's), `last_at`,
    `last_err`, `ok_at` (the newest successful capture's date), `pending_at` (an unverified
    200 awaiting CDX)."""
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
        s = state.setdefault(rec["url"], {"attempts": 0, "refusals": 0, "last_at": "", "last_err": "",
                                          "ok_at": "", "pending_at": "", "job_id": "", "kind": rec.get("kind") or "posting"})
        err = str(rec.get("err") or "")
        at = str(rec.get("at") or "")[:10]
        if err == "verified":                     # a CDX confirmation, not an attempt
            s["ok_at"], s["pending_at"], s["last_err"], s["job_id"] = at, "", "", ""
            continue
        s["attempts"] += 1
        if _family(err) in HOST_REFUSAL or err == "unverified":
            s["refusals"] += 1
        s["last_at"], s["last_err"] = at, err
        # the job whose end was not read (authenticated rung): the next run asks its status
        s["job_id"] = str(rec.get("job_id") or "") if err == "pending" else ""
        if err in SUCCESS and (rec.get("snap") or err == "cached"):
            s["ok_at"], s["pending_at"] = at, ""
        elif err == "pending":
            s["pending_at"] = at
        else:
            s["pending_at"] = ""
    return state


def cooldown_days(err: str, refusals: int, attempts: int = 0) -> int:
    """Days before an address is due again. Tired (30 days) after MAX_ATTEMPTS REFUSALS --
    the archive's own failures do not count, or a fortnight of outages would have retired
    every address it touched (160 of 483 uncaptured urls had only archive-side lines on
    09-15) -- or after three times that many attempts of any kind, so an address the
    archive specifically cannot take (a 5xx on one huge page) is not asked every day for
    ever."""
    err = _family(err)
    if refusals >= MAX_ATTEMPTS or attempts >= 3 * MAX_ATTEMPTS:
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
    return _days(today, s["last_at"]) >= cooldown_days(s["last_err"], s["refusals"], s["attempts"])


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


def interleave(postings: list, boards: list) -> list:
    """The day's send order: a board after every `len(postings) // len(boards)` postings
    (150 / 25 is one in six), leftovers of either kind at the tail. Boards queued behind
    every posting read `boards 0 (of ~595 due)` on every night from 09-04 to 09-15,
    because the day ends before the postings do."""
    if not boards:
        return list(postings)
    if not postings:
        return list(boards)
    every = max(1, len(postings) // len(boards))
    out, b = [], 0
    for i, p in enumerate(postings, 1):
        out.append(p)
        if i % every == 0 and b < len(boards):
            out.append(boards[b])
            b += 1
    out.extend(boards[b:])
    return out


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


def _exc_result(e: BaseException, on_timeout: str) -> Result:
    """A network error as a ledger class: `on_timeout` for a timeout (the anonymous rung's
    `pending`; the keyed rung's `net:TimeoutError`, because its POST answers in a second and
    a silence there is the archive not answering), else `net:<class>[:<reason class>]` --
    `net:URLError` said nothing 137 times (09-04..09-15); the reason's class does."""
    if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
        return Result(0, "", on_timeout)
    why = type(e.reason).__name__ if isinstance(e, urllib.error.URLError) and e.reason is not None else ""
    return Result(0, "", "net:" + type(e).__name__ + (":" + why if why else ""))


def _submit_anon(url: str, timeout: float = 60.0) -> Result:
    """The anonymous rung: one GET of `/save/<url>`; never raises. The response arrives a
    minute or more after the capture, so a read timeout is `pending` -- the archive may hold
    the capture, and the next run asks it -- while an error before the request could be sent
    is `net:<class>`, retried."""
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
        return _exc_result(e, "pending")


# ------------------------------------------------------------------ the authenticated rung
@dataclass(frozen=True)
class Auth:
    """The account, or the reason there is none. `why` is "" when keyed -- and "" on a bare
    `Auth()` too, which is how a test asks for the anonymous rung WITHOUT the alarm clause;
    `from_env` never returns that: no keys is always a `why`."""
    access: str = ""
    secret: str = ""
    why: str = ""

    @property
    def keyed(self) -> bool:
        return bool(self.access and self.secret)

    @classmethod
    def from_env(cls, env=None) -> "Auth":
        env = os.environ if env is None else env
        a, s = (env.get(ACCESS_KEY) or "").strip(), (env.get(SECRET_KEY) or "").strip()
        if a and s:
            return cls(a, s)
        missing = ", ".join(k for k, v in ((ACCESS_KEY, a), (SECRET_KEY, s)) if not v)
        return cls("", "", f"no keys ({missing} unset)")


def _auth_headers(auth: Auth) -> dict:
    """The only place a key is read into a request. Never logged: `_redact` covers the one
    print that carries free text (the crash line)."""
    return {"User-Agent": UA, "Accept": "application/json", "Authorization": f"LOW {auth.access}:{auth.secret}"}


def _redact(text: str, env=None) -> str:
    env = os.environ if env is None else env
    out = str(text)
    for k in (ACCESS_KEY, SECRET_KEY):
        v = (env.get(k) or "").strip()
        if v:
            out = out.replace(v, "***")
    return out


def _json_call(req, timeout: float):
    """(HTTP status, the JSON answer or None, a Result or None). The Result is set when the
    call itself failed -- a non-2xx (429 `throttled` with its Retry-After, 5xx `server`, 4xx
    `http`) or a network error (`net:<class>`, a timeout included: the POST answers in a
    second) -- so the two families are the same on both rungs. A non-2xx still yields its JSON
    when it carried one (a `message` about the account rides on a 4xx)."""
    try:
        with _open(req, timeout) as r:
            status = int(getattr(r, "status", None) or r.getcode())
            raw = r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            try:
                raw = e.read(200_000).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                raw = ""
            return int(e.code), _json_or_none(raw), classify(int(e.code), e.headers, "", "")
        finally:
            try:
                e.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        return 0, None, _exc_result(e, "net:TimeoutError")
    return status, _json_or_none(raw), None


def _json_or_none(raw: str):
    try:
        data = json.loads(raw or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _body_class(text: str) -> str:
    """The BODY_CLASSES word for a refusal the archive wrote as prose, "" when none."""
    low = (text or "").lower()
    for cls, rx in BODY_CLASSES:
        if rx.search(low):
            return cls
    return ""


def _classify_job(data, http: int = 200, job_id: str = "") -> Result:
    """A `/save/status/<job_id>` answer (or a POST's answer that carried no job) as a
    ledger class. `success` names the capture; `error` is the archive's `status_ext` word
    through STATUS_EXT; `pending` is the job still running; a bare `message` is prose the
    archive wrote instead of a job -- "same snapshot had been made 3 minutes ago" (`cached`),
    a limit -- and an unreadable answer is the archive's (`server`), never the address's."""
    d = data if isinstance(data, dict) else {}
    jid = str(d.get("job_id") or job_id or "")
    st = str(d.get("status") or "")
    if st == "success":
        ts = str(d.get("timestamp") or "")
        ts = ts if ts.isdigit() and len(ts) == 14 else _ts(d.get("timestamp"))
        return Result(http, ts, "" if ts else "pending", job_id=jid, status_ext="" if ts else "success-no-timestamp")
    if st == "error":
        word = str(d.get("status_ext") or "error:unknown")
        return Result(http, "", STATUS_EXT.get(word.split(":", 1)[-1], "server"), job_id=jid, status_ext=word)
    if st == "pending":
        return Result(http, "", "pending", job_id=jid)
    msg = str(d.get("message") or "")
    if msg:
        cls = _body_class(msg)
        return Result(http, "", cls or "server", job_id=jid, status_ext="message:" + msg[:80])
    return Result(http, "", "server", job_id=jid, status_ext="unreadable")


def _poll(job_id: str, auth: Auth, timeout: float) -> Result:
    """Read one job to its end: POLL_S apart, the first read after one wait (a capture takes
    seconds; an immediate read is a wasted status request), bounded by the clock AND by a
    count (`timeout // POLL_S + 1`: a stubbed sleep under a real clock must not spin). A 429
    on a read waits its Retry-After and reads again -- it must NOT re-submit a job that is
    still running. A read the endpoint failed is skipped, not a verdict. Past the bound the
    job is `pending` WITH its id, and the next run asks for its end."""
    deadline = time.monotonic() + timeout
    n, last = 0, Result(200, "", "pending", job_id=job_id)
    for n in range(1, int(timeout // POLL_S) + 2):
        _sleep(min(POLL_S, max(0.0, deadline - time.monotonic())))
        req = urllib.request.Request(STATUS_URL + job_id, headers=_auth_headers(auth))
        status, data, err = _json_call(req, 30.0)
        if err is not None and err.err == "throttled" and err.retry_after:
            _sleep(min(err.retry_after, max(0.0, deadline - time.monotonic())))
        elif data is not None and data.get("status"):
            last = _classify_job(data, 200, job_id)
            if last.err != "pending":
                break
        if time.monotonic() >= deadline:
            break
    last.polls = n
    return last


def _submit_job(url: str, timeout: float, auth: Auth) -> Result:
    """The authenticated rung: `POST /save` with the url in the body, then the job to its
    end. A 401/403 to the POST is OUR keys refused -- neither family, and nothing will
    succeed after it: `server` with `status_ext=unauthenticated`, which ends the day and
    puts the clause in the mail. The POST carries `url` only: no `capture_all` (an error
    page would mark the address done for ever with a 404 where a dispute needs the text),
    no `if_not_archived_within` (the ledger is the dedupe)."""
    body = urllib.parse.urlencode({"url": url}).encode("ascii")
    headers = dict(_auth_headers(auth), **{"Content-Type": "application/x-www-form-urlencoded"})
    req = urllib.request.Request(SAVE_API, data=body, headers=headers, method="POST")
    # The POST answers in a second from this machine and held for more than 30 s on the
    # runner 43 times in 154 requests on the first scheduled night (2026-09-16): the archive
    # holds the POST until a slot frees. Its wait is the job's ceiling, not a socket blip --
    # a 30-s cut-off turned a queued job into `net:TimeoutError`, a 15-s retry and a second
    # POST for the same url.
    status, data, err = _json_call(req, timeout)
    if status in (401, 403):
        return Result(status, "", "server", status_ext="unauthenticated")
    if err is not None:
        if data and data.get("message"):
            cls = _body_class(str(data["message"]))
            if cls:
                return Result(status, "", cls, status_ext="message:" + str(data["message"])[:80])
        return err
    if data and data.get("job_id"):
        res = _poll(str(data["job_id"]), auth, timeout)
        res.http = status
        return res
    return _classify_job(data, status)


def submit(url: str, timeout: float = 60.0, auth: Auth | None = None) -> Result:
    """One capture request, on the rung the keys allow. Never raises."""
    if auth is not None and auth.keyed:
        return _submit_job(url, timeout, auth)
    return _submit_anon(url, timeout)


def _user_status(auth: Auth, timeout: float = 30.0):
    """`GET /save/status/user`: the account's free `available` slots, `daily_captures` and
    `daily_captures_limit`. Not a capture request: never in `requests`."""
    return _json_call(urllib.request.Request(STATUS_URL + "user", headers=_auth_headers(auth)), timeout)


def _job_status(job_id: str, auth: Auth, timeout: float = 30.0):
    return _json_call(urllib.request.Request(STATUS_URL + job_id, headers=_auth_headers(auth)), timeout)


def _probe(auth: Auth, caps: Caps, rep: Report):
    """Read the account before the day is planned (the cap it lowers is the one `plan_batch`
    reads). Keyed: workers = min(the ceiling, `available`), the day = min(the cap, what the
    account has left). No keys, or the archive refusing them: the anonymous rung with the
    `unauthenticated` clause in the alarm -- loud, never silent. The endpoint failing
    (5xx, a network error) is NOT the keys failing: keyed, the ceiling's workers, printed.
    Returns (the auth to run with, `daily_captures` before the run or None)."""
    if not auth.keyed:
        rep.auth = "anon"
        if auth.why:
            rep.add_alarm("unauthenticated: " + auth.why)
            print(f"[wayback] UNAUTHENTICATED: {auth.why} -- anonymous rung", flush=True)
        return auth, None
    status, data, err = _user_status(auth)
    if status in (401, 403):
        why = f"the archive answered {status} to /save/status/user (keys refused)"
        rep.auth = "anon"
        rep.add_alarm("unauthenticated: " + why)
        print(f"[wayback] UNAUTHENTICATED: {why} -- anonymous rung", flush=True)
        return Auth("", "", why), None
    rep.auth = "keyed"
    if not isinstance(data, dict) or "available" not in data:
        print(f"[wayback] authenticated, but /save/status/user answered {status} "
              f"{err.err if err else 'unreadable'}: {caps.workers} workers, day cap {caps.day} kept", flush=True)
        return auth, None
    avail = int(data.get("available") or 0)
    used = int(data.get("daily_captures") or 0)
    lim = int(data.get("daily_captures_limit") or 0)
    caps.workers = max(1, min(caps.workers, avail))
    if lim:
        if lim - used <= 0:
            caps.day = caps.boards = 0
            rep.stop = "daily-limit"
            rep.add_alarm(f"daily-limit: the account's {lim} captures were spent before this run")
        else:
            caps.day = min(caps.day, lim - used)
    print(f"[wayback] authenticated: {avail} slots, {used} of {lim} captures used today; "
          f"{caps.workers} workers, day cap {caps.day}", flush=True)
    return auth, used


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
def _now(today: dt.date | None = None) -> str:
    """The timestamp a ledger line carries. `today` is the RUN's date when the caller was
    given one, and the wall clock otherwise (which is every production path).

    Why the run's date matters: `read_ledger` folds `at` into `ok_at` / `pending_at`, and
    every cadence here is `_days(today, that)`. A run told `today=2026-09-05` that stamps its
    lines with the real clock produces NEGATIVE day-deltas the moment the real date passes
    the fixture's -- so a test written in September passed in September and started failing
    in October, having tested nothing about the code in between. The three-day-old pending
    line simply stopped being selected for verification and `verified` went to 0."""
    if today is not None:
        return f"{today.isoformat()}T12:00:00Z"
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

    def __init__(self, targets, ledger, out, rep, caps, started, budget_s, now=None, auth=None):
        self.queue = list(targets)
        self.ledger, self.out, self.rep, self.caps = ledger, out, rep, caps
        self.started, self.budget_s, self.now, self.auth = started, budget_s, now, auth
        self.lock = threading.Lock()
        self.next_send = 0.0
        self.stop = ""
        self.pause_at = None             # when the current pause (a 429 or an outage streak) began
        self.pause_wait = 0.0
        self.episodes = 0                # pauses so far; PAUSE_EPISODES is the day's allowance
        self.arch_streak = 0             # consecutive archive-side requests since the last real answer
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
            if now + wait - self.started > self.budget_s:
                return False                 # a pause that ends past the budget is not slept through and then sent
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
            res = self._submit(t)
            if _family(res.err) in ARCHIVE_SIDE and res.status_ext != "unauthenticated":   # our keys refused: no second ask
                res, sent = self._retry(t, res, sent)
            self.record(t, attempt, res, sent)

    def _submit(self, t: Target) -> Result:
        """One capture on the run's rung, its status reads counted where the stamp can
        show them (`jobs`, `polls`) -- here, because the first result of a retried pair
        never reaches `record`."""
        res = submit(t.url, self.caps.timeout_s, self.auth)
        with self.lock:
            self.rep.polls += res.polls
            if res.job_id:
                self.rep.jobs += 1
        return res

    def _pause(self, sent: float, wait: float, reason: str) -> float:
        """Under the lock. The day's one pause primitive: a 429 (`throttled`, the archive's
        per-IP block, its Retry-After or five minutes) and an archive-side streak
        (`archive-down`, OUTAGE_AFTER connection errors / 5xx in a row, OUTAGE_WAIT_S) both
        push every thread's next send past the pause. Returns the pause every thread now
        waits, or 0.0 when this trigger ENDS the day: the request was sent after the current
        pause had elapsed -- judged by send time, because three in-flight threads all see one
        block at once and a paused thread's own resend is not a new episode (wave 1) -- and
        the day's PAUSE_EPISODES are spent. One episode ended the day until 09-15, and on
        09-13/14/15 the resend after it was refused each night at 5 requests a minute."""
        if self.stop:
            return 0.0
        now = time.monotonic()
        if self.pause_at is not None and sent < self.pause_at + self.pause_wait:
            return self.pause_wait               # sent inside the current pause: the same episode
        if self.episodes >= PAUSE_EPISODES:
            self.stop = reason
            return 0.0
        self.episodes += 1
        self.pause_at, self.pause_wait = now, wait
        self.next_send = max(self.next_send, now + wait)
        self.arch_streak = 0
        print(f"[wayback] pause {self.episodes} of {PAUSE_EPISODES} ({reason}): {wait:.0f} s after "
              f"{self.rep.requests} requests (net {self.rep.net}, server {self.rep.server})", flush=True)
        return wait

    def _arch(self, sent: float) -> bool:
        """Under the lock. One archive-side REQUEST (a connection error or a 5xx) sent at
        `sent`. A request sent inside the current pause is not evidence about the archive
        after it (a thread already asleep in `slot()` sends on its old schedule). True when
        this one made the streak long enough to open a pause or end the day."""
        if self.pause_at is not None and sent < self.pause_at + self.pause_wait:
            return False
        self.arch_streak += 1
        if self.arch_streak < OUTAGE_AFTER:
            return False
        self._pause(sent, OUTAGE_WAIT_S, "archive-down")
        return True

    def _retry(self, t: Target, res: Result, sent: float):
        """Once, and only when the ARCHIVE failed (a refusal of the address is final for the
        day). A 429: every thread pauses for its Retry-After (else five minutes), and a 429 to
        a request sent after that pause opens the day's second pause, then ends the day. A
        connection error or 5xx: this thread waits 15 s -- unless it was the OUTAGE_AFTER-th
        in a row, when the archive is down and the pause is the retry. Returns the result to
        record and when it was sent.

        The account's 429 is a different animal (measured 2026-09-16, `--limit 20`): with
        three slots and three workers the archive answered 429 with NO Retry-After to the
        POST that followed a job's end -- its slot count lags a finished job (`available`
        read 2 after the run with nothing in flight) -- and the 300-s anonymous-block pause
        that answered it cost ten of the run's fifteen minutes, twice. So on the keyed rung a
        429 without a Retry-After is "no free slot": THIS thread waits SLOT_WAIT_S and asks
        once more, and only a second 429 in a row opens the day-wide pause (OUTAGE_WAIT_S,
        not five minutes). A 429 that names its Retry-After is the archive's word and pauses
        every thread for it, as before."""
        keyed = self.auth is not None and self.auth.keyed
        slot_wait = False
        with self.lock:
            if res.err == "throttled":
                self.rep.throttled += 1
                if keyed and not res.retry_after:
                    wait, slot_wait = SLOT_WAIT_S, True
                else:
                    wait = self._pause(sent, res.retry_after or self.caps.throttle_wait_s, "throttled")
                    if not wait:
                        return res, sent
            else:
                if self._arch(sent):
                    return res, sent
                wait = 15.0
            if time.monotonic() - self.started + wait > self.budget_s:
                return res, sent
        if res.err != "throttled" or slot_wait:
            _sleep(wait)
        if not self.slot():
            return res, sent
        sent = time.monotonic()
        res2 = self._submit(t)
        if res2.err == "throttled":
            with self.lock:
                self.rep.throttled += 1
                self._pause(sent, res2.retry_after or (OUTAGE_WAIT_S if keyed else self.caps.throttle_wait_s), "throttled")
        return res2, sent

    def record(self, t: Target, attempt: int, res: Result, sent: float = 0.0) -> None:
        with self.lock:
            self.out.append(_line(t, attempt, res, self.now), self.rep)
            fam = _family(res.err)
            if res.err in SUCCESS or res.err == "pending":
                if t.kind == "board":
                    self.rep.boards += 1
                else:
                    self.rep.submitted += 1
                if res.snap or res.err == "cached":
                    self.rep.captured += 1
                self.streak[t.host] = 0
                if res.err != "pending":             # a timeout is unread: it neither counts nor resets
                    self.arch_streak = 0
                return
            self.rep.failed += 1
            self.rep.tally(res.err)
            if res.status_ext == "unauthenticated":  # our keys refused mid-run: nothing after it can succeed
                self.stop = "unauthenticated"
                self.rep.add_alarm(f"unauthenticated: the archive answered {res.http} to a capture request (keys refused)")
            if fam in ARCHIVE_SIDE:                  # the archive's failure: the streak, never the host
                if fam != "throttled":               # a 429 had its own pause in `_retry`
                    self._arch(sent)
            else:
                self.arch_streak = 0
            if fam in HOST_REFUSAL:                  # only the archive's word about THIS address parks it
                self.streak[t.host] = self.streak.get(t.host, 0) + 1
                if self.streak[t.host] >= self.caps.host_park_after and t.host not in self.parked:
                    self.parked.add(t.host)
                    self.rep.host_parked += 1
                    print(f"[wayback] {t.host}: {self.streak[t.host]} consecutive refusals, parked for today", flush=True)
            if res.err == "daily-limit":
                self.stop = "daily-limit"
                self.rep.add_alarm("daily-limit: the archive refused further captures today"
                                   + (f" ({res.status_ext})" if res.status_ext else ""))

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
                self.rep.stop = self.stop
            self.rep.backlog += len(self.queue)
            self.queue = []


def run(root: str = ROOT, today: dt.date | None = None, caps: Caps | None = None,
        dry_run: bool = False, limit: int = 0, auth: Auth | None = None) -> Report:
    # A caller that names the day stamps the ledger with THAT day: every cadence here is a
    # difference against `today`, so a line dated by the wall clock in a run dated otherwise
    # is a cadence measured against two different calendars (see `_now`). A production run
    # (no `today`) stamps each line when it is written: one `now` for the whole run gave
    # every line of a night the run's start time, and the ledger could not show that the
    # archive's failures come in runs of 12-50 (09-15; they were measured by line ORDER).
    now = _now(today) if today else None
    today = today or dt.date.today()
    caps = dataclasses.replace(caps or Caps.from_env())   # the probe lowers the caller's caps for this run only
    auth = auth or Auth.from_env()
    rep = Report()
    rep.auth = "keyed" if auth.keyed else "anon"
    started = time.monotonic()
    budget_s = caps.time_min * 60
    path = os.path.join(root, LEDGER)
    ledger = read_ledger(path)
    targets = collect_targets(root, today)
    used_before = None
    if not dry_run:                                  # BEFORE the plan: the cap it lowers is the one `plan_batch` reads
        auth, used_before = _probe(auth, caps, rep)
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
        #    A `pending` that carries a `job_id` (the authenticated rung, 2026-09-16) is a job
        #    whose end was not read: `/save/status/<job_id>` is asked first and is exact --
        #    `success` is `verified`, an `error` end is its own class (the archive's word,
        #    never `unverified`, which is a refusal of the address) -- and only a line with
        #    no id, or a status read that failed, takes the availability path.
        for url, s in pending:
            if time.monotonic() - started > budget_s or rep.requests >= caps.requests:
                break
            ts = None
            if s.get("job_id") and auth.keyed:
                status, data, _err = _job_status(s["job_id"], auth)
                rep.requests += 1
                if isinstance(data, dict) and data.get("status") in ("success", "error"):
                    res = _classify_job(data, status or 200, s["job_id"])
                    if res.err:
                        out.append(Line(now or _now(), url, s["kind"], 0, s["attempts"], res.http, "", res.err,
                                        res.job_id, res.status_ext), rep)
                        rep.failed += 1
                        rep.tally(res.err)
                        _sleep(caps.pace_s)
                        continue
                    ts = res.snap
            if ts is None:
                ts = capture_since(url, s["pending_at"])
                rep.requests += 1
            if ts:
                rep.verified += 1
                out.append(Line(now or _now(), url, s["kind"], 0, s["attempts"], 200, ts, "verified"), rep)
            elif _days(today, s["pending_at"]) >= PENDING_DAYS:
                out.append(Line(now or _now(), url, s["kind"], 0, s["attempts"], 200, "", "unverified"), rep)
            _sleep(caps.pace_s)
        # 2. the day's captures, boards one in six so an early end still reaches them
        _Pool(interleave(postings, boards), ledger, out, rep, caps, started, budget_s, now, auth=auth).run()
    finally:
        out.close()
    if rep.auth == "keyed" and used_before is not None:
        # the same read after the day: the morning check compares this delta to `jobs` (the
        # archive counts every job it opened, an error end included)
        status, data, err = _user_status(auth)
        if isinstance(data, dict) and "daily_captures" in data:
            used = int(data.get("daily_captures") or 0)
            print(f"[wayback] authenticated: {int(data.get('available') or 0)} slots, {used} of "
                  f"{int(data.get('daily_captures_limit') or 0)} captures used today (+{used - used_before} this run)", flush=True)
        else:                                        # never silent: the first night's line was simply absent
            print(f"[wayback] authenticated: the account could not be re-read after the day "
                  f"({status or 'net'} {err.err if err else 'unreadable'})", flush=True)
    # `captured`, not `submitted`: a night of timeouts "accepted" 64 and named 0 (09-12), and
    # 37 of those were `unverified` three days later. The token is what the mail check greps,
    # and it composes with the clauses above it (`add_alarm`) rather than yielding to them.
    if rep.captured == 0 and (postings or boards):
        rep.add_alarm(f"zero-produce: 0 named of {len(postings) + len(boards)} planned "
                      f"(accepted {rep.submitted + rep.boards}, {rep.split()})")
    return rep


def _line(t: Target, attempt: int, res: Result, now: str = "") -> Line:
    return Line(now or _now(), t.url, t.kind, t.tier, attempt, res.http, res.snap, res.err, res.job_id, res.status_ext)


def _report(rep: Report, dry_run: bool) -> None:
    print(rep.line(), flush=True)
    if dry_run:
        return
    stages.stamp(STAGE, **rep.counters())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"- wayback: **{rep.submitted} postings** + {rep.boards} boards accepted, "
                        f"{rep.captured} named, {rep.failed} failed ({rep.split()}), {rep.backlog} left for tomorrow, {rep.verified} verified"
                        + (f", **alarm:** {rep.alarm}" if rep.alarm else "") + "\n")
        except OSError:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="plan and print; no request, no ledger line")
    ap.add_argument("--limit", type=int, default=0, help="at most N captures this run")
    ap.add_argument("--root", default=ROOT, help="repo root (the caches and the ledger)")
    a = ap.parse_args(argv)
    if not a.dry_run:
        # the one loader (`pipeline/secretsenv`): the repo root's `secrets.env` locally, the
        # repo secrets on a runner, `AJIL_SECRETS=<path>` from a worktree. Here and not in
        # `run()`: a test's `run()` must never load the operator's file.
        from pipeline import secretsenv
        secretsenv.load(ROOT)
    try:
        rep = run(a.root, dry_run=a.dry_run, limit=a.limit)
    except Exception as e:  # noqa: BLE001 - a crash is a stamped alarm, never a silent step
        print(f"[wayback] CRASHED: {type(e).__name__}: {_redact(str(e)[:200])}", flush=True)
        if not a.dry_run:
            stages.stamp(STAGE, submitted=0, failed=0, backlog=-1, alarm=f"crashed:{type(e).__name__}")
        return 1
    _report(rep, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
