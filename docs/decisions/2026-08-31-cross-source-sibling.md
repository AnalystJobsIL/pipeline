# 2026-08-31 (evening) — a role's other copies of itself become fillable, on role-level identity

*lane: `jd-text`. Session record: `docs/sessions/2026-08-31-jd-text-b.md`.*

## The decision

When a role's canonical address yields no job description — a listing page with no posting on
it, a 404 at the employer's own board, a JS shell — the driver now asks **the other copies of
that same role** (`enrich_matched_jd._donor_pass`). Four donor classes, cheapest first:

| class | where it comes from | why it is that role's |
|---|---|---|
| `own-address` | a link on the employer's OWN listing page (`jdfill.role_addresses_on`) | the page names this posting by its own id (Bylith's `seen_ids` say `scrape:36`; the page links `/careers/position/36`) or spells out its title (G Stat's `/jobs/אנליסט-ית-דיגיטל/`) |
| `cache` | a `scraped_cache.json` card whose `store.merge_key` IS this row's | merge_key is the repo's own answer to "is this the same role" |
| `copy` | a LinkedIn/Indeed copy this role's `seen_ids` name (`jdfill.source_copy_url`) | **only** when the FETCHED DOCUMENT declares itself to be this title at this employer |
| `archive` | a Wayback snapshot of the role's own url (`jdfill.wayback_snapshot`) | it is a snapshot OF this role's address |

It reaches rows `run_backfill` never walks — `gone`-terminal and archived — because the
backfill is age-blind by the operator's rule. Archived rows stay free-only unless
`--archived-bd`, so the 2026-08-26 lesson (a closed Taboola row bought a credit at 118 % of
the pool) is untouched.

**The measurement: 7 published rows with no usable description → 1**, six filled — four of
them for **0 credits** — and the seventh carrying a written reason. Two credits spent.

| row | outcome |
|---|---|
| `bylith\|product analyst` | `ok:own-address:www.bylith.com` — 2,117 chars, free |
| `g stat\|אנליסט ית דיגיטל` | `ok:own-address:g-stat.com` — 505 chars, free |
| `questar auto\|senior data scientist…` | `ok:cache:questar.applytojob.com` — 5,999 chars, free |
| `mobileye\|experienced data analyst` | `ok:copy:www.linkedin.com` — 2,345 chars, free, on a row `gone` ×3 |
| `oak\|product analyst` | `ok:canonical:il.indeed.com` — 3,685 chars, 1 credit (the cap, not the rung) |
| `diageo\|performance analytics analyst` | `ok:canonical:il.indeed.com` — 6,000 chars, 1 credit |
| `taboola\|product analyst maternity…` | `structural:gone(donors:0)` — 404 at its own Greenhouse board, and **no LinkedIn or Indeed copy was ever held**: `sources` is `["greenhouse"]` alone, `discovered_cache.json` has no entry for the role, no `scraped_cache` key, and the Wayback CDX has no snapshot of the posting or of the board url |

## The property this is arranged around

**Enumeration may be generous; admission may not be.** Text attached to a role on a weak
address heuristic is text laundered under our own name — the defect the `roles` lane measured
in `store.merge_duplicates` on the same day, where an unrestricted donor handed our board url
to a competitor's card, "laundering its JD under our own address, the one shape `names_in_url`
then reads as clean".

So the three structural classes identify themselves by construction, and the one class fetched
at somebody else's address (`copy`) is admitted only on the document's **own declaration**
(`declared_identity` → `doc_names_role`): two of the title's significant words and one of the
company's, read from an Indeed pane keyed to our own `jk` or from a page's `<title>`/
`og:title`. Both halves are load-bearing and each has a scar behind it — the role half alone
put 2,406 characters of Percepto's Data Insights Operations posting on its Senior Product
Analyst row; the employer half alone is what `store._same_origin` refuses by measurement
("it would have published Fetcherr's JD and apply link under Bright Data's name").

The live counterexample this was tested against: Diageo's own discovery cache holds a **second**
Indeed jk (`8eec28efd124a6d2`) whose pane is "VP, Brands in Culture, NAM" — a different role at
the right employer. Company-level jk membership would have laundered it onto the analyst row.

## Alternatives rejected, each on a number

| alternative | the number that killed it |
|---|---|
| donate across `merge_key`s (Oak's own twin `oak identity security os\|product analyst` carries a passing 3,735-char JD) | that binds on company-NAME similarity, which is the Bounce/Bounce-AI and 5-company-fanout shape (`370`); filed to `roles`/`registry` as an identity defect instead — the two rows are one posting and the merge is theirs to make |
| trust the discovery card's `company`/`title` claim | it is a claim, not evidence (rule 5): אסם and Nestlé are ONE posting under two employer names, and Diageo's other jk is a different role |
| `roles.names_in_url` as the cross-source gate | `store._same_origin`'s own docstring rejects it BY MEASUREMENT as an admission gate on foreign content |
| byte-identity as an admission signal | that is the fanout SYMPTOM (`370`: `otorio\|senior data analyst` byte-identical to the Armis row), and `_quality_pass` already alarms on it the morning after |
| an unrestricted fetch-the-siblings pass | measured at zero yield by wave 1 on 2026-08-26; this rung fetches only addresses bound to the role |
| `slug_names_title` for the listing-page match | it allows one slug word to miss, and the word that misses is the discriminating one: `אנליסט/ית דיגיטל` matched three G Stat siblings (digital, credit, economist) |
| picking the first of several equal title matches | a coin flip publishes another opening's text; an ambiguous match now yields NOTHING |

## Two defects found while building it, both fixed here

1. **`_SLUG_WORD` was `[a-z0-9]+`**, so every slug rule in `jdfill` answered False for a Hebrew
   posting by construction — and half of what this board publishes is Hebrew. Widened to
   include Hebrew; measured over all 4,379 (url, title) pairs the caches hold: `is_job_url`
   changes on **0**, `title_in_slug` gains exactly **3**, each a url that really does spell out
   its own card's title.
2. **`urllib` raises `UnicodeEncodeError` on a non-ASCII URL** before a packet leaves, and
   `plain_fetch`'s catch-all turned that into the same silent `(None, "")` a timeout gives — so
   every Hebrew address this repo holds was unfetchable AND indistinguishable from a network
   failure. `jdfill.wire_url` now encodes at the point of the request: byte-identical on all
   1,607 ASCII cache urls, idempotent, and it changed the 3 Hebrew ones from "unfetchable" to
   fetchable. G Stat's fill is 505 characters that were unreachable by construction before it.

Also corrected: `_after_the_wall` opened its candidate at a sign-in mark's END, and the mark is
where the wall's last SENTENCE begins — Mobileye's fill carried 97 characters of "you agree to
LinkedIn's User Agreement , Privacy Policy , and Cookie Policy ." as the first line of its
description. The candidate now opens after that line, falling back to the raw offset for a
posting that begins on the mark's own line. The morning's two wall-first recoveries are
unchanged (Ashley 2,395, Questar 4,931) and activations over the stored corpus stay at 0.

## The reason, and who reads it

`matched.jd_why` (new column, added by `_ensure_columns` the way `jd_tries` was) records
`ok:<class>:<host>`, `refused:identity(N)` or `structural:<reason>(donors:N)`. This is
`jd-text`'s half of `443`: until now the reason a fill failed lived only inside the run, so the
morning after, a row refused for `not-a-job-url` was indistinguishable from one refused for
`auth-walled`. A `structural:` value may only be written once **every** donor class has
actually been enumerated — it is a statement about the world, not about a budget — and the
`roles` lane reads it verbatim into the published dataset's `description_blocker` column
(contract agreed with that lane's session on 2026-08-31: `ok:`/`refused:` are never blockers,
a row whose text passes `looks_like_jd` never carries one, and MARK-never-exclude stands per
`2026-08-31-snippet-rows.md`).
