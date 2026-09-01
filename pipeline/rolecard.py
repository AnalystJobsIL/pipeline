"""The role as it reads — one card per role (lane: render, ARCHITECTURE.md §7d, part 1b).

`build(job, run_date, ...)` turns a `matched` row (plus, when the caller has it, the role's
ledger record from `pipeline/roles.py`) into a plain dict of raw strings and lists: every
value a renderer needs and nothing pre-escaped. `pipeline/digest.py` renders cards; it never
derives. `cross_check(cards)` looks ACROSS the cards of one product for the shapes that put a
role under the wrong name (two employers on one board tenant, one title under two near-
identical names, two names collapsing to one cell, a blurb that names a different employer)
and returns issues for the mail.

What the ledger contributes, and only this: who else claimed the posting (`also_listed_as`),
the dates it was re-posted, and — on the archive only — when it closed. Tags are computed
from the text on every render; the ledger's `tags` snapshot is the roles lane's column, not
a cache for this one (a vocabulary change here must show on every card the same morning).

Never raises: a card whose derivation fails degrades to a bare card (company, title, url,
location) with the failure named in `card["issues"]`, so one poisoned description — or a row
whose title is an int — cannot cost the day's board or email; the mail says how many cards
degraded and why.
"""
from __future__ import annotations

import datetime as _dt
import functools
import re
import unicodedata
from collections import Counter
from urllib.parse import urlparse, parse_qsl, urlencode

from . import jdtext, roleprofile
from .company_info import _JUNK_OUT
from .firmographics import STAGES, identity_key
from .seniority import _HEBREW_SENIOR, _JUNIOR, _SENIOR

# a failed `claude -p` (or similar CLI error) must never render as an About blurb — and
# neither must a first-person "I'm not sure what this company does" meta answer. The
# writer's gate (company_info._JUNK_OUT) is the rule; this is it plus what only a blurb
# that was cached before that gate existed can still carry.
_ABOUT_JUNK = re.compile(_JUNK_OUT.pattern + r"|unable to (?:confirm|verify)", re.I)

# one label per stage the researcher can emit (firmographics.STAGES) — pinned total by test
_STAGE_LABEL = {"early-private": "early-stage private", "growth-private": "growth-stage private",
                "public": "public", "acquired-by-bigtech": "acquired",
                "private-enterprise": "private enterprise"}
assert set(_STAGE_LABEL) == STAGES, sorted(set(_STAGE_LABEL) ^ STAGES)

REPOST_DAYS = 3         # posted_date bumped this far past first_seen = the company re-posted it


def _s(v, cap=None):
    """A field as one line of text, whatever the row or the ledger held (None, int, list…)."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        v = " ".join(str(x) for x in v if x is not None)
    t = " ".join(str(v).split())
    return t[:cap] if cap else t


def newcut(run_date):
    """The first_seen/posted date from which a role is 'new' on the board (yesterday)."""
    try:
        return (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=1)).isoformat()
    except Exception:
        return "9999"


def firmo_facts(rec):
    """"What is this company, actually" — the researched facts, as short display chips.

    The firmographics layer researches sector/stage/employees/founded/IL-centre for every
    company on the board and then nothing rendered it: the answer to "should I want to work
    here" lived only in a sqlite table. Order is the order a reader asks it in. Each chip is
    one line of text: a researcher's stray newline must not close the mail's code span.
    """
    if not isinstance(rec, dict):
        return []
    out = []
    if isinstance(rec.get("sector"), str) and rec["sector"].strip():
        out.append(_s(rec["sector"], 60))
    stage = _s(rec.get("stage")) if isinstance(rec.get("stage"), str) else ""
    if stage:
        out.append(_STAGE_LABEL.get(stage, stage))
    n = rec.get("employees_global")
    if type(n) is int and n > 0:
        out.append(f"~{n:,} employees")
    if isinstance(rec.get("founded"), (str, int)) and _s(rec["founded"]):
        out.append(f"founded {_s(rec['founded'], 12)}")
    if isinstance(rec.get("il_center"), str) and rec["il_center"].strip():
        out.append(_s(rec["il_center"], 60))
    return [c for c in out if c][:5]


# characters no employer name legitimately carries: controls, zero-width, bidi marks
# and the invisible fillers/joiners (wave 1: U+061C is the third bidi mark next to
# LRM/RLM, and soft hyphen, word joiners, Hangul fillers, BOM and TAG characters all
# survive both `str.split()` and every escaper on the render path)
_DN_JUNK = re.compile(r"[\x00-\x1f\x7f-\x9f\xad\u061c\u115f-\u1160\u180b-\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u3164\ufeff\U000e0000-\U000e007f]")
# an LLM's non-answer must never become an employer's public name
_DN_NON_ANSWER = {"n/a", "na", "null", "none", "unknown", "unclear", "tbd", "the company"}
# `&rlm;`-shaped text survives `_md_esc` (it escapes `#`, not `&`) and GitHub renders
# the entity — re-introducing downstream exactly what `_DN_JUNK` strips at the source
_DN_ENTITY = re.compile(r"&#|&[a-zA-Z][a-zA-Z0-9]*;")
_DN_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
# Greek and Cyrillic: legitimate here only as a WHOLE-script name (then the identity
# is empty and already refused), never mixed into a Latin brand
_DN_FOREIGN = re.compile("[\u0370-\u03ff\u0400-\u04ff]")


@functools.lru_cache(maxsize=8)
def _id_token_index(keys):
    """Identity token set per firmographics key, once per dict — the per-card scan was
    ~5.5 ms against the full 1,313-key export (vs ~0.6 µs cached), and a brand that
    leaves its company's identity group is the NORMAL case, not the exception."""
    return tuple((k, frozenset(identity_key(unicodedata.normalize("NFKC", str(k))).split()))
                 for k in keys)


def display_name(rec, company="", firmographics=None):
    """The brand company-intel evidenced for this company ('' when it did not).

    `display_name` on a firmographics record is optional, brand-only, never the registry
    slug (the 2026-08-30 contract with company-intel). "No evidence" — absent, empty,
    whitespace, non-str, over 60 chars (a truncated brand would be a WRONG name, so junk
    length is refused, never cut; the cell's CSS ellipsis handles width), an LLM
    non-answer ("N/A", "unknown"), entity-shaped text, or no letter at all — leaves
    every caller at today's behaviour byte for byte.

    The impersonation guard: a brand whose identity leaves this company's group and
    token-matches (equal or subset, either way — "Wix Analytics" is still Wix) another
    company the renderer knows THIS MORNING is refused. The `firmographics` dict is the
    board + role companies, not the whole registry, so an off-board victim is caught the
    morning it appears; company-intel's write-time check is the wider net. A record
    carrying another employer's name is the wrong-facts failure shape (`Bounce`, 489);
    rendered, it would impersonate that employer with only the board tooltip carrying
    the truth. A brand whose identity keys to nothing (homoglyph scripts — NFKC folds
    the compatibility ones first) or only to single letters is unverifiable: refused."""
    v = rec.get("display_name") if isinstance(rec, dict) else None
    if not isinstance(v, str):
        return ""
    # whitespace collapses BEFORE the junk strip (a newline is a separator, not junk —
    # stripping it first would glue a two-word brand together), and again after it
    # (deleting a zero-width between two spaces would leave a double space)
    dn = _s(_DN_JUNK.sub("", _s(v)))
    if (not dn or len(dn) > 60 or dn.lower() in _DN_NON_ANSWER
            or _DN_ENTITY.search(dn) or not _DN_LETTER.search(dn)
            # a name NFKC rewrites (fullwidth, math-bold, ligatures) is styled to look
            # like a name, not to be one — the homoglyph shapes an escaper can't catch
            or unicodedata.normalize("NFKC", dn) != dn
            # ...and a Latin name carrying a Cyrillic or Greek letter is the homoglyph
            # NFKC keeps: identity_key silently DELETES the foreign letter, so a
            # Cyrillic-o "Monday.com" keys to tokens that match nothing while reading
            # as the victim's name (wave 2)
            or bool(re.search("[a-zA-Z]", dn) and _DN_FOREIGN.search(dn))):
        return ""
    its = frozenset(identity_key(dn).split())
    if not its or all(len(t) < 2 for t in its):
        return ""
    mine = frozenset(identity_key(unicodedata.normalize("NFKC", company)).split())
    if its != mine:
        for k, o in _id_token_index(tuple(firmographics or ())):
            if k != company and o and (o <= its or its <= o):
                return ""
    return dn


def company_about(company, desc, company_info):
    """The company one-liner for a card: the researched blurb, else a sentence anchored on the
    company's own name in the JD ("<Company> is a …"); never the first "X is a …" of the
    text, which in an agency's posting describes the client. A CLI error or a first-person
    meta answer never gets through."""
    about = (company_info or {}).get(company)
    about = about if isinstance(about, str) else ""
    if not about or _ABOUT_JUNK.search(about):
        about = jdtext._company_blurb(desc, company, anchored_only=bool(company)) or ""
    about = _s(about)
    # The summaries are already constrained to 2-3 sentences at the source; show them
    # whole. The cap is only a safety net for pathological output — cut at a sentence
    # boundary so the "how it makes money" half is never chopped mid-thought.
    if len(about) > 700:
        cut = about[:700]
        p = max(cut.rfind(". "), cut.rfind("! "))
        about = cut[:p + 1] if p > 200 else cut[:cut.rfind(" ")] + "…"
    return about


def sen_canon(chip, title):
    """Collapse any seniority hint to ONE tidy label so the column scans in a glance:
    Junior / Mid / Senior / Lead+ (— when unknown). The vocabulary is the classifier's
    (`seniority._SENIOR`, `_JUNIOR`, `_HEBREW_SENIOR`) and the lexicon's (`roleprofile._LEAD`)
    — not a third copy. The raw parsed value ('Advanced (5-8 Years)') stays for the tooltip."""
    c = (chip or "").lower()
    t = title or ""
    if "junior" in c or "entry" in c or "intern" in c or _JUNIOR.search(t):
        return "Junior"
    if roleprofile._LEAD.search(c) or roleprofile._LEAD.search(t):
        return "Lead+"
    if (any(w in c for w in ("senior", "advanced", "expert", "mid-senior"))
            or _SENIOR.search(t) or _HEBREW_SENIOR.search(t)):
        return "Senior"
    m = re.search(r"(\d+)", c)
    if m:
        y = int(m.group(1))
        return "Lead+" if y >= 8 else "Senior" if y >= 5 else "Mid"
    if "mid" in c:
        return "Mid"
    return "—"


def is_mangled_title(title):
    """Is this "title" a card blob rather than a role's name — a scrape that swallowed the
    bullet list, the location, the whole tile?

    The rule the board has always hidden a card on, named so a second caller can ask the
    same question. `pipeline.run` asks it while SELECTING the email, because hiding the
    card at render time left the role in `out/digest-<date>.json` and `mark_sent` burned
    it as delivered — hidden from the reader and unreachable forever after."""
    t = _s(title)
    return bool(jdtext._MANGLED_TITLE.search(t)) or len(t) > 100


_LAST_RESORT = {
    "company": "", "display_company": "", "display_name": "", "title": "(untitled)", "hebrew_title": False, "mangled": False,
    "url": "", "loc": "Israel (unspecified)", "posted": "", "age": "", "rel_date": "—", "first_seen": "",
    "raw_chip": "", "chip": "—", "rank": 99, "emp": "", "about": "", "facts": [], "skills": [],
    "skill_names": [], "family": "Other", "years": None, "degree": None, "deg_txt": "", "deg_rank": 0,
    "tasks": [], "ai_day": [], "ai_req": [], "soft": [], "resp": [], "req": [], "repost": False,
    "repost_dates": [], "new": False, "blob": "", "also_listed_as": [], "closed_on": "", "issues": [],
}


def _bare(job, run_date):
    """What every card carries even when the description defeats the extractors. Every
    field is coerced to text first: a row whose title is an int is a bad row, not a crash."""
    job = job if isinstance(job, dict) else {}
    title = _s(job.get("title"), 300) or "(untitled)"
    company = _s(job.get("company"), 200)
    pdate = _s(job.get("posted_date"), 40)
    card = dict(_LAST_RESORT, issues=[], facts=[], skills=[], skill_names=[], tasks=[], ai_day=[],
                ai_req=[], soft=[], resp=[], req=[], repost_dates=[], also_listed_as=[])
    card.update({
        "company": company, "display_company": jdtext._display_company(company),
        "title": title, "hebrew_title": bool(jdtext._HEBREW.search(title)),
        "mangled": is_mangled_title(job.get("title")),
        "url": _s(job.get("url"), 2000), "loc": jdtext._norm_location(_s(job.get("location"), 200)),
        "posted": pdate, "age": jdtext._age_note(pdate, run_date), "rel_date": jdtext._rel_date(pdate, run_date),
        "first_seen": _s(job.get("first_seen"))[:10], "emp": jdtext._employment_badge(title),
    })
    return card


def build(job, run_date, *, ledger_rec=None, company_info=None, firmographics=None, archived=False):
    """One card. Raw strings only — the renderer escapes. Never raises."""
    try:
        card = _bare(job, run_date)
    except Exception as e:  # noqa: BLE001 — the row itself is unreadable: name it, ship a stub
        card = dict(_LAST_RESORT, issues=[f"card unreadable ({e.__class__.__name__})"], facts=[], skills=[],
                    skill_names=[], tasks=[], ai_day=[], ai_req=[], soft=[], resp=[], req=[],
                    repost_dates=[], also_listed_as=[])
        card["company"] = _s(job.get("company"), 200) if isinstance(job, dict) else ""
        card["display_company"] = card["company"]
        return card
    try:
        _fill(card, job, run_date, company_info if isinstance(company_info, dict) else {},
              firmographics if isinstance(firmographics, dict) else {})
    except Exception as e:  # noqa: BLE001 — one bad description must not cost the board
        card["issues"].append(f"card degraded ({e.__class__.__name__})")
    try:
        _from_ledger(card, job, ledger_rec, archived)
    except Exception as e:  # noqa: BLE001 — a malformed ledger line is the roles lane's alarm
        card["issues"].append(f"ledger record unreadable ({e.__class__.__name__})")
    return card


def _fill(card, job, run_date, company_info, firmographics):
    company, rtitle = card["company"], card["title"]
    # the evidenced brand, when company-intel recorded one — derived HERE and only here
    # (stored on the card so every surface reads one verdict), and it depends only on the
    # firmographics record: a poisoned description cannot cost the name
    dn = display_name(firmographics.get(company), company, firmographics)
    card["display_name"] = dn
    if dn:
        card["display_company"] = dn
    desc = job.get("description")
    desc = desc if isinstance(desc, str) else _s(desc)
    prof = roleprofile.extract(rtitle, desc)
    resp_parts = jdtext._responsibilities_snippet(desc)
    req_parts = jdtext._requirements_snippet(desc)
    # WHERE an AI mention sits is signal: requirements = prior experience you must
    # bring; responsibilities = something the role will do (learnable on the job)
    ai_req = roleprofile.classify_ai(" • ".join(t for t, _ in req_parts)) if req_parts else []
    soft = roleprofile.classify_soft(" • ".join(t for t, _ in req_parts)) if req_parts else []
    ai_day = roleprofile.classify_ai(" • ".join(resp_parts)) if resp_parts else []
    if not ai_day and not ai_req:
        ai_day = prof["ai"]                 # mentioned only in intro prose
    if resp_parts:
        tasks = roleprofile.classify_tasks(resp_parts)
    else:
        # prose-style JDs ("As an analyst you will …") have no bullet section to
        # extract, but the pre-requirements text still tells us the day-to-day
        d2 = jdtext._LABEL_PREFIX.sub("", jdtext._clean_desc(desc))
        mreq = jdtext._req_header_match(d2)
        intro = (d2[:mreq.start()] if mreq else d2)[:2200]
        # split prose into sentence chunks so the emphasis threshold means something
        chunks = [c for c in jdtext._SENT_SPLIT.split(intro) if len(c) > 15] or ([intro] if intro else [])
        tasks = roleprofile.classify_tasks(chunks)
    raw_chip = jdtext._seniority_chip(desc) or ""
    chip = sen_canon(raw_chip, rtitle)
    skill_names = [s for s, _ in prof["skills"]]
    # degree marker: level + fields + required-vs-plus, e.g. "BSc · CS/Industrial Eng."
    deg = prof["degree"]
    deg_txt = ""
    if deg:
        deg_txt = deg["level"] + (" · " + "/".join(deg["fields"]) if deg["fields"] else "")
        if deg["status"] == "preferred":
            deg_txt += " (a plus)"
    # a posting whose posted_date jumped well past when WE first saw it was re-posted
    # (bumped) by the company — mark it honestly instead of letting it look brand-new
    fs0, pd0 = card["first_seen"], card["posted"][:10]
    repost = False
    try:
        if len(fs0) == 10 and len(pd0) == 10:
            repost = (_dt.date.fromisoformat(pd0) - _dt.date.fromisoformat(fs0)).days >= REPOST_DAYS
    except ValueError:
        repost = False
    fs = pd0 or fs0
    card.update({
        "raw_chip": raw_chip, "chip": chip, "rank": jdtext._sen_rank(raw_chip or chip),
        "about": company_about(company, desc, company_info),
        "facts": firmo_facts(firmographics.get(company)),
        "skills": prof["skills"], "skill_names": skill_names, "family": prof["family"], "years": prof["years"],
        "degree": deg, "deg_txt": deg_txt, "deg_rank": {"BSc": 1, "MSc": 2, "PhD": 3}.get(deg["level"], 0) if deg else 0,
        "tasks": tasks, "ai_day": ai_day, "ai_req": ai_req, "soft": soft,
        "resp": resp_parts, "req": req_parts,
        "repost": repost, "new": (not repost) and bool(fs) and fs >= newcut(run_date),
        # skills + task tokens join the search blob so the filter box finds
        # "sql", "tableau", "reporting", "stakeholders" jobs
        "blob": (f"{company} {rtitle} {card['loc']} {chip} "
                 + " ".join(skill_names) + " " + prof["family"] + " "
                 + " ".join(tok for _, tok in tasks) + " "
                 + " ".join(tok for _, tok in ai_day) + " "
                 + " ".join(tok + "-req" for _, tok in ai_req) + " "
                 + " ".join(tok for _, tok in soft)
                 # the brand joins the blob so the filter finds the row by the name its
                 # cell shows (the registry name stays in the blob's first token)
                 + ((" " + dn) if dn else "")),
    })


def _from_ledger(card, job, rec, archived):
    """The facts only the role record knows. `_claimed_by` is the in-run form (this morning's
    claim resolution, before the ledger flushed); `attribution.claimed_by` the stored one. A
    claimant that is this employer under another spelling is not "also listed as"."""
    claimed = [c for c in (job.get("_claimed_by") or []) if isinstance(c, str)] if isinstance(job, dict) else []
    if isinstance(rec, dict):
        att = rec.get("attribution") or {}
        if isinstance(att, dict):
            claimed += [c for c in (att.get("claimed_by") or []) if isinstance(c, str)]
        dates = sorted(_s(d, 10) for d in (rec.get("reposts") or []) if isinstance(d, str) and d)
        if dates:
            card["repost_dates"] = dates
            card["repost"] = True
            card["new"] = False
        if archived and rec.get("status") == "closed" and isinstance(rec.get("closed_on"), str):
            card["closed_on"] = rec["closed_on"][:10]
    # the brand is this employer's own name too: `Port` shown as `Port.io` must not
    # print `### Port.io _(also listed as Port.io)_` (wave 1, the one live claimant)
    mine = {identity_key(card["company"]), identity_key(card["display_name"])} - {""}
    card["also_listed_as"] = sorted({_s(c, 120) for c in claimed
                                     if _s(c) and identity_key(_s(c)) not in mine
                                     and _s(c) not in (card["company"], card["display_name"])})
    if card["also_listed_as"]:
        card["blob"] += " " + " ".join(card["also_listed_as"])


# --------------------------------------------------------------------------- #
# across cards: the shapes that put a role under the wrong name
# --------------------------------------------------------------------------- #
# a posting on an aggregator is not on a tenant: every company there shares the host
_AGGREGATOR_HOST = re.compile(r"(?:^|\.)(?:linkedin|indeed|glassdoor|drushim|alljobs|jobmaster|google|telegram)\."
                              r"|(?:^|\.)t\.me$", re.I)
# hosts that carry MANY employers, one per first path segment
_PATH_TENANT_HOST = re.compile(r"(?:^|\.)(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
                               r"workable\.com|jobvite\.com|rippling\.com|dover\.com|jazz\.co|"
                               r"pinpointhq\.com)$", re.I)      # breezy.hr / applytojob.com carry the tenant in the host
# path segments that are platform plumbing, never a tenant (roles' list plus the API shapes)
_EXTRA_PLUMBING = {"v0", "v1", "v2", "v3", "postings", "companies", "company", "widget", "accounts",
                   "embed", "job_app", "careers-api", "wday", "cxs", "external", "list", "all-positions",
                   "positions", "posting-api", "job-board", "job-boards", "public", "api", "jobs", "apply"}
try:
    from .roles import _PLUMBING as _ROLES_PLUMBING       # the base list, roles' — when the lane is present
except ImportError:                                       # a tree without roles.py must still render
    _ROLES_PLUMBING = set()
_PLATFORM_MAX = 3       # more distinct employers than this on one "tenant" = a platform host, not a shared board


def _tenant(url):
    """The board a posting was read from. Multi-tenant ATS hosts (Greenhouse, Lever, Ashby,
    Comeet job pages, SmartRecruiters, Workable…) key on host + first non-plumbing path
    segment; every other host carries its tenant in the host itself (Workday, BambooHR, a
    company's own careers site) and keys on the host alone. '' on aggregators."""
    try:
        p = urlparse(_s(url, 2000))
    except ValueError:
        return ""
    host = p.netloc.lower().split("@")[-1].split(":")[0]
    if not host or _AGGREGATOR_HOST.search(host):
        return ""
    if "comeet.co" in host and "/careers-api/" in p.path:
        return ""
    if _PATH_TENANT_HOST.search(host) or "comeet.co" in host:
        segs = [x.lower() for x in p.path.split("/") if x]
        first = next((x for x in segs if x not in _ROLES_PLUMBING and x not in _EXTRA_PLUMBING), "")
        return f"{host}/{first}" if first else ""
    return host


# The query is KEPT: on a company site it is the posting — `?gh_jid=` (11 rows in the store on
# 2026-08-30) and `?ContentID=` (1). What is dropped is a tracking key; none of these occurs on
# any non-aggregator url in the store today, so the set is defensive. Aggregator urls (`?jk=`
# on Indeed, `?_l=` on LinkedIn) never reach the query: `_AGGREGATOR_HOST` returns '' first,
# and THAT — not the query — is what keeps six Indeed employers off one key.
_TRACKING_KEYS = {"_l", "src", "source", "ref", "coref", "gh_src", "utm_source", "utm_medium",
                  "utm_campaign", "utm_content", "utm_term"}
_POSTING_MAX = 2        # one posting belongs to at most two rows; three names on one url is a listing page
# a url that is a board's root, not a posting: two rows stored with `https://x.com/careers` as
# the role url are one LISTING PAGE under two names, not one posting (wave 1) — the strongest
# claim in the mail is not made on a url with no path beyond the tenant, or ending in one of these
_ROOT_WORDS = {"careers", "career", "jobs", "job", "openings", "open-positions", "positions",
               "all-positions", "vacancies", "join-us", "joinus", "work-with-us", "opportunities"}
# on a root path only a query key that names a POSTING makes it one: `?gh_jid=` (Greenhouse
# embedded), `?ContentID=`, `?jobId=`, `?p=` — never `?dept=` / `?location=` (listing filters)
_ID_KEY = re.compile(r"(?:^|[_-])(?:id|jid|nr|no)$|^p$|job|position|posting|opening|vacancy|req", re.I)
_COMEET_POSTING_SEGS = 5     # jobs/<slug>/<token>/<title>/<id>; three segments is the tenant's listing


def _posting_key(url):
    """The POSTING a card was read from — not the board it sits on (`_tenant`). Two cards
    with one key under two company names are one posting published twice.

    ALSO the ledger's collapse key: `roles._pk` reuses this so the claim guard and the
    mail's same-posting warning agree on what a posting is — a change here changes which
    store rows are superseded (roles lane's tests pin the Checkout and Bounce pairs). Host + path,
    lower-cased, a trailing `/application` (Ashby's apply page) and `/` dropped, the query
    kept minus tracking keys; '' on an aggregator, whose url names nobody's posting, and ''
    on a board root or listing page (`_ROOT_WORDS`). Misses, by design — they cost recall,
    never a false pair: the same Greenhouse posting under `boards.` and `job-boards.` hosts,
    Lever's `/apply` variant, `www.` vs bare host."""
    try:
        p = urlparse(_s(url, 2000))
    except ValueError:
        return ""
    host = p.netloc.lower().split("@")[-1].split(":")[0]
    if not host or _AGGREGATOR_HOST.search(host):
        return ""
    path = p.path.lower()
    if path.endswith("/application"):
        path = path[:-len("/application")]
    path = path.rstrip("/")
    q = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                         if k.lower() not in _TRACKING_KEYS))
    segs = [x for x in path.split("/") if x]
    rooty = len(segs) < 2 or segs[-1] in _ROOT_WORDS or segs[-1] in _EXTRA_PLUMBING
    id_in_query = any(_ID_KEY.search(k) for k, _ in parse_qsl(p.query, keep_blank_values=True))
    if rooty and not id_in_query:
        return ""                                 # a board root or a listing page, nobody's posting
    if "comeet.co" in host and len(segs) < _COMEET_POSTING_SEGS:
        return ""                                 # `jobs/<slug>/<token>` is the tenant, not a posting
    return f"{host}{path}?{q}" if q else f"{host}{path}"


# a name and the same name plus one of these is one employer (Kornit / Kornit Digital, Port /
# Port.io, Siemens / Siemens EDA, HP / HP Indigo, one zero / ONE ZERO BANK) — but not plus an
# arbitrary word: Aleph / Aleph Farms and Papaya Gaming / Papaya Global are two companies
_SITE_WORDS = {"digital", "eda", "io", "ai", "bank", "israel", "technologies", "technology", "tech",
               "group", "labs", "ltd", "inc", "indigo", "holdings", "international", "systems",
               "software", "solutions", "media", "web", "services", "corp", "corporation"}
# a name written as its domain is the name: Checkout.com / Checkout, Investing.com / Investing.
# On the RAW name, never on the key — `identity_key` has already turned the dot into a space,
# and as key words `net`/`org` would fold `Green Net` onto `Green` (wave 1). Measured over every
# pair of the 1,099 active names on 2026-08-30: exactly one fold, Checkout.
_DOMAIN_TAIL = re.compile(r"\.(?:com|net|org|co|io|ai)\s*$", re.I)
_PARENT = re.compile(r"\(([^)]{2,40})\)\s*$")


def same_employer(a, b):
    """Two company names that are one employer for the wrong-company checks: equal identity
    keys; equal once spaces are dropped (Spear UAV / SpearUAV, Crazy Labs / CrazyLabs); one
    key is the other plus site/legal words (`_SITE_WORDS`); or one is a division of the other
    written as 'X (Parent)' (Splunk (Cisco) / Cisco, Habana Labs (Intel) / Intel). Not a name
    plus an arbitrary word: Aleph / Aleph Farms are two companies."""
    ra, rb = _s(a), _s(b)
    ka, kb = identity_key(ra), identity_key(rb)
    if not ka or not kb:
        return ra.lower() == rb.lower()
    if ka == kb or ka.replace(" ", "") == kb.replace(" ", ""):
        return True
    if ra.lower().replace(" ", "") == rb.lower().replace(" ", ""):
        return True
    if _DOMAIN_TAIL.search(ra) or _DOMAIN_TAIL.search(rb):
        if identity_key(_DOMAIN_TAIL.sub("", ra)) == identity_key(_DOMAIN_TAIL.sub("", rb)):
            return True
    for x, y in ((ka, kb), (kb, ka)):
        if y.startswith(x + " ") and all(w in _SITE_WORDS for w in y[len(x):].split()):
            return True
    for raw, other in ((ra, kb), (rb, ka)):
        m = _PARENT.search(raw)
        if m and identity_key(m.group(1)) == other:
            return True
    return False


def _names(cards_or_names, n=4):
    xs = sorted(set(cards_or_names))
    return "/".join(xs[:n]) + (f" +{len(xs) - n}" if len(xs) > n else "")


_COMMON_WORDS = {"global", "port", "bounce", "meta", "apple", "matrix", "dream", "anchor", "nova", "rise",
                 "unit", "fabric", "health", "cloud", "data", "digital", "group", "media", "next", "bright",
                 "wave", "point", "check", "mind", "deep", "blue", "green", "open", "smart", "secure",
                 "prime", "first", "one", "zero", "light", "clear", "true", "simple", "pure", "core",
                 "spark", "scale", "shift", "flow", "sense", "vision", "insight", "signal", "edge", "peak"}


def cross_check(cards):
    """Issues visible only ACROSS the cards of one product. Mutates `display_company` where
    two different employers would otherwise share a cell. Returns short strings for the mail:

      same-posting A/B      one posting url under two company names (Checkout / Checkout.com
                            on one Ashby id) — two registry rows read one board; the two guesses
                            below stay silent about that PAIR (a third name on the same tenant
                            is still a shared board) — look, then park the duplicate row
      shared-board A/B      two employers (not one under two spellings) whose cards were read
                            from one ATS tenant (Scopio Labs and Sckipio on one Comeet board):
                            the attribution is whatever `roles._winner` decided — look
      title-twin A/B        one normalised title under two near-identical names (Port /
                            Port.io, Bounce / Bounce AI) — the claim guard saw two postings;
                            a reader will see one role twice — look
      display-collision A/B two differently named employers whose short cell names collide —
                            both now render their full name
      blurb-names-other A→B A's About text names employer B and not A — counted, never
                            dropped (acquirers and customers are named legitimately;
                            company-intel owns the blurb)
    """
    issues = []
    cards = [c for c in cards if isinstance(c, dict)]
    names = sorted({c["company"] for c in cards if c.get("company")})
    # (0) one POSTING, two names — a fact, not a guess, so it is named first and the two
    # guesses below stay silent about the pair (2026-08-30: Checkout / Checkout.com on one
    # Ashby id, Bounce AI / finbounce on one Comeet id, both read as "shared-board … may be
    # under the wrong name" when the data said "the same posting, twice"). More than
    # `_POSTING_MAX` names on one url is a listing page stored as a posting, not a duplicate.
    by_posting = {}
    for c in cards:
        k = _posting_key(c.get("url"))
        if k and c.get("company"):
            by_posting.setdefault(k, set()).add(c["company"])
    same_posting = set()
    for k, ns in by_posting.items():
        if 1 < len(ns) <= _POSTING_MAX:
            pair = tuple(sorted(ns))
            if pair not in same_posting:
                same_posting.add(pair)
                issues.append(f"same-posting {'/'.join(pair)}")
    # (a) one tenant, two employers
    by_tenant = {}
    for c in cards:
        t = _tenant(c.get("url"))
        if t:
            by_tenant.setdefault(t, set()).add(c["company"])
    seen = set()
    for t, ns in by_tenant.items():
        distinct = []
        for n in sorted(ns):                       # `same_employer` is not transitive: fix the order
            if not any(same_employer(n, d) for d in distinct):
                distinct.append(n)
        if 1 < len(distinct) <= _PLATFORM_MAX and tuple(sorted(ns)) not in same_posting:
            key = _names(ns)
            if key not in seen:
                seen.add(key)
                issues.append(f"shared-board {key}")
    # (a') one title under two near-identical names, whatever the boards
    by_title = {}
    for c in cards:
        by_title.setdefault(jdtext._title_key(c["title"]), set()).add(c["company"])
    for t, ns in by_title.items():
        ns = sorted(ns)
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                if (same_employer(ns[i], ns[j]) and ns[i] != ns[j]
                        and (ns[i], ns[j]) not in same_posting):
                    issues.append(f"title-twin {ns[i]}/{ns[j]}")
    # (b) two employers, one short name — judged on the names as written, because the
    # identity key strips exactly the suffixes the short name drops
    by_display = {}
    for c in cards:
        by_display.setdefault(c["display_company"], set()).add(c["company"])
    for short, ns in by_display.items():
        folded = {" ".join(n.lower().split()) for n in ns}
        # a BRAND folding two registry rows onto one cell is a collision even when the
        # raw names fold too (helfy/Helfy both shown "Helfy" would render a registry
        # duplicate as if it were fine — wave 1); a no-brand case-twin stays silent
        branded_merge = len(ns) > 1 and any(
            c.get("display_name") == short for c in cards if c["company"] in ns)
        if len(folded) > 1 or branded_merge:
            issues.append(f"display-collision {_names(ns)}")
            for c in cards:
                if c["company"] in ns:
                    c["display_company"] = c["company"]
                    c["display_name"] = ""      # the revert must win on EVERY surface
    # (c) the About text names a different rendered employer, and not this one
    tokens = {}
    for n in names:
        key = identity_key(n)
        toks = [t for t in key.split() if len(t) >= 4] or ([key] if key else [])
        # one token that is an ordinary English word (Global-e, Port, Bounce, Meta, Rise)
        # would fire on every blurb that uses the word; such a company needs two tokens
        if len(toks) == 1 and (toks[0] in _COMMON_WORDS or len(toks[0]) < 5):
            continue
        if toks:
            tokens[n] = toks
    counted = Counter()
    for c in cards:
        about = (c.get("about") or "").lower()
        me = c.get("company")
        if not about or me not in tokens:
            continue
        if any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", about) for t in tokens[me]):
            continue
        for other, toks in tokens.items():
            if other != me and not same_employer(other, me) and all(
                    re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", about) for t in toks):
                counted[(me, other)] += 1
                break
    for (a, b), n in sorted(counted.items()):
        issues.append(f"blurb-names-other {a}→{b}")
    return sorted(set(issues), key=issues.index)


def report(cards, hidden=0):
    """Counts for one product: (line fragment, alarms). `hidden` = cards not rendered because
    their title was a scraped blob — they are named so the number is never silent. Alarm
    text carries no prefix; the renderer labels the line."""
    degraded = [c for c in cards if c.get("issues")]
    why = Counter(i.split(" (")[0] for c in degraded for i in c["issues"])
    frag = f"{len(cards)} cards"
    alarms = []
    if degraded:
        frag += f", {len(degraded)} degraded ({', '.join(f'{k} {v}' for k, v in why.most_common(3))})"
        alarms.append(f"{len(degraded)} card(s) degraded — "
                      + ", ".join(sorted(set(i for c in degraded for i in c["issues"])))[:160])
    if hidden:
        frag += f", {hidden} hidden: mangled title"
        alarms.append(f"{hidden} role(s) hidden — the scraped title is a card blob, fix the scrape")
    return frag, alarms
