"""The JD as text -> structure (lane: render, ARCHITECTURE.md §7d, part 1a).

Pure functions over a posting's own words: the requirements and responsibilities sections
as clean bullets with MUST/PLUS badges, the "what the company does" sentence, the location
label, the seniority chip, the posted-date label. No LLM, no network, nothing imported beyond
the standard library and the lexicon — so every tag on a card is reproducible, free, and
testable from a string.

`pipeline/rolecard.py` assembles these into one card per role; `pipeline/digest.py` renders
cards into the board, the archive and the mail. Nothing here escapes for HTML or Markdown —
that is the renderer's job, and the one place it happens. The lexicon (`roleprofile.SKILLS`,
`SOFT_SKILLS`) is imported for one question: is this short fragment a skill or a leftover.
"""
from __future__ import annotations

import datetime as _dt
import re


# --------------------------------------------------------------------------- #
# snippet / metadata helpers (address the digest UX review)
# --------------------------------------------------------------------------- #
_ZW = re.compile(r"[﻿​‎‏­]")           # BOM / zero-width / soft hyphen
_LABEL_PREFIX = re.compile(r"^\s*(experience level\s*:[^.]*\.\s*)?(description\s*:\s*)?", re.I)
_EXP_LEVEL = re.compile(r"experience level\s*:\s*([^.]+)", re.I)
_YEARS = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?\b", re.I)
# "<Company> is a/an/the <predicate>." -> company one-liner
_COMPANY_IS = re.compile(r"\b(?:is|are)\s+(?:a|an|the)\s+(.{5,90}?)[\.\n;]", re.I)
_HEBREW = re.compile(r"[֐-׿]")
# a failed `claude -p` (or similar CLI error) must never render as an About blurb —
# and neither must a first-person "I'm not sure what this company does" meta answer:
# a job seeker should read facts about the company, never the model talking about itself.
# a title with a breadcrumb separator or a place/CTA fused onto it is a scraped card blob
_MANGLED_TITLE = re.compile(r"[⋅•·|►▸\n\r]|,\s*israel\b|tel[\s-]?aviv,|"
                            r"(?<=[a-z])(?:Tel Aviv|Israel|Apply|Remote|Full[\s-]?time)|"
                            r"israel(?=[A-Za-z])|\s[/>]\s.*\b(?:apply|remote|hybrid|full[\s-]?time)\b|"
                            r"\s[-–—]\s*apply(?:\s+now)?\b", re.I)


def _clean_desc(desc):
    d = " ".join(_ZW.sub("", str(desc or "")).split())
    return re.sub(r"\s*\bShow (?:more|less)\b", "", d)   # LinkedIn scrape artifact


def _company_blurb(desc, company="", anchored_only=False):
    """Extract a short 'what the company does' phrase from a JD, or ''.

    Prefer a phrase anchored on the company NAME ("<Company> is/builds/provides …") — that
    can't accidentally grab role text ("… is looking for a Data Analyst"), and it catches
    the article-less forms the generic pattern misses ("Blockaid is redefining trust …").
    With `anchored_only` the unanchored "X is a …" fallback is skipped: in an agency's
    posting that sentence describes the CLIENT ("Our client, Fireblocks, is a …")."""
    d = _LABEL_PREFIX.sub("", _clean_desc(desc)).lstrip(" •")
    if company:
        anchored = re.search(
            re.escape(company)
            + r"[^.•]{0,40}?\b(?:is|are|builds?|provides?|offers?|powers?|helps?|enables?|"
            r"delivers?|develops?|creates?|makes?)\s+"
            r"(?!seeking|looking|hiring|searching|recruiting|excited|thrilled|proud|now\b)"
            r"(?:(?:a|an|the)\s+)?(.{6,110}?)[.•\n;]",
            d[:400], re.I)
        if anchored:
            words = anchored.group(1).strip().rstrip(".").split()
            stray = {"of", "to", "for", "and", "or", "with", "that", "which",
                     "by", "from", "as", "but", "nor"}
            if len(words) >= 3 and words[0].lower() not in stray:
                return " ".join(words[:16])
    if anchored_only:
        return ""
    m = _COMPANY_IS.search(d[:220])
    if not m:
        return ""
    words = m.group(1).strip().rstrip(".").split()
    return " ".join(words[:12])


# hard requirement headers — the practical "what you need" section. Tried first, earliest
# wins. NOTE: "we're looking for" is deliberately NOT here — it usually opens a company
# intro ("We are looking for a <role> to join…"), not a qualifications list.
_REQ_HARD = re.compile(r"(requirements?|qualifications?|what (?:you.?ll|you will) (?:bring|need)|"
                        r"what are we looking for|what we.?re looking for|what we expect|"
                        r"(?:perfect|ideal) job for someone who (?:has|is)|"
                        r"to thrive in this role,? you.?ll need|what you need to succeed|"
                        r"דרישות(?: התפקיד)?|מה אנחנו מחפשים|כישורים נדרשים|"
                        r"what (?:will make|makes) you successful|who you are|about you|"
                        r"what we.?re looking for in you|must[- ]have|your (?:profile|experience|"
                        r"background)|minimum qualifications|desired (?:skills|qualifications)|"
                        r"skills (?:&|and) (?:experience|qualifications)|you(?:'?ll)? (?:have|bring))"
                        r"\s*:?", re.I)
_REQ_SOFT = re.compile(r"(ideal candidate|what you.?ll do|what you.?ll own)\s*:?", re.I)
# a new JD section starting = stop the requirements segment there
# NOTE: "advantage"/"bonus"/"nice to have" are deliberately NOT section terminators —
# they appear INLINE in bullets ("Vertica knowledge – strong advantage") and as the
# nice-to-have SUB-list we want to keep (badged as plus via _PLUS_SECTION below).
_SECTION_END = re.compile(r"(?:•\s*)?\b(responsibilit|benefits?|perks|about (?:us|the company)|"
                           r"why join|what we offer|"
                           r"we offer|our (?:stack|tech)|equal opportunit|why you.?ll love|"
                           r"what makes\b|please (?:ensure|note)|founded in \d{4}|"
                           r"היקף משרה|אנחנו על המפה|קו\"ח|שעות עבודה|רמת ותק|סוג תעסוקה|send your cv)\b\s*:?", re.I)
# a nice-to-have SUB-header inside the requirements section: everything after it is
# still shown, but badged "plus" — never dropped, never presented as required
_PLUS_SECTION = re.compile(r"(?:•\s*)?\b(?:advantages?|nice[- ]to[- ]haves?|"
                            r"bonus(?: points)?(?: if you have)?|it would be (?:great|a plus)|"
                            r"preferred qualifications|יתרון(?: משמעותי)? אם)\b\s*:", re.I)
# leaked section-header words to strip from the front of a bullet
_LEAD_JUNK = re.compile(r"^(responsibilities|requirements?|qualifications?|the role|"
                         r"about the role|role description|what you.?ll (?:need|bring|do|own))"
                         r"\s*:?\s*", re.I)
# a bullet that is ONLY a category header (e.g. "Experience & Technical Skills") — drop it
_HEADER_ONLY = re.compile(r"^(experience|technical skills?|education|skills?|qualifications?|"
                           r"requirements?|nice to have|advantages?|bonus(?: points)?|"
                           r"(?:key|main|job|core|your|primary) responsibilities|"
                           r"about you|background|responsibilities|"
                           r"what we(?:'re| are)? ?(?:expect|need|want|require|value|look\w*)|"
                           r"what you.?ll (?:need|do|bring|own|be doing)|technical|professional)"
                           r"(?:\s*(?:&|and|/|,)\s*(?:experience|technical|skills?|education|"
                           r"qualifications?|requirements?|background))*\s*:?$", re.I)
# fallback splitter (no • markers survived): sentences / dashed clauses
_SENT_SPLIT = re.compile(r"(?<=[a-z0-9%)א-ת])\.\s+(?=[A-Z0-9א-ת])|\s[–—]\s(?=[A-Z0-9])")
# scraped requirement lists often lose their bullets entirely ("...related field 3+ years
# of experience Strong SQL skills"); split a long run-on before words that typically open
# a fresh requirement (English capitalized openers / Hebrew openers)
_RUNON_SPLIT = re.compile(
    r"(?<=[a-zא-ת)%\.])(?<!Fluent)(?<!fluent)(?<!Native)(?<!native)(?<!Excellent)(?<!excellent)"
    r"(?<!Good)(?<!good)(?<!Strong)(?<!strong)"
    r" (?=(?:\d+\+? years?|Strong|Proven|Excellent|Experience|Experienced|"
    r"Knowledge|Familiarity|Ability|Proficien\w*|Fluent|High(?: proficiency| level)|Advanced|"
    r"Deep|Solid|Hands[- ]on|Degree|B\.?Sc|M\.?Sc|Bachelor|Master|Team player|Self[- ]|"
    r"Willingness|Availability|English|Hebrew|Excellent|Very|Good|Great|"
    r"At least|Minimum(?: of)?|Fluency|Fluent|"
    r"ניסיון|תואר|ידע|יכולת|שליטה|אנגלית|היכרות|נכונות)\b)")
# a requirement's own must/nice-to-have marker, at the end of the bullet
_REQ_MUST = re.compile(r"[\s\-–—(:]*(?:a\s+)?(?:must(?:\s+have)?|mandatory|requir\w*|חובה)[.!)]?\s*$", re.I)
_REQ_PLUS = re.compile(r"[\s\-–—(:]*(?:an?\s+)?(?:(?:big|strong|significant|major|huge|"
                        r"added|great|definite)\s+)?(?:advantage|plus|nice to have|preferred|"
                        r"bonus|יתרון(?: משמעותי)?)[.!)]?\s*$", re.I)


# scraped lists also glue requirements with " - Hands on…" separators; split before a
# capitalized opener but never right before a bare must/advantage marker
_DASH_SPLIT = re.compile(r"\s+-\s+(?=[A-Z])(?!(?:Must|Mandatory|Requir|Advantage|Plus|Big|Nice|An?\b))")
# never render as a requirement: recruiter hashtags, links, résumé notes, culture blurbs
_BULLET_JUNK = re.compile(r"^#|https?://|www\.|#li-|\brésumé\b|resume(?:/cv)? you attach|"
                          r"send (?:your|us your) cv|\S+@\S+\.[a-z]{2,}|[📍📩🏠]|רמת ותק|סוג תעסוקה|"
                           r"why you.?ll love|equal opportunit|privacy policy|"
                           r"apply now|click here|meet 100% of|not about checklists|"
                           r"encourage you to apply|describes you perfectly", re.I)


_LEAD_MUST = re.compile(r"^\s*(?:must(?:[- ]haves?)?|mandatory|חובה)(?:\s*[-–—:]+\s*|\s+(?=[A-Zא-ת]))", re.I)
_LEAD_PLUS = re.compile(r"^\s*(?:advantage|nice to have|bonus|יתרון)\s*[-–—:]+\s*", re.I)


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


_REQ_SIGNAL = re.compile(
    r"\b(experience|years?|degree|proficien|knowledge|ability|familiar|proven|strong|expert|"
    r"hands[- ]on|sql|python|excel|tableau|looker|power ?bi|bachelor|master|fluent|"
    r"understanding|background|skilled|passion|track record|mindset)\b", re.I)


def _looks_like_header(c):
    """A short, all-capitalized fragment with no requirement signal is a decorative section
    header a company used to title its list (e.g. 'Your Chain of Strengths') — not a bullet."""
    words = c.split()
    if len(words) > 5 or re.search(r"\d", c) or _REQ_SIGNAL.search(c):
        return False
    caps = sum(1 for w in words if w[:1].isupper())
    # a two-word fragment that IS a skill or a soft skill ("Team player") is a bullet, not a
    # header; "At least" / "You have" (split leftovers) and "Product analytics" still are
    if len(words) == 2 and (_is_skill_name(c) or any(rx.search(c) for _, _, rx in _soft_skills())):
        return False
    return len(words) >= 2 and caps >= len(words) - 1


# a fragment opening with an imperative verb is a RESPONSIBILITY, not a requirement —
# used to reject header matches that were really a mid-sentence "…ad-hoc requirements"
_RESP_VERB = re.compile(r"^(develop|create|perform|build|design|lead|manage|work|partner|"
                         r"collaborate|own|drive|support|monitor|analy[sz]e|define|deliver|"
                         r"maintain|conduct|translate|identify|provide|present|research|"
                         r"optimi[sz]e|execute|prepare|implement|serve|gather|track|run)\b", re.I)


# an equal-opportunity footer ("…without regard to race…") also says "requirements" and
# "qualifications"; a header whose following text is that footer anchors nothing
_EEO = re.compile(r"equal opportunit|regardless of|without regard|protected (?:class|status|"
                  r"characteristic|veteran)|discriminat|affirmative action", re.I)


def _req_header_match(d2):
    """First _REQ_HARD match that anchors a real requirements SECTION: the text right
    after it must not open with a responsibility verb (which means the 'header' was a
    mid-sentence word like '…ad-hoc requirements Develop dashboards…') and must not be
    the equal-opportunity footer."""
    cands = list(_REQ_HARD.finditer(d2))[:5]
    for m in cands:
        head = d2[m.end():m.end() + 160].strip(" ?:-–—•")
        first = _clean_bullet(head.split("•")[0])
        if first and not _RESP_VERB.match(first) and not _EEO.search(head.split("•")[0]):
            return m
    rest = [m for m in cands if not _EEO.search(d2[m.end():m.end() + 160].split("•")[0])]
    return (rest[0] if rest else None) or _REQ_SOFT.search(d2)


_PLUS_HEADER_ONLY = re.compile(r"^(?:advantages?|nice[- ]to[- ]haves?|bonus(?: points)?"
                                r"(?: if you have)?|preferred qualifications|יתרונות)\s*:?$", re.I)


def _is_skill_name(c):
    """The whole fragment names one tool in the lexicon (`roleprofile.SKILLS`)."""
    from . import roleprofile
    return any(rx.fullmatch(c) for _, _, rx in roleprofile.SKILLS)


def _soft_skills():
    from . import roleprofile
    return roleprofile.SOFT_SKILLS


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
        # a one-word requirement ("Python", "Excel") is real when it IS a lexicon skill — the
        # 8-char floor was dropping it as junk (a split leftover like "Fluent" still goes)
        if not (8 <= len(c) <= 220 or (3 <= len(c) < 8 and _is_skill_name(c)))                 or _HEADER_ONLY.match(c) or _looks_like_header(c):
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


_RESP_HEAD = re.compile(r"(responsibilit(?:ies|y)|what (?:you|you'?ll) (?:do|be doing|own|work on)|"
                         r"your (?:role|impact|day[- ]to[- ]day)|in this role,? you|role overview|"
                         r"day[- ]to[- ]day|you will be|as part of (?:the|this) role|"
                         r"תחומי אחריות|מה תעשו|היומיום של)\s*:?", re.I)
# responsibilities lists glue the same way requirement lists do — split before an
# imperative opener when the bullets got lost in scraping
_RUNON_RESP = re.compile(
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

def _seniority_chip(desc):
    m = _EXP_LEVEL.search(desc or "")
    if m:
        return m.group(1).strip().rstrip(".")
    y = _YEARS.search(desc or "")
    return f"{y.group(1)}+ yrs" if y else ""


# --------------------------------------------------------------------------- #
# location: one display label per place, every spelling the boards use
# --------------------------------------------------------------------------- #
# (label, aliases). Aliases are matched case-insensitively with hyphen/space folded; the
# Hebrew forms are the ones `pipeline/israel.py` recognises, so a Hebrew careers page's
# city renders beside its English twin. A test pins that every token israel.py knows
# resolves here (a place it recognises but this table cannot label is a display bug).
_LOC_GROUPS = [
    ("Tel Aviv", ["tel aviv", "telaviv", "tel aviv-yafo", "tel aviv-jaffa", "tel aviv yafo", "tlv",
                  "תל אביב", "תל אביב-יפו", "יפו", "jaffa", "ramat hahayal", "ramat ha'hayal", "רמת החייל"]),
    ("Jerusalem", ["jerusalem", "ירושלים"]),
    ("Haifa", ["haifa", "חיפה"]),
    ("Herzliya", ["herzliya", "herzelia", "herzeliya", "hertzeliya", "hertzliya", "herzliyya",
                  "herzliya pituach", "הרצליה", "הרצליה פיתוח"]),
    ("Ra'anana", ["ra'anana", "raanana", "ra anana", "רעננה"]),
    ("Netanya", ["netanya", "nathania", "נתניה", "עיר הימים"]),
    ("Ramat Gan", ["ramat gan", "רמת גן"]),
    ("Petah Tikva", ["petah tikva", "petach tikva", "petah tiqwa", "petah tiqva", "פתח תקווה", "פתח תקוה"]),
    ("Be'er Sheva", ["beer sheva", "be'er sheva", "beersheba", "beersheva", "באר שבע"]),
    ("Yokneam", ["yokneam", "yoqneam", "יקנעם", "יקנעם עילית"]),
    ("Caesarea", ["caesarea", "qesarya", "קיסריה"]),
    ("Kiryat Gat", ["kiryat gat", "qiryat gat", "קרית גת", "קריית גת"]),
    ("Kiryat Ono", ["kiryat ono", "qiryat ono", "קרית אונו", "קריית אונו"]),
    ("Kiryat Motzkin", ["kiryat motzkin", "קרית מוצקין"]),
    ("Kiryat Shmona", ["kiryat shmona", "קרית שמונה"]),
    ("Kiryat Bialik", ["kiryat bialik"]),
    ("Kiryat Yam", ["kiryat yam"]),
    ("Kiryat Tivon", ["kiryat tivon"]),
    ("Rehovot", ["rehovot", "rechovot", "רחובות"]),
    ("Hod HaSharon", ["hod hasharon", "hod ha'sharon", "הוד השרון"]),
    ("Or Yehuda", ["or yehuda", "אור יהודה"]),
    ("Airport City", ["airport city", "קרית שדה התעופה"]),
    ("Modi'in", ["modiin", "modi'in", "modiin-maccabim-reut", "מודיעין", "מודיעין-מכבים-רעות"]),
    ("Ness Ziona", ["ness ziona", "nes ziona", "nes tziona", "נס ציונה"]),
    ("Rishon LeZion", ["rishon lezion", "rishon le zion", "rishon letsiyon", "ראשון לציון"]),
    ("Kfar Saba", ["kfar saba", "kfar sava", "כפר סבא"]),
    ("Tirat Carmel", ["tirat carmel", "tirat hakarmel", "טירת כרמל"]),
    ("Givatayim", ["givatayim", "גבעתיים"]),
    ("Holon", ["holon", "חולון"]),
    ("Rosh HaAyin", ["rosh haayin", "rosh ha'ayin", "rosh ha ayin", "afek", "ראש העין"]),
    ("Karmiel", ["karmiel", "carmiel", "כרמיאל"]),
    ("Migdal HaEmek", ["migdal haemek", "migdal ha'emek", "מגדל העמק"]),
    ("Yakum", ["yakum"]),
    ("Bnei Brak", ["bnei brak", "bene beraq", "בני ברק"]),
    ("Lod", ["lod", "לוד"]),
    ("Ashdod", ["ashdod", "אשדוד"]),
    ("Ashkelon", ["ashkelon", "אשקלון"]),
    ("Sderot", ["sderot", "שדרות"]),
    ("Nazareth", ["nazareth", "נצרת"]),
    ("Nof HaGalil", ["nazareth illit", "nof hagalil", "נוף הגליל"]),
    ("Even Yehuda", ["even yehuda", "אבן יהודה"]),
    ("Azor", ["azor", "אזור"]),
    ("Yavne", ["yavne", "yavneh", "יבנה"]),
    ("Afula", ["afula", "עפולה"]),
    ("Tiberias", ["tiberias", "טבריה"]),
    ("Eilat", ["eilat", "אילת"]),
    ("Dimona", ["dimona", "דימונה"]),
    ("Safed", ["safed", "tzfat", "צפת"]),
    ("Akko", ["akko", "עכו"]),
    ("Nahariya", ["nahariya", "נהריה"]),
    ("Yehud", ["yehud"]),
    ("Beit Shemesh", ["beit shemesh", "bet shemesh"]),
    ("Rosh Pina", ["rosh pina"]),
    ("Zichron Yaakov", ["zichron yaakov", "zikhron yaakov"]),
    ("Gedera", ["gedera"]),
    ("Netivot", ["netivot"]),
    ("Ofakim", ["ofakim"]),
    ("Nesher", ["nesher"]),
    ("Binyamina", ["binyamina"]),
    ("Pardes Hanna", ["pardes hanna"]),
]
# a district or region is a label only when no city is named
_LOC_REGIONS = [
    ("Central Israel", ["center district", "central district", "hamerkaz", "מחוז המרכז", "center", "central", "שפלת יהודה"]),
    ("Tel Aviv area", ["tel aviv district", "מחוז תל אביב", "gush dan", "גוש דן"]),
    ("Haifa area", ["haifa district", "מחוז חיפה"]),
    ("Northern Israel", ["northern district", "north district", "מחוז הצפון", "north"]),
    ("Southern Israel", ["southern district", "south district", "מחוז הדרום", "south"]),
    ("Jerusalem area", ["jerusalem district", "מחוז ירושלים"]),
    ("Sharon area", ["hasharon", "השרון", "sharon"]),
]
# words that say nothing about WHERE
_LOC_NOISE = {"il", "israel", "isr", "ישראל", "on site", "on-site", "onsite", "office", "remote",
              "hybrid", "full time", "full-time", "part time", "part-time", "n/a", "tbd", "location"}


def _lkey(s):
    """Fold a place spelling: lower, one space, hyphen and space interchangeable."""
    s = " ".join(str(s or "").lower().replace("_", " ").split())
    return re.sub(r"\s*-\s*", "-", s)


def _loc_index(groups):
    idx = {}
    for label, aliases in groups:
        for al in aliases:
            k = _lkey(al)
            idx[k] = label
            idx[k.replace("-", " ")] = label
            idx[k.replace(" ", "-")] = label
    return idx


_LOC_CITY = _loc_index(_LOC_GROUPS)
_LOC_REGION = _loc_index(_LOC_REGIONS)
# longest alias first, so "kiryat gat" wins over "gat"-like prefixes inside a glued string
_LOC_SUBSTR = sorted(_LOC_CITY, key=len, reverse=True)
_LOC_SPLIT = re.compile(r"\s[-/|·•]\s|,|\s\(|\)")


def _norm_location(loc):
    """One display label for a posting's location string, whatever the board did to it:
    'Tel Aviv-Yafo, Tel Aviv District, IL' → 'Tel Aviv'; 'On Site - Kiryat Gat, Israel' →
    'Kiryat Gat'; 'Senior BI Analyst Tel Aviv - Israel' (the scraper glued the title on) →
    'Tel Aviv'; 'ראשון לציון, מחוז המרכז' → 'Rishon LeZion'; 'Center District, Israel' →
    'Central Israel'; 'Tel Aviv District, Israel' → 'Tel Aviv area'; an unknown town keeps its own spelling; nothing → 'Israel (unspecified)'."""
    raw = " ".join(str(loc or "")[:200].split())
    parts = [p.strip(" .") for p in _LOC_SPLIT.split(raw) if p and p.strip(" .")]
    keys = [_lkey(p) for p in parts]
    for k in keys:                                   # 1. a part IS a city
        if k in _LOC_CITY:
            return _LOC_CITY[k]
    for k in keys:                                   # 2. a region, when no part is a city
        if k in _LOC_REGION:
            return _LOC_REGION[k]
    whole = _lkey(raw)
    for al in _LOC_SUBSTR:                           # 3. a city glued inside a string
        if len(al) >= 4 and re.search(r"(?<![a-zא-ת])" + re.escape(al) + r"(?![a-zא-ת])", whole):
            return _LOC_CITY[al]
    for p, k in zip(parts, keys):                    # 4. an unknown town, as written
        if k not in _LOC_NOISE and not any(k.startswith(n + " ") or k.endswith(" " + n) for n in ("on site", "office")) \
                and len(k) > 1 and not k.isdigit():
            return p[:60]
    return "Israel (unspecified)"


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


def _title_key(title):
    """One normalised form of a title, for 'the same role under two names'."""
    return " ".join(re.sub(r"[^0-9a-z\u05d0-\u05ea]+", " ", str(title or "").lower()).split())


def _display_company(name):
    """Short display name for the table cell: keep the brand, drop taglines and
    legal suffixes ('Oak - Identity Security OS' -> 'Oak'). Full name stays in the
    tooltip, the expanded card, and the search blob."""
    n = str(name or "")
    n = re.split(r"\s+[-–—|]\s+", n)[0]
    n = re.sub(r"\s+(?:ltd\.?|inc\.?|בע\"מ)$", "", n, flags=re.I)
    n = re.sub(r"\s+(?:technologies|media group|group)$", "", n, flags=re.I)
    return n.strip() or name
