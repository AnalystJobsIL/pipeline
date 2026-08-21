"""Relevance + experience classification for analytics roles.

Target (per the user's refined spec):
  * The role's core is DATA ANALYSIS / an analytic mindset — producing insights,
    reports, dashboards, business/product metrics. **The title does not matter**: a
    role called "Data Scientist" counts if it is really product/business analytics
    (e.g. experimentation / A-B testing, as many DS roles at Meta/Google are).
  * It is NOT an ML / modelling / data-engineering / software role. Anything whose core
    requirement is machine learning, model building, pipelines, or software eng is out.
  * It requires roughly **3+ years** of experience (no juniors/interns/entry-level).

Design: a cheap deterministic keyword layer removes the obviously-irrelevant and
fast-accepts the unambiguous senior-analyst titles; everything with an analytics signal
that the keywords can't resolve confidently goes to the `claude -p` LLM, which reads the
job description and judges the three conditions above. Every decision records its path
(`keyword` / `llm` / `llm_cache` / `llm_failed_fallback`) so the digest stays auditable.
LLM verdicts are cached by title.
"""
from __future__ import annotations

import re
import subprocess

# --------------------------------------------------------------------------- #
# keyword layer
# --------------------------------------------------------------------------- #

# Hard-exclude: engineering / ML / infra roles and non-data "<x> analyst" roles.
# These are rejected deterministically (no LLM) even if a data word appears.
_HARD_EXCLUDE = re.compile(
    r"\b("
    # engineering / infra / software
    r"software|backend|back-end|frontend|front-end|full ?stack|web developer|"
    r"data engineer|data engineering|analytics engineer|platform engineer|"
    r"devops|dev ops|sre|site reliability|infrastructure|embedded|firmware|"
    r"qa engineer|automation engineer|security engineer|solutions? engineer|"
    r"sales engineer|support engineer|hardware|elect(ronic|rical)|mechanical|"
    # explicit ML / research-modelling
    r"machine learning|deep learning|\bml\b|mlops|ml ops|\bnlp\b|computer vision|"
    r"algorithm(s)? engineer|algo engineer|"
    # non-data "<x> analyst" families
    r"security analyst|soc analyst|infosec analyst|information security analyst|"
    r"compliance analyst|governance analyst|"
    r"financial analyst|finance analyst|credit analyst|investment analyst|"
    r"equity analyst|budget analyst|treasury analyst|actuarial analyst|billing analyst|"
    r"qa analyst|quality assurance analyst|test analyst|"
    r"systems? analyst|it analyst|network analyst|application analyst|"
    r"support analyst|service desk analyst|help ?desk analyst|desktop analyst"
    r")\b",
    re.I,
)
_HARD_EXCLUDE_MISC = re.compile(r"\b(fp&a|actuary)\b", re.I)

# STRONG analyst-role titles. If one of these appears WITH a senior marker, we accept on
# the keyword alone (a senior/lead/principal analyst reliably means 3+ years).
_STRONG = re.compile(
    r"("
    r"\bdata analyst|\bbusiness analyst|\bb\.?i\.? analyst|business intelligence|"
    r"\bbi (developer|lead|manager|analyst)|"
    r"analytics (manager|team ?lead|lead|director)|"
    r"(head|director|vp|vice president) of analytics|"
    r"\bproduct analyst|\bmarketing analyst|\bgrowth analyst|\breporting analyst|"
    r"\binsight?s analyst|customer insights|\bweb analyst|\bdigital analyst|"
    r"\bdata analytics|"
    # analytics-flavored Data Scientist (Meta/Google style) — explicitly IN per the spec;
    # the analytics qualifier in the TITLE itself makes it deterministic (no LLM needed)
    r"data scientist,?\s+(product\s+)?analytics|"
    r"(product|decision|marketing|growth|business)\s+(data\s+)?scientist|"
    r"data scientist,?\s+(product|marketing|growth|business|insights?)\b"
    r")",
    re.I,
)

# Any analytics/data-insight signal that means "plausibly relevant -> let the LLM judge".
# Deliberately broad and title-agnostic (includes "scientist"/"data science").
_SIGNAL = re.compile(
    r"("
    r"\banalyst\b|analytics|business intelligence|\bbi\b|insight|"
    r"data scien|data scientist|decision scien|scientist|"
    r"reporting|\bmetrics\b|statistician|econometr|\bquant\b|quantitative"
    r")",
    re.I,
)

# Hebrew analytics signal + seniority markers (Israeli careers sites post in Hebrew too)
_HEBREW_SIGNAL = re.compile("אנליסט|אנליטיקה|"
                           "נתונים|בינה עסקית|דאטה")
_HEBREW_SENIOR = re.compile("בכיר|ראש צות|מוביל")

# When a *title* is only a SIGNAL (not STRONG) — e.g. a bare "Senior Data Scientist" —
# the description decides. A description dominated by ML/model-building with no analytics
# counter-signal is an ML role and must be rejected even in no-LLM/fallback mode (the spec
# excludes ML). Used ONLY to veto signal-tier acceptances; STRONG titles are never vetoed.
_DESC_ML = re.compile(
    r"\b(machine learning|deep learning|\bml\b|mlops|\bnlp\b|computer vision|"
    r"neural network|\bllms?\b|large language model|generative ai|reinforcement learning|"
    r"model (training|development|building|deployment)|train(ing)? (models?|deep|neural)|"
    r"pytorch|tensorflow|hugging ?face|transformer model|"
    # academic / applied ML the plain terms miss
    r"data science projects?|scientific reasoning|\bpymc\b|bayesian|xgboost|scikit|keras|"
    r"recommendation (system|engine)|real[- ]time bidding|feature engineering|"
    r"predictive model|statistical model(l?ing)?|ml algorithms?|research scientist)\b", re.I)
_DESC_ANALYTICS = re.compile(
    r"\b(dashboard|a/b test|a-b test|experiment|business metrics|\bkpis?\b|"
    r"stakeholder|reporting|report\b|tableau|looker|power ?bi|\bbi\b|product analytics|"
    r"business intelligence|data visuali|ad[\s-]?hoc|\bsql\b|\binsights?\b|"
    r"business questions?|self[- ]serve|decision[- ]making|analytic|analyz|querying)\b", re.I)
# where the ROLE-specific text begins — skips the company-boilerplate intro (at AI companies
# it's full of "AI-powered" noise that isn't about the job).
_ROLE_START = re.compile(
    r"\b(about the role|the role\b|responsibilit|what you'?ll|what we'?re looking|"
    r"requirements?|qualifications?|as an? |in this role|you'?ll |your role|day[- ]to[- ]day|"
    r"we'?re looking for a|what you.?ll do|what you.?ll own)", re.I)
# the requirements section header — the distilled "what you need", the cleanest ML/analytics tell
_REQ_HEADER = re.compile(
    r"\b(requirements?|qualifications?|what you'?ll (?:need|bring)|must[- ]have|"
    r"your (?:profile|experience|background)|who you are|about you|desired skills)\b\s*:?", re.I)


def _desc_is_ml(desc):
    """True when the ROLE is core ML/modelling. Measured on the REQUIREMENTS section (the
    distilled 'what you need') when present, else the role portion — never the company intro,
    so an AI company's boilerplate doesn't mislabel a real analyst. ML must DOMINATE analytics
    (the main thing), so 'some ML as a bonus' in an analyst role still passes."""
    d = desc or ""
    if not d:
        return False
    rs = _ROLE_START.search(d)
    text = d[rs.start():] if rs else d         # the role, minus the company-intro boilerplate
    ml = len(_DESC_ML.findall(text))
    an = len(_DESC_ANALYTICS.findall(text))
    return (ml >= 2 and an == 0) or (ml >= 2 and ml > an)


# A signal-tier title (e.g. a bare "Scientist") is only trustworthy in no-LLM mode when it
# actually anchors on data/analytics — otherwise "Senior Scientist, Antibody Discovery" or
# "Applied Scientist, Personalization" (a wet-lab / ML role) sneaks in on the word "scientist".
_DATA_ANCHOR = re.compile(
    r"\b(data|analyt|business intelligence|\bbi\b|insight|reporting|metrics?|"
    r"statistic|econometr|\bquant\b)\b", re.I)


# a "Data Scientist / Data Science X" title with NO analytics qualifier ("… Product Analytics",
# "Business Data Scientist") defaults to ML — the spec keeps it only when it's REALLY analytics.
_BARE_DS = re.compile(r"\bdata scien(?:ce|tist)\b", re.I)
_DS_ANALYTICS_QUALIFIER = re.compile(
    r"analyt|\banalyst\b|insight|business intelligence|\bbi\b|reporting|"
    r"marketing|growth|decision|product", re.I)


def _sig_accept_nollm(rel, sen, title_l, desc):
    """Should a signal-tier (non-strong) title be accepted without the LLM? Yes only when it
    is senior, not a core-ML description, AND anchored on data/analytics. A bare 'Data Scientist'
    (no analytics qualifier in the title) must show POSITIVE analytics evidence in its
    description — never the word 'data' in the title alone — so an ML DS with a thin/empty
    description doesn't slip through on its title."""
    if rel != "signal" or sen != "senior":
        return False
    if _desc_is_ml(desc):
        return False
    if _BARE_DS.search(title_l) and not _DS_ANALYTICS_QUALIFIER.search(title_l):
        return bool(_DESC_ANALYTICS.search(desc or ""))
    return bool(_DATA_ANCHOR.search(title_l) or _DESC_ANALYTICS.search(desc or ""))


_SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|vp|vice president|"
    r"chief|expert|manager)\b",
    re.I,
)
_JUNIOR = re.compile(
    r"\b(junior|jr\.?|intern|internship|student|trainee|apprentice|graduate|"
    r"entry[- ]?level|working student|campus|early[- ]?career)\b",
    re.I,
)


def _seniority(title_l):
    senior = bool(_SENIOR.search(title_l)) or bool(_HEBREW_SENIOR.search(title_l))
    junior = bool(_JUNIOR.search(title_l))
    if junior and not senior:
        return "junior"
    if senior:
        return "senior"
    return "unknown"


def _relevance(title_l):
    """strong-accept | signal (->LLM) | none, plus hard-exclude short-circuit."""
    strong = bool(_STRONG.search(title_l))
    if _HARD_EXCLUDE.search(title_l) or _HARD_EXCLUDE_MISC.search(title_l):
        # A STRONG analytics title beats a stray generic domain word — "Business Analyst,
        # Software Solutions" / "Data Scientist, Infrastructure" are analytics roles, not
        # excludes. Send them to the LLM rather than deterministically rejecting. Real
        # "<x> engineer" / non-data "<x> analyst" titles (no STRONG match) still exclude.
        return "signal" if strong else "excluded"
    if strong:
        return "strong"
    if _SIGNAL.search(title_l) or _HEBREW_SIGNAL.search(title_l):
        return "signal"
    return "none"


# --------------------------------------------------------------------------- #
# LLM fallback
# --------------------------------------------------------------------------- #
_LLM_PROMPT = (
    "You screen job postings for an EXPERIENCED DATA ANALYST. Answer YES only if ALL "
    "three conditions hold; otherwise NO.\n\n"
    "(1) ANALYTIC ROLE — the core of the job is analyzing data to produce insights, "
    "reports, dashboards, and business/product metrics, requiring an analytic mindset. "
    "THE TITLE DOES NOT MATTER: a posting called 'Data Scientist' DOES count if the actual "
    "work is product/business analytics, experimentation, or A/B testing (as many DS roles "
    "at Meta/Google are). BI, business/product/marketing/growth analytics, and analytics "
    "leadership all count.\n"
    "(2) NOT ML / ENGINEERING — answer NO if the core requirement is machine learning or "
    "model development (building/training models), data engineering / pipelines, or software "
    "engineering. Merely collaborating with ML teams is fine if the person's own output is "
    "analysis. Also NO for finance/FP&A/accounting, security/SOC, sales, and pure product-"
    "management or architect roles.\n"
    "(3) EXPERIENCE — the role requires roughly 3+ years of relevant experience. Answer NO "
    "for junior, intern, student, entry-level, or ~0-2 year roles. If the description states "
    "years, use it; otherwise infer from seniority cues in the title and description.\n\n"
    "Answer EXACTLY one word: YES or NO.\n\n"
    "Job title: {title}\n"
    "Company: {company}\n"
    "Location: {location}\n"
    "Description (may be empty): {description}\n"
)


def _is_windows():
    import os
    return os.name == "nt"


def llm_is_relevant(job, timeout=90):
    """Call `claude -p` for one posting. Returns True/False, or None on failure."""
    # Strip HTML and skip the company-boilerplate intro (same _ROLE_START logic as the
    # deterministic path) BEFORE truncating — otherwise long intros eat the whole 1400-char
    # budget and Claude never sees the requirements, biasing verdicts to NO.
    desc = re.sub(r"<[^>]+>", " ", job.get("description") or "")
    desc = re.sub(r"\s+", " ", desc).strip()
    rs = _ROLE_START.search(desc)
    if rs:
        desc = desc[rs.start():]
    prompt = _LLM_PROMPT.format(
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        description=desc[:1400],
    )
    try:
        proc = subprocess.run(
            ["claude", "-p"], input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # descriptions carry BOM/Hebrew/curly quotes
            timeout=timeout, shell=_is_windows(),
        )
    except Exception:  # noqa: BLE001 - never let one posting crash the whole run
        return None
    out = (proc.stdout or "").strip().upper()
    if not out:
        return None
    m = re.search(r"\b(YES|NO)\b", out)
    return None if not m else (m.group(1) == "YES")


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def classify(job, *, use_llm=True, llm_cache=None):
    """Classify one normalized job.

    Returns {decision: accept|reject, path: keyword|llm|llm_cache|llm_failed_fallback|
             keyword_nollm, reason, relevance, seniority}.
    """
    title_l = (job.get("title") or "").lower()
    rel = _relevance(title_l)
    sen = _seniority(title_l)
    base = {"relevance": rel, "seniority": sen}

    if rel == "excluded":
        return {**base, "decision": "reject", "path": "keyword",
                "reason": "engineering/ML/non-data-analyst title"}
    if rel == "none":
        return {**base, "decision": "reject", "path": "keyword",
                "reason": "no analytics signal in title"}
    if sen == "junior":
        return {**base, "decision": "reject", "path": "keyword",
                "reason": "junior/intern/entry-level (needs 3+ yrs)"}
    if rel == "strong" and sen == "senior":
        return {**base, "decision": "accept", "path": "keyword",
                "reason": "senior analyst title (>=3 yrs implied)"}

    # Everything else with an analytics signal is ambiguous on relevance and/or the 3+yr
    # bar -> the LLM reads the description and judges (title-agnostic).
    if not use_llm:
        # Deterministic-only mode (e.g. cloud run w/o Claude): accept a strong analyst
        # title, otherwise a senior signal title UNLESS its description is core-ML.
        sig_ok = _sig_accept_nollm(rel, sen, title_l, job.get("description"))
        decision = "accept" if (rel == "strong" or sig_ok) else "reject"
        reason = ("ML/non-data description vetoed a bare senior-scientist title"
                  if rel == "signal" and sen == "senior" and not sig_ok
                  else "no-LLM mode; strong/data-anchored-senior-signal->accept else reject")
        return {**base, "decision": decision, "path": "keyword_nollm", "reason": reason}

    # keyed per company: the same title can be analytics at Meta and pure-ML elsewhere
    key = f"{(job.get('company') or '').strip().lower()}|{title_l.strip()}"
    if llm_cache is not None and key in llm_cache:
        verdict = llm_cache[key]
        return {**base, "decision": "accept" if verdict else "reject",
                "path": "llm_cache", "reason": "cached LLM verdict"}

    verdict = llm_is_relevant(job)
    if verdict is None:
        sig_ok = _sig_accept_nollm(rel, sen, title_l, job.get("description"))
        decision = "accept" if (rel == "strong" or sig_ok) else "reject"
        return {**base, "decision": decision, "path": "llm_failed_fallback",
                "reason": "LLM failed; strong/data-anchored-senior-signal->accept else reject"}
    if llm_cache is not None:
        llm_cache[key] = verdict
    return {**base, "decision": "accept" if verdict else "reject",
            "path": "llm", "reason": "LLM verdict"}
