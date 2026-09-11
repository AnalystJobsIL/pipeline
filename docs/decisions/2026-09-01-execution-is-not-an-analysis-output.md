# 2026-09-01 — analysis that steers your own execution is not an analysis output

*lane: `classifier` (`pipeline/seniority.py`). Extends condition (5) of
`docs/decisions/2026-08-30-quantitative-scope.md`, which it does not replace. It also carries
item `531`'s clause into condition (3), because both ship on one contract bump.*

## What forced the question

The 08-30 record drew the line between quantitative and qualitative OUTPUT. It does not
reach a third thing, which the operator's audit found twice: a role whose output is neither
a report nor an opinion but **an action** — a campaign, a resolved case, a configured
system — where the person reads measured data all day to steer their own work.

`Kibeeri | Marketing Analyst` and `Natural Intelligence | Marketing Analyst` are the pair the
audit named. Both are titled "Marketing Analyst"; `marketing analyst` is deliberately IN and
word-bounded in `_QUALITATIVE_HINT` so it keeps its `strong` tier. Nothing in the rules told
the seam that running the campaigns is not analysing them.

## The boundary

> Analysis done in service of the person's OWN execution is not an analysis **output**: when
> the responsibilities lead with running campaigns, owning budgets, resolving cases or
> configuring a system, and the analysis exists to steer that same execution, answer NO —
> someone who sets up and optimises paid-search campaigns is running campaigns, however many
> numbers they read.

With the tie-breaker, because most real postings are mixed:

> Where the responsibilities genuinely split between execution and producing reports or
> insights **others** act on, judge which the posting leads with, and treat data analysis
> offered only as "an advantage" or "a plus" in the requirements as corroboration that it is
> the secondary half.

The test is *who acts on it*. An analyst produces something a decision-maker uses; an
operator produces the decision itself, executed.

## Worked examples

| posting | what the person produces | verdict |
|---|---|---|
| `Natural Intelligence \| Marketing Analyst` | "Manage and optimize large-scale paid search marketing campaigns"; "Own and manage high marketing budgets"; media buying is the job | **OUT** |
| `Kibeeri \| Marketing Analyst` | responsibilities lead "Manage PPC Search campaigns"; requirements say "Data Analysis – a plus" | **OUT** |
| `Cato Networks \| Marketing Ops & Analytics Manager` | "multi-touch attribution, funnel and cohort analysis"; "executive dashboards … pipeline health, velocity, campaign ROI, CAC" — leadership acts on it | **IN** |
| `LTX \| Commercial Operations Analyst` | "Own the end-to-end setup of commercial deals across CRM and billing"; "resolve discrepancies before they reach Finance"; SQL/BI "an advantage" | **OUT** |
| `Global-e \| Payment Operations Analyst` | "Investigate and resolve payment-related issues across gateways, acquirers"; BI tools "advantage" | **OUT** |
| `Bylith \| Product Analyst` | "Requirement gathering and gap analysis"; "Writing high-level and detailed specification documents" — a systems analyst | **OUT** |
| `Percepto \| Data Insights Operations` | "Translate visual data into insights" on client timelines; no metric, dashboard, SQL or BI anywhere | **OUT** |
| `Migdal \| Data Analyst` | explicitly split — CRM implementation and "בניית דוחות שוטפים ואד-הוק" with "הצגת ממצאים ותובנות להנהלה" (present findings and insights to management) | **IN** |
| `Paz - yellow \| Trade Marketing Analyst` | planogram building **and** "בקרה שוטפת על נתוני הקטגוריות: מכר ונתחי שוק" feeding category recommendations | **IN** |
| `CloudHiro \| Junior Technical Operations Analyst` | "Analyze cloud infrastructure usage and cost data to identify optimization opportunities" delivered to customers | **IN** |
| `withfaye \| Insurance Operations Analyst` | "Build and maintain operational reports, dashboards, and tracking tools"; "ad hoc analyses to support operational decision-making" | **IN** |

The last four are the reason the rule has a tie-breaker rather than a keyword. All four are
mixed, all four keep BI tooling at "advantage" level, and all four were adjudicated **IN**
because a reporting deliverable someone else consumes is named among the responsibilities.
A first draft of this clause made "an advantage" decisive on its own; it would have taken all
four off the board, and it was softened to corroboration before it shipped.

## `531` — temporariness is not a ground, and now the rules say so

Filed 2026-08-31: the seam twice answered NO for
`AppsFlyer | Financial Data Analyst - Temporary position (9 months)` partly because the role
"is also not a permanent job", under two different contracts, while the same pass accepted
three Taboola maternity-cover roles. Condition (3) now closes:

> Nor because the job is not permanent: a fixed-term, contract, temporary or maternity-cover
> position IS a job.

**Measured, 4 postings, one call each** (artifact
`tests/fixtures/classifier/2026-09-01-boundaries-b.json`):

| posting | verdict |
|---|---|
| `Check Point \| Revenue Operations Data Analyst - Temporary position` | **YES** — "a temporary position is still a job" |
| `Taboola \| Product Analyst - Taboola News (Maternity Leave Cover)` | **YES** — "fixed-term maternity cover counts as a job" |
| `WalkMe \| Product Analyst (Temporary Position)` | **YES** — "temporary (fixed-term, not internship)" |
| `AppsFlyer \| Financial Data Analyst - Temporary position (9 months)` | **NO** — FP&A, a named exclusion |

**0 of 4 lost for being temporary**, which is the failure `531` names, and the AppsFlyer row
stays withdrawn on the FP&A ground the operator himself named. Reported honestly: the model
**still volunteers** temporariness in that one reason ("and it's also a temporary/fixed-term
position"), after the FP&A ground. The clause stops the verdict, not the remark. `531` is
closed on the verdict; the remark is noted where the next reader will find it.

## Rejected alternatives

| alternative | why not, with the number |
|---|---|
| Demote `ppc`, `campaign`, `media buying` in `_QUALITATIVE_HINT` | It is an OUTPUT judgement and no title carries it: both worked examples are titled "Marketing Analyst", which the 08-30 record deliberately keeps `strong` and word-bounded so `marketing analyst` survives. A demotion here would also hit `Cato Networks`, which is IN. |
| Make "an advantage / a plus" decisive | Measured against the audit's own borderline set: it moves Migdal, Paz, CloudHiro and withfaye — four roles with a real reporting deliverable — off the board. Corroboration, not a test. |
| Put it in condition (1) instead | Condition (1) is about what the job's core IS; this is about who consumes the output, which is condition (5)'s subject. Keeping the two apart is what let the 08-30 record stay one sentence. |
| Ship `531` separately | Its own filing says the repair "costs a contract bump plus a measurement round, so it belongs with the next scope change rather than on its own". This is that scope change. |

## Consequences filed, not taken

* The seam still names temporariness as a secondary reason (`531`'s remark, above) — closed
  on the measured verdict, and worth re-reading if a fixed-term role is ever lost.
* `Global-e | Data Analyst (Chargeback)` **stays withdrawn**: the audit called its removal
  questionable under "the domain never decides", and the domain is indeed not the ground —
  the ground is that the output is dispute case-handling ("Review and represent chargebacks
  and retrieval requests"; SQL "Advantage"), which is this record's boundary. The 08-31
  record named it borderline and it is named here too.
* `NoTraffic | Global Compensation & People Analytics Manager` **stays withdrawn** on the
  same axis as Alma Lasers: "own commission administration, calculations and payout
  validation" and HRIS ownership are policy and execution. The HR domain is not the ground.


## 2026-09-11 addendum — the weekly delta audit's rows, judged on this boundary

*lane: `classifier`. Five of the 25 rows adjudicated on 2026-09-11 turned on this record; the
seam (`v3.0f84ab84`) read each once, and three times where it and this lane disagreed.
Artifact: `tests/fixtures/classifier/2026-09-11-delta-audit.json`.*

| posting | what the person produces | verdict |
|---|---|---|
| `Edikted \| Retail Data Analyst` | three analysis bullets open a nine-bullet list of which six are the analyst's own replenishment execution: "Place replenishment orders in the warehouse system based on data insights", "Coordinate shipments between the warehouse and retail locations", "Maintain and update replenishment files"; requirements ask only Excel / Google Sheets. Seam NO on three of three passes | **OUT** — the LTX shape; this lane's first read was IN on the opening bullets and the stable verdict plus the record's own test ("judge which the posting leads with") settled it |
| `Flex \| Material Planning Analyst` | "Create weekly purchase orders", "Daily review of RMA transactions", packing lists, item master; the reporting is "Assists in" and "May assist" | **OUT** (carried from the 09-04 audit, unactioned for a week) |
| `Qlik Israel \| BI Developer (Qlik Specialist)` | "מפתח BI ומנהל פרויקטים": planning, backend/frontend development and implementation of the project through every phase at the client's site, two years of technology project management mandatory; the one analysis phrase is a skills line | **OUT** — configuring a system and delivering it. The contrast kept IN the same day is `Experda \| BI Consultant & Data Developer`, whose stated output is dashboards and "proactively suggest metrics and insights" for its clients |
| `Bank Leumi \| Business Analyst, Corporate Banking HQ` | "אנליסט/ית מטה ופרויקטים": coordinating and tracking tasks and decisions, preparing management-meeting materials, producing conferences and welfare events; two analysis bullets ("תנתחו ותטייבו מידע", "תפתחו דוחות ניהוליים") serve that staff work; requirements are Excel and PowerPoint | **OUT** — the Migdal-precedent half the 09-04 audit named is outweighed by what the posting leads with |
| `Ferrero \| Business Analyst` (the body says Trade Marketing Analyst) | leads with "Manage and oversee the company's external merchandising operations" and "Maintain and monitor sales targets within commercial systems", then "Prepare analytical materials for recurring commercial meetings" | **IN, kept** — this lane read the merchandising-operations lead as execution; the seam answered YES on three of three passes ("analyzing sales/market data, tracking performance, preparing analytical materials") and a stable verdict is not overridden on a mixed posting |
| `ICE \| Analyst, Index Operations` | four of six bullets are index production (corporate-action validation, pricing verification, rebalancing checks); "Prepare report templates, with standard charts and data tables" and "prepare analyses in support of ad-hoc client requests" are named deliverables | **IN, kept** — the withfaye / CloudHiro line: a named report deliverable keeps a mixed operations role in; seam YES on two of three |

The rule the two kept rows add: **a stable seam verdict on readable text is not overridden by
one reader's weighting of a mixed posting.** Where this lane and the seam disagree, the seam
is asked twice more; a 3-of-3 answer stands, a 2-of-3 or a flap is resolved in the
conservative direction (a retraction is permanent), and the disagreement is recorded here
rather than settled by whichever read came last.
