# 2026-09-18 — `company-intel`

Four items: DoiT's blurb naming Google Israel, Holisto being trivago, the `Flare` identity
flap, and Group19 Tech's sector. Every number below was read on the worktree at `e88aa3f`
unless it says otherwise.

**A procedural note first, because it changes how this record should be read.** The plan this
session was told to execute was not in the scratchpad — only its answers file
(`plan_0918_companyintel_answers.txt`) existed. The four items, their order and their binding
decisions come from that answers file and from `PROMPT 7`; everything else here was
re-derived. Where a number in the answers disagrees with what I measured, mine is stated and
labelled (the "6 measured hits" is the one case: I read **7**, and the answers' 6 is the same
set with `DoiT`/`doitintl` counted once — one company).

## What moved

| | before | after |
|---|---|---|
| firmographics records for one employer under two brand names | 3 pairs (`DoiT`/`doitintl`, `Flare`/`Hello Flare`, `Trivago`/`Holisto`) | **0** |
| `cloud_state/firmographics.json` | **1,704** | **1,701** |
| records with a `display_name` | 189 | **190** (`Holisto`→`Trivago`, `Hello Flare`→`Flare`) |
| roles the two declarations fold (predicted) | dataset 186, `superseded` 17 | **183** / **20** — the 09-19 row |
| `blurb-names-other` over 210 cached blurbs, true positives | 7 hits, **0** real | not fixed — filed as `632` with the diff that reads 7→2, both real |
| `Group19 Tech` sector | `aerospace & defense tech` | `defense & aerospace` — **confirmed**, not corrected |

Spend: **1 seam call, 15 s, 1 web search** (`seam: claude-sonnet-5 | 1 calls, 15s, 1
searches`), **0 Bright Data credits**. A `--only` run stamps nothing, so that line is the
only receipt; the record it produced is in the export.

## 1. The guard the prompt asked for would have been wrong (item 1, DoiT)

The prompt says DoiT's blurb names Google Israel, "so the render hides DoiT's LIVE `Product
Analyst` card", and asks for a write-time refusal. Two halves of that are not true, and the
third would cost more than it buys.

**The card is not hidden.** `doitintl | Product Analyst` renders on today's board
(`docs/index.html`, card 131 of 131, `data-company="doitintl"`, reposted 09-17). What the
mail carries is a COUNT: `Render: board 131 cards, blurb-names-other doitintl→Google Israel`.
`rolecard.cross_check`'s own docstring (`541`) says the clause is "counted, never dropped".

**The blurb is right.** DoiT is a Google Cloud and AWS reseller; the blurb says so and names
no Israeli entity. `Google Israel` is what the guard prints because `_ID_SUFFIX` strips the
trailing `israel`, so that registry row's whole searchable identity is the single token
`google`. It fires on any blurb that uses the word and does not spell its own registry key.

**Measured, so the refusal could be judged rather than assumed.** Over all **210** blurbs in
`cloud_state/seen.db` against the **1,701**-record export as victims, first-match per blurb:
**7** hits, **0** impersonations — 2 DoiT rows (the blurb names the brand, the key is the ATS
slug) and 5 Hebrew-keyed rows whose English blurbs use one ordinary English noun that is some
registry company's only surviving token (`products` ×2 from `Air Products`, `system` from
`Poc System`, `capital`, `automotive`). On the rendered surfaces: **1** on the board, **3**
over board+archive. A write-time refusal would have refused 7 correct blurbs to prevent 0
impersonations, and the first one it refused would have been DoiT's.

So the defect is the READER, and it is `render`'s file. Filed as **`632`** with the exact
diffs and the measurement: the me-check at `rolecard.py:628` reads `tokens[me]`, the registry
KEY, so a blurb naming the company by the brand cannot excuse it — bridging through `ALIASES`
(3 lines) takes 7→5; and the victim side at `rolecard.py:615/618` reduces a two-word brand to
one ordinary noun whenever the first word is short, which `_COMMON_WORDS` does not cover — one
condition takes 7→4. **Together 7→2**, and both survivors are real duplicate employers
(`Pagayais`'s blurb names `Pagaya`; the Hebrew Harel row's names the Latin one, `621`).

## 2. `Flare` was `Hello Flare`, and the flap was a brand arriving

`Flare` did not lose a match. It did not have one: the LinkedIn net published
`senior-data-analyst-at-flare-4432756905` on 09-17, the ledger filed a new employer, the
gauge counted it `firmo: none` that morning, and the nightly drain bought it a record —
`git log -S'"Flare":'` names exactly one commit, `706e45b`, the 09-17 cloud run. What looked
like an identity-key regression is a NEW key.

The row's own board is the evidence, three ways: `Hello Flare`'s Comeet board is tenant
`36.00F`, whose public postings live at `comeet.com/jobs/`**`flare`**`/36.00F/...`;
`board_verify`'s reading of that feed names the employer `Flare`; and the 09-18 verify of the
discovered name `Flare` resolved it to `www.helloflare.com/careers` — the row's own domain,
`ok`, `employer_named: "Flare"`. The two role records carry byte-identical `tags` (same eight
skills, family `Data Analyst`, years 4, track IC). Checked before declaring, the Oak lesson
(`522`): `Flare` is not a `companies.csv` row in any state, the only rows carrying the word
are `Hello Flare` and `Cloudflare` (identity `cloudflare`), and nothing else answers to
`flare`. `ALIASES["flare"] = "hello flare"`.

**What the second record came with is worse than the duplicate.** `Flare`'s blurb (09-17)
reads "Flare is a threat intelligence company that monitors the dark web…" — that is Flare
Systems, a Canadian company, on a Tel Aviv legal-tech role. It has never rendered (the card
is `Hello Flare`'s) and after the fold it cannot. Left in place and NAMED here rather than
purged, per the orchestrator's ruling: no new purge arm this session. The other inert blurb
is `Trivago`'s, which is the empty string.

## 3. `618` built, because the second pair of that class was not harmless

09-13 measured this class at one record and left it: "the records agree, nothing renders
wrong, and a second fold rule is a second deletion the export guard must be taught to
excuse." `Flare` is the second, and it disagrees with its own blurb.

`alias_only_folds` is the map; `fold_aliases` still applies it, so there is no second deletion
— both key-removing passes stay the one `settle_keys` call, and `--export`'s superset guard
excuses exactly what the views remove, unchanged. The bar is still two facts that must agree,
and the registry's half is stronger here than a parked row's prose: the `ALIASES` declaration
AND the registry saying **this name is nobody's row in any state** while **exactly one ACTIVE
row** answers to the identity. A name the registry holds is refused and left to
`declared_aliases`, so this arm can never be the cheaper way past the bar that keeps `AWS`,
`Investing.com` and `Meta Israel` where they are; an identity two active rows answer to folds
onto neither.

Measured over the committed export: **2** pairs, `DoiT`→`doitintl` and `Flare`→`Hello Flare`.
1,704 → 1,702.

**Deleted or unified.** `_registry_rows` is now the single cached reader of `companies.csv`
for both passes, and `_derived` memoises each derivation beside the rows it came from, so one
mtime invalidates all of it. Two readers would have parsed 2,477 rows twice on every
`save_shared` and could have disagreed about the file mid-commit.

## 4. `Holisto` is `Trivago`, and the display name is the board's spelling

trivago N.V. completed the Holisto acquisition on 2025-07-31 and runs it as its Israel
"Innovation Center". One opening, twice: `holisto|senior data analyst` (Comeet 76.001, Rishon
Lezion) and `trivago|senior data analyst` (Indeed `jk=2cbff46345fc2ad1`, ראשון לציון), plus a
second, closed, pair under `Data Analyst`. Holisto's Comeet postings live under the path
segment `trivago` (`comeet.com/jobs/trivago/76.001/data-analyst/24.E6B`).

`registry` parked `Trivago` `alias-of Holisto 2026-09-18` in `c5fe0df` — the second dated
declaration a registry NAME needs — and relayed the direction evidence: the tenant's
`company_name` reads `Trivago` on 6 of 6 positions and **4 of the 6 apply mailboxes are
`holisto.<uid>@applynow.io`**, so the Israeli entity is the employer of record and survives.
No coverage was traded: the greenhouse `trivago` board the row held reads **11/0 IL**
(Düsseldorf), so neither role ever came from it.

**The `Landacorp` half, and the mechanism I got wrong first.** An override
`rolecard.display_name` refuses is a name no reader ever sees. I wrote a comment claiming the
fold (removing the `Trivago` record) is what saves it, then measured: `display_name` returns
early on `its == mine`, and the `ALIASES` declaration is what makes
`identity_key("Trivago") == identity_key("Holisto") == "holisto"` — the victim scan never
runs. The fold is a second, independent reason.
`display_name({'display_name': 'Trivago'}, 'Holisto', <union>)` returns `''` only with the
declaration removed AND the duplicate present, which is the test's control. Landacorp had
neither, so its refusal was right and `534` is still the defect there.

`DISPLAY_NAME_OVERRIDES["Holisto"] = "Trivago"`; the table is 6 rows, four ATS slugs and two
registry names that are not the employer's.

## 5. `Group19 Tech`: the sector was right and the BOARD is the defect

Re-asked with evidence (1 seam call). Verbatim answer:

    {"sector": "defense & aerospace",
     "sub_sector": "UAV/space software and engineering services",
     "stage": "private-enterprise", "size_band": "S", "employees_global": 23,
     "founded": null, "il_center": "Yeruham (HQ)",
     "business_model": "Engineering and software services/projects",
     "customer_type": "B2B / Government (defense, aerospace, drone companies)",
     "stage_note": "Social-business subsidiary of Group19, founded by Hana Rado and
                    Inbar Cohen; no venture funding found"}

The sector stands. Two fields moved and neither is it: `stage` `early-private` →
`private-enterprise` (the FUNDING MODEL test — a social business with no venture money is not
an early-private startup), and a `stage_note` that says what the company is instead of "small
privately-held engineering services firm".

What the re-profile found instead: the ROW reads the parent group's shared careers page.
`group19.org.il/career` carries 8 listings across several companies in the group — trading-desk
control, a financial analyst, a studio designer, digital marketing, customer service, back
office, a mechanical-engineering student, and the `Data Analyst` we publish — and that analyst
posting (661 chars, live on the board today) is `בניית דוחות ודשבורדים בPBI` for
`המגזר הציבורי`. Public-sector Power BI consulting, not UAV engineering. The tell is general
and cheap: **the record and the blurb disagree about the same name** (the blurb, written from
the board's own job text, says "data analytics and business intelligence services … public
sector organizations"). Filed for `registry` as **`633`**. The record must NOT be re-bought to
match a board that is not its own — that is the `596` failure this lane spent 09-13 undoing.

## Cross-lane

`SendMessage` to the roles implementer **did not resolve** (no agent named `Implement: roles
lane 09-18`, and `roles` matched only a 15-day-old session on another machine). The sentence
it would have carried, per the footer's rule: *both pairs have same-title twins under the
canonical name, so both take `_fold_into_twin` and the loser goes SUPERSEDED; expected
delta on the committed `cloud_state/roles.csv` is 186 → 183 rows and `excluded superseded`
17 → 20 (2 open pairs + 1 closed pair); nothing leaves the window.* The orchestrator relayed
the same two pairs independently and `docs/sessions/2026-09-18-roles.md` (`d58a0af`) records
roles' own reading of them, which agrees.

## Verdicts

| | |
|---|---|
| `python -m pytest` (worktree, on the pushed tree) | **2,096 passed, 13 skipped, 0 failed** |
| `tools/guard_kill.py --base origin/master` | **KILLS 7** of 7 new tests; no CANNOT-FAIL |
| CI on `dd37f9f` | run `35366756545` — QUEUED behind three lanes at 16:09Z; the job-level verdict is the 09-19 row |
| CI on `48b9857` | run `35367019912`. That commit and `dd37f9f`'s successor are DOC-ONLY, so `35366756545` is the run that carries every code change of this session; the later run is named here because `6d3a608` set the rule that a row should point at the LAST sha, and a pushed row may not be re-worded to say so |
| `python check_invariants.py --strict` | 2,485 rows · 1,429 active · 0 orphans |
| `python docs/check_docs.py` | 0 errors, 2 warnings (the `1,000+` active-rows floor, not this lane's) |
| mutation records, this session | **0 filed, deliberately.** `631` is open because the catalogue went 391 → 416 in one afternoon and six of eight shards died on the 40-minute wall with zero survivors; `infra` took it to twenty shards in `62eab37` the same evening. Adding records today would spend the headroom that fix just bought. Every new guard was proved to kill instead — `guard_kill` above, plus three hand-aimed mutants (drop `ALIASES["flare"]`; `alias_only_folds` returns `{}`; drop the `Holisto` override), each red on the tests that name it |

Two STANDING tests found the one thing this branch got wrong, and they are worth naming:
`test_no_override_ships_a_name_that_render_would_refuse` and
`test_no_identity_group_merges_two_genuinely_different_companies` both went red because I
committed the export UNSETTLED — I wanted the 09-19 cron to produce the `-3` as an unattended
number. They are right and I was wrong: the committed file is what a reader and a test see, so
the export is carried here already written by its one writer (`--export` from this branch),
and the diff against origin is exactly three keys gone and two display names added, nothing
else. The cron's number is still the morning row.

## What I made harder for the next lane

- `settle_keys` now removes keys for **three** reasons, not two. A record that vanishes from
  the export with no `alias-of` row and no `DISOWNED` entry may be `alias_only_folds`, and the
  only way to see it is to run `settle_keys` — there is still no per-pass log line.
- `alias_only_folds` reads `companies.csv` on the `save_shared` path. `_registry_rows` caches
  on mtime, but a test that monkeypatches `declared_aliases` to `{}` no longer disables the
  whole fold: it must patch `_registry_rows` too, and three tests in
  `tests/test_company_intel.py` now do.
- `ALIASES` gained two entries (`flare`, `trivago`) and `DISPLAY_NAME_OVERRIDES` a sixth. The
  overrides table now contains a key that is NOT an ATS slug, so the sentence "these keys are
  ATS slugs" in the comment above it is no longer the whole truth and the comment says so.
- `Hello Flare` renders as `Flare` and `Holisto` as `Trivago` from tonight. A reader grepping
  the board for a registry name will not find either.
- Three blurbs in `cloud_state/seen.db` are now unreachable or wrong and none is purged:
  `Flare` (the wrong company entirely), `Trivago` (empty) and `DoiT` (a duplicate of
  `doitintl`'s). No arm deletes them and nothing counts them.
