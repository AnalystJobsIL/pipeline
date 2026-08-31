# 2026-08-31 — the description text ships as roles_text.jsonl, not a roles_full.csv

*lane: `roles` — decided while fixing the five public-dataset defects (session
`docs/sessions/2026-08-31-roles.md`)*

## What the operator asked for

> The operator wants the text itself, to analyse. Do NOT add a prose column to the
> daily-diffed roles.csv — it is committed every run and the git history becomes
> unclonable. Ship a second artefact published beside it (e.g. roles_full.csv,
> regenerated wholesale each publish), or an equivalent — consider alternatives and pick.

## The question

The text already exists in `cloud_state/roles_text.jsonl` (573,923 bytes, 169 records,
keyed by `role_id` — the CSV's own documented join key). What reaches the reader, and at
what history cost?

## Decision: publish `roles_text.jsonl` itself beside the CSV (backlog `498@infra`)

The file is already committed daily and **changes only when a description changes**, so its
history cost is already paid; the Pages copy is one line in infra's publish loop, and the
meta names the copy the day `ROLES_TEXT_PAGES_URL` is set (`published_on_pages`, mirroring
the CSV's own flag). Until infra applies 498, the text is still reachable from the published
artefact set: the meta's `description_text.raw_url` points at the raw GitHub address of a
public repo. The analyst's cost is one `pandas.merge` on `role_id`
(`pd.read_csv` + `pd.read_json(lines=True)`), documented in the meta's
`description_text.join`.

## Rejected, with the numbers

- **A committed `roles_full.csv`** (join of csv+text, ~700 KB): `write_dataset` sorts by
  `role_id` and every open row's `last_seen` moves daily, so nearly every line re-diffs
  every day — each now dragging up to 6,000 chars of prose into the delta. That is the
  exact "git history unshrinkable" cost the operator forbade for a prose column, wearing a
  second filename.
- **An uncommitted, Pages-only `roles_full.csv`**: needs a `.gitignore` edit, has no
  `raw_url` (breaking the meta's "raw_url is always true" convention), can silently drift
  from `roles_text.jsonl`, still needs the same infra copy-loop line — all to save the one
  merge.
- **Both**: the second artefact's cost for no added reach.

Not automatic until `infra` applies 498's diff (the copy loop, the `git add` loop, the two
env names, the `persist_state.SINGLE_WRITER` entries — the item carries the exact lines).
