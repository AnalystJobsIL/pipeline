# Reading one run — every line the digest can print, and what its absence means

Written 2026-08-27 by the `docs` lane, because the daily mail now carries **nine audit lines
contributed by seven different lanes** and no document listed them. Reading
`digests/latest.md` currently means knowing seven sections of `ARCHITECTURE.md`. Each lane
owns its own line's *behaviour* and documents it in its own section; this page is the
dictionary — what emits each line, where, and the thing a dictionary is actually for: **what
it means when a line is missing**, which in this repo is almost always worse than what it
means when it is wrong.

The mail is built by `pipeline/digest.py`; the numbers are assembled in `pipeline/run.py`;
the cross-cron stamps come from `pipeline/stages.py` over `cloud_state/pipeline_stages.json`.

## Above the fold — `**Needs a look**`

Rendered by `digest.py` (the uncollapsed block before the run audit). Fixed order, and a line
is **omitted entirely when it has nothing to say** — so absence is normal here and only
`Stages:` is worth reading as a positive signal.

| line | fed by | absent means |
|---|---|---|
| `- **Sources not producing:**` | `run.py` ← `pipeline/sources.py` health | every intake source produced something |
| `- **Registry:**` | `cloud_state/registry_alarms.json`, written by `registry_health.py --census` | no pool moved enough to alarm |
| `- **Stages:**` | `stages.alarms()` + `run.py`'s own in-flight alarms | **no stage is stale and none raised** — the one line whose silence is meaningful |
| `- **Render:**` | `rolecard.cross_check` via `digest.render_all`, and `digest._subject_vs_body` | no same-posting, title-twin, shared-board or display collision, and the subject's number is the body's bullet count |

Every one of these is also printed as `::warning::<kind> <line>` by `run.py`, so it is a red
annotation on the run page as well as a bold line in the mail. `run.py` emits the kinds
`stage`, `discovery source`, `registry`, `boards` and `roles`.

## Inside `<details><summary>Run audit</summary>`

| line | emitted by | what it is |
|---|---|---|
| `Companies scanned: N (failed: M)` | `run.py` | the registry rows this run actually read |
| `Jobs fetched … Israel-matched …` | `run.py` | before and after `pipeline/israel.py` |
| `Accepted … after merge … new:` | `run.py` | classifier YES → dedupe → what the email will carry |
| `Decision paths:` | `seniority.Classifier` | `keyword` / `llm` / `llm_cache` / `merged-copy`; **must sum to Israel-matched**, and `run.py` alarms if it does not |
| `LLM calls this run: N` | `seniority.Classifier` | 0 with a large fallback count is the token-expiry symptom |
| `- **Boards** changed today:` / `standing:` | `pipeline/health.py::_by_reason` | new and cleared fetch errors, then the standing counts |
| `- **Company intel:**` | `pipeline/company_intel.py` | research and blurb spend for the run. `digest drain (20m):` / `bulk cron (60m):` names which drain stamped `firmo` (2026-09-11); `N held (…)` is a name whose own board belongs to another company and `N board-names-other` the same shape rescued by the name-only re-ask — both are `registry` work, and `ARCHITECTURE.md` §7 has the rules |
| `- **Roles:**` | `pipeline/roles.py` | open / closed / reopened / reposted / `ledger N = store N` |
| `- **Render:**` | `pipeline/digest.py` | board, archive and email card counts |
| `- Stage order:` | `stages.summary()` | every cron's last stamp, in pipeline order, with its detail keys |
| `- Failed companies:` | `run.py` | the per-company exceptions behind `failed: M` |

**`Stage order:` is the one line that reports on jobs this run did not perform.** It reads
`cloud_state/pipeline_stages.json`, so `collect: 2026-08-26 (1d ago)` means the 00:00 scrape
refresh did not run before this digest — which on 2026-08-27 is exactly what happened.

## The step log, which the mail does not carry

| prefix | file | note |
|---|---|---|
| `=== collect:` | `refresh_scrape_cache.py` | the scrape refresh's own stamp, printed by the 00:00 job, not the digest |
| `classify:` | `pipeline/seniority.py` → printed by `run.py` | includes the model tally, e.g. `sonnet x19` |
| `jd-fill:` | `pipeline/jdfill.py` → printed by `run.py` | `N/M descriptions fetched inline`, then the per-reason failure tally |
| `[company-intel]` | `run.py` | the same text as the mail's `Company intel:` line |
| `[linkedin] N cards across 27 queries · path free= blank= recovered= blocked= paid= · blocked N/M guest requests (x%) · free walk served N of 27 queries, M cut mid-walk, K straight to paid on the 18-min budget` | `discovery_daily.main()` | the breadth sweep. The **rate** is the number to read, not the count: `blocked` was a flat 34-36 on five nights whose request totals ran 250-365. `served/cut/straight-to-paid` is what `LINKEDIN_TIME_BUDGET_MIN` cost; `cut` > 0 with a low `served` means the budget is binding in the NATIONAL block, and then the answer is the pause, not the budget |
| `  [linkedin:<kw>] stopped with N jobs: the free-walk time budget ...` | `discovery_daily.linkedin_search` | that query ended on OUR clock, not on a block. It is deliberately not spelled `BLOCKED`: five queries printed `raise LINKEDIN_GUEST_PAGES` on 2026-08-25 for walks LinkedIn had blocked, and the false line was the evidence a cap bump cited |
| `[discovery-stamp] skipped: <e>` | `discovery_daily.main()` | the `discovery` stage was not written, so tomorrow's mail will say `discovery never ran` about a sweep that ran. Never fatal: a stamp must not be the thing that loses a sweep |
| `[bd-spend]` | `discovery_daily.py` | month-to-date Bright Data credits and the projection, read from the LIVE account — **the only place the ACCOUNT is totalled** |
| `[bd-spend] this step bought N credit(s) ... -- search N, unlock N` | `bd_rescue._report_spend`, at the exit of every process that spends | what THIS step bought and WHAT FOR. One line per process in `cloud_state/bd_spend.jsonl`, which outlives the deleted run record and is what `bd:` reads back. A process with no Bright Data credential writes NO line, whatever its counter says (a credit cannot be bought without a key, and a fabricated line is worse than none) |
| `[bd-gauge]` and the `bd:` stamp on `Stage order:` | `pipeline/bd_budget.stamp()`, `daily-digest.yml` before the pipeline step | month-to-date from the account, the **7-day rate per PURPOSE** (`search` / `unlock` / `discovery` / `jd-fill`) from the ledger, and the month's projection against the 5,000 free tier (`soft`). `mtd=unknown` means the account could not be read and the projection came from the repo's own ledger (`from_ledger=1`) — never a zero. Past the tier a `bd projected …` clause appears on `Stages:` with the dollars at $1.50/1,000; it alarms and **refuses nothing**, which is the operator's ruling of 2026-09-11 |
| `[wayback] submitted N, failed M, backlog K, boards B (of D due), verified V, throttled T, requests R` | `archive_evidence.py`, the first step of `jd-archive.yml` (12:30), not the digest | what reached the Internet Archive today and how far behind the ledger runs; the same numbers are the `wayback` stamp in `Stage order:`, and a `wayback …` clause on `Stages:` means the stamp is two days old, a day landed nothing, the archive's daily limit bit, or the step crashed (`wayback crashed:<Exc>`) |
| `::group::` per phase | `run.py::_phase` | and the phase name is what lands in `out/crash.json` if the run dies |

## The failure this page exists to name

**Every one of those lines is emitted by a run. A run that never starts emits none of them,
and nothing anywhere notices.** `stages.alarms("publish", 1)` can only fire from *inside* a
later digest; `persist_state.py outcome`'s dated failure notice is a step of the workflow that
did not run. On 2026-08-27 GitHub did not dispatch the 05:00 digest at all — no board, no
mail, no alarm, no `::warning::`. **Silence reads as success.** Filed as `docs/BACKLOG.md`
292 (`infra`); `docs/AUTOMATION.md` has the measured dispatch lag and the one command that
answers "did yesterday actually happen".

## Every seam that spends the Claude subscription

There is exactly **one** process seam to Claude in the repo — `pipeline/llm.py::_invoke` —
and it builds argv directly: `--model <m> --effort <e> --tools <t> --no-session-persistence
--output-format json --json-schema <s> --system-prompt <p>`, with no shell on any OS and a
**scratch cwd**, because from the repo root every call read `CLAUDE.md` and the gitignored
`CLAUDE.local.md` into the prompt: 24,845 cache-creation tokens against 4,633 from a scratch
directory.

Re-derive with `grep -rn "llm.call_json\|llm.call_meta\|llm.call(" --include=*.py --exclude-dir=.claude .`

| seam | model | effort | tools | override |
|---|---|---|---|---|
| `pipeline/seniority.py` — the classifier tier | sonnet | default `low` | none | `CLASSIFY_MODEL` |
| `pipeline/jdfill.py` — the jd-quality judge (`enrich_matched_jd.py`) | `claude-sonnet-5`, **hardcoded** | default `low` | none | none for the model; `JD_QUALITY=0`, `JD_QUALITY_LLM_CAP`, `JD_QUALITY_TIME_BUDGET_MIN` |
| `pipeline/firmographics.py` — research / blurb / employees | sonnet ×3 | `RESEARCH_EFFORT` | **web search, mandated** | `FIRMO_*_MODEL` |
| `resolve_llm.py` — the registry's LLM rung | sonnet | default `low` | none | `LLM_RESOLVE_MODEL` |
| `triage_dark.py` — the page judge | sonnet | default `low` | none | `TRIAGE_LLM_MODEL` |
| `scrape_universal.py` — strategy 5 | sonnet | `low` | none | `SCRAPE_LLM_MODEL` |

**A seam is only armed where its STEP is armed.** The jd-quality row above was missing from
this table until 2026-09-01, and its step in `daily-digest.yml` was missing
`CLAUDE_CODE_OAUTH_TOKEN` for three mornings — every call an instant 401 under
`continue-on-error`, reported as `no verdict: llm-auth13` while classify made 372 calls in
the same job. `test_every_llm_step_of_the_digest_carries_the_subscription_token` now pins the
three steps that reach the seam (`enrich_matched`, `firmo_drain`, `pipeline`). A refusal with
no credential present is `llm-no-token`; `llm-auth` means one was sent and rejected.

**Two measurements other lanes paid for, worth not repeating:**

- **Effort is not the knob.** `company-intel` measured research quality at low / medium /
  high and got 2/2 on all three; low is half the cost. What *did* move the answer was
  MANDATING web search rather than suggesting it: a prompt that suggested it searched on 1 of
  4 companies and every searchless answer was staler than the record it replaced; mandating
  gave 4 of 4, all current.
- **`usage.server_tool_use.web_search_requests` reads 0 even when search ran.** The real
  counter is `modelUsage[m].webSearchRequests`. Reading the wrong one is also the root cause
  of the mail's `haiku x237` attribution: the haiku search side-agent out-reads the answering
  model (23,449 input tokens against 6) and gets counted as the model that answered.

`tools` is deliberately ONE argument covering both `--tools` and `--allowedTools`, because a
caller that sets one and forgets the other fails **silently**: the model answers, in schema,
having never searched.

**This lane spends none of it.** A documentation pass makes no `claude -p` call; the only
Claude cost of a `docs` session is the session itself.
