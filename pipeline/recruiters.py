"""Recruiting-agency / staffing-firm exclusion.

These aren't direct employers — they re-post dozens of client roles across unrelated domains,
which floods the digest (a single agency dumped 12-16 "analyst" roles in one run). The user's
spec has always excluded them (same reason SiiRA / Megayeset were out).

Two layers:
  * `_CONFIRMED` — specific names verified as recruiters/staffing via web research (each has a
    dated source in the commit that added it). Names that a keyword rule can't catch (e.g.
    "Talent-HR", "comblack") live here.
  * `_KEYWORD` — a conservative pattern that stops auto-expand from ever adding an obvious new
    agency. Deliberately narrow to avoid false-positives on real employers.
"""
from __future__ import annotations

import re

# Verified recruiters/staffing firms (web-researched 2026-08-17). Lowercase, exact-ish match.
_CONFIRMED = {
    "comblack",                 # "high-tech talent management … places talents at major companies"
    "sqlink group", "sqlink",   # IT recruitment/placement; owns Gotfriends + Dialog placement firms
    "recruitx",                 # "recruitment & headhunting agency"
    "talent-hr", "talent hr",   # staffing/recruitment (hires Recruitment/Talent-Acquisition Specialists)
    "elad software systems",    # IT services + full-cycle IT recruitment/staffing
    # added 2026-08-21 (surfaced by Telegram-channel discovery):
    "experis", "experis israel", "experis academy israel",  # ManpowerGroup staffing brand
    # Hebrew spellings: the registry carries agencies under their Hebrew names too, and a
    # Latin-only list let one back in as an ACTIVE row after the English ones were purged.
    "אקספריס", "אקספריס אקדמי", "מנפאואר", "אלעד מערכות", "ניסן דיגיטל", "אתגר",
    "abra", "abra rnd", "abra r&d",       # IT services/outsourcing; re-posts client roles
    "malamteam", "malam team",            # Malam-Team IT services/outsourcing
    "yael group", "yael korentec technologies",  # IT services group; client placements
    "moveo source",                       # placement/sourcing arm of Moveo consultancy
    "nogamy",                             # IT staffing (posts numbered client roles "JB-####")
    "g-stat",                             # data-consultancy placements (numbered client roles)
    "log-on software",                    # IT services/outsourcing
    "matchit",                            # placement ("MatchIT" = match-to-IT-roles)
    # added 2026-08-23: its companies.csv row was deactivated for exactly this reason
    # ("outsourcing partner re-posting Similarweb roles - covered directly"), but the
    # discovery layer carries the employer NAME, not the row, so its re-posts kept coming
    # in under a company we already scan.
    "alpha | similarweb partner", "alpha similarweb partner",
    # Added 2026-08-25. Both were classified as staffing firms by OUR OWN enrichment layer
    # (cloud_state/firmographics.json: Nisha Pro 2026-08-25 "IT staffing / workforce
    # outsourcing … placement fees"; Shavit Software 2026-08-22 "IT staffing / outsourcing …
    # placing … BI … consultants at client companies") while is_recruiter() said no — and
    # Nisha Pro was published in the 2026-08-25 email as a newly covered company, its blurb
    # saying "staffing" directly under the role. No Hebrew form of Nisha Pro exists in any
    # data file (grep 2026-08-25 = 0), so none is listed; Shavit's is in _HEBREW_MARKERS.
    "nisha pro", "nisha group", "shavit software",
    # Added 2026-08-26, after the 05:38 mail published `### Jobgether` as a covered employer
    # with a role under it. These are JOB-BOARD / PLACEMENT BRANDS, not employers of the
    # roles they carry, and the category differs per entry — say which, or the next session
    # researching "Jobgether" finds a claim about staffing the evidence does not support:
    #   jobgether  - a remote-job AGGREGATOR. `jobgether.` is already on aggregators.HOSTS
    #                beside remoteok./weworkremotely.: this repo had ruled on its HOST and
    #                not on its NAME, and the name is what a discovery card carries. 15 cards
    #                in the committed cache on 2026-08-26, one of them mailed.
    #   ethosia    - an Israeli HR / placement agency; `ethosia.` on aggregators.HOSTS beside
    #                drushim.co.il / alljobs.co.il / gotfriends. 2 cards.
    #   staffin    - staffing, and the `_KEYWORD` rule misses it: `\bstaffing\b` does not
    #                match "Staffin". 1 card. ("Quik Hire Staffing" needs no entry - the
    #                keyword already catches it; verified 2026-08-26.)
    # The bare brand is listed beside the display form because LinkedIn display names drift
    # (the `experis` / `experis israel` / `experis academy israel` trio above exists for that
    # reason) and the exact-match list matches the WHOLE name: "Staffin" or "Ethosia Human
    # Resources" would otherwise walk straight past. Measured over the 3,586 (name, slug)
    # pairs in companies.csv u research_companies.json u discovered_cache.json: these entries
    # flip exactly 3 names and ZERO companies.csv rows, active or parked.
    # Deliberately NOT derived from aggregators.HOSTS by brand stem, which was tried and
    # measured: the stems include `google` (google.com/search), and Google is a real employer
    # with 12 cached cards. Pinned as the counter-example in the guard.
    # No Hebrew form of any of the three exists in any data file (grep 2026-08-26 = 0 for
    # this repo's files), so none is listed - same evidence standard as Nisha Pro above.
    "jobgether", "ethosia", "ethosia human resources", "staffin", "staffin israel",
    # Researched and KEPT OUT the same day, same firmographics scan: Genpact ("IT services /
    # business process outsourcing", 40/40 IL on its own board) and appsforce ("software
    # outsourcing", an active deep-validated row) both hire directly — the Matrix case.
}

# Some agencies are only ever written in Hebrew, and some carry the parent group in the
# name ("Mertens – part of the Malam-Team group"), which no exact-match entry catches.
# These are substring markers, checked against the whole name.
_HEBREW_MARKERS = (
    "מלם תים",        # Malam-Team: IT services / outsourcing, re-posts client roles
    "מרטנס",          # Mertens, its placement arm
    "מנפאואר",        # ManpowerGroup
    "אקספריס",        # Experis
    "השמה",           # "placement"
    "גיוס והשמה",     # "recruitment and placement"
    "כוח אדם",        # "manpower"
    # Added 2026-08-23. Both appeared as employer names in ONE live Indeed query
    # ("data analyst", il.indeed.com via the Web Unlocker) and both passed is_recruiter()
    # AND looks_like_junk(), i.e. each was one auto-expand run away from a companies.csv
    # row. This is the exact failure the block above was written for: the Latin entry
    # exists and the Hebrew spelling walks past it.
    "קומבלק",         # Comblack IT Ltd — `comblack` is already in _CONFIRMED in Latin
    "חברה דיסקרטית",  # "discreet company": Israeli-board equivalent of the `confidential`
                      # entry in _CONFIRMED — an anonymous agency posting, not an employer
    # Two more of the same shape, found the same day by re-running the scan below over the
    # 99 companies one live intake pass queued. Both names are ALREADY on the Latin list
    # above and both walked straight past it:
    "קבוצת יעל",      # Yael Group — `yael group` / `yael korentec technologies`
    "לוג-און תוכנה",  # Log-On Software — `log-on software`
    # Third time the same shape: found 2026-08-25 as its OWN research-queue entry beside
    # the Latin "Shavit Software", seeded from an Indeed posting whose title names a
    # client ("לחברה מובילה במרכז דרוש/ה אנליסט/ית") — the Idor Computers tell.
    "שביט סופטוור",   # Shavit Software — `shavit software`
    # Re-run after touching _CONFIRMED. Anything Hebrew that prints here and is a staffing
    # or IT-outsourcing firm belongs above. It scans the QUEUE and the job cache as well as
    # the registry: the 2026-08-25 twin (Shavit) was in research_companies.json, one
    # auto_expand run before it would have reached companies.csv where this used to look.
    #   python -c "
    #   import re,csv,json
    #   from pipeline.recruiters import is_recruiter
    #   from pipeline.firmographics import looks_like_junk
    #   h=re.compile(r'[֐-׿]')
    #   names={r[0] for r in csv.reader(open('companies.csv',encoding='utf-8')) if r}
    #   names|={e['name'] for e in json.load(open('research_companies.json',encoding='utf-8'))}
    #   names|={j['company'] for j in json.load(open('discovered_cache.json',encoding='utf-8'))}
    #   for n in sorted(names):
    #       if h.search(n) and not is_recruiter(n) and not looks_like_junk(n): print(n)"
    # Researched 2026-08-23 (web + the wording of their own postings), not guessed:
    "עידור מחשבים",   # Idor Computers, ~100 staff, "professional IT outsourcing services"
                      # for banks/insurers. Decided by its OWN posting, which names a CLIENT
                      # and not itself: "אנליסט/ית אקטואר לחברת ביטוח מובילה בפתח תקווה"
                      # (actuarial analyst FOR A LEADING INSURANCE COMPANY). Same class as
                      # log-on software / abra / malam team above.
    # Deliberately NOT listed, and both were checked rather than left unknown:
    #   מטריקס (Matrix IT) — 16,000 staff, TASE-listed (MTRX). It does sell outsourcing, but
    #     it is also a large direct employer AND we already scan it: `Matrix` (comeet) and
    #     `Matrix IT` (breezy) are both active rows, deep-verified 25/0 and 34/0 IL on
    #     2026-08-21. Blocking the Hebrew form would contradict two verified rows. The real
    #     defect there is that it is a THIRD identity for one employer — an alias problem,
    #     not a recruiter problem (docs/BACKLOG.md, "One identity layer").
    #   Software AG-SPL — surfaced by the same client-naming scan
    #     ("Network security analyst לארגון בטחוני במרכז") but it is Software AG's Israeli
    #     R&D centre, formerly SPL, a real product employer. The scan is a FINDING AID for
    #     names to research, never a filter.
)

# Obvious agency markers — blocks future auto-expand additions. Narrow on purpose.
_KEYWORD = re.compile(
    # `recruit(ing|ment|x)?\b` could not match the plural NOUN -- "Acme Recruitment" was
    # refused and "Acme Recruiters" walked through -- and `\b` never fires between a letter
    # and a digit, so "Human Capital Recruitment1" (a real queue entry, 2026-08-30) passed
    # too. Measured before widening: 3 of 572 queue names newly refused, 0 ACTIVE registry
    # rows, 1 parked row ("Yamo Overseas Recruiters Limited", correctly); re-checked over
    # 2,697 distinct names across registry, queue, cache and firmographics: those 4 and no
    # other. The closing boundary is `(?![a-z])` -- "not an ASCII letter" (re.I covers the
    # upper case) -- so a digit, `_` or a non-Latin letter now ends the token where `\b`
    # did not; the singular `recruiter` is caught too.
    r"\b(recruit(ing|ment|ers?|x)?|staffing|headhunt(ing|ers?)?|manpower|"
    r"placement agenc|talent acquisition|gotfriends|hr solutions|hr consulting)(?![a-z])", re.I)


# An ANONYMISED employer -- "Undisclosed", "Stealth Startup", "Confidential Global Company".
# Not a recruiter and not a company: it is a placeholder where the employer name should be,
# and it defeats every downstream identity check for the same reason "Tel Aviv" does -- there
# is no company to prove a board against. `confidential` / `confidential careers` lived in
# `_CONFIRMED` for want of a home (removed in this commit: this rule subsumes both, and the
# Hebrew `חברה דיסקרטית` in `_HEBREW_MARKERS` is the same class again).
#
# THE RULE IS WHOLE-NAME, not substring, and that is the whole of its safety: a name is
# refused only when EVERY word is an anonymiser or generic corporate filler. `Confidential
# Computing Inc`, `Stealth Security Ltd`, `Discreet Logic` and `Anonymous Analytics Ltd` are
# real-company shapes and all four pass. Blast radius measured 2026-09-03 over the 2,757
# distinct names in registry u queue u cache u firmographics: **8 newly refused, 0 of them an
# ACTIVE row** -- `Confidential Careers`, `Confidential Company`, `Confidential Global
# Company` and `Stealth Startup`, each already a PARKED row that scans empty forever, plus the
# same four as cache cards. `Undisclosed` and `Discreet Company` arrived from LinkedIn the
# same morning (docs/decisions/2026-09-03-discovery-description-queries.md).
_ANON_WORD = (r"undisclosed|confidential|discreet|anonymous|unnamed|stealth")
_ANON_FILLER = (r"company|companies|careers|career|global|startup|start-?up|mode|ltd|limited|"
                r"inc|corp|group|jobs|employer|client|israel|il|the|a|an|of|and|co")
_ANON_ANY = re.compile(r"\b(?:%s)\b" % _ANON_WORD, re.I)
_ANON_ONLY = re.compile(r"^(?:\W*(?:%s|%s)\b\W*)+$" % (_ANON_WORD, _ANON_FILLER), re.I)


def is_anonymous_employer(name):
    """True when the whole NAME is an anonymiser plus corporate filler, and nothing else.

    Named for what it tests rather than folded into `_CONFIRMED` as a list of spellings: the
    class is open (`Undisclosed`, `Stealth Mode Startup`, `Confidential Global Company` are
    all the same posting convention) and an exact-match list cannot close it -- which is how
    four rows of it reached `companies.csv` while `confidential` sat on the list.
    """
    n = " ".join(str(name or "").strip().lower().split())
    return bool(n) and bool(_ANON_ANY.search(n)) and bool(_ANON_ONLY.match(n))


def is_recruiter(name, slug=""):
    """True for a staffing / placement firm, OR an anonymised employer name (see
    `is_anonymous_employer`: neither is a company we can resolve a board for, and both
    reach this predicate so that every existing caller gets both).

    `slug` is optional and FREE evidence: a
    LinkedIn company slug often says what the display name hides — "Dialog" (8 cached
    cards, 2026-08-25) is `dialog-recruiting`, and recruiters.py's own comment has named
    Dialog as an SQLink placement firm since 2026-08-17. The slug was captured on 827 of
    848 cached LinkedIn jobs and read by nothing."""
    if slug and _is_recruiter_name(str(slug).replace("-", " ")):
        return True
    return _is_recruiter_name(name)


def _is_recruiter_name(name):
    n = " ".join(str(name or "").strip().lower().split())
    # hyphen == space for the exact-match list, or "Malam-Team" misses the "malam team"
    # entry that was added for it. Both spellings appear in the registry.
    variants = {n, n.replace("-", " "), n.replace("-", "")}
    if variants & _CONFIRMED:
        return True
    if any(m in n for m in _HEBREW_MARKERS):
        return True
    if is_anonymous_employer(n):
        return True
    return bool(_KEYWORD.search(n))
