# Agent brief — read this before touching anything

For a session spawned to work on ONE part of the pipeline while other sessions work on
others. It exists because the docs are deep but not ordered, and because several parts of
this repo are unsafe to edit concurrently.

## Read in this order (~20 minutes)

0. **`CLAUDE.md`** — two minutes, and it loads automatically. What ships, the flow, the five
   rules, the quotas, the pre-push contract. If you read nothing else, read this.
1. **`ARCHITECTURE.md` §0 and "the whole system on one screen"** — what the user actually
   receives, and how to run anything locally without side effects. Non-negotiable.
2. **`ARCHITECTURE.md` §2** — §2's **four registry rules** (distinct from `CLAUDE.md`'s
   five, which are the whole-repo set): the
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

6. **`docs/RUN_LOG.md`** if you are about to read a digest mail or a step log — every line
   the run can print, what emits it, and what its absence means, plus the one table of
   every seam that spends the Claude subscription and which model it uses.
7. **`docs/AUTOMATION.md`** if you are about to trust a schedule. `ARCHITECTURE.md` §4 says
   when a cron is *supposed* to fire; that page has the measured lag, and on 2026-08-27
   three crons did not fire at all.

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
   │  lane: registry ✱  │   park what is genuinely dark   ──▶ companies.csv  (800+ active)
   └────────┬───────────┘
            ▼
   ┌── 3 FETCH ─────────┐   ats-fetch · native ATS APIs   (17 platforms)
   │ lanes: ats-fetch   │   scraper   · the browser scraper (the rest)
   │       + scraper    │                                 ──▶ scraped_cache.json
   └────────┬───────────┘
            ▼
   ┌── 4 ENRICH ────────┐   jd-text      · a description for every relevant role, any age
   │ lanes: jd-text     │   company-intel · sector / stage / size / founded
   │     + company-intel│                                 ──▶ cloud_state/firmographics.json
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

   lane: docs — cuts across all eight steps  ✱ = only one session at a time
```

## Lanes, and what each may write

Pick ONE. The split exists so that two lanes never write the same file.

| lane | step | owns | primary files |
|---|---|---|---|
| **`discovery`** | 1 | where new roles and new employers come from | `discovery_daily.py`, `discovery_telegram.py`, `pipeline/aggregators.py`, `pipeline/recruiters.py` |
| **`registry`** *(one at a time)* | 2 | dark rows, and the 5-rung resolution ladder (§3) over 9 re-check pools | **`registry_health.py`** (read-only: census, who re-checks what, which ATS to build, `--explain "<name>"`), `companies.csv`, `listing_hunt.py`, `triage_dark.py`, `crack_walled.py`, `deep_validate.py`, `repair_*.py`, `resolve_*.py`, `audit_empty_rows.py`, `probe_candidates.py`, `scan_dead_domains.py`, `auto_expand.py`, `apply_resolved.py` |
| **`ats-fetch`** | 3 | how a board's API is read; adding a platform | `pipeline/fetchers.py`, `pipeline/platform_check.py`, `pipeline/health.py` |
| **`scraper`** | 3 | the 5-strategy browser extraction for every company with no API | `scrape_universal.py`, `refresh_scrape_cache.py`, `cache_new_rows.py` |
| **`jd-text`** | 4 | every relevant role gets its description, whatever its age | `pipeline/jdfill.py`, `enrich_scrape_jd.py`, `enrich_matched_jd.py` |
| **`company-intel`** | 4 | sector / stage / employees / founded / Israel centre | `pipeline/firmographics.py`, `pipeline/company_info.py`, `research_firmographics.py`, `bd_employees.py`, `fill_employees_llm.py`, `company_type_analysis.py` |
| **`classifier`** | 5 | which roles qualify, and the LLM tier that decides the ambiguous ones | `pipeline/seniority.py`, `pipeline/israel.py`, the `llm_cache` key scheme; `pipeline/llm.py` is shared |
| **`roles`** | 6 | the role as an ENTITY: is it the same one, is it still open, was it re-posted, when does it leave the board | **`pipeline/roles.py`** (the ledger: `cloud_state/roles.jsonl` + `roles_text.jsonl`), `pipeline/store.py` (`matched`/`sent`, `merge_key`, `seen_id`, `merge_duplicates`, `filter_new`, `upsert_matched`), the role-selection block in `pipeline/run.py`, repost detection |
| **`render`** | 6 | how a role reads; every tag on a card | `pipeline/jdtext.py` (text→structure), `pipeline/rolecard.py` (the card), `pipeline/digest.py` (rendering), `pipeline/roleprofile.py` (the lexicon), `docs/TAGGING.md` — model: `ARCHITECTURE.md` §7d |
| **`infra`** *(one at a time)* | 8 | delivery and the machinery under all of it: merges, workflows, the relay | `persist_state.py`, `merge_*.py`, `check_invariants.py`, `.github/workflows/*`, `mark_sent.py`, `pipeline/run.py` (orchestration only), `tests/rehearse_infra.py` |
| **`docs`** | — | making all of the above legible to the next agent and to a visitor, and keeping it honest | `README.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `CLAUDE.md`, `docs/*` incl. `docs/check_docs.py` |

**Exactly one agent may hold `registry` at a time, and one `infra`.** `registry` writes the
file every other lane reads; `infra` writes the workflows that run them all. The other nine
are concurrent with each other and with one of each.

### The `roles` lane exists because the role record was nobody's

The role — not the company — is what the product is about, and until 2026-08-24 no lane
owned it: the record lived in `store.py` (given to `infra`), repost detection in `digest.py`
(given to `render`), the description in `jd-text`, and the tags nowhere at all. Three lanes,
no owner, for the central entity.

**What exists today.** `matched` is the durable list of every role ever accepted — 135 rows
on 2026-08-27 (`select count(*) from matched`) —
keyed by `company|title`, carrying location, url, posted_date, seniority, sources, the JD
text, `first_seen`, `last_seen`, and every contributing posting's `seen_id`. `sent` records
what has been emailed so nothing is sent twice. A role is "still open" if we saw it in the
latest scan of its employer; when we stop seeing it, it stops being on the board and appears
in the archive. **Reposts are recorded in the ledger** (`pipeline/roles.py`, a `posted_date`
at least `REPOST_DAYS` = 3 past that episode's `first_seen`; 13 records carry one today) and
re-derived by the same rule at render time (`rolecard.REPOST_DAYS`) when no ledger record
exists.

**The tags ARE stored** — this paragraph said they were not until 2026-08-27, and the
column had been built two days earlier. `cloud_state/roles.jsonl` carries a `tags` snapshot
per role (132 of 135 records today: skills, family, years, degree, track, AI usage),
versioned by `v` and invalidated when `tags_sha1` stops matching `desc_sha1`. What is still
true is that the BOARD recomputes from the description on every render, so a lexicon change
lands the same morning — and that a role's tags are only ever as good as the description
captured while it was open. `company_type_analysis.py` answers
that by re-deriving them each time, over whatever descriptions happen to be present now. And
a role's tags are only ever as good as the description that was captured while it was open;
once it closes, that text is frozen. If persisted tags are wanted, this lane owns the column
and `render` owns what goes in it.

### Shared plumbing — read freely, change loudly

`pipeline/`: `notes.py` `verdicts.py` `identity_gate.py` `identity_facts.py`
`company_identity.py` `atomic.py` `http.py` `companies.py` `stages.py` `sources.py`
`llm.py`. Eleven modules; `docs/MODULES.md` marks the same eleven `**shared**`, and
`llm.py` is on this list because it is the ONE process seam to Claude in the whole repo —
the `classifier` row below names it but does not own it. Every lane imports these and no
lane owns them. If your change needs one modified, **say so in your report and name the
lanes it could affect** — `identity_gate` gates every write path that activates a row in
`companies.csv` (`company_identity` supplies its primitives and is inert on every ATS host
by design).

`pipeline/run.py` is the orchestrator: `infra` owns it, but any lane may need a hook in it.
Propose the hook, do not smuggle it.

### Not in any lane (deliberately)

**`docs/MODULES.md` classifies every root module**, and `docs/check_docs.py`
fails the test suite if a new one is unclassified. 25 are `legacy` — one-shot captures,
probes and superseded resolvers — and nothing scheduled imports any of them; the linter
proves that on every push rather than asking you to trust it. Do not spend time there.

The trap the registry exists for: 9 modules are `library` — **no workflow runs them and live
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
- **DuckDuckGo is rate-limited from this machine, not blocked** — it answers, then returns
  zero for the same query minutes later (measured: `ddg("Wix")` gave 4 URLs, then 0). Treat
  it as a rung that sometimes answers, never the only one. It is reliable on the runners.

## Rules that will bite you

1. **A green workflow means nothing.** **44+ of the workflow steps** are `continue-on-error`.
   Read the step output; confirm a capability did work by looking at what it produced.
2. **A mass-zero result is a broken run, not a measurement.** Strip its verdicts, diagnose,
   re-run.
3. **Never `git add -A`** — another lane's work is in this tree. Stage explicit paths.
4. **`python check_invariants.py` must pass before you commit** anything touching
   `companies.csv`. `python -m pytest` must pass before any push — **not `-q`**, which
   `pytest.ini` already sets, so a second one hides the `N failed, M passed` line. Every
   one of them is a bug that shipped; if one goes red, your change is wrong. `pytest` also
   runs `docs/check_docs.py`, so a doc that names a file you deleted fails the suite.
   Asking "why was company X activated or refused?" is one command, offline:
   `python registry_health.py --explain "<name>"` (add `--fetch` for the one page GET).
5. **Say which run mode you are in, and never copy `secrets.env` into a worktree.**
   The ceiling is `python -m pipeline.bd_budget`, never a number written in prose: it is
   **unlimited through 2026-08-31 and 5,000/month from 2026-09-01**, no rollover, and both
   sides of that boundary are pinned by a guard so the rule changes itself on the day
   (`pipeline/bd_budget.py`; this rule quoted "5,000, ~6,798 already used, permanent and
   unrecoverable" for two days after the operator replaced it). There are two modes:

   **Dry** — no `secrets.env`, `JD_BD=0 BD_RUN_CAP=0`. Every paid rung is **disarmed**, and
   that is the trap: a disarmed rung does not error, it returns a refusal. A zero or a
   "dead" from a dry worktree **is not evidence** — one such pass wrote 57 of 57 rows dead.
   Never write a `dead` / `parked` / `zero-confirm` verdict from one.

   **Armed** — reference the operator's file where it is, never copy it into a worktree,
   and set `BD_RUN_CAP=<n>` explicitly: **unset means no cap**, `0` means buy nothing. A
   copy is an uncapped spender in a tree nobody is watching, and from 2026-09-01 ten
   concurrent sessions at `PAGE_UNLOCK_BUDGET` = **100** each is the month's pool in five
   days. `python -m pytest` can no longer spend (`tests/conftest.py` bans the transport);
   `python -m pipeline.run` still can — it arms the key inside `run()` and `JD_BD` defaults
   to **1 = spending**. Declare what you spent when you hand back.
6. **Commit as `ajil-bot` and push with plain `git push`.** Read `CLAUDE.local.md` first —
   the public repos must not be linkable to the owner's personal account.
7. **Prefer letting the crons run.** If you must dispatch a workflow manually, delete the run
   record afterwards (`CLAUDE.local.md` §3). If you cancel a digest run, cancel it **before**
   the `Mark digested roles as sent` step, or that run's roles are burned as delivered and
   the next run will not email them.
8. Local runs never email and never publish: `python -m pipeline.run --only "Wix,Fiverr"
   --no-llm --db /tmp/scratch.db` writes `out/docs-preview/` and nothing else. **"Safe" is
   about delivery, not about money** — this line used to say "safe by default", and it is not:
   `--no-llm` does not turn off `JD_BD`, which defaults to **1 = spending**. Add `JD_BD=0
   BD_RUN_CAP=0` (rule 5).

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
| **derived facts** | a number a doc states drifting from the code — 9 registered facts, 18 sites. EXACT facts (`len(FETCHERS)`, module counts, the c-o-e ratio) are held to equality, because only a push moves them. CENSUS facts (active rows, registry rows) move when a cron ran and nobody pushed, so since 2026-08-28 they are held ONE-SIDED: the site writes a FLOOR, `N+`, and only a COLLAPSE through it is an error — a bare number and a two-sided band are both refused, because widening a band is the move that deletes the alarm. A count no decision turns on carries the command instead, the way the profile count now does: `python -c "import json;print(len(json.load(open('cloud_state/firmographics.json',encoding='utf-8'))))"`. `--facts` prints all of them |
| **product scope** | a doc, or a rendered string, promising a filter the classifier does not enforce. The facts registry above checks NUMBERS; this is the first check of a CLAIM, and it exists because there was none: on 2026-08-28 the experience bar was removed and six live surfaces went on advertising it all day, including the line that becomes the mail's subject, with this linter green throughout. Two-way, and decided by the code — `check_scope_claims` AST-reads the SHIPPED default of `pipeline/seniority.py`'s `EXPERIENCE_BAR` (never imports it, and never reads the live global, which `CLASSIFY_EXPERIENCE_BAR=1` would flip). Bar off ⇒ no surface may state the retired promise **and** `README.md`/`CLAUDE.md`/`ARCHITECTURE.md` must each say what replaced it, so deleting the sentence is not a way to go green |
| **the backlog index** | a stale per-lane index, or an item naming a lane that does not exist |
| **morning checks** | a prediction stated in prose where nobody can answer it, or a verdict a reader cannot check |
| paths exist | a doc naming a file that was renamed or deleted |
| links resolve | a dead cross-reference between docs |
| section references | an `ARCHITECTURE.md` §N pointer left behind by a renumber |
| the module registry | a new root script nobody classified; a `legacy` module live code imports; a `scheduled` module no workflow runs |
| the cron table | `ARCHITECTURE.md` §4 and the workflow files disagreeing, in either direction |
| the continue-on-error ratio | the "a green run proves nothing" number drifting from the workflows |
| the HANDOFF shape | the current-state file growing back into an archive |

It still cannot check whether a *sentence* is true — only that what it points at exists and
that every number it registers agrees with the code. The rest needs a reader, and the
measure of how much rest there is: three Opus attackers reading these documents against
the tree on 2026-08-27 found **46 measured contradictions**, every one of them green under
the linter that morning. Among them: a "rolling 2-week board" that selects
`get_matched_since("0000-01-01")`, a per-company board cap that has never existed, and a
local command printed under "without side effects" that overwrites the published board.

**Constraints: documentation only.** Do not "tidy" code in this lane — a rename here breaks
four other lanes silently. `docs/check_docs.py` is the one exception, and it only reads.
When you move text, **move it** — do not rewrite it from memory. Every claim must be checked
against the code or a live run.

**The lane's tools.** `docs/check_docs.py` and `docs/backlog.py` are both owned here, both
read-only unless given an explicit write flag, both stdlib-only, and neither imports
anything from `pipeline/`. That is the carve-out from "documentation only": this lane may
own a tool that *reads* the code to check a document, and nothing else.

**What is left in this lane, 2026-08-27.** The 32 unreferenced root modules are still
classified but not relocated — moving a file is a code change. `docs/TAGGING.md`,
`docs/BRIGHTDATA.md` and `docs/ATS_PLATFORMS.md` were re-verified line by line on
2026-08-27 and corrected; `docs/POC_COMPANY_PROFILES.md` is a dated POC report that belongs
in `docs/decisions/` (`docs/BACKLOG.md` 296). The automation inventory this paragraph used
to ask for is `docs/AUTOMATION.md`. Open, with numbers, in `python docs/backlog.py lane
docs`.

## Definition of done

- The change is verified by its **output**, not its exit code — quote the numbers.
- **`pytest` green means green in CI, on the commit you pushed** — not green where you
  ran it. They are different suites: yours has your tree's state files, your
  environment, and your `GITHUB_ACTIONS` unset, and on 2026-08-30 three guards that
  passed on every laptop failed on every push for exactly that reason. After you push:
  `gh run list -R AnalystJobsIL/pipeline --workflow tests.yml --limit 1 --json
  headSha,conclusion,databaseId` — the sha must be yours and the conclusion `success`,
  and **the run id goes in your `HANDOFF.md` line**. A red run is yours to fix or to
  revert, whoever made it red: `tests.yml` was red on **100 consecutive runs** to
  2026-08-30, with every lane reporting a passing suite, because everybody read their
  own terminal. If it was already red when you arrived, say so in your line with the
  run id, so the next session knows what it inherited.
- **A change to a scheduled step is not done until a run you did not start has produced a
  number.** The step's own lane is the last to notice it is broken: `enrich_scrape_jd.py`
  ran **3 seconds of a 30-minute budget** and filled 0 on the 2026-08-29 digest, green,
  and every session on that lane reported done. So:
  **(a)** the proof is an UNATTENDED run — `gh run view <id> --json event,headSha` must say
  `event: schedule`, and `git merge-base --is-ancestor <your sha> <headSha>` must hold, or
  you are quoting a run that never executed your code. **Dispatching it yourself is not
  that**, and neither is a local run.
  **(b)** `HANDOFF.md` quotes the **exact counter or log line** (`matched_filled=`,
  `relay notified:`) with its number and `run <id>` — not a nearby number that shares a
  word: `JDs fetched inline: 132` is the inline enricher, not the nightly backfill.
  **(c)** until that run has happened, the entry says **"unattended run not yet read"** and
  a `## Morning checks` row carries the date it comes due — the first slot after your push
  plus the 180-minute grace. The linter will hold you to that date.
  **(d)** a step that can produce **zero** makes zero visible where a human reads daily
  (`Stages:` / `Stage order:`); a step with no daily surface cites the state commit that
  proves it ran (`git log -1 --format='%h %s' -- <the file it writes>`).
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
