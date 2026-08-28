# 2026-08-28 — `classifier`: a trailing "s" defeated the only exclusion left

*Lane: `classifier` (`pipeline/seniority.py`). Closes `375@classifier`; sizes and explicitly
declines to bundle `373@classifier`; files `378@classifier`. Also tightens the board/mail
wording from "out of scope" to "excluded", which is what `375` was actually for — declared,
because `pipeline/digest.py`, `README.md` and `CLAUDE.md` are `render`'s and `docs`'.*

## What was wrong

When the operator removed the experience bar on 2026-08-28, **the internship exclusion became
the whole remaining boundary** — the one thing `_NOT_A_JOB` still has to catch. It was
enumerated in the singular only. Every stem closed with `\b`:

```
Data Analyst Intern          -> reject  keyword        "internship/student placement, not a job"
Data Analyst Interns         -> ACCEPT  keyword_nollm
Senior Data Analyst Interns  -> ACCEPT  keyword        "senior analyst title (>=3 yrs implied)"
Student Data Analyst         -> reject
Data Analyst Internship      -> reject
```

Eleven English variants were admitted this way: **interns, internships, students, trainees,
traineeship, apprentices, apprenticeships, co-op / coop / co-ops, working students.**

The two worst are the bottom of that list's shape rather than its size: `Senior Data Analyst
Interns` and `Head of Analytics Internships` were accepted on the **`keyword`** path — a
*deterministic accept of an internship, with the LLM never asked* — because once the gate
misses, the `strong`+`senior` shortcut two lines below catches them.

### The order was already right — and that matters

The brief asked me to fix an ordering problem. **There isn't one**, and saying so is more
useful than pretending to fix it. `_NOT_A_JOB` already sits *above* the `strong`+`senior`
accept in `_classify`, which is exactly why the **singular** `Data Analyst Intern` rejected
with the right reason while carrying `rel=strong`. The plural was accepted because the gate
**missed**, not because the shortcut ran first.

What was missing was a guard on the ordering, so I added one:
`test_the_not_a_job_gate_precedes_the_strong_senior_accept` asserts that a title carrying both
markers wins on `_NOT_A_JOB`, and that the accept it beat is genuinely reachable for the same
title without the marker. Moving the shortcut up is a one-line edit that would ship
internships to the board with `>=3 yrs implied` as the reason; it is now a red test.

## What changed

`_NOT_A_JOB` is **stems + an optional nominal suffix**, not a hand-listed alternation:

```python
_NOT_A_JOB_STEMS = ("intern", "student", "trainee", "apprentice", "co-?op", "campus")
r"\b(?:%s)(?:s|ship|ships)?\b" ... + r"|סטודנט|מתמח|סטאז|(?<!תחום )התמחות|מתלמד|חני[כך] + a (?![הת]) lookahead"
```

**The suffix group is also the safety.** A bare `\bintern` prefix — the obvious "just make it
match more" fix — would eat `Head of International Sales`, `Internal Audit Manager` and
`Internal Occupational Physician`, all three real titles in `scraped_cache.json` today
(measured over 1,656 distinct titles). `intern`+`ship` reaches `internship`; `intern`+`s`
never reaches `internal`, because `\b` must still hold after the suffix. That mutant is
pinned.

### The Hebrew arm had the same bug in the other alphabet

The old arm spelled out `סטודנט|סטודנטית|מתמחה|מתמח`, which *reads* complete — two of those
are redundant, since the Hebrew side is a substring match and a prefix already covers its own
plural. That redundancy is probably why nobody noticed the English side was singular-only.

Four terms added, each the counterpart of an English stem, so the two sides now enumerate the
same class:

| term | why |
|---|---|
| `סטאז` | stage/internship |
| `(?<!תחום )התמחות` | the ordinary noun for an internship — **guarded**, because bare `התמחות` also means "specialisation" and `תחום התמחות` is "field of specialisation". This gate rejects without appeal, so an unguarded add would silently lose a real role |
| `מתלמד` | = `apprentice` |
| `חני[כך]` with a `(?![הת])` lookahead | = `trainee` |

**`חני[כך]` is a character class because Hebrew final forms are different codepoints.** `חניך`
ends in final kaf U+05DA; its plural `חניכים` carries a medial kaf U+05DB. My first draft
wrote `חניך(?!ה)` and silently admitted the plural — **the same singular-only mistake, one
alphabet over, made while fixing it.** My own test caught it, and then caught a second flaw:
`(?!ה)` blocks `חניכה` (inauguration) but not its construct `חניכת`. The lookahead is
`(?![הת])`, which keeps `חניכות` — the labour-law word for *apprenticeship* — and drops the
inauguration family. All six forms are pinned with their glosses.

**`צוער` (cadet) and `קדם-אקדמי` are deliberately in neither arm.** There is no `cadet` stem
on the English side either, and a cadet track is a career, not a placement. Adding one
language's term without the other is how this drifted in the first place, so a test asserts
the two arms stay symmetric.

## Measured before shipping

| measurement | result |
|---|---|
| golden fixture, title-only rows | **0 of 252 moved** |
| distinct live titles (`scraped_cache.json` + role ledger) | **0 of 1,482 newly caught, 0 released** |
| mutants killed | **8 of 8** |
| variants pinned | 31, parametrised |

**The change moves nothing on today's board.** The hole was real and nothing had walked
through it yet, so this is a boundary repair that lost no role and moved no card. I want that
stated plainly rather than implied away: no internship was removed from the board today,
because none was on it.

The parametrised guard asserts the **`keyword` path and the reason string**, not just
`reject`. Several variants already returned `reject` before the fix — from the no-LLM
fallback, because a bare title has no description — which is an accident of the corpus, not
the boundary working. With a description they would have gone to the tier.

## `373@classifier` — sized, and deliberately NOT bundled

The brief said: *"If it is one fix, make it one fix."* It is not one fix, and the sizing is
the argument.

**36 of the 83 classified records in `cloud_state/roles.jsonl` — 43 % — took the `keyword`
shortcut and were never adjudicated.** Reading them: the overwhelming majority are `Senior
Data Analyst` / `Senior Product Analyst` / `Senior BI Analyst`, which is exactly what the
shortcut exists for. The suspicious ones are `EPAM | Managing Principal / Senior Director,
Data Analytics Consulting` (the known counter-example, which the seam rejects as a
sales/leadership role) and arguably `Alma Lasers | Total Rewards & People Analytics Lead`.

So the exposure is **broad** (43 % of all verdicts) while the suspected error rate is **low**
— which is the exact shape where changing the shortcut on one counter-example is the wrong
move. 373's own text, which I wrote when I filed it, says: *"One instance is not a rate.
Before changing the shortcut, MEASURE it."* Bundling an unmeasured precision change to a
cost-bounding shortcut into an urgent boundary repair, hours before a digest, would also make
the whole thing harder to revert if the morning goes wrong.

What 375 *did* do for 373: it removed one class of abuse of that shortcut — an internship
reaching it at all. What is left is pure precision on real analyst titles, and it still needs
the rate. The measurement costs **~36 LLM calls, not the ~70 I originally estimated**, and
373 now carries that number and the command.

## 375's real done: the wording

`docs` refused to write "no internships" into the board and the mail *because of this bug*,
and wrote "out of scope" instead — a statement about intent rather than a guarantee. With the
class enumerated in both alphabets and pinned, the stronger word is now the true one:

- `pipeline/digest.py` — the mail's subtitle: "internships and student placements are
  **excluded**"
- `CLAUDE.md` — "internships and student placements are **excluded**"
- `README.md` — "**Excluded:** internships, student placements, apprenticeships and trainee
  programmes — deterministically, in English and Hebrew, above every accept."

**Not strengthened further, on purpose.** A posting whose *title* never says "internship"
still reaches the LLM tier, which is judgement rather than exclusion — and behind the
`strong`+`senior` shortcut, not even that. The promise is exactly as strong as the gate.

`check_docs.check_scope_claims` (built this morning) stays green across the rewording: its
retired-phrase patterns do not match, and the three prose docs still state "any experience
level".

## Gates

Clean worktree off `origin/master` (`2daacaf`):

| gate | before | after |
|---|---|---|
| `python -m pytest` | 1185 passed, 11 skipped, **0 failed** | 1227 passed, 11 skipped, **0 failed** (+42 guards) |
| `python check_invariants.py` | OK — 1496 rows, 998 active, 0 orphans | unchanged (`companies.csv` not touched) |
| `python docs/check_docs.py` | **0 errors**, 6 warnings, 51 documents | **0 errors**, 6 warnings, 51 documents |

The six warnings are pre-existing and unrelated. **Spent: no LLM calls, no Bright Data
credits, no SerpApi** — every probe here is `use_llm=False` or a regex over a committed file.

## What I did NOT finish

- **`373@classifier`** — sized at 36/83 and left open with the command and the real call
  count. It needs a measured false-accept rate before the shortcut changes.
- **`378@classifier`** — `campus` is the one stem naming a *place* rather than the person's
  status, and `Campus Recruiting Data Analyst` is a real job it would reject. Pre-existing,
  0 occurrences in 1,482 live titles, so it is unmeasurable today and was left alone rather
  than tuned blind.
- The `strong`+`senior` reason string still reads `senior analyst title (>=3 yrs implied)`
  and is written into the public `cloud_state/roles.jsonl`. It is `373`'s to fix, since
  whether that path should exist at all is the open question.
- `pipeline/fetchers.py:200`/`:213`'s stale "3+ year check" comments — `ats-fetch`'s.
