# 2026-08-30 company-intel (b) — the employer's own name, as a field

The operator read the board and saw `withfaye` where the employer is Faye. 8 of 161
published rows carried a slug-or-Hebrew company name: `withfaye`, `helfy`, `finbounce`,
`comblack` ×2, `entrypoint` genuinely wrong; `אסם` and `מטריקס` are the employers' real
names and are excluded from the count on purpose. `cloud_state/firmographics.json` had no
name-like field anywhere — the real name existed only as prose inside blurbs.

## 1. The contract (agreed live with the render session, cross-session messages)

`display_name`: optional top-level string on a firmographics record, same tier as
`sector`. The employer's public brand name as written; no legal suffix, no tagline;
absent entirely when unevidenced — never the slug echoed back, never an empty string.
The registry key never changes (it joins this file, the roles ledger and the public CSV —
459's rename sequencing is exactly what this field avoids). Render shows it over the
registry name when present; their side resolves through `enrich_for_run`'s firmo_display
(exact key then `identity_key`), which also covers the `helfy`/`Helfy` case-twin in
roles.csv. Render's identity guard refuses at source any display_name whose
`identity_key` belongs to a different company — so `finbounce` renders `finbounce`
everywhere until `487@registry` parks the duplicate row, with no mail line. That is
correct: the record carries the true fact ("Bounce AI"), the guard owns the display
consequence.

## 2. What shipped

- `pipeline/firmographics.py`: `display_name_from_evidence` (the rule),
  `apply_display_names` (the single writer), `DISPLAY_NAME_OVERRIDES` (4 rows),
  `fold_sectors`, `_EVIDENCE_EXEMPT`, and `_coerce` lower-casing `sector`.
- `research_firmographics.py`: the pass runs in `--export` after the superset guard and
  before both writes; `--display-report` prints the full write/absent/report triage;
  the export prints `display_names=N (+A/-R) divergent=D sectors_folded=S`.
- `cloud_state/firmographics.json` materialized in the same commit.
- 8 guards in `tests/test_company_intel.py`, all KILLS under `tools/guard_kill.py`.

**Evidence arms, and only these.** (1) `cloud_state/board_verify.json`'s `employer_named`
— an LLM's read of the company's OWN careers page, quote-required, `verdict == "ok"` only
— accepted only when `display_name_from_evidence` judges the page's name recognisably the
SAME company: shared stem (`identity_key` over an NFKD accent-fold, squashed), containment
either way (brand-shorter `Faye` ⊂ `withfaye`; registry-shorter allowed to add ≤ 1 word),
or acronym. (2) The override table, each row carrying first-party evidence in its comment:
`withfaye→Faye`, `helfy→Helfy`, `comblack→Comblack` (each self-names in its own JD text,
`cloud_state/roles_text.jsonl`), `finbounce→Bounce AI` (same Comeet tenant E9.00C as the
active Bounce AI row). A page naming a DIFFERENT string — parent, product, mis-read — is
reported, never written: a confidently wrong name is worse than a slug.

**Counts, measured at the fold (re-derive with `--display-report`):** 908 verify rows →
559 ok+named → 341 resolve to a record (267 have no record yet — the pass self-heals as
coverage and research grow) → after wave 1a's cuts (§3b) **72 written · 55 reported ·
the rest absent** (identical / all-caps styling / casing-not-richer). The first cut wrote
104; the audit removed 32, and the SAME pass retracted them — the clear-on-no-evidence
semantics doing exactly its job on its first day. Sector case-fold: **565** records
changed; 0 mixed-case sectors remain.

## 3. Three behaviours the tests pin, and why

1. **Set AND clear.** `merge` fills the winner's empties from the loser, so a wrong
   display_name could never be retracted by re-research (render's wave found this). The
   pass is authoritative at export: evidence withdrawn → field withdrawn next run. An
   unreadable verify (`load` → `{}`) applies overrides only and clears NOTHING — a corrupt
   read must never become a destructive write.
2. **`_EVIDENCE_EXEMPT`.** `_evidence` feeds `newer()` ties, `merge` winners and
   `display_index` rank; a record gaining a cosmetic key must not switch which record
   answers for an identity group (the AWS-over-Amazon class, already in the module's own
   docstring).
3. **Never from the model.** `_coerce` drops the key; `_RESEARCH_SCHEMA` forbids it.
   Research cannot smuggle a name in; only evidence writes it.

**The join surprise (not in any plan):** `board_verify` keys its rows by a LOWERCASED
name; the store is keyed by the cased registry string. Only 27 of 863 verify names match a
record exactly; 313 more match case-insensitively. The pass resolves through a lowercase
index and judges the REAL registry key — without that, every case-only difference reads
as a "fix" (an early un-resolved run wrote 436 names, 4× too many). An ambiguous
lowercase twin is skipped, never guessed.

## 3b. Wave 1a — an opus audit of all 104 written names found 13 defect classes

The audit read every written pair against its verify record and `companies.csv`. Confirmed
and fixed the same evening, each with a rule and a pinned test
(`test_wave1a_defect_classes_are_refused_parent_casing_israel_and_collisions`):

- **Parent/umbrella substitution** (`Yael Korentec Technologies`→`Yael Group` — a
  staffing-agency parent; `Ultra Clean Technology`→`Ultra Clean Holdings`; `HSBC Group`):
  `identity_key` strips `group/technologies/israel`, so the parent stems equal to the
  subsidiary. Fix: an umbrella word the registry name does not carry → `report`.
- **Identity collision** (`Trigo Retail`→`Trigo` beside the ACTIVE French `Trigo` row —
  the wrong-company class; `kelasys`→`Kela Technologies` beside `KELA`; plus
  `Atera Networks`→`Atera`, `brightdata`→`Bright Data`, `Alice IO`→`Alice`, same employer
  but a byte-identical name on two rows): a derived name whose `identity_key` is another
  record's is refused as `identity-collision(<row>)`. Genuine improvements lost to this
  (`brightdata`) come back when `registry` collapses the duplicate rows — that is 487's
  class, not a display fix.
- **Casing degradation** (`KELA`→`Kela`, `Onebeat`→`onebeat`, `RealPlay`→`Realplay`):
  same letters must now be a strict casing ENRICHMENT (`Abbvie`→`AbbVie` still writes).
- **The parenthetical held the brand** (`Riverside.fm` ← `RiversideFM, Inc.
  (Riverside.fm)`): a parenthetical squash-equal to the registry name is a vote FOR it.
- **`X Israel`→`X` inversion** (`Publicis Groupe Israel`→`Publicis Groupe`): absent.
- **Digits defeated the all-caps guard** (`GROUP19`: 5 alpha chars): digits now count.

Clean under attack: zero Hebrew leakage, zero domain-shaped writes, all 4 overrides
verified against their evidence, and the report bucket's direction of error is right (it
correctly held `QuantLR`←`HEQA Security`, `UserWay`←`Level Access`, `Outbrain`←`Teads`).

## 4. The 8 rows, one by one

| row | display_name | evidence |
|---|---|---|
| `withfaye` | `Faye` | JD self-naming + bv-ok row (extractor derives it too) |
| `helfy` | `Helfy` | JD self-naming (no bv row → override) |
| `comblack` ×2 | `Comblack` | JD self-naming (no bv row → override) |
| `finbounce` | `Bounce AI` | Comeet tenant E9.00C = Bounce AI's; renders only after 487 |
| `entrypoint` | ABSENT | contested — board names Entry Point USA (wrong-url 2026-08-30) |
| `אסם`, `מטריקס` | ABSENT | the key IS the employer's name; excluded from the count |

`Migdal Group` (the "incomplete" class, 2 rows, not slug-shaped): its verify row EXISTS
and the page self-names `מגדל חברה לביטוח (קבוצת מגדל)` — Hebrew, so the honest verdict
is report, not write. The bounded answer for this whole class is board_verify itself:
coverage grows on its cadence, the pass picks up every new ok row at the next `--export`,
zero marginal cost. Reading all ~1,097 active rows' sites in one pass was rejected
(~1,097 page reads for a class the existing cadence already drains).

## 5. Raised, not decided (504) + leads (503)

**504**: which language should an employer's name render in? Two mirror classes: the two
Hebrew-keyed published rows on an English-facing board, and ~24 divergent rows whose own
page self-names in Hebrew (`Discount Bank` ← `בנק דיסקונט`, `Migdal Group`, `Isracard`…).
`display_name` writes neither direction; if decided, it is a separate field. **503**: 8
verified boards name a different employer (`Outbrain`←`Teads`, `UserWay`←`Level Access`,
`QuantLR`←`HEQA Security`…) — rename/acquisition leads for `registry`.

## 6. Rejected designs

- **display_name in the research schema** — a web-searched name is a guess, not evidence;
  the brief's rule, kept absolute (`_coerce` drops the key; a guard pins it).
- **`display_name_source` companion key** — one writer, two arms in one function;
  `employees_source` earns its keep arbitrating multiple writers, this wouldn't.
- **Renaming registry rows** — orphans intel + role history (459); the field IS the fix.
- **Direct JSON edits for the 4 slug rows** — the pass's clear-when-underived semantics
  would delete them on the first export; the override table survives every re-export.
- **Writing the divergent pile** (operator's call): 43 held back; the sample above shows
  why — parents, products, Hebrew self-namings, mis-reads mixed with genuine improvements.

## 7. Spend

Bright Data 0 (evidence already committed; no page read was needed — even Migdal's answer
was already in board_verify). Claude LLM calls 0. SerpApi 0. `companies.csv` untouched.

## 8. Verification

Local from the worktree at `deb030c`: lane suite 148 passed; `tools/guard_kill.py --base
origin/master` → 7 of 7 KILLS; full gates + CI verdict recorded in HANDOFF.md's line and
the morning-check row due 2026-09-01 (`display_names=104 (+0/-0) divergent=43
sectors_folded=0` expected in the unattended `firmo_drain` log — the delivery-bar proof).
The pass is idempotent: a second `--export` produced a byte-identical file.
