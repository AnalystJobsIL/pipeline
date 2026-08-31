# 2026-08-31 — the dataset's `company` cell shows the evidenced brand; `company_registry` keeps the join key

*lane: `roles` — decided while fixing the five public-dataset defects; supersedes the
additive-only proposal in BACKLOG 504*

## What the operator asked for

> 6 published rows render the company as a URL slug … Make the csv export do the same [as
> the board and mail]: display_name, falling back to the registry name. NEVER rename the
> registry row.

Verification named: "0 slug-shaped company names" — a grep over the `company` column, which
an additive column cannot satisfy.

## Decision

`company` ← `rolecard.display_name(fm, company, firmographics)` (the guarded resolver every
reader surface uses — junk/NFKC/homoglyph filters plus the impersonation guard; never the
raw firmographics field), falling back to the registry name. A new `company_registry` column
directly after it carries the registry name verbatim — the stable join key to
`companies.csv`, `firmographics.json` and the ledger; `role_id` derives from it. 54 → 56
columns (with `description_quality`). The registry row itself is untouched.

**The guard's victim set is the full firmographics union** (~1,300 names), a superset of
the board's morning dict, so the CSV's refusals are a superset of the board's: the two
surfaces can diverge only in the safe direction — the CSV showing the honest slug where the
board shows the brand — never toward an impersonation. Pinned by
`test_a_brand_the_impersonation_guard_refuses_falls_back_to_the_registry_name`.

**And the brand renders only on the EXACT firmographics key** — the same lookup the board
makes (`rolecard._fill` never falls back to `identity_key`). An adversarial wave showed the
first version breaking its own divergence claim through `by_ident`: an identity-matched
record could print a brand the board never renders, making the board no review surface for
it. Identity-matched records still donate their firmo COLUMNS; they never donate a name.
Pinned by `test_the_csv_brand_renders_only_on_the_exact_key_the_board_reads`.

## The contract break, said plainly

The dataset is one day old (`DATASET_SINCE 2026-08-30`); a day-one downloader grouping on
`company` sees values change. Chosen deliberately: the semantics change will never be
cheaper, and the meta documents both columns.

## Rejected

- **Additive `display_name` column, `company` stays the registry name** (504's shape):
  fails the operator's instruction and his verification grep; the one surface still showing
  `withfaye` would be the downloadable dataset — the defect being fixed.
- **`company` ← brand with no registry column**: orphans every join a consumer makes back
  to this repo's files; `role_id` is documented "DO NOT split it", so it cannot serve.

## Residuals, named

`finbounce` stays `finbounce` (guard refusal while a real Bounce AI row exists — its row
leaves as `superseded` via the BACKLOG 488 fix regardless); `comblack` ×2 leave via the
recruiter purge; `entrypoint` has NO display evidence and `DISPLAY_NAME_OVERRIDES`
(company-intel's file) demands first-party evidence, so it stays a slug until company-intel
writes one — filed as `512@company-intel`.
