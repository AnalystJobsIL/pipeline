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
| `daily-digest` | `0 5 * * *` | 05:34 · 05:42 · 05:36 · 05:38 | **never fired** (re-checked 09:00) |
| `self-heal` | `0 6 * * *` | 06:17 · 06:29 · 06:20 · 06:22 | **never fired** |
| `auto-expand` | `0 8,20 * * *` | 08:34/20:26 · 08:51/20:33 · 08:47/20:32 · 08:48/**22:53** | **never fired** |
| `firmographics` | `0 10 * * *` | added 2026-08-26 **19:50 UTC**, after that day's slot | **first real slot came and went: 0 runs at 10:17** |
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
3. **The relay can miss the mail entirely.** *(Answered 2026-08-28: the relay is now
   triggered by a push from the digest, and the delivery deadline moves with it — see the
   section below. The paragraph is kept because it is what the measurement said.)*
   `AnalystJobsIL/inbox` polls at
   `17 6,7,8,10 * * *`. A digest that lands after 10:17 is not relayed that day at all. Even
   on a normal day the promise is not being kept: the 08-26 issue was created at 07:10:36Z
   and the 08-25 one at 09:01:19Z, against a documented "expect the mail at ~06:20 UTC".

**Re-checked at 09:00 UTC**: still nothing. Five of the day's six due crons had not fired
(00:00 ran at 05:41; 02:30, 05:00, 06:00 and 08:00 had not run at all), and the relay's last
poll is 10:17 — so 2026-08-27's email is most likely lost outright, with no artefact anywhere
recording that it was.

**How to check, in one command, whether yesterday actually happened:**

```bash
gh run list --repo AnalystJobsIL/pipeline --workflow daily-digest.yml --limit 3
gh issue list --repo AnalystJobsIL/inbox --limit 3 --state all      # did the mail go out?
```

### 2026-08-28: a second such day, and what changed because of it
*(appended by `infra` 2026-08-28; the table above is 08-23..08-27 and is not restated here)*

| workflow | due | actual |
|---|---|---|
| `triage-dark` | 18:00 (08-27) | 02:02 (+8 h 02) |
| `listing-hunt` | 19:00 (08-27) | 02:24 (+7 h 24) |
| `auto-expand` | 08:00 | 04:05 |
| `scrape-refresh` | 00:00 | **07:49** (+7 h 49) |
| `retry-unreachable` | 02:30 | **never fired** |
| `daily-digest` | 05:00 | **never fired** — dispatched by hand at 06:43 |
| `self-heal` | 06:00 | **never fired** |
| inbox relay | 06:17 / 07:17 / 08:17 / 10:17 | **0 of 4** — dispatched by hand at 08:28 |

Point 3 above is now half-answered and point 2 is not. The relay's real trigger is a **push**
from `daily-digest`'s last step, which carries the sha256 of what actually landed; its four
crons remain as a backup (ARCHITECTURE §4, `docs/decisions/2026-08-28-relay-trigger.md`).
So a digest that *happens* is now mailed without waiting on a clock. A digest that is never
dispatched still emits nothing at all — that is 292/308@infra, and it is untouched.

Worth recording because it is the part that worked: the second, hand-dispatched digest run
that day FAILED at its `pipeline` step, and `cloud_state/last_run.json` reads
`"delivered": true, "notice": false` — the delivery guard refused to overwrite the morning's
good digest with a failure notice.

Two more things every job now reports, both new on 2026-08-28: `[bd-spend] this step bought N
Bright Data credit(s)` from any process that touches the account (previously only
`scrape-refresh` counted, and only into a state file), and `path: N -> M keys (+g / -l)` for
every keyed cache a commit pushes (ARCHITECTURE §5d).

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
- `firmographics.yml` has now **missed its first real cron slot**. It was created at
  19:50 UTC on 2026-08-26, *after* that day's 10:00 window — so "never fired, ever" was
  true but meant nothing until today. At **10:17 on 2026-08-27** the 10:00 slot had passed
  and `gh run list --workflow firmographics.yml` was still empty. That is now evidence,
  not an artefact of when the file landed, and it matches the same morning's 02:30, 05:00,
  06:00 and 08:00 crons not firing either (`infra`/`company-intel`).
