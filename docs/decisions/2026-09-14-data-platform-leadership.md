# 2026-09-14 — leading or owning the data platform is OUT, whatever sits on top of it

*lane: `classifier` (`pipeline/seniority.py`, condition (2) of `LLM_RULES`). Extends
`docs/decisions/2026-08-28-analyst-scope.md` condition (2) and
`docs/decisions/2026-09-01-analytics-engineer-boundary.md`. It SUPERSEDES that record's
2026-09-11 addendum where the addendum read "the platform is the means" on a posting whose
own stated core IS the platform — `Jazz | Senior BI Developer`, kept IN there, is the worked
OUT example here. Written 2026-09-18, dated to the ruling. Artifact:
`tests/fixtures/classifier/2026-09-18-delta-audit.json`.*

## The ruling

The operator ruled on 2026-09-14:

> **Data-platform leadership is OUT.** A role that leads data engineers, or owns the data
> platform, is out **even when it also leads a BI team**. SuperPlay Head of BI stays
> withdrawn.

## The boundary, stated both ways

**OUT** — the posting's own core is *leading data engineers*, or *owning the ingestion,
warehouse, orchestration or data infrastructure itself*, and that stays OUT with a BI team,
a reporting function or an executive dashboard set on top of it. Either arm is sufficient on
its own: a role that owns the platform is out with no team led, and a role that leads data
engineers is out however much of its output is analysis.

**IN** — an individual contributor who owns the BI tool and the dashboards, with pipelines
beneath as the means (the BioCatch shape; `Central Bottling | BI Developer 17621` and both
Sunflower BI Developer rows stay the worked IN examples of the 09-01 record) — and a Head of
Analysis or Head of Analytics who leads **analysts** (Menora Mivtachim, Insightec, the
Phoenix Digital Analytics Team Lead, Clalit's `מנהל.ת מרכז מידע ואנליטיקה` 49965, Nebius Head
of Analytics, Pagaya BI Team Lead).

**The test**, and it is the 09-01 record's test applied one level up: does the posting weigh
*platform ownership* or *people-leadership of engineers* as its core? Weigh

> "Owning the platform is a huge part of this role" · "Build the platform from zero" ·
> "Ownership of production data infrastructure at scale" · "You're the architect" · "Lead and
> develop the BI team, **including a team of data engineers**"

against

> "Build dashboards that executives actually use" · "Shape company-wide KPIs" · "leading a
> team of data **analysts**".

Naming a dashboard somewhere still does not settle it, and neither does naming a pipeline.

## Why it had to enter the contract, measured

A ruling the seam cannot see is a hand-drain for ever. Under the contract live on 2026-09-18
(`v3.0f84ab84`) the seam was asked three times about Jazz and bought **YES / YES / YES**:

> "Despite building the data platform, the role's own output includes defining company KPIs
> and building executive/GTM/R&D dashboards."

That is the 09-11 addendum's own reasoning, reached freshly, because the rules text says the
pipelines beneath a reporting layer are the means and says nothing about a platform that is
the person's stated core. So the sentence ships **inside condition (2)**, which moves the
`CONTRACT` hash and re-judges what it invalidates without anyone remembering to.

**The candidate sentence was measured before it landed** (`--source ledger`-shaped run of the
production seam with the sentence spliced into condition (2), one call per row): every
published BI-developer / Head-of-BI / Head-of-Data / BI-team-lead / analytics-leadership row
in the ledger, plus the two withdrawn anchors the ruling must keep OUT. **20 rows, 2 moved.**

| | rows | outcome |
|---|---|---|
| moved accept → reject | **2** | `jazz\|senior bi developer`, `upwind\|head of data` |
| already OUT, stayed OUT | 2 | `superplay\|head of bi`, `guardio\|senior bi developer` |
| unchanged IN | 16 | Alma, BioCatch, Central Bottling 17621, Clalit 49965, Connecteam, Ecoppia, Insightec, Intelligent Business, Investing, Menora, Nebius ×2, Pagaya, Phoenix Digital Analytics Team Lead, Sunflower BI Developer, Sunflower BI Developer – Payments |

Both flips are the ruling's own arms, and each was re-read twice more: **NO/NO/NO** under the
candidate contract for both.

## The worked examples

| posting | what the posting puts its core on | verdict |
|---|---|---|
| `jazz \| senior bi developer` | "stand up Jazz's data platform end to end — ingestion, modeling, warehouse, orchestration, cost control", "Owning the platform is a huge part of this role", "Build the platform from zero", "You're the architect". The executive metric set and the C-level dashboards are the second half. **No team is led** — this is the ownership arm alone, and it is enough. | **OUT** (reverses the 09-11 addendum) |
| `upwind \| head of data` | "Lead and develop the BI team, including a team of data engineers and data analysts", "Build a scalable, reliable data platform", "Raise Upwind's data governance maturity". A BI organisation sits on top, which is exactly the case the ruling names. | **OUT** — the leadership arm |
| `superplay \| head of bi` | leads data engineering and owns the data architecture and tooling strategy | **OUT**, withdrawn 2026-09-13 and it stays withdrawn |
| `guardio \| senior bi developer` | pipelines, data models and infrastructure consumed by other engineers | **OUT**, and the 09-01 boundary already reached it |
| `biocatch \| business intelligence developer` | "main focal point for dashboard creation, BI tool usage, and data-driven decision-making across the organization"; ETL and DWH modelling are beneath it | **IN** — the IC arm |
| `menora mivtachim \| head of analysis`, `nebius \| head of analytics`, `pagayais \| bi team lead`, `phoenix financial \| digital analytics team lead`, `clalit \| מנהל.ת מרכז מידע ואנליטיקה 49965` | leads **analysts**, accountable for the analytical output | **IN** — leading analysts is not leading engineers |
| `alma \| head of data` | "Shape company-wide KPIs", "Deliver deep product, CS, and leadership insights"; no engineers led, no platform owned | **IN** — a "Head of Data" title decides nothing |

## What would reopen it

* A posting whose core is genuinely analysis, refused because it mentions owning a warehouse
  as one bullet among many. The clause that guards against that is the 09-01 record's: weigh
  which side the posting itself puts the core on. If the flip set of a future measurement
  carries such a row, the sentence is too broad and this record is amended, not ignored.
* A "Head of Data" who leads analysts only. That is IN today and must stay IN; Alma is the
  fixture row that proves it.
* The operator ruling otherwise.

## Rejected, with the number

* **Keeping the ruling as a record applied by hand lines.** Measured: the seam re-buys Jazz
  YES 3 out of 3 under the live rules, so every future Jazz-shaped posting costs a human
  reading for ever. The cost of the bump is the other side of the ledger: the bump
  re-supersedes the **882** cells that carry `v3.0f84ab84`, drained at the existing cap of
  250 NO + 150 YES a morning — roughly three mornings. The cap is **not** raised (2026-08-30:
  an uncapped drain starves the email window).
* **A vocabulary arm** (a `_HARD_EXCLUDE` or `_relevance` entry for "platform", "architect",
  "head of data"). Refused at 0 admitted: the rule is about which side a posting weights, and
  every one of the 16 unchanged rows above contains at least one of those words.
* **Making "leads engineers" the only arm.** The operator's words were "or owns the data
  platform"; Jazz leads nobody and is the worked OUT example.
