# Architecture — how jobs get pulled, verified, and delivered

> Working on this after a break? Read **`HANDOFF.md`** first — recent changes,
> known traps, what's running, and the open-items list. This file is the
> durable system model.

## 0. Start here: what the user actually receives

Two deliverables, both produced by the **digest run** (the 05:00 UTC GitHub Actions
workflow `daily-digest.yml` — everything in this system runs as GitHub Actions cron jobs,
no server):

1. **A daily email** — only roles **new in the last 48h**, grouped by company. Delivery is
   keyless: the digest is posted as a GitHub issue in the *private* repo
   `AnalystJobsIL/inbox` with a `cc @owner` mention, and GitHub emails the mention
   (workflow `digest-email.yml` there; deduped by content hash).
2. **The job board** — a rolling **2-week** searchable page, `docs/index.html`, published
   to the public repo `AnalystJobsIL/board` → https://analystjobsil.github.io/board/.

**Per-company caps** (`pipeline/run.py`): the email shows at most **3** roles per company,
the board **8** — so "only one Wix role arrived" can be the cap, not a coverage gap.

**What qualifies as a role** (the actual product decision, implemented in
`pipeline/seniority.py`): experienced (**~3+ years**) data-analysis work — data/BI/product/
marketing analytics, analytics leadership. **The title does not matter**: a "Data Scientist"
posting counts if the work is really product/business analytics. **Out**: core ML/model
building, data engineering, software engineering, finance/FP&A, security/SOC, and
junior/intern/entry-level. Deterministic keyword rules decide the clear cases; ambiguous
titles go to `claude -p`, whose YES/NO **role judgment** is cached per `company|title` in
`cloud_state/seen.db` (distinct from a row's coverage **verdict**, §2).

**Vocabulary** (used consistently below):
- **the digest** = the 05:00 run that produces both the email and the board.
- **the job board** = our published 2-week page. **a careers board** = a company's own ATS
  listing. Never abbreviate either to "the board" alone.
- **role judgment** = classifier YES/NO on one posting. **row verdict** = the dated
  coverage note on a `companies.csv` row.
- **parked** = `active=false` with a verdict explaining why; parked rows are still
  re-checked (§2), never forgotten.
- **JD** = job description text. **discovery net** = the LinkedIn/Indeed/Telegram sweeps.

**Repo layout note:** `pipeline/` holds the digest-run library (`run.py`, `fetchers.py`,
`seniority.py`, `israel.py`, `store.py`, `digest.py`, `health.py`, `recruiters.py`).
**Every other script named in this document lives at the repo root.**

### Run it locally without side effects

**Two traps:** several root scripts have no `if __name__ == "__main__"` guard, so *importing*
them executes them (`merge_research.py` rewrites `research_companies.json` on import).
And 13 of 39 workflow steps carry `continue-on-error: true`, so a hard failure in an
audit/hunt step still shows a green run — check the step log, not the badge.

```bash
python -m pipeline.run --only "Fiverr,Wix" --no-llm    # produce-only: NEVER emails/publishes
                                                      # scoped runs write out/docs-preview/,
                                                      # never the published docs/
python -m pipeline.run --db /tmp/scratch.db            # don't touch the real seen-store
python scrape_universal.py "Company" "https://…/careers"   # test extraction on one page
python audit_empty_rows.py                             # dry-run (add --apply to write)
```
`pipeline.run` only writes `out/digest-<date>.{html,txt,json}` — emailing and board
publishing are separate workflow steps, so a local run cannot notify anyone. Most tools
follow the same convention: **dry-run by default, `--apply` to write**. Useful env vars:
`SCRAPE_LLM=1` (LLM extraction fallback), `SCRAPE_ASSUME_IL=1` (accept page-level Israel
signal), `LLM_RESOLVE_CAP`, `JD_ENRICH_CAP`/`JD_ENRICH_BD_CAP`, `SERPAPI_KEY`,
`BRIGHTDATA_API_KEY`/`BRIGHTDATA_ZONE`, `CLAUDE_CODE_OAUTH_TOKEN` (subscription OAuth, not
an API key). Local secrets live in the gitignored `secrets.env`.

### The common job shape

Every fetcher and scraper must return a list of dicts in exactly this shape — this is the
contract that makes sources interchangeable:

```python
{"company": "Fiverr", "title": "Senior Business Data Analyst",
 "location": "Tel Aviv, Israel", "country_code": "IL",       # "" if unknown; israel.py falls back to text
 "url": "https://…/apply/12345", "posted_date": "2026-08-21",  # ISO; "" if unknown
 "ats_platform": "comeet", "job_id": "23.F66",                 # job_id must be stable per posting
 "description": "About the role… Requirements…"}               # plain text, ≤6000 chars, "" allowed
```

One-screen mental model:

```
 SOURCES                     NORMALIZE            CLASSIFY              DELIVER
 ───────                     ─────────            ────────              ───────
 native ATS APIs  ──┐
 (comeet/greenhouse/│
  lever/ashby/      │        pipeline/fetchers.py  pipeline/seniority.py  digest email (issue relay)
  workday/oraclehcm…)│  ──►  one normalizer per ──► keyword layer +   ──► rolling 2-week board
 scraped listings ──┤        source → common job    claude -p for         (docs/index.html →
 (scraped_cache)    │        shape → israel.py      ambiguous titles      AnalystJobsIL/board)
 discovery nets   ──┘        location filter        (verdict cached
 (LinkedIn/Indeed via                               per company|title)
  Bright Data, Telegram
  channels)
```

Everything below exists to answer one question honestly: **"which Israeli-relevant
companies have open roles right now?"** — with a verifiable trail for every claim,
including the claim "none".

## 1. Coverage tiers (how a company's jobs are read)

1. **Native ATS fetchers** — `pipeline/fetchers.py` `FETCHERS` map. A `companies.csv` row
   whose `ats_platform` names a platform is fetched live every digest run via its public
   JSON API. Adding a platform = one `fetch_x(row)` normalizer + a map entry.
2. **Scrape rows** (`ats_platform=scrape`) — `api_url` holds a LISTINGS page URL.
   `refresh_scrape_cache.py` (daily 00:00 UTC) renders it with `scrape_universal.py` and
   writes `scraped_cache.json`; the digest reads the cache via `fetch_scrape`.
   `scrape_universal.scrape()` escalates through **5 strategies**:
   captured XHR/JSON bodies → rendered-DOM job links → repeated heading/class-hinted card
   groups → position-links (N same-prefix links, fetch each page) → **LLM extraction**
   (`SCRAPE_LLM=1`: Claude reads the rendered text, returns JSON; gated on jobs-signals).
3. **Discovery nets** — `discovery_daily.py` (Bright Data LinkedIn/Indeed keyword sweeps)
   and `discovery_telegram.py` (public t.me/s channel previews) write
   `discovered_cache.json`, read by `fetch_discovery`. This is the safety net for
   companies with no readable board — and the intake that feeds NEW companies into
   resolution (below).

Full `FETCHERS` map (16): comeet, greenhouse, lever, smartrecruiters, recruitee, ashby,
workday, oraclehcm, custom_json, jazzhr, microsoft, workable, breezy, bamboohr, plus the
pseudo-platforms `scrape` and `discovery`.

Support policy: a platform seen 3+ times gets native support; otherwise the scraper's
strategies carry it (Phenom/Eightfold/iCIMS/Radancy/Rippling are all read via strategy 1
XHR-capture or 3/4 without native fetchers).

## 2. Row lifecycle — every company carries a dated, evidence-based verdict

`companies.csv` is **the source of truth for coverage** — the registry of who gets read and
the log of what we know. Columns: `company_name, ats_platform, token, api_url, active,
notes`. Three real rows, one of each kind:

```csv
Fiverr,comeet,60.002,https://www.comeet.com/careers-api/2.0/company/60.002/positions?token=62188018812631018862C4188,true,
Google Israel,scrape,,https://www.google.com/about/careers/applications/jobs/results/?location=Israel,true,re-audit 2026-08-22: user-found listing URL; heading-group scrape verified 20 IL (page 1)
Imagindairy,scrape,https://www.imagindairy.com/careers,https://imagindairy.com/careers/,false,"chrome-verified 2026-08-22: careers live, CURRENT OPENINGS empty (true 0) - monitored candidate"
```

For API rows `api_url` is the endpoint; for scrape rows it is the **listings page URL**.
`notes` is the row-verdict log: each tool appends ` | <tool> <date>: <finding>` and strips
its own previous suffix, so a row accumulates one current verdict per tool.
**Caveat:** `listing_hunt`'s `found` branch, `refresh_scrape_cache`'s parking pass,
`retry_unreachable._row_for` and `recheck_suspects.py`'s suspect-cleared branch still
REPLACE the whole cell (they set a row's final state,
so history loss is acceptable there) — but never copy that pattern for a diagnostic
verdict: overwriting destroys the `monitored candidate` / `host documented` tokens that
`listing_hunt`'s fast-path keys on. Taxonomy:

| state | active | meaning | who re-checks it |
|---|---|---|---|
| (verified board) | true | endpoint/listing verified to return real jobs | every digest / daily refresh |
| `… N/0 IL` (N>0) | true | board healthy, N global roles, none in Israel | every digest — lights up automatically |
| `… 0/0 IL` | true | zero of zero: **may be a dead token/moved board**, `pipeline/health.py` calls this `empty-board`. Discriminator: comeet returns HTTP **400** for dead creds, **200 + `[]`** for a live empty board | digest → `stale.json` → 06:00 self-heal (5 strikes) |
| `host documented, 0 IL now` | false | walled-ATS host found, extraction unproven | daily probe + hunt |
| `monitored candidate` / `host documented` | false | real page documented, extraction unproven | daily probe + 14-day re-hunt |
| `probe-woken: re-hunt pending` | false | probe saw signals rise; awaiting same-day hunt | today's 14:00 hunt (fast-path) |
| `no listing found` / `no ATS detected` | false | full render found nothing parseable | weekly audit + hunt cron |
| `unsupported ATS <x>` | false | ATS known, no extraction path yet | crack_walled / listing-hunt |
| `domain-dead …` | false | DNS/conn dead (GET-verified, lenient TLS — strict TLS on the scanning machine produced 6 false positives) | re-tested after 30d by the Sunday audit; **a revived domain clears the flag automatically** |
| `defunct: …` | false | company confirmed shut down/acquired | permanently excluded |
| `chrome-verified …` | either | a human-equivalent browser check confirmed the state | as per its class |

Recruiting/staffing agencies are excluded everywhere via `pipeline/recruiters.py`
(`is_recruiter`) — rows, discovery jobs, and resolution queues all check it.

### State transitions (who moves a row, and when)

```
   new name (discovery / manual)
            │  research_companies.json queue
            ▼
   ┌──── auto_expand (08:00/20:00) ────┐   resolve_deep → resolve_llm (capped, else deferred)
   │ resolved+verified │  failed        │
   ▼                   ▼                ▼
 ACTIVE ROW        parked: "scanned; no open" / "unreachable" / "aggregator URL"
   │  ▲                   │
   │  │                   │ listing_hunt 14:00 (finds listings URL, verifies ≥1 IL job)
   │  │                   │ crack_walled / deep_validate (on demand)
   │  │                   │ audit_empty_rows (Sun) — re-verifies ALL parked rows
   │  └───────────────────┘
   │
   │ scrape yields 0 for ROT_PARK_DAYS(3) → parked "scrape rotted" → back to listing_hunt
   │ API fetch fails → stale.json → self-heal 06:00 re-resolves (weekly retry, 5 strikes)
   ▼
 parked: "monitored candidate" (URL known, extraction unproven)
   │  probe_candidates (05:00 daily) sees job/Israel signals rise vs baseline
   ▼  → note becomes "probe-woken: re-hunt pending"
 listing_hunt 14:00 takes the FAST-PATH: scrape the stored URL directly; verified → ACTIVE
```

Terminal-ish states: `defunct:` (company gone — permanently excluded) and `domain-dead`
(DNS/conn dead, GET-verified — candidate for defunct research). Everything else is
re-checked on some cadence; **a failing API row keeps `active=true`** (its roles stay on
the job board via the failed-company exemption, §5a) while a rotting *scrape* row is
parked, because only parked rows are visible to the hunt/audit machinery.

### The verdict-string rule (read before changing ANY resolver)

Re-check pools are **allowlists of note substrings**, and the allowlist now lives in ONE
place: `pipeline/verdicts.py` (`TOKENS` / `in_pool` / `stale`). Add any new verdict string
to `TOKENS` there. `audit_empty_rows` and `deep_validate` import `in_pool`; the tools that
legitimately want a subset (`crack_walled` → walled ATSes, `probe_candidates` → documented
candidates) narrow it explicitly rather than re-implementing it. Hand-maintained copies
drifted once already — `listing_hunt` knew 15 tokens while the other two knew 7, leaving
**64 companies invisible to two pools**. If a string is missing from `TOKENS`,
its coverage is lost with no error anywhere. This is exactly how 52 rows became stranded
(`bd_rescue.py` wrote `scanned via brightdata; …`, which matched none of them).
Corollary: a diagnostic verdict must **append** (`base | tool date: finding`), never
replace the cell — overwriting also destroys the `monitored candidate` / `host documented`
tokens that `listing_hunt`'s fast-path keys on.

**Append through `pipeline/notes.py`, never by hand** (2026-08-23). The cell is capped at
220 chars, and every writer used to make room by SLICING the base — `(base + " | " + seg)[:220]`
or `base[:220 - len(seg) - 3]`. The newest segment lives at the END of the base, so the trim
ate exactly the thing worth keeping: 87 rows came to read `dark-triage 2026-08-22: page-emp`
(also `page-e`, and on one row `pa`), naming a mode no downstream filter matches.
`notes.append()` drops OLD WHOLE segments until the new one fits; `notes.replace_own(marker)`
re-stamps this tool's own segment and leaves every other tool's alone. Keep segments SHORT —
one full URL in a segment is 117 characters and will evict everything else.
`test_every_note_writer_uses_the_append_log_helper` fails on the next hand-rolled trim.

Every re-check filter must have a **staleness escape** (`_stale_hunt` 14d, `_revalidatable`
30d, `_recrackable` 30d). A filter of the form `"tool-name" not in note` freezes coverage
forever — that pattern has been introduced and removed three times.

### The activation rule (2026-08-23 — read before flipping any row to active)

"There are Israel jobs on this page" is not "these are THIS company's jobs", and it is not
"this is a page that lists jobs". A row may only be activated when all three hold:

1. `pipeline.aggregators.is_aggregator(url)` is false — an aggregator's "similar jobs"
   sidebar is other employers' roles.
2. `pipeline.company_identity.is_foreign(company, url)` is false — FairFly was activated off
   fireflyspace.com (25 Firefly Aerospace roles), SimilarTech off greenhouse `similarweb`
   (25 of Similarweb's), "Moonsite - Moonsoft Development" off Moon Active's Ashby board.
   For an ATS host the identity is the TENANT SLUG, and a rebrand or acquisition looks
   identical to a mis-resolution — Momentis really does post under `memic` — so a `weak`
   verdict is settled by `page_mentions_company(..., strict=True)`, never by the domain
   alone.
3. `pipeline.company_identity.looks_like_a_job_listing_page(url)` is true — `SCRAPE_ASSUME_IL`
   makes every card on the page an Israel role, so a nav menu scores like a board:
   `iai.co.il/solution/research-academy-space` "verified 6 IL" whose titles were "Domain
   Operations" and "Press Releases".

`test_every_activation_path_checks_company_identity` walks the AST of every root script for
`row[4] = "true"` and fails if that module never consults `company_identity`.

### The single-writer rule (most dangerous rule here — read before any write)

`companies.csv` writers must **re-read the file immediately before every write**
(read-modify-write per verdict, matching on **company name, never row index**) and never
hold a start-of-run snapshot; two concurrent snapshot-writers silently destroy each other's
verdicts (lost-update incident 2026-08-22).

**All 20 `companies.csv` writers, by safety class** (verified 2026-08-22):

- **Compliant** (re-read + match by name before every write): `crack_walled.py`,
  `probe_candidates.py`, `listing_hunt.py`, `audit_empty_rows.py`, `deep_validate.py`,
  `scan_dead_domains.py`, `refresh_scrape_cache.py` (parking pass).
- **Modified-rows merge** (equally safe — merges only the names it changed into a fresh
  read): `bd_rescue.py`, `retry_unreachable.py`, `wayback_rescue.py`, `validate_empty.py`,
  `validate_bd.py`, `recheck_suspects.py`.
- **Append-only** (safe): `auto_expand.py`, `comeet_resolve.py`, `ingest_research.py`,
  `resolve_any.py`, `resolve_parallel.py`, `resolve_unknowns.py`.
  (`resolve_deep.py` and `scrape_batch.py` write only `out/*.csv`, never the registry.)
- **Line-based snapshot, sub-second window** (tolerated): `apply_resolved.py`.

No whole-snapshot index-keyed writer remains. If you add one it will silently revert
concurrent verdicts — use one of the first three patterns.

**Concurrency has TWO layers — both must be handled.** In-process discipline (above)
protects writers on one machine. The **git layer** needs `merge_csv_rows.py`: a cloud run
commits a file whose baseline may be hours old, so `git pull --rebase` hits a content
conflict and the retry loop would discard the entire run (a 3.5-hour listing-hunt cycle was
lost this way, 2026-08-22). Every csv-committing workflow therefore snapshots
`/tmp/base.csv` right after checkout, and on conflict resets to origin and replays only the
rows this run changed (`merge_csv_rows.py base ours target`). Copy that pattern into any
new workflow that writes the registry.

**Every workflow that edits `companies.csv` must `git add` it.** The digest workflow does —
the candidate probe writes verdicts there while `candidate_probe.json` advances baselines;
committing one without the other loses the wake *and* consumes its signal.

Cloud workflows that commit the csv serialize via the `repo-state` concurrency group —
**except `daily-digest.yml`**, which uses its own group, so a digest CAN overlap an
audit/hunt run; both re-read, so verdicts survive. A local `--apply` run adds a third
writer: avoid the cron windows in §4 (and never run two browser-driving tools at once —
Playwright sync instances conflict).

## 3. Resolution ladder — how a dark company becomes covered

New names enter via discovery (`research_companies.json` queue) or manual seeding. Then:

1. `auto_expand.py` (cron 08:00/20:00): deterministic `resolve_deep` — recognizable ATS
   URLs, iframes. Failures get ONE shot at tier 2 (capped `LLM_RESOLVE_CAP`/run; excess
   **deferred**, not parked).
2. `resolve_llm.py`: evidence bundle (page fetch + SerpApi search + ATS-hint extraction) →
   single `claude -p` proposal `{platform, token, api_url}` → **verified** via the real
   fetcher. One retry carrying the verification error.
3. `listing_hunt.py` (cron 14:00): for rows still dark — find the LISTINGS URL (harvested
   links; Claude picks; rebrand redirects resolved), verify via `scrape_universal`.
   Woken/documented rows take the **fast-path**: scrape the stored URL first.
4. `deep_validate.py` / `crack_walled.py` (on demand): Chromium render + network-request
   sniffing (`/wday/cxs/`, `careers-api`, `COMEET.init` static token extraction, …),
   platform host guessing, Claude evidence judgment.
5. Manual Chrome sweep: a human/agent reads the page in a real browser; every miss becomes
   a new detection pattern in the code.

**Verification invariants (never bypass):** see also "The activation rule" in §2, which is
the short version of the three gates and the code that enforces them.

- No row activates unless its endpoint/listing **returned real jobs through the production
  fetch path** at resolution time (for scrape rows: ≥1 *Israel* job) — AND the page claims
  to list jobs at all (`looks_like_a_job_listing_page`). Real Israel jobs are not enough:
  `SCRAPE_ASSUME_IL` turns every card on a page into an Israel role, so a nav menu and a
  blog index both "verify".
- Slug/tenant must resemble the company name — `_slug_matches` (`audit_empty_rows.py`),
  enforced in `audit_empty_rows`, `deep_validate`, `crack_walled`, and `resolve_llm._verify`.
  **Known coverage holes in this guard:** comeet uids (`XX.XXX`) are exempt by design (the
  uid comes from the company's own page), and `_resolve_rebrand` in `listing_hunt.py` can
  only *document* a non-matching cross-domain redirect — it cannot tell a rebrand
  (piiano→a16y.ai, legitimate) from an acquisition (deci.ai→nvidia.com), so those need a
  human/LLM call before activation.
  Search fallbacks WILL offer another company's board that verifies with real jobs:
  **CyberArk→PANW** and **Imperva→Thales** were applied and had to be reverted (see their
  `companies.csv` notes); **Lili→Eli Lilly** was caught only by the 0-Israel-jobs gate.
  Historical note: `resolve_llm` relied on prompt-grounding alone until 2026-08-22.
  Since 2026-08-23 all four activation paths call `company_identity`, and a `weak` domain
  verdict is settled by whether the fetched page NAMES the company as a phrase.
- **The search rung is Bright Data's Google, not SerpApi.** `resolve_broken._careers_url_via_serp`
  tries SerpApi first and falls back to `deep_validate.google_via_unlocker`. It was
  SerpApi-only until 2026-08-23, and that quota has been exhausted since mid-August — so the
  last rung of the self-heal was returning None before it made a request, and every board
  that had MOVED rather than broken came back "no working ATS". DuckDuckGo is blocked from
  some networks (including the dev machine) and works on the runners; the unlocker works
  from both.
- Never activate a scrape of an aggregator page (LinkedIn/Indeed/Glassdoor/secrethunter) —
  their "similar jobs" sidebars attribute other companies' roles to the target. Enforced at
  resolution (all resolvers) **and at runtime** in `pipeline/run.py`, which drops such rows
  from the digest with a SKIP line. Note `scrape_universal.py` itself has no aggregator
  logic — never call it directly on an aggregator URL.
- A mass-zero result (e.g. 0 finds across a whole run) is a **broken run, not a
  measurement** — strip its verdicts and re-run after diagnosis (nested-Playwright
  incident: two sync Playwright instances in one thread fail silently). To strip: verdicts
  are ` | listing-hunt <date>: …` suffixes in the `notes` column; remove that suffix, or the row waits
  14 days for `_stale_hunt` to re-admit it. (Before 2026-08-22 the `no listing found`
  verdict was **terminal** — a bad batch retired hundreds of companies permanently.)
  Only `refresh_scrape_cache.py` self-protects automatically (aborts if the rebuilt cache
  shrinks >20%); every other runner needs the operator to apply this rule.

## 4. Schedules and latency guarantees (UTC)

| time | workflow | effect |
|---|---|---|
| 00:00 | scrape-refresh | re-render all scrape rows (JD carry-forward keeps enrichment) |
| 02:30 | retry-unreachable | Bright Data re-fetch of flaky endpoints |
| 05:00 | daily-digest | discovery → telegram → probe candidates → JD-enrich → fetch ALL active rows → classify → persist state → **publish board (persist runs first, on purpose)** |
| 05:45 / 08:30 | inbox relay (private repo) | digest → email via issue+mention, content-hash dedup |
| 06:00 | self-heal | re-resolve stale/rotted boards |
| 08:00 / 20:00 | auto-expand | drain resolution queue (deterministic + LLM tiers) |
| 14:00 | listing-hunt | re-hunt woken/eligible dark rows (no-ops in minutes when clean) |
| Sun 04:00 | audit-coverage | wayback rescue, empty cross-validation, full parked-row re-audit, **liveness re-scan (revives domains), walled-ATS re-crack**, coverage report |

Latency: active API rows — **same-day**; active scrape rows — **~1 day** (00:00 refresh →
05:00 digest); monitored candidates — **~1–2 days** (probe wake → 14:00 verify → next
digest); deep re-hunt every 14 days and weekly audit are backstops only.

## 5. State files

| file | contents | written by |
|---|---|---|
| `companies.csv` | the coverage registry + verdicts | resolvers/audits (see rule below) |
| `cloud_state/seen.db` | tables: `sent` (email dedup), `matched` (job-board rows), `llm_cache` (role judgments), `company_info` (blurbs), `firmographics` | pipeline runs |
| `scraped_cache.json` | rendered scrape-row jobs (+enriched JDs) | scrape-refresh, enrich, auto-expand |
| `discovered_cache.json` | discovery-net jobs (21-day TTL at read) | discovery_daily, discovery_telegram |
| `research_companies.json` | resolution queue (names + seed URLs) | discovery bridges; drained by auto-expand |
| `cloud_state/telegram_seen.json` | last message id per channel | discovery_telegram |
| `cloud_state/candidate_probe.json` | probe signal baselines | probe_candidates |
| `cloud_state/stale.json` | per-company health verdicts: `fetch-error`, `regressed-to-zero`, `empty-board`, `misconfig-scrape-on-ats` | pipeline/health.py during digest |
| `cloud_state/health_baseline.json` | **all-time high-water** job count per company (monotonic — never decreases, which is why `regressed-to-zero` latches) | pipeline/health.py |
| `cloud_state/resolve_attempts.json` | self-heal retry throttle (weekly; 5 strikes → abandoned) | resolve_broken.py |
| `cloud_state/scrape_rot.json` | consecutive empty/error days per scrape row | refresh_scrape_cache.py |
| `cloud_state/firmographics.json` | **the shared, git-mergeable export of the `firmographics` table.** sqlite cannot be merged, so this text file is what the local and cloud stores converge through; the digest reads sqlite ∪ this file (fresher `as_of` wins) and writes the union back | `research_firmographics.py --export`, `pipeline/run.py` |
| `cloud_state/pipeline_stages.json` | which nightly stage last finished and how much it did (`pipeline/stages.py`) — the digest warns in its audit when a prerequisite stage did not run today | each stage's workflow, via `python -m pipeline.stages stamp <stage>` |
| `cloud_state/source_health.json` | per discovery source: records returned this run, and the last day it returned any (`pipeline/sources.py`). A source that goes quiet is a workflow warning AND a line in the digest audit — Indeed returned zero for five days unnoticed | discovery_daily, discovery_telegram |
| `state/` (gitignored) | resume markers (audit done-list). Written in the cloud too but **never committed**, so the Sunday audit re-audits every parked row from scratch (a SerpApi budget fact) | audit/local runs |

(The single-writer and commit-together rules live with the csv schema in §2.)

## 5a. Fetch-failure semantics (what a broken careers board does to our job board)

A company whose fetch raises does **not** crash the run (`pipeline/run.py` per-company
try/except): it lands in `companies_failed` and gets `status: fetch-error` in `stale.json`.
Its already-matched roles **stay on the board** — `_alive` in `run.py` exempts failed
companies so a transient outage doesn't blank a company — bounded by the 14-day
`first_seen` window. Repair path: `stale.json` → 06:00 self-heal (`resolve_broken.py`,
re-resolves via careers-page capture, needs `SERPAPI_KEY` for the search step; retries at
most weekly, abandons after 5 strikes → "discovery covers it").

Scrape rows rot differently and are handled in `refresh_scrape_cache.py`: an **error**
carries the previous jobs forward for at most `CARRY_MAX_DAYS` (14) — never forever — while
an **empty** result carries nothing. Either state persisting `ROT_PARK_DAYS` (3) days parks
the row (`scrape rotted …`) so the listing-hunt pool re-finds and re-verifies it, because
**active rows are otherwise invisible to listing-hunt and the weekly audits**.

**The four unrelated "14"s** — don't conflate them: the job board's 14-day `first_seen`
window; `CARRY_MAX_DAYS`=14 (stale scrape jobs); the 14-day deep re-hunt cadence; and
`_stale_hunt`'s 14-day suppression of a row carrying a hunt verdict.

## 5b. Diagnosing "why isn't company X in my email?"

In order — each step names the file to open:

1. **`companies.csv`** — is there a row? Is `active=true`? Read the `notes` verdict: it
   names the tool, date, and finding (e.g. `monitored candidate`, `domain-dead`, `defunct`).
2. **`pipeline/recruiters.py`** — `is_recruiter(name)` true? Agencies are excluded by design.
3. **Aggregator SKIP** — the digest run prints `SKIP <company>: scrape row points at an
   aggregator`; such rows are dropped at runtime.
4. **API row failing?** `cloud_state/stale.json` (`fetch-error` / `regressed-to-zero`) and
   `cloud_state/health_baseline.json` (last-known-good counts) → repaired by 06:00 self-heal.
5. **Scrape row?** Look for the company key in `scraped_cache.json` (jobs extracted last
   refresh) and `cloud_state/scrape_rot.json` (consecutive dead days). Remember scrape data
   is up to a day old by design.
6. **Job present but not emailed?** Two filters remain: `pipeline/israel.py`
   (`is_israel_job`) and `pipeline/seniority.py` (`classify`). Reproduce a single decision:
   ```bash
   python -c "from pipeline.seniority import classify; print(classify({'title':'Senior Data Analyst','company':'X','description':'…'}, use_llm=False))"
   ```
   It returns the decision, path (`keyword` / `llm` / `llm_cache` / `keyword_nollm` /
   `llm_failed_fallback`) and reason. The cache key column in `llm_cache` is `title_key`. A cached role judgment lives in `cloud_state/seen.db` → `llm_cache`
   (key `company|title`); delete that row to force re-judgment.
7. **Emailed before?** `seen.db` → `sent` table is the across-day dedup: a role is emailed
   once. The 2-week job board still shows it; the email only carries the last 48h.
8. **Not in `companies.csv` at all?** Check `research_companies.json` (resolution queue) and
   `discovered_cache.json` (discovery-net jobs, 21-day TTL) — it may be mid-onboarding.

Inspect the store directly with sqlite: tables are `sent`, `matched` (job board rows),
`llm_cache` (role judgments), `company_info` (blurbs), `firmographics`.

**Trap:** the `cloud_state/*.json` files are snapshots of the **last committed cloud run**,
not live views of `companies.csv` — a company's absence from `health_baseline.json` or
`stale.json` proves nothing about whether it is being fetched (as of 2026-08-22, 158 of 722
active rows had no baseline entry). To settle it, run the row yourself:
`python -m pipeline.run --only "<name>" --no-llm`.

## 6. Recipes

- **BEFORE adding any company (every time):** (1) grep the name **stem**, not the marketing
  name — `grep -in deci companies.csv` finds a row that `Deci AI` misses; many rows omit the
  `AI`/`Labs`/`Technologies` suffix. (2) Check the careers URL's **final** host:
  `curl -sIL <url> | grep -i ^location` — an acquired Israeli startup keeps a live URL that
  301s to the acquirer's global board (`deci.ai/careers/` → `nvidia.com`), which *will*
  verify with the acquirer's Israel jobs and attribute them to the wrong company. Acquired
  companies get `active=false` + a `defunct:` note, never an active row.
- **Add a company you found manually**: never hand-write an unverified row. Verify first —
  `python -c "from audit_empty_rows import verify; print(verify('Name','greenhouse','slug','https://boards-api.greenhouse.io/v1/boards/slug/jobs'))"`
  (returns `(total, israel)`; raises if the endpoint is bad) or, for a listings page,
  `python scrape_universal.py "Name" "https://…"` — it must extract ≥1 Israel job. Then add
  the row with `active=true` and a dated note, e.g.
  `Deci AI,scrape,,https://deci.ai/careers/,true,manual 2026-08-22: listing verified 4 IL`.
  Never point a scrape row at LinkedIn/Indeed/Glassdoor/secrethunter (§3 invariant).
- **Add an ATS platform**: write `fetch_x(row)` in `pipeline/fetchers.py` returning the
  common job shape (§0) — copy `fetch_ashby` as the simplest template — add the `FETCHERS`
  entry, then wire **all four detection tables** or no resolver will ever discover the
  platform on its own: `SIGS` (`audit_empty_rows.py`), `_HTML_ATS` (`resolve_broken.py`,
  self-heal), the pattern list **and platform enum** in `resolve_llm.py`'s prompt, and
  `ATS_HOST` (`pipeline/health.py`). `deep_validate.py` re-imports `SIGS`, so it needs
  nothing. Verify with the `verify(...)` one-liner above before adding rows.
- **Add a Telegram channel**: append to `CHANNELS` in `discovery_telegram.py` (must have a
  public t.me/s preview; secrethunter-format parses deterministically).
- **A company's verdict looks wrong**: check its `notes` for the evidence date and method,
  reproduce with the named tool, and if the verdict flips — fix the row AND encode the
  miss as a detection pattern so the class is covered, not the instance.

## 7. Company firmographics — the company-type layer

Structured per-company facts (sector, stage, size, business model) that join with the
matched jobs to answer **"what does this TYPE of company ask for?"**. Built 2026-08-22;
distinct from the prose blurbs in `company_info` (§0's "About" text) — same lazy-cached
pattern, structured JSON instead of two sentences.

### The record

One JSON object per company, produced by `pipeline/firmographics.py::research_company`
(a `claude -p --allowedTools WebSearch` call, ~15-60s) and validated before caching:

```json
{"sector": "cybersecurity", "sub_sector": "cloud security (CNAPP)",
 "stage": "acquired-by-bigtech",              // enum: public | acquired-by-bigtech | growth-private | early-private
 "stage_note": "acquired by Google $32B, closed 2026-03",
 "size_band": "L",                            // enum: S <200 | M 200-1000 | L 1000-5000 | XL >5000
 "employees_global": 3148, "founded": 2020,   // founded accepts 1600..today (Barclays=1690!)
 "business_model": "SaaS per cloud workload", "customer_type": "enterprises",
 "il_center": "Tel Aviv", "as_of": "2026-08-22",
 "employees_source": "linkedin", "employees_as_of": "2026-08-22"}   // present when a fill pass touched it
```

**Validation philosophy: reject, never repair.** A record with no identifiable sector, an
out-of-enum stage, or an implausible number is dropped entirely (`_coerce` returns None) —
a failure is retried on a later pass, junk is never cached. The researcher is instructed
to answer null over guessing; the fill passes below close the nulls.

**Retry throttles (quota protection, added after adversarial review 2026-08-22):**
research failures land in the `firmo_failed` table (both the bulk script and the run.py
hook consult it) and retry at most **weekly** — so ambiguous names can't re-spend a
web-search call every chain run or capture the hook's 5-per-run budget. Companies whose
employee count neither fill pass could establish get `employees_lookup_miss` stamped on
the record and retry **monthly**. Anything that writes `employees_global` must re-derive
`size_band` via `pipeline.firmographics.band_for` — the researcher's `_coerce` and both
fill passes all do; a band/count contradiction means someone bypassed it. All three
chain scripts force UTF-8 stdout (`sys.stdout.reconfigure`): under the scheduled task
stdout is a redirected file, Windows picks cp1252, and a Hebrew company name in a print
used to kill the whole stage.

**Failure-classification semantics (wave-2 review):** `research_company` distinguishes
the NAME failing (model answers unknown / junk / validation reject → returns None →
caller records a `firmo_failed` strike) from the INFRASTRUCTURE failing (CLI logged out,
timeout, network → raises `ResearchUnavailable` → caller records **nothing**; the bulk
script and web fill abort after 3 consecutive, the run.py hook stops its loop). Without
this, one expired-login chain run at 03:00 stamped week/month gates onto the entire
pending backlog.

**Identity rules (wave-2 review):** leaked job-title "companies" ("Sql developer - X",
"my team") are pre-filtered by `firmographics.looks_like_junk` — never researched; the
earlier claim that research "correctly fails" them was false (the model profiles the
company mentioned *inside* the string, creating a duplicate under the junk key).
Company identity is **normalized** (`store._norm_company`) when targeting research and
when `company_type_analysis` joins jobs to profiles — "SolarEdge" and "SolarEdge
Technologies" are one company; 9 such duplicate pairs were merged on 2026-08-22.
Re-research of an existing record **merge-preserves** the `employees_*` fields the fill
passes paid for whenever the fresh record has no count of its own — `--refresh-days`
must never regress established counts to null.

### Collection & re-collection (three layers, all idempotent)

1. **Bulk / catch-up** — `research_firmographics.py` researches every company that is
   missing or stale (`--refresh-days N`; `as_of` is the staleness clock). Targets =
   active `companies.csv` rows **∪ companies appearing in `cloud_state/seen.db` matched**
   (CI's discovery surfaces employers we never listed). `--dry-run` reports, `--export`
   writes `state/firmographics.json`. Thread-pooled, saves per-company — Ctrl-C-safe.
2. **Employee fills** — `bd_employees.py` fetches LinkedIn company pages via Bright Data
   Web Unlocker (1 credit/page) for null `employees_global`; then `fill_employees_llm.py`
   re-researches (a) remaining nulls and (b) **suspect LinkedIn matches** — a count
   contradicting the page's own size bucket or under 10, which is how generic names
   (Bit, Aleph, Sunflower) match the wrong page. Every filled count carries
   `employees_source` + `employees_as_of`.
3. **Steady state** — two automatic paths keep it current with zero operator effort:
   - the Windows scheduled task **`IsraeliJobs-Firmographics`** (every 6h:
     09:00/15:00/21:00/03:00 local, catch-up on wake) runs `run_firmo_chain.cmd` =
     research → LinkedIn fill → web verify/fill → export, logging to `state/firmo_chain.log`;
   - `pipeline/run.py` researches up to `FIRMO_MAX_PER_RUN` (5) unprofiled board companies
     per digest run (stat `firmographics_researched`) — this is the only writer on the
     **cloud** side.

### The split-store trap — CLOSED 2026-08-23 (read this before "why is the data missing?")

It used to be: the full dataset lived in the **local** `state/seen.db` (`firmographics`
table) and its gitignored export, while the **cloud** `cloud_state/seen.db` held only what
its own 5-per-run hook had accumulated. 919 researched profiles sat on one laptop while the
cloud digest — the only thing that RENDERS them — had an empty table and re-researched from
zero. sqlite is the reason: git cannot merge a binary, so neither store could publish to
the other.

The stores now converge through **`cloud_state/firmographics.json`**, a sorted JSON export
that git diffs line by line. `research_firmographics.py --export` writes it (so the 6-hourly
Windows chain publishes automatically), and `pipeline/run.py` reads **sqlite ∪ export**,
fresher `as_of` winning per company, then writes the union back. Whichever machine did the
research, every consumer sees it.

If you add another table with two writers, do the same thing — do not seed one sqlite from
the other, which lasts exactly until the next conflict-recovery commit reverts it.

### Consumption

`company_type_analysis.py` joins matched jobs (default `--db cloud_state/seen.db`) with
the export, runs `pipeline/roleprofile.py::extract` per job, and aggregates requirement
stats (top skills, median years, degree-required rate, lead share, AI-mention rate) along
three axes: sector / stage / size_band → `out/company_type_analysis.{json,md}`.
Free-text sectors are collapsed through `primary_sector()`'s alias table there — extend
that table when a new sector variant fragments the grouping; don't edit stored records.

### Known limitations

- Discovery sometimes leaks **job titles or categories as company names** ("AppSec",
  "my team", "Sql developer - …"); `looks_like_junk` pre-filters the title-shaped ones
  for free, but bare category words ("AppSec") pass the filter and burn weekly-gated
  research attempts until the discovery-side parser is fixed.
- "Discovery"-class **ambiguous names** can't be researched safely without JD context;
  the run.py hook passes context, the bulk script does not.
- Employee counts for acquired subsidiaries are the **unit's** approximate headcount
  (see `employees_source` for the story) — don't sum them with parent-company records.
- The researcher found several listed companies **dead or absorbed** (Alike Health,
  Syte, Sckipio, SimilarTech, NanoLock, Rewire R&D) — firmographics is currently the only
  place that knowledge lands; the `companies.csv` rows are not auto-parked from it.
