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
    "confidential careers", "confidential",  # anonymous agency postings
    # added 2026-08-23: its companies.csv row was deactivated for exactly this reason
    # ("outsourcing partner re-posting Similarweb roles - covered directly"), but the
    # discovery layer carries the employer NAME, not the row, so its re-posts kept coming
    # in under a company we already scan.
    "alpha | similarweb partner", "alpha similarweb partner",
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
    # Re-run after touching _CONFIRMED. Anything Hebrew that prints here and is a staffing
    # or IT-outsourcing firm belongs above:
    #   python -c "
    #   import re,csv
    #   from pipeline.recruiters import is_recruiter
    #   from pipeline.firmographics import looks_like_junk
    #   h=re.compile(r'[֐-׿]')
    #   for r in csv.reader(open('companies.csv',encoding='utf-8')):
    #       if r and h.search(r[0]) and not is_recruiter(r[0]) and not looks_like_junk(r[0]):
    #           print(r[0])"
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
    r"\b(recruit(ing|ment|x)?|staffing|headhunt(ing|ers?)?|manpower|"
    r"placement agenc|talent acquisition|gotfriends|hr solutions)\b", re.I)


def is_recruiter(name):
    n = " ".join(str(name or "").strip().lower().split())
    # hyphen == space for the exact-match list, or "Malam-Team" misses the "malam team"
    # entry that was added for it. Both spellings appear in the registry.
    variants = {n, n.replace("-", " "), n.replace("-", "")}
    if variants & _CONFIRMED:
        return True
    if any(m in n for m in _HEBREW_MARKERS):
        return True
    return bool(_KEYWORD.search(n))
