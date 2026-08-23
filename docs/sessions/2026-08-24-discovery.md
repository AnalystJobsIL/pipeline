# 2026-08-24 — `discovery` lane

> **Date note.** The session was briefed as 2026-08-24; the machine clock reads
> **2026-08-23 17:37 UTC** (`date -u`). Every measurement below is dated **2026-08-23**,
> which is when it was taken. Only this filename follows the brief.

Scope: the intake layer — `discovery_daily.py`, `discovery_telegram.py`,
`pipeline/aggregators.py`, `pipeline/recruiters.py`, and the new `ARCHITECTURE.md` §1a.
Nothing else was written. Bright Data spend: **~200 dataset records + 8 Web Unlocker
requests**, one day's normal budget. Claude tokens: **0** — nothing here calls `claude -p`.
SerpApi: 0 (429, exhausted).

## What was wrong

Four defects, every one silent, every one in the class `ARCHITECTURE.md` §8 item 1 calls
"a row quietly leaving a re-check pool".

**1. Telegram was invisible to the dead-source detector.** `discovery_telegram.main()`
`return`ed as soon as a scan produced nothing, and the `sources.record()` call sat *below*
that return. `pipeline/sources.py` exists for exactly one purpose — to notice that a source
which used to produce has stopped — and it was written because the Bright Data Indeed
dataset returned zero for five days with a green workflow every morning. Proof it never saw
Telegram: `cloud_state/source_health.json` held `indeed`, `linkedin` and `linkedin-targeted`
and **no `telegram` key at all**, while `discovered_cache.json` held **104 telegram-sourced
jobs**. A source that cannot record a zero can never be reported dead.

It also recorded `len(added)` — jobs surviving dedup against the cache — so a channel
producing normally but repeating a role we already held would have scored 0 and read as
dead. It now records posts *parsed*.

**2. The targeted LinkedIn sweep asked about the same 20 companies every day, forever.**
`_targeted_inputs` took `unresolved[:20]`, and `cloud_state/stale.json` is rebuilt every
digest in `companies.csv` row order (`pipeline/health.py`'s `record` iterates
`results.items()`), so the slice was a stable prefix, not a sample. **110 stale entries, 20
searched, 90 never once.** It also spent inputs on `misconfig-scrape-on-ats` rows — 22 of
the 110 — which is a warning about the *row's shape*, not a broken board; the digest reads
those companies fine every morning.

Fixed: the window advances by day-of-year over the three reasons that mean "the board has
moved" (`empty-board`, `regressed-to-zero`, `fetch-error`). **Identical records per run, all
88 targetable companies covered in 5 days** instead of 20 in perpetuity.

**3. `per_source["indeed"]` meant something different from every other key** — post-filter
unique jobs where the dataset sources record raw records. Same field, two meanings, and an
Indeed page whose cards were all rejected as junior/stale would have scored as a dead
source. Now raw records everywhere; the kept count prints beside it.

**4. A Latin entry in `_CONFIRMED` does not cover the Hebrew spelling.** The file's own
docstring warns about this ("a Latin-only list let one back in as an ACTIVE row after the
English ones were purged") and it was live again. **One** Indeed query returned
`קומבלק איי.טי. בע"מ` (Comblack IT — `comblack` on the list since 2026-08-17) and
`חברה דיסקרטית` ("discreet company", the Hebrew of the `confidential` entry). Re-running the
scan over the 99 companies a full intake pass queued found two more: `קבוצת יעל` (Yael
Group) and `לוג-און תוכנה` (Log-On Software) — **both already on the Latin list**. All four
passed `is_recruiter` AND `looks_like_junk`, i.e. each was one `auto_expand` run from an
active row. Agencies rejected at the source went from **9 → 16** in one pass.

Verified no coverage was lost: **0** existing registry rows match the four new markers, and
`0` active rows are now flagged as recruiter.

## What was added

**Three Telegram channels — `secretcyberjobs`, `secretfinancejobs`, `secretsalesjobs`.**
Keyless, no quota, no key. Seventeen candidates were probed for the secrethunter layout the
parser needs; the number that decides is how many of the ~20 front-page messages parse:

| verdict | channels |
|---|---|
| added | `secretcyberjobs` 16/20 · `secretfinancejobs` 18/20 · `secretsalesjobs` 18/20 |
| rejected on **relevance**, not capability | `secrethrjobs` 17/20 · `secretqajobs` 15/20 — they parse fine, they have no analyst yield |
| no public `t.me/s` preview (0 messages — the parser can never see them) | `secretbizdevjobs` · `secretanalystjobs` · `secretdesignjobs` · `secretstudentjobs` · `secretjobs` |

Widening intake is cheap here **because the resolver queue is not the bottleneck**:
`auto_expand`'s drainable backlog was **77 entries against an `AUTO_EXPAND_LIMIT` of 200 per
run, twice a day**. That is the number to re-check before adding more (command in §1a).

## What the whole layer does when it runs — measured, not asserted

Both scripts were run end to end against sandbox copies of every state file, in the
workflow's order. `pipeline/companies.py` and `pipeline/sources.py` resolve paths against
the **package, not `cwd`**, so `sources.PATH` had to be redirected explicitly or the run
would have written live state — the recipe is in §1a.

```
[indeed:data analyst] 15 cards        [linkedin] 30 records
[indeed:business intelligence] 0      [linkedin-targeted] 160 records
[indeed:BI developer] 10 cards        [secretdatajobs]    3 parsed,  1 skipped
[indeed:product analyst] 15 cards     [secretmarketingjobs] 0 parsed, 1 skipped
[indeed:אנליסט] 15 cards               [secretproductjobs]  4 parsed,  1 skipped
[indeed] 55 raw -> 47 kept            [secretcyberjobs]   81 parsed, 19 skipped
                                      [secretfinancejobs] 91 parsed,  9 skipped
                                      [secretsalesjobs]   89 parsed, 11 skipped
137 discovery jobs cached · 262 telegram jobs merged
16 agencies rejected before they could become rows · 99 new companies queued
```

| | before | after |
|---|---|---|
| `discovered_cache.json` | 205 | 517 |
| `research_companies.json` | 1,233 | 1,332 |
| `source_health.json` keys | 3 | 4 (`telegram` present for the first time) |
| `sources.stale()` | — | `[]`, no dead source |

Then the same cache through tomorrow's classify step (`--no-llm`, no writes): the read-side
filters in `fetchers.fetch_discovery` drop 146 of the 517 (**103 past the 21-day TTL, 44
recruiters** — Experis Israel, MalamTeam, Log-On Software, G-STAT, Gotfriends, Moveo Source
… — 0 mis-attributed), leaving 371 against 184 before. **Accepted roles 39 → 42.**

Be honest about what that costs: `keyword_nollm` went 49 → 62, so ~13 more ambiguous titles
reach the LLM tier. That is a **one-off**, not per-day — `llm_cache` is keyed
`company|title`. Against 163 LLM calls on the 08-23 digest it is under 10%, and the real
return is not the +3 roles, it is the 86 new employer names, which is the path by which
`companies.csv` grows.

The **backfill was deliberately not committed.** Three new channels walk back 5 pages on
their first run; letting that happen in the cloud keeps the jobs and the Telegram watermark
in the same commit. Advancing the watermark locally and committing only part of it is how
79 verified roles were lost on 2026-08-21.

## Claims I could NOT verify

- **Whether SerpApi's `google_jobs` covers Israel at all.** `daily-digest.yml` says it was
  "verified to NOT cover Israel"; `CLAUDE.md` says the quota is exhausted. Both cannot be
  true as the reason it is off, and the key answers **HTTP 429**, so neither is testable
  before 2026-09-01. Marked UNVERIFIED with the date in `pipeline/aggregators.py` and
  `ARCHITECTURE.md` §1a; the delete-or-keep decision is `docs/BACKLOG.md` item 4. What IS
  settled: `AGGREGATOR_ENABLED` is set in no workflow, test or script, so
  `fetch_serpapi_google_jobs` has **never run in the cloud**.
- **Whether `מטריקס` (Matrix) and `עידור מחשבים` (Idor Computers) should be excluded.** Both
  are Israeli IT-services firms that also hire directly, neither has a Latin entry to
  inherit from, and this lane has no evidence either way. Named in `pipeline/recruiters.py`
  as deliberately not listed.
- `[indeed:business intelligence] 0 cards` in the dry run. Every other query returned
  10–15. Not diagnosed — could be Indeed genuinely having nothing inside `fromage=7`, or one
  unlocker response failing. Worth one look if it repeats; `sources.py` will not catch it
  because the aggregate was 55.

## Claims I deleted

- `discovery_daily.py`'s "Budget: ~40 records/day * 30 = ~1200/mo". Measured: **108 dataset
  records + 5 unlocker requests per day, ~3,240/month** against the 5k free tier. The line
  predated the targeted sweep, which is by itself two thirds of the spend.
- `pipeline/aggregators.py`'s docstring framing SerpApi google_jobs as a live daily source
  ("enough for a once-daily run with a few queries"). It has never run.
- The idea that Google for Jobs could be recovered through the Bright Data unlocker.
  Tested, 3 credits: `google.com/search?q=…&ibp=htl;jobs` returns **HTTP 200 with a
  zero-byte body** (client-rendered widget); the same URL *without* `ibp=htl;jobs` returns
  440,906 bytes, which is why `deep_validate.google_via_unlocker` works on organic links and
  a jobs-widget version cannot. Recorded so nobody re-runs the experiment.

## What I did NOT finish — all of it outside this lane, all in `docs/BACKLOG.md`

1. **A company can leave `companies.csv` and nothing says so.** `check_invariants.py` checks
   the registry's shape, never its size; `merge_csv_rows.merge()` iterates `ours` only, so a
   name in `base` and missing from `ours` is neither restored nor mentioned; the mail's run
   audit has no registry delta. Three commits have shrunk the file — `88d2b50` −13,
   `c0f7635` −3, `0180e75` −2 — all deliberate, all explained in the commit subject, none
   visible to the pipeline or to the reader of the mail. **An untracked `registry_health.py`
   appeared in the working tree mid-session**: the `registry` lane is building the detection
   half and reports 15 name-deletions across the file's history. Do not build a second one.
   The half still missing is getting the delta into the email (`infra` + `render`).
2. **The seed URL a discovery bridge can offer is always an aggregator** — a discovered
   job's `url` IS its posting. **206 of 1,233** queue entries carry one (132 secrethunter,
   45 linkedin, 26 indeed) and **45 registry rows** do. `auto_expand` guards its `scrape`
   branch but its `empty`/`unreachable` branches write the seed URL into the row unguarded.
   `secrethunter.io/jobz/<id>` cannot be followed to the real posting either: a 33,495-byte
   JS shell, byte-identical for every job id, no external link but tracking pixels. Discovery
   cannot drop the field — `auto_expand`'s `todo` filter requires it truthy, so a company
   with no `careers_url` would never drain. Fix belongs to `registry`.
3. **Per-channel Telegram liveness.** `sources.stale()` applies one 2-day threshold to every
   key and that line goes in the mail, so six channels as six keys would put a niche feed's
   quiet weekend in front of the reader. One aggregate `telegram` key is recorded and the
   per-channel counts go to the step log — which means **a single channel dying alone is
   still invisible**. `secretmarketingjobs` returned 0 new posts in the dry run. Needs a
   per-key threshold in `pipeline/sources.py`, which is shared plumbing no lane owns.
4. **`looks_like_junk` let `"Infrastructure Team"` through** into the resolver queue. Its
   team-phrase rule is anchored `^(my team|our team|the team)$`. The function lives in
   `pipeline/firmographics.py` (`company-intel`). Same family as backlog item 9 from the
   ten-agent audit.
5. **`linkedin-targeted` is the lane's biggest Bright Data line item and 4 of its 43 cached
   jobs are on-target**; **38 are at companies whose rows are `active=true` and fetched
   directly every morning**. LinkedIn's keyword engine ranks on "data analyst" and treats
   the company name as spare tokens. The *targeting* was fixed this session; halving
   `limit_per_input` from 8 to 4 was **not** done — one lane should not shrink a safety net
   on one day's data. Command to re-measure is in the backlog item.
6. **`מנורה מבטחים החזקות` and `Menora Mivtachim Group` are the same employer under two
   scripts** — the alias problem in "One identity layer", now with a Hebrew case.
