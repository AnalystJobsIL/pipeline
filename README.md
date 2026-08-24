# AnalystJobsIL pipeline

A free job board of experienced (**≈3+ years**) data-analyst / BI / analytics openings at
Israeli high-tech companies, and a daily email of what is new.

- **The board** → https://analystjobsil.github.io/board/ — every role we can still see on
  its employer's own careers page, searchable, with company facts on each card.
- **The archive** → https://analystjobsil.github.io/board/archive.html — roles that have
  come off their employer's page. Nothing is deleted.
- **The email** — once a day, only roles posted in the last 48h, grouped by company.

The point of the design: **we do not scrape aggregators.** The pipeline reads 846 companies'
*own* careers boards every morning — 433 through a native ATS API (Comeet, Greenhouse, Lever,
SmartRecruiters, Recruitee, Ashby, Workday, Oracle HCM and 8 more) and 412 by rendering the
page, out of a ~1,200-row registry — filters to Israel-located analytics roles, and publishes
what it can still verify. Every company row carries a dated verdict explaining what we know
about it — including the claim "this company has no open roles", which is the claim most
job boards get wrong.

It runs entirely on GitHub Actions cron jobs. There is no server.

## How a job gets from a company's careers page to your inbox

```
 1 INTAKE      LinkedIn · Indeed · Telegram sweeps find roles and new employer names
    │          discovery_daily.py · discovery_telegram.py
    ▼
 2 REGISTRY    resolve each employer to a readable careers board, or park it with a
    │          reason. companies.csv — ~1,200 rows (check_invariants.py prints today's split)
    ▼
 3 FETCH       433 rows via a native ATS API · 412 rendered from the page ·
    │          1 synthetic row that reads the discovery cache
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

Counts are from 2026-08-23 and drift daily; `ARCHITECTURE.md` §5c has the snippets that
re-derive them.

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
| debugging "why isn't company X in my email?" | `ARCHITECTURE.md` §5b |
| adding a company or an ATS platform | `docs/ATS_PLATFORMS.md`, then `ARCHITECTURE.md` §6 |
| wondering what a root script is for | `docs/MODULES.md` |

| file | what it is |
|---|---|
| `CLAUDE.md` | the 2-minute orientation; loaded automatically by Claude Code |
| `ARCHITECTURE.md` | the durable system model, the rules, the runbooks |
| `HANDOFF.md` | current state: what changed last session, what is known-broken |
| `docs/AGENT_BRIEF.md` | the ten lanes and which files each may write |
| `docs/MODULES.md` | every module, what it does, and whether it is still live |
| `docs/BACKLOG.md` | known gaps that outlive a session |
| `docs/TAGGING.md` | every tag on a role card and where it is computed |
| `docs/BRIGHTDATA.md` | the Web Unlocker setup and budget |
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
- `run.py` — the orchestrator. `python -m pipeline.run` produces
  `out/digest-<date>.{html,txt,json}` and **never** emails or publishes.

The ~67 scripts at the repo root are the coverage machinery: resolvers, hunts, audits and
one-shot probes. `docs/MODULES.md` says which are scheduled, which are libraries, which are
operator tools and which are dead weight — 30 of them are reachable from no workflow, no
test and no live import.

### Run it locally without touching anything shared

```bash
python -m pipeline.run --only "Fiverr,Wix" --no-llm   # produce-only; writes out/docs-preview/
python -m pipeline.run --db /tmp/scratch.db           # don't touch the real seen-store
python scrape_universal.py "Company" "https://…/careers"
python audit_empty_rows.py                            # dry-run; --apply to write
python -m pytest -q && python check_invariants.py && python docs/check_docs.py
```

Most tools are dry-run by default and take `--apply` to write. A local run cannot email
anyone: publishing and relaying are separate workflow steps.

Deliberately excluded as scrape sources: Glassdoor and LinkedIn Jobs. Both aggressively block
automated access and enforce their ToS against scrapers, so they'd be fragile and legally risky
— the opposite of "deterministic." They're also aggregators, so anything posted there already
exists on the company's own career site, which is what this pipeline targets directly.
