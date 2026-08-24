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
    # the Latin siblings of Hebrew names below that had none (2026-08-24). Not bare "acre":
    # `(?<![a-z])acre(?![a-z])` matches US street addresses; "akko" carries that city.
    "yavne", "yavneh", "afula", "tiberias", "eilat", "dimona", "safed", "tzfat", "akko",
    "nahariya",
    # districts (how Greenhouse/Lever tenants write an Israeli office) and the towns a
    # 41-board live sample + a hand list found missing (2026-08-24 wave 1)
    "center district", "central district", "tel aviv district", "haifa district",
    "northern district", "southern district", "jerusalem district", "hamerkaz", "tlv",
    "yehud", "beit shemesh", "bet shemesh", "rosh pina", "zichron yaakov", "zikhron yaakov",
    "gedera", "netivot", "ofakim", "nesher", "kiryat tivon", "binyamina", "pardes hanna",
    "petah tiqva", "kfar sava", "hertzliya", "herzliyya", "qiryat gat", "qiryat ono",
    "rishon letsiyon", "kiryat yam",
]

# The same places in Hebrew. An Israeli careers page writes its own locations in Hebrew —
# "תל אביב", "מחוז המרכז" — and the scraper already recognised them when deciding a card was
# Israeli, but this module did not, so it then dropped the role it had just found. The two
# lists must stay together for that reason: `scrape_universal.ISRAEL_LOC` is derived from
# BOTH (guarded by check_invariants check G).
_IL_PLACES_HE = [
    "ישראל",
    "תל אביב", "תל-אביב", "תל אביב-יפו",
    "ירושלים",
    "חיפה",
    "הרצליה", "הרצליה פיתוח",
    "רעננה",
    "נתניה",
    "רמת גן", "רמת-גן",
    "פתח תקווה", "פתח-תקווה", "פתח תקוה",
    "באר שבע", "באר-שבע",
    "יקנעם", "יקנעם עילית",
    "קיסריה",
    "קרית גת", "קריית גת", "קרית אונו", "קריית אונו", "קרית שמונה", "קרית מוצקין",
    "רחובות",
    "הוד השרון",
    "אור יהודה",
    "עיר הימים", "קרית שדה התעופה",
    "מודיעין", "מודיעין-מכבים-רעות",
    "נס ציונה", "ראשון לציון", "כפר סבא", "טירת כרמל",
    "גבעתיים",
    "חולון",
    "ראש העין",
    "כרמיאל",
    "מגדל העמק",
    "בני ברק",
    "לוד",
    "אשדוד",
    "אשקלון",
    "רמת החייל",
    "שדרות",
    "נצרת", "נוף הגליל",
    "אבן יהודה",
    "אזור",
    "יבנה", "עפולה", "טבריה", "אילת", "דימונה", "צפת", "עכו", "נהריה",
    # regions, which is how Indeed writes an Israeli location
    "מחוז המרכז", "מחוז תל אביב", "מחוז הצפון", "מחוז הדרום", "מחוז ירושלים",
    "מחוז חיפה", "השרון", "שפלת יהודה",
]

# Precompiled word-boundary regexes for place matching. The lookarounds are ASCII-only on
# purpose: a Hebrew name is already delimited by the surrounding punctuation/whitespace, and
# `(?<![a-z])` never blocks it. A digit AFTER a name blocks it ("lod3BakeYZ7" was a Siemens
# junk location that passed on `lod`) but a digit BEFORE does not: two real Get SAT rows carry
# the mangled location `u0022Israel` (wave 2, 2026-08-25). A space inside a name
# also matches a hyphen — the scraper's `ISRAEL_LOC` already accepted "Kfar-Saba" and this
# module then dropped the role it had just found (32 such forms, 2026-08-24).
_PLACE_PATTERNS = [
    re.compile(r"(?<![a-z])" + re.escape(p.replace("'", "")).replace(r"\ ", r"[\s-]")
               + r"(?![a-z0-9])", re.IGNORECASE)
    for p in _IL_PLACES + _IL_PLACES_HE
]
# apostrophes and the Hebrew maqaf are spelling, not delimiters: Giv'atayim / Yoqne'am /
# תל־אביב must read as the listed form
_SPELLING = str.maketrans({"'": "", "\u2019": "", "\u05be": "-", "`": ""})


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
        s = str(t).translate(_SPELLING)
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
