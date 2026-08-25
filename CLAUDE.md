# CLAUDE.md — read this first (2 minutes)

**What this repo is.** A daily pipeline that publishes a board of experienced (≈3+ yrs)
data-analyst / BI / analytics roles at Israeli companies, plus a daily email of the last
48h. It reads 846 companies' *own* careers boards every morning (out of a ~1,200-row
registry) — never aggregators — and runs entirely on GitHub Actions cron jobs. No server.
`README.md` has the visitor version; `ARCHITECTURE.md` is the system model.

**What ships every day.** 05:00 UTC `daily-digest.yml` → `docs/index.html` (the board,
published to `AnalystJobsIL/board`) + `digests/latest.md` → relayed as an email at 05:45 /
08:30 by the private `AnalystJobsIL/inbox` repo. `ARCHITECTURE.md` §4 is the only schedule
table in the repo and is checked against the real crons.

**The flow, and the file that owns each step.**

```
1 INTAKE   discovery_daily.py · discovery_telegram.py  → discovered_cache.json
2 REGISTRY auto_expand · listing_hunt · triage_dark …  → companies.csv  (verdict per row)
3 FETCH    pipeline/fetchers.py (API) · scrape_universal.py (page) → scraped_cache.json
4 ENRICH   pipeline/jdfill.py (job text) · pipeline/firmographics.py (company facts)
5 CLASSIFY pipeline/israel.py → pipeline/seniority.py (keywords, then `claude -p`)
6 RENDER   pipeline/digest.py · pipeline/roleprofile.py
7 DELIVER  persist_state.py (merge_csv_rows · merge_json_cache) · the workflows
```

## The five rules that cost real data to learn

Full versions in `ARCHITECTURE.md` §2 and §8. Short versions, because each of these has
already destroyed a day of work:

1. **A green workflow means nothing.** 35 of the 77 workflow steps are
   `continue-on-error: true`. Verify a capability by what it PRODUCED, and quote the number.
2. **A mass-zero result is a broken run, not a measurement.** Strip its verdicts, diagnose,
   re-run — do not let it commit.
3. **The `notes` column of `companies.csv` is an append-log.** Write it through
   `pipeline/notes.py`, never by hand. Overwriting a cell erases another tool's verdict and
   silently drops the row out of its re-check pool.
4. **Re-read `companies.csv` immediately before every write**, and match rows by company
   name, never by index. Two snapshot-writers destroy each other's verdicts.
5. **"There are Israel jobs on this page" is not "these are THIS company's jobs".** No row
   activates without `pipeline/identity_gate` (the gate; `company_identity` is only its
   primitives, inert on every ATS host by design).

## Working here

**Pick a lane before you touch anything: `docs/AGENT_BRIEF.md`.** It has the ten lanes, the
files each may write, the shared quotas, and the reading list. Two lanes (`registry`,
`infra`) allow only one session at a time. Other sessions may be running right now — **never
`git add -A`**, stage explicit paths.

Run anything locally without side effects:

```bash
python -m pipeline.run --only "Fiverr,Wix" --no-llm   # produce-only; writes out/docs-preview/
python -m pipeline.run --db /tmp/scratch.db           # don't touch the real seen-store
python audit_empty_rows.py                            # dry-run; --apply to write
```

Most root tools are dry-run by default. Several have no `if __name__ == "__main__"` guard,
so *importing* them runs them — `docs/MODULES.md` flags which.

**Shared and finite** (declare what you intend to spend): Bright Data credits,
`CLAUDE_CODE_OAUTH_TOKEN` (one subscription, four consumers), GitHub Actions concurrency
group `repo-state` (eight workflows share it). **SerpApi is exhausted until 2026-09-01** —
anything relying on it silently returns nothing; the working search is
`deep_validate.google_via_unlocker`.

## Before you push — the doc contract

1. `python -m pytest -q` and `python check_invariants.py` green. Every bug you fix gets an
   assertion in `tests/test_units.py`.
2. `python docs/check_docs.py` green. It fails if a doc names a file that no longer exists,
   if a link or an `ARCHITECTURE.md` §N pointer is broken, if a root module is missing from
   `docs/MODULES.md`, if the cron table disagrees with the workflows, or if `HANDOFF.md`
   grows past 250 lines.
3. **Update the doc your lane owns, in the same commit as the change.** Behaviour →
   `ARCHITECTURE.md` (the section is tagged with your lane). A new gap you did not fix →
   `docs/BACKLOG.md`. A new module → `docs/MODULES.md`. Always → three lines in
   `HANDOFF.md`: what was wrong, what you changed, **what you did NOT finish**.
4. Commit as `ajil-bot`, push with plain `git push`. **Read `CLAUDE.local.md` first** — it
   is gitignored and holds the identity rules for the public repos.
5. Don't dispatch or cancel workflows between 05:00 and 08:30 UTC. If you must cancel a
   digest run, cancel **before** `Mark digested roles as sent` — after that step its roles
   are burned as delivered and the next run will not email them.

A confident document that is no longer true is the failure this repo punishes hardest: the
old root SCHEDULING.md (now `docs/decisions/2026-08-14-email-delivery.md`) told readers the
daily email was unbuilt for three days after it started shipping, and nothing caught it.
Check every claim you write against the code or a live run.
