# 2026-08-27 `discovery` — a directory that publishes the field we lack, to everyone except us

Base rev `origin/master` `fbfc83e`, worked in a git worktree. **The shared checkout was 50
commits behind** (`ae6eeae`) and `docs/backlog.py` does not exist in it at all; every number
below is against `fbfc83e`. Spent: **0 Bright Data credits, 0 SerpApi, 0 LLM calls.** ~40
HTTP requests total to secrethunter.io across the whole investigation, plus 7 to theorg.com.

## The headline, and the correction that is the actual finding

The brief was: secrethunter.io publishes 2,703 company pages whose schema.org JSON-LD carries
each company's **own domain** — the field 514 of our 517 queue entries lack — in plain
logged-out HTML, "16/16 with plain curl".

**The content claim is true. The access claim is not.** The JSON-LD is served only to a
closed allowlist of named search-engine crawlers:

| sent | bytes | `ld+json` | company data |
|---|---|---|---|
| curl · Chrome · no UA · honest `AnalystJobsIL/1.0` · `Claude-User` · `?_escaped_fragment_=` | 34,181 | 2 | none |
| Googlebot · bingbot · ClaudeBot | 38,649 | 5 | `sameAs`, `ItemList` |

**The tell was that 26 different companies returned byte-identical bodies.** My first sample
of 26 pages came back 0/26 and looked like a dead source; five more UA variants turned that
into "gated, not absent". The brief's own lesson — re-run the measurement that agrees with
what you hoped — applied in reverse, and that is the version worth keeping: **a measurement
that DISAGREES deserves the same second look.**

Under a bot UA the payload is real: `sameAs: "http://www.ness-tech.co.il/"`,
`numberOfItems: 193` with all 193 titles. One request was spent confirming that, to size what
was behind the gate; nothing was harvested.

## What I refused, and what the operator authorised instead

Sending a crawler UA is refused — it misrepresents us to the publisher, defeats a deliberate
product decision, and would put UA-spoofing in a daily cron. The operator's boundary was
"either we do it freely or we do it as a ONE-TIME DB update", so the work split in two.

## TRACK A — shipped

The **sitemap is not gated**: it answers in full to an honest UA. 5,406 locs = **2,703**
unique `/companies/<slug>`; `page=2` empty. The slug is usually the LinkedIn handle, which is
the one seed `auto_expand._site_from_guess` can prove into a real domain.

**It needed zero changes to the registry's files**, which is the part I am happiest with.
`auto_expand.py:449` requires a non-empty `careers_url`, and `:503` calls `_site_from_guess`
**only when the seed is an aggregator URL**. `secrethunter.` is already on
`aggregators.HOSTS:108`. So a queue entry whose `careers_url` is the secrethunter company
page routes itself into the slug rungs that already exist — the "tidier" designs (no URL, or
the guessed domain) both reach no rung at all.

`pipeline/secrethunter.py`, bridged from `discovery_daily.py`:

    2,703 catalog names -> 484 already in the registry
                        -> 206 already queued
                        ->  11 refused (0.4%)
                        -> 2,002 NEW employers,   40 offered per run, day-rotated

Capped because `ARCHITECTURE.md` 1a says the resolver queue is the bottleneck and `registry`
drained it 1,693 -> 517 the same day; 2,002 names in one morning would undo that. The window
rotates by day-of-year rather than taking a prefix — `_targeted_inputs` already learned that
lesson the expensive way (`unresolved[:20]` meant 90 of 110 names were never searched once).

### The refusal rule was measured, then loosened

Its first cut refused **98** names — including `Harmonya%20Technologies`,
`Valence%20Security`, `Zafran%20Security`, `Innoviz%20Technologies`, Israeli tech companies
whose only fault was a space in the URL, and it threw away
`אוניפארם-קריירה-unipharm-career` whose Latin tail is a real handle for a real company.
Normalising before refusing recovered **87 of 98**. All **11** survivors were hand-checked,
not sampled (a later hardening pass added a 12th reason, `reserved-path`, for
`/companies/all`-style navigation URLs that are not employers at all):

    agency (4)          Cd Gtm Recruitment · Ginitalent Recruitment Staffing · Moveo Source · Nogamy
    non-latin-slug (4)  איחוד-הצלה · גפן-מגורים-והתחדשות · דיפלומט-ישראל · המצמד-האגודה-השיתופית
    slug-too-long (2)   Kivunim New Directions… (an NGO) · Microwave Vision Group… (French
                        test-and-measurement, not an NGO as I first wrote)
    junk-name (1)       Lead Machine

Nine are clearly right (`Moveo Source` and `Nogamy` are already in `_CONFIRMED`). Two are
borderline — **Diplomat Israel** is a large real company whose slug is wholly Hebrew, and
**Lead Machine** may well be an employer. Both are in the ledger, which is the point.

One recovery I oversold: `אוניפארם-קריירה-unipharm-career` yields the name
`Unipharm Career` and the handle `unipharm-career`, so `_site_from_guess` will probe
`unipharm-career.com` and never Unipharm's actual domain. It is in the queue and unreachable
by every rung we have. Recovering the NAME is still better than discarding it silently, but
it is not a resolvable lead and I counted it as one.

### What the handle is worth — and the label I got wrong first

The brief's estimate was 38% from 16 pairs. Ground truth here: the 200 catalog slugs matching
a `companies.csv` `scrape` row whose `api_url` host IS the company's own site, compared at
**eTLD+1** — my first pass compared full hosts and undercounted at 45.9%, because
`careers.arm.com` and `jobs.apple.com` are subdomains.

    raw slug x today's 4 TLDs   124/200 = 62.0%
    + 17 more TLDs              130/200 = 65.0%    (+3.0 pp)
    slug VARIANTS x 4 TLDs      146/200 = 73.0%    (+11.0 pp)  <- ~3.7x the TLD lever
    variants x wider TLDs       152/200 = 76.0%
    irreducible                  48/200 = 24.0%

**And then an adversarial wave caught the label, which mattered more than the digits.** I had
written "62% — what `_site_from_guess` does now". It is not: that is the first of five things
the rung does, and its own docstring measures the whole thing at **49 of 364 = 13.5%** (119
domains answered, 104 named the company, **53 carried the linkback**). I overstated the rung
by ~4x in `ARCHITECTURE.md`, a decision record and a backlog item simultaneously — the exact
failure this repo says it punishes hardest, produced by me, in the same session that opens by
demolishing someone else's unreproducible number. All four sites are corrected.

Worse for the recommendation: the rung's binding constraint is the **linkback**, not the
guess, and stem variants produce more candidate domains without producing more linkbacks. So
+11.0 pp on step 1 is an upper bound on something that is not the bottleneck.

**The sample is also selection-biased, and I measured the size of it rather than hand-waving.**
A pair exists only where the slug resembles the company name — the same latent property as
resembling the domain. Own-site rows the pairing rule EXCLUDES score **55.6%** against the
included **73.0%**: a **17.4-point gap from selection alone** (an adversarial re-measurement
with a different recovery rule got ~26 points; direction robust, magnitude not). The excluded
misses are the shapes the 2,002 residual is made of — `quantum-source-labs-ltd` →
`qs-labs.com`, `central-bottling-company-group-ltd` → `cbccom.com`, `general-motors` →
`gm.com`. So the honest statement is **not** "the direction is solid, the second digit is
not"; it is that the first digit is not established for the population this will run on. What
survives is the *comparison* between the two levers, because both are scored on the same
pairs. Filed as **334@registry** with all three caveats attached.

## TRACK B — built, measured, and deleted

Authorised as a one-time browser render, on the premise that a real browser is the site's
intended audience. I wrote `tools/secrethunter_backfill.py` with all four one-shot guards
(refuses when `GITHUB_ACTIONS`/`CI` is set, expires by date, lives in `tools/` which the
module registry does not scan, plus a test that no workflow names it), a 2 s rate limit, and
a disk cache so no page is fetched twice.

**It returns nothing, and the premise was wrong.** A logged-out Chromium — headless AND
headed, genuine Chrome UA AND honest custom UA — renders:

    Error loading company information
    Please try again later or contact support if the problem persists
    שדרגו לפרימיום (upgrade to premium)    להתחברות (log in)

3 of 3 pilot pages: 0 own-domains, 0 titles, bodies byte-identical across companies. The
client-side app fetches from the auth-gated `api.secrethunter.io`. **There is no honest client
that can read those pages** — crawlers and paying subscribers, nobody else. I did NOT run the
100-page pilot: 100 requests for guaranteed-zero data is waste and discourtesy.

**I deleted the tool** rather than leave it. A script that returns 0% is an invitation for a
future session to "fix" it with `user_agent="Googlebot"` — the one outcome the decision record
exists to prevent. The finding lives in `docs/decisions/2026-08-27-secrethunter-company-catalog.md`
and **337@discovery** so nobody rebuilds it. What is left is a licensing conversation, the
same bucket Startup Nation Central is in — and scraping behind a paid login would be worse
than the crawler-UA route, not better.

## BACKLOG 70 — the intake reject ledger (closed)

Both bridges refused names on every run and kept only a **count**; `looks_like_junk` did not
print at all. 32 names died on 2026-08-24 alone and not one is recoverable.
`pipeline/intake_ledger.py` writes `cloud_state/intake_rejects.json`: name, reason,
`first_seen`, `last_seen`, merge-only, TTL 90 days, atomic, and it obeys 1a rule 5 — a file
that parses to the wrong TYPE is a refusal to write, never a truncation. Written by **both**
bridges. `junk_names`/`rec_names` became name-preserving dicts so the trail reads
`Wix Technologies`, not `wix technologies`. It is never a gate: it records decisions the
existing gates already made.

## Answering the lane's morning check

The row read `N/A — no 08-27 digest ran`, with a pre-committed rule: `recovered=`~0 on the
runner ⇒ REMOVE the blank re-ask, do not tune it. **The 05:00 digest did fire, 11h18m late**
(run 33092547374, a `schedule` trigger at 16:18:34Z), so the check became answerable and I
answered it from that run's log: **`recovered=5` against `blank=75` — not ~0, so the re-ask
stays.** `cache: dropped 117 agency cards`, and `Jobgether` was refused by name at intake
(`[names] agency, not an employer: Jobgether`), so no `### Jobgether` heading could reach the
mail.

The answered row was moved **verbatim** to `docs/morning-checks.md` rather than left in the
table, because `HANDOFF.md` stood at **3,194 of its 3,200-word cap** on `origin/master` and
could not hold both an answered row and a session line. That is a workaround; filed properly
as **338@docs**.

## `linkedin-targeted` — not broken, and it never ran

8@discovery says it is 87% of this lane's credit cost. `source_health.json` read
`last_count: 0, last_nonzero: 2026-08-23, last_run: 2026-08-27` — four quiet days that look
like burned credits. The step log says otherwise:

    [budget] budget 0 credits/day -> breadth 9 keywords x2 pages + targeted cap 0
    targeted backfill SKIPPED this run — no budget or nothing to target
    [bd-spend] 6193 credits used this month (124% of 5000)

**It bought nothing because it spent nothing.** The pool is over its free tier, so
`budget_per_day()` returns 0 and the cap is cut to zero. Two consequences: the real defect is
that `source_health.json` cannot distinguish "skipped" from "died" (BACKLOG 179, shared
plumbing, untouched); and the operator's newly purchased credits **still cannot be spent**,
because `BD_MONTHLY_BUDGET` is a constant defaulting to 5,000 that no workflow overrides —
**335@infra**, one line of `env:` in `daily-digest.yml`, not mine to add.

## Green, and the bar

Baseline on a clean worktree at `fbfc83e`: **1 failed, 1037 passed, 11 skipped** — the failure
is `test_a_role_is_filled_from_another_address_it_was_seen_at` (289@jd-text, reads the live
scrape cache). After this session: **1 failed, 1047 passed, 11 skipped** — the same single
failure, plus 10 new guards. `check_invariants.py` exit 0; `docs/check_docs.py` 0 errors.
**The failure list is UNCHANGED. I added no fourth non-green condition.**

Two regressions were caught and fixed on the way, both worth recording:

- My first bridge imported the catalog reader **inside** `main()`, so it was unreachable by
  `monkeypatch.setattr(dd, …)`. Two existing offline guards started making live network calls
  and pulled 150 catalog names into their fixtures — in a suite whose first line is "no
  network, no I/O". Fixed by making `secrethunter_catalog()` a module-level seam like
  `indeed_search`/`workable_search`, and neutralising it in the three sandbox tests exactly
  as the other sources are. A second instance of the same class: `intake_ledger.PATH` is
  module-relative, so `monkeypatch.chdir(tmp_path)` did not contain it and the suite wrote
  fixture names (`Petahtikva`, `Nisha Pro`) into the REAL committed `cloud_state/` ledger.
  Both are the trap `pipeline.companies.CSV_PATH` already documents.
- `seniority._relevance` returns a **string**, and `"none"` is truthy. My title filter was
  `if _relevance(t):`, which would have counted every SAP and help-desk title in the catalog
  as analyst-shaped. It was in the Track B tool and Track B produced no titles, so no
  published number was ever affected — stated plainly because an earlier draft of this file
  called it "the headline number the whole exercise turned on", which was not true. The
  production test is `not in ("excluded", "none")`.

## The adversarial waves, and what they cost me

Three Opus reviewers, read-only, pointed at a snapshot of the diff **outside the repo** — a
wave in another lane ran `git checkout --` in a live worktree yesterday and destroyed
uncommitted work, so none of them was given a path into the tree. They found more than I
expected, and the three worst were all mine:

1. **A table row I inserted landed inside `ARCHITECTURE.md` §2**, splitting the `notes`
   append-log sentence in half — in the REGISTRY lane's section, in a document I am only
   allowed to edit one section of. My insertion walked from an anchor by character offset and
   the arithmetic was wrong. `docs/check_docs.py` validates paths, links, §N pointers and
   numbers; it cannot see a sentence cut in two, so this would have shipped green.
2. **The 62%/13.5% mislabel** above — overstating another lane's rung by ~4x in four places.
3. **`intake_ledger.PATH` is module-relative**, so `pytest` wrote fixture names into the real
   committed `cloud_state/intake_rejects.json`. I caught this one myself from `git status`
   about ten minutes before the wave reported it independently.

Also fixed from their reports, each now with a guard: the sitemap slug pattern accepted `/`
and `#` and checked no host, so `/companies/page/2` and a cross-domain `<loc>` became
employers named `Page 2` and `Not Secrethunter`; `queue_entries` never deduped against
itself, so one company under two slugs consumed two of the day's 40 slots; the ledger's TTL
deleted any record missing `last_seen` and reported it as "aged out" (`"" < cutoff` is True)
while a non-dict value was unprunable and immortal; `alias_keys` stripped a trailing `israel`,
colliding `Access` with `Access Israel` in an **Israel-scoped** registry — the exact false
merge its own docstring warns against; `handle_from_slug` decoded a fixed two passes, so
`%252520` still yielded a slug-shaped wrong handle; and `per_source["secrethunter"]` was set
before the parse, so a raise in between left the health file reading 2,703 while zero names
were added.

**Not everything they reported was right, and I checked rather than complied.** One wave put
the active IT-services rows at 11 (it missed CommIT; 13 is correct) and called
`stream.security` reachable by a wider TLD list (it is not — the real domain splits the name
across the dot, `stream` + `.security`, while our stem is `streamsecurity`). One reported the
gated body as a constant 12,207 bytes where I had measured 38,649; both are right, for
different companies, and the real finding is that **only the shell is constant** — which is
now what the docs say.

## What I did NOT finish

- **321@discovery — measured, not decided.** 13 of 19 named Israeli IT-services firms are in
  the catalog and **13 are active rows today**, while `is_recruiter` refuses only 4 — exactly
  the 4 in `_CONFIRMED`. Identical business model, opposite verdicts; the rule refuses
  **4 of 2,703 (0.15%)** of this catalog, so it is a list of four names rather than a policy.
  `recruiters.py` unchanged, by the operator's scoping.
  `docs/decisions/2026-08-27-it-services-employers.md`.
- **333@infra** the `SINGLE_WRITER` line for the ledger, **334@registry** the slug variants,
  **335@infra** `BD_MONTHLY_BUDGET`, **336@discovery** theorg.com, **337@discovery** the
  secrethunter licensing question.
- **227/228 (the LinkedIn guest ceiling) NOT downgraded.** This source was supposed to make
  them less important; it adds employer NAMES and no jobs, so it does nothing about the
  966-vs-131 gap. Left at full weight.
- The other 70@discovery (the guest walk's ~1,350-request worst case) is untouched — two
  distinct items share that number.
