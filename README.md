# AnalystJobsIL pipeline

A free job board of experienced (**≈3+ years**) data-analyst / BI / analytics openings at
Israeli high-tech companies, and a daily email of what is new.

- **The board** → https://analystjobsil.github.io/board/ — every role we can still see at
  its employer, searchable, with company facts on each card. Most are read from the
  employer's own careers page; a minority arrive through the discovery net (below) and link
  to the post there.
- **The archive** → https://analystjobsil.github.io/board/archive.html — roles that have
  come off their employer's page. Nothing is deleted.
- **The email** — once a day, only roles posted in the last 48h, grouped by company.

The point of the design: **an employer's own careers board is the source of truth, not an
aggregator's copy of it.** The pipeline reads ~900 companies' *own* boards every morning —
about half through a native ATS API (Comeet, Greenhouse, Lever, SmartRecruiters, Recruitee,
Ashby, Workday, Oracle HCM and 9 more), the rest by rendering the page — out of a registry of
1,200–1,300 rows, filters to Israel-located analytics roles, and publishes what it can still
verify. The API/page split moves every day, because moving a row from one to the other is
the whole job of the coverage machinery; `python registry_health.py --census` prints today's.
Every company row carries a dated verdict explaining what we know about it — including the
claim "this company has no open roles", which is the claim most job boards get wrong.

It runs entirely on GitHub Actions cron jobs. There is no server.

## How a job gets from a company's careers page to your inbox

```
 1 INTAKE      LinkedIn · Indeed · Telegram sweeps find roles and new employer names
    │          discovery_daily.py · discovery_telegram.py
    ▼
 2 REGISTRY    resolve each employer to a readable careers board, or park it with a
    │          reason. companies.csv — registry_health.py --census prints today's split
    ▼
 3 FETCH       a native ATS API · the page, rendered · and 1 synthetic row
    │          that reads the discovery cache
    ▼
 4 ENRICH      fetch the full job description · research the company
    │          (sector, stage, size, founded, Israel centre)
    ▼
 5 CLASSIFY    is it in Israel? is it ≈3+ years of analytics work?
    │          deterministic keyword rules, then an LLM for the ambiguous ones
    ▼
 6 RENDER      the board, the archive, the email, every tag on a role card
    │
    ▼
 7 DELIVER     publish the board · relay the email · commit the day's state
```

No count above is hard-coded: `python registry_health.py --census` prints the registry
split, `python check_invariants.py` prints rows and active rows, and `docs/check_docs.py`
fails the build if a number in this file drifts from the code (see `--facts`).

**What counts as a role:** experienced data/BI/product/marketing analytics and analytics
leadership. The title does not matter — a "Data Scientist" posting counts if the work is
really product analytics. Out: core ML, data engineering, software engineering, FP&A,
security/SOC, and anything junior/intern/entry-level. The full product decision, and the
code that implements it, are in `ARCHITECTURE.md` §0.

## Reading this repo

| you are | start at |
|---|---|
| a visitor | this file, then `ARCHITECTURE.md` §0 |
| an agent or a returning maintainer | `CLAUDE.md` (2 minutes), then `docs/AGENT_BRIEF.md` |
| asking "what re-checks this row / why did company X vanish / which ATS should we build" | `python registry_health.py` |
| debugging "why isn't company X in my email?" | `ARCHITECTURE.md` §5b |
| adding a company or an ATS platform | `docs/ATS_PLATFORMS.md`, then `ARCHITECTURE.md` §6 |
| wondering what a root script is for | `docs/MODULES.md` |

| file | what it is |
|---|---|
| `CLAUDE.md` | the 2-minute orientation; loaded automatically by Claude Code |
| `ARCHITECTURE.md` | the durable system model, the rules, the runbooks |
| `HANDOFF.md` | current state: what changed last session, what is known-broken |
| `docs/AGENT_BRIEF.md` | the eleven lanes and which files each may write |
| `docs/MODULES.md` | every module, what it does, and whether it is still live |
| `docs/BACKLOG.md` | known gaps that outlive a session |
| `docs/TAGGING.md` | every tag on a role card and where it is computed |
| `docs/BRIGHTDATA.md` | the Web Unlocker setup and the one shared credit pool |
| `docs/AUTOMATION.md` | every scheduled job, what it spends, and when it actually ran |
| `docs/RUN_LOG.md` | every line a digest can print, and every LLM seam it may spend |
| `docs/ATS_PLATFORMS.md` | `companies.csv` columns and the per-platform API URL patterns |
| `docs/sessions/` | what past sessions found, in their own words |
| `docs/decisions/` | superseded design decisions, kept for the record |

## The code

`pipeline/` is a zero-dependency (stdlib-only) Python package — the digest run itself:

- `http.py` — GET/POST JSON with retry/backoff.
- `fetchers.py` — one normalizer per ATS platform → the common job shape.
- `israel.py` — deterministic Israel-location filter (country code, then place-name scan).
- `seniority.py` — keyword tier, then one bounded, tool-less `claude -p` for the residue the keywords cannot decide (title-agnostic; `ARCHITECTURE.md` §7b).
- `store.py` — SQLite seen-store (across-day dedup + cross-platform merge) + LLM cache.
- `digest.py` — the board, the archive and the email, with an auditable run summary.
- `run.py` — the orchestrator. A **scoped** `python -m pipeline.run --only ...` produces
  `out/digest-<date>.{html,txt,md,json}` and `out/docs-preview/`, and never emails or
  publishes. An unscoped one still never emails, but it does overwrite the published board.

The 70 scripts at the repo root are the coverage machinery: resolvers, hunts, audits and
one-shot probes. `docs/MODULES.md` says which are scheduled, which are libraries, which are
operator tools and which are dead weight — 30 of them are reachable from no workflow, no
test and no live import.

### Run it locally without touching anything shared

```bash
python -m pipeline.run --only "Fiverr,Wix" --no-llm   # produce-only; writes out/docs-preview/
python -m pipeline.run --only "Wix" --db /tmp/scratch.db   # ...and not the real seen-store
python scrape_universal.py "Company" "https://…/careers"
python audit_empty_rows.py                            # dry-run; --apply to write
python -m pytest && python check_invariants.py && python docs/check_docs.py   # not -q: pytest.ini sets it
```

Most tools are dry-run by default and take `--apply` to write. A local run cannot email
anyone: publishing and relaying are separate workflow steps. **`--only`/`--limit` is what
makes a run harmless, not `--db`** — an unscoped run overwrites the published `docs/index.html`
and `docs/archive.html`.

**Where aggregators do and do not appear.** Glassdoor is not used at all. LinkedIn and Indeed
are used as a *discovery net* (`discovery_daily.py`, via Bright Data): they are how we learn
that an employer we have never heard of is hiring, and that employer then gets resolved to its
own careers board and scanned directly from then on. They are never the primary source for a
company we already cover. One synthetic `Discovery` registry row does publish postings we have
only seen there, so a minority of board cards link to a LinkedIn or Indeed post rather than to
the employer's own page — on 2026-08-27 that was 18 of 76 live cards, and 25 if you count a
third aggregator host (`secrettelaviv.com`) that a registry row currently points at. That is
a deliberate coverage trade, not an oversight: the alternative is dropping a real Israeli
analytics opening because its employer has no readable board yet.
