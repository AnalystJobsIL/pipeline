# Board tagging system

How every tag, badge, and chart on the published board is computed, and where to change it.
Everything is **deterministic** — regex lexicons and header rules over the stored posting text.
No LLM calls at render time, so tags are reproducible and free. The flip side: a tag can be
missing simply because the posting never said it, and coverage is capped by how much
description text the fetch layer stored.

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
- **ETL & Infrastructure** — pipelines, modeling, warehouse, cloud platforms
- **Coding, ML & Statistics** — languages plus statistical methods (Statistics, A/B testing,
  Forecasting deliberately live here, not under visualization)
- **Visualization & BI** — dashboarding tools + the generic "Dashboards" activity
- **Product & Marketing Analytics** — measurement platforms (Amplitude/Mixpanel/GA are event
  *measurement* tools, not visualization tools — their charts are a feature, not the skill)

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
the pre-requirements text is classified instead — chips without bullets.

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

Chips render in the requirements column (when the mention is in requirements) and the
Day-to-day section (when in responsibilities, or only in intro prose); the dashboard has a
dedicated "AI usage" chart. As more jobs accumulate, revisit whether "unspecified" shrinks
and whether new buckets (e.g. AI governance/QA) deserve their own regex.

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
