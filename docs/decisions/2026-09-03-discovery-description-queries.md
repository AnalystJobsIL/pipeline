# 2026-09-03 — searching job DESCRIPTIONS for analyst roles whose title we never match

*lane: `discovery`. A measurement session in the shape of
`docs/decisions/2026-08-30-discovery-own-domain-sources.md`, where AllJobs, Drushim and TASE
were each measured and refused: the deliverable is a number per query, a bar, and a decision.
**Ten probes measured, ten refused.** Spend: **4 Bright Data credits** (3 Indeed probes + 1
Indeed control; the LinkedIn half is keyless and cost 0), **30 `claude -p` calls**, 0 SerpApi.
Every number below was produced from a worktree at `origin/master` `5ad8a1d`; the commands are
in `docs/sessions/2026-09-03-discovery.md`.*

## 0. The question, and why it is a real one

The operator asked: *"Is there any way to expand discovery to look for roles that look for
analyst but with different names? for example look for descriptions with insights or
recommendations or analyze as options for LLM classification?"*

It is a real gap. Discovery searches **nine title words** and nothing else
(`discovery_daily.py:66-68`), while LinkedIn's `keywords=` and Indeed's `q=` are FULL-TEXT
searches that match the description. So there is, in principle, a frontier the pipeline cannot
see: a role at an employer we never fetch, whose title matches no keyword of ours, reachable
only because the search engine indexed its JD.

**The frontier exists. It is measurably not full of analysts.**

## 1. The finding that had to be established first

The spawn brief said the in-pipeline half was already handled — *"the classifier now demotes
gate-rejected titles to the LLM on technical markers."* **It does not, on `origin/master`
today.** `pipeline/seniority.py:400-402` falls through to `return "none"`, and `:836`:

```python
        if rel == "none":
            return {**base, "decision": "reject", "path": "keyword",
                    "reason": "no analytics signal in title"}
```

No description is read and no LLM call is made. `_DESC_ANALYTICS` exists but only as a veto
and as positive evidence for titles that ALREADY reached `signal`. The same gate is the
JD-fetch gate (`pipeline/jdfill.py:2597-2598`), so such a posting never even acquires text.
`_GATE_APPEAL` (`seniority.py:219`) is two literal phrases, not a marker rule.

So a frontier posting would be found, cached, and then rejected on its title. The experiment
therefore measured **three things separately** and never let one stand for another: what
production does today, what the role actually IS, and what the EMPLOYER is worth.

## 2. Method

Ten probes in two rounds plus two controls, each ONE flat query — never a boolean, because
the result pool is per QUERY (`discovery_daily.py:63-65`: one combined `OR` bought 10 new
companies against 76 from nine flat queries). Round 2 exists because refusing the operator's
idea on six first guesses would be refusing the instrument, not the idea: round 1 probed
TOOLS (`SQL Tableau`), round 2 probed analyst IDIOMS (`ad hoc analysis`, `actionable
insights`) — the shapes closest to the operator's own words.

Walked through production's own code — `discovery_daily.linkedin_search(kw, pages=0)`, the
keyless guest endpoint, `pages=0` making the paid fallback structurally unreachable
(`:430`) — capped at 15 pages (150 cards) per query, uniform across probes AND controls so
the comparison is fair. Every card scored with functions production already owns:
`store.seen_id` / `merge_key`, `companies.load_companies`, `firmographics.identity_key`,
`recruiters.is_recruiter`, `israel.is_israel_job`, `seniority.classify(use_llm=False)`.

**The controls are what make the table readable.** `C1 data analyst` is an existing keyword;
`C2 insights analyst` was dropped on 2026-08-23 as saturated (`+0` employers,
`discovery_daily.py:61`). Both returned **0 new employers**, which (a) reproduces the
2026-08-23 measurement three weeks on and (b) proves the harness is not simply blind — the
probes DO return new employers where the controls return none.

## 3. The yield table

*`ovl%` = share of the query's postings already in `discovered_cache.json` (2,521 cards — what
the existing 27 queries found in the last 21 days). `bank` = new postings, in Israel, past the
intake gates, whose title production accepts or sends to the LLM. `analyst-surfaced` = new
employers that were found **via an analyst-shaped posting**.*

| # | query | credits | postings | overlap | ovl% | new postings | bank | NEW employers | noise | analyst-surfaced |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | `data analyst` *(control)* | 0 | 129 | 95 | 73 % | 27 | 5 | **0** | 0 | 0 |
| C2 | `insights analyst` *(control)* | 0 | 132 | 96 | 72 % | 29 | 2 | **0** | 0 | 0 |
| D1 | `SQL Tableau` | 0 | 131 | 74 | 56 % | 50 | 4 | 6 | 0 | **0** |
| D2 | `Power BI dashboards` | 0 | 128 | 70 | 54 % | 49 | 2 | 8 | 3 | **0** |
| D3 | `SQL insights` | 0 | 109 | 78 | 71 % | 26 | 2 | 1 | 0 | **0** |
| D4 | `A/B testing metrics` | 0 | 112 | 85 | 75 % | 21 | 1 | 1 | 0 | **0** |
| D5 | `SQL נתונים` | 0 | 135 | 62 | 45 % | 66 | 2 | 7 | 1 | **0** |
| D6 | `תובנות עסקיות` | 0 | 140 | 73 | 52 % | 59 | 0 | 13 | 6 | **0** |
| E1 | `ad hoc analysis` | 0 | 107 | 68 | 63 % | 37 | 4 | 4 | 1 | **0** |
| E2 | `data driven decisions` | 0 | 55 | 41 | 74 % | 12 | 1 | 0 | 0 | **0** |
| E3 | `actionable insights` | 0 | 104 | 76 | 73 % | 17 | 1 | 2 | 0 | **0** |
| E4 | `הפקת תובנות` | 0 | 142 | 75 | 52 % | 60 | 1 | 14 | 5 | **0** |
| | **ten probes** | **0** | **1,163** | — | — | **397** | 9 *(deduped)* | **56** *(53 distinct)* | **15 of 53 (28 %)** | **0** |

## 4. The four numbers that decide it

**(1) 0 of 53 new employers were surfaced by an analyst-shaped posting.** (56 is the sum of
the per-query columns; three names — `Accenture España`, `Strauss Group`, `Superkit` — were
marginal in both rounds, so the distinct union is 53.) Every one arrived attached to a role
production classifies `none` (41) or `excluded` (12): a QA Engineer, a
Database Operations Engineer, a Penetration Tester, a Bookkeeper, a Plumber Lead, an Office
Coordinator, a Luxury sales consultant, a Video Producer. That is the whole finding in one
line — **analyst vocabulary in a description is not distinctive.** `SQL`, `Power BI`,
`dashboards`, `ad hoc analysis` and `תובנות עסקיות` are in every backend, finance, operations
and sales ad in Israel, so a description query returns those employers' engineers and
salespeople. The names funnel's value is that a LinkedIn-seeded employer arrives *with a job
signal* — which is why LinkedIn-seeded rows convert to a role at **25.2 %** against the
catalog's 4.9 % (2026-08-30 record). These 53 arrive with a signal pointing the other way.

**(2) 0 of 30 frontier postings are in scope, judged by production's own seam.** Of the 397
new postings, 133 were the true frontier (new, in Israel, past the gates, title REJECTED). 129
of their descriptions were fetched keylessly through `jdfill.fetch_jd(bd=None)`. The 30 calls
were then spent on the **highest `seniority._DESC_ANALYTICS` marker density**, deduped by
`company|title` — so the result is an **UPPER BOUND**, and the population is precisely the one
a description-marker demotion in the classifier would itself select. All 30 came back **NO**,
with coherent reasons: `Subsidiaries Controller`, `Principal Product Manager`, `MySQL DBA`,
`Financial Controller`, `Director of Global Procurement`, `FP&A Business Unit Manager`,
`Sr. Software Engineer`. Not one disguised analyst.

**(3) 9 bankable postings, 0 at an employer the registry lacks.** Deduped across all ten
probes, every role whose title production would act on is at a company we already hold a row
for — Arm, PwC Israel, Clalit, Rafael, Cognyte, KayHut, Xsight Labs, Tesnet, Rhino. We read
those boards directly, and LinkedIn is explicitly never the primary source for a company we
already cover (`CLAUDE.md`).

**(4) Indeed is worse, and it is the only half that costs money.** Three probes at 1 credit
each returned 15 / 1 / 6 cards. The analyst-shaped roles among them are real —
`אנליסט/ית דיגיטל`, `DATA ANALYST` at קבוצת יעל, `אנליסט.ית עסקי.ת` at קבוצת כלמוביל — but a
**1-credit control on the EXISTING `אנליסט` query returned 5 of those same 6**, at an employer
we already hold in every case. The one exception (`Nogamy | אפיון וניתוח מערכות BI`) is at an
employer the existing query also returns. So Indeed's description probes bought **0 new
in-scope roles for 3 credits** — the operator's bar (at least 1 per 10 credits) fails
outright, and it is the only probe where the bar could even bind.

## 5. The bar, and why it needed a second half

The agreed bar was *at least 1 genuinely new in-scope role per 10 credits, net of overlap.*
**On the keyless LinkedIn path that bar cannot discriminate** — the queries cost 0 credits, so
any query returning anything passes it. The operator ruled on 2026-09-03 that a query may earn
a slot on **new employers OR new roles**, so the bars actually applied were:

| bar | reading |
|---|---|
| 1 new in-scope role / 10 credits | **FAILS**: 0 new in-scope roles at 4 credits and 30 LLM calls |
| saturation (under 90 % overlap) | passes — 45-75 %, genuinely fresh windows |
| new employers per run | passes on volume — 56 across ten probes, at 0 credits |
| **junk rate of those employers** | **FAILS**: 15 of 53 = **28 %** by hand-read (every name listed in the session record), statistically identical to the queue's existing 27 % — and this arrives on top of a drain doing 112/night against 161 median intake |
| **employers arriving with a job signal** | **FAILS**: 0 of 53 |

A source that adds resolvable names to a queue that is already 27 % noise makes the registry's
day worse, not better — the 2026-08-30 record's closing sentence, and it applies unchanged.

## 6. Decision

**Wire nothing. All ten probes refused.** No change to `_LI_KEYWORDS`, `INDEED_QUERIES` or
`_li_queries()`. The one code change this session makes is unrelated to the probes and is
described in §8.

**What would change the answer**, stated in advance so the next session does not re-run this
blind:

- A query whose terms are analyst-EXCLUSIVE rather than analyst-typical. Nothing in the ten
  probes came close, and the two controls show the title words are still the discriminating
  ones. If anyone tries again, the instrument is a term that an engineer's JD does not
  contain — and the burden is to name one, not to guess six.
- The walk stopped at the **15-page cap on every query**, so all counts are FLOORS. Depth is
  the one dimension not tested. It is also the one least likely to help: the frontier's
  problem is the KIND of role returned at every depth, not how many.
- A classifier that reads descriptions would not rescue this either — see §7.

## 7. Filed, not fixed

- **`classifier`**: `_relevance` returns `none` on the TITLE alone, so no description marker
  can ever reach the LLM and `jdfill` never fetches the text. This session's 30 calls are the
  first measurement of what that gate costs on the discovery frontier, and the number argues
  **against** building the demotion rather than for it: on the 30 most analytics-marker-dense
  gate-rejected postings, a marker-based demotion would have spent 30 calls to accept **0**
  roles. **Scope caveat, stated because it matters:** that population is postings found BY
  description queries, i.e. non-analyst titles that mention SQL by construction. It is not
  evidence about postings arriving from a company's own board, which is the population a real
  demotion would serve. `tools/measure_title_gate.py --tier rejected` over `scraped_cache.json`
  is the measurement that would settle that, and it is the classifier lane's to spend.
- **`discovery`**: five agency-SHAPED names walked past `is_recruiter` in this session's own
  returns and are queue CANDIDATES, not verdicts — `HUNTHEAD`, `Snatch UP Jobs`,
  `iTalent - Hire Smarter`, `TASC Consulting & Capital` and the Hebrew `יו-מאן בע"מ`. Each
  needs a researched `_CONFIRMED` entry, the way the 2026-08-30 record's twenty do; none is
  asserted to be an agency here, because one posting is not evidence. **The name that proves
  why:** `MAGNUS International Search and Rescue` reads as a recruiter for exactly two words
  and is a search-and-RESCUE organisation. It was on this list until the exact string was
  checked.

## 8. Built anyway: the anonymised-employer gate

Not a probe result — a defect the probes exposed. `Undisclosed` and `Discreet Company` came
back as employer names, and the registry turned out to already carry **four parked rows of the
same class**: `Confidential Careers`, `Confidential Company`, `Confidential Global Company`,
`Stealth Startup`. Each is a placeholder where the employer name should be; each defeats every
downstream identity check for the same reason `Tel Aviv` does — there is no company to prove a
board against — and each scans empty forever while holding a re-check pool slot.

`pipeline/recruiters.py` already carried `confidential`, `confidential careers` and the Hebrew
`חברה דיסקרטית` for exactly this, as exact strings on `_CONFIRMED`. **An exact-match list
cannot close an open class**, which is how the four rows got in while the list sat there.

`is_anonymous_employer(name)` replaces all three: a name is refused only when EVERY word is an
anonymiser or generic corporate filler. Whole-name, never substring — that is the whole of its
safety. Called from `_is_recruiter_name`, so it reaches every existing caller (the read-side
gate in `fetchers.fetch_discovery`, `auto_expand`, the queue drain), not only the two intake
sites; the two `_CONFIRMED` entries are **deleted** in the same commit because the rule
subsumes them.

**Blast radius, measured before the change** over the 2,757 distinct names in registry, queue,
cache and firmographics: **8 newly refused, 0 of them an ACTIVE row** — the four parked rows
and the same four as cache cards. The near misses that must not move, and do not:
`Confidential Computing Inc`, `Stealth Security Ltd`, `Discreet Logic`, `Anonymous Analytics
Ltd`. Guard: `test_an_anonymised_employer_name_is_refused_whole_name_not_by_substring`;
mutations `anon-employer-substring`, `anon-employer-drop`.

## 9. Alternatives considered, and why each was rejected

- *"Add the best probe (`הפקת תובנות`, 14 new employers) anyway — it is free."* Rejected on
  section 4(1): 0 of its 14 employers arrived with a job signal, 5 of 14 are noise, and free
  is not the binding cost — the registry drain is (112/night against 161 median intake).
- *"Widen the walk to 50 pages and re-measure."* Rejected: the counts are floors, but the
  defect is compositional, not depth-related. 0 of 30 at the top of the marker ranking does
  not improve by adding cards below it.
- *"Use a boolean to cover all six terms in one query."* Rejected on the existing measurement
  (`discovery_daily.py:63-65`), not re-tested: one window instead of six.
- *"Score in-scope with a cheaper title heuristic instead of 30 model calls."* Rejected: the
  whole question is what the DESCRIPTION says, and a title heuristic is the thing under test.
- *"Refuse after round 1."* Rejected: six tool-name probes would have refused the instrument
  rather than the idea. Round 2's analyst idioms are the operator's own words and failed the
  same way, which is what makes the refusal about the idea.
- *"Put `is_anonymous_employer` in `firmographics.looks_like_junk`."* Rejected: that is the
  `company-intel` lane's file, and `looks_like_junk` is applied to the names funnel only
  (`discovery_daily.py:1167`) — a placeholder name must also be kept out of the CACHE, which
  only the recruiter gate reaches (`:1115`).
