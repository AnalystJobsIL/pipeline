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

## The flow, and the lane that owns each step

```
   ┌── 1 INTAKE ────────┐   LinkedIn · Indeed · Telegram  ──▶ discovered_cache.json
   │   lane D1          │   new employer names            ──▶ research_companies.json
   └────────┬───────────┘
            ▼
   ┌── 2 REGISTRY ──────┐   resolve a name to a board, repair a dead one,
   │   lane R  (excl.)  │   park what is genuinely dark   ──▶ companies.csv  (846 active)
   └────────┬───────────┘
            ▼
   ┌── 3 FETCH ─────────┐   F1 native ATS APIs (16 platforms, 435 rows)
   │   lanes F1 · F2    │   F2 the browser scraper        (411 rows) ──▶ scraped_cache.json
   └────────┬───────────┘
            ▼
   ┌── 4 ENRICH ────────┐   E1 job description text for every relevant role, any age
   │   lanes E1 · E2    │   E2 company facts: sector/stage/size/founded  (919 profiles)
   └────────┬───────────┘
            ▼
   ┌── 5 CLASSIFY ──────┐   Israel filter → relevance/seniority → LLM for the ambiguous
   │   lane K           │                                  ──▶ matched (the store)
   └────────┬───────────┘
            ▼
   ┌── 6 RENDER ────────┐   the board, the archive, the email, every tag on a role card
   │   lane V           │
   └────────┬───────────┘
            ▼
   ┌── 7 DELIVER ───────┐   commit state · publish the board · relay the email · archive
   │   lane S  (excl.)  │   semantics · the merge machinery · the workflows
   └────────────────────┘

   lane W · docs and readability — cuts across all seven
```

## Lanes, and what each may write

Pick ONE. The split exists so that two lanes never write the same file.

| lane | step | owns | primary files |
|---|---|---|---|
| **D1 · discovery & intake** | 1 | where new roles and new employers come from | `discovery_daily.py`, `discovery_telegram.py`, `pipeline/aggregators.py`, `pipeline/recruiters.py` |
| **R · registry & resolvers** *(exclusive)* | 2 | dark rows, the 23-tool resolution ladder | `companies.csv`, `listing_hunt.py`, `triage_dark.py`, `crack_walled.py`, `deep_validate.py`, `repair_*.py`, `resolve_*.py`, `audit_empty_rows.py`, `probe_candidates.py`, `scan_dead_domains.py`, `auto_expand.py`, `apply_resolved.py` |
| **F1 · ATS fetch layer** | 3 | how a board's API is read; adding a platform | `pipeline/fetchers.py`, `pipeline/platform_check.py`, `pipeline/health.py` |
| **F2 · the scraper** | 3 | the 5-strategy browser extraction for the 411 no-API companies | `scrape_universal.py`, `refresh_scrape_cache.py`, `cache_new_rows.py` |
| **E1 · JD enrichment** | 4 | every relevant role gets its description, whatever its age | `pipeline/jdfill.py`, `enrich_scrape_jd.py`, `enrich_matched_jd.py` |
| **E2 · company intelligence** | 4 | sector / stage / employees / founded / Israel centre | `pipeline/firmographics.py`, `pipeline/company_info.py`, `research_firmographics.py`, `bd_employees.py`, `fill_employees_llm.py`, `company_type_analysis.py` |
| **K · classifier** | 5 | which roles qualify, and the LLM tier that decides the ambiguous ones | `pipeline/seniority.py`, `pipeline/israel.py`, `llm_cache` invalidation |
| **V · board & email rendering** | 6 | how a role reads; every tag on a card | `pipeline/digest.py`, `pipeline/roleprofile.py`, `docs/TAGGING.md` |
| **S · state, delivery & infra** *(exclusive)* | 7 | stores, merges, workflows, archive semantics, the relay | `pipeline/store.py`, `pipeline/run.py`, `merge_*.py`, `check_invariants.py`, `.github/workflows/*`, `mark_sent.py` |
| **W · docs & readability** | — | making all of the above legible to the next agent and to a visitor | `README.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `CLAUDE.md`, `docs/*` |

**Exactly one agent may hold R at a time, and one S.** R writes the registry every other
lane reads; S writes the workflows that run them all. Everything else is concurrent.

### Shared plumbing — read freely, change loudly

`pipeline/`: `notes.py` `verdicts.py` `company_identity.py` `atomic.py` `http.py`
`companies.py` `stages.py` `sources.py`. Every lane imports these and no lane owns them. If
your change needs one modified, **say so in your report and name the lanes it could affect** —
`company_identity` alone gates four activation paths, and `notes` gates every write to
`companies.csv`.

`pipeline/run.py` is the orchestrator: lane S owns it, but any lane may need a hook in it.
Propose the hook, do not smuggle it.

### Not in any lane (deliberately)

About 19 root scripts are one-shot captures, probes and superseded resolvers —
`bigtech_capture*.py`, `comeet_probe*.py`, `shot_*.py`, `ms_capture.py`, `probe_expand.py`,
`verify_jsearch.py`, `gen_test_board.py`, and friends. `HANDOFF.md` §4d lists them as safe to
delete after an import check; several are imported only for their regex tables, which is
itself the problem. **Lane W's job is to mark them; nobody else should spend time there.**

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

## Lane W · docs & readability — the standing brief

This lane has a fixed goal: **someone who has never seen this repo should understand what it
does and how the flow hangs together in ten minutes, and an agent should know where to start
in twenty.** Today neither is true. The known gaps, in order:

1. **There is no `CLAUDE.md`,** so nothing loads automatically — every session starts blind
   unless its prompt happens to name the right files. It should be short and point outward:
   what this repo is, the three rules that cost data (activation, single-writer, append-log),
   the local-run-without-side-effects commands, and "read `docs/AGENT_BRIEF.md`".
2. **`README.md` does not describe the flow.** 90 lines, most of it `companies.csv` API-URL
   patterns. A visitor cannot tell what the seven steps above are, or that a board and a
   daily email exist. It needs the flow at the top and the ATS patterns moved to `docs/`.
3. **`ARCHITECTURE.md` is a reference manual with no map.** 596 lines, correct and dense,
   but §0 is prose — there is no single picture of intake → registry → fetch → enrich →
   classify → render → deliver. Add one, and make every section say which lane owns it.
4. **`HANDOFF.md` is 753 lines mixing two things**: durable rules that belong in
   `ARCHITECTURE.md` (the ownership matrix in §1b, the failure classes in §2, the backlogs in
   §4c/§4d) and dated session narrative that belongs in a per-session archive. Split it. What
   remains should be: what changed last session, what is known-broken, what is unclaimed.
   It also has two sections numbered `## 4d.`
5. **A reader cannot tell live code from dead.** 89 modules, ~19 of them one-shot or
   superseded, no marker. Move them to `legacy/` or annotate them — after checking imports,
   because several are imported only for their regex tables.

Constraints: **documentation only.** Do not "tidy" code in this lane — a rename here breaks
four other lanes silently. Every claim you write must be checked against the code or a live
run, because the failure mode this repo punishes hardest is a confident document that is no
longer true (`SCHEDULING.md` told readers the email was unbuilt for three days after it
started shipping). When you move text, move it — do not rewrite it from memory.

Done when: a `CLAUDE.md` exists, `README.md` opens with the flow, `ARCHITECTURE.md` has a map
and per-section lane ownership, `HANDOFF.md` is under ~250 lines of current state, and dead
code is marked. Verify by re-reading `docs/AGENT_BRIEF.md`'s reading list and checking every
pointer still resolves.

## Definition of done

- The change is verified by its **output**, not its exit code — quote the numbers.
- `pytest` and `check_invariants.py` green; a new guard added for any bug you fixed
  (`tests/test_units.py` is a list of shipped bugs, one assertion each).
- `HANDOFF.md` updated: what was wrong, what you changed, what you did NOT finish.
- Say explicitly what you left for someone else, and what you spent (BD credits, LLM calls).
