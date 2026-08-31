# 2026-08-31 — a snippet "description" is MARKED (`description_quality`), never excluded

*lane: `roles` — decided while fixing the five public-dataset defects*

## What the operator asked for

> Smaller and correct beats larger and wrong — a row that cannot be completed is EXCLUDED
> (or explicitly marked) with a stated reason, not published half-empty. Decide the
> policy, write it down, enforce it at export.

## Measured (2026-08-31, the 161-row repo copy)

**11** rows fail `jdfill.looks_like_jd` (8 open, 3 closed; the task brief's 9 undercounted
the two ~160-char Hebrew rows, which fail on length, not on the marker families — the
markers do carry Hebrew), and **2** rows hold no text at all (Bylith open, Taboola closed).

## Decision: MARK — new column `description_quality ∈ {jd, snippet, none}`, empty = unmeasured

- The exclusion classes (`superseded`/`purged`/`withdrawn`) are verdicts about the ROLE.
  These 11 roles are real market observations — company, title, url, dates all stand — and
  excluding 7% of the file to fix a text problem misstates the market, which is the
  "larger and wrong" failure in a different column.
- Exclusion **churns**: `jd-text`'s nightly enrich targets exactly these rows, so an
  excluded open row re-enters the file the day its text fills, and the `removed` list
  machinery is built for permanent verdicts, not oscillation.
- `description_len` already told the truth; the mark makes it explicit and filterable.
  `description_len`/`description_sha1` stay — honest measurements, and the join key.
- Judged **at export**, never stamped on the record: the verdict is rule×content-derived,
  so a `looks_like_jd` change re-judges every row on the next export instead of stranding
  169 stale stamps. The run's own in-memory description (reconciled by `open_sync`,
  sqlite-sourced on a frozen-text day) is judged FIRST; the disk `roles_text.jsonl`
  (sha1-matched, and an empty sha1 is never a wildcard) is the CLI's fallback — an
  adversarial wave showed the disk-only version silently killing the column for 159 of 161
  rows on a stale-but-well-formed dump while the mail's `weak text` number IMPROVED. A row
  that can't be judged leaves the cell empty — "could not measure", never a guess — and any
  unmeasured count now rides the mail line (`text unmeasured N`) plus a Stages alarm.
- Closed rows: same treatment (their quality is final; the column says what we hold).
- Surfaces: the meta's `description_text.quality` counts with their own identity
  (`jd+snippet+none+unmeasured == rows`), and the mail's dataset line gains
  `· weak text N (S snippet, K none)` while any remain — the daily number `jd-text` drains.

## Rejected

- **Exclude open rows failing `looks_like_jd`** (a fourth excluded class): see churn and
  market-misstatement above; also leaves the classifier and board publishing roles the
  dataset denies, a cross-surface disagreement nothing reconciles.
- **Blank `description_len`/`sha1` on snippet rows**: hides a real measurement and breaks
  the documented join for exactly the rows a reader most needs to inspect.

The enum doc claims only "fails the test" — `looks_like_jd` can fail a genuinely terse real
ad (its own docstring records a 394-char remainder judged correctly-False), so `snippet`
must never be read as "not a posting".


## Addendum, 2026-08-31 evening — the WHY beside the mark, and the policy made flippable

`description_blocker` closes the loop this record opened: a snippet/none row now says WHY
it is structurally hard to complete, or says nothing. Contract agreed live with `jd-text`
(both sessions, via SendMessage): a recorded `matched.jd_why` verdict of `structural:*`
(donors exhausted) ships VERBATIM and beats the derived reasons (`gone` from the
GONE_MARK stamp; `unfillable:<why>`; `listing-page` for a non-aggregator canonical whose
posting key is empty). The mark is gated on the text actually FAILING — a `gone` posting
that gained a donor copy carries no blocker, because GONE_MARK judges the ADDRESS.

The MARK-never-exclude decision above stands tonight, and is now ONE constant instead of
a shape: `roles.BLOCKED_POLICY = "mark"`. The exclude branch is built, pinned, and keeps
every meta identity whole (a removed row's reason stays counted;
`reconciliation` gains `blocked_excluded`) — so the operator's row-by-row audit can flip
the policy without touching the derivation, per the orchestrator's condition. The meta's
`description_text.blocked` block names the live policy beside the counts.
