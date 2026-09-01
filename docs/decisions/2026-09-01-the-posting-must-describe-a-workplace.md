# 2026-09-01 — a posting that never describes its own workplace is advertising somebody else's job

*lane: `classifier` (`pipeline/seniority.py`). Extends condition (4) of
`docs/decisions/2026-08-28-analyst-scope.md`, which it does not replace. It decides the
CLASSIFIER's half only; whether these companies should be `active` rows is still
`321@registry`, open since 2026-08-27 and untouched here.*

## What forced the question

Condition (4) has said since 2026-08-28 that "a staffing agency, a recruitment firm or an
IT-outsourcing house advertising a position at a CLIENT company" is out, and that "the tells
are in the text — it names a different company as the actual workplace, or the application
contact belongs to an agency". Both tells are **explicit disclosures**, and the operator's
audit surfaced seven postings that disclose neither and are still placements: INGIMA, Compie,
entrypoint, G-Stat, TechBiz, TLVTech, Peak Innovation. The rule as written reaches Matrix
(which names the ministry) and Peak Innovation (whose CV address is `@pickpeak.co`) and
misses the rest.

## The boundary

Three further tells, **strongest together**:

1. a **requisition number** carried in the title or body — `Data Analytics Team Lead (5485)`,
   `Data Analyst -5664`;
2. the workplace given only as an **unnamed client** — "a leading government ministry",
   "large, complex, multi-system organizations", "partner with senior stakeholders across the
   organization";
3. a requirement for experience in a **client's industry** where the posting never describes
   an industry of its own — "Experience in the insurance or financial services industry",
   "רקע פיננסי/בנקאי – יתרון".

And the question that makes them one rule rather than a list:

> **Does the posting describe a workplace at all?** A company hiring for ITSELF says what it
> builds, what the team does, or what systems the person would own. A posting that never once
> describes the advertiser's own product, team or systems, while carrying those tells, is
> advertising somebody else's job.

That is the generalisable half — it survives the next agency, which will have a different
name, a different requisition format and no `@agency` address. It ships inside condition (4)
of `LLM_RULES` and enters the `CONTRACT` hash.

## Why the model can apply it, and why the name list is not extended

The seam is sent title, company, location and description — **not** a firmographic record. A
rule phrased "the burden flips at a consultancy" would require the model to know the
employer's business model, which it cannot see; an adversarial read of the draft caught that
and the rule is written entirely on **text the model receives**.

`_AGENCY_EMPLOYER` is deliberately **not** extended with the five new names. Measured: all
five already reach the LLM (`strong` relevance, seniority `unknown`, so the strong+senior
fast-accept never fires), so the demotion would buy nothing for routing — and unlike
`_QUALITATIVE_HINT`, `_AGENCY_EMPLOYER` is **excluded from the no-LLM rescue**
(`seniority.py`), so a wrong name there becomes a deterministic reject on any breaker-open
morning. The 08-28 record's "a wrong name costs one call, never a role" does not transfer to
a name that is added today.

## Worked examples, from the stored JDs

| posting | tells | own workplace described? | verdict |
|---|---|---|---|
| `מטריקס \| מנתח/ת ומאייפנ/ת מערכות BI` | names the client outright: "למשרד ממשלתי מוביל בירושלים"; contact `jobs@matrixdna.ai` | no | **OUT** |
| `Peak Innovation \| Credit Risk Analytics Team Lead` | "Send your CV to: Ahinoam@pickpeak.co"; "global cross-functional stakeholders", no employer named | no | **OUT** |
| `INGIMA \| Data Analytics Team Lead (5485)` | req number; "across the organization"; "Experience in the insurance or financial services industry" | **not one sentence** | **OUT** |
| `entrypoint \| Data Analyst -5664` | req number; "large, complex, multi-system organizations" | no | **OUT** |
| `Compie \| Data Analyst` | "Experience from the banking, financial, or credit card industry"; client-side control tooling; Banking industry tags on an IT-services firm's post | no | **OUT** |
| `G-Stat \| אנליסט/ית דיגיטל` | "רקע פיננסי/בנקאי – יתרון"; Glassbox, a client-deployed platform; a 505-char requirements stub with no responsibilities section | no | **OUT** |
| `EPAM \| Managing Principal / Senior Director` | none — clients named as coverage, not as the workplace | **yes**: owns EPAM's own portfolio, margin, utilization and 15+ consultants | **IN on (4)** — and out on condition (1), see the analytics-engineer record |
| `Oak \| Product Analyst` | none | yes: own product, own $60M seed, "own Product Ops at Oak" | **IN** |

**`TLVTech | Data Analyst` is the honest weak case and is recorded as one.** Its text names
no client, carries no requisition number and gives no agency address; the only tell is
marketing copy — "building exceptional products … for the world's most admired companies".
Under this rule alone it would stay IN. It is withdrawn on **condition (2)** instead: the
role requires Node.js and React and asks the person to "bridge the gap between data insights
and application development", which is half software engineering. The seam, asked, answered
NO — but its reason asserted "TLVTech is a staffing/tech recruitment firm", a fact **not in
the posting**. That is the failure mode this rule is written to avoid, and it is why the
withdrawal cites the engineering ground, which stands on the text.

## `Team8 | Briya - Medical Data Analyst` is NOT this rule

The JD names a different company as the workplace throughout — "We are seeking an experienced
and dynamic medical data analyst to join **Briya**" — which fires condition (4) read
mechanically. It should not. Team8 is a venture builder whose Comeet board carries the
companies it co-founds; it is none of the three things condition (4) enumerates, and Briya is
a portfolio company, not a client. The role is **IN**, and the defect is that the record's
`company` is "Team8" so the reader is told the wrong employer — the `Faye`/`withfaye` shape.
Handed to `roles` with the evidence rather than rejected here; a real employer is never
"unidentifiable".

## Measured

**Six** of these rows are in the 24-row pass described in
`docs/decisions/2026-09-01-analytics-engineer-boundary.md`
(`tests/fixtures/classifier/2026-09-01-boundaries.json`): INGIMA, entrypoint, Compie,
G-Stat, TLVTech and EPAM. **Four moved YES→NO** — INGIMA, entrypoint, Compie, G-Stat — and
each seam reason names the tells above rather than the company's name; TLVTech and EPAM
held NO.

**`מטריקס`, `Peak Innovation` and `Oak` were NOT re-judged this session and no fixture
contains them.** Their verdicts here are adjudications on their stored JDs against the
rule, supported by the earlier measurements that already named them — Matrix moved YES→NO
in `docs/decisions/2026-08-30-quantitative-scope.md`, and Peak Innovation is named in the
08-28 record. Oak is an accept nothing has disturbed. Saying so matters: a record that
cites a fixture for a row the fixture does not contain is the failure this repo punishes
hardest, and an adversarial read caught exactly that sentence here.

## Rejected alternatives

| alternative | why not, with the number |
|---|---|
| Add the five names to `_AGENCY_EMPLOYER` | Measured: all five already reach the LLM, so it changes no routing; and the list is excluded from the no-LLM rescue, so a wrong entry becomes a silent deterministic reject on a breaker-open morning. Cost: a role. Benefit: nothing. |
| Reuse `pipeline/recruiters.is_recruiter` | Measured 2026-08-28: `False` for all six names it was tested on; it matches recruitment words in a NAME, and `Matrix`, `Compie` and `entrypoint` have none. `docs/decisions/2026-08-27-it-services-employers.md` measured the same rule against the 2,703-name catalog and found the rule and the source do not intersect at all. |
| "The burden flips at a consultancy" (the draft) | The seam is never told what the employer is. An adversarial read killed this before it shipped; the rule is now written on text the model receives. |
| Reject any posting carrying a requisition number | Real employers number requisitions too — `Central Bottling \| BI Developer 17621` is IN, and its number is in the title. The tells are load-bearing only together, and only against a posting that describes no workplace of its own. |
| Decide the row instead of the posting (park the companies) | That is `321@registry`, deliberately not taken here: the 08-27 record measured that the class has to be decided for all thirteen rows at once, and it needs `registry`. |
