# 2026-08-29 — `registry`: resolving the queue

Against `origin/master` `51defbd`. The brief was "resolve all 877, budget is not a constraint".
The queue is not resolved. **Every one of the 877 is now individually accounted for**, which is
the answer the file could not previously give — and three of the four rungs are exhausted
against this population, with the fourth named rather than implied.

---

## First, the thing that made "what is left" unanswerable

A `research_companies.json` entry carries four keys — `name`, `careers_url`, `ats`, `slug` —
and **no attempt count, no date, no reason**. The state was scattered: `auto_expand_seen` 770,
`resolve_attempts` 194, `candidate_probe` 361, and **393 of the 877 appeared in none of them**.
A name tried twenty times was indistinguishable from one never touched, so every tool re-walked
the same prefix and nothing could retire a name that is genuinely unfindable.

That is `docs/BACKLOG.md` 407 one level down: a ROW gets a verdict, a date and a pool; a NAME
got none of the three, so it had no owner and no cadence. `queue_state.py` +
`cloud_state/queue_state.json` give it all three, copying the model that already works rather
than inventing one — an **append-log** (because `notes.py` exists for exactly this hazard and
three tools touch these names), a **date** per attempt, and **`in_queue_pool`** so each rung's
outstanding work is a function. A verdict there is never a claim about a company; it records
what a RUNG did, and the file cannot activate or park anything.

**It got two things wrong first, and both are the same mistake.** `TERMINAL` matched as a
PREFIX, so `resolved-domain` — rung 1 finding the company's own SITE, which is evidence and not
a board — settled 55 names that still had every later rung to run. And `is_settled` read only
the NEWEST verdict, so backfilling the drain's attempts after stamping `already-a-row` buried
64 of 65 settled names and the census said 2 settled where 66 were. It scans every attempt now
and re-derives `already-a-row` from `companies.csv` rather than trusting a stamp.

One derivation is recorded explicitly rather than inferred: `walk_one` runs its rungs in order
and only reaches a later one when every earlier one declined, so a name carrying a `search`
attempt is evidence — **`implied-by-ladder`** — that the slug probe and the Comeet reader had
their turn. Without it the census claimed 786 names were owed a slug probe that had already run.

## Rung 1 — `_site_from_guess` over 758 names, having never run against more than 364

|  | REAL HANDLE | NAME-DERIVED | TOTAL | 08-27 (364) |
|---|---|---|---|---|
| names tried | 83 | 675 | 758 | 364 |
| domains answered | 18 | 208 | **226** | 119 |
| …named the company | 13 | 189 | **202** | 104 |
| …carried the linkback | 7 | 57 | **64** | 53 |
| …passed ALL THREE | 5 | 50 | **55** | 49 |

Ninety seconds, free. **Twice the names for six more domains**, and the split is why: **89% of
the slugs normalise to the name exactly**, so they carry no identity LinkedIn asserted — folding
them together would make this run look like the 08-27 one and it is not. **The linkback is the
binding constraint**: 202 pages named the company and 64 linked back.

`_site_from_guess` now takes a `stats=` counter and records what it DECLINED, so those four
numbers come from the rung itself instead of a private mirror of its stages — which is the only
way two runs a fortnight apart can be compared at all.

## Rung 2 — the first honest test of a tier this repo had written off

`278@registry` measured `resolve_llm` at *"0 resolved from 7 asked"*. But `_verify` refuses any
answer without a page on the company's OWN domain (`_own_page_names_token`), and those 7 were
asked without one. `cloud_state/resolve_attempts.json` holds 194 names and its intersection
with this queue is **zero**: the chain handle → own-domain → `resolve_llm` had never been run.

**2a, given rung 1's 55 verified own-domains:** 55 asked, **55 had an own-domain page**, 65
`claude` calls, **4 resolved**. 0% → **7.3%**. Two became rows — `RealSense` (bamboohr, 8/6 IL)
and `develeap` (comeet, 1/1 IL). `Imubit`'s board answered 0 and was **deferred, not recorded
empty**; `Residenthome`'s board is already read under another name.

**2b, given the 585 names whose SEARCH found a page on their own site** — evidence the tier had
never seen, from the 843-search drain earlier the same night:

```
200 of 585 walked · 131 asked · 83 had an own-domain page · 229 claude calls · RESOLVED 0
```

**I stopped it at 200, and that is a deviation from "to exhaustion" that you should overrule if
you disagree.** Two reasons, both measured rather than felt. The yield was 0 of 131 asked and
the mechanism is understood, so the remaining 385 had an expected yield near zero. And the rung
was *slowing* — 50 names took 424 s, then 666 s — which is rate-limiting on
`CLAUDE_CODE_OAUTH_TOKEN`, the single subscription the 05:00 digest's classifier shares. Ninety
more minutes of two concurrent `claude -p` through that window risks the classifier falling back
on the one run a day the product depends on, to learn something I already knew at n=131. The
385 unattempted names keep their `search-page-no-ats` verdict and are re-selectable: the
attempt log says exactly which 200 were asked.

**That is the measurement, and it is the useful half.** The tier resolves at 7.3% on a
*verified* own-domain and at **0% on a search-found page**, at n=131. The difference is
`_site_from_guess`'s three-way binding — the full name on the page, an exact linkback, and the
same registrable domain after redirects. A page the search merely returned is not evidence
`_verify` can use, so feeding more of them is not "more evidence", it is more of the wrong kind.

## Rung 3 — already spent

The paid search rung ran over all 876 names earlier the same night: **843 Bright Data credits**,
111 actionable proposals, 56 rows. Its residue is the largest class below.

## Step 4 — every remaining name, accounted for

```
QUEUE 877  -  SETTLED 70  -  REMAINING 807
```

| disposition | n | what it means |
|---|---|---|
| `search-page-no-ats` | 369 | the search found the company's pages; none carried an ATS signature |
| `no-proposal` | 246 | an LLM was given the company's own page and proposed nothing verifiable |
| `walked-nothing-found` | 106 | the drain walked it and every rung declined |
| `already-a-row` | 67 | the registry already holds this name |
| `held-name-twin` | 20 | a proposal HELD: the name overlaps a row we have — a human read, not a refusal |
| `gate-refused` | 20 | a board was proposed and the identity gate refused it |
| `probe-no-il` | 17 | a guessable board exists and carries no Israel posting |
| `comeet-dup-board` / `dup-board` / `dup-name` / `probe-dup-board` | 24 | the board or name is one the registry already reads |
| `comeet-no-il` | 2 | the Comeet board answered with no Israel posting |
| `board-empty-deferred` | 3 | a board was found and answered 0: **deferred, never recorded empty** |
| `junk` / `aggregator` / `probe-ambiguous` | 3 | not a company / not this employer's board / two candidates, so deferred |

**No name is unexplained**, and `python queue_state.py --name "<name>"` prints any one name's
whole history.

**The one rung that has not run** is `hunt` — `listing_hunt`'s queue arm, Playwright plus a
search engine, the rung measured at 33 boards and 521 Israel jobs from 73 names. It has run
against **0** of the 807. It is named here rather than run because it **ACTIVATES**: it writes a
row for every name it touches, including a park saying a company has nothing, which is the
operator's rule 1 at 807× scale. Running it needs either the rule relaxed deliberately or the
arm changed to emit proposals the way `drain_queue` does.

## No zero was written tonight

The gate the operator set applies to anything recorded as having no Israeli openings. **Nothing
tonight recorded that.** `apply_proposals` writes rows that assert PRESENCE and nothing else;
`Imubit` and two others whose board answered 0 were **deferred with no row**; and a
`queue_state` verdict is a fact about a RUNG (`no-linkback`, `search-page-no-ats`), never about
a company. So the four conditions had nothing to gate, and `cloud_state/zero_confirm.json` is
unchanged from the 247 entries of the previous session.

## Cost

| | |
|---|---|
| Bright Data | **0 this session** — rung 1 is free HTTP, rung 2's search ladder found no new candidates to unlock. The 843 credits of the queue drain were the previous session's |
| `claude -p` | **294** - 65 (rung 2a, 4 resolved) + 229 (rung 2b, 0 resolved) |
| rows written | 2 (`RealSense`, `develeap`), both verified through the production fetcher, both through `apply_proposals`' full gate stack |

## The evening: the check was better than the thing it checked

`queue_disposition` retires a name only after a hunt AND an LLM read. It ran over 444
candidates and returned **120 `no-board`, 323 `cannot-tell`, 1 `has-board`**. Retirement is the
only act in this session that DELETES something, so 20 of the 120 were QA'd — not by re-reading
the stored evidence, but by asking the question again from scratch: one fresh paid search per
name, and a model shown only the name and the URLs it returned.

> **An independent search disagreed with 15 of 20 — 75%.**
> `apester.com/careers/` · `allyable.com/careers/` · `wenrix.com/careers/` ·
> `minrav.co.il/en/careers/` · `meitav.co.il/jobs/` · a live Comeet board for `Formtitan`

The cause is structural, not a bad model: `judge()` reasons from the evidence the HUNT stored,
so on a name the hunt failed it can only re-confirm the failure. All 120 verdicts were
overturned in `cloud_state/queue_disposition.json` and **nothing was pruned on them**. The 120
`no-web-presence` records the same pass wrote into `queue_state` were stripped too — that
verdict is TERMINAL, and it had frozen 111 names out of every later rung.

Two things were retired honestly: **317 names that had become registry rows**, which is a
lookup rather than a claim (`queue 877 -> 560`).

## `queue_resolve_search.py` — the QA instrument, promoted to a rung

Six defects were found by chasing ONE company the operator questioned (`bdo.co.il` is not
BDO's careers page — they were right). Every one of them biased toward a false "no board":

| defect | effect |
|---|---|
| `google_via_unlocker(name)` builds its own `f"{name} careers"`; we passed `"X careers"` | searched `"X careers careers"` |
| `DEEP_BD_SEARCH_CAP` is **150 per process** and returns `[]` silently | a 137-name shard went blind at ~75; the rest logged `no-search-results` |
| `unlock()` returns `""` once Playwright has run in the process | after the first scrape, EVERY later name became a false `no-search-results` |
| `urllib` cannot request a raw-Hebrew URL | `bdo-career.hunterhrms.com/כל-המשרות/` read as a 0-char page |
| `is_aggregator` does not know `lnkd.in` | `QTREX` "resolved" to a shortlink and scraped 32 fake Israel roles |
| every gate judged the URL, never the page | a `/services/` page passed; an 85,761-char real board was refused |

The design answer to the last one is the operator's: **stop maintaining a notion of what a
board looks like.** A page is a board if scraping it returns jobs — host-agnostic, so an ATS
this repo has never seen and a self-hosted board pass for the same reason Greenhouse does.
`looks_like_a_job_listing_page` drops from a veto to a tie-breaker.

IDENTITY does not relax, because that is the property that publishes one company's roles under
another's name: `identity_ok`, or the company's token from `_name_targets` as a **whole word**
in the title the tenant wrote. Anchored at word boundaries deliberately — substring matching is
what put Bancor onto The Bancorp Bank's board, and `test_the_title_rescue_admits_an_unknown_ats_but_not_a_lookalike`
pins both directions.

The rung runs in two phases: every paid search first with no browser in the process, cached to
disk per name, then fetch-and-scrape. That is not tidiness — it is the only thing that stops a
render from poisoning the next name's search.

Verified end to end: `BDO Israel` -> `bdo-career.hunterhrms.com/כל-המשרות/` · `Teva` ->
`tevapharm.com/your-career/` · `NVIDIA AI` -> `jobs.nvidia.com/careers` (4 IL).

## What was written, and what was refused

`apply_proposals` wrote **205 rows** from the queue — 49 ACTIVE, 156 parked-with-an-address
(the daily `probe_candidates` watch). Every proposal went through `qa_proposals` first, and the
refusal rate is the reason that step is not optional:

| batch | proposals | refused as another company's |
|---|---|---|
| recovered monitors | 257 | **26 (10%)** — `Israel Police`, `Israel Post`, `Menora`, `Melisron` |
| activatable | 95 | **9 (9%)** — incl. `Greylock Partners`, a VC |
| final hunt | 27 | **4 (15%)** — `Kuehne+Nagel`, `Lacuna Space`, `Lightheaded Lighting` |

## What I did NOT finish

* The 549-name sweep with the fixed rung was still running. Its proposals are NOT applied and
  have NOT been QA'd; nothing it produced is in `companies.csv`.
* **425** — 7 active rows embed a Comeet board the gate cannot admit; needs one Playwright pass.
* **426** — a worktree has no `secrets.env`, so paid rungs no-op silently. 57 of 57 names came
  back `dead` from a credential-less run; the same 57 resolved once armed. **The operator has a
  key and expects it to be used** — read it from the checkout root, never copy it in (381).

