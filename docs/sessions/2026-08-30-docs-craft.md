# 2026-08-30 — `docs` (craft): three clauses about outcome and safety, none about shape

Base `a476f24`. Worktree `.claude/worktrees/docs-0830c`. No Bright Data credits, no LLM
calls, no SerpApi, no dispatch, nothing written to `companies.csv`; `gh` read-only. Dry mode
(`JD_BD=0 BD_RUN_CAP=0`), no `secrets.env`.

The two earlier `docs` sessions today made the definition of done outcome-first (clause 1),
gave clause 2 the workflow / cadence / alarm table, and gave clause 3 teeth about what a
`cancelled` run means. All three are kept word for word. What none of them asks is whether the
code should exist in the shape it landed in — and the tree answers that question by itself.

## The evidence, each claim re-checked in this worktree before it was written

| the claim in clause 4 | what the tree says at `a476f24` |
|---|---|
| three `_load_secrets` copies survive the loader that replaces them | `pipeline/secretsenv.py` exists; `bd_rescue.py:46`, `bd_employees.py:41`, `pipeline/jdfill.py:89` still define their own; `468` carries the three-line replacement for each |
| the file with one copy took five commits the day the diff was filed | `git log --since=2026-08-30 -- pipeline/jdfill.py` → 5 (`40aa439` … `6428b75`), all `jd-text`; `load_secrets` still at line 89 |
| two enrichers over one library | `enrich_scrape_jd.py` 491 lines, `enrich_matched_jd.py` 665, both importing `pipeline/jdfill.py` |
| hand-maintained vocabularies | `pipeline/roleprofile.py`: `SKILLS`, `SOFT_SKILLS`, `TASK_GROUPS`, `AI_USAGE`, `_FAMILIES`, `_DEG_LEVELS`, `_DEG_FIELDS` — seven; `SOFT_DESC`, `SKILL_DESC`, `TASK_DESC`, `AI_DESC` are four parallel dicts |
| a state machine as prose in a 220-character cell | `pipeline/notes.py`: `CAP = 220`, and its own docstring: every tool made room the same way |
| a section titled for the failure mode | `ARCHITECTURE.md:5845` `## 8. Failure classes — what this codebase does instead of erroring` |

The spawn prompt said "three hand-maintained tag vocabularies"; the module has seven lists and
four description dicts. The clause says what the count is, not what I was told.

## What changed

**Clause 4 — "The change is smaller than the problem — evidence, not a verdict."** The draft I
was handed asked five good questions as prose. Three things changed in it:

* **Rank, stated first.** Clause 1 outranks it: a queue drained on an ugly fix beats a
  beautiful change that moved nothing. The clause decides what the report contains, never
  whether the number counts.
* **Each question names the artefact that answers it** — a two-column table. `git diff --stat`
  and the `+`/`−` totals for "what did you delete"; `grep -n "def <name>"` for "what did you
  extend"; the alternative and the number that killed it for "what did you reject"; the `grep`
  the next session would type, and what it hits first, for "would they find this"; a count of
  new flags / files / keys for "what did you make harder". "Well-crafted" is a judgement and
  the repo's discipline is measurement; a report that answers with adjectives has not answered.
* **The last question is named as the one no linter can ask** — which is why it is in the
  report and not in `check_docs.py`.

**The cross-lane debt rule — "Debt in another lane's file".** Two rules, one of them held by
the linter, and the three rejected designs beside them with the measurement that rejected each:

1. **A unification may cross lanes**: replace N copies with one function and delete the copies
   in the same commit. This is the rule that would have killed the four copies on 08-30 —
   `infra` had the loader, the diff and a green suite, and the old rule told it to file.
2. **A filed diff is applied by the next lane to open that file**, or declined in the HANDOFF
   line with the number. `check_debt_on_touched_files` in `docs/check_docs.py` holds it.

Rejected: a standing cleanup lane (a session writing every other lane's files is the hazard
the split exists to prevent, and this lane's own "do not tidy code" rule was written after one
rename broke four lanes); "file it with the diff" alone (`468` is that, and it survived five
commits to its target); a periodic audit (`438` was an audit finding on 08-29; the copies are
still here).

**`CLAUDE.md` contract item 4** gained one sentence pointing at clause 4. Nothing else there.

## The check, and what it measured before it shipped

`check_debt_on_touched_files`: `base = _baseline_ref()` (honours `AJIL_PUSH_BASE` on a
runner, else the merge-base; silent with none), `git diff --name-only base HEAD`, every OPEN
item whose body has a fenced block and cites a tracked code file **by line** outside the fence,
and the `+` lines of `HANDOFF.md` on the branch. A touched file with such an item and no added
line citing the number is an ERROR.

**The first version cried wolf, and the replay caught it before it shipped.** Replayed over the
66 first-parent commits of 2026-08-30 with each commit's own `docs/BACKLOG.md` and its parent
as the base:

| heuristic | commits refused | on what |
|---|---|---|
| fenced block + any path mention | **26 of 66** | 25 of them on `311` and `421`, which name `tests/test_units.py` — the file every lane appends to; and `427`, which mentions `docs/check_docs.py` in prose while describing a gap elsewhere |
| fenced block + a **line-anchored** citation, files every lane appends to excluded | **5 of 66** | `458@infra` → `persist_state.py` (three infra commits), `459@registry` → `listing_hunt.py`, `468@registry` → `tests/conftest.py` |

The second is the one that shipped. `_EVERY_LANE_APPENDS` is `tests/test_units.py`,
`tests/mutations.json`, `docs/BACKLOG.md`, `HANDOFF.md` — the files the brief already says
belong to no lane. `jd-text`'s five `jdfill.py` commits are **not** among the five: on their
branch `468` did not exist yet (it landed at 10:03Z in `e5fee4d`, the branch was cut before),
so the check catches that copy on the **next** touch, not retroactively. That is the honest
shape of the rule.

`python docs/check_docs.py --debt` prints what is owed today — every diff-bearing item, its
files, and the commits to each since the item's section date — and the count is the `docs`
lane's number: **5 files** (`468` → `pipeline/jdfill.py` 5 commits; `458` → `persist_state.py`
3; `421`, `459`, `468` one each). Target 0.

**Held to its own rule:** this branch touches `docs/check_docs.py`, and `427@registry` names
that file. Under the first heuristic the check would have refused this very push; under the
shipped one it does not, because `427` names the file in prose and carries no diff for it —
which is the case the line anchor exists to separate.

## `next` reserves by reading master, and the gate refuses what it missed

`python docs/backlog.py next` printed `max+1` of the **local** file. Two branches cut from the
same base compute the same number and both land; four numbers came to name two items each on
2026-08-30 alone — **445, 446, 461, 462** (`python docs/backlog.py show <n>`). The batches the
spawn prompt named (482–500) are unique on master: they were renumbered at rebase, which is the
cost the old tool imposed on whichever lane landed second.

Three designs:

* **A reservation file on master.** A true reservation needs a shared writer, which here is a
  push — and it races exactly the way the number does. Rejected: it moves the collision from
  the item to the reservation.
* **Lane-prefixed numbering** (`infra-12`). Kills the collision by construction, and re-keys
  470 citations across 74 files, including two workflows. Rejected on the same measurement
  `backlog.py`'s header already records for renumbering.
* **Read master, refuse at the gate.** Taken. `next` = `max+1` over this tree **and**
  `origin/master:docs/BACKLOG.md` as last fetched (never fetching, for the reason
  `check_docs.py` never does — ten sessions contend on the ref lock); and `check` — both the
  tool's and `check_docs.check_backlog` — ERRORs on a number with two claimants where one is
  absent at the merge-base by `(number, title)`. The 38 existing collisions are grandfathered;
  a new one is the pushing lane's to renumber, and nothing cites it yet. Run `next` after
  `git pull --rebase`, right before the push; the index text says so now.

Measured: `next` here printed **503** with master read, matching the index; the gate on this
branch reports no new collision.

## The lanes table, re-derived at 18:00 UTC from this worktree

| lane | 05:xx | 18:00 | command |
|---|---|---|---|
| `registry` | 259 owed of 276 | **557 owed of 572** (397 attempted · 175 never tried); 210 → 572 in one day; drain 112/night vs intake 161/day median, 212 mean | `python queue_state.py` |
| `discovery` | 42 of 276 re-added | **165 of 572** carry a conclusive retirement; intake capped **40/day** (`SECRETHUNTER_DAY_CAP`), steady state ~31; 27 % noise | the cell's one-liner |
| `company-intel` | 84 exact | **21 by `identity_key`**, 37 by exact name — the spawn prompt said 18 and the lane's note said 68 at 05:xx; the 10:17 cron ran in between, and the command decides | the new identity-key one-liner |
| `roles` | no dataset; seniority empty on 154 | **3 wrong rows in the public CSV**, still in master and on Pages; retraction BUILT, public at the 08-31 digest; seniority 0 empty of 172 | `curl … \| grep -c 'Comcast\|Jobgether'` |
| `render` | (no number) | **7 of 17 mails** with a wrong subject count; 6 vs 13 on 08-30; fixed today, unattended proof 08-31 | H1 vs the bullet grep |
| `classifier` | 191, cap 60 | **210 re-judgeable** + **30 no cap reaches** (no description; `464`) | `grep … SUPERSEDED digests/latest.md` |
| `ats-fetch` | 17 | **18** | `registry_health.py --stale-boards` |
| `scraper` | 33 | **34** | the cell's one-liner |
| `jd-text` | 223 of 1,396 / 8 of 154 | **204 of 1,404 / 9 of 172** | the sqlite one-liner |
| `infra` | 5 of 71 | **5 of 75**, 1 isolated drop; CI **33325163882 success, 13 of 13** | `tests/schedule_census.py --days 14` |
| `docs` | CI red, 60 runs | CI **green** (delivered by `infra`; the `ci` alarm is in the 08-30 mail); new number **5 files** of filed debt | `python docs/check_docs.py --debt` |

`HANDOFF.md`'s state table said `210 owed` for the intake queue; corrected to 557 of 572 with
the time, since it is the same number this table re-derives.

## By clause 4, on this change

* **Deleted or unified:** nothing in code — this lane may not. `git diff --stat`: docs and
  two tools, plus three guards. `−` lines are the eleven table cells and the two sentences the
  tools' docstrings replaced.
* **Extended, not duplicated:** `_baseline_ref`, `_git`, `_backlog` and `Item.unfenced` /
  `.title` in the two tools; `parse(text)` for the merge-base read. `_merge_base()` in
  `backlog.py` is a near-copy of `_baseline_ref()` — the tool imports nothing from
  `check_docs.py` by design, and both are stdlib-only; named here rather than hidden.
* **Rejected:** the two designs above, and the first debt heuristic, each with its number.
* **Would the next session find it:** `grep -rn "_load_secrets" --include=*.py` still lands on
  three definitions. Until the copies go, no.
* **Made harder:** one new check that can go red on a rebase, one new `--debt` flag, one new
  ERROR path in `backlog.py check`, and the every-lane file list a future reader must know
  about. Four.

## What I could not verify, and what is left

* Whether a lane will read the new ERROR and apply the diff rather than write "not applied"
  in HANDOFF. The rule allows the second; the count `--debt` prints is what tells us.
* The CI verdict on `dc3a787`: run **33328309775**, `success` on all 13 jobs (`guard`,
  `guard-kill`, five `mutation-gate` shards, six rehearsals). The run before it, on
  `a476f24`, was `success` too, so nothing red was inherited. The three guards added here
  ran under `guard-kill` there and passed it: each fails with its target reverted to base.
* **The follow-up `a13045a` was pushed red, by me.** Recording the verdict put `HANDOFF.md`
  at 3,206 words against the 3,200 cap; I read the lint's last line, not its error line, and
  pushed. Run 33329556885 is expected to fail `guard` on `test_docs_are_consistent_with_the_code`.
  Fixed in the next commit by trimming the line; the same cap three lanes hit today, and the
  same misread clause 3 warns about — the step you care about is not the verdict.
