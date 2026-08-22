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

# Industry words are NOT identity. Matching on one sent Tamar Robotics to arberobotics.com
# (Arbe Robotics) and Phoenix Financial to phoenixtma.com — both real companies, neither
# the right one. Only a DISTINCTIVE token may stand in for the company name.
_STOP = {"the", "group", "israel", "technologies", "technology", "systems", "software",
         "solutions", "labs", "inc", "ltd", "corp", "company", "holdings", "international",
         "digital", "global", "security", "tech", "ai", "co", "robotics", "financial",
         "finance", "medical", "analytics", "energy", "foods", "food", "pharma",
         "pharmaceutical", "pharmaceuticals", "health", "healthcare", "bio", "nano",
         "cyber", "data", "cloud", "capital", "ventures", "industries", "networks",
         "semiconductor", "semiconductors", "electronics", "intelligence", "imaging",
         "sciences", "science", "media", "mobile", "motors", "automotive", "insurance",
         "bank", "telecom", "communications", "materials", "storage", "vision", "power"}


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
    kept = [w for w in words if w.lower() not in _STOP]
    # "General Motors" -> dropping the industry word leaves "g", which matches nothing.
    # An acronym needs every word; only fall back to filtering when that is ambiguous.
    if len(kept) < 2 <= len(words):
        kept = words
    return "".join(w[0].lower() for w in (kept or words))


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

    if dom == cn:
        return "match"
    # Containment must be TIGHT. "rad" is a substring of "radlogics" and "nooga" of
    # "noogata", but rad.com is RAD Data Communications and nooga.net is not Noogata —
    # a much shorter domain that merely prefixes the name is not evidence. Allow only a
    # near-equal length difference (sproutt/sprout yes, radlogics/rad no).
    nd = _norm(dom)
    if nd and (nd in cn or cn in nd) and abs(len(nd) - len(cn)) <= 1:
        return "match"                    # sproutt/sprout yes; nooga/noogata no
    # per-word: a DISTINCTIVE (non-industry) word of the name appearing in the domain.
    # 4 chars, so "Teva Pharmaceutical" -> tevapharm.com resolves on "teva".
    words = [w for w in re.findall(r"[a-z0-9]{4,}", cname) if w not in _STOP]
    hit = next((w for w in words if w in dom), "")
    if hit:
        # If the domain carries a lot of EXTRA content beyond the matched token, this is
        # only suggestive: "phoenix" matches phoenixtma.com, which is a different company.
        # Say so rather than assert it, and let the caller confirm against page content.
        return "match" if len(dom) - len(hit) <= 2 else "weak"
    ac = _acronym(company)
    if len(ac) >= 2 and (dom == ac or dom.startswith(ac + "-") or dom.startswith(ac + "_")
                         or _norm(dom).startswith(ac) and len(_norm(dom)) <= len(ac) + 4):
        return "match"
    return "mismatch"


def is_foreign(company: str, url: str) -> bool:
    """True when the page provably belongs to a different company (or is a job board).

    `weak` is NOT foreign — it is unproven. Callers that ACTIVATE a row must demand a
    strong verdict (see page_mentions_company); callers that merely rank candidates can
    treat weak as a maybe.
    """
    return verdict(company, url) == "mismatch"


def page_mentions_company(company: str, html: str) -> bool:
    """Does the fetched page actually name this company?

    Far stronger than any domain heuristic: arberobotics.com does not say "Tamar Robotics"
    and rad.com does not say "RADLogics". Used to confirm `weak` domain verdicts before a
    row is repaired or activated.
    """
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = _norm(text)
    if not text:
        return False
    if _norm(company) in text:
        return True
    words = [w for w in re.findall(r"[a-z0-9]{4,}", (company or "").lower())
             if w not in _STOP]
    # every distinctive token must appear; one generic hit is not identity
    return bool(words) and all(w in text for w in words)
