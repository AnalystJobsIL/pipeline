# Board tagging system

How every tag, badge, and chart on the published board is computed, and where to change it.
Everything is **deterministic** — regex lexicons and header rules over the stored posting text.
No LLM calls at render time, so tags are reproducible and free. The flip side: a tag can be
missing simply because the posting never said it, and coverage is capped by how much
description text the fetch layer stored.

**On description coverage (2026-08-23):** four list endpoints carry no JD at all — `workday`,
`smartrecruiters`, `bamboohr`, `microsoft` — so their roles used to reach the board with a
title and nothing to tag. `pipeline/jdfill.py` fetches the JD from the posting's own URL
before classification, and `enrich_matched_jd.py` backfills the `matched` table itself at any
age. If a role still renders "Requirements aren't captured", the posting's page is the reason
(a JS shell or a bot wall), not the fetch layer.

All extraction lives in two files:

| File | Owns |
|---|---|
| `pipeline/roleprofile.py` | skill lexicon + clusters, role family, IC/lead track, years, degree, day-to-day task groups, AI-usage classification, per-board aggregation |
| `pipeline/digest.py` | requirements/responsibilities section extraction (`_requirements_snippet`, `_responsibilities_snippet`), MUST/PLUS badges, reposted marker, and all rendering |

## Skills

`roleprofile.SKILLS` — a curated list of `(canonical name, category, regex)`. Patterns are
word-bounded and case-insensitive; risky short names (R, Excel, VBA, Java) carry context guards.
Hebrew transliterations are included where seen in the wild (טאבלו, פייתון, אקסל).
`SKILL_DESC` holds the one-line tooltip for each skill — add one when adding a skill.

Skills roll up into **non-overlapping clusters** for the dashboard (`CLUSTERS` +
`_CAT2CLUSTER`, with per-name overrides in `_NAME_CLUSTER`):

- **SQL & Databases** — query engines and stores
- **ETL & Infrastructure** — pipelines, modeling, warehouse, cloud platforms, version control
- **Coding, ML & Statistics** — languages plus statistical/analysis methods (Statistics,
  A/B testing, Forecasting, Cohorts & LTV, experimentation platforms)
- **Visualization & BI** — dashboarding tools, the "Dashboards" activity, AND product
  event-analytics platforms (GA4, Amplitude, Mixpanel, Pendo, Heap). Decision 2026-08-21,
  based on listing evidence: the market's own phrasing files them together ("Experience
  working with BI tools (Looker, Tableau, Metabase, Amplitude, or similar)" — Bounce AI),
  and cross-tab showed roles ask for ONE tool from the family, almost never both a BI tool
  and an event platform (32 BI-only / 2 event-only / 1 both across 80 described jobs).
- **Other** — everything domain-specific: ad platforms, MMPs, SEO, CRM/martech, ERPs
  (SAP, Priority), work tools. The catch-all for future additions that fit nowhere else.

Languages (English) are tagged on cards but excluded from cluster charts.

## Requirements ("What you'll need")

`digest._requirements_snippet` finds a requirements **header** (English + Hebrew forms; a
match is rejected if the text after it opens with an imperative verb — that catches
mid-sentence words like "…ad-hoc requirements Develop dashboards…"), cuts the section at the
next section header, splits bullets (recovering lists whose `•` markers were lost in
scraping), and filters junk (culture blurbs, hashtags, "Apply now", addresses).

**MUST / PLUS badges** mirror the posting's own wording — leading or trailing
"must / mandatory / חובה" and "advantage / a plus / nice to have / יתרון". A whole
"Advantages:" / "Bonus points:" sub-section auto-badges everything after it as PLUS.
No badge means the posting didn't mark that line — absence is not signal.

## Day-to-day ("Responsibilities")

`digest._responsibilities_snippet` mirrors the requirements extractor for the
responsibilities section. `roleprofile.TASK_GROUPS` then classifies the bullets into
groups (label / filter-token / regex): Dashboards & Reporting, Analysis & Insights,
Experiments & Models, Data & Pipelines, Stakeholders & Communication, Monitoring & Data
Quality. `TASK_DESC` holds tooltips. When a JD has no responsibilities section (prose-style),
the pre-requirements text is split into sentences and classified instead — chips without
bullets.

**Hard segmentation** (2026-08-22 workshop, modeled bottom-up from the board's 332 real
responsibility bullets): the taxonomy was rebuilt with **action titles** and a
**single-assignment rule** — `classify_bullet` gives every bullet exactly ONE group (most
vocabulary hits wins; ties go to the more specific group, i.e. earlier in TASK_GROUPS).
A bullet can never feed two clusters, so cross-cluster double-tagging is structurally
impossible. Measured tie rate on the corpus: 17% of bullets, and tie resolution follows
the intended semantics ("partner to define KPIs" → metrics; "partner to analyze" →
analysis; "semantic layer" → pipelines, not dashboards).

The eight groups, in tie-priority order (most specific first): Instrument & manage
tracking · Assure data quality (absorbs alerting/anomalies — NOT "monitoring", which
reads as dashboard-watching and now lives with reporting) · Run experiments & build
models · Define metrics & KPIs (metric ownership is neither dashboarding nor analysis) ·
Build pipelines & data models · Build dashboards & track performance · Analyze & recommend
(recommendations belong with insights, not with communication) · Partner & present.

**Chip rule**: a group earns its chip when it wins ≥2 bullets, or ≥25% of a short list;
chips order dominant-first. Current distribution: median 2 chips/job; Analyze 70%,
Partner 33%, Dashboards 26%, Pipelines 19%, Quality 12%, Experiments 7%, Metrics 5%,
Tracking 3%.

A full per-group review of all 332 bullets (not just samples) was done 2026-08-22; fixes
from it: bare "models" removed from the Experiments vocabulary ("analytics models" beside
"pipelines" was landing there — now only statistical/predictive/risk/"build models"
phrasing counts), the Define-metrics verb-to-KPI window widened to 45 chars ("Own and
define key product, business, and customer KPIs" was slipping through), and "What we
expect" added as a requirements header (Playtika's requirements were leaking into
responsibilities). Known residual seams, both single-bullet ties left as-is: Airflow
orchestration with "alerting/SLAs" can land in Assure-data-quality instead of Pipelines;
Hebrew ממשק can pull a tool-building bullet into Partner & present.

## AI usage 🤖

`roleprofile.classify_ai` answers *what is the analyst expected to DO with AI*, not whether
the posting mentions AI:

1. Find AI mentions (`_AI_HIT`: LLM/GenAI/AI tools/ChatGPT/Copilot/Claude/prompt-engineering…).
2. Skip mentions of the **company's product** (`_AI_PRODUCT`: "our AI agents",
   "AI-powered platform"…) — analyzing an AI product is product analysis, not AI usage.
3. Judge the remaining mentions by the words inside the **same bullet** (window is clipped
   at `•` boundaries so neighboring bullets can't leak context) into `AI_USAGE` buckets:
   - **AI for efficiency** — use AI tools to work faster
   - **AI for automation** — AI to automate processes/workflows
   - **Building with AI** — building LLM/AI-powered features or data products
   - **AI (unspecified)** — a real mention with no stated purpose

**Requirement vs. day-to-day** — the same bucket means different things depending on WHERE
the mention sits, and the system keeps them apart end to end:

- Mention inside the **requirements** section ⇒ *prior experience the candidate must bring*
  ("Hands-on experience with GenAI tools"). Chips render in the requirements column, filter
  tokens are suffixed `-req` (e.g. `ai-building-req`), and the dashboard groups them under
  "Required coming in".
- Mention inside the **responsibilities** section (or only in intro prose) ⇒ *part of the
  job* — a duty, learnable on the job ("build AI-powered features"). Chips render under
  Day to day, plain tokens (`ai-building`), dashboard group "In the day-to-day".

So "Building with AI" under day-to-day is NOT a hiring bar — it says the role will produce
AI-powered work; the same label under requirements says you must already have done so.

As more jobs accumulate, revisit whether "unspecified" shrinks, whether the req/day split
shifts (day-heavy = teams hiring analysts to grow into AI; req-heavy = AI experience
becoming a real gate), and whether new buckets (e.g. AI governance/QA) deserve a regex.

## Soft skills

`roleprofile.SOFT_SKILLS` — nine person-traits (not tools), tagged from the
**requirements section only**: Communication & storytelling, Team player, Ownership &
independence, Business acumen, Problem solving, Attention to detail, Curiosity &
learning, Thrives in fast pace, Leadership & mentoring. Presence-based (a soft skill is
usually a single bullet), English + Hebrew patterns, `SOFT_DESC` for tooltips. Rendered
as dotted chips under the requirements column, filterable by single-word tokens
(`ownership`, `curiosity`, `fastpaced`…), with a purple "Soft skills" chart on the
dashboard. Deliberately separate from the hard-skill lexicon and clusters.

## Other markers

- **Years** — first number adjacent to "experience"/ניסיון (`_YEARS_EXP`; שנתיים → 2).
- **Degree** — level (BSc/MSc/PhD), fields, and required-vs-plus judged only inside the
  degree's own clause, so "BSc required (MSc an advantage)" stays a required BSc.
- **Role family / track** — title-first regexes (`_FAMILIES`, `_LEAD`); used for search,
  not displayed as a fact (a bare "Senior"/"Data Analyst" label carries no information).
- **reposted** — `posted_date` ≥ 3 days after the board's `first_seen` ⇒ company bump;
  the card shows the original date. Truly-new = `first_seen` within the last day.

## Where users see it

Tooltips on every tag/bar explain meaning; the board page carries a collapsible
"How the tags on this board are computed" legend (generated from `TASK_DESC` / `AI_DESC` /
`CLUSTERS` at render time, so it can't drift from the code).
