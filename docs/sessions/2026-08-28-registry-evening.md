# 2026-08-28 evening — `registry`

Everything here is against `origin/master` `759ba36`. Numbers were re-derived, not inherited.
**Four diagnoses of the red test were wrong before the right one, and two of them were mine.**
The chain is written out rather than tidied, because the tidy version would be the fourth
confident wrong answer.

---

## The brief said master was red on one test. It was red on three, and none was that one.

`test_two_rehearsed_nights_keep_every_pool` — the test both `docs/BACKLOG.md` 379 and 380 name,
the one two lanes reproduced independently — **passes on a pristine `759ba36`**:

```
rehearsal OK: 2 night(s), policy worst
```

It passes because `Salvador Technologies` acquired a `domain-dead` token overnight. That is
terminal, so `in_probe_pool` excludes the row, so it is not in `pools0` at all and nothing can
"lose" it. **A data-driven rehearsal going green is not evidence that a defect was fixed.**

What master was actually red on, reproduced in a throwaway `--detach` worktree at `759ba36`:

| test | lane | disposition |
|---|---|---|
| `test_no_two_active_rows_share_a_board` | **`registry`** | **fixed** (`382`) |
| `test_native_url_is_derived_from_the_public_url_alone` | `jd-text` | filed `383` — exposed by a row of mine |
| `test_every_open_role_in_the_ledger_carries_a_job_description` | `jd-text` | left; expected churn |

## 379 was not a note defect, and I had to be shown that by an adversary

Four answers, in order.

**(a) The backlog's cause does not hold.** It says the evicted `no IL listing` was the row's
membership in `validate_empty`'s pool. `in_validate_empty_pool:42` keys on
`no open israel roles` / `cross-validated` / `empty-but-suspect` — **all three already
protected**. Protecting `no IL listing` would have changed nothing. Its second proposal was
already implemented.

**(b) The cap is not involved.** Replayed over the row's real `063d14b` cell, the note is
**188 characters** when the token disappears. Nothing was evicted for space. What removes it is
`replace_own`: `retry_unreachable._note` uses one marker for every branch, so its `empty`
verdict is replaced by its `still unreachable` verdict.

**(c) My answer — make `replace_own` keep a protected FACT its replacement does not restate —
was measured and rejected.** I shipped it, guarded it with four tests and four mutants (all
killed), and sent an adversarial pass at it. It drove **37 real writer call-sites over the 537
real parked rows**, deciding membership through `registry_health.pools()`, and found:

```
one night : 0 rows lose a pool that the old code kept   (net-positive: 3401 -> 3346 losses)
two nights: 63 rows DO                                  (51 validate_empty, 36 the 02:30 pool)
```

Two nights is the real regime — both writers are daily crons. The mechanism is the cap after
all, one step removed: a retained segment lengthens the base, `append` then finds every
remaining segment protected, and its "newcomer is DROPPED whole" branch discards **the tool's
own fresh verdict**. `Biomica` keeps `retry 2026-08-28: scanned; no open Israel roles now` and
loses `retry 2026-08-29: still unreachable`, leaving the retry pool. `check_invariants` cannot
see it — F needs a dangling `<tool> <date>:` and F2 a truncated mode, and the note it produces
is syntactically perfect. **My own guard was blind by construction**: it asserted
`len(cell) < 220` to prove the cap was not the point, and the cap was the point.

I tried a best-effort variant (retain only when nothing is displaced). It does not fit:
188 + 3 + 51 = 242 > 220. There is no version of this that keeps both the fresh verdict and the
stale fact in 220 characters. **Reverted whole** — code, four guards, four mutants,
`ARCHITECTURE` §2 paragraph.

**(d) The transition is LEGITIMATE.** A row that has become UNREACHABLE is no longer a row we
believe is EMPTY. Measured with the pristine code:

```
BEFORE  validate_empty=True   owned by 7 pools
AFTER   validate_empty=False  owned by 6 pools        orphans: []
```

`tests/rehearse_registry.py` subtracts five legitimate exits from `lost` and none of them is
*the tool that owns the segment carrying the pool's token retracted it*. That is a **sixth**
exit, the same shape as the fifth (added for probe → hunt → probe). Filed as **388** and
deliberately not done tonight: ARCHITECTURE §2 names loosening this check as the obvious way to
fake a green rehearsal, so it needs its own control re-proved, not a tired session.

**What the exercise was worth anyway.** Two real defects came out of the adversary's sweep and
are filed: `389` (`replace_own`'s bare-prefix marker test — `retry` deletes `retry-resolved`,
the `SmartRecruiters`/`recruiter` shape of `72`) and the residue in `384`, now with the cost
table that says why widening the protected list is not free.

## `Unframe` / `Unframe AI`: two active rows, one board — and the path that minted it

Found by the red suite. Both on `boards-api.greenhouse.io/v1/boards/unframe/jobs`, both active,
both "verified 10 IL". `check_invariants` check B cannot see it *because it counts names*.

Traced commit by commit:

| commit | `Unframe` |
|---|---|
| `d76fb10` | created, no url, inactive |
| `f45e24c` | `listing_hunt` activates it on `job-boards.greenhouse.io/unframe` — the **human** page |
| `759ba36` | **self-heal re-resolves** it to `boards-api.greenhouse.io/...` = `Unframe AI`'s url |

Every de-dup key in this lane is checked when a row is **created**. `apply_resolved` rewrites
col 3 of a row that already exists, so each key had been checked against the value the row
*used to have*. It had an identity veto and no check that the address it was about to write was
already held. **`_boards_held()` now refuses that**, on normalised url or `(platform, token)`,
reading the lines the run is editing so an intra-run collision is caught too. The row is left
where it was rather than parked: deciding *which* twin keeps the board needs evidence this tool
does not have — the board's own `<title>` said **Unframe**, so `Unframe AI` was parked
`alias-of`. 0 roles were in `matched`/`sent` under either name.

**The general question, all 1,000 active rows:** exact `api_url` **0** groups, `(platform,
token)` **0**, Comeet uid **0**, normalised host+path **2 groups / 4 rows** — `AWS` and the two
`Microsoft` rows, both already in `test_no_two_active_rows_share_a_board`'s dated allowlist as
`232`. So the check was not the gap; the moment it was never run was. Tonight's applier cannot
mint these: it checks five keys against a fresh read before every append and only ever appends.

## The region variant — PLAYSTUDIOS is 1 of 32, not 1 of 20

```
region-marked ACTIVE rows: 32   (us 11, global 10, en_us 6, eu 3, uk 1, asia 1)
  native-ATS, countable for free : 4
  the class — answers, right company, ZERO Israel : 1
```

The other 28 are `scrape`; 12 are cached and none is the class, **16 are not in the scrape cache
at all** so they are not measurable tonight. The number that matters is not 1, it is **why
nothing was looking**: PLAYSTUDIOS' `-asia` board ANSWERS, with 4 postings, so its
`health_baseline` is 4 — and `confirm_zero`'s pool requires exactly 0. **The class is invisible
to the zero audit by construction.** It is now one command: `registry_health.py --regions
--fetch`.

Its Israeli studio is **SuperPlay** (`comeet.com/jobs/superplay/28.003`, 16 postings / 14 Tel
Aviv, incl. *Head of BI*, *FP&A Analyst*, *Game Economist*) — an active row, but read by a
browser off `superplay.co`. Repaired to the native Comeet API. The live "Gaming Business
Analyst" is on **neither** board, so PLAYSTUDIOS is a wrong ADDRESS, not an empty company:
routed `needs re-resolution` into the 19:00 hunt.

## The zero audit's own tool was parking companies into silence

Three fixes to `confirm_zero.py` before running it on 194 rows, each of which would have
corrupted a verdict at scale:

1. **`wrong-url` parked into no pool.** It set `active=false` and wrote a segment carrying no
   `verdicts.TOKENS` token — and did so **even when the note write was skipped** as evicting,
   so a row could be parked carrying no `zero-confirm` segment at all.
   `_assert_routed_rows_are_owned` filtered on `"board answered"`, the *other* branch's wording,
   so it could not see either. The park now carries `needs re-resolution`, happens only when the
   note was written, and the assertion covers every row the tool turns off. **It immediately
   caught the damage already done: `Fast Simon`, `Veriti` and `Belkin Vision` were in no pool
   at all since yesterday.** Repaired — pool 421 → 425.
2. **A landing page could be `confirmed`.** Condition (c) was documented and unimplemented:
   `_JOBLINK` was dead code and the LLM gate checked only cond1/cond2. `cond3 == False` can no
   longer confirm, and `board_link()` follows one hop to the same-domain board the page names,
   which becomes the page of record.
3. **No idempotency skip** — the cadence its own docstring claims was a SORT key only, so every
   run re-rendered and re-judged every row already answered. Now a filter, with `--force`.

**And the tool could never have completed an `--apply` run from the CLI at all.**
`if __name__ == "__main__"` sat four lines above `_assert_routed_rows_are_owned`, so running it
as a script called `main()` before the body finished evaluating: `NameError`, raised at the
write, **after ~40 renders and ~35 `claude -p` calls were spent** and after the evidence had
been written — so the run looked like it had worked and nothing reached the registry. A dry run
returns before the assertion, and `python -c "import confirm_zero; confirm_zero.main()"`
evaluates the body first, which is how it was driven yesterday. Only the documented CLI failed.
Filed as **390**, fixed, and guarded repo-wide by
`test_no_root_module_defines_anything_after_its_entry_point`, with a positive control run
against the unfixed file.

## A board can answer perfectly and be dead — 18 rows, and one of them was emailed

The operator's tip, and the class nothing here could see. `HiBob` was `smartrecruiters/HiBob`:
HTTP 200, valid JSON, `totalFound 1`, and the one posting was *IT Assistant*, **London**,
released **2020-01-24**. Proven unreachable rather than argued — the row exactly as it was:

```
in any re-check pool : NONE     orphans() sees it : []     in stale.json : False
in_zero_confirm_pool : False    check_invariants C2/C3 : both PASS
```

Every escape is structural. `health.py` sees postings > 0, so the row never enters
`stale.json`, so the 06:00 self-heal — whose scope IS `stale.json` — never sees it.
`confirm_zero` needs an all-time high of exactly 0 and this returns 1, the same escape
PLAYSTUDIOS used. Every pool requires `active == "false"`. **`orphans()` ranges only over
PARKED rows**, so the one invariant that exists to catch "owned by nothing" is blind to the
active half by construction. C2/C3 pass because the endpoint IS on smartrecruiters and the
tenant IS the name. And the note said `deep-verified MANUALLY` — **a human verdict is exactly
as stale as an automated one, and this is the counter-example.**

The signal is `posted_date`, in the common job shape, in every payload we fetch, read by
nothing. One free fetch per active native row:

| newest posting | rows |
|---|---|
| < 3 months | 415 |
| 3–12 months | 4 |
| 12–24 months | 3 |
| 24–36 months | 4 |
| **> 36 months** | **11** |

**18 at ≥ 12 months.** Oldest `Ness Technologies` **2014-03-18**, then `Nexar` 2017,
`DustPhotonics` 2019, HiBob 2020. **14 of the 18 are `smartrecruiters`** — a platform pattern,
not a coincidence.

**It had already shipped**: `TLVTech`'s *Data Analyst*, posted **2024-10-22**, is in `matched`,
was **emailed**, and is still seen today. A 22-month-old posting published as a current job.

HiBob is repaired, and the answer was in our own registry — two rows already read
`*.careers.hibob.com`, so HiBob runs careers sites on HiBob. `careers.hibob.com` is a
Comeet-powered page the production scraper reads for **17 postings, 17 Israeli**, including the
*Senior Business Analyst* the operator named. The other 17 rows are NOT repaired.
`registry_health.py --stale-boards`; filed as **406**, with **407** for why `orphans()` cannot
see any of this.

## The queue

The 2026-08-28 proposal file had 36 unapplied entries; 31 were only applicable that calendar day
(`--max-age` reads a date). Dry-run then applied: **1 row** (`Harnessinc`, greenhouse, 81/1 IL,
board `<title>` "Harness" — containment, which is why it is not equality). Everything else was
correctly held or deferred: 10 name-overlap HOLDs, all real twins (`Rapyd Financial
Network`/`Rapyd`, `ERGO NEXT Insurance`/`Next Insurance`, …), 8 deferrals with `il >= 1` whose
page fails `looks_like_a_job_listing_page` — recorded, not parked as empty. The `Enlight
Renewable Energy Ltd (ENLT)` HOLD was the valuable one: the answer was not a second row but that
the FIRST row's address was weak — **repaired to its Comeet board, 1 IL → 14**, grounded on the
company's own careers page linking the uid.

**The search rung.** The free ladder's measured ceiling on this queue is 2.2% on never-hunted
names, and every one of the 877 seeds is an aggregator permalink with no company address, so a
real search is the only thing that answers them. `drain_queue` gained **R5**, last on purpose,
so a credit is only spent on a name nothing free could answer. The credential is stashed at lock
time and handed back for the duration of one call — `_gate._UNLOCK_BUDGET` stays 0 throughout,
and `_receipt()` now prints `unlock_spent=0 ... search_spent=N` and still asserts the gate
counter is zero, so a declared spend and an accidental one can never be confused.

Its first measurement found my own bug: `propose_from_text` has **no Comeet recogniser** (nor
does `probe_ats._PLATFORMS`), so hosted `comeet.com/jobs/<slug>/<uid>` URLs — what the search
returns for an Israeli employer more often than anything else — fell through as
`search-page-no-ats`. **4 of the 6 searched names had found a Comeet board and the rung reported
0 hits.** Wired to the module's existing `comeet_from_hosted_page`; yield on the same 8 names
**0% → 25%**, and every non-conversion now records why (`comeet-dup-board`, `comeet-no-il`,
`comeet-notoken`).

**The full run, and it is the session's largest number.** 876 names walked, **843 searches**,
3,163 s, `bound=queue`:

```
111 actionable proposals (107 ats + 4 scrape)   never-hunted yield 111/876 = 12.7%
   search-comeet 69 · search 36 · own-site 4 · slug-probe 2
653 refused: search-page-no-ats 605 · probe-no-il 20 · comeet-dup-board 15 · comeet-no-il 7
```

**12.7% against the free ladder's measured 2.2%** — 5.8×, and `search-comeet` produced 69 of
the 111, so the bug above was worth about two thirds of the rung.

Applied: **56 rows**, 22 held as name twins, 23 deferred with no row, 6 skipped. Then measured
through the repo's own predicates rather than assumed:

```
55 of 55 activated rows produce >= 1 Israel posting   222 Israel postings
3 accepted by the keyword tier with no LLM: brightdata (Payment Risk Analyst),
  Vectorious (Analyst, Accounts Payable), Hello Flare (Senior Data Analyst)
```

100% of the activated rows produce, which is the number that says the rung's `il >= 1` gate is
doing its job. The 4 `scrape` proposals are all the `own-site` rung with `il_hint = 0` and can
never be applied — **401**, filed before the run and confirmed by it.

`44 Ventures` was parked by hand: `pipeline/aggregators.py` lists it WITH EVIDENCE (a VC page
serving another company's board) and its own Comeet tenant carries its PORTFOLIO's jobs. The
applier's aggregator gate now reads the whole trail rather than only the endpoint — a search
rung resolves an aggregator's page to the ATS behind it and the endpoint is then an ATS host,
which no aggregator test can refuse. It did **not** catch this one (the search returned the
comeet URL directly), so the row is parked explicitly and the gap is recorded rather than
papered over.

## The zero audit could not drain its own pool, and only running it showed that

Two more defects, both mine, both invisible to reading:

- **The cadence keyed on the NOTE.** The note write is best-effort by design — `_write` skips
  it whenever it would evict another tool's segment, which on this pool is most rows, because a
  row is in this pool precisely because it has been stamped many times. So the filter excluded
  nothing: **the same 29 rows were re-rendered and re-judged in four consecutive batches**, a
  Playwright render and a `claude -p` call each, every time. It reads
  `cloud_state/zero_confirm.json` now, which has no cap and is written for every judged row.
- **`not-ours` was the one cond2 value never sent to the model.** Those rows returned
  `unconfirmed`, which writes nothing to the row AND nothing to the ledger, so four of them
  (Dolby, UserWay, Sight Sciences, Incredo) spun for ever. It is the *wrong-url* finding in its
  rawest form — the page names a different employer — so it is now judged: two came back
  `wrong-url` immediately, and `UserWay`'s real address is `levelaccess.com`, which acquired it.
  An `unconfirmed` ATTEMPT is now recorded in the ledger, never on the row.

And **the tool could never have completed an `--apply` run from its own CLI**: the entry point
sat four lines above `_assert_routed_rows_are_owned`, so `main()` ran before the body finished
evaluating and `NameError` fired at the write — after ~40 renders and ~35 `claude -p` calls
were spent, and after the evidence had been written, so the run *looked* like it had worked.
A dry run returns before the assertion and `python -c "import confirm_zero; confirm_zero.main()"`
evaluates the body first, which is how it was driven on 2026-08-28. Only the documented CLI
failed. **405**, fixed, and guarded repo-wide by an AST lint with a positive control run
against the unfixed file.

## The adversarial waves found four unsound verdicts of my own, hours old

Three waves, each in its own worktree, none spending Bright Data or dispatching anything.
Wave 1 reversed a fix (above). Waves 2 and 3 read code I had written the same evening.

**Four of the seven `confirmed` verdicts that evening rested on evidence that does not support
them, and they are stripped** (`ARCHITECTURE.md` section 8, applied to my own run rather than to
someone else's). By luck all four companies do appear to have no Israeli roles today, so no
published claim was factually wrong — the process was unsound, and that is what was stripped.

| row | why it was not sound |
|---|---|
| Dolby Laboratories | `cond2: not-ours` **and** a follow to `careers.dolby.com/go/Jobs-in-Germany/` |
| Procter & Gamble | a follow to `/global/en/other-careers` |
| Nominal | a follow from the BOARD to a single job-posting page |
| T-Mobile | `api_jobs == WALK_CAP` (1200) while the board reports 2000, reported as "A COMPLETE walk" |

Two of those are defects I introduced hours earlier, and both were invisible to reading:

- **`verdict_from` never read `cond2`.** Ownership rested on one LLM boolean, and
  `employer_named` is legally `""` under the schema. That was harmless while `not-ours` never
  reached the model — and my change to send it (so those rows stopped spinning) made it
  load-bearing the same night. `cond2 == "not-ours"` is now `wrong-url`, full stop.
- **The one-hop follow manufactured a board and therefore manufactured the reading.** It fires
  exactly when a page shows no postings, which is also what a correctly empty Israel-filtered
  board looks like. `jobs.dolby.com/careers?location=Israel` says "No results" — `shows-none`,
  unresolved by the operator's own rule — and the follow turned that into `lists-roles` on
  Germany's page. **A followed page may now ROUTE and never CONFIRM**: it is evidence the row's
  ADDRESS is wrong, never evidence about the company.

And a third: **every ERROR verdict was freezing its row for 30 days** through the ledger cadence
I had just added — 34 rows held on facts about our own renderer. Errors and stripped verdicts
now re-select; `unconfirmed` still holds, because we did render it, ask, and fail to tell.

**`Agency` was ACTIVE on the real registry.** Wave 3 proved the board-`<title>` check is gated
on `rung == "slug-probe"`, so the search rung is exempt — and then the row turned out to be
live already, written by the 20:23 `auto-expand` cron, which has no title check at all:
`auto-expand slug-probe; 821/1 IL`. `board_employer` on that board returns **'Meridial'**.
Parked `alias-of Meridial` hours before the 05:00 digest would have published 821 of another
employer's postings under a one-word queue name. Filed as **408**; the gating is still open.

Wave 3 also showed the Comeet title exemption is **load-bearing and lucky** (409):
`board_employer` on a hosted Comeet page returns the ATS vendor's title, so the check would
refuse every Comeet board — and the `company_name` the code cites as its independent signal is
overwritten by `fetch_comeet` with the name we passed in. What actually saves the path is
undocumented. Thirteen findings filed, 408-420.

## Cost

| | |
|---|---|
| Bright Data | **~861 credits** — 843 on the declared search rung over the whole queue, 12 on its two calibration probes, 6 on direct searches for PLAYSTUDIOS and HiBob. `unlock_spent=0` on every run: the gate's counter and the rung's are reported separately so a declared spend and an accidental one can never be confused |
| `claude -p` | the zero audit's reads (~35 spent on the crashed run, then the real batches) |
| Playwright | local, free |
| workflows dispatched | **none**, so no run record to delete |

`secrets.env` was never copied into this worktree (`381`); the key was passed per-command.
