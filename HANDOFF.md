# Session handoff — 2026-08-22

Read `ARCHITECTURE.md` first (system model, invariants, runbooks). This file is the
"what just happened / what to watch / what's next" layer on top of it.

## 1. What changed in the last two sessions (2026-08-21 → 22)

**Infrastructure**
- Migrated from the private personal repo to **public `AnalystJobsIL/pipeline`** (unlimited
  free Actions minutes). Anonymity rules are in the gitignored `CLAUDE.local.md` — read it
  before committing or dispatching anything. Old repo `shailiv/israeli-jobs-pipeline` is a
  private archive with all workflows disabled (local remote `backup`).
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
