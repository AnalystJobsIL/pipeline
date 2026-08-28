# 2026-08-28 — `docs`: the product advertised a filter it had stopped running

*Lane: `docs`, **plus `pipeline/digest.py`'s scope wording and `pipeline/__init__.py`'s
docstring** — both declared loudly below, in `HANDOFF.md` and in `369@docs`. Closes
`369@docs`; files `374@docs`, `375@classifier`, `376@registry`, `377@infra` and a note on
`142@infra`.*

## What was wrong

On 2026-08-28 the operator removed the ~3+ years experience bar. The `classifier` lane
shipped it correctly in `66d9e3c`, wrote `docs/decisions/2026-08-28-analyst-scope.md`, and
filed `369@docs` naming four files it did not own. **The code was right and the product's
description of itself was wrong, for the whole of that day, in fourteen places** — including
the sentence that becomes the operator's email subject.

That is the failure this repo names as the one it punishes hardest. The root `SCHEDULING.md`
told readers the daily email was unbuilt for three days while it shipped every morning; this
is the same shape in a new place. **And it is the same shape for the same reason:**
`docs/check_docs.py` proves that what a doc *points at* still exists, and since 2026-08-27
that the *numbers* a doc states match the code. A **claim** had no test at all. The linter
was green through the entire drift, and would have stayed green.

### The most-read sentence in the project was the wrong one

The mail's subject is not `build_digest`'s `subject` — that string reaches
`out/digest-<date>.json` and nothing reads it. The relay builds the GitHub issue title from
the **first line of `digests/latest.md`**, i.e. `digest.py`'s H1. The live inbox:

```
[AnalystJobsIL/inbox] 🎯 4 new senior analytics roles — 2026-08-28 (Issue #11)   08:29Z
```

So `pipeline/digest.py:107` is the single most-read sentence the project has, and it was
advertising a bar that had been removed hours earlier.

### "senior" was already false before the bar was removed

Measured against the board as published that morning, with `seniority._seniority()`'s own
regex:

| page | roles | no seniority marker in the title |
|---|---|---|
| `docs/index.html` | 72 | **36 (50 %)** |
| `docs/archive.html` | 61 | **45 (74 %)** |

`data-years` on the board: **two roles already asked for 2 years**, eight stated none. So the
H1 was not made false by the operator's decision — it was made *undeniable* by it. Dropping
"senior" is not a claim that the board is junior-friendly; it is the removal of a level claim
the subject line has no room to qualify. The nuance moved one line down, into the subtitle,
which has room. It also removes an internal contradiction for free: `digest.py:109`'s sibling
branch already said "analytics role" with no adjective.

### The archive had been lying about all 61 of its rows

`digest.py:737` is **one** `<div class="sub">` rendered on both pages. Under
`<h1>61 archived roles (no longer on the employer's careers page)</h1>` it read
"…**open roles**, refreshed daily…". Every clause of the replacement is true on both pages,
so this is fixed as a by-product rather than left one line from the sentence being repaired.

## What changed

**Fourteen sites, where `369@docs` listed four.** Its own grep
(`3+ yrs\|≈3+\|senior analytics roles`) finds nine of them: it misses `~3+` (the
`ARCHITECTURE.md` §0 spelling, tilde not `≈`), `README.md:41`'s diagram line,
`README.md:57`'s bare "experienced", the `anything junior/intern/entry-level` clause, and
`pipeline/__init__.py`.

| file | what it said → what it says |
|---|---|
| `README.md` ×4 | the headline, the flow diagram, "What counts as a role", and the row calling `docs/decisions/` merely "superseded" |
| `CLAUDE.md` | the opening sentence. The **phrase** was replaced, not the lines — `:5` carries two registered census sites (`reads 800+ companies'`, `registry of 1,300+ rows`) and reflowing them is a linter error |
| `ARCHITECTURE.md` §0 | the scope paragraph — which **also still named the retired `v2\|company\|title\|jd` cache key**; it is `v3.<sha1 of the rules text>` since `66d9e3c` |
| `ARCHITECTURE.md:2010` | quoted the old H1 as an example |
| `ARCHITECTURE.md` §1a | see "one fact in another lane's section" below |
| `pipeline/digest.py` `:107 :123 :259 :737` | the four live rendered strings |
| `pipeline/__init__.py:1` | the package docstring |
| `tests/test_units.py:769` | pinned the old H1; `:11795`'s docstring quoted `CLAUDE.md`'s old first sentence |

### What ships tomorrow

Rendered from the real `render_all`, offline, with synthetic jobs:

```
EMAIL H1  (= the subject in the operator's inbox)
  # 🎯 1 new analytics role — 2026-08-29
EMAIL SUBTITLE
  Israeli high-tech scan — data / BI / analytics roles from the **last 48h**, freshest
  first. Any experience level; internships and student placements are out of scope. Each
  role title links to apply.
BOARD  <h1>   2 open analytics roles at Israeli companies
BOARD  <sub>  Data / BI / analytics · any experience level · refreshed daily · click a row
              to expand, a header to sort
ARCHIVE <h1>  1 archived roles (no longer on the employer's careers page)
ARCHIVE <sub> (the same line — and now true on this page too)
```

`heading` is a **control flag**, not just a string: `archived = "archived" in heading`
(`digest.py:272`), with three more branches at `:436`, `:500`, `:765`. Neither replacement
carries that substring, and the render check confirms the archive kept its own `<h1>`, its
`index.html` back-link and its suppressed tag-legend, while the board kept its archive link.

### Two clauses I did NOT write, because they would have been new false claims

An adversarial pass killed both, and I verified both against the shipped classifier:

1. **"no agency-posted roles."** `_AGENCY_EMPLOYER` only *demotes* to the LLM tier — the
   decision record says so itself ("It **never rejects**"). The board **today** carries
   `peak innovation | credit risk analytics team lead` and `epam systems, inc. | managing
   principal / senior director, data analytics consulting`. Publishing "no agency-posted
   roles" on a page that lists them would have been the same defect, one day later. The docs
   say **out of scope**, "judged per posting, not by a name list"; the rendered strings say
   nothing about it, because it is a boundary and not a promise.
2. **"no internships."** Measured — `Data Analyst Intern` rejects, but:

   ```
   Data Analyst Interns           -> ACCEPT  keyword_nollm
   Senior Data Analyst Interns    -> ACCEPT  keyword        <- LLM never asked
   Head of Analytics Internships  -> ACCEPT  keyword
   ```

   `_NOT_A_JOB`'s English alternation has no plurals and the `\b` kills them, so a senior
   marker plus a plural walks past the reject into the keyword accept. Filed as
   `375@classifier`. Everything now says internships are **out of scope** — a statement about
   what the board is for, which is true — never "no internships", which is a guarantee the
   code does not keep.

A third draft sentence, "a title with no seniority marker must show analytics in its
description", was also wrong as written: it holds only for `signal`-tier titles and only on
the no-LLM fallback path (`_sig_accept_nollm`'s own docstring), and a bare "Data Analyst"
with an empty description is accepted as `strong` with no description evidence at all. The
shipped wording is bounded accordingly.

### One fact in another lane's section

`ARCHITECTURE.md` §1a (`discovery`'s) said `seniority.classify` "rejects **every one**" of
the junior/student Telegram postings, and quoted a reason string,
`junior-intern-entry-level`, that **no longer exists in the code**. Both false since
`66d9e3c`; the second would send the next reader looking for something that is not there.
Corrected as a *fact fix*, on the operator's instruction — the section's design is untouched
and the correction says so in place.

**`ARCHITECTURE.md` §7b (`classifier`'s) needed nothing.** Checked line by line: `:3506`
restricts the deterministic reject to `_NOT_A_JOB`; `:3507` gates `_EARLY_CAREER` on
`EXPERIENCE_BAR` and states it is off since 2026-08-28; `:3508` documents `_AGENCY_EMPLOYER`
as a demotion; `:3512-3528` carries both boundary changes and the 20-of-252 → 0-of-252
measurement. That lane had already done its half.

## The durable half: a claim can go red now

`docs/check_docs.py` gains **`check_scope_claims()`**, wired into `CHECKS`. The fact registry
above it checks NUMBERS; this is the repo's first check of a **claim**.

- **Two-way, and decided by the code.** It AST-reads the *shipped default* of
  `pipeline/seniority.py`'s `EXPERIENCE_BAR`. Bar off ⇒ no surface may state the retired
  promise **and** `README.md` / `CLAUDE.md` / `ARCHITECTURE.md` must each say what replaced
  it. Bar on ⇒ the inverse.
- **AST, not import** — `_fetcher_keys`' rule ("importing from a linter is a side effect
  waiting to happen"). And **not the live global**, which is the sharper reason: `EXPERIENCE_BAR`
  is `os.environ.get(...) == "1"`, so a check reading `seniority.EXPERIENCE_BAR` would take
  the bar-ON branch under `CLASSIFY_EXPERIENCE_BAR=1`, assert the promise is present, find it
  present, and go green over the whole drift. A one-word green, from the environment of
  whoever ran the suite.
- **An explicit five-file surface list — no tree walk, no exemption list.** The first draft
  walked the tree. `.claude/` is untracked but **not gitignored**, so the walk saw 2,879
  `.md`/`.py` files, 2,600 of them stale copies inside 21 sibling worktrees; and from *inside*
  a worktree every absolute path contains `.claude`, which would have made the guard 100 %
  vacuous in exactly the checkout where the fix gets written. The closed list is the shape of
  the nearest prior art, `test_no_document_still_claims_capped_roles_lead_the_next_digest`,
  and deleting the exemption list deletes the laundering surface with it.
- Patterns are case-insensitive (the board's subtitle said "**E**xperienced (") and
  whitespace-tolerant (`ARCHITECTURE.md` wrapped "0 new senior analytics\n   roles" straight
  through the phrase). A line-by-line, case-sensitive matcher misses both.

**Proof it would have caught this.** Pointed at `origin/master` (`66d9e3c`), the real
function raises **19 errors** naming every site — `README.md:41` and `digest.py:737`
included, the two an earlier pattern draft missed. It would have been red inside the commit
that created the drift.

**Its own guards**, four, each driving the real `check_scope_claims()` over a `tmp_path`
`ROOT` so the function under test is the function that runs: the promise goes red (asserting
**zero** errors on the clean fixture, not merely "no bar error" — a pattern that stopped
matching would otherwise make the guard vacuous); **deleting the sentence does not go green**;
the check reads the shipped default and not the environment; and every live surface exists
and is non-trivial, so the list cannot rot into nothing.

**Six mutants, all killed** — dropping the positive control, reading the live global,
narrowing the surface list, making the patterns case-sensitive, matching line-by-line, and
turning a missing surface into silence. The first run had **two survivors** (case-sensitivity
and the missing-surface branch), because every dirty fixture also carried `~3+ yrs`, which
the tilde pattern matches in either case, and nothing drove the missing-surface error. Both
fixtures were added; that is the difference between a guard and a decoration.

### What it deliberately does not cover, and why

- **`senior analytics OPENINGS`** — `build_digest:845` and `:878`. That renderer is dead
  (`142@infra` deletes it; it writes `out/digest-<date>.html/.txt` and a `subject` key nothing
  reads). The operator declined to polish strings in code scheduled for deletion, because it
  makes the dead code look maintained and 142 harder to argue. **Noted on 142 so the strings
  die with it**, and noted in the check.
- **`persist_state.py:826` and `.github/workflows/daily-digest.yml:180`** quote the old H1 in
  a comment. They promise a reader nothing, and they are `infra`'s, one session at a time.
  `377@infra`.
- **`docs/sessions/`, `docs/decisions/`, `docs/BACKLOG.md`** quote the retired phrase on
  purpose. `tests/test_units.py:12056` already forbids registering a frozen archive, for the
  same reason: it could only be made green by editing history.
- **Boundary 4 (agencies)** has no guard: it is an LLM condition plus a demoting list, so
  there is no shipped boolean to bind to. `374@docs` says what to do if a third boundary ever
  arrives — one named flag per boundary in `seniority.py`, and iterate them — rather than a
  fifth regex.

One consequence of the check as written, and it is the right one: it went red on **my own
first draft of the fix**, because I had explained the change by reprinting "the ~3+ years bar
was removed" in three live docs. The retired phrase belongs in the decision record, which is
exempt and where it is already written in full; a live surface says "any experience level"
and links. No negation heuristic, no window, nothing to launder through.

## Gates

From a clean worktree off `origin/master`. **"After" is measured after the rebase**, not
before it: `registry` pushed `0424610` and `063d14b` while this was being written, and a
pre-rebase green says nothing about what actually lands.

| gate | before (`66d9e3c`) | after (rebased onto `063d14b`) |
|---|---|---|
| `python -m pytest` | 1171 passed, 11 skipped, **0 failed** | **1185 passed, 11 skipped, 0 failed** (+4 mine, +10 `registry`'s) |
| `python check_invariants.py` | OK — 1466 rows, 969 active, 0 orphans | OK — 1496 rows, 998 active, 0 orphans (`registry`'s rows, not mine) |
| `python docs/check_docs.py` | **0 errors**, 6 warnings, 50 documents | **0 errors**, 6 warnings, 51 documents |
| `python docs/check_docs.py --facts` | 19 matched claims, all `ok` | 19 matched claims, all `ok` |

The rebase conflicted once, in `tests/test_units.py`, where `registry` and this session had
each appended a block at EOF. Resolved as the **union** — neither side touched the other's
lines, and `test_the_collected_test_count_never_falls` exists precisely because a
checkout-era copy once deleted seven already-pushed guards.

(19 matches across the 18 registered sites — `coe_ratio`'s `ARCHITECTURE.md` pattern hits
twice, at `:139` and `:2578`. Four of the sentences rewritten here sit beside census sites —
`reads 800+ companies'` and `registry of 1,300+ rows` in both `README.md` and `CLAUDE.md` —
and a registered site that stops matching is an error, not a warning, so the two `--facts`
outputs were diffed rather than eyeballed.)

The six warnings are pre-existing and unrelated (three session files a day out, an unanswered
`roles` morning check, and the two standing backlog warnings). `check_invariants` measured
`66d9e3c`'s `companies.csv`, not today's live registry.

`test_the_collected_test_count_never_falls`'s floor was left at 1153 rather than raised:
six lanes are live tonight and raising it guarantees a conflict for whoever pushes second.

**Spent:** no Bright Data credits, no LLM calls, no SerpApi. The render check runs offline
against synthetic jobs; the classifier probes are `use_llm=False`.

## What I did NOT finish

- `374@docs` — the check guards one claim. Boundary 4 has no shipped boolean to bind to.
- `375@classifier` — **`Data Analyst Interns` is accepted, and an internship is not a job.**
  This is the one that bounds the wording: fix `_NOT_A_JOB` and "out of scope" can become
  "excluded". The Hebrew side is weaker still — no `התמחות`, no `סטאז'`.
- `376@registry` — "agencies are excluded everywhere via `recruiters.py`" in §2 and the §5b
  runbook. A `registry` session was live in those sections; untouched by design.
- `377@infra` — two comments quoting the old H1.
- `pipeline/seniority.py:594`'s reason string `"senior analyst title (>=3 yrs implied)"`
  fires on the **live** keyword-accept path and is written into the public
  `cloud_state/roles.jsonl`; `:598`'s comment still says "the 3+yr bar". `seniority.py` was
  off limits this session. Folded into `375@classifier`.
- `pipeline/fetchers.py:200`/`:213` — stale "3+ year check" comments (`ats-fetch`).
- The committed `docs/index.html`, `docs/archive.html` and `digests/latest.md` still carry
  the old strings and **were deliberately not hand-edited**: they are generated, and the
  05:00 run rewrites all three (`run.py:722-727`, `persist_state.py:1143`). They will
  disagree with the source until then. That is expected, not a bug.
