# 2026-08-31 — the domain never decides, and every published row carries a verdict

*lane: `classifier` (`pipeline/seniority.py`, `pipeline/class_backfill.py`, the `llm_cache`
key scheme), with two hooks in `pipeline/run.py` and `pipeline/roles.py` applied under the
operator's ruling below and named in `HANDOFF.md`.*

Two decisions, taken together because both move the judgment contract and one bump is
cheaper than two.

## 1. The domain never decides (supersedes a paragraph of `2026-08-28-analyst-scope.md`)

**The operator's ruling, verbatim, 2026-08-31:**

> "the fact its finance or security don't matter. I expect classifier to get descriptions
> and understand from them if the role is relevant."
>
> "sales is fine. domain specific is fine, most data analysts are domain specific. FP&A, SOC
> and \"market intelligence\" specifically can be excluded, other than that description based
> is best"

**What forced the question.** The 2026-08-31 mail shipped `Chainalysis | Intelligence
Analyst - Fraud Researcher`. Asked whether a fraud-intelligence researcher is in scope, the
enforced rules and the written record disagreed: `docs/decisions/2026-08-28-analyst-scope.md`
says "Finance (including FP&A, investment, credit, actuarial) and security (SOC, threat
intelligence, fraud) analysts are out", while condition (2) of `LLM_RULES` said only
"Also NO for finance/FP&A/accounting, security/SOC, sales, and pure product-management or
architect roles". Neither is what the operator wants.

**What the rules say now.** Condition (2) keeps its ML / data-engineering / software-
engineering exclusions and replaces the categorical clause with a work test plus four named
exclusions:

> THE DOMAIN NEVER DECIDES: most data analysts are domain specific, so a role in sales,
> marketing, fraud, risk, compliance, HR / compensation, healthcare, retail, operations or
> any other field IS in scope when the person's own core output is analysis of measured
> data. Judge the WORK, not the field. Four kinds of work are out however quantitative they
> look, and these are exclusions, not examples: FP&A, budgeting, forecasting and accounting
> close; SOC / security monitoring and investigations; market intelligence; and pure
> product-management or architect roles.

The first draft of that clause read "…answer NO **only where the work itself is not
analysis**: FP&A, …", and put `market intelligence` in condition (5) among the qualitative
research outputs. Both were wrong for the same reason: they made the operator's three named
exclusions *derivable* rather than *stated*. A model that judges a particular FinOps posting
to BE analysis can conclude the first does not apply, and condition (5) closes with "judge
the WORK DESCRIBED, never the title", so a quantitative market-intelligence analyst passed
it. An adversarial read caught both before they shipped.

**Measured in three rounds, 30 calls, through the production seam** (`seniority._claude`,
same model, same schema):

| round | cohort | result |
|---|---|---|
| (i) the first wording | 12 of run 33387229779's flips whose subject matter the clause bears on — Chainalysis (fraud intelligence), both EY roles (compensation, financial services), Harel (insurance BA), Mizrahi-Tefahot (compliance/AML), Paz (trade marketing), Nestlé (commercial effectiveness), Computer Guard (retail loyalty), dentsu + Ashley Digital (marketing), SolarEdge (sales data), mećkano — plus 5 the morning rejected ON the domain: Medison (Total Rewards), KELA (threat intelligence), Micron (OSINT), Vectorious (accounts payable), LTX (commercial ops) | **0 of 17 moved** |
| (ii) the SHIPPED wording | the 13 of those with stored text, re-judged | **1 moved**: `Chainalysis \| Intelligence Analyst - Fraud Researcher` → NO, *"fraud/scam investigation and research (prompt engineering, web research on scammers) akin to security monitoring/investigations"*. Every marketing, sales, compensation and commercial-analytics YES held |
| (iii) the gate above | the 2 finance-titled postings the keyword tier rejects that carry a description | **both NO** — `Applied Materials \| Operations Finance Analyst` (FP&A), `Crossriver \| IT Compliance Analyst` |

The one verdict that moved is the posting that raised the question, and it moved because the
spec now says so rather than because anyone hand-picked it. Chainalysis needs no retraction:
its YES was made under `v3.da2cb878`, the bump supersedes it, and the drain re-judges it on
the next run — the mechanism working as designed.

**`CONTRACT` moves `v3.da2cb878` → `v3.7cb6831f`** (once, for both changes), and the drain
re-buys the verdicts made under the old one across the next unattended runs, bounded by
`CLASSIFY_REJUDGE_CAP` (250 NO) + `CLASSIFY_REJUDGE_YES_CAP` (150 YES) behind the 80-call
fresh reserve. Nothing here changes those caps, so the 48-hour email window is protected by
construction.

### The limit this rule does NOT reach, stated plainly

**It governs what reaches the model.** The title gate above it still rejects a bare
`Financial / Compliance / Security / SOC / Credit / Equity / Investment Analyst` on the
`keyword` path — no description read, no appeal — so *"the domain never decides"* is true of
the LLM tier and **not** of `_HARD_EXCLUDE`. The measurement in round (i) could not have
caught this: every posting in it had already passed the gate.

The gate is left alone, and that is a decision rather than an oversight:

* **0 of the 116 `excluded`-tier rejections** in the exhaustive 401-posting title-gate
  measurement (2026-08-28, `ARCHITECTURE.md` §7b) was a genuine analyst role;
* both live finance-titled postings that carry a description are NO under the new rules
  (round iii);
* **28 live titles** are affected in total, and 20 of them are SOC or security roles the
  operator names as out.

Re-derive the 28:
`python -c "import json,re;from pipeline import seniority as s,israel;D=re.compile(r'\b(financial|finance|compliance|investment|credit|equity|budget|treasury|actuarial|billing|governance|infosec|information security|security|soc)\s+analyst\b',re.I);p=set();\
[p.add((str(j.get('company') or k or '').strip(),str(j.get('title') or '').strip())) for f in ('scraped_cache.json','discovered_cache.json') for k,v in (json.load(open(f,encoding='utf-8'))).items() if isinstance(v,list) for j in v if isinstance(j,dict) and israel.is_israel_job(j)];\
print(sum(1 for c,t in p if s._relevance(t.lower(),c.lower())=='excluded' and D.search(t)))"`

What would reopen it: a measured false negative in that tier. Filed as `529@classifier` with
the measurement it needs, because loosening a gate that three measurements call precise, on
no evidence, is how this repo loses a morning.

**One inconsistency the measurement found and this rule does not resolve.** `EY | אנליסט
שכר והטבות` (compensation benchmarking) is YES and `Medison Pharma | Senior Total Rewards
Analyst` is NO, both under both contracts, and the seam's own reasons draw the line between
*analysing* compensation data and *managing* compensation policy. That is a defensible line
and it is not written anywhere; it is filed rather than legislated, because a rule invented
to settle two postings is a rule nobody can find.

## 2. A published row is never "included but never judged"

`cloud_state/roles.csv` published **33 of 167 rows with an empty `class_decision`** on the
morning of 2026-08-31 — every one of them `closed`, 30 carrying a real job description.

**Why the existing machinery could not reach them.** `rec["class"]` has exactly one writer
(`pipeline/roles.py`, from `by_key` = the jobs this run fetched and accepted), so a role that
closed before that field existed (2026-08-25) is never in `merged` again and its cell stays
empty for ever. The contract drain cannot reach them either — it re-judges RECORDED verdicts,
and these have none. **Nothing in the system was going to fix this**, and the count only
grows: every role that closes during an outage joins it.

The operator's rule is that closed roles belong in the dataset. They do — and "included"
must not mean "never judged", because three of his own examples (`AppsFlyer | Senior FinOps
Analyst`, `AppsFlyer | Senior Product Manager - Analytics`, `Amazon | Sr GTM SSA Analytics`)
are rows the current contract rejects.

**What ships.** `pipeline/class_backfill.py` judges every verdict-less ledger record under
the current contract, once, and hands `Ledger.record_run` a `{role_id: class}` map it applies
to EMPTY cells only. It runs two ways, deliberately the same code: from `pipeline/run.py`
after both classify sites (so the column cannot silently refill, and no fresh role loses a
call slot to a backlog), and as `python -m pipeline.class_backfill` for a backlog that should
not wait for a cron.

Measured this session: **42 verdict-less records, 41 judged (17 YES, 24 NO) + 1 answered by
the keyword tier for free, 0 held; empty `class_decision` 33 → 0.**

The shipped queue is narrower than that first pass: `candidates()` now takes only the
statuses the dataset PUBLISHES (`open`/`closed`). The three excluded statuses were kept at
first on the reasoning that they would be "cheap (a keyword reject or a cache hit for
most)" — measured, **9 of the 42 were purged or withdrawn and all 9 were `strong` relevance**,
so every one bought a paid call, 21 % of the pass, to fill a cell no reader can see. Seven
were staffing agencies the pipeline had already purged as never ours. A rationale a
measurement contradicts is not a rationale.

**A NO does not vanish by itself, and this is where an adversarial read earned its keep.**
18 of the 24 rejects were on published rows. Every one was re-read against the seam's own
reason and its stored description, and **14 were given a line** in
`cloud_state/roles_retractions.jsonl` — the `roles` lane's hand-curated input, reason and
evidence on the line. **Four were lifted:**

| lifted | why |
|---|---|
| `Minute Media \| Data Scientist` | Condition (1) says a posting called "Data Scientist" **counts** when the work is experimentation or A/B testing; this JD says *"Strong causal-inference and experimentation skills. **This is the core of the role.**"* The verdict read the modelling half only — and the role had been **emailed on 2026-08-23** |
| `Mobileye \| Experienced Data Analyst` | 770 chars, `looks_like_jd` False, quality `snippet` |
| `Questar Auto \| Senior Data Scientist` | 1,800 chars, quality `snippet`, cut at the capture cap |
| `Central Bottling \| BI Developer 17621` | *"Power BI dashboards, reports, semantic models"* beside the ETL: where the analytics-engineer line falls is a product boundary no decision record draws (`532`) |

The two snippet cases are the general rule, not two exceptions: **everywhere else in this
seam a verdict on text that is not a JD is provisional** — served bare, re-judged the day the
description arrives — while a retraction is permanent and nothing re-checks it. All four keep
an honest `class_decision=reject` in the dataset and are revisable the day `464@jd-text`
fills them.

Two of the 14 that stand are borderline and are named rather than buried: `NoTraffic | Global
Compensation & People Analytics Manager` (judged comp/HR *management*) and `Global-e | Data
Analyst (Chargeback)` (judged dispute *operations*). Lifting either is deleting its line.

One reason string was rewritten rather than quoted: the seam twice called
`AppsFlyer | Financial Data Analyst - Temporary position (9 months)` out partly because it is
temporary. **Temporariness is not a ground** — boundary 3 covers student placements only, and
the same pass accepted three Taboola maternity-cover roles — so the line states the FP&A
ground, which stands alone, and says the other is not one. That the model reaches for it
twice is a gap in the rules, filed as `531` rather than fixed here: it changes no verdict
today, and a third contract bump would cost a third measurement round.

Next run: **167 → 153 rows, 0 empty `class_decision`, reconciliation `holds: True`**
(rehearsed on a scratch copy of `cloud_state`).

## Rejected alternatives

| alternative | why not, with the number |
|---|---|
| Judge the backlog through `clf.classify` in the existing loop | 30 of the 33 are historical ACCEPTS with real JDs — a fresh cohort at a ~100 % YES rate, over `MASS_YES_RATE` (55 %), which would quarantine the run's **whole fresh cohort**: the morning's real roles withheld on the strength of a backlog pass. `judge_backfill` is a separate cohort for exactly this reason (`_suspect` subtracts it). |
| A one-shot CLI and a tripwire, no in-run hook | Fixes 33 once and re-opens the same gap the next time a role closes while the seam is down. The `seniority` column needed **both** halves (`roles.py:1146` in-run + `backfill-seniority` CLI) for the same reason. |
| Look the verdict up in `llm_cache` at export time | The export is contractually spend-free and record-derived; ≥1 of the 33 (`Taboola | Product Analyst (Maternity-Leave Replacement)`, 0 chars) has no cache row under any key and would stay empty for ever, and a contract bump would silently rewrite published cells with no provenance. |
| Exclude a `reject` row automatically in `build_rows` | A rules flip could then mass-remove published rows with no human in the loop — the failure the mass-purge hold exists to catch elsewhere. A retraction is "a human said so", and it stays that way; the seam prints an alarm naming the count instead. |
| Keep the categorical domain clause and special-case Chainalysis | The clause is either the spec or it is not; a special case is a spec nobody can find (the same reasoning that retired the experience bar). |

## Consequences filed, not taken

* **`withdrawn` now carries two meanings** (`530@roles`). The dataset's meta note says a
  withdrawn row "was published in error"; 14 of the 17 withdrawn rows were correctly
  published under a retired spec and are out of scope under the current one. The reason
  string on each line says so; the note a downloader reads does not. **Seven of the 14 were
  emailed to subscribers**, so the note is also the only place that could say what a
  withdrawal does and does not claim about a delivered mail.
* **The BI-developer boundary** (`532@classifier`): a role building Power BI dashboards,
  reports and semantic models alongside ETL is neither plainly "BI … counts" (condition 1)
  nor plainly data engineering (condition 2). Three of the 18 sat on it; one was lifted for
  that reason. It deserves the treatment the agency boundary got in the 08-28 record.
* **Temporariness is not a ground and the rules never say so** (`531@classifier`).
* **The keyword tier's domain rejections** (`529@classifier`), above.
* The EY / Medison compensation line, above.
* `NVIDIA` and `NVIDIA AI` are two company strings for one employer, so the same posting
  bought **two** LLM calls this morning (12:03:28Z and 12:03:41Z). Classification sees two
  jobs because the cache key is `company|title`; the fix is identity, which is `roles`'
  (`533`).
