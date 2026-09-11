# 2026-09-11 — `company-intel`

The spawn prompt asked why a test this lane owns flips with cron commits. The answer turned
out to be the lane's whole queue: the ten names the test was counting were not ten fresh
rows waiting their turn, they were **one class of name that no retry of ours could ever
answer**, and they had been going round a seven-day loop since 2026-09-04.

## What moved

| | before | after |
|---|---|---|
| names with no facts (render set, `identity_key`) | 10, and 10 of the 10 struck | **1** — `Mars Antennas And Rf Systems`, named |
| of those, names in a loop no retry can end | **10** | 1, and it is now visible every morning |
| firmographics records | 1,607 | 1,598 — nine declared duplicates folded |
| `Company intel:` says which drain stamped it | no (`474`, wrong on 4 of 4 mornings) | yes, off `budget_min` |
| a CI red any cron can cause on a clean tree | `<= 10` in `tests/test_company_intel.py` | the gauge is measured, printed, and alarmed in the MAIL |

Spend: **0 Bright Data credits** and **12 seam calls / 14 searches / 243 s** (this lane's
seam is `claude -p` + WebSearch; `secrets.env` holds only SerpApi and Bright Data keys, so a
worktree can run the research and cannot spend a credit).

## 1. The test was not flaky — the ten names were stuck

`tests/test_company_intel.py::test_every_name_this_lane_publishes_facts_for_has_them` reads
three COMMITTED files (`companies.csv`, `cloud_state/firmographics.json`,
`cloud_state/seen.db`) and nothing else: no date, no env, no locale, no network, no live
account. Nothing outside the checkout. It flipped because **crons commit state**: the 12:59
auto-expand run added `Sartorius` and `Searchapi` (10 → 12, red at `39f4f61` on a clean
`origin/master`, and red for `registry` and two other lanes), and the 14:27 intel cron
researched exactly those two (`firmo` stamp `todo=2 attempted=2 gated=10`) and it went green
again at exactly 10. Nobody fixed anything either time.

The ten were exactly the ten entries of `cloud_state/firmo_failed.json` inside the 7-day
strike gate — the `gated=10` in that same stamp. Every one had been refused by the
`employer_name` echo guard and struck, and the digest logs name them:

    09-04  FAIL Mars Antennas And Rf Systems (held: research profiled 'Mars, Incorporated', …)
    09-06  FAIL Bdo International            (held: research profiled 'BDO USA, P.C.', …)
    09-07  FAIL DataCore                     (unidentified despite role evidence)
    09-08  FAIL Arrow Components             (held: research profiled 'Arrow Electronics, Inc.', …)
    09-08  FAIL Noga Iso                     (held: … 'Noga - Israel Independent System Operator …')
    09-09  FAIL Shabak - … - Career          (held: … 'Shabak (Israel Security Agency / Shin Bet)')
    09-09  FAIL Rafa Labartories             (held: … 'Rafa Laboratories Ltd.')
    09-09  FAIL Greylock Partners            (unidentified despite role evidence)
    09-10  FAIL Loops Lab                    (held: … 'Loops (getloops.ai)')
    09-11  FAIL Mars Antennas …, Regatta Data (held: … 'The Regatta Group')

A strike is a seven-day gate, after which the SAME question is asked again — and for a
`held:` refusal the second call `research_with_evidence` buys is `_disambiguate`, *"a live
posting exists, identify THAT employer"*, which for a row whose url belongs to another
company answers with that same other company. Held, struck, gated, repeat. There was no
exit, and the gap could only grow: that is why `registry backlog` rose on 3 of the 7
mornings the 09-07 check measured, and why its delta clause failed.

## 2. Two causes, opposite fixes

**A — the echo was this company, spelled the page's way.** Five names. `_same_company`
compares stems, and `Loops Lab` vs `Loops (getloops.ai)` differs by a parenthetical the
page added, `Rafa Labartories` by a typo of ours, `Arrow Components` by a trading name,
`Mars Antennas And Rf Systems` by the word `and`.

`_same_company_loose` is the second chance, and its two arms are deliberately **not**
equally trusting:

* the ANNOTATION arm drops a parenthetical from the echo and re-runs the whole relation —
  but never when the asked name is a DIVISION, where the parenthetical is the only thing
  telling two records apart (`Sony (Semiconductor)` must keep refusing `Sony (PlayStation)`,
  which is why `identity_key` keeps a distinguishing parenthetical in the first place);
* the CONNECTIVE arm (`and`, `the`, `of`) licenses **equality only, never containment**, and
  that asymmetry is the whole of its safety. Drop `the` from `The Regatta Group` and the
  echo stems to `regatta`, which edge-contains `regattadata` — a UK clothing retailer cached
  onto an Israeli database startup until 2027-02, which is `525`'s exact failure rebuilt by
  a convenience. Equality after the drop is a different claim, and it is the one Mars needs.

Three names were declared in `ALIASES` rather than relaxed for, each against the board on
its own row: `rafa labartories` → `rafa laboratories` (`rafa.co.il/careers`, 9 IL),
`noga iso` → `noga israel independent system operator` (`noga-iso.co.il/jobs/`),
`arrow components` → `arrow electronics` (`careers.arrow.com`). Checked before declaring,
which is the Oak lesson (`522`): `Arrow Electronics` is a separate registry row, and the
declaration makes the two one identity — which is what one board read by two names is.

**B — the board on the row is another company's.** Five names, and the guard was RIGHT about
every one; the defect is the `api_url`. A `held:` refusal now buys a **NAME-ONLY** second
ask instead of the posting-subject one: same seam, same schema, same validator, the give-up
sentence exchanged through `_swap` (so a reworded base prompt fails at import, as
`_DISAMBIG_SYSTEM` already does), both fence sentences verbatim — they matter most here,
because the context names the impostor. The data says which page we hold and whose it is.

A record bought that way comes back with reason `board-names-other: <who owns the page>` —
a **success that carries a defect in the ROW**, printed on the `ok` line, counted in the
`firmo` stamp and surfaced in the mail. The fix is a registry cell and nothing in this lane
can make it, so the most this lane can do is buy the facts anyway and say why. Filed as
`596` with the five rows and whose board each one is.

Deliberately NOT done: a third call after `unidentified despite role evidence`. Two tests
pin that path at two calls, and for `Greylock Partners` — whose "board" is a VC's
portfolio-jobs aggregator — a third ask would profile the VC and hang its facts on the
postings of the companies it funds. That is the wrong-company shape, and the row itself is
the question (`596`).

## 3. The fold, and the three things that would have made it wrong

`579` asked for four duplicate records to be merged; `393` for one more. The naive version
is a trap with a measurement already attached to it (`242`), and two more turned up here:

1. **`newer()` crowns the wrong side in three of the five pairs** — `DT` (09-01) over
   `Digital Turbine` (08-21), `Port.io`'s 200 employees over `Port`'s 508, the null-headcount
   Hebrew Menora record over the Latin one's 1,335. So the direction comes from the
   registry's own ruling: `declared_aliases()` pairs a PARKED row's dated `alias-of <R>`
   verdict with an `identity_key` that agrees — the same two-declaration bar
   `roles._alias_fold_target` sets — and the survivor is `<R>`. The survivor's facts win and
   the alias fills only its empties.
2. **"Any group with an `ALIASES` member" folds 40 pairs, not 5.** Measured on the live
   registry before writing the rule. Twenty-three of them are `X Israel` site rows, and a
   site record carries the SITE's facts — the Microsoft-founded-1989 sentence §7 has carried
   since August. `_SITE_FORM` refuses those even when declared.
3. **Two of the 40 are ACTIVE rows.** `AWS` and `JPMorganChase` are separate scanner rows
   with their own boards; a rule reading the alias map alone takes both. `_declared` refuses
   any active row outright.

Nine records folded, 1,607 → 1,598: `DT`, `Port.io`, `Gong.io`,
`AutoDS - Automatic Dropshipping Tools`, `Investing.com`, `Intel Corporation`,
`Cadence Design Systems`, `JPMorgan Chase` and `מנורה מבטחים החזקות`. Every survivor kept
its own facts; on the live export the alias filled **nothing**, all nine survivors being
complete already.

It runs inside `union_store` AND `save_shared`, not once over the file, because
`cloud_state/seen.db` is `SINGLE_WRITER: daily-digest` and a key deleted from the export
comes back out of the runner's sqlite copy the next morning. Folding every view makes the
deletion stick with **no tombstone and no second writer** — `242`'s two blockers avoided
rather than solved. `--export`'s superset guard had to learn the difference: it refused the
first folded publish (`the union DROPS 5 record(s)`), and now subtracts the declared folds,
so a deliberate deletion publishes and a real loss still refuses. That guard's mutation
record was re-aimed rather than deleted.

**`autods` keeps its brand**, which is the half a fold breaks if nobody looks: the
`display_name: "AutoDS"` lived on the ALIAS record, and the page that names the employer
(`autods.com/jobs/`) has a `board_verify` row keyed by the alias. `display_plan` now lets a
declared alias's verify row vouch for its survivor when the survivor has no row of its own.
Measured: it writes exactly one name that was not written before — `autods`.

## 4. `474`: the mail was calling the digest's own drain "the bulk cron"

Two jobs write the one `firmo` stamp: `daily-digest.yml`'s `firmo_drain` step
(`--budget-min 20`, ~09:53Z) and `firmographics.yml` (`--budget-min 60`, ~14:2xZ). The mail
read whichever was on disk and labelled it `bulk cron:` — so on 09-08..09-11 it reported
`13 researched of 15 to do, 2 failed` as the cron's work on mornings the cron had researched
2 of 2 with no failures. The stamp already knew: only the digest passes 20 minutes.
`_drain_label` reads `budget_min`; a stamp without one (every stamp written before today,
and the four tests that pin the old wording) keeps `bulk cron:`.

The `_age >= 3` growth warning cannot fire any more — the drain stamps daily, so the age is
0 whatever the cron did — so it is REPLACED rather than revived: the gap grew **and** a name
is held. Both halves, like every other alarm in this section, because either alone is
routine. `stages.alarms("firmo", 2)` in `run.py` is untouched (four tests pin it), and the
question it was a proxy for belongs to the `cron` watch, which measures slots instead of
inferring one from a key two jobs write. A `FIRMO_STAGE` split was rejected: `infra`'s
workflow line plus a re-pin of four tests, where a label costs one branch. One token is
still owed by `infra` (`595`): the killed-drain re-stamp writes no `budget_min`.

## 5. The census assertion came out of CI

`assert len(gap) <= 10` measured a number **no push can move and every cron can**. It went
red on a clean `origin/master` for three lanes that had not touched this code, and green
again four hours later for the same reason. The test now measures the gap and prints it; the
named closures (`Oak`, `Hila & Co.`, `University of Notre Dame`, `Kidum Rehab Projects`) and
the Kidum wrong-company check stay, because those are things the CODE decides. The daily
reading moved to where a person actually looks: `registry backlog N (+D since <date>)` with
`N held (…)` and `N board-names-other` beside it, and a warning when the gap grows while a
name is held.

Rejected: counting only "stuck" rows in CI (still a census over cron-written state — the
morning a wrong-url row is activated, every lane goes red again).

## 6. The live run: 9 of the 10, and the tenth proves the class

`python research_firmographics.py --workers 2 --only "<the ten>"` from this worktree —
`--only` records no strike and stamps nothing, so a hand run cannot make the mail describe a
laptop:

    1414 active companies, 1598 researched, 10 to do
    4 name(s) gained their board's own live titles from the scrape cache
    ok   Arrow Components: electronics distribution / technology solutions / public / XL
    ok   Bdo International: professional services / private-enterprise / XL
    ok   DataCore: enterprise software / private-enterprise / S
    ok   Greylock Partners: financial services / private-enterprise / S
    ok   Loops Lab: software / data analytics / growth-private / S
    ok   Noga Iso: energy / utilities / private-enterprise / M
    FAIL Mars Antennas And Rf Systems (held: research profiled 'Mars, Incorporated', …)
    ok   Rafa Labartories: pharmaceuticals / private-enterprise / M
    ok   Shabak - Israeli Security Agency - Career: government / defense & intelligence / …
    ok   Regatta Data: data infrastructure / databases / growth-private / S
    9 researched, 1 failed, 1607 total in store; 10 to do, 10 attempted, 0 left (2.2 min)
    seam: claude-sonnet-5 x12 | 12 calls, 243s, 14 searches, 1 SEARCHLESS

Then `--export`: **1,607 records** (1,598 after the fold plus these nine), and the strike
ledger 16 → **7**, eleven cleared. The gauge, re-derived from the committed files:
**10 → 1**, and the active-rows gauge the same.

Five of the nine are the class-A fix doing its work — `Arrow Components`, `Rafa
Labartories`, `Noga Iso`, `Shabak - … - Career` and `Loops Lab` passed the echo guard on the
FIRST ask because of `_same_company_loose` and the three declarations. Four more
(`Bdo International`, `DataCore`, `Greylock Partners`, `Regatta Data`) answered on the first
ask this time where they had refused before; twelve calls for ten names says two names
bought a second one.

Three of the records are worth quoting, because they are the evidence `594` is filed on:

* `Greylock Partners` — *"Partner-owned VC firm founded 1965; not itself the employer for
  the listed jobs, which are portfolio-company openings"*. The model said the thing the row
  is wrong about, in its own `stage_note`.
* `DataCore` — *"HQ in Florham Park, NJ"*, which is **Datacor Inc**, the company whose
  greenhouse tenant the row actually reads. The facts match the BOARD; the NAME on the row
  is the defect, and `il_center` is honestly `None identified`.
* `Bdo International` — BDO's global network, with `Tel Aviv (HQ of BDO Israel/Ziv Haft)`
  named. Honest about a network rather than a company.

**The tenth is the one that proves the mechanism is not a wish.** `Mars Antennas And Rf
Systems` was asked again about the NAME, with `careers.mars.com` named as the confectioner's
page and off limits — and the answer still echoed `Mars, Incorporated`, so the guard held it
a second time and nothing was cached. That is the correct outcome for this row on this url:
the record we do not have is better than the confectioner's, and the row is `594`.

One caveat this run surfaced and did not fix: `1 SEARCHLESS` of 12 calls — one of these nine
records is a parametric guess — and **the run does not say which name**. The count is in the
mail and the name is nowhere, which is the same shape as the refusals this repo makes print
their name. Filed as `595`.

## 7. What I made harder for the next lane

Four new names to know, and one behaviour that is no longer where you would look for it:

* `firmographics.declared_aliases()` reads `companies.csv` and caches on its mtime — a new
  cache, and the first thing to suspect if a fold does not fire after a registry commit in
  the same process.
* `fold_aliases` DELETES keys from the export. A reader who greps `cloud_state/
  firmographics.json` for `DT` or `Port.io` now finds nothing; `display_index` answers for
  both, as it always did.
* the `firmo` stamp carries three more keys (`held`, `board_other`, `held_names`), and
  `held_names` is a `+`-joined token because `Stage order:` is `k=v` pairs and a guard pins
  the token shape.
* `research_with_evidence` can now return a non-None record WITH a non-empty reason. Every
  caller already tested `if rec:`, which is why the shape is still a 2-tuple, but a future
  reader who assumes `why` means failure will be wrong.
