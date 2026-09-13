# 2026-09-13 — `company-intel`

Five items: the PARTIAL 09-12 row (`1 held (saver1)` and `registry backlog 3 (+1)`), the
firmographics mirror of `596`, `579` after two days of crons, the repointed boards' names, and
`597`. Every number below was read on the worktree at `346b4e4` unless it says otherwise.

## What moved

| | before | after |
|---|---|---|
| render-set gap (the mail's `registry backlog`, re-derived from committed files) | **1** (`Saver1`) | **0** of 1,442 |
| active rows with no sector (the `AGENT_BRIEF` command) | 2 (`Discovery`, `Saver1`) | **1** (`Discovery`) |
| records describing the company on a board the registry ruled foreign | 3 (`DataCore`, `Bdo International`, `Greylock Partners`) | **0**, and they cannot come back out of sqlite |
| `cloud_state/firmographics.json` | 1,651 | **1,649** (−3, +`Saver1`) |
| strike ledger | 8 names | 7 (`Saver1` cleared) |
| a searchless research answer | counted | counted **and named** (`597` closed) |

Spend: **1 seam call, 1 web search, 16 s** (`seam: claude-sonnet-5 | 1 calls, 16s, 1
searches`), **0 Bright Data credits**. A `--only` run stamps nothing, so that line is the only
receipt; the record it produced is checkable.

## 1. `saver1` was ours, and the third name was a clock

`Saver1` (`saver.one/careers`, activated by the 09-12 queue drain) failed on the 09-12 digest,
run `34685065990`: `FAIL Saver1 (held-twice: research profiled 'SaverOne (Saver1) 2014 Ltd.',
not this name)`. The echo is the company's legal name with our spelling inside it, and the
row's own scraped posting reads `מתקין שטח | SaverOne … חברת סייברוואן`. `_same_company` compares
stems, and `saver1` and `saverone` share no edge. That is class A of the 09-11 record, the
page's spelling of the same company, so the fix is the same: an `ALIASES` declaration checked
against the board, `"saver1": "saverone"`. No other row, record or role answers to `saverone`.
The test pins that the declaration admits the echo and that `Savers Inc` and `Saver Holdings`
are still held. A looser relation was not considered; 09-11 measured what one costs.

Researched from the worktree: `ok Saver1: automotive tech / road safety / public / S`, founded
2014, Petah Tikva, `Nasdaq: SVRE`. The first export rendered its brand `SaverOne 2014`, because
`_clean_display` strips `Ltd.` and keeps the registration year before it. Over every
`employer_named` in `cloud_state/board_verify.json` that shape occurs **twice** (`SaverOne 2014
Ltd.`, `APPTOR A.I 2023 LTD`). The year is now dropped only behind a stripped legal suffix, so
`Studio 2020` keeps its year. Re-running `apply_display_names` over the whole export changes
**one** name: `Saver1` → `SaverOne`.

**The 09-13 `registry backlog 3`** was not auto-expand. At the digest's sha (`00078d3`) the
render-set gap before its own drain read **15**; the drain researched 12 of 12. What was left:
`Mars Antennas And Rf Systems` and `Saver1`, both strike-gated (`gated=2` in the stamp), and
`ClixScale`, whose first role was matched by the pipeline step at 11:17 while the drain had run
at 10:46, and was held off the board, so the hook never saw it. The 14:24 cron researched it.

So the honest floor at 05:00 is an identity, not a number: `gated + failed + left` from the
`firmo` stamp beside the line, plus companies first matched after the drain and held off the
board. The 09-07 and 09-12 rows both failed on a `<= N` ceiling. The new 09-14 row asserts the
identity. `ARCHITECTURE.md` §7 says so beside the gauge.

## 2. `596`'s mirror: the records follow the row

`registry`'s `121ea58` parked or retired the twelve rows. Of those, six hold a firmographics
record. Each was read against what it describes:

| row | record describes | verdict |
|---|---|---|
| `DataCore` | Datacor Inc, Florham Park NJ, 1981, chemical ERP (the greenhouse tenant `datacor`) | **the board's owner** |
| `Bdo International` | the BDO global network | **the board's owner** |
| `Greylock Partners` | the VC, 1965 | **the board's owner** |
| `Entropy Organizational Development` | the Israeli consulting group, not `entropy.sa` | the row |
| `hms - Strategic Financial IT` | Halperin Consulting, Tel Aviv | the row |
| `Alma Labs` | edtech, an AI-literacy platform in Tel Aviv, researched 08-26 from its LinkedIn roles, before the hunt pointed the row at `almainc.com` on 08-31 | the row, not Alma Lasers; its postings (`almalabs.ai`, clients and dashboards) do not contradict it, and nothing on file confirms the product line either |
| `City Of Sunbury Ohio`, `Y Axis Global`, `GENECIT`, `John Bryce Solutions`, `TOTSAOT` | the row's own entity (the rows are retired as non-employers, and the records are honest about what they are) | left |

`Regatta Data` already describes `regatta.dev`, `אסם` is Osem, and `Ethos` and `Mars` hold no
record. No row was repointed to a board whose owner differs from the old record, so nothing
needed a re-profile. `DataCore` has no posting and no board, so there is no evidence to re-ask
from, and a name-only ask would have no guard against Datacor again.

**What shipped: `firmographics.DISOWNED` and `drop_disowned`.** None of the three renders today,
because no role carries them. But a record keyed by the name answers `n in have` for 180 days.
The morning the hunt re-activates `DataCore` on its own board, nothing would research it. The
drop is **dated**: a record whose `as_of` is after 2026-09-13 was bought afterwards and stays.

Rejected, on the table above: deriving the list from `identity_facts.not_domains` /
`not_tenants`. Three of the six declared rows with a record are right, and a derivation deletes
all three.

**Deleted or unified.** Two passes remove keys from a view: the declared fold and now the drop.
Four call sites need to agree about them: `union_store`, `save_shared`, `--display-report` and
`--export`'s superset guard. They are now one call, `settle_keys`. The guard runs it over a
copy of the file, so it excuses exactly what the views remove. The alternative was a second
copy of the fold's guard logic for the drop. The 09-11 wave already caught that guard excusing
20 keys nothing folded. One copy, not two.

## 3. `579` after two days

- `grep -c '"DT"\|"Port.io"' cloud_state/firmographics.json` = **0**; `Digital Turbine` and
  `Port` hold one record each.
- Osem triplet: one record, `אסם`. `Nestlé`, `Nestle` and `Nespresso` are `declared_aliases()`
  entries and hold none. `Nestlé Nespresso SA` keeps its own record, which is `registry`'s 09-01
  ruling (a different legal entity) and not a duplicate.
- `digital turbine|senior data scientist` (registry's fold): one role, one record.
- Netafim, Exyte, DoubleVerify: one record each. `Arrow Components` holds the record, with
  `display_name` `Arrow Electronics`. The separate `Arrow Electronics` row resolves to it
  through the 09-11 alias and holds none of its own.
- Identity groups with two or more records: **30**. Twenty-seven are `X Israel` site forms,
  kept by design. `Intel Corporation`, `Cadence Design Systems` and `JPMorganChase` are the
  one-declaration shape the 09-11 fold refused. The last is **`DoiT` / `doitintl`**. Its
  `ALIASES` entry exists, but no registry row is named `DoiT`, so the second declaration the
  fold needs cannot exist. It is the only record of that class in the export. Filed as `618`,
  not built: the records agree, nothing renders wrong, and a second fold rule is a second
  deletion the export guard must be taught.

No new pair appeared from the 09-13 events.

## 4. The repointed boards

Netafim (24 IL), Exyte (19), Arrow Components (5) and DoubleVerify (2) each hold a record
already, so the 09-14 mail should open `all N board companies profiled`. That is the 09-15 row.
Nothing to clear tonight.

## 5. `597`, closed

`ask` sets `searchless` on the result it returns. `research_company_detail` keeps the company
in `meta["searchless_names"]`. The job's `seam:` line and warning, and the mail's
`N SEARCHLESS (…)` clause and warning, print the names. `pipeline/llm.py` is untouched. A
refusal is still not a guess: the `_known` test in `ask` decides both the count and the name.

## Verdicts

| | |
|---|---|
| `python -m pytest` (worktree, before the rebase) | **1 failed, 2,024 passed, 13 skipped**; the failure was `test_docs_are_consistent_with_the_code`, run while the archived morning-check row was still missing, and it passes alone on the committed tree (`1 passed`) |
| CI on `79d5781` | run `34780964192`, **16 of 16 success** |
| `docs/check_docs.py` | 0 errors, 0 warnings |
| `check_invariants.py` | 2,383 rows · 1,381 active · 0 orphans |
| mutation records, this session | 5 run (4 new, 1 re-aimed), **5 killed**, every killer `behavioural` by `_classify_killer` |

## What I made harder for the next lane

- `firmographics.DISOWNED` is a hand-maintained dict. A record that vanishes from the export
  with no fold is now either a loss or a DISOWNED entry. `settle_keys` is where to look.
- `settle_keys` replaced three direct `fold_aliases` calls. A reader grepping `fold_aliases(`
  for the views finds only the definition, `settle_keys` and the tests.
- `meta["searchless_names"]` is a new key on the seam audit dict, and it reaches
  `last_run.json` through `rep["llm"]`.
- `_clean_display` now drops a trailing registration year behind a legal suffix.
- `ALIASES["saver1"]` is one more declaration, and the Oak check was run first.
- Five mutation records join a catalogue `617` says is already past its shard budget.
  At ~41 s a record that is ~200 s across the eight shards.
