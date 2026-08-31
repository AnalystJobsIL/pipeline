# 2026-08-28 — what counts as an analyst role

*lane: `classifier` (owns `pipeline/seniority.py` and the `llm_cache` key scheme), with
consequences for `render`, `docs`, `registry` and `discovery` that are filed, not taken.*

This record exists because the product's scope has been enforced for eight days by a regex
and a system prompt, and stated nowhere as a decision. `README.md` and `CLAUDE.md` describe
it in a phrase — "experienced (≈3+ yrs) data-analyst / BI / analytics roles at Israeli
companies" — and `ARCHITECTURE.md` §7b describes the *mechanism*. Neither says what is out of
scope or why, so every session has re-derived the boundary from `_HARD_EXCLUDE` and argued
with it. Two of the four boundaries below turn out to be real product judgements that no
document had ever made.

## The spec, as it is now enforced

A role qualifies when **all** of these hold:

1. **The core of the job is analysis** — producing insights, reports, dashboards,
   business/product metrics. **The title does not matter**: a posting called "Data Scientist"
   counts when the work is product/business analytics, experimentation or A/B testing.
2. **It is not ML, data engineering or software engineering.** Analytics-flavoured data
   science is in; building and training models is out.
3. **It is a job, not a student placement.** Internships, student positions, apprenticeships
   and trainee programmes are out. There is **no minimum years of experience**.
4. **The employer is the workplace.** A staffing agency, recruitment firm or IT-outsourcing
   house advertising a role at a client company is out.
5. It is in Israel (`pipeline/israel.py`, per posting — not per company).

Finance (including FP&A, investment, credit, actuarial) and security (SOC, threat
intelligence, fraud) analysts are out. They are analysts; they are not this product's
analysts, and the reader is a data/BI analyst.

> **SUPERSEDED 2026-08-31 — `docs/decisions/2026-08-31-domain-scope.md`.** That paragraph is
> no longer the rule and was never quite what the code enforced. The operator's ruling: the
> DOMAIN never decides, because most data analysts are domain specific — a quantitative
> analyst in finance, fraud, sales, compliance or compensation is IN, and only **FP&A /
> accounting close, SOC / security monitoring and investigations, and market intelligence**
> are named exclusions. Everything else is decided from the description. Measured at 0 of 17
> verdicts moved.

Boundaries 3 and 4 changed today. The rest is a written-down version of what the code already
did.

## What changed, and the evidence for each

### The experience bar is removed (boundary 3)

**Was:** "roughly 3+ years", enforced three ways — `_JUNIOR` rejected junior/intern/
entry-level titles deterministically, `_sig_accept_nollm` required a senior marker, and
condition (3) of `LLM_RULES` told the model to answer NO for "~0-2 year roles".

**Now:** any experience level, except that an internship or student placement is still not a
job this reader can take. `_JUNIOR` splits into `_NOT_A_JOB` (still a deterministic reject)
and `_EARLY_CAREER` (no longer one); `_JUNIOR` itself survives unchanged in meaning because
`pipeline/rolecard.py` imports it for the card's chip, which is display and not a gate.

**The case that forced it.** `mećkano | Data Analyst | Petah Tikva` — a real Israeli SaaS
company hiring for itself, "Analyze data from various company systems and generate actionable
business insights… Build reports and interactive dashboards… complex SQL… Power BI, Tableau
or Looker", asking "At least 2 years of experience as a Data Analyst in a SaaS company". The
seam judged it NO on 2026-08-28 and was right under the old spec. It is the kind of role this
board exists to surface. `Peak Innovation | Data Analyst – JB-1608` ("1-2 years… A must!") is
excluded now for a different reason — see boundary 4.

**The cost, measured before shipping.** Deleting the seniority test from
`_sig_accept_nollm` moved **20 of the golden fixture's 252 title-only rows** from reject to
accept, among them `analytics ai engineer`, `מהנדס/ת נתונים` (a data engineer) and
`people operations & analytics` — because with no description, `_DATA_ANCHOR` matches the
word "data" in the title and nothing is left to disagree. That rule runs **only when the LLM
is unavailable**, which is exactly when nobody is watching. So the rule is not "seniority no
longer matters" but **less seniority evidence means more description evidence**: a
non-senior signal-tier title must now show analytics in its DESCRIPTION, which is the same
bar the bare-"Data Scientist" case has always had. Golden-fixture movement after that change:
**0 of 252**.

### Agency and IT-integrator postings are out (boundary 4)

**The case.** `Peak Innovation` is `pickpeak.co`; the JD behind
`career_opportunities/data-analyst-jb-1628/` is FIZE Medical's, and the application contacts
are `dikla@pickpeak.co`, `livnat@pickpeak.co`, `reoot@pickpeak.co`. `מטריקס`, `Logica-IT`,
`MatchPointIT` and `REAL DEV INC` are the same class: their own careers boards, listing other
companies' roles.

**Why out.** The board's promise is a role *at an Israeli company* the reader can evaluate —
the card carries the employer's name, sector, size and founding year, all of which would be
the agency's and none of which would describe where the person actually works. A reader who
clicks through finds a different company, or none.

**Why it is not simply a name list.** `pipeline/recruiters.is_recruiter` exists and is the
obvious thing to reuse. Measured 2026-08-28: it returns `False` for **all six** of the names
above — it matches recruitment words in a company NAME, and `Matrix`, `Logica-IT` and
`Peak Innovation` have none. So the rule is split:

- **The LLM decides**, on the evidence in the posting: `LLM_RULES` gains a fourth condition,
  and the tells are in the text (the JD names a different company as the workplace, or the
  contact belongs to an agency). It caught Peak Innovation, both Logica-IT roles and all
  three Matrix roles unprompted by any name list.
- **`_AGENCY_EMPLOYER` only demotes.** A strong title at one of the measured six becomes
  `signal` instead of `strong`, so it reaches the LLM rather than taking the keyword
  shortcut — exactly what `_BA_DOMAIN` already does for "Business Analyst, Salesforce". It
  **never rejects**, so a wrong name in that list costs one call, never a role.

**What this costs, stated plainly.** `מטריקס | מנתח/ת ומאייפנ/ת מערכות BI` was accepted on
2026-08-28 and is on the board. It is a real BI analyst role. It is now excluded, because
Matrix places it at a government ministry. That is the decision doing its job, not a
regression — but it is a role the board loses today, and if the operator disagrees this is
the paragraph to reopen.

**This decides only the classifier's half of `321@registry`**, which has been open since
2026-08-27 and which `docs/decisions/2026-08-27-it-services-employers.md` deliberately
declined to answer. The row-level question — should these companies be `active` at all —
is still `registry`'s and `discovery`'s, and is filed, not taken here.

## What would reopen this

- **The 2-year line.** "No minimum" is a wider door than "roughly 3+". If the board fills
  with roles the reader is over-qualified for, the answer is not to restore the bar but to
  surface the years signal on the card (`render` owns the chip; `pipeline/jdtext.py` already
  derives it) and let the reader filter.
- **A staffing firm hiring for itself.** The rule is about the *workplace*, not the industry.
  `EPAM Systems, Inc.` is an IT consulting house hiring a `Managing Principal / Senior
  Director, Data Analytics Consulting` **for EPAM** — it is deliberately not in
  `_AGENCY_EMPLOYER`. The seam rejected it anyway, as a sales/leadership role rather than an
  analyst one, but the keyword tier accepted it on `strong` + `senior` and never asked. See
  the precision gap filed below.
- **A measured false-negative rate on the title gate** that makes the vocabulary, rather than
  the LLM, the thing worth changing.

## Rejected alternatives

| alternative | why not |
|---|---|
| Extend `recruiters._CONFIRMED` with the six names | It is `discovery`'s file and a name list does not generalise: none of the six has a recruitment word in its name, so the next one will not either. The evidence is in the posting, so the judgement belongs where the posting is read. |
| Reject on the `_AGENCY_EMPLOYER` list directly | A wrong entry would silently drop every analyst role at a real employer. Demotion costs one LLM call and cannot lose a role. |
| Keep the experience bar and special-case `mećkano` | The bar is either the spec or it is not. A special case is a spec nobody can find. |
| Drop the junior reject entirely, interns included | An internship is not a job this reader can take; the board would be lying about what it lists. |
| Bump `KEY_VERSION` by hand for the new rules | It was bumped once, ever, in eight days. See `ARCHITECTURE.md` §7b: the key now digests the rules text and the model, so a scope change re-judges what it invalidates without anyone remembering to. |

## Consequences filed for other lanes

The product describes itself as **"experienced (≈3+ yrs)"** in `README.md`, `CLAUDE.md`,
`ARCHITECTURE.md`, the board page and the digest's own header ("N new **senior** analytics
roles"). Boundary 3 makes those strings untrue, and they are `docs`' and `render`'s to change
— a confident document that is no longer true is the failure this repo punishes hardest.
Filed in `docs/BACKLOG.md`, not edited here.
