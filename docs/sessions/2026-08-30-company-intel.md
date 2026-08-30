# 2026-08-30 — company-intel: the gap has a direction, the cron a budget, and a broken night a name

Every number below was re-derived from `origin/master` (`7ac03d0`, later `16d077d`) in a
clean worktree; the shared checkout was 171 commits stale that morning. Commands are given
next to the numbers so the next reader re-derives rather than trusts.

## 1. What I was told, and what measured

| claim (orchestrator, 2026-08-30 morning) | measured | verdict |
|---|---|---|
| active registry rows 1,099 | 1,099 (`python check_invariants.py`) | confirmed |
| firmographics entries with a sector 1,247 | 1,247 records, **1,247 with a sector** — no record has ever been stored with an empty sector | confirmed, but the gap is 100 % *missing records*, never empty sectors |
| active rows with no sector **84** | **84 by exact name; 68 through `identity_key`** — the join `firmographics.yml`'s own summary step uses (`display_index`), and the one the mail's `registry backlog` prints | overstated by 16 |
| "was 59 the previous morning" | 08-29 (`2b713a1`) = **56** exact / 41 identity. **59 is the 2026-08-27 figure** (`d76fb10`) | wrong day |
| the cron fired 3×, +605 / +662 / +293 min | identical; all `event: schedule`, all `success`; **those are the only three runs ever** | confirmed |
| the per-run cap was raised from 40 | to **150** (`firmographics.yml:106`, 2026-08-28). **It has never bound**: the one 139-to-do night (run 33210826528) ran under the old 40 | confirmed |

The gap, one snapshot per day (latest state commit each UTC day; `git show <sha>:companies.csv`
and `git show <sha>:cloud_state/firmographics.json`, joined through `display_index` /
`identity_key`):

| date | commit | active | records | gap exact | gap identity |
|---|---|---|---|---|---|
| 08-23 | bab228f | 862 | 922 | 31 | 20 |
| 08-24 | 0b41823 | 877 | 940 | 30 | 19 |
| 08-25 | 197d56b | 870 | 942 | 37 | 26 |
| 08-26 | 74e51e5 | 875 | 973 | 15 | 4 |
| 08-27 | d76fb10 | 937 | 995 | 59 | 46 |
| 08-28 | 8e481a5 | 976 | 1,186 | 21 | 7 |
| 08-29 | 2b713a1 | 1,071 | 1,247 | 56 | 41 |
| 08-30 | b4ac2a7 | 1,099 | 1,247 | 84 | 68 |

Profiles added to the export vs active rows added, per day, 08-24 → 08-30:
**18/15 · 2/9 · 31/5 · 22/64 · 191/155 · 61/99 · 0/28** (medians 22 vs 28). The "sector went
from empty to filled" series is 0 on every day.

**The item is not capacity.** The 08-29 cron cleared 61 of its 67-name queue in one run;
150 a run against a 92-a-day median intake holds. The gap is *measured* at 05:00 by the
digest, and the *only* bulk producer fires once a day at 15:00–21:00 UTC (+293…+662 min
late), so every morning's number is the previous evening's intake (19:00 hunt, 20:00
expand) waiting for a cron that has not fired yet. The +28 on 08-30 is exactly "0 produced,
28 added" — a scheduling shape, not a cap. What *is* real: 08-28 added 155 rows in a day,
above the 150 cap, and a count cap cannot see a night where every call times out.

## 2. What changed (lane files only)

**`research_firmographics.py`**
- `--budget-min` (default 0 = off): a wall-clock bound beside the count bound. The pool is
  fed **lazily** — at most `--workers` calls in flight, the next launched only while the
  clock allows; a call in flight finishes and is saved (per-company saves were already the
  resume mechanism). Refused negative like `--limit`.
- The `firmo` stamp now says what was *asked*, not only what was done:
  `todo` (the queue before any cap), `attempted`, `left = todo − attempted`, `gated`,
  `minutes`, `budget_min`. A run that was cut by the cap or the budget is legible in the
  stamp the next morning.
- `alarm="zero-produce(N to do, 0 researched, F failed, U unavailable, L unattempted)"` when
  the queue was non-empty and nothing was researched for a reason neither `infra-abort` nor
  `mass-failure` names (not for ≤ 4 junk names all answered and refused — the routine shape
  after a drain); `crashed(<Type>)` and `empty-registry(...)` after wave 1 (section 9 below). It rides the stamp's `alarm` key, which `stages.alarms("firmo", 2)`
  in `run.py` already surfaces regardless of age — no change to `run.py`, whose literal is
  pinned by three tests.

**`pipeline/company_intel.py`**
- `_direction()`: reads the lane's own previous `intel` stamp, computes `backlog_delta`, and
  on an unscoped run writes a new `intel` stamp (`backlog`, `board`, `researched`, `blurbs`)
  into `cloud_state/pipeline_stages.json` — the file the digest already commits and
  `persist_state.s_stage_stamps` merges per key. Rejected carriers: a `_meta` key in
  `firmographics.json` (`load_shared_status` flags it `partial` and every writer refuses),
  a new `cloud_state` file (needs a `persist_state.STRATEGY` entry — `infra`'s), parsing
  yesterday's `digests/latest.md`.
- The mail: `registry backlog 68 (+27 since 2026-08-29)` / `(first measurement)`, and a
  `bulk cron: last ran <date> (Nd ago), X researched of Y to do, Z left[, F failed][, alarm …]`
  sentence built from the `firmo` stamp's numbers (its *age* stays `run.py`'s to judge).
  One warning, for one shape: the gap **grew** AND the cron has not run since the day
  before yesterday (or never). Not an absolute threshold — rejected twice before.
- `unavailable_kind` is recorded for the blurb loop too and printed:
  `claude unavailable after 0 blurbs calls (transient: is_error …)`.
- The poisoned blurb is **purged**, once, on an unscoped run (`DELETE FROM company_info`),
  not re-dropped every morning; only names that came from the store, never a hand-written
  profile; `blurbs_purged` on the line.
- `stopped_outage` was read by the audit line and written nowhere; a research soft-outage
  stop is now booked as `N not attempted (stopped)` instead of `skipped (budget 8m spent)`.

**Tests** — `tests/test_company_intel.py` 126 → **141** (+15: 7 for the changes, 6 for the
wave-1 fixes, 2 for wave 2), one per change; the `env`
fixture now redirects `stages.PATH` (an unscoped run stamps, and the first test run of
the day wrote the real `cloud_state/pipeline_stages.json` — restored before commit).

## 3. `is_error (api_error_status=None)` — what it is, and whose

Two consecutive digests, not one: 08-28 17:39Z (run 33193786610, after **2** successful
blurb calls) and 08-29 11:59Z (run 33250362574, on call 0). Same job, same token: the
classifier made 67 successful sonnet calls minutes earlier and the 14:53Z cron researched
61 companies with WebSearch. So: not auth, not quota, not the CLI missing. The string is
manufactured at `pipeline/llm.py:125-129` — the envelope had `is_error: true` and an
**empty `result`**, and `_invoke` discards `subtype` and `errors`, so the actual cause never
leaves shared plumbing. **`pipeline/llm.py` is shared; not edited here.** Proposed diff for
its owner (`classifier` names it; every lane calls it):

```diff
     data = _envelope(proc.stdout)
     if data is not None and data.get("is_error"):
         status = data.get("api_error_status")
-        msg = _ascii(data.get("result") or f"is_error (api_error_status={status})")
+        errs = data.get("errors")
+        first_err = errs[0] if isinstance(errs, list) and errs else ""
+        msg = _ascii(data.get("result")
+                     or f"is_error subtype={data.get('subtype')} "
+                        f"api_error_status={status} errors={first_err!r} "
+                        f"stdout={proc.stdout[:160]!r}")
         kind = "auth" if status in (401, 403) else _kind(msg)
```

**What the placeholder actually means (wave 1, from the 2.1.251 CLI bundle's result schema;
2.1.241 not verified).** There are two result variants. The success one always carries
`result`. The ERROR one — `subtype` ∈ `error_during_execution | error_max_turns |
error_max_budget_usd | error_max_structured_output_retries` — carries **no `result` and no
`api_error_status` key at all**, and its only human-readable cause is `errors[]` (for
`error_during_execution`: `[ede_diagnostic] result_type=… last_content_type=…
stop_reason=…`). So `None` was not a null status; it was a key that does not exist on that
variant. Timing from the step logs: both failing calls took **~9.7 s ≈ 2 × a normal 5 s
blurb** — one attempt plus one fallback retry — which fits a structured-output retraction
on a refusal (the blurb is the one call that hands scraped job text to a factual
identification prompt; 452) far better than any outage. `max_turns`/`max_budget` are ruled
out (the seam passes neither flag, scratch cwd). Filed as 449 with the fuller diff (`subtype`
+ first `errors[]` entry + a stdout excerpt). Until it lands, this lane prints the *kind*
beside the reason so the mail at least says whether the seam thought it was auth, drift or
a blip.

## 4. `Tel Aviv` — where it came from and whose it is

Not a city reaching the gate fresh. One `discovery-telegram` post in `discovered_cache.json`
(`Director of finance`, secrethunter.io) → `companies.csv` row (line 1212, now
`active=false`) → 7 `matched` rows and 7 `roles.jsonl` records from `jobs.secrettelaviv.com`
(a city board whose JDs name the real employers: Alma/Sisram, Artlist, Chargeflow) → one
`firmo_failed` strike → `company_info['Tel Aviv']` = Alma's blurb, cached 2026-08-25. The
daily `blurb dropped, not a company: Tel Aviv` was the read-time drop of that cached row,
printed on every digest since. **The gate is the right place to stop the spend**, and now
also purges the row (the hook runs inside daily-digest, seen.db's single writer). The rest
is not this lane's: the 7 ledger records still render a `### Tel Aviv` section (`roles`,
BACKLOG 223) and the seed row in `discovered_cache.json` (`discovery`).

## 5. For `infra` — `.github/workflows/firmographics.yml`, proposed, not written

```diff
 on:
   schedule:
     - cron: "0 10 * * *"
+    - cron: "0 23 * * *"       # after the 19:00 hunt (+200 min) and 20:00 expand: drain the
+                               # evening's intake BEFORE the 05:00 digest measures the gap
 ...
           python research_firmographics.py \
             --workers 2 \
             --limit "${{ github.event.inputs.limit || '150' }}" \
+            --budget-min 60 \
             --refresh-days "${{ github.event.inputs.refresh_days || '180' }}"
```

```diff
+      - uses: actions/setup-node@v4
+        with:
+          node-version: "22"        # 2.1.241 declares node >=22; the runner's default is 20
       - name: Install the Claude CLI
 ...
+      - name: Stamp the stage when the step died
+        # a job killed from OUTSIDE python (the 120-min timeout, an OOM) stamps nothing, and
+        # yesterday's stamp reads as healthy for two more mornings
+        if: failure()
+        run: python -m pipeline.stages stamp firmo alarm=step-failed
```

**Until `infra` applies this, nothing about the gap is automatic beyond one late slot a
day.** The three things the operator's standard names, as they stand: the workflow exists;
its cadence is one slot at 10:00 UTC that has fired 3 of 3 days, 5–11 h late; its alarms are
`alarms("firmo", 2)` (two missed nights), the stamp's `alarm=` key (any age) and the mail's
direction line. What this session changed is what the run *says*; what it could not change
is when it runs.

Why 23:00: `repo-state` is shared, so the run queues behind listing-hunt if it overruns;
a 60-minute budget ends before the 00:00 scrape-refresh wants the group. Why keep 150: a
ceiling under a budget is free. The §4 cron table is the linter's to hold, so this is
`infra`'s diff to land.

## 6. Aging (item 6) — decided, not fixed

1,247 records; `as_of` histogram: 08-21 **394**, 08-22 378, 08-23 154, then 14/15/18/22,
08-28 138, 08-29 114. **926 (74 %) share the 08-21..23 birth week**, so at
`--refresh-days 180` they all go stale in the same week of 2027-02 (BACKLOG 387;
`docs/decisions/2026-08-28-firmographics-refresh.md` re-measures 2026-11-19). It is **not**
the biggest thing here today: nothing is older than nine days, `employees_global` is null
on 39 and `founded` on 23, and the two defects this session fixed were both about *today's*
runs being illegible. The `--budget-min` loop is the mechanism a staggered refresh will
need (refresh names go last; a budget, not a cap, decides how many get a slot).

## 7. Model and params (item 7)

`research_company`: `sonnet` (served `claude-sonnet-5`), effort `low`, `WebSearch`
mandated by the system prompt (4/4 searched vs 1/4 when merely suggested — the 2026-08-26
measurement); blurbs: same model, tool-less; employees fill: idle in the cloud. Sonnet 5 is
$2/$10 per MTok against Opus 5's $5/$25; the lane's own N=2-per-level measurement found
effort moves nothing (2/2 at every level, `low` 30 % faster and half the cost). Optimised;
kept. `modelUsage[m].webSearchRequests` is the counter read (`llm._searches`).

## 8. Spend

Bright Data **0** — no rung of this lane runs in the cloud and pages do not close a gap of
missing LLM research. Claude **0 real calls** — every rehearsal through the fake seam.
No workflow dispatched or cancelled; `companies.csv` untouched.

## 9. Adversarial waves (Opus, read-only, against the worktree diff)

**Wave 1 — three attackers, 18 findings, 15 fixed with a guard each, 3 declined.**

Stamp/alarm attacker: (1) CRITICAL — a `--budget-min`-truncated all-fail run struck names
below the mass-failure guard, the exact objection the 08-28 record had raised → no strikes
when `done == 0 and attempted < queued`; (2) CRITICAL — zero attempts wrote the
`_stamp_ok` heartbeat vacuously → needs `attempted > 0`; (3) HIGH — a crash left
yesterday's stamp, silent for three mornings → `except BaseException` stamps
`crashed(<Type>)` and re-raises; (4) HIGH — `--budget-min` not wired in the workflow →
`infra`'s, 450; (5) HIGH — `load_companies()` returning `[]` stamped like a drained queue →
`empty-registry(...)` alarm and the same stamp shape on the early return; (6) `NaN` budget
passed the sign check and wrote `NaN` into a committed JSON → `math.isfinite`; (7)
`zero-produce` fired on one routine junk name → skipped for ≤ 4 names all answered and
refused, text carries `unavailable`; (8) infra-abort waited for in-flight calls and threw
their paid answers away → launches stop, in-flight is drained, `infra_streak` sticky at 3;
(9) `minutes` excluded setup → the run's own `t0`; (10) `stages.stamp` rebases on `{}` on
an unreadable file → shared, 451; (11) doc contract → this record.

Direction attacker: (F1) a second same-day digest re-based the baseline (08-28 ran twice)
→ only the day's first measurement stamps; (F2) the warning fired at firmo-stamp age 2, one
dropped slot, which `run.py`'s `alarms("firmo", 2)` deliberately ignores → age ≥ 3; (F3)
the zero-todo early return stamped without `todo` → fixed with (5); (F4) an unparseable
stamp date printed `(?)` beside "has never run" → `age unknown`, never warns; (F5) a
corrupt stamp file read as `(first measurement)` forever and disarmed the warning →
`direction unknown`, nothing written; (F6) the purge had no ceiling behind a predicate two
other lanes own → `max(3, 5 %)`, and the deleted text is printed. Verified read-only against
`cloud_state/seen.db`: 1 of 121 cached names flagged (`Tel Aviv`), 8 of 2,045 registry
names, 0 of 40 profiles. (F7) `stages.stamp` writes a LOCAL date — BACKLOG 269, unchanged.
Attacks that failed: persist merge losing the `intel` key; a no-digest morning; `-1` then
counted; a crashed `_enrich`; `st.conn` absent; the SQL; a stranded `.tmp`; the legacy
report; the export-field ban.

Envelope attacker: decoded the two 2.1.x result variants from the CLI bundle (449), timed
both failures at ~9.7 s ≈ 2 normal blurb calls, ruled out prompt-content envelope
mis-selection (nested objects are never decoded; the context travels on stdin), and found
the pinned CLI running on Node 20 against a `>=22` engine requirement (450). Listed the
eleven §7 sentences the diff made false or stale — all rewritten — and verified every
mutation-fixture `find` still occurs exactly once (60 records).

Declined: wiring `--budget-min` here (the workflow is `infra`'s); changing `stages.stamp`
(shared).

**Wave 2 — one attacker against the fixes: all 11 pinned (each reverted → a red test), 6 new
findings, all fixed with a guard.** (1) `except BaseException` stamped
`crashed(KeyboardInterrupt)` into a tracked file on the documented Ctrl-C path → re-raised
before the handler. (2) Wave 1's "≤ 4 junk names all refused is routine" carve-out is the
soft-outage shape on the steady-state queue — strike-gated names never reach `todo`, so a
small queue is NEW rows, and 4 of 4 refused also strikes 4 real names — **reverted**: every
all-fail night alarms, the number tells one leftover junk name from a dead morning.
(3) The truncated-run no-strike branch sits ahead of the mass-failure guard, so the heartbeat's
`not mass_failure` wrote "proved good" over 6-of-6 failures under a cap → heartbeat needs
every name attempted and < 5 failures. (4) `empty-registry` required a non-empty store,
disarmed on the double mass-zero → `not names` alone. (5) The grew-and-stale warning sat
inside the `export ok` branch, silenced on a corrupt-export morning → hoisted. (6) The purge
ceiling let a ≤ 3-row store be emptied → never the whole store. Test-quality: the scoped-run
assertion passed without the `not scoped` guard (the same-day rule blocked it) → runs
against a fresh stamp file now. Attacks that failed: sticky `infra_streak` on a recovered
run; strike starvation on a permanently capped queue (not a regression); argparse
`SystemExit` stamped as a crash; `gated` before assignment; `None`/`{}` through both
callers; `-1` then counted; the per-key merge under a same-hour double push; negative
`left`; `stages.stamp` raising inside the handler. Noted, unchanged: a local unscoped
`python -m pipeline.run` on the laptop would claim the day's `intel` baseline before the
cloud digest (the documented local invocations are scoped).
