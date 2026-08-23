# Module registry - what every file is, and whether it is alive

Generated and re-verified on 2026-08-23 by the `docs` lane. **Every root `*.py` appears
here exactly once**, and `docs/check_docs.py` fails the test suite if a new one does not.
That is the point of the file: before it existed a reader could not tell live code from a
one-shot probe, and `HANDOFF.md` listed two load-bearing modules as safe to delete.

The `runs in` and `imported by` columns are **computed from the code**, not typed by hand.
Regenerate with `python docs/gen_modules.py` after adding or retiring a module — the prose
lives in that script's `CLASS` dict, and it refuses to run if a root module is missing.
(That sentence is hand-added: `gen_modules.py` does not emit it, so every regeneration
drops it again — see `docs/BACKLOG.md`, "gen_modules.py does not round-trip its own file".)

| class | meaning | count |
|---|---|---|
| `scheduled` | a workflow invokes it | 27 |
| `library` | no workflow runs it; live code imports it | 6 |
| `operator` | a human or agent runs it; nothing in CI does | 10 |
| `legacy` | one-shot, superseded, or kept only for the record | 25 |
| | **total root modules** | **68** |

`pipeline/` is listed at the end. Lane ownership for all of these is in `docs/AGENT_BRIEF.md`.


## Scheduled - a GitHub Actions workflow runs these

If one of these stops working the pipeline degrades silently, because most of their steps are `continue-on-error`. The `runs in` column is computed from the workflow files.

| module | runs in | what it does |
|---|---|---|
| `apply_resolved.py` | self-heal | applies out/resolved_configs.json into companies.csv after the self-heal |
| `audit_empty_rows.py` | audit-coverage | weekly re-verification of every parked row; also the `verify()` helper every resolver imports |
| `auto_expand.py` | auto-expand | drains research_companies.json: deterministic tier, then the capped LLM tier |
| `bd_rescue.py` | retry-unreachable | re-fetches unreachable rows through the Bright Data Web Unlocker |
| `check_invariants.py` | daily-digest, tests | structural gate on companies.csv + the store; blocks the digest commit |
| `coverage_report.py` | audit-coverage | Sunday summary: of everything researched, how much is scanned |
| `crack_walled.py` | audit-coverage, listing-hunt | Chromium + network sniffing against walled ATSes (Phenom/Eightfold/iCIMS/SuccessFactors) |
| `deep_validate.py` | deep-validate | Saturday deep re-validation; owns `google_via_unlocker`, the only search rung that works today |
| `discovery_daily.py` | daily-digest | LinkedIn + Indeed sweeps via Bright Data -> discovered_cache.json + new employer names |
| `discovery_telegram.py` | daily-digest | public t.me/s channel previews; keyless |
| `enrich_matched_jd.py` | daily-digest | age-blind JD backfill over the matched table itself |
| `enrich_scrape_jd.py` | daily-digest | JD backfill for scrape-source jobs, with the 7-day cooldown stamp |
| `health_check.py` | self-heal | weekly backstop to the free health detection inside pipeline.run |
| `listing_hunt.py` | listing-hunt | finds the real listings URL for dark rows and verifies it; the 200-minute night job |
| `mark_sent.py` | daily-digest | marks a produced digest's roles delivered - records intent, not delivery (see docs/BACKLOG.md) |
| `merge_csv_rows.py` | audit-coverage, auto-expand, daily-digest, deep-validate, listing-hunt, retry-unreachable, scrape-refresh, self-heal, triage-dark | git-layer segment-aware merge for companies.csv; every csv-committing workflow calls it |
| `merge_json_cache.py` | audit-coverage, auto-expand, daily-digest, deep-validate, listing-hunt, retry-unreachable, scrape-refresh, self-heal | three-way merge for the company-keyed JSON caches |
| `probe_candidates.py` | daily-digest | cheap daily signal probe of monitored-candidate pages; wakes rows for the hunt |
| `refresh_scrape_cache.py` | scrape-refresh | 00:00 re-render of every scrape row; JD carry-forward and rot-parking |
| `repair_dead_urls.py` | listing-hunt | replaces stored URLs whose hostname does not resolve - runs BEFORE the hunt on purpose |
| `repair_extract_gap.py` | listing-hunt | re-scrapes rows triage marked `extract-gap`; the cheapest recovery class |
| `resolve_broken.py` | self-heal | 06:00 self-heal: re-resolves boards that went stale, throttled weekly, 5 strikes |
| `retry_unreachable.py` | retry-unreachable | 02:30 Bright Data retry of flaky endpoints |
| `scan_dead_domains.py` | audit-coverage, daily-digest | liveness scan over parked rows; a revived domain clears its flag automatically |
| `triage_dark.py` | triage-dark | 18:00 classification of every parked row by failure mode (`dark-triage <date>: <mode>`) |
| `validate_empty.py` | audit-coverage | Sunday cross-validation that 'validated-empty' rows really are empty |
| `wayback_rescue.py` | audit-coverage | Sunday rescue of unreachable rows via the Wayback Machine |

## Libraries - no workflow runs them, live code imports them

**These are the trap.** They look unused in the Actions history and they are load-bearing. `docs/check_docs.py` fails if a module listed here is imported by nothing.

| module | imported by | what it does |
|---|---|---|
| `comeet_resolve.py` | `audit_empty_rows.py`, `resolve_llm.py` | reads `window.comeetvar` off a rendered page to recover a Comeet uid+token |
| `ingest_research.py` | `resolve_parallel.py`, `resolve_unknowns.py`, `retry_unreachable.py` | resolve+verify helpers for the research queue. **Not deletable**: `retry_unreachable` (02:30 daily) imports `PROBE_FAST`, `_cand_slugs` and `_try` from it |
| `probe_ats.py` | `ingest_research.py`, `probe_expand.py` | guessable-slug probing. **Not deletable**: `ingest_research` imports `slug_variants` |
| `resolve_deep.py` | `auto_expand.py`, `bd_rescue.py`, `recheck_suspects.py` +4 more | deterministic resolver tier (recognizable ATS URLs, iframes) |
| `resolve_llm.py` | `auto_expand.py`, `deep_validate.py`, `listing_hunt.py` | the LLM resolution tier: evidence bundle -> one `claude -p` proposal -> verified through the real fetcher |
| `scrape_universal.py` | `bd_rescue.py`, `cache_new_rows.py`, `check_invariants.py` +10 more | the 5-strategy browser extractor, and a CLI: `python scrape_universal.py "Name" "<url>"`. Has no aggregator logic of its own - never point it at LinkedIn/Indeed |

## Operator tools - a human or an agent runs these on demand

Live and documented, but nothing in CI calls them. The firmographics three are driven by the Windows scheduled task `IsraeliJobs-Firmographics`, which no GitHub Action can see.

| module | what it does |
|---|---|
| `bd_employees.py` | LinkedIn employee-count fill via the Web Unlocker, 1 credit/page. Same Windows chain |
| `cache_new_rows.py` | scrapes rows activated since the last refresh and merges them into the cache |
| `company_type_analysis.py` | joins firmographics with matched jobs -> out/company_type_analysis.{json,md} (ARCHITECTURE.md section 7) |
| `fill_employees_llm.py` | re-researches employee counts the LinkedIn pass missed or got suspiciously wrong. Same Windows chain |
| `firmo_health_check.py` | tripwire: is the firmographics chain actually classifying anything? |
| `registry_health.py` | read-only registry census + row-deletion guard, recomputed re-check ownership matrix, live probe of every resolution rung, and the unsupported-ATS build queue. `--census` is the only thing it writes |
| `research_firmographics.py` | bulk firmographics research + `--export`. Run every 6h by the Windows task `IsraeliJobs-Firmographics` via run_firmo_chain.cmd |
| `setup_brightdata.py` | one-time: store the Bright Data token + zone in secrets.env |
| `setup_serpapi_key.py` | one-time: store the SerpApi key (quota exhausted until 2026-09-01) |
| `verify_company.py` | live-fetch verification of one company's endpoint - the research discipline as a script |

## Legacy / one-shot / superseded

Kept, not run. Nothing scheduled and nothing in `pipeline/` imports any of these - `docs/check_docs.py` fails if that stops being true. They are the deletion candidates, but read the note first: several exist only to document a finding, and two still write `companies.csv`.

| module | what it does |
|---|---|
| `bd_discover.py` | one-off test of Bright Data's Jobs-Scraper datasets |
| `bigtech_capture.py` | one-shot Playwright capture of big-tech careers XHRs |
| `bigtech_capture2.py` | the interactive second attempt at the same capture |
| `capture_bodies.py` | one-shot: dump the response bodies of a careers page's internal calls |
| `comeet_probe2.py` | superseded Comeet probe (kept: it documents how the widget lazy-loads) |
| `comeet_probe3.py` | superseded Comeet probe - the finding became comeet_resolve |
| `comeet_probe_pw.py` | the original Comeet diagnostic |
| `detect_ats.py` | superseded ATS sniffing; the live version is resolve_deep + audit_empty_rows.SIGS |
| `gen_test_board.py` | renders build_board_html with sample jobs for styling review |
| `merge_research.py` | **rewrites research_companies.json on import.** Do not import it |
| `ms_capture.py` | one-shot capture of the Microsoft careers search request |
| `poc_company_profile.py` | the firmographics POC (docs/POC_COMPANY_PROFILES.md); superseded by pipeline/firmographics.py |
| `probe_bigtech.py` | one-off probe of big-tech public job-search APIs |
| `probe_expand.py` | one-off probe of companies not yet in the registry |
| `recheck_suspects.py` | the ONLY clearer of the `empty-but-suspect` verdict, and on no schedule. Deleting it strands that verdict class |
| `resolve_any.py` | superseded general resolver |
| `resolve_parallel.py` | superseded fast HTTP resolver |
| `resolve_unknowns.py` | superseded slug-probe pass |
| `scrape_batch.py` | batch driver for the scraper over the research queue; writes out/*.csv only |
| `scrape_jobs.py` | the first Playwright scraper; superseded by scrape_universal |
| `shot_board.py` | screenshots the local board for visual review |
| `shot_details.py` | screenshots expanded job-detail blocks |
| `validate_bd.py` | second-pass validation of Bright-Data-scanned rows; superseded by deep_validate |
| `verify_jsearch.py` | confirms the SerpApi Google-for-Jobs source works; that quota is exhausted |
| `workday_probe.py` | one-off Workday tenant/site probe |

## `pipeline/` - the digest-run library

Eight of these are **shared plumbing**: every lane imports them and no lane owns them.
Changing one is a say-so-loudly event (`docs/AGENT_BRIEF.md`).

| module | what it does |
|---|---|
| `pipeline/aggregators.py` | is this URL an aggregator? Gates activation and runtime |
| `pipeline/atomic.py` | **shared** - atomic writes for every state file |
| `pipeline/companies.py` | **shared** - load companies.csv into row dicts |
| `pipeline/company_identity.py` | **shared** - does this URL belong to this company? Gates all four activation paths |
| `pipeline/company_info.py` | the two-sentence company blurb |
| `pipeline/digest.py` | the board, the archive and the email |
| `pipeline/fetchers.py` | one normalizer per ATS platform -> the common job shape. 16 platforms |
| `pipeline/firmographics.py` | per-company sector / stage / size / business model |
| `pipeline/health.py` | per-company ATS health -> cloud_state/stale.json + health_baseline.json |
| `pipeline/http.py` | **shared** - the zero-dependency HTTP helper |
| `pipeline/israel.py` | deterministic Israel-location filter |
| `pipeline/jdfill.py` | fetches a job description for a role that arrived without one |
| `pipeline/notes.py` | **shared** - the companies.csv notes append-log. Never hand-roll a trim |
| `pipeline/platform_check.py` | self-check that an ATS platform is wired into all of its sites |
| `pipeline/recruiters.py` | recruiting-agency exclusion |
| `pipeline/roleprofile.py` | per-job skills / role family / IC-vs-lead / years |
| `pipeline/run.py` | **the orchestrator.** Owned by `infra`; any lane may need a hook in it - propose it, do not smuggle it |
| `pipeline/seniority.py` | relevance + experience classification; the LLM tier for ambiguous titles |
| `pipeline/sources.py` | **shared** - per-discovery-source liveness |
| `pipeline/stages.py` | **shared** - which nightly stage last finished, and how much it did |
| `pipeline/store.py` | the SQLite seen-store: sent / matched / llm_cache / company_info / firmographics |
| `pipeline/verdicts.py` | **shared** - the single source of truth for verdict tokens and re-check pools |

## Modules that execute on import

8 root modules have no `if __name__ == "__main__"` guard, so *importing* them runs them.
`merge_research.py` rewrites `research_companies.json` on import. All 8 are `legacy`, so
nothing live imports them today - but that is a fact about today, not a guard:

`bigtech_capture.py`, `gen_test_board.py`, `merge_research.py`, `ms_capture.py`, `probe_bigtech.py`, `probe_expand.py`, `shot_board.py`, `shot_details.py`

