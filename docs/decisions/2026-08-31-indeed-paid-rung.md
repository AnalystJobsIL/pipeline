# 2026-08-31 — Indeed becomes `paid_only`, and the marker bar learns the requirement idioms

*lane: `jd-text`. Session record: `docs/sessions/2026-08-31-jd-text.md`.*

## The decision

`indeed.com` leaves `_UNFILLABLE` and becomes the first **`paid_only`** host: the free
rungs keep their `auth-walled` verdict and the plain GET is still never spent, but
`fetch_jd`'s paid rung buys the ONE address a parser of ours can read —
`il.indeed.com/jobs?q=a&l=Israel&vjk=<jk>`, whose `window._initialData` embeds the full
viewjob response keyed by `jobKey`. One raw credit per posting, no render.

The measurement that decided it: **90 of the 92 cached Indeed postings filled with 300+
characters passing `looks_like_jd`** — 76 of the 78 still live at source, plus all 14
EXPIRED postings, whose pane still answers with the text (and an archived role's
description is still this lane's mandate). The residue: 1 marker-poor, 1 fetch error,
**0 auth-walls**. The two rows the operator named as the irreducible wins, TransUnion
(jk `7349c47d967eb4a7`, 6,670 chars) and אסם (`a7cd257b81d9ba1d`, 971 chars), both filled
in the sample round.

## Why the old verdict fell

The 2026-08-26 entry rested on 401/403 to 22 of 22 free GETs and `reject_authwall` from the
Unlocker — measured **three days before render support existed**, and never against the
SERP two-pane form, the `www.` host, or the dataset. The wall is real but narrower than the
entry claimed: only the `viewjob` page is closed.

## Alternatives rejected, each on a number

| alternative | the number that killed it |
|---|---|
| keep the `_UNFILLABLE` entry, bypass it inside `fetch_jd` when `bd` is armed | all three drivers refuse via `unfillable()` BEFORE `fetch_jd` runs, so the bypass is dead code from every caller; and refusals are never stamped, so the 92-card backlog would re-spend at full cap nightly with no 7/14/28 backoff |
| an "indeed" platform in `native_jd` / `_READERS` | that seam is free-only (`plain_fetch`, jdfill.py `native_jd`) and the page answers it 401/403; a paid fetch there reshapes the shared native path for every platform |
| the BD Indeed **dataset** (`gd_l4dx9j9sscpvs7no2`) | `discover_new` mode: five straight days of `dataset_size: 0` (rate-limited by Indeed), the documented do-not-re-enable; collect-by-URL was held as the fallback and never needed — the SERP form filled 5/5 first |
| rendered `viewjob` (the untried form the render discovery suggested) | not reached: E1 (raw SERP) hit the 4-of-5 promotion bar before E2 spent a credit; raw is also 1 credit vs 2 and off the 45 s render clock |
| letting `extract_jd`/`jsonld_jd` read the bought SERP as a fallback | `extract_jd` returned the SAME 3,028 characters of page furniture for three different jks (identity check 0/5), and a JobPosting ld+json on a SERP is some other job's — the pane parser with the `jobKey == jk` anchor is the only reader |
| a second cap env var for the matched driver | its failures stamp `jd_attempted` and ride the 7/14/28 ladder (~13 credits/month on today's 6 rows); only the inline layer, which stamps nothing against cards re-offered nightly, needed a bound (`JDFILL_INDEED_CAP` 8 → ceiling 240/month, 4.8 % of the pool) |

## The wall-first half

`extract_jd` gained `_after_the_wall`: when the head of a page fails the two-family bar, a
candidate segment opens at each SIGN-IN furniture mark's end and closes at the next
furniture of any kind; the first candidate passing the same two tests wins. It exists
because "keep the full text, fail the bar, go to the fetch" (the 08-28 rule for STORED
text) is circular at fetch time — the fetch returns the same wall-first LinkedIn page.
Measured: Ashley Digital's posting sits at offset 2,240 under six stacked sign-in blocks
(`furniture_at` = 326); the fallback recovered 2,395 and 4,931 characters on the two live
wall-first pages and activates on **0 of 1,478 stored bodies**. Rail marks (`similar jobs`,
`people also viewed`) never open a candidate — a segment opened there is other employers'
titles with this row's company still attached. Rejected: cutting `jd_body` at the LAST
furniture instead of the first (destroys the ordinary tail-cut that 13 rows depend on), and
a length-guard on the head cut (the 08-28 session measured that keeping 6,000 chars of
login form because the remainder is short is how the board showed one).

## The marker-bar half — and the wave that tightened it

The same session recalibrated `looks_like_jd`'s two-family bar with requirement-idiom
families, measured over all 1,478 stored bodies (149 failing ≥300-char bodies). The first
draft (`advantage`/`יתרון`, `major plus`, `must have`/`nice to have`, `דרוש/ה`, the degree
ask, each a separate family) promoted 10 real postings and 0 corpus walls — **and an
adversarial wave showed the corpus could not carry that safety claim**: the walls were
cleaned out of stored text on 08-28 (1 sign-in-marked body left), and six synthesized junk
texts passed the draft end-to-end — a cookie banner ("must have JavaScript enabled" +
"improve your experience"), an FAQ with zero job vocabulary ("must have: a valid email.
Nice to have: a phone" — one idiom pair counted as two families), a benefits paragraph and
marketing prose ("take advantage of ... experience"), a Hebrew nav, a bilingual line
(`יתרון` + `advantage` double-counted).

The shipped line answers each mechanism, not each example:

* **the idioms fold to ONE family** (`_REQ_IDIOM`): they are synonyms of one concept, so a
  classic section family is still required beside them;
* **`advantage` refuses the marketing verb** — `take/taking/takes/took advantage` is 10 of
  the 804 corpus occurrences and every one is a benefits blurb (Plarium, Cognyte ×2,
  Continental ×2, TELUS ×4);
* **`must have`/`nice to have` dropped outright** — 1 corpus flip (Teads) against three
  junk classes that ride them (cookie banners, FAQs, browser requirements).

Shipped result: **8 promotions of the 149, all real postings** (the three published rows +
BrancoWeiss ×2, C2A Security, IBI, zap group); every synthesized junk text refused; the one
synthetic that still passes carries two CLASSIC families and passes the 08-28 bar as well.
Also rejected, from the first draft's sweep: bare `דרושים` (the Israeli nav-link word),
`a plus` (Plus500's "Career WITH A PLUS" slogan), CV-submission phrases (two careers
landing pages), `you will` (26 flips, 9 junk). Lost against the draft: Teads (its one
flip), Cognyte's marketing-prose flip ("they are taking advantage") — a flip supplied by
the wrong mechanism, correctly surrendered.
