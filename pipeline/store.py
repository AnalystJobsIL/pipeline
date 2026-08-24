"""Dedupe/seen store (SQLite, stdlib) + persistent LLM verdict cache.

Two separate dedup concerns, handled with two different keys:

1. Across-day "only show NEW postings" — keyed by a stable per-posting id
   `seen_id = "{ats_platform}:{job_id}"`. Every posting ever included in a digest is
   recorded here; a posting is NEW iff its seen_id is absent. Because it keys on the
   platform's own job id, a genuinely new opening (new id) re-alerts, while the same
   posting never alerts twice.

2. Cross-platform duplicate merge WITHIN one digest — keyed by `merge_key =
   normalized(company) + "|" + normalized(title)` (location-independent). Collapses e.g.
   a role that appears on both a company's Comeet and Ashby boards into one entry, while
   recording every contributing seen_id as sent so none of them re-appear tomorrow.

The LLM verdict cache lives in the same DB so `claude -p` is not re-invoked for a title
already judged on a previous day.
"""
from __future__ import annotations

import os
import re
import sqlite3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "state", "seen.db")

_SUFFIXES = re.compile(r"\s+(ltd|inc|llc|corp|co|gmbh|technologies|software|labs|group)\.?$", re.I)


def _norm(s):
    """Normalize for identity matching. Titles keep every word — 'Analytics Group Lead'
    and 'Analytics Lead' are different roles."""
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-z֐-׿]+", " ", s)
    return " ".join(s.split())


def _norm_company(s):
    """Company identity: additionally strip ONE trailing corporate suffix
    ('Acme Ltd' == 'Acme') but never mid-name ('Acme Labs' != 'Acme Group')."""
    return _norm(_SUFFIXES.sub("", (s or "").strip()))


def seen_id(job):
    """Stable per-posting identity for across-day dedup."""
    jid = str(job.get("job_id") or "").strip()
    if jid:
        return f"{job.get('ats_platform', '')}:{jid}"
    # Fallback when a platform gives no id: use the URL.
    return f"{job.get('ats_platform', '')}:{job.get('url', '')}"


def merge_key(job):
    """Location-independent identity to collapse cross-platform duplicates in a digest."""
    return f"{_norm_company(job.get('company'))}|{_norm(job.get('title'))}"


def merge_duplicates(jobs):
    """Collapse jobs sharing a merge_key into one canonical entry.

    Returns a list of merged jobs. Each merged job gains:
      - `seen_ids`: list of every contributing posting's seen_id (all marked sent)
      - `sources`: sorted list of distinct ats_platforms it appeared on
    The canonical fields come from the first-seen contributor, preferring one that has a
    real ISO posted_date and a url.
    """
    groups = {}
    order = []
    for j in jobs:
        k = merge_key(j)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(j)

    merged = []
    for k in order:
        members = groups[k]
        # canonical = prefer an entry with an ISO date, then one with a url, else first.
        canonical = sorted(
            members,
            key=lambda j: (
                0 if re.match(r"^\d{4}-\d{2}-\d{2}$", str(j.get("posted_date", ""))) else 1,
                0 if j.get("url") else 1,
            ),
        )[0]
        out = dict(canonical)
        out["seen_ids"] = sorted({seen_id(m) for m in members})
        out["sources"] = sorted({m.get("ats_platform", "") for m in members})
        merged.append(out)
    return merged


class SeenStore:
    """SQLite-backed store of sent postings + LLM verdict cache."""

    def __init__(self, path=DEFAULT_DB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sent (
                seen_id     TEXT PRIMARY KEY,
                company     TEXT,
                title       TEXT,
                location    TEXT,
                url         TEXT,
                first_sent  TEXT,
                last_seen   TEXT
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                title_key   TEXT PRIMARY KEY,
                verdict     INTEGER,
                updated     TEXT
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS company_info (
                company     TEXT PRIMARY KEY,
                summary     TEXT,
                updated     TEXT
            )""")
        # structured firmographics (pipeline/firmographics.py), one JSON record per company
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS firmographics (
                company     TEXT PRIMARY KEY,
                record      TEXT,
                updated     TEXT
            )""")
        # failure memory for firmographics research: permanently failing names (junk from
        # discovery, ambiguous names) must not capture the per-run research budget forever
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS firmo_failed (
                company     TEXT PRIMARY KEY,
                attempts    INTEGER,
                last        TEXT
            )""")
        # Full display record of every matched role, keyed by company|title, with the date
        # we FIRST saw it. Powers the rolling windows: email = first_seen within 48h,
        # board = first_seen within 14 days.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS matched (
                mkey        TEXT PRIMARY KEY,
                company     TEXT,
                title       TEXT,
                location    TEXT,
                url         TEXT,
                posted_date TEXT,
                seniority   TEXT,
                sources     TEXT,
                description TEXT,
                first_seen  TEXT,
                last_seen   TEXT
            )""")
        try:  # migration: carry posting ids so mark_sent gets real seen_ids
            self.conn.execute("ALTER TABLE matched ADD COLUMN seen_ids TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    # ---- seen/sent tracking -------------------------------------------------
    def is_sent(self, sid):
        cur = self.conn.execute("SELECT 1 FROM sent WHERE seen_id = ?", (sid,))
        return cur.fetchone() is not None

    def filter_new(self, merged_jobs):
        """Return only merged jobs where NONE of their seen_ids has been sent before."""
        new = []
        for j in merged_jobs:
            if not any(self.is_sent(sid) for sid in j.get("seen_ids", [seen_id(j)])):
                new.append(j)
        return new

    def mark_sent(self, merged_job, run_date):
        for sid in merged_job.get("seen_ids", [seen_id(merged_job)]):
            self.conn.execute(
                """INSERT INTO sent (seen_id, company, title, location, url, first_sent, last_seen)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(seen_id) DO UPDATE SET last_seen=excluded.last_seen""",
                (sid, merged_job.get("company"), merged_job.get("title"),
                 merged_job.get("location"), merged_job.get("url"), run_date, run_date),
            )
        self.conn.commit()

    def count_sent(self):
        return self.conn.execute("SELECT COUNT(*) FROM sent").fetchone()[0]

    # ---- LLM verdict cache --------------------------------------------------
    def load_llm_cache(self):
        cur = self.conn.execute("SELECT title_key, verdict FROM llm_cache")
        return {k: bool(v) for k, v in cur.fetchall()}

    def save_llm_cache(self, cache, run_date):
        """Write only NEW or CHANGED verdicts, so `updated` is the judgment date. Every row
        used to be upserted on every run (all 247 said 2026-08-24; verdict age unknowable)."""
        have = dict(self.conn.execute("SELECT title_key, verdict FROM llm_cache").fetchall())
        for k, v in cache.items():
            if not isinstance(v, bool):        # a verdict is True/False; "NO" would store as YES
                continue
            if k in have and have[k] == (1 if v else 0):
                continue
            self.conn.execute(
                """INSERT INTO llm_cache (title_key, verdict, updated) VALUES (?,?,?)
                   ON CONFLICT(title_key) DO UPDATE SET verdict=excluded.verdict,
                   updated=excluded.updated""",
                (k, 1 if v else 0, run_date),
            )
        self.conn.commit()

    # ---- company summaries ("what it does + how it earns money") ------------
    def load_company_info(self):
        cur = self.conn.execute("SELECT company, summary FROM company_info")
        return {c: s for c, s in cur.fetchall()}

    def save_company_info(self, info, run_date):
        for company, summary in info.items():
            self.conn.execute(
                """INSERT INTO company_info (company, summary, updated) VALUES (?,?,?)
                   ON CONFLICT(company) DO UPDATE SET summary=excluded.summary,
                   updated=excluded.updated""",
                (company, summary, run_date),
            )
        self.conn.commit()

    # ---- structured firmographics (sector/stage/size/business model) --------
    def load_firmographics(self):
        """Return {company: record_dict}; silently skips rows that fail to parse."""
        import json as _json
        cur = self.conn.execute("SELECT company, record FROM firmographics")
        out = {}
        for c, r in cur.fetchall():
            try:
                out[c] = _json.loads(r)
            except (ValueError, TypeError):
                continue
        return out

    def save_firmographics(self, records, run_date):
        import json as _json
        for company, rec in records.items():
            self.conn.execute(
                """INSERT INTO firmographics (company, record, updated) VALUES (?,?,?)
                   ON CONFLICT(company) DO UPDATE SET record=excluded.record,
                   updated=excluded.updated""",
                (company, _json.dumps(rec, ensure_ascii=False), run_date),
            )
        self.conn.commit()

    def load_firmo_failures(self):
        """Return {company: (attempts, last_iso_date)} of failed research attempts."""
        cur = self.conn.execute("SELECT company, attempts, last FROM firmo_failed")
        return {c: (a, l) for c, a, l in cur.fetchall()}

    def record_firmo_failure(self, company, run_date):
        self.conn.execute(
            """INSERT INTO firmo_failed (company, attempts, last) VALUES (?,1,?)
               ON CONFLICT(company) DO UPDATE SET attempts=attempts+1, last=excluded.last""",
            (company, run_date),
        )
        self.conn.commit()

    def revoke_firmo_failures(self, companies, run_date):
        """Undo TODAY's strikes for these names — used by the mass-failure guard when a
        whole run produced nothing (soft outage: exit-0 prose, broken tool grant), which
        is evidence about the infrastructure, not about 50 company names.

        For repeat-strike names, `last` must be pushed back out of the weekly gate window
        too — gating keys on `last` alone, so merely decrementing `attempts` would keep
        the whole retry cohort gated another 7 days on a run that proved nothing."""
        import datetime as _dt
        ungated = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=8)).isoformat()
        for c in companies:
            self.conn.execute(
                "DELETE FROM firmo_failed WHERE company=? AND last=? AND attempts<=1",
                (c, run_date))
            self.conn.execute(
                "UPDATE firmo_failed SET attempts=attempts-1, last=? WHERE company=? AND last=?",
                (ungated, c, run_date))
        self.conn.commit()

    # ---- matched roles (rolling windows for email 48h / board 2 weeks) ------
    def upsert_matched(self, job, run_date):
        """Insert a matched role (keyed by company|title).

        first_seen persists across daily re-sightings but RESETS when the role reappears
        after >3 days of absence (a genuinely new opening re-alerts). An ISO posted_date is
        never overwritten by a non-ISO one; sources and seen_ids are unioned.
        """
        mkey = merge_key(job)
        new_sources = set(job.get("sources") or [job.get("ats_platform", "")])
        new_sids = set(job.get("seen_ids") or [seen_id(job)])
        new_pd = str(job.get("posted_date") or "")
        prev = self.conn.execute(
            "SELECT sources, seen_ids, posted_date, last_seen FROM matched WHERE mkey=?",
            (mkey,)).fetchone()
        keep_first = False
        if prev:
            old_sources, old_sids, old_pd, old_last = prev
            new_sources |= set((old_sources or "").split("+")) - {""}
            new_sids |= set((old_sids or "").split("+")) - {""}

            def _iso(p):
                return len(p) == 10 and p[4:5] == "-"
            if _iso(str(old_pd or "")) and not _iso(new_pd):
                new_pd = old_pd                       # keep the better date
            try:
                import datetime as _d
                gap = (_d.date.fromisoformat(run_date)
                       - _d.date.fromisoformat(str(old_last))).days
            except (ValueError, TypeError):
                gap = 0
            keep_first = gap <= 3                     # reappeared quickly -> same opening
        # A description is knowledge we may have paid Bright Data for, and most list
        # endpoints (workday, smartrecruiters, bamboohr, microsoft) return NONE — so a
        # daily re-sighting used to overwrite a backfilled JD with "". Never downgrade:
        # only a longer, non-empty text replaces what is stored.
        new_desc = (job.get("description") or "").strip()[:6000]
        if prev and keep_first:
            self.conn.execute(
                """UPDATE matched SET location=?, url=?, posted_date=?, seniority=?,
                   sources=?, seen_ids=?,
                   description=CASE WHEN length(?) > length(COALESCE(description,''))
                                    THEN ? ELSE description END,
                   last_seen=? WHERE mkey=?""",
                (job.get("location"), job.get("url"), new_pd, job.get("seniority", ""),
                 "+".join(sorted(new_sources)), "+".join(sorted(new_sids)),
                 new_desc, new_desc, run_date, mkey))
        else:
            self.conn.execute(
                """INSERT INTO matched
                   (mkey, company, title, location, url, posted_date, seniority, sources,
                    seen_ids, description, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(mkey) DO UPDATE SET location=excluded.location,
                     url=excluded.url, posted_date=excluded.posted_date,
                     seniority=excluded.seniority, sources=excluded.sources,
                     seen_ids=excluded.seen_ids,
                     description=CASE WHEN length(excluded.description)
                                           > length(COALESCE(matched.description,''))
                                      THEN excluded.description
                                      ELSE matched.description END,
                     first_seen=excluded.first_seen, last_seen=excluded.last_seen""",
                (mkey, job.get("company"), job.get("title"), job.get("location"),
                 job.get("url"), new_pd, job.get("seniority", ""),
                 "+".join(sorted(new_sources)), "+".join(sorted(new_sids)),
                 new_desc, run_date, run_date))
        self.conn.commit()

    def get_matched_since(self, cutoff_iso):
        """Return matched roles with first_seen >= cutoff (ISO date), newest first."""
        cur = self.conn.execute(
            """SELECT company, title, location, url, posted_date, seniority, sources,
                      seen_ids, description, first_seen, last_seen FROM matched
               WHERE first_seen >= ? ORDER BY first_seen DESC, posted_date DESC""",
            (cutoff_iso,))
        cols = ["company", "title", "location", "url", "posted_date", "seniority",
                "sources", "seen_ids", "description", "first_seen", "last_seen"]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["sources"] = (d["sources"] or "").split("+") if d["sources"] else []
            d["seen_ids"] = (d["seen_ids"] or "").split("+") if d["seen_ids"] else []
            rows.append(d)
        return rows

    def close(self):
        self.conn.close()
