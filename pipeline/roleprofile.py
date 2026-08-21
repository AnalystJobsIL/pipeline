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
    ("ClickHouse",     "query",  r"\bclickhouse\b"),
    ("Vertica",        "query",  r"\bvertica\b"),
    ("Presto/Trino/Athena", "query", r"\bpresto\b|\btrino\b|\bathena\b"),
    ("Hive",           "query",  r"\bhive\b"),
    ("Teradata",       "query",  r"\bteradata\b"),
    ("DuckDB",         "query",  r"\bduckdb\b"),
    ("Firebolt",       "query",  r"\bfirebolt\b"),
    ("Splunk",         "query",  r"\bsplunk\b"),
    ("Synapse",        "query",  r"\bazure synapse\b|\bsynapse analytics\b"),
    # programming & analysis
    ("Python",         "prog",   r"\bpython\b|פייתון"),
    ("R",              "prog",   r"(?<![\w&.+/-])R(?![\w&.+#-])(?=[\s,/;.)]|$)"),
    ("SAS",            "prog",   r"\bsas\b"),
    ("VBA",            "prog",   r"\bvba\b|\bexcel macros?\b|\bmacros\b"),
    ("Scala",          "prog",   r"\bscala\b"),
    ("Java",           "prog",   r"\bjava\b(?!script)"),
    ("MATLAB",         "prog",   r"\bmatlab\b"),
    ("SPSS/Stata",     "prog",   r"\bspss\b|\bstata\b"),
    ("SageMaker/Vertex AI", "prog", r"\bsagemaker\b|\bvertex ai\b|\bmlflow\b"),
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
    ("Datadog",        "bi",     r"\bdatadog\b"),
    ("Hex/Mode",       "bi",     r"\bhex\b(?![a-z])|\bmode analytics\b|\blightdash\b"),
    ("Cognos",         "bi",     r"\bcognos\b"),
    ("Metabase",       "bi",     r"\bmetabase\b"),
    ("Redash",         "bi",     r"\bredash\b"),
    ("Domo",           "bi",     r"\bdomo\b"),
    ("ThoughtSpot",    "bi",     r"\bthoughtspot\b"),
    ("Google Sheets",  "bi",     r"\bgoogle sheets\b|\bgsheets?\b"),
    ("Streamlit",      "bi",     r"\bstreamlit\b"),
    # product event analytics — the market files these with BI tools (see docs/TAGGING.md)
    ("Google Analytics", "bi",   r"\bgoogle analytics\b|\bga4\b|\buniversal analytics\b|\bfirebase\b"),
    ("Amplitude",      "bi",     r"\bamplitude\b"),
    ("Mixpanel",       "bi",     r"\bmixpanel\b"),
    ("Pendo",          "bi",     r"\bpendo\b"),
    ("Heap",           "bi",     r"\bheap\b"),
    ("Hotjar/FullStory", "bi",   r"\bhotjar\b|\bfullstory\b|session replay"),
    # marketing / domain stacks → the "Other" cluster
    ("Google Tag Manager", "pa", r"\bgoogle tag manager\b|\bgtm\b"),
    ("AppsFlyer/MMP",  "pa",     r"\bappsflyer\b|\badjust\b|\bsingular\b|\bmmp\b|\bmobile measurement\b"),
    ("Google Ads",     "pa",     r"\bgoogle ads\b|\badwords\b|\bppc\b|\bsem\b"),
    ("Meta Ads",       "pa",     r"\bfacebook ads\b|\bmeta ads\b"),
    ("TikTok/LinkedIn Ads", "pa", r"\btiktok ads\b|\blinkedin ads\b|\bpaid social\b"),
    ("SEO",            "pa",     r"\bseo\b"),
    ("CRM/Salesforce", "pa",     r"\bsalesforce\b|\bhubspot\b|\bcrm\b"),
    ("Braze/Iterable", "pa",     r"\bbraze\b|\biterable\b|\bmarketing automation\b"),
    ("SAP ERP",        "pa",     r"\bsap\b(?!\s*(?:bo\b|business\s?objects))"),
    ("Priority ERP",   "pa",     r"\bpriority erp\b|פריוריטי"),
    ("Jira",           "pa",     r"\bjira\b"),
    ("monday.com",     "pa",     r"\bmonday\.com\b"),
    # data engineering
    ("ETL",            "de",     r"\betl\b|\belt\b"),
    ("dbt",            "de",     r"\bdbt\b"),
    ("Airflow",        "de",     r"\bair ?flow\b"),
    ("SSIS/SSAS",      "de",     r"\bssis\b|\bssas\b|\bssrs\b"),
    ("Data modeling",  "de",     r"\bdata model(?:ing|ling|s)?\b|\bdimensional model|\bstar schema\b"),
    ("Data warehouse", "de",     r"\bdata ?warehouse\b|\bdwh\b"),
    ("Kafka",          "de",     r"\bkafka\b"),
    ("Fivetran",       "de",     r"\bfivetran\b|\bstitch\b"),
    ("Snowplow",       "de",     r"\bsnowplow\b"),
    ("Talend/Informatica", "de", r"\btalend\b|\binformatica\b|\bpentaho\b|\bdatastage\b"),
    ("AWS Glue",       "de",     r"\baws glue\b|\bglue jobs?\b"),
    ("Segment/CDP",    "de",     r"\bsegment\.(?:io|com)\b|twilio segment|\bcdp\b|customer data platform"),
    ("Git",            "de",     r"\bgit(?:hub|lab)?\b"),
    ("Microsoft Fabric", "de",   r"\bmicrosoft fabric\b|\bms fabric\b|\bonelake\b"),
    ("Power Platform", "de",     r"\bpower (?:platform|apps|automate)\b"),
    ("Workato/Zapier/Make", "de", r"\bworkato\b|\bzapier\b|\bn8n\b|\bmake\.com\b"),
    ("Alteryx/KNIME",  "de",     r"\balteryx\b|\bknime\b"),
    ("Delta Lake/Iceberg", "de", r"\bdelta lake\b|\biceberg\b|\blakehouse\b"),
    # cloud
    ("AWS",            "cloud",  r"\baws\b|\bamazon web services\b"),
    ("GCP",            "cloud",  r"\bgcp\b|\bgoogle cloud\b"),
    ("Azure",          "cloud",  r"\bazure\b"),
    # statistics / methods
    ("A/B testing",    "method", r"\ba/?b[- ]test|\bexperimentation\b|\bsplit test"),
    ("Statistics",     "method", r"\bstatistic(?:s|al)\b|\bhypothesis test|\bregression\b"),
    ("Machine learning", "method", r"\bmachine[- ]learning\b|\bml models?\b|\bpredictive model"),
    ("Forecasting",    "method", r"\bforecast(?:ing|s)?\b"),
    ("Cohorts & LTV",  "method", r"\bcohorts?\b|\bltv\b|lifetime value|\bchurn\b|\bretention analysis\b"),
    ("Experimentation platforms", "method", r"\boptimizely\b|\bvwo\b|\blaunchdarkly\b|\bsplit\.io\b"),
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
            ("other", "Other")]
_CAT2CLUSTER = {"query": "sqldb", "de": "etl", "cloud": "etl", "prog": "code",
                "bi": "viz", "method": "viz", "pa": "other"}
# statistical-analysis methods live with coding & ML; only Dashboards stays visualization
_NAME_CLUSTER = {"Machine learning": "code", "Statistics": "code",
                 "A/B testing": "code", "Forecasting": "code",
                 "Cohorts & LTV": "code", "Experimentation platforms": "code"}


def cluster_of(name, cat):
    """Cluster key for one skill, or None (languages stay off the charts)."""
    return _NAME_CLUSTER.get(name) or _CAT2CLUSTER.get(cat)


# ---- day-to-day task groups, classified from the responsibilities bullets ----
# Action-titled and hard-segmented: every bullet is assigned to exactly ONE group —
# the group whose vocabulary it matches most; ties go to the more specific group
# (earlier in this list). Modeled bottom-up from the board's real responsibility
# bullets (2026-08-22 workshop, see docs/TAGGING.md).
TASK_GROUPS = [
    ("Instrument & manage tracking", "tracking",
     re.compile(r"instrument|event[- ]track|tracking plan|taxonom|tagging|google tag manager|"
                r"\bgtm\b|attribution setup", re.I)),
    ("Assure data quality", "quality",
     re.compile(r"data quality|data integrit|cleans|validat|\bqa\b|audit|anomal|alert|"
                r"data issues|accuracy|consistency|observabilit|govern|בקרת נתונים", re.I)),
    ("Run experiments & build models", "experiments",
     # bare "models" deliberately excluded — "analytics models" next to "pipelines"
     # belongs to data modeling, not statistical modeling
     re.compile(r"a/?b[- ]test|experiment|forecast|predict|machine[- ]learning|hypothes|"
                r"simulat|build(?:ing)?\s+models?\b|"
                r"(?:statistical|predictive|risk|churn|propensity|regression|scoring)\s+model\w*|"
                r"מודל", re.I)),
    ("Define metrics & KPIs", "metrics",
     re.compile(r"(?:defin|standardi[sz]|own|document)\w*[^.•]{0,45}(?:kpis?|metrics?)|"
                r"metric specs?|single source of truth|north[- ]star|הגדרת מדדים", re.I)),
    ("Build pipelines & data models", "pipelines",
     re.compile(r"pipeline|\betl\b|\belt\b|data model|warehouse|\bdbt\b|airflow|\bssis\b|"
                r"semantic layer|modeled data|infrastructur|automat|integrat|ingest|תשתית", re.I)),
    ("Build dashboards & track performance", "reporting",
     re.compile(r"dashboard|report(?:s|ing)?\b|visuali[sz]|scorecard|self[- ]serve|"
                r"(?:track|monitor)\w*[^.•]{0,40}(?:performance|metrics?|kpis?|flows?)|"
                r"monitor(?:ing)?\b|דוחות|דשבורד", re.I)),
    ("Analyze & recommend", "analysis",
     re.compile(r"analy[sz]|insight|deep[- ]dive|dive deep|investigat|explor|research|uncover|"
                r"identify[^.•]{0,40}(?:trend|opportunit|pattern|friction)|root[- ]cause|"
                r"recommend|segment|cohort|funnel|ניתוח|תובנות|המלצ", re.I)),
    ("Partner & present", "partnering",
     re.compile(r"stakeholder|present|communicat|partner|collaborat|cross[- ]functional|"
                r"business (?:teams|units|leaders)|advis|translate|work (?:closely|with)|"
                r"gather[^.•]{0,20}requirement|support (?:teams|the business)|ממשק|הצגה", re.I)),
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
    "Pendo": "Product analytics & in-app guides",
    "Heap": "Auto-capture product analytics",
    "Hotjar/FullStory": "Session replay & behavior analytics",
    "Metabase": "Open-source BI & dashboards", "Redash": "Open-source SQL dashboards",
    "Domo": "Cloud BI platform", "ThoughtSpot": "Search-driven BI",
    "Google Sheets": "Collaborative spreadsheets", "Streamlit": "Python data apps",
    "ClickHouse": "Columnar OLAP database", "Vertica": "Columnar analytics database",
    "Presto/Trino/Athena": "Distributed SQL query engines", "Hive": "SQL on Hadoop",
    "Teradata": "Enterprise data warehouse", "DuckDB": "In-process analytics database",
    "Firebolt": "Cloud data warehouse (Israeli)",
    "Fivetran": "Managed data-ingestion connectors", "Snowplow": "Behavioral event pipeline",
    "Talend/Informatica": "Enterprise ETL suites", "AWS Glue": "AWS managed ETL",
    "Segment/CDP": "Customer-data platform / event routing",
    "Git": "Version control (Git/GitHub/GitLab)",
    "SPSS/Stata": "Statistical analysis packages",
    "Cohorts & LTV": "Cohort, retention, churn & lifetime-value analysis",
    "Experimentation platforms": "A/B-testing platforms (Optimizely, VWO…)",
    "TikTok/LinkedIn Ads": "Paid social advertising",
    "Braze/Iterable": "Marketing-automation / CRM messaging platforms",
    "SAP ERP": "SAP enterprise systems (as a data source)",
    "Priority ERP": "Priority ERP (common in Israeli companies)",
    "Jira": "Ticketing & project tracking", "monday.com": "Work management platform",
    "Splunk": "Search & analytics over logs and machine data",
    "Synapse": "Azure's analytics warehouse",
    "Microsoft Fabric": "Microsoft's unified data & analytics platform",
    "Power Platform": "Microsoft low-code apps & automation (Power Apps/Automate)",
    "Workato/Zapier/Make": "No-code workflow automation tools",
    "Alteryx/KNIME": "Visual data-prep & analytics workflows",
    "Delta Lake/Iceberg": "Lakehouse table formats",
    "Datadog": "Monitoring & observability dashboards",
    "Hex/Mode": "Notebook-style analytics & BI tools",
    "Cognos": "IBM's enterprise BI suite",
    "SageMaker/Vertex AI": "Managed ML platforms (AWS/GCP)",
}

TASK_DESC = {
    "Instrument & manage tracking": "Setting up event tracking, taxonomies and instrumentation",
    "Assure data quality": "Validation, anomaly detection, alerting — keeping the data trustworthy",
    "Run experiments & build models": "A/B tests, statistical models and forecasts",
    "Define metrics & KPIs": "Owning metric definitions — the single source of truth for KPIs",
    "Build pipelines & data models": "ETL, warehouse models and analytical infrastructure",
    "Build dashboards & track performance": "Dashboards, recurring reports and performance tracking",
    "Analyze & recommend": "Deep dives and analysis that end in insights and recommendations",
    "Partner & present": "Working with business teams — gathering needs, presenting findings",
}


def classify_bullet(bullet):
    """Assign ONE task group to a bullet — the group with the most vocabulary hits;
    ties break toward the more specific group (earlier in TASK_GROUPS). Returns
    (label, token) or None. Single assignment is what keeps the groups segmented:
    a bullet can never feed two clusters."""
    best, best_score = None, 0
    for label, token, rx in TASK_GROUPS:
        score = len(rx.findall(bullet))
        if score > best_score:
            best, best_score = (label, token), score
    return best


def classify_tasks(bullets):
    """Map responsibility bullets to the day-to-day TASK_GROUPS the role EMPHASIZES.

    Each bullet is single-assigned via classify_bullet; a group earns its chip only
    when it wins at least 2 bullets (or 1 for very short lists) — one passing mention
    is not a day-to-day focus. Returns [(label, token)] dominant-first."""
    bullets = [b for b in (bullets or []) if b]
    if not bullets:
        return []
    from collections import Counter
    wins = Counter()
    for b in bullets:
        g = classify_bullet(b)
        if g:
            wins[g] += 1
    total = sum(wins.values()) or 1
    # a chip = the group won 2+ bullets, or a quarter of a short list
    kept = [(g, c) for g, c in wins.items() if c >= 2 or c / total >= 0.25]
    kept.sort(key=lambda x: -x[1])
    return [g for g, _ in kept]


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
        for lbl, tok in p.get("ai_req", []):
            ai_counts[("req", lbl, tok)] += 1
        for lbl, tok in p.get("ai_day", []):
            ai_counts[("day", lbl, tok)] += 1
        fam = p["family"]
        fam_jobs[fam] += 1
        fam_skills[fam].update(n for n, _ in p["skills"] if n not in fam_exclude)
    clusters = [(label, cl_counts[k].most_common(8))
                for k, label in CLUSTERS if cl_counts[k]]
    tasks = [(lbl, tok, c) for (lbl, tok), c in task_counts.most_common()]
    ai_req = [(lbl, tok, c) for (side, lbl, tok), c in ai_counts.most_common()
              if side == "req"]
    ai_day = [(lbl, tok, c) for (side, lbl, tok), c in ai_counts.most_common()
              if side == "day"]
    by_family = {f: {"jobs": fam_jobs[f], "top": fam_skills[f].most_common(6)}
                 for f in fam_jobs}
    return {"total": total, "with_skills": with_skills, "clusters": clusters,
            "tasks": tasks, "ai_req": ai_req, "ai_day": ai_day, "by_family": by_family}
