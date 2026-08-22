"""Does this URL actually belong to this company?

The resolution ladder verifies a candidate page by scraping it and counting Israel jobs.
That check answers "are there Israel roles here?" but never "are they THIS company's?" —
so any page listing real Israel jobs would activate the row. Live damage found 2026-08-23:

    FairFly    <- fireflyspace.com        (Firefly Aerospace, 25 roles)
    Ironblocks <- fireblocks.com          (Fireblocks, 11 roles)
    COTI       <- jobs.citi.com           (Citigroup, 4 roles)
    1MRobotics <- careers.micron.com      (Micron, 1 role)
    L7 Defense <- search-careers.gm.com   (General Motors, 2 roles)
    factify    <- duckduckgo.com          (a search results page)

The hard part is that plenty of legitimate boards look nothing like the company name:
acronym domains (Texas Instruments -> ti.com, Schneider Electric -> se.com), ATS hosts
(boards.greenhouse.io/<token>), and brand/parent relationships (AWS -> amazon.jobs). So
this returns a three-way verdict and the caller decides; "unknown" should mean *document
for review*, never *activate silently*.
"""
from __future__ import annotations

import re
import urllib.parse

# Hosts where the company identity lives in the PATH/token, not the domain. The token is
# already slug-checked at resolution time, so the domain proves nothing either way.
ATS_HOST = re.compile(
    r"(greenhouse|lever\.co|ashbyhq|comeet|myworkdayjobs|workday|smartrecruiters|recruitee|"
    r"workable|bamboohr|breezy\.hr|jazzhr|applytojob|icims|oraclecloud|successfactors|"
    r"phenom|eightfold|avature|careers-page\.com|rippling|hibob|teamtailor|willhire|"
    r"comeet\.com|jobs\.ashbyhq)", re.I)

# Brand/parent pairs a string comparison can never derive. Keep SMALL and evidence-based —
# every entry is a claim that one company's board legitimately carries the other's roles.
KNOWN_PARENT = {
    "aws": ("amazon.jobs", "amazon.com"),
    "amazon web services": ("amazon.jobs", "amazon.com"),
    "google israel": ("google.com", "abc.xyz"),
    "microsoft israel": ("microsoft.com",),
    "microsoft (xbox/gaming)": ("microsoft.com",),
    "volkswagen (cariad)": ("volkswagen-group.com", "cariad.technology"),
    "siemens digital industries software": ("sw.siemens.com", "siemens.com"),
    "siemens eda": ("sw.siemens.com", "siemens.com"),
    "applied materials israel": ("appliedmaterials.com",),
}

_STOP = {"the", "group", "israel", "technologies", "technology", "systems", "software",
         "solutions", "labs", "inc", "ltd", "corp", "company", "holdings", "international",
         "digital", "global", "security", "tech", "ai", "co"}


def registrable(host: str) -> str:
    """Second-level label, tolerating multi-part suffixes (foo.co.il -> foo)."""
    h = (host or "").lower().split(":")[0]
    if h.startswith("www."):
        h = h[4:]
    parts = [p for p in h.split(".") if p]
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov", "edu"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else h


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _acronym(name: str) -> str:
    """Texas Instruments -> ti, Central Bottling Company -> cbc. Stopwords are dropped only
    when something remains, so 'Israel Electric Corporation' still yields 'iec'."""
    words = [w for w in re.findall(r"[A-Za-z]+", name or "")]
    kept = [w for w in words if w.lower() not in _STOP] or words
    return "".join(w[0].lower() for w in kept)


def verdict(company: str, url: str) -> str:
    """'ats' | 'match' | 'mismatch' | 'unknown'.

    'mismatch' is a positive finding that the page belongs to someone else; 'unknown' means
    we could not tell. Callers must treat BOTH as "do not activate" — the difference only
    affects whether it is worth a human's or an LLM's time.
    """
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if not host:
        return "unknown"
    if ATS_HOST.search(host):
        return "ats"

    dom = registrable(host)
    cname, cn = (company or "").lower().strip(), _norm(company)
    if not dom or not cn:
        return "unknown"

    for parent in KNOWN_PARENT.get(cname, ()):
        if host.endswith(parent) or dom == registrable(parent):
            return "match"

    if dom == cn or dom in cn or cn in dom:
        return "match"
    # hyphen/space variants: "qs-labs" vs "Quantum Source" -> compare stripped forms
    if _norm(dom) and (_norm(dom) in cn or cn in _norm(dom)):
        return "match"
    # per-word: a >=4-char word of the name appearing in the domain is strong evidence
    words = [w for w in re.findall(r"[a-z0-9]{4,}", cname) if w not in _STOP]
    if any(w in dom for w in words):
        return "match"
    ac = _acronym(company)
    if len(ac) >= 2 and (dom == ac or dom.startswith(ac + "-") or dom.startswith(ac + "_")
                         or _norm(dom).startswith(ac) and len(_norm(dom)) <= len(ac) + 4):
        return "match"
    return "mismatch"


def is_foreign(company: str, url: str) -> bool:
    """True when the page provably belongs to a different company (or is a job board)."""
    return verdict(company, url) == "mismatch"
