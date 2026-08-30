# 2026-08-30 `discovery` — which source would give the registry an OWN domain (research)

Base `origin/master` `c1fda51`, worked in `.claude/worktrees/discovery-0830`. **Dry mode
throughout**: no `secrets.env` in the worktree, so every paid rung was disarmed — and none
was needed. Spent: **0 Bright Data credits, 0 SerpApi, 0 `claude -p`**; ~120 honest-UA
HTTP GETs (feeds, Wikidata, ~85 TASE company sites, 6 Drushim/AllJobs pages, 2 LinkedIn
guest pages, 1 Drushim page in a real Chrome). Three Opus adversarial waves, all read-only.

The decision record is `docs/decisions/2026-08-30-discovery-own-domain-sources.md`. This
file is the workings: every command, what it printed, and what the attackers overturned.

## The brief, and the premise that did not survive re-derivation

The orchestrator measured 563 of 572 queue entries carrying an aggregator `careers_url`
and asked why secrethunter yields aggregator links when "its sitemap carries the domain".
The 572 / 456 / 104 / 3 / 8 / 1 split reproduced exactly:

```
python - <<'EOF'
import json,collections,urllib.parse
r=json.load(open('research_companies.json',encoding='utf-8'))
print(len(r),collections.Counter(urllib.parse.urlparse(x.get('careers_url') or '').netloc or 'none' for x in r).most_common())
EOF
```

But the premise came from the operator's Desktop prompt of 08-28, not from a decision
record: the 08-27 record says the sitemap carries the LinkedIn **handle** and the domain is
crawler-UA-gated. `pipeline/secrethunter.py:434` writes the catalog URL as the seed on
purpose so `auto_expand` routes the name to `_site_from_guess`; `slug` is filled 454/456.
The wave-1 attacker re-walked every keyless path (5 sitemap types, `/jobz/`,
`api.secrethunter.io` → 403, every cached body in the tree): no domain field exists to
discard.

## What the own-site rung has already done to the queue

From `cloud_state/queue_state.json`, matched by lower-cased name:

```
secrethunter 456: own-site tried 272 → no-domain-answered 212 · no-linkback 35 · not-named 12
                  · no-handle 6 · redirected-off 3 · resolved-domain 4 ; never tried 184
linkedin 104:     own-site tried 76 (77 attempts) → 53 · 6 · 5 · no-handle 7 · proposal 1
                  · redirected-off 1 · resolved-domain 4 ; never tried 28
ALL own-site attempts: 881, every one dated 2026-08-29, resolved-domain 55
python queue_state.py → SETTLED 15 · OWED 557 · next rung own-site 213
```

**The attacker's correction that matters:** 1.5 % on the residual queue is survivorship —
46 of the 55 winners have left the queue (41 are rows). The rung's yield is 55/881 = 6.2 %;
the docstring's 13.5 % is on real handles. Expected from the 214 untried: ~13 domains,
then ~1 board at `resolve_llm`'s 7.3 %. The LinkedIn tally in my first draft was also wrong
(3 → 4 `resolved-domain`; `no-handle 7`, `proposal 1`, `redirected-off 1` omitted).

LinkedIn guest job-view pages, two from the queue (Aristocrat, University of Haifa): zero
non-LinkedIn links; the only own-domain signal is an e-mail in the JD prose.

## The queue's names (item 9 / question 5)

`looks_like_junk`, `is_place_name`, `is_recruiter`: **0 / 0 / 0 of 572**. The attacker's
full read of the 572, which I verified on a seeded 100: foreign 79, not-an-org/duplicate 67,
recruiters the gate passes 23, union ~155 (27 %).

The recruiter hole (`recruit(ing|ment|x)?\b` — no plural, and `\b` does not fire before a
digit) is fixed in this commit. Blast radius measured before and after:

```
queue newly refused:  Sales Experts Executive Recruiters · Human Capital Recruitment1 · Yarden Abramovich HR Consulting
ACTIVE rows newly refused: []      parked rows newly refused: Yamo Overseas Recruiters Limited
pytest -k recruiter: 28 passed
```

## Catalog provenance — the number the cap decision turns on

My first measurement ("28 rows noted `secrethunter`, 0 roles") was the WRONG population
(pre-catalog Telegram `/jobz/` seeds). Reconstructed from every commit of
`research_companies.json` since 08-26 (18 commits, 2,698 names ever queued):

```
first-queued provenance: other 1031 · catalog 892 · linkedin 517 · jobz 214 · indeed 44
catalog names now rows: 351 (active 136); with matched roles: 4 companies / 5 roles
matched companies by provenance: other 52 · linkedin 37 · never-queued 20 · indeed 9 · jobz 8 · catalog 4
```

## The candidates (all keyless, honest UA)

- **Wikidata TASE** — `SELECT ?c ?en ?he ?w WHERE { ?c wdt:P414 wd:Q1507974 . OPTIONAL {?c wdt:P856 ?w} …}`:
  778 entities, 675 with website, 577 registrable domains; by `identity_key` on EN/HE labels
  + domain match: 96 known (35 active), 7 queued, 675 new, 574 with a website. (My first
  query used the wrong Q-id, Q1073226, and returned 0 — the `wbsearchentities` lookup fixed
  it.) Random 30 of the new (`tase_sample.py`, seed 20260830): 22 answered, 4 careers links,
  0 analyst-shaped titles (only 4 careers pages were actually read). Large-cap stratum
  (51 names / 49 sites matched on a hand list of TA-125 domains): 46 homepages answered,
  20 careers links, 18 pages read, 3 analyst-shaped title strings — 1 finance, 1 trade
  marketing (Paz), 1 skill line — none accepted by the repo's title gate, all three LLM
  calls. Discount Bank's board is Oracle HCM and `fetch_oraclehcm` read it keylessly:
  64 requisitions, 5 signal-tier titles, 0 in scope (wave 2b).
- **Geektime** `/category/funding/feed/`: 30 items per page, 22 Jul → 28 Aug on page 1,
  8 Jun → 20 Jul on `?paged=2` (0.74/day over 81 days); ~24 name an identifiable employer,
  7 carry its domain; my hand read said 19 new, the `identity_key` join found 9 of them
  already held → 9–11 genuinely new a month, ~4 with a domain. `/feed/` (main):
  gadgets and Google news. TheMarker `cmlink/1.145`: 100 items of general business news;
  its `/misc/rss` index exposes no section ids. Globes `iID=594` (15) / `iID=1725` (93):
  columns, no employer domains. Calcalist / CTech: every guessed feed URL 404, no RSS
  index page.
- **TASE's own site/API**: 403 to our UA. Not spoofed.
- **Drushim**: `/companies/` lists 96 company links; four of them 404 to `urllib` and two
  (superfish, Matrix) 404 in a real Chrome. Stopped at the third attempt per the browser
  rule. No page → no domain.
- **AllJobs**: `/companies.aspx` 200; the only outbound link is AllJobs's own LinkedIn.

## What the waves overturned

Wave 1 (re-derivation): LinkedIn tally; the 1.5 % denominator; the catalog population
(28 → 892/351/5); the 27 % noise read; the recruiter regex hole; a spoofed UA in
`discovery_telegram.py:58`.

Wave 2a (the code change and recommendation 1): the regex is clean over 2,697 distinct
names (exactly the 4 predicted); the mutation record's `\b` had become a BACKSPACE through
the Bash heredoc (fixed with a script file); the cap changes growth (+138 → +28 net/run),
not the noise share; an Israel filter at intake is not computable without ≤4 GETs/name;
`auto_expand` writes no per-rung record, so "drains in ~9 nightly runs" was unsupported
(twice-daily cron; 176 never-batched names reach the rung in ~7 runs); three counts off
by one (272 / 212 / 184; 214 untried).

Wave 2b (TASE and RSS): my catalog yield mixed denominators — on a consistent basis it is
4.9 % vs 8.7 % registry-wide vs 25.2 % LinkedIn-seeded (1.8×, not 11×), and holds on a
same-age cohort (3.3 % vs 12.2 %); the cap is per RUN and 08-28 saw four runs (586 catalog
names), so the throttle must be per DAY; the large-cap sample was 51/49 sites, 46 answered,
18 careers pages actually read (the random 30: 4 pages read); Discount Bank's "unread JS
board" is Oracle HCM that `fetch_oraclehcm` reads today — 64 requisitions, 5 signal-tier
titles, 0 in scope, two of them Hebrew forms of English hard-excludes (filed `486`); the
3 large-cap title strings are all LLM calls and none is accepted; Geektime's feed pages
(`?paged=2`: 8 Jun → 20 Jul, 0.74/day) and 9 of my "19 new" were already known, so it is
9–11 new/month, ~4 with a domain. TASE moved from "metered, large-cap-first" to "not at
all"; Geektime moved below the free baseline.

## Not finished

- The ~10 large-cap TASE boards that are ATS-hosted were not swept with `platform_check`;
  one of them (Discount Bank) was read and answered the question in the direction the
  verdict took, so this is a confirmation left undone, not an open question.
- The catalog Israel-signal filter and the 40/run cap are filed, not built (`infra` owns
  the env line).
- 20 agencies still pass `is_recruiter` and need researched `_CONFIRMED` entries.
- `queue_pipeline.py --census` writes `cloud_state/queue_receipt.json`; I ran it in a
  worktree and reverted the file — it is not in this commit.
