# 2026-09-02 — classifier: the deferred rows adjudicated, the closed half held to the live contract, and the gate opened by two phrases

Lane `classifier` (`ARCHITECTURE.md` §7b). One commit. **24 LLM calls, 0 Bright Data
credits.** Cross-lane: 7 appended lines in `cloud_state/roles_retractions.jsonl` (`roles`'
hand-curated input, the sanctioned channel — the 08-31 and 09-01 precedents wrote 14 and 21
of their lines from this lane). No other lane's file is written.

This finishes the 2026-09-01 session's deferred list. It settles rulings; it does not reopen
them.

## 1. The 2026-09-02 morning check, answered first — it is the evidence base

Run **33613841435** (`schedule`, headSha `92f87bf`, 09:23Z, conclusion `success`).

| the 09-02 prediction | measured | verdict |
|---|---|---|
| `classify:` names `v3.0f84ab84` | `contract v3.0f84ab84 re-judged 250/cap 250 + 96 stale-yes/cap 150, served stale 84 (15 unreachable)` | **PASS** |
| a `roles withdrawn` alarm names **34** | `roles withdrawn 34 role(s) from every product and the public dataset` | **PASS**, on the nose |
| `roles retraction lifted` names **Parametrix** | `roles retraction lifted for 1 role(s) … Parametrix GmbH \| Technical Data Analyst (Tel Aviv)` | **PASS** |
| no `roles retraction unmatched` | 0 occurrences in the run log | **PASS** |
| empty `class_decision` still 0 | **0 of 151**; `backfill: 0 verdict-less record(s)` | **PASS** |
| rows **137**, or **134** if `roles`' change lands too | **151** | **PASS** under the prediction's own clause — it said both numbers are *before* that morning's intake and a higher count is not a failure. The arithmetic: 157 − 21 withdrawn + 1 lifted = 137, and the digest's own header reads `17 new analytics roles`, of which 14 were new records |

**Parametrix returned reading `class_decision=reject`, exactly as the 09-01 record predicted
it would** — the lift returns the ROW, not the verdict, and `544@roles` is still what fixes
that. This session then measured that cell and did not withdraw the row; see §3.

## 2. The deferred cohort — NINE records, 4 withdrawn and 5 kept

**The cohort first, because the spawn prompt's "7" and the fixture's 9 are both right and the
first draft of this note added them wrong.** The 2026-09-01 record deferred seven ROWS, of
which `Holisto` is two role records — eight. The ninth is `בנק דיסקונט`, which that record put
in a different bucket entirely: *"3 not in the ledger — Clal, dt, Bank Discount … there is
nothing in the dataset to act on."* **It does have a role record**, in both stores, and it is
`open` and published, so that claim was wrong and is corrected here rather than quietly
inherited. Nine records judged, one call each, `sonnet`, artifact
`tests/fixtures/classifier/2026-09-02-deferred.json`.

**And the framing this session was handed does not survive the stores.** "Their text is
settled — jd-text confirmed each is faithfully that posting's own" is **false for two of the
nine**, and a first draft of this note repeated it as a blanket. `jd-text`'s own 09-01 record
says of Prisma, in terms: *"it does not say that."* Two adversarial passes caught it, one
step before the push, and it had already produced a withdrawal line. Everything below is
written against the stores, not the framing.

| row | seam, `v3.0f84ab84` | adjudication |
|---|---|---|
| `TransUnion \| Manager - Data Science & Analytics` | NO | **OUT.** The stored text is TransUnion India's corporate overview and the only role in it is a client-facing **Pre Sales Consultant**. Neither the workplace nor the work matches the title this row publishes |
| `Diageo \| Performance Analytics Analyst` | **YES** | **OUT, and the seam is right.** Its own opening lines read `Role: … Level: 6 \| Location: 3 WTC (New York)`; the work is the U.S. Spirits and Beer/FMB marketplace. Scope is not the ground and is not disputed — geography is, and this seam is never asked about it |
| `Prisma Photonics \| Senior Product Analyst` | NO on the stored text, **YES on its own** | **IN, and the withdrawal line was dropped.** The store holds another posting's JD. See below |
| `TechBiz Global \| Data Analyst` | NO | **OUT.** Condition (4) + the workplace record: 695 characters that never name a product, team or system of the advertiser's own |
| `בנק דיסקונט \| …ראש.ת צוות` | NO | **OUT.** A credit-risk analysis and underwriting **team lead** — credit decisioning, not analysis of measured business data. The domain is not the ground; the output is |
| `Holisto \| Senior Data Analyst` and `\| Data Analyst` | YES ×2 | **IN, both kept.** In-house SQL/BI analytics on marketing and product performance. The JD names the trivago Innovation Center because trivago is the employer behind the Holisto team — a `company` display question, not a scope one |
| `Gamida Cell \| Senior Business Analyst, Commercial Data & Analytics` | **NO** | **IN — the session's one adjudication against a seam verdict on readable text.** See 2d |
| `Ballerine \| AI Fraud Data Analyst (Senior)` | NO on the stored text, **YES on the JD buried in it** | **IN, no line written.** See below |

**The measurement that answers the task's own question, and it is a structural finding.**
`cache_keys()` is `<contract>|<company>|<title>|jd` — **there is no description hash in the
key.** A text repair therefore does not invalidate a verdict made under the live contract;
the seam re-reads a repaired posting only when the *contract* moves. Here it happened to (the
bump landed 09-01, the repairs landed 09-01, the 09-02 digest read both), so these verdicts
did see the new text. That is luck, not mechanism, and it is worth saying because the next
repair after a contract settles will not get it — and because two of the nine (Prisma,
Ballerine) show the seam faithfully re-judging text that was never the row's to begin with,
which no contract bump can fix.

**בנק דיסקונט is the case where it already went wrong.** Its only current-contract key is
`|bare`, while the row carries **1,819 characters** — so the seam had judged it with **no
description at all**, and the published `accept` came from a verdict made on a title. Judged
here on the actual Hebrew text: NO. It is withdrawn, and the row is the concrete instance of
the gap above.

### 2b. Prisma Photonics — the withdrawal that was written and dropped

**This is the finding of the session, and it was one push away from deleting a live role.**

`matched.description` for `prisma photonics|senior product analyst` is **3,276 characters of
the company's Senior DATA ENGINEER posting** — *"Design, develop, and maintain scalable data
pipelines that integrate data from multiple sources…"*, requirements asking *"5+ years of
professional experience in Data Engineering"*. On that text the seam says NO, correctly, and a
retraction line citing boundary (a) had been written and staged.

The row's OWN card is in `scraped_cache.json` under `/job/senior-product-analyst/`, **2,617
characters**, and it is a clean condition-(1) accept: *"Conduct statistical analysis and use
data visualization tools to present findings"*, *"Provide data-driven insights and
recommendations to support decision-making processes"*, *"At least 5 years of experience in
data analysis, business intelligence"*, SQL / Python / Tableau / Power BI. **Judged through the
seam under the same contract: YES.** `seen_ids` names both urls — the 2026-08-24 scraper
title↔url off-by-one that `docs/sessions/2026-09-01-jd-text.md` recorded and that is still
unrepaired in sqlite.

The row is `open`, `accept`, `last_seen 2026-09-02` and **on the published board**. The line
was dropped. Two things it costs to say plainly:

* **The framing was the failure, not the seam.** Every verdict here was correct for the text
  it was shown. What went wrong is that this session accepted "the text is settled" as a
  property of all seven rows instead of checking each against the stores — and jd-text's own
  record had already written the opposite for this row.
* **It is the 09-01 Percepto near-miss again with the check inverted.** That session verified
  a line against the wrong predicate; this one verified the predicate (all 7 lines bind to
  exactly one record) and did not verify the TEXT. The binding check was clean throughout,
  and would have deleted a real analyst role with a perfect score.

`567@jd-text` carries the repair and the guard.

### 2c. Ballerine — the chrome does not merely obscure the verdict, it inverts it

Its 3,998 stored characters are **2,671 of site chrome and product marketing** followed by
**1,327 of the posting's own JD**: *"This is a full-time on-site role for an AI Data Analyst,
located in the Tel Aviv District, Israel. The AI Data Analyst will be responsible for
analyzing data, developing data models, conducting statistical analysis, and communicating
findings to relevant stakeholders … Strong background in SQL and writing scripts in
Python / JS."* `jd-text`'s 09-01 record calls it *"the right JD, buried"*.

**Measured, three calls:** the full 3,998 characters answer **NO** (twice — the 09-02 digest's
own cached verdict and this session's), and the 1,327-character JD alone answers **YES**:
*"a full-time on-site analyst role at Ballerine itself, focused on analyzing fraud/payments
data, statistical analysis, and generating actionable insights."* The fraud DOMAIN has not
been a ground since `docs/decisions/2026-08-31-domain-scope.md`.

So the row is correctly published `accept` and no line is written — but the reason is not the
one a first draft of this note gave. *"A permanent retraction is never written on a text
nobody can read"* was too weak and, as an adversarial pass pointed out, inconsistent with
withdrawing Prisma partly on unreadability the same evening. The real finding is sharper and
is now `567`'s: **a leading-chrome prefix can flip a verdict**, because `prompt_slice` sends a
1,400-character window and 2,671 characters of chrome fill it before the JD begins. That is a
guard jd-text can write, not a judgement a session has to make row by row.

`jd-text`'s own 2026-09-02 morning check reads **FAIL** on this row — *"Ballerine still 1,662,
not 4,000 (both stores were repaired; the cache card is the thing that would hand it back)"* —
and it is 3,998 characters from `ok:canonical:www.ballerine.com`. Answered here so that lane
does not re-measure it.

### 2d. Gamida Cell — the one adjudication against a seam verdict on readable text

Its capture is **exactly 6,000 characters** (the cap) and begins **mid-sentence**
(*"responsibilities will be managing internal KPI reporting…"*). Between the intro and the
role's own `Roles and Responsibilities | Commercial Analytics & Business Intelligence` block
sit six field-sales bullets belonging to a different posting — *"Lead engagement across key
transplant centers to drive adoption of Omisirge® and APHEXDA®"*, *"Promote products through
clinically credible and value-driven messaging"*, *"Build trusted relationships with transplant
physicians"*. The contamination is measured: those bullets are at characters 430–910, and the
company's board now carries one card (`Junior Maintenance Technician`), so the posting is gone
and the text cannot be re-fetched.

**A first draft of this note said "the seam answered on the contamination", and an adversarial
pass showed it could not.** The seam gave two grounds — *"account/territory engagement duties,
leaning toward FP&A-style forecasting and commercial ops"* — and the second lives entirely
inside the role's OWN block (*"Support in the monthly/quarterly forecasting process"*,
*"Incentive Compensation Operations … attainment calculations, payout validation"*). The words
quoted as proof are in the clean block too: `territory` appears 4 times after the
responsibilities heading and 0 times in the contaminated head. So: **the contamination is
demonstrated, its effect on this verdict is not**, and the honest position is that this is a
genuine disagreement on a mixed posting, not a verdict explained away.

Adjudicated **IN** on the block that matches the row's own title — *"business performance
reporting, forecasting, and commercial analytics"*, *"Deliver actionable insights and
recommendations"*, *"Oversee delivery of all recurring reports and dashboards"* — which is
condition (1), against an incentive-compensation half that is condition (5)'s execution. It is
the conservative direction on purpose: **a retraction is permanent and nothing re-checks it**,
while leaving the row lets the drain re-judge it. It is also the closest call in the session
and is recorded as such rather than as a settled reading.

**The abort rule, and the count.** The pre-committed rule was the 09-01 one: *more than 3
disagreements with the seam ⇒ stop and file rather than ship*. There is **one** — Gamida.
Diageo is not a second (the seam and this session agree on scope; the row leaves on an axis
the seam is never shown), and Prisma and Ballerine are not disagreements at all: the seam was
right about the text it was given, and the text was wrong.

## 3. The closed-row-reject ruling, applied

`docs/decisions/2026-09-02-a-closed-row-is-judged-by-the-live-contract.md`. All **151**
published rows swept; **4 carry `reject`, all closed**; each judged once through the seam.

| row | live contract | action |
|---|---|---|
| `mobileye \| experienced data analyst` | NO | withdrawn |
| `questar auto \| senior data scientist individual contributor` | NO | withdrawn |
| `minute media \| data scientist` | NO | withdrawn — the sweep's find |
| `parametrix \| technical data analyst tel aviv` | **YES** | **not withdrawn** |

**The wording is load-bearing and one row proves it.** Written as *"a row carrying a reject
cell"*, the ruling deletes Parametrix — whose cell is a frozen verdict under a contract this
repo retired on 2026-09-01, and whose live verdict is YES (*"lightweight ETL with building
dashboards and data quality analysis consumed by Product and Sales teams"*). Written as
*"judged NO under the live contract"*, it does not. The two differ on exactly **1 of the 4**.
It would also have reversed, the next morning, the lift the 09-01 session paid for.

**Minute Media is a reversal of one 09-01 sentence and it is named as one.** That record said
*"its honest reject stands and the row stays published"*. The verdict was never in dispute and
re-confirms NO; the **bar** changed — a correct `reject` was being read as a reason to leave
the row in the file, and the operator's acceptance test says the file may not carry it.

**The `545` check was run with the predicate that decides**, not a hand-rolled copy of it —
that mistake is what nearly shipped a live-role deletion on 09-01. `Retractions.load` →
`bind(records, extra=<sqlite matched rows>)` → `match_all` over **both** stores, counting
`(line, record)` pairs: **46 lines, 0 bad, 92 pairs, 0 lines naming more than one record, 0
naming none** — 2 pairs per line is the same record found in the ledger and in sqlite. Each of
this session's 7 lines names exactly **1**. It matters here specifically:
`mobileye|experienced data analyst` carries a url-shaped LinkedIn `seen_id`, the exact shape
`545` is about, and `a8acce2`'s `_owned` fix is what holds it.

## 4. `542` — two phrases shipped, the third refused on a measurement

Three roles judged YES on 09-01 were stranded: the gate refuses the title before any verdict
is consulted, so the pipeline never reaches them.

**A correction first, because `542`'s own text named the wrong vehicle.** "Add the phrase as a
`_QUALITATIVE_HINT`-style demotion" cannot be done *to* `_QUALITATIVE_HINT`: it is read only
inside `_relevance`'s `if strong:` branch, **after** the hard-exclude branch has returned, so
it cannot rescue `excluded` and is never consulted on the `none` path at all. It reaches
**none of the three**. The intent was right; a separate vocabulary read in both refusing
branches is what implements it.

`_GATE_APPEAL` routes a refused title to `signal` and nothing else — never `_STRONG` (a
fast-accept admits the title unread; rejected by name in the boundary record), never a reject,
and **never an accept without the LLM**: `_sig_accept_nollm` refuses a title `_gate_appealed`
says is `signal` only because of the appeal. The whole evidence for a phrase here is a verdict
the model gave, so on a breaker-open morning there is no evidence — *the rescue means ASK,
never assume*, which is the rule `strong_enough` already carries for the `_STRONG` rescue.
`_gate_appealed` exists because `Junior Data/Financial Analyst` **does** match `_SIGNAL` (on
the bare word `analyst`) and is still `excluded`, so "does `_SIGNAL` match?" is the wrong
question; what `_relevance` would have answered is the right one.

**Measured, all offline:** `Calculum | Junior Data/Financial Analyst` and
`IAI | תהליכי בקרה ו-AI` both `excluded`/`none` → **`signal`**; **2 of 4,599** distinct
(company, title) pairs across both caches move; **0 of the 252** title-only golden-fixture
rows move; **`CONTRACT` unchanged at `v3.0f84ab84`** — the gate is not in the rules hash, so a
gate change re-supersedes nothing. Both re-confirmed YES through the seam this session, both
alive in the 09-02 caches with text (4,000 and 1,247 chars) and both passing `is_israel_job`.

### The third is refused — and the number the operator decided on was WRONG

`Zoll Medical | Business Operations, CMS` carries no analytics word at all, so the only title
phrase that reaches it is the bare `business operations` — **11** cards where the two shipped
phrases admit 2, of which 8 are non-analyst titles answering NO every run and **6 carry no
description**, each becoming a new Bright Data JD-fetch candidate. That part holds.

The generic alternative the operator asked for — a **description** appeal, re-reading text a
posting already carries and never fetching — was measured over the whole refused tier (4,377
refused cards, **1,427** of them already carrying ≥300 characters) across six predicates, and
each of the six missed at least one of the three. On that basis this session wrote *"the three
known misses are found by three different predicates and no shared one … no cheap generic
description predicate exists here"*, and the operator refused Zoll on it.

**An adversarial pass then found the shared predicate on its second try, and this session
re-derived it independently.** Every one of the six scored DENSITY or PROXIMITY; none asked
whether the posting says the words *data analysis* at all:

| predicate over the same 1,427 | admits | Calculum | IAI | Zoll |
|---|---|---|---|---|
| `data analytics｜data analysis｜ניתוח נתונים` | 87 | ✓ | ✓ | ✓ |
| ...plus `not _desc_is_ml` and `is_israel_job` | 84 | ✓ | ✓ | ✓ |
| ...plus an output word AND a tool word | **22** | ✓ | ✓ | ✓ |

**22 is below the ~27 this session had already called affordable**, reaches all three, and
costs no Bright Data at all. So the claim is retracted in every place it was written — the
source comment, `ARCHITECTURE.md` §7b and `542` — and `542` now carries the corrected table
with the retraction named, so nobody cites the wrong finding.

**What did NOT change, and why.** The ship is still the two phrases. The description appeal is
a NEW mechanism (a gate that reads a description) that arrived after the golden fixture and
the corpus had been measured for the phrase list, on an evening already carrying a gate change
and seven withdrawals — and this repo's own rule is that a gate three measurements call
precise is not loosened in a hurry. What it costs is bounded and stated: 22 recurring calls
out of a run that logged `re-judged 250/cap 250` against a 450 cap, i.e. from the contract
drain, which is this lane's own number. **The operator's decision was taken on a figure of
348; the figure is 22, and the decision is theirs to re-take.** `542`'s reopening condition is
a `classify:` line no longer at its rejudge cap.

### 4b. The by-product: the first false-negative measurement of the refused-WITH-TEXT tier

The three predicates disagree, which makes their intersection a principled shortlist rather
than a hand-picked one: flagged by **≥2 of 3**, `is_israel_job`, not ML, and not a class the
rules already name — **8 rows**, containing both known misses. The 6 non-target rows were
judged (`tests/fixtures/classifier/2026-09-02-gate-residue.json`):

**1 of 6 is YES — `Wiliot | Data Solutions Analyst` — and it is a San Mateo posting. So 0 of
6 is a lost Israeli analyst role.** The other five are correct rejections on the execution
boundary (Surecomp Sales/BusOps, Velotix RevOps, HiBob Deal Desk, Wiliot Team Lead, Challenge
Group Safety Officer). The 2026-08-28 pass measured the `excluded` tier; nobody had measured
the population that is refused **and already carries a description**, which is where a miss is
both real and cheap to find. Six rows is not a rate and `529` is **not closed** on it — but it
is the first evidence that the tier is not hiding a pool.

## 5. The defect three findings converged on: the Israel filter believes the aggregator

`566@classifier`, filed not fixed. Four postings, found on two unrelated errands:

* `Diageo` — location `מחוז המרכז` from Indeed; own text `Location: 3 WTC (New York)`.
* `TransUnion` — the same Indeed stamp over TransUnion India's overview.
* `Wiliot | Data Solutions Analyst…San Mateo` and `…Team Lead…Dallas` — `is_israel_job` true
  with the US office name inside their own **title**.

`pipeline/israel.py` is this lane's file, so this is not a hand-off — it is a deferral with a
reason: a change to `is_israel_job` moves every card in both caches and needs its own
before/after measurement, and this commit already carries a gate change and seven withdrawals.
Same family as `548@classifier` (`country_code` as the sole Israel signal), different field.
The two published instances leave the dataset today by hand.

## 6. What I did NOT do

* **No `_STRONG` extension, and no `business operations` phrase.** Both alternatives are
  rejected with the number that killed them, above and in `542`.
* **No hand-edit of `cloud_state/roles.jsonl`, `roles.csv` or `roles_archive.csv`.** Single
  writer `daily-digest`, `s_ours` merge — a hand-edit pushed mid-digest is discarded silently.
  The withdrawals go through the one sanctioned human channel and the export applies them.
* **No fix to `pipeline/israel.py`** (`566`), **no repair of the three broken captures** —
  Prisma's wrong-posting text in sqlite, Ballerine's chrome prefix, Gamida's page-slice
  (`567@jd-text`) — **and no `543`/`544`**, which are `roles`' files and are what would make
  this ruling automatic instead of hand-applied, one line per row, every scope change.
* **Zoll's description appeal is designed and measured but NOT shipped** (`542`). Naming it
  here because the reason is a judgement, not an obstacle: 22 recurring calls out of a
  cap-bound drain, on an evening already carrying a gate change and seven withdrawals.
* **Two `HANDOFF.md` rows were moved to `docs/morning-checks.md`, verbatim, to fit the word
  cap** — this lane's answered 2026-09-01 row, and one `infra` row (`2026-09-01`,
  `mutation-gate` shards, answered FAIL on 2026-08-31) whose finding `infra` has since acted
  on: `SHARDS` 5 → 8 landed and is recorded in `4db7461`. Naming it because moving another
  lane's row is not this lane's call to make silently, and because the cap makes it a
  recurring temptation: the file was **3,173 words of a 3,200 cap** (`check_docs`'s own
  count) before this session wrote a line.
* **`Percepto | Data Insights Operations` was not touched**: `roles` re-added that line on
  2026-09-02 with `545` fixed, and the check above confirms it now binds to one record.

## 7. Green, and where — and what this session did NOT deliver

**Locally, from this worktree at `origin/master` + this diff:** `python -m pytest` (not `-q`)
**1,804 passed, 13 skipped, 0 failed**; `python check_invariants.py`
**`companies.csv OK: 2142 rows, 1157 active, 0 orphans, pool=854`**; `python docs/check_docs.py`
**0 error(s), 15 warning(s) over 111 documents** — every warning is another lane's not-yet-due
morning check. CI run id and conclusion go in the `HANDOFF.md` line after the push; the
baseline it is measured against is `roles`' **33670937402, 16 of 16**, on `8300b08`.

**Both new guards were verified RED before being trusted green** — against a neutered
`_GATE_APPEAL`, and, after an adversarial pass showed half of one assertion could not fail,
against the `_STRONG`-promotion mutant the guard exists to catch.

**Clause 1 — the lane's number did not move, and this is not a delivery.** *0 role records
without a classifier verdict*, re-derived after the change: **0 of 154**. It was 0 before this
session started and nothing here moves it; what this session changed is the CORRECTNESS of
verdicts already recorded, which that queue does not measure.

**Clause 2 — for the dataset half: NOT DELIVERED — still a hand-drain.** Seven withdrawals
were written by hand, one line per row, and the ruling that produced them is applied the same
way every time the scope moves. The decision record says so in its own last paragraph, and
`543@roles` and `544@roles` are the two changes that would make it automatic; neither is this
lane's file. **The gate half IS delivered**: `_GATE_APPEAL` runs in `daily-digest.yml` at
05:00 UTC with nobody watching, its alarm is the mail's `classify:` line, and the 2026-09-03
morning-check row is the unattended proof — until that row is answered, even that half is
unproven rather than done.

## Traps this session hit

* **`os.popen` reads a Hebrew state file as cp1252 and dies mid-parse.** `git show
  origin/master:cloud_state/roles.jsonl` through `os.popen` raised
  `UnicodeDecodeError: 'charmap' codec can't decode byte 0x90`. Redirect to a file and open it
  with an explicit `encoding="utf-8"`; `PYTHONIOENCODING=utf-8` fixes only the console.
* **A distinct-pair count depends on what you put in the tuple.** The first corpus measurement
  read 4,779 `(company, title, location)` triples and "3 titles move"; the honest figure is
  **4,599 distinct `(company, title)` pairs and 2 moving**, because one title appears at two
  locations. Every number in this record is the second measurement.
* **The tree was 32 commits behind at session start** and `origin/master` moved again
  (`40f02e2` → `636a8e2`) while the plan was being written. Both readings were re-checked
  against the newer head before anything was staged; the intervening commit touched only
  `tests/`.
* **A new guard must be verified red, and "red" is not one mutation.** Both tests were run
  against a neutered `_GATE_APPEAL` and both failed — and an adversarial pass then showed
  that half of the "never `strong`" assertion **could not fail under the mutation it names**:
  for `data/financial analyst`, `_HARD_EXCLUDE` returns before the `strong` return is
  reachable, so `_relevance(...) != "strong"` holds even with the phrase promoted into
  `_STRONG`. It now asserts the phrases' ABSENCE from `_STRONG` instead, and is verified red
  against that promotion mutant specifically.
* **The most expensive mistake of the session was trusting a framing over the stores.** The
  spawn prompt said the seven deferred rows' text was "settled ... jd-text 09-01 confirmed
  faithful"; `docs/sessions/2026-09-01-jd-text.md` says of one of them, in terms, *"it does
  not say that"*. A withdrawal line for a live, in-scope, published role was written on
  another posting's JD and survived the binding check — which was clean, because binding is
  not the question the text asks. **Verify the predicate AND the text.**
