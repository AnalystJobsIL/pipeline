"""Build the email digest (subject + HTML + plaintext) from accepted new jobs.

The digest is intentionally auditable: besides the job listings it carries a run-summary
(how many scanned / Israel-matched / accepted / new, the keyword-vs-LLM path breakdown,
and any companies whose fetch failed) so the reader can trust what they're seeing.
"""
from __future__ import annotations

import datetime as _dt
import html
import re as _re
import re

from . import roleprofile


def _safe_url(u):
    """Only http/https survive — blocks javascript:/data: from scraped/discovered links."""
    u = str(u or "").strip()
    return u if u[:7].lower() == "http://" or u[:8].lower() == "https://" else ""


_MD_META = re.compile(r"[\`*_{}\[\]()#+\-!@~|>]")


def _md_esc(s):
    """Escape Markdown metacharacters so scraped company/title text can't inject links,
    @mentions, or formatting into the emailed issue."""
    return _MD_META.sub(lambda m: "\\" + m.group(0), str(s or ""))


def _fmt_date(d):
    return d or "—"


def _short(text, n=240):
    """Trim text to n chars at a word boundary."""
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut + "…"


# --------------------------------------------------------------------------- #
# snippet / metadata helpers (address the digest UX review)
# --------------------------------------------------------------------------- #
_ZW = re.compile(r"[﻿​‎‏­]")           # BOM / zero-width / soft hyphen
_LABEL_PREFIX = re.compile(r"^\s*(experience level\s*:[^.]*\.\s*)?(description\s*:\s*)?", re.I)
_EXP_LEVEL = re.compile(r"experience level\s*:\s*([^.]+)", re.I)
_YEARS = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?\b", re.I)
# markers that indicate the role-specific part of a JD begins here
_ROLE_MARKER = re.compile(
    r"(responsibilities|requirements|what you.?ll (?:do|be doing|bring)|qualifications|"
    r"about the role|about the position|in this role|role overview|your role|"
    r"we.?re looking for|we are looking for|as an?\s|you will|what you bring)", re.I)
# "<Company> is a/an/the <predicate>." -> company one-liner
_COMPANY_IS = re.compile(r"\b(?:is|are)\s+(?:a|an|the)\s+(.{5,90}?)[\.\n;]", re.I)
_HEBREW = re.compile(r"[֐-׿]")
# a failed `claude -p` (or similar CLI error) must never render as an About blurb —
# and neither must a first-person "I'm not sure what this company does" meta answer:
# a job seeker should read facts about the company, never the model talking about itself.
_ABOUT_JUNK = re.compile(r"not logged in|please run|/login|usage:|command not found|invalid api|"
                         r"api key|traceback|rate limit|quota|unauthor|permission denied|"
                         r"\bI['’]?m\b|\bI\s+(?:don['’]?t|do not|can['’]?t|cannot|"
                         r"couldn['’]?t|am|have|would|need|recommend)\b|\bI['’]d\b|"
                         r"unable to (?:confirm|verify)|no (?:job post )?context was provided|"
                         r"web[- ]search access", re.I)
# a title with a breadcrumb separator or a place/CTA fused onto it is a scraped card blob
_MANGLED_TITLE = re.compile(r"[⋅•·|►▸]|,\s*israel\b|tel[\s-]?aviv,|"
                            r"(?<=[a-z])(?:Tel Aviv|Israel|Apply|Remote|Full[\s-]?time)|"
                            r"israel(?=[A-Za-z])", re.I)


def _clean_desc(desc):
    d = " ".join(_ZW.sub("", str(desc or "")).split())
    return re.sub(r"\s*\bShow (?:more|less)\b", "", d)   # LinkedIn scrape artifact


def _company_blurb(desc, company=""):
    """Extract a short 'what the company does' phrase from a JD, or ''.

    Prefer a phrase anchored on the company NAME ("<Company> is/builds/provides …") — that
    can't accidentally grab role text ("… is looking for a Data Analyst"), and it catches
    the article-less forms the generic pattern misses ("Blockaid is redefining trust …")."""
    d = _LABEL_PREFIX.sub("", _clean_desc(desc)).lstrip(" •")
    if company:
        anchored = _re.search(
            _re.escape(company)
            + r"[^.•]{0,40}?\b(?:is|are|builds?|provides?|offers?|powers?|helps?|enables?|"
            r"delivers?|develops?|creates?|makes?)\s+"
            r"(?!seeking|looking|hiring|searching|recruiting|excited|thrilled|proud|now\b)"
            r"(?:(?:a|an|the)\s+)?(.{6,110}?)[.•\n;]",
            d[:400], _re.I)
        if anchored:
            words = anchored.group(1).strip().rstrip(".").split()
            stray = {"of", "to", "for", "and", "or", "with", "that", "which",
                     "by", "from", "as", "but", "nor"}
            if len(words) >= 3 and words[0].lower() not in stray:
                return " ".join(words[:16])
    m = _COMPANY_IS.search(d[:220])
    if not m:
        return ""
    words = m.group(1).strip().rstrip(".").split()
    return " ".join(words[:12])


# hard requirement headers — the practical "what you need" section. Tried first, earliest
# wins. NOTE: "we're looking for" is deliberately NOT here — it usually opens a company
# intro ("We are looking for a <role> to join…"), not a qualifications list.
_REQ_HARD = _re.compile(r"(requirements?|qualifications?|what (?:you.?ll|you will) (?:bring|need)|"
                        r"what are we looking for|what we.?re looking for|what we expect|"
                        r"(?:perfect|ideal) job for someone who (?:has|is)|"
                        r"to thrive in this role,? you.?ll need|what you need to succeed|"
                        r"דרישות(?: התפקיד)?|מה אנחנו מחפשים|כישורים נדרשים|"
                        r"what (?:will make|makes) you successful|who you are|about you|"
                        r"what we.?re looking for in you|must[- ]have|your (?:profile|experience|"
                        r"background)|minimum qualifications|desired (?:skills|qualifications)|"
                        r"skills (?:&|and) (?:experience|qualifications)|you(?:'?ll)? (?:have|bring))"
                        r"\s*:?", _re.I)
_REQ_SOFT = _re.compile(r"(ideal candidate|what you.?ll do|what you.?ll own)\s*:?", _re.I)
# a new JD section starting = stop the requirements segment there
# NOTE: "advantage"/"bonus"/"nice to have" are deliberately NOT section terminators —
# they appear INLINE in bullets ("Vertica knowledge – strong advantage") and as the
# nice-to-have SUB-list we want to keep (badged as plus via _PLUS_SECTION below).
_SECTION_END = _re.compile(r"(?:•\s*)?\b(responsibilit|benefits?|perks|about (?:us|the company)|"
                           r"why join|what we offer|"
                           r"we offer|our (?:stack|tech)|equal opportunit|why you.?ll love|"
                           r"what makes\b|please (?:ensure|note)|founded in \d{4}|"
                           r"היקף משרה|אנחנו על המפה|קו\"ח|שעות עבודה)\b\s*:?", _re.I)
# a nice-to-have SUB-header inside the requirements section: everything after it is
# still shown, but badged "plus" — never dropped, never presented as required
_PLUS_SECTION = _re.compile(r"(?:•\s*)?\b(?:advantages?|nice[- ]to[- ]haves?|"
                            r"bonus(?: points)?(?: if you have)?|it would be (?:great|a plus)|"
                            r"preferred qualifications|יתרון(?: משמעותי)? אם)\b\s*:", _re.I)
# leaked section-header words to strip from the front of a bullet
_LEAD_JUNK = _re.compile(r"^(responsibilities|requirements?|qualifications?|the role|"
                         r"about the role|role description|what you.?ll (?:need|bring|do|own))"
                         r"\s*:?\s*", _re.I)
# a bullet that is ONLY a category header (e.g. "Experience & Technical Skills") — drop it
_HEADER_ONLY = _re.compile(r"^(experience|technical skills?|education|skills?|qualifications?|"
                           r"requirements?|nice to have|advantages?|bonus(?: points)?|"
                           r"about you|background|responsibilities|"
                           r"what we(?:'re| are)? ?(?:expect|need|want|require|value|look\w*)|"
                           r"what you.?ll (?:need|do|bring|own|be doing)|technical|professional)"
                           r"(?:\s*(?:&|and|/|,)\s*(?:experience|technical|skills?|education|"
                           r"qualifications?|requirements?|background))*\s*:?$", _re.I)
# fallback splitter (no • markers survived): sentences / dashed clauses
_SENT_SPLIT = _re.compile(r"(?<=[a-z0-9%)א-ת])\.\s+(?=[A-Z0-9א-ת])|\s[–—]\s(?=[A-Z0-9])")
# scraped requirement lists often lose their bullets entirely ("...related field 3+ years
# of experience Strong SQL skills"); split a long run-on before words that typically open
# a fresh requirement (English capitalized openers / Hebrew openers)
_RUNON_SPLIT = _re.compile(
    r"(?<=[a-zא-ת)%\.]) (?=(?:\d+\+? years?|Strong|Proven|Excellent|Experience|Experienced|"
    r"Knowledge|Familiarity|Ability|Proficien\w*|Fluent|High(?: proficiency| level)|Advanced|"
    r"Deep|Solid|Hands[- ]on|Degree|B\.?Sc|M\.?Sc|Bachelor|Master|Team player|Self[- ]|"
    r"Willingness|Availability|English|Hebrew|Excellent|Very|Good|Great|"
    r"At least|Minimum(?: of)?|Fluency|Fluent|"
    r"ניסיון|תואר|ידע|יכולת|שליטה|אנגלית|היכרות|נכונות)\b)")
# a requirement's own must/nice-to-have marker, at the end of the bullet
_REQ_MUST = _re.compile(r"\s*[-–—(:]*\s*(?:a\s+)?(?:must(?:\s+have)?|mandatory|requir\w*|חובה)[.!)]?\s*$", _re.I)
_REQ_PLUS = _re.compile(r"\s*[-–—(:]*\s*(?:an?\s+)?(?:(?:big|strong|significant|major|huge|"
                        r"added|great|definite)\s+)?(?:advantage|plus|nice to have|preferred|"
                        r"bonus|יתרון(?: משמעותי)?)[.!)]?\s*$", _re.I)


# scraped lists also glue requirements with " - Hands on…" separators; split before a
# capitalized opener but never right before a bare must/advantage marker
_DASH_SPLIT = _re.compile(r"\s+-\s+(?=[A-Z])(?!(?:Must|Mandatory|Requir|Advantage|Plus|Big|Nice|An?\b))")
# never render as a requirement: recruiter hashtags, links, résumé notes, culture blurbs
_BULLET_JUNK = _re.compile(r"^#|https?://|www\.|#li-|\brésumé\b|resume(?:/cv)? you attach|"
                           r"why you.?ll love|equal opportunit|privacy policy|"
                           r"apply now|click here|meet 100% of|not about checklists|"
                           r"encourage you to apply|describes you perfectly", _re.I)


_LEAD_MUST = _re.compile(r"^\s*(?:must(?:[- ]haves?)?|mandatory|חובה)(?:\s*[-–—:]+\s*|\s+(?=[A-Zא-ת]))", _re.I)
_LEAD_PLUS = _re.compile(r"^\s*(?:advantage|nice to have|bonus|יתרון)\s*[-–—:]+\s*", _re.I)


def _req_badge(p):
    """Split a bullet's leading or trailing must/advantage marker off into a badge tag."""
    if _LEAD_PLUS.search(p):
        return _LEAD_PLUS.sub("", p), "plus"
    if _LEAD_MUST.search(p):
        return _LEAD_MUST.sub("", p), "must"
    if _REQ_PLUS.search(p):
        return _REQ_PLUS.sub("", p).rstrip(" -–—(:"), "plus"
    if _REQ_MUST.search(p):
        return _REQ_MUST.sub("", p).rstrip(" -–—(:"), "must"
    return p, None


def _clean_bullet(p, cap=210):
    """Tidy one requirement fragment: strip markers/leaked headers, fix stray spacing from
    justified source text ("Ph . D", "4 + years", "SQL ,"), cap length uniformly."""
    p = " ".join(str(p or "").split()).strip(" \t•·–—-:;.")
    p = _LEAD_JUNK.sub("", p).strip(" :–—-")
    p = re.sub(r"\s+([,.;:%)])", r"\1", p)          # no space before punctuation
    p = re.sub(r"(\d)\s+\+", r"\1+", p)             # "4 +" -> "4+"
    p = re.sub(r"\(\s+", "(", p)                    # "( x" -> "(x"
    if len(p) > cap:
        p = p[:cap].rsplit(" ", 1)[0].rstrip(" ,;:–—-") + "…"
    if p.count("(") > p.count(")"):                 # unbalanced truncated parenthetical
        li = p.rfind("(")
        if len(p[li + 1:].strip()) < 2:             # dangling empty "(" -> drop it
            p = p[:li].rstrip(" -–—,")
        else:                                       # real content -> just close it
            p = p.rstrip(" -–—,") + ")"
    # drop a dangling connector left by mid-sentence truncation ("... experience with", "is an")
    p = re.sub(r"[\s,]+(?:is an?|are|with|and|or|to|of|the|for|in|on|an?|is)$", "", p, flags=re.I)
    # a header match like "The ideal candidate" leaves a subject-less "is highly skilled…"
    p = re.sub(r"^(?:is|are|has|have|will be)\s+", "", p, flags=re.I)
    return p.rstrip(" -–—,;:")


_REQ_SIGNAL = _re.compile(
    r"\b(experience|years?|degree|proficien|knowledge|ability|familiar|proven|strong|expert|"
    r"hands[- ]on|sql|python|excel|tableau|looker|power ?bi|bachelor|master|fluent|"
    r"understanding|background|skilled|passion|track record|mindset)\b", _re.I)


def _looks_like_header(c):
    """A short, all-capitalized fragment with no requirement signal is a decorative section
    header a company used to title its list (e.g. 'Your Chain of Strengths') — not a bullet."""
    words = c.split()
    if len(words) > 5 or _re.search(r"\d", c) or _REQ_SIGNAL.search(c):
        return False
    caps = sum(1 for w in words if w[:1].isupper())
    return len(words) >= 2 and caps >= len(words) - 1


# a fragment opening with an imperative verb is a RESPONSIBILITY, not a requirement —
# used to reject header matches that were really a mid-sentence "…ad-hoc requirements"
_RESP_VERB = _re.compile(r"^(develop|create|perform|build|design|lead|manage|work|partner|"
                         r"collaborate|own|drive|support|monitor|analy[sz]e|define|deliver|"
                         r"maintain|conduct|translate|identify|provide|present|research|"
                         r"optimi[sz]e|execute|prepare|implement|serve|gather|track|run)\b", _re.I)


def _req_header_match(d2):
    """First _REQ_HARD match that anchors a real requirements SECTION: the text right
    after it must not open with a responsibility verb (which means the 'header' was a
    mid-sentence word like '…ad-hoc requirements Develop dashboards…')."""
    cands = list(_REQ_HARD.finditer(d2))[:5]
    for m in cands:
        head = d2[m.end():m.end() + 160].strip(" ?:-–—•")
        first = _clean_bullet(head.split("•")[0])
        if first and not _RESP_VERB.match(first):
            return m
    return (cands[0] if cands else None) or _REQ_SOFT.search(d2)


_PLUS_HEADER_ONLY = _re.compile(r"^(?:advantages?|nice[- ]to[- ]haves?|bonus(?: points)?"
                                r"(?: if you have)?|preferred qualifications|יתרונות)\s*:?$", _re.I)


def _bullets(seg, default_badge):
    """Split one section of requirement text into clean (text, badge) fragments.
    A bare 'Advantages'/'Nice to have' sub-header flips the default badge to 'plus'
    for everything after it."""
    raw = seg.split("•") if "•" in seg else _SENT_SPLIT.split(seg)
    # secondary pass: a fragment that is still a wall of text gets the run-on splitters
    raw = [piece for p in raw
           for piece in (_RUNON_SPLIT.split(p) if len(p) > 80 else [p])]
    raw = [piece for p in raw
           for piece in (_DASH_SPLIT.split(p) if len(p) > 80 else [p])]
    parts = []
    for p in raw:
        # peel the must/advantage marker BEFORE the length cap so it can't be half-cut
        txt, badge = _req_badge(" ".join(str(p or "").split()))
        c = _clean_bullet(txt)
        if _PLUS_HEADER_ONLY.match(c):
            default_badge = "plus"
            continue
        if not (8 <= len(c) <= 220) or _HEADER_ONLY.match(c) or _looks_like_header(c):
            continue
        if _BULLET_JUNK.search(c):
            continue
        # a long fragment with no requirement vocabulary is company/culture boilerplate
        if len(c) > 120 and not _REQ_SIGNAL.search(c):
            continue
        parts.append((c, badge or default_badge))
    return parts


def _requirements_snippet(desc, n=2600):
    """The practical part of a JD (Requirements / What you'll bring) as clean
    (text, badge) fragments, badge in {'must','plus',None}. Deterministic — header
    regex + <li>-marker splitting, no LLM. Returns [] when absent."""
    d2 = _LABEL_PREFIX.sub("", _clean_desc(desc))
    m = _req_header_match(d2)
    if not m:
        return []
    seg = d2[m.end():].strip(" ?:-–—•")
    e = _SECTION_END.search(seg)
    if e and e.start() > 20:
        seg = seg[:e.start()]
    seg = seg[:n]
    # a "Advantages:"/"Bonus points:" sub-header splits the section: everything after
    # it is real content shown with a plus badge, never dropped or shown as required
    ps = _PLUS_SECTION.search(seg)
    if ps and ps.start() > 20:
        parts = _bullets(seg[:ps.start()], None) + _bullets(seg[ps.end():], "plus")
    else:
        parts = _bullets(seg, None)
    out = []
    for c, b in parts:
        if c.lower() not in (x.lower() for x, _ in out):
            out.append((c, b))
    return out[:12]


_RESP_HEAD = _re.compile(r"(responsibilit(?:ies|y)|what (?:you|you'?ll) (?:do|be doing|own|work on)|"
                         r"your (?:role|impact|day[- ]to[- ]day)|in this role,? you|role overview|"
                         r"day[- ]to[- ]day|you will be|as part of (?:the|this) role|"
                         r"תחומי אחריות|מה תעשו|היומיום של)\s*:?", _re.I)
# responsibilities lists glue the same way requirement lists do — split before an
# imperative opener when the bullets got lost in scraping
_RUNON_RESP = _re.compile(
    r"(?<=[a-zא-ת)%.]) (?=(?:Develop|Create|Perform|Build|Design|Lead|Manage|Work|Partner|"
    r"Collaborate|Own|Drive|Support|Monitor|Analy[sz]e|Define|Deliver|Maintain|Conduct|"
    r"Translate|Identify|Provide|Present|Research|Optimi[sz]e|Execute|Prepare|Implement|"
    r"Serve|Gather|Track|Run|Ensure|ניתוח|בניית|עבודה|אחריות)\b)")


def _responsibilities_snippet(desc, n=2200):
    """The day-to-day part of a JD (Responsibilities / What you'll do) as clean bullet
    fragments. Deterministic, mirrors _requirements_snippet. Returns [] when absent."""
    d2 = _LABEL_PREFIX.sub("", _clean_desc(desc))
    m = _RESP_HEAD.search(d2)
    if not m:
        return []
    seg = d2[m.end():].strip(" ?:-–—•")
    # the section ends where requirements (or any other section) begin
    ends = [x.start() for x in (_REQ_HARD.search(seg), _SECTION_END.search(seg))
            if x and x.start() > 20]
    if ends:
        seg = seg[:min(ends)]
    seg = seg[:n]
    raw = seg.split("•") if "•" in seg else _SENT_SPLIT.split(seg)
    raw = [pc for p in raw for pc in (_RUNON_RESP.split(p) if len(p) > 90 else [p])]
    parts = []
    for p in raw:
        c = _clean_bullet(" ".join(str(p or "").split()))
        if not (8 <= len(c) <= 220) or _HEADER_ONLY.match(c) or _looks_like_header(c):
            continue
        if _BULLET_JUNK.search(c):
            continue
        if c.lower() not in (x.lower() for x in parts):
            parts.append(c)
    return parts[:8]


def _role_snippet(desc, n=230):
    """Prefer the role-specific text: strip field labels + leading company boilerplate,
    jump to a responsibilities/requirements marker when present."""
    d = _LABEL_PREFIX.sub("", _clean_desc(desc))
    if not d:
        return ""
    m = _ROLE_MARKER.search(d)
    if m and m.start() < 700:
        d = d[m.start():]
    else:
        # drop a leading "<Company> is a … ." sentence if that's all we have
        cm = _COMPANY_IS.search(d[:220])
        if cm and cm.end() < 220:
            d = d[cm.end():].strip(" .,-")
    return _short(d, n)


def _seniority_chip(desc):
    m = _EXP_LEVEL.search(desc or "")
    if m:
        return m.group(1).strip().rstrip(".")
    y = _YEARS.search(desc or "")
    return f"{y.group(1)}+ yrs" if y else ""


_LOC_DROP = {"il", "israel", "isr", "tel aviv district", "central district", "center district",
             "hamerkaz", "haifa district", "southern district", "northern district",
             "jerusalem district", "hadarom", "hatzafon", "center"}
# canonicalize the many spellings of the same city to one label
_LOC_CANON = {"tel aviv-yafo": "Tel Aviv", "tel aviv-jaffa": "Tel Aviv", "tel aviv jaffa": "Tel Aviv",
              "telaviv": "Tel Aviv", "tel-aviv": "Tel Aviv", "tlv": "Tel Aviv",
              "ramat-gan": "Ramat Gan", "petah-tikva": "Petah Tikva", "petach tikva": "Petah Tikva",
              "rishon lezion": "Rishon LeZion", "rishon le zion": "Rishon LeZion",
              "kiryat bialik": "Kiryat Bialik", "beer sheva": "Be'er Sheva", "beersheba": "Be'er Sheva",
              "יפו": "Tel Aviv", "תל אביב": "Tel Aviv", "תל אביב-יפו": "Tel Aviv",
              "באר שבע": "Be'er Sheva", "רעננה": "Ra'anana", "הרצליה": "Herzliya",
              "חיפה": "Haifa", "ירושלים": "Jerusalem", "פתח תקווה": "Petah Tikva",
              "רמת גן": "Ramat Gan", "חולון": "Holon", "נתניה": "Netanya",
              "יקנעם עילית": "Yokneam", "יקנעם": "Yokneam", "טירת כרמל": "Tirat Carmel",
              "מחוז הצפון": "Northern Israel", "מחוז המרכז": "Central Israel",
              "מחוז תל אביב": "Tel Aviv", "מחוז חיפה": "Haifa area", "ישראל": "Israel (unspecified)"}


def _norm_location(loc):
    # split on commas AND " - " / " / " separators (e.g. "Israel - Petah Tikva")
    raw = re.split(r"\s[-/]\s|,", str(loc or ""))
    parts = [p.strip() for p in raw if p.strip()]
    kept = [p for p in parts if p.lower() not in _LOC_DROP]
    out = []
    for p in kept:                      # drop consecutive duplicates (e.g. "Tel Aviv, Tel Aviv")
        if not out or out[-1].lower() != p.lower():
            out.append(p)
    city = out[0] if out else (parts[0] if parts else "")
    if not city or city.lower() in ("israel", "isr", "il"):
        return "Israel (unspecified)"
    return _LOC_CANON.get(city.lower(), city)


_SEN_INFER = re.compile(r"\b(senior|sr\.?|principal|staff|head of|lead|director|vp|chief|expert|manager)\b", re.I)


_SEN_LEAD = re.compile(r"\b(team ?lead|tech ?lead|group lead|manager|head of|principal|staff|"
                       r"director|vp|vice president|chief)\b", re.I)


def _sen_canon(chip, title):
    """Collapse any seniority hint to ONE tidy label so the column scans in a glance:
    Junior / Mid / Senior / Lead+ (— when unknown). The raw parsed value (e.g.
    'Advanced (5-8 Years)') is preserved by the caller as a hover tooltip."""
    c = (chip or "").lower()
    t = (title or "").lower()
    if "junior" in c or "entry" in c or "intern" in c:
        return "Junior"
    if _SEN_LEAD.search(c) or _SEN_LEAD.search(t):
        return "Lead+"
    if any(w in c for w in ("senior", "advanced", "expert", "mid-senior")) or _SEN_INFER.search(t):
        return "Senior"
    m = re.search(r"(\d+)", c)
    if m:
        y = int(m.group(1))
        return "Lead+" if y >= 8 else "Senior" if y >= 5 else "Mid"
    if "mid" in c:
        return "Mid"
    return "—"


def _sen_rank(chip):
    """Numeric rank for correct seniority sorting (junior→lead; unknown last)."""
    c = (chip or "").lower()
    if c in ("", "—"):
        return 99
    if "junior" in c or "entry" in c:
        return 1
    if any(w in c for w in ("lead", "manager", "head", "principal", "staff", "director", "vp", "chief")):
        return 6
    if "mid-senior" in c:
        return 4
    if "senior" in c:
        return 5
    if "mid" in c:
        return 3
    m = re.search(r"(\d+)", c)
    if m:
        y = int(m.group(1))
        return 6 if y >= 5 else 5 if y >= 3 else 3
    return 6 if ("advanced" in c or "expert" in c) else 4


_EMP = [("maternity", "Maternity cover"), ("temporary", "Temp"), ("contract", "Contract"),
        ("internship", "Intern"), ("part-time", "Part-time")]


def _employment_badge(title):
    t = (title or "").lower()
    for kw, label in _EMP:
        if kw in t:
            return label
    return ""


_REL_DAYS = re.compile(r"(\d+)\+?\s*day", re.I)
_REL_MONTHS = re.compile(r"(\d+)\+?\s*month", re.I)


def _rel_date(posted_date, run_date):
    """'today' / '3d ago' style label. Recovers relative strings ('Posted 4 Days Ago')
    that slipped through un-normalized, and NEVER leaks raw junk — unparseable → '—'."""
    s = str(posted_date or "")
    try:
        p = _dt.date.fromisoformat(s[:10])
        r = _dt.date.fromisoformat(str(run_date)[:10])
        days = (r - p).days
        return "today" if days <= 0 else "1d ago" if days == 1 else f"{days}d ago"
    except (ValueError, TypeError):
        pass
    sl = s.lower()
    if "today" in sl or "just posted" in sl or "just now" in sl:
        return "today"
    if "yesterday" in sl:
        return "1d ago"
    m = _REL_DAYS.search(sl)
    if m:
        return f"{int(m.group(1))}d ago"
    m = _REL_MONTHS.search(sl)
    if m:
        return f"{int(m.group(1)) * 30}d ago"
    m = re.match(r"posted\s+(\d+)", sl)          # 'Posted 4 [Days Ago]' truncations
    if m:
        return f"{int(m.group(1))}d ago"
    return "—"


def _age_note(posted_date, run_date):
    """Return a staleness flag for ISO dates older than ~45 days, else ''."""
    try:
        d = _dt.date.fromisoformat(str(posted_date)[:10])
        r = _dt.date.fromisoformat(str(run_date)[:10])
    except ValueError:
        return ""
    days = (r - d).days
    if days >= 60:
        return f" · ⚠️ posted ~{days // 30}mo ago"
    if days >= 45:
        return f" · ⚠️ posted {days}d ago"
    return ""


def build_markdown(jobs, run_date, stats, company_info=None, board_url="",
                   firmographics=None):
    """Return (title, body_markdown) — a COMPACT, email-friendly digest.

    Grouped by company (freshest first). Each company shows its one-line "what it does /
    how it earns money", then its roles as a bullet list where the title is a direct apply
    link plus location/date/seniority. No `<details>` collapsibles in the listing: email
    clients (Gmail) render those expanded anyway, so a compact list reads better everywhere;
    the full role description is one tap away on the apply link.

    `company_info` maps company name -> a plain-text "what it does + how it earns money".
    """
    company_info = company_info or {}
    firmographics = firmographics or {}
    n = len(jobs)
    title = f"🎯 {n} new senior analytics role{'' if n == 1 else 's'} — {run_date}"

    by_company = {}
    for j in jobs:
        by_company.setdefault(j["company"], []).append(j)
    for c in by_company:
        by_company[c].sort(key=lambda x: str(x.get("posted_date") or ""), reverse=True)
    # companies ordered by their freshest posting
    companies = sorted(by_company, key=lambda c: max(str(x.get("posted_date") or "")
                                                     for x in by_company[c]), reverse=True)

    lines = [f"# {title}", "",
             "Israeli high-tech scan — experienced (≈3+ yrs) data-analysis / BI / analytics "
             "roles from the **last 48h**, freshest first. Each role title links to apply.", ""]
    if board_url:
        lines += [f"🔎 **[Open the full board →]({board_url})** — every role still open, "
                  "searchable & sortable.", ""]
    if n == 0:
        lines.append("_No new matching openings today._")

    for company in companies:
        jobs_c = by_company[company]
        about = company_info.get(company) or _company_blurb(jobs_c[0].get("description"))
        if about and _ABOUT_JUNK.search(about):   # never email a CLI error or meta answer
            about = _company_blurb(jobs_c[0].get("description")) or ""
        lines.append(f"### {_md_esc(company)}")
        if about:
            lines.append(f"_{about}_")
        facts = _firmo_facts(firmographics.get(company))
        if facts:
            lines.append("`" + "` · `".join(_md_esc(f) for f in facts) + "`")
        lines.append("")
        for j in jobs_c:
            url = j.get("url") or ""
            title_txt = j.get("title") or "(untitled)"
            if _HEBREW.search(title_txt):
                title_txt += " (Hebrew)"
            su = _safe_url(url)
            head = (f"**{_md_esc(title_txt)}** — {su}" if su
                    else f"**{_md_esc(title_txt)}**")
            chip = _seniority_chip(j.get("description"))
            meta = [f"📍 {_norm_location(j.get('location'))}",
                    f"🗓 {j.get('posted_date') or '—'}" + _age_note(j.get("posted_date"), run_date)]
            if chip:
                meta.append(f"🎓 {chip}")
            lines.append(f"- {head} · {' · '.join(meta)}")
        lines.append("")

    # collapsed audit so the email stays clean but is still verifiable
    s = stats
    paths = ", ".join(f"{k}={v}" for k, v in sorted(s.get("paths", {}).items()))
    lines += [
        "---",
        "<details><summary>Run audit</summary>", "",
        f"- Companies scanned: **{s.get('companies_scanned',0)}** (failed: {s.get('companies_failed',0)})",
        f"- Jobs fetched: {s.get('jobs_fetched',0)} · Israel-matched: {s.get('israel_matched',0)}",
        f"- Accepted: {s.get('accepted',0)} · after merge: {s.get('after_merge',0)} · **new: {s.get('new',0)}**",
        f"- Decision paths: {paths}",
        f"- LLM calls this run: {s.get('llm_calls',0)}",
    ]
    if s.get("failed_companies"):
        lines.append(f"- Failed companies: {', '.join(s['failed_companies'])}")
    lines += ["", "</details>"]
    return title, "\n".join(lines)


def _newcut(run_date):
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=1)).isoformat()
    except Exception:
        return "9999"


_STAGE_LABEL = {"early-private": "early-stage private", "growth-private": "growth-stage private",
                "public": "public", "acquired-by-bigtech": "acquired", "subsidiary": "subsidiary",
                "government": "government", "nonprofit": "non-profit"}


def _firmo_facts(rec):
    """"What is this company, actually" — the researched facts, as short display chips.

    The firmographics layer researches sector/stage/employees/founded/IL-centre for every
    company on the board and then nothing rendered it: the answer to "should I want to work
    here" lived only in a sqlite table. Order is the order a reader asks it in.
    """
    if not isinstance(rec, dict):
        return []
    out = []
    if rec.get("sector"):
        out.append(str(rec["sector"]))
    stage = _STAGE_LABEL.get(str(rec.get("stage") or ""), str(rec.get("stage") or ""))
    if stage:
        out.append(stage)
    n = rec.get("employees_global")
    if isinstance(n, int) and n > 0:
        out.append(f"~{n:,} employees".replace(",", ","))
    if rec.get("founded"):
        out.append(f"founded {rec['founded']}")
    if rec.get("il_center"):
        out.append(str(rec["il_center"]))
    return [c for c in (x.strip() for x in out) if c][:5]


def build_board_html(jobs, run_date, stats, company_info=None, analytics_html="", contact_url="",
                     heading="senior analytics roles in Israel", firmographics=None):
    """Interactive board (GitHub Pages): an accessible, expandable, sortable TABLE.

    Columns: Company / Role / Location / Posted / Seniority. Rows expand (click or Enter/Space)
    to the company profile + role details + apply link; headers sort (click or Enter/Space,
    with real numeric seniority ranking); the search box filters live and shows a result count.
    Sticky header via a bounded-height scroll region. `analytics_html` injects a tracker;
    `contact_url` adds a Contact link.
    """
    company_info = company_info or {}
    firmographics = firmographics or {}

    def _display_company(name):
        """Short display name for the table cell: keep the brand, drop taglines and
        legal suffixes ('Oak - Identity Security OS' -> 'Oak'). Full name stays in the
        tooltip, the expanded card, and the search blob."""
        n = str(name or "")
        n = re.split(r"\s+[-–—|]\s+", n)[0]
        n = re.sub(r"\s+(?:ltd\.?|inc\.?|בע\"מ)$", "", n, flags=re.I)
        n = re.sub(r"\s+(?:technologies|media group|group)$", "", n, flags=re.I)
        return n.strip() or name

    # defensive: never render a run-together scraped card blob as a title
    jobs = [j for j in jobs if not _MANGLED_TITLE.search(j.get("title") or "")
            and len(j.get("title") or "") <= 100]
    ordered = sorted(jobs, key=lambda j: str(j.get("posted_date") or ""), reverse=True)
    n = len(ordered)

    def esc(s):
        return html.escape(str(s or ""))

    rows = []
    profiles = []
    for j in ordered:
        company = j.get("company", "")
        rtitle = j.get("title") or "(untitled)"
        prof = roleprofile.extract(rtitle, j.get("description"))
        resp_parts = _responsibilities_snippet(j.get("description"))
        req_parts = _requirements_snippet(j.get("description"))
        # WHERE an AI mention sits is signal: requirements = prior experience you must
        # bring; responsibilities = something the role will do (learnable on the job)
        prof["ai_req"] = (roleprofile.classify_ai(" • ".join(t for t, _ in req_parts))
                          if req_parts else [])
        prof["soft"] = (roleprofile.classify_soft(" • ".join(t for t, _ in req_parts))
                        if req_parts else [])
        prof["ai_day"] = roleprofile.classify_ai(" • ".join(resp_parts)) if resp_parts else []
        if not prof["ai_day"] and not prof["ai_req"]:
            prof["ai_day"] = prof["ai"]     # mentioned only in intro prose
        if resp_parts:
            prof["tasks"] = roleprofile.classify_tasks(resp_parts)
        else:
            # prose-style JDs ("As an analyst you will …") have no bullet section to
            # extract, but the pre-requirements text still tells us the day-to-day
            d2 = _LABEL_PREFIX.sub("", _clean_desc(j.get("description")))
            mreq = _req_header_match(d2)
            intro = (d2[:mreq.start()] if mreq else d2)[:2200]
            # split prose into sentence chunks so the emphasis threshold means something
            chunks = [c for c in _SENT_SPLIT.split(intro) if len(c) > 15] or ([intro] if intro else [])
            prof["tasks"] = roleprofile.classify_tasks(chunks)
        profiles.append(prof)
        about = (company_info.get(company) or _company_blurb(j.get("description"), company) or "")
        if _ABOUT_JUNK.search(about):           # a failed `claude -p` error must never show
            about = _company_blurb(j.get("description"), company) or ""
        # The summaries are already constrained to 2-3 sentences at the source; show them
        # whole. The cap is only a safety net for pathological output — cut at a sentence
        # boundary so the "how it makes money" half is never chopped mid-thought.
        if len(about) > 700:
            cut = about[:700]
            p = max(cut.rfind(". "), cut.rfind("! "))
            about = cut[:p + 1] if p > 200 else cut[:cut.rfind(" ")] + "…"
        raw_chip = _seniority_chip(j.get("description")) or ""
        chip = _sen_canon(raw_chip, rtitle)
        rank = _sen_rank(raw_chip or chip)
        loc = _norm_location(j.get("location"))
        pdate = j.get("posted_date") or ""
        age = _age_note(pdate, run_date)
        url = esc(_safe_url(j.get("url")))
        emp = _employment_badge(rtitle)
        skill_names = [s for s, _ in prof["skills"]]
        # skills + task tokens join the search blob so the filter box finds
        # "sql", "tableau", "reporting", "stakeholders" jobs
        blob = esc(f"{company} {rtitle} {loc} {chip} "
                   + " ".join(skill_names) + " " + prof["family"] + " "
                   + " ".join(tok for _, tok in prof["tasks"]) + " "
                   + " ".join(tok for _, tok in prof["ai_day"]) + " "
                   + " ".join(tok + "-req" for _, tok in prof["ai_req"]) + " "
                   + " ".join(tok for _, tok in prof["soft"])).lower()
        emp_html = f' <span class="emp">{esc(emp)}</span>' if emp else ''
        # a posting whose posted_date jumped well past when WE first saw it was re-posted
        # (bumped) by the company — mark it honestly instead of letting it look brand-new
        fs0 = (j.get("first_seen") or "")[:10]
        pd0 = pdate[:10]
        repost = False
        try:
            if len(fs0) == 10 and len(pd0) == 10:
                repost = (_dt.date.fromisoformat(pd0) - _dt.date.fromisoformat(fs0)).days >= 3
        except ValueError:
            repost = False
        if repost:
            emp_html += (f' <span class="repb" title="Re-posted by the company on {esc(pd0)} — '
                         f'this listing first appeared here on {esc(fs0)}">reposted</span>')
        else:
            fs = pd0 or fs0
            if fs and fs >= _newcut(run_date):
                emp_html += ' <span class="newb">new</span>'
        # honest label: a LinkedIn URL is not "the company site"
        apply_label = ('View the posting on LinkedIn →' if 'linkedin.com' in url.lower()
                       else 'Apply on the company site →')
        apply = (f'<a class="apply" href="{url}" target="_blank" rel="noopener">'
                 f'{apply_label}</a>') if url else ''
        # --- two-column detail card: company + day-to-day (left) | demands (right) ---
        _BADGE_TIP = {"must": "The posting marks this as a hard requirement",
                      "plus": "Marked as an advantage — nice to have, not required"}
        left = ""
        if about:
            left += f'<p class="about" dir="auto"><b>About {esc(company)}</b> — {esc(about)}</p>'
        facts = _firmo_facts(firmographics.get(company))
        if facts:
            left += ('<p class="cofacts">'
                     + "".join(f'<span>{esc(f)}</span>' for f in facts) + '</p>')
        if repost:
            left += (f'<p class="repline">↻ Re-posted {esc(pd0)} — this listing first '
                     f'appeared here {esc(fs0)}</p>')
        ai_day, ai_req = prof["ai_day"], prof["ai_req"]
        if resp_parts or prof["tasks"] or ai_day:
            left += '<p class="rlabel">Day to day</p>'
            chips = "".join(
                f'<button class="skilltag ttag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.TASK_DESC.get(lbl, lbl))} · click to filter the board">'
                f'{esc(lbl)}</button>' for lbl, tok in prof["tasks"])
            chips += "".join(
                f'<button class="skilltag aitag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.AI_DESC.get(lbl, lbl))} · click to filter the board">'
                f'🤖 {esc(lbl)}</button>' for lbl, tok in ai_day)
            if chips:
                left += f'<div class="skills">{chips}</div>'
            if resp_parts:
                lis = "".join(f'<li dir="auto">{esc(p)}</li>' for p in resp_parts[:5])
                left += f'<ul class="reqs resp">{lis}</ul>'
        left += apply
        right = ""
        if req_parts:
            lis = []
            for txt, badge in req_parts:
                b = (f' <span class="rq rq-{badge}" title="{esc(_BADGE_TIP[badge])}">{badge}</span>'
                     if badge else "")
                lis.append(f'<li dir="auto">{esc(txt)}{b}</li>')
            right += (f'<p class="rlabel">What you&#8217;ll need</p>'
                      f'<ul class="reqs">{"".join(lis)}</ul>')
            if ai_req:
                achips = "".join(
                    f'<button class="skilltag aitag" data-skill="{esc(tok)}-req" '
                    f'title="{esc(roleprofile.AI_DESC.get(lbl, lbl))} — asked as prior '
                    f'experience · click to filter the board">'
                    f'🤖 {esc(lbl)}</button>' for lbl, tok in ai_req)
                right += f'<div class="skills">{achips}</div>'
        else:
            right += ('<p class="rlabel">What you&#8217;ll need</p>'
                      '<p class="about muted" dir="auto">Requirements aren&#8217;t captured '
                      'for this posting yet &mdash; open the listing for the full details.</p>')
        if skill_names:
            tags = "".join(
                f'<button class="skilltag" data-skill="{esc(s.lower())}" '
                f'title="{esc(roleprofile.SKILL_DESC.get(s, s))} · click to filter the board">'
                f'{esc(s)}</button>' for s in skill_names[:12])
            right += f'<p class="rlabel">Skills mentioned</p><div class="skills">{tags}</div>'
        if prof["soft"]:
            stags = "".join(
                f'<button class="skilltag stag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.SOFT_DESC.get(lbl, lbl))} · click to filter the board">'
                f'{esc(lbl)}</button>' for lbl, tok in prof["soft"])
            right += f'<p class="rlabel">Soft skills asked for</p><div class="skills">{stags}</div>'
        # degree marker: level + fields + required-vs-plus, e.g. "BSc · CS/Industrial Eng."
        deg = prof["degree"]
        deg_txt = ""
        if deg:
            deg_txt = deg["level"] + (" · " + "/".join(deg["fields"]) if deg["fields"] else "")
            if deg["status"] == "preferred":
                deg_txt += " (a plus)"
        # no facts card on desktop — everything it held is on the row (or meaningless in
        # isolation, like a bare "Senior"). The dup-marked facts survive for MOBILE only,
        # where the Location/Posted/Degree columns are hidden.
        facts = [("Location", loc, True), ("Posted", _rel_date(pdate, run_date), True)]
        if deg_txt:
            facts.append(("Degree", deg_txt, True))
        shown = [f for f in facts if not f[2]]        # facts the row doesn't already show
        facts_html = ('<dl class="facts">' + "".join(
            f'<div class="fact{" dup" if dup else ""}"><dt>{esc(k)}</dt>'
            f'<dd{" class=nd" if (not v or v == "—") else ""}>{esc(v or "—")}</dd></div>'
            for k, v, dup in facts) + '</dl>')
        side = f'<aside class="dside{"" if shown else " monly"}">{facts_html}</aside>'
        detail = (f'<div class="dcard"><div class="dcol">{left}</div>'
                  f'<div class="dcol dcol2">{right}</div>{side}</div>')
        # dedicated columns carry the high-level ask: top skills, years, degree.
        # ALL skills render in the cell; the +N chip is computed live by JS from how
        # many actually fit, so dragging the column divider expands the visible list.
        if skill_names:
            sks = "".join(f'<span class="sk">{esc(s)}</span>' for s in skill_names)
            skl_cell = (f'<span class="sklist">{sks}</span>'
                        '<span class="skmore" style="display:none"></span>')
        else:
            skl_cell = '<span class="nd">—</span>'
        yrs_cell = f"{prof['years']}+" if prof["years"] else '<span class="nd">—</span>'
        if deg:
            deg_cell = esc(deg["level"]) + ((' <span class="rq rq-plus" title="The posting marks '
                                             'the degree as an advantage, not a requirement">plus</span>')
                                            if deg["status"] == "preferred" else '')
        else:
            deg_cell = '<span class="nd">—</span>'
        deg_rank = {"BSc": 1, "MSc": 2, "PhD": 3}.get(deg["level"], 0) if deg else 0
        rows.append(
            f'<tr class="row" tabindex="0" role="button" aria-expanded="false" '
            f'data-blob="{blob}" data-company="{esc(company).lower()}" '
            f'data-role="{esc(rtitle).lower()}" data-loc="{esc(loc).lower()}" '
            f'data-date="{esc(pdate)}" data-years="{prof["years"] or 99}" '
            f'data-deg="{deg_rank}" data-skills="{esc(" ".join(skill_names)).lower()}">'
            f'<td class="cco" title="{esc(company)}">{esc(_display_company(company))}</td>'
            f'<td class="cro">{esc(rtitle)}{emp_html}</td>'
            f'<td class="cskl">{skl_cell}</td>'
            f'<td class="cloc">{esc(loc)}</td>'
            f'<td class="cyrs" title="Years of experience asked for">{yrs_cell}</td>'
            f'<td class="cdeg">{deg_cell}</td>'
            f'<td class="cdate" title="{esc(pdate)}">{esc(_rel_date(pdate, run_date))}{esc(age)}</td></tr>'
            f'<tr class="detail"><td colspan="7"><div class="db">{detail}</div></td></tr>')

    # ---- aggregated demand view: what the market is asking for, computed per posting ----
    insights = ""
    if profiles and "archived" not in heading:
        agg = roleprofile.aggregate(profiles)

        def _bar(token, label, c, mx, desc=""):
            tip = (desc + " · " if desc else "") + f"{c} roles · click to filter"
            return (f'<button class="ibar" data-skill="{esc(token)}" title="{esc(tip)}">'
                    f'<span class="ibar-fill" style="width:{max(4, round(c / mx * 100))}%"></span>'
                    f'<span class="ibar-name">{esc(label)}</span><span class="ibar-n">{c}</span></button>')

        ccards = ""
        for clabel, items in agg["clusters"]:
            if not items:
                continue
            mx = items[0][1] or 1
            bars = "".join(_bar(s.lower(), s, c, mx, roleprofile.SKILL_DESC.get(s, ""))
                           for s, c in items)
            ccards += (f'<div class="ccard"><div class="fhead">{esc(clabel)}</div>'
                       f'<div class="cbars">{bars}</div></div>')
        if agg["tasks"]:
            mx = agg["tasks"][0][2] or 1
            bars = "".join(_bar(tok, lbl, c, mx, roleprofile.TASK_DESC.get(lbl, ""))
                           for lbl, tok, c in agg["tasks"])
            ccards += (f'<div class="ccard ctasks"><div class="fhead">Day-to-day focus'
                       f'<span class="fn">what these roles actually do</span></div>'
                       f'<div class="cbars">{bars}</div></div>')
        if agg["ai_req"] or agg["ai_day"]:
            mx = max([c for _, _, c in agg["ai_req"]] + [c for _, _, c in agg["ai_day"]]) or 1
            inner = ""
            if agg["ai_req"]:
                inner += ('<div class="aisub" title="The posting asks for prior AI '
                          'experience in its requirements">Required coming in</div>'
                          + "".join(_bar(tok + "-req", lbl, c, mx,
                                         roleprofile.AI_DESC.get(lbl, "") + " — asked as prior experience")
                                    for lbl, tok, c in agg["ai_req"]))
            if agg["ai_day"]:
                inner += ('<div class="aisub" title="AI appears in the responsibilities — '
                          'something the role does, learnable on the job">In the day-to-day</div>'
                          + "".join(_bar(tok, lbl, c, mx,
                                         roleprofile.AI_DESC.get(lbl, "") + " — part of the role\'s duties")
                                    for lbl, tok, c in agg["ai_day"]))
            ccards += (f'<div class="ccard cai"><div class="fhead">🤖 AI usage'
                       f'<span class="fn">required skill vs. part of the job</span></div>'
                       f'<div class="cbars">{inner}</div></div>')
        if agg["soft"]:
            mx = agg["soft"][0][2] or 1
            bars = "".join(_bar(tok, lbl, c, mx, roleprofile.SOFT_DESC.get(lbl, ""))
                           for lbl, tok, c in agg["soft"])
            ccards += (f'<div class="ccard csoft"><div class="fhead">Soft skills'
                       f'<span class="fn">asked for in requirements</span></div>'
                       f'<div class="cbars">{bars}</div></div>')
        if ccards:
            insights = (
                '<details class="insights"><summary>📊 Skills &amp; day-to-day demand — '
                f'across the {agg["with_skills"]} roles with captured postings '
                f'(of {agg["total"]} open; click anything to filter)</summary>'
                f'<div class="ins-clusters">{ccards}</div></details>')

    fresh = sum(1 for j in ordered if not _age_note(j.get("posted_date"), run_date))
    audit = (f"{n} open roles · {fresh} posted recently · "
             f"{stats.get('companies_scanned',0)} companies scanned · refreshed {esc(run_date)}")
    contact = (f' · <a href="{esc(contact_url)}" target="_blank" rel="noopener">Contact</a>'
               if contact_url else '')
    if "archived" not in heading:
        contact += ' · <a href="archive.html">Job archive</a>'
    else:
        contact += ' · <a href="index.html">Back to live board</a>' 

    css = """<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#141821;--muted:#5b6470;--body:#333a44;--card:#f6f8fa;
--border:#e3e6ea;--line:#dfe3e8;--accent:#1a56db;--btn:#1f6feb;--head:#0a0d12;--rowh:#eef3fb;
--chipbg:#eef1f5;--emp:#8a5a00;--empbg:#fff4d6}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e9eef5;--muted:#9aa4b0;--body:#c4ccd6;
--card:#161b22;--border:#2a2f37;--line:#272d36;--accent:#6ea8ff;--btn:#2563eb;--head:#ffffff;
--rowh:#1a2130;--chipbg:#1e2530;--emp:#f0c674;--empbg:#3a2f12}}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
color:var(--fg);background:var(--bg);line-height:1.45}
.wrap{max-width:1560px;margin:0 auto;padding:18px 20px 40px}
h1{font-size:22px;margin:0 0 5px;color:var(--head);letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
#q{width:100%;padding:11px 13px;height:44px;font-size:15px;border:1px solid var(--border);
border-radius:10px;background:var(--card);color:var(--fg);margin-bottom:12px}
#q:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#fbar{display:flex;align-items:center;gap:12px;margin:-4px 0 12px;font-size:12.5px;
color:var(--accent);font-weight:600}
#fbar[hidden]{display:none}
#fclear{border:1px solid var(--border);background:var(--card);color:var(--muted);cursor:pointer;
border-radius:999px;padding:3px 11px;font-size:11.5px;font-weight:600;font-family:inherit}
#fclear:hover{color:var(--accent);border-color:var(--accent)}
.tw{overflow:auto;max-height:calc(100vh - 150px);border:1px solid var(--border);border-radius:12px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px;
table-layout:fixed;min-width:880px}
thead th{position:sticky;top:0;z-index:5;background:var(--card);text-align:left;padding:11px 14px;
color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.03em;text-transform:uppercase;
cursor:pointer;user-select:none;border-bottom:1px solid var(--border);white-space:nowrap;
box-shadow:0 2px 6px -4px rgba(0,0,0,.35);overflow:visible}
thead th:not(:last-child){border-right:1px solid var(--line)}
.rz{position:absolute;top:0;right:-5px;width:11px;height:100%;cursor:col-resize;z-index:7}
.rz:hover,.rz.on{background:linear-gradient(to right,transparent 4px,var(--accent) 4px,
var(--accent) 6px,transparent 6px)}
thead th:hover{color:var(--fg)} thead th:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
th[aria-sort=ascending]:after{content:" \\2191";color:var(--accent)}
th[aria-sort=descending]:after{content:" \\2193";color:var(--accent)}
tbody td{padding:11px 14px;border-top:1px solid var(--line);vertical-align:top}
tbody tr.row:first-child td{border-top:none}
tr.row{cursor:pointer} tr.row:hover td{background:var(--rowh)}
tr.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
td.cco{color:var(--body);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
td.cro{font-weight:700;color:var(--head);font-size:14.5px}
td.cco::before{content:"\\25B8  ";color:var(--muted)}
tr.row[aria-expanded=true] td.cco::before{content:"\\25BE  "}
td.cdate{white-space:nowrap;color:var(--muted);font-size:13px}
td.cro{overflow:hidden}
td.cloc{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.cskl{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;position:relative}
.sklist{display:inline-block;max-width:calc(100% - 30px);overflow:hidden;white-space:nowrap;
vertical-align:middle}
.sk+.sk::before{content:" · "}
.skmore{position:absolute;right:6px;top:50%;transform:translateY(-50%);color:var(--accent);
font-weight:700;font-size:11px;background:var(--chipbg);border-radius:6px;padding:1px 6px}
td.cyrs{white-space:nowrap;font-size:13px;color:var(--body);font-variant-numeric:tabular-nums}
td.cdeg{white-space:nowrap;font-size:12.5px;color:var(--body)}
td .nd{color:var(--muted)}
.sen{display:inline-block;white-space:nowrap;font-size:12px;font-weight:600;padding:2px 9px;
border-radius:999px;background:var(--chipbg);color:var(--fg)}
.sen.empty{background:transparent;border:1px dashed var(--border);color:var(--muted);font-weight:500}
/* one tidy vocabulary — Lead+ carries the most weight, Junior the least */
.sen-leadp{background:var(--empbg);color:var(--emp)}
.sen-junior,.sen-mid{background:transparent;border:1px solid var(--border);color:var(--muted)}
.emp{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:6px;
background:var(--empbg);color:var(--emp);vertical-align:middle}
.newb{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:6px;
background:#1a7f37;color:#fff;vertical-align:middle}
.repb{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:6px;
background:var(--empbg);color:var(--emp);vertical-align:middle;cursor:help}
tr.detail{display:none} tr.detail.open{display:table-row}
tr.detail td{background:var(--card);border-top:none;padding:0}
.db{padding:20px 18px 22px}
.dcard{display:grid;grid-template-columns:minmax(0,10fr) minmax(0,11fr);gap:6px 60px;
align-items:start;max-width:1280px}
.dcol{min-width:0}
.repline{color:var(--emp);font-size:12.5px;margin:-6px 0 16px;font-weight:500}
.dside{display:none}
.about{color:var(--body);margin:0 0 10px;font-size:14px;line-height:1.68}
.cofacts{margin:0 0 16px;display:flex;flex-wrap:wrap;gap:6px}
.cofacts span{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 9px;white-space:nowrap}
.about b{color:var(--fg);font-weight:700} .about.muted{color:var(--muted);font-style:italic}
.rlabel{display:flex;align-items:center;gap:12px;font-size:11px;text-transform:uppercase;
letter-spacing:.07em;color:var(--muted);font-weight:700;margin:2px 0 10px}
.rlabel:after{content:"";flex:1 1 auto;height:1px;background:var(--line)}
ul.reqs{margin:0 0 16px;padding:0;list-style:none}
ul.reqs li{position:relative;padding-left:18px;margin:7px 0;color:var(--body);font-size:13.5px;
line-height:1.5}
ul.reqs li:before{content:"";position:absolute;left:2px;top:8px;width:5px;height:5px;
border-radius:50%;background:var(--accent)}
.rq{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;
vertical-align:1px;text-transform:uppercase;letter-spacing:.04em}
.rq-must{background:var(--empbg);color:var(--emp)}
.rq-plus{background:transparent;border:1px solid var(--border);color:var(--muted)}
.facts{margin:0;border:1px solid var(--border);border-radius:11px;overflow:hidden;background:var(--bg)}
.fact.dup{display:none} .dside.monly{display:none}
.fact{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:10px 13px;
border-top:1px solid var(--line)} .fact:first-child{border-top:none}
.fact dt{margin:0;color:var(--muted);font-size:10.5px;font-weight:700;text-transform:uppercase;
letter-spacing:.05em}
.fact dd{margin:0;color:var(--fg);font-size:13px;font-weight:600;text-align:right}
.fact dd.nd{color:var(--muted);font-weight:500}
.apply{display:inline-block;margin-top:2px;padding:11px 18px;background:var(--btn);color:#fff;
text-decoration:none;border-radius:9px;font-weight:600;font-size:13.5px}
.apply:hover{filter:brightness(1.08)} .apply:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.skills{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.skilltag{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;
background:var(--chipbg);color:var(--fg);border:1px solid var(--border);cursor:pointer;
font-family:inherit}
.skilltag:hover{border-color:var(--accent);color:var(--accent)}
.insights{margin:0 0 12px;border:1px solid var(--border);border-radius:12px;background:var(--card)}
.insights summary{padding:12px 16px;cursor:pointer;font-size:13.5px;font-weight:600;color:var(--fg);
user-select:none}
.insights summary:hover{color:var(--accent)}
.insights[open] summary{border-bottom:1px solid var(--line)}
.ins-clusters{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;
padding:16px}
.ccard{border:1px solid var(--border);border-radius:10px;padding:12px 13px;background:var(--bg)}
.ccard .fhead{margin-bottom:9px}
.cbars{display:flex;flex-direction:column;gap:4px}
.ctasks .ibar-fill{background:var(--emp)}
.cai .ibar-fill{background:#1a7f37;opacity:.22}
.csoft .ibar-fill{background:#8250df;opacity:.2}
.stag{border-style:dotted}
.aisub{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
color:var(--muted);margin:7px 0 2px;cursor:help}
.aisub:first-child{margin-top:0}
.aitag{border-style:solid;border-color:#1a7f37;color:inherit}
.aitag:hover{border-color:#2ea043;color:#2ea043}
.legend{margin:16px 0 0;border:1px solid var(--border);border-radius:12px;background:var(--card)}
.legend summary{padding:11px 16px;cursor:pointer;font-size:12.5px;font-weight:600;color:var(--muted)}
.legend summary:hover{color:var(--fg)}
.legend[open] summary{border-bottom:1px solid var(--line)}
.legend .lg{padding:14px 18px;font-size:12.5px;color:var(--body);line-height:1.65;max-width:110ch}
.legend .lg p{margin:0 0 10px} .legend .lg b{color:var(--fg)}
.ibar{position:relative;display:flex;align-items:center;gap:8px;height:26px;border:none;
background:transparent;cursor:pointer;padding:0 8px;border-radius:6px;font-family:inherit;
overflow:hidden;text-align:left}
.ibar:hover .ibar-name{color:var(--accent)}
.ibar-fill{position:absolute;left:0;top:0;bottom:0;background:var(--accent);opacity:.14;
border-radius:6px}
.ibar-name{position:relative;font-size:12.5px;font-weight:600;color:var(--fg);flex:1 1 auto;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ibar-n{position:relative;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.ins-fams{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
gap:12px;padding:0 16px 16px}
.fcard{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:var(--bg)}
.fhead{font-size:12.5px;font-weight:700;color:var(--fg);margin-bottom:8px;display:flex;
justify-content:space-between;align-items:baseline;gap:8px}
.fn{font-size:11px;color:var(--muted);font-weight:500;white-space:nowrap}
.fskills{display:flex;flex-wrap:wrap;gap:5px}
.fskills .skilltag{font-size:11px;padding:2px 8px}
ul.reqs.resp li:before{background:var(--emp)}
.ttag{border-style:dashed}
.nores{padding:26px;text-align:center;color:var(--muted)}
.foot{color:var(--muted);font-size:12px;margin-top:16px} .foot a{color:var(--accent)}
@media(max-width:600px){td.cloc,th.hloc,td.cdate,th.hdate,td.cskl,th.hskl,td.cdeg,th.hdeg{display:none}
.wrap{padding:14px 10px 30px} td.cro{font-size:14px} h1{font-size:22px}
.db{padding:16px 13px 18px} .dcard{grid-template-columns:1fr;gap:14px}
.fact.dup{display:flex} .dside{display:block;order:-1}}
</style>"""

    js = """<script>
var tb=document.getElementById('tb'),q=document.getElementById('q'),
    cnt=document.getElementById('cnt'),nores=document.getElementById('nores');
function R(){return [].slice.call(tb.querySelectorAll('tr.row'));}
function filt(){var v=q.value.toLowerCase().split(/\\s+/).filter(Boolean),shown=0;
  R().forEach(function(r){var s=v.every(function(w){return r.dataset.blob.indexOf(w)>-1;});
    r.style.display=s?'':'none'; if(!s){r.nextElementSibling.classList.remove('open');r.setAttribute('aria-expanded','false');}
    if(s)shown++;});
  if(cnt)cnt.textContent=shown; if(nores)nores.style.display=shown?'none':'';
  var fb=document.getElementById('fbar'),fbt=document.getElementById('fbtxt');
  if(fb){if(q.value.trim()){fb.hidden=false;
    fbt.textContent='Filtering by “'+q.value.trim()+'” — showing '+shown+' of '+R().length+' roles';}
  else fb.hidden=true;}
  updSk();}
q.addEventListener('input',filt);
var fclear=document.getElementById('fclear');
if(fclear)fclear.addEventListener('click',function(){q.value='';filt();q.focus();});
/* skills cells hold the FULL list; count how many names are clipped and show +N */
function updSk(){[].slice.call(document.querySelectorAll('td.cskl')).forEach(function(td){
  var list=td.querySelector('.sklist'),more=td.querySelector('.skmore');
  if(!list||!more||td.offsetWidth===0)return;
  var base=list.offsetLeft,lim=list.clientWidth+2,hidden=0;
  [].slice.call(list.children).forEach(function(s){
    if(s.offsetLeft-base+s.offsetWidth>lim)hidden++;});
  if(hidden>0){more.textContent='+'+hidden;more.style.display='';}
  else{more.style.display='none';}});}
/* draggable column dividers on the headers */
var cols=[].slice.call(document.querySelectorAll('colgroup col')),
    ths=[].slice.call(document.querySelectorAll('thead th'));
[].slice.call(document.querySelectorAll('.rz')).forEach(function(h){
  h.addEventListener('click',function(e){e.stopPropagation();});
  h.addEventListener('keydown',function(e){e.stopPropagation();});
  h.addEventListener('pointerdown',function(e){
    e.preventDefault();e.stopPropagation();h.classList.add('on');
    if(h.setPointerCapture)try{h.setPointerCapture(e.pointerId);}catch(_){}
    var ci=+h.dataset.ci,startX=e.clientX,startW=ths[ci].getBoundingClientRect().width;
    function mv(ev){cols[ci].style.width=Math.max(56,startW+ev.clientX-startX)+'px';}
    function up(){document.removeEventListener('pointermove',mv);
      document.removeEventListener('pointerup',up);h.classList.remove('on');
      justRz=true;setTimeout(function(){justRz=false;},0);updSk();}
    document.addEventListener('pointermove',mv);
    document.addEventListener('pointerup',up);});});
window.addEventListener('resize',updSk);
updSk();
function toggle(r,e){if(e&&e.target&&e.target.closest('a'))return;
  var open=r.nextElementSibling.classList.toggle('open'); r.setAttribute('aria-expanded',open);}
R().forEach(function(r){
  r.addEventListener('click',function(e){toggle(r,e);});
  r.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(r,e);}});});
var dir={};
function sortBy(th){var k=th.dataset.k;dir[k]=!dir[k];var m=dir[k]?1:-1;
  var ps=R().map(function(r){return [r,r.nextElementSibling];});
  ps.sort(function(a,b){
    if(k==='years'||k==='deg'){return ((+a[0].dataset[k]||0)-(+b[0].dataset[k]||0))*m;}
    var x=a[0].dataset[k]||'',y=b[0].dataset[k]||''; return x<y?-m:x>y?m:0;});
  ps.forEach(function(p){tb.appendChild(p[0]);tb.appendChild(p[1]);});
  [].slice.call(document.querySelectorAll('th[data-k]')).forEach(function(t){t.setAttribute('aria-sort','none');});
  th.setAttribute('aria-sort',dir[k]?'ascending':'descending');}
var justRz=false;
[].slice.call(document.querySelectorAll('th[data-k]')).forEach(function(th){
  th.addEventListener('click',function(){if(justRz){justRz=false;return;}sortBy(th);});
  th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();sortBy(th);}});});
[].slice.call(document.querySelectorAll('[data-skill]')).forEach(function(b){
  b.addEventListener('click',function(){q.value=b.dataset.skill;filt();
    document.querySelector('.tw').scrollIntoView({behavior:'smooth',block:'start'});});});
</script>"""

    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Israeli analytics jobs — {esc(run_date)}</title>' + css
            + '</head><body><div class="wrap">')
    top = (f'<h1><span id="cnt">{n}</span> ' + esc(heading) + '</h1>'
           '<div class="sub">Experienced (≈3+ yrs) data / BI / analytics · open roles, '
           'refreshed daily · click a row to expand, a header to sort</div>'
           '<input id="q" type="search" aria-label="Filter roles" '
           'placeholder="Filter by company, role, skill, or location…">'
           '<div id="fbar" hidden><span id="fbtxt"></span>'
           '<button id="fclear" type="button" title="Clear the filter">✕ clear filter</button></div>')
    empty_row = ('<tr id="nores" style="display:none"><td colspan="7" class="nores">'
                 'No roles match your filter.</td></tr>')
    rz = '<span class="rz" data-ci="{i}" title="Drag to resize column"></span>'
    table = ('<div class="tw"><table>'
             '<colgroup><col style="width:165px"><col><col style="width:250px">'
             '<col style="width:135px"><col style="width:72px"><col style="width:95px">'
             '<col style="width:105px"></colgroup>'
             '<thead><tr>'
             '<th data-k="company" tabindex="0" role="columnheader" aria-sort="none">Company' + rz.format(i=0) + '</th>'
             '<th data-k="role" tabindex="0" role="columnheader" aria-sort="none">Role' + rz.format(i=1) + '</th>'
             '<th data-k="skills" tabindex="0" role="columnheader" aria-sort="none" class="hskl">Skills' + rz.format(i=2) + '</th>'
             '<th data-k="loc" tabindex="0" role="columnheader" aria-sort="none" class="hloc">Location' + rz.format(i=3) + '</th>'
             '<th data-k="years" tabindex="0" role="columnheader" aria-sort="none" class="hyrs" '
             'title="Years of experience asked for">Years' + rz.format(i=4) + '</th>'
             '<th data-k="deg" tabindex="0" role="columnheader" aria-sort="none" class="hdeg">Degree' + rz.format(i=5) + '</th>'
             '<th data-k="date" tabindex="0" role="columnheader" aria-sort="none" class="hdate">Posted</th>'
             '</tr></thead><tbody id="tb">'
             + ("".join(rows) + empty_row if rows
                else '<tr><td colspan="7" class="nores">No open roles right now.</td></tr>')
             + '</tbody></table></div>')
    # ---- on-page documentation of the tagging system (kept in sync with the code) ----
    legend = ""
    if "archived" not in heading:
        tg = " · ".join(f"<b>{esc(l)}</b> ({esc(roleprofile.TASK_DESC.get(l, ''))})"
                        for l, _, _ in roleprofile.TASK_GROUPS)
        au = " · ".join(f"<b>{esc(l)}</b> ({esc(d)})" for l, d in roleprofile.AI_DESC.items())
        cl = ", ".join(l for _, l in roleprofile.CLUSTERS)
        legend = (
            '<details class="legend"><summary>ℹ️ How the tags on this board are computed</summary>'
            '<div class="lg">'
            '<p><b>Everything is extracted deterministically from the posting text</b> — a fixed '
            'keyword lexicon and header rules, no AI guessing. A tag can be missing simply because '
            'the posting never stated it; postings without a captured description show no tags at all.</p>'
            f'<p><b>Skills</b> are matched from a curated ~55-term lexicon and grouped into '
            f'non-overlapping clusters: {esc(cl)}. Hover any tag for its meaning.</p>'
            '<p><b>MUST / PLUS badges</b> mirror the posting&#8217;s own wording (&#8220;a must&#8221;, '
            '&#8220;an advantage&#8221;, חובה / יתרון) — absence of a badge means the posting didn&#8217;t '
            'mark that line. <b>Years</b> is the experience figure stated nearest to '
            '&#8220;experience&#8221;. <b>Degree</b> shows the level and fields asked for; '
            '&#8220;plus&#8221; means the posting itself calls the degree an advantage.</p>'
            f'<p><b>Day-to-day groups</b> classify the responsibilities section: {tg}. '
            'A chip appears only when a group matches <b>multiple</b> responsibility bullets — '
            'it marks an emphasis of the role, not a passing mention — and chips are ordered '
            'by how dominant each theme is.</p>'
            f'<p><b>🤖 AI usage</b> classifies what the analyst is expected to do with AI, judged '
            f'from the words around each AI mention: {au}. WHERE the mention sits matters: in the '
            'requirements section it is <b>prior experience you must bring</b>; in the '
            'responsibilities it is <b>part of the job</b> — learnable, not a bar to entry. The '
            'dashboard and chips keep the two apart. Mentions of the company&#8217;s own AI '
            'product (&#8220;analyze our AI agents&#8221;) are deliberately NOT counted — that is '
            'product analysis, not AI usage.</p>'
            '<p><b>Soft skills</b> (dotted chips) are tagged from the requirements section only — '
            'the person the posting describes, separate from the toolbox: communication, ownership, '
            'business acumen, curiosity, and so on. Hover any chip for its meaning.</p>'
            '<p><b>reposted</b> marks a posting whose date was bumped 3+ days after this board first '
            'saw it, with the original date in the card.</p>'
            '</div></details>')
    foot = f'<div class="foot">{esc(audit)}{contact}</div>'
    return (head + top + insights + table + legend + foot + '</div>' + js
            + analytics_html + '</body></html>')


def _path_label(path):
    return {
        "keyword": "keyword",
        "keyword_nollm": "keyword(no-llm)",
        "llm": "LLM",
        "llm_cache": "LLM(cached)",
        "llm_failed_fallback": "LLM-failed→fallback",
    }.get(path, path or "?")


def build_digest(jobs, run_date, stats):
    """Return (subject, html, text).

    `jobs` are merged+new accepted jobs, each with keys: company, title, location, url,
    posted_date, sources (list), and `_class` (the classify() result dict).
    `stats` is a dict of run counters.
    """
    n = len(jobs)
    subject = f"[Israeli Jobs] {n} new senior analytics opening" + ("" if n == 1 else "s") + f" — {run_date}"

    # group by company (alphabetical), jobs within a company by posted_date desc
    by_company = {}
    for j in jobs:
        by_company.setdefault(j["company"], []).append(j)
    for c in by_company:
        by_company[c].sort(key=lambda j: str(j.get("posted_date") or ""), reverse=True)

    # ---------- plaintext ----------
    tl = [subject, "=" * len(subject), ""]
    if n == 0:
        tl.append("No new matching openings today.")
    for company in sorted(by_company):
        tl.append(f"\n{company}")
        tl.append("-" * len(company))
        for j in by_company[company]:
            src = "+".join(j.get("sources", [])) or j.get("ats_platform", "")
            path = _path_label(j.get("_class", {}).get("path"))
            tl.append(f"  • {j['title']}")
            tl.append(f"      {j.get('location') or '—'} | posted {_fmt_date(j.get('posted_date'))} | via {src} | match:{path}")
            tl.append(f"      {j.get('url') or ''}")
    tl.append("")
    tl.append(_text_audit(stats))
    text = "\n".join(tl)

    # ---------- HTML ----------
    def esc(s):
        return html.escape(str(s or ""))

    hb = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:720px;margin:0 auto;color:#1a1a1a;">',
        f'<h2 style="margin:0 0 4px;">{esc(str(n))} new senior analytics opening{"" if n==1 else "s"}</h2>',
        f'<div style="color:#666;font-size:13px;margin-bottom:16px;">Israeli high-tech ATS scan · {esc(run_date)}</div>',
    ]
    if n == 0:
        hb.append('<p style="color:#666;">No new matching openings today.</p>')
    for company in sorted(by_company):
        hb.append(f'<h3 style="margin:22px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px;">{esc(company)}</h3>')
        for j in by_company[company]:
            src = "+".join(j.get("sources", [])) or j.get("ats_platform", "")
            path = _path_label(j.get("_class", {}).get("path"))
            url = esc(_safe_url(j.get("url")))
            title = esc(j.get("title"))
            title_html = f'<a href="{url}" style="color:#1a56db;text-decoration:none;">{title}</a>' if url else title
            hb.append(
                '<div style="margin:8px 0 12px;">'
                f'<div style="font-size:15px;font-weight:600;">{title_html}</div>'
                f'<div style="color:#555;font-size:13px;margin-top:2px;">'
                f'{esc(j.get("location") or "—")} &nbsp;·&nbsp; posted {esc(_fmt_date(j.get("posted_date")))} '
                f'&nbsp;·&nbsp; via {esc(src)} '
                f'&nbsp;·&nbsp; <span style="color:#888;">match: {esc(path)}</span>'
                '</div></div>'
            )
    hb.append(_html_audit(stats, esc))
    hb.append("</div>")
    return subject, "\n".join(hb), text


def _text_audit(s):
    paths = s.get("paths", {})
    lines = [
        "-" * 40,
        "RUN AUDIT",
        f"  companies scanned: {s.get('companies_scanned', 0)}  (failed: {s.get('companies_failed', 0)})",
        f"  jobs fetched: {s.get('jobs_fetched', 0)}  | Israel-matched: {s.get('israel_matched', 0)}",
        f"  accepted: {s.get('accepted', 0)}  | after merge: {s.get('after_merge', 0)}  | NEW (this digest): {s.get('new', 0)}",
        f"  decision paths: " + ", ".join(f"{k}={v}" for k, v in sorted(paths.items())),
        f"  LLM calls this run: {s.get('llm_calls', 0)}"
        + (f"  | JDs fetched inline: {s.get('jd_filled_inline', 0)}"
           if s.get("jd_filled_inline") else ""),
    ]
    if s.get("stages"):
        lines.append(f"  stage order: {s['stages']}")
    if s.get("failed_companies"):
        lines.append("  failed companies: " + ", ".join(s["failed_companies"]))
    return "\n".join(lines)


def _html_audit(s, esc):
    paths = s.get("paths", {})
    fc = s.get("failed_companies", [])
    return (
        '<div style="margin-top:28px;padding:12px 14px;background:#f7f7f8;border-radius:8px;'
        'font-size:12px;color:#666;">'
        '<div style="font-weight:600;color:#444;margin-bottom:6px;">Run audit</div>'
        f'Companies scanned: {esc(s.get("companies_scanned",0))} (failed: {esc(s.get("companies_failed",0))})<br>'
        f'Jobs fetched: {esc(s.get("jobs_fetched",0))} · Israel-matched: {esc(s.get("israel_matched",0))}<br>'
        f'Accepted: {esc(s.get("accepted",0))} · after merge: {esc(s.get("after_merge",0))} · '
        f'<b>NEW: {esc(s.get("new",0))}</b><br>'
        f'Decision paths: {esc(", ".join(f"{k}={v}" for k,v in sorted(paths.items())))}<br>'
        f'LLM calls this run: {esc(s.get("llm_calls",0))}'
        + (f' · JDs fetched inline: {esc(s.get("jd_filled_inline",0))}'
           if s.get("jd_filled_inline") else "")
        + (f'<br>Stage order: {esc(s.get("stages",""))}' if s.get("stages") else "")
        + (f'<br>Failed companies: {esc(", ".join(fc))}' if fc else "")
        + '</div>'
    )
