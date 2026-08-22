# Architecture — how jobs get pulled, verified, and delivered

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

Support policy: a platform seen 3+ times gets native support; otherwise the scraper's
strategies carry it (Phenom/Eightfold/iCIMS/Radancy/Rippling are all read via strategy 1
XHR-capture or 3/4 without native fetchers).

## 2. Row lifecycle — every company carries a dated, evidence-based verdict

`companies.csv` columns: `company_name, ats_platform, token, api_url, active, notes`.
The `notes` field is the verdict log. Taxonomy:

| state | active | meaning | who re-checks it |
|---|---|---|---|
| (verified board) | true | endpoint/listing verified to return real jobs | every digest / daily refresh |
| `… 0/0 IL` or `0 IL now` | true | board verified, zero Israel roles today | same — lights up automatically |
| `monitored candidate` / `host documented` | false | real page documented, extraction unproven | daily probe + 14-day re-hunt |
| `probe-woken: re-hunt pending` | false | probe saw signals rise; awaiting same-day hunt | today's 14:00 hunt (fast-path) |
| `no listing found` / `no ATS detected` | false | full render found nothing parseable | weekly audit + hunt cron |
| `unsupported ATS <x>` | false | ATS known, no extraction path yet | crack_walled / listing-hunt |
| `domain-dead …` | false | DNS/conn dead (GET-verified) | liveness scan; candidate defunct |
| `defunct: …` | false | company confirmed shut down/acquired | permanently excluded |
| `chrome-verified …` | either | a human-equivalent browser check confirmed the state | as per its class |

Recruiting/staffing agencies are excluded everywhere via `pipeline/recruiters.py`
(`is_recruiter`) — rows, discovery jobs, and resolution queues all check it.

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

**Verification invariants (never bypass):**
- No row activates unless its endpoint/listing **returned real jobs through the production
  fetch path** at resolution time (for scrape rows: ≥1 *Israel* job).
- Slug/tenant must resemble the company name — `_slug_matches` (`audit_empty_rows.py`),
  enforced in `audit_empty_rows`, `deep_validate`, `crack_walled`, and `resolve_llm._verify`.
  Search fallbacks WILL offer another company's board that verifies with real jobs:
  **CyberArk→PANW** and **Imperva→Thales** were applied and had to be reverted (see their
  `companies.csv` notes); **Lili→Eli Lilly** was caught only by the 0-Israel-jobs gate.
  Historical note: `resolve_llm` relied on prompt-grounding alone until 2026-08-22.
- Never activate a scrape of an aggregator page (LinkedIn/Indeed/Glassdoor/secrethunter) —
  their "similar jobs" sidebars attribute other companies' roles to the target. Enforced at
  resolution (all resolvers) **and at runtime** in `pipeline/run.py`, which drops such rows
  from the digest with a SKIP line. Note `scrape_universal.py` itself has no aggregator
  logic — never call it directly on an aggregator URL.
- A mass-zero result (e.g. 0 finds across a whole run) is a **broken run, not a
  measurement** — strip its verdicts and re-run after diagnosis (nested-Playwright
  incident: two sync Playwright instances in one thread fail silently). To strip: verdicts
  are ` | listing-hunt <date>: …` suffixes in the `notes` column; remove that suffix or the
  row is suppressed from re-hunts for 14 days (`_stale_hunt` in `listing_hunt.py`).
  Only `refresh_scrape_cache.py` self-protects automatically (aborts if the rebuilt cache
  shrinks >20%); every other runner needs the operator to apply this rule.

## 4. Schedules and latency guarantees (UTC)

| time | workflow | effect |
|---|---|---|
| 00:00 | scrape-refresh | re-render all scrape rows (JD carry-forward keeps enrichment) |
| 02:30 | retry-unreachable | Bright Data re-fetch of flaky endpoints |
| 05:00 | daily-digest | probe candidates → discovery → telegram → JD-enrich → fetch ALL active rows → classify → persist state → publish board |
| 05:45 / 08:30 | inbox relay (private repo) | digest → email via issue+mention, content-hash dedup |
| 06:00 | self-heal | re-resolve stale/rotted boards |
| 08:00 / 20:00 | auto-expand | drain resolution queue (deterministic + LLM tiers) |
| 14:00 | listing-hunt | re-hunt woken/eligible dark rows (no-ops in minutes when clean) |
| Sun 04:00 | audit-coverage | wayback rescue, empty cross-validation, full parked-row re-audit, coverage report |

Latency: active API rows — **same-day**; active scrape rows — **~1 day** (00:00 refresh →
05:00 digest); monitored candidates — **~1–2 days** (probe wake → 14:00 verify → next
digest); deep re-hunt every 14 days and weekly audit are backstops only.

## 5. State files

| file | contents | written by |
|---|---|---|
| `companies.csv` | the coverage registry + verdicts | resolvers/audits (see rule below) |
| `cloud_state/seen.db` | sent-dedup, matched roles (board), LLM verdict cache, company blurbs | pipeline runs |
| `scraped_cache.json` | rendered scrape-row jobs (+enriched JDs) | scrape-refresh, enrich, auto-expand |
| `discovered_cache.json` | discovery-net jobs (21-day TTL at read) | discovery_daily, discovery_telegram |
| `research_companies.json` | resolution queue (names + seed URLs) | discovery bridges; drained by auto-expand |
| `cloud_state/telegram_seen.json` | last message id per channel | discovery_telegram |
| `cloud_state/candidate_probe.json` | probe signal baselines | probe_candidates |
| `cloud_state/stale.json` | per-company health verdicts (fetch-error / regressed-to-zero) | pipeline/health.py during digest |
| `cloud_state/health_baseline.json` | last-known-good job counts per company | pipeline/health.py |
| `cloud_state/resolve_attempts.json` | self-heal retry throttle (weekly; 5 strikes → abandoned) | resolve_broken.py |
| `cloud_state/scrape_rot.json` | consecutive empty/error days per scrape row | refresh_scrape_cache.py |
| `state/` (gitignored) | local resume markers (audit done-list) | local runs only |

**Every workflow that edits `companies.csv` must `git add` it** — the digest workflow does
(the candidate probe writes verdicts there while `candidate_probe.json` advances baselines;
committing one without the other loses the wake *and* consumes its signal).

## 5a. Fetch-failure semantics (what a broken board does to the board)

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

**Single-writer rule:** `companies.csv` writers must re-read the file immediately before
every write (read-modify-write per verdict, matching on company name — never by row index)
and never hold a start-of-run snapshot; two concurrent snapshot-writers silently destroy
each other's verdicts (lost-update incident 2026-08-22). Compliant writers:
`crack_walled.py`, `probe_candidates.py`, `listing_hunt.py`, `audit_empty_rows.py`,
`refresh_scrape_cache.py` (parking pass), `apply_resolved.py` (line-based),
`auto_expand.py` (append-only). Cloud workflows that commit the csv serialize via the
`repo-state` concurrency group — **except `daily-digest.yml`**, which uses its own
`daily-digest` group, so a digest run CAN overlap an audit/hunt run; both re-read, so
verdicts survive, but a local run must still avoid overlapping either.

## 6. Recipes

- **Add a company you found manually**: verify its board URL returns jobs, add the row
  (platform+token+api_url, `active=true`, dated note). For scrape rows also run
  `scrape_universal.py "<name>" "<url>"` once to confirm extraction.
- **Add an ATS platform**: `fetch_x(row)` in `pipeline/fetchers.py` + `FETCHERS` entry +
  a signature regex in `audit_empty_rows.SIGS` so resolvers can detect it.
- **Add a Telegram channel**: append to `CHANNELS` in `discovery_telegram.py` (must have a
  public t.me/s preview; secrethunter-format parses deterministically).
- **A company's verdict looks wrong**: check its `notes` for the evidence date and method,
  reproduce with the named tool, and if the verdict flips — fix the row AND encode the
  miss as a detection pattern so the class is covered, not the instance.
