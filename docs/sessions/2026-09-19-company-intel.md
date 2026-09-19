# `company-intel`, 2026-09-19 — seven declarations, a record the group's own site paid for, and a guard that refused a fold it had performed

Branch `cintel-2026-09-19` from `origin/master` (`525de44`). Three commits:
`a25e1c3` (pushed **02:21:01Z**, well inside the pre-05:00Z window the digest needs),
`f036253` (02:29:07Z), `fdc9e70` (02:33:18Z), plus this record. Every number below was measured
on this tree or on a live run; where I re-measured a planner's number and got a different one,
mine is stated and labelled.

**Spend: 3 seam calls, 62 s, 6 web searches, 0 Bright Data credits.** Every command that could
reach the unlocker was passed `JD_BD=0 BD_RUN_CAP=0 PAGE_UNLOCK_BUDGET=0`; the three seam calls
were `research_firmographics.py --only "Group19"` from the SHARED checkout, which is the only
place a paid rung is armed (`worktree-has-no-credentials`).

---

## 1. The seven declarations (`a25e1c3`)

`registry` landed five alias parks and a new parent row today; the 2026-09-11 rule is that a
park and its `firmographics.ALIASES` declaration land the **same day**, because either half
alone folds nothing and the failure is silent. Seven keys, six through `declared_aliases` (a
parked row's own dated `alias-of <R>` verdict plus the declaration) and one through
`alias_only_folds` (`618`).

**Measured before writing**, on the committed registry (2,494 rows) and the committed export
(1,701 records) — for each pair: exactly one parked row whose `verdicts.alias_target` names the
survivor, exactly **ONE ACTIVE** row on the survivor's identity (`roles._alias_fold_target`'s
and `alias_only_folds`' shared precondition), and the value an `identity_key` **fixed point**.

| key | survivor | path |
|---|---|---|
| `phoenix financial` | `הפניקס` | parked row |
| `pagaya` | `pagayais` | parked row |
| `רם אדרת ram aderet` | `ram aderet engineering` | parked row |
| `group19 tech` | `group19` | parked row |
| `בנק דיסקונט` | `discount bank` | parked row |
| `discount bank בנק דיסקונט` | `discount bank` | parked row |
| `clal insurance finance כלל ביטוח ופיננסים` | `clal insurance and finance` | `alias_only_folds` |

**The blast radius, measured rather than hoped.** `identity_key` is global, so I computed it
before and after over the union of registry rows, export keys and the roles ledger — **2,520
names, exactly 7 move, and they are the 7 declared.** Six identity groups grow (Discount's by
two). Nothing else in the population changes identity, which is the check the `Bounce`/`Bounce AI`
class asks for and the one a declaration batch can only pass by measurement.

**Two of the seven were not new pairs, and that is the finding.** `בנק דיסקונט` has carried
`alias-of Discount Bank` since **2026-09-01** and `Discount Bank בנק דיסקונט` since
**2026-08-28**. The parks were right, dated and terminal; the `ALIASES` half had never been
written, so **the fold had been inert for eighteen days** — a park doing nothing, with no log
line, no counter and nothing in the ledger to say so. That is the `571` shape, and `registry`
found it by looking for the DECLARATIONS rather than for the parks. It is the argument for this
lane keeping a standing test over the live snapshot instead of a checklist: a park is visible,
an absent declaration is not.

**Export 1,701 → 1,695 (-6).** Six keys folded, and the sixth was not one of mine to declare:

| folded key | survivor | what moved |
|---|---|---|
| `Phoenix Financial` | `הפניקס` | `employees_global` **5170** into an empty; `size_band` re-derived **L → XL** by `band_for` (not copied) |
| `Pagaya` | `Pagayais` | nothing — the survivor was complete |
| `רם אדרת \| Ram Aderet` | `Ram Aderet Engineering` | `employees_global` **150** into an empty |
| `בנק דיסקונט` | `Discount Bank` | nothing |
| `Clal Insurance & Finance- כלל ביטוח ופיננסים` | `Clal Insurance And Finance` | nothing |
| `הראל ביטוח ופיננסים` | `Harel Insurance & Finance` | nothing |

The Harel row is the one I did not declare: its key landed earlier the same day and could not
fold until `registry` re-activated the Latin row (`f2de9a6` — a cron had reverted it, `644`).
This was the first `--export` since, so the fold happens here. `Discount Bank בנק דיסקונט` has
no record, so its declaration folds nothing and waits for one — a declaration can be correct and
still move zero records. One field the single writer re-derived on the way past:
`Vessel Technologies, Inc.` gains `display_name` `Vessel` from `board_verify`, which the next
cron would have written anyway.

**Guards.** Three new tests on the dated registry snapshot (`tests/fixtures/registry/2026-09-19-companies.csv`,
re-cut by `registry` today) — the six pairs with each declaration removed one at a time, the
empties-only fill on the pair that actually moved a field, and the Clal arm **with both of its
refusals** (a name the registry holds in any state is left to `declared_aliases`; an identity two
ACTIVE rows answer to folds onto neither). Plus **one clause added to the existing fixed-point
test**: every alias VALUE must be a fixed point of `identity_key`. The map is consulted AFTER the
suffix strip and returns its value RAW, so `ALIASES["x"] = "Demo Ltd"` makes `identity_key("x")`
`Demo Ltd` while `identity_key("Demo Ltd")` is `demo` — a declaration that folds nothing,
silently, and one `_declared` can never satisfy. The comment beside `habana labs intel` has said
"post-suffix-strip forms" since the map was written; now it is asserted. Eight hand-aimed
mutants, **8 killed**.

## 2. I pushed before the suite finished, and it cost two tests (`f036253`)

Stated first because it is the process failure, not a footnote. `a25e1c3` went to origin with its
targeted tests, `check_invariants --strict` and `check_docs` green and the FULL suite still
running. The suite came back **2 failed, 2137 passed**, both caused by that commit.

**A declaration's blast radius is not only `identity_key`. It is every test that recorded the
world BEFORE it**, and only the full suite knows which those are.

1. `test_blurb_names_other_reads_the_brand_and_refuses_a_two_word_noun` — `render`'s `632` fix,
   landed hours earlier. Its clause (4) is titled *"the two survivors, both registry duplicates
   render must NOT fold (handed to registry)"*: `Pagayais`' blurb naming `Pagaya`, and the Hebrew
   Discount row's naming `Discount Bank`. `registry` has now ruled on both and I wrote the
   declarations, so `cross_check`'s me-check returns on `its == mine` before the victim scan and
   **`632`'s residue is 0, not 2** — `render`'s own 6→2 becomes 6→0 the same day. The clause now
   asserts the identity equality beside the absence, because that equality IS the reason; clauses
   (2) and (3) remain the accusing control and they are undeclared pairs, not a word list.
2. `test_the_site_census_sees_two_active_rows_on_one_site_that_the_exact_key_gate_cannot` —
   `registry`'s `site_twins`, landed today. Its positive control was the REAL Ram Aderet pair with
   both rows ACTIVE, a state that no longer exists in the registry (one is parked) and can no
   longer exist in the code: the two names are one `identity_key`, and `site_twins`' own third rule
   says a site whose rows share one identity is `shared_boards`' business. The control keeps the
   site, the two paths and the shape under two names the map does not fold, and the real pair is
   asserted below it as `site_twins(...) == {}` — the case now answered twice.

Neither test was weakened: both are re-aims at the same property, and the three mutants (drop
`pagaya`, drop `בנק דיסקונט`, drop `רם אדרת ram aderet`) still red the test that names them.

## 3. `Group19`: the record the group's own site paid for (`fdc9e70`)

`633`, filed by this lane on 09-18 on a cheap and general tell — **the record and the blurb
disagreed about the same name.** A public-sector Power BI `Data Analyst` in אופקים was publishing
under a `defense & aerospace` / `UAV/space software` profile, because the row read the GROUP's
shared careers page while the record had been bought for the Tech SUBSIDIARY. `registry` crowned
the group today and parked `Group19 Tech` `alias-of Group19`; a survivor with NO record folds
nothing (`459`), so without this the UAV record would have been orphaned rather than folded.

Bought through the evidence path — `board_url https://www.group19.org.il/career`, the new row's
own ACTIVE url, which `_row_evidence` hands the prompt. **3 asks**, and the reason is on the
record: the first answered `stage: early-private` beside a `stage_note` reading *"no public
funding round or valuation found"*, which contradicts the prompt's own FUNDING MODEL test and is
the exact correction 09-18 made for the sibling. `private-enterprise` is **2 of 3** and agrees
with `Group19 Tech`'s own record. The published record is the third ask **as the seam wrote it** —
nothing hand-assembled, because a record edited to match a board is the `596` failure this lane
spent 09-13 undoing:

    {"sector": "it services / outsourcing",
     "sub_sector": "Peripheral-region tech, digital and back-office services",
     "stage": "private-enterprise", "size_band": "S", "employees_global": 23, "founded": null,
     "il_center": "Sderot (HQ); branches in Safed, Mitzpe Ramon, Ofakim, Yeruham, Be'er Sheva",
     "business_model": "Services and outsourcing: employs teams in peripheral sites and delivers
                        digital, software, robotics, data and customer-service work for client
                        companies",
     "customer_type": "B2B",
     "stage_note": "Privately held social-enterprise company founded by Chana Rado; no venture
                    funding or public listing found"}

**`il_center` is the check that it read the SITE**, not a search engine's idea of the name: six
towns, five of them the towns the site's own subsidiary pages name. The second ask, which I did
not publish, named Beit Shean — a town the site does not carry — which is what a wrong reading
looks like from the outside. **0 of the 3 asks said defence, aerospace or UAV.**

**No `display_name`.** `board_verify`'s 09-19 read of the page names the employer `Group19`,
which is the row's own spelling, and `rolecard.display_name` returns early on `its == mine`: an
override equal to the name is one no reader ever sees (the `Landacorp` lesson, 09-18).

**Export 1,695 → 1,695**, one key for another: `Group19` added, `Group19 Tech` folded away, and
**the fold moved 0 fields** — the new record is complete but for `founded`, and the alias's
`founded` is null too. So nothing of the UAV profile survives on the key that publishes the
analyst, which is the whole of `633`. The `defense & aerospace` fact is not lost, it is
`Group19 Tech`'s and it is in `docs/sessions/2026-09-18-company-intel.md` and in git.

## 4. The defect this bought: a guard refusing a fold it had itself performed

`--export` refused outright:
`::error::company-intel refusing to publish: the union DROPS 1 record(s) the export already holds (Group19 Tech)`.

The superset guard asks `settle_keys` over a copy of the **FILE**, to learn which vanished keys
were meant. `fold_aliases` refuses a survivor with NO record — so a survivor bought in the **SAME
run** is invisible to that copy: the fold really happened in `recs`, the alias key was never
excused, and the guard refused to publish a deletion the union had itself performed.

**Eighteen declarations had never met this**, because every previous pair had both records in the
file already (`DoiT`, `Flare`, `Trivago`, all five 09-11 pairs). `Group19` is the first fold here
whose survivor is a brand-new record, and every future first-ever survivor record hits it.

The population is now `{**recs, **shared}` — the survivors the export actually holds, with the
file winning on value. It is still a guard: a key that vanished for a BAD reason has no survivor
record to enable a fold and is still flagged. One behavioural test carries both halves (the fold
is excused; a key nothing removed still refuses, **file byte-identical after**), and three mutants
die on it: restoring the file-only expression, `lost = []`, and dropping `_settled`.

## 5. Verdicts

| | |
|---|---|
| `python -m pytest` (worktree, on the pushed tree `fdc9e70`) | **2,140 passed, 13 skipped, 0 failed** |
| `tools/guard_kill.py --base 525de44` | **KILLS 4** of 4 new tests; no CANNOT-FAIL |
| `python check_invariants.py --strict` | 2,495 rows · 1,430 active · 0 orphans |
| `python docs/check_docs.py` | 0 errors, 30 warnings (none this lane's) |
| CI | `35415388118` (`a25e1c3` — **expected RED**, the two tests above), `35415782094` (`f036253`, the fix), `35415997435` (`fdc9e70`). All three were `queued` behind four lanes at 02:33Z, which is why the 09-20 row is a row |
| mutation records filed | **0, deliberately**, as on 09-18: `631` is open and the catalogue is the shared budget. Every guard was proved to kill instead — `guard_kill` above plus **11 hand-aimed mutants, 11 killed**, each named with the test that killed it |

## 6. What I made harder for the next lane

* **`fold_aliases` has now folded its first parent/subsidiary pair**, and it cannot tell that
  from a spelling pair. `645` carries the measurement and the two candidate fixes. Until then,
  the thing protecting `Group19`'s record from its subsidiary's headcount is that the parent's
  own ask happened to return one.
* **`employees_global` 23 is on file for `Group19` after being on file for `Group19 Tech`**, from
  independent asks, and it can be true of at most one of them (`645`). It costs nothing today —
  `band_for(23)` is `S` either way.
* **The superset guard's population changed**, so a reader of `ARCHITECTURE.md` §7 who remembers
  "a copy of the file" is remembering the version before 2026-09-19.
* **`declared_aliases()` now reads 18 pairs, not 7**, of 78 `alias-of` rows. Any test that pins
  that count pins a number two lanes move.
* **Two other lanes' tests carry my re-aim.** `render`'s `632` clause and `registry`'s
  `site_twins` control both now cite this session; a lane re-deriving its own number from its own
  session doc will find 2 where the code says 0.
* **`Group19` has no `scraped_cache.json` key until the 00:00 refresh runs** (registry's note,
  repeated because it is also a firmographics-blurb input): a blurb for the new row cannot be
  written from a board this checkout can read.
