# 2026-08-30 — which source would actually give the registry a company's OWN domain

*lane: `discovery`. A research session, not a build: the deliverable is a number per
candidate, a ranking, a recommendation, and an explicit list of what is NOT built. Every
number below was re-derived from a worktree at `origin/master` `c1fda51` on 2026-08-30;
the commands are in `docs/sessions/2026-08-30-discovery.md`. Spend: 0 Bright Data credits,
0 SerpApi, 0 LLM calls; ~120 honest-UA HTTP GETs.*

## 0. The bar, and the finding that reframed the question

**The bar** (set 2026-08-28, still right): a source is useful only if it yields a company
NAME **plus the company's OWN DOMAIN**. A name with an aggregator link reaches no rung
that can prove an address, and the registry lane is already fighting a queue of exactly
that shape.

**The finding**: the intake queue (`research_companies.json`) holds **572** entries and
their `careers_url` points at **secrethunter.io 456 · il.linkedin.com 104 · il.indeed.com 3
· nothing 8 · an own domain 1**. Aggregator-hosted 563, own-domain 1. Reproduced exactly.

**The premise attached to it does not hold.** The brief said *"secrethunter was worth it
because its sitemap carries the domain — so either the extraction is not running or the
value is discarded."* No decision record says that; the sentence comes from the operator's
stale Desktop prompt. The 2026-08-27 record
(`docs/decisions/2026-08-27-secrethunter-company-catalog.md` §2–3) says the opposite: the
sitemap carries the **LinkedIn handle**, the domain sits in JSON-LD served only to
Googlebot/bingbot/ClaudeBot, spoofing a crawler UA was **refused**, and a real browser gets
`Error loading company information`. An adversarial pass today re-walked every keyless
path — all five sitemap types, the `/jobz/` shell, `api.secrethunter.io` (403), every
cached body in the repo — and found **no domain field to discard**.

So `pipeline/secrethunter.py:434` writing `careers_url = secrethunter.io/companies/<slug>`
is **by design** ("THE SEED IS NOT A VERDICT"): an aggregator seed routes `auto_expand` to
the handle rung, `_site_from_guess`, and the resolvable field is `slug` — filled on
**454 of 456**. There is nothing to fix in the extraction.

## 1. Questions (1) and (2): the "free wins", sized

`_site_from_guess` (`auto_expand.py:374`) turns a handle into a PROVEN domain: the site
answers, names the company, links back to `linkedin.com/company/<handle>`, is not foreign.
`cloud_state/queue_state.json` records every attempt.

| | secrethunter 456 | LinkedIn 104 |
|---|---|---|
| handle present | 454 | 100 |
| own-site rung already tried | **272** | **76** (77 attempts) |
| `no-domain-answered` | 212 | 53 |
| `no-linkback` / `not-named` / `redirected-off` | 35 / 12 / 3 | 6 / 5 / 1 |
| `no-handle` | 6 | 7 |
| **`resolved-domain`** | **4** (2 foreign: Geniussports, Gevernova) | **4** (1 an agency: Maof → maof-hr.co.il) |
| never tried | 184 | 28 |

**Read the yield from the right population.** All 881 own-site records carry one date,
2026-08-29 — a one-day backfill by the registry lane, not nightly attempts — and 46 of the
rung's 55 successes have since LEFT the queue (41 are rows). Over everything it ran on the
rung yields **55/881 = 6.2 %** (13.5 % on real handles, `auto_expand.py:383`); on today's
residual queue it reads 8/349 = 2.3 % because the winners are gone. `resolved-domain` is
evidence, not a board — `queue_state.py:59-63` says so — and of verified domains
`resolve_llm` then resolves **7.3 %** (`docs/sessions/2026-08-29-registry-queue.md`).

**Expected from the 214 untried names (212 on the two aggregator hosts; `queue_state.py`
reports 213 owed the rung): ~13 domains (3–30), then ~1 board** — and the board is not
free, it is a `claude -p` call at `LLM_RESOLVE_CAP=10`. The rung already runs twice a day
(`auto-expand.yml`, `0 8,20 * * *`, `AUTO_EXPAND_SITE_MAX=25`): 176 of the 214 have never
been in an auto-expand batch, sort to the front of `todo` (`auto_expand.py:600-604`) and
are reached in ~7 runs (~4 days); the other ~38 are indistinguishable from the 340 already
refused, because **`auto_expand` writes no per-rung record** (`grep -c queue_state
auto_expand.py` → 0 — the 881 own-site records are the registry lane's 08-29 backfill via
`queue_pipeline`), so they fall into the ~22-run cycle over all 552 handle-bearing names.
Progress is NOT readable from `queue_state.json`; only `queue_pipeline.py --census`
re-derives it. Nothing to build; one thing to know.

**LinkedIn (2):** the bridge keeps six card fields (`discovery_daily.py:247-262`) and there
is no seventh carrying a website; the guest job-view page carries no non-LinkedIn link
(measured on two queue URLs today — `Aristocrat`, `University of Haifa`; the only own-domain
signal is an e-mail address in the JD prose, the exact substring trap the 08-27 record
warns about). `_site_from_slug` (the LinkedIn `/about/` page) is a sign-in wall — measured
0 of 3, off by default (`AUTO_EXPAND_SLUG_SEED`). Nothing is being thrown away.

## 2. Question (5): what the queue names ARE — this outranks every new source

All three intake gates refuse **0 of 572** (`looks_like_junk` 0 · `is_place_name` 0 ·
`is_recruiter` 0). Item 9's original class — a job title in the employer slot — is gone
(7 names carry a title-ish word; all are real organisations). What is in the queue instead,
by a full hand-read of the 572 (adversarial pass, verified on a seeded 100):

| class | n | examples |
|---|---|---|
| plainly foreign, no Israeli operation | **79 (14 %)** | `Wzv Sint Gillis Waas` (a Flemish water board), `Cityofdesperes` (Missouri), `Lycee Professionnel Toulouse Lautrec`, `Ministere Des Affaires Etrangeres Francais`, `Holimont Ski Resort`, `Klett Schokolade Gmbh` |
| not an organisation, or not a distinct employer | **67 (12 %)** | `Gov Il`, `Matnasim` (a common noun), `Mali`, `Levant`, `SD;LC`, three spellings of monday.com, job-board brands `Gamblingcareers` / `Joberacom` / `Huzzle Com` |
| recruiters that `is_recruiter` PASSED | **23 (4 %)** | `Sales Experts Executive Recruiters`, `Human Capital Recruitment1`, `ELAD HR`, `Bridgz Outsourcing`, `Brooks Keret` |
| union | **~155 (27 %)** | |

**The recruiter hole was a regex boundary and is fixed in this commit** — the one code
change this session makes, in the lane's own file: `pipeline/recruiters.py:144`
`recruit(ing|ment|x)?\b` never matched the plural noun (*Recruitment* refused, *Recruiters*
admitted) and `\b` never fires before a digit. Widened to `recruit(ing|ment|ers?|x)?` with
`(?![a-z])`, plus `hr consulting`. Blast radius measured before the change: **3 queue names
newly refused, 0 active registry rows, 1 parked row** (`Yamo Overseas Recruiters Limited`,
correctly). Guard: `test_the_recruiter_keyword_matches_the_plural_noun_and_a_trailing_digit`;
mutation `recruiter-plural-drop`. The other 20 (`ELAD HR`, `Bridgz Outsourcing`, …) need
`_CONFIRMED` entries after research, not a wider regex — filed.

**The catalog is where most of the foreign names come from — because it is most of the
queue.** Per name it is ~2× as foreign as the LinkedIn seed (the LinkedIn 104 hold ~8 plainly
foreign, 7.7 %; the catalog 456 must hold ~71, 15.6 %), so a refusal aimed only at catalog
slugs still leaves ~8 foreign LinkedIn names per queue.

**And its yield, on a CONSISTENT basis** — reconstructed over all 34 commits touching
`research_companies.json` (catalog names first entered 08-21, not 08-26), joined to
`cloud_state/roles.csv` by `identity_key`:

| seed | ever queued | rows | active | with a role | role / active |
|---|---|---|---|---|---|
| catalog | 1,075 | 545 | 246 | 12 | **4.9 %** |
| linkedin | 522 | 376 | 151 | 38 | **25.2 %** |
| indeed | 47 | 40 | 22 | 8 | 36.4 % |
| registry, all | — | 2,045 | 1,099 | 96 | **8.7 %** |

Age does not explain it: on names first queued on or after 08-23 — same weeks of scans —
the catalog converts at **3.3 %** (6 of 182 active) and the LinkedIn seed at **12.2 %**
(15 of 123). So the gap is real and not survivorship, **but it is 1.8× against the registry
and 5× against LinkedIn, not the 11× my first draft claimed** ("1.1 % vs 12 %" divided
catalog rows into matched companies and compared that to a per-active-row figure; and the
"28 rows, 0 roles" before it measured the pre-catalog Telegram `/jobz/` seeds — both
caught by the adversarial passes). Twelve companies with roles at 0 credits is what a
throttle spends. The catalog adds 150 names per RUN, and the pipeline commits **up to four
runs a day** (four `cloud run` commits on 08-28, 586 catalog names first queued that day),
which is the queue's refill 210 → 572.

## 3. Question (3)–(4): the candidates, costed against the bar

| candidate | keyless · machine-readable | carries the OWN domain | NEW companies | cost | noise | measured |
|---|---|---|---|---|---|---|
| **Wikidata — TASE-listed companies** (`P414=Q1507974`, website `P856`) | yes · SPARQL JSON, one GET | **yes** | **675 entities not in registry or queue, 574 with a website** (778 total; 96 known, 7 queued) | 0 credits; wiring = one weekly GET | the population is real-estate, energy partnerships, small caps — and the large caps are banks and insurers whose boards are finance titles | random 30 of the new: 22 homepages answered, **4 careers pages read, 0 analyst-shaped titles**. Large-cap stratum (Bezeq, Discount Bank, Bank of Jerusalem, Shufersal, Strauss, Partner, Cellcom, Delek, Paz, Harel, Migdal, Menora, Rami Levy, Fox, Shikun & Binui …): **51 companies / 49 sites, 46 homepages answered, 18 careers pages read, 3 analyst-shaped title strings — 0 of which the repo's title gate ACCEPTS and all 3 of which would cost an LLM call** (`Investment Analysis Analyst/Associate` is not on `_HARD_EXCLUDE`, which carries `investment analyst`; `Google Analytics / Statistics` is a skill line; Paz's `אנליסט/ית טרייד מרקטינג` is `signal` with no description → refused on a breaker-open morning). **The "unread JS boards" are not an unmeasured upside:** Discount Bank's board is Oracle Recruiting Cloud, which `fetch_oraclehcm` reads today with no new code — **64 requisitions, 5 signal-tier titles, 0 in scope**: two credit analysts (out by the 08-28 scope), a bare Data Scientist, and Hebrew forms of `systems analyst` and `project manager` that the English `_HARD_EXCLUDE` would have killed deterministically |
| **Geektime funding RSS** (`/category/funding/feed/`, pages with `?paged=N`) | yes · RSS 2.0, 30 items per page | **rarely: 7 of 30** | 60 items over 81 days (two pages, 8 Jun → 28 Aug) = **0.74 items/day**; of the last 30, ~24 name an identifiable employer, **9 already in the registry or queue** (ActiveFence, At-Bay, BioCatch, Cyera, Decart, XSight, Glow, Encore, Faye), 2 are round-ups, 5 are acquisitions (a worse lead, not a new one) → **≈ 9–11 genuinely new employers a month, ~4 of them with a domain** | 0 credits; needs a Hebrew-prose name parser or an LLM call per item | funding items only; the main feed is gadgets and Google news | first hand-read said 19 new; the `identity_key` join corrected it |
| Globes tech RSS (HE `iID=594`, EN `iID=1725`) | yes · RSS | no (image hosts only) | columns and analysis, not company announcements | 0 | high | 15 / 93 items, 0 with an employer domain |
| TheMarker `cmlink/1.145` | yes · RSS, 100 items | unverified | general business news (fuel prices, TASE indices) | 0 | very high | its `/misc/rss` index page exposes no per-section feed ids |
| Calcalist / CTech RSS | **no feed found** — every guessed URL 404, the RSS index pages are empty or 404 | — | — | — | — | not machine-readable keylessly today |
| **Drushim** | company LIST page 200 (SSR, 96 links); **every company page it links to is a 404** — with `urllib` (4/4) and in a real Chrome (2/2: superfish, Matrix) | **no page, so no domain** | — | — | — | AllJobs again; not re-tested further |
| **AllJobs** | companies page 200 | **no** — the only outbound link is AllJobs's own LinkedIn | — | — | — | the 08-27 rejection stands; note the "2,069 employers" figure has no reproducible record in the repo (carried from the operator's investigation). **Do not propose a third time.** |
| theorg.com (BACKLOG 336) | yes · JSON-LD (7/7 on 08-27) | **yes** (`url` + LinkedIn `sameAs`) | a RESOLVER for names we hold, not a source | 1 GET per name, ~572 | global, no titles | unchanged since 08-27; not built |
| Bright Data LinkedIn company dataset (website per handle) | key · per RECORD | yes | resolves the 562 handles we hold | 562 credits = 11 % of a month from 2026-09-01 (free until then) | the family that `rate_limit`ed for five days | **rejected without a sample**: it buys a domain for names that are 27 % noise |
| secrethunter with a crawler UA | — | yes | — | — | — | **refused on 08-27 and refused again** |

## 4. Ranking, and the recommendation

Against "≈13 domains, ≈1 board, for free, already draining" as the baseline:

1. **Slow the catalog before adding a source, and be precise about what that buys.**
   `SECRETHUNTER_QUEUE_CAP` (150/run, `daily-digest.yml:101` + `pipeline/secrethunter.py:78`)
   was the operator's front-loading value and the front-loading is half done (892 of 2,002
   offered). At **40 per run** (the 08-27 record's throughput-derived figure) net growth falls from
   the measured **~+138 to ~+28 per run — but the cap is per RUN and the pipeline commits
   up to four runs a day (586 catalog names on 08-28), so the throttle that bounds anything
   is per DAY**, a date-keyed window in `pipeline/secrethunter.py` rather than an env line; and catalog names stop
   displacing job-backed LinkedIn leads at the front of the resolver batch. **It does NOT
   change the 27 % noise share** — the window is day-rotated, so every slug is still
   reached, just over ~28 days instead of ~7. An adversarial pass established that no
   Israel filter is computable at intake: `company_identity.is_foreign` is a name-vs-domain
   identity check (1 of the 4 headline foreign names caught; applied to the only URL intake
   holds it refuses the whole catalog, Cellcom included), and a real signal costs
   `_site_from_guess`'s ≤4 GETs / ≤20 s per name — 150 names is ~50 min inside a step capped
   at `timeout-minutes: 25`. So: a per-day cap (`discovery`'s file; the env line is `infra`'s), then re-measure
   the 4.9 % in a fortnight; a filter is a separate, costed decision (`483`).
2. **Wikidata TASE — not at all, and the reason is the classifier, exactly the risk the
   operator named.** It is the one probe that passes the bar outright and costs nothing,
   which is why it was measured twice. A random 30 of its 574 new domains read 0
   analyst-shaped titles; the 51 large caps read 3, **none the title gate accepts and all
   three LLM calls**; and the one bank board the repo can already read keylessly
   (Discount Bank, Oracle HCM, 64 requisitions) yields **5 signal-tier titles and 0
   in-scope roles**. Extrapolated over the ~10 bank/insurer boards this is roughly 30–50
   extra signal-tier calls per scan against a 300/day cap running at 67–83, buying
   nothing. The source's first-order effect is cost and false-positive pressure, not
   roles. If anyone re-measures, the instrument is a `platform_check` sweep over the ~10
   ATS-hosted boards, not Playwright — and the Hebrew hard-exclude gap it exposed is
   filed for `classifier` (`486`).
3. **Geektime funding RSS — small and real, and below the free baseline:** ~9–11 new
   employers a month, ~4 with a domain, against ~13 domains draining from the untried
   queue for nothing. Worth a keyless reader only after (1), and only if a Hebrew name
   parser is cheap; the domain-less two-thirds arrive in the same shape as the LinkedIn
   queue.
4. Everything else: not worth a line of code.

**What I would NOT build:** Drushim (no company page reachable); AllJobs (no domain — for
the second time in writing); a crawler-UA or logged-in read of secrethunter; the Bright
Data company dataset; RSS from Globes/TheMarker (no employer signal); Calcalist/CTech (no
feed); any source whose output is a name without a domain; and any new source at all
before the catalog's intake is throttled — a source that adds resolvable names to a queue
that is 27 % noise makes the registry's day worse, not better.

## 5. Alternatives considered, and why each was rejected

- *"Raise `AUTO_EXPAND_SITE_MAX` so the 214 untried names drain tonight."* Rejected: a
  successful guess unlocks a ~342 s `resolve_deep` with no deadline check (ARCHITECTURE
  §1a, BACKLOG 339); the 176 never-batched names reach the rung within ~7 twice-daily
  runs anyway.
- *"Filter the catalog on an Israel signal at intake."* Rejected for today: not computable
  without a GET per slug (see item 1); filed as a costed follow-up rather than recommended.
- *"Drop the secrethunter catalog entirely."* Rejected: 4 companies with roles at 0 credits
  is not nothing, and 1,110 of its 2,002 names are still unoffered; throttle and filter
  rather than delete, and re-measure the 4.9 % after the cap.
- *"Wire the TASE list now, it passes the bar."* Rejected until the large-cap stratum is
  read: the bar is necessary, not sufficient — a domain with no careers board is a row that
  scans empty forever, and `confirm_zero` already audits 200+ of those.
- *"Sample Drushim with a browser UA / logged in."* Rejected: same conduct rule as
  secrethunter; and the site's own links 404 in a real browser, so there is nothing behind
  them for an honest client.
- *"Use Bright Data for the RSS names' domains."* Rejected: 5,000 credits/month from
  2026-09-01 and the names are ~10/month — `_site_from_guess` on a Latin name is free.

## 6. Filed, not fixed

- `486@classifier`: `_HARD_EXCLUDE` carries `systems analyst` and `project manager` in
  English only; the Hebrew `מנתח.ת מערכות` and `מנהל.ת פרויקטים` reach the signal tier and
  cost a call each (Discount Bank, 2 of 5 signal titles). `investment analysis analyst` also
  slips past `investment analyst`.

- `482@company-intel`: the public `sector` enum is not normalised — active rows carry
  `cybersecurity` 135 / `Cybersecurity` 38, `fintech` 66 / `Fintech` 13, `semiconductors`
  20 / `Semiconductors` 5, `adtech` 8 / `AdTech` 3, `retail tech` 3 / `Retail Tech` 3, and it
  ships in `https://analystjobsil.github.io/board/roles.csv`.
- `483@discovery` (+`infra` for the env line): the catalog's per-DAY cap (item 1 above); the Israel filter is a separate costed decision inside it.
- `484@discovery`: 20 agencies still pass `is_recruiter` and need researched `_CONFIRMED` entries.
- `485@discovery`: `discovery_telegram.py:58` sends a spoofed Chrome UA — the opposite of the
  conduct the 08-27 record commits to; and `parse_post` keeps only the first URL of a post.

## 7. Built the same evening: the per-day cap (483), at the operator's instruction

*"Wire nothing, throttle the catalog" was half delivered while the throttle was a backlog
item.* Shipped in `pipeline/secrethunter.py` + `discovery_daily.py`, no workflow change:

- **The window is cut over the catalog minus registry rows and retired names**, not over
  "what is not queued yet". That basis moves only when the registry gains a row, so every run
  of one day selects the same slice and the second run adds nothing — no state file. Cut over
  the raw catalog instead, a slice landing on known names offered almost nothing (the real
  catalog is 38 % known), which the existing shape-alarm test caught.
- **`SECRETHUNTER_DAY_CAP` = 40**, and the effective offer is `min(QUEUE_CAP, DAY_CAP)`, so
  the workflow's per-run 150 is bounded without touching `.github/` (`494@infra` retires
  the stale env line). 40 is from the flows: the registry's queue arms stamp ~120 rows a
  night (79 / 422 / 57 by note date on 08-28/29/30); LinkedIn+Indeed intake is 26–178 names a
  day, median ~50; catalog intake was 598 / 150 / 144 on its three days. At 40/day a median
  day is ~90 in against ~120 out.
- **Retired names are not re-offered** (`queue_pipeline.RETIRED_VERDICTS`, imported lazily;
  an unreadable disposition file reads as "nothing retired"). This is 441, and it WAS intake:
  the two 08-30 cloud runs re-added 149 catalog names each, ~100 and ~48 carrying a
  retirement verdict. Dry run on the real catalog today: 2,703 slugs → 1,026 known · **258
  retired** · 324 queued · 1,083 fresh → **2 offered** (the day's region had already been consumed by the morning's two runs), **0 on a second run, 1 after one row activation**. Steady state ≈ 40 × 1,083/1,407 ≈ **31 a day**: a name waiting in the queue keeps its slot, which is the price of an idempotent slice.

**What the queue should look like after it** (question 2): intake ≈ 31 catalog + ~50
LinkedIn/Indeed ≈ **80/day median** against the registry arms' ~120/night, so the queue
**shrinks ~40 a median day** and grows only on a LinkedIn spike (three of the last seven
days were 100+); the 1,407-name basis takes ~35 days to cycle and, once offered,
are never re-offered unless the registry's verdict is overturned. On 08-28 the same arithmetic
was 586 + 53 in against ~80 out. Guards: `test_the_catalog_offers_the_same_slice_on_every_run_of_one_day`,
mutations `catalog-window-over-fresh`, `catalog-retired-drop`. Unattended proof due: the
first `[secrethunter]` step line after this lands must read `day window 40` and an `offered`
≤ 40, and the second run of the same day `offered 0`.

**The 146 names with no gate — cap or filter?** (question 3): a cap. The 67 not-an-employer
/ duplicate names are exactly what the registry's `--dispose` retires, and with dispositions
honoured they stay out; the 79 foreign names die at the own-site rung's `is_foreign` — the
filter already exists, at the only cost it can have (a GET per name), and the cap bounds how
many reach it. No second filter.

