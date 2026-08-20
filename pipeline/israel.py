"""Deterministic Israel-location matching.

Used to filter global/multinational boards (Workday, Amazon, big Greenhouse tenants)
down to Israel-based postings before anything reaches seniority classification.

Two signals, checked in order:
  1. An explicit country code on the posting (ISO alpha-2 "IL" or alpha-3 "ISR").
  2. Israeli place-names appearing in any location/URL text on the posting.

Signal 1 is authoritative when present. Signal 2 is the fallback for platforms that
don't expose a machine-readable country (Lever's free-text location, Workday's
externalPath slug, etc.).
"""
from __future__ import annotations

import re

# ISO country codes that mean Israel.
_IL_COUNTRY_CODES = {"IL", "ISR", "ISL_ISRAEL"}  # ISL guarded below (Iceland is ISL/IS)

# Canonical: only these two are Israel. Kept separate to avoid the Iceland (IS/ISL) trap.
IL_ALPHA2 = "IL"
IL_ALPHA3 = "ISR"

# Israeli cities / regions / common English + transliteration variants. Lowercased.
# Word-boundary matched so "haifa" won't match inside an unrelated token.
_IL_PLACES = [
    "israel",
    "tel aviv", "tel-aviv", "telaviv", "tel aviv-yafo", "tel aviv-jaffa",
    "jerusalem",
    "haifa",
    "herzliya", "herzelia", "herzeliya", "hertzeliya", "herzliya pituach",
    "ra'anana", "raanana", "ra anana",
    "netanya", "nathania",
    "ramat gan", "ramat-gan",
    "petah tikva", "petach tikva", "petah tiqwa", "petah-tikva",
    "beer sheva", "be'er sheva", "beersheba", "beer-sheva", "beersheva",
    "yokneam", "yoqneam",
    "caesarea", "qesarya",
    "kiryat gat", "kiryat-gat",
    "kiryat ono", "kiryat motzkin", "kiryat shmona", "kiryat bialik",
    "rehovot", "rechovot",
    "hod hasharon", "hod ha'sharon",
    "or yehuda",
    "airport city",
    "modiin", "modi'in", "modiin-maccabim-reut",
    "ness ziona", "rishon lezion", "kfar saba", "tirat carmel", "nes ziona", "nes tziona",
    "givatayim",
    "holon",
    "rosh haayin", "rosh ha'ayin", "rosh ha ayin",
    "karmiel", "carmiel",
    "migdal haemek", "migdal ha'emek",
    "yakum",
    "bnei brak", "bene beraq",
    "lod",
    "ashdod",
    "ashkelon",
    "ramat hahayal", "ramat ha'hayal",
    "afek", "rosh haayin",
    "sderot",
    "nazareth", "nazareth illit", "nof hagalil",
    "tirat carmel", "tirat hakarmel",
    "even yehuda",
    "azor",
]

# Precompiled word-boundary regexes for place matching.
_PLACE_PATTERNS = [
    re.compile(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", re.IGNORECASE)
    for p in _IL_PLACES
]


def country_is_israel(code) -> bool:
    """True iff an explicit country code denotes Israel. Robust to case/whitespace.

    Deliberately does NOT accept "IS" or "ISL" (those are Iceland) — only IL / ISR.
    """
    if not code:
        return False
    c = str(code).strip().upper()
    return c in {IL_ALPHA2, IL_ALPHA3}


def text_mentions_israel(*texts) -> bool:
    """True iff any Israeli place-name appears in the given text fragments."""
    for t in texts:
        if not t:
            continue
        s = str(t)
        for pat in _PLACE_PATTERNS:
            if pat.search(s):
                return True
    return False


def is_israel_job(job) -> bool:
    """Decide whether a normalized job posting is Israel-based.

    `job` is a normalized dict (see pipeline.fetchers). Uses country_code first
    (authoritative), then falls back to scanning location + url text.
    """
    if country_is_israel(job.get("country_code")):
        return True
    # Some feeds set a non-IL country code confidently (e.g. "US"): trust that as a
    # negative and skip the text scan to avoid a US posting that merely mentions an
    # Israeli city in its body. Only fall through to text when country is unknown.
    code = job.get("country_code")
    if code and str(code).strip():
        return False
    return text_mentions_israel(job.get("location"), job.get("url"))
