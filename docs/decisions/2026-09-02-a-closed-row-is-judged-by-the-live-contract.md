# 2026-09-02 — a closed row is held to the live contract, exactly as an open one is

*lane: `classifier` (`pipeline/seniority.py`, the `llm_cache` key scheme). Applies the
operator's acceptance bar — "every published row deemed relevant, including no longer active"
— to the half of the dataset nobody was applying it to. It overturns one sentence of
`docs/sessions/2026-09-01-classifier.md` §5 and nothing else.*

## The ruling

> A row the dataset publishes must be relevant, whatever its `status`. **A closed row judged
> NO under the contract that is live today, on that row's own readable text, is withdrawn
> with its reason, exactly as an open one is** — its `reject` cell is not a substitute,
> because a `reject` cell removes nothing: the row stays in `roles.csv` for the whole 90-day
> window with `class_decision=reject`, which is the dataset asserting in public that it is
> publishing a role it has judged out of scope. The verdict that decides is the **live
> contract's**, never the cell: a cell can be a frozen verdict from a retired contract
> (`544@roles`), and on this sweep the two differ on exactly one of the four rows.

**Both qualifiers earn their place, and an adversarial pass put them there.** Without *"on
that row's own readable text"* the rule reaches two more rows in this very commit —
`Ballerine` and `Gamida Cell` are both closed AND answered NO by the live-contract seam, and
both are correctly still published: Ballerine's stored capture is 2,671 characters of site
chrome in front of a 1,327-character JD that answers **YES** on its own, and Gamida's is a
6,000-character page-slice carrying a second posting's bullets. A rule scoped only to the
`class_decision=reject` column would have read as covering them, and a reader applying it next
month would delete both. `567@jd-text` is the guard; this sentence is the fence until it lands.

## The sweep, and why the wording is load-bearing

All **151** published rows on 2026-09-02 (`cloud_state/roles.csv`, after the 09-02 digest,
run 33613841435). Four carry `class_decision=reject`; all four are `closed`. Each was judged
once through the production seam under `v3.0f84ab84` on the text it carries today —
artifact `tests/fixtures/classifier/2026-09-02-deferred.json`:

| row | live-contract verdict | action |
|---|---|---|
| `mobileye \| experienced data analyst` | **NO** — validation infrastructure for the REM ML mapping system | withdrawn |
| `questar auto \| senior data scientist individual contributor` | **NO** — builds and deploys predictive models and DS pipelines | withdrawn |
| `minute media \| data scientist` | **NO** — ML models and an experimentation platform | withdrawn |
| `parametrix \| technical data analyst tel aviv` | **YES** — dashboards and data-quality analysis consumed by Product and Sales | **NOT withdrawn** |

**Parametrix's own text is disclosed here rather than left flattering.** Its 1,800 characters
open with site navigation (*"Solutions Data Center SLA Cyber and Tech E&O Enterprise Risk
Cloud Outage Analytics Resources…"*), are cut mid-word at the capture cap
(*"…handled both the analysis and the preparati"*), and the posting says of itself *"This role
sits right between Data Engineering and Business Intelligence, perfect for someone who wants
to build, not just analyze"* alongside *"Own and optimize lightweight ETL/ELT processes (dbt,
Airflow)"*. It is a genuine analytics-engineer boundary case, and it is kept because it also
names dashboards *"to help the Product and Sales teams see global cloud stability and exposure
at a glance"* — a reporting layer non-engineers consume, which is boundary (a)'s test. Saying
so matters because the same commit refuses to withdraw `Ballerine` on a capture of the same
navigation-prefix shape: the two are treated consistently, and this table would read as though
one were clear-cut if the shape went unmentioned.

**Parametrix is why the rule says "judged NO under the live contract" and not "carrying a
reject cell".** Its cell reads `reject` under a contract this repo retired on 2026-09-01, and
it reads that way because a closed role never re-enters `merged`, so nothing rewrites
`rec["class"]` for it (`543@roles`, `544@roles`). A ruling written on the cell would have
deleted a role the seam accepts — the second time in two days that a plausible-looking
retraction line was one measurement away from removing a real posting (`545@roles` was the
first). Withdrawing it would also have reversed the lift the 09-01 session had just paid for.

**Minute Media is the one reversal.** The 2026-09-01 session adjudicated it OUT and wrote
*"its honest reject stands and the row stays published"*. That sentence is superseded here.
The verdict was never in dispute and is re-confirmed NO; what changed is the bar — a correct
`reject` was being treated as a reason to leave a row in the file, and the operator's test says
the file may not carry it.

## Rejected alternatives

| alternative | why not |
|---|---|
| Leave closed rows alone — nobody applies to a closed posting | The dataset is the product (`docs/decisions/2026-08-28-analyst-scope.md`, and the operator's own acceptance test names the archived rows explicitly). A downloader filtering `status == closed` for a historical picture of the Israeli analyst market gets three roles that are not analyst roles, with no signal that the file already knows |
| Publish the `reject` cell as the exclusion, and add a column | That is what happens today, and it fails the bar in the other direction: the row is *in* the file. `meta.removed[]` is the channel that already carries an exclusion **with its reason**, which is precisely what the acceptance test asks for — "excluded-with-reason otherwise" |
| Let the drain do it | The drain moves the **cache**, never the cell, and a closed role never re-enters `merged` — measured: three rows have read `accept` against a cached NO since 2026-08-30 (`543@roles`). Nothing automatic reaches these rows, which is why each needs a human line |
| Withdraw every row whose cell reads `reject` | Parametrix. One of the four |

## What this does not decide

The withdrawal removes the row from `roles.csv` and publishes it in `roles.csv.meta.json`'s
`removed[]` with the reason above. It does **not** rewrite `rec["class"]`, which no path does
for a closed role — so `544@roles` (a `contract` key on the published cell) and `543@roles`
(the run's own rejects handed to `record_run`) are both still the durable fixes, and until they
land this ruling is applied by hand, one line per row. Three lines this morning under this
ruling (seven across the whole session); the next scope change makes another handful.
