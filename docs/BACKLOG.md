# Backlog — what is known-wrong and not yet fixed

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
3. `_REQ_HEADER` in `seniority.py` is dead code — `_desc_is_ml`'s docstring claims it reads
   the requirements section but it uses `_ROLE_START`, which lands on boilerplate 22% of the
   time and cuts the requirements past the 1400-char LLM window.
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
67 root scripts, 10 workflows, 27 root scripts invoked by a workflow (re-counted
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
   nothing on the same day. First moves: `DEEP_BD_SEARCH_CAP` defaults to 150 searches per
   run and is the largest single lever; then a shared pre-flight budget check the six
   non-discovery spenders also call, since `discovery_daily` throttling alone just makes it
   absorb everyone else's overrun.

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

## From the registry lane, 2026-08-24

Found while fixing the re-check pools. Each of these is **outside the `registry` lane's
write list**, which is why it is a proposal and not a commit. Ordered by what it costs today.

1. **One re-check pool definition** — lane: `docs` (or whoever next touches shared
   plumbing). `pipeline/verdicts.TOKENS` is supposed to be the single source, and there are
   still three copies: `TOKENS` (18 tokens), `listing_hunt.main()`'s inline regex (17), and
   `check_invariants.POOL` (18). `url-cleared` and `url-flagged` are in both inline copies
   and **missing from `TOKENS`**, so the 57 rows carrying one are invisible to
   `audit_empty_rows` and `deep_validate`. The fix is two lines in `pipeline/verdicts.py`:

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
   `defunct / domain-dead / duplicate of / redundant / recruiter` and **omits `alias-of`**,
   which is why `audit_empty_rows` and `crack_walled` had alias rows in *activating* pools
   (fixed 2026-08-24 by spelling the exclusion out in each tool, which is now the FOURTH
   copy — `listing_hunt` and `deep_validate` already had their own). Adding `"alias-of"` to
   that tuple lets all four be deleted. `registry_health.TERMINAL` is the fifth and would
   go too.

3. **Registry alarms in the daily mail** — lanes: `infra` (`pipeline/run.py`) + `render`
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
