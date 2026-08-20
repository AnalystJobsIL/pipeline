"""Render build_board_html with representative sample jobs to verify current styling."""
from pipeline.digest import build_board_html

jobs = [
    {"company": "Upwind", "title": "Senior Data Analyst", "location": "Tel Aviv-Yafo, IL",
     "url": "https://example.com/1", "posted_date": "2026-08-14",
     "description": "We're looking for a Senior Data Analyst with 5+ years building dashboards, "
     "SQL models and driving product decisions with data. Own analytics end to end."},
    {"company": "Connecteam", "title": "Analytics Engineer (Maternity Cover)",
     "location": "Tel Aviv", "url": "https://example.com/2", "posted_date": "2026-08-12",
     "description": "Build the dbt + Snowflake analytics layer. 3+ years in analytics engineering."},
    {"company": "NVIDIA", "title": "Data Scientist, Product Analytics", "location": "Yokneam, IL",
     "url": "https://example.com/3", "posted_date": "2026-08-08",
     "description": "Product data scientist doing experimentation and analytics (not ML research). "
     "Partner with PMs. 4+ years."},
    {"company": "HoneyBook", "title": "BI Developer", "location": "Tel Aviv-Yafo",
     "url": "https://example.com/4", "posted_date": "2026-08-05",
     "description": "Own the BI stack, Looker + SQL. Lead analytics for GTM teams."},
    {"company": "Medtronic", "title": "Lead Business Intelligence Analyst", "location": "Yakum, IL",
     "url": "https://example.com/5", "posted_date": "2026-07-30",
     "description": "Lead BI for the R&D org. 7+ years, stakeholder management, Tableau."},
    {"company": "Eleos Health", "title": "Data Analyst", "location": "Israel",
     "url": "https://example.com/6", "posted_date": "2026-08-13", "description": ""},
]
html = build_board_html(jobs, "2026-08-15", {"companies_scanned": 193},
                        company_info={}, contact_url="https://github.com/AnalystJobsIL/board/issues/new")
with open("out/board_test.html", "w", encoding="utf-8") as f:
    f.write(html)
print("wrote out/board_test.html", len(html), "bytes")
