# Session handoff — 2026-08-23 (morning)

Read `ARCHITECTURE.md` first (system model, invariants, runbooks). This file is the
"what just happened / what to watch / what's next" layer on top of it.

## 0. 2026-08-23 morning session — what was wrong and what was done

The brief was to make the six-step flow actually work end to end: fix invalid companies,
pull from LinkedIn/Indeed/Telegram/company sites, triage newly discovered companies, give
every relevant role its full description and tags whatever its age, email the last 48h, and
keep the board to live roles with everything else archived.

**Sixteen defects, A–P below. Every one of them had a green workflow and a plausible log
line** — that is the whole character of this codebase's failure mode, and it is why the
morning was spent reading outputs rather than exit codes. Two were costing coverage every
day (Indeed had returned zero records since it was wired up; four fetchers never carried a
description). Three were about to publish other companies' roles under Israeli names (86
Israel roles between them). One had discarded an entire completed run — 894 companies, 187
LLM calls, a built board — over a single false positive in the gate that guards the commit.

### A. Nothing ever gave a Workday/SmartRecruiters/BambooHR role a description
Their LIST responses simply have no description field — 120 active companies. So those
roles reached the *classifier* as a bare title (the LLM tier exists to read the description
and judge, and had nothing to read) and reached the *board* with no requirements, no skills
and no tags. `enrich_scrape_jd.py` only ever covered scrape-source companies.
- `pipeline/jdfill.py` fetches the JD from the posting's own URL before classification,
  title-gated and wall-clock budgeted (`JDFILL_TIME_BUDGET_MIN`).
- `enrich_matched_jd.py` does the age-blind version over the `matched` table itself —
  every role we ever accepted, any source, any age — with the Bright Data fallback.

### B. The store erased those descriptions every morning
`upsert_matched` wrote `job.get("description") or ""` on each re-sighting, so the day after
a JD was backfilled the same description-less Workday response overwrote it with "". A
description is now only ever replaced by a longer one.

### C. The board dropped live roles into a page headed "expired or filled"
It selected `first_seen >= today-14d`. A role open for three weeks left the board while
still open. The board is now the set of roles still present on their employer's careers page
(`_alive`), with no per-company cap; the archive is exactly the roles that are gone.

### D. Four of the five "repairs" from the overnight run pointed at other companies
`repair_extract_gap` re-scrapes a dark row's STORED url — which is usually the hunt's
documented best *guess*. Hours after the hunt refused fireflyspace.com for FairFly on
identity, the repair pass activated it: 25 Firefly Aerospace roles about to publish under
FairFly's name. Also MyndYou→MyndSolution (a BPO), SeatPick→djinni.co (an aggregator), and
both IAI alias rows→a product page whose "6 jobs" were nav links.
- Every path that flips `active` to true now consults `pipeline/company_identity`
  (`repair_extract_gap`, `crack_walled`, `deep_validate`, `audit_empty_rows`), guarded by
  `test_every_activation_path_checks_company_identity`, which walks the AST for
  `row[4] = "true"`.
- Two holes in the identity check itself: `verdict()` scored `time.com` a clean **match**
  for "Time To Know" (the token IS the whole domain), and `page_mentions_company()` then
  confirmed it because TIME's careers page contains both "time" and "know". A `weak`
  verdict now needs the name as a phrase, and matching is per token.

### E. Indeed has returned zero records since the day it was wired up
Every Bright Data snapshot: `dataset_size: 0, error_codes: {"rate_limit": 15}`. The step
printed "[indeed] 0 records" and exited 0. Indeed is now read through the Web Unlocker
directly (`discovery_daily.indeed_search`, one request per query, five queries), and
`pipeline/sources.py` records what each source returned so a source that goes quiet — or
has never produced — is a workflow warning AND a line in the digest's own run audit.

### F. The push-conflict recovery reverted other workflows' state
Every workflow copied its own checkout-era `cloud_state/` back over origin after a
`git reset --hard`, silently reverting every `seen.db` row committed in between (HANDOFF
open item 7). Each job now restores only what it owns; `scraped_cache.json`, the one
genuinely shared artifact, gets a three-way merge (`merge_json_cache.py`).

### G. The firmographics were researched and rendered nowhere
919 profiles sat in the gitignored `state/seen.db` while the cloud digest — the only thing
that renders them — had an empty table. They now render as company-fact chips on every
board and archive card and under each company in the email, and the two stores converge
through `cloud_state/firmographics.json`, a sorted export git can merge.

### H. 32 active rows were a second row for a company we already scan
50 identity groups had more than one row; 32 of those pairs pointed at the **identical**
URL. "Intel", "Intel Israel" and "Intel Corporation" all fetched the same Workday tenant.
`merge_key` normalizes only a trailing corporate suffix, so "intelisrael" never collapses
into "intel": the board listed every Intel opening three times and three fetches paid for
it. Parked with an `alias-of <canonical>` note, which `check_invariants` treats as TERMINAL.
The ~15 groups whose rows point at DIFFERENT urls (Amazon/AWS/Amazon Israel, Applied
Materials, Microsoft, PayPal, Samsung, Siemens) genuinely cover different pages and stay.

### I. Oracle HCM returned a confident zero for any large employer
`fetch_oraclehcm` walked the newest 500 requisitions and stopped. JPMorganChase posts
7,354, so its Israel roles were never in that window. The CE API takes `keyword=` the way
Workday takes `searchText`; the fetcher runs both passes and dedupes. Dell 2 → 8 Israel.

### J. The consent banner was being shipped as job openings
Ten companies had cached "Strictly necessary cookies", "Manage Consent Preferences",
"Cookie List", "Heading 4". "Analytics Cookies" carries an analytics signal, so it reached
the LLM tier as a candidate role. `fetchers.clean_scraped` filters page chrome on READ.

### K. One false positive withheld the entire day's digest, board and email
The 05:00 run scanned 894 companies, made 187 LLM calls, fetched 20 JDs inline and built a
board — then `check_invariants` check H failed on **one** row and the whole run was
discarded. The row was fine: check H normalized only the COMPANY side of the comparison, so
"G-STAT" became `gstat` while the slug stayed `g-stat`. Same for Port.io, Checkout.com and
"EY" (two letters cannot carry identity). Its slug regex was also non-greedy, so a
requisition number inside the title ended the match before the employer:
`business-data-analyst-**241239**-at-experis-israel`.

Three changes: `company_identity.url_names_other_company()` normalizes both sides;
`fetch_discovery` drops mis-attributed cards **at ingest**, where the 147-row incident came
from, so one bad card can no longer reach the commit gate; and check H is a **warning**.
A guard that withholds the day's product to report one bad row is worse than the row.

`check_invariants` also crashed on its own message — it prints violations through a cp1252
stdout, and a Hebrew company name in the text describing the problem killed the gate.

### L. A navigation menu is not a job board
`SCRAPE_ASSUME_IL=1` makes the scraper treat every card on a page as an Israel role. So
`iai.co.il/solution/research-academy-space/` "verified 6 IL" — "Domain Operations", "Press
Releases" — and was activated twice in one morning. Adcore's row was a BLOG POST whose three
"jobs" were article titles. `looks_like_a_job_listing_page()` asks whether the URL even
claims to list openings; of 417 active scrape rows exactly ten failed, six of them wrongly
active. It gates all four activation paths.

### M. Sixteen entrypoints could die on their own success message
`merge_csv_rows` prints `"N rows changed → M applied"` plus a company name through a cp1252
stdout. The UnicodeEncodeError lands AFTER the merged file is written, and in the cloud
conflict path the call is `|| true` — so the process dies on its summary and the run's
changes are discarded with no error anyone reads. All 16 root entrypoints now reconfigure
stdout/stderr to UTF-8 with `errors="replace"` (HANDOFF §4d item 5).

### N. Eight rows were fetching another company's ATS tenant
An ATS row's identity is its TENANT SLUG. Verified by fetching each and reading the roles
back: **SimilarTech** pointed at greenhouse `similarweb` (65 jobs, **25 in Israel** — and
Similarweb has its own row, so they were queued to publish twice, once under a company whose
domain no longer resolves). **ASTERRA** pointed at `asteralabs` — Astera Labs, a San Jose
semiconductor company — **30 Israel roles**. **"Moonsite - Moonsoft Development Ltd."** had
`jobs.ashbyhq.com/moonactive`, i.e. Moon Active's board, **23 Israel roles**. Donisi
Health→`oshihealth`, Anonybit→`anonyome`, Tritone→`tranetechnologies`, More
Foods→`usfoods`, Alike Health→`exactcare`: all real, all currently empty of Israel roles.
None had reached the board yet.

The same audit found coverage we were missing: **Moon Active** had been on a Comeet endpoint
returning 0 for weeks while its board moved to Ashby (33 jobs, 24 Israel, including a
Marketing Data Analyst), and **Armis** was on a SmartRecruiters tenant showing 2 roles while
greenhouse `armissecurity` — reached through OTORIO's row, because Armis acquired OTORIO —
had 18 (8 Israel, including a Senior Data Analyst).

`check_invariants` C3 warns on the shape and can only ever warn: a rebrand or acquisition is
indistinguishable from a mis-resolution. Momentis Surgical really does post under `memic`,
Itamar Medical under `zoll`, SentinelOne under `sentinellabs`. Thirteen rows still match and
were each checked by hand today — **all thirteen are correct**, so do not re-audit them:

| row | endpoint | why it is right |
|---|---|---|
| Ibex Medical Analytics | `ib1.recruitee.com` | its own abbreviated tenant; 3 IL |
| 7AI | ashby `sevenai` | its own spelled-out tenant (Boston HQ, 0 IL today) |
| SentinelOne | greenhouse `sentinellabs` | SentinelLabs is its research arm; 12 IL |
| Momentis Surgical | greenhouse `memic` | rebrand (Memic → Momentis) |
| Itamar Medical | workday `zoll` | acquired by ZOLL; 4 IL, all Caesarea/Herzliya |
| ClearML | `clear.ml` | the TLD carries the "ml"; page names the company |
| Sight Sciences | `recruiting2.ultipro.com/SIG1008SIGH` | UltiPro tenant code |
| Secret Double Octopus | `jobs.jvpvc.com/jobs/secret-double-octopus` | JVP portfolio board, scoped by slug |
| HUB Security | `comeet.com/jobs/hub-technologies` | hubsecurity.io 301s to hub-technologies.com |
| onsemi / Verint / Dell / Fortinet | opaque Oracle HCM tenants | tenant ids are not names |

The warning is where the NEXT one shows up.

### O. Five "companies" were leaked job titles, and Imperva failed 100% of its fetches
Discovery writes the employer field straight through, and sometimes that field is the whole
posting headline: "Data researcher - Navina", "Data scientist engineer - Fetcherr",
"Sql developer - SkySoft Solutions By Commit", "Engineering team lead- data & AI platform -
everc", "my team" — all ACTIVE, all fetched daily, and in each case the real employer already
had its own row. `listing_hunt` now skips names `looks_like_junk` recognises rather than
searching for a careers page for a non-company (it had just returned
`remoterocketship.com/company/guildmortgage` for "AppSec" and `usajobs.gov` for "ICE").

Separately, four rows have been failing every fetch for as long as the audit block has
existed, with the same names each time — which is exactly why nobody looked. **Imperva** was
`ats_platform=workday` pointing at its own careers HTML, so every run POSTed a Workday body
to an HTML page. Finaloop's Recruitee tenant 404s, Bit's Ashby slug 404s, Comcast's Workday
tenant returns 410 Gone. A row that fails 100% of the time never changes, so it never reads
as a regression; check C2 now warns when a native-ATS row's endpoint is not on that ATS.

### P. An Israeli careers page writes "תל אביב"
`scrape_universal` has always recognised Hebrew place names and stamps the matched text as
the role's location; `pipeline.israel`, which makes the keep/drop decision, had none. Zero
roles are lost today (scraped cards fall back to the literal "Israel" and Indeed sets
`country_code=IL`), but it is a latent hole on a path that just became busy. The scraper's
regex is now DERIVED from both lists instead of keeping its own eight-name copy.

### Q. A scraped location was the card around the place, not the place
`_loc_from_ctx` took a fixed 12-character window either side of the matched place name.
Both ends land mid-word, so the location became whatever the card had next to it: rows on
the board today read `Apply       Tel Av` and `d Scientist Haifa`. The window starts at the
place name now and stops at a word boundary, and button words next to it are stripped.
**The stored locations only change when the cache is rebuilt** — the 00:00 UTC
scrape-refresh — so the board shows the old strings until tomorrow morning.

### Also
- 87 rows carried a truncated triage mode (`page-emp`, `page-e`, `pa`) that no pool matches;
  all restored, and `check_invariants` check F2 warns on the next one.
- `pipeline/stages.py` (written last session, never wired) is stamped by the repair, collect
  and expand workflows and read by the digest, which now says in its audit when a
  prerequisite stage did not run today.
- A scoped `--only`/`--limit` run no longer overwrites `cloud_state/stale.json`.
- The email is capped at 40 roles, and an undated role at a company we are scanning for the
  FIRST time is board-only — 336 companies were activated overnight and their whole back
  catalogue would otherwise have read as "posted in the last 48h".

## What happened to today's digest runs

The 05:00 scheduled run **failed** — it is still in the Actions history, and it is the one
described in §K: 894 companies scanned, 187 LLM calls, a board built, and then the invariant
gate rejected one false-positive row and the whole run was discarded before it could commit
or publish.

Everything after that was manual (`workflow_dispatch`). Each was cancelled and re-dispatched
as another defect turned up — an email that would have printed its own escape characters, a
role that would have been listed in two sections, eight rows fetching another company's ATS
tenant. Cancelling before the `Mark digested roles as sent` step is what makes that safe:
nothing is committed and no role is burned. The cancelled records were deleted per
`CLAUDE.local.md` §3, which is why the history shows the failure and then a single success.

If you need to do this again: cancel only BEFORE mark_sent, or the roles in that run's email
are marked delivered and the next run will not include them.

## Watch list for the next session

0. **75 active companies have an all-time-high job count of ZERO** — including Adobe,
   Broadcom, PayPal, Outbrain, At-Bay, Snyk, Deel, Capital One, Analog Devices, XM Cyber,
   Explorium, AI21 Labs, Frontegg, Aporia, Vayyar. Their endpoints answer correctly and
   return an empty board, so nothing errors and nothing is flagged: greenhouse `outbraininc`
   replies `{"jobs":[],"meta":{"total":0}}`. These companies are obviously hiring, so the
   tenant is stale — they have moved boards, exactly as Moon Active had (its Comeet endpoint
   returned 0 for weeks while 33 jobs, 24 in Israel, sat on Ashby).

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
   day. HANDOFF §4d item 3 wants this anyway ("one identity layer").
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

# Previous handoff — 2026-08-22

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

## 1b. Who re-checks a parked row — the ownership matrix

Every inactive row must be owned by at least one *recurring* job, or it is permanently dark.
Verified 2026-08-23 by tracing each scheduled entrypoint's row filter (17 rows were owned by
nothing; now 0). **If you add or narrow a row filter, re-run this check** — the snippet is in
§5. Ownership is by note content, not by mode:

**Update 2026-08-23 — `page-empty` rows are ACTIVE now.** They were inactive, which meant a
role posted at one of them waited for the next triage cycle to be seen. But a `page-empty`
row has a *validated, working* careers page that simply has no openings today: that is a
healthy daily source, not a dark row. 130 were activated and are scraped every day like any
other company. Two rules follow, both now enforced:
- **Empty is not broken.** `refresh_scrape_cache` used to park any active scrape row that
  came back empty 3 days running — in this market a company can have no openings for a
  month. Empty rows are now NEVER parked; a 45-day streak only asks triage to re-read the
  page (it can tell "no openings" from "openings we fail to extract") and the row stays
  active throughout. Only ERRORS park a row, at 7 days.
- Consequently the table below applies to rows that are still `active=false`.

| tool | cadence | claims rows whose note matches | re-opens the hunt? |
|---|---|---|---|
| `triage_dark` | daily 18:00 | `no listing found` / `no IL listing` / `no ATS detected` / **`dark-triage`** | yes — its rewrite drops the old `page-empty` stamp |
| `listing_hunt` | daily 19:00 | the wide parked-shape regex, **minus** `page-empty` | — |
| `repair_extract_gap` | daily 19:00 | `dark-triage …: extract-gap` | activates directly |
| `probe_candidates` | daily 05:00 | `monitored candidate` / `host documented` / `no IL listing` | yes — `_wake_note` strips every stale segment |
| `crack_walled` | daily 19:00 + weekly | `unsupported ATS` | — |
| `scan_dead_domains` | daily 05:00 | liveness only — **never looks at roles** | no |
| `audit_empty_rows` | weekly | `verdicts.in_pool` + not audited in `AUDIT_TTL_DAYS` (30) | activates directly |
| `deep_validate` | **weekly Sat 04:00** | `in_pool` + `_revalidatable` | activates directly |

Two traps this matrix exists to prevent, both of which were live:
- **An inert wake.** `probe_candidates` cleared `listing-hunt|crack-walled` but not
  `dark-triage`, so `listing_hunt._triaged_page_empty` still excluded every woken
  page-empty row: 105/105 wakes went nowhere. A wake must clear *every* stamp that any
  downstream filter excludes on.
- **Note erosion retiring a row from its own pool.** Each re-stamp trims the base note to
  fit 220 chars; once the original verdict eroded (`no IL listing; monitored candidate` →
  `no `), the row matched no pool at all. `triage_dark.TARGET_NOTES` therefore matches its
  **own** `dark-triage` stamp, which makes it self-sustaining.

## 1c. The 2026-08-23 night: dead capabilities and fabricated data

Two bug classes dominated, and both are **invisible from the outside** — the workflow is
green, the step prints a plausible summary, and the coverage simply never happens.

**(a) Capabilities that were wired but had never executed once.** Check for these first when
a tool "runs" nightly and nothing ever improves:

| what | why it never ran | how to notice |
|---|---|---|
| `crack_walled` | `_budget` / `_t0` used in the loop, never defined → `NameError` on the FIRST target | step is `continue-on-error`, so the run is green and prints only its header line |
| `refresh_scrape_cache` rot-parking | `_write_csv_rows` (undefined) on the parking path — raised AFTER the cache was written | cache updates fine; no row is ever parked |
| `SCRAPE_VIA_UNLOCKER` | set in **no workflow**, so `scrape_universal`'s residential fallback never fired | every bot-walled page silently scored "no roles" |
| hunt's Bright Data creds | absent from the hunt step, so `google_via_unlocker` could not run | invisible whenever DuckDuckGo returns empty |
| `hunt_one(mode=...)` | passed by the caller, **never read** in the body | docstring described strategy routing that did not exist |

`python -m compileall` cannot catch the undefined-name ones — they are runtime lookups —
so `test_no_script_references_an_undefined_name` now walks the AST of all 82 modules.
**If you add a tool, also add its env to the workflow, and confirm it did work by reading
its output — not by the step's exit code.**

**(b) Fabricated URLs outliving their verification.** `crack_walled` guessed
`https://careers.<domain>/careers?location=Israel` and persisted the guess as the row's
`api_url` even when verification failed. 43 rows ended up pointing at hostnames with **no
DNS record** (`careers.pliops.com`, `careers.tevapharm.com`, `careers.lili.co`), and every
later tool honestly re-tested the fabrication and logged another "unreachable" verdict.
Four confident-looking verdicts, all describing a page that never existed.

- **NXDOMAIN cannot be rendered, unlocked or cracked** — there is nothing there. It is the
  one failure that *only* search can fix, which is why `repair_dead_urls.py` runs BEFORE
  the hunt. Repairing the address is also what reveals the real ATS: Lili and Shortical
  both turned out to be on **Comeet**, natively supported, while labelled "unsupported ATS
  phenom" purely from a page signature.
- **Never persist an unverified address.** A wrong URL is worse than no URL: it looks like
  data and it launders itself through every downstream verdict.

**(c) "There are Israel jobs here" is not "these are THIS company's jobs."** The hunt
activated a row from any page yielding ≥1 Israel job. `pipeline/company_identity.py` now
gates activation. Beware over-correcting: `careers.ti.com` IS Texas Instruments and
`amazon.jobs` IS AWS, while `arberobotics.com` is NOT Tamar Robotics. Generic industry
words ("robotics", "financial") are not identity, and a much shorter domain that merely
prefixes the name ("rad" in "radlogics") is not either. When the domain is only suggestive
the verdict is `weak`, and `page_mentions_company()` — does the fetched page actually name
the company — settles it. That check beats every domain heuristic; prefer it.

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
3b. **The notes column is an append-log, so row-level merging is not enough.** On 2026-08-22
   the 14:00 hunt committed a `row-merged state` whose row versions predated the evening
   triage: `merge_csv_rows` applied its rows wholesale and the `dark-triage` segment
   vanished from **351 of 352 rows** (the hunt pool then computed to literally 0). The merge
   is now segment-aware (`_merge_notes`, keyed by owning tool). **If you add a new verdict
   token, add it to `_TOOL` in `merge_csv_rows.py` too** — an unrecognised segment is keyed
   by its first 28 chars, so two different runs of it collide and one is dropped.
   Guarded by `test_merge_unions_note_segments_from_both_writers`.
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
| 19:00 | listing-hunt | repair-extract-gap (35 min) → hunt (200 min) → walled-ATS re-crack (60 min) |
| Sun 04:00 | audit-coverage | wayback, empty cross-validation, full re-audit, liveness, re-crack |

## 4. Open items — highest value first

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
- **Orphan check — run after touching ANY row filter** (§1b). Must print 0; a non-zero count
  is companies no recurring job will ever look at again:
  ```bash
  python -c "
  import csv,re
  T=re.compile(r'no listing found|no IL listing|no ATS detected|dark-triage',re.I)
  S=re.compile(r'defunct|domain-dead|recruiter|duplicate|redundant',re.I)
  P=re.compile(r'monitored candidate|host documented|no IL listing',re.I)
  rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>=6]
  dark=[r for r in rows if r[4]=='false' and 'dark-triage' in (r[5] or '')]
  orph=[r for r in dark if not ((T.search(r[5]) and not S.search(r[5])) or
        (P.search(r[5]) and 'domain-dead' not in r[5] and (r[3] or '').startswith('http')))]
  print(len(orph),'orphaned of',len(dark),'dark'); [print('  ',r[0]) for r in orph[:10]]"
  ```
- "Did tonight's dark-row work reach the pool?" — the hunt pool should be non-zero and
  shrink over successive nights:
  ```bash
  python -c "
  import csv,re,collections
  rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>5]
  c=collections.Counter(m.group(1) for r in rows if (m:=re.search(r'dark-triage [0-9-]+: ([a-z-]+)',r[5])))
  print(sum(c.values()),'triaged:',dict(c))"
  ```
  **A count of ~0 here means a concurrent writer clobbered the notes column** — check the
  most recent `row-merged state` commit and see §2.3b before re-running triage.

## 6. Session hygiene reminders

- Commit as `ajil-bot`; push over the deploy key (plain `git push`), never `gh`-authenticated
  HTTPS. Avoid `gh workflow run` on the public repo; if unavoidable, delete the run record.
- Don't `git add -A` — a parallel session's work lives in this tree.
- Prefer letting the crons run over manual dispatches.
