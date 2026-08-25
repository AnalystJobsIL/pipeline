# Handoff — current state

**What this file is:** the state of the system *right now* — what changed last session, what
is known-broken, what nobody has claimed. Nothing else. It is capped at 250 lines and
`docs/check_docs.py` enforces the cap, because this file was 753 lines of four different
things on 2026-08-23 and nobody could find the current bit.

Where the other three things went:

| you want | read |
|---|---|
| the durable system model, the rules, the runbooks | `ARCHITECTURE.md` |
| a design debt or a known gap that outlives a session | `docs/BACKLOG.md` |
| what one past session found and fixed, in its own words | `docs/sessions/<date>.md` |
| where to start as a spawned agent | `CLAUDE.md`, then `docs/AGENT_BRIEF.md` |

**Update this file before you push.** Three lines is enough: what was wrong, what you
changed, what you did NOT finish. Add your session's narrative to `docs/sessions/` if it is
long enough to be worth keeping.

---

## Last session — 2026-08-23 (morning): seventeen defects, A–Q

Full write-up: **`docs/sessions/2026-08-23.md`**. In one paragraph: the six-step flow was
made to work end to end. Every one of the seventeen defects had a green workflow and a
plausible log line — two were costing coverage every day (Indeed had returned zero records
since it was wired up; four fetchers never carried a description), three were about to
publish other companies' roles under Israeli names (86 Israel roles between them), and one
had discarded a completed run — 894 companies, 187 LLM calls, a built board — over a single
false positive in the commit gate. That is the character of this codebase's failure mode and
the reason `ARCHITECTURE.md` §8 exists.

**2026-08-23 (afternoon), `docs` lane:** the documentation infrastructure. `CLAUDE.md` now
loads automatically, `README.md` opens with the flow, `ARCHITECTURE.md` has a map and names
the owning lane in every section, this file was split, and `docs/check_docs.py` makes the
docs a build artifact that can go red. See the last section of this file for what it did
not finish.

**2026-08-23 (evening), `discovery` lane:** Telegram was invisible to the dead-source detector (no `telegram` key in `source_health.json` beside 104 telegram jobs in the cache) and the targeted LinkedIn sweep searched the same 20 of 110 stale companies every day; both fixed, 3 channels added, 4 Hebrew agency spellings that walk past their own Latin entries blocked, new `ARCHITECTURE.md` §1a — `docs/sessions/2026-08-24-discovery.md`, 5 items left in `docs/BACKLOG.md`.

**2026-08-24, `discovery` lane (follow-ups):** the 05:00 run answered the open question — the free guest path works on GitHub runners (`free=166 paid=14`, 188 new companies) — but four keywords ended on the 30-page cap with pools unread, the national window was Tel Aviv-weighted, and a starved targeted cap (4, BD pool at 97%) still burned a doomed dataset trigger. Shipped: guest walk 30→50, Be'er Sheva + Haifa city windows (free-only by construction, paid worst case unchanged), targeted skip below `TARGETED_MIN_CAP`, comment density cut. NOT finished: the module split (BACKLOG 14, needs a quiet day), rejected-names ledger + Geektime feed filed as BACKLOG 70/71. Watch tomorrow: `[linkedin] … across 27 queries` and a `linkedin_blank` spike (would mean the +18 free queries triggered soft-limiting — back the city product off first).

## State at handoff (2026-08-23 07:35 UTC, verified against the published product)

| | |
|---|---|
| registry | 1,189 rows · **846 active** · 343 parked (32 of them `alias-of` duplicates parked today) |
| today's digest | scanned **846** companies, **1** failed (was 3-4 every run), **163** LLM calls (was 34) |
| classifier | 71 accepted → 54 after merge → **11 emailed** (1 posted in the last 48h + 10 at 9 newly covered companies) |
| board | **56 live roles**, every one with researched company facts; archive **49** |
| store | 105 matched roles, **98 with a real JD (93%)**, 29 sent, 919 firmographics |
| descriptions | 15 fetched inline before classification, 14 into the scrape cache, 3 backfilled into the store at any age |
| discovery | Indeed **33 jobs** (0/day for the previous five), LinkedIn 30 + 78 targeted, Telegram quiet; 9 agencies rejected at the source |
| guards | 122 unit assertions (was 71), all green; `check_invariants` clean with 2 informational warnings |

The two remaining identity warnings are ClearML (`clear.ml` — the TLD carries the name) and
Secret Double Octopus (a JVP portfolio board scoped by slug). Both verified by hand.

**Re-counted from the working tree at 2026-08-23 19:00 UTC** (`docs` lane, same commands,
after the 09:01 auto-expand run): **1,199 company rows · 846 active · 353 parked**, 39 of
them carrying an `alias-of` note. (`check_invariants.py` prints `1200 rows` for the same
file — it counts the header line. Not a bug, but the two numbers will keep looking like a
discrepancy until someone makes it skip the header.) `cloud_state/seen.db`: 105 matched, 29 sent, 198 `llm_cache`
rows, 98 `company_info`, 919 `firmographics`; `cloud_state/firmographics.json` carries 926.
Test suite: **123 cases from 54 test functions**, all green (122 before this session).

## Today's digest runs

The 05:00 scheduled run failed on a false-positive invariant (defect §K in the archive) and
everything after it was a manual dispatch, each cancelled and re-dispatched as another
defect turned up. The cancelled records were deleted per `CLAUDE.local.md` §3, which is why
the Actions history shows one failure and then a single success. **If you ever cancel a
digest run, cancel it BEFORE `Mark digested roles as sent`** — after that step the run's
roles are burned as delivered and the next run will not email them.

## Watch list for the next session

0. **75 active companies have an all-time-high job count of ZERO** — including Adobe,
   Broadcom, PayPal, Outbrain, At-Bay, Snyk, Deel, Capital One, Analog Devices, XM Cyber,
   Explorium, AI21 Labs, Frontegg, Aporia, Vayyar. Their endpoints answer correctly and
   return an empty board, so nothing errors and nothing is flagged: greenhouse `outbraininc`
   replies `{"jobs":[],"meta":{"total":0}}`. These companies are obviously hiring, so the
   tenant is stale — they have moved boards, exactly as Moon Active had (its Comeet endpoint
   returned 0 for weeks while 33 jobs, 24 in Israel, sat on Ashby).

   > **`docs` re-count, 2026-08-23 19:00 UTC: it is 256, not 75.** Same computation, run
   > against the committed `cloud_state/health_baseline.json` (897 entries, written by
   > today's 07:34 digest):
   > `python -c "import json,csv;b=json.load(open('cloud_state/health_baseline.json'));r={x['company_name'] for x in csv.DictReader(open('companies.csv')) if x['active']=='true'};print(sum(1 for n,v in b.items() if int(v)==0 and n in r))"`
   > The number grew because the baseline did — the 08-22 run only reached part of the
   > registry, and every active row now has an entry (ARCHITECTURE §5b's "158 of 722 had no
   > baseline" trap is currently 0 of 846). **Split by platform it is a different problem
   > than the paragraph above describes:** 192 of the 256 are `scrape` rows, most of them the
   > deliberately-activated `page-empty` class where zero is the correct answer, and only
   > **64 are native-ATS rows** — that 64 is the "board has moved" set this item is about.
   > Feed the recovery command below the 64, not the 256, or it is a many-hour run mostly
   > spent re-rendering pages that are honestly empty.

   This is the largest remaining coverage item, and the self-heal cannot reach it today:
   `resolve_broken.candidates()` reads `stale.json`, which holds only what the LAST digest
   happened to scan, and every one of the 75 is throttled to a weekly retry with one strike
   already spent. `--only` now reaches any registry row (fixed this session), so the
   recovery run is:

       python resolve_broken.py --only "$(python -c "import json,csv;b=json.load(open('cloud_state/health_baseline.json'));r={x['company_name'] for x in csv.DictReader(open('companies.csv')) if x['active']=='true'};print(','.join(n for n,v in b.items() if int(v)==0 and n in r))")"
       python apply_resolved.py            # skips anything repaired by hand the same day

   Started once this session; it renders each public careers page and sniffs, so it is slow
   and it fails on anti-bot Workday tenants. The ones it cannot crack want `crack_walled`
   with the residential unlocker, or a hand-check like the ones in §N.

   **When it retries, it will at least be able to try.** `cloud_state/resolve_attempts.json`
   holds one strike each, dated 2026-08-22 for 61 of them and 2026-08-17 for 13, so the
   weekly throttle releases them on **2026-08-29** and **2026-08-24** respectively. By then
   both reasons the retry was pointless are gone: the search rung works (it was SerpApi-only,
   and that quota has been out since mid-August), and today's digest rewrites `stale.json`
   across all ~846 active companies rather than the 558 the 08-22 run happened to reach.
   Check `resolve_attempts.json` after those dates — names that disappear were fixed, names
   at `fails: 2` were not. To not wait, run the two commands above by hand.

   A forced run with the fixed ladder was started this session and stopped after ~15
   companies, having recovered none — which is itself the finding: these are not broken URLs
   but boards that MOVED somewhere a render-and-sniff of the old address cannot see (Outbrain
   is the worked example: its board is on greenhouse's EU region, below). It costs about 90
   seconds per company, so a full pass is a ~2-hour job; run it detached. Its attempt bumps
   were deliberately not committed, so the scheduled retry keeps its own clock.

   **Greenhouse has an EU region and our fetcher does not know it.** Outbrain's real board is
   `job-boards.eu.greenhouse.io/outbraininc`; the US `boards-api.greenhouse.io/v1/boards/
   outbraininc/jobs` answers `{"jobs":[],"meta":{"total":0}}`, which is why it reads as an
   empty board rather than a wrong one. There is no `boards-api.eu.greenhouse.io` (NXDOMAIN)
   and `api.eu.greenhouse.io` returns 401, so the EU board has no public JSON API — the page
   is a JS shell and needs the renderer. The right shape is probably a
   `job-boards.eu.greenhouse.io/<slug>` scrape row, or a greenhouse fetcher that falls back
   to rendering the EU board when the US API returns zero. Lever has the same split
   (`api.eu.lever.co`), which the README already mentions and no code handles. Worth checking
   how many of the 75 are this, before writing anything bespoke.


1. **`merge_key` should move onto `firmographics.identity_key`** — the ~15 remaining alias
   groups (Amazon/AWS, Microsoft/Microsoft Israel, PayPal/PayPal Israel) can only collapse
   there. It is the `matched` PRIMARY KEY, so this needs a migration: re-key existing rows
   in place, or the old rows freeze, fall out of `_alive` and appear in the archive for a
   day. `docs/BACKLOG.md` ("One identity layer") wants this anyway.
2. **`mark_sent` still records intent, not delivery.** It runs before the digest is pushed
   and long before the relay posts. The relay's second cron (08:30) covers a single
   failure, so the exposure is bounded, but a role can still be burned unsent.
3. **`cloud_state/seen.db` is committed daily at ~1.2MB.** Now that firmographics also
   travel as JSON, the sqlite copy of that table is redundant — dropping it (and
   VACUUMing) would take the daily binary back to ~790KB.
4. **HiBob is an ATS with no native fetcher** (2 rows today: WINT, one other). Its careers
   site is an Angular SPA, so the universal scraper gets nothing. If it reaches 3+ rows,
   write the fetcher (ARCHITECTURE §6 recipe).
5. **`jazzhr`, `eightfold`, `iCIMS`, `SuccessFactors`** — unchanged from the last handoff.

---

## Open items — highest value first

1. **352 dark rows now carry a triage mode; ~212 are in tonight's hunt pool.** `triage_dark.py`
   classified every inactive row by failure mode (see `dark-triage <date>: <mode>` in notes):

   | mode | count | who repairs it | needs search? |
   |---|---|---|---|
   | `url-dead` 97 / `wrong-page` 76 | 173 | `listing_hunt.py` (19:00) | yes — slowest, may not resolve |
   | `page-empty` | 134 | *nobody hunts these* — page is live with genuinely no roles | no |
   | `extract-gap` | 33 | `repair_extract_gap.py` (19:00, before the hunt) | **no** — highest yield/minute |
   | `js-shell` 5 / `blocked` 5 | 10 | hunt, then `crack_walled` / Bright Data | partly |
   | `acquired` | 1 | manual — should be marked terminal | no |

   **The hunt is time-budgeted (200 min), so it will NOT clear 212 rows in one night.**
   Expect a trickle over several nights; `extract-gap` should land first since it needs no
   search. A row failing 14 nights running is genuinely dark and covered only by discovery.
2. **Phenom / Eightfold / iCIMS / SuccessFactors** — no native fetchers; they're read via
   the browser scraper when a listing URL is known. If any platform starts appearing 3+
   times in new discoveries, write a native fetcher (ARCHITECTURE §6 recipe).
3. **`CLAUDE_CODE_OAUTH_TOKEN` may expire.** Symptom: `LLM calls this run: 0` with a large
   `llm_failed_fallback` count in the digest audit. Re-run `claude setup-token` and reset
   the secret (helper: `israeli-jobs-private-notes/Set-Claude-Token.cmd`).
4. **SerpApi exhausted until 2026-09-01.** `audit_empty_rows` reserves 50 calls; resolution
   quality is degraded until then (DDG + Bright Data still work).
5. **2026-08-25 `render` (the split, the card, the `Render:` line — 1 Opus design critic + 4 attackers + 3 confirmers):** `digest.py` (1,444 lines at `60fae33`, derived and rendered in one loop) is now `jdtext.py` (text→structure, stdlib only) → `rolecard.py` (one card per role from the row + its ledger record; never raises; `cross_check` names shared-board / title-twin / display-collision / blurb-names-other) → `digest.py` (rendering + escaping only; `render_all` is run.py's one call, board and archive BEFORE the mail). Pure move proven byte-identical on 6 products, then each change with its enumerated diff (`tests/rehearse_render.py --golden/--cards/--real/--full`); a failed board/archive is not written (yesterday's page stays), a failed email ships a stub and burns nothing; two adversarial waves (4 attackers + 3 confirmers): 7 HIGH fixed and pinned, the last one (`_capped` joined into characters) found by wave 2 on the live store. The mail carries `- **Render:** board N cards[, hidden/degraded/shared-board] · archive N · email N`; alarms above the fold; `also listed as` / re-posted / archive `closed on` from the ledger; stage label total (BACKLOG 99), one blurb gate (100), one seniority vocabulary and every `israel.py` place labelled (119), `<`/`@`/blurb escaping in the mail. **Out of lane, approved:** `run.py` render block (one `render_all` call, `summary["render"]`). NOT finished: 142–146; morning check 2026-08-26: `- **Render:** board N cards` must reconcile with the board's row count, nothing on `Needs a look` from `render`. Record: `docs/sessions/2026-08-24-render.md`; spec ARCHITECTURE §7d; `docs/TAGGING.md` re-verified.
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

> **`docs` re-count, 2026-08-23 19:00 UTC** for item 1, from the working tree — the modes
> have moved since it was written and the shape of the work changed with them:
> **279 rows carry a triage mode** (`url-dead` 76, `page-empty` 124, `js-shell` 26,
> `extract-gap` 26, `wrong-page` 20, `blocked` 7), of which **159 are still inactive**. The
> `js-shell` class grew from 5 to 26 and `blocked` from 5 to 7, so the browser/unlocker
> path (`crack_walled`) now owns more rows than the table implies, and `extract-gap`
> — the cheapest class, no search needed — is down from 33 to 26. The snippet is
> `HANDOFF.md`'s own "did tonight's dark-row work reach the pool?" one-liner, now in
> `ARCHITECTURE.md` §5c.

## What the `docs` lane did NOT finish (2026-08-23)

- **`docs/MODULES.md` classifies, it does not move.** Nothing was relocated to a `legacy/`
  directory: 30 root modules are reachable from no workflow, no test and no live import, but
  moving a file is a code change and this lane is documentation-only. Whoever does the move
  owns the import fixes — start from the registry, and note that `ingest_research` and
  `probe_ats` are on the old "safe to delete" list while `retry_unreachable.py` (02:30
  daily) imports them.
- **`docs/check_docs.py` checks structure and existence, not truth.** It proves that every
  path a doc names exists, that every link resolves, that the cron table matches the
  workflows and that every root module is classified. It cannot prove a sentence is still
  true — only that the file it points at is still there. The 75→256 and 33→26 corrections
  above were found by hand, and that kind of drift will keep needing a reader.
- **SCHEDULING.md moved to `docs/decisions/2026-08-14-email-delivery.md`; nothing else
  was consolidated.** The
  automation inventory `docs/BACKLOG.md` asks for (one table covering Actions crons, the
  Windows scheduled task and by-hand runs) is not written — the Windows task
  `IsraeliJobs-Firmographics` is still documented only inside `ARCHITECTURE.md` §7.
- **No lane's section was filled in for them.** The lane rows in `docs/AGENT_BRIEF.md` say
  which doc each lane must update before pushing; the enforcement is a convention plus the
  linter, not a per-lane content check.
- **2026-08-25 `registry` (today's logs, the pending backlog, §2/§3 re-verified — 3 Opus attackers + 1 confirmation wave):** auto-expand rendered every aggregator seed (338 of 342 queued) for 17–25 s AFTER the LLM cap was spent (76 wasted min/run ×2 daily, `resolved 0` on 5 runs) and buried the 10 it did try under the posting's URL; the 02:30 chain erased listing-hunt's and Bright Data's segments on 9 rows nightly (`b3d1d49`); the mutation gate was cancelled at 45 min on every push. Shipped: aggregator seeds deferred + rotated (`cloud_state/auto_expand_seen.json`), `resolve_llm` ladder SerpApi→DDG→unlocker (`LLM_BD_SEARCH_CAP` 5) asked only with a page in hand (live: Upwind Security → comeet 49.004, 51/15 IL), 28 buried rows un-addressed; `retry_unreachable`/`bd_rescue`/`wayback`/`validate_empty` append instead of rebuilding the cell; `tools/mutate.py` derived subset + baseline-red exclusion + `--jobs`; census step no longer probes the ladder; rows: 76 converted (Qualcomm 37 IL, GE HealthCare 23, Fortinet 15), ten `alias-of` twins + Sckipio + `Tel Aviv` parked (877→865 active), `repair_extract_gap` gained the terminal exclusion it lacked. **Out of lane, disclosed:** `persist_state` STRATEGY +1, `auto-expand.yml` env/`--own`, `verdicts.TOKENS` +2. Wave 1 (3 Opus attackers) found and I fixed: `validate_empty`/`bd_rescue`/`wayback_rescue` selectors with no terminal exclusion (would have re-activated Primis Tech, kornit, Tel Aviv on Sunday), the LLM resolver admitting another company's board off search evidence (Similarweb→similartech; now grounded on the company's own page, Comeet via a browser read), a ghost node id reading as a KILL in the harness, and the resolver's bare `claude -p` (now `pipeline/llm.py::call_json`, sonnet, tool-less, schema). 2026-08-26 batches 0–1 (`d4e4cfc`, `8a4deac`): 92/62/63/74 + 7 mislabeled closures; the Saturday deep-validate cron is now the Sunday audit's Chromium rung (6), the audit's rotation key is committed (38/164), suspect verdicts re-arm the hunt (65), apply_resolved vetoes parked rows (56), the unlocker reports its error code and policy-closed hosts are never retried (110), corrupt caches are never overwritten (156). Batch 2 (`cff7ee3`): eightfold API rows from crack_walled (77), Questar a scrape row (79), 4 parent/subsidiary twins alias-of (194, 861 active), the slug rung built but off (178, 3/3 empty live); 78/80 measured, nothing to convert. NOT finished: batches 3–5 (durable pools 53/197/27/72/190/52; path-tenant 33/50/22/37/198/9/51; 117; 196/199 after a week of logs). Morning check 2026-08-31 (Sunday): `deep rung: N of M dark rows` in the audit log and `cloud_state/audit_seen.json` in that day's state commit. Morning check 2026-08-26: `tests.yml` mutation-gate green under 15 min; 02:30 log `validated N` with those rows keeping `scanned via brightdata`; 08:00 auto-expand < 10 min with `dfer (<reason>)` and `LLM-cracked N`; digest census step without `rung DOWN`; mail `Registry:` line = SeeTree only. Record: `docs/sessions/2026-08-25-registry.md`.
- **2026-08-24 `scraper` (error is not empty; the refresh in four processes; the scrape reaches the mail — three adversarial waves, 10 Opus sessions: 26 code defects fixed and pinned, 5 filed with owners, 2 accepted, ~30 doc corrections):** `scrape()` swallowed every navigation failure into `[]` (0 errors in 428 sites; a 403 night deleted a company's jobs), the refresh ran 112 min sequentially with one company unbounded, and the workflow's bare `stamp collect` erased any counts. Now `scrape_result()` separates ERROR (navigation, HTTP ≥400, HTTP-200 walls, blank renders) from EMPTY; `refresh_scrape_cache.py` runs a spawn pool (425 rows in 37 min locally), carries only on error, parks after 7 *observed* error nights, refuses mass-failure and mass-empty nights, terminates stuck children, writes atomically, and stamps `collect` with `rows scraped with_jobs empty no_il errors carried unprocessed parked workers minutes [alarm]` — printed in the digest audit (rehearsed end to end). Scoped local runs write nothing. **Out of lane, approved:** the workflow's re-stamp step deleted; `scrape rotted` added to `merge_csv_rows._TOOL`; `stages.alarms()` + four lines in `run.py`/`digest.py` so a stale or alarmed `collect` stamp is a bold `Stages:` line and a `::warning::` (closes BACKLOG 85). **NOT finished:** rot-parked page-empty rows never reach the hunt (`registry`, 84); `cache_new_rows.py` is a shim to retire (`docs`, 87); Port.io-type Comeet embeds lose DOM-only roles to first-hit-wins (`scraper`, 88); the first cloud run 2026-08-25 00:00 is the remaining proof — owner: whoever reads that morning's mail (`scraper` lane next session): the `collect:` line must reconcile per §5a; `(1d ago)` means it crashed and nothing was committed. Spent locally: BD 0, pipeline Claude 0; 10 Opus attacker sessions. Record: `docs/sessions/2026-08-24-scraper.md`.
- **2026-08-24 `ats-fetch`:** the Eightfold fetcher shipped 2026-08-23 answers 403 (or 404) on every real tenant; `fetch_microsoft` was already the working pcsx search and is now `fetch_eightfold` (Qualcomm 31–36 IL per call, paging bug fixed), `phenom` got its own `/widgets` fetcher (GE HealthCare 20 IL) — both wait on `registry` row conversions (BACKLOG 76); 25 of the 26 Workday `empty-board` rows were live tenants with 0 Israel roles, so `israel_scoped` fetchers no longer raise it and Dell (0 worldwide) raises `BoardEmpty`; the mail carries two `- **Boards**` bullets (`changed today: new/cleared`, then `standing:` counts) with reasons. NOT done: the row edits, BACKLOG 76-83. Record: `docs/sessions/2026-08-24-ats-fetch.md`.
- **2026-08-24 `company-intel` (one bounded cloud path; the mail says what it did — two adversarial waves, 6 Opus sessions, 17 wave-1 findings all fixed or filed):** `pipeline/run.py`'s two blocks are one call, `company_intel.enrich_for_run` (`pipeline/company_intel.py`) (never raises; ≤5 research calls in ≤10 min, ≤30 blurbs, first outage stops it, no strikes on an outage, `` blurbs retried monthly, facts read as prose when the blurb is missing, chips ≤48 chars); every reader/writer uses `union_store` (export ∪ sqlite, field-level merge) so the chain no longer re-buys the cloud's research (2 on 08-24) or truncates the export (19 at risk); a corrupt export is reported, never replaced; one `claude` seam (`shell` only on Windows; brace-safe JSON); the audit block carries `- **Company intel:** …` + `::warning::company-intel` (rehearsed: json / unknown / prose / fail / corrupt / missing / --no-llm). 940-record export committed. NOT done: chain retirement (BACKLOG 97), 29 duplicate groups (98), stage label (99, `render`); morning check 2026-08-25 = the `Company intel:` line must reconcile and `N newer than the store` must be 0 after the seed. Record: `docs/sessions/2026-08-24-company-intel.md`.
- **2026-08-24 `jd-text` (one ladder, a reason for every failure, the layer in the mail — 1 Opus design attack + 3 attacker sessions):** `pipeline/jdfill.py` is the library (native JSON for Workday/SmartRecruiters/BambooHR/comeet/Greenhouse-`gh_jid` → HTML → Unlocker; every outcome has a reason; timeout/5xx/BD-down stamp `transient` = retry tomorrow, not in 7 days; search URLs never spend a credit); the two `enrich_*_jd.py` scripts are ~60-line drivers over `run_backfill` and stamp `enrich` through `record_enrich` (union; the workflow step is now a gap-filler), so the mail's `Stage order:` carries `scrape_*`/`matched_*` and `- **Stages:**` says `bd-unavailable(…)`/`jd-massfail(…)`/`crash:…`/`no-report`; 16 guards; BD spent 3 requests. NOT finished: BACKLOG 105–113; tomorrow's mail is the proof (baseline `jd-fill: 93/153`, scrape 7, matched 0 with 4 wasted credits). New `ARCHITECTURE.md` §7a; record `docs/sessions/2026-08-24-jd-text.md`.
- **2026-08-24 `classifier` (one bounded seam, a reason for every verdict, the tier in the mail — 2 Opus design attacks + 5 attacker sessions + 3 confirmers; wave 1: 41 confirmed defects, 31 fixed and pinned, 7 filed; wave 2: 1 HIGH fixed (both-cohort quarantine), 1 regression of wave 1 fixed (`u0022Israel`), 6 guards added, 1 corrupt working-tree file rebuilt from HEAD):** bare `claude -p` was running **claude-fable-5** (~$0.58/call, 163 calls yesterday) with every tool on, the session persisted and the repo as cwd (`CLAUDE.md` + `CLAUDE.local.md` read into every call, 24,845 vs 4,633 tokens); now `seniority.Classifier` — one per run — calls `--model sonnet --tools "" --json-schema --system-prompt`, no shell, scratch cwd, a cap (300) and a minutes budget (60, timeouts charged), a breaker that reads the real 2.1.241 401 envelope and opens on the first auth/drift hit, per-cohort quarantine of a mass-NO/YES morning, keys `v2|company|title|jd|bare` (a bare verdict re-judged once text arrives, 107 closed; the 235 legacy rows read as bare, never purged locally — 116), `save_llm_cache` writes only changed rows, reasons in the step log, alarms on the bold `Stages:` line (12 fake-CLI modes + `--no-llm` rehearsed end to end, `tests/rehearse_classifier.py`; real: 19 sonnet calls, 4.3 min; A/B 25 hand-labelled: sonnet 18/19, fable 17/19, haiku 15/19). Israel filter is per posting by design (70-company sample 3,370→674, genuine loss ≈0.15 %, BACKLOG 118); hyphen/apostrophe/district forms and 40 names added. **Out of lane, approved:** `git diff --stat` — `run.py` 32 lines (+21/−11), `store.py` +7, `digest.py` +1, `daily-digest.yml` +6/−3 (the CLI pinned `@2.1.241` **and the conflict path's `cp -r` → `cp -rT`: it was nesting a `cloud_state` directory inside `cloud_state` and committing origin's store on every conflict day — 125, the seven other workflows still do**). Follow-up 2026-08-25: `pipeline/llm.py` is the shared seam (117 half), alarms render above the fold (127), `cp -rT` in all five workflows (125), a behavioural `run.py` guard (132). NOT finished: 116, 118–124, 126, 128–130; the ubuntu start-up time is the unverified number — the first digest after this push (2026-08-26 05:00 UTC) is the proof: `classify:` line, `Decision paths` summing to `Israel-matched`, no `classify` text on `Stages:`. New `ARCHITECTURE.md` §7b; record `docs/sessions/2026-08-24-classifier.md`.
- **2026-08-25 `infra` (one delivery path, the mail says when a run broke — 3 Opus attackers + confirmers):** nine hand-copied commit/conflict shell blocks (last-writer-wins on a checkout-era copy: `0b41823` deleted listing-hunt's `repair` stamp, so the mail read `repair: never run`) are one `persist_state.py commit --own …` step, `if: always()`, gated (JSON/sqlite/`check_invariants`), merging each file by its own rule on a conflict (stamps per key, caches per company with deletions honoured, lists by key, the registry base-aware); a lost digest is now a dated failure notice in `digests/latest.md` (`persist_state.py outcome`, committed alone from a fresh worktree) so the relay mails it; failed pre-steps, every stage, and yesterday's post-pipeline failures are bold `Stages:` lines; the log is grouped, crashes are `::error::` + `out/crash.json`, the run page has a summary; the inbox relay now polls 06:17/07:17/08:17/10:17 (mail ~06:20, was ~08:45). Rehearsed: `tests/rehearse_infra.py --all --golden dcca442` (only `+ Stages: repair never ran` differs). NOT finished: BACKLOG 153–170 (167–169 are today's mail oddities; 170: the mutation gate has timed out on every push since f720627 — pre-dates this lane, registry owns the fix); the scraper test `test_refresh_shrink_abort…` is red on origin since `f720627` (date-rotation flake, 158). Morning check 2026-08-26: the inbox issue at ~06:20; `Stage order:` shows `repair: <date>` after tonight's 19:00 hunt AND after the 20:00 auto-expand; no `workflow step` line on `Stages:` unless a step really failed. Record: `docs/sessions/2026-08-24-infra.md`; spec ARCHITECTURE §4/§5.
- **2026-08-25 `roles` (the role record gets an owner, a text ledger and a mail line — 1 Opus design attack + 4 attacker sessions, wave 2 confirmers; rehearsed as tomorrow's run before push):** three postings sat under two company names in the committed store (Port/Port.io both ACTIVE: one posting on the board twice) and nothing compared posting identity across companies; now `pipeline/roles.py` — `cloud_state/roles.jsonl` + `roles_text.jsonl` (one line per role, never deleted: status/episodes/reposts/class/tags/attribution/sent), sqlite ∪ ledger reconciled at open (rehydrates rows and `sent` marks sqlite lost; a corrupt file is reported, never overwritten), one posting under two names kept ONCE (`claim conflicts N (A<-B)` in the mail, loser `superseded`, never deleted; store sweep for parked halves), judged once per role (BACKLOG 124 closed; `merged-copy` in `Decision paths`), closure/reopen/repost recorded only where the run looked, a mass-close HELD and alarmed. Mail: `- **Roles:** open · closed today · reopened · reposted · merged-copy · ledger N = store N` + alarms on the bold `Stages:` line. Dry run 2026-08-25 (no LLM): 862 scanned, 4,844 Israel-matched, paths reconcile, `claim conflicts 2 (Port<-Port.io, HP<-HP Indigo)`; golden HEAD-vs-tree differs only by the collapse. **Out of lane, disclosed:** `run.py` role-selection block (+21/−14: classify moved out of the fetch loop into the seam, 4 hook lines), `digest.py` 3 render one-liners, one classifier assertion retargeted (`roles.classify_grouped(` ×2). Seeded `cloud_state/roles*.jsonl` from the committed store. NOT finished: BACKLOG 132–139 (retire `matched`, the 13 registry alias groups, a jsonl row-merge on the conflict path, discovery roles never close); `docs/AGENT_BRIEF.md`'s "tags are not stored" paragraph and `docs/TAGGING.md` are now false (`docs`/`render`). Morning check 2026-08-26: the `Roles:` line must say `ledger N = store N` with no `!=`/`corrupt`/`mass-close` on `Stages:`, and `cloud_state/roles.jsonl` must be in that day's state commit. New `ARCHITECTURE.md` §7c; record `docs/sessions/2026-08-24-roles.md`.
- **2026-08-25 `discovery` (the run audit; what the mail published under a city's name — 2 Opus planners + 3 attackers + 1 verifier, 0 credits):** the 05:36 run put `### Tel Aviv` (an aggregator row: a Telegram post with no company line → city as employer → `listing_hunt` activated secrethunter's city board, 7 of 81 board roles) and `### Nisha Pro` (a staffing firm our own firmographics had classified) in the mail; LinkedIn blocked the runner mid-walk and five queries printed the false 'raise LINKEDIN_GUEST_PAGES' tripwire while a blocked request was counted nowhere. Six commits: recruiters (+slug), `secrettelaviv.` host, the missing-company shape, one exit-reason string + `blocked=`, a truthful summary line, and the cache/queue writes as chokepoints (163 agency cards and 13 queue entries leave tomorrow). §1a inverted: the pool is at 111% (53% this lane's own dataset) and the resolver queue IS the bottleneck (341 names, 0 resolved in 5 runs, 10/run buried as `empty` on a JS shell — BACKLOG 177). NOT finished: the `Tel Aviv` row/cache/7 ledger roles (registry+roles, 167), the false `linkedin-targeted: nothing for 3d` alarm from 08-26 (179), 178–187. Morning check 08-26: `[linkedin] … blocked=`, no `### Tel Aviv`, `cache: dropped ~163 agency cards`. Record: `docs/sessions/2026-08-24-discovery.md` (2026-08-25 section).
