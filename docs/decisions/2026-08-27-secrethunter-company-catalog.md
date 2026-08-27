# 2026-08-27 — reading the secrethunter.io company catalog

*lane: `discovery`. Decides how much of a 2,703-company directory this pipeline takes, by
what means, and at what rate. Two decisions: the sitemap is read (shipped); the company
pages are NOT (measured, not assumed — see §3, which reverses the approval this work
started with).*

## 1. What we were short of

514 of 517 `research_companies.json` entries carry an aggregator posting URL instead of the
company's own domain, which is why `resolve_llm._verify` can confirm almost nothing for them
and why `docs/BACKLOG.md` 2 has stood since 2026-08-23. secrethunter.io publishes a catalog
of Israeli employers. The question was whether it could supply that missing field.

## 2. What the catalog actually serves, and to whom

The investigation this work started from reported the company pages' schema.org JSON-LD as
present "in the PLAIN, LOGGED-OUT HTML — random sample of 16 slugs, plain curl, no session,
no JS: own-domain present 16/16."

**That does not reproduce.** Measured 2026-08-27, one GET per row:

| what we sent | bytes | `ld+json` blocks | company data |
|---|---|---|---|
| `curl/8.4.0` | 34,181 | 2 | none |
| a Chrome UA | 34,181 | 2 | none |
| no `User-Agent` at all | 34,181 | 2 | none |
| `AnalystJobsIL/1.0 (+…)` — honest | 34,181 | 2 | none |
| `Claude-User` — the published identifier for an agent fetching for a user | 34,181 | 2 | none |
| `?_escaped_fragment_=` with an honest UA | 34,181 | 2 | none |
| **`Googlebot`** | **38,649** | **5** | `Organization.sameAs`, `ItemList` |
| **`bingbot`** | **38,649** | **5** | same |
| **`ClaudeBot`** | **38,649** | **5** | same |

The 34,181-byte body is **byte-identical across 26 different companies** — it is the SPA
shell, and that identity is what gives the game away. The two `ld+json` blocks in it are
secrethunter's own `Organization` and `WebSite`, not the company's.

The prerender is dynamic rendering keyed on a **closed allowlist of named search-engine
crawlers**. Six honest identifiers were tried, including both of the ones Anthropic
publishes; none reaches it.

Under a bot UA the payload is real and rich — verified once, on one page, to size what was
behind the gate:

```
Organization  name: "Ness Technologies | נס טכנולוגיות"
              sameAs: "http://www.ness-tech.co.il/"      <- the field we lack
              foundingDate: "1999"
ItemList      numberOfItems: 193, all 193 titles present
```

**Two lessons, both of which cost time here.** Parse the structured data, never grep the
markup — the original check "found" the domain by grepping the raw HTML and had matched a
substring of `linkedin@ness-tech.co.il`, an email address. And a measurement that *disagrees*
with what you expected deserves the same re-run as one that agrees: the first sample said the
source was dead, and it took five more UA variants to learn it was gated rather than absent.

## 3. Decision — what we do, and what we refuse

**SHIPPED: read the sitemap. It is not gated.** `https://secrethunter.io/sitemap.xml?type=companies&page=1`
answers in full to an honest UA: 5,406 `<loc>` entries = **2,703** unique `/companies/<slug>`
pages (each listed plain and `?lang=en`); `page=2` is empty. The slug is usually the
company's LinkedIn handle, and a handle is precisely what `auto_expand._site_from_guess` can
turn into a *proven* own domain. `pipeline/secrethunter.py` reads it; nothing else.

**REFUSED: sending a crawler User-Agent.** It misrepresents us to the publisher, defeats a
deliberate product decision, breaks their analytics, and would put UA-spoofing inside a daily
cron. Not done, and not to be added later.

**REJECTED ON MEASUREMENT: rendering the pages in a real browser.** This was approved by the
operator as a one-time database backfill — honest, because a real browser is the site's
intended audience — and a bounded one-shot reader was written for it. It does not work. A
logged-out Chromium, **headless and headed, with a genuine Chrome UA and with an honest
custom UA**, renders the same shell every time and displays:

```
Error loading company information
Please try again later or contact support if the problem persists
שדרגו לפרימיום   (upgrade to premium)      להתחברות   (log in)
```

The client-side app fetches company data from `api.secrethunter.io`, which is auth-gated;
3 of 3 pilot pages yielded 0 own-domains and 0 titles, and the rendered bodies were
byte-identical across companies. **So there is no honest client that can read those pages** —
the content is available to search-engine crawlers and to authenticated (premium) users, and
to nobody else. The one-shot tool was deleted rather than left in the tree: a script that
returns 0% invites a future session to "fix" it with `user_agent="Googlebot"`, which is the
one outcome this record exists to prevent.

**Left to the operator, not an engineering task:** if this data is wanted, it is a
subscription or a licensing conversation with secrethunter — the same bucket Startup Nation
Central is already in. Note that scraping behind a paid login would be *worse* than the
crawler-UA route, not better.

## 4. Conduct for what we do take

- **One GET per run**, for the sitemap only (~2.7 MB). No company page is ever requested.
- **Honest identification**: `AnalystJobsIL/1.0 (+https://github.com/AnalystJobsIL/pipeline)`.
  This is deliberately the opposite of `pipeline/http.py`'s default UA, which carries no
  identifying token on purpose so ATS providers cannot fingerprint the scanner. A bulk read
  of one small publisher's catalog is the case where they are entitled to see who it is.
- **`robots.txt` is respected and permits this**: `Allow: /`, with only `/search?`,
  `/*jobs_filters` and `/auth/` disallowed; `/companies/` permitted; a sitemap published.
  ClaudeBot, GPTBot, CCBot, Google-Extended and PerplexityBot are each named and allowed —
  which is what makes the page gate a *rendering* decision rather than a crawling ban.
- **Volume into our own queue is capped**, not by politeness but by the resolver queue being
  the bottleneck — see §5.
- **Zero Bright Data credits, zero SerpApi, zero LLM calls.**

## 5. Why the catalog is metered into the queue

`ARCHITECTURE.md` §1a: *"Widening intake is no longer free — the resolver queue IS the
bottleneck."* `LLM_RESOLVE_CAP` is 10 against 250-name batches, and the `registry` lane
deliberately drained this queue **1,693 → 517** on 2026-08-27. Adding 2,002 names in one
morning would undo that and bury the leads that are already there.

The cap is set from the registry's THROUGHPUT, not from what the source could
supply: the 2026-08-27 auto-expand run resolved 11 rows from a batch of 250 on the free
rung, so ~22/day. A first cut used 150/run, which a sandbox dry run against copies of the
real state files showed to be **+138 net per run** — the queue back over 1,500 inside a
week and the drain undone. 40 clears the whole 2,002 in ~50 days and is one env var away
if someone wants it faster.

**And a queued name goes to the FRONT of the batch, not the back:** `auto_expand.py:455`
sorts `todo` by last-tried date, and an unseen name sorts to `""`. So these 40 are tried
ahead of older leads while carrying **no job signal at all**, where a LinkedIn or Indeed
card arrives attached to an analyst-shaped posting. The cap bounds the queue's DEPTH; what
those 40 slots DISPLACE is not measured, and the analyst-role yield of the 2,002 is
unestimated. That is the strongest argument for keeping the cap low.

`SECRETHUNTER_QUEUE_CAP` (default 150) meters it, and the window is **rotated by day-of-year**
rather than taken as a prefix — the same fix `_targeted_inputs` needed when `unresolved[:20]`
over a stably-sorted list meant the same 20 names went out daily and the other 90 of 110 were
never searched once (§1a rule 3). Every slug is reached in ~50 days.

## 5b. The catalog ENRICHES the queue, it does not only extend it

The first cut skipped any name already queued, so it could only ever ADD — and that left the
most valuable thing in the sitemap on the floor. **135 of the 517 queue entries carried no
handle at all**, and among them **all 91** that this same source had queued as
`secrethunter.io/jobz/` postings back when there was no catalog reader. Those 91 were the
subset of the queue that **no rung could even attempt**: an aggregator seed is only rescued by
`_site_from_guess(name, slug)`, and they had no slug to guess from.

`backfill_handles` fills an EMPTY `slug` on an entry we already hold, from the same sitemap
already in memory. Measured against the committed queue:

| | |
|---|---|
| no-handle entries filled | **71 of 135** |
| of which the stranded `secrethunter.io/jobz/` ones | **59 of 91** |
| handles we hold that the catalog DISAGREES with | **25** — kept ours, disagreement logged |
| fills lost to an ambiguous key | **0** |

**It never overwrites a handle we already hold.** Roughly 10% genuinely differ — `Grain` vs
`grainfinance`, `Wayve` vs `wayve-technologies` — and ours came from a LinkedIn card that
named the company, which is provenance a third-party directory slug does not have. The
disagreement goes to `cloud_state/intake_rejects.json` as `handle-mismatch` so it is visible
and appealable, and ours stands.

Where two catalog slugs claim the same name key, **neither** handle is written. Writing the
wrong one would send `_site_from_guess` at another company's domain, with
`page_mentions_company` the only thing between that and a wrong row; leaving it empty costs
one lead. On today's data that conservatism costs nothing — 0 of the 64 still-empty entries
were lost to ambiguity; they are simply not in the catalog.

Additive to the queue's existing four-key shape, so no other lane changes.

## 6. The numbers, all against `origin/master` `fbfc83e`

| | |
|---|---|
| catalog size | **2,703** slugs = **2,698** distinct companies (5,406 locs; 5 slugs are second spellings, e.g. `NeuReality`/`neureality`) |
| double-percent-encoded slugs | **26** (16 Hebrew, 10 European: `bäckerei-…`, `loréal`) — the investigation said ~204 Hebrew |
| already in `companies.csv` | **484** |
| already in `research_companies.json` | **206** |
| **new employers, refused by nothing** | **2,002** |
| refused by our gates | **11 (0.4%)** — 4 agency, 4 wholly-Hebrew, 2 over-long, 1 junk-name |
| offered per run | 150, day-rotated |

**The refusal rule was measured, then loosened.** Its first cut refused 98 names, including
`Harmonya%20Technologies`, `Valence%20Security`, `Zafran%20Security` and
`Innoviz%20Technologies` — Israeli tech companies whose only fault was a space in the URL —
and discarded `אוניפארם-קריירה-unipharm-career` entirely although its Latin tail is a real
handle for a real company. Normalising before refusing recovered **87 of the 98**. All 11
survivors were hand-checked, not sampled: the 4 agencies are correct (`Moveo Source` and
`Nogamy` are already in `recruiters._CONFIRMED`), the 4 Hebrew-only slugs genuinely reach no
rung we have, and 2 over-long names (Kivunim, an NGO; Microwave Vision Group, a French test-and-measurement firm) plus `Lead Machine` are borderline — every one of them
recorded in `cloud_state/intake_rejects.json`, which is what makes a wrong refusal appealable
(`docs/BACKLOG.md` 70).

## 7. What the slug is actually worth — and what this number is NOT

**Read the label carefully, because the first version of this section got it wrong.** What
follows measures ONE step: does `<stem>.<tld>` reach the company's real registrable domain.
That is the first of five things `auto_expand._site_from_guess` does. It then requires the
page to be ≥2,000 chars, `page_mentions_company(name, html, strict=True)`, a **whole-handle**
`linkedin.com/company/<handle>` linkback, and `not is_foreign` — and it returns `None` on the
first TLD that answers without naming the company.

**The rung's own measured yield is in its docstring (`auto_expand.py:283-285`):**

> *"over the 364 drainable names carrying a valid handle: 119 domains answered, 104 named the
> company, 53 carried the linkback, and 49 satisfied ALL THREE."*

**49 / 364 = 13.5%.** That is what the rung produces. The table below is a ceiling on its
first step, and an earlier draft of this file labelled it "what `_site_from_guess` does now",
which overstated the rung by about four times. Anyone sizing work against it should size
against 13.5%.

Ground truth for the step: the catalog slugs that match a `companies.csv` `scrape` row whose
`api_url` host IS the company's own site, compared at the registrable domain (eTLD+1 —
comparing full hosts undercounts, because `careers.arm.com` and `jobs.apple.com` are
subdomains).

| rule | reaches the real registrable domain |
|---|---|
| `<slug>.<tld>`, today's four TLDs | **124 / 200 = 62.0%** |
| the same, with 17 more TLDs | 130 / 200 = 65.0% (**+3.0 pp**) |
| **slug VARIANTS × today's four TLDs** | **146 / 200 = 73.0% (+11.0 pp)** |
| variants × wider TLDs | 152 / 200 = 76.0% |
| irreducible — abbreviation / restructuring | **48 / 200 = 24.0%** |

Two things follow, both handed to `registry` rather than taken here (`auto_expand.py` is
theirs, `docs/BACKLOG.md` 334):

1. **Varying the stem is worth ~3.7× what widening the TLD list is** (+11.0 pp vs +3.0 pp).
   The variants that pay are lossless: de-hyphenate, strip a trailing `-ltd`/`-israel`.
   `applied-materials → appliedmaterials.com`, `bookmap-ltd → bookmap.com`. Do NOT truncate a
   meaningful token — `_lossless_slugs` refuses that, and BACKLOG 317 records what a stem that
   near-equals a *different* company costs.
2. **But the step this improves is not the rung's binding constraint.** Of the 119 domains
   that answered, 104 named the company and only **53** carried the linkback. Stem variants
   produce more *candidates*; they do nothing about a company whose site does not link to its
   own LinkedIn page. So +11.0 pp on step 1 becomes materially less than +11.0 pp on the rung,
   and 325 should be measured end-to-end before anyone banks it.

### The sample is biased, and here is the size of it

The pairing rule only creates a pair when the slug-derived name collides with a registry name
— which conditions the sample on *slug resembles the company name*, the same latent property
as *slug resembles the domain*. **The sample partly excludes the failure mode it is
estimating.** Measured, with identical scoring code:

| sample | variants × today's four TLDs |
|---|---|
| pairs the strict rule **includes** (n=200) | **73.0%** |
| own-site rows it **excludes**, recovered by a looser match (n=27) | **55.6%** |

A **17.4-point gap from sample selection alone.** (An adversarial re-measurement using a
different recovery rule put the gap at ~26 points; the direction is robust across both
constructions, the magnitude is not.) The excluded misses are exactly the shapes the 2,002
residual is made of: `quantum-source-labs-ltd → qs-labs.com`,
`central-bottling-company-group-ltd → cbccom.com`, `the-estee-lauder-companies-inc →
elcompanies.com`, `elbit-systems-ltd → elbitsystemscareer.com`, `general-motors → gm.com`.

Compounding it: these 200 are companies we have ALREADY resolved, and a visible share are
foreign multinationals (Apple, AstraZeneca, Microsoft, Oracle, SAP, Siemens) whose domains a
slug reaches easily and which **`is_foreign` discards inside the very rung being measured**.

**So the honest statement is not "the direction is solid, the second digit is not." It is:
the first digit is not established either for the population this will actually run on, and
this sample cannot establish it.** What the table does support is the *comparison* between the
two levers — stem variants beat TLD widening — because both are scored on the same pairs.

## 8. Sources rejected without a line of code

Carried forward from the investigation, re-stated so nobody re-derives them:
**AllJobs** (2,069 employers) carries no outbound company domain — names only, which
reproduces exactly the queue we cannot resolve. **Startup Nation Central Finder** (13,965
startups, the richest set) returns 403 unauthenticated and gates on an account: a licensing
conversation, not an engineering task. **korotchaim.com** (20 companies, no domain field),
**mappedinisrael.com** (sitemap `lastmod` 2024), **science.co.il/companies** (no outbound
links), **geektime.co.il** (blog sitemaps) — all rejected. **Drushim** (2,391 companies)
expected to be names-only, unverified.

**theorg.com is the one worth a look, and it was not on the original list as viable.** Spot
check 2026-08-27, honest UA, 7 of 7 companies: it serves `Organization` JSON-LD carrying
`url` (the company's own domain), a LinkedIn company URL in `sameAs` — which is the handle,
not a guess at it — plus `address`, `legalName` and employee records. Its weaknesses are that
it is global rather than Israel-scoped and carries no job titles. Filed as `docs/BACKLOG.md`
327 rather than built, because it is a second source and this session already added one.
