# Agent brief — read this before touching anything

For a session spawned to work on ONE part of the pipeline while other sessions work on
others. It exists because the docs are deep but not ordered, and because several parts of
this repo are unsafe to edit concurrently.

## Read in this order (~20 minutes)

0. **`CLAUDE.md`** — two minutes, and it loads automatically. What ships, the flow, the five
   rules, the quotas, the pre-push contract. If you read nothing else, read this.
1. **`ARCHITECTURE.md` §0 and "the whole system on one screen"** — what the user actually
   receives, and how to run anything locally without side effects. Non-negotiable.
2. **`ARCHITECTURE.md` §2** — §2's **four registry rules** (distinct from `CLAUDE.md`'s
   five, which are the whole-repo set): the
   verdict-string rule, the activation rule, the single-writer rule, and the note
   append-log. **If you are changing a resolver, an activation path, or anything that
   writes `companies.csv`, these ARE the spec.**
3. **`ARCHITECTURE.md` §8** — the failure classes. Silent exclusion, the mass-zero
   measurement, the two concurrency layers. One page, and it is why this repo needs a brief
   at all.
4. **`HANDOFF.md`** — the whole file; it is capped at 250 lines. Current state, the watch
   list, and what is unclaimed. Your lane may be on it.
5. **Your lane's section** from the table below, and **`docs/MODULES.md`** for the modules it
   names — it says which are scheduled, which are libraries nothing appears to run, and
   which are dead weight.

6. **`docs/RUN_LOG.md`** if you are about to read a digest mail or a step log — every line
   the run can print, what emits it, and what its absence means, plus the one table of
   every seam that spends the Claude subscription and which model it uses.
7. **`docs/AUTOMATION.md`** if you are about to trust a schedule. `ARCHITECTURE.md` §4 says
   when a cron is *supposed* to fire; that page has the measured lag, and on 2026-08-27
   three crons did not fire at all.

Skim only when relevant: `ARCHITECTURE.md` §3 (resolution ladder), §5 (state files and who
writes them), §5b + §5c (the "why isn't company X in my email" runbook and the debugging
one-liners), §7 (firmographics), `docs/TAGGING.md` (every board tag and where it is
computed), `docs/BRIGHTDATA.md`, `docs/ATS_PLATFORMS.md` (companies.csv columns and the
per-platform URL patterns).

**Archaeology, not required to start:** `docs/sessions/2026-08-23.md` is the seventeen
defects (A–Q) found that morning and how each was fixed — the best single description of how
this codebase fails: green workflow, plausible log line, no coverage. Read the ones adjacent
to your lane if you have time. `docs/sessions/2026-08-22.md` is the migration and the
ten-agent audit. `docs/decisions/` holds superseded design decisions — the root
SCHEDULING.md moved there on 2026-08-23, having been **wrong for three days**, telling
readers the daily email was unbuilt while it shipped every morning. That is the failure
mode this whole documentation set is arranged against.

## The flow, and the lane that owns each step

```
   ┌── 1 INTAKE ────────┐   LinkedIn · Indeed · Telegram  ──▶ discovered_cache.json
   │   lane: discovery  │   new employer names            ──▶ research_companies.json
   └────────┬───────────┘
            ▼
   ┌── 2 REGISTRY ──────┐   resolve a name to a board, repair a dead one,
   │  lane: registry ✱  │   park what is genuinely dark   ──▶ companies.csv  (800+ active)
   └────────┬───────────┘
            ▼
   ┌── 3 FETCH ─────────┐   ats-fetch · native ATS APIs   (17 platforms)
   │ lanes: ats-fetch   │   scraper   · the browser scraper (the rest)
   │       + scraper    │                                 ──▶ scraped_cache.json
   └────────┬───────────┘
            ▼
   ┌── 4 ENRICH ────────┐   jd-text      · a description for every relevant role, any age
   │ lanes: jd-text     │   company-intel · sector / stage / size / founded
   │     + company-intel│                                 ──▶ cloud_state/firmographics.json
   └────────┬───────────┘
            ▼
   ┌── 5 CLASSIFY ──────┐   Israel filter → relevance/seniority → LLM for the ambiguous
   │  lane: classifier  │                                  ──▶ accepted roles
   └────────┬───────────┘
            ▼
   ┌── 6 ROLE RECORD ───┐   is this the same role we saw yesterday? still open? a repost?
   │   lane: roles      │   what drops off the board, and what the archive keeps
   └────────┬───────────┘                                 ──▶ matched · sent (the store)
            ▼
   ┌── 7 RENDER ────────┐   the board, the archive, the email, every tag on a role card
   │   lane: render     │
   └────────┬───────────┘
            ▼
   ┌── 8 DELIVER ───────┐   commit state · publish the board · relay the email ·
   │   lane: infra ✱    │   the merge machinery · the workflows
   └────────────────────┘

   lane: docs — cuts across all eight steps  ✱ = only one session at a time
```

## Lanes, and what each may write

Pick ONE. The split exists so that two lanes never write the same file.

| lane | step | the queue it owns — **today's reading, 2026-08-30**, and how to re-derive it | primary files |
|---|---|---|---|
| **`discovery`** | 1 | **165 of the 572 names in the intake queue carry a conclusive retirement and were re-added anyway** (42 of 276 at 05:xx; two digest runs then re-added 362 names, 189 of them already retired). Nothing that writes `research_companies.json` reads `cloud_state/queue_disposition.json`, so the queue cannot stay drained (`441`). Intake is throttled since today — the catalog offer is capped at **40 a DAY** (`SECRETHUNTER_DAY_CAP`, `pipeline/secrethunter.py`; steady state ~31; first unattended proof is a `[secrethunter]` step line reading `day window 40`) — and the queue is **27 %** noise on a seeded 100 (foreign, not-an-org, recruiters the gate passes; `484`). Target 0 re-added. `python -c "import json;d=json.load(open('cloud_state/queue_disposition.json',encoding='utf-8'));r=json.load(open('research_companies.json',encoding='utf-8'));print(sum(1 for x in r if (x.get('name') or '').strip().lower() in {k.strip().lower() for k,v in d.items() if (v.get('verdict') or '') in ('no-board','duplicate-of','not-an-employer','acquired-by')}))"` — *(owns: where new roles and new employers come from)* | `discovery_daily.py`, `discovery_telegram.py`, `pipeline/aggregators.py`, `pipeline/recruiters.py` |
| **`registry`** *(one at a time)* | 2 | **37 OWED of a 414-name unsettled queue** (2026-09-01 15:0xZ, `python queue_state.py`: 37 OWED · 360 ON CADENCE, answered and waiting out 14 days · 17 answerable from disk; all 37 sit on the cheapest rung, `own-site`). It read 65 on 2026-08-31 and the first real drain has run since. **Read `OWED`, not the queue size, and not the mail's `owed=`** — the 08-31 digest stamped `owed=369` at 11:29Z and the same tree read 65 by 14:20Z, because that run's dispose step retires names AFTER composing its own stamp. The number under this one is capacity: the nightly drain does **112** (`queue_resolve_search.nightly_capacity()`) against brand-new intake of **161 a day at the median, 212 mean** (seven days to 08-30). A drain below intake cannot hold, whatever a session does by hand (`491@infra`, retire-settled first). **The drain has never once recorded an attempt in the cloud** — every previous night died in 6 seconds on a missing `out/` dir under `continue-on-error`; fixed (`df803a1`), first real test is the 08-31 19:00 run, and a disarmed key can no longer masquerade as one (`empty_search_share`, `queue drain BOUGHT NOTHING`). Target 0, and a drain that exceeds intake. `python queue_state.py` (read-only without `--ingest`) — *(owns: dark rows, and the 5-rung resolution ladder (§3) over 9 re-check pools)* | **`registry_health.py`** (read-only: census, who re-checks what, which ATS to build, `--explain "<name>"`), `companies.csv`, `listing_hunt.py`, `triage_dark.py`, `crack_walled.py`, `deep_validate.py`, `repair_*.py`, `resolve_*.py`, `audit_empty_rows.py`, `probe_candidates.py`, `scan_dead_domains.py`, `auto_expand.py`, `apply_resolved.py`, `confirm_zero.py` (the zero audit: it parks ACTIVE rows `needs re-resolution`, so it writes registry verdicts), `queue_disposition.py` (the only sanctioned way a NAME leaves `research_companies.json` — it writes the evidence; `discovery` owns the re-add that ignores it, `441`) |
| **`ats-fetch`** | 3 | **18 active rows whose newest posting is 12+ months old** (17 at 05:xx: HiBob was repaired and two aged in) — a board that answers and has not moved since 2024 is a row we count as covered and a company we are not covering. Target 0. `python registry_health.py --stale-boards` — *(owns: how a board's API is read; adding a platform)* | `pipeline/fetchers.py`, `pipeline/platform_check.py`, `pipeline/health.py` |
| **`scraper`** | 3 | **34 cards whose JD page is shared, not their own** (`_jd_shared_page` in `scraped_cache.json`; 33 at 05:xx) — a posting whose url is a listing page cannot be read, judged on its own text, or linked to. The nightly `not-a-job-url` refusal count is the flow behind it and is **not in committed state** (`443`). Target 0. `python -c "import json;s=json.load(open('scraped_cache.json',encoding='utf-8'));print(sum(1 for v in s.values() if isinstance(v,list) for j in v if j.get('_jd_shared_page')))"` — *(owns: the 5-strategy browser extraction for every company with no API)* | `scrape_universal.py`, `refresh_scrape_cache.py`, `cache_new_rows.py` |
| **`jd-text`** | 4 | **3 of 193 matched roles fail `looks_like_jd`** (2026-09-01; was 4 this morning, 1 of 187 on 08-31 evening — the pool grew), and all three are honest: `taboola\|product analyst…` (`structural:gone(donors:0)`), `madanes insurance agency\|manager bi` (its only address is a LinkedIn guest page that serves no posting — `bd-no-markers`, stamped) and `8fig\|credit risk analyst`. **But that number measures COVERAGE, not correctness, and on 2026-09-01 an operator audit found 7 published rows whose text is not their role's — every one of them PASSING this bar.** So the lane now carries a second number, and it is the one to read: **38 of 190 rows that pass the bar carry no strict mention of their own employer** (`quality_suspect` → `no-company-echo`), each awaiting one cached model call. Target 0 unexplained on the first, and on the second a verdict for every flag — which does NOT happen unattended today: the tier is auth-refused on the runner (`llm-auth13`, `infra`'s Open item 3), so guards 3 and 4 of §7a only bite when a session runs the driver by hand. **109 attempted scrape cards are still under 200 characters** (of 1,027 attempted). The MATCHED per-row reason IS committed state (`matched.jd_why`); the scrape-card reason still is not. `python -c "import sqlite3,sys;sys.path.insert(0,'.');from pipeline.jdfill import looks_like_jd,quality_suspect;c=sqlite3.connect('cloud_state/seen.db');r=[x for x in c.execute('select mkey,coalesce(company,\"\"),coalesce(description,\"\"),coalesce(jd_why,\"\") from matched where coalesce(status,\"\")!=\"superseded\"')];print(len([1 for m,co,d,w in r if not looks_like_jd(d)]),'no-JD;',len([1 for m,co,d,w in r if looks_like_jd(d) and quality_suspect(d,company=co)=='no-company-echo']),'no-echo')"` — *(owns: every relevant role gets its description, whatever its age — and that it is THAT role's)* | `pipeline/jdfill.py`, `enrich_scrape_jd.py`, `enrich_matched_jd.py` |
| **`company-intel`** | 4 | **21 active rows with no sector, by `identity_key`** — 37 by exact name, and the exact-name count OVERSTATES the gap: the join `firmographics.yml`'s own summary step and the mail's `registry backlog` use is `pipeline.firmographics.identity_key` (84 exact / 68 by key at 05:xx; the 10:17 cron drained it since). Target 0. `python -c "import json,csv;from pipeline.firmographics import identity_key as k;f=json.load(open('cloud_state/firmographics.json',encoding='utf-8'));s={k(n) for n,v in f.items() if (v.get('sector') or '').strip()};print(sum(1 for r in csv.DictReader(open('companies.csv',encoding='utf-8')) if r['active'].strip().lower()=='true' and k(r['company_name']) not in s))"` — *(owns: sector / stage / employees / founded / Israel centre)* | `pipeline/firmographics.py`, `pipeline/company_info.py`, `research_firmographics.py`, `bd_employees.py`, `fill_employees_llm.py`, `company_type_analysis.py` |
| **`classifier`** | 5 | **0 role records without a classifier verdict**, and it held through the 2026-09-01 digest — the 08-31 backfill's 33 went to 0 and stayed there (`backfill: 0 verdict-less record(s)` in run 33494404810). Re-derive: python -c "import json;print(sum(1 for l in open('cloud_state/roles.jsonl',encoding='utf-8') if l.strip() and not (json.loads(l).get('class') or {}).get('decision') and json.loads(l).get('status') in ('open','closed')))". **The number under it is the contract drain**, and the command that reads it was WRONG until 2026-09-01: it took `max()` over the contract PREFIX, which is a hex hash, so a job re-judged under a contract that sorts low counted as superseded — it read 537 of 561 on a morning whose true figure was **189 of 561** (`541@classifier`, the same bug in production's own `_lookup`, fixed). Today, after the 2026-09-01 boundary bump (`v3.7cb6831f` → `v3.0f84ab84`), it is **561 of 561** by construction and the drain starts from a full pool: the 09-01 run re-judged 339 (242 NO + 97 stale-YES, `flipped +5/-8`) and had reached 372 of 561 current before the bump re-superseded them. That is the price of a scope change, stated where the number is so nobody subtracts the two. Expect several mornings, not one — the drain is **encounter-limited, not cap-limited** (it only reaches a verdict when that posting appears in the run; no cap bound on 09-01 either) — plus **13 that no cap reaches**, having no description (`464`, lane `jd-text`). python -c "import sqlite3;from pipeline import seniority as s;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);j={};[j.setdefault((s._versioned(k)[0].rsplit('|',1)[0] if s._versioned(k) else k),set()).add(s._versioned(k)[1] if s._versioned(k) else 'legacy') for k,_ in c.execute('select title_key,verdict from llm_cache') if not k.startswith('jdq1|')];print(sum(1 for v in j.values() if s.CONTRACT not in v),'of',len(j))" — *(owns: which roles qualify, and the LLM tier that decides the ambiguous ones)* | `pipeline/seniority.py`, `pipeline/class_backfill.py`, `pipeline/israel.py`, the `llm_cache` key scheme; `pipeline/llm.py` is shared |
| **`roles`** | 6 | **1 adjudicated-OUT row still in the PUBLIC csv, and 2 seen-id collisions in the mail** (2026-09-02). The 08-30 reading this replaces — 3 wrong rows, 2 Comcast and 1 Jobgether — is **0** today (`cloud_state/roles.csv`, 151 rows), so that class closed; what is left is `Percepto | Data Insights Operations`, adjudicated OUT on 09-01 and not withdrawn because one line matched a SECOND, live role through a stray `seen_id` (`545`, fixed and written), and `roles seen-id collision (2 id(s) …)` on the 09-02 `Stages:` line, which was ONE HoneyBook pair the ledger had already folded (fixed: a settled twin group now drops instead of skipping). **Both are fixed in code and neither is yet proven by an unattended run** — the 2026-09-03 morning check is the proof, and until it answers this reads 1 and 2, not 0 and 0. Target 0 and 0. `python -c "import csv,io;print(sum(1 for r in csv.DictReader(io.open('cloud_state/roles.csv',encoding='utf-8')) if r['title']=='Data Insights Operations'))"` and `grep -c 'roles seen-id collision' digests/latest.md` — *(owns: the role as an ENTITY: is it the same one, is it still open, was it re-posted, when does it leave the board)* | **`pipeline/roles.py`** (the ledger: `cloud_state/roles.jsonl` + `roles_text.jsonl`), `pipeline/store.py` (`matched`/`sent`, `merge_key`, `seen_id`, `merge_duplicates`, `filter_new`, `upsert_matched`), the role-selection block in `pipeline/run.py`, repost detection |
| **`render`** | 6 | **7 of the last 17 mails carried a wrong number in the subject** — the H1 counted one of the mail's two sections: `6 new analytics roles` over 13 bullets on 08-30, 1/4 on 08-29, 2/5 and 4/5 on 08-28. Fixed today (`build_markdown` counts rendered cards; a `Render: email subject says N roles, the body carries M` tripwire under *Needs a look*); the first unattended proof is the 08-31 mail. Target 0 mornings. `grep -m1 '^# ' digests/latest.md; grep -cE '^- \*\*[^*]*\*\*( — [^ ]+)? · 📍 ' digests/latest.md` — *(owns: how a role reads; every tag on a card)* | `pipeline/jdtext.py` (text→structure), `pipeline/rolecard.py` (the card), `pipeline/digest.py` (rendering), `pipeline/roleprofile.py` (the lexicon), `docs/TAGGING.md` — model: `ARCHITECTURE.md` §7d |
| **`infra`** *(one at a time)* | 8 | **5 of 75 scheduled slots not seen in the last fortnight** (1 isolated single-slot drop; ≥ 3 by 2026-09-10 ⇒ build the recovery cron, otherwise it stays rejected). Every other lane's number is held down by a cron, so this is the number under all of them — and CI has a verdict again: **run 33325163882, `success` on all 13 jobs** (`bc7f144`). Target 0 dropped, and every lane's cron named in its own row. `python tests/schedule_census.py --days 14` — *(owns: delivery and the machinery under all of it: merges, workflows, the relay)* | `persist_state.py`, `merge_*.py`, `check_invariants.py`, `.github/workflows/*`, `mark_sent.py`, `pipeline/run.py` (orchestration only), `tests/rehearse_infra.py`, `tools/mutate.py` (the mutation HARNESS and the sharding `tests.yml` drives) |
| **`docs`** | — | **`tests.yml` on master is GREEN — run 33325163882, 13 of 13 jobs `success`** (60 consecutive non-green runs at 05:34Z; delivered by `infra`'s three-job split, and the alarm `444` asked for is in the mail: the 08-30 `Stages:` line reads `ci tests.yml on master is failure - 1 consecutive non-green runs`). The lane's number now: **5 files carry a filed diff and were committed to after it was filed** (`468` → `pipeline/jdfill.py`, 5 commits; `458` → `persist_state.py`, 3; `421`, `459`, `468` one each) — debt that was filed and outlived every session that opened the file. Target 0. `python docs/check_docs.py --debt` — *(owns: making all of the above legible to the next agent and to a visitor, and keeping it honest)* | `README.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `CLAUDE.md`, `docs/*` incl. `docs/check_docs.py` |

**Every number in that column was re-derived on 2026-08-30 at 18:00 UTC from a clean
worktree at `origin/master`, not copied from a report** (the 05:xx readings it replaced are
in brackets where they differ). Two could not be reproduced from committed state
and say so instead of carrying a figure nobody can check: the nightly JD-fill failure count
and the nightly `not-a-job-url` count are RUN counters that the caches do not keep
(`docs/BACKLOG.md` 443). A made-up target is worse than an admitted gap — if your lane's
number is stale or wrong, re-derive it with the command in its own cell and correct it in the
same commit as the work.

**Exactly one agent may hold `registry` at a time, and one `infra`.** `registry` writes the
file every other lane reads; `infra` writes the workflows that run them all. The other nine
are concurrent with each other and with one of each.

**`tests/mutations.json` belongs to no lane and is appended by all of them**, exactly as
`tests/test_units.py` is: each record is a defeat some lane's own code suffered, and the
coverage check fails the build the commit a new activating writer appears without its
mutations. `tools/mutate.py` — the harness that runs the catalogue and the sharding
`tests.yml` drives — is `infra`'s. Both were unowned until 2026-08-30, which is how a
catalogue that four records could no longer match went unnoticed.

### The `roles` lane exists because the role record was nobody's

The role — not the company — is what the product is about, and until 2026-08-24 no lane
owned it: the record lived in `store.py` (given to `infra`), repost detection in `digest.py`
(given to `render`), the description in `jd-text`, and the tags nowhere at all. Three lanes,
no owner, for the central entity.

**What exists today.** `matched` is the durable list of every role ever accepted — 135 rows
on 2026-08-27 (`select count(*) from matched`) —
keyed by `company|title`, carrying location, url, posted_date, seniority, sources, the JD
text, `first_seen`, `last_seen`, and every contributing posting's `seen_id`. `sent` records
what has been emailed so nothing is sent twice. A role is "still open" if we saw it in the
latest scan of its employer; when we stop seeing it, it stops being on the board and appears
in the archive. **Reposts are recorded in the ledger** (`pipeline/roles.py`, a `posted_date`
at least `REPOST_DAYS` = 3 past that episode's `first_seen`; 13 records carry one today) and
re-derived by the same rule at render time (`rolecard.REPOST_DAYS`) when no ledger record
exists.

**The tags ARE stored** — this paragraph said they were not until 2026-08-27, and the
column had been built two days earlier. `cloud_state/roles.jsonl` carries a `tags` snapshot
per role (132 of 135 records today: skills, family, years, degree, track, AI usage),
versioned by `v` and invalidated when `tags_sha1` stops matching `desc_sha1`. What is still
true is that the BOARD recomputes from the description on every render, so a lexicon change
lands the same morning — and that a role's tags are only ever as good as the description
captured while it was open. `company_type_analysis.py` answers
that by re-deriving them each time, over whatever descriptions happen to be present now. And
a role's tags are only ever as good as the description that was captured while it was open;
once it closes, that text is frozen. If persisted tags are wanted, this lane owns the column
and `render` owns what goes in it.

### Shared plumbing — read freely, change loudly

`pipeline/`: `notes.py` `verdicts.py` `identity_gate.py` `identity_facts.py`
`company_identity.py` `atomic.py` `http.py` `companies.py` `stages.py` `sources.py`
`llm.py`. Eleven modules; `docs/MODULES.md` marks the same eleven `**shared**`, and
`llm.py` is on this list because it is the ONE process seam to Claude in the whole repo —
the `classifier` row below names it but does not own it. Every lane imports these and no
lane owns them. If your change needs one modified, **say so in your report and name the
lanes it could affect** — `identity_gate` gates every write path that activates a row in
`companies.csv` (`company_identity` supplies its primitives and is inert on every ATS host
by design).

`pipeline/run.py` is the orchestrator: `infra` owns it, but any lane may need a hook in it.
Propose the hook, do not smuggle it.

### Not in any lane (deliberately)

**`docs/MODULES.md` classifies every root module**, and `docs/check_docs.py`
fails the test suite if a new one is unclassified. 25 are `legacy` — one-shot captures,
probes and superseded resolvers — and nothing scheduled imports any of them; the linter
proves that on every push rather than asking you to trust it. Do not spend time there.

The trap the registry exists for: 9 modules are `library` — **no workflow runs them and live
code imports them**, so they look dead in the Actions history. `ingest_research` and
`probe_ats` were on an earlier "safe to delete" list while `retry_unreachable.py` (02:30
daily) imports the first, which imports the second.

## Shared, finite, and easy to exhaust

Declare these in your plan before spending them:

- **Bright Data credits** — the Web Unlocker and the LinkedIn/Indeed datasets. Every
  discovery run, JD enrichment pass and unlocker search spends them. Budget env vars exist
  (`JD_ENRICH_BD_CAP`, `MATCHED_JD_BD_CAP`, `DEEP_BD_SEARCH_CAP`); use them.
- **SerpApi — exhausted until 2026-09-01.** Anything relying on it silently returns nothing.
  The working search is `deep_validate.google_via_unlocker`.
- **`CLAUDE_CODE_OAUTH_TOKEN`** — one subscription, shared by role classification, company
  blurbs, firmographics research and LLM extraction. Symptom of expiry: `LLM calls this
  run: 0` with a large `llm_failed_fallback` count.
- **GitHub Actions concurrency group `repo-state`** — eight of the nine scheduled workflows
  share it (all but `daily-digest.yml`, which has its own). A long job makes the next one
  queue or be superseded, with no error anywhere.
- **DuckDuckGo is rate-limited from this machine, not blocked** — it answers, then returns
  zero for the same query minutes later (measured: `ddg("Wix")` gave 4 URLs, then 0). Treat
  it as a rung that sometimes answers, never the only one. It is reliable on the runners.

## Rules that will bite you

1. **A green workflow means nothing.** **44+ of the workflow steps** are `continue-on-error`.
   Read the step output; confirm a capability did work by looking at what it produced.
2. **A mass-zero result is a broken run, not a measurement.** Strip its verdicts, diagnose,
   re-run.
3. **Never `git add -A`** — another lane's work is in this tree. Stage explicit paths.
4. **`python check_invariants.py` must pass before you commit** anything touching
   `companies.csv`. `python -m pytest` must pass before any push — **not `-q`**, which
   `pytest.ini` already sets, so a second one hides the `N failed, M passed` line. Every
   one of them is a bug that shipped; if one goes red, your change is wrong. `pytest` also
   runs `docs/check_docs.py`, so a doc that names a file you deleted fails the suite.
   Asking "why was company X activated or refused?" is one command, offline:
   `python registry_health.py --explain "<name>"` (add `--fetch` for the one page GET).
5. **Say which run mode you are in, and never copy `secrets.env` into a worktree.**
   The ceiling is `python -m pipeline.bd_budget`, never a number written in prose: it is
   **unlimited through 2026-08-31 and 5,000/month from 2026-09-01**, no rollover, and both
   sides of that boundary are pinned by a guard so the rule changes itself on the day
   (`pipeline/bd_budget.py`; this rule quoted "5,000, ~6,798 already used, permanent and
   unrecoverable" for two days after the operator replaced it). There are two modes:

   **Dry** — no `secrets.env`, `JD_BD=0 BD_RUN_CAP=0`. Every paid rung is **disarmed**, and
   that is the trap: a disarmed rung does not error, it returns a refusal. A zero or a
   "dead" from a dry worktree **is not evidence** — one such pass wrote 57 of 57 rows dead.
   Never write a `dead` / `parked` / `zero-confirm` verdict from one.

   **Armed** — reference the operator's file where it is, never copy it into a worktree,
   and set `BD_RUN_CAP=<n>` explicitly: **unset means no cap**, `0` means buy nothing. A
   copy is an uncapped spender in a tree nobody is watching, and from 2026-09-01 ten
   concurrent sessions at `PAGE_UNLOCK_BUDGET` = **100** each is the month's pool in five
   days. `python -m pytest` can no longer spend (`tests/conftest.py` bans the transport);
   `python -m pipeline.run` still can — it arms the key inside `run()` and `JD_BD` defaults
   to **1 = spending**. Declare what you spent when you hand back.
6. **Commit as `ajil-bot` and push with plain `git push`.** Read `CLAUDE.local.md` first —
   the public repos must not be linkable to the owner's personal account.
7. **Prefer letting the crons run.** If you must dispatch a workflow manually, delete the run
   record afterwards (`CLAUDE.local.md` §3). If you cancel a digest run, cancel it **before**
   the `Mark digested roles as sent` step, or that run's roles are burned as delivered and
   the next run will not email them.
8. Local runs never email and never publish: `python -m pipeline.run --only "Wix,Fiverr"
   --no-llm --db /tmp/scratch.db` writes `out/docs-preview/` and nothing else. **"Safe" is
   about delivery, not about money** — this line used to say "safe by default", and it is not:
   `--no-llm` does not turn off `JD_BD`, which defaults to **1 = spending**. Add `JD_BD=0
   BD_RUN_CAP=0` (rule 5).

## The `docs` lane — standing brief

Fixed goal: **a visitor understands what this does and how the flow hangs together in ten
minutes; an agent knows where to start in twenty.** As of 2026-08-23 the structure for that
exists — `CLAUDE.md` (2 min) then this brief (20 min) then the lane's own files — and the
job is now to keep it true, not to build it.

**What this lane owns.** `README.md` (the visitor), `CLAUDE.md` (the agent's first two
minutes), `ARCHITECTURE.md` (the model), `HANDOFF.md`'s shape and cap, `docs/*` including
`docs/MODULES.md` and `docs/check_docs.py`. **Other lanes own their content in these files;
this lane owns the container and the enforcement.**

**The enforcement, so honesty is not a matter of goodwill.** `docs/check_docs.py` runs in
`tests/test_units.py::test_docs_are_consistent_with_the_code`, so `tests.yml` fails on every
push if:

| the check | what it catches |
|---|---|
| **derived facts** | a number a doc states drifting from the code — 9 registered facts, 18 sites. EXACT facts (`len(FETCHERS)`, module counts, the c-o-e ratio) are held to equality, because only a push moves them. CENSUS facts (active rows, registry rows) move when a cron ran and nobody pushed, so since 2026-08-28 they are held ONE-SIDED: the site writes a FLOOR, `N+`, and only a COLLAPSE through it is an error — a bare number and a two-sided band are both refused, because widening a band is the move that deletes the alarm. A count no decision turns on carries the command instead, the way the profile count now does: `python -c "import json;print(len(json.load(open('cloud_state/firmographics.json',encoding='utf-8'))))"`. `--facts` prints all of them |
| **product scope** | a doc, or a rendered string, promising a filter the classifier does not enforce. The facts registry above checks NUMBERS; this is the first check of a CLAIM, and it exists because there was none: on 2026-08-28 the experience bar was removed and six live surfaces went on advertising it all day, including the line that becomes the mail's subject, with this linter green throughout. Two-way, and decided by the code — `check_scope_claims` AST-reads the SHIPPED default of `pipeline/seniority.py`'s `EXPERIENCE_BAR` (never imports it, and never reads the live global, which `CLASSIFY_EXPERIENCE_BAR=1` would flip). Bar off ⇒ no surface may state the retired promise **and** `README.md`/`CLAUDE.md`/`ARCHITECTURE.md` must each say what replaced it, so deleting the sentence is not a way to go green |
| **the backlog index** | a stale per-lane index, or an item naming a lane that does not exist |
| **morning checks** | a prediction stated in prose where nobody can answer it, or a verdict a reader cannot check |
| paths exist | a doc naming a file that was renamed or deleted |
| links resolve | a dead cross-reference between docs |
| section references | an `ARCHITECTURE.md` §N pointer left behind by a renumber |
| the module registry | a new root script nobody classified; a `legacy` module live code imports; a `scheduled` module no workflow runs |
| the cron table | `ARCHITECTURE.md` §4 and the workflow files disagreeing, in either direction |
| the continue-on-error ratio | the "a green run proves nothing" number drifting from the workflows |
| the HANDOFF shape | the current-state file growing back into an archive — the **caps** (250 lines / 3,200 words / 60 per line) are a **pre-push** gate since 2026-09-01, not a CI one: with five sessions appending, what CI caught was a race, reddening master for every other lane over prose three times on 08-31 (+1, +3, +6 words). A missing section is nobody's race and still fails on a runner |

It still cannot check whether a *sentence* is true — only that what it points at exists and
that every number it registers agrees with the code. The rest needs a reader, and the
measure of how much rest there is: three Opus attackers reading these documents against
the tree on 2026-08-27 found **46 measured contradictions**, every one of them green under
the linter that morning. Among them: a "rolling 2-week board" that selects
`get_matched_since("0000-01-01")`, a per-company board cap that has never existed, and a
local command printed under "without side effects" that overwrites the published board.

**Constraints: documentation only.** Do not "tidy" code in this lane — a rename here breaks
four other lanes silently. `docs/check_docs.py` is the one exception, and it only reads.
When you move text, **move it** — do not rewrite it from memory. Every claim must be checked
against the code or a live run.

**The lane's tools.** `docs/check_docs.py` and `docs/backlog.py` are both owned here, both
read-only unless given an explicit write flag, both stdlib-only, and neither imports
anything from `pipeline/`. That is the carve-out from "documentation only": this lane may
own a tool that *reads* the code to check a document, and nothing else.

**What is left in this lane, 2026-08-27.** The 32 unreferenced root modules are still
classified but not relocated — moving a file is a code change. `docs/TAGGING.md`,
`docs/BRIGHTDATA.md` and `docs/ATS_PLATFORMS.md` were re-verified line by line on
2026-08-27 and corrected; `docs/POC_COMPANY_PROFILES.md` is a dated POC report that belongs
in `docs/decisions/` (`docs/BACKLOG.md` 296). The automation inventory this paragraph used
to ask for is `docs/AUTOMATION.md`. Open, with numbers, in `python docs/backlog.py lane
docs`.

## Definition of done

Everything in this section used to be process — tests green, docs updated, a line in
`HANDOFF.md`, an item filed. Every clause was about not breaking things and none was about
achieving anything, and a lane could satisfy all of them having drained nothing. That is what
the finish line was rewarding: on 2026-08-30 six lanes were optimising for auditability,
because auditability was what it asked for.

The product is four empty queues: **companies resolved, intel complete, every open role
carrying its description, and a public dataset somebody can use.** A session is done when its
queue is shorter than it found it.

### 1. The number moved

**Name the queue your lane owns (the table above), state where you left it, and measure that
AFTER the push.** A closed backlog item that does not move the number is reported as **"not
done"** — say so plainly in your `HANDOFF.md` line. Three items closed and a green suite is
not an outcome; `jd-text` closed three on 2026-08-29 while its own number did not move.

If the number went the wrong way, say that too, with both readings. A lane that reports only
the direction it likes is a lane nobody can plan around.

### 2. It keeps moving without a session — and this is a delivery bar, not a wish

The standard is not "the queue reached zero". It is **"this flows automatically in git from
now on."** A lane whose number falls only while a session is running has **not delivered**,
however far it fell, and must say those words — *not delivered: still a hand-drain* — rather
than reporting the drained number as a result. A number that only moves while an agent
watches is a demo: the queue refills the night after the session ends and the next lane
re-derives the same work.

So name three things, concretely:

| | what to name | if it does not exist |
|---|---|---|
| **the workflow** | the `.github/workflows/*.yml` job that moves this number with nobody watching | that gap **is your remaining work** |
| **the cadence** | its cron, and the unattended run that proved it — `event: schedule`, and a `headSha` your commit is an ancestor of (`gh run view <id> --json event,headSha`) | a workflow that has never fired unattended is a workflow you have not tested |
| **the alarm** | what fires, **where a human reads daily**, when it stops or falls behind — a `Stages:` clause in the mail, not a line on a run page nobody opens | an unalarmed cron is a cron that will stop silently, and this repo has lost four of them that way |

**All three, or the lane is not done.** Any one of them missing is the lane's real remaining
work — not the backlog items around it, and not the number you drained by hand this evening.

**If the fix needs a workflow change, that is `infra`'s file and you may not write it.** Then
the deliverable is the **exact diff**: the file, the anchor, the lines, filed in
`docs/BACKLOG.md` with the lane set to `infra` — and your report says plainly that **until
`infra` applies it, nothing is automatic.** A proposal is not a cron; say which one you have.

### 3. Nothing broke — the price of admission, not the achievement

- `python -m pytest`, `python check_invariants.py` and `python docs/check_docs.py` green
  **from a clean worktree at `origin/master` after the push** — paste the **counts**, not the
  word "green": `N passed`, the row/active/orphan line, `N error(s), M warning(s)`.
- Green **in CI on the commit you pushed** — **quote the run id AND its conclusion, whatever
  it is.** A `cancelled` run is not a soft pass and not a missing datum: **it names nothing**,
  because the job died before it could judge anything, and it must be reported in those
  words. When CI cannot reach a verdict — as it could not on 2026-08-30, when four
  consecutive pushes were cancelled on the `guard` job's own 10-minute timeout (`442`) —
  write **"UNVERIFIED IN CI"** and why, in `HANDOFF.md`. **Never write "green" for a commit
  no runner judged**, and never quote a passing sub-step as if it were the verdict: the step
  that concerns you passing is worth saying, and it is not the same claim. Green where you ran it is a
  different suite: `tests.yml` was red on **100 consecutive runs** to 2026-08-30 while every
  lane reported a passing one, and three guards that passed on every laptop failed on every
  push. If it was already red when you arrived, say so with the run id, so the next session
  knows what it inherited.
- A new guard for any bug you fixed (`tests/test_units.py` is a list of shipped bugs, one
  assertion each), the docs your change touched updated **in the same commit**, and what you
  left for someone else and what you spent (BD credits, LLM calls).

**Reporting this section as the outcome is the mistake the section exists to stop.**

### 4. The change is smaller than the problem — evidence, not a verdict

**Clause 1 outranks this one.** A queue that drained on an ugly fix beats a beautiful change
that moved nothing, and nothing here decides whether your number counts. It decides what your
report must contain, because "as elegant as possible" has sat in every spawn prompt as an
aspiration with nothing behind it, and the tree shows what an aspiration buys: three copies
of `_load_secrets` still in the tree the evening `infra` shipped the one loader
(`pipeline/secretsenv.py`) and filed the three-line diff to remove them (`468`) — five commits
landed on `pipeline/jdfill.py` that day, the file with one of the copies, and none applied it;
two enrichers of 491 and 665 lines over one library (`enrich_scrape_jd.py`,
`enrich_matched_jd.py` over `pipeline/jdfill.py`); seven hand-maintained vocabularies in
`pipeline/roleprofile.py`, four with a parallel `*_DESC` dict kept in step by hand; a
registry state machine written as English prose inside a 220-character `notes` cell; and an
`ARCHITECTURE.md` section titled *"what this codebase does instead of erroring"*. Every one was
added by a session whose number moved and whose gates were green.

"Well-crafted" is a judgement and this repo's discipline is measurement, so the questions
below each name the artefact that answers them. Answer them in your report; they are not
rhetorical, and "n/a" is an answer only with the reason beside it.

| the question | what answers it |
|---|---|
| **What did you delete or unify?** A change that only adds grows the thing everyone agrees is too big. | `git diff --stat origin/master...HEAD` — the `+`/`−` totals. If `−` is 0, say so and say why that was right this time |
| **Which existing function did you extend, and which did you decline to duplicate?** | its name, and `grep -n "def <name>"`. If you found none, say where you looked — this codebase hides its seams (`pipeline/secretsenv.py` existed for a day while three copies were edited around it) |
| **What design did you reject, and on what evidence?** A choice with no rejected alternative was not a choice. | the alternative in one line, and the number that killed it — the way `docs/sessions/2026-08-30-docs-ci.md` rejects a pinned count with "it broke within a day and took the registry gate down with it" |
| **Would the next session find this?** Not "is it documented" — would someone looking for this behaviour land on your code, or on the thing it replaced? | the `grep` they would type, and what it hits first. If it hits the old thing, the old thing is not gone |
| **What did you make harder for the next lane?** A new flag, a new file, a new state-file key, a new place a future reader must know about. | count them, and name each. Do not pretend there wasn't one; the only change with no cost is a deletion |

The last question is the one no linter can ask, which is why it is in the report and not in
`docs/check_docs.py`. The first four are checkable, and a report that answers them with
adjectives instead of the artefact in the right-hand column has not answered them.

### Debt in another lane's file — what you do when you find it

Every lane is told "write only your lane's files". That is right for safety, and it is why
duplication here never dies: **filing it is the current answer, and it measurably does not
work** — `438` named the four `_load_secrets` copies on 2026-08-29, `468` carried the exact
three-line replacement for each by the morning of 08-30, and the copies outlived every
session that opened those files that day. So, two rules, and the linter holds the second:

1. **A unification may cross lanes.** When you replace N copies with one function, **delete
   the copies in the same commit.** A behaviour-preserving substitution of a function body,
   suite green, is not "writing another lane's file" — it is finishing your own change, and
   leaving the copies is what leaves the repo bigger than you found it. Name the lanes in your
   `HANDOFF.md` line. If the owning lane is mid-edit, the rebase conflict is its signal, and
   git already delivers it. (This is the rule that would have killed the four copies: `infra`
   had the loader, the diff and a green suite on 08-30, and the old rule told it to file.)
2. **A filed diff is applied by the next lane to open that file.** If you commit to a file
   that carries an OPEN `docs/BACKLOG.md` item with a fenced diff naming that file, apply it
   in your commit — or cite the item's number in the `HANDOFF.md` line you add and say why
   not. `docs/check_docs.py` (`check_debt_on_touched_files`) fails the push otherwise;
   `python docs/check_docs.py --debt` lists what is owed today, and that count is the `docs`
   lane's number.

Rejected, with the measurement: a **standing cleanup lane** (a session writing every other
lane's files is the concurrency hazard the split exists to prevent, and this lane's own
"do not tidy code" rule was written after one rename broke four lanes); **"file it with the
diff"** on its own (that is `468`, and it survived five commits to its target file); a
**periodic audit** (finds, does not kill — `438` was an audit finding, and the copies are
still here).

### Where a change gets written down

Not optional, and not a separate task at the end: a change that is not written down is a
change the next session re-derives from the code, or worse, contradicts.

| you changed | write it in |
|---|---|
| behaviour of a step | the `ARCHITECTURE.md` section tagged with your lane |
| a rule that would cost data to re-learn | `ARCHITECTURE.md` §2 or §8 |
| a schedule or a workflow | the §4 cron table (the linter will make you) |
| a new root module, or a module's status | `docs/MODULES.md` (the linter will make you) |
| something you found broken and did NOT fix | `docs/BACKLOG.md`, with the lane that would own it |
| what you did this session | `HANDOFF.md`, three lines; the long version in `docs/sessions/` |
| a tag on a role card | `docs/TAGGING.md` |
| a decision you made, and the alternatives you rejected | `docs/decisions/<date>-<topic>.md` |

Anything a future reader would have to run the code to discover belongs in a doc. Anything
a future reader can discover by running one command belongs in a doc **as that command**.
