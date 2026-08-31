# 2026-08-31 — the identity fold lands at INTAKE + a ledger sweep, and `merge_key` does not move

**Context.** Backlog 533: run 33387229779 judged `NVIDIA | Senior Business Intelligence
Analyst` and `NVIDIA AI | …` thirteen seconds apart — two LLM calls, two records, two
board cards, both emailed, one employer. The class behind it is the lane's oldest debt:
`store.merge_key` folds the raw company string, so alias name-forms double-list. The
operator's standing correction: close the CLASS, evidence-driven, with Faye/withfaye and
NVIDIA/NVIDIA AI folding while Bounce/Bounce AI (two real companies, the 489 lesson)
never do.

**Decision.** Canonicalize the company STRING where it enters the role record —
`roles.fold_company_aliases` on the candidate list before `classify_grouped`, plus
`Ledger.fold_aliases` over the stored records — and leave `merge_key` untouched.
`roles._alias_fold_target` is the single gate both use:

- refuse any REGISTRY name, active or parked (Bounce and Bounce AI are both rows; a
  parked `Meta Israel` keeps its historical string);
- require `identity_key(C) == identity_key(R)` with exactly ONE active match (11
  same-identity groups of active rows — Amazon/AWS class — fold onto neither);
- then ONE evidence gate: casefold-only difference | a curated `firmographics.ALIASES`
  declaration (tested against the plain-normalized name, never the stripped stem) | the
  posting's address passing `store._same_origin` against R's board.

Sweep semantics: casefold twin ⇒ field repair (role_id unchanged — `_norm` lowercases);
twin under the canonical key ⇒ supersede with seen_ids + `sent` mirror unioned (nothing
re-emailed); foldable with no twin ⇒ LEFT, counted and named on the mail.

**Measured on the committed store before shipping** (193 records, 1,100 active rows):
7 candidates — Appcharge→AppCharge, GE HEALTHCARE→GE HealthCare, Helfy→helfy (casefold,
key-preserving), NVIDIA AI→NVIDIA (declared; same-title twin ⇒ supersede); refused: Meta
Israel, SolarEdge Technologies, TechBiz Global GmbH (all parked registry rows); 0
ambiguous, 0 foldable-with-no-twin. Store identity groups were **3, not the ~13 the
spawn brief carried** — 13 was BACKLOG 133's REGISTRY figure, which re-derives today as
0 groups by `api_url` and 11 same-identity-different-board.

## Rejected, with the killing number

1. **Migrate `merge_key` onto `identity_key`** (HANDOFF watch item 1, BACKLOG 132–139's
   framing). A primary key must be a pure function of the row, and a pure function has
   nowhere to put an evidence gate: `identity_key("AppSec Labs") ==
   identity_key("AppSec")` and those were two employers (BACKLOG 144) — the migration
   folds them with zero evidence. It also re-keys all 193 role_ids (`roles_text.jsonl`
   joins on role_id; `LedgerShrink` reads a rename as a drop; episode/`first_seen`
   semantics churn).
2. **Fold only at `resolve_claims`.** The 533 pair shares no seen_id, no url, and both
   `_posting_key`s are `''` (aggregators) — 0 of `_groups`' three evidence buckets
   intersect, so the claim guard cannot even SEE the pair; and the two LLM calls happen
   earlier, in `classify_grouped`.
3. **Fold only at render/export.** Two records, two calls, two emails remain; render's
   `title-twin NVIDIA/NVIDIA AI` warning existed on 2026-08-31 and prevented nothing.
4. **Detect declarations via `identity_key(C) in ALIASES.values()`.**
   `identity_key("NVIDIA Labs")` is `nvidia` (suffix strip), which IS an alias value —
   the test folds an undeclared name. The shipped test matches the alias KEY against the
   plain normalization (`_plain_norm("NVIDIA Labs")` = `nvidia labs`, not a key ⇒
   refused), and a pinned test holds every alias key a fixed point of `_plain_norm`.
   Conservative miss accepted: an alias key that is a post-strip stem differing from the
   raw form is refused — a miss costs today's behavior, never a wrong fold.
5. **A `firmographics.identity_stem` seam** (exposing the pre-ALIASES stem). Not needed
   once (4)'s key-vs-stem test existed; `ALIASES` is imported read-only, precedent
   `roles.py` importing `identity_key`. company-intel notified that `ALIASES` is now
   also a role-record declaration table.

## What stays unsolved, stated

- **Faye/withfaye is NOT this mechanism** and must not become it: the registry key
  `withfaye` deliberately cannot change (firmographics.py:880-894 — it joins intel, the
  ledger and the CSV), and the brand renders via `display_name`. Nothing to fold.
- The Amazon/AWS-class same-identity ACTIVE pairs stay separate rows by design; their
  posting-level overlaps remain `same_posting`'s job.
- A foldable record with no twin keeps its historical role_id (measured empty today).
- The classifier cache pays at most one re-judge per folded name on its first post-fold
  sighting (the NVIDIA pair's canonical key was already warm: 0 extra).
- `firmo_match=identity` inheritance for showcase names (NVIDIA AI would have inherited
  NVIDIA's 42,000 headcount on the next digest) is mooted by the supersede, not fixed as
  a class — an identity-matched record still donates firmo columns to a LIVE row.

The same-company twin collapse (`same_role_twin`, the seen-id collision repair) shipped
in the same commit and is documented in `ARCHITECTURE.md` §7c beside the id_collisions
alarm; its evidence bar and refusals (junior/senior absolute, weak-id demotion at ≥3
records, tie ⇒ refuse) were chosen against the enumerated 13 colliding seen_ids —
HoneyBook and Fetcherr fold at run time, Modellama at the sweep, Guardio and Percepto
stay two records as the accepted cost of never folding two real openings.

lane: `roles`. Session record: `docs/sessions/2026-08-31-roles-b.md`.


## Post-wave amendments (same evening, before the push)

Two Opus waves attacked the committed draft (`f703726`); every reproduced finding was
fixed and pinned before anything left the branch. The design above changed in three ways:

1. **Gate (iii) — board corroboration — is DELETED**, not shipped: `_same_origin`'s
   tenant branch never checks the host, so `_same_origin(<Bounce AI's comeet posting>,
   'Bounce')` is True and every suffix-strip variant (`Bounce Labs`, `Bounce Ltd`,
   `Bounce Israel`) folded onto the OTHER employer — board-authoritative and free to
   donate its url and text. Measured against it: **0 live folds bought** (of 2,355
   stored urls), 7 urls passing `_same_origin` against a foreign active row. The gate's
   seam stays in the signature; an empty identity_key is also refused outright.
2. **`same_role_twin`'s arms were rebuilt on the wave's population**: the bare
   identical-pk arm folded 7 genuinely different live pairs (the scraper's href ladder
   binds several cards to one url — 85 `(company,url)` pairs carry 2+ titles), and the
   bare >=2-ids arm counted two url-fallback `scrape:` sids as two witnesses (the Nift
   sidebar-junk shape). Now: two shared PLATFORM-ISSUED id spaces, or plain
   `same_posting` (its four-guard bypass restored). `_PLACE_WORDS` gained the schedule
   furniture (`full`/`part`/`time`) so the real Modellama twin still folds.
3. **Cycle and reclaim locks**: the run-time arm skips a group holding an
   already-superseded member and `_supersede` follows the winner's chain, refusing one
   that leads back (the two arms' winner rules can disagree — the reproduced cycle took
   both halves off every product with `ledger N = store N` green); a same-company
   superseded record never reclaims itself; the compound alias+retitle twin folds at the
   ledger via `same_role_twin` over the canonical company's records.
