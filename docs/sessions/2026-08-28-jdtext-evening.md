# jd-text, 2026-08-28 (evening) — a job description has an END

Files owned: `pipeline/jdfill.py`, `enrich_matched_jd.py`, `enrich_scrape_jd.py`.
Doc section: `ARCHITECTURE.md` §7a. Decision recorded:
`docs/decisions/2026-08-28-llm-judges-the-jd.md` (which reverses the 08-26 no-LLM decision).
Cross-lane: `pipeline/roles.py` `better_description` — `roles` owns that file, please review.

Worked in a `git worktree` at `origin/master` (`.claude/worktrees/jdtext-0828b`). Base
**`66d9e3c`**; every number below is re-derived at that rev unless it says otherwise.

## The base moved under me, and that is the first finding

My first reading was against the working tree at `ae6eeae`. `origin/master` was 35 commits
ahead, and one of them was **`124d27e`, this same lane, 01:45 this morning** — which had
already shipped `looks_like_jd`, `is_job_url(url, title)` + `slug_names_title`, and
`_store_text`. Roughly half of what I had planned was already in the tree. Everything below is
re-derived at `66d9e3c`; the plan I started from is wrong wherever it disagrees.

The brief's own framing had to go too. It asked about roles "under 1,200 chars" — a character
count, which is the thing the operator had already rejected. At the shipped bar the pool is
**11 roles**, not 15, and two of the four it named (TLVTech 992, Sunflower 1,160) were already
carrying the employer's own text: `native_jd` returns 992 and 1,123 characters for them, i.e.
exactly what is stored. They were never defects.

## What was actually wrong

### A. The never-attempted class had one cause, and it was not the character count

Every row in the pool with `jd_attempted = ''` is **archived**, and the single cause is
`dead_role_ids` (`enrich_matched_jd.py:54,192-196`): the ledger filter *removed* closed and
purged roles from the todo, so the driver had never once looked at Mobileye's two rows — sat
there since 2026-08-16 with a free Lever endpoint one call away.

**The brief's premise about אסם is wrong.** Its stamp is empty *by design*:
`run_backfill:686-712` deliberately never stamps a refused address, so the canary cannot put
itself to sleep for seven days. It is refused, counted (`matched_unfillable`,
`matched_why=auth-walled…`) and correctly not stamped. That is the design working.

### B. Fourteen rows published a login form as the job description

`looks_like_jd` asks whether a text *contains* a job description. Nothing asked where the
description *stops*, and on an aggregator that is most of the text.

| company | stored | posting | LinkedIn sign-in form | status |
|---|---|---|---|---|
| Migdal Group | 6000 | 367 | 5,633 | open |
| Modellama | 5900 | 300 | 5,600 | open |
| Hila & Co. | 6000 | 457 | 5,543 | open |
| SHILA Medical | 6000 | 682 | 5,318 | closed |
| … 13 more | | | | |
| **total** | | | **60,015 characters across 17 bodies** | 12 open |

Every one passed the morning's bar, because a login wall says "experience" and "skills".

**The two rows the operator reported that morning — Hila & Co. and Modellama — are in this
set.** The morning session called them a RENDER bug on the grounds that "their text is in the
ledger, day-to-day and all". The text in the ledger was the form. That conclusion is corrected
here, with the measurement.

### C. A live regression path, shipped that morning

`_store_text` prefers any text that passes `looks_like_jd` over any text that does not.
comblack held 1,043 clean characters that fail the bar; its LinkedIn page returns **6,000
characters beginning "Skip to main content"** that pass it. The next run to reach an open role
in that shape would have replaced clean prose with a login form.

## What changed

### The furniture cut, and the three markers that measurement rejected

`_PAGE_FURNITURE` is the mirror of `seniority._ROLE_START`; `jd_body(text)` is the posting with
the chrome cut off; `looks_like_jd` and `extract_jd` both judge `jd_body`. Markers were chosen
by measuring each candidate over **all 542 stored bodies** (141 ledger texts + 401
`scraped_cache.json` cards), and **three that read as obviously safe were rejected by that
measurement**:

| candidate | hits | why it was rejected |
|---|---|---|
| `skip to main content` | 14 | a HEAD marker — offset 12, 25, 42 (Weizmann, Amdocs, Simply). Cutting there deletes the body whole |
| `privacy policy` | 77 | cuts real text: C2A Security reaches its privacy line at 916 of 4,000 with the job still to come |
| `cookie` | 43 | same shape, 5 bodies demoted |
| Hebrew `להצטרפות` | 14 | **not a LinkedIn string** — the ordinary word "to join", mid-sentence in IBI's real posting (`מחפשים FP&A להצטרפות לצוות`). Would have destroyed 1,791 characters of a genuine description |

Two English markers that fired on **nothing** (`continue with google`, `get notified about
new`) were also left out: an unfired marker carries no measurement.

The set MATCHES **17 of 542 bodies** and would remove 60,015 characters. **A cut is only made
when what is left is still a job description**, so four are refused: the real figure is
**13 rows, 39,969 characters, no description damaged**.

That floor was not there when I first shipped this, and the sentence that stood here said
*"those roles really do hold only a few hundred characters"*. **It was wrong, and the same
commit contained the proof** — see wave 2 below.

`_reclean` cuts it out of the store too, for no requests and no credits, and is the only path
in this lane allowed to shorten. It refuses above `RECLEAN_MAX_SHARE` (15 %) — rule 2 applied
to text.

### The same trap sprang a second time, in `roles`

After the repair, **13 rows and 39,956 characters of furniture were back — in sqlite**.
`roles.better_description` compares `looks_like_jd`, which now *trims before it judges*: a row
of 3,546 characters of Melio posting plus 2,454 of sign-in form is a job description by that
test, and so is the repaired row. Both being JDs, "longer wins" chose the one with the form and
`open_sync` wrote it back. It now compares — and **returns** — `jd_body`. `roles` owns the file.

### A role's own address, when the published one cannot be read

`store.seen_id()` writes `f"{ats_platform}:{job_id}"` and `sibling_urls` keeps only parts
starting with `http`, so `greenhouse:8035268` was thrown away — while **48 of 135 matched rows
publish a LinkedIn guest page** and several carry a native id.

**The board is the identity gate.** The token comes from `companies.csv` joined on *this role's
own company* and never from a `seen_id`; the id half names a job, never a board. `seen_ids` is
not a list of a role's own addresses (`nift|data analyst` carries five other employers'
postings), so a stray id can only ever be asked for on our own employer's board, where it 404s.

Measured wins: Lever's region comes from the registry `api_url`
(`api.lever.co/…/mobileye/<uuid>` → **404**, `api.eu.lever.co` → **200**), and `_lever_read`
takes `lists` as well as `description` — reading `description` alone returns **686 characters,
exactly the useless blurb already stored**; the rung would have looked like it worked and
changed nothing. With `lists`: **2,835**.

### The retry ladder

`retry_days_for` widens 7 → 14 → 28 → a standing 30 on `matched.jd_tries` (new column,
declared to `roles`/`infra`). A transient failure does not widen it. **No number of failures
removes a role from the pool.** Liveness became a *budget* rule: archived roles are worked
every cycle on the free rungs and reach the Unlocker only under `--archived-bd`.

**Exactly one state is final:** `GONE_MARK`, a 404/410 from a per-job endpoint on the company's
own board. Taboola's `greenhouse:8035268` and Mobileye's second Lever uuid both answer that way.

**Found by attacking my own change before the waves reported:** `gone` was written on ANY
404, and the `?gh_jid=` branch of `native_url` guesses the board slug from the company name
when the registry has no row (`careers.acmewidgets.com/job?gh_jid=1` →
`boards/acmewidgets/jobs/1`). That URL 404s for every company on earth, so the first version
would have retired live roles for ever on a name we made up. `_authoritative` now gates it,
and `test_only_an_authoritative_404_may_retire_a_role` pins it.

### The ambiguous text goes to the model

Operator decision, recorded separately. `quality_suspect` picks candidates for nothing;
`jd_quality` asks one bounded Sonnet question; verdicts cache on the sha1 of the text under
`jdq1|` in `llm_cache`. **A verdict can only move a role between the todo and done** — no
branch writes text on the model's word, which is what makes an injecting posting harmless.

Two bugs found while building it, both worth keeping: the schema must be a **JSON string**
(a dict is a `TypeError` the seam reports as `cli-missing` — an outage message for a caller
bug), and the tier runs **before** the fetch budget, so at 7.8 s a call the 60-call cap alone
is 7.8 minutes on top of 20, against a 25-minute step. It has its own wall clock now.

### Nothing leaves the pool unaccounted for

Every non-superseded row lands in exactly one counted bucket and the driver **asserts** they
sum to the row count. This layer has been caught by silent exclusion twice; both times nothing
added up.

## The repair, and where it stands

Run against the committed `cloud_state/seen.db`, then synced through `Ledger.open_sync`/`flush`.

| | 66d9e3c, judged by the rule that shipped that morning | now |
|---|---|---|
| open roles carrying the employer's own posting | 69 of 72 | **69 of 72** |
| ALL roles, archived included | 130 of 144 | **135 of 144** |
| characters of page furniture in the STORE | 60,015 across 17 bodies | **0** |
| …and in `scraped_cache.json` | 3,551 in one card | **3,551, unchanged** |

**The open figure did not move, and that is the honest headline.** The work was in the archive
and in the text itself: 5 roles filled, 16 re-cleaned, and two of the three open roles that had
been showing a login form now show a posting.

Filled: Migdal Group 0 → 1,027 (ld+json), Hila & Co. 0 → 920 (ld+json), **Mobileye · Business
Analyst 686 → 2,835** (archived, via `seen_ids` → the EU Lever API), SHILA Medical → 1,544,
comblack 1,043 → 1,667.

The nine without a posting, named, with what would be needed:

| role | why | who could |
|---|---|---|
| Taboola · Product Analyst | `gone` — 404 on Taboola's own Greenhouse board | nobody; terminal |
| Mobileye · Experienced Data Analyst | `gone` — 404 on Mobileye's own Lever board | nobody; terminal |
| אסם, Navan | Indeed only; 401/403 to every client we own | `discovery`, BACKLOG 343 |
| Zipher · Data Analyst | own page reached and **paid for**; JS-rendered, `bd-no-markers` | `scraper`, BACKLOG 377 |
| Ashley Digital, Questar | LinkedIn guest wall; plain GET **and one credit each** → `no-markers` | nobody today, BACKLOG 376 |
| Meta ×2 | the row's address is a SEARCH page | `registry`, BACKLOG 266/371 |

## Will it survive 10×

Measured 2026-08-28: **0.92 s per role** on the free rungs (native 0.24–1.02 s, a LinkedIn
plain GET of a 250 KB page 0.67–0.95 s, a fully failing ladder 1.23 s). Role intake from
`first_seen`: **~8.7 new roles/day** against 846 boards.

| store | daily todo | at 0.92 s | at a pessimistic 3 s | if every one hits the 25 s timeout |
|---|---|---|---|---|
| 144 (today) | ~9 | 8 s | 27 s | 3.8 min |
| 500 | ~30 | 28 s | 1.5 min | 12.5 min |
| 1,500 (10× boards) | ~87 | 1.3 min | 4.4 min | **36 min — over budget** |

**The steady state is not what breaks it.** Two things do. The retry ladder makes the todo
O(every role ever accepted) rather than O(new roles); and `ORDER BY last_seen DESC` meant the
freshest rows were walked first *every* morning while `run_backfill` skips rather than breaks —
so the tail was never reached. Ordering by `(jd_tries, jd_attempted, last_seen DESC)` turns the
fixed budget into a round-robin. **One lap exceeds a day at ~800 roles at 1.5 s, ~400 at 3 s**,
and `matched_cycle_days` in the stamp says so instead of the tail starving in silence.

## The adversarial waves, and what they found in my own work

Three Opus sessions, each in its own worktree at the commit under attack, each told that a
finding counts only with a reproduction. **They found three P0s, and one of the three was a
regression I had introduced that morning.** Every one is fixed and pinned.

### The two that would have cost data

**Wave 2, P0 — `_reclean` deleted three real Hebrew job descriptions.** The cut takes the
EARLIEST furniture marker, and on a Hebrew LinkedIn page the sign-in block renders **before**
the posting. So for Migdal Group, Hila & Co. and SHILA Medical the rule kept 367–682 characters
of navigation (`… | מקומות תעסוקה ב-LinkedIn / דילוג לתוכן הראשי …`) and threw away 5,633
characters carrying דרישות / אחריות / ניסיון.

It survived only because the fetch that followed happened to answer. `_reclean` runs and
commits **before** the fetch loop, so a rate limit, a spent budget or a 500 would have left a
navigation menu on the board as Migdal's description with the posting unrecoverable from either
store. **My own session record asserted the opposite** — "those roles really do hold only a few
hundred characters" — and the same commit contained the disproof: the 1,027 characters the
ledger ships for Migdal are verbatim inside the tail `_reclean` had deleted. The floor is now
`looks_like_jd(new)`, not a length: 16 rows → 13, and the three spared are exactly the three
that were damaged.

**Wave 3, P0 — a NULL `url` crashed the whole driver, and I introduced it.** `matched.url` is
nullable (`roles._valid` accepts a record without one and `store.insert_matched` writes it
through), and `_address` asked `unfillable(url)` before the None guard. `unfillable(None)`
raises, the driver died, the step is `continue-on-error: true` — a green workflow and 144 roles
getting nothing. The parent commit was safe.

### The one that made the layer lie

**Wave 3, P0 — `matched_cycle_days` fell as starvation grew.** The denominator was
`tried + cooldown + unfillable`, and a cooled-down row is *skipped*, not worked. At 1,500 rows
with a true 25-day lap it reported **3.5**, and it read greener the fuller the cooldown pool
got. It is the one number introduced to detect the tail starving, and the morning check I wrote
reads "at or under 1.0" as healthy. The denominator is rows worked now.

**Wave 3, P0 — a refused re-clean reported total success.** Above the 15 % ceiling `_reclean`
returned `0`, which is exactly what a clean store returns; the refusal reached the step log and
the mail not at all, while `matched_ok` went on saying every row carried the employer's own
posting. A store full of login walls and a store with none were the same number in the morning
mail — the failure this session exists to fix, re-armed above the ceiling. It returns a negative
count now and raises `matched:reclean-refused`.

### The rest, all fixed

| wave | what | now |
|---|---|---|
| 1 | `_own_address` asked about the COMPANY and never the ROLE — `percepto\|senior product analyst` would have stored 2,406 characters of the *Data Insights Operations* posting | `_own_posting` = company **and** `title_in_slug` |
| 1 | a stray `seen_id` 404ing **retired the role for ever and skipped its readable page** — an invented id retired a live AppsFlyer role whose LinkedIn page was readable all along | a `seen_ids`-derived candidate is tried but never authoritative, and `gone` no longer short-circuits the ladder |
| 1 | `gone` was written from a **guessed** board slug (`boards/linkedin/…` off a LinkedIn host) | `_authoritative` — I had found this one myself an hour earlier |
| 1 | an unreadable ledger put closed roles on the **paid** rung on the daily cron | unknown liveness ⇒ the free rungs |
| 1 | `--limit 3` produced 53 fetches: the archived pass was uncapped | the cap spans both passes |
| 1 | an ident went into the URL path unvalidated (`greenhouse:../../boards/EVILCO/jobs/1`) | `_SAFE_IDENT` |
| 1/3 | the suite is **red under `JD_BD=0`**, which is what CLAUDE.md tells every local session to export | the two Unlocker tests pin `JD_BD=1` |
| 2 | `better_description` returning `jd_body` could return `""` and blank a row through `reconcile` | it may prefer a cleaner text, never destroy one |
| 2 | the shared-text detector was keyed by company, so one page fanned across **different employers** was invisible — Armis/OTORIO hold byte-identical text | keyed by the text alone |
| 2 | `jd_quality` raised `AttributeError` on a non-dict, inside the tier that "may never take a driver down" | guarded |
| 2 | the verdict cache had no contract version | the key hashes the prompt, schema, model, title and company |
| 3 | the backoff **never engaged for a live role while the Unlocker was capped** — 60 plain fetches in 60 days with `jd_tries` frozen, against 4 on the archived pass, which has no Unlocker at all. The ladder was inverted | a page we read and found empty is a definitive verdict |
| 3 | archived roles starved completely at scale: 20 consecutive days of zero archived work while the stamp reported 750 of them | `ARCHIVED_BUDGET_SHARE` reserves a quarter of the clock |
| 3 | the cache rung counted a fill **before** the write decided, and reported two fills that never happened, every morning | `_store_text` decides, then it counts |
| 3 | `matched_llm_rejected`/`_truncated` summed across dispatches (6 rejected rows in a 3-row store) | reclassified as gauges |
| 3 | `matched_short`/`matched_actionable` ignored the LLM verdicts, so the layer contradicted itself in one stamp | they read `incomplete` too |

### What they could not break

The bucket invariant survived 60 random stores × 2 dispatches with no failure — though wave 3
notes it is algebraically forced and so cannot detect a leak either. Termination on definitive
failure is exactly the documented 7/14/28/30. The round-robin ordering genuinely works (two
budgeted runs, 850 and 100 urls, **zero overlap**). `llm_cache` namespacing is sound in both
directions. The headline furniture measurement re-derived independently over 1,748 bodies —
`touched 17, removed 60,015` — matched exactly. The Bright Data cap is per-run, not per-pass.
Wall time at 1,500 rows is 0.9 s of driver overhead outside the fetches.

## Spent

* **Bright Data: 3 credits**, all three `no-markers`, all three a measurement rather than a
  loss — they settle that the residential path does not open the LinkedIn guest wall (Ashley
  Digital, Questar) and does not render Zipher's page. **Do not buy them again**; BACKLOG
  376/377 record it. The `--archived-bd` catch-up pass the operator authorised is therefore
  **done, and it recovered nothing that the free rungs had not already got.**
* **Claude: 10 calls** (7 cached on re-runs), ~7.8 s each. Everything else in this session —
  the furniture cut, the re-clean, the Lever rung, the `seen_ids` class — cost **0 credits and
  0 tokens**.

## NOT finished

* **370 is half closed.** The tail-chrome half is shut and detection of the shared-page case
  exists — but only in `enrich_matched_jd`. `enrich_scrape_jd` has neither `_reclean` nor
  `_quality_pass`, so the 22 `scraped_cache.json` postings that item counts are unchanged.
  Filed as **374**, and doing it properly means item **112** (the two drivers are one driver
  twice).
* **155's inline half** is still held, still waiting on `scraper`'s 265.
* **341** (DESC_MAX truncates a posting) is now *visible* — three roles are judged incomplete
  for that reason and reported rather than re-queued — but not fixed; the cap is not this
  lane's to raise.
* `enrich_scrape_jd` still takes the canonical url only; `_address` is matched-driver-only.

## Morning check, 2026-08-29

Run this; it should print **`69 of 72 open; 135 of 144 all`** or better, and never worse:

```bash
python -c "import json,sys;sys.path.insert(0,'.');from pipeline.jdfill import looks_like_jd;\
r=[json.loads(l) for l in open('cloud_state/roles.jsonl',encoding='utf-8-sig') if l.strip()];\
t={d['role_id']:d.get('description') or '' for d in (json.loads(l) for l in open('cloud_state/roles_text.jsonl',encoding='utf-8-sig') if l.strip())};\
o=[x for x in r if x.get('status')=='open'];\
print(sum(1 for x in o if looks_like_jd(t.get(x['role_id'],''))), 'of', len(o), 'open;',\
sum(1 for x in r if looks_like_jd(t.get(x['role_id'],''))), 'of', len(r), 'all')"
```

And in the mail's `Stage order:` line: `matched_terminal=2` (Taboola, Mobileye #2),
`matched_recleaned=0` (the backlog was cleared tonight — anything above 0 means a new wall
arrived), `matched_bd_calls=0`, and `matched_cycle_days` at or under 1.0 — that gauge now
counts rows WORKED, so it rises when the tail starves instead of falling.

**And on the bold `Stages:` line, `matched:reclean-refused` is the one to act on the same
morning.** It means an aggregator wall arrived on more than 15 % of the store at once, the
re-clean declined to rewrite it, and the board is rendering those walls right now.

**If `matched_recleaned` is large on a morning, that is a new aggregator wall, not a bug** —
read the `[CUT]` lines, confirm the marker, and add it with its measurement.
