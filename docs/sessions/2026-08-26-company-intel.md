# 2026-08-26 — `company-intel`: the last bare `claude -p`, the search mandate, and the cloud

> Every count is a snapshot — re-derive it with the command shown next to it before trusting
> it. `ARCHITECTURE.md` §7 is the durable version; this is what happened and why.

**Scope.** Written: `pipeline/firmographics.py`, `pipeline/company_info.py`,
`pipeline/company_intel.py`, `research_firmographics.py`, `fill_employees_llm.py`,
`cloud_state/firmographics.json`, `tests/test_company_intel.py`,
`tests/fixtures/company_intel/*`, `ARCHITECTURE.md` §7, `docs/BACKLOG.md`, this record, one
`HANDOFF.md` line. **Out of lane, disclosed and approved by the operator:** `pipeline/llm.py`
(shared plumbing — `tools=`, `call_meta`, `_served`, `_searches`; argv proven byte-identical
for `classifier`, `registry`, `scraper`, and none of their source touched) and a new
`.github/workflows/firmographics.yml` (`infra`'s directory; additive, modifies no existing
workflow). The §4 cron row and the continue-on-error ratio in `CLAUDE.md` /
`docs/AGENT_BRIEF.md` were forced by the docs linter, which `docs/AGENT_BRIEF.md` itself says
it will do to whoever adds a workflow.

**Spent.** 21 `claude -p` calls, all in the measurement below. Bright Data 0. SerpApi 0. No
workflow dispatched. Three Opus attacker sessions.

---

## 1. The finding that was not on anyone's list: git was eating the research

`state/firmographics.json` held **968** records; the committed
`cloud_state/firmographics.json` held **946**; **0** records went the other way. The chain's
own log claimed it had published them:

```
exported 968 records -> ...\state\firmographics.json + ...\cloud_state\firmographics.json
==== chain done Wed 08/26/2026 21:00:05 ====     firmo health OK
```

The export's mtime was **21:00:42**. `git reflog` showed
`HEAD@{2026-08-26 21:00:42}: pull --rebase -q: Fast-forward` — another lane's pull, **to the
second** — and `git show "stash@{0}:cloud_state/firmographics.json"` held the 968.
`stash@{1}` (an autostash) carries a firmographics diff too, so it was not the first time.

The chain writes the record of truth into the **shared checkout** as an unstaged tracked file
and never commits it, so the next lane's pull stashes it away. 22 companies' research,
destroyed silently, with the health check reporting `OK` throughout.

Recovered in `f71d4ac` through the lane's own `union_store`/`merge`/`save_shared` with five
refusal gates, all clean: 0 lost, 0 thinned, 0 aged backwards, 0 band/count contradictions,
0 records without a sector. Coverage of the 873 active registry rows: **844 (96.7 %) → 866
(99.2 %)**.

*This is why `firmographics.yml` exists. Anything that writes that file must commit it.*

## 2. There was no model. There were two.

`firmographics._claude` ran `["claude", "-p"]` with no `--model`, no `--effort`, no
`--json-schema`, no `--system-prompt`, no `--output-format json`, `shell=True` on Windows,
and **cwd inherited = the repo root**. So:

- `~/.claude/settings.json` on the laptop is `{"model": "opus[1m]"}` and the runner has no
  such file — the corpus was researched by *different models depending on which machine ran
  the call*, and nothing recorded which;
- no envelope meant no `modelUsage`, no cost, and no evidence the web search ever ran;
- the repo as cwd pulled `CLAUDE.md` and the gitignored `CLAUDE.local.md` into every call;
- reading only the exit code meant a CLI that **exits 0 with an `is_error` envelope** was
  scored as the *name* failing — a weekly strike against a real company.

## 3. The measurement (21 calls) — the prompt, not the model, was the lever

Four companies whose stored records carry a checkable recent fact. A prompt that **suggested**
search searched on **1 of 4**, and every searchless answer was staler than the record it would
have replaced:

| company | searches | what came back |
|---|---|---|
| Amdocs | 0 | headcount 26,688 → 30,000, note thinner |
| Aidoc | 0 | "Series E ~$150M raised 2024" — **missed** the 2026-04 Series E and $534M |
| 7AI | 2 | good; said Oct 2025 for a Dec 2025 round |
| Aleph Farms | 0 | **missed** the 2025 down-round entirely |

**Mandating** it ("ALWAYS search the web before you answer … your training data is months old
… never answer from memory alone") → **4 of 4 searched**, every fact current. Aidoc returned
*"$150M Series E led by Goldman Sachs Alternatives, April 2026"*; Aleph Farms returned
*"struggling financially, cutting jobs, seeking funding as of 2026"*, newer than the stored
record. `_coerce` accepted 4/4.

**Effort is not the knob.** N=2 per level, schema-constrained: low 2/2 correct at 1.5 searches
/ 20 s / $0.064; medium 2/2 at 1.5 / 23 s / $0.111; high 2/2 at 2.0 / 28 s / $0.128.

**Two counters everyone gets wrong.** `usage.server_tool_use.web_search_requests` reads 0 even
when WebSearch ran twice — it counts the *server-side* tool, and Claude Code's is client-side;
the real one is `modelUsage[m].webSearchRequests`, confirmed against `--output-format
stream-json` showing `TOOL CALLS: ['WebSearch', 'StructuredOutput']`. And Claude Code delegates
WebSearch to a **haiku side-agent** that reads the results — 23,449 input tokens against the
answering sonnet's **6** — which is the root cause of `docs/BACKLOG.md` 207's `haiku x237`.

## 4. Wave 1 — three Opus attackers, and the two they caught were the same bug rebuilt

Each was asked for a reproduction, not an opinion. Every finding below was reproduced.

| # | finding | fix | pinned by |
|---|---|---|---|
| A1 | **HIGH.** The `result` fallback (live on every WebSearch call) took the FIRST object with a key outside `{unknown, known}`, so a company named in the model's *reasoning* became the answer: Wix's profile stored under `Tel Aviv`, `_coerce` accepting it, the run reporting success. The 2026-08-25 Alma incident, rebuilt in new code | schema-shaped objects only, **last** wins | `test_the_result_fallback_never_profiles_a_company_from_the_context` |
| A2 | **HIGH.** `enrich_for_run` could raise: `_report()` calls `_knob()` (an env cast) *outside* the never-raises try, and `run.py::_load_secrets_env` sets env inside `run()` | `_knob` never raises; `rep` built inside the try; `audit_lines` wrapped | `test_enrich_for_run_survives_a_malformed_budget_env` |
| A3 | **HIGH.** The failed-name clause folded the reason but not the **company name**, and `companies.csv` has an ACTIVE Hebrew-named row while `run.py` prints that line outside the guard on a cp1252 console — reporting the failure would *be* the failure | `_ascii` on the name; the three new refusal prints too | `test_a_hebrew_company_name_cannot_kill_the_run_through_the_audit_line` |
| A4 | **MEDIUM.** All 31 bare head nouns were junk — **`Analyst`** is Analyst I.M.S., a TASE-listed Israeli investment house | two-token minimum | `test_a_bare_head_noun_is_a_company_not_a_job_title` |
| A5 | **MEDIUM.** The Latin-only tokenizer made Hebrew *invisible* to the closure test, so `Analyst בע"מ` read as entirely role vocabulary | uncovered letters veto | `test_the_title_rule_never_judges_a_name_on_its_latin_fragment` |
| A6 | **MEDIUM.** The gate was on one of three spenders: `research_firmographics` (the 10:00 cron, reading the table that held `Tel Aviv`) used `looks_like_junk`, and existing records still rendered facts chips | `not_a_company` in the bulk gate and at display | `test_the_bulk_researcher_uses_the_money_gate_not_the_shared_one`, `test_a_non_company_never_renders_facts_chips_either` |
| A7 | **MEDIUM.** Blurbs and research share one clock with no reserve; 30 blurbs eat 450 s of 480, and the clamped per-call timeout then made *our own* budget exhaustion read as `claude unavailable after 0 research calls` | reserved share, `RESEARCH_MIN_S`, clamp-kill counted as budget | `ci-blurbs-eat-the-clock`, `ci-clamped-timeout-reads-as-outage` |
| A8 | **MEDIUM.** `_served` preferred the asked model at ZERO output tokens, making `seniority.alarms()`'s drift check unable to fire; one combined exact/substring pass let a substring hit beat an exact match | exact before substring, `[1m]` stripped, must have spoken — degrading to inputTokens when the envelope has none, so the classifier's own pinned shape still passes | `test_the_served_model_must_have_actually_spoken` |
| A9 | `known` was only rejected when literally `False` (the string `"false"` is truthy); a refusal written into `sector` was stored | truth-value coercion + a refusal regex | `test_known_is_a_truth_value_and_a_refusal_in_the_sector_field_is_rejected` |
| A10 | `_served`/`_searches` raise on a drifted envelope on the **success** path, and five consumers only catch `ResearchUnavailable` | defensive reads + `ask()` translates everything | `test_the_seam_never_raises_anything_but_research_unavailable` |
| A11 | `BLURB_MAX_PER_RUN` still sliced from the import-time constant — the one loop that can spend 30 calls | `rep["blurb_cap"]` | `test_the_blurb_cap_env_actually_caps_the_calls` |
| A12 | Refusals were counted but never named, against §1a's appeal contract | every refusal prints its name | `test_every_refusal_prints_the_name_it_refused` |
| A13 | The backlog warning fired on every healthy morning | gated on candidates, not on the registry | — |
| A14 | Wording: `more` dropped from the gated clause; a soft outage labelled a spent budget; `waiting` called "over the cap" when under it | all three restored | `test_audit_lines_cover_every_report_shape` |

**Found sound, do not re-attack:** argv byte-identity for the four incumbent `llm.py` callers
(verified head-vs-tip for `seniority`, `resolve_llm`, `triage_dark`, `scrape_universal`);
`_tools` of `""`/`None`/`()`/`0`/`False`; `_PLACES` lazy init under the 3-worker pool (never
reached, and benign anyway); the reconcile identity `researched + failed + skipped + waiting =
candidates`; the `.cmd` shim's byte-identical delivery of all four system prompts and schemas;
`registry_backlog`'s cost (0.005 s); `not_a_company`'s cost (3 µs/name).

**Filed, not fixed:** `%VAR%` in an argv element is expanded when `claude` resolves to a
`.cmd` (no current prompt contains `%`); the two `is_place_name` implementations diverge on
typographic apostrophes; `PLACE_OK` reaches only this lane's half of the place gate; the
rehearsal driver still has no assertions (`docs/BACKLOG.md` 246).

## 5. What shipped

`f71d4ac` recovery · `2709dc9` the withdrawal (below) · `b55ccb6` the seam · `cc748ab` the
gate and the mail · `49fb8bf` the cloud cron, §7 and the catalogue · `d7892c8` wave 1.

**And one mistake of my own, worth recording.** `persist_state.py commit --own <path>` runs a
bare `git commit` with no pathspec, so it commits the **whole index** — on a runner that is
empty, in this shared checkout it is four other lanes' staged work. `f71d4ac` went out with
**17 files** instead of 1. Withdrawn in `2709dc9`: a forward commit built through a temporary
index, no rewrite and no force push, so the working tree was never touched and those lanes'
newest edits stayed theirs and uncommitted. All three affected sessions were told directly.
Filed as `docs/BACKLOG.md` 241 for `infra`; the fix is `git commit --only -- <owned>`, with
`discovery`'s caveat that `--only` errors on an empty commit.

## 5b. The cloud validation (evening) — and what it cost to make the rehearsal honest

**BACKLOG 246 closed, and the first attempt at it was still blind.** The driver had no
assertions and returned 0 whatever happened. I gave it 14 checks — and then deleted the
poisoned-blurb drop from a throwaway worktree and *all fourteen still passed*, because every
one of them looked at the **export** while the poison lives in `company_info`, which goes to
the **cards**. The check that closes it reads the rendered board and digest and asserts that
no blurb cached under a refused name appears there. Clean tree: exit 0. Fix deleted: exit 1,
naming `Tel Aviv -> Alma, a Sisram Medical company, develops...`. 110 checks across 7 cases.

One thing is a NOTE and not a check, deliberately: `### Tel Aviv` still has a digest section,
from 7 open ledger rows. That is `223`, lane `roles`; asserting it would make this driver
permanently red for an item this lane cannot close, so it prints the name, the item and the
owning lane instead.

**The employee fill** had been moved onto the seam that morning and never run once — untested
code that spends a shared subscription. Three guards now: the seam's shape (pinned model,
WebSearch on both axes, no shell on any platform — it was `shell=True` on *every* platform,
which on Linux ran a bare `claude`, and a cwd that is not the repo); the 1..5,000,000 clamp,
which refuses 0, -5, 9,000,000, null and `"many"` and is the only thing between a hallucinated
number and a card reading `~0 employees`; and an exit-0 error envelope raising
`ResearchUnavailable(auth)`, because `fill_employees_llm.main` catches only that. Plus one
pinning `bd_employees` OUT of the seam, so an LLM outage cannot stop the cheap Bright Data
counter.

**The cloud run** (`workflow_dispatch`, `limit=3`, 20:54 UTC, record deleted per
`CLAUDE.local.md` §3) is in §7 with its output. Two things it taught that the laptop could
not: the runner saw **8 to do** where the laptop's dry run saw 3 plus 5 gated — the two
`firmo_failed` stores are split-brained (`243`) — and the cron was spending the subscription
**invisibly**, reporting none of the calls, seconds or searches the digest hook reports. Now
it does, with the same `SEARCHLESS` warning; a job that spends silently is how the search
mandate quietly stops holding.

## 6. Morning check — 2026-08-27

1. The `Company intel:` line names **sonnet**, shows `N searches` with **no `SEARCHLESS`**,
   `registry backlog` ≤ 7, and `export N records` matching the file on disk.
2. No `::warning::company-intel` for model drift or a stalled backlog.
3. The **10:00 UTC** `firmographics.yml` run: its step summary reports the export size and the
   remaining backlog, and it commits `cloud_state/firmographics.json` alone.
4. `state/firmographics.json` vs `cloud_state/firmographics.json` — if they diverge again, the
   chain is still losing work to the shared checkout and 97's retirement is overdue.
5. The **10:00 UTC** run is now the one that matters most: its `seam:` line must show
   `N searches` with no `SEARCHLESS`, and its commit must touch exactly one path.

## 7. NOT finished

`docs/BACKLOG.md` **241–246**, and the pre-existing `97` (the Windows task is redundant now
but is `infra`'s to retire), `98` (see 242 for why the obvious merge is wrong), `138`, `142`,
`144`.

### Correction, same evening — two things above were wrong when re-checked

Written down because a confident document that is no longer true is what this repo punishes
hardest, and both were mine.

1. **`120` was not "the kwarg exists, the hook does not". The kwarg did not exist either.**
   `audit_lines` rendered `llm_off_upstream` and *nothing set it* — a mail sentence that could
   never fire, which is worse than an unstarted item because it reads as done. Now actually
   wired in `5f11603`: `_SHARED_OUTAGE` matches only `auth`/`missing` (a transient 529 in
   another process says nothing about this one; `drift` is about the classifier's own flags),
   plus one argument at `run.py`'s existing call site — `infra`'s file, the hook the plan
   disclosed. Guarded both ways: the kwarg's behaviour, and that `run.py` passes it.
2. **`141` was closed in the same commit but was missing from this list**, along with
   `--export`'s help string, which claimed it writes `state/firmographics.json` while writing
   `cloud_state/`.

**And the gauge was measuring the wrong universe.** `registry_backlog` counted active
*registry rows*, but a company reaches a card by having a **role** — 27 companies with role
records are not active rows, and `Peak Innovation` renders without facts where the gauge could
not see it. The universe is now active rows ∪ every company ever matched ∪ today's board. The
`Discovery` row is excluded by **platform** (`ats_platform == "discovery"`), not by name —
it is the LinkedIn+Indeed layer, not an employer, so it was a permanent backlog of 1 and a
research call every week forever; `Discovery Inc` is a real company and a name-based rule
would have refused it.

Verified with `research_firmographics.py --dry-run`, zero spend: *"899 active companies, 968
researched, 3 to do"*, and it refuses `Tel Aviv` through the new gate. **One thing that dry
run exposed and I did not fix:** it reports **5** strike-gated names where
`cloud_state/seen.db`'s `firmo_failed` holds **2** — the laptop's and the runner's failure
memories are split-brained, so "gated" means something different on each machine. That belongs
with `243`.

**Backlog numbering collided.** Items **240–246 are each used two or three times** on
`origin/master`: three lanes filed into the same range within the hour (`scraper` 240–245,
this lane 241–246, `ats-fetch` 238–240). Nothing is lost — every item's text is intact — but
the numbers are no longer unique, so cite this lane's by **lane and date** until the `docs`
lane renumbers. `147` already tracks the earlier 70/71/132/133/215 collisions; this is the
same failure at four-lane concurrency, and it is an argument for allocating ranges per lane.
