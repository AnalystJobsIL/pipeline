# POC: per-company profile — firmographics × requirement fingerprint (2026-08-21)

Goal: connect the TYPE of company to the TYPE of requirements it asks for.
Five companies from different fields, live data:

| Company | Field | Stage | IL jobs | What the fingerprint shows |
|---|---|---|---|---|
| Wiz | cybersecurity (cloud) | acquired by Google, 3,148 emp | 23 | multi-cloud stack (AWS 13 / GCP 13 / Azure 12), median 5 yrs, almost no degree asks |
| Melio | fintech (B2B payments SMB) | acquired by Xero, ~693 emp | 5 | tiny senior IL core: median 7 yrs, Python/AWS/ML |
| Aidoc | healthtech (clinical AI) | growth-private $1B+, ~596 emp | 27 | Python+ML platform, heaviest Lead ratio (12/27), degree-required culture (13 explicit asks) — regulated-medical pattern |
| Mobileye | automotive/semis (ADAS) | public (MBLY), ~4,300 emp | 134 | algorithm/perception research roles; extraction largely misses years/degrees — different JD style |
| monday.com | SaaS (work management) | public (MNDY), ~2,500 emp | 13 | AI pivot visible in requirements: highest "Building with AI" rate, agentic-team titles |

## Files
- `poc_company_profile.py` — fetches the 5 companies via the existing fetchers, filters Israel,
  runs `roleprofile.extract` per job, folds into a per-company requirement fingerprint,
  merges `poc_firmographics.json`, writes `out/poc_company_profiles.json`.
- `poc_firmographics.json` — hand-researched company facts (schema in `_schema`), the
  cacheable half. Researched once per company, like `company_info.py` blurbs.

## Conclusions from the POC
1. **No external data API is needed for the requirements half.** The pipeline already holds
   the richest possible source — full JD text per company — and `roleprofile.extract` turns it
   into comparable fingerprints for free.
2. **Firmographics: per-company research beats a generic API at this scale.** ~300 companies ×
   one-time research (the cached `claude -p` pattern `company_info.py` already uses, extended to
   a structured schema instead of 2 sentences) covers the list without a paid key. Generic APIs
   (Apollo free tier, People Data Labs) only become worth it if the list grows into the thousands
   or the data must refresh continuously.
3. **Main gap exposed: the role-family lexicon is analyst-shaped.** Engineering-heavy companies
   collapse: 74/134 Mobileye jobs land in "Other", and Wiz's Account Executives/Backend Engineers
   get tagged "Data Science" because the `\bai\b|algorithm|ml` fallback fires on the JD intro.
   To make type↔requirement comparisons honest, `_FAMILIES` needs engineering/security/sales
   families (Backend, Frontend, DevOps/SRE, Security Research, Algorithms, QA, Sales/CS) and the
   title-first rule should win more aggressively over the desc fallback.
4. **The connection the user wanted is real and visible even in n=5**: regulated-medical →
   degrees + leads; cloud-security → multi-cloud breadth, no degrees; automotive → research
   algorithms; SaaS-in-AI-pivot → building-with-AI requirements; SMB-fintech → small senior teams.
