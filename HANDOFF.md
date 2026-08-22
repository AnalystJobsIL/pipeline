# Session handoff — 2026-08-22

Read `ARCHITECTURE.md` first (system model, invariants, runbooks). This file is the
"what just happened / what to watch / what's next" layer on top of it.

## 1. What changed in the last two sessions (2026-08-21 → 22)

**Infrastructure**
- Migrated from the private personal repo to **public `AnalystJobsIL/pipeline`** (unlimited
  free Actions minutes). Anonymity rules are in the gitignored `CLAUDE.local.md` — read it
  before committing or dispatching anything. The pre-migration repo is kept as a private
  archive with all workflows disabled; it is wired locally as the `backup` remote (see
  `CLAUDE.local.md` for its address — deliberately not named in a public file).
- Email now relays through the **private `AnalystJobsIL/inbox`** repo (issue + mention),
  content-hash deduped.

**Coverage: 446 → ~716 active verified companies.** Recovered along the way: Intel, Cisco,
Splunk, Nike, Merck, Dell, OpenText, Qualcomm, Google Israel, Intuit, SuperPlay, Verint,
Glassbox, KELA, Legit Security, Entro, Hunters, Palo Alto Networks (149 IL), VAST Data,
WalkMe, Cloudinary, Port.io, Miggo, Thales. Roughly **1,400+ Israel jobs** entered scope.

**New capabilities**
- `scrape_universal.py` now escalates through **5 strategies** (XHR/state capture → DOM
  cards → heading/class-hinted groups → position-links → **LLM extraction**). This is what
  cracked Google, Intuit, SuperPlay, Legit, Entro.
- `fetch_oraclehcm` native fetcher (Dell, Verint, onsemi).
- Telegram discovery (`discovery_telegram.py`, 3 channels), JD enrichment
  (`enrich_scrape_jd.py`), candidate probing (`probe_candidates.py`), listing hunting
  (`listing_hunt.py`), walled-ATS cracking (`crack_walled.py`), liveness scanning
  (`scan_dead_domains.py`), and the git-layer merge (`merge_csv_rows.py`).
- Claude classification is **live** (`CLAUDE_CODE_OAUTH_TOKEN` set); verdicts cached per
  `company|title`.
- **Firmographics layer** (2026-08-22, see ARCHITECTURE §7): structured company profiles
  (sector/stage/size/employees/founded/business model) for all ~718 profileable companies,
  researched via `claude -p` + web search, cached in the **local** `state/seen.db`
  (export: `state/firmographics.json` — note the split-store trap, §7). Self-maintaining:
  Windows scheduled task `IsraeliJobs-Firmographics` runs `run_firmo_chain.cmd` every 6h
  (research → LinkedIn employee fill via Bright Data → web verify → export), and
  `pipeline/run.py` researches ≤5 new board companies per digest run.
  `company_type_analysis.py` joins profiles with matched jobs → "what does each TYPE of
  company ask for" (`out/company_type_analysis.{json,md}`). Side-finding: several listed
  companies are dead/absorbed (Alike Health, Syte, Sckipio, SimilarTech, NanoLock) — their
  rows are NOT auto-parked; and discovery leaks job-title junk as company names
  ("AppSec", "my team") which firmographics research correctly refuses.

## 2. Things that will bite you (learned the hard way this session)

1. **Silent exclusion is the dominant bug class here.** Every serious defect found was a
   row quietly leaving a re-check pool: a verdict string missing from an allowlist, a
   `"marker" not in note` filter with no staleness escape, or a note overwrite that erased
   another tool's token. None of them error. See ARCHITECTURE §2 "verdict-string rule".
2. **A mass-zero result is a broken run, not a measurement.** A hunt cycle once reported
   0/501 because two sync Playwright instances collided silently. Strip those verdicts and
   re-run; never let them commit.
3. **Two concurrency layers.** In-process (re-read before every write) *and* git-layer
   (`merge_csv_rows.py`). A 3.5-hour cycle was discarded because only the first existed.
   Heavy local pushes during a long cloud run used to destroy it; now they don't.
4. **Search results will hand you another company's board** — and it verifies, with real
   jobs. `_slug_matches` guards it. But note the inverse: CyberArk→PANW and Imperva→Thales
   looked like false matches and were actually **real acquisitions**. Check before "fixing".
5. **DuckDuckGo is blocked from this developer machine** (returns nothing) but works on
   GitHub runners. Local resolution work needs the Bright Data path
   (`deep_validate.google_via_unlocker`). SerpApi quota resets **2026-09-01**.
6. **Never overwrite a file you didn't read.** `pipeline/aggregators.py` already existed and
   held `fetch_serpapi_google_jobs`; creating a same-named module destroyed it silently
   (restored). The tooling warned; the warning was missed.
7. `python -m pipeline.run` with `--only`/`--limit` now writes `out/docs-preview/`, not the
   published board. Several root scripts have **no `__main__` guard** — importing them runs
   them (`merge_research.py` rewrites state on import).

## 3. What is running, and when (UTC)

| time | workflow | notes |
|---|---|---|
| 00:00 | scrape-refresh | daily (was Mon/Thu); JD carry-forward; rot-parking |
| 02:30 | retry-unreachable | Bright Data retries |
| 05:00 | **daily-digest** | discovery → telegram → liveness scan → probe → JD-enrich → fetch → classify → persist → publish |
| 05:45 / 08:30 | inbox relay | the email |
| 06:00 | self-heal | re-resolve rotted boards |
| 08:00 / 20:00 | auto-expand | drain resolution queue |
| 14:00 | listing-hunt | + walled-ATS re-crack (daily) |
| Sun 04:00 | audit-coverage | wayback, empty cross-validation, full re-audit, liveness, re-crack |

## 4. Open items — highest value first

1. **~286 rows marked `no ATS detected`.** The daily hunt cycle works through these. Expect
   a slow trickle of recoveries; each one that fails 14 days running is genuinely dark and
   is covered only by the discovery nets.
2. **Phenom / Eightfold / iCIMS / SuccessFactors** — no native fetchers; they're read via
   the browser scraper when a listing URL is known. If any platform starts appearing 3+
   times in new discoveries, write a native fetcher (ARCHITECTURE §6 recipe).
3. **`CLAUDE_CODE_OAUTH_TOKEN` may expire.** Symptom: `LLM calls this run: 0` with a large
   `llm_failed_fallback` count in the digest audit. Re-run `claude setup-token` and reset
   the secret (helper: `israeli-jobs-private-notes/Set-Claude-Token.cmd`).
4. **SerpApi exhausted until 2026-09-01.** `audit_empty_rows` reserves 50 calls; resolution
   quality is degraded until then (DDG + Bright Data still work).
5. **Board/UI work** lives in a parallel session: `pipeline/digest.py`, `roleprofile.py`,
   `company_profiles.json`, and a firmographics POC (`pipeline/firmographics.py`). Those
   files are render-side; coordinate before editing them.
6. **Never-yet-exercised in cloud:** `cloud_state/candidate_probe.json` and
   `scrape_rot.json` are created on first write (both workflows `git add` them), and
   `merge_csv_rows.py` only fires on a push conflict. Verify they appear after the first
   full day; their absence after 2026-08-23 means the wiring failed.
7. **CI conflict-recovery clobbers `cloud_state/seen.db` (found by adversarial audit
   2026-08-22, cross-workflow — needs the workflow owner).** Every workflow's conflict
   branch does `git reset --hard origin` then copies back its **checkout-era**
   `cloud_state/` wholesale, row-merging only `companies.csv` — so a run that conflicts
   hours after checkout silently reverts every `seen.db` row (sent/matched/llm_cache/
   firmographics/firmo_failed) committed by other workflows in between; last-writer-wins.
   Observed: a "row-merged state" commit fired within an hour of the mechanism shipping.
   Damage today is bounded (firmographics self-heals at 5 calls/run; sent-table reverts
   can re-email roles). Proper fix: merge seen.db at the table level (or copy ONLY the
   artifacts this workflow owns), not a wholesale directory copy.

## 4b. Overnight-readiness fixes applied 2026-08-22 (pre-flight audit)

- `daily-digest` timeout **60 → 150 min** (discovery polling alone can take 45 min; a
  timeout cancels the job so persist+publish never run and the whole run is discarded).
- The git-conflict merge branch now **preserves every artifact**, not just `companies.csv`:
  `git reset --hard` was destroying `cloud_state/seen.db` (which would re-email every role),
  caches and digests. It also no longer exits 0 having pushed nothing.
- `listing-hunt` budgets rebalanced (hunt 280→200 min) so the new daily re-crack step has
  headroom; `crack_walled` gained `CRACK_TIME_BUDGET_MIN`.
- `scrape-refresh` sets `SCRAPE_LLM=1` and now actually installs the Claude CLI (strategy 5
  was silently unreachable there).
- `enrich_scrape_jd`'s 7-day cooldown stamp now survives the nightly cache rebuild even when
  enrichment failed (it was re-spending Bright Data calls on the same dead URLs every night).
- **All 14 `companies.csv` writes are now atomic** (`pipeline/atomic.py`, temp+`os.replace`).
  Previously a process killed mid-write inside a `continue-on-error` step could commit a
  truncated registry.
- `docs/index.html` / `archive.html` are now staged by the digest (the committed copies had
  gone stale).

**Known, accepted:** five scheduled workflows share the `repo-state` concurrency group, so a
long Sunday run can cause a queued run to be superseded. Every job is idempotent and
self-draining, so this costs a cycle, not correctness — but it's why a run can vanish with
no error.

## 4c. Ten-agent audit, 2026-08-22 — what it found and what was fixed

Ten parallel read-only audits (extensibility, discovery, fetch layer, classifier, store,
scraper, secrets, observability, testability, duplicated knowledge). Highlights:

**Fixed — these were actively corrupting data:**
- `discovery_daily.py` **truncated** the shared discovery cache instead of merging, deleting
  every Telegram-sourced job each morning (79 verified roles lost 2026-08-21, unrecoverable).
- 147 board rows were attributed to the **wrong employer** (LinkedIn-scrape incident);
  purged along with the poisoned `sent` rows that would suppress them under the real one.
- The scraper stamped `country_code="IL"` on everything, which makes `israel.is_israel_job`
  skip its real check — Wiliot shipped roles in Kyiv/Dallas/Portugal as Israeli. Now `""`.
- `job_id` fell back to the listing URL, so **21 companies shared one dedup key** and could
  never report a new role again after the first digest. Now hashed per role.
- `_DESC_ANALYTICS`/`_DATA_ANCHOR` had a trailing `` after PREFIX alternatives, so
  `analytics`, `dashboards`, `stakeholders`, `experiments`, `analyze` **never matched**.
  This is the likely cause of the 91% LLM rejection rate; 367 stale NO verdicts invalidated.
- Re-check pools had drifted (15 tokens vs 7) leaving **64 companies invisible to two
  pools**. Consolidated into `pipeline/verdicts.py`.
- Hebrew seniority `ראש צות` was a typo (one vav) matching nothing.
- `jazzhr` returns `[]` by design but wasn't exempt from `empty-board`, so it has been in
  `stale.json` forever with self-heal retrying weekly.

**New guard rails:** `tests/test_units.py` (41 assertions, ~0.5s, every one a shipped bug),
`check_invariants.py` (blocking pre-commit gate in the digest), `pipeline/platform_check.py`
(exposes silently half-wired ATS platforms), `.github/workflows/tests.yml` (runs on push,
no continue-on-error).

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

## 4d. Infra inputs from the firmographics workstream — for the robustness/expandability phase

What building §7 (and three adversarial-review waves over it) revealed about the
infrastructure itself. Complements §4c's backlog; ordered by leverage.

1. **One state layer, not two.** The local/cloud split (`state/` vs `cloud_state/`) forced
   every firmographics consumer to care *which* seen.db it reads, and open item 7 exists
   because sqlite binaries can't git-merge. Direction: keep sqlite as a per-machine cache
   and make the *committed* artifact a text export per table (JSON/JSONL — diffable,
   row-mergeable with the `merge_csv_rows.py` pattern), or move shared state off git
   entirely. Whatever the choice, "who owns which table" should be declared in one place.
2. **Retire `companies.csv` as a database.** 20 writers, a state machine encoded in prose
   verdict strings, six allowlist pools that must be updated in sync (the documented #1 bug
   class), plus literal duplicate rows (Datadog/MongoDB/Elastic twice) and alias rows
   (Meta/Meta Israel — §4c item 5). A registry table with an explicit state enum +
   transition log would delete the entire "verdict-string rule" hazard category.
3. **One identity layer.** `_norm_company` existed but nothing used it for keys — that gap
   alone produced 9 double-researched companies and 3 wasted run.py budget slots per digest.
   Normalized identity (plus an explicit alias map for the Meta/Meta-Israel class) should be
   THE key in every store, join, and dedupe — not a per-consumer patch, which is what the
   firmographics fixes are today.
4. **A single automation inventory.** Jobs now live in three schedulers: GitHub Actions
   crons, the Windows scheduled task (`IsraeliJobs-Firmographics`, 6-hourly), and whatever a
   session runs by hand. Nothing lists all three; SCHEDULING.md covers only CI. One table
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
   its own caps and none metered centrally. Extending §4c's `metrics.jsonl` idea with
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

## 4d. Honest state of the infrastructure — READ BEFORE ADDING ANYTHING

**It is sprawling, and that is the top thing to fix next.** Numbers, not adjectives:
62 root scripts, 10 workflows, 19 scheduled entry points, and **23 separate tools whose job
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

**Legacy / one-shot / superseded** (safe to delete after checking imports — several are
imported for their regex tables, which is itself the problem): `resolve_any`,
`resolve_parallel`, `resolve_unknowns`, `probe_ats`, `detect_ats`, `scrape_jobs`,
`bigtech_capture*`, `ms_capture`, `capture_bodies`, `gen_test_board`, `shot_*`,
`ingest_research`, `merge_research`, `probe_expand`, `verify_jsearch`, `validate_bd`,
`recheck_suspects` (the only clearer of `empty-but-suspect`, and on no schedule).

### The consolidation plan for the next session, in order

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

### Guard rails that now exist — keep them working
`tests/test_units.py` (41 assertions, every one a shipped bug), `check_invariants.py`
(blocking gate before the digest commits), `pipeline/platform_check.py`,
`.github/workflows/tests.yml` (on push, no `continue-on-error`). If a change makes these
red, the change is wrong — they were all written from real incidents.

## 5. Debugging entry points

- "Why isn't company X in my email?" → ARCHITECTURE §5b (ordered runbook).
- "Is this verdict true?" → the row's `notes` names the tool and date; re-run that tool.
- "Did the run actually work?" → `gh run view <id> -R AnalystJobsIL/pipeline --log`.
  **13 of 39 workflow steps are `continue-on-error`, so a green run can still hide a
  failed step** — read the step, not the badge.
- Coverage snapshot:
  ```bash
  python -c "import csv;r=[x for x in csv.reader(open('companies.csv',encoding='utf-8')) if x and len(x)>5];print(len(r),'rows',sum(1 for x in r if x[4]=='true'),'active')"
  ```

## 6. Session hygiene reminders

- Commit as `ajil-bot`; push over the deploy key (plain `git push`), never `gh`-authenticated
  HTTPS. Avoid `gh workflow run` on the public repo; if unavoidable, delete the run record.
- Don't `git add -A` — a parallel session's work lives in this tree.
- Prefer letting the crons run over manual dispatches.
