# Agent brief — read this before touching anything

For a session spawned to work on ONE part of the pipeline while other sessions work on
others. It exists because the docs are deep but not ordered, and because several parts of
this repo are unsafe to edit concurrently.

## Read in this order (~20 minutes)

0. **`CLAUDE.md`** — two minutes, and it loads automatically. What ships, the flow, the five
   rules, the quotas, the pre-push contract. If you read nothing else, read this.
1. **`ARCHITECTURE.md` §0 and "the whole system on one screen"** — what the user actually
   receives, and how to run anything locally without side effects. Non-negotiable.
2. **`ARCHITECTURE.md` §2** — the four rules that cost real data to learn: the
   verdict-string rule, the activation rule, the single-writer rule, and the note
   append-log. **If you are changing a resolver, an activation path, or anything that
   writes `companies.csv`, these ARE the spec.**
3. **`ARCHITECTURE.md` §8** — the failure classes. Silent exclusion, the mass-zero
   measurement, the two concurrency layers. One page, and it is why this repo needs a brief
   at all.
4. **`HANDOFF.md`** — the whole file; it is capped at 250 lines. Current state, the watch
   list, and what is unclaimed. Your lane may be on it.
5. **Your lane's section** from the table below, and **`docs/MODULES.md`** for the modules it
   names — it says which are scheduled, which are libraries nothing appears to run, and
   which are dead weight.

Skim only when relevant: `ARCHITECTURE.md` §3 (resolution ladder), §5 (state files and who
writes them), §5b + §5c (the "why isn't company X in my email" runbook and the debugging
one-liners), §7 (firmographics), `docs/TAGGING.md` (every board tag and where it is
computed), `docs/BRIGHTDATA.md`, `docs/ATS_PLATFORMS.md` (companies.csv columns and the
per-platform URL patterns).

**Archaeology, not required to start:** `docs/sessions/2026-08-23.md` is the seventeen
defects (A–Q) found that morning and how each was fixed — the best single description of how
this codebase fails: green workflow, plausible log line, no coverage. Read the ones adjacent
to your lane if you have time. `docs/sessions/2026-08-22.md` is the migration and the
ten-agent audit. `docs/decisions/` holds superseded design decisions — the root
SCHEDULING.md moved there on 2026-08-23, having been **wrong for three days**, telling
readers the daily email was unbuilt while it shipped every morning. That is the failure
mode this whole documentation set is arranged against.

## The flow, and the lane that owns each step

```
   ┌── 1 INTAKE ────────┐   LinkedIn · Indeed · Telegram  ──▶ discovered_cache.json
   │   lane: discovery  │   new employer names            ──▶ research_companies.json
   └────────┬───────────┘
            ▼
   ┌── 2 REGISTRY ──────┐   resolve a name to a board, repair a dead one,
   │  lane: registry ✱  │   park what is genuinely dark   ──▶ companies.csv  (846 active)
   └────────┬───────────┘
            ▼
   ┌── 3 FETCH ─────────┐   ats-fetch · native ATS APIs   (16 platforms, 433 rows)
   │ lanes: ats-fetch   │   scraper   · the browser scraper (412 rows)
   │       + scraper    │                                 ──▶ scraped_cache.json
   └────────┬───────────┘
            ▼
   ┌── 4 ENRICH ────────┐   jd-text      · a description for every relevant role, any age
   │ lanes: jd-text     │   company-intel · sector / stage / size / founded
   │     + company-intel│                                 ──▶ 926 company profiles
   └────────┬───────────┘
            ▼
   ┌── 5 CLASSIFY ──────┐   Israel filter → relevance/seniority → LLM for the ambiguous
   │  lane: classifier  │                                  ──▶ accepted roles
   └────────┬───────────┘
            ▼
   ┌── 6 ROLE RECORD ───┐   is this the same role we saw yesterday? still open? a repost?
   │   lane: roles      │   what drops off the board, and what the archive keeps
   └────────┬───────────┘                                 ──▶ matched · sent (the store)
            ▼
   ┌── 7 RENDER ────────┐   the board, the archive, the email, every tag on a role card
   │   lane: render     │
   └────────┬───────────┘
            ▼
   ┌── 8 DELIVER ───────┐   commit state · publish the board · relay the email ·
   │   lane: infra ✱    │   the merge machinery · the workflows
   └────────────────────┘

   lane: docs — cuts across all eight      ✱ = only one session at a time
```

## Lanes, and what each may write

Pick ONE. The split exists so that two lanes never write the same file.

| lane | step | owns | primary files |
|---|---|---|---|
| **`discovery`** | 1 | where new roles and new employers come from | `discovery_daily.py`, `discovery_telegram.py`, `pipeline/aggregators.py`, `pipeline/recruiters.py` |
| **`registry`** *(one at a time)* | 2 | dark rows, the 23-tool resolution ladder | `companies.csv`, `listing_hunt.py`, `triage_dark.py`, `crack_walled.py`, `deep_validate.py`, `repair_*.py`, `resolve_*.py`, `audit_empty_rows.py`, `probe_candidates.py`, `scan_dead_domains.py`, `auto_expand.py`, `apply_resolved.py` |
| **`ats-fetch`** | 3 | how a board's API is read; adding a platform | `pipeline/fetchers.py`, `pipeline/platform_check.py`, `pipeline/health.py` |
| **`scraper`** | 3 | the 5-strategy browser extraction for the 412 no-API companies | `scrape_universal.py`, `refresh_scrape_cache.py`, `cache_new_rows.py` |
| **`jd-text`** | 4 | every relevant role gets its description, whatever its age | `pipeline/jdfill.py`, `enrich_scrape_jd.py`, `enrich_matched_jd.py` |
| **`company-intel`** | 4 | sector / stage / employees / founded / Israel centre | `pipeline/firmographics.py`, `pipeline/company_info.py`, `research_firmographics.py`, `bd_employees.py`, `fill_employees_llm.py`, `company_type_analysis.py` |
| **`classifier`** | 5 | which roles qualify, and the LLM tier that decides the ambiguous ones | `pipeline/seniority.py`, `pipeline/israel.py`, `llm_cache` invalidation |
| **`roles`** | 6 | the role as an ENTITY: is it the same one, is it still open, was it re-posted, when does it leave the board | `pipeline/store.py` (`matched`/`sent`, `merge_key`, `seen_id`, `merge_duplicates`, `filter_new`, `upsert_matched`), the role-selection block in `pipeline/run.py`, repost detection |
| **`render`** | 7 | how a role reads; every tag on a card | `pipeline/digest.py`, `pipeline/roleprofile.py`, `docs/TAGGING.md` |
| **`infra`** *(one at a time)* | 8 | delivery and the machinery under all of it: merges, workflows, the relay | `merge_*.py`, `check_invariants.py`, `.github/workflows/*`, `mark_sent.py`, `pipeline/run.py` (orchestration only) |
| **`docs`** | — | making all of the above legible to the next agent and to a visitor, and keeping it honest | `README.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `CLAUDE.md`, `docs/*` incl. `docs/check_docs.py` |

**Exactly one agent may hold `registry` at a time, and one `infra`.** `registry` writes the
file every other lane reads; `infra` writes the workflows that run them all. The other nine
are concurrent with each other and with one of each.

### The `roles` lane exists because the role record was nobody's

The role — not the company — is what the product is about, and until 2026-08-24 no lane
owned it: the record lived in `store.py` (given to `infra`), repost detection in `digest.py`
(given to `render`), the description in `jd-text`, and the tags nowhere at all. Three lanes,
no owner, for the central entity.

**What exists today.** `matched` is the durable list of every role ever accepted — 105 rows —
keyed by `company|title`, carrying location, url, posted_date, seniority, sources, the JD
text, `first_seen`, `last_seen`, and every contributing posting's `seen_id`. `sent` records
what has been emailed so nothing is sent twice. A role is "still open" if we saw it in the
latest scan of its employer; when we stop seeing it, it stops being on the board and appears
in the archive. Reposts are detected at render time by comparing `posted_date` against
`first_seen`.

**What does NOT exist.** The tags are not stored. Skills, role family, years, degree,
day-to-day tasks and AI-usage are recomputed from the description on every render, so there
is no way to ask "how many roles asked for SQL in July" — `company_type_analysis.py` answers
that by re-deriving them each time, over whatever descriptions happen to be present now. And
a role's tags are only ever as good as the description that was captured while it was open;
once it closes, that text is frozen. If persisted tags are wanted, this lane owns the column
and `render` owns what goes in it.

### Shared plumbing — read freely, change loudly

`pipeline/`: `notes.py` `verdicts.py` `identity_gate.py` `company_identity.py` `atomic.py` `http.py`
`companies.py` `stages.py` `sources.py`. Every lane imports these and no lane owns them. If
your change needs one modified, **say so in your report and name the lanes it could affect** —
`identity_gate` gates every activating write path (`company_identity` supplies its primitives)
`companies.csv`.

`pipeline/run.py` is the orchestrator: `infra` owns it, but any lane may need a hook in it.
Propose the hook, do not smuggle it.

### Not in any lane (deliberately)

**`docs/MODULES.md` classifies every root module**, and `docs/check_docs.py`
fails the test suite if a new one is unclassified. 25 are `legacy` — one-shot captures,
probes and superseded resolvers — and nothing scheduled imports any of them; the linter
proves that on every push rather than asking you to trust it. Do not spend time there.

The trap the registry exists for: 6 modules are `library` — **no workflow runs them and live
code imports them**, so they look dead in the Actions history. `ingest_research` and
`probe_ats` were on an earlier "safe to delete" list while `retry_unreachable.py` (02:30
daily) imports the first, which imports the second.

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
- **GitHub Actions concurrency group `repo-state`** — eight of the nine scheduled workflows
  share it (all but `daily-digest.yml`, which has its own). A long job makes the next one
  queue or be superseded, with no error anywhere.
- **DuckDuckGo is blocked from this machine** and works on the runners.

## Rules that will bite you

1. **A green workflow means nothing.** 26 of the 78 workflow steps are `continue-on-error`.
   Read the step output; confirm a capability did work by looking at what it produced.
2. **A mass-zero result is a broken run, not a measurement.** Strip its verdicts, diagnose,
   re-run.
3. **Never `git add -A`** — another lane's work is in this tree. Stage explicit paths.
4. **`python check_invariants.py` must pass before you commit** anything touching
   `companies.csv`. `python -m pytest -q` (123 cases, ~2s) must pass before any push. Every
   one of them is a bug that shipped; if one goes red, your change is wrong. `pytest` also
   runs `docs/check_docs.py`, so a doc that names a file you deleted fails the suite.
5. **Commit as `ajil-bot` and push with plain `git push`.** Read `CLAUDE.local.md` first —
   the public repos must not be linkable to the owner's personal account.
6. **Prefer letting the crons run.** If you must dispatch a workflow manually, delete the run
   record afterwards (`CLAUDE.local.md` §3). If you cancel a digest run, cancel it **before**
   the `Mark digested roles as sent` step, or that run's roles are burned as delivered and
   the next run will not email them.
7. Local runs are safe by default: `python -m pipeline.run --only "Wix,Fiverr" --no-llm
   --db /tmp/scratch.db` never emails, never publishes, and writes `out/docs-preview/`.

## The `docs` lane — standing brief

Fixed goal: **a visitor understands what this does and how the flow hangs together in ten
minutes; an agent knows where to start in twenty.** As of 2026-08-23 the structure for that
exists — `CLAUDE.md` (2 min) then this brief (20 min) then the lane's own files — and the
job is now to keep it true, not to build it.

**What this lane owns.** `README.md` (the visitor), `CLAUDE.md` (the agent's first two
minutes), `ARCHITECTURE.md` (the model), `HANDOFF.md`'s shape and cap, `docs/*` including
`docs/MODULES.md` and `docs/check_docs.py`. **Other lanes own their content in these files;
this lane owns the container and the enforcement.**

**The enforcement, so honesty is not a matter of goodwill.** `docs/check_docs.py` runs in
`tests/test_units.py::test_docs_are_consistent_with_the_code`, so `tests.yml` fails on every
push if:

| the check | what it catches |
|---|---|
| paths exist | a doc naming a file that was renamed or deleted |
| links resolve | a dead cross-reference between docs |
| section references | an `ARCHITECTURE.md` §N pointer left behind by a renumber |
| the module registry | a new root script nobody classified; a `legacy` module live code imports; a `scheduled` module no workflow runs |
| the cron table | `ARCHITECTURE.md` §4 and the workflow files disagreeing, in either direction |
| the continue-on-error ratio | the "a green run proves nothing" number drifting from the workflows |
| the HANDOFF shape | the current-state file growing back into an archive |

It cannot check whether a sentence is TRUE — only that what it points at still exists. Two
numbers were found wrong by hand on 2026-08-23 (75 zero-baseline companies was really 256;
33 `extract-gap` rows was really 26) and that kind of drift still needs a reader.

**Constraints: documentation only.** Do not "tidy" code in this lane — a rename here breaks
four other lanes silently. `docs/check_docs.py` is the one exception, and it only reads.
When you move text, **move it** — do not rewrite it from memory. Every claim must be checked
against the code or a live run.

**What is left in this lane** (from `HANDOFF.md`, "what the `docs` lane did NOT finish"):
the 30 unreferenced root modules are classified but not relocated; there is still no single
automation inventory covering the Windows scheduled task alongside the Actions crons; and
`docs/TAGGING.md`, `docs/BRIGHTDATA.md` and `docs/POC_COMPANY_PROFILES.md` have not been
re-verified line by line against the code.

## Definition of done

- The change is verified by its **output**, not its exit code — quote the numbers.
- `pytest`, `check_invariants.py` and `docs/check_docs.py` green; a new guard added for any
  bug you fixed (`tests/test_units.py` is a list of shipped bugs, one assertion each).
- **The docs your change touched are updated in the same commit** — see the table below.
- `HANDOFF.md` updated: what was wrong, what you changed, what you did NOT finish.
- Say explicitly what you left for someone else, and what you spent (BD credits, LLM calls).

### Where a change gets written down

Not optional, and not a separate task at the end: a change that is not written down is a
change the next session re-derives from the code, or worse, contradicts.

| you changed | write it in |
|---|---|
| behaviour of a step | the `ARCHITECTURE.md` section tagged with your lane |
| a rule that would cost data to re-learn | `ARCHITECTURE.md` §2 or §8 |
| a schedule or a workflow | the §4 cron table (the linter will make you) |
| a new root module, or a module's status | `docs/MODULES.md` (the linter will make you) |
| something you found broken and did NOT fix | `docs/BACKLOG.md`, with the lane that would own it |
| what you did this session | `HANDOFF.md`, three lines; the long version in `docs/sessions/` |
| a tag on a role card | `docs/TAGGING.md` |
| a decision you made, and the alternatives you rejected | `docs/decisions/<date>-<topic>.md` |

Anything a future reader would have to run the code to discover belongs in a doc. Anything
a future reader can discover by running one command belongs in a doc **as that command**.
