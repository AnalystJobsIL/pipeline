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
    ("Python",         "prog",   r"\bpython\b|פייתון"),
    ("R",              "prog",   r"(?<![\w&.+/-])R(?![\w&.+#-])(?=[\s,/;.)]|$)"),
    ("SAS",            "prog",   r"\bsas\b"),
    ("VBA",            "prog",   r"\bvba\b|\bexcel macros?\b|\bmacros\b"),
    ("Scala",          "prog",   r"\bscala\b"),
    ("Java",           "prog",   r"\bjava\b(?!script)"),
    ("MATLAB",         "prog",   r"\bmatlab\b"),
    # BI / visualization
    ("Excel",          "bi",     r"(?<![a-z])excel\b(?!\s+(?:in|at|as)\b)|\bpivot tables?\b|אקסל"),
    ("Tableau",        "bi",     r"(?<![a-z])tableau\b|טאבלו"),
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

# ---- non-overlapping skill clusters for the demand dashboard ----
CLUSTERS = [("sqldb", "SQL & Databases"), ("etl", "ETL & Infrastructure"),
            ("code", "Coding, ML & Statistics"), ("viz", "Visualization & BI"),
            ("domain", "Product & Marketing Analytics")]
_CAT2CLUSTER = {"query": "sqldb", "de": "etl", "cloud": "etl", "prog": "code",
                "bi": "viz", "method": "viz", "pa": "domain"}
# statistical-analysis methods live with coding & ML; only Dashboards stays visualization
_NAME_CLUSTER = {"Machine learning": "code", "Statistics": "code",
                 "A/B testing": "code", "Forecasting": "code"}


def cluster_of(name, cat):
    """Cluster key for one skill, or None (languages stay off the charts)."""
    return _NAME_CLUSTER.get(name) or _CAT2CLUSTER.get(cat)


# ---- day-to-day task groups, classified from the responsibilities bullets ----
# (label shown on the board, one-word token used for filtering/search)
TASK_GROUPS = [
    ("Dashboards & Reporting", "reporting",
     re.compile(r"dashboard|report|kpi|visuali[sz]|looker|tableau|power ?bi|scorecard|דוחות|דשבורד", re.I)),
    ("Analysis & Insights", "insights",
     re.compile(r"analy[sz]|insight|deep[- ]dive|trend|investigat|explor|research|segment|"
                r"root[- ]cause|opportunit|understand|ניתוח|תובנות", re.I)),
    ("Experiments & Models", "experiments",
     re.compile(r"a/?b[- ]test|experiment|model(?:ing|s)?\b|forecast|predict|machine[- ]learning|"
                r"statistical|hypothes|simulat|מודל", re.I)),
    ("Data & Pipelines", "pipelines",
     re.compile(r"pipeline|\betl\b|\belt\b|data model|warehouse|\bdbt\b|airflow|infrastructur|"
                r"automat|integrat|ingest|תשתית", re.I)),
    ("Stakeholders & Communication", "stakeholders",
     re.compile(r"stakeholder|present|communicat|partner|collaborat|cross[- ]functional|"
                r"business (?:teams|units|leaders)|advis|recommend|translate|work (?:closely|with)|"
                r"gather.{0,20}requirement|ממשק|הצגה", re.I)),
    ("Monitoring & Data Quality", "monitoring",
     re.compile(r"monitor|alert|anomal|data quality|\bqa\b|govern|validat|audit|accuracy|"
                r"consistency|בקרה", re.I)),
]


# one-line meanings shown as tooltips on tags and chart bars
SKILL_DESC = {
    "SQL": "The standard language for querying databases",
    "Snowflake": "Cloud data warehouse", "BigQuery": "Google's cloud data warehouse",
    "Redshift": "Amazon's cloud data warehouse", "SQL Server": "Microsoft's database (T-SQL)",
    "PostgreSQL": "Open-source relational database", "MySQL": "Open-source relational database",
    "Oracle": "Oracle relational database", "MongoDB": "NoSQL document database",
    "Elasticsearch": "Search & log analytics engine",
    "Databricks": "Data & AI platform built on Spark",
    "Spark": "Distributed engine for processing big data",
    "Python": "General-purpose language, the default for data work",
    "R": "Statistical programming language", "SAS": "Legacy statistical analysis suite",
    "VBA": "Excel macros & automation", "Scala": "JVM language, common around Spark",
    "Java": "General-purpose programming language", "MATLAB": "Numeric computing environment",
    "Excel": "Spreadsheets: pivot tables, advanced functions",
    "Tableau": "Dashboarding & visualization tool", "Power BI": "Microsoft's BI & dashboard tool",
    "Looker": "Google's BI platform (LookML)", "Looker Studio": "Free Google dashboard tool",
    "Qlik": "BI platform (QlikView / Qlik Sense)", "Sisense": "Embedded BI platform",
    "MicroStrategy": "Enterprise BI platform", "OBIEE": "Oracle's BI suite",
    "SAP BO": "SAP BusinessObjects BI suite", "Superset": "Open-source BI tool",
    "Grafana": "Dashboards for monitoring & metrics",
    "Google Analytics": "Web & app traffic measurement",
    "Amplitude": "Product event-analytics platform (user behavior)",
    "Mixpanel": "Product event-analytics platform (user behavior)",
    "Google Tag Manager": "Managing tracking tags without code",
    "AppsFlyer/MMP": "Mobile attribution & marketing measurement",
    "Google Ads": "Paid search & PPC advertising", "Meta Ads": "Facebook/Instagram advertising",
    "SEO": "Search-engine optimization", "CRM/Salesforce": "Customer-relationship systems",
    "ETL": "Moving & transforming data between systems (ETL/ELT)",
    "dbt": "SQL-based data-transformation framework",
    "Airflow": "Scheduling & orchestrating data pipelines",
    "SSIS/SSAS": "Microsoft's ETL & analysis-services stack",
    "Data modeling": "Designing warehouse schemas (star schema, dimensions)",
    "Data warehouse": "The central store for analytical data",
    "Kafka": "Real-time event streaming",
    "AWS": "Amazon's cloud", "GCP": "Google's cloud", "Azure": "Microsoft's cloud",
    "A/B testing": "Controlled experiments to compare variants",
    "Statistics": "Statistical analysis & hypothesis testing",
    "Machine learning": "Building predictive models",
    "Forecasting": "Projecting metrics & trends forward",
    "Dashboards": "Building dashboards & data visualizations",
    "English": "Working proficiency in English",
}

TASK_DESC = {
    "Dashboards & Reporting": "Building and maintaining dashboards, recurring reports and KPIs",
    "Analysis & Insights": "Ad-hoc analysis and deep dives that turn data into business insights",
    "Experiments & Models": "A/B tests, statistical models and forecasts",
    "Data & Pipelines": "Building or maintaining data pipelines, models and infrastructure",
    "Stakeholders & Communication": "Working with business teams: gathering needs, presenting findings",
    "Monitoring & Data Quality": "Watching metrics and anomalies, keeping the data trustworthy",
}


def classify_tasks(bullets):
    """Map responsibility bullets to the day-to-day TASK_GROUPS they cover.
    Returns [(label, token)] in TASK_GROUPS order — one entry per group matched."""
    text = " • ".join(bullets or [])
    return [(label, token) for label, token, rx in TASK_GROUPS if rx.search(text)]


# --------------------------------------------------------------------------- #
# AI usage: not IF a posting mentions AI, but WHAT the analyst is expected to
# do with it. Mentions of the COMPANY'S AI product (e.g. "analyze how our AI
# agents perform") are excluded — that is product analysis, not AI usage.
# --------------------------------------------------------------------------- #
_AI_HIT = re.compile(
    r"\bllms?\b|\bgen(?:erative)?\s?ai\b|\bgenai\b|\bai[- ]tools?\b|ai[- ]assisted|"
    r"chatgpt|copilot|\bclaude(?: code)?\b|prompt[- ]?engineer\w*|context engineering|"
    r"use of ai|leverag\w* (?:of )?ai\b|working with ai\b", re.I)
# the AI belongs to the company/product, not to the analyst's toolkit
_AI_PRODUCT = re.compile(
    r"\bour (?:\w+ ){0,3}ai\b|company'?s ai|\bai[- ](?:powered|driven|native|first)\b|"
    r"\bai (?:platform|product|solution|company|startup)|"
    r"\bai agents?\b(?=[^.]{0,70}(?:perform|platform|product|secur|protect|identit|endpoint))", re.I)
_AI_TOOLWORDS = re.compile(r"ai[- ]tools?|chatgpt|copilot|claude|cursor|ai[- ]assisted|llm[- ]based", re.I)

AI_USAGE = [
    ("AI for efficiency", "ai-efficiency",
     re.compile(r"efficien|faster|productiv|streamlin|speed|improve (?:your |our |the )?workflows?|"
                r"day[- ]to[- ]day|daily work|as part of your workflow", re.I)),
    ("AI for automation", "ai-automation",
     re.compile(r"automat|agentic|auto[- ]generat|\bworkflows?\b", re.I)),
    ("Building with AI", "ai-building",
     re.compile(r"build|develop|design|implement|creat\w+|deploy|enablement|integrat|"
                r"semantic layer|fine[- ]?tun|\brag\b", re.I)),
]
AI_DESC = {
    "AI for efficiency": "Expected to use AI tools (Copilot, ChatGPT, Cursor…) to work faster",
    "AI for automation": "Using AI to automate processes and workflows",
    "Building with AI": "Building AI/LLM-powered features, models or data products",
    "AI (unspecified)": "AI named as a requirement without a stated purpose",
}


def classify_ai(text):
    """Return [(label, token)] describing HOW a posting expects AI to be used.

    Each AI mention is judged by its ±70-char context; product-marketing mentions
    are skipped. A real mention with no recognizable purpose yields 'AI (unspecified)'."""
    text = _clean(text)
    found = set()
    hit_any = False
    for m in _AI_HIT.finditer(text):
        start = max(0, m.start() - 70)
        win = text[start:m.end() + 70]
        # judge only within the mention's own bullet — neighboring bullets leak context
        off = m.start() - start
        lb = win.rfind("•", 0, off) + 1
        rb = win.find("•", off)
        win = win[lb:rb if rb != -1 else len(win)]
        if _AI_PRODUCT.search(win) and not _AI_TOOLWORDS.search(win):
            continue
        hit_any = True
        for label, token, rx in AI_USAGE:
            if rx.search(win):
                found.add((label, token))
    out = [(lbl, tok) for lbl, tok, _ in AI_USAGE if (lbl, tok) in found]
    if hit_any and not out:
        out = [("AI (unspecified)", "ai-unspecified")]
    return out

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

# ---- academic degree: level + fields + required-vs-nice-to-have ----
_DEG_LEVELS = [
    ("PhD", re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|תואר שלישי", re.I)),
    ("MSc", re.compile(r"\bm\.?\s?sc\b|\bm\.?\s?a\b|\bmba\b|\bmaster(?:'?s)?\b|תואר שני", re.I)),
    ("BSc", re.compile(r"\bb\.?\s?sc\b|\bb\.?\s?a\b|\bbachelor(?:'?s)?\b|תואר ראשון|"
                       r"\b(?:academic|university) degree\b|\bdegree in\b", re.I)),
]
_DEG_PREF = re.compile(r"advantage|a plus|preferred(?! fields?)|nice to have|desirable|bonus|יתרון", re.I)
_DEG_FIELDS = [
    ("CS", re.compile(r"computer science|מדעי המחשב", re.I)),
    ("Industrial Eng.", re.compile(r"industrial engineering|הנדסת תעשייה|תעשייה וניהול", re.I)),
    ("Info Systems", re.compile(r"information systems|מערכות מידע", re.I)),
    ("Statistics", re.compile(r"statistics|סטטיסטיקה", re.I)),
    ("Economics", re.compile(r"economics|כלכלה", re.I)),
    ("Math", re.compile(r"mathematic|מתמטיקה", re.I)),
    ("Engineering", re.compile(r"\bengineering\b|הנדסה", re.I)),
    ("Business", re.compile(r"business (?:administration|management)|מנהל עסקים", re.I)),
    ("Finance", re.compile(r"\bfinance\b|מימון|חשבונאות", re.I)),
    ("Life Sciences", re.compile(r"life science|biolog|מדעי החיים", re.I)),
]


def _degree(text):
    """Return {'level','status','fields'} for the primary academic ask, or None.

    The primary ask is the LOWEST level mentioned as required (a JD asking 'BSc
    required, MSc an advantage' is a BSc job); if every mention is hedged with
    advantage/preferred wording, status is 'preferred'."""
    found = []
    for level, rx in _DEG_LEVELS:
        m = rx.search(text)
        if not m:
            continue
        window = text[m.end():m.end() + 150]
        # scope the required-vs-plus judgment to THIS degree's own clause: stop at a
        # bullet break, sentence end, or the mention of a DIFFERENT degree level —
        # otherwise "B.Sc required (M.Sc an advantage)" downgrades the B.Sc itself
        window = re.split(r"[•\n]|(?<=[a-zא-ת])\.\s", window)[0]
        for other_level, orx in _DEG_LEVELS:
            if other_level == level:
                continue
            om = orx.search(window)
            if om:
                window = window[:om.start()]
        status = "preferred" if _DEG_PREF.search(window) else "required"
        fields = [f for f, frx in _DEG_FIELDS if frx.search(window)][:3]
        found.append({"level": level, "status": status, "fields": fields})
    if not found:
        return None
    req = [d for d in found if d["status"] == "required"]
    pool = req or found
    order = {"BSc": 0, "MSc": 1, "PhD": 2}
    primary = min(pool, key=lambda d: order[d["level"]])
    if not primary["fields"]:                     # borrow fields from any sibling mention
        for d in found:
            if d["fields"]:
                primary = {**primary, "fields": d["fields"]}
                break
    return primary


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
    if re.search(r"שנתיים", text):               # Hebrew word-numeral: "two years"
        years = 2
    hits = [int(m.group(1)) for m in _YEARS_EXP.finditer(text) if 1 <= int(m.group(1)) <= 15]
    if hits:
        # a JD usually states the core ask first and nice-to-haves later; take the first
        # plausible mention, but prefer any value explicitly tied to "experience"
        exp_hits = [int(m.group(1)) for m in _YEARS_EXP.finditer(text)
                    if 1 <= int(m.group(1)) <= 15
                    and re.search(r"experience|ניסיון", text[max(0, m.start() - 60):m.end() + 30], re.I)]
        years = (exp_hits or hits)[0]

    return {"skills": skills, "family": family, "track": track, "years": years,
            "degree": _degree(text), "ai": classify_ai(text)}


def aggregate(profiles):
    """Fold per-job profiles into board-level demand stats, counted per posting.

    Returns {'total', 'with_skills',
             'clusters': [(cluster_label, [(skill, count)...])],   # non-overlapping charts
             'tasks': [(label, token, count)...],                  # day-to-day focus
             'by_family': {family: {'jobs': n, 'top': [(skill, count)...]}}}"""
    from collections import Counter, defaultdict
    total = len(profiles)
    fam_jobs = Counter()
    fam_skills = defaultdict(Counter)
    cl_counts = {k: Counter() for k, _ in CLUSTERS}
    task_counts = Counter()
    ai_counts = Counter()
    with_skills = 0
    # activities every JD mentions — fine inside their own cluster, noise in family cards
    fam_exclude = {"Dashboards", "Statistics"}
    for p in profiles:
        if p["skills"]:
            with_skills += 1
        for n, c in p["skills"]:
            ck = cluster_of(n, c)
            if ck:
                cl_counts[ck][n] += 1
        for lbl, tok in p.get("tasks", []):
            task_counts[(lbl, tok)] += 1
        for lbl, tok in p.get("ai", []):
            ai_counts[(lbl, tok)] += 1
        fam = p["family"]
        fam_jobs[fam] += 1
        fam_skills[fam].update(n for n, _ in p["skills"] if n not in fam_exclude)
    clusters = [(label, cl_counts[k].most_common(8))
                for k, label in CLUSTERS if cl_counts[k]]
    tasks = [(lbl, tok, c) for (lbl, tok), c in task_counts.most_common()]
    ai = [(lbl, tok, c) for (lbl, tok), c in ai_counts.most_common()]
    by_family = {f: {"jobs": fam_jobs[f], "top": fam_skills[f].most_common(6)}
                 for f in fam_jobs}
    return {"total": total, "with_skills": with_skills,
            "clusters": clusters, "tasks": tasks, "ai": ai, "by_family": by_family}
