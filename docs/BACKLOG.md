# Backlog — what is known-wrong and not yet fixed

> Item numbers restart per section (1-15 are reused). Cite an item by its SECTION heading
> plus its number; numbers above 15 happen to be unique, by luck, not design.

Everything here is **durable**: a design debt or a known gap that outlives any one session.
Current-state items ("what broke last night", "what to watch tomorrow") belong in
`HANDOFF.md`, not here; dated narrative belongs in `docs/sessions/`.

Moved out of `HANDOFF.md` §4c/§4d verbatim on 2026-08-23 by the `docs` lane. Each item names
the lane that would own the fix (see `docs/AGENT_BRIEF.md` for the lane table). Nothing here
is claimed — if you take one, say so in `HANDOFF.md`.

---

## From the ten-agent audit, 2026-08-22

**Known and NOT fixed — the ranked backlog:**
1. `pipeline/ats.py` registry: adding an ATS platform still touches ~22 sites in 14 files;
   `platform_check` reports the gaps but the consolidation itself is the real fix.
2. Relative-date parsing exists in 5 places with different capabilities (none handle
   "week"/"hour"; SerpApi dates never normalize at all).
3. ~~`_REQ_HEADER` in `seniority.py` is dead code~~ — **closed 2026-08-24 (`classifier`)**:
   `_desc_is_ml` and the LLM's `prompt_slice` both start at the requirements header when one
   exists (375 stored JDs: `_ROLE_START` hit 183, `_REQ_HEADER` 119, and in 29 of those the
   requirements began past the 1,400-char window); 0 of the 252 asserted title-only decisions moved on the first cut; 3 changed on purpose in wave 1 and carry `"changed"`.
4. `metrics.jsonl` (one JSON line per run) would answer "is coverage growing / did a source
   die / did the classifier stop working" — none of which is answerable today.
5. Company aliases: `Meta`+`Meta Israel`, `IBM`+`IBM Israel`, `Port`+`Port.io` are separate
   active rows scraping the same board.
6. `mark_sent` records intent, not delivery — a relay failure burns roles as sent.

## Infra inputs from the firmographics workstream

*(was `HANDOFF.md` §4d, first of the two sections that carried that number)*

What building §7 (and three adversarial-review waves over it) revealed about the
infrastructure itself. Complements the ten-agent audit backlog above; ordered by leverage.

1. **One state layer, not two.** The local/cloud split (`state/` vs `cloud_state/`) forced
   every firmographics consumer to care *which* seen.db it reads, and open item 7 exists
   because sqlite binaries can't git-merge. Direction: keep sqlite as a per-machine cache
   and make the *committed* artifact a text export per table (JSON/JSONL — diffable,
   row-mergeable with the `merge_csv_rows.py` pattern), or move shared state off git
   entirely. Whatever the choice, "who owns which table" should be declared in one place.
2. **Retire `companies.csv` as a database.** 20 writers, a state machine encoded in prose
   verdict strings, six allowlist pools that must be updated in sync (the documented #1 bug
   class), plus literal duplicate rows (Datadog/MongoDB/Elastic twice) and alias rows
   (Meta/Meta Israel — audit item 5 above). A registry table with an explicit state enum +
   transition log would delete the entire "verdict-string rule" hazard category.
3. **One identity layer.** `_norm_company` existed but nothing used it for keys — that gap
   alone produced 9 double-researched companies and 3 wasted run.py budget slots per digest.
   Normalized identity (plus an explicit alias map for the Meta/Meta-Israel class) should be
   THE key in every store, join, and dedupe — not a per-consumer patch, which is what the
   firmographics fixes are today.
4. **A single automation inventory.** Jobs now live in three schedulers: GitHub Actions
   crons, the Windows scheduled task (`IsraeliJobs-Firmographics`, 6-hourly), and whatever a
   session runs by hand. Nothing lists all three; ARCHITECTURE.md section 4 covers only CI. One table
   (owner, trigger, machine, quota it spends, state it writes) is a prerequisite for making
   anything "less messy" — you can't simplify what you can't enumerate.
5. **Design away the Windows-automation traps instead of re-fixing them per script:** cp1252
   stdout under redirection (three scripts crashed on Hebrew names before
   `sys.stdout.reconfigure`; mandate `PYTHONIOENCODING=utf-8` at every entrypoint), cmd/
   PowerShell quoting for detached launches (an inline `Start-Process` argument string
   failed silently; committed `.cmd` wrappers work), unbuffered `-u` for anything logging to
   a file, and **git + sqlite inside OneDrive** — sync races with live db writes are an
   incident waiting; consider excluding `state/` from sync or moving the repo out.
6. **Consolidate root-script sprawl.** 40+ root scripts, several executing on import (no
   `__main__` guard), each hand-rolling its own arg parsing, secrets loading, store opening,
   and now UTF-8/retry boilerplate. A `python -m pipeline <command>` CLI with shared
   bootstrap would shrink the surface the next audit has to re-verify.
7. **Unified quota ledger.** LLM calls are spent from four sites (role judgments, blurbs,
   firmographics research, employee fills) plus Bright Data credits and SerpApi — each with
   its own caps and none metered centrally. Extending the `metrics.jsonl` idea above with
   per-source spend counters per run would make "what does a day of this system cost" and
   "what just burned the quota" answerable.
8. **One backoff/retry store.** The same gating machinery now exists twice
   (`cloud_state/resolve_attempts.json` for self-heal; `firmo_failed` + retry-day constants
   for firmographics) with different semantics (weekly/5-strikes vs weekly/monthly). A
   generic attempts table (key, kind, strikes, last, next-eligible) would serve both and
   whatever comes next.
9. **Validate discovery output at the source.** Job titles leak into company names ("Sql
   developer - X", "my team", "AppSec") and then every downstream layer needs its own guard
   (`looks_like_junk` is a patch, not a fix). The discovery bridge should validate/reject
   company fields before anything enters `research_companies.json` or `matched`.
10. **Let company-death knowledge flow back.** Firmographics research keeps discovering
    defunct/absorbed companies (Alike Health, Syte, Sckipio, SimilarTech, NanoLock, Rewire
    R&D) but that knowledge dies in a JSON field — rows stay active and keep being fetched.
    A small review queue proposing `defunct:` parking from firmographics evidence closes
    the loop.

## Honest state of the infrastructure — READ BEFORE ADDING ANYTHING

*(was `HANDOFF.md` §4d, second of the two sections that carried that number)*

**It is sprawling, and that is the top thing to fix next.** Numbers, not adjectives:
68 root scripts (registry_health.py added 2026-08-24), 10 workflows, 27 root scripts invoked by a workflow (re-counted
2026-08-23 — it said 62/19), and **23 separate tools whose job
is "work out where a company's jobs live"**:

    auto_expand  resolve_llm  resolve_deep  resolve_broken  resolve_any  resolve_parallel
    resolve_unknowns  listing_hunt  deep_validate  crack_walled  audit_empty_rows
    validate_empty  validate_bd  recheck_suspects  wayback_rescue  bd_rescue
    retry_unreachable  scan_dead_domains  triage_dark  repair_extract_gap  probe_ats
    detect_ats  comeet_resolve

Each was a rational response to one concrete failure (a bot-walled ATS, a dead domain, a
JS-only page, a stale URL). Together they overlap heavily, share four near-duplicate
detection tables, and are individually cheap but collectively hard to reason about. Nobody
designed this shape; it accreted in a day.

**What is genuinely load-bearing** (touch these first, ignore the rest until you must):
`pipeline/` (run, fetchers, seniority, israel, store, digest, health, verdicts,
aggregators, atomic), `scrape_universal.py`, `auto_expand.py`, `listing_hunt.py`,
`triage_dark.py`, `discovery_daily.py`, `discovery_telegram.py`, `refresh_scrape_cache.py`,
`enrich_scrape_jd.py`, `probe_candidates.py`, `check_invariants.py`, `merge_csv_rows.py`.

**Legacy / one-shot / superseded** — this list has moved to `docs/MODULES.md`, which
classifies every root module and is enforced by `docs/check_docs.py` (a new root script
with no entry there fails the test suite). Two names on the original list were wrong:
`ingest_research` is imported by `retry_unreachable.py`, which runs daily at 02:30, and it
in turn imports `probe_ats` for `slug_variants` — deleting either breaks a scheduled
workflow. That is precisely the "imported for their regex tables" hazard, so the registry
records the importer for every legacy module rather than the adjective.

### The consolidation plan, in order

1. **`pipeline/ats.py` platform registry.** One frozen dataclass per platform (host regex,
   detection patterns, endpoint builder, fetcher, flags). Derive `FETCHERS`, `ATS_HOST`,
   `SIGS`, `ATS_PATTERNS`, `_HTML_ATS`, the `resolve_llm` prompt table + enum, and the
   `empty-board` exemption from it. Adding a platform becomes one literal instead of ~22
   edit sites in 14 files. `pipeline/platform_check.py` already reports the gaps — use it as
   the regression harness, and rewrite it to assert against the registry rather than grep.
2. **Collapse the 23 resolvers into one ladder with pluggable strategies.** They already
   form a de-facto ladder (deterministic → LLM → render+sniff → listing-hunt → unlocker);
   make that explicit, with each strategy a function and the triage mode selecting which to
   run. `triage_dark.py` is the right seam — it already classifies; the resolvers should be
   its handlers.
3. **`pipeline/dates.py`** — five relative-date parsers today, none handling "week"/"hour",
   and SerpApi dates never normalize at all.
4. **`pipeline/jdtext.py`** — `_ROLE_START` / `_ROLE_MARKER` / `_REQ_HEADER` / `_REQ_HARD`
   are four vocabularies for "where does the role text start". `_REQ_HEADER` is dead code,
   and `_desc_is_ml`'s docstring describes behaviour it does not have. Measured: the digest
   copy finds a requirements header in 21% of JDs where the classifier copy does not, which
   is why the LLM often never sees the requirements section.
5. **`metrics.jsonl`** — one line per run (rows, active, scanned, failed, empty, paths,
   by_source). Nine counters are already computed and thrown away in `run.py`. Without it
   nobody can answer "is coverage growing" or "did a source die" — Indeed silently returned
   zero for five days and nothing noticed.
6. **Company aliases** — `Meta`+`Meta Israel`, `IBM`+`IBM Israel`, `Port`+`Port.io` are
   separate active rows scraping the same board.
7. **Concurrency** — five workflows share `repo-state`; long jobs queue for hours and
   superseded runs are recorded as `cancelled` with zero output (happened twice today).
   Either shard the group or shorten the long jobs.


## From the `discovery` lane, 2026-08-23

Found while auditing the intake layer. Each was verified with the command shown; none is
fixed, and every one of them is outside the `discovery` lane's write list.

1. **A company can leave `companies.csv` and nothing anywhere says so.** *(lane: `infra`,
   with a line for `render`.)* `check_invariants.py` checks shape, duplicate names,
   scannability and tenant identity — it never compares the row set against the previous
   commit, so a delete passes the blocking gate. `merge_csv_rows.merge()` iterates `ours`
   only: a name in `base` and missing from `ours` is not in `changed`, so the merge neither
   restores it nor mentions it. The digest email's run audit reports `companies_scanned` but
   no registry delta. Three commits have shrunk the file (`git log` over `companies.csv`,
   row counts per revision): `88d2b50` −13 (LinkedIn-poisoned rows, reason in the subject),
   `c0f7635` −3, `0180e75` −2 (Cordio Medical, JPMorganChase). All three were deliberate and
   explained in the commit message; none was visible to the pipeline or to the reader of the
   mail. **In flight:** an untracked `registry_health.py` appeared in the working tree at
   20:35 on 2026-08-23 while this was being written — another session (`registry`) is
   answering exactly the first half of this and reports **15 name-deletions across the whole
   history of the file**, one of them deleted on purpose, resurrected by a concurrent run's
   conflict merge, then re-deleted as a silent side effect of a commit about Oracle HCM. Do
   not build a second one; check whether it landed. What it does not cover is the second
   half — getting the delta in front of the reader.
   Proposed: `check_invariants.py` diffs the company-name set against
   `git show HEAD:companies.csv` and (a) fails on a delete carrying no `defunct:` /
   `duplicate` / `alias-of` reason, (b) exports the delta so `pipeline/digest.py` can print
   `registry: +N −M` with the reason in the run-audit block. Re-derive the shrink list with:

       for c in $(git log --format=%h -- companies.csv); do echo "$c $(git show $c:companies.csv | python -c "import sys,csv;print(sum(1 for r in csv.reader(sys.stdin) if r))")"; done

2. **The discovery bridges can only seed an aggregator URL, and the registry keeps it.**
    **CLOSED 2026-08-25 (`registry`, via 177):** the proposal is the code — `auto_expand.py` skips `resolve_deep` for an aggregator seed and never writes its `empty`/`unreachable` row (deferred on rotation); `--clear-agg-urls` un-buried the 28 rows. The counts are stale (queue 514 of 1,544 aggregator-seeded at HEAD, not 206 of 1,233); the secrethunter 33,495-byte shell finding still holds.
   *(lane: `registry`.)* A discovered job's `url` IS the posting on LinkedIn / Indeed /
   secrethunter, so `careers_url` in `research_companies.json` is an aggregator for **206 of
   1,233 entries** (132 secrethunter.io, 45 linkedin.com, 26 il.indeed.com; measured
   2026-08-23). `auto_expand` guards the `scrape` branch — an aggregator result is parked
   with "aggregator URL; resolve real careers page before activating" — but its `empty` and
   `unreachable` branches write that same seed URL into the row unguarded, which is why
   **45 registry rows carry an aggregator URL today** (39 inactive, 6 active where it sits
   harmlessly in the unused `token` column). `secrethunter.io/jobz/<id>` cannot be followed
   to the real posting either: tested 2026-08-23, it 200s to a 33,495-byte JS shell that is
   byte-identical for every job id and holds no external link but facebook/linkedin pixels.
   Discovery cannot drop the field — `auto_expand`'s `todo` filter requires `careers_url`
   truthy, so a company with none would never drain. Proposed: `auto_expand` skips the
   deterministic rung when `is_aggregator(careers_url)` and goes straight to `resolve_llm`
   (which searches by NAME and does not need the seed), and its `empty`/`unreachable`
   branches write `""` rather than the aggregator. Verify with:

       python -c "import json;from pipeline.aggregators import is_aggregator as a;r=json.load(open('research_companies.json',encoding='utf-8'));print(sum(1 for e in r if a(e.get('careers_url') or '')),'of',len(r))"

3. **Per-channel Telegram liveness needs a per-key quiet threshold.** *(lane: whoever holds
   `pipeline/sources.py` — shared plumbing, no lane owns it.)* `sources.stale()` applies one
   `max_quiet_days=2` to every key, and that line goes into the mail. Six Telegram channels
   as six keys would put a niche feed's normal quiet weekend in front of the reader every
   few days, so `discovery_telegram._health` records ONE aggregate `telegram` key and prints
   the per-channel counts to the step log instead. A channel that dies alone is therefore
   still invisible. Proposed: `record()` takes an optional per-key threshold.

4. **Decide `fetch_serpapi_google_jobs`'s fate on 2026-09-01, not before.** *(lane:
   `discovery` to propose, `infra` to remove the `run.py` hook.)* It has never run in the
   cloud — `AGGREGATOR_ENABLED` is set in no workflow, test or script — and two
   incompatible reasons are on record (`daily-digest.yml`: "verified to NOT cover Israel";
   `CLAUDE.md`: quota exhausted). The key answers HTTP 429 today, so neither can be tested.
   If the "no Israel coverage" claim holds after the quota resets, deleting it also retires
   `verify_jsearch.py` and one assertion in `tests/test_units.py`.

5. **CLOSED 2026-08-23 — the targeted sweep did not work at all, and fixing it was cheaper
   than tuning it.** *(lane: `discovery`.)* It was filed here as "4 of 43 cached jobs are
   on-target, consider halving the budget". Re-measuring the day's own run made it worse: of
   160 records spent on 20 named companies, **0 came back for any of the 20, and 0 for any of
   the 110 stale companies**. The cause was not the budget — the dataset takes a dedicated
   `company` input and the code was concatenating the name into `keyword`, so LinkedIn ranked
   on "data analyst" alone. Scoped: **25 records, 22 on-target**. Fixed, `cap` raised 20 → 100.
   What is left, and it is a real question nobody has answered: the broken version was
   accidentally a second BREADTH sweep and found 17 employers we had never seen
   (J&J MedTech, Vishay, IAI, Ben-Gurion University). Two extra keywords were added to the
   breadth sweep to compensate; **whether that trade is net-positive has not been measured
   over more than one run.**

6. **URGENT — the pipeline's Bright Data spend does not fit in its free pool, and the
   failure will be silent.** *(lane: `infra`; discovery has throttled its own half.)*
   Production-only figures, tests excluded by taking the digest-window hours on clean
   single-run days: **~94 Web Scraper records + ~49 Web Unlocker requests per day = 4,292
   credits/month, 86% of the 5,000 pool before a single SERP request or test run.** Add
   `reqs_serp`, which went from 0 to 199/272/116 a day when `resolve_broken` gained its
   `google_via_unlocker` fallback on 2026-08-23, and the projection is 93%–203%. The account
   was created 2026-08-15, so the pool has never yet run out; it stood at 4,106/5,000 on
   08-23 with eight days left. **When it empties, every BD step fails silently and every
   workflow stays green** — discovery, `enrich_scrape_jd`, `enrich_matched_jd`, `bd_rescue`,
   `crack_walled`, `retry_unreachable` and the resolution ladder's search rung all return
   nothing on the same day. First move, and it is a one-line class of bug:
   **`DEEP_BD_SEARCH_CAP` is not the cap it looks like.** `deep_validate._BD = {"used": 0}`
   is a module-level counter, so 150 is per PROCESS, and six scripts import
   `google_via_unlocker` in processes of their own — `resolve_broken` (06:00),
   `listing_hunt` (19:00), `crack_walled` (19:00 + weekly), `repair_dead_urls`,
   `deep_validate` (Sat), `audit_empty_rows` (Sun). Effective ceiling **~450 credits on a
   weekday, ~750 at the weekend**; observed peak 272, i.e. two processes' worth. Then a
   shared pre-flight budget check those six also call, since `discovery_daily` throttling
   alone just makes it absorb everyone else's overrun.
   **Context, and it has changed:** discovery moved its breadth sweep from the per-RECORD
   dataset to the per-REQUEST Unlocker on 2026-08-23 (391 credits/day → 10), so the whole
   pipeline now sits at ~127 credits/day = 3,810/month and **fits the free tier**. SERP is
   therefore no longer one cost among several — it is the only thing that can still push the
   month over. See `ARCHITECTURE.md` §1a, "Is it sustainable?".

8. **`linkedin-targeted` is 87% of discovery's credit cost for ~1 new company/day.**
   *(lane: `discovery`.)* It is the last sweep billed per RECORD (67 credits/day) while the
   breadth sweep that finds 35 new companies costs 10. It cannot move to the Unlocker as-is:
   LinkedIn's public search filters by company only through a numeric `f_C` id, which the
   registry does not store. Options, in order of appeal: harvest `f_C` ids once from each
   company's LinkedIn URL and cache them; drop the sweep and rely on the broad sweep
   incidentally covering those employers (it already found 2 of the 15); or keep it and
   accept the cost, since it is the only thing covering 15 active rows whose own board
   reports zero.
   **2026-08-24 update:** the failure shape landed — Bright Data at 97% of pool throttled
   the cap to 4 and the trigger still ran, returning 0 records. `discovery_daily` now skips
   the trigger below `TARGETED_MIN_CAP` (default 10) with an explicit log line; the `f_C`
   harvest above remains the real fix.

7. **Reading it is CLOSED; the six scripts that spend it are item 6.**
   *(lane: `infra`.)* `discovery_daily.bd_spend_this_month()` now reads the whole pool —
   `datasets/v3/snapshots` for Web Scraper records plus `zone/cost` for `reqs_unblocker` and
   `reqs_serp` — and prints it every run. The pool is **5,000 credits/month shared by all
   three products**, verified against Bright Data's docs; on 2026-08-23 it stood at
   **4,106 = 82%**, of which **1,117 credits (27%) were unlocker + SERP requests made by
   `enrich_scrape_jd`, `enrich_matched_jd`, `bd_rescue`, `crack_walled`, `retry_unreachable`
   and `deep_validate.google_via_unlocker`** — none of which meters itself or knows what the
   others have spent. `discovery_daily` now throttles ITS OWN spend to what remains, which
   means it absorbs the whole cost of everyone else's overrun. The right fix is a shared
   pre-flight check those six also call. Note `DEEP_BD_SEARCH_CAP` alone defaults to 150
   searches per run. Still worth widening the token's billing scope at
   `brightdata.com/cp/setting/users` so `/customer/balance` (403 today) gives the account's
   own figure rather than the documented default.

7. **`/customer/balance` is 403 for this API token — a two-minute console fix.**
   *(lane: `infra`; needs Bright Data console access, so it is an operator action, not a
   code change.)* The code now reconstructs the spend from two other endpoints and compares
   it against the 5,000/month the public docs state. That is one assumption away from the
   truth: it does not know this account's actual plan. Ticking the billing scope for the
   token at `brightdata.com/cp/setting/users` makes `/customer/balance` readable, after
   which `BD_MONTHLY_BUDGET` can be replaced by the account's own number and the throttle
   stops guessing.

## From the adversarial review of the discovery layer, 2026-08-23

An independent hostile review of the rewritten intake layer. Twelve defects were found and
fixed in-lane the same day (see `docs/sessions/2026-08-24-discovery.md`). These five are
outside the `discovery` lane and are NOT fixed.

9. **`fetch_discovery`'s slug guard drops real employers, and every drop is uncounted.**
   *(lane: `ats-fetch` / shared — `pipeline/fetchers.py:588-591`.)* Three filters, one list
   comprehension, no logging: 22 of 205 cached jobs are dropped as recruiters every run and
   nothing says so. Worse, `url_names_other_company` drops a job whenever the registry name
   and the LinkedIn slug differ — which is exactly what an acquisition looks like:
   `NVIDIA`/`at-mellanox-technologies`, `Palo Alto Networks`/`at-cyberark`,
   `Meta`/`at-facebook`, `Bank Hapoalim`/`at-poalim` all test as DROPPED. `ARCHITECTURE.md`
   §8 item 4 warns about this exact class ("CyberArk→PANW and Imperva→Thales looked like
   false matches and were actually real acquisitions") and the guard drops them anyway,
   invisibly. It measures 0/205 today only because the old dataset path made name and slug
   agree; the new `linkedin_search` takes the DISPLAY name, so divergence becomes routine.
   Fix: count and print each drop class, and never slug-drop a name already in
   `companies.csv`.
   > **`ats-fetch` 2026-08-24: counted, and exempted narrowly.** `fetch_discovery` prints
   > `[discovery] kept 881 of 1097 cached jobs (dropped: expired 107, recruiter 109)`
   > (that run: slug-mismatch 0), and keeps a card whose slug names a DECLARED identity
   > of the company (`pipeline/identity_facts.py` tenants/domains, matched as an exact
   > whole leading run of the employer's slug words, 3+ chars: "Merck (MSD)"/`at-msd`,
   > "AWS"/`at-amazon-web-services`). The blanket "never drop a registry name" is
   > deliberately not done — the 147 mis-attributed rows carried registry names too — so
   > NVIDIA/`at-mellanox` still needs a declaration in `identity_facts` (lane: `registry`),
   > which is the right place for it. (`check_invariants.py:211` runs the same predicate
   > over the board as a `warn()`, not a gate — an earlier version of this note said it
   > blocked; it does not.)


10. **`discovered_cache.json` and `research_companies.json` are restored wholesale on the
    git conflict path.** *(lane: `infra` — `.github/workflows/daily-digest.yml:155` and the
    same block in 7 other workflows.)* The adjacent comment explains why `scraped_cache.json`
    is EXCLUDED from the wholesale `cp /tmp/ours/$p $p` and merged per key instead. These two
    have two writers each and get no such treatment, and `merge_json_cache.py` only handles
    company-keyed dicts — `discovered_cache.json` is a LIST. A concurrent digest re-dispatch
    (the 08-21 and 08-23 histories show these happen) silently discards origin's discovery
    jobs and queue entries. Fix: a list mode in `merge_json_cache.py` keyed on
    `(company,title)`, or move both files out of the wholesale-restore loop.

11. **`looks_like_junk` cannot catch a bare job title.** *(lane: `company-intel` —
    `pipeline/firmographics.py:53-72`.)* `_JUNK_NAME` requires a role word FOLLOWED BY a
    separator, so `"Senior Data Analyst"` and `"BI Developer"` are not junk, and
    `CATEGORY_NAMES` is exact-match only. Any source whose employer field is a headline feeds
    those straight into the auto-expand queue and they become `companies.csv` rows two runs
    later. The queue is clean today (0 of 1,233), so this is a live hole rather than live
    damage. Fix: a separator-free arm — a name that is ENTIRELY role words plus seniority
    modifiers is junk.

12. **`pipeline/run.py` has no `sys.stdout.reconfigure`** while 23 other root scripts do.
    *(lane: `infra`.)* It dies with `UnicodeEncodeError` printing a Hebrew company name on a
    cp1252 console — hit for real during the review. Local-only; runners are UTF-8.

13. **The `(company,title)` dedup key costs ~1.1% of real postings.** *(lane: shared —
    `pipeline/store.merge_key`, and the same key in `discovered_cache.json`.)* Measured
    against `scraped_cache.json`: 1,110 jobs, 1,079 distinct keys, 12 postings dropped —
    e.g. `amazon israel | senior delivery consultant – ai/ml` in two locations. The
    qualitative cost is larger than the count: a Telegram post carrying a usable seed URL
    loses to a LinkedIn card with the same key, and only one `url` survives. Deliberate (it
    is what stops one role appearing three times from three sources), so this is a recorded
    trade, not a bug — but the number should be known before anyone "fixes" duplicates.

14. **`discovery_daily.py` is a 1,214-line monolith doing six jobs.** *(lane: `discovery`.)*
    Four source integrations, a credit ledger, a budget planner, four normalizers, the cache
    merge and the names bridge, in one file with 22 top-level functions. The seams are
    already visible in the function groupings, so the split is mechanical:
    a source module per site under a new `pipeline/sources/` package, a budget module, and a
    thin runner. (Named without backticks on purpose: docs/check_docs.py verifies that every
    path a doc names EXISTS, so a proposal must not spell a future file as a real one.)
    **Deliberately not done 2026-08-24**, and the reason matters more than the item: this is
    a rename, `docs/AGENT_BRIEF.md` is explicit that a rename here breaks four other lanes
    silently, and the file had just absorbed four adversarial review waves in a day. The risk
    of re-introducing one of the twelve defects those waves found outweighs the tidiness. Do
    it on a quiet day, with the test suite as the harness, and not while another lane holds
    `companies.csv`.

15. ~~**The comment density in `discovery_daily.py` needs a reader who was not in the
    incidents.**~~ — **closed 2026-08-25**: done in `30aece9` (498 → 348 prose lines).
    *(lane: `discovery`, or `docs`.)* It carries **0.77 lines of prose per line
    of code** (370 comment + 120 docstring against 635 code). Each paragraph documents a real
    defect and this repo's house style is to keep the incident next to the code — but
    collectively they now bury what they protect. The author of a comment is the worst judge
    of whether it is still load-bearing; someone else should decide which of these are rules
    and which are just war stories that belong in `docs/sessions/`.

## From the registry lane, 2026-08-24

Found while fixing the re-check pools. Each of these is **outside the `registry` lane's
write list**, which is why it is a proposal and not a commit. Ordered by what it costs today.

1. **One re-check pool definition** — lane: `docs` (or whoever next touches shared
    **CLOSED 2026-08-25:** both halves landed — `verdicts.TOKENS` carries `url-cleared`/`url-flagged` (162), and every `registry_health.pools()` mirror imports the tool's own `in_*_pool` (`_EXTRACT_GAP` deleted, `_PROBE_SHAPE` = `probe_candidates.PROBE_POOL`). Residual: one token list spelled three times with one deliberate gap (`HUNT_POOL` lacks `dark-triage`), pinned by `test_the_three_copies…`.
   plumbing). `pipeline/verdicts.TOKENS` is supposed to be the single source, and there are
   **four** copies: `TOKENS` (18 tokens), `listing_hunt.main()`'s inline regex (17),
   `check_invariants.POOL` (18), and `registry_health._HUNT_SHAPE` (17) — **this lane added
   the fourth**, and an earlier version of this item did not know it existed. `url-cleared`
   and `url-flagged` are in the inline copies and **missing from `TOKENS`**, so of the 39
   rows carrying one, the **9** that carry nothing else are invisible to `audit_empty_rows`
   and `deep_validate`.

   *(An earlier version of this item said "three copies" and "57 rows". Both were wrong, and
   ARCHITECTURE.md section 2 already said so — it names the 57 a conflation of "rows that
   carry the token" with "rows the token hides". A stale number on the hand-off surface is
   worse than no number: the next agent sizes the job off it. Reproduce:*
   `python -c "import csv;from pipeline.verdicts import in_pool;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>=6][1:];n=[x for x in r if 'url-cleared' in x[5].lower() or 'url-flagged' in x[5].lower()];print(len(n),len([x for x in n if not in_pool(x[5])]))"`
   *-> `39 9`, measured 2026-08-24.)*

   **Three more mirrors this lane added and did not disclose**, found by wave 8:
   `registry_health._PROBE_SHAPE` (mirrors `probe_candidates`' filter),
   `registry_health._EXTRACT_GAP` (mirrors `repair_extract_gap.MODE`), and the crack-pool
   literal. Measured 2026-08-24 the drift is **0** on all three (`_EXTRACT_GAP` 40 vs `MODE`
   40; `_PROBE_SHAPE` + `is_terminal_note` 153 vs the tool's 153) — so they are accurate,
   unguarded, and free to drift. `_EXTRACT_GAP` is strictly *looser* than `MODE` (it does not
   require a date), which is the over-counting direction that hides orphans.
   `test_the_ownership_matrix_is_built_from_the_tools_own_predicates` pins only the triage
   count and two negative properties of the hunt; extending it to compare all four mirrors
   against their tools is a `registry`-lane job and is the cheap half of this item.

   The fix is two lines in `pipeline/verdicts.py`:

   ```python
   "url-cleared":  "listing_hunt / manual",   # the stored address was an aggregator
   "url-flagged":  "listing_hunt / manual",   # ...or another company's page
   ```

   Then `listing_hunt.main()`'s regex and `check_invariants.POOL` both become
   `verdicts.in_pool`, and `test_the_three_copies_of_the_re_check_pool_still_agree_where_
   they_are_supposed_to` tells you to delete its `EXPECTED_GAP` — it is written to fail
   loudly at that moment rather than to be forgotten. Reproduce the gap with the snippet in
   `ARCHITECTURE.md` §2.

2. **One terminal-state list** — lane: shared plumbing. `verdicts.TERMINAL` is
    **CLOSED (47, 2026-08-24):** `verdicts.TERMINAL` carries `alias-of`; `check_invariants`, `registry_health` and the four tools derive from `TERM_RX`. Live residual is 72 (`recruiter` substring), planned in the durable-pools batch.
   `defunct / domain-dead / duplicate of / redundant / recruiter` and **omits `alias-of`**,
   which is why `audit_empty_rows` and `crack_walled` had alias rows in *activating* pools
   (fixed 2026-08-24 by spelling the exclusion out in each tool, which is now the FOURTH
   copy — `listing_hunt` and `deep_validate` already had their own). Adding `"alias-of"` to
   that tuple lets all four be deleted. `registry_health.TERMINAL` is the fifth and would
   go too.

3. **Registry alarms in the daily mail** — lanes: `infra` (`pipeline/run.py`) + `render`
    **CLOSED (12/13, 2026-08-24):** `pipeline/run.py` calls `registry_health.alarms_state()` and all three renderers print `- **Registry:** …`.
   (`pipeline/digest.py`). `registry_health.alarms()` returns the short lines that answer
   "did a company disappear, and can the ladder still crack anything" — and today they reach
   nobody, because no registry tool has a path into the digest. The channel already exists:
   `dead_sources` is a `list[str]` that `run.py` puts in `summary` and all three renderers
   print. Four lines:

   ```python
   # pipeline/run.py, next to the _dead_sources block
   try:
       from registry_health import alarms as _registry_alarms
       _registry = _registry_alarms()
   except Exception:                      # never let the audit block the product
       _registry = []
   for _line in _registry:
       print(f"::warning::registry {_line}", flush=True)
   # ...and in `summary`:  "registry_alarms": _registry,
   ```

   plus one line in each of `digest.build_markdown`, `_text_audit` and `_html_audit`,
   copying the `dead_sources` line verbatim with the label **"Registry"**. Without this,
   tasks that say "tell me in the mail" have no mail to be told in.

   The census also needs a refresher step, which is a workflow change (`infra`): one
   `python registry_health.py --census` after the digest's commit, with
   `cloud_state/registry_census.json` added to that step's `git add`. Note the *absence* of
   the refresher is fail-safe, not fail-silent: a stale census keeps reporting the same
   deletion every day until a human re-baselines it.

4. **`merge_csv_rows` can resurrect a deliberately deleted row** — lane: `infra`. Its
   `changed` set is "rows where ours differs from base", and the else-branch is
   `target.append(r)` with no check that the row was deleted from master on purpose. That is
   exactly what happened to `Time To Know` (`8644d8fd`, 1190 → 1191 rows; see
   `ARCHITECTURE.md` §2, "Never DELETE a row"). A tombstone would fix it properly; the cheap
   version is to refuse to re-append a row whose base note carries a terminal token, and to
   print the names it appended so the resurrection is at least visible in the step log.

5. **`check_invariants.py` has no size check** — lane: `infra`. Checks A–H all validate the
   registry's SHAPE. A truncated write, a bad merge or an accidental deletion changes its
   SIZE, and nothing looks. One warning is enough (a violation would withhold the digest,
   which is the trade that failed on 2026-08-23):

   ```python
   # I. size — a registry that shrank was not edited, it was lost
   prev = registry_health.load_census()
   n_prev = len([k for k in prev if k != "__notes__"])
   if n_prev and len(body) < n_prev * 0.98:
       warn(f"registry shrank {n_prev} -> {len(body)} rows — truncated write or bad merge?")
   ```

6. **`audit_empty_rows` and `deep_validate` select the identical 255 rows** — lane:
    **CLOSED 2026-08-26 (`registry`, `8a4deac`):** `deep_validate.validate_one` + the extracted `apply_verdict` are the Sunday audit's second rung over what the cheap rung left dark (`audit_empty_rows._deep_rung`, `AUDIT_DEEP_BUDGET_MIN` 120, deep's own 30-day cooldown, oldest-stamped first); `deep-validate.yml` retired; `deep_validate.py --only` for an on-demand pass. Both selected the identical 270 rows the day before.
   `registry`, unclaimed. Same predicate, different depth (raw HTML vs Chromium render +
   network sniff), 24 hours apart, on consecutive weekend mornings. Sunday's audit re-walks
   everything Saturday's deep validation just failed on. The lean shape is one Saturday pass
   that escalates per row, with `deep_validate`'s renderer as the second rung of
   `audit_empty_rows` rather than a separate job — it would also halve the `repo-state`
   concurrency pressure on the weekend. Not attempted here: it is a real refactor of two
   scheduled entrypoints plus their two workflows, not a documentation pass.

7. **`oraclecloud.com` is parked as an "unsupported ATS" on 4 rows while `oraclehcm` is a
   supported fetcher with 4 active rows** — lane: `ats-fetch`. `Fortinet` is the worked
   example: it is an *active scrape* row pointed at
   `edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/...` (11 IL verified by the hunt),
   being browser-rendered every night for something the native REST fetcher could read.
   `deep_validate._UNSUP` lists `oraclecloud.com` as unsupported, which is what wrote those
   verdicts. Full inventory: `python registry_health.py --ats`.

8. **`gen_modules.py` does not round-trip its own file** — lane: `docs`. `docs/MODULES.md`
   carries two hand-added lines telling the reader to regenerate it with
   `python docs/gen_modules.py`; the generator does not emit them, so **every regeneration
   silently deletes the instruction for how to regenerate**. Found 2026-08-24 by the
   `registry` lane adding one `CLASS` entry and diffing the result. Either move the sentence
   into the generator's header template or have `check_docs.py` assert the file matches a
   fresh generation — right now nothing notices prose disappearing from a generated doc.

## From the registry lane's adversarial review, 2026-08-24 (wave 2)

Two independent read-only agents attacked the wave-1 commit (`5505d3d`). Nine of their
findings were real and are fixed; these are the ones outside this lane, plus the one
structural problem that keeps producing them.

9. **`company_identity.verdict()` is the single unguarded door** — lane: shared plumbing.
   It returns the blanket `"ats"` — which its own docstring defines as *"we cannot tell"* —
   for every URL on a known ATS host whose tenant lives in the **subdomain**, and
   `is_foreign()` reads "cannot tell" as "not foreign". Every activating path treats that as
   a pass: `listing_hunt`'s documented fast-path and its found branch, `deep_validate`,
   `crack_walled`, `repair_dead_urls`. Wave 1 patched two of those call sites with two
   *different* ad-hoc gates, which is precisely why the Bancor leak escaped the patched tool
   into the unpatched one (fixed, but as a fourth private gate). `verdict()` should extract
   the tenant from the subdomain (`careers-bancorpbank.icims.com` -> `bancorpbank`) and
   check it the way it already checks a path tenant. Until it does, every downstream fix is
   a fix to one hallway. Reproduce:
   `python -c "from pipeline.company_identity import verdict, is_foreign; u='https://careers-bancorpbank.icims.com/jobs/search'; print(verdict('Bancor',u), is_foreign('Bancor',u))"`
   -> `ats False`.

10. **`audit-coverage.yml` runs the new search ladder with 1 of its 3 rungs** — lane: `infra`.
    The `audit_empty_rows` step gets only `SERPAPI_KEY`/`SERP_RESERVE`; SerpApi is exhausted
    until 2026-09-01 and `google_via_unlocker` returns `[]` without `BRIGHTDATA_API_KEY`, so
    the Sunday audit searches with DuckDuckGo alone — the one thing ARCHITECTURE §3 says it
    may never do. The tool's own warning prints `brightdata=MISSING`. Add
    `BRIGHTDATA_API_KEY`/`BRIGHTDATA_ZONE` to that step (and to the Sunday `crack_walled`
    step, which also lacks `SCRAPE_VIA_UNLOCKER`, so its identity gate has no residential
    fallback). Give the audit its own small cap when you do: `deep_validate._BD` is
    per-process module state, so the two jobs do NOT share a counter despite the docstring.

11. **`listing-hunt.yml`'s budgets sum to 325 of its 330-minute timeout** — lane: `infra`.
    30 + 35 + 200 + 60, leaving 5 minutes for checkout, `npm install`,
    `playwright install --with-deps chromium` and a commit step whose retry loop sleeps up to
    225s. Each tool stops cleanly at its budget so the verdicts are on disk; what a timeout
    kills is the **commit** — the 3.5-hour loss of 2026-08-22 all over again, and
    `Commit verdicts` has no `if: always()`. `HUNT_TIME_BUDGET_MIN: "200"` -> `"150"` (sum
    275) and fix the stale comment, which still says "leaves ~90 min" from before the two
    repair steps existed.

12. **Nothing runs `registry_health.py`** — lane: `infra`. `grep -rn registry_health
    .github/` is empty, so the census never refreshes and the alarms reach nobody. One step
    in `daily-digest.yml` after `check_invariants` and before the commit:
    `python registry_health.py --census` (the existing `git add cloud_state` already covers
    both files it writes). The absence is fail-safe, not fail-silent — a stale census keeps
    reporting the same deletion until a human re-baselines — but `census_diff` judges a
    removal against the note **as of the last census**, so the explained/unexplained split
    degrades toward "everything is unexplained" the longer the refresher is missing.

    **CLOSED 2026-08-24:** `daily-digest.yml` runs `registry_health.py --census` AFTER the
    invariant guard and before the commit (continue-on-error, so it can never withhold the
    digest); a census taken before the gate would bless a corrupted registry as the new
    baseline. `pipeline/run.py` calls `alarms_state()` directly (0.19s import, no network)
    and the digest renders the lines as `- **Registry:** …` in all three renderers.

13. **The mail hook is now `alarms_state`, not `alarms`** — supersedes item 3 above. Item 3's
    patch called `alarms()`, which probes the resolution ladder; `daily-digest.yml` installs
    no Playwright and sets `BRIGHTDATA_*` only on unrelated steps, so it would have printed
    two PERMANENTLY FALSE `rung DOWN` lines in the email every single day. Use:

    ```python
    from registry_health import alarms_state as _registry_alarms   # no env, no network
    ```

    Ladder status still reaches the mail, the honest way: each registry workflow's
    `--census` writes `cloud_state/registry_alarms.json`, and `alarms_state` reports it when
    it goes stale — which is also how a workflow that stopped running becomes visible.

    **CLOSED 2026-08-24 — and it nearly returned through a file:** `--census` used to write
    the FULL `alarms()` (ladder included) into the file `alarms_state` re-emits from. Now
    `--census` records `alarms_state` only, and the ladder has its own file
    (`cloud_state/registry_ladder.json`, written by `listing-hunt.yml --ladder`, the one job
    with Playwright, and never by anything that reads it). Every mailed line is stable while
    the state is stable — no `Nd old`, no `as of <today>` — because the inbox relay dedups
    the digest on a content hash. Pinned by `test_the_mail_hook_does_not_record_the_ladder`
    and `test_the_mailed_alarm_lines_do_not_change_on_a_day_nothing_changed`.

14. **`tests/test_units.py` has no per-lane split, and a stale copy silently reverts another
    lane's guards** — lane: `docs`. Commit `9e4ce72` committed a checkout-era copy of the
    file and deleted seven registry-lane tests that had been committed and pushed in
    `5505d3d`; they were restored by hand. Nine sessions append to one file in one working
    tree, and nothing detects a test *disappearing* — `pytest` is just as green with fewer
    tests. Either split it (`tests/test_<lane>.py`, which `pytest` collects automatically) or
    have `docs/check_docs.py` assert the collected test count never falls. Same class as the
    `Time To Know` resurrection in ARCHITECTURE §2: two writers, one file, last writer wins.

## From three independent verdict agents, 2026-08-24 (wave 3)

All three returned NO-GO on the wave-2 state and all three named the same defect first (the
`registry_health` NameError, now fixed). What remains is outside this lane.

15. **The conflict-recovery merge silently defeats 47 of 153 probe wakes** — lane: `infra`.
    `probe_candidates._wake_note` strips the `listing-hunt` / `dark-triage` segments to wake a
    row. `merge_csv_rows._merge_notes` unions the segments and re-adds them *from theirs*,
    precisely because ours no longer owns those keys — so the resurrected
    `listing-hunt <date>` re-arms the 14-day cooldown and the row leaves the hunt pool. The
    same recovery block restores `cloud_state/candidate_probe.json` wholesale, so the
    baseline has already advanced: **the wake is spent, not deferred**. Measured on the live
    file: 152 of 153 woken rows reach the 19:00 hunt on the normal push path, 47 do not on
    the conflict path (Pliops, Lili, MediWound, AiVF, Siemens Healthineers, …). The
    mechanism predates this lane; wave 2 is what makes wakes reach the tail and survive the
    18:00 triage, so it moves from dormant to routinely exercised. Fix: teach `_merge_notes`
    that a `probe-woken` segment in *ours* means "this run deliberately deleted the other
    tool's segments — do not restore them."

16. **`listing-hunt.yml` overrun got worse, not better** — lane: `infra`, extends item 11.
    Budgets already summed to 325 of a 330-minute timeout. Wave 2 added a residential-unlocker
    call *inside* the per-row loop of two of those steps, and both budget checks are per row:
    `repair_dead_urls` can now overrun its 30 by ~9 min (6 candidates × 20s fetch + 90s
    unlock) and `crack_walled` its 60 by ~6 min (3 captures × 25s + 90s). Worst case ≈ 340
    against a 330 timeout, and `Commit verdicts` has no `if: always()`. Lower
    `HUNT_TIME_BUDGET_MIN` to 150 **and** add `if: always()` to the commit step.

17. **`audit-coverage.yml` writes `cloud_state/scan_seen.json` and never commits it** — lane:
    `infra`. Its `git add` names only `companies.csv scraped_cache.json`, so the tree is dirty
    every Sunday. If the 05:00 digest lands a `scan_seen.json` while the Sunday run is still
    inside its 330-minute window, `git pull --rebase --autostash` leaves conflict markers in
    the file, **exits 0**, and the push succeeds — Sunday's rotation work is thrown away with
    the runner. No corruption reaches master; add the file to that step's `git add`.
    Its `crack_walled` step also sets neither `CRACK_TIME_BUDGET_MIN` nor `CRACK_LIMIT`, so
    `_budget = 0` and it is unbounded.

18. **Both rotations are no-ops on the FIRST cloud run** — accepted, recorded so nobody reads
    it as a failure. `cloud_state/scan_seen.json` ships as `{}` and 0 of 117
    `candidate_probe.json` entries carry a `last` key, so every sort key is `""` and Python's
    stable sort reproduces file order exactly. Night 1 is byte-identical to the old
    behaviour; the rotation starts on night 2. Measured over three truncated nights
    afterwards: 120 of 153 distinct companies covered, against 40 before.

19. ~~**`crack_one` still writes `fr[3]` when the identity page is UNREADABLE**~~ —
    **CLOSED by commit 674cb9c, one commit after this item was written.** `_ok_to_write`
    requires `_page_names_company(...) is True`, so `None` is refused, and it gates the WRITE
    rather than any single `return` — both `fr[3]` assignments in `crack_walled.main()` sit
    under it. Left here struck through rather than deleted, because the item and the
    ARCHITECTURE paragraph that matched it both survived the fix and a reviewer lost time on
    a solved problem: **when you close something, grep for the places that describe it.**

20. **`audit_empty_rows`'s docstring advertises `AUDIT_BD_SEARCH_CAP`; the code reads
    **CLOSED 2026-08-25 (verified):** the docstring now says there is no `AUDIT_BD_SEARCH_CAP` and why `DEEP_` is the name. The per-process counter note (no shared cap with Saturday) still holds and matters for item 6.
    `DEEP_BD_SEARCH_CAP`** — lane: `registry`, one line. And per item 10, `deep_validate._BD`
    is per-process module state, so the Sunday audit does NOT share a counter with Saturday's
    deep-validate however it is named.

## The root cause, and why the obvious fix is wrong — registry lane, 2026-08-24 (wave 4)

21. **`company_identity.is_foreign` returns False for EVERY ATS host, and that is
    deliberate** — lane: shared plumbing, but **do not "fix" it the obvious way**.

    Three independent reviewers converged on the same recommendation: make `is_foreign` see
    the subdomain tenant, so that clauses 2 and 3 of the activation rule stop being inert on
    432 of the 1,199 rows. The evidence for the problem is real —
    `NanoLock Security -> gen.wd1.myworkdayjobs.com` is Gen Digital's tenant, and `verdict()`
    itself returns `mismatch` while `is_foreign` overrides it to False.

    **It was built, wired in, and reverted, because it rejects 36 ACTIVE rows and they are
    legitimate:**

        Momentis Surgical -> greenhouse/memic          (ARCHITECTURE section 2 cites this one)
        Itamar Medical    -> zoll.wd5.myworkdayjobs
        Habana Labs (Intel) -> intel.wd1.myworkdayjobs
        VMware (Broadcom) -> broadcom.wd1.myworkdayjobs
        Splunk (Cisco)    -> cisco.wd5.myworkdayjobs
        HP Indigo, Samsung/sec, Yahoo/ouryahoo, Rakuten Viber, Flex/flextronics, ... (36)

    A tenant naming the acquirer is **inheritance, not theft**, and `page_mentions_company`
    cannot separate the two either: the acquirer's board does not say the subsidiary's name.
    That is the whole reason the permissiveness exists, and it is why every downstream gate
    in this lane is a heuristic rather than a rule.

    **So the fix needs a second signal, not a tighter string match.** The two candidates,
    both real work:
    (a) an explicit `acquired-by` / `posts-under` column or note token, so an inherited
        tenant is *declared* rather than inferred — the registry already carries `alias-of`
        for the analogous duplicate case, and firmographics research already discovers these
        acquisitions and throws the knowledge away (BACKLOG item 10);
    (b) require the ROLE to be Israel-located AND the tenant to be either near-equal or
        declared — which is close to what the digest already does, one layer later.

    Until one of those exists: `audit_empty_rows.tenant_is_this_company` implements the
    near-equality/subdomain-tenant rule. **It is no longer in `crack_walled._ok_to_write`**
    (wave 7 measured that veto refusing 7 of the 9 active rows on crack_walled's own target
    platforms) and it is now used in `audit_empty_rows.main` and, as a veto only, in
    `repair_dead_urls.main`. An earlier version of this paragraph said it "is used in exactly
    one place ... so it can add no new false negative"; the identical sentence was corrected
    in `tests/test_registry.py` two commits before this one and left standing here, in the
    item the brief tells the next agent to read *first*.

    **And the substitute predicate fails the same test.** Wave 8 measured
    `_page_names_company` live against the three companies this item names as the reason the
    permissiveness exists:

        Momentis Surgical   html 23198 chars  names subsidiary=False  names Memic=True  -> refused
        Habana Labs (Intel) html  6750 chars  names subsidiary=False  names Intel=True  -> refused
        Itamar Medical      html  7286 chars  names subsidiary=False  names ZOLL =True  -> refused

    All three pages read in FULL (so `False`, not `None`), and all three are stamped
    `not this company's board`. This item's own text predicted it — "`page_mentions_company`
    cannot separate the two either: the acquirer's board does not say the subsidiary's name"
    — so this is confirmation, not a new finding, and **it is not an argument for restoring
    the tenant veto**, which was measured costing 36 rows. It is the argument for the
    `acquired-by` column: no string predicate can separate inheritance from theft, and every
    gate built so far refuses acquisitions in the safe direction. The cost is bounded — those
    rows are already active and this gate runs on parked rows — but it is real and it is now
    measured. `test_a_tenant_mismatch_alone_must_not_block_an_ats_row` pins the 36-row
    measurement so the next reviewer finds it before rebuilding this.

    **The declaration landed 2026-08-24:** `pipeline/identity_facts.py` is the `acquired-by`
    table 21(a) asked for. A declared row's tenant is authoritative both ways; Habana,
    VMware, Splunk, Itamar, Citrix, Momentis and SentinelOne are declared with evidence.
    The blocked-active set went 24 -> 22 (re-measure: Census B in the plan); the rest of
    the 24 are candidates, each to be declared with evidence or parked -- never a reason
    to loosen the string rule.

22. **17 rows carrying a `listing_hunt` fast-path token have a walled-ATS `api_url` today**
    — lane: `registry`, unclaimed, and it needs item 21 decided first. The fast path gates on
    `is_foreign` alone, so for those rows it does not gate. Six of the 17 look wrong on
    inspection (`NanoLock Security`, `Sight Diagnostics`, `Fetcher`, `Quris AI`, and two
    Comeet rows); the rest look like ordinary tenants. They should be hand-checked and either
    corrected or given the declared-inheritance token from 21(a) — a code gate cannot tell
    them apart, which is the finding.

23. **`python registry_health.py` is named in no document a new agent actually reads** —
    lane: `docs`. It is the single command that answers all three questions the registry lane
    gets asked ("what re-checks this row", "why did a company disappear", "which ATS is worth
    building"), and `grep -c registry_health CLAUDE.md docs/AGENT_BRIEF.md README.md` returns
    `0 0 0`. A reviewer timing the orientation goal reached it at step 7, ~680 lines into
    `ARCHITECTURE.md`, via a third document — and could answer none of the three at the
    2-minute mark. One line in `CLAUDE.md`'s "Run anything locally without side effects"
    block and one in `docs/AGENT_BRIEF.md`'s registry row would close the goal:

        python registry_health.py     # registry: census, who re-checks what, which rungs work

24. **`docs/AGENT_BRIEF.md` still says DuckDuckGo is blocked from this machine** — lane:
    `docs`. Corrected in `ARCHITECTURE.md` §3 and §8 on 2026-08-23 (it is rate-limited, not
    blocked — measured 4 URLs, then 0 for the same query minutes later). `AGENT_BRIEF` is the
    document a spawned agent reads FIRST, and it is the one place the old claim survives.

25. **`HANDOFF.md` contradicts itself 13 lines apart** — lane: `docs`. L46 says
    `1,189 rows · 343 parked`; L59 says `1,199 rows · 353 parked`. Both presented as current
    state; L59 is right. Same table also still says "122 unit assertions" and
    `AGENT_BRIEF` rule 4 says "123 cases"; `pytest --collect-only -q | tail -1` is the
    only number worth quoting here (206 when this item was written, 222 six hours later, 224
    six hours after that — three values in a day, which is the point: a hard-coded count in
    a doc is a defect with a timer on it, and this item has now been wrong twice about the
    very thing it is complaining about),
    and `tests/test_registry.py` is named in no `.md` at all while both documents still tell
    the reader every guard lives in `tests/test_units.py`.

25b. **Ten terminal-state definitions, six disagreeing memberships** — lane: shared
    plumbing. This is item 1's problem in a second concept, and it is worse than either
    document said: section 2 spoke of "the two inline copies", an earlier draft of this list
    said five. Measured 2026-08-24 (`grep -rn "defunct" --include=*.py . | grep -v tests/`):

    | membership | files |
    |---|---|
    | `defunct, domain-dead, alias-of` | `audit_empty_rows`, `check_invariants`, `crack_walled`, `deep_validate`, `listing_hunt` |
    | `defunct, domain-dead, duplicate of, redundant, recruiter` | `pipeline/verdicts.TERMINAL` |
    | `defunct, domain-dead, alias-of, duplicate of, redundant, recruiter` | `registry_health._REASON` |
    | `defunct, domain-dead, alias-of, duplicate, redundant, recruiter` | `triage_dark.SKIP_NOTES` |
    | `defunct, domain-dead` | `probe_candidates` |
    | `defunct` | `scan_dead_domains` |

    Note `triage_dark` matches the bare substring `duplicate` where `verdicts` requires
    `duplicate of` — the kind of difference that is invisible until a note reads
    `duplicate listing`. **Adding `alias-of` to `verdicts.TERMINAL` does not let the others
    be deleted**, which an earlier version of this list claimed: `probe_candidates` and
    `scan_dead_domains` are strict subsets that would start excluding rows they currently
    scan, and `triage_dark`'s is a superset. The real fix is one predicate with one
    membership, and it is a behaviour change for at least three tools, not a tidy-up. Before
    this lane there were 8 definitions; it added **4** — `registry_health._REASON`, the
    census helper, **and `audit_empty_rows.TERMINAL` and `crack_walled.TERMINAL`**, both of
    which are new this lane (`git show e525dab:audit_empty_rows.py | grep TERMINAL` returns
    nothing). An earlier version of this item said 2, in the item complaining about
    duplication.

26. **Three orphan detectors, three answers** — lane: `registry` + `infra`, unclaimed.
    `registry_health.orphans()` says 1 (`SeeTree`), `ARCHITECTURE.md` §5c's hand-typed
    one-liner says 4 with zero name overlap, and `check_invariants.py` says 0 because it
    whitelists **seven** names in `ALLOWED_ORPHANS` — not five, as this item and §5c both
    said until 2026-08-24. Reproduce:
    `python -c "import check_invariants as ci; print(len(ci.ALLOWED_ORPHANS), sorted(ci.ALLOWED_ORPHANS))"`
    -> `7 ['Alpha | Similarweb Partner', 'Google', 'Marvell Israel', 'NICE', 'Orca-AI', 'SeeTree', 'Via Transportation']`.
    §5c now points at the tool and admits the disagreement, but the right end state is one
    definition. Note `check_invariants.py:219` prints the literal string `0 orphans`
    unconditionally — it can never report otherwise.

    **Before wiring alarms into the mail (items 3/13), note what ships with them.**
    `registry_health`'s only standing alarm today is `SeeTree`, whose row reads
    `no careers page (redirects home); discovery-net only` and which `check_invariants`
    deliberately whitelists. That is a permanent, un-actionable daily line unless the
    expected count is recorded and subtracted. **Expected orphan count on 2026-08-24: 1
    (`SeeTree`).** An alarm nobody can act on is how a digest teaches its reader to skim.

27. **`crack_walled` retires 13 of its own 25 pool rows per all-refusing night** — lane:
    `registry`, unclaimed, and it is the residual the note-shortening could not remove. The
    refusal segment is 49 chars against a pool whose mean note is 203/220, so `notes.append`
    still evicts another tool's `unsupported ATS` token from 13 rows — better than the 16 the
    `novrfy` note it replaced cost and the 25 the 107-char form cost, but not zero. The floor
    is 4/25 at an EMPTY payload, so no further string diet fixes it: **the cell is
    structurally full.** `deep_validate` re-stamps `unsupported ATS` on its Saturday pass, so
    coverage is delayed up to a week rather than lost, and no row is ever orphaned. The real
    fix is a wider cell or a second column, which is `pipeline/notes.py` and `companies.csv`
    schema — i.e. shared plumbing plus every reader.

28. **`no-url` is a triage mode `triage_dark` writes and `listing_hunt` routes on, and it is
    missing from `check_invariants.TRIAGE_MODES`** — lane: `infra`. Result: 13 permanent
    `::warning::` lines every run, in the blocking gate in front of the email, for rows that
    are behaving correctly. A warning that is always there is a warning nobody reads.

29. **`tenant_is_this_company('SupPlant', 'careers.workable.com')` returns True** — noted so
    the record is straight: commit `0a3cf30`'s message claimed it separates that case. It does
    not. Every label of that host is plumbing (`careers`, `workable`, `com`), so there is no
    tenant to check and the predicate correctly answers "cannot tell". `SupPlant` is caught by
    `_page_names_company` instead, which is the gate that matters, but the commit message
    overstated the predicate.

## From the registry lane's wave-7 review, 2026-08-24

Three independent agents drove the tools instead of reading them. Five of the write-path
defects they found had been *introduced* by wave 6's hardening, two of them in the branch
whose commit message announced the hole was closed — which is why item 30 is the one that
stops this recurring.

30. **`_ok_to_write` and `_page_names_company` are plumbing living in `crack_walled.py`** —
    lane: shared plumbing. **Four** tools now import them — `deep_validate` and
    `listing_hunt` take `_ok_to_write`, `audit_empty_rows` and `repair_dead_urls` take
    `_page_names_company` — and three of the four import **lazily, inside the function**,
    because `crack_walled` imports from `deep_validate` and `audit_empty_rows`: a cycle in
    both directions. Those lazy imports are a smell with a real cost: they are invisible to
    any static check of "does this tool gate its writes".

    *(An earlier version of this item listed `audit_empty_rows`, `deep_validate`,
    `repair_dead_urls` and omitted `listing_hunt` — at the time, two of the three named
    imported nothing from `crack_walled` and instead carried their own two-valued copy of
    the predicate. Wave 8 found that; the copies are gone and the list is now accurate.
    Reproduce: `grep -n "from crack_walled import" *.py`.) These two functions are the single identity gate for every column-3/4 write in
    the repo and belong in `pipeline/` next to `company_identity`. Doing so also makes the
    guard in `tests/test_registry.py` enumerable ("every tool that writes `fr[3]` imports the
    gate") instead of four hand-written fixtures. **Do not do this at the same time as item
    9** — fix `verdict()` first, then move what is left.

31. **`docs/AGENT_BRIEF.md` sends a registry agent to the wrong files** — lane: `docs`.
    L111 says "every one of the **67** root modules"; `ls *.py | wc -l` is **68** (this lane
    added `registry_health.py` and updated `docs/gen_modules.py` + `BACKLOG.md`, but the
    brief's count is hand-typed and `check_docs.py` verifies classification, not the number).
    The registry lane's row lists 12 primary files and **omits `registry_health.py`** — the
    one read-only tool that answers section 2's five orientation questions. Together with
    item 23 (it is named in none of `CLAUDE.md`, `AGENT_BRIEF`, `README.md`) this is why a
    reviewer timed at the 2-minute orientation could not answer any of the three questions:
    the tool that answers all three is unreachable from every entry point.

32. **`HANDOFF.md`'s ATS watch-list gives the wrong answer to "what should we build"** —
    lane: `docs`. L153 lists `jazzhr`, `eightfold`, `iCIMS`, `SuccessFactors` as "unchanged
    from the last handoff", implying no fetcher. `fetch_jazzhr` (`pipeline/fetchers.py:594`)
    and `fetch_eightfold` (`:655`) both exist and are wired into `FETCHERS`. Cost if
    believed: an `ats-fetch` session rebuilding two live fetchers. `python registry_health.py --ats`
    is derived and correct — on 2026-08-24 it reports **3 WIRE / 5 BUILD over 55 rows**.
    *(This item said "8 of 8 WIRE, 0 BUILD ... a moving target, it was 3/5 six hours
    earlier". Both halves were false: `git diff --stat 8812ed3 HEAD -- companies.csv` is
    empty, so the input never moved, and the tool has never produced 8/0. Commit `09427f4`
    corrected that sentence in ARCHITECTURE.md and HANDOFF.md and edited THIS FILE in the
    same commit without fixing it here.)* The durable fix is to
    delete the hand-maintained list and point at the command.

## From the registry lane's wave-8 review, 2026-08-24

Three independent agents, all NO-GO. Two of the defects were mine, introduced by wave 7's
fixes; one was a claim I made that a doc of this repo already contradicted on the line above.

33. **`tenant_is_this_company`'s "cannot tell" satisfies the audit's gate on 382 of 460
    active ATS rows** — lane: `registry`, **and the obvious fix is measured wrong**. The
    predicate returns True both for "the tenant is near-equal" and for "there is nothing here
    to check". Measured 2026-08-24: **430 of the 461** active ATS-host rows get a True, and
    only ~72 of those had a tenant actually compared. Reproduce:
    `python -c "import csv;from audit_empty_rows import tenant_is_this_company as T;from listing_hunt import ATS_HOST;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>=6][1:];a=[x for x in r if x[4]=='true' and ATS_HOST.search(x[3] or '')];print(len(a),len([x for x in a if T(x[0],x[3])]))"`
    -> `461 430`.

    *(An earlier version of this item said "382 of 460", broke it down as "358 path-tenant
    plus 24", and listed per-platform counts summing to 371 — three numbers that cannot all
    be right, and the 382 had been copied into `audit_empty_rows.py`'s source comment. Wave 9
    caught it. The shape of the finding is unchanged; only the size was wrong.) What decides those rows is
    `_slug_matches`, plain containment, which passes `Bancor`/`bancorpbank`,
    `Bit`/`bitdefender`, `Lili`/`elililly`.

    The fix that suggests itself — require a positive near-equality match, else fall through
    to the page read on the next line — was **built and reverted on 2026-08-24**, because on
    exactly the platforms it would newly gate there is no page to read:

    ```
    fetch("https://boards-api.greenhouse.io/v1/boards/fiverr/jobs")         -> 0 bytes
    fetch("https://www.comeet.co/careers-api/2.0/company/60.002/positions") -> 0 bytes
    fetch("https://api.ashbyhq.com/posting-api/job-board/deel")             -> 28 bytes
    ```

    `_page_names_company` needs 2000 chars to answer anything but `None`, so "fall through"
    refuses all 358 and stamps a false verdict on each — the same over-block wave 8 caught in
    `deep_validate`, one tool over. It was caught only because the fixture carries a positive
    control. Two fixes that would work: tighten `_slug_matches` to near-equality for PATH
    tenants (the rule already used for subdomain tenants), or read the platform's *human*
    board URL rather than the API endpoint. Both are real work; neither is a one-liner.

34. **No pool has a per-tool floor, so a pool can fall to zero with every guard green** —
    lane: `infra` + `registry`. `check_invariants` check E has one aggregate floor
    (`pool_n < 50`, actual 266) and `registry_health`'s only alarm is `OWNED BY NOTHING`.
    Wave 8 simulated 14 nights and watched `crack_walled` go 25 -> 2 -> 0 and
    `probe_candidates` 153 -> 19 -> 16 while `check_invariants` printed
    `OK pool=266, exit 0` every night. That is precisely the "coverage that silently never
    happens" ARCHITECTURE.md section 8 calls the most common way this codebase breaks, and
    the health tool this lane built cannot report it. A per-tool floor in
    `registry_health.alarms()` is the cheap half and is `registry`-lane work.

    **CLOSED 2026-08-24 (the alarm half):** `registry_health.pool_floor` compares each
    tool's pool to the size the last census recorded (`//pools//` in
    `cloud_state/registry_census.json`): collapse to zero, or halving from >= 8, alarms
    by name in the daily mail. Literal thresholds; the first census after deploy never
    alarms. Deliberately NOT in `check_invariants` — that is the hard gate, and a pool
    collapse must be mailed, not used to withhold the digest.

    **Known shape (confirmation-wave R3):** the floor compares against LAST NIGHT's census,
    and `--census` re-baselines every night -- a collapse alarms for exactly one digest,
    then the new size is the baseline. The alarm fires once and visibly; a rolling or
    high-water baseline would repeat it. Deliberate for now; revisit if one is missed.

35. **`merge_csv_rows._TOOL` does not key `url-repaired`, and its overflow trim deletes the
    other writer's segments** — lane: shared plumbing. The marker is keyed by `seg[:28]`,
    which includes the date, so two runs on different days both survive and double the
    220-char budget. The module special-cases the literal `"url-repaired"` twenty lines
    below, so it knows the marker; the regex does not list it. Worse, on overflow
    `while out and len(" | ".join(out)) > cap: out.pop()` pops from the tail of
    `split(ours) + split(theirs)` — i.e. it deletes 100% of the concurrently-committed
    writer's segments. That is the "351 lost triage modes" bug class re-entering through the
    trim, on exactly the rows where notes are longest.

36. **`_page_names_company`'s unlocker call is uncapped Bright Data spend** — lane:
    `registry`. `DEEP_BD_SEARCH_CAP` guards `google_via_unlocker` only; `_page_names_company`
    calls `bd_rescue.unlock` gated on the key alone with no counter — correct for accuracy,
    wrong for the budget. Now that four tools route through it, the 19:00 job can spend
    several hundred credits a night on top of ARCHITECTURE.md section 3's "~450 on a
    weekday", against a pool measured at 4,292/5,000. It does not make the email late (every
    BD step is `continue-on-error`) but it accelerates the date on which item 37 starts
    writing false verdicts.

    **CLOSED 2026-08-24:** the rung carries a per-process budget (`PAGE_UNLOCK_BUDGET`, default 100 — one process is one workflow step). Exhausted, the page honestly reads None, identical to the key being absent for that row. Armed the day item 59's closure put the key on two Sunday cron steps (wave-6 R3: ceiling 69+9 calls/Sunday, growing with the pool); pinned by `unlock-budget-drop`.

37. **When Bright Data runs out, every walled row degrades to `None` and every tool writes
    `not this company's board`** — lane: `registry`. `_page_names_company` is carefully
    three-valued and `_ok_to_write` collapses `None` and `False` into one refusal that stamps
    the same positive claim. With `BRIGHTDATA_API_KEY` unset, wave 8 drove Bancor and
    Riskified and got `page_names=None -> REFUSE + stamp "not this company's board"` for
    both. Silent, durable, and self-sealing. The refusal note should distinguish "we could
    not read the page" from "the page names someone else", and an unreadable page should not
    consume the row's re-check token.

38. **`audit_empty_rows`' rotation key is in gitignored `state/`, so the Sunday budget
    **CLOSED 2026-08-26 (`registry`, + one `--own` line in audit-coverage.yml, disclosed):** `cloud_state/audit_seen.json`, registered in `persist_state.STRATEGY`; a local `state/audit_done.json` is read once as a migration. 164 is the same fix.
    re-walks the same prefix forever** — lane: `registry` + `infra`. `state/` is gitignored
    and `audit-coverage.yml` never stages it, so in Actions `done` is always `{}` and
    `parked.sort(key=lambda ir: done.get(ir[1][0], ""))` is a stable sort on a constant —
    file order, every Sunday. The code comment already knows the first half and the next
    line's claim ("the next run starts where this one stopped") is false in the cloud. This
    is the identical starvation bug this lane FIXED in `scan_dead_domains` by moving its key
    to `cloud_state/scan_seen.json`. One line here plus one `git add` in the workflow.

39. **`listing-hunt.yml`'s budgets already exceed its own timeout, and no commit step in the
    repo has `if: always()`** — lane: `infra`. Budgets sum to 325 of 330 minutes before
    checkout, `npm install -g`, `playwright install --with-deps` (3-6 min) and a commit retry
    loop that sleeps 225s. Every budget is checked BETWEEN rows, so each step overruns by one
    full row — and this lane added a `_page_names_company` call (up to 25s fetch + 90s
    unlock) to that per-row cost. Worst case measured at ~395 min against a 330-minute
    timeout; on timeout the job is cancelled, `Stamp the repair stage` runs (`if: always()`)
    and `Commit verdicts` does not, so the entire night's registry writes are discarded. Fix
    is two lines: `HUNT_TIME_BUDGET_MIN: 200 -> 150` and `if: always()` on the commit. Filed
    as items 11 and 16 in earlier waves and shipped unfixed three times.

40. **`ARCHITECTURE.md` §2 is now 36% of the document for one of seven pipeline steps** —
    lane: `registry`, and it is this lane's own bloat. It went from **300 lines (25%)** at
    `e525dab` to **471 lines (36%)** at HEAD. Commit `ae7ba62`, on the same day, is titled
    *"Section 1a was 32% of the architecture document for one of seven steps"* and cut §1a by
    384 lines — §2 is now past the threshold that commit set.

    The "registry in two minutes" block earns its place and must stay. What should move to
    `docs/sessions/` are the four dated post-mortem narratives now embedded in the reference
    text — the "an earlier version of this said X" paragraphs. They were written to stop a
    number being re-trusted, which was right at the time, but a reference document should
    state what is true and let the session log carry how it was got wrong. Proposal, not an
    action: this is a documentation pass and the brief forbids deleting in one.

    **CLOSED 2026-08-24:** §2 is 361 of 1209 lines (29.9%). Fifteen post-mortem blocks
    moved to `docs/sessions/2026-08-24-registry.md` under their own heading; the
    hand-written ownership matrix replaced by the derived `registry_health.py` pointer
    with the pool constants named; seven stale facts corrected against code. The ~300
    target was not forced: going lower meant deleting normative reference content
    (state-transition diagram, verdict taxonomy, the three rule sections), and a
    reference that is complete beats one that is short.

41. **`registry_health.py` has four retyped pool mirrors and a guard that checks one** —
    **CLOSED 2026-08-25 (verified):** all mirrors import the tools' predicates; `test_every_ownership_mirror_agrees_with_the_tool_it_mirrors` pins all of them.
    lane: `registry`. `_HUNT_SHAPE`, `_PROBE_SHAPE`, `_EXTRACT_GAP` and the crack literal
    mirror four tools' filters; only `triage_dark`'s predicates are imported.
    `test_the_ownership_matrix_is_built_from_the_tools_own_predicates` pins the triage count
    and two negative properties of the hunt, and nothing compares the other three against
    their tools. Drift measured 0 on 2026-08-24, and `_EXTRACT_GAP` is strictly looser than
    `repair_extract_gap.MODE` (it does not require a date) — the direction that hides
    orphans. Extending that test to compare all four is the cheap half of item 1.

## From the registry lane's wave-9 review, 2026-08-24 — and the close-out

Wave 9 was the last review wave. Its severe findings are fixed; everything below is filed
rather than fixed, under a stated bar: **does it write wrong data into `companies.csv` or the
email, or silently lose coverage?** If no, it is filed. That bar is the close-out criterion —
see `docs/sessions/2026-08-24-registry.md` for why nine waves did not converge without one.

42. **`company_identity.ATS_HOST` omits `jobvite.com` and `taleo.net`** — lane: shared
    plumbing. Every registry tool supports them (`crack_walled._HOST_PATTERNS`,
    `audit_empty_rows._SUBDOMAIN_TENANT_HOST`, `deep_validate._UNSUP`,
    `registry_health --ats`), but `ATS_HOST` does not — so on those hosts `verdict()`
    compares the company against the ATS *vendor's* domain, returns `mismatch`, and
    `is_foreign` is True. A correct board is then refused outright even with perfect page
    evidence: `Varonis -> jobs.jobvite.com/varonis` and `Radware -> radware.taleo.net/...`,
    both URLs that `crack_walled.listing_urls()` itself constructs. Worked around locally in
    `listing_hunt._ATS_NOT_IN_ATS_HOST`; the workaround should be deleted when the two hosts
    join `ATS_HOST`. Note also that `ATS_HOST` is an unanchored substring search, so
    `clever.com`, `hibobble.com` and `workablefoods.com` would classify as ATS hosts — no
    such row exists today (checked all 1,199), so that half is latent.

    **CLOSED 2026-08-24 (consolidation):** `ATS_HOST` names both; `identity_gate`'s
    `_ATS_NOT_IN_ATS_HOST` shim and its special branch are deleted (the ordinary ATS path
    is the identical expression). Registry blast radius measured: 0 rows changed. Pinned
    by the re-aimed `identity-jobvite-open` mutation and the Varonis/Radware cells.

43. **`verdict() == "weak"` has no consumer anywhere in the repo** — lane: shared plumbing.
    Produced at `pipeline/company_identity.py:235`, read nowhere:
    `grep -rn '"weak"' --include=*.py .` returns that one line. `is_foreign` is
    `verdict() == "mismatch"` only, so a `weak` row passes every gate except
    `crack_walled._ok_to_write`'s page test — including `Phoenix Financial ->
    phoenixtma.com`, the example `company_identity`'s own docstring gives for "a real
    company, not the right one". ARCHITECTURE.md section 2 and section 3 both described a
    consumer that does not exist; both corrected 2026-08-24.

44. **Three `registry_health.py` reporting defects** — lane: `registry`, none of which can
    **CLOSED 2026-08-25 (`registry`):** no key reads `no SERPAPI_KEY`; an unknown flag prints the known flags and exits 2; the doubled ladder alarm is gone with the census step no longer probing the ladder at all.
    write a row. `--resources` correctly reports a missing key, but the default report prints
    `SerpApi: key present; quota NOT checked` unconditionally when `live` is false, even with
    no `SERPAPI_KEY` at all. The ladder alarm is emitted twice once `registry_alarms.json`
    exists. An unknown flag (`--pools`, `--not-a-flag`) silently prints the default report and
    exits 0 rather than saying it did not understand.

45. **`repair_extract_gap` double-counts its summary** — lane: `registry`. `still` is
    **CLOSED 2026-08-25 (`registry`):** refusal branches `continue`; `test_repair_extract_gap_counts_a_refused_row_once`.
    incremented once per failed gate rather than once per row, so a run over 4 rows printed
    "1 activated, 6 still dark". Cosmetic, but it is the log a human reads to decide whether
    the gate is too tight.

46. **Do not re-measure an activating tool's gate against ACTIVE rows.** Wave 9 reported the
    `deep_validate` gate refusing 25 of 31 tenant-mismatched rows and named the BACKLOG 21
    acquisition roll-call (Itamar Medical, Habana Labs, VMware, Splunk, HP Indigo, Samsung).
    `deep_validate` reads `r[4] == "false"` only, so it never sees any of them. The reachable
    set is **5 parked rows** — `NanoLock Security -> gen.wd1` (Gen Digital),
    `Sight Diagnostics -> SIG1008SIGH` (Sight Sciences' board), `Datorios -> sartorius.wd3`,
    `Kubiya -> apply.workable.com/kubapay`, `Harel Insurance -> geico.wd1` — and all five are
    boards the gate SHOULD refuse. Recorded because the finding was well-evidenced,
    confidently argued, and measured on a population the tool cannot reach; the next reviewer
    should check reachability before quoting a refusal count.

## From the registry rebuild, 2026-08-24 (the refactor pass)

47. **Unifying the terminal-state definitions costs 10 rows of coverage, and they are the
    right 10** — lane: shared plumbing. Measured, not estimated. There are **6 distinct
    memberships** across the tree:

    | membership | where |
    |---|---|
    | `defunct, domain-dead, alias-of` | `audit_empty_rows:55`, `check_invariants:64`, `crack_walled:48`, `deep_validate:285`, `listing_hunt:274` |
    | `defunct, domain-dead, duplicate of, redundant, recruiter` | `pipeline/verdicts.TERMINAL:40` — the nominal source, and the only one **missing `alias-of`** |
    | `defunct, domain-dead, alias-of, duplicate, redundant, recruiter` | `registry_health:214`, `triage_dark:80` (note bare `duplicate`, not `duplicate of`) |
    | `defunct, domain-dead, alias-of, duplicate of, redundant` | `registry_health._REASON:77` |
    | `defunct, domain-dead` | `probe_candidates:96` |
    | `defunct` | `scan_dead_domains:96`, `repair_dead_urls:69` |

    Adding `alias-of` to `verdicts.TERMINAL` and pointing the five inline copies at
    `is_terminal` makes **10 parked rows newly terminal**, because those five gain
    `duplicate of` / `redundant` / `recruiter`:

        Abra · NICE · Via Transportation · Marvell Israel · Google  (+5 more)

    Every one is a deliberate permanent deactivation, and five of them are exactly
    `check_invariants.ALLOWED_ORPHANS`. So the unification is arguably CORRECT — those rows
    should stop being re-checked, and they would stop being orphans — but it is a coverage
    change of 10 rows in shared plumbing, not a tidy-up, and `probe_candidates` and
    `scan_dead_domains` hold strict SUBSETS that would start excluding rows they currently
    scan. Reproduce before touching it:

    `python -c "import csv,re;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>=6][1:];p=[x for x in r if x[4]=='false'];n=re.compile(r'defunct|domain-dead|alias-of',re.I);w=re.compile(r'defunct|domain-dead|alias-of|duplicate of|redundant|recruiter',re.I);print(len([x for x in p if n.search(x[5] or '')]),len([x for x in p if w.search(x[5] or '')]))"`
    -> `76 86` on 2026-08-24.

    **Deliberately not done in the rebuild pass**, which was a safety refactor: it is a
    behaviour change to a file every lane imports, and the brief's rule for shared plumbing
    is to declare it and let the affected lanes weigh in, not to smuggle it into a commit
    about identity gates. Do it with `ALLOWED_ORPHANS` in the same change, since these 10
    rows are why that list exists.

    **CLOSED 2026-08-24 (consolidation), with the measurement redrawing the plan:**
    `verdicts.TERMINAL` gained `alias-of` (37 rows, all genuine aliases, newly terminal);
    `audit_empty_rows`, `crack_walled`, `probe_candidates` and `triage_dark` all derive
    from `TERM_RX` (probe and triage measured zero change; audit/crack widen by 9 named
    rows — recruiters, a kept-inactive duplicate, three redundant-scrape twins — all
    correctly final and none carrying a pool token, so pool membership moved 0).
    `scan_dead_domains` is the ONE deliberate divergence, kept and documented at its
    selector: excluding `domain-dead` would end its core function (re-testing dead domains
    so a revived one is cleared) — that is where this item's original 10-row cost lived,
    and the answer was to not unify that tool, not to pay the cost.

48. **The re-check pool is still defined in four places** — lane: shared plumbing, unchanged
    **Registry half CLOSED 2026-08-25:** `listing_hunt.HUNT_POOL` + `in_hunt_pool` are module-level and imported by the mirror; `url-cleared`/`url-flagged` are in `TOKENS` (the '9 invisible rows' claim is stale). What survives is one token list spelled three times (1's residual).
    by the rebuild for the same reason as 47. `pipeline/verdicts.TOKENS` (18),
    `listing_hunt.main()`'s inline regex (16), `check_invariants.POOL` (17),
    `registry_health._HUNT_SHAPE` (16). `url-cleared` and `url-flagged` are in the inline
    copies and missing from `TOKENS`, so of the 39 rows carrying one, the 9 that carry
    nothing else are invisible to `in_pool`. The rebuild DID remove the two mirrors it could
    remove without a behaviour change — `registry_health.pools()` now imports
    `identity_gate.is_walled` and `repair_extract_gap.MODE` rather than retyping them, and
    `test_every_ownership_mirror_agrees_with_the_tool_it_mirrors` keeps them honest. The
    remaining two need `listing_hunt` to grow an extractable `targets(rows)`; that is the
    real fix and it is a `registry`-lane job.

## From the rebuild's wave-1 review, 2026-08-24

Three reviewers, all findings reproduced before action. Seven were fixed; these are filed.

49. **`activation_ok` refuses a legitimate acquisition on a subdomain-tenant machine
    endpoint, and that is deliberate** — lane: shared plumbing, and the fix is a data column.
    `page_names_company` returns `None` for a page it could not read and `is True` refuses
    `None`, so where the endpoint is a machine API (`/wday/cxs/<tenant>/<site>/jobs`, HTTP
    400 on GET) a failed tenant near-match IS the refusal — no page can ever be read there.

        activation_ok("Habana Labs (Intel)", "workday",
                      "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/x/jobs", 12) -> False

    That is item 21's shape re-entering through the `None` branch rather than a `mismatch`
    veto. It is accepted for a narrower reason than item 21 covers: these five callers
    ACTIVATE a currently-parked row, so a wrong refusal leaves the row parked, visible and
    recoverable, while a wrong acceptance publishes another company's jobs under this
    company's name. Item 21 measured the cost of vetoing rows that were already ACTIVE.
    The real fix is the `acquired-by` column, not a cleverer string test.

    **CLOSED 2026-08-24:** `Habana Labs (Intel)` is declared (`pipeline/identity_facts.py`);
    the data column this item named exists, as a table.

50. **On PATH-tenant platforms the gate admits without ever reading the page it holds** —
    lane: `registry`. `tenant_is_this_company` answers True when there is nothing checkable,
    and greenhouse/lever/comeet/ashby put the tenant in the PATH, so:

        tenant_is_this_company("Bancor", "https://boards-api.greenhouse.io/v1/boards/bancorpbank/jobs") -> True

    i.e. `activation_ok` accepts it even when the caller's own HTML says "Bancorp". The
    equivalent iCIMS URL is refused, because iCIMS is a subdomain-tenant platform the
    predicate scopes. Not fixed here because the obvious repair — read the page whenever we
    hold it — is what item 33 measured refusing 358 rows, and the obvious repair to THAT —
    match the name's head token — is measured wrong too: `page_mentions_company("Sight",
    <Sight Sciences' page>)` is True, and `Sight Diagnostics` is a different company on that
    same board. Tightening `_slug_matches` to near-equality for PATH tenants is the fix that
    would work; it is real work, not a one-liner.

    **The held-page half is CLOSED by f1b28a8 (wave 3):** `activation_ok` now lets a
    READABLE page the caller holds decide, either way, before any tenant clause --
    pinned by `test_validate_empty_a_readable_page_decides_and_a_refusal_is_visible`.
    What remains open is exactly the no-page half: an activation with no html in hand
    on a path-tenant platform is still admitted by vacuity, and the slug-tightening
    above is still the fix that would work.

    **Declared rows closed 2026-08-24:** on a path platform `embedded_board_ok` checks the
    row's own token against its declaration, both ways. What stays open, said plainly: an
    UNDECLARED row on a path platform is still admitted by vacuity in
    `tenant_is_this_company` -- a declaration can only be matched against subdomain
    labels or the row's token, never a URL path (the Riskified/Novartis incident).

51. **A `_WALLED_HOST` entry can be deleted with the suite green whenever that platform has
    no pool members** — lane: `registry`. `test_the_walled_pool_survives_another_tools_note_
    rewrite` defends whichever platform currently has rows (workday, 22 of them); dropping
    `icims\.com` — the platform the Bancor incident happened on — is green today because the
    parked iCIMS pool is 0, and becomes silent coverage loss the moment an iCIMS row parks.
    A per-platform floor, or making the guard iterate `_PLATFORM_ALIAS`, closes it.

52. **The 14-night chain simulation has never actually completed** — lane: `registry`.
    Reviewer R3 attempted it and disclosed that it did not finish: `listing_hunt` spawns
    out-of-process Chromium that an in-process socket stub cannot reach, so night 1 ran past
    40 minutes. Only night 0 was captured (`active=862 crack=50 hunt~=216 unsupATS=50
    darktriage=354 monitored=232 unreach=20 avgnote=102.5`). **Treat "no pool reaches zero
    over 14 nights" as UNPROVEN, not as verified** — every prior claim of that came from a
    simulation with the renderer stubbed at a different layer. A headless-safe harness (or a
    `NO_RENDER=1` switch in `listing_hunt`) is what makes this measurable.

## From the rebuild's wave-2 review, 2026-08-24

Six blocking findings, all reproduced and fixed. These are the residuals.

53. **`probe_candidates`' pool is three tokens `listing_hunt` owns and rewrites: 148 -> 4
    over 14 nights** — lane: `registry`, PRE-EXISTING (`git diff` on that file across the
    whole rebuild is empty). Its selector is
    `monitored candidate|host documented|no IL listing`, and `pipeline/verdicts.py` attributes
    all three to `listing_hunt`/`crack_walled`. `listing_hunt`'s failure branch does
    `replace_own(fr[5], "listing-hunt", "listing-hunt <date>: no listing found")`, which by
    design deletes its own previous `no IL listing; monitored candidate` segment — and with
    it the entire predicate another tool's pool stands on.

    **This is exactly the anti-pattern `identity_gate.is_walled` was rewritten to fix for
    `crack_walled`, left standing for `probe_candidates`.** The fix has the same shape: give
    the pool a durable signal (`probe_candidates` has one — the row's own `api_url` host and
    its `candidate_probe.json` baseline) instead of a string a different tool owns.

    Measured two ways. String algebra on the real registry: applying `listing_hunt`'s own
    write to only its 227 selected rows removes **139** rows from the probe pool. And live,
    in the 14-night simulation: `148 -> 4`, monotone, no recovery, `registry_health` printing
    `4  probe_candidates (05:00 daily)` and raising no alarm because there is no per-tool
    floor (item 34). Caveat the reviewer stated and I keep: the simulation's stubbed
    `hunt_one` never returns a candidate URL on a `nolisting` verdict, so the branch that
    re-adds `monitored candidate` never fired; a real hunt would re-add some rows. The
    139-row single-night figure is stub-free and stands on its own.

54. **`auto_expand._row_for_ats`'s refusal persists the REFUSED board into cols 2-3; its
    sibling resets to the row's own URL** — lane: `registry`. Same payload, two builders:

        auto_expand : ['Riskified', 'scrape', 'https://novartis.wd3...', 'https://novartis.wd3...', 'false', ...]
        retry       : ['Riskified', 'scrape', 'https://www.riskified.com/careers/', ...same..., 'false', ...]

    `_row_for_ats`'s own docstring names `retry_unreachable._row_for` as "the same shape for
    the same reason", and they diverge. It matters more than cosmetics now that
    `identity_gate.is_walled` derives pool membership from `row[3]`'s host: a row parked this
    way joins `crack_walled`'s pool pointing at Novartis's Workday. Not blocking because
    `auto_expand` appends rows from the discovery cache, so no `companies.csv` selector can
    enumerate a reachable row.

    **CLOSED by f1b28a8 (wave 3) for the two builders it named** -- and wave-4 R1 showed
    that annotation overstated: `auto_expand._row_for_scrape`, 25 lines above, kept the
    identical leak (`good_url` is a FOLLOWED link that routinely leaves the company's own
    host). The third builder was closed in wave 4; `expand-ats-seed-leak` and
    `expand-scrape-seed-leak` in `tests/mutations.json` re-introduce each leak and must go
    red.

55. **The `taleo.net` half of `_ATS_NOT_IN_ATS_HOST` is untested and its registry set is
    empty** — lane: `registry`. `test_the_jobvite_taleo_branch_is_a_gate_and_not_a_pass_through`
    is named for both platforms and both of its assertions use `jobs.jobvite.com`. Deleting
    `taleo\.net` from the regex is green. Reachable set is 0 today (`taleo.net` appears in 0
    of 1210 rows, `jobvite.com` also 0), so it is filed rather than blocking — one line to
    close by duplicating the jobvite assertions for `radware.taleo.net`.

    **CLOSED 2026-08-24:** the Radware/Taleo both-directions pair now sits next to the
    jobvite cells in the same test.

56. **`apply_resolved`'s veto is scoped to ACTIVE rows, so a PARKED row is re-pointed with
    **CLOSED 2026-08-26 (`registry`):** the veto (proven foreignness) applies to every row.
    no identity check** — lane: `registry`. Deliberate scope ("this tool cannot activate a
    row"), and worth revisiting: a parked row holding a foreign address is exactly what
    `ok_to_write`'s docstring calls "what `listing_hunt`'s fast path later activates on".

57. **`check_invariants.NOTE_CAP` is declared and never used** — lane: `infra`. `grep -n
    NOTE_CAP check_invariants.py` returns one line, the assignment. The 220-char cap is
    enforced only inside `pipeline/notes.py`, so any writer that bypasses that module (there
    was one, `validate_empty`, fixed in this wave) is unguarded by the blocking gate that
    runs in front of the digest. One `bad()` on `len(r[5]) > NOTE_CAP` closes it.

## From the rebuild's wave-3 review, 2026-08-24

Three blocking findings (one per reviewer), all reproduced and fixed in f1b28a8 and fc02764:
the held-page ordering (census pinned), the orphaning refusal notes (hand-off token pinned),
and the dead `platform` parameter (removed; M8 transposition record). fc02764 also closed two
harness masks found while fixing: the gate-call-site detector now resolves aliases, and
`is_aggregator` no longer counts as an identity predicate in the writer enumeration (the
FairFly shape). These are the residuals.

58. **The readable-page rule's accepted cost: a pool row whose own page names only a
    name-shape variant is refused, visibly** — lane: `registry`. The wave-1/wave-3
    calibration dispute ended per protocol (both error cells non-empty, so no threshold
    tuning): a readable page decides either way, and `Siemens Healthineers` on its own
    board whose page says only "Siemens" becomes a VISIBLE `empty-but-suspect`, never a
    silent confirm and never an unread promote. That row is the one proven member
    (end-to-end repro, wave 1). The exposure upper bound is derivable, not fixed — rows in
    `validate_empty`'s pool whose name still has >1 token after `_NAME_STOP` stripping:

        python -c "import csv,re;from pipeline.identity_gate import _NAME_STOP;rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>=6][1:];pool=[r for r in rows if 'no open israel roles' in (r[5] or '').lower()];c=[r[0] for r in pool if len([w for w in re.findall('[A-Za-z0-9]+',r[0]) if w.lower() not in _NAME_STOP])>1];print(len(pool),len(c),c)"

    (59 pool rows, 22 candidates when filed; a candidate only lands in the cell if its page
    actually omits the tail word, which needs a page read to know.) The durable fix is not a
    looser matcher — head-token matching is measured unsafe (`Sight` matches Sight Sciences'
    page; Sight Diagnostics is a different company on that same board). It is a data column
    (`display-name` / `page-name`), the same resolution the tenant veto reached.

59. **`validate_empty` runs with no `BRIGHTDATA_API_KEY`, so the gate's unlocker rung is
    silently inert on the Sunday audit** — lane: `infra`. In `audit-coverage.yml` the only
    `env:` carrying the key is the `crack_walled` step; the `validate_empty` step has none.
    `pipeline/identity_gate.py`'s `page_names_company` gates the residential retry on the
    KEY by design (a missing flag must not downgrade the gate — its docstring), so on this
    step every bot-walled careers page reads as `None`. Direction is over-refusal only: an
    unreadable page falls to the tenant clause, and a subdomain mismatch that the unlocker
    HTML would have overturned lands as a visible `empty-but-suspect`, never a wrong write.
    One `env:` line on the step closes it.

    **CLOSED 2026-08-24:** both audit steps (`wayback_rescue`, `validate_empty`) carry the
    key in `audit-coverage.yml`, same as the crack step.

60. **The push-conflict merge resurrects note segments a fresher run deliberately deleted,
    and 47 of 152 woken rows lose their wake to it** — lane: `infra`, PRE-EXISTING.
    `probe_candidates._wake_note` strips the `listing-hunt` / `dark-triage` /
    `crack-walled` segments so the 19:00 hunt re-selects the row; `merge_csv_rows`'
    conflict path unions ours with theirs and re-adds those segments from `theirs`
    precisely because ours no longer owns the keys. Measured on the real registry: a
    resurrected `listing-hunt <date>` stamp re-arms the 14-day cooldown on 47 of the 152
    woken rows (Pliops, Lili, MediWound, AiVF, Siemens Healthineers, ...), and the same
    recovery block restores `cloud_state/candidate_probe.json` wholesale from ours, so the
    baseline has already advanced — the wake is SPENT, not deferred. Only fires on a push
    conflict (same trigger as item 35, same file). A merge that honours deletions needs the
    deleting tool to own its keys in the union, not just in its own cell.

## From the rebuild's wave-4 review, 2026-08-24

61. **`embedded_board_ok`'s accepted cost: a held page cannot vouch for a board it merely
    embeds, so an embed whose tenant token does not near-match the name is a visible
    suspect, never a promote** — lane: `registry`. The wave-4 B1: `validate_empty` and
    `bd_rescue` fetch the row's CAREERS page and gate the BOARD `extract_ats` finds inside
    it; a page genuinely naming this company (Cogniteam's own, naming it 120x) carrying a
    stale shared-template embed promoted Riskified's board, active=true, on the Sunday
    cron. Reproduced end-to-end; the SimilarTech-off-Similarweb incident is the same shape.
    The fix requires the board to vouch for itself (`identity_gate.embedded_board_ok`:
    subdomain mismatch refuses; otherwise the extracted tenant token must near-equal the
    name). The classes that now land as VISIBLE suspects instead of silent promotes:
    acquirer slugs (Momentis->memic), names not containing the acquirer token
    (Habana-class — consistent with item 49's deliberate refusal), and opaque Comeet uids.
    The 81/460 near-equality measurement (item 21) does not transfer: this predicate runs
    only where the sole page->board binding is the embed itself, on parked audit-pool rows
    that keep their re-check tokens and print in the Sunday suspect summary. If the
    suspect volume in practice says otherwise, the durable answer is the same data column
    item 50 names (`acquired-by`), not a looser matcher — `lili` is a substring of
    `elililly` and that promotion is a recorded incident.

    **Recalibrated in wave 5** after R1/R2 measured the predicate against the slug shapes
    production actually emits (44 own-board path tokens with a generic tail word, all 83
    Workday composite tokens, 21 parenthetical names): a checkable subdomain label that
    passed `tenant_is_this_company` is no longer double-checked against the token; generic
    tail WORDS are stripped from path tokens; `_name_targets` yields parenthetical alias
    halves. Own-board acceptance after: workday 66/83, greenhouse 91/106, comeet 1/127.
    The remaining refusal classes stand as filed above (Comeet uids; rebrand slugs like
    SentinelOne->sentinellabs; names whose extra word is not generic).

    **The acquirer-slug class is DECLARABLE (2026-08-24):** Momentis->memic and
    SentinelOne->sentinellabs are declared and admitted; the Comeet-uid class stays a
    visible suspect by design; the vocabulary class is item 71's.

62. **`restore_only` is exempt from the scheduled-leak check `legacy_unscheduled` gets** —
    lane: `registry`. `test_the_writer_allow_list_only_covers_tools_no_workflow_runs`
    intersects only `_LEGACY_UNSCHEDULED` with the scheduled set; both buckets feed
    `tools/mutate.py:_load_exempt` identically, so a name added to `restore_only` is
    exempted from the enumeration AND mutation coverage with no workflow check. No defeat
    rides it today (the wayback behavioural fixture still fails when R2 demonstrated the
    bypass). The close is one line: intersect both buckets, and demand that a
    `restore_only` entry's writes never touch col 4.

63. **`_modules_a_workflow_runs` sees only `python <name>.py` run-lines and does not follow
    imports** — lane: `registry`. A `python -m` invocation or a wrapper script would not
    register, and three scheduled modules import from `legacy_unscheduled` ones
    (`auto_expand` <- `resolve_deep`, `retry_unreachable` <- `ingest_research`,
    `audit_empty_rows` <- `comeet_resolve`). Verified harmless at 8636b48: every ungated
    write in those three sits under a `__main__` guard or writes `out/deep_rows.csv`, so
    nothing a scheduled importer touches reaches a registry write. It stays true only by
    convention; the derivation should follow imports or the allow-list test should assert
    the imported modules' writer functions are never called.

64. **Registry writers run inside the 05:00-08:30 UTC freeze, and three writer workflows
    commit without `check_invariants`** — lane: `infra`, PRE-EXISTING. `self-heal.yml`
    06:00 runs `apply_resolved.py`; `auto-expand.yml` 08:00 appends rows. The freeze rule
    as written (CLAUDE.md) binds the operator's dispatch/cancel, not the crons — but the
    digest at 05:00 reads what 02:30 wrote, and `auto-expand`/`retry-unreachable`/
    `audit-coverage` commit `[skip ci]` with no `check_invariants` step
    (`grep -rn check_invariants .github/workflows` -> daily-digest.yml, tests.yml only).
    Wave 3/4 changed neither the schedules nor the rows-per-run.

    **The invariants half is CLOSED 2026-08-24 — in two passes, because the first
    overclaimed:** the first commit gated three workflows and wave-6 R3 named the five
    other cron writers still committing ungated (self-heal, triage-dark, listing-hunt,
    scrape-refresh, deep-validate) plus wave-6 R2 the fourth conflict-recovery sibling
    (daily-digest's). All NINE committing workflows now run `check_invariants.py` before
    their commit step and on the recovery-path merged registry, and `merge_csv_rows` —
    the one truncating companies.csv writer outside `pipeline.atomic` — writes atomically,
    so a runner kill mid-merge leaves the OLD file. The asymmetry R3 measured (an ungated
    writer's break makes every GATED workflow discard its runs) is thereby gone: whoever
    breaks it, fails. The freeze-window observation stands as written.

65. **`empty-but-suspect` waits out `listing_hunt`'s 14-day cooldown, and no scheduled tool
    **CLOSED 2026-08-26 (`registry`):** the suspect stamp is dated (`empty-but-suspect <date>; …`) and `listing_hunt.actionable_mode` (module-level now) treats one newer than its own last verdict as actionable; `recheck_suspects.py` stays legacy.
    clears the verdict** — lane: `registry`. A suspect row usually already carries a
    `listing-hunt <date>` stamp, so the hunt suppresses it for the rest of the cooldown
    (latency, not loss — the row stays owned). `recheck_suspects.py` is the only clearer
    and appears in no workflow. The hand-off works; it is just slow, and its terminal
    reader is manual.

66. **`retry_unreachable`'s `ats` refusal branch may have an empty reachable set** — lane:
    `registry`, a measurement note from wave-4 R3: `resolve_deep.ATS_PATTERNS` yields only
    path-tenant platforms (plus `apply.workable.com`, whose labels are all plumbing), so
    `tenant_is_this_company` never vetoes there and `is_foreign` is False on every ATS
    host — the branch fires today only via the gate's page-fetch tail. Do not count a
    fixture on this branch as proof of a live path; the scrape branch is the reachable one.

## From the rebuild's wave-5 review, 2026-08-24 (the final wave)

67. **`merge_csv_rows._merge_notes` has no `_TOOL` key for `empty-but-suspect`, so the
    conflict path can carry two suspect segments for one row** — lane: `infra`,
    PRE-EXISTING. The dedup key falls to `seg[:28]`, which contains the varying `N IL`
    prefix. Measured (wave-5 R3): bounded — six consecutive conflict Sundays hold at one
    duplicate, 0 of 1210 rows lose their own selector, `check_invariants` exits 0; the
    trim pops the stale duplicate first. Cost is one wasted note segment. One `_TOOL`
    entry (`empty-but-suspect`) closes it.

    **CLOSED 2026-08-24 (wave-7 close):** `empty-but-suspect` is a keyed tool prefix; two
    conflict-Sunday segments dedupe to one with ours winning, verified.

68. **`_merge_notes` pops the NEWEST segment while its docstring says "never the newest"**
    — lane: `infra`, PRE-EXISTING. `out` is built oldest-first and `out.pop()` trims the
    tail. In every measured case this is protective (the own selector is `out[0]`), so
    behaviour is fine and the DOCSTRING is what needs the fix — flag with item 67.

    **CLOSED 2026-08-24:** the comment now states what the code does and why it is
    protective (theirs-tail trims first; 0 of 1210 rows lose their own selector).

69. **`_tenant_near`'s ±1 window is loose for names whose core is ≤3 chars** — lane:
    `registry`. Five reachable pool rows (`MAX Security`, `MSD`, `Z2A Digital`,
    `zap group`, `3M`) would accept any 2-4-char token containing the core. No wrong
    accept is exhibitable without live pages (wave-5 R3 named the rows; the one real
    coincidence, `Z2A Digital` <- KELA's Comeet uid `2A.004`, predates the window pin).
    If one ever fires, the fix is a minimum-length floor on the target, not a wider
    window — the window is pinned at ±1 by `embed-near-window-drift`.

    **The minimum-length rule landed in wave 6:** a form or target under 3 chars must
    match EXACTLY, which closes the digit-stripped-Comeet-uid class (`F2.004` -> `f`
    contained in `f5`) and `hp`/`hpe`, with the acceptance census byte-identical.
    The residual is near-length collisions above the floor (`orca`/`orcam`), still
    outside every caller's reachable set; the durable answer remains the data column.

## From the `discovery` lane follow-up, 2026-08-24

70. **The intake filters throw away company names every day and nothing records WHICH.**
    — lane: `discovery`. `looks_like_junk` and `is_recruiter` rejected 32 names on
    2026-08-24 alone; both bridges keep only a COUNT, so a wrongly-rejected employer is
    invisible forever and un-appealable. The fix is a small merge-only ledger (name,
    reason, first/last seen, bounded by TTL) written from both `discovery_daily.py` and
    `discovery_telegram.py`. Deliberately NOT built 2026-08-24 (operator's call); this
    entry exists so the gap stays visible.

71. **A funding-news feed is the only source shape that finds a company BEFORE its first
    job posting.** — lane: `discovery`. Geektime publishes funding announcements over a
    keyless RSS feed; a funded Israeli company hires analysts before any job board indexes
    it, so this would feed the research queue names no sweep can see yet. Probe before
    wiring, per the Telegram-channel rule: the number that matters is how many items parse
    to a company name. New work, not a resumption — nothing in the repo has tried it.

## From the extended program's wave-6 review, 2026-08-24

Four verified blocking findings, all fixed in the wave-6 batch: the parenthetical-filler
target (B1: bare `israel` as an identity for `Dun & Bradstreet (Israel) Ltd.` — a pure-filler
alias half is no longer a target); the ungated fourth conflict-recovery sibling plus the
non-atomic merge writer (B4); the unguarded new TERMINAL tokens (B3 — `redundant` drop
re-opened Marvell Israel into the activating crack pool, suite green); and the consumer-side
pool selectors (B3 — `search`->`match` emptied the probe 130->0 and triage 18->0, suite
green; each tool now owns an `in_*_pool` predicate that `main()` selects with,
`registry_health` imports, and behavioural cells drive on mid-note tokens).

70. **The LinkedIn guest walk's worst case grew ~5x inside the digest job** — lane:
    `discovery`, filed from wave-6 R1: `f6d7605` makes the sweep 27 queries and `efdf76a`
    raises `LINKEDIN_GUEST_PAGES` 30->50, so the ceiling is ~1,350 sequential requests
    inside `daily-digest.yml`'s 150-minute budget, behind continue-on-error. Also filed:
    ~~`discovery_daily.py` does not clear `ended_on_cap` on the paid-budget break, so every
    city query on a blocked runner prints the raise-the-cap tripwire — the exact evidence
    the 30->50 bump cited.~~ **Proven and fixed 2026-08-25** (`6edc8ec`): the 05:36 run
    printed it for five blocked queries; one exit-reason string now, guarded by
    `test_a_blocked_guest_walk_does_not_print_the_raise_the_cap_tripwire`. The first half
    (the ~1,350-request worst case inside the digest job) is still open; measured 2026-08-25
    the 27 queries took 4m15s with LinkedIn blocking mid-walk.

## Wave 7 (the confirmation review) — GO, and the program's close, 2026-08-24

Zero blocking. The wave-6 batch verified end-to-end: the acceptance census is
byte-identical across all 464 rows (the only change in 2,875 census lines is the intended
`israel` target removal), the atomic merge is byte-identical on the success path, all
three pool extractions select identically, and all nine workflow gates sit before their
commits. Five filed test gaps, four closed the same day with cells and records
(`tenant-short-exact-tighten`, `unlock-spent-increment-drop`, `invariants-terminal-narrow`,
`merge-inplace-revert` — each verified killed); items 67 and 68 closed. Catalogue 101.

71. **A generic-adjacent parenthetical still yields a generic target: `Citrix (Cloud
    Software Group)` -> `cloud`** — lane: `registry`, PRE-EXISTING (identical at 93f6f5d).
    The wave-6 filter removes only PURE-filler variants; `cloud` is not in `_NAME_FILLER`,
    so it admits any tenant within the ±1 containment window (`icloud`, `clouds`). No
    wrong accept is exhibitable on today's registry and the row is outside every embed
    caller's pool. Deliberately NOT closed by widening `_NAME_FILLER` — that set feeds
    `tenant_is_this_company` registry-wide and needs its own measured change; the durable
    answer is the same data column as items 50/61.

    **CLOSED 2026-08-24, two ways:** the parenthetical split no longer exists (identity B5),
    and `Citrix (Cloud Software Group)` is declared -> tibco, so it builds no string targets.

## From the health / declared-identity / legibility program's confirmation wave, 2026-08-24

72. **`verdicts.TERMINAL`'s `recruiter` token matches the substring in `SmartRecruiters`** —
    lane: `registry`, PRE-EXISTING (the unification widened its reach to `listing_hunt` and
    `deep_validate`). Three ACTIVE rows carry the substring in a note with no pool token
    today — `Armis`, `HiBob`, `kueez` — so nothing changes tonight; the day any of them is
    parked with a live verdict token it is permanently terminal and no pool re-opens it.
    `registry_health._REASON` already documents this class ("agency-hood is decided by the
    company NAME via `is_recruiter`, never by text found in the note"); `TERM_RX` did not
    get it. Fix: `is_recruiter(name)` in place of the token, or a word boundary — measured
    against Census A and the pools before it lands.

73. **A declared row is refused by a subdomain bearing its OWN name** — lane: `registry`,
    by design: the declaration replaces the heuristic rather than adding to it
    (`identity_facts.py`: "declared rows skip them entirely"), so `Merck (MSD)` on a
    hypothetical `merck.wd5` host refuses until `merck` is declared. Reachable set 0 today;
    filed so a future tenant migration is diagnosed as a declaration edit, not a gate bug.

74. **`cloud_state/registry_alarms.json` is written nightly and read by nothing** — lane:
    `registry`. The digest calls `alarms_state()` directly; the file is an audit trail that
    churns its `date` daily in a committed state file. Keep (it is the record of what was
    mailed) or drop the `date` — either is one line.

75. **The workflow-edit failure class, three times this session** — lane: `infra` +
    `registry`. Every blocker the confirmation wave found (and wave 6's B4 before it) was a
    workflow edit whose sibling sweep was incomplete: a producer declared failure-tolerant
    while its consumer treated the output as mandatory; a step missing the env its
    siblings carry; four of nine commit steps gated. Each is now pinned by a text-parse
    test, but the class deserves one generic check in `docs/check_docs.py` or the suite:
    for every `continue-on-error` step that writes a file, no later `git add` may list that
    file alongside mandatory paths; for every step invoking a module that reads a secret,
    the step names it. Filed rather than built here: a linter right 95% of the time is
    the wrong tool, and the two named shapes are exactly what a first version should pin.

## From the `scraper` lane, 2026-08-24

Record: `docs/sessions/2026-08-24-scraper.md`. Numbers re-derived that day; re-derive before acting.

84. **A rot-parked row that carries `dark-triage …: page-empty` never reaches the hunt** —
    **Measured 2026-08-25 (`registry`):** reachable set today is 0 — no parked row carries both `scrape rotted` and a `page-empty` stamp — so the rule stays filed, not built.
    lane: `registry`. `refresh_scrape_cache._park` writes `scrape rotted (error Nd) …; parked
    for re-hunt`, but `listing_hunt.in_hunt_pool` excludes any note matching the page-empty
    triage stamp, and 108 of the 207 rot-tracked rows carry one. Simulated across those 108:
    `registry_health.pools()` → `listing_hunt 0, triage_dark 108` — owned, but only by the tool
    that already stamped page-empty. A `scrape rotted` segment written AFTER the triage stamp
    should probably win (the row was active and erroring, so page-empty is stale). Found by
    wave-1 attacker C.

85. **CLOSED 2026-08-24 (scraper lane, with the operator's approval — `stages.alarms()`,
    read by `pipeline/run.py`, rendered as `- **Stages:**` by all three renderers).** Was:
    nothing reads the `collect` stamp's `alarm`, and `stages.require("collect", 1)` is
    silent at exactly one day — lane: `infra` (`pipeline/run.py`, the three audit renderers
    in `pipeline/digest.py`). A mass-failure night stamps `date=TODAY`, so `require` says
    fresh; the only trace in the mail is `alarm=…` inside the collapsed `Stage order:` line. A
    crash night leaves yesterday's stamp, `age == 1`, and `1 > 1` is False, so no
    `::warning::` either. Proposed hook, ≤6 lines after the `stages.require` calls:
    `alarm = (stages._load().get("collect") or {}).get("alarm")`; if `alarm` or
    `stages.age_days("collect") != 0`, print `::warning::stage collect …` and put the line in
    `summary["stage_alarms"]`, rendered as `- **Stages:** …` beside `- **Registry:** …`.
    Found by wave-1 attacker D.

86. **`pipeline/fetchers.fetch_scrape` hard-codes `scraped_cache.json` next to the package**
    — lane: `ats-fetch`. A rehearsal that wants the digest to read a scratch cache has to
    pre-seed `fetchers._SCRAPE_CACHE` from a Python driver (the scraper session did exactly
    that). An env override (`SCRAPE_CACHE_IN`) or a `path=` parameter would make
    `python -m pipeline.run --only … ` rehearsable from the shell.

87. **Retire `cache_new_rows.py`** — lane: `docs` (it names the file in `docs/MODULES.md:76`,
    `docs/gen_modules.py:61`, `docs/AGENT_BRIEF.md:90`). It is a 15-line shim now: no
    workflow ever ran it, the refresh always follows the 19:00 hunt (both in the `repo-state`
    group), and its one useful behaviour is `python refresh_scrape_cache.py --only-missing
    --apply`. Delete the shim and the three rows together; `docs/check_docs.py` enforces it.

88. **Strategy 2 (rendered-DOM links) produces run-together cards, and `_loc_from_ctx` keeps
    up to 28 characters of title in the location when the card has no punctuation** — lane:
    `scraper`. On the captured Port.io page the DOM pass added 16 entries with location
    `"Editor Tel Aviv - Israel"` — 6 US-titled roles and 10 mangled twins of real Tel Aviv
    postings; the extractor now stops at the first strategy that yields (so those no longer
    ship, at the cost of DOM-only roles the structured pass misses — one on Port.io), but a
    page where the DOM pass is the FIRST hit still gets them. A synthetic card `<h3>Senior Data Analyst</h3><span>Tel Aviv,
    Israel</span>` yields location `"nior Data Analyst 0 Tel Aviv, Israel"`
    (`test_scrape_card_headings_need_three_siblings_and_role_titles` documents it). Fix the
    `([A-Za-z][\w.\-' ]{1,28},?\s*Israel)` capture to stop at a title boundary.

89. **Two scraper costs nobody has measured, and one silent cap** — lane: `scraper`.
    `_LINK_PAGES_PER_PREFIX = 25` truncates strategy 4 without a flag (Bright Data sits at
    exactly 25 in the cache; a deadline truncation IS flagged since wave 3). (a) The plain-HTTP re-fetch
    after strategies 1–2 miss runs for every empty company (~200 × ≤15 s a night) and its HTML
    is concatenated onto the rendered page, so strategies 3–5 parse a doubled document. (b) The
    last-ditch `re.finditer(r"\{[^{}]{0,4000}\}")` scan runs over every non-JSON body,
    including multi-megabyte HTML documents that mention `JobPosting`. Count how many cached
    jobs each produces (the A/B harness in the session record can) before changing either.

90. **Per-job strategy provenance in the cache** — lane: `scraper`. `ScrapeResult.strategy`
    exists and the refresh prints per-run strategy counts; a `_strategy` key per job (the
    `_jd_attempted` precedent) would answer "which strategy carries the fleet" from the cache,
    at the cost of diff noise on 1,200 entries. Deferred on purpose.

91. **A warning-first invariant on the `collect` stamp** — lane: `infra`
    (`check_invariants.py`). If `cloud_state/pipeline_stages.json["collect"]` is dated today
    and `errors / scraped > 0.5`, or `with_jobs` is under half of the previous night's, print
    `::warning::` — never block (§K in `docs/sessions/2026-08-23.md`: a blocking check once
    discarded a full run).

92. **Mutation records for the scraper guards** — lane: `registry` (owns `tools/mutate.py`
    and `tests/mutations.json`). Proposed ids: `scrape-error-inverted` (swap the `status ==
    "error"` test in `_apply_result`), `scrape-carry-on-empty`, `scrape-massfail-threshold`
    (20 → 80), `scrape-park-outside-error`, `scrape-since-not-reset` (drop the `why` change
    test in `_rot_bump`). Each is killed by a behavioural test in `tests/test_units.py` today.

93. **Stale numbers in docs the scraper lane may not write** — lane: `docs`. The one-screen
    diagram in `ARCHITECTURE.md` (`433 API rows`, `16 platforms`, `412 rows`), `docs/
    AGENT_BRIEF.md:53,90` (`412`), `HANDOFF.md:175-176` (Eightfold/Phenom "no native fetchers"
    — `grep -n "def fetch_eightfold\|def fetch_phenom" pipeline/fetchers.py` finds both), and `docs/BACKLOG.md` item 13's dedup
    measurement (today, with `pipeline.store.merge_key`: 1,225 jobs / 1,194 keys / 31 dropped,
    not 1,110 / 1,079 / 12).

95. ~~**`merge_json_cache.merge` cannot express a deletion**~~ — **closed 2026-08-25 (`infra`)**: the deletion rule is in `merge()`, pinned by the cache-merge guard and `tests/rehearse_infra.py --conflict`. Original text: — lane: `infra`. It starts from
    `theirs` and iterates `ours`, so a company key the refresh deliberately dropped tonight
    (empty, carry expired after `CARRY_MAX_DAYS`, parked) comes back with yesterday's jobs
    on every push-conflict night, and the `pipeline_stages.json` restored beside it still
    describes the cache that was not committed. Rule to add: drop `k` when `k in base and
    k not in ours and base[k] == theirs[k]` (origin did not touch it; we deleted it on
    purpose). Found by wave-3 attacker A; conflicts on the 00:00 push are rare (the hunt
    ends by 00:30) but the loss is silent and repeats nightly.

96. **Three scraper constants no test observes** — lane: `scraper`. Predicted (not applied)
    survivors of the 2026-08-24 mutation sweep: `_extract`'s plain-fetch gate
    (`deadline.remaining() >= 3` → `>= 30` would silently stop the plain-HTTP rescue for any
    company with 3–30 s left), `_readable`'s 2,000-byte floor (the classification table only
    uses 500 / 2,500 / 3,000), and `_LINK_PAGES_PER_PREFIX = 25` (every test injects
    `pages_per_prefix`, so the module default is never read; a live board with 25 positions
    would yield 2 under `= 2`). One assertion each, then a `tests/mutations.json` record (92).

94. ~~**`daily-digest.yml`'s conflict path restores `cloud_state/` wholesale**~~ — **closed 2026-08-25 (`infra`)**: `persist_state.py` rebuilds each owned path from the run's own commit; nothing is copied. Original text: — lane: `infra`
    (HANDOFF open item 7 already names `seen.db`). It can also revert a `collect` stamp that
    scrape-refresh pushed after the 05:00 checkout; the next 00:00 run re-stamps, so no mail
    number changes, but the same wholesale copy is what the other workflows were cured of.

## From the `ats-fetch` lane, 2026-08-24

Record: `docs/sessions/2026-08-24-ats-fetch.md`. Everything below is outside that lane's
write list; each item names the lane that owns it and the command that proves it.

76. **Three active scrape rows have a validated native fetcher waiting** — lane: `registry`
    **Rows converted 2026-08-25 (`registry`, `bebbee9`):** Qualcomm→eightfold 37 IL, GE HealthCare→phenom 23 IL, Fortinet→oraclehcm 15/503 IL (each re-verified through `fetch_company` that day). The `check_invariants.PLATFORM_HOST` half is item 193.
    (a `companies.csv` write; the fetchers shipped and are covered in `tests/test_units.py`).
    Measured 2026-08-24 with `python -c "from pipeline.fetchers import fetch_company; ..."`:
    | row today | convert to | `api_url` | result |
    |---|---|---|---|
    | Qualcomm (scrape, "verified 8 IL") | `eightfold`, token `qualcomm.com` | `https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com` | **31–36 Israel roles** (`count=36`; the pager is unstable between calls — distinct requisitions 31, 32 and 36 on three fetches) |
    | GE HealthCare (scrape, active, reports 0) | `phenom` | `https://careers.gehealthcare.com/widgets` | **20 Israel roles** (20 of 985 worldwide, exact) |
    | Fortinet (scrape on Oracle CE, "11 IL") | `oraclehcm` | `https://edel.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_2001` | board 910; `keyword=Israel` 7; `fetch_oraclehcm` on that row returns 503 jobs of which 14 carry "Israel" in `location` (re-measured by the wave-1 audit; an earlier cell here said "total 7, keyword 0" and was wrong) |
    Both new platforms would then need `check_invariants.py`'s `PLATFORM_HOST` map
    (`infra`) to know `eightfold` (`/api/pcsx/`) and `phenom` (`/widgets`) — tenant hosts
    vary, the path does not — or check C2 ("endpoint is not on that host") can never fire
    for them and the one mis-wiring the fetchers warn about (a Phenom host on the pcsx
    path) goes unflagged. Measured but NOT worth converting: PayPal (paypal.eightfold.ai: 0 of
    75), Dolby (jobs.dolby.com: pcsx 0 of 96; `/widgets` 401), Lam Research (0 of ~1,325),
    P&G / eBay / OpenText (Phenom: 0 of 172 / 472 / 317 — exact, unfiltered walks).
    `nutanix.eightfold.ai` and `telekom-growthhub.eightfold.ai` answer 404 on both API
    paths; on the pcsx path `app.eightfold.ai` answers `domain=ericsson.com` with count 0
    and `domain=tevapharm.com` with 403 (the reverse of the old `/api/apply/v2/jobs` path).

77. **`crack_walled` recognises `/api/pcsx` and `/widgets` hosts and still emits `scrape`
    **Eightfold half CLOSED 2026-08-26 (`registry`):** `listing_urls` offers the `/api/pcsx/search?domain=` endpoint first and `crack_one` verifies it through `verify()` like oraclehcm (`cracked-api`). Phenom's `/widgets` is offered too but is POST-only, so `ok_to_write`'s page read returns None and the write is refused — it lands with the path-tenant batch's human-URL mapper. `deep_validate._UNSUP` keeps both names on purpose: `unsupported ATS <x>` is the hand-off token that routes the row to `crack_walled`.
    rows for them** — lane: `registry` (`crack_walled.py:79-80,121-125`). Now that
    `fetch_eightfold` / `fetch_phenom` exist, a cracked Eightfold/Phenom tenant should
    become an API row with the endpoint above, not a nightly browser render. Same for
    `deep_validate._UNSUP`, which still lists `eightfold.ai` as unsupported.

78. **`health.ATS_HOST` does not name `eightfold.ai`** — lane: `registry` + `ats-fetch`,
    **Measured 2026-08-26 (`registry`):** the three `*.eightfold.ai` scrape rows do not convert — Ericsson `app.eightfold.ai?domain=ericsson.com` → `BoardEmpty` (0 worldwide), Deutsche Telekom `telekom-growthhub` → 404 on the pcsx path, PayPal 0 of 75 IL (76). Adding the host to `ATS_HOST` would still hand them to `resolve_broken` for nothing; stays open until they can be converted.
    deliberately left. Adding it would flag the 3 active scrape rows whose `api_url` host
    is `*.eightfold.ai` (Deutsche Telekom, Ericsson, PayPal Israel) as `misconfig-scrape-on-ats` and hand them to `resolve_broken`, whose `_HTML_ATS`
    cannot resolve an Eightfold tenant — a weekly strike for nothing. Add both halves
    together (77 first).

79. **The single `jazzhr` row (Questar Auto Technologies) is scanned daily and can never
    **Row CLOSED 2026-08-26 (`registry`):** `scrape` on `questar.applytojob.com/apply` — `scrape_universal` extracts 4 Herzliya roles from it (measured). Retiring the `jazzhr` platform (`FETCHERS`, `health._PSEUDO_OR_BY_DESIGN`, `platform_check`, `PLATFORM_HOST`) is `ats-fetch`'s.
    produce** — lane: `registry`. `fetch_jazzhr` returns `[]` by design; the row's
    `api_url` is an `/apply` page. Convert it to a `scrape` row on that page or park it,
    then retire the `jazzhr` platform (`FETCHERS`, `health._PSEUDO_OR_BY_DESIGN`,
    `platform_check`, `check_invariants` host map) — `ats-fetch` will do the code half once
    the row is gone.

80. **Greenhouse EU boards are unreadable without a renderer** — lane: `scraper` /
    **Measured 2026-08-26 (`registry`):** rendered in Chromium (6 s settle), `job-boards.eu.greenhouse.io/outbraininc` is 10,887 chars with **0** job links and no Israel mention; the `/embed/job_board?for=` variant 6,231 chars, 0 links. No scrape row is possible today; the EU-fallback rule stays with `scraper`/resolver.
    `registry`. Outbrain's board is `job-boards.eu.greenhouse.io/outbraininc`; the US
    `boards-api.greenhouse.io` answers `{"jobs":[],"meta":{"total":0}}` (so it reads as
    empty, HANDOFF watch-list item 0), `boards-api.eu.greenhouse.io` is NXDOMAIN, and the
    EU page and its `/embed/job_board?for=` variant are a JS shell with **0 job links in
    the HTML** (2026-08-24). There is no JSON to fetch: the fix is a scrape row on the EU
    URL, and a resolver rule that tries the EU host when the US API returns total 0.
    Lever has the same split (`api.eu.lever.co`); the three empty Lever rows today
    (Leadspace, Chaos Labs, Pillar Security) are 404 there too — genuinely empty.

81. **Numbers other lanes' files still carry from before this session** — lane: `docs`
    (`ARCHITECTURE.md`'s one-screen map: "16 platforms, 433 API rows … 412 rows" — today
    18 keys / 436 / 425; `docs/ATS_PLATFORMS.md`'s platform list lacks `eightfold` and
    `phenom` and their URL patterns; `docs/gen_modules.py` line 94 and its output
    `docs/MODULES.md` "16 platforms"); `jd-text` (`pipeline/jdfill.py` docstring:
    "workday (88 active companies), smartrecruiters (19), bamboohr (12)" — today
    66 / 16 / 11, and `eightfold` and `phenom` roles arrive with an empty description on
    purpose — Phenom's ~350-char teaser would clear the 300-char bar and never states
    years — so both belong on that list).

82. **`health_check.py` (the Monday backstop in `self-heal.yml`) overwrites the daily
    run's `stale.json` without the `error` reasons, prints no `mail_lines`, and re-fetches
    all 66 active Workday rows in a burst** — lane: whoever owns `self-heal.yml`'s step
    (`infra`) + `ats-fetch` for the module. Found by the wave-1 health review. It should
    pass `error=` into its results dict and either print `health.mail_lines()` to the
    workflow log or be retired: the daily run has done the same sweep inline since
    2026-08-22, so the "weekly backstop" is now a second writer of the same file.

83. **The fetch loop is ~7 minutes of the digest's 27, sequentially, and `pipeline/run.py`
    owns it** — lane: `infra`. Two censuses on 2026-08-24 summed to 421 s and 434 s of
    per-row fetch time over 436 API rows (median 0.5 s/row; oraclehcm 4–15 s; one
    greenhouse 22 s) — ~69 % of the "Run the pipeline" step (10 m 14 s) and ~26 % of the
    job. A pool of 4–8 threads over `fetchers.fetch_company` would cut it to ~2 min. Not done by `ats-fetch`: the
    loop, `health_results` and `jdfill` live in `run.py`. Evidence on Workday's tolerance
    is mixed — 25 POSTs at 10 threads answered 200 in 3.2 s, and one earlier burst that day
    answered 500 on 14 tenants and never reproduced — so keep Workday rows on one worker
    and measure before trusting it. Note `http.py`'s 30 s timeout × 3 retries makes a
    hung host cost ~100 s on any worker.

97. **Retire (or weekly) the Windows firmographics chain** — lane: `company-intel` (+ `infra`
    for the scheduled task `IsraeliJobs-Firmographics`). Since 2026-08-24 the cloud digest is
    the writer of record and covers the board on its own (ARCHITECTURE §7); the chain spends
    the shared subscription on ~800 registry rows that never render and its output reaches the
    cloud only when someone commits `cloud_state/firmographics.json` by hand. Condition: seven
    consecutive mornings of a healthy `Company intel:` line with no `::warning::company-intel`.
    **2026-08-25 evidence (`discovery` lane, found by accident):** the task is still armed —
    `IsraeliJobs-Firmographics`, trigger every 6 h from 09:00 local (09/15/21/03), last run
    15:00:01, next 21:00 — and it runs `run_firmo_chain.cmd` INSIDE the shared checkout, so
    it rewrote `cloud_state/firmographics.json` at 15:00 and 15:42 (12 new profiles, e.g.
    AGILINA — itself a placement firm) while a lane session was mid-commit. Side effects
    for every lane: a dirty tracked file that nobody staged, `git pull --rebase` refusing
    ("You have unstaged changes") until it is stashed, and a diff that looks like someone
    else's uncommitted work. Reproduce: `Get-ScheduledTask -TaskName IsraeliJobs-* |
    Get-ScheduledTaskInfo`. Until 97's condition is met, the cheapest mitigation is to
    point the task at a separate clone (or `--out` to a scratch path) rather than the
    checkout lanes work in.
    **Operator, 2026-08-25: do NOT retire or disable the task yet — wait for the condition
    above.** Leave it running; only the mitigation (a separate clone / scratch output path)
    is open for a lane to take.
    Then delete `run_firmo_chain.cmd`, `firmo_health_check.py` and the task; `research_firmographics.py`
    stays as the by-hand bulk tool. Until then: `--workers 3` hits `529 Overloaded` (2 of 3
    calls on 2026-08-24 09:13) — drop to 2.
98. **29 identity-duplicate groups in the export** — lane: `company-intel`. AMD / AMD Israel,
    Intel / Intel Corporation / Intel Israel, Amazon / AWS / Amazon Israel … (list:
    ARCHITECTURE §7, "Identity"). `display_index` picks deterministically (fullest, then
    shortest name); merging the records (keep the winner, inherit non-empty fields per
    `firmographics.merge`) is a data change to the committed export, best done in one commit
    with a before/after count.
99. ~~**`_STAGE_LABEL` in `pipeline/digest.py` is not total over `firmographics.STAGES`**~~ — **closed 2026-08-25** (`rolecard._STAGE_LABEL` total over `firmographics.STAGES`, asserted at import; `test_every_stage_the_researcher_can_emit_has_a_card_label`). Original text: — lane:
    `render`. `private-enterprise` (44 records) renders as the raw enum on every card (today's
    SHILA card); `subsidiary`/`government`/`nonprofit` label values the researcher can never emit.
    Pin: `assert not (firmographics.STAGES - set(digest._STAGE_LABEL))`. Declined by the operator
    for the company-intel session on 2026-08-24 as out of lane.
100. ~~**Two junk regexes for one rule**~~ — **closed 2026-08-25** (`rolecard._ABOUT_JUNK = company_info._JUNK_OUT ∪ unable-to-confirm`; `test_the_blurb_gate_is_the_writers_gate_plus_the_render_only_case`). Original text: — lane: `render` (+ `company-intel`). `digest._ABOUT_JUNK`
    misses `UNKNOWN` and `Error:`; `company_info._JUNK_OUT` misses `unable to confirm`. The
    renderer's gate should import the writer's and extend it. Since 2026-08-24
    `company_profiles.json` is filtered through `_JUNK_OUT` on load, so nothing reaches the card
    today; the drift remains.
101. **`looks_like_junk` cannot catch a bare job title** — lane: `company-intel`. Restated from
    item 11: a name that is ENTIRELY role words plus seniority modifiers ("Senior Data Analyst",
    "BI Developer") is not junk. Pin: `assert looks_like_junk("Senior Data Analyst")`.
102. **`company_info` has no `''`-aware API** — lane: shared (`pipeline/store.py`). The monthly
    retry of empty blurbs reads `st.conn` directly in `company_intel._blurbs`; move to a
    `load_company_info_status()` when the store owner next touches the table, and give blurbs
    the same failure memory `firmo_failed` gives research.
103. ~~**`daily-digest.yml`'s conflict path and the export**~~ — **closed 2026-08-25 (`infra`)**: `cloud_state/firmographics.json` merges per company on a conflict (`persist_state.STRATEGY`). Original text: — lane: `infra`. Item 94's wholesale
    restore also reverts `cloud_state/firmographics.json`; `merge_json_cache.merge` is the right
    tool (company-keyed dict) and `firmographics.merge` the right per-record rule.
104. **Mutation records for the company-intel guards** — lane: `registry` (owns `tools/mutate.py`).
    **CLOSED 2026-08-25 (`registry`):** `tools/mutate.py --catalogue PATH` (repeatable; coverage runs over the union). The company-intel catalogue itself is that lane's to add.
    The catalogue in `docs/sessions/2026-08-24-company-intel.md` §"Mutation sweep" was run
    through `tools.mutate.run_one` from a scratch runner; a `--catalogue PATH` flag would let
    each lane keep its own file beside `tests/mutations.json`.


## From the `jd-text` lane, 2026-08-24

Record: `docs/sessions/2026-08-24-jd-text.md`. Numbers re-derived that day; re-derive before acting.

105. ~~**`cloud_state/pipeline_stages.json` has a lost-update window and a wholesale restore**~~ — **the restore half closed 2026-08-25 (`infra`)**: stamps merge per key on a conflict (ARCHITECTURE §4); the in-process read-modify-write window of two overlapping jobs stays (item 159). Original text: —
    lane: `infra`. `scrape-refresh.yml` (00:00, `timeout-minutes: 330`, group `repo-state`) and
    `daily-digest.yml` (05:00, its own group) can overlap by design, and both read-modify-write
    the stamp file (`refresh_scrape_cache.py:537`, `pipeline/run.py` `stages.stamp("publish")`,
    now `jdfill.record_enrich`). Worse, the digest's conflict path (`daily-digest.yml:163-164`)
    copies `cloud_state` back wholesale from checkout time, deleting any stamp another job wrote
    since. The `enrich` stamp is now load-bearing for the mail; a per-key merge of this file
    (like `merge_json_cache`) belongs in the conflict path. Found by the wave-0 design attack.
106. ~~**The markdown mail never prints the inline jd-fill count**~~ — **closed 2026-08-25** (`build_markdown` prints `· JDs fetched inline: N` after `LLM calls this run` when the count is non-zero — wave-1 docs attacker caught the first closure as false: the line had only been added to the two legacy audits). Original text: — lane: `render`.
    `jd_filled_inline` is in the summary dict (`pipeline/run.py`) and rendered by `_text_audit`
    (`digest.py:1385`) and `_html_audit` (`:1418`) but not by `build_markdown` — the one that
    becomes `digests/latest.md`. One line after `digest.py:635`
    (`- LLM calls this run:`): `f"- JDs fetched inline: {s.get('jd_filled_inline', 0)}"`. Until
    then the step log's `jd-fill: 93/153 …` line is the only place the number exists.
107. ~~**A role judged on a bare title keeps that verdict after its text arrives**~~ —
    **closed 2026-08-24 (`classifier`, ARCHITECTURE §7b)**: keys are `v2|company|title|jd`
    or `|bare`; a bare verdict is re-judged once text arrives, a `|jd` one never; the 235
    readable legacy rows are read as bare (12 title-only rows are unreachable). The original text, for the record — lane:
    `classifier`. `llm_cache` is keyed `company|title` (`seniority.py:313`) with no record of
    whether a description was present; a Workday role rejected on 2026-08-23 with `""` is
    `llm_cache` forever, even though the native rung now fetches its JD before `classify`. The
    key (or the cached value) should carry a "had description" bit so a later run with text
    re-judges once. Measured need: 60 of 153 inline fills failed on 2026-08-24, all classified
    bare; their verdicts are cached.
108. **`merge_json_cache` merges per company; the enrichment writes per job** — lane: `infra`.
    `merge_json_cache.py:46-56` keeps OUR whole job list for any company `enrich_scrape_jd`
    touched (base snapshot is taken at checkout, `daily-digest.yml:41-42`). If `scrape-refresh`
    commits first on an overlap day, origin's NEW cards for that company are dropped in favour
    of our older cards-with-descriptions; if the digest commits first, `_carry_jd` keeps
    everything. The correct merge key is `url`/`job_id` — exactly what
    `refresh_scrape_cache._carry_jd:242` already uses. Blast radius today: 20 todo jobs.
109. **6 of the 7 short `matched` rows carry URLs that are not job pages** — lane: `roles`.
    `python -c "import sqlite3;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);print(*c.execute(\"select company,url from matched where length(coalesce(description,''))<300\"),sep='\n')"`
    → two Meta rows point at `metacareers.com/jobs?offices[0]=…` (a search page), Navan at an
    Indeed `viewjob`, Nebius/Taboola at `?gh_jid=` embeds, Port.io at a comeet page. The URL
    a discovery source carries becomes the role's URL on first sight (`store.upsert_matched`),
    and a later sighting from the company's own board does not replace it when the merge key
    matches. Consequence measured: 4 Unlocker credits on 2026-08-24 for 0 fills.
    `jdfill.is_job_url` now refuses the search pages before the Unlocker; the Greenhouse and
    Comeet rungs read the other four. The Meta rows need a real URL from the store's side.
110. **`bd_rescue.unlock` discards what the Unlocker reports** — lane: `registry`.
    **CLOSED 2026-08-26 (`registry`):** `unlock_status()` reads `x-brd-error-code` and `LAST["error"]` says why for every spender that imports `unlock`; a `policy_*` host is stamped `bd-policy <date>: <code>` and never retried; a 401/402/403 from the API stops the pass with a `::warning::` and no stamp.
    `bd_rescue.py:42-53` swallows the exception and never reads `x-brd-error-code`, so a dead
    token (401), a refused host (`policy_20140` — every `myworkdayjobs.com` page) and a walled
    page (`reject_block`) all look like "no HTML". `pipeline.jdfill.Unlocker` reads them; the
    five other spenders (`crack_walled`, `retry_unreachable`, `deep_validate`, `listing_hunt`,
    `discovery_daily`'s Indeed path) should share it, and stop retrying `policy_*` hosts.
111. **The aggregator loop in `pipeline/run.py` has no inline fill** — lane: `infra`. The
    SerpApi/Google-Jobs block (`AGGREGATOR_ENABLED`, dark today) classifies without
    `jdfill.maybe_fill`; if it is ever switched on its roles are judged bare.
112. **`enrich_scrape_jd.py` and `enrich_matched_jd.py` are the same 60-line driver twice** —
    lane: `docs` + `infra`. Both are `run_backfill` with a different `items`/`save` pair. One
    driver module (say `enrich_jd`) with `--target cache|matched` needs: the two `run:` lines in
    `daily-digest.yml`, `docs/gen_modules.py` + `docs/MODULES.md`, `docs/AGENT_BRIEF.md`'s lane
    row, and this file. Not done in the jd-text pass because a rename crosses three lanes.
113. **Eightfold/Microsoft and Phenom job text** — lane: `jd-text`. Eightfold's
    `/api/apply/v2/jobs/{id}?domain=<domain>` answers a plain GET (Microsoft, `job_description`
    6,758 chars, 2026-08-24) but the `domain` is not in the public URL
    (`jobs.careers.microsoft.com/global/en/job/{id}`), so `native_url` cannot derive it; 1 row
    today. Phenom (`descriptionTeaser` deliberately dropped, `fetchers.py:642`) has 0 rows and
    no verified detail endpoint. Wire both when either platform reaches 3 rows; until then the
    inline `by_platform` counters say what the plain page yields.
114. ~~**Only `collect` and `enrich` reach the bold `Stages:` line**~~ — **closed 2026-08-25 (`infra`)**: `repair`/`expand`/`publish` alarm with a one-day window. Original text: — lane: `infra`
    (`pipeline/run.py`). `repair: never run` and a stale `expand` sit inside the collapsed
    `Stage order:` line with a `::warning::` nobody reads; `stages.alarms()` should be
    called for every stage in `stages.ORDER` except `publish`. Found by the wave-2 rehearsal.
115. ~~**A scoped run prints `wrote: … docs/index.html`**~~ — **closed 2026-08-25 (`infra`)**: the tail prints the real directory. Original text: — lane: `infra` (`pipeline/run.py`).
    It actually wrote `out/docs-preview/index.html` (the guard works); the line makes an
    operator think a local experiment clobbered the board.

## From the `classifier` lane, 2026-08-24

Record: `docs/sessions/2026-08-24-classifier.md`; spec: `ARCHITECTURE.md` §7b.

116. **Legacy `llm_cache` rows are never purged** — lane: `classifier`. The 247 rows keyed
    `company|title` (12 of them title-only, unreachable) are read as bare verdicts and re-keyed
    only when a role is re-judged; they stay in `cloud_state/seen.db` until someone runs
    `DELETE FROM llm_cache WHERE title_key NOT LIKE 'v2|%'` — **from a cloud run's own
    commit or on a quiet day, never from a local checkout**: every `repo-state` job's conflict
    path restores `cloud_state/` wholesale (105), so a hand-committed binary that races a
    workflow is silently reverted. Count them: `python -c "import sqlite3;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);print(c.execute(\"select sum(title_key not like 'v2|%') from llm_cache\").fetchone())"`.
    `updated` is only meaningful from the first v2 run (before it every row was upserted daily).
117. ~~**One `claude -p` seam for the repo**~~ — **half closed 2026-08-25**: `pipeline/llm.py` exists (`call()`, envelope-first, tool-less) and `seniority` uses it; `firmographics._claude`, `resolve_llm.py`, `triage_dark.py`, `scrape_universal.py` still spawn their own — lane: `company-intel` / `registry` / `scraper` to migrate (a shared `llm` module under `pipeline/`, was not yet created). Two seams now
    exist with the same shape and different guarantees: `seniority._claude` (tools off, schema,
    system prompt, `is_error` read, cwd = scratch, no shell) and `firmographics._claude`
    (`--allowedTools WebSearch`, return code only, cwd = repo — so every blurb and research call
    still reads `CLAUDE.md` + `CLAUDE.local.md`, ~20k tokens). Hoist the classifier's into
    that module with `tools=` and let `company-intel` migrate; `resolve_llm.py`,
    `triage_dark.py`, `scrape_universal.py` spawn their own too.
118. **Greenhouse `location.name` is a work-mode at some tenants** — lane: `ats-fetch`.
    Cloudflare's 296 postings say `Hybrid` / `In-Office`; the office is in `offices[]`, which
    `fetch_greenhouse` (`fetchers.py:242`) does not read, so an Israeli Cloudflare role would be
    dropped by the Israel gate. Read `offices[].name`/`location` into the location string.
119. **`digest._LOC_CANON` and the four seniority vocabularies are copies** — **partly closed 2026-08-25** (locations: `jdtext._LOC_GROUPS` covers every `israel.py` token, pinned; seniority: `rolecard.sen_canon` uses `seniority._SENIOR/_JUNIOR/_HEBREW_SENIOR` + `roleprofile._LEAD`. Open: the four requirements-header regexes are three lanes' and answer three different questions — left as they are, by decision) — lane: `render`.
    `digest.py:381-393` keeps its own city table (Latin + Hebrew) with no derivation from
    `israel.py` (the 40 names added today render un-canonicalised); `digest._SEN_INFER`,
    `digest._SEN_LEAD`, `roleprofile._LEAD` restate `seniority._SENIOR`, and `roleprofile.py:441`
    files `financial analyst` under Business Analyst while `seniority` hard-excludes it.
120. **Company intel rediscovers an outage the classifier already found** — lane:
    `company-intel`. When the classifier's breaker opens (`Classifier.off_reason`), the digest
    still spends up to 15 min of `enrich_for_run` learning the same thing; one process-level
    "claude unavailable since …" flag (or reading `clf.off_reason` in `run.py`) would skip it.
121. **CLI start-up dominates the LLM tier's wall time** — lane: `classifier`. Locally a call is
    13.5 s wall for 3.2 s of API (`duration_api_ms`); 163 calls ≈ 37 min, which is why the
    minutes budget is 60. Unverified on the ubuntu runner (read tomorrow's `attempts N in M
    min`). `--bare` might trim it under token auth but breaks keychain login locally and is
    untested with `CLAUDE_CODE_OAUTH_TOKEN`; batching several postings per call was rejected
    (cross-contamination, cache shape) — revisit if the runner is as slow.
122. **The cap and the budget bite the same companies every day** — lane: `classifier`.
    `run.py` walks `companies.csv` in file order, so once `CLASSIFY_LLM_CAP` /
    `CLASSIFY_TIME_BUDGET_MIN` is spent the alphabetical tail is `llm_skipped` (keyword rule,
    not cached) run after run. The mail names the count; a rotation (start from where
    yesterday stopped) or "skipped roles first" would drain it.
123. **A quarantined cohort is re-bought every morning until someone reads the mail** — lane:
    `classifier`. `Classifier.commit()` withholds a mass-NO / mass-YES / mass-flip cohort (never
    cached), so the next run pays for the same postings again, bounded only by `CLASSIFY_LLM_CAP`.
    Two consecutive quarantines should open the breaker for the day; that needs one bit of
    state across runs (the `publish` stamp in `cloud_state/pipeline_stages.json` is the place).
124. **One role on two boards is classified twice in one run, and the bare copy can win** —
    lane: `roles` (with `classifier`). `store.merge_duplicates` runs AFTER `classify`
    (`pipeline/run.py`), so a company listed on comeet and greenhouse pays two LLM calls; if the
    bare copy is judged YES first and the JD-backed copy NO, `accepted` keeps the YES for today's
    board while the cache stores the NO. Dedupe on `store.merge_key` before classifying.
125. **Every workflow's conflict path nests `cloud_state/` instead of restoring it** — lane:
    `infra`, **high**. `cp -r "/tmp/ours/$p" "$p"` into an EXISTING directory copies INTO it
    (a second `cloud_state` directory inside the first, likewise `docs` and `digests`), so
    on a conflict day origin's `seen.db`, board and digest are committed instead of the run's —
    the run's verdicts, `matched` upserts and `sent` marks are lost, yesterday's board is
    published and yesterday's digest re-relayed. Fired 4x in production (`8644d8f` shows
    `seen.db` shrinking 1,241,088 → 794,624 bytes). `daily-digest.yml` now uses `cp -rT`
    (classifier lane, 2026-08-24, out of lane); **the other four** with the same block (`auto-expand`,
    `listing-hunt`, `scrape-refresh`, `self-heal`) got the same one-token fix on 2026-08-25 — closed;
    what remains is verifying the next conflict-day commit keeps the run's `seen.db`. Repro: `mkdir -p /tmp/t/cloud_state /tmp/t/ours/cloud_state; touch /tmp/t/ours/cloud_state/seen.db; cd /tmp/t; cp -r ours/cloud_state cloud_state; find . -name seen.db`.
126. **`scrape_universal.ISRAEL_LOC` has no word boundaries** — lane: `scraper`. It is pure
    substring matching: `Akkodis`, `melody`, `explode`, `The Azores`, `unsafed`, `Lodz` all match
    (`Akko`, `lod`, `Azor`, `safed`, `Lod`). Benign in today's pages (10 of 165 matches were inside
    a word, all `Israeli`/Hebrew prefixes) but it feeds `_from_dom`'s 220-char proximity test and
    `_page_is_il` under `SCRAPE_ASSUME_IL`, and the 40 names added 2026-08-24 (`tlv`, `yehud`, `gedera`, `nesher`, `eilat`, `akko`, `safed` …) widened it.
    Build it with `israel.py`'s lookarounds (`(?<![a-z0-9])…(?![a-z0-9])`); it stays a superset.
127. ~~**The bold `Stages:` / `Registry:` alarms sit INSIDE the collapsed `<details>` audit block**~~ — **closed 2026-08-25** (`build_markdown` puts them above the fold under **Needs a look**; pinned). Original text:
    of the markdown that becomes the email — lane: `render` (`digest.py:628-655`), contradicting
    `stages.py:13` ("a bold line in the audit, not a token inside a collapsed block"). Emit the
    alarm lines above the `<details>` and keep the counts inside.
128. ~~**The declared step budgets sum past the job's `timeout-minutes: 150`**~~ — **closed 2026-08-25 (`infra`)**: job 180 min, per-step timeouts, persist `if: always()`; the CLI install stays a hard fail on purpose (the classifier is pinned to it). Original text: — lane: `infra`.
    scan_dead_domains ~15 + probe_candidates 10 + enrich_scrape_jd 25 + enrich_matched_jd 20 +
    JDFILL 25 + classify 60 + FIRMO 15 = 170 min before the two unbounded discovery steps and
    862 fetches; a timeout kill skips the Persist step, so nothing the run paid for survives.
    Raise `timeout-minutes` (210) or make Persist `if: always()`. Related: the
    `npm install -g @anthropic-ai/claude-code@2.1.241` step is the only hard-fail install and
    gates the whole day, while the classifier degrades cleanly to `missing` — give it
    `continue-on-error: true`.
129. **Keyword-tier gaps the wave-1 title sweep left open** — lane: `classifier`. Of 3,723 live
    + cached titles: `analysis`/`analytical` and `head of data` now reach the LLM (fixed), but
    STRONG titles are never ML-vetoed (`Senior Product Data Scientist` accepts on the title
    alone, by design), `Lead Generation Analyst` reads as senior (`lead`), and `Analytical
    Consultant` / `Manager, Performance Research and Analysis` (16 titles) are `signal` +
    `unknown` seniority, so they cost an LLM call each. Re-sweep after a week of `[llm]` reasons.
130. **`test_refresh_shrink_abort_keeps_the_cache_and_stamps_its_reason` fails at HEAD on
    2026-08-25** — lane: `scraper`. `assert (11 <= 12 and False)`: the stamp reads
    `unprocessed-14`, not `shrink-abort-…`. Verified in a throwaway worktree of HEAD (`ef96190`+)
    with no classifier change applied, so it is date- or fixture-dependent, not a regression of
    2026-08-24's work. The suite is otherwise green (508 of 509).
131. ~~**Two documents the `docs` lane owns still describe the old classifier**~~ — **closed 2026-08-25** (README:86 and the brief's lane row corrected). Original text:
    `README.md:86` says "`claude -p` fallback for ambiguous titles only" (the LLM tier is
    title-agnostic and bounded, §7b); `docs/AGENT_BRIEF.md:93` gives the lane "`llm_cache`
    invalidation" where §7b says "the `llm_cache` table's key scheme", and the brief has no note
    that the lane touched `run.py`/`store.py`/`digest.py`/`daily-digest.yml` under an approved
    out-of-lane exception (recorded in `HANDOFF.md` and the session note).
132. ~~**`run.py`'s classifier wiring is pinned by a source-string test, not a behavioural one**~~ — **closed 2026-08-25** (`test_the_pipeline_runs_one_classifier_and_saves_its_verdict_before_rendering`). Original text:
    lane: `classifier` + `infra`. `stats["llm_calls"] = 0` or dropping `clf.commit()` is caught only
    by `test_run_py_holds_one_classifier_and_the_mail_gets_its_alarms` (`inspect.getsource`) — the
    class of guard `tools/mutate.py` marks `must_be_killed_by_behavioural`. The end-to-end
    behaviour is exercised by `tests/rehearse_classifier.py` (by hand), not by pytest. A pytest
    that runs `pipeline.run.run(only=…)` with `fetchers.fetch_company` and `seniority._claude`
    monkeypatched and a tmp db would close it.

## From the `roles` lane, 2026-08-25

Record: `docs/sessions/2026-08-24-roles.md`; spec: `ARCHITECTURE.md` §7c. Closed by this
pass: **124** (judged once per role per text, `roles.classify_grouped`) and the store half
of **109** (a bare discovery card that inherits its verdict is never the canonical in
`merge_duplicates`, so the board's own url is the role's url; the date the card carries is
kept; the Meta listing-url rows are superseded).

132. **Retire `matched` once its four SQL readers read the ledger** — lane: `roles`. The
    ledger (`cloud_state/roles.jsonl` + `roles_text.jsonl`) is the record; sqlite `matched`
    is kept only because `enrich_matched_jd.py` (writes `description`/`jd_attempted` by raw
    SQL), `company_type_analysis.py`, `research_firmographics.py` and `check_invariants.py`
    (check H) read it. When each reads `roles.load()` instead, `matched` becomes a derived
    cache and `seen.db` shrinks by its 105 descriptions (~340 KB before VACUUM).
133. **13 active registry groups read one board under two identities** — lane: `registry`.
    **Same-identity half CLOSED 2026-08-25 (`registry`, `bebbee9`):** ten twins parked `alias-of` their canonical row (Hippo Insurance, Vayyar Imaging, SpearUAV, GenCell Energy, Crazy Labs, Siemens EDA, one zero, ONE ZERO Digital Bank, kornit, Primis Tech); comeet 87.00C is Scopio Labs' (its slug page renders, Sckipio's redirect to the vendor root) so Sckipio is un-addressed and hunt-owned. The parent/subsidiary pairs are item 194. Found on the way: `repair_extract_gap` had no terminal exclusion and selected GenCell Energy the moment it was parked — fixed (`in_extract_gap_pool`).
    Hippo/Hippo Insurance, Cisco/Splunk (Cisco), HP/HP Indigo, Intel/Habana Labs (Intel),
    Broadcom/VMware (Broadcom), Primis/Primis Tech, Vayyar/Vayyar Imaging, Spear UAV/SpearUAV,
    Sckipio/Scopio Labs (two UNRELATED companies on comeet `87.00c`), Crazy Labs/CrazyLabs,
    Siemens/Siemens EDA, ONE ZERO ×3, Kornit Digital/kornit — plus Port/Port.io (both
    active, the posting was on the board twice until 2026-08-25). `test_no_two_active_rows_
    scan_the_same_board` keys on `identity_key` and so passes on all of them. The runtime
    guard (§7c) keeps the product right; the registry fix is `alias-of` parking for the
    same-identity pairs and a decision for the parent/subsidiary ones. Enumerate:
    `python -c "import csv,collections;r=[x for x in csv.DictReader(open('companies.csv',encoding='utf-8')) if x['active']=='true'];g=collections.defaultdict(list);[g[x['api_url']].append(x['company_name']) for x in r if x['api_url']];print(*[v for v in g.values() if len(v)>1],sep='\n')"`.
134. ~~**The conflict path restores `cloud_state/` wholesale, so the ledger cannot merge**~~ — **closed 2026-08-25 (`infra`)** in the only way the ledger needs today: the digest is its single writer, so a conflict keeps the run's file whole; a row-level jsonl merge is item 160 if a second writer ever appears. Original text: —
    lane: `infra`. `daily-digest.yml`'s `cp -rT` (and the seven `repo-state` siblings) copies
    ours over origin's; a `merge_jsonl_rows` script (no such file yet) keyed on `role_id` (newer `updated` wins,
    lists union — `roles.reconcile` is the rule) would make `roles*.jsonl` the first state
    file that survives a conflict day row by row, and is the precedent for doing the same to
    `seen.db`'s other tables (HANDOFF open item 7, BACKLOG 125).
135. **`sent` is now mirrored in the ledger (`sent{}` per role, `emailed_on`)** — lane:
    `infra` + `roles`. `mark_sent.py` still writes the sqlite `sent` table right after the
    run, and `open_sync` mirrors it into the ledger the next morning; once BACKLOG 6 ("intent,
    not delivery") is solved the delivery stamp should land in the ledger directly and the
    table can go.
136. ~~**Discovery-net roles are never closed by `record_run`**~~ — **closed 2026-08-25
    (wave 1)**: on a full run every company but the failed ones is judged, so a role whose
    employer is no registry row (discovery card, stripped recruiter) closes when `_alive`
    drops it; scoped runs still judge only what they scanned.
137. **`render` re-derives what the ledger now records** — **partly closed 2026-08-25** (the `digest.py:793-809` pointer below is pre-split; the rule now lives in `rolecard._fill`/`_from_ledger`) (the render half: `also listed as` on the board card, the archive card and the email heading from `attribution.claimed_by`; re-post dates and archive-only `closed on` from the record. Declined: reading the ledger's `tags` for rendering — a record, not a cache; a vocabulary change must show on every card the same morning (ARCHITECTURE §7d)) — lane: `render`. `digest.py:793-809`
    recomputes the repost badge from `posted_date - first_seen`, `_seniority_chip` ignores
    the stored `seniority`, and `roleprofile.extract` runs on every card each render; the
    ledger carries `reposts`, `status`, `closed_on`, `tags` (`v: 1`) per role. Reading them
    would make the archive able to say "closed on <date>" and the board's insights stable
    across renders. `docs/TAGGING.md` should say tags are persisted (this lane could not
    edit it).
138. **`firmographics` sqlite table is redundant with its export** — lane: `company-intel`.
    Same shape as 132: `cloud_state/firmographics.json` is authoritative (§7), the table is a
    cache, and it is ~half of the daily 1.4 MB binary (HANDOFF watch item 3).
140. **`enrich_matched_jd.py` does not know `matched.status`** — lane: `jd-text`. Its
    query (`WHERE length(COALESCE(description,'')) < ?`) picks superseded rows too (2 of the
    3 today have an empty description), so it spends Bright Data on roles that can never
    appear anywhere; add `AND COALESCE(status,'') != 'superseded'` (one line).
141. **`research_firmographics.py` and `run.py` disagree on the company set** — lane:
    `company-intel`. `SELECT DISTINCT company FROM matched` (research_firmographics.py:144)
    still includes superseded-only companies (OTORIO, Meta Israel, Port.io) while
    `run.py`'s `all_companies` excludes them; read through `get_matched_since` or filter on
    status. `company_type_analysis.py:64` has the same query (analysis only).
139. **A pipeline outage longer than 3 days resets every role's `first_seen`** — lane:
    `roles`. `upsert_matched`'s reappearance rule (gap > 3 days ⇒ new opening) fires for
    EVERY role after a 4-day gap in runs, so every role gets a new episode and would be
    email-eligible again (`filter_new` then suppresses the ones already sent, so the visible
    damage is the board's "new" badges and the `reopened` count). Seen in the rehearsal
    fixture when day 6 was 5 days after day 5. The rule should compare against the last RUN
    date, not the calendar.
142. **`build_digest` is a dead renderer that every lane still pays for** — lane: `infra` (+
    `company-intel`). `run.py` calls it and writes `out/digest-<date>.html/.txt`; nothing reads
    them (verified 2026-08-25 across all 10 workflows and every `.py`) — only its `subject`
    reaches the JSON payload, which `mark_sent.py` never reads. Each new mail line is therefore
    written three times (`build_markdown`, `_text_audit`, `_html_audit`). Remove the call in
    `run.py` (keep a one-line subject), then delete the two audits; the company-intel mutation
    fixture `tests/fixtures/company_intel/mutations.json` (`ci-intel-line-md/txt`) pins their
    source text and must be updated in the same commit.
143. **`roles.tenant_slug` is not a tenant** — lane: `roles`. It returns the second
    non-plumbing segment of host+path (`_url_segments` already drops the host words and the
    ATS plumbing), so `job-boards.greenhouse.io/scopio/jobs/1` → `1` and
    `il.linkedin.com/jobs/view/123` → `123`: the posting id, not the tenant. `attribution.slug`
    is written from it, but no record in the committed ledger carries an `attribution` dict yet,
    so the damage is latent. `rolecard._tenant` (host + first non-plumbing path segment on
    multi-tenant ATS hosts, the host alone elsewhere, aggregators excluded) is the rule the
    shared-board check needed; adopt it or import it.
144. **One identity group, two employers: the blurb crosses** — lane: `company-intel`.
    `identity_key("AppSec Labs") == identity_key("AppSec")` (`labs` is a stripped suffix), and
    `company_intel.py` deliberately shares a blurb across a group's name-forms — so one
    company's About text serves both cards. `rolecard.cross_check` counts a blurb that names
    another *rendered* employer and not its own (`blurb-names-other`), but the AppSec pair is
    invisible to it (same key). Needs either a declared-distinct list in `identity_facts` or a
    narrower suffix rule.
145. **`matched.seniority` is empty for every row** — lane: `roles` / `classifier`. All 111
    rows carry `''` on 2026-08-25 (`select count(*) from matched where seniority=''`), so the
    column the store defines is written by nothing; the card derives seniority from the
    posting's own text and the title instead (`rolecard.sen_canon`). Either write the
    classifier's verdict into it or drop the column.
146. **Tests reach into `digest`'s private names** — lane: `docs` (test owners). `_text_audit`,
    `_html_audit`, `_path_label`, `_firmo_facts` are imported by `tests/test_units.py`,
    `tests/test_company_intel.py` and `tests/test_registry.py`; `digest.py` re-exports
    `_firmo_facts` from `rolecard` for that reason alone. When 142 lands, retarget the audit
    tests at `build_markdown` and drop the re-export.
147. **BACKLOG numbers 70, 71, 132 and 133 are each used twice** — lane: `docs`. `grep -oE '^[0-9]+\.' docs/BACKLOG.md | sort -n | uniq -d` → `1.`–`15.` (numbered sub-lists inside items, false positives), then the real duplicates `70.`, `71.`, `132.`, `133.`; a citation of "BACKLOG 133" lands on the classifier's `claude -p` item before the registry's "13 active groups read one board" item. Renumber the second block of each (and every citation) in one commit.
148. **`docs/AGENT_BRIEF.md`'s roles paragraph is stale** — lane: `docs`. "Reposts are detected at render time by comparing `posted_date` against `first_seen`" (the ledger records them, `pipeline/roles.py`), "the tags are not stored" (`cloud_state/roles.jsonl` carries a `tags` snapshot, `v: 1`), "105 rows" (111 on 2026-08-25). The render lane row was corrected on 2026-08-25 (disclosed, out of lane); the paragraph was not.
149. **`same_employer` and `blurb-names-other` are heuristics with a known false-positive
    surface** — lane: `render`. Wave 2 measured the registry-wide worst case (every active
    company posting one "Data Analyst") at 45 cross-check issues; after `_SITE_WORDS`, the
    space-stripped comparison, the `X (Parent)` rule and the common-word stoplist the named
    pairs are right, but the rules are lists. A declared-identity source (`identity_facts`)
    would replace them; until then, a false `shared-board`/`title-twin` is a line in the
    mail, never a change to a product.
150. **A failed email stub replaces yesterday's `digests/latest.md`** — lane: `render` /
    `infra`. When `build_markdown` raises, `render_all` ships a stub that names the failure
    and `run.py` gives `mark_sent` no roles (nothing is burned); the relay still mails the
    stub. Whether a reader prefers the stub or yesterday's digest again is a product decision.
151. **39 of the 111 shipped roles keep an aggregator url as their canonical** — lane:
    `roles`. HEAD's BACKLOG 109 damage: a LinkedIn/Indeed card reached `matched` first, so
    the reader's link is the card's. The 21 open ones self-heal on the next sighting
    (`upsert_matched` overwrites `url`; the inherited-copy rule keeps the board's from now
    on); the 18 closed ones keep it in the archive forever. One-shot repair: re-canonicalise
    from `seen_ids` (any non-`discovery-*` id names the board) — or accept it.
    Count: `python -c "import json;print(sum(1 for l in open('cloud_state/roles.jsonl',encoding='utf-8') if any(h in json.loads(l).get('url','') for h in ('linkedin.com','indeed.com'))))"`.
152. **The inline JD fill's wall-clock budget now starts with the whole fetch phase already
    spent** — lane: `roles` (with `jd-text`). `JDFiller.t0` is set at construction, before
    the fetch loop, and classify-once moved the first `maybe_fill` from "after company #1" to
    "after all 862" (~8 min of fetching inside the 25-min `JDFILL_TIME_BUDGET_MIN`). Not
    binding on 2026-08-24 (`jd-fill: 93/153` at 06:07, budget to 06:24) and the fill now runs
    once per role, not per copy — but the headroom shrank quietly. Start the clock at the
    first `maybe_fill`, or construct the filler after the loop.

## From the `infra` lane, 2026-08-25

Record: `docs/sessions/2026-08-24-infra.md`; spec ARCHITECTURE §4/§5. Closed there: 10 (the
two list caches merge by key), 15/60 (base-aware note union), 17, 39, 94, 95, 103, 105 (restore
half), 114, 115, 125 (mechanism gone), 128, 134. Open, with owners:

153. **`pipeline/health.py` writes `stale.json` and `health_baseline.json` with no temp file**
    — lane: shared (`pipeline/health.py:117-122`). `json.dump(data, open(path, "w"))` inside
    `except OSError: pass`; a kill mid-write leaves a truncated baseline, `_load` reads `{}`,
    every board's high-water mark resets to 0 and `regressed-to-zero` can never fire again.
    `pipeline.atomic.write_json` is three lines away. Found by the 2026-08-25 hand-over audit.
154. **`cloud_state/scrape_rot.json` has no reader, so a scrape ERROR reads as `empty` in the
    `Boards` lines** — lane: `scraper` + `ats-fetch`. `fetch_scrape` returns `[]` for
    never-scraped, empty and error-with-expired-carry alike and cannot raise, so `run.py`
    records `status: "empty"` and `health.stale_reason` can never say `fetch-error` for a
    scrape row. The file that carries the verdict (`why: error`, `http`, `error`) is read by
    nobody (`grep -rn scrape_rot` → writer, workflow, two tests). Either `run.py` reads it to
    mark `status: "error"` (and self-heal must then skip scrape rows) or the `Boards` line
    reads the `collect` stamp's `errors=` count beside it.
155. **The two JD cooldowns never see each other, so a failed scrape-source JD is paid for
    twice a day** — lane: `jd-text`. `enrich_scrape_jd` stamps `_jd_attempted` on the cache
    job (7 d); `store.upsert_matched` drops it; `enrich_matched_jd` twelve seconds later finds
    `matched.jd_attempted == ''`, `jdfill.due('')` is True and the same URL goes to the
    Unlocker again (`MATCHED_JD_BD_CAP` 250). Carry `_jd_attempted → jd_attempted` in the
    upsert, or skip URLs the cache already stamped. Also: `enrich_scrape_jd._todo` treats
    only `""` as missing while `enrich_matched_jd` uses `< 300` chars.
156. **Three loaders turn a corrupt `scraped_cache.json` into `{}` and write it back** —
    **Registry half CLOSED 2026-08-26:** `auto_expand._load_cache` and `retry_unreachable.main` report `::error::` and skip the cache write when the file is unreadable (absent stays `{}`). `refresh_scrape_cache.py` is the `scraper` half.
    lane: `registry` (`retry_unreachable.py:154-156` + `:190`, `auto_expand.py:50-54` +
    `:183`) and `scraper` (`refresh_scrape_cache.py:431-436`). A momentarily unreadable
    file becomes an empty cache on the next write. Copy `discovery_daily.py:975-983`'s
    pattern: refuse to write over what could not be read. (The git-conflict path no longer
    does this — `persist_state.s_company_dict` yields to the readable side.)
157. **`mark_sent.py` and `pipeline.run` default to `state/seen.db` (gitignored) while
    `enrich_matched_jd.py` defaults to `cloud_state/seen.db`** — lane: `infra`. The cloud
    always passes `--db`; locally the three tools disagree on which store they mean. One
    default (`cloud_state/seen.db` when it exists) or none.
158. **`test_refresh_shrink_abort_keeps_the_cache_and_stamps_its_reason` is red on origin
    since `f720627` (four consecutive pushes, 2026-08-25)** — lane: `scraper`. Its third
    scenario expects the first ~10 processed rows to include the 5 emptied ones, but
    `refresh_scrape_cache.py:446-448` rotates the processing order by `date.today().toordinal()
    % len(rows)`, so on some dates the budget-cut run never reaches them and `alarm` is not
    `shrink-abort-…` (assert `11 <= 12 and False`). Pin the rotation (monkeypatch the date or
    the offset) inside the test. Until then every push to master is red on that one test.
159. **`pipeline_stages.json` is still read-modify-written in process by two overlapping
    jobs** — lane: shared (`pipeline/stages.py:40-49`, fixed `.tmp` name). `scrape-refresh`
    (00:00, 330-min timeout) and the digest (05:00, its own group) can both stamp; the
    conflict-path half is closed (item 105), the in-process half needs a lock or a per-stage
    file.
160. **`roles*.jsonl` and `seen.db` have exactly one cloud writer, which is why `ours` is
    the right conflict rule today** — lane: `roles` + `infra`. If a second workflow ever
    writes them (BACKLOG 132's retirement of `matched`, or a mark-sent-from-the-relay), add
    a row-level strategy to `persist_state.STRATEGY` first (`roles.reconcile` is the rule);
    the unit guard `test_every_path_a_workflow_owns_has_a_persist_strategy` will not catch a
    second writer of an `ours` path — only a reviewer will.
161. **The relay marks nothing** — lane: `infra` (out of this repo). `mark_sent` records
    intent (BACKLOG 6); the private relay could `PATCH` a `delivered` file back, or the
    pipeline could read the inbox's latest issue hash at 05:00 and re-queue anything unsent.
    Not started; the four relay passes bound the exposure to one bad morning.
163. **A failed `checkout` / `setup-python` still means silence** — lane: `infra`. The
    persist and outcome steps are `if: always()`, but without a checkout there is no
    `persist_state.py` to run: no `last_run.json`, no notice, yesterday's digest re-relayed
    unlabelled. The residual of BACKLOG 6; the only in-job mitigation is a shell fallback
    that curls the notice into the inbox, which would need a token the public repo must not
    hold. Watch for it by absence: a morning with no inbox issue and no notice.
164. **Every Sunday audit starts from row 1** — lane: `infra` + `registry` (restates 38 with
    **CLOSED 2026-08-26** with 38.
    the writer line): `audit_empty_rows.py:280` writes its resume ledger to
    `state/audit_done.json` and `state/` is gitignored, so the 90-minute budget re-audits the
    same head of the list weekly. Own it under `cloud_state/` and add it to
    `audit-coverage.yml`'s `--own`.
165. **`persist_state.commit()` and `outcome()` grew under two attack waves** — lane: `infra`.
    719 lines, `outcome()` 91 and `commit()` 71 — each guard is a branch with a one-line
    why, which is right for a file that must never lose a night, but it no longer reads on
    one screen. Split `commit()` into `stage → push loop → conflict` helpers and `outcome()`
    into `decide → write → publish`, behind the existing 20 guards, on a quiet day; no
    behaviour change.
166. **An ops report over the last N days, and a skill that reads it** — lane: `infra`
    (user request, 2026-08-25). Everything needed is already committed, just not compiled:
    `git log -p --since=N.days -- digests/latest.md` is a day-by-day archive of every audit
    block (scanned / failed / fetched / Israel-matched / accepted / new / LLM calls / Boards
    changed / Company intel / Roles / Stage order with the scrape's and the JD layer's
    counts); `git log -p -- cloud_state/pipeline_stages.json` is what each nightly stage did;
    `cloud_state/source_health.json` what discovery returned; `cloud_state/last_run.json`
    the failed steps; bot commits tagged `(row-merged)` are the conflict nights; `gh run
    list -R AnalystJobsIL/pipeline` the durations and red runs; `gh issue list -R
    AnalystJobsIL/inbox` when the mail went out. Bright Data spend is the one number only in
    the run log (`discovery_daily.report_bd_spend`). Build `ops_report.py --days N` (root,
    infra-owned, offline except `gh`; a `docs/gen_modules.py` line) that compiles these into
    one markdown table per day and per flow step — intake → registry → fetch → enrich →
    classify → roles → render → deliver — with, for each: discovered, spent, failed, fell
    back (`llm_failed_fallback`, `bd-unavailable`, carried scrape rows, row-merged nights),
    added (new active rows, newly covered companies), sent (`new:` per day, inbox issue
    times); then a Claude Code skill (a SKILL.md under .claude/skills/ops-review/) that runs the
    script FIRST and only interprets its output (an agent must never re-derive the numbers
    by hand — §8), ending with the three things most worth a session, each pointing at a
    BACKLOG item. Half a day; the interim prompt that does it by hand is in
    `docs/sessions/2026-08-24-infra.md` ("Ops review by hand").
167. **A company named "Tel Aviv" in the mail** — source FIXED 2026-08-25 (`0870d87`,
    **Registry half CLOSED 2026-08-25 (`registry`, `bebbee9`):** row parked `redundant: not a company …` (terminal; `--explain` shows no pool), 145 cards dropped from `scraped_cache.json`. The 7 ledger roles remain `roles`'.
    `e82f467`); residue re-filed for `registry` + `roles`. As first filed this pointed at
    the wrong file: the two mailed roles did NOT come from the discovery cache but from an
    ACTIVE registry row — `companies.csv:1212` `Tel Aviv,scrape,,https://jobs.secrettelaviv.com/,true,… listing-hunt 2026-08-24: verified 145 IL via jobs.secrettelaviv.com`.
    Chain: a Telegram post with no company line (`t.me/secretfinancejobs/5348`) → `parse_post`
    emitted the CITY as the employer → queued → `listing_hunt` resolved it onto secrethunter's
    city board, which was not on `aggregators.HOSTS`, and activated it (`registry_health
    --explain "Tel Aviv"` → `tenant_is_this_company = True`: a company named after its
    host's city defeats every identity primitive) → 145 cards in `scraped_cache.json`, 7
    open roles in `cloud_state/roles.jsonl` (8.6% of the 81-role board), 2 in the mail, a
    blurb about Alma. Fixed at intake: the parser skips the dated shape, the Telegram path refuses a
    place name at both the cache and the queue, the host is an aggregator (so `run.py`
    skips the row from the next run).
    **Still to do — `registry`:** park or delete row 1212 (parking alone re-arms it: its
    note matches the re-check pools and the hunt will "verify" it again — the host now being
    an aggregator is what stops that); drop the `Tel Aviv` key from `scraped_cache.json`;
    remove the queue entry. **`roles`:** the 7 ledger records are never looked at again once
    the row is skipped, so they never close — close them explicitly.
    Reproduce: `grep -n "^Tel Aviv," companies.csv`; `grep -c secrettelaviv docs/index.html`.
168. **A location that swallowed the title's tail** — lane: `scraper` (+ `render` for the
    card). Gett: `**Experienced Product Analyst** … 📍 ced Product Analyst Tel Aviv` in the
    same digest — the DOM extraction split the card text at a fixed offset. Reproduce:
    `git show 58212df:digests/latest.md | grep -n "ced Product Analyst"`; the cached card is
    in `scraped_cache.json` under `Gett`.
169. **Location and employment type glued into a Comeet title** — lane: `scraper`.
    Modellama: `**Data Analyst Raanana Full-time**` beside a clean `Data Analyst` from
    LinkedIn for the same role (so the roles ledger also sees two titles for one posting).
    Reproduce: `git show 58212df:digests/latest.md | grep -n "Raanana Full"`.
170. **The mutation gate cannot finish any more: 108 mutations × the whole suite** — lane:
    **CLOSED 2026-08-25 (`registry`, `701d1a9`):** derived per-record test subset + full-suite fallback (verdicts unchanged), baseline-red exclusion, `--jobs 4`, `--catalogue`; local sweep of 124 records finishes — see `docs/sessions/2026-08-25-registry.md` for the CI time on the first push.
    `registry` (owns `tools/mutate.py`) + `infra` (owns `tests.yml`). `tests.yml`'s
    `mutation-gate` job (`timeout-minutes: 45`) has been `cancelled` at exactly 45 min on
    every push since `f720627` (2026-08-25 01:00, four runs before the infra push; last green
    `60fae33`, 35 min). `run_one` (`tools/mutate.py:115`) runs `python -m pytest -q` — the
    entire suite — once per mutation, and the guard job now measures the suite at 55 s on
    the runner: 108 × 55 s ≈ 100 min before any overhead, so no timeout fixes it. The
    infra lane's git-backed guards already skip under the archive export (`_needs_git`); the
    remaining growth is the roles/render/classifier fixtures added 2026-08-24/25. Fix in
    `mutate.py`: run only the tests that can see a registry mutation (`tests/test_registry.py`
    plus the `tests/test_units.py` guards each catalogue entry names as its killer, `-k`),
    and keep one full-suite pass per push in the `guard` job. Until then every push is red
    on this job and `python tools/mutate.py --all` is a local-only check.
177. **`auto_expand` buries real employers as `scanned; no open Israel roles now` when the
    **CLOSED 2026-08-25 (`registry`, `a2a2f94`, `63d9822`):** aggregator seeds skip `resolve_deep` and are deferred (never parked) on a rotation key; `resolve_llm` has the SerpApi→DDG→unlocker ladder (`LLM_BD_SEARCH_CAP` 5/run) and is asked only with a page in hand; the 28 buried rows were un-addressed (`--clear-agg-urls --apply`, `url-cleared`, hunt-owned). Live control: Upwind Security → comeet 49.004, 51/15 IL, one call, DDG only.
    seed is an aggregator URL, and burns 20 evidence-free `claude -p` calls a day doing it**
    — lane: `registry`. Five consecutive `auto-expand.yml` runs (08-23 → 08-25) printed
    `resolved 0 (LLM-cracked 0), empty 10, unreachable 0, deferred 240`. 337 of the 341
    drainable queue names are seeded with `linkedin.com/jobs/view/…` or the
    `secrethunter.io/jobz/<id>` JS shell; `resolve_llm._gather` starts with zero candidate
    pages for an aggregator seed (`resolve_llm.py:125-131`) and asks SerpApi (429 until
    2026-09-01), so every LLM shot returns `None` and `auto_expand.py:170-172` writes an
    `empty` row with the shell as its board — 44 rows now: ctera, Houzz, yad2, Upwind
    Security, RISCO Group, Tonic Security, Agilite … Only 7 of 70 aggregator-seeded rows
    were ever rescued by `listing_hunt`. Cheap guard: never write an `empty`/`unreachable`
    verdict when `_is_agg_url(url)` — defer instead, and skip the LLM tier while SerpApi is
    down. The names funnel — the stated point of intake — has added zero active companies
    for at least five runs while the queue grew 74 → 355. Reproduce:
    `gh run view <auto-expand run id> -R AnalystJobsIL/pipeline --log | grep -E "unresolved:|=== resolved"`.
178. **`auto_expand` ignores the `slug` the LinkedIn bridge already writes** — lane:
    **Built, OFF by default 2026-08-26 (`registry`):** `_site_from_slug` reads the `about_website` link off the public LinkedIn company page and, under `AUTO_EXPAND_SLUG_SEED=1`, a real site replaces the aggregator seed for tier 1. Measured from the dev machine: fiverr / riskified / upwind-security all return no link (guest page), and every GET competes with discovery's LinkedIn budget on the runner — so it stays inert until the fetch is worth it. Filed as-is; enabling is one env line.
    `registry`. `research_companies.json` entries carry `slug` (`nishapro`,
    `shavit-software`, `dialog-recruiting`) — the one non-aggregator seed intake can
    produce (`linkedin.com/company/<slug>` → the company's own site), and `auto_expand.todo`
    never reads it. Adjacent to 2 and 177.
179. **A deliberately skipped source reads as a dead one** — lane: whoever holds
    `pipeline/sources.py` (shared plumbing). `linkedin-targeted` records a zero on every
    budget-starved run (correct), but `stale()` cannot tell "skipped: no budget" from
    "died": from 2026-08-26 the mail's *Sources not producing* line says
    `linkedin-targeted: nothing for 3d` and counts up daily until the pool resets on
    2026-09-01. Proposed: `record()` accepts a per-key reason (`{"linkedin-targeted":
    {"count": 0, "skipped": "budget"}}`) and `stale()` prints it instead. Same family as 3.
180. **Intake has no line of its own in the mail** — lane: `infra` (+ `render` for the
    line). `pipeline/stages.ORDER` has no `discover` stamp, so the mail shows source deaths
    and nothing else: the per-source yield, `blocked=`, the queue depth (170) and the BD
    pool percentage live in the step log only. Proposed: a `discover` stage stamped by
    `discovery_daily.main()` with `new_companies`, `queued`, `queue_depth`, `bd_pct`,
    `blocked`, and one `- **Intake:**` line rendered from it.
181. **`discovery-indeed` descriptions can never be fetched inline** — lane: `jd-text`.
    `jd-fill … discovery-indeed http-401 17` on 2026-08-25: `il.indeed.com/viewjob?jk=…`
    answers 401/403 to any non-browser client (verified on two cache URLs). Meanwhile
    `indeed_normalize` already stores the card snippet — 82 of 82 cached Indeed jobs have a
    `description`, mean 164 chars. Mark the platform `unfillable` inline (the counter
    exists) or route it through the Unlocker under a cap; today it spends a request per job
    to replace text we hold with nothing.
182. **Two mutation cells for the 2026-08-25 discovery guards** — lane: `infra`
    (`tests/mutations.json`). `M7-constant-drift`: drop `"secrettelaviv."` from
    `aggregators.HOSTS`. `M2-gate-inversion`: change `linkedin_search`'s final `if why:` to
    `if why and out:` (restores the Haifa blind spot). Each is a 109th/110th full-suite pass
    per push, so the gate's owner decides.
184. **`fetch_discovery` judges the display name only; the slug it has in hand says
    "recruiting"** — lane: `ats-fetch`. `pipeline/fetchers.py:856` is
    `elif _is_rec(j.get("company")):` while the same dict carries `company_slug`
    (`dialog-recruiting`). `is_recruiter(name, slug="")` takes it since `70dba5f`; the
    cache write now drops such cards, so this is belt-and-braces for cards written by an
    older run. One-line fix: `_is_rec(j.get("company"), j.get("company_slug", ""))`.
    Same for `registry_health.py:614` (`--explain` prints the name-only verdict, so it says
    `is_recruiter = False` for a name the intake gate refuses) and `auto_expand.py:122`
    (item 178).
185. **A lettered decoration header still shifts a Telegram post by one line** — lane:
    `discovery`. `parse_post` strips leading lines with NO letters ("🔥🔥🔥"); a header like
    "🔥 HOT JOB 🔥", "New!" or "#דרושים" survives the strip, the job title becomes the
    employer and the company becomes the city. Not observed in any of the six channels
    (the 2026-08-25 rehearsal constructed it); the comment above the loop already says it
    fires the first time a channel decorates. A date-anchored parse (title = the line
    three above the date) would cover the dated shape.
186. **A Telegram post with company present and CITY missing is skipped** — lane:
    `discovery`, documented limitation. `parse_post` cannot tell title/city/date from
    title/company/date, and the module's contract is "skipped and counted, never guessed";
    0 of 229 cached cards had the shape, 2 of 320 live posts had the other one.
187. **`aggregators._AGG_RX` fires on any `//` inside a path** — lane: `discovery`.
    `https://acme.com/x//secrettelaviv.com` is an aggregator and
    `careers.acme.com/?ref=jobs.secrettelaviv.com` is not; pre-existing, theoretical, noted
    by the 2026-08-25 review. The `(?://|^)` alternative should anchor on the scheme.
188. **A corrupt `research_companies.json` is silently replaced by this run's additions** —
    lane: `discovery`. `discovery_daily.py:1109` does `except Exception: research = []` and
    then writes `added` over the file; `discovery_telegram._load_json(..., [])` collapses
    absent and unreadable the same way. The job cache already distinguishes ABSENT from
    CORRUPT (`_load_cache` / the `::error::` path) — the queue needs the same guard, or a
    half-written file (both steps are continue-on-error and runs do get cancelled) deletes
    1,500 names and prints "N new companies queued, 0 already waiting". Pre-existing; found
    by the 2026-08-25 rehearsal.
189. **Three loose ends from the 2026-08-25 attack waves, none load-bearing today** — lane:
    `discovery`. (a) `discovery: rejected N … agencies` counts POSTINGS, not names (27
    "place names" were 2 names in the rehearsal) — say "postings" or count distinct.
    (b) On the corrupt-cache path the line `cache: 0 this run -> 0 total (0 carried)` prints
    right after the `::error::` that says the file was NOT touched. (c) The blank-tail exit
    after cards (`linkedin_search`, `if out: break`) is the one silent exit that is also
    indistinguishable from a soft rate-limit; `blank=` on the sweep line is the only tell.
    Also for `infra`: `test_a_blank_page_does_not_disarm_the_everything_is_billed_alarm`
    slices the source between `elif ok:` and `if not ok or`, a window that now holds the
    `linkedin_blocked` branch too — still green, but no longer isolates what it names.
183. **`bd_spend_this_month`'s zone pinning is dead code, and the API's real `cost` is
    discarded** — lane: `discovery`. `zone/cost` keys its reply by CUSTOMER id
    (`{"hl_b9b328bb": {"custom": {"cost": 3.846, "reqs_unblocker": 1649, "reqs_serp": 915}}}`),
    so `zone in d` (`discovery_daily.py` ~line 631) is never true and the "arbitrary one"
    fallback its own comment forbids is the path always taken — correct today only because
    there is exactly one key. The reply also carries the accrued dollar `cost` (3.846) while
    `report_bd_spend` prints a projected $2.39 from list prices. Verified live 2026-08-25;
    left as-is because a second zone is needed to test the fix.
162. **`check_invariants.POOL` still differs from `pipeline.verdicts.TOKENS`** — lanes:
    **CLOSED 2026-08-25 (`registry`, out-of-lane one-liner disclosed):** `TOKENS` gained `url-cleared`/`url-flagged`; `test_the_three_copies…` now asserts `POOL − TOKENS == ∅` and 0 parked rows invisible to audit/deep. Remaining deliberate gap: `HUNT_POOL` lacks `dark-triage`.
    `registry` (owns the deliberate gap, pinned by `test_the_three_copies…`) + `infra`.
    Measured 2026-08-25: `url-cleared`/`url-flagged` are in-pool for the gate and
    `listing_hunt` and out-of-pool for `audit_empty_rows`/`deep_validate`/`registry_health`
    → 10 orphans by `verdicts.in_pool`, 1 by the gate. Deriving `POOL` from `TOKENS` was
    tried and reverted this session because the registry lane pins all three copies on
    purpose; the fix is `TOKENS` gaining the two strings (shared plumbing).

## From the `registry` lane, 2026-08-25

Record: `docs/sessions/2026-08-25-registry.md`; spec: `ARCHITECTURE.md` §2/§3. Closed by
this pass: **170, 104, 177, 44, 45, 162**; rows for **76, 133 (same-identity half), 167
(registry half)**; 84 measured (0 reachable). Filed:

190. **The 02:30 chain is not in `registry_health.pools()`** — lane: `registry`. `bd_rescue`
    and `retry_unreachable` both activate and both select parked rows on the `unreachable`
    token (retry minus terminal since 2026-08-25), but neither exports an `in_*_pool` and the
    ownership matrix does not list them, so `orphans()` cannot credit a row to them and
    `pool_floor` cannot watch them. Extract `in_retry_pool(r)` (shared by both, imported by
    the mirror), like the five others.
191. **`no-url` is a triage mode `check_invariants.TRIAGE_MODES` does not know** — lane:
    `infra` (the list at `check_invariants.py:71`). `triage_dark` writes it (`triage_dark.py:158`)
    and `listing_hunt` handles it (`seed_is_bad`), but every registry workflow prints
    `14 rows carry a truncated/unknown triage mode … no-url` daily — a false warning that
    will mask a real truncation. Measured 2026-08-25: 14 rows, 9 of them in the hunt pool.
192. **`BD_MONTHLY_BUDGET` is 5,000; the operator's ceiling from 2026-09 is 4,500** — lane:
    `discovery` (`discovery_daily.py:610`) + `infra` (the env in the workflows). Decision
    2026-08-25: this month's overage (5,553 measured, 6,886 projected ≈ $2.39) is accepted;
    next month must not pass 4,500 for the whole project. The registry's new paid rung is
    `LLM_BD_SEARCH_CAP=5`/run (≈300/month, 7% of 4,500) and is counted separately from
    `DEEP_BD_SEARCH_CAP` (per process, 150).
193. **`check_invariants.PLATFORM_HOST` has no `eightfold` / `phenom` entry** — lane: `infra`.
    Since 2026-08-25 two active rows are on those platforms (Qualcomm `/api/pcsx/`, GE
    HealthCare `/widgets`); check C2 cannot fire for them. Tenant hosts vary, the path does
    not — key the pattern on the path (BACKLOG 76's second half).
194. **Four parent/subsidiary pairs still scan one board under two names** — lane:
    **CLOSED 2026-08-26 (`registry`, operator decision):** Splunk (Cisco), HP Indigo, Habana Labs (Intel), VMware (Broadcom) parked `alias-of <parent>`; roles were never separable at the board and none of the eight rows had an open role. 865 → 861 active, orphans unchanged.
    `registry`, needs a decision per pair: Cisco / Splunk (Cisco), HP / HP Indigo,
    Intel / Habana Labs (Intel), Broadcom / VMware (Broadcom) — all Workday, identical
    `api_url`, 0 open roles on either row today. Either the subsidiary row becomes `alias-of`
    the parent (its roles were never separable at the board) or it keeps a distinct
    `display-name` once that column exists (items 50/61). Enumerate with the one-liner at 133.
195. **`tests.yml`'s `mutation-gate` comment still says "~15 minutes" and the `guard` job
    is red on BACKLOG 158** — lane: `infra` + `scraper`. The harness now excludes that
    baseline-red test from every verdict and prints it as a `::warning::`, so the gate is
    honest about it, but the `guard` job itself stays red until 158 is fixed. Keep
    `timeout-minutes: 45` as the backstop (a build where every mutant survives is ~35 min
    and fails anyway).
196. **`resolve_llm` still asks SerpApi first** — lane: `registry`. When the quota resets on
    **Measure first (2026-08-26):** the `dfer … no-candidates` vs `llm-none` counts in the 08:00/20:00 logs over the week of 08-26 → 09-01 are the DDG hit rate; reorder only if DDG ≥ 60 %.
    2026-09-01 the ladder spends 250 free searches in ~6 days at 20 entries/run (two runs a
    day), then falls back to DDG for the rest of the month. Fine, but the order could be
    DDG-first with SerpApi as the tie-breaker for names DDG cannot find — measure the DDG
    hit-rate on the runners from the `dfer … no-candidates` counts first.
197. **`url-cleared` costs the `scanned; no open` token its place under the 220 cap** — lane:
    `registry`. On the 28 un-buried rows the oldest segment is `scanned; no open Israel roles
    now`; after triage + hunt + one deep-validate stamp it is evicted (headroom 32 chars,
    every deep-validate verdict is 38–53). Only `validate_empty` keys on it, and those rows
    have no address to validate, so the loss is nil today — but a pool that keys on an
    eroding token is the shape that hid 87 truncated modes once. Durable fix: key the
    Sunday cross-validation on state (`active=false` + an http address + no verified stamp),
    not on a note substring. Measured by the wave-1 pools attacker (14-night simulation).
198. **`Sckipio`'s "comeet 87.00C is Scopio Labs' board" lives only in a note segment** —
    lane: `registry` (+ shared `identity_facts`). The 94-char `url-cleared` segment is the
    longest on the row and is evicted after four nights of routine stamps; the two pools
    that keep the row both activate. A NEGATIVE declaration (`identity_facts`: this
    tenant is NOT this company's) is the durable form; today the table only declares what
    a company owns.
199. **An address-less (`url-cleared`) row pays one unlocker search on every DDG-empty
    **Measure first (2026-08-26):** the hunt's BD count in the mail over the same week for the 38 address-less rows; escalate to 192 only if it moves the month.
    hunt night** — lane: `registry`. `hunt_one` with an empty seed goes `ddg` →
    `google_via_unlocker` when `len(cands) < 2`; bounded by `DEEP_BD_SEARCH_CAP` in the
    hunt's process. 29 such rows today. Cost, not correctness; count it against the 4,500
    ceiling (192) if the hunt's BD line in the mail grows.
