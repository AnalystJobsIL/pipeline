"""Deterministic Israel-location matching.

Used to filter global/multinational boards (Workday, Amazon, big Greenhouse tenants)
down to Israel-based postings before anything reaches seniority classification.

Three signals, checked in order:
  1. An explicit country code on the posting (ISO alpha-2 "IL" or alpha-3 "ISR").
  2. The posting's OWN text naming an office abroad and no Israeli place anywhere
     (`stated_foreign_place`, 2026-09-13): a city ending the title, a place glued to it, or a
     `Location:` line under a weak location field. It only ever says no.
  3. Israeli place-names appearing in any location/URL text on the posting.

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


# --------------------------------------------------------------------------- #
# The posting's OWN statement that it is somewhere else (docs/BACKLOG.md 566)
# --------------------------------------------------------------------------- #
# `location` is often not the posting's word: an aggregator stamps its search region
# (`il.indeed.com` wrote `מחוז המרכז` over Diageo's `Location: 3 WTC (New York)`), and a
# careers widget copies one chip onto every card (Wiliot's eight cards read `Israel` while
# the office sits glued to each title: `Data Solutions AnalystSan Mateo`). The rule below is
# ONE-SIDED: it can only take a posting OUT, never put one in, and it is silent whenever an
# Israeli place appears anywhere in the title or the description -- a Tel Aviv JD that names
# its New York HQ is the common case and must not move.
#
# CITIES decide, not countries or regions, in a title. Measured 2026-09-13 over both caches:
# every region/country suffix on an Israel-located card was a TERRITORY (`KYC Analyst …
# EMEA` in Tel Aviv, `Sales account manager – europe` in Rosh Ha'ayin: 9 of 9 discovered
# flips of a broader draft were wrong), while every city suffix was an office (Wiliot,
# Wayve's `…Leonberg, Germany`, Adcore's `– Toronto, Canada`). A country counts only where it
# cannot be a territory: glued to the title by a widget, or on a labelled `Location:` line.
# A city here is a closed list, spelled as it is written; a word that is also an English
# word or a surname (Reading, Mobile, Nice, Phoenix, Lima, Victoria, Georgia, Jordan) is
# deliberately absent.
FOREIGN_CITIES = (
    "New York", "NYC", "San Francisco", "San Mateo", "San Jose", "Sunnyvale", "Palo Alto",
    "Mountain View", "Menlo Park", "Redwood City", "Santa Clara", "Los Angeles", "San Diego",
    "Seattle", "Boston", "Chicago", "Austin", "Dallas", "Houston", "Denver", "Atlanta",
    "Miami", "Detroit", "Philadelphia", "Minneapolis", "Nashville", "Charlotte", "Raleigh",
    "Pittsburgh", "Salt Lake City", "Washington DC", "Washington, DC", "Washington D.C.",
    "Toronto", "Montreal", "Vancouver", "Ottawa",
    "London", "Manchester", "Edinburgh", "Dublin", "Berlin", "Munich", "Hamburg", "Frankfurt",
    "Stuttgart", "Leonberg", "Cologne", "Paris", "Lyon", "Amsterdam", "Rotterdam", "Brussels",
    "Zurich", "Geneva", "Vienna", "Madrid", "Barcelona", "Lisbon", "Porto", "Milan", "Rome",
    "Warsaw", "Krakow", "Kraków", "Wroclaw", "Wrocław", "Prague", "Budapest", "Bucharest",
    "Sofia", "Belgrade", "Kyiv", "Kiev", "Lviv", "Athens", "Limassol", "Nicosia", "Larnaca",
    "Istanbul", "Stockholm", "Copenhagen", "Oslo", "Helsinki", "Tallinn", "Riga", "Vilnius",
    "Dubai", "Abu Dhabi", "Bangalore", "Bengaluru", "Mumbai", "Pune", "Hyderabad", "Chennai",
    "Gurgaon", "Gurugram", "Noida", "New Delhi", "Singapore", "Hong Kong", "Shanghai",
    "Beijing", "Shenzhen", "Tokyo", "Seoul", "Taipei", "Manila", "Sydney", "Melbourne",
    "Sao Paulo", "São Paulo", "Mexico City", "Buenos Aires", "Bogota", "Bogotá",
)
FOREIGN_COUNTRIES = (
    "United States", "United Kingdom", "England", "Germany", "France", "Spain", "Portugal",
    "Italy", "Netherlands", "Belgium", "Switzerland", "Austria", "Ireland", "Poland",
    "Ukraine", "Romania", "Bulgaria", "Serbia", "Croatia", "Greece", "Cyprus", "Turkey",
    "Czech Republic", "Czechia", "Hungary", "Sweden", "Denmark", "Norway", "Finland",
    "Estonia", "Latvia", "Lithuania", "India", "China", "Japan", "Australia", "Canada",
    "Mexico", "Brazil", "Argentina", "Colombia", "Philippines", "Vietnam", "Thailand",
    "Indonesia", "South Korea", "United Arab Emirates", "UAE",
    # US states, spelled out: an office line writes `Austin, Texas`. Not Georgia or
    # Washington (a country and a city), and never the two-letter `IL`.
    "California", "Texas", "New Jersey", "Massachusetts", "Florida", "Illinois", "Colorado",
    "Virginia", "North Carolina", "Pennsylvania", "Ohio", "Michigan", "Arizona", "Oregon",
    "Utah", "Minnesota",
)


def _alt(names):
    return "|".join(re.escape(n).replace(r"\ ", r"\s+")
                    for n in sorted(names, key=len, reverse=True))


# `US`/`UK`/`USA` are case-sensitive: `us` is a pronoun
_ABBR = r"U\.S\.A?\.?|USA|US|UK"
_TAIL = r"(?:\s*,\s*[^,\n]{0,40}){0,2}(?:\s*\([^)\n]{0,24}\))?\s*\)?\s*$"
# a city at the end of a title, after a separator: `… - Houston`, `… (New York)`,
# `Compliance Officer - San Francisco`, `…Sunnyvale, California USA`
_TITLE_CITY = re.compile(r"(?<![A-Za-z])(" + _alt(FOREIGN_CITIES) + r")" + _TAIL, re.I)
# ...or a place GLUED to the title by a widget that drops the separator: a lower-case letter
# (or a closing bracket) followed by a capitalised place. Case-sensitive by construction, so
# a country is safe here -- a territory is never glued.
_TITLE_GLUED = re.compile(r"(?<=[a-z0-9)])(" + _alt(FOREIGN_CITIES + FOREIGN_COUNTRIES)
                          + r")" + _TAIL)
# a labelled location line inside the description: `Location: 3 WTC (New York)`,
# `<br>Job Location: Austin, TX`, `Role: … | Location: London`. The label must be followed
# by a colon or a spaced dash, so `location-based` is not a label; the value stops at the
# end of the line, so an empty label never borrows the NEXT line's words.
_LOC_LINE = re.compile(r"(?:^|[\n>|•·])[ \t]*(?:job[ \t]+|work[ \t]+|office[ \t]+)?"
                       r"(?:location|מיקום)[ \t]*(?::|[-–][ \t])[ \t]*([^\n|<]{1,120})",
                       re.I)
_PLACE_ANY = re.compile(r"(?<![A-Za-z])(?:" + _alt(FOREIGN_CITIES + FOREIGN_COUNTRIES)
                        + r")(?![A-Za-z])", re.I)
_ABBR_ANY = re.compile(r"(?<![A-Za-z])(?:" + _ABBR + r")(?![A-Za-z])")
# `, TX` -- a US state code, IL excluded (Comeet writes Israel that way)
_STATE_CODE = re.compile(r",\s*(?:A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[DAN]|KS|KY|LA|M[EDAINSOT]|"
                         r"N[EVHJMYCD]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[TA]|W[AVIY])(?![A-Za-z])")
# a location field that is not the posting's own word: nothing, the bare country, a work
# mode. An aggregator's url makes ANY location weak (its region stamp, not the employer's).
_WEAK_LOCATION = {"", "israel", "ישראל", "remote", "hybrid", "anywhere"}


def _location_is_weak(job) -> bool:
    loc = re.sub(r"[^\w֐-׿]+", " ", str(job.get("location") or "")).strip().lower()
    if loc in _WEAK_LOCATION:
        return True
    from .aggregators import is_aggregator          # late: stdlib-only, but keep israel.py's
    return is_aggregator(str(job.get("url") or ""))  # import surface at `re`


# how many cards THIS process's gate refused on the posting's own text: the classifier's
# step-log line prints it, so an unattended run proves the arm fired (a list, so the count
# is mutable without a `global` at 33 call sites)
VETOED = [0]


def vetoed() -> int:
    return VETOED[0]


def stated_foreign_place(job):
    """The place outside Israel that the posting's OWN text names, as `"title:<place>"` or
    `"description:<place>"`, or `None`.

    Two arms, and each needs its evidence to be the posting's rather than the feed's:

    * **title** — a listed CITY ending the title after a separator, or any listed city or
      country GLUED to it (`AnalystSan Mateo`). A trailing country or region alone is a
      territory and never fires (9 of 9 measured).
    * **description** — a labelled `Location:` line naming a listed place, a `US`/`UK`
      abbreviation or a `, ST` state code — ONLY when the card's own location is weak
      (empty, the bare word `Israel`, a work mode, or an aggregator's url). A company board
      that says `On Site - Kiryat Gat, Israel` outranks a line in text that may be another
      posting's bleed (Gamida Cell, `552`): that is the second signal `548` asks for.

    Both are silenced by any Israeli place anywhere in the title or the description, checked
    LAST because it is the expensive scan and a foreign statement is rare."""
    title = str(job.get("title") or "")
    found = None
    m = _TITLE_CITY.search(title) or _TITLE_GLUED.search(title)
    if m:
        found = "title:" + " ".join(m.group(1).split())
    desc = job.get("description")
    desc = desc if isinstance(desc, str) else ""
    if found is None and desc and _location_is_weak(job):
        for lm in _LOC_LINE.finditer(desc):
            val = lm.group(1)
            hit = _PLACE_ANY.search(val) or _ABBR_ANY.search(val) or _STATE_CODE.search(val)
            if hit:
                found = "description:" + " ".join(hit.group(0).strip(", ").split())
                break
    if found is None:
        return None
    if text_mentions_israel(title, desc):
        return None
    return found


def is_israel_job(job) -> bool:
    """Decide whether a normalized job posting is Israel-based.

    `job` is a normalized dict (see pipeline.fetchers). Uses country_code first
    (authoritative), then the posting's own statement that it is elsewhere
    (`stated_foreign_place`), then falls back to scanning location + url text.
    """
    if country_is_israel(job.get("country_code")):
        return True
    # Some feeds set a non-IL country code confidently (e.g. "US"): trust that as a
    # negative and skip the text scan to avoid a US posting that merely mentions an
    # Israeli city in its body. Only fall through to text when country is unknown.
    code = job.get("country_code")
    if code and str(code).strip():
        return False
    # the title or the posting's own location line names an office abroad, and nothing on
    # it names Israel: the location field was the feed's word, not the posting's (566)
    if stated_foreign_place(job):
        VETOED[0] += 1
        return False
    return text_mentions_israel(job.get("location"), job.get("url"))
