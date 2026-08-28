# 2026-08-28 — a census fact is claimed one-sided, or not at all

*Decision by the `docs` lane. What changed: `docs/check_docs.py`'s census class no longer
accepts a two-sided claim. What was rejected, and why, is the point of this record.*

## The problem, stated as a measurement

`docs/check_docs.py` splits the numbers a doc states into two classes by **who moves the
number**. `exact` facts (`len(FETCHERS)`, the module counts, the continue-on-error ratio)
move only when somebody pushes code, so equality is the right contract. `census` facts —
active rows, registry rows, profiles — move because eight cron jobs ran.

Until today a census site carried a **bracket** (`~900`, meaning 850–949, the precision read
off the trailing zeros) or a **range** (`850-950`). On the morning of 2026-08-28 the linter
said:

```
active_rows            census  969         RED  README.md:15 = ~900  today 969, outside 850-949
                                           RED  CLAUDE.md:5 = ~900   today 969, outside 850-949
                                           RED  docs/AGENT_BRIEF.md:57 = ~900 today 969, outside 850-949
```

Nothing was broken. The registry lane drained the intake queue and active rows went **873 → 969
in 14 hours 26 minutes** (`599d7b8` 2026-08-27T16:42Z → `9bbaf69` 2026-08-28T07:08Z), **42 of
them in 73 minutes** (`0c69eaa` 895 at 20:26Z → `d76fb10` 937 at 21:39Z). The documentation
check went red *because the project was working*.

That is not a cosmetic failure. `test_docs_are_consistent_with_the_code` shells out to the
linter, so a red linter is a red `pytest`, and `Registry invariants`, `Fourteen rehearsed
nights` and `Five mixed-policy rehearsals` are steps **below** `Unit guards` in the same
`tests.yml` job. GitHub skips every later step in a failed job. Verified on runs
`33115068319`, `33115297808`, `33116880121`, `33117303189`, `33118081587`, `33119191959`,
`33119862389` — seven consecutive pushes on 2026-08-27, `Registry invariants=skipped` and
`Fourteen rehearsed nights=skipped` in every one. (Their cause that day was a jd-text unit
test, fixed by `124d27e`; the mechanism does not care which test failed.) **A stale number in
a README can switch off the registry gate.**

And the other two census facts were failing in the two different ways a band can fail.
`registry_rows` was 1,465 against `1,300–1,500` — **35 rows from going red**, i.e. days.
`firmographics_profiles` was 995 against `~1,000`, which under the trailing-zero precision
model claimed **500–1,499**, because `~1,000` claims THOUSANDS, not hundreds: 495 above its
floor and 504 below its ceiling. That one was never going to fire; it could not fire without
the store halving or growing by half. Which is the other failure mode exactly — a band
narrow enough to mean something is a scheduled false alarm, a band wide enough never to fire
checks nothing, and the same registry held one of each on the same morning.

## The evidence the design is built on

One snapshot per commit that ever touched `companies.csv` — 111 of them, over all of
`origin/master`, timestamps normalised to UTC (`git log --reverse` order is NOT
chronological here: committer stamps mix `+03:00` and `Z`, and reading it as chronological
is how the first draft of this record got four of its six numbers wrong):

| quantity | range observed | largest single-commit rise | largest fall | largest drawdown |
|---|---|---|---|---|
| active rows | 394 → 969 | **+140** (`47aef45` 559 → `ab8384c` 699) | **−32** (`0180e75` 894 → `cc3e281` 862, in 5m43s) | **900 → 846 = −6.0 %**, `8644d8f` 05:44Z → `c832a2a` 06:44Z on 2026-08-23, in **one hour** |
| registry rows | 1,087 → 1,465 | +134 (`0c69eaa` → `d76fb10`) | −13 (`6fa54f9` → `88d2b50`) | −1.2 %, in 3m29s |
| profiles (11 snapshots) | 919 → 995 | +22 | **never fell** | 0 % |

Two things follow. Growth is fast, lumpy and unpredictable, so **no band narrow enough to
mean anything survives it**. And the worst legitimate fall on record is 6.0 %, so a floor
with materially more headroom than that catches an emergency and nothing normal.

## What was decided, per fact

### `active_rows` → (a) a one-sided floor, `800+`, at all three sites

The sentence is the product's headline — the first thing a visitor reads in `README.md` and
the first thing an agent reads in `CLAUDE.md` — and the reader needs the magnitude: "hundreds
of employers, not five" is the claim. A floor keeps the magnitude and can only be broken by
the thing worth an alarm.

`800+` rather than the linter's own suggestion of `820+` or the rounder `900+`: `900+` leaves
7.1 % of headroom against a 6.0 % drawdown already observed, which is a knife-edge, and the
cost of firing is a red CI that switches off the registry gate. `800+` is the first round
floor with headroom (17.4 %) about three times the worst thing that has ever happened.

### `registry_rows` → (a) a one-sided floor, `1,300+`

Same sentence, same reader; this one is the denominator of every coverage claim the project
makes ("reads N of M"), so the magnitude is load-bearing. `1,300+` is tighter than the
linter's suggested `1,200+` and is justified by measurement: across 111 snapshots the
registry has never fallen more than 13 rows (a −1.2 % drawdown), so 165 rows of slack is
ample — twelve times the worst fall on record.

### `firmographics_profiles` → (c) the command; the `Fact` is deleted

Its only site was a cell in `docs/AGENT_BRIEF.md`'s flow diagram. Three things decided it:
its reader is an **agent**, who can run a command; every *other* cell in that diagram names
the FILE a step produces (`discovered_cache.json`, `scraped_cache.json`) rather than how much
of it there is, so the count was the odd one out; and no decision anywhere turns on 995
versus 900. The cell now reads `cloud_state/firmographics.json` and the count is one command,
quoted in the brief's own enforcement table.

**What is lost, stated plainly:** nothing that was being checked, because a bracket was never
a collapse alarm — it fired on growth just as readily. But the store now has no alarm at all,
and it deserves one: 919 → 995 over 11 commits, never falling. Filed as **BACKLOG 359**
against `company-intel`, whose digest line already prints the export count.

## The three options, and why two lose

**(b) a generated value — a marker the tool fills, so a stale hand-written number becomes
impossible.** Rejected, and it is the most tempting of the three. A generated number is true
by construction and therefore *can never go red*. On the morning the registry collapses from
969 to 400, the generator would quietly write "400" into the README and the build would stay
green. It converts an alarm into a mirror. The same objection applies to extending `--fix` to
census facts, which is why `test_fix_never_touches_a_census_fact` still stands.

**(c) replace the number with the command that produces it.** Right for the profile count,
wrong for the other two. `docs/AGENT_BRIEF.md` says "anything a future reader can discover by
running one command belongs in a doc **as** that command", and the test is *who the reader
is*: a visitor reading `README.md`'s opening paragraph cannot run anything, and an opening
pitch that says "reads `python registry_health.py --census` companies' boards" tells them
nothing. Note that both surviving sites already carry the command **beside** the number
(`README.md:50`, `ARCHITECTURE.md:35`), which is the honest reading of that rule: the number
orients, the command settles.

**Widening the band — explicitly rejected, and it was taken anyway while this was being
written, which is the best evidence for rejecting it.** Commit `21a8700` (`scraper`, 08:03Z
— its stamp reads `11:03:48+03:00`, and writing that as `11:03Z` was this record's own
instance of the mistake it complains about two sections up) found master red, widened the
three sites from `~900` to **`900-1,100`**, and recorded the
reasoning honestly: *"which is the remedy the linter itself prescribes and holds for about a
week at the current growth."* The linter did prescribe it, which was a fault in the linter.

That band sits **131 rows below its own upper edge**, so 132 more rows turn it red.
Measured against three trailing windows
on the same 111 snapshots:

| trailing window | rate | `900-1,100` goes red in |
|---|---|---|
| 2 days (`6e68642` 870 → 969) | +49.0 rows/day | **2.7 days** |
| 3 days (`8a887a7` 877 → 969) | +30.4 rows/day | **4.3 days** |
| 5 days (`c832a2a` 846 → 969) | +24.5 rows/day | **5.4 days** |

So the remedy bought between three and six days, not a week, and it bought them by making
the *lower* edge 900 — which is a floor of 900 with a countdown attached. Widening again
buys less each time, because the rate is rising; and a band wide enough never to fire checks
nothing. Which is why the two-sided forms are now **refused** rather than discouraged:
leaving them legal leaves the move available, and the linter's own error message used to
recommend it.

## What the grammar is now

```
800+  1,300+  FLOOR     - the only legal form. True iff today >= the floor.
900-1,100     RANGE     - an error as of today, and the reason the grammar changed.
875           BARE      - an error, as before; it will be wrong within a day.
~900          BRACKET   - an error as of today: a band with soft edges.
850-950       RANGE     - an error as of today: a band with hard ones.
~900+         MALFORMED - a floor is exact.
1,30+  1,,200+  MALFORMED - grouping must be canonical. `_int` strips commas, so `1,30+`
                            read as 130: one keystroke, a tenfold drop, and a green build.
0+  00+       MALFORMED - a floor of zero is not a claim.
٨٠٠+          MALFORMED - `\d` is Unicode-wide, so Arabic-Indic 800 was TRUE and
                            unreadable at the same time.
```

And one rule that is not about the token at all: **a floor may only ever be RAISED.** The
linter reads the committed blob and errors when an edit lowers a floor the number has not
actually fallen through. Lowering is widening a band under another name, it was fully
available until an adversary set all three sites to `0+` and got a green build, and
`floor_is_stale` cannot see it because a decay detector cannot tell `800+`-written-in-August
from `0+`-written-this-morning. The "has not actually fallen through" clause is what stops it
deadlocking: if the number really collapsed, its own error fires and lowering is the repair.

The bracket model took its tolerance from the trailing zeros the author wrote — `~1,200`
claimed hundreds, `~870` claimed tens — and the module was proud that **no tolerance number
lived in it**. That model is deleted, along with `precision()`, `_round_half_up()`,
`bracket_holds()` and `census_span()`. The claim it was making is now stronger, not weaker:
the *check* has no tolerance at all, because `today >= floor` is exact.

One advisory constant remains, `CENSUS_HEADROOM = 0.15`, and it never decides whether a check
passes. It answers "what floor should I suggest to an author writing one now?" (today's value
less 15 %, rounded down to two significant figures) and "when has a floor fallen so far behind
that it has stopped checking anything?" (twice that, so a WARNING at 30 %). It is set from the
6.0 % measurement above, not from taste.

The ratchet is a **warning**, not an error and not a `--fix`: the growth that caused the decay
was nobody's push, so an error would punish whichever lane happened to be pushing — the same
incentive inversion `check_morning_checks` already warns about. Prior art for the shape is in
the test suite: `test_the_collected_test_count_never_falls` asserts `n >= 1124` and says
"Raise the floor when you add tests; never lower it to go green." (This commit raised it from
963; the first draft of this paragraph quoted an intermediate value that no longer existed by
the time the commit was written — found by the wave-3 claim audit, which is what it is for.)

## The guards

`tests/test_units.py` gained **twenty-one** functions (+29 collected items, 1,112 → 1,141),
of which two are the deliverable:

* `test_a_census_fact_that_grows_does_not_go_red` — the same document, the same floor, a
  measured value three times it; asserts **zero** errors, not "no collapse error", because a
  site whose pattern stopped matching also errors and would make the guard vacuous.
* `test_a_census_fact_that_collapses_goes_red` — same document, same floor, value 400;
  asserts the error names the collapse and both numbers.

Both drive the real `check_derived_facts()` over a synthetic `FACTS` entry and a `tmp_path`
`ROOT`, so the function under test is the function that runs. Around them:
`test_the_only_legal_census_form_is_a_floor`,
`test_a_census_site_may_not_carry_a_bare_number_or_a_two_sided_band` (the anti-widening
guard), `test_the_ratchet_is_advisory_and_only_ever_points_upward`,
`test_the_floor_notation_never_captures_the_three_plus_years_idiom` (`CLAUDE.md`'s first
sentence says "experienced (≈3+ yrs)", and this repo's own histogram idiom writes
`via=cards56+links37+dom35+`, which is ten syntactically perfect floors on one line), and
`test_every_live_census_site_carries_a_floor_and_clears_it`, which reads what actually
shipped rather than a fixture.

Ten more came out of the adversarial waves, and the shape of two of them is the lesson:
`test_a_value_exactly_at_the_floor_is_green` and
`test_lowering_a_floor_is_refused_through_the_real_check` exist because the first versions of
their guards pinned the *predicate* while the *wiring* went untested — `floor_holds` had
zero production callers, and unwiring the lowering ratchet killed no test. The second guard
builds a real git repository in `tmp_path` rather than calling `floor_was_lowered`. A guard on
a function nothing calls is the defect this file exists to prevent, and it was made twice in
one day.

## Also decided here

The fact registry now **describes itself**: `facts_registry` is an `exact` fact computing
`(len(FACTS), sum(len(f.sites)))` with its site in `docs/AGENT_BRIEF.md`'s enforcement table.
That paragraph said "10 registered facts, 18 sites" while `FACTS` held 9 — the one number in
the repo that explains the registry was the one number the registry did not check.
