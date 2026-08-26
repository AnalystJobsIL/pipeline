# 2026-08-26 — the jd-text layer spends no Claude tokens

*lane: `jd-text`. Spec: `ARCHITECTURE.md` §7a. Session: `docs/sessions/2026-08-26-jd-text.md`.*

## The question

Every other lane that extracts something from a page has an LLM tier: the scraper's strategy 5
(sonnet, on the densest jobs section), the classifier's ambiguous residue, the registry's page
judge, company-intel's blurbs. The `jd-text` layer has none — `pipeline/jdfill.py` is bare
`urllib` and neither driver spawns `claude`. Is that an oversight?

## What was measured

The layer's whole failure surface on 2026-08-26 (cloud run `32934864207`) was **38 inline
fetches and 3 backfill failures**. Split by what an LLM could possibly do about it:

| class | count | what the page actually contains | could a model help? |
|---|---|---|---|
| `discovery-indeed http-401` | 17 | **nothing** — 401/403 on 22 of 22 URLs sampled, `reject_authwall` to the Unlocker | no: there is no text to read |
| `discovery-telegram no-markers` | 5 | a byte-identical 33,495-byte JS shell (776 chars of text) for every job id (`secrethunter.io`) | no |
| `scrape shell` (Shopify) | 5 | 267 KB of HTML yielding **56 characters** of text, and no JSON-LD | no: nothing to read without a renderer |
| `scrape no-markers` | 5 | listing pages and a search page | no: they are not job pages |
| `discovery-linkedin no-markers` | 5 | a real page whose JD our two-marker heuristic refused | **it would have helped** — but so did a free parser |
| `scrape http-400` | 1 | a broken address | no |

Only the fifth row was a case where a page held a job description and we failed to extract it.
On the 25 LinkedIn bodies captured that morning the marker heuristic was right 23 times; one of the two misses (Mobileye,
9,833 characters of page text and a single marker family) carried its description in a
`<script type="application/ld+json">` `JobPosting` block that `html_to_text` deletes before
anything else looks at it.

So the choice was **a model call or a 30-line deterministic parser**, on the same input.

## The decision

**A JSON-LD parser, not an LLM.** Reasons, in the order that decided it:

1. **It is free and it is exact.** `@type: JobPosting` is a declaration by the page itself
   that this text is the job description. There is nothing to infer, so there is nothing to
   get wrong. Measured over a 62-page corpus captured that morning: **1 gained, 0 lost, 61
   unchanged.**
2. **The residue after it is not LLM-shaped.** What remains is the Shopify class, where the
   page yields 56 characters. A model cannot read what was never sent; that needs the
   `scraper` lane's Chromium rung (`docs/BACKLOG.md` 262).
3. **The blast radius of a wrong answer is larger here than anywhere else in the pipeline.**
   This text lands in `matched.description` and the role ledger, where it drives the
   classifier's accept/reject verdict, the years-of-experience figure, the skills, the family
   and every tag on a published board card. A plausible invented paragraph would not look
   wrong in the mail — it would look like a job. The classifier's LLM tier returns a *verdict*
   that a human can sanity-check against a title; this layer would be returning the *evidence*.
4. **Cost, for completeness.** ~15 candidate pages a day at the scraper lane's measured sonnet
   price (~$0.026/call) is ~$0.39/day, against a shared `CLAUDE_CODE_OAUTH_TOKEN` with four
   consumers — to recover text a free parser already recovers.

## What would reopen it

A measurement, not an opinion. Any of:

* `scrape_why` in the daily stamp (added this session) shows `no-markers` growing into a
  double-digit daily class **after** the JSON-LD parser, i.e. real JDs on pages that declare
  nothing — the number to watch is in the mail's `Stage order:` line every morning.
* The `scraper` lane's renderer lands and the Shopify class becomes pages with real text that
  our parsers still cannot segment.
* A platform appears whose job pages carry the description in prose with no section headings
  at all, in numbers (3+ registry rows, the same bar `docs/BACKLOG.md` 113 uses for a fetcher).

## Rejected alternatives, and why

* **Relaxing `extract_jd`'s two-marker rule to one.** Cheapest of all, and wrong: the rule
  exists because a careers page's nav and footer boilerplate ("experience", "full-time")
  trivially clears one marker, and the text it would then store is junk that reads like a job.
  The 08-24 mutation sweep already pinned `requirement`/`requirements` counting as one family
  for exactly this reason.
* **Making `no-markers` a `transient` failure so it retries daily.** Proposed by one of this
  session's audits. Rejected: a page we successfully read and that carried no JD is a
  *definitive* read, and flipping it would re-fetch ~15 pages every morning for ever. The
  honest fix for "our gate refused a real JD" is to make it **visible** (`*_why` in the stamp)
  and to add a parser that does not need the gate — both of which this session did.
* **An LLM only on the Bright Data body** (the credit is already spent, so the marginal cost
  is just tokens). Same objection as (3) above, and the JSON-LD parser now runs on that body
  too — which is where it pays best: two of the three credits spent on 08-26 ended in
  `bd-no-markers`.
