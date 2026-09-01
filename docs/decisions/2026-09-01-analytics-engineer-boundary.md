# 2026-09-01 — a BI role is IN when someone outside the data team consumes what it delivers

*lane: `classifier` (`pipeline/seniority.py`, the `llm_cache` key scheme). Closes
`532@classifier`, filed 2026-08-31 and named there as deserving "the treatment the agency
boundary got in the 08-28 record". Extends `docs/decisions/2026-08-28-analyst-scope.md`
conditions (1) and (2); it replaces nothing.*

## What forced the question

The operator's row-by-row audit of the published dataset produced 57 findings, and 27 were
BORDERLINE. Eleven of those sat on one line: a role that builds ETL, dbt models or a
warehouse **and** the reporting layer above it is neither plainly "BI … counts"
(condition 1) nor plainly "data engineering … is out" (condition 2). The 08-31 backfill had
already tripped over it — it withdrew both Guardio rows on that reading and **lifted**
`Central Bottling | BI Developer 17621` on the opposite one, in the same pass, and said so.

Deciding it one unreviewed LLM call at a time is how the board loses real BI roles or keeps
engineering ones.

## The boundary

> Building ETL, pipelines or data models does **not** by itself make a role data
> engineering. Ask **who consumes what the person delivers.** If a reporting or insight
> layer that business, commercial or product decision-makers consume — dashboards, reports,
> semantic models, KPIs, analyses — is part of their own stated output, the role is **IN**
> and the pipelines beneath it are the means. It is **OUT** when the delivered thing ends at
> datasets, pipelines, platform, infrastructure or model-training data, consumed by other
> engineers, data scientists, researchers or product features, with no reporting or analysis
> output of the person's own.

And the clause that stops it being a keyword rule: **naming a dashboard somewhere does not
settle it — weigh which side the posting itself puts the core on.**

It ships as a sentence inside condition (2) of `LLM_RULES`, so it enters the `CONTRACT` hash
and re-judges what it invalidates without anyone remembering to.

## Worked examples, from the stored JDs

| posting | the deliverable, and who consumes it | verdict |
|---|---|---|
| `Central Bottling \| BI Developer 17621` | "Develop and maintain Power BI dashboards, reports, semantic models" + "Partner with business stakeholders … translate them into impactful BI solutions", with SSIS/ADF beneath | **IN** |
| `Ecoppia \| Senior BI Developer` | "Analyze data and create business insights" + Tableau reports, "end-to-end BI solution" for "business stakeholders across the company", ETL beneath | **IN** |
| `Sunflower \| BI Developer` and `\| BI Developer, Payments` | Looker dashboards "consumed daily by Finance, Payments, Risk and Fraud"; dbt/BigQuery named as the means, Data Engineering a separate partner team | **IN** |
| `NVIDIA \| Senior BI Analyst` | "end-to-end Business Intelligence solutions" and Tableau/Power BI for "internal business and IT partners globally" | **IN** |
| `Guardio \| Senior BI Developer` and `\| Senior BI Engineer` | "building the data pipelines that power our cybersecurity data infrastructure"; "foundational datasets" for "analysts, researchers and security experts" and "product features". **Zero dashboards in 3,300 characters** | **OUT** |
| `Similarweb \| ML & Big Data Analyst` | "ensure the quality of Similarweb's data and algorithms", "evaluate and improve novel algorithms produced by the data scientists in your team" | **OUT** |
| `Aidoc \| AI Data Analyst` | "Mining the optimal data for our datasets… Evaluating our algorithms' performances"; dataset development for AI training | **OUT** |

**The two the reviewer said the rule could not separate — and it does not.** An adversarial
read of the draft objected that Central Bottling and Ecoppia are the same role wearing two
descriptions, and that the record wanted one IN and one OUT. It was right about the reading
and the answer is that **they land together, IN.** Ecoppia was the audit's OUT and the
2026-08-30 record's seam reject; on its own text it says "Analyze data and create business
insights" and ships Tableau reporting to business stakeholders, which is condition (1)
verbatim. The audit's finding is **refuted**, and a rule whose two worked examples it cannot
tell apart would have been the wrong rule, not the wrong pair.

**The example that earns the last clause.** `Parametrix | Technical Data Analyst` *does*
name dashboards — "to help the Product and Sales teams see global cloud stability and
exposure at a glance" — and also says of itself: *"This role sits right between Data
Engineering and Business Intelligence, perfect for someone who wants to build, not just
analyze."* Presence of the word "dashboard" is therefore not the test; the posting's own
weighting is. See the reinstatement below for how this one actually resolved.

## Analytics leadership, which is the same question one level up

Condition (1) already ends "BI, business/product/marketing/growth analytics, and analytics
leadership **all count**", and the audit called two leadership rows OUT as "management, not
analysis". That reading would delete the clause. The line that reconciles them, and it is
the one the 08-28 record's EPAM example already draws:

- **IN** — the leader is accountable for the analytical OUTPUT. `SuperPlay | Head of BI`:
  "scalable reporting and insights on media acquisition channels, user usage, and business
  metrics"; `Guardio | Director of Data`: "Provide insights and analytics on media
  acquisition channels, user usage, business, and product metrics".
- **OUT** — the leader is accountable for commercial results and staffing.
  `EPAM | Managing Principal / Senior Director`: "Own and grow a multi-million-dollar
  engagement portfolio ($20M+ annually)", "margin, utilization, bill rate". It passes
  condition (4) — EPAM is hiring for EPAM — and fails condition (1).

This also settles the `EY | אנליסט שכר והטבות` vs `Medison | Senior Total Rewards Analyst`
inconsistency the 08-31 record filed rather than legislated: the same axis, one level down.
`Alma Lasers | Total Rewards & People Analytics Lead` is OUT here for the Medison reason —
"Run the global compensation cycle end to end", "Own the HRIS (HiBob) as system owner" — and
the HR domain is explicitly **not** the ground.

## Measured, through the production seam, before shipping

24 published rows judged once under the new rules, `sonnet`, one call each; the "before" leg
is the verdict deciding each row today. Artifact:
`tests/fixtures/classifier/2026-09-01-boundaries.json`. Re-derive:

```bash
python tools/measure_scope_rule.py --source ledger --only "<role_id>,…" --workers 4
```

**Moved: 3 NO→YES, 7 YES→NO; 12 held; 2 had no prior verdict.** Every NO→YES is this
boundary or the leadership line working — Central Bottling, Ecoppia, SuperPlay — and no
quantitative analyst role moved to NO for being qualitative or for its domain.

**Two verdicts disagreed with the session's own adjudication, and both were adjudicated
rather than rubber-stamped** (the abort rule was >3):

- `Parametrix | Technical Data Analyst` — seam **YES**, session had it OUT. Its stored text
  is cut mid-word at the 1,800-character capture cap, so the qualifications were never read.
  A verdict on partial text is provisional everywhere else in this seam while **a retraction
  is permanent and nothing re-checks it** (the 08-31 record's own rule, which lifted two rows
  for exactly this). Its retraction line is deleted in this commit, so the next run **lifts
  the withdrawal** and the row returns. Stated precisely, because a lift is not a re-verdict:
  nothing rewrites `rec["class"]` for a closed role, so it comes back reading
  `class_decision=reject` under the retired contract until `544@roles` lands. Central
  Bottling — the NO→YES this record was drawn for — is frozen the same way and has no line to
  lift, which is the clearest argument for `544` in the tree.
- `Zipher | Data Scientist` — seam **YES**, an evidence pass had it OUT and called it its own
  least confident call. "Build dashboards, reports, and internal tools that help teams
  understand product performance" is condition (1); the accept **stands**.

## The limit, stated plainly: the title gate never asks

This rule admits the hybrid the industry calls an **analytics engineer**, and
`_HARD_EXCLUDE` rejects that exact title on the `keyword` path with no description read and
no appeal — `_relevance("senior analytics engineer") == "excluded"`, and the existing
demote-on-a-strong-signal escape cannot fire because `_STRONG` does not match it either. So
this boundary is true of the LLM tier and **not** of the gate above it, exactly as
"the domain never decides" was on 08-31.

Measured today: **3 live Israeli titles** are affected — `Connecteam | Senior Analytics
Engineer`, `Extreme | BI System Analyst`, `INGIMA | BI Systems Analyst … (5471)` — and only
the first is a case this record would newly admit; the INGIMA row is out on the consultancy
boundary anyway. Two independent gate audits run by the orchestrator the same day — **its**
counts, not re-derived by this lane: 3,265 cached rejected titles, then 1,142 rejects
carrying 300+ characters of text, a **~0.35 %** flag rate — surfaced 4 candidate misses.
Judged through this seam, **3 of the 4 are real** (below), so the seam-confirmed rate over
that second population is ~0.26 %. Two of the three carry **no analytics signal in the title
at all**, which no demotion reaches — only reading the description would.

**And then the measurement arrived, the same afternoon.** Those audits handed over 4
confirmed misses that are alive and already carry cached text, so they were judged through
the production seam under this record's own contract (4 calls, artifact
`tests/fixtures/classifier/2026-09-01-gate-false-negatives.json`): **3 of the 4 are YES** —
`Calculum | Junior Data/Financial Analyst` (rejected by the finance hard-exclude),
`IAI | תהליכי בקרה ו-AI` and `Zoll Medical | Business Operations, CMS` (both rejected as
having no analytics signal in the title at all). `Elbit | Senior Data Product Owner` is a
correct reject.

**The gate is still left alone in this commit, and now for a stated reason rather than for
lack of evidence.** One of the three (Calculum) is the demotion's class and is the measured
false negative `529@classifier` names as its own reopening condition. The other two are
`none`-verdict titles that **no vocabulary demotion can reach** — only reading the
description would, which is a different mechanism with a different cost. Shipping a gate
change here would mean designing that mechanism, re-running the 252-row golden fixture and
pricing the extra LLM volume, on the same evening as a contract bump and 22 withdrawals;
this repo's rule is that a gate three measurements call precise is not loosened in a hurry.
The evidence is recorded in `542@classifier` with both classes named separately, so the next
session inherits a measurement rather than a task — and Elbit's posting leaves the 21-day
cache around 2026-09-06, which is the clock on re-deriving it.

## Rejected alternatives

| alternative | why not, with the number |
|---|---|
| Decide it on the title — `bi developer` IN, `analytics engineer` OUT | Both titles sit on both sides in this corpus: Guardio's OUT row is titled "Senior BI Developer" and Central Bottling's IN row is titled "BI Developer". A title cannot carry a judgement about who consumes the output; that is the same finding that kept `market research` out of `_HARD_EXCLUDE` on 08-30. |
| Count the ETL bullets against the dashboard bullets | Every IN example here would fail it: Central Bottling, Sunflower and NVIDIA all list ETL first. Ordering is a layout accident, not a statement about the deliverable. |
| Put Central Bottling and Ecoppia on opposite sides, as the draft did | They are the same role on the evidence — an adversarial read found this before it shipped, and a rule that cannot separate its own two worked examples is not a rule. |
| Extend `_STRONG` with `analytics engineer` so the gate stops rejecting it | It would enable the `strong` + `senior` keyword fast-accept, which accepts a title **blind** with no description read — admitting "Senior Analytics Engineer" unread is a worse error than refusing it. A demotion, not a promotion, is the shape this needs, and it needs its own measurement (`542`). |
| Leave `532` open for another session | It was filed on 2026-08-31 and had already produced two contradictory verdicts in one pass. The audit put eleven rows on it. |

## Consequences filed, not taken

* **`542@classifier`** — the title gate refuses `analytics engineer` / `bi system analyst`,
  with the two gate audits' numbers and the 3 live titles.
* **`541@classifier`** — superseded verdicts were ordered by contract *hash*, not by date;
  this bump would have served an older verdict for 336 jobs, 12 of them disagreeing. Fixed
  in this commit, filed for the record and for the `tools/` copy of the same bug.
* **Guardio's two rows are one Comeet posting under two titles** (3,300 and 3,299 characters,
  byte-identical but for the title word), so both `role_id`s carry a withdrawal — the same
  duplicate-identity shape as `533@roles`.
