# Agent brief — read this before touching anything

For a session spawned to work on ONE part of the pipeline while other sessions work on
others. It exists because the docs are deep but not ordered, and because several parts of
this repo are unsafe to edit concurrently.

## Read in this order (~20 minutes)

1. **`ARCHITECTURE.md` §0** — what the user actually receives, and how to run anything
   locally without side effects. Non-negotiable.
2. **`ARCHITECTURE.md` §2** — the four rules that cost real data to learn: the
   verdict-string rule, the activation rule, the single-writer rule, and the note
   append-log. **If you are changing a resolver, an activation path, or anything that
   writes `companies.csv`, these ARE the spec.**
3. **`HANDOFF.md` §0 (A–Q)** — the seventeen defects found on 2026-08-23 and how each was
   fixed. Read the ones adjacent to your lane; skim the rest. This is the best single
   description of how this codebase fails: green workflow, plausible log line, no coverage.
4. **`HANDOFF.md` "Watch list"** — what is known-broken and unclaimed. Your lane may be on it.
5. **Your lane's section** from the table below.

Skim only when relevant: `ARCHITECTURE.md` §3 (resolution ladder), §5 (state files and who
writes them), §5b (the "why isn't company X in my email" runbook), §7 (firmographics),
`docs/TAGGING.md` (every board tag and where it is computed), `docs/BRIGHTDATA.md`.

**Do NOT read `SCHEDULING.md`** — it is stale (2026-08-14) and says the email is "NOT YET
ENABLED". The email has shipped daily since 2026-08-20 via `AnalystJobsIL/inbox`'s
`digest-email.yml`. `ARCHITECTURE.md` §4 has the real schedule.

`HANDOFF.md` §1–§4d is dated narrative from earlier sessions. Useful when archaeology is
needed; not required to start.

## Lanes, and what each may write

Pick ONE. The point of the split is that two lanes never write the same file.

| lane | owns | may write | must not touch |
|---|---|---|---|
| **A · board & email rendering** | how a role reads | `pipeline/digest.py`, `pipeline/roleprofile.py`, `docs/TAGGING.md` | anything under "coverage" |
| **B · classifier quality** | which roles qualify | `pipeline/seniority.py`, `pipeline/israel.py`, the LLM prompt, `llm_cache` invalidation | `companies.csv` |
| **C · coverage & resolvers** *(exclusive)* | dark rows, the 23-tool ladder | `companies.csv`, `listing_hunt.py`, `triage_dark.py`, `crack_walled.py`, `deep_validate.py`, `repair_*.py`, `resolve_*.py` | `pipeline/digest.py`, workflows |
| **D · fetch layer & ATS registry** | how a board is read | `pipeline/fetchers.py`, `pipeline/ats.py`, `pipeline/platform_check.py` | `companies.csv` rows (ask C) |
| **E · state & infra** *(exclusive)* | stores, merges, workflows | `pipeline/store.py`, `merge_*.py`, `.github/workflows/*`, `check_invariants.py` | `companies.csv` |

**Exactly one agent may hold lane C at a time, and one lane E.** C writes the registry that
every other lane reads; E writes the workflows that run them all. A and B and D can run
concurrently with each other and with one C and one E.

## Shared, finite, and easy to exhaust

Declare these in your plan before spending them:

- **Bright Data credits** — the Web Unlocker and the LinkedIn/Indeed datasets. Every
  discovery run, JD enrichment pass and unlocker search spends them. Budget env vars exist
  (`JD_ENRICH_BD_CAP`, `MATCHED_JD_BD_CAP`, `DEEP_BD_SEARCH_CAP`); use them.
- **SerpApi — exhausted until 2026-09-01.** Anything relying on it silently returns nothing.
  The working search is `deep_validate.google_via_unlocker`.
- **`CLAUDE_CODE_OAUTH_TOKEN`** — one subscription, shared by role classification, company
  blurbs, firmographics research and LLM extraction. Symptom of expiry: `LLM calls this
  run: 0` with a large `llm_failed_fallback` count.
- **GitHub Actions concurrency group `repo-state`** — five scheduled workflows share it. A
  long job makes the next one queue or be superseded.
- **DuckDuckGo is blocked from this machine** and works on the runners.

## Rules that will bite you

1. **A green workflow means nothing.** 13 of 39 steps are `continue-on-error`. Read the step
   output; confirm a capability did work by looking at what it produced.
2. **A mass-zero result is a broken run, not a measurement.** Strip its verdicts, diagnose,
   re-run.
3. **Never `git add -A`** — another lane's work is in this tree. Stage explicit paths.
4. **`python check_invariants.py` must pass before you commit** anything touching
   `companies.csv`. `python -m pytest -q` (122 assertions, ~1s) must pass before any push.
   Every assertion in that file is a bug that shipped; if one goes red, your change is wrong.
5. **Commit as `ajil-bot` and push with plain `git push`.** Read `CLAUDE.local.md` first —
   the public repos must not be linkable to the owner's personal account.
6. **Prefer letting the crons run.** If you must dispatch a workflow manually, delete the run
   record afterwards (`CLAUDE.local.md` §3). If you cancel a digest run, cancel it **before**
   the `Mark digested roles as sent` step, or that run's roles are burned as delivered and
   the next run will not email them.
7. Local runs are safe by default: `python -m pipeline.run --only "Wix,Fiverr" --no-llm
   --db /tmp/scratch.db` never emails, never publishes, and writes `out/docs-preview/`.

## Definition of done

- The change is verified by its **output**, not its exit code — quote the numbers.
- `pytest` and `check_invariants.py` green; a new guard added for any bug you fixed
  (`tests/test_units.py` is a list of shipped bugs, one assertion each).
- `HANDOFF.md` updated: what was wrong, what you changed, what you did NOT finish.
- Say explicitly what you left for someone else, and what you spent (BD credits, LLM calls).
