"""Deterministic per-job role profile: skills, role family, IC/lead track, years.

Extracted from title+description with a curated lexicon — no LLM, no network — so it
can run at render time on every board build. Powers the skill tags on each job card,
the Experience fact, filter-box matching on skill names, and the aggregated
"skills in demand" view.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# skill lexicon: canonical name -> (category, detection regex)
# Order matters only for display: listed roughly by how load-bearing the skill is.
# Patterns are matched case-insensitively against the whole title+JD text; every
# pattern must be word-bounded tightly enough to survive scraped run-together text.
# --------------------------------------------------------------------------- #
_S = [
    # querying & databases
    ("SQL",            "query",  r"\bsql\b"),
    ("Snowflake",      "query",  r"\bsnowflake\b"),
    ("BigQuery",       "query",  r"\bbig ?query\b"),
    ("Redshift",       "query",  r"\bredshift\b"),
    ("SQL Server",     "query",  r"\bsql server\b|\bt-?sql\b|\bms ?sql\b|\bssms\b"),
    ("PostgreSQL",     "query",  r"\bpostgre(?:s|sql)?\b"),
    ("MySQL",          "query",  r"\bmysql\b"),
    ("Oracle",         "query",  r"\boracle\b"),
    ("MongoDB",        "query",  r"\bmongo ?db\b"),
    ("Elasticsearch",  "query",  r"\belastic ?search\b"),
    ("Databricks",     "query",  r"\bdatabricks\b"),
    ("Spark",          "query",  r"\b(?:py)?spark\b"),
    # programming & analysis
    ("Python",         "prog",   r"\bpython\b"),
    ("R",              "prog",   r"(?<![\w&.+/-])R(?![\w&.+#-])(?=[\s,/;.)]|$)"),
    ("SAS",            "prog",   r"\bsas\b"),
    ("VBA",            "prog",   r"\bvba\b|\bexcel macros?\b|\bmacros\b"),
    ("Scala",          "prog",   r"\bscala\b"),
    ("Java",           "prog",   r"\bjava\b(?!script)"),
    ("MATLAB",         "prog",   r"\bmatlab\b"),
    # BI / visualization
    ("Excel",          "bi",     r"\bexcel\b(?!\s+(?:in|at|as)\b)|\bpivot tables?\b"),
    ("Tableau",        "bi",     r"\btableau\b"),
    ("Power BI",       "bi",     r"\bpower\s?-?\s?bi\b|\bdax\b|\bpower query\b"),
    ("Looker",         "bi",     r"\blooker\b(?! studio)"),
    ("Looker Studio",  "bi",     r"\blooker studio\b|\bdata studio\b"),
    ("Qlik",           "bi",     r"\bqlik(?:view| sense)?\b"),
    ("Sisense",        "bi",     r"\bsisense\b"),
    ("MicroStrategy",  "bi",     r"\bmicrostrategy\b"),
    ("OBIEE",          "bi",     r"\bobiee\b|\boracle bi\b"),
    ("SAP BO",         "bi",     r"\bsap (?:bo|business ?objects)\b"),
    ("Superset",       "bi",     r"\bsuperset\b"),
    ("Grafana",        "bi",     r"\bgrafana\b"),
    # product / marketing analytics stacks
    ("Google Analytics", "pa",   r"\bgoogle analytics\b|\bga4\b|\buniversal analytics\b"),
    ("Amplitude",      "pa",     r"\bamplitude\b"),
    ("Mixpanel",       "pa",     r"\bmixpanel\b"),
    ("Google Tag Manager", "pa", r"\bgoogle tag manager\b|\bgtm\b"),
    ("AppsFlyer/MMP",  "pa",     r"\bappsflyer\b|\badjust\b|\bmmp\b|\bmobile measurement\b"),
    ("Google Ads",     "pa",     r"\bgoogle ads\b|\badwords\b|\bppc\b|\bsem\b"),
    ("Meta Ads",       "pa",     r"\bfacebook ads\b|\bmeta ads\b"),
    ("SEO",            "pa",     r"\bseo\b"),
    ("CRM/Salesforce", "pa",     r"\bsalesforce\b|\bhubspot\b|\bcrm\b"),
    # data engineering
    ("ETL",            "de",     r"\betl\b|\belt\b"),
    ("dbt",            "de",     r"\bdbt\b"),
    ("Airflow",        "de",     r"\bair ?flow\b"),
    ("SSIS/SSAS",      "de",     r"\bssis\b|\bssas\b|\bssrs\b"),
    ("Data modeling",  "de",     r"\bdata model(?:ing|ling|s)?\b|\bdimensional model|\bstar schema\b"),
    ("Data warehouse", "de",     r"\bdata ?warehouse\b|\bdwh\b"),
    ("Kafka",          "de",     r"\bkafka\b"),
    # cloud
    ("AWS",            "cloud",  r"\baws\b|\bamazon web services\b"),
    ("GCP",            "cloud",  r"\bgcp\b|\bgoogle cloud\b"),
    ("Azure",          "cloud",  r"\bazure\b"),
    # statistics / methods
    ("A/B testing",    "method", r"\ba/?b[- ]test|\bexperimentation\b|\bsplit test"),
    ("Statistics",     "method", r"\bstatistic(?:s|al)\b|\bhypothesis test|\bregression\b"),
    ("Machine learning", "method", r"\bmachine[- ]learning\b|\bml models?\b|\bpredictive model"),
    ("Forecasting",    "method", r"\bforecast(?:ing|s)?\b"),
    ("Dashboards", "method", r"\bdata visuali[sz]|\bdashboards?\b"),
    # languages (the Israeli market cares)
    ("English",        "lang",   r"\benglish\b|\bאנגלית\b"),
]
SKILLS = [(name, cat, re.compile(pat, re.I)) for name, cat, pat in _S]

CATEGORY_LABELS = {"query": "Querying & databases", "prog": "Programming", "bi": "BI & visualization",
                   "pa": "Product / marketing analytics", "de": "Data engineering",
                   "cloud": "Cloud", "method": "Methods & statistics", "lang": "Languages"}

# --------------------------------------------------------------------------- #
# role family (title-first, JD fallback) and IC-vs-lead track
# --------------------------------------------------------------------------- #
_FAMILIES = [
    ("Product Analyst",   re.compile(r"product analyst|game analyst", re.I)),
    ("Marketing Analyst", re.compile(r"marketing analy|growth analyst|performance analyst|"
                                     r"campaign analyst|ppc|paid (?:media|search|social)|"
                                     r"monetization analyst|user acquisition", re.I)),
    ("BI & DWH",          re.compile(r"\bbi\b|business intelligence|dwh|data ?warehouse|"
                                     r"tableau|power ?bi|qlik|analytics engineer", re.I)),
    ("Data Engineering",  re.compile(r"data engineer|etl developer|big data (?:developer|engineer)", re.I)),
    ("Data Science",      re.compile(r"data scien|machine learning|algorithm|\bml\b|\bai\b", re.I)),
    ("Product Manager",   re.compile(r"product manager|product owner|\bpm\b(?! ?o)", re.I)),
    ("Business Analyst",  re.compile(r"business analyst|business data analyst|process analyst|"
                                     r"financial analyst|risk analyst|fraud analyst", re.I)),
    ("Data Analyst",      re.compile(r"data analyst|analytics|analyst", re.I)),
]

_LEAD = re.compile(r"\b(team ?lead|tech ?lead|group ?lead|lead\b|manager|head of|principal|"
                   r"staff|director|vp|vice president|chief)\b", re.I)

_YEARS_EXP = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?|שנות|שנים)\b", re.I)


def _clean(s):
    return " ".join(str(s or "").split())


def extract(title, desc):
    """Return {'skills': [(name, cat), ...], 'family': str, 'track': 'IC'|'Lead',
    'years': int|None} for one job. Pure text work; safe on empty input."""
    title = _clean(title)
    desc = _clean(desc)
    text = f"{title} {desc}"

    skills = [(name, cat) for name, cat, rx in SKILLS if rx.search(text)]

    family = "Other"
    for fam, rx in _FAMILIES:
        if rx.search(title):
            family = fam
            break
    else:
        for fam, rx in _FAMILIES:
            if rx.search(desc[:400]):
                family = fam
                break

    track = "Lead" if _LEAD.search(title) else "IC"

    years = None
    hits = [int(m.group(1)) for m in _YEARS_EXP.finditer(text) if 1 <= int(m.group(1)) <= 15]
    if hits:
        # a JD usually states the core ask first and nice-to-haves later; take the first
        # plausible mention, but prefer any value explicitly tied to "experience"
        exp_hits = [int(m.group(1)) for m in _YEARS_EXP.finditer(text)
                    if 1 <= int(m.group(1)) <= 15
                    and re.search(r"experience|ניסיון", text[max(0, m.start() - 60):m.end() + 30], re.I)]
        years = (exp_hits or hits)[0]

    return {"skills": skills, "family": family, "track": track, "years": years}


def aggregate(profiles):
    """Fold per-job profiles into board-level demand stats.

    Returns {'total': n, 'with_skills': n, 'top': [(skill, count)...],
             'by_family': {family: {'jobs': n, 'top': [(skill, count)...]}}}
    counted per job posting."""
    from collections import Counter, defaultdict
    total = len(profiles)
    top = Counter()
    fam_jobs = Counter()
    fam_skills = defaultdict(Counter)
    with_skills = 0
    for p in profiles:
        names = [n for n, _ in p["skills"]]
        if names:
            with_skills += 1
        top.update(names)
        fam = p["family"]
        fam_jobs[fam] += 1
        fam_skills[fam].update(names)
    by_family = {f: {"jobs": fam_jobs[f], "top": fam_skills[f].most_common(6)}
                 for f in fam_jobs}
    return {"total": total, "with_skills": with_skills,
            "top": top.most_common(18), "by_family": by_family}
