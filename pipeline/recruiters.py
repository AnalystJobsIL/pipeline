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
