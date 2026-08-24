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
    r"comeet\.com|jobs\.ashbyhq|jobs\.gem\.com|ultipro|trinethire|inflightcloud|"
    r"zohorecruit|myworkdaysite|paylocity|dayforcehcm|ripplingats|jobvite|taleo\.net)", re.I)

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
    # branded careers domains and post-acquisition boards, each verified by hand
    "ge healthcare israel": ("gehealthcare.com",),
    "procter & gamble": ("pgcareers.com",),
    "deutsche post dhl": ("dhl.com",),
    "johnson & johnson": ("jnj.com",),
    "general motors israel": ("gm.com",),
    "userway": ("levelaccess.com",),          # acquired by Level Access
    "abbott": ("jobs.abbott",),
    "abb": ("careers.abb", "abb.com"),
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


def _norm_split(host_label: str) -> list:
    """The registrable label split into its written parts: 'ide-tech' -> ['ide', 'tech']."""
    return [p for p in re.split(r"[^a-z0-9]+", (host_label or "").lower()) if p]


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


# path/host segments that are structural, never a tenant name
_NOT_A_SLUG = {"jobs", "job", "careers", "career", "embed", "job_board", "boards", "v1",
               "v0", "api", "en", "en-us", "en-il", "search", "postings", "list", "widget",
               "external", "apply", "company", "positions", "opportunities", "www", "com",
               "co", "io", "ai", "net", "org", "hq", "app", "my", "public", "posting-api",
               "job-board", "wday", "cxs", "index", "home", "openings", "all",
               "careers-api", "careers-home", "job-boards", "jobboard", "search-results",
               "job_board", "widgets", "accounts", "boards-api", "recruiting2", "hcmrestapi",
               "resources", "latest", "recruitingcemobile", "requisitions", "results"}


def _slug_candidates(parsed) -> list:
    """Tenant tokens an ATS URL can carry: host labels and path segments.

    greenhouse -> /<slug>;  comeet -> /jobs/<slug>/<uid>;  lever -> /<slug>;
    workday -> <tenant>.wdN.myworkdayjobs.com;  applytojob -> <slug>.applytojob.com
    """
    host_bits = [b for b in parsed.netloc.lower().split(".")
                 if b and b not in _NOT_A_SLUG and not re.fullmatch(r"wd\d+", b)
                 and not ATS_HOST.fullmatch(b or "")]
    path_bits = [seg.lower() for seg in parsed.path.split("/")
                 if seg and seg.lower() not in _NOT_A_SLUG]
    # drop opaque ids (Comeet uids like A6.009, numeric ids)
    # Opaque tenant ids carry NO identity: Comeet uses hex uids (60.002), Workable numeric
    # account ids. Dropping them is what makes an EMPTY candidate list mean "cannot tell".
    path_bits = [b for b in path_bits
                 if not re.fullmatch(r"[0-9a-f.\-]{2,8}", b, re.I) and not b.isdigit()
                 and not re.fullmatch(r"[\d.]+", b)]
    return host_bits + path_bits


def _slug_matches_company(company: str, parsed) -> bool:
    """Does any tenant token in the URL plausibly name this company?

    Permissive on purpose — an ATS slug is often abbreviated — but it must share real
    substance with the name, not merely be present.
    """
    cn = _norm(company)
    if not cn:
        return False
    words = [w for w in re.findall(r"[a-z0-9]{4,}", (company or "").lower())
             if w not in _STOP]
    ac = _acronym(company)
    for raw in _slug_candidates(parsed):
        t = _norm(raw)
        if not t:
            continue
        if t == cn or t in cn or cn in t:
            return True
        if any(w in t or t in w for w in words if len(t) >= 4):
            return True
        if len(ac) >= 3 and t == ac:
            return True
        # Abbreviated tenants that no acronym rule derives: "amat" for Applied Materials.
        # Subsequence, so the letters must still appear IN ORDER in the company name —
        # "asecurity" is not a subsequence of "myrrorsecurity" (no 'a'), nor "amat" of
        # "3dbattery" (no 'm'), so the real impostors stay caught.
        if len(t) >= 4 and _is_subsequence(t, cn):
            return True
    return False


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def verdict(company: str, url: str) -> str:
    """'ats' | 'match' | 'mismatch' | 'unknown'.

    'mismatch' is a positive finding that the page belongs to someone else; 'unknown' means
    we could not tell. Callers must treat BOTH as "do not activate" — the difference only
    affects whether it is worth a human's or an LLM's time.
    """
    parsed = urllib.parse.urlparse(url or "")
    host = parsed.netloc.lower()
    if not host:
        return "unknown"
    if ATS_HOST.search(host):
        # On an ATS the identity is the SLUG, not the domain — every company shares the
        # host. Returning a blanket "ats" skipped identity entirely and accepted
        # comeet.com/jobs/a_security/... for Myrror Security and amat.wd1.myworkdayjobs.com
        # (Applied Materials) for 3DBattery. Check the tenant token instead.
        # No checkable tenant token (Comeet's careers-api carries only an opaque uid like
        # 60.002) means we CANNOT TELL — and "cannot tell" must never read as "wrong
        # company". Asserting mismatch here flagged ~150 legitimate Comeet boards.
        if not _slug_candidates(parsed):
            return "ats"
        return "ats" if _slug_matches_company(company, parsed) else "mismatch"

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
    # The registry is full of "<Name> Israel" / "<Name> Technologies" rows whose board is
    # just <name>.com. Compare against the name with the generic words stripped, or
    # jobs.sap.com reads as foreign to "SAP Israel".
    core = _norm("".join(w for w in re.findall(r"[A-Za-z0-9]+", company or "")
                         if w.lower() not in _STOP))
    # EXACT only. `core.startswith(nd)` would re-admit rad.com for RADLogics and
    # nooga.net for Noogata — the same loose-prefix bug, one layer along.
    if core and nd and nd == core:
        return "match"
    # per-word: a DISTINCTIVE (non-industry) word of the name appearing in the domain.
    # 4 chars, so "Teva Pharmaceutical" -> tevapharm.com resolves on "teva".
    words = [w for w in re.findall(r"[a-z0-9]{4,}", cname) if w not in _STOP]
    hit = next((w for w in words if w in dom), "")
    if hit:
        # If the domain carries a lot of EXTRA content beyond the matched token, this is
        # only suggestive: "phoenix" matches phoenixtma.com, which is a different company.
        # Say so rather than assert it, and let the caller confirm against page content.
        #
        # The mirror case is just as wrong and was reading as a clean "match": the token is
        # the WHOLE domain but only part of the name. "Time To Know" -> time.com scored
        # match on `time` alone, and the repair pass moved the row to TIME magazine's own
        # careers page. If a distinctive word of the name is missing from the domain, this
        # is suggestive at best.
        missing = [w for w in words if w not in dom]
        return "match" if (len(dom) - len(hit) <= 2 and not missing) else "weak"
    # A HYPHENATED domain whose parts line up, token for token, with the company's words is
    # strong evidence — ide-tech.com IS IDE Technologies, c2a-sec.com IS C2A Security,
    # bren-energy.com IS Brenmiller Energy, and all three were scoring `mismatch`, which
    # blocks a legitimate recovery. Two independent tokens agreeing is what makes it safe:
    # the single-token version of this rule is exactly the rad.com/RADLogics and
    # nooga.net/Noogata false match, so a one-part domain is not eligible.
    dparts = [p for p in _norm_split(dom) if p]
    cwords = [w for w in re.findall(r"[a-z0-9]+", cname) if w not in ("the",)]
    if (len(dparts) >= 2 and len(dparts) == len(cwords)
            and all(len(d) >= 3 and w.startswith(d) for d, w in zip(dparts, cwords))):
        return "match"

    ac = _acronym(company)
    if len(ac) >= 2 and (dom == ac or dom.startswith(ac + "-") or dom.startswith(ac + "_")
                         or _norm(dom).startswith(ac) and len(_norm(dom)) <= len(ac) + 4):
        return "match"
    return "mismatch"


def is_foreign(company: str, url: str) -> bool:
    """True only when a NON-ATS domain provably belongs to someone else.

    ATS slug mismatches are dominated by legitimate rebrands and acquisitions — Momentis
    Surgical still posts under `memic`, OTORIO under `armissecurity`, Itamar Medical under
    `zoll` — so blocking on those costs real coverage. The FairFly/fireflyspace and
    COTI/citi.com shape lives on ordinary domains, which is what this blocks. For ATS
    slugs, confirm with page_mentions_company() instead of refusing outright.
    """
    host = urllib.parse.urlparse(url or "").netloc
    if ATS_HOST.search(host or ""):
        return False
    return verdict(company, url) == "mismatch"


_LEGAL_TOKEN = {"ltd", "ltd.", "inc", "inc.", "llc", "plc", "gmbh", "bv", "sa", "ag",
                "co", "corp", "corporation", "limited"}


def _page_tokens(html: str) -> list:
    return re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", " ", html or "").lower())


def page_mentions_company(company: str, html: str, strict: bool = False) -> bool:
    """Does the fetched page actually name this company?

    Far stronger than any domain heuristic: arberobotics.com does not say "Tamar Robotics"
    and rad.com does not say "RADLogics". Used to confirm `weak` domain verdicts before a
    row is repaired or activated.

    `strict` requires the name's words to appear CONSECUTIVELY, and is what a `weak`
    verdict needs. The loose test — every distinctive word appears SOMEWHERE on the page —
    accepted time.com/join-time for "Time To Know", because TIME's own careers page
    naturally contains both "time" and "know". Two ordinary English words scattered over a
    long page are not a company name.

    Matching is per-token, not substring: the old version normalized the whole page to one
    letter-run, where "…the time. To know more…" contains "timetoknow".
    """
    toks = _page_tokens(html)
    if not toks:
        return False
    name = [w for w in re.findall(r"[a-z0-9]+", (company or "").lower())
            if w not in _LEGAL_TOKEN]
    if not name:
        return False
    n = len(name)
    if any(toks[i:i + n] == name for i in range(len(toks) - n + 1)):
        return True
    if "".join(name) in toks:              # run-together spelling: "TimeToKnow"
        return True
    if strict:
        return False
    words = [w for w in name if len(w) >= 4 and w not in _STOP]
    # every distinctive token must appear; one generic hit is not identity
    return bool(words) and all(w in toks for w in words)


# GREEDY, and anchored at the id: LinkedIn puts the employer LAST, and a title with
# a requisition number in it ("Business Data Analyst - 241239 - at Experis Israel")
# stops a non-greedy match before the employer ever appears.
_JOB_SLUG = re.compile(r"/jobs/view/(.+)-\d{6,}(?:[/?#]|$)")


def url_names_other_company(company: str, url: str) -> bool:
    """For a LinkedIn posting URL, does the slug name a DIFFERENT employer?

    LinkedIn's job URL carries "<title>-at-<employer>-<id>", which is the only place a
    scraped LinkedIn card states who is actually hiring. A run once attributed 147 board
    rows to the wrong employer this way.

    Both sides are normalized to bare alphanumerics before comparing, which the first
    version did only to the company: "G-STAT" became "gstat" while the slug stayed
    "g stat", so five perfectly good rows read as mis-attributed — and one of them failed
    the invariant gate and withheld an entire day's digest, board and email.

    Returns False (i.e. "no evidence of a problem") whenever we cannot tell: a non-LinkedIn
    url, or a company name too short to carry identity ("EY").
    """
    m = _JOB_SLUG.search(url or "")
    if not m:
        return False
    slug = _norm(urllib.parse.unquote(m.group(1)))
    cn = _norm(company)
    # 2 characters cannot carry identity ("EY"); 3 can ("Wiz", "SAP").
    if not slug or len(cn) < 3:
        return False
    if cn in slug:
        return False
    words = [w for w in re.findall(r"[a-z0-9]{4,}", (company or "").lower())
             if w not in _STOP]
    return not any(w in slug for w in words)


# Says-so-in-the-path: a page that lists openings almost always announces it in the URL.
_LISTING_PATH = re.compile(
    r"career|job|position|opening|vacanc|hiring|recruit|employment|talent|"
    r"opportunit|join-?us|work(ing)?-?(at|with|for)|drushim|apply|"
    r"%d7%9e%d7%a9%d7%a8|משרות", re.I)
# ...or it is hosted by something whose entire business is listing openings.
_LISTING_HOST = re.compile(
    r"teamtailor\.com|candidateexperience|willhire\.|myworkdayjobs|greenhouse\.io|"
    r"lever\.co|ashbyhq\.com|comeet\.co|smartrecruiters\.com|workable\.com|"
    r"recruitee\.com|breezy\.hr|bamboohr\.com|applytojob\.com|jazz\.co|"
    r"eightfold\.ai|icims\.com|successfactors|taleo\.net|oraclecloud\.com", re.I)


def looks_like_a_job_listing_page(url: str) -> bool:
    """Does this URL even claim to be a listings page?

    An activation gate, not a verdict about a company. `SCRAPE_ASSUME_IL=1` makes the hunt
    treat every card on a page as an Israel role, so a page of navigation links scores as
    well as a real board: `iai.co.il/solution/research-academy-space/` "verified 6 IL" whose
    titles were "Design and Integration", "Domain Operations" and "Press Releases". Of 417
    active scrape rows only ten fail this test, and six of those ten are a blog post, a
    product page, a research page and a country landing page.
    """
    p = urllib.parse.urlparse(url or "")
    if not p.netloc:
        return False
    return bool(_LISTING_HOST.search(p.netloc) or _LISTING_PATH.search(p.netloc)
                or _LISTING_PATH.search(p.path + "?" + (p.query or "")))
