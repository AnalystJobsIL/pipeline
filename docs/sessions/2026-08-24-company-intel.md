# 2026-08-24 — `company-intel` lane: one bounded cloud path, and the mail says what it did

> Append-only, wave-structured; later waves win. Every count is a snapshot — re-derive it
> with the command shown next to it before trusting it.

**Scope.** Files written: `pipeline/firmographics.py`, `pipeline/company_info.py`,
`research_firmographics.py`, `fill_employees_llm.py`, `company_type_analysis.py`,
`tests/test_company_intel.py` (new), `ARCHITECTURE.md` §7, `docs/BACKLOG.md` (new items),
this record, one `HANDOFF.md` line. **Out-of-lane edits, approved by the operator before
they were made:** `pipeline/run.py` (the two company-intel blocks replaced by one call into
the lane) and `pipeline/digest.py` (one `Company intel:` line in each of the three audit
renderers). Declined by the operator: the `_STAGE_LABEL` entry for `private-enterprise`
(filed for `render`).

**Spent, locally.** Bright Data: 0. SerpApi: 0. Pipeline Claude calls: 0 — every rehearsal
ran `--no-llm` or against a fake `claude.cmd` shim first on PATH; every test monkeypatches
the seam. Opus attacker sessions: see the tally at the end.

## Baseline (re-derived before any edit, `git rev-parse --short HEAD` = 2f1529f)

| fact | value | how |
|---|---|---|
| export `cloud_state/firmographics.json` | HEAD **924** · worktree **940** · cloud sqlite **921** · local sqlite **940** | `git show HEAD:cloud_state/firmographics.json \| python -c "import json,sys;print(len(json.load(sys.stdin)))"`; `python -c "import json;print(len(json.load(open('cloud_state/firmographics.json',encoding='utf-8'))))"`; `sqlite3 cloud_state/seen.db "select count(*) from firmographics"` |
| who commits the export | the cloud digest (`git add cloud_state`) and, by hand, `97f58ed` — the Windows chain writes the file and **never commits it** (§7 said "publishes automatically") | `git log --format='%h %an %s' -- cloud_state/firmographics.json` |
| coverage of the 940 | 0 lack sector / stage / size_band / employees_global; founded null **5**; il_center empty **4**; band/count contradictions **0** | python count over the export |
| identity-duplicate groups | **29** (§7 said "9 pairs merged") | `python -c "import json,collections;from pipeline.firmographics import identity_key as k;d=json.load(open('cloud_state/firmographics.json',encoding='utf-8'));g=collections.defaultdict(list);[g[k(c)].append(c) for c in d];print(sum(1 for v in g.values() if len(v)>1))"` |
| duplicate research spend today | **2** — Phoenix Financial, SHILA Medical Services LTD: cloud digest 05:42 UTC (`updated='2026-08-24'` in cloud sqlite), then the local chain at 15:00 local (`state/firmo_chain.log`); they are exactly the two records that differ between HEAD and the worktree | `sqlite3 cloud_state/seen.db "select company from firmographics where updated='2026-08-24'"` vs the chain log |
| chain runs today (local, 6-hourly) | 12 · 0 (two `529 Overloaded` + one 240 s timeout → 3-strike abort) · 2 · 0 researched; 40–80 s per call at 3 workers (§7 said 15–60 s) | `grep -E "chain start\|researched," state/firmo_chain.log` |
| blurbs | cloud `company_info` **102**, **5** are `''` (SQLink Group, Trivago, TechBiz Global GmbH, Shavit Software, Parametrix GmbH); 7 of 90 matched companies have no usable blurb | `sqlite3 cloud_state/seen.db "select company from company_info where summary=''"` |
| the mail | today's `Run audit` has no company-intel line; `firmographics_researched` and `company_summaries` are counted in `run.py` and printed nowhere; Peak Innovation rendered with no facts and nothing said so | `digests/latest.md` |
| tests guarding this lane | **0** of 371 collected (261 units + 110 registry) | `python -m pytest -q --co` |
| latent cloud bugs | `fill_employees_llm.lookup` `shell=True` on every platform; `company_type_analysis.py` reads gitignored `state/firmographics.json`; `run.py` writes the tracked export on scoped `--only` runs; a corrupt export is silently replaced by the smaller sqlite table | read of the code; rehearsal case (d) below |
| research time inside the digest | today 2 researched; no time budget — worst case 5 × 240 s + 30 × 90 s = 65 min of a 150-min job | `gh run view 32694484572 --log` |

## The design (ARCHITECTURE §7 is the durable version)

Three alternatives for where steady-state research lives were weighed: (i) the cloud digest
hook alone, the Windows chain optional; (ii) the chain made self-publishing from an isolated
worktree; (iii) both, the chain reading the export first. **(i)**, because the runner already
has the CLI, the OAuth token and the daily commit, and only ~90 companies have ever rendered.
(iii)'s read-fix is kept so the chain is harmless while it still runs; (ii) was rejected — a
second writer of record, push credentials on a laptop, git + sqlite under OneDrive, and the
cloud conflict path (BACKLOG 94) would still clobber it. The blurb-vs-facts redundancy is
closed by reading the facts as prose when the blurb is missing (`derive_blurb`), not by giving
the blurb its own web search (double cost for prose the card already implies).

## The defects — wave 1 (3 Opus attackers on the untouched code), all reproduced by the reviewer

| # | finding | fix | pinned by (`tests/test_company_intel.py`) |
|---|---|---|---|
| A1 | the digest hook struck up to 5 names per run on a soft outage (exit-0 prose); `revoke_firmo_failures` was called from nowhere | `SOFT_OUTAGE_MIN_FAILS` (3) failures with no success → no strikes, a warning | `test_audit_lines_cover_every_report_shape[soft_outage]` |
| A2/C6 | a `''` blurb was re-bought every run, forever (5 names since 08-17/08-20) | retried monthly via `company_info.updated`; three empties in a row stop the loop | `test_empty_blurbs_retry_monthly_not_daily` |
| A3 | greedy `\{.*\}` turned a valid answer with a brace in its preamble into a strike | `extract_json` — `JSONDecoder.raw_decode` from every `{` | `test_cli_failure_raises_and_prose_returns_none` + `test_claude_subprocess_never_uses_a_shell_off_windows` |
| A4/C3 | `firmographics_researched` / `company_summaries` counted and printed nowhere; `LLM calls this run` excludes every blurb and research call | `audit_lines` → `stats["company_intel"]` → three renderers + `::warning::` | `test_company_intel_line_reaches_all_three_audit_renderers`, `test_audit_lines_cover_every_report_shape` |
| B1 | `--export` wrote the local table over the shared file (19 cloud records deleted per tick) | `union_store` + `save_shared` (atomic) | `test_export_writes_the_union_not_the_local_table` |
| B2 | chain and hook gated re-research on sqlite alone (Phoenix Financial, SHILA bought twice on 08-24) | `sync_store` + `union_store` everywhere | `test_chain_targets_exclude_companies_the_export_already_holds`, `test_sync_seeds_sqlite_from_the_export_and_is_idempotent` |
| B3 | `newer()` tie → shared side; whole-record replace lost employee fills (26 records with `employees_as_of` > `as_of`) | `_evidence` tie-break; field-level `merge` with the `_COUNT_COMPANIONS` rule | `test_newer_prefers_the_later_as_of_then_the_fuller_record` |
| B4 | a corrupt export read as `{}` and the union wrote 921 records over 940 | `load_shared_status`; corrupt → reported, never overwritten | `test_corrupt_export_is_never_overwritten_by_the_union`, `test_missing_export_is_reported_and_recreated` |
| B5 | `--only … --db scratch` rewrote the tracked export | `scoped=True` skips publish | `test_scoped_run_never_writes_the_shared_export` |
| B6 | `_by_key` last-wins: "Amazon Israel" answered for "Amazon"/"AWS" by sort order | `display_index` (fullest record, then shortest name) | covered by the union tests; group listing in §7 |
| B7 | 16 profiles + 2 corrections unpublished in the worktree while the chain rewrote the file 4×/day | the union export settles the file; committed this session | — (data) |
| C1 | `_STAGE_LABEL` lacks `private-enterprise` (44 records render the enum) | declined (render lane) → BACKLOG 99 | — |
| C2 | `il_center` chips up to 223 chars, `nowrap`, 426 of 940 records | `chip_safe` on the display copy only | `test_facts_chips_are_unchanged_for_a_full_record` + §8 byte-compare |
| C4 | `_ABOUT_JUNK` ≠ `_JUNK_OUT`; `company_profiles.json` bypassed both | profiles filtered through `_JUNK_OUT` on load; regex drift → BACKLOG 100 | `test_the_three_callers_share_the_seam` |
| C5 | one `sqlite3.OperationalError` in the hook = no email, no board | `enrich_for_run` never raises; partial results + `company intel FAILED (…)` in the line | `test_audit_lines_cover_every_report_shape` (`error`) |
| — | `fill_employees_llm.lookup` `shell=True` on Linux; `company_type_analysis` read a gitignored file | one seam; committed export by default | `test_claude_subprocess_never_uses_a_shell_off_windows`, `test_company_type_analysis_reads_the_committed_export_by_default` |

Found SOUND by the attackers (do not re-attack): `ResearchUnavailable` vs `None` in
`research_company`; `save_shared` atomicity; `save_shared({})` guard; the band/count invariant
(0 of 940); `looks_like_junk` + intra-batch identity dedupe; HTML/markdown escaping of chips;
the `firmo_display` identity fallback; `record_firmo_failure` write ordering; the bulk script's
3-streak abort and mass-failure guard (both fired correctly on 08-24 09:13).

## Rehearsal — tomorrow's digest, against scratch copies, zero spend

Driver: a scratch script copies `cloud_state/seen.db` + the export, strips every key from the
environment, puts a fake `claude.cmd` first on PATH (`FAKE_CLAUDE=json|unknown|prose|fail|
sleep`, every call logged), monkeypatches `firmographics.SHARED_EXPORT`, `stages.PATH` and
`run._load_secrets_env`, calls `pipeline.run.run(...)`, and asserts `git status --short` is
unchanged afterwards (it was, every time). `--hole` deletes named companies from the scratch
copies so there is research to do.

| case | `Company intel:` line (verbatim) | calls | strikes | export |
|---|---|---|---|---|
| a (`--no-llm`) | `research off (--no-llm); all 55 board companies profiled · blurbs: 0 written · export 940 records, newest 2026-08-24, 20 newer than the store` | 0 | — | untouched (scoped) |
| json, hole = Phoenix + SHILA | `2 of 54 board companies unprofiled (cap 5/run, budget 10m): 2 researched, 0 failed (1 more unprofiled: research failed, weekly retry) · blurbs: 2 written · export 938 records …` | 4 | none | untouched (scoped) |
| unknown / prose | `… 0 researched, 2 failed (1 more unprofiled …) · blurbs: 0 written …` | 4 | 2 (below the 3-fail soft-outage rule — accepted, documented) | — |
| fail (`Not logged in`) | `… claude unavailable after 0 research calls (Not logged in . Please run /login) — 2 unprofiled board companies wait for the next run …` + `::warning::company-intel …` | 1 | **none** | — |
| export corrupt (`{"a": `) | `… export CORRUPT at cloud_state/firmographics.json — cards render from sqlite only (921 records); file left untouched` + warning | 0 | — | byte-identical to the corrupt input |

"1 more unprofiled" is Peak Innovation — struck on 08-24 by both stores, weekly retry.
The 20 (later 19) "newer than the store" is 940 − 921 export-only records + Phoenix's fuller
local re-research; after the seed tomorrow's line should say 0 unless the chain ran overnight.

**No-regression proof.** `_firmo_facts` over all 940 stored records, before and after: byte-
identical (`cmp facts_before.txt facts_after.txt`). The trimming is applied to the display copy
only, and only to `il_center` (426 of 940 records; e.g. `Tel Aviv (HQ; registered as Zipher
Technologies Ltd, no. 517004768)` → `Tel Aviv` — the `;` splits inside the parenthesis and the
dangling `(` clause is dropped; the stored text is untouched).

## Mutation sweep

See BACKLOG 104; the catalogue lives in the scratchpad of this session and the survivors, if
any, are listed under wave 3 below.

## Wave 2 — the implementation diff (3 Opus attackers), 18 findings, all fixed in-lane and pinned

| # | finding | fix | pinned by |
|---|---|---|---|
| A1 | 30 blurb calls read as `blurbs: 1 written`; the empties stop was disarmed by one early success | `blurbs_asked` / `blurbs_empty` / `blurbs_skipped_budget` in the line; three empties in a row stop regardless | `test_blurb_calls_are_counted_and_three_empties_in_a_row_stop_the_loop` |
| A2 | the research budget started after the blurb loop: the hook's envelope was 55 min, the mail said 10 | one `_Clock` for both loops; `FIRMO_TIME_BUDGET_MIN` default 15 | `test_one_wall_clock_bounds_blurbs_and_research_together` |
| A3 | a blurb-side soft outage did not stop research | `blurb_outage` gates research; `_research` checks the rule inside its loop | `test_a_blurb_soft_outage_skips_research_entirely` |
| A4 | a blurb outage rendered as "0 research calls" | `unavailable_in` names the loop | `test_a_blurb_outage_names_its_loop` |
| A5 | an all-fail research morning below the 3-fail rule struck names with no warning | a `::warning::` names it | `test_an_all_fail_research_run_warns_even_below_the_outage_threshold` |
| A6 | no identity dedupe for blurbs (Meta / Meta Israel both paid) | one blurb per identity; the group's variants read it | `test_one_blurb_call_per_identity_not_per_name_variant` |
| A7 | on Windows `shell=True` makes the seam timeout advisory | documented in §7; the digest runs on Linux | — (accepted) |
| A8 | `sync_store` wrote the committed sqlite on the documented produce-only command | no sync on a scoped run | `test_a_scoped_run_writes_neither_the_export_nor_the_store` |
| B1 | CLI stderr / a Hebrew exception in the line raised `UnicodeEncodeError` on the laptop's cp1252 pipe — after the never-raises guard | `_ascii()` folds interpolated text; `run.py` reconfigure stays BACKLOG 12 (`infra`) | `test_audit_lines_survive_a_cp1252_console_and_a_hebrew_error` |
| B2 | a failed `os.replace` left a `.tmp` beside the export and the line still said "export 940 records" | `publish_error` → `export NOT written (…)` + warning; temp unlinked in `finally` | `test_an_unwritten_export_is_said_and_leaves_no_tmp` |
| B3 | two local writers shared one `.tmp` name | `.{pid}.tmp` | `test_save_shared_uses_a_per_process_temp_name_and_reports_a_noop` |
| B4 | `_stamp_ok` had no `makedirs` (`state/` is gitignored) | `makedirs` | — (one line) |
| B5 | `published=True` when `save_shared` declined an empty union | `save_shared` returns whether it wrote | same test as B3 |
| C1 | my §7 guard shipped red (heading renamed under it) | anchor on `## 7. `; positive claims only | `test_architecture_section_7_names_the_real_identity_function` |
| C2 | one `soft_outage` flag for two loops: a false warning on a healthy research loop; the three `''` rows that triggered a blurb outage were month-gated | separate flags and sentences; the `''` rows are deleted on a blurb outage | `test_a_blurb_soft_outage_skips_research_entirely` |
| C3 | `display_index` evidence-first: a fill-touched "AWS" answered for "Amazon"; "Dell Israel" beat "Dell Technologies" | rank = canonical name, non-site-form, evidence, shortest | `test_display_index_prefers_the_canonical_name_over_an_alias_or_a_site_form` |
| C4 | `extract_json` took a leading `{}` / restated `{"unknown": true}` | first substantive object | `test_extract_json_prefers_the_substantive_object_over_a_restated_escape_hatch` |
| C5 | nine wave-1 fixes had no guard (reverting each left the suite green) | ten pins added (`merge`, `_COUNT_COMPANIONS`, thresholds, chips, profiles, front door, chain export, …) | see the wave-1 table's last column |

Wave-2 C's spend declaration: one probe reached the real `claude -p` seam before it was
guarded — **at most one** `claude -p --allowedTools WebSearch` call may have been spent on the
subscription. Everything else in this session: 0.

## Final rehearsal (same driver, finished code)

| case | `Company intel:` line (verbatim, scratch copies; "1 more unprofiled" is Peak Innovation, struck on 08-24) | calls | strikes |
|---|---|---|---|
| a `--no-llm` | `research off (--no-llm); 2 of 54 board companies unprofiled (1 more unprofiled: research failed, weekly retry) · blurbs: 0 asked, 0 written · export 938 records, newest 2026-08-24` | 0 | — |
| json | `2 of 54 board companies unprofiled (cap 5/run, budget 15m): 2 researched, 0 failed (1 more unprofiled: …) · blurbs: 2 asked, 2 written · export 938 records, newest 2026-08-24` | 4 | none |
| unknown | `… 0 researched, 2 failed (…) · blurbs: 2 asked, 0 written, 2 empty · …` + `::warning::company-intel every research answer failed (2 of 2) — below the 3-fail outage rule, so the names were struck` | 4 | 2 (weekly) |
| fail | `… 0 researched, 0 failed (…) · claude unavailable after 0 blurbs calls (Not logged in . Please run /login) — 2 unprofiled board companies wait for the next run · blurbs: 0 asked, 0 written · …` + warning | 1 | none |
| corrupt export | `… export CORRUPT at cloud_state/firmographics.json — cards render from sqlite only (921 records); file left untouched` + warning; file byte-identical | 0 | — |
| missing export | `… export MISSING at cloud_state/firmographics.json — cards render from sqlite only (921 records)`; recreated | 0 | — |

`git status --short` identical before and after every case. The scoped runs no longer write
`N newer than the store` because a scoped run seeds nothing; the unscoped cloud run tomorrow
will (expected: `19 newer than the store` = 940 − 921, then 0 the day after).

## Mutation sweep (wave 3C, scratch runner over `tools.mutate`'s idea, on a copy of the tree)

18 mutations in `mutations_company_intel.json` (scratchpad; BACKLOG 104 asks `tools/mutate.py`
for a `--catalogue` flag): **17 killed, 1 survived** — `ci-sync-not-idempotent` (drop the
`rec != have.get(c)` half of `sync_store`'s filter) is an equivalent mutant: `newer()` returns
`a` on a tie, so an identical record is never chosen twice; recorded, not a gap.

## Tally

Opus attacker sessions: 6 (wave 1: 3, wave 2: 3); wave 3 was the mutation sweep plus this
record's own cold read. Tests: 443 collected (278 units + 110 registry + 55 company-intel), all
green; `check_invariants.py` clean; `docs/check_docs.py` 0 errors over 21 documents. Bright
Data 0, SerpApi 0, pipeline Claude calls 0 from this session (≤1 from an attacker probe).

## Follow-up the same evening — the split

The first commit left `pipeline/firmographics.py` at 802 lines carrying five concerns under
banners. Second commit: the digest hook and the mail line moved to `pipeline/company_intel.py`
(the shape §7 already described); `firmographics.py` keeps the record, identity, the `claude`
seam and the export. `run.py` imports `company_intel` at the approved hook site; no other
importer touched a hook name. The rehearsal driver and the fake `claude` shim are committed
as `tests/rehearse_company_intel.py` + `tests/fixtures/company_intel/` (with the mutation
catalogue), so the next agent runs them instead of rewriting them.

## Morning-after checklist — 2026-08-25 (read-only; nothing dispatched 05:00–08:30 UTC)

1. `gh run view <id> --log | grep -E "company-intel"` → one `[company-intel]` line whose counts
   reconcile; a `::warning::company-intel` only for an outage / corrupt export / all-fail.
2. `git show origin/master:digests/latest.md | grep "Company intel"` equals it.
3. export key count = 940 + researched; a **fall** = truncation → high.
4. `firmo_failed` in the committed `seen.db`: new rows ≤ `failed`; none if the line said outage.
5. the board: `curl -s https://analystjobsil.github.io/board/ | grep -c 'class="cofacts"'` ≈
   profiled board companies; no `il_center` chip over 48 chars.
6. the 09:00 local chain: `python research_firmographics.py --dry-run` must not list a company
   the cloud researched that morning.
7. `git status --short cloud_state/firmographics.json` after `git fetch`: the local chain's
   overnight export must be a superset of origin's (union), never smaller.

### As written in HANDOFF.md, 2026-08-24 (`company-intel`)

*Moved here verbatim on 2026-08-27 by the `docs` lane, because a whole
session written as one 3,000-character line defeated HANDOFF.md's cap.
sha256(first 16) of the line as it stood: `ab4903950f7570e0`.*

- **2026-08-24 `company-intel` (one bounded cloud path; the mail says what it did — two adversarial waves, 6 Opus sessions, 17 wave-1 findings all fixed or filed):** `pipeline/run.py`'s two blocks are one call, `company_intel.enrich_for_run` (`pipeline/company_intel.py`) (never raises; ≤5 research calls in ≤10 min, ≤30 blurbs, first outage stops it, no strikes on an outage, `` blurbs retried monthly, facts read as prose when the blurb is missing, chips ≤48 chars); every reader/writer uses `union_store` (export ∪ sqlite, field-level merge) so the chain no longer re-buys the cloud's research (2 on 08-24) or truncates the export (19 at risk); a corrupt export is reported, never replaced; one `claude` seam (`shell` only on Windows; brace-safe JSON); the audit block carries `- **Company intel:** …` + `::warning::company-intel` (rehearsed: json / unknown / prose / fail / corrupt / missing / --no-llm). 940-record export committed. NOT done: chain retirement (BACKLOG 97), 29 duplicate groups (98), stage label (99, `render`); morning check 2026-08-25 = the `Company intel:` line must reconcile and `N newer than the store` must be 0 after the seed. Record: `docs/sessions/2026-08-24-company-intel.md`.

