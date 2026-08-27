# 2026-08-27 — Israeli IT-services employers: the measurement, and why this is NOT decided

*lane: `discovery` (owns `pipeline/recruiters.py`) with `registry`. This record exists
because a new source made the question urgent and then measured it. It deliberately does
**not** answer it — `docs/BACKLOG.md` 321 stays open.*

## Why this came up now

The secrethunter catalog (`docs/decisions/2026-08-27-secrethunter-company-catalog.md`) adds
2,002 Israeli employer names, and IT-services firms are visibly among them. Whatever the
policy on that class is, this source applies it at scale.

**One sentence has been removed from this section.** It said the catalog's *"top 25 by job
count"* was health funds, the police, a hotel chain, a bakery and five named IT-services
firms. Job counts exist only in the `ItemList` on the company pages, which are behind the
crawler-UA gate and were read exactly once (Ness, to size the payload). That ranking could
not have come from any measurement this session made or admits to; it was inherited from the
investigation whose central claim the sibling record spends a section refuting. Unverifiable,
so deleted rather than dressed up — that is this repo's rule.

## The measurement

Against `origin/master` `fbfc83e`, over the 19 Israeli IT-services / outsourcing firms named
in `docs/BACKLOG.md` 321 and in `recruiters._CONFIRMED`. Matching is by exact normalised
handle against the catalog's 2,703 slugs (a substring match, used in a first pass, reported
13 in the catalog and was simply wrong):

| | |
|---|---|
| appear in the catalog | **10 of 19** — Matrix, Aman Group, Directeam, CodeValue, doitintl, AllCloud, Moveo Group, TCM Technologies, TLVTech, Ness Technologies |
| are **ACTIVE rows on the board today** | **13 of 19** rows, covering 12 firms (`Matrix` and `Matrix IT` are two rows for one group) |
| refused by `is_recruiter` | **4 of 19** — MalamTeam, Abra, Log-On Software, Elad Software Systems |
| **of those 4, how many are in the catalog** | **ZERO** |
| of the whole 2,703-name catalog, refused as `agency` | **4 (0.15%)** — and they are a *different* four: Cd Gtm Recruitment, Ginitalent Recruitment Staffing, Moveo Source, Nogamy |

**Read those rows together and the rule's shape is exact: every one of the ten IT-services
firms the catalog actually contains passes `is_recruiter`, and every one it refuses is a firm
the catalog does not have.** The rule and the source do not intersect at all.

It gets sharper. `MalamTeam` — the one entry `_CONFIRMED` was extended for, hyphen variants
and all — appears in this catalog as the slug **`malam`**, and:

```bash
python -c "from pipeline.recruiters import is_recruiter; print(is_recruiter('Matrix',''), is_recruiter('Malam','malam'), is_recruiter('MalamTeam',''))"
# False False True
```

So the catalog will queue **Malam** as a fresh employer, past the very entry written to stop
it. Note also `Abra`: the catalog's `abra-usa` is a US company that happens to share the name
of an Israeli firm on the refusal list — the list was curated against ~1,200 Israeli names and
is now being pointed at 2,703 mixed ones, where its short generic tokens (`abra`, `matchit`,
`nogamy`, `g-stat`, `confidential`) match more loosely than intended.

`_CONFIRMED` describes its entries as *"IT services / outsourcing; re-posts client roles"* —
the same description as the thirteen active rows, with the opposite verdict.

## The finding

**The current rule and this catalog do not intersect, and the rule is not internally
consistent.** The 0.15% is real but it is not evidence of negligence — it is small mostly
because a catalog of 2,703 mixed employers contains few staffing firms. The finding that
matters is the one above it: of the ten IT-services firms the catalog does contain, the rule
refuses none, and `Malam` walks past the entry added for `MalamTeam`. Adding a source does
not make the rule wrong; it makes the inconsistency routine instead of occasional.

## Why it is not decided here

1. **The operator scoped this session to the catalog and the reject ledger**, explicitly not
   to item 321.
2. **Whoever decides must decide the CLASS and apply it to all thirteen at once**, not to
   whichever two a rung happened to add last night. Parking TLVTech and Ness while leaving
   the other eleven active would apply a stricter rule to the newest arrivals than to the
   incumbents — which is how 321 got filed in the first place.
3. **The cost of getting it wrong is asymmetric and already paid once.** This repo has lost
   36 legitimate acquisitions and 358 path-tenant rows to rules tightened without measuring
   the cost. TLVTech's `Data Analyst` is this product's exact target class: on one reading it
   is a real Israeli analyst job, on the other it is a client's role published under the
   wrong employer. That is a product judgement, not a lint rule.
4. It needs the `registry` lane too — the thirteen rows are theirs to move.

## What the next session needs, and now has

- the counts above, each reproducible from the commands in this file;
- the fact that a name's CATALOG SPELLING is what the gate sees: `malam`, not
  `MalamTeam`. Any decision on the class has to be applied to the spellings the
  sources actually emit, which is a third form on top of the Latin/Hebrew pair below;
- `cloud_state/intake_rejects.json`, so that once a rule changes, what it newly refuses is
  recorded by name and appealable instead of vanishing into a count (`docs/BACKLOG.md` 70);
- the note that a Latin entry in `_CONFIRMED` does not cover the Hebrew spelling — `מלם תים`
  had to be added separately for Malam-Team — so any decision on the class costs two entries
  per firm, not one.

**No change was made to `pipeline/recruiters.py` in this session.**
