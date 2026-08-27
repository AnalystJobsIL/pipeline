# Automation inventory — everything that runs without a human, and when it actually ran

`docs/BACKLOG.md` has asked for this table since 2026-08-22 ("you can't simplify what you
can't enumerate"). It exists because the schedules live in three places — GitHub Actions
crons, a Windows scheduled task, and whatever a session runs by hand — and no document
covered all three. `ARCHITECTURE.md` §4 is still the **authoritative** cron table and the one
`docs/check_docs.py` checks against the workflow files; this page adds the two things §4 does
not carry: **what each job spends**, and **when it actually fired**.

Lane: `infra` owns the workflows. `docs` owns this page. Written 2026-08-27.

## The nominal schedule is not the real one

Every cron below is dispatched by GitHub, and GitHub dispatches when it feels like it.
Measured from `gh run list --repo AnalystJobsIL/pipeline --json name,event,createdAt`, all
scheduled runs 2026-08-23 → 2026-08-27:

| workflow | cron (UTC) | 08-23 … 08-26 actual | 2026-08-27 |
|---|---|---|---|
| `scrape-refresh` | `0 0 * * *` | 00:38 · 00:39 · 00:38 · 00:39 | **05:41** (+5 h 41) |
| `retry-unreachable` | `30 2 * * *` | 03:29 · 03:25 · 03:31 | **never fired** |
| `audit-coverage` | `0 4 * * 0` | 04:40 (Sun 08-23) | next due 08-30 |
| `daily-digest` | `0 5 * * *` | 05:34 · 05:42 · 05:36 · 05:38 | **never fired** (checked 07:41) |
| `self-heal` | `0 6 * * *` | 06:17 · 06:29 · 06:20 · 06:22 | **never fired** |
| `auto-expand` | `0 8,20 * * *` | 08:34/20:26 · 08:51/20:33 · 08:47/20:32 · 08:48/**22:53** | — |
| `firmographics` | `0 10 * * *` | added 2026-08-26 | **0 runs, ever** |
| `triage-dark` | `0 18 * * *` | 18:28 · 18:39 · 18:38 · **19:46** | — |
| `listing-hunt` | `0 19 * * *` | 19:18 · 19:24 · 19:26 · **21:34** | — |
| `tests` | on push | — | — |

**Three things follow from that table, and each is a real exposure.**

1. **The documented ordering is not enforced by anything.** `triage-dark` 18:00 →
   `listing-hunt` 19:00 → `scrape-refresh` 00:00 → `daily-digest` 05:00 is a chain each step
   of which reads the previous one's output. On 2026-08-27 the refresh ran at 05:41, i.e.
   *after* the digest's own slot. Nothing detects the inversion; the digest simply reads
   yesterday's cache and its `Stage order:` line says `collect: … (1d ago)`.
2. **A run that never starts emits nothing at all.** Every "the run broke" path in this repo
   — `stages.alarms("publish", 1)`, `persist_state.py outcome`'s dated failure notice, the
   `Stages:` line — fires from *inside* a later digest. If the digest is never dispatched
   there is no board, no mail, no alarm and no `::warning::`: **silence reads as success.**
   On 2026-08-27 no email was sent and nothing anywhere said so. Owner: `infra`.
3. **The relay can miss the mail entirely.** `AnalystJobsIL/inbox` polls at
   `17 6,7,8,10 * * *`. A digest that lands after 10:17 is not relayed that day at all. Even
   on a normal day the promise is not being kept: the 08-26 issue was created at 07:10:36Z
   and the 08-25 one at 09:01:19Z, against a documented "expect the mail at ~06:20 UTC".

**How to check, in one command, whether yesterday actually happened:**

```bash
gh run list --repo AnalystJobsIL/pipeline --workflow daily-digest.yml --limit 3
gh issue list --repo AnalystJobsIL/inbox --limit 3 --state all      # did the mail go out?
```

## What each job spends, and what it writes

`BD` = holds `BRIGHTDATA_API_KEY`. `LLM` = holds `CLAUDE_CODE_OAUTH_TOKEN`. Both are counted
from the workflow files, not asserted.

| workflow | concurrency group | BD | LLM | writes |
|---|---|---|---|---|
| `daily-digest` | `daily-digest` (its own) | yes | yes | `docs/index.html`, `docs/archive.html`, `digests/latest.md`, `cloud_state/seen.db`, `roles*.jsonl`, `stale.json`, `pipeline_stages.json` |
| `scrape-refresh` | `repo-state` | yes | yes | `scraped_cache.json`, `scrape_rot.json` |
| `retry-unreachable` | `repo-state` | yes | no | `companies.csv` |
| `self-heal` | `repo-state` | yes | no | `companies.csv`, `resolve_attempts.json` |
| `auto-expand` | `repo-state` | yes | yes | `companies.csv`, `research_companies.json`, `auto_expand_seen.json` |
| `triage-dark` | `repo-state` | yes | yes | `companies.csv` |
| `listing-hunt` | `repo-state` | yes | yes | `companies.csv`, `registry_ladder.json` |
| `audit-coverage` | `repo-state` | yes | yes | `companies.csv`, `audit_seen.json` |
| `firmographics` | `repo-state` | no | yes | `cloud_state/firmographics.json` only — never `seen.db` |
| `tests` | — | no | no | nothing |

**Eight of the nine scheduled workflows share the `repo-state` concurrency group**; only
`daily-digest` has its own. A long job makes the next one queue or be superseded, with no
error anywhere.

## The other two schedulers

**The Windows scheduled task is dead.** `IsraeliJobs-Firmographics` ran
`run_firmo_chain.cmd` every 6 h on the operator's machine. It is **`Disabled`** — verified
2026-08-27 with `Get-ScheduledTask -TaskName 'IsraeliJobs*'`. It was disabled on the
operator's instruction that production belongs in the cloud, and because it was actively
harmful: it wrote `cloud_state/firmographics.json` into the *shared* checkout without
committing, so another lane's `git pull --rebase` stashed 22 researched companies. Its work
is now `.github/workflows/firmographics.yml`. To bring it back:
`Enable-ScheduledTask -TaskName 'IsraeliJobs-Firmographics'`.

**By-hand runs.** `docs/MODULES.md`'s *Operator tools* section is the list, and
`docs/check_docs.py` now fails if any of them is silently promoted to a cron without being
reclassified — which is exactly what happened to the three firmographics tools when
`firmographics.yml` landed.

## Known gaps, filed not fixed

- Nothing notices a cron that did not fire (`infra`).
- `cloud_state/last_run.json` was two days stale on 2026-08-27 (`2026-08-25`), which silently
  degrades one of the digest's own alarm feeds, `run.py::_last_run_alarms` (`infra`).
- `firmographics.yml` has never fired on its cron since it was added on 2026-08-26
  (`infra`/`company-intel`).
