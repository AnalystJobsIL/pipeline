# 2026-08-28 — `company-intel`: a strike that could not survive its own runner, and 137 companies

The lane had not run a session all week. In that time the registry grew **862 → 1,000 active
rows** and the facts corpus did not follow. The operator's goal for the weekend was "all
companies + intel".

Everything below is pinned to a rev and re-derived. The shared checkout was 102 commits behind
`origin/master`, so every read was `git show origin/master:<path>` and all work happened in
`.claude/worktrees/cintel-0828`, branched from **`759ba36`**.

---

## 1. The deliverable: 138 → 4

**The brief's "154 without intel" is a raw-NAME count, and the code already resolves 16 of
them.** `HP`→`HP Inc.`, `Dell`→`Dell Israel`, `eBay`→`eBay Israel`, `Check Point
Software`→`Check Point Software Technologies`, `PayPal Israel`→`PayPal`, `Akamai
Technologies`→`Akamai`, `Samsung Israel`→`Samsung`, `Continental`→`Continental Israel`, `GE
HealthCare`→`GE HealthCare Israel`, `Innoviz`→`Innoviz Technologies`, `Applied Materials -
Israel`→`Applied Materials`, `ISCAR ISRAEL`→`Iscar`, plus `TechBiz Global`, `PAPAYA`,
`Tenengroup Ltd.` and `Nexar Inc.` `rolecard`/`digest` render these through `display_index`,
so their cards were already correct and they cost nothing. The digest's own gauge agreed with
the code and not with the brief: it printed `registry backlog 139` at 17:39 on 08-28.

Minus the `Discovery` pseudo-row (excluded by **platform**, not by name — `Discovery Inc` is a
real company), the real target set was **137**.

```
python -c "import json,csv;from pipeline.firmographics import identity_key as k,display_index;d=json.load(open('cloud_state/firmographics.json',encoding='utf-8'));i=display_index(d);a=[r['company_name'] for r in csv.DictReader(open('companies.csv',encoding='utf-8-sig')) if r['active'].strip().lower()=='true'];m=[n for n in a if not (d.get(n) or i.get(k(n)))];print(len(a),len(m),sorted(m))"
```

**Result: 133 researched, 2 failed, export 997 → 1,132.** Registry backlog **138 → 4**, and
each survivor is named with a reason:

| name | why it is still there |
|---|---|
| `Discovery` | the pseudo-row. Never a research target, by design |
| `Peak Innovation` | strike since 2026-08-24, weekly retry, releases 08-31 |
| `ImagineArt` | failed tonight — and also failed on the 08-27 cron. Struck |
| `Plateful` | failed tonight. Struck |

Render-set coverage (active rows ∪ every matched company, minus the pseudo-row) is
**1,022 of 1,027 = 99.5 %**; the five without facts add `Tel Aviv` (refused by
`not_a_company`) and `Hila & Co.` (strike) to the four above.

**Verified by output before the commit, not by exit code:** a strict superset of origin's 997
with **0 dropped and 0 pre-existing records changed**; on all 135 new records `sector`
non-empty, `stage ∈ STAGES`, `size_band ∈ SIZE_BANDS` and equal to
`band_for(employees_global)`; **0** refused by `not_a_company`; **0** new key colliding with an
existing `identity_key`; `as_of` = 2026-08-28 on all 135.

Two checks I had planned were **wrong** and were dropped or moved:

- `il_center ≤ 48 chars` is the **chip** cap (`company_intel.CHIP_MAX`), not the record's.
  `_coerce` caps free text at 300, and **439 of the pre-existing 997 exceed 48 by design** —
  applying it would have rejected good records, or worse, tempted a write-time truncation that
  destroys the full text `chip_safe` deliberately preserves.
- the superset assertion belongs in `--export`, where it now lives, **not** in a human
  verification step that only one agent will ever perform.

## 2. The cron: what one run does, against what the registry does

`gh api .../workflows/firmographics.yml/runs` → `total_count: 1`. **One run, ever.**

| | |
|---|---|
| run `33111630696`, event `schedule` | created **2026-08-27T20:05:39Z**. The cron is `0 10 * * *` — **+605 minutes late** |
| queued on `concurrency: repo-state` | ~21 min |
| research step | **2 m 53 s** |
| produced | **19 researched, 4 failed**, export 971 → 995 |
| spent | `seam: claude-sonnet-5 x23 \| 23 calls, 334 s, 30 searches` — **no `SEARCHLESS`** |
| the backlog it faced | **23**. `--limit 40` never bound |

**The 2026-08-28 10:00 slot never fired** — no `firmo-bot` commit exists for 08-28, and across
that day's two digests `registry backlog` went **74 → 139** with nothing draining it.

**The arithmetic.** 40/run × the observed 1-of-2 slot reliability ≈ **20 profiles/day
effective**, against registry growth of **+29/day** mean and **+62/day** over the last 48 h.
One run cannot keep pace and the gap grows. Wall clock is not the constraint — 14.5 s/call at
2 workers means 40 calls in ~10 minutes inside a 120-minute job. The operator's decision was
to leave `--limit 40` (after tonight's drain a 40-deep backlog should be rare), so the finding
is reported rather than engineered around, and what shipped instead is the alarm that makes
the next silent stall visible.

## 3. The defect: a strike that cannot survive the runner that made it

The 08-27 run struck `Sivo`, `ImagineArt`, `Chalk` and `Instacart`. The committed
`cloud_state/seen.db`'s `firmo_failed` holds three unrelated rows and **none of the four**.

The sharp statement is not "the workflow does not commit `seen.db`". It is that
**`store.DEFAULT_DB` is `<repo>/state/seen.db` and `.gitignore` ignores `state/`**, so on a
runner `SeenStore()` opens a brand-new **empty** sqlite every run: the cron's strike write is
ephemeral **by construction**. Consequences, both live: the bulk researcher re-bought every
unresearchable name on every run, and `refresh_abandoned` (4+ strikes) could never fire in the
cloud at all.

Shipped: `cloud_state/firmo_failed.json`, read by **both** tiers through
`firmographics.all_failures` — the digest read `st.load_firmo_failures()` alone, so it would
re-buy at up to 5 calls/run what the cron had struck. Merged by `merge_failures`, which takes
`attempts` and `last` **independently**; the merge it replaces kept `max(attempts)` *inside*
`if last > have[1]`, so an older source's higher count was discarded with its date — the exact
reset `_failure_union`'s own docstring promised to prevent.

Validated on read, because every bad shape has a permanent consequence: `"last": null`
stringifies to `"None"`, and `"None" > "2026-08-21"` is **True** (`N` is 0x4E, `2` is 0x32), so
a null would win every "latest strike wins" comparison **and** clear the 7-day gate — gating
that company for the life of the file. Written read-modify-write and **never from a corrupt or
partial read**, because `s_company_dict` honours deletions (correctly: dropping a key is the
only way this ledger can say "researched since").

Live proof it works: tonight's two strikes are in the committed file. Under the old code they
would have died with the process that made them. And `Chalk` and `Instacart`, which the 08-27
cron struck, both **succeeded** tonight — so some of those failures were transient, which makes
clearing-on-success worth as much as the persistence.

## 4. Two more found in the write path while measuring

- **`--export` published the sqlite table over a corrupt export.** `union_store(st)` calls
  `load_shared()`, which drops `load_shared_status`'s verdict, so over a corrupt or
  half-written file the union was sqlite **alone** and `save_shared` wrote it with an
  encouraging `exported N records`. That is the one thing `load_shared_status`'s own docstring
  says must never happen, and the digest hook was the only caller honouring it. It now
  refuses, asserts the superset, reports the delta with a sign, and **exits non-zero** — an
  `::error::` that exits 0 is CLAUDE.md rule 1 from the inside.
- **No refresh can run while the backlog exceeds `--limit`.** Refresh names are appended last
  and `--limit` truncates from the end: `plan_counts(137, 20, 40) == (40, 20)` — all twenty
  deferred. The ordering is right and stays (a company with **no** facts renders a card with
  no chips, which is worse than one whose chips are six months old); what was wrong is that it
  was silent, and it bites exactly when the registry is growing fast. Now reported, and the
  `N to do` line prints what will actually be attempted — it printed the pre-limit count, so a
  `--limit 40` run announced "137 to do" and attempted 40.
- **Per-company progress was block-buffered**, so a 45-minute run emitted its first byte at the
  end: the 08-27 run's 23 result lines all carry the timestamp `20:30:05`. An unflushed long
  job is indistinguishable from a hung one.

## 5. Staleness: decided with a number, and the number says do not build

Full reasoning in **`docs/decisions/2026-08-28-firmographics-refresh.md`**. In short:

**There is no stale tail.** Every one of the 997 `as_of` values fell in 2026-08-21..28
(394/378/154/14/15/18/22/2 by day). Nothing was older than **seven days**, so §7's "a company
profiled once in July" cannot be true — there is no July. And a refresh path **does** exist
(`--refresh-days`, `is_stale`, `REFRESH_CAP = 20`): nothing re-researches before **2027-02-17**
by design.

**The planned 12-call measurement was dropped, and that is the finding.** Re-researching a
7-day-old record measures **model variance**, not staleness — the rule attributed all of it to
elapsed time. And n=12 with a ≥3 threshold says "build it" **11 %** of the time at a 10 % noise
floor and "build nothing" **56 %** of the time at a real 20 % rate. A rule that cannot say no
for the right reason is not a measurement. A real one needs a current-evidence control arm and
**~20–30 per arm (40–60 calls)**, and is not runnable at any n until records have actually
aged. Re-measure **2026-11-19**.

Two things that are true and were free: **548 of 997** records cite nothing newer than 2023 in
`stage_note` (evidence recency, not record age; one cites **2027** — `Alma Labs`), and all 997
share a birth **week**, so at 180 days the whole store turns stale between 2027-02-17 and
2027-02-24 against a 20/run cap. Filed as **387**, with six months of warning.

## 6. The LLM contract: both claims hold, one document correction

- **The search MANDATE is live in shipped code.** `firmographics._RESEARCH_SYSTEM` still
  carries `"ALWAYS search the web before you answer… Never answer from memory alone"`, pinned
  by `test_the_research_prompt_mandates_a_web_search` over both `_RESEARCH_SYSTEM` and
  `fill_employees_llm._SYSTEM`. **Production confirms it**: the 08-27 cron made 23 calls and 30
  searches with no `SEARCHLESS`, and tonight's drain made 137 calls and **162 searches, 0
  SEARCHLESS**.
- **`modelUsage[m].webSearchRequests` is still the counter.** `pipeline/llm.py:184 _searches()`
  sums exactly that field, and its docstring still names
  `usage.server_tool_use.web_search_requests` as the wrong one.
- **Correction for the next reader:** `docs/RUN_LOG.md` is not a dated run log — it is "Reading
  one run", written 08-27, and it carries both claims correctly. **There was no 2026-08-27
  digest at all**, so anyone checking "the 08-27 mail" for this lane's line finds nothing; the
  08-27 evidence is the workflow run log.

## 7. The alarm (`359@company-intel`, half closed)

The `Company intel:` line now raises `::warning::company-intel` when the export's newest record
is more than `EXPORT_STALE_DAYS` (2) old **and** the registry backlog is non-zero.

Deliberately **not** a backlog threshold. The registry adds 30–100 active rows a day, so an
absolute bar is crossed on healthy mornings — and the clause immediately above it in
`audit_lines` was rejected in August for exactly that reason ("a warning that is always on is a
warning nobody reads"). The `_rb > 0` half is what stops a *drained* backlog and a quiet week
from firing it. Known blind spot, quantified: the digest stamps today's date on any board
company **it** researches, which would reset the clock while the bulk cron stayed dead — but it
researched 0 on all three of the 08-27/08-28 runs, because board companies are profiled
same-day and stay profiled.

The **floor** half of 359 is filed as **388@infra**, not built here:
`persist_state.key_deltas` already measures this exact path every run, and `shrank()` simply
cannot fire on it — it needs `lost ≥ 10` **and** `lost ≥ 3 %`, which on a 1,132-record store is
34 keys, so the 22-record loss of 2026-08-26 raised nothing. That threshold is shared by seven
`s_company_dict` paths and moving it on this lane's judgement would shift five other lanes'
noise floors.

## What this spent

| | |
|---|---|
| **Bright Data** | **0.** `bd_employees.py` was not run. No Unlocker, no dataset. `secrets.env` was never copied into the worktree (`381@registry`: pytest books real credits when it is present) |
| **SerpApi** | 0 — exhausted until 2026-09-01 |
| **Claude subscription** | **137 research calls**, 2,882 s model time, **162 web searches, 0 SEARCHLESS**, sonnet at `effort=low`. The 12-call staleness measurement was **not** spent |
| Subagents | 7 Opus sessions: 2 design critics (both NO-GO on parts of the first design), 3 attackers, 2 confirmers |

## Gates

**Baseline at `759ba36`, my own edits stashed: `3 failed, 1251 passed, 11 skipped`** —
`test_no_two_active_rows_share_a_board` (`registry`),
`test_native_url_is_derived_from_the_public_url_alone`, and
`test_every_open_role_in_the_ledger_carries_a_job_description` (reads live data). **None is
this lane's, and none is `379`/`374`** — the brief named those two, but `379`/`380`'s
`test_two_rehearsed_nights_keep_every_pool` is now GREEN (fixed by `registry` in `43c68f8`) and
`374` is not a test failure at all, it is two open backlog items in `jd-text` and `docs`.

After: **same three failures**, `1272 passed` — independently confirmed by the mutation gate's
own baseline line. `check_invariants.py` and `docs/check_docs.py` green (0 errors).

## The design critics changed the plan before any code was written

Both wave-0 critics returned NO-GO on parts of the original design, and they were right:

- **The invariance replay I planned was a screenshot.** `--dry-run` **returns before**
  `if a.limit:`, so "the dry-run output is byte-identical before and after" would have been
  guaranteed by control flow no matter what the patch did. Replaced by `plan_counts`, a pure
  function with behavioural assertions and a mutation aimed at it.
- **`--budget-min` as designed was unimplementable.** All futures are submitted up front
  (`futs = {ex.submit(...) for name in todo}`), so there is no "next submit" to guard: breaking
  the loop either drains the whole queue anyway (the budget is a no-op that still prints
  `N not reached`) or discards results already paid for. It also could have converted a soft
  outage into four real strikes by truncating below the `failed >= 5 and done == 0` guard, and
  a budget stop with zero calls would still have stamped `_stamp_ok()` — the health heartbeat
  that deletes the operator's standing alert. **Dropped from tonight entirely**; the drain ran
  with no `--limit` and no budget flag, which the module docstring already documents as
  Ctrl-C-safe.
- **The drain would have run against an EMPTY store.** A fresh worktree has no `state/`, so
  `SeenStore()` would have had no failure memory. The main checkout's `state/seen.db` was
  copied in first, which gated 2 names that would otherwise have been re-bought.
- **The backlog-threshold alarm and the shrink alarm were both NO-GO** — the first fires on
  every healthy morning, the second read a value that does not exist (`pipeline_stages.json`
  holds `collect`/`enrich`/`expand`/`publish`/`repair` and no record count).
- **The 12-call staleness measurement was NO-GO** for the reasons in §5.

## NOT finished

- **387** — the 2027-02 thundering herd. Six months of warning; do not spend now.
- **388@infra** — `shrank()` cannot see a 22-record loss on this store. The floor half of 359.
- **`385@company-intel`** (`bd_employees.unlock` is an uninstrumented spend path) is untouched;
  this session ran it zero times.
- The `Discovery` pseudo-row is excluded from targeting by platform but is **not** refused by
  `not_a_company`, so it still counts against the render set. Cosmetic; not filed separately.
- Whether the 10:00 cron fires at all is `infra`'s (`293`), and this session adds its second
  and third data points rather than building a second cron.
