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
}

# Obvious agency markers — blocks future auto-expand additions. Narrow on purpose.
_KEYWORD = re.compile(
    r"\b(recruit(ing|ment|x)?|staffing|headhunt(ing|ers?)?|manpower|"
    r"placement agenc|talent acquisition|gotfriends|hr solutions)\b", re.I)


def is_recruiter(name):
    n = " ".join(str(name or "").strip().lower().split())
    if n in _CONFIRMED:
        return True
    return bool(_KEYWORD.search(n))
