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
