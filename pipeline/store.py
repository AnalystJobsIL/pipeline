"""Dedupe/seen store (SQLite, stdlib) + persistent LLM verdict cache.

Two separate dedup concerns, handled with two different keys:

1. Across-day "only show NEW postings" — keyed by a stable per-posting id
   `seen_id = "{ats_platform}:{job_id}"`, and `"{ats_platform}@{tenant}:{job_id}"` on the
   platforms whose ids are unique only per tenant (`_TENANT_SCOPED`). A `job_id` that is not
   an identifier — `fetch_workday` hands over a display label — falls through to the url
   (`_is_id_shaped`). Every posting ever included in a digest is
   recorded here; a posting is NEW iff its seen_id is absent. Because it keys on the
   platform's own job id, a genuinely new opening (new id) re-alerts, while the same
   posting never alerts twice.

2. Cross-platform duplicate merge WITHIN one digest — keyed by `merge_key =
   normalized(company) + "|" + normalized(title)` (location-independent). Collapses e.g.
   a role that appears on both a company's Comeet and Ashby boards into one entry, while
   recording every contributing seen_id as sent so none of them re-appear tomorrow.

The LLM verdict cache lives in the same DB so `claude -p` is not re-invoked for a title
already judged on a previous day.

3. The role RECORD (lane: roles, ARCHITECTURE §7c) is `matched` plus the text ledger next to
   this file — `roles.jsonl` / `roles_text.jsonl`, written by `pipeline/roles.py`. sqlite is
   the working index every SQL reader keeps using; the ledger is the durable, diffable,
   never-deleting copy. `status='superseded'` marks a row whose posting another company
   row also fetched (the same job under two names): kept, but off the board and the archive.
"""
from __future__ import annotations

import os
import re
import sqlite3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "state", "seen.db")

# The store's share of the 6,000-character capture cap, which was a bare literal inside
# `upsert_matched` while `fetchers._DESC_MAX` and `jdfill.DESC_MAX` were named constants
# pinned equal by a test. It is NOT raised here: both layers above truncate first, so the
# characters are already gone by the time a job reaches this file, and raising this alone
# would change nothing while implying the cap had moved. What the public dataset can say
# honestly is that a row sits ON the cap and is therefore cut — `roles.build_rows` reads
# this constant to say it (`description_truncated`).
DESC_MAX = 6000

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


# ---- the across-day key -----------------------------------------------------------------
# Platforms whose job-id space is per TENANT rather than per platform, so two companies on
# the same ATS can produce the same id. The criterion is the fetcher's id expression, not
# today's collision count: measured 2026-08-27 over every active board, only bamboohr had
# actually collided (3 of 72 ids), but oraclehcm req Ids, eightfold/microsoft `displayJobId`
# and phenom `jobSeqNo` are all per-tenant spaces that have simply not collided yet.
# Deliberately NOT here, each with its enumeration on that date: comeet (2,246 ids, 0
# collisions), greenhouse (8,088, 0), smartrecruiters (5,958, 0), ashby (2,076, 0), lever
# (756, 0), recruitee (233, 0), workable (105, 0), breezy (54, 0) — globally unique by
# construction; `scrape` and every `discovery-*` prefix, whose ids are already urls; and
# `workday`, whose collision is SAME-tenant (see `_is_id_shaped`) and which tenant-scoping
# would not fix while making the record look as though it had been addressed.
# How many RUNS a role may be absent from and still be the same opening. Runs, not days:
# see `upsert_matched` and `SeenStore.missed_runs`.
MISSED_RUNS = 3


_TENANT_SCOPED = frozenset(("bamboohr", "oraclehcm", "eightfold", "microsoft", "phenom"))

# A path segment meaning "the posting starts here" — everything after it varies per posting
# (the office, the title slug, the id), so the tenant is what comes before. Chosen from the
# data: without this cut, 21 of 56 scoped boards yielded more than one tenant token, because
# the Workday path carries the office and the Eightfold path a per-posting id.
_TENANT_MARK = frozenset((
    "job", "jobs", "apply", "details", "detail", "opening", "openings", "position",
    "positions", "career", "careers", "vacancy", "vacancies", "posting", "postings",
    "req", "requisition",
))
# `+` is the matched.seen_ids column delimiter (see `upsert_matched`) and `:` is the key
# separator, so neither may ever reach a tenant: a `+` would make that column round-trip
# lossy and re-email the role.
_TENANT_BAD = re.compile(r"[^a-z0-9./-]+")


def _tenant_of(job):
    """The board a posting came from, derived from the posting's OWN url.

    Reads nothing outside the job dict, so no fetcher and no registry column has to change.
    Host alone is not enough: Oracle HCM has SHARED SaaS pods (Verint sits on
    `fa-epcb-saasfaprod1.fa.ocs.oraclecloud.com`, one host that can carry many tenants),
    separated only by the `sites/CX_...` segment — a host-only rule would have re-created
    the very bug it fixes, on a different platform.

    Returns "" when no tenant can be derived, and every caller then keeps today's behaviour.
    """
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(job.get("url") or ""))
    except ValueError:
        return ""
    host = (parts.netloc or "").lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return ""
    segs = [x for x in (parts.path or "").split("/") if x]
    jid = str(job.get("job_id") or "").strip().lower()
    keep = []
    for seg in segs:
        low = seg.lower()
        if low in _TENANT_MARK:
            break
        if jid and jid in low:
            break
        if len(seg) > 24 or seg.count("-") > 2:      # a title or office slug, not a tenant
            break
        keep.append(low)
    # ...and the one segment that is a tenant by POSITION rather than by vocabulary. Oracle
    # HCM addresses a tenant as `sites/<site>`, and both of the rules above can eat it: a
    # requisition id of `2001` matches the site `CX_2001` (so Fortinet's tenant changed with
    # its own job id), and Dell's site is literally named `careers`, a _TENANT_MARK word.
    # Either way the key degraded to the SHARED POD prefix, which is exactly the collision
    # `_tenant_of` exists to prevent.
    if "sites" in [x.lower() for x in segs]:
        i = [x.lower() for x in segs].index("sites")
        if i + 1 < len(segs) and segs[i + 1].lower() not in keep:
            keep.append(segs[i + 1].lower())
    return _TENANT_BAD.sub("-", "/".join([host] + keep)).strip("-")


_WS = re.compile(r"\s")
_DIGIT = re.compile(r"\d")


def _is_id_shaped(jid):
    """Is this string a posting identifier at all?

    `fetch_workday` reads `bulletFields[0]`, which is a TENANT-CONFIGURED DISPLAY LIST, not
    a requisition number. Measured 2026-08-27 against the live boards: sixteen of Thales'
    seventeen Israel postings arrived with `job_id` "Regular Employee", F5's four with "0",
    Aristocrat's two with "Regular". One seen_id for sixteen roles means that the moment one
    is emailed, `filter_new` suppresses the other fifteen FOREVER — a larger loss than the
    cross-tenant collision this key was re-shaped for, and invisible to an audit that counts
    only cross-COMPANY collisions.

    A real id carries a digit and has no whitespace. That admits every shape in the fleet
    (`39`, `JR-019918`, `4697159006`, `BC.A60`, a uuid) and refuses "Regular Employee" and
    "Regular". It is deliberately fail-SAFE rather than fail-tight: a false positive falls
    through to the url, which is MORE unique than the id, so the cost is one night of key
    churn (absorbed by `upsert_matched`'s union, ARCHITECTURE section 7c) and never a lost
    or a duplicated role.

    It does NOT catch F5's "0": a one-character numeric id is shaped exactly like a real
    bamboohr id, and no lexical rule can separate them. That class is left to the run-scoped
    collision alarm (`roles.Ledger.id_collisions`), which needs no lexical judgement at all
    because it sees both postings, and to BACKLOG 311, which fixes the cause.

    `pipeline/fetchers.py` is `ats-fetch`'s file, so the expression itself is BACKLOG 311;
    this guard is the durable half, because it defends against the next tenant to configure
    a word rather than against the three boards that already did.
    """
    jid = str(jid or "")
    return bool(jid) and not _WS.search(jid) and bool(_DIGIT.search(jid))


def _no_delim(part):
    """`+` joins the `matched.seen_ids` column and splits it again, so a `+` anywhere in a key
    makes that column lossy: the two halves land in nobody's `sent` table and `filter_new`
    calls the role new again. The tenant is regex-constrained, but the URL BRANCH below is
    not — and `_is_id_shaped` deliberately routes far more traffic onto it, so a careers link
    with `?role=data+analyst` would have re-emailed. Percent-encode instead of dropping, so
    the address `enrich_matched_jd.sibling_urls` reads back out is still fetchable."""
    return str(part or "").replace("+", "%2B")


def seen_id(job):
    """Stable per-posting identity for across-day dedup.

    `{platform}:{job_id}`, with the board's tenant folded into the PLATFORM half —
    `{platform}@{tenant}:{job_id}` — for the platforms whose ids are unique only per tenant.

    The tenant goes before the colon, never after it, because two readers in this repo parse
    this string and both take everything after the FIRST colon as the identifier:
    `roles._strong_ids`, and — the one that matters — `enrich_matched_jd.sibling_urls`,
    which does `sid.split(":", 1)[1]` and then `startswith("http")`. The fallback branch
    below puts a url in the id half, so a tenant after the colon would silently kill
    `jd-text`'s whole scrape-sibling JD recovery, for every role.
    """
    plat = str(job.get("ats_platform", "") or "")
    jid = str(job.get("job_id") or "").strip()
    if plat in _TENANT_SCOPED:
        tenant = _tenant_of(job)
        if tenant:
            plat = f"{plat}@{tenant}"
    if _is_id_shaped(jid):
        return _no_delim(f"{plat}:{jid}")
    # No id, or a value that is not an identifier: the url, which is per posting.
    return _no_delim(f"{plat}:{job.get('url', '')}")


def merge_key(job):
    """Location-independent identity to collapse cross-platform duplicates in a digest."""
    return f"{_norm_company(job.get('company'))}|{_norm(job.get('title'))}"


def _url_parts(url):
    """(host, path) of a url, lowercased, `www.` and a trailing slash stripped."""
    from urllib.parse import urlsplit
    try:
        p = urlsplit(str(url or ""))
    except ValueError:
        return "", ""
    h = (p.netloc or "").lower().split(":")[0]
    h = h[4:] if h.startswith("www.") else h
    return h, (p.path or "").rstrip("/").lower()


def _same_origin(url, origin):
    """Does this address belong to the board the registry row was fetched from?

    `origin` is the registry row's `token` when that is a tenant (every native-ATS row has
    one: comeet `26.00E`, greenhouse `nift`, ashby `moonactive` — 133/133, 106/106, 52/52 on
    2026-08-27) and its `api_url` when the token is itself a url (a `scrape` row).

    This is an identity of SOURCE, and that is the whole point. The obvious alternative —
    "the company is named in the url", `roles.names_in_url` — is a NO-GO here and was
    measured to be one: `names_in_url("Bright Data", ".../jobs/fetcherr/.../data-analyst--
    tableau/...")` is True, because the company token `data` matches the JOB TITLE in the
    url slug. That predicate was built as tiebreak key 0 of seven among candidates already
    known to be the same posting; as an admission gate on foreign content it fails, and it
    would have published Fetcherr's JD and apply link under Bright Data's name.

    Strict on purpose: a false negative costs a repair we could have made, a false positive
    publishes another employer's content, and only one of those is reversible.
    """
    from . import aggregators
    url = str(url or "")
    origin = str(origin or "").strip()
    if not url or not origin or aggregators.is_aggregator(url):
        return False
    mh, mp = _url_parts(url)
    if not mh:
        return False
    if origin.lower().startswith("http"):          # a scrape row: the board's own address
        oh, op = _url_parts(origin)
        return bool(oh) and mh == oh and (op == "" or mp == op or mp.startswith(op + "/"))
    # a native-ATS tenant: it must name a whole PATH segment of the address — never a prefix
    # of one (`nift` must not match `data-analyst-at-nift-4448328003`) and never a HOST label
    # (`HiBob` is itself a registry row, and `*.careers.hibob.com` is its multi-tenant ATS
    # domain, so matching host labels made every Bob customer's posting "HiBob's own board").
    tok = origin.lower()
    if len(tok) < 3:
        return False
    return tok in [seg for seg in mp.split("/") if seg]


def _is_aggregator_url(url):
    """True for a LinkedIn/Indeed/city-board address. Imported lazily: `aggregators` is
    shared plumbing and this module is imported by tools that never need it."""
    from . import aggregators
    return bool(url) and aggregators.is_aggregator(str(url))


def _authoritative(job, origins):
    """May this member donate its url or its description to the merged record?"""
    if not origins:
        return False
    return _same_origin(job.get("url"), origins.get(job.get("company")))


def _is_posting_page(job, origins):
    """Authoritative AND deeper than the board's own address — a POSTING, not the listing.

    Promoting a member merely because it is on the employer's domain can hand the reader the
    board's root: three Meta records were promoted to `metacareers.com/jobs?offices[0]=…`, a
    search page that `roles.same_posting` separately warns is shared by every Meta role. It
    also strips the strongest name evidence `Ledger._winner` has, because an aggregator card
    url literally contains `-at-<company>-`. So only a deeper address may take the canonical
    slot or donate the url; when a group offers none, the election is exactly what it was.
    """
    if not _authoritative(job, origins):
        return False
    origin = str(origins.get(job.get("company")) or "")
    path = _url_parts(job.get("url"))[1]
    if not origin.lower().startswith("http"):
        # a tenant token names a whole path segment — but the BOARD ROOT contains that
        # segment too (`boards.greenhouse.io/nift`, `comeet.com/jobs/brightdata`), and
        # calling the root a posting is the very thing this predicate exists to refuse. A
        # posting has something after the tenant.
        segs = [x for x in path.split("/") if x]
        tok = origin.lower()
        return bool(segs) and tok in segs and segs.index(tok) < len(segs) - 1
    return path != _url_parts(origin)[1]


def merge_duplicates(jobs, origins=None):
    """Collapse jobs sharing a merge_key into one canonical entry.

    Returns a list of merged jobs. Each merged job gains:
      - `seen_ids`: list of every contributing posting's seen_id (all marked sent)
      - `sources`: sorted list of distinct ats_platforms it appeared on

    The merge is FIELD-wise, not member-wise. It used to copy one canonical member wholesale
    and rescue only `posted_date`, and that lost two different things at once: a role seen on
    an aggregator (real date, short snippet) and on its employer's own board (no date, full
    JD) published the SNIPPET and linked to the AGGREGATOR, because the canonical is elected
    on having an ISO date and scrape rows carry `posted_date: ""` (BACKLOG 260 / 109 / 151;
    109's stated mechanism — that `upsert_matched` refuses to replace `url` — was false for
    every url until 2026-08-31; `upsert_matched` now refuses exactly TWO downgrades, a
    stored non-aggregator url replaced by an aggregator one and any stored url blanked, and
    overwrites every other case).

    `origins` is `{company_name: token-or-api_url}` from the registry. Without it the
    rescues are inert and this behaves exactly as it did before: every degraded path here
    falls back to today's answer rather than guessing.
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
        # canonical = prefer a member that is a POSTING on the employer's own board, then
        # one with an ISO date, then one with a url, else first — never a copy that only
        # INHERITED its verdict (pipeline/roles.classify_grouped): a bare discovery card's
        # LinkedIn url and date must not become the role's record.
        #
        # The second key is an identity of SOURCE and it is load-bearing. A "demote anything
        # on an aggregator" key was tried here and is a NO-GO: demoting one member PROMOTES
        # another, the promoted one was never tested against `origins`, and a competitor card
        # scraped off our own careers page then published its url and its JD under our name —
        # measured, in both member orders, and a regression against the rule it replaced.
        # This key can only ever promote a member we have proven is on the company's board.
        canonical = sorted(
            members,
            key=lambda j: (
                1 if j.get("_inherited") else 0,
                0 if _is_posting_page(j, origins) else 1,
                0 if re.match(r"^\d{4}-\d{2}-\d{2}$", str(j.get("posted_date", ""))) else 1,
                0 if j.get("url") else 1,
            ),
        )[0]
        out = dict(canonical)
        # a known posting date is never discarded: a bare discovery card cannot be the
        # canonical (its url is LinkedIn's), but the date it carries is real evidence
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(out.get("posted_date", ""))):
            for m in members:
                if re.match(r"^\d{4}-\d{2}-\d{2}$", str(m.get("posted_date", ""))):
                    out["posted_date"] = m["posted_date"]
                    break
        # the reader's link, and the text we publish, come from the employer's own board
        # when any member offers one. `_inherited` copies are excluded from the description
        # rescue because their text is a COPY of the group's longest (roles.classify_grouped
        # writes it there), not something that posting carried.
        # ONE donor supplies both the link and the text. Taking the url from the first
        # authoritative member and the description from the longest one published a Tel Aviv
        # posting's link with a Haifa posting's JD — `merge_key` is location-independent by
        # design, so two members can be genuinely different openings with the same title.
        own = [m for m in members if _authoritative(m, origins) and not m.get("_inherited")]
        # `deep` draws from ALL members, `_inherited` ones included: an inherited copy's TEXT
        # is a copy (roles.classify_grouped wrote the group's longest onto it) and stays out
        # of `own`, but its ADDRESS is something the scrape really read and `_is_posting_page`
        # has proven against the registry — a board card whose list endpoint carries no text
        # (Zipher's `/careers/data-analyst/`, most greenhouse list rows) must still donate the
        # link, or the aggregator copy's url ships forever (BACKLOG 488's sibling defect).
        # The origin gate, not the flag, is what keeps a competitor card out of `deep`.
        deep = [m for m in members if _is_posting_page(m, origins) and m.get("url")]
        # The donor is whichever member supplies the LINK, and own-board text may only come
        # from the donor's own address. Taking the url from one member and the longest
        # description from another published a Tel Aviv posting's link with a Haifa
        # posting's JD: `merge_key` is location-independent by design, so two members can be
        # different openings with one title. When the canonical already IS a posting on the
        # company's board it donates to itself. The ONE exception to one-donor-for-both
        # (2026-08-31, §7c): a bare `_inherited` board card donating its ADDRESS over an
        # aggregator canonical pairs the board link with the aggregator's snippet of the
        # same role — deliberate, marked by `description_quality`, and self-healing (the
        # enrich layer can now fill from the role's own address).
        if _is_posting_page(out, origins):
            donor_url = str(out.get("url") or "")
        elif deep and (_is_aggregator_url(out.get("url"))
                       or not str(out.get("url") or "").strip()):
            # Donate ONLY over an aggregator (or url-less) canonical. A non-inherited
            # competitor card scraped off our own page can be the canonical, and handing it
            # our board url would launder its JD under our own address — the one shape no
            # downstream check can catch (wave A). Over an aggregator canonical this is the
            # deliberate asymmetry §7c documents: the board ADDRESS ships and the text stays
            # the group's. Every member of `deep` here is `_inherited` by construction (a
            # non-inherited posting page would have been the canonical), so no donor can
            # also give text; the url tiebreak keeps the choice order-independent when two
            # bare board cards share one merge_key.
            donor_url = min(deep, key=lambda m: str(m.get("url") or ""))["url"]
            out["url"] = donor_url
        else:
            donor_url = None
        best = ""
        if donor_url is not None:
            for m in own:
                if str(m.get("url") or "") != donor_url:
                    continue
                t = str(m.get("description") or "").strip()
                if len(t) > len(best):
                    best = t
        # ...and never let promoting the employer's own page COST the role its only text.
        # Some board pages carry `description: ""` (most list endpoints do), so swapping the
        # canonical onto one took two live roles from 169 and 152 characters to zero — a loss
        # `upsert_matched`'s sqlite ratchet cannot undo on a role's first sighting, and one
        # `jd-text` would then pay Bright Data to re-fetch. When the promoted posting has no
        # text of its own, the merged record keeps the longest text the group had, which is
        # exactly what shipped before this rule existed.
        if not best and not str(out.get("description") or "").strip():
            # ...but only from a member an AGGREGATOR attributed to this company, never from
            # a stranger's own site. A first attempt fell back to the longest text in the
            # group and re-opened the hole the origin gate exists to close: a competitor card
            # scraped onto our careers page has no text-bearing rival when our board page is
            # empty, so it would have won by default. `_inherited` copies are excluded for
            # the same reason as above — their text is a copy, not something they carried.
            cands = [m for m in members
                     if not m.get("_inherited")
                     and (_authoritative(m, origins) or _is_aggregator_url(m.get("url")))]
            best = max((str(m.get("description") or "").strip() for m in cands),
                       key=len, default="")
        # A ratchet, not a replacement, and this is the conservative choice on purpose. When
        # the canonical is NOT on the employer's board, its text is usually our own role as
        # an aggregator copied it — legitimate, and for many roles the only text we have — and
        # nothing here can tell that from a competitor card on the same page. Replacing it
        # would delete real coverage to remove a hypothetical; lengthening from a proven
        # board member cannot. The foreign-text-on-a-foreign-canonical case is older than
        # this rule and is BACKLOG 312.
        if len(best) > len(str(out.get("description") or "").strip()):
            out["description"] = best
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
                last_seen   TEXT,
                seen_ids    TEXT,
                jd_attempted TEXT,
                status      TEXT,
                superseded_by TEXT
            )""")
        # One row per date the pipeline ran. It is the only honest answer to "was this role
        # absent, or was there no run?" — a calendar gap cannot tell those apart and fires on
        # an outage, and the distinct `last_seen` values of `matched` cannot either, because
        # that column is overwritten on every re-sighting and so records the days something
        # DIED (eight commits on 2026-08-21 against one distinct value; it holds dates that
        # precede the first run; it is missing 2026-08-18).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_date    TEXT PRIMARY KEY
            )""")
        # migrations for stores created before a column existed. `jd_attempted` used to be
        # added out-of-band by enrich_matched_jd.py (its ALTER is now a no-op here);
        # `status`/`superseded_by` are the roles lane's (pipeline/roles.py).
        for col in ("seen_ids", "jd_attempted", "status", "superseded_by"):
            try:
                self.conn.execute(f"ALTER TABLE matched ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        self.conn.commit()
        self.path = path

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
        # the ledger's `sent` mirror, in the same commit (pipeline/roles.py, lane: roles)
        from . import roles as _roles
        _roles.stamp_sent(self.path, {sid: run_date
                                      for sid in merged_job.get("seen_ids", [seen_id(merged_job)])})

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

    # ---- the run log --------------------------------------------------------
    def record_run_date(self, run_date):
        """Stamp that the pipeline ran. Idempotent; `pipeline/roles.Ledger.record_run` is the
        only caller, so a scoped local run stamps too — which is correct, it DID look."""
        self.conn.execute("INSERT OR IGNORE INTO runs (run_date) VALUES (?)", (run_date,))
        self.conn.commit()

    def missed_runs(self, old_last, run_date):
        """How many runs happened strictly between two dates — the number of chances this
        role had to be seen and was not.

        Returns None when the log CANNOT ANSWER, and `upsert_matched` then keeps the calendar
        rule. That is not only the empty-log case: for the first days after the log is
        introduced its earliest entry is later than most roles' `last_seen`, so it would
        answer 0 — "no run missed it" — for every role that had in fact been absent for
        weeks, and the calendar rule it replaced would no longer be there to catch them. So
        the log answers only about a gap it actually spans.
        """
        first = self.conn.execute("SELECT MIN(run_date) FROM runs").fetchone()[0]
        if not first or str(first) > str(old_last):
            return None
        return self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE run_date > ? AND run_date < ?",
            (str(old_last), str(run_date))).fetchone()[0]

    # ---- matched roles (rolling windows for email 48h / board 2 weeks) ------
    def upsert_matched(self, job, run_date, closed_keys=None):
        """Insert a matched role (keyed by company|title).

        `first_seen` persists across re-sightings and RESETS when the role REAPPEARS after
        having been absent — a genuinely new opening under the same company|title has to
        re-alert. An ISO posted_date is never overwritten by a non-ISO one; sources and
        seen_ids are unioned.

        What counts as "absent" is `closed_keys`: the role ids the ledger recorded as closed
        (`pipeline/roles.Ledger.closed_keys`). The ledger is the right instrument because it
        closes a role ONLY where the run actually looked — never on a failed board, never at
        a company a scoped run did not scan — so it distinguishes "we looked and it was
        gone" from "we did not look".

        It used to be a calendar gap of >3 days, which cannot tell those apart and fires on
        an OUTAGE: with no digest on 2026-08-27 and a resume on 08-30, all 76 open roles
        would have taken a fresh `first_seen`, badging ~70 of them "new" on the board.
        Counting distinct `last_seen` values instead was considered and measured to be
        worse: that column is overwritten on every re-sighting, so it records the days
        something DIED, not the days we ran — `git log cloud_state/seen.db` shows eight
        commits on 2026-08-21 against one distinct `last_seen`, and the column holds
        2026-08-16/17/19, which precede the first run of the pipeline (BACKLOG 139).

        `closed_keys=None` keeps the old calendar rule, so a caller without a ledger — a
        rehearsal, a scratch store, a frozen or corrupt ledger — behaves exactly as before.
        """
        mkey = merge_key(job)
        new_sources = set(job.get("sources") or [job.get("ats_platform", "")])
        new_sids = set(job.get("seen_ids") or [seen_id(job)])
        new_pd = str(job.get("posted_date") or "")
        prev = self.conn.execute(
            "SELECT sources, seen_ids, posted_date, last_seen, url FROM matched WHERE mkey=?",
            (mkey,)).fetchone()
        keep_first = False
        new_url = job.get("url")
        if prev:
            old_sources, old_sids, old_pd, old_last, old_url = prev
            # A stored board url is never regressed to an aggregator link, and no stored
            # url is ever blanked. merge_duplicates promotes the employer's own posting
            # page when the group offers one, but on a cache-blink day the group holds only
            # the aggregator copy — and this overwrite is exactly how the Zipher fix
            # regressed (the 08-27 scrape-cache refresh blanked the donor and the Indeed
            # url came straight back). Board→board moves and aggregator→aggregator
            # refreshes still overwrite; the two downgrades are refused.
            if old_url and (not str(new_url or "").strip()
                            or (_is_aggregator_url(new_url)
                                and not _is_aggregator_url(old_url))):
                new_url = old_url
            new_sources |= set((old_sources or "").split("+")) - {""}
            new_sids |= set((old_sids or "").split("+")) - {""}

            def _iso(p):
                return len(p) == 10 and p[4:5] == "-"
            if _iso(str(old_pd or "")) and not _iso(new_pd):
                new_pd = old_pd                       # keep the better date
            missed = self.missed_runs(old_last, run_date)
            if closed_keys is not None and missed is not None:
                # Two independent reasons to call this a NEW opening, and both are needed.
                # The ledger is authoritative when it closed the role — it closes only where
                # the run actually looked. But it closes NOTHING on a failed board, so a
                # board broken for four runs would otherwise pin a stale `first_seen` that
                # `get_matched_since(cutoff_email)` can never return, and the returning
                # requisition would be silently un-emailable. The run log answers that: it
                # counts the chances this role had to be seen, so an OUTAGE (no runs at all)
                # keeps `first_seen` while a broken board that missed four real runs does not.
                keep_first = mkey not in closed_keys and missed <= MISSED_RUNS
            else:
                try:
                    import datetime as _d
                    gap = (_d.date.fromisoformat(run_date)
                           - _d.date.fromisoformat(str(old_last))).days
                except (ValueError, TypeError):
                    gap = 0
                keep_first = gap <= 3                 # reappeared quickly -> same opening
        # A description is knowledge we may have paid Bright Data for, and most list
        # endpoints (workday, smartrecruiters, bamboohr, microsoft) return NONE — so a
        # daily re-sighting used to overwrite a backfilled JD with "". Never downgrade:
        # only a longer, non-empty text replaces what is stored.
        new_desc = (job.get("description") or "").strip()[:DESC_MAX]
        if prev and keep_first:
            self.conn.execute(
                """UPDATE matched SET location=?, url=?, posted_date=?,
                   seniority=CASE WHEN ? != '' THEN ? ELSE seniority END,
                   sources=?, seen_ids=?,
                   description=CASE WHEN length(?) > length(COALESCE(description,''))
                                    THEN ? ELSE description END,
                   last_seen=? WHERE mkey=?""",
                (job.get("location"), new_url, new_pd,
                 job.get("seniority") or "", job.get("seniority") or "",
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
                 new_url, new_pd, job.get("seniority", ""),
                 "+".join(sorted(new_sources)), "+".join(sorted(new_sids)),
                 new_desc, run_date, run_date))
        self.conn.commit()

    MATCHED_COLS = ["mkey", "company", "title", "location", "url", "posted_date", "seniority",
                    "sources", "seen_ids", "description", "first_seen", "last_seen",
                    "jd_attempted", "status", "superseded_by"]

    def _matched_cols_live(self):
        """MATCHED_COLS plus the optional columns another lane's driver adds in place.
        `jd_why` is jd-text's (added by `enrich_matched_jd._ensure_columns` on its next
        run, 2026-08-31 contract), so any snapshot between their commit and that run lacks
        it — the read must tolerate both states, whichever commit landed first."""
        if getattr(self, "_mcols", None) is None:
            try:
                have = {r[1] for r in self.conn.execute("PRAGMA table_info(matched)")}
            except Exception:  # noqa: BLE001 — degrade to the contract columns
                have = set()
            self._mcols = self.MATCHED_COLS + [c for c in ("jd_why",) if c in have]
        return self._mcols

    def get_matched_since(self, cutoff_iso, include_superseded=False):
        """Return matched roles with first_seen >= cutoff (ISO date), newest first.

        A `superseded` row is the same posting another company row also fetched (one job
        under two names); it stays in the store but is off the board and the archive unless
        asked for."""
        cols = self._matched_cols_live()
        cur = self.conn.execute(
            f"""SELECT {', '.join(cols)} FROM matched
                WHERE first_seen >= ?
                {'' if include_superseded else "AND COALESCE(status,'') != 'superseded'"}
                ORDER BY first_seen DESC, posted_date DESC""",
            (cutoff_iso,))
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["sources"] = (d["sources"] or "").split("+") if d["sources"] else []
            d["seen_ids"] = (d["seen_ids"] or "").split("+") if d["seen_ids"] else []
            rows.append(d)
        return rows

    # ---- the roles ledger's seams (pipeline/roles.py is the only caller) --------------
    def supersede(self, mkey, by_mkey):
        """One posting under two company names: keep the loser's row, off the product."""
        self.conn.execute("UPDATE matched SET status='superseded', superseded_by=? WHERE mkey=?",
                          (by_mkey, mkey))
        self.conn.commit()

    def update_matched(self, mkey, **fields):
        """Field-level write used by the ledger reconcile (never touches first_seen's rule)."""
        cols = [c for c in fields if c in self.MATCHED_COLS and c != "mkey"]
        if not cols:
            return
        vals = [("+".join(sorted(fields[c])) if isinstance(fields[c], (list, set)) else fields[c])
                for c in cols]
        self.conn.execute(f"UPDATE matched SET {', '.join(c + '=?' for c in cols)} WHERE mkey=?",
                          (*vals, mkey))
        self.conn.commit()

    def insert_matched(self, rec):
        """Rehydrate one role the ledger has and sqlite lacks. Idempotent (INSERT OR IGNORE).
        sqlite carries one status only, `superseded`; open/closed are the ledger's."""
        rec = dict(rec)
        if rec.get("status") != "superseded":
            rec["status"], rec["superseded_by"] = None, None
        vals = [("+".join(sorted(rec.get(c) or [])) if c in ("sources", "seen_ids")
                 else rec.get(c)) for c in self.MATCHED_COLS]
        self.conn.execute(
            f"INSERT OR IGNORE INTO matched ({', '.join(self.MATCHED_COLS)}) "
            f"VALUES ({', '.join('?' * len(self.MATCHED_COLS))})", vals)
        self.conn.commit()

    def load_sent(self):
        """{seen_id: first_sent} — what has been emailed, for the ledger's `sent` mirror."""
        return dict(self.conn.execute("SELECT seen_id, first_sent FROM sent").fetchall())

    def upsert_sent_missing(self, rows):
        """Rehydrate `sent` from the ledger: rows = {seen_id: first_sent}. Returns inserted."""
        n = 0
        for sid, first in rows.items():
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO sent (seen_id, first_sent, last_seen) VALUES (?,?,?)",
                (sid, first, first))
            n += cur.rowcount
        self.conn.commit()
        return n

    def close(self):
        self.conn.close()


# --------------------------------------------------------------------------------------- #
# The audit that keeps the key honest. Run it after any change to `seen_id`, `_tenant_of` or
# `_TENANT_SCOPED`, and after `registry` converts rows onto a scoped platform:
#
#     python -m pipeline.store --audit-ids            # every active board, free public APIs
#     python -m pipeline.store --audit-ids --platform bamboohr
#
# It asserts three things, and the THIRD is the one this lane learned the hard way. An audit
# that counts only cross-COMPANY collisions passes while sixteen Thales postings share one
# key inside a single tenant.
#
#   1. no seen_id is produced by two different companies
#   2. no board yields more than one tenant token  (a token that moves is not a tenant)
#   3. no board collapses two of its own postings onto one seen_id
# --------------------------------------------------------------------------------------- #

def audit_ids(platforms=None, csv_path=None):
    """Return (rows, problems). Network-bound: reads every active board it is asked about."""
    import collections
    from . import fetchers
    from .companies import load_companies

    rows = load_companies(csv_path) if csv_path else load_companies()
    want = set(platforms or [])
    owners, per_board, problems = collections.defaultdict(set), collections.defaultdict(set), []
    counted = collections.Counter()
    for r in rows:
        plat = r.get("ats_platform", "")
        if plat not in fetchers.FETCHERS or plat in ("scrape", "discovery"):
            continue
        if want and plat not in want:
            continue
        try:
            jobs = fetchers.FETCHERS[plat](r) or []
        except Exception:                    # a broken board is `ats-fetch`'s problem, not this one
            continue
        counted[plat] += len(jobs)
        seen_here = collections.defaultdict(set)
        for j in jobs:
            sid = seen_id(j)
            owners[sid].add(r["company_name"])
            seen_here[sid].add((j.get("title") or "", j.get("url") or ""))
            if plat in _TENANT_SCOPED:
                per_board[(plat, r["company_name"])].add(_tenant_of(j))
        for sid, postings in seen_here.items():
            if len({u for _, u in postings if u}) > 1:
                problems.append(("one board, one key, many postings", r["company_name"], sid,
                                 sorted(t for t, _ in postings)[:4]))
    for sid, who in owners.items():
        if len(who) > 1:
            problems.append(("two companies, one key", ", ".join(sorted(who)), sid, []))
    for (plat, name), toks in per_board.items():
        if len(toks) > 1:
            problems.append(("one board, two tenant tokens", name, plat, sorted(toks)[:4]))
    return dict(counted), problems


def _audit_main(argv):
    import sys
    plats = []
    if "--platform" in argv:
        plats = argv[argv.index("--platform") + 1].split(",")
    counted, problems = audit_ids(plats or None)
    for plat, n in sorted(counted.items(), key=lambda kv: -kv[1]):
        print(f"  {plat:16} {n:6} postings")
    print(f"\n{len(problems)} problem(s)")
    for kind, who, sid, extra in problems:
        print(f"  [{kind}] {who}: {sid}" + (f" {extra}" if extra else ""))
    return 1 if problems else 0


if __name__ == "__main__":                   # never on import: this module is a library
    import sys
    if "--audit-ids" in sys.argv:
        sys.exit(_audit_main(sys.argv))
    print("usage: python -m pipeline.store --audit-ids [--platform a,b]")
