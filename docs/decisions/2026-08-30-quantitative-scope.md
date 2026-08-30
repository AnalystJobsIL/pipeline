# 2026-08-30 — quantitative analysis, not qualitative reports

*lane: `classifier` (owns `pipeline/seniority.py` and the `llm_cache` key scheme). Extends
`docs/decisions/2026-08-28-analyst-scope.md`, which this record does not replace: boundaries
1–5 there are unchanged.*

## What the operator asked for

> "web scraping is ok, but the insights and feel need to be quantitative and not qualitative
> reports"
>
> "I only want to keep analyst roles in israel. all levels and all dates but still needs
> descriptions for all to make sure they are relevant"

## The boundary, as now enforced

A role qualifies when, in addition to boundaries 1–5 of the 2026-08-28 record, **the person's
own output is analysis of MEASURED data**: product / web / digital / SEO / marketing / growth
analytics, business metrics, experiments, dashboards, or reporting built on recorded events,
transactions or usage.

It does **not** qualify when the core output is a qualitative opinion or research report:
market research, consumer or market insights, brand / category strategy, industry, policy or
competitive-intelligence write-ups, survey narratives, user / UX research.

Israel-only, **all seniority levels and all dates** are unchanged. "Quantitative" is a
statement about the OUTPUT, not about seniority and not about how technical the role is: a
junior analyst writing SQL is in scope, and a Principal Consultant writing strategy decks is
not.

## Where it lives, and why not somewhere cheaper

**Condition (5) of `LLM_RULES`**, built inside `_rules()` so it enters the `CONTRACT` hash and
re-judges what it invalidates without anyone remembering to.

The three roles the operator named are the argument for putting it there:

| role | the text | verdict |
|---|---|---|
| `Modellama \| Research Analyst` | "Less dashboards. More thinking… Strong SQL (SQL Server), Python or R, statistical thinking… 3–5 years as a Data Analyst… large sports datasets" | **IN.** Quantitative analysis of measured data. The word "research" in the title is exactly why this cannot be a title rule. |
| `Hila & Co. \| Consumer & Market Insights (CMI) Manager` | "לְהוביל את תחום תובנות הצרכן והשוק… ניהול מחקרי שוק מקצה לקצה… ניסיון כפלנר/ית במשרד פרסום… עבודה מול מכוני מחקר"; posted by "Hila Malka 🔺 Headhunter & Talent Acquisition" | **OUT**, twice over: qualitative market-research output (condition 5) and an agency posting (condition 4). Its registry row has since been parked by `registry`. |
| `Percepto \| Data Insights Operations` | "Translate visual data into insights… learn the industries of Percepto's clients… engage with clients and commercial team… basic programming knowledge… excellent verbal and written communication" | **OUT.** A client-delivery / operations role on drone imagery; nothing in it is analysis of measured data. It was a current-contract **YES** — a rule-(1) over-read of the word "insights" — and the new rule moves it. |

### Alternatives rejected

| alternative | why not |
|---|---|
| Add `market research \| insights \| research analyst \| economist` to `_HARD_EXCLUDE` | It would reject `Modellama \| Research Analyst` and `Qualitest \| Quantitative Research Analyst` on the title alone, with no appeal and no cached verdict anyone could review — and it would re-decide them wrongly every morning. The title gate's false-negative rate was measured at **0.25 % over 401 postings** and that is the standard a deterministic reject has to meet; an OUTPUT judgement made on a title cannot. |
| Narrow `_STRONG` (drop `insight?s analyst`, `customer insights`) | Right direction, too narrow a reach: it misses `market`, `survey` and `competitive`, and it silently changes the tier of quantitative titles carrying those words. Subsumed by the demotion, which does the same job through the mechanism that already exists for this. |
| The rules text alone | Necessary but not sufficient: a `strong` + `senior` qualitative title (`Senior Market Insights Analyst`) is accepted by the keyword tier and never reaches the rules at all. |
| **Chosen: condition (5) + `_QUALITATIVE_HINT` demotion + read the description of a strong+senior role** | The rule decides on evidence; the keyword layer only ensures the evidence is read. |

`_QUALITATIVE_HINT` **only demotes** `strong` → `signal`, the mechanism `_BA_DOMAIN` and
`_AGENCY_EMPLOYER` already use, so a wrong word costs one LLM call and can never lose a role.
Three candidate words were **removed after measurement** because they demoted quantitative
roles: `intelligence` (matches `business intelligence developer` — 3 golden-fixture rows),
`strateg(y|ic)` (`strategic product analyst`), `consumer` (adds nothing `insights` and `market`
do not already reach). `market` is word-bounded so `marketing analyst` keeps its strong tier,
which `test_no_role_this_lane_published_a_yes_for_can_be_dropped_before_the_tier` requires.

## What it cost, measured before shipping

- **Keyword-tier movement: 0 of the golden fixture's 252 title-only rows, and 0 of the 4,266
  distinct live (company, title) pairs in the two committed caches.** The demotion closes a
  path nothing has yet walked through — the same shape as the 2026-08-28 internship fix.
- **False negatives of condition (5): 0 of 96.** Every Israel posting in the committed caches
  that passes the title gate and carries at least 300 characters of text (96 after
  de-duplication; 77 on the LLM tier, 19 fast-accepted) was judged once through the production
  seam under the new rules and compared with the verdict deciding it today. The artifact is
  committed: `tests/fixtures/classifier/2026-08-30-scope.json`. Three moved YES→NO —
  `Percepto | Data Insights Operations` (condition 5), `Play Perfect | Fraud Analyst`
  (condition 2, fraud-model development) and
  `מטריקס | מנתח/ת ומאייפנ/ת מערכות BI למשרד מממשלתי מוביל בירושלים - Matrix - DNA`
  (condition 4) — and **none of the three is a quantitative analyst role rejected for being
  qualitative**, which is what a false negative of this rule would be. Six moved NO→YES, every
  one the experience bar draining. Re-derive:
  `python tools/measure_scope_rule.py --tier both --workers 4`.
- **The measurement is not bit-reproducible.** Two passes over the same 77 postings moved 2 and
  3 verdicts; `Play Perfect | Fraud Analyst` appeared only in the second. A single pass is
  evidence about the cohort, not an oracle for one role.
- The sample is thin in exactly the place the rule is aimed: the corpus holds ~15
  qualitatively-titled postings and most have no description at all. So the FN rate above is
  evidence that the rule does not *break* quantitative roles, and much weaker evidence about
  how well it *catches* qualitative ones. That is the honest reading, and it is why an
  adversarial pass constructed boundary cases rather than trusting the corpus.

## What this decision also changed, because it could not be honest otherwise

**A `strong` + `senior` title with a description is now read** (`373@classifier`). The
shortcut's stated justification — "a senior/lead/principal analyst reliably means 3+ years" —
died with the experience bar on 2026-08-28, and it is the one path no description ever
touches, so condition (5) could not reach the ~30 roles a run that take it. Measured: of the
19 such roles that carry a description, the seam **rejects 5** — `EPAM Systems, Inc. |
Managing Principal / Senior Director, Data Analytics Consulting` (leadership and sales),
`Ecoppia | Senior Business Intelligence Developer` and `Zipher | Senior Data Analyst` (both
core data engineering), `Hunter Douglas, Inc. | Manager, Business Intelligence & Analytics`
(the stored text is industrial-maintenance boilerplate) and `Ballerine | AI Fraud Data Analyst
(Senior)` (the stored text is product marketing). A role with **no** description is still
accepted on its title, and so is every strong title when the seam is unavailable, so no
title-only role and no breaker-open morning is affected. Cost: ≤19 calls once, ~1–3 a day
after, against a 300-call cap running at 67–83.

## What would reopen this

- **A false negative on a real quantitative role.** The rule is one sentence in a prompt;
  a counter-example with its JD is enough to change it, and `tools/measure_scope_rule.py`
  re-measures the whole corpus for ~100 calls.
- **A qualitative role reaching the board through a title the demotion does not carry.**
  The demotion is a vocabulary and vocabularies are never finished; the evidence would be a
  board role whose JD is market research.
- **The `market` boundary.** `marketing analyst` is deliberately IN and `market analyst`
  deliberately demoted. If a real employer titles a quantitative role `Market Analyst`, that
  costs one call and nothing else — but if the seam then rejects it, this is the paragraph
  to reopen.
