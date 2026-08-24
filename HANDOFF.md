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

- **2026-08-24 `registry` (7 adversarial waves, 15 commits, one entry):** every activating write path now needs the CANDIDATE page to name the company; the tenant string is evidence in neither direction (it refused 7 of 9 known-good rows on crack_walled's own platforms while calling Novartis-for-Riskified a plain `ats`). Fixed across `crack_walled`/`audit_empty_rows`/`deep_validate`/`repair_dead_urls`, each with an end-to-end guard that fails on the prior commit and carries a positive control. Wave 7 found two of these were regressions introduced by wave 6's own fix, which is why the guards are no longer `inspect`-based. New read-only `registry_health.py` (census + row-deletion diff, computed ownership matrix, ladder probe, ATS wire/build queue) — run it first, it answers section 2's five questions. Guards live in `tests/test_registry.py`, NOT `test_units.py`: four sessions committed a stale copy of that file over them (7, 18, 22, 15 guards) and pytest stayed green every time. There are **six** tools that write `active`/`api_url`, not the four or five earlier versions of this line claimed - count them from the `activates?` column of ARCHITECTURE section 2's ownership matrix, never from a hand-written list, which is exactly how the sixth was missed for eight waves. The last one wired in was `repair_extract_gap` (`c4f9a5d`), which runs 30 minutes BEFORE `listing_hunt` in the same 19:00 job, forces `SCRAPE_ASSUME_IL=1` (the weakest evidence any activating path uses), and had only `is_foreign` - six of its 40 rows were on an ATS host, one of them putting `Sight Diagnostics` on the board `Sight Sciences` is already active on. A seventh tool, `apply_resolved.py`, writes `api_url` with no identity check of its own (its gate is upstream in `resolve_llm._verify`): it cannot activate a row but it can re-point an active one. **REBUILT 2026-08-24 (later the same day), and the rebuild found the enumeration was HALF WRONG.** Two code shapes write this registry: `fr[3]=`/`fr[4]="true"` (8 modules) and a whole-row literal `[name, plat, tok, api, "true", note]` (14 modules). Nine waves only ever saw the first, because the guard that finds writers walks the AST for a subscript assignment to index 4 and a list literal has none. **Five of the fourteen run on cron and had no identity check of any kind** - `bd_rescue`/`retry_unreachable` (02:30), `wayback_rescue`/`validate_empty` (Sun 04:00), `auto_expand` (08:00 and 20:00); driven against the pre-fix commit, four of them activate `Bancor` onto The Bancorp Bank's iCIMS board. All now gated. The gate is `pipeline/identity_gate.py` (declared plumbing change; affects `ats-fetch`, `scraper`, `infra`), which also killed both import cycles and the four lazy in-function imports that hid them. **Never count the write paths by hand** - `python -m pytest tests/test_registry.py -k every_registry_writer` derives them, and `python tools/mutate.py --all` (41 text-preserving mutations, coverage derived per writer) asserts the gates are real; its first sweep found 4 fake guards and its `must_be_killed_by_behavioural` rule found 3 more whose only witness was a source-string match. **NOT done, filed with the numbers:** unifying the terminal-state definitions costs 10 rows of coverage (items 47/48), and ARCHITECTURE section 2 was cut to 30% of the document (item 40, closed 2026-08-24; post-mortems live in the session doc). **Closed out after 9 adversarial waves against a stated bar** (does it write wrong data or silently lose coverage?), not a green verdict — the waves stopped converging once most findings were regressions from the previous wave's fixes; `docs/sessions/2026-08-24-registry.md` ends with why, and what to do instead. Last severe fix: `crack_walled`'s pool was the literal string `unsupported ATS`, which `deep_validate` owns and `notes.replace_own` deletes — one all-dark Saturday took the pool 25 -> 0 with every guard green; membership now derives from the row's host too, plus rotation. 230 tests. **NOT done, all outside this lane:** `registry_health`'s alarms still reach no email and it is in no workflow (`docs/BACKLOG.md` 12/13/23), and `company_identity.verdict()`'s ATS-subdomain hole is the root cause of most of the above (item 9). Full write-up incl. waves 3-7: `docs/sessions/2026-08-24-registry.md`.
- **2026-08-24 `registry` (rebuild waves 3-5, capped and complete):** ten more verified blockers found and fixed by table-triage, the largest: a held careers page could ADMIT any board it merely embeds (Cogniteam onto Riskified's greenhouse, end-to-end on the Sunday cron) — closed by `identity_gate.embedded_board_ok` at all three `extract_ats` callers (`validate_empty`, `bd_rescue`, `wayback_rescue`); a page can refuse a board, never vouch for one. The hunt-pool selector is now `listing_hunt.HUNT_POOL`, imported by `registry_health` and pinned against `check_invariants.POOL` — never retype a pool regex. 267 tests; `python tools/mutate.py --all` = 89/89 killed, coverage derived per call site incl. M8 argument mutations. Accepted visible costs and residuals: `docs/BACKLOG.md` 58-69; waves 3-5 record incl. the tripwire judgment call: `docs/sessions/2026-08-24-registry.md`.
- **2026-08-24 `registry` (extended program waves 6-7, closed on a GO):** wave 6 found and fixed four blockers in the consolidation itself (a pure-filler parenthetical made bare `israel` an identity target; the fourth ungated conflict-recovery sibling plus the one non-atomic registry writer; unpinned TERMINAL tokens; consumer-side pool selectors with no behavioural guard). Wave 7 confirmed the fix batch clean end-to-end and the program closed: 274 tests, 101 mutations killed with the sweep blocking every push in CI, all nine committing workflows invariant-gated, every pool predicate tool-owned. Deferred with reasons: registry_health-to-reader (12/13) and the acquired-by column (50/61). Record: docs/sessions/2026-08-24-registry.md.
