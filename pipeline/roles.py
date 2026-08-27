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
TAGS_V = 1                 # bump when roleprofile's vocabulary changes shape -> re-snapshot
CORRUPT_FRAC = 0.10        # more bad lines than this and the file is a wreck, not a ledger
MASS_CLOSE_MIN = 10        # closures/day above max(MIN, FRAC * open) are a broken fetch,
MASS_CLOSE_FRAC = 0.25     # not a measurement: statuses are held and the mail is told
REPOST_DAYS = 3            # the render rule (digest.py): posted_date jumped >=3d past first_seen
STATUSES = ("open", "closed", "superseded", "purged")
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


_STR_FIELDS = [c for c in CORE if c not in ("sources", "seen_ids")] + ["role_id", "closed_on", "emailed_on", "updated", "desc_sha1", "description"]
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


def dump(path, records):
    """Atomic, sorted, one line per role, keys sorted — the diff is the change."""
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
    return bool(_ISO.match(str(s or "")))


def _rowval(row, c):
    """A sqlite value in the ledger's shape (NULL -> "", lists sorted, no empties)."""
    v = row.get(c)
    return sorted(set(v or []) - {""}) if c in ("sources", "seen_ids") else (v or "")


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
    da, db = (row.get("description") or ""), (rec.get("description") or "")
    out["description"] = da if len(da) >= len(db) else db
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
        self.alarms = []
        self.claims = []                # "Winner<-Loser" strings

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
        recs = [r for r in self.records.values() if r.get("status") not in ("superseded", "purged")]
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
                    (_store.merge_key(j), (j.get("url") or "").strip()))
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
        _norm_never_ours = set(never_ours or ())
        sent = self.st.load_sent()
        c = Counter()
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
            if row.get("status") == "superseded":
                if rec.get("status") != "superseded":
                    rec["status"], rec["superseded_by"] = "superseded", row.get("superseded_by") or ""
                    self._touch(rec)
                continue
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
            if _norm_never_ours and _store._norm_company(rec.get("company")) in _norm_never_ours:
                if rec.get("status") != "purged":
                    rec["status"], rec["closed_on"] = "purged", run_date
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
        # the run log: this run LOOKED, whatever it found. `upsert_matched` counts these to
        # tell a role that was absent from four real runs from a role that was absent from no
        # run at all because the pipeline never fired (BACKLOG 139). Stamped here rather than
        # in run.py so a scoped local run stamps too — it did look, at what it was given.
        try:
            self.st.record_run_date(run_date)
        except Exception:                 # never let the log take the digest down
            pass
        if self.dirty or self.text_dirty:
            self.flush(run_date)
        ledger_n, store_n = len(self.records), len(rows)
        if ledger_n != store_n:
            self.alarms.append(f"roles ledger {ledger_n} != store {store_n} after sync")
        line = (f"open {c['open']} · closed today {c['closed_today']} · reopened {c['reopened']}"
                f" · reposted {c['reposted']}"
                + (f" · purged {c['purged']}" if c["purged"] else "")
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
                self.text = {k: v for k, v in self.text.items() if k in self.records}
                dump(self.text_path, self.text)
                self.text_dirty = False
            return True
        except Exception as e:  # noqa: BLE001
            self.alarms.append(f"roles ledger write failed: {e.__class__.__name__}: {str(e)[:80]}")
            return False


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
    except Exception:  # noqa: BLE001 — a bookkeeping mirror must never block delivery
        return 0
