# Scheduling the daily run (NOT YET ENABLED — needs your decision)

Per the project guardrails, no recurring live send is wired up until you (a) approve the
digest format and (b) pick a send mechanism. This doc lays out the options so you can choose.
`run_daily.ps1` already implements the deterministic, no-send core (git pull → produce digest).

## The one real decision: how does the email get SENT?

The pipeline itself is plain Python and runs fine unattended on this machine (the seniority
LLM fallback shells out to the local `claude -p`, which works headlessly). The only piece that
needs a channel is the actual email send. Three options:

### Option A — Gmail MCP via a scheduled Claude agent  (matches your original ask)
A Claude Code scheduled agent runs daily: it executes the pipeline, reads `out/digest-<date>.html`,
and sends it with the connected Gmail MCP tools, then runs `mark_sent.py`.
- ✅ Uses the Gmail connector you already have; no new credentials.
- ⚠️ Risk: headless/cron Claude runs may not have the claude.ai-authenticated Gmail MCP
  available (this exact caveat was flagged by the harness). Needs a test run to confirm.
- ⚠️ The agent must run on THIS machine (where companies.csv, the seen-store, and `claude -p`
  live), not a remote cloud agent.

### Option B — SMTP from Python via Windows Task Scheduler  (most deterministic)
A Windows Scheduled Task runs `run_daily.ps1` + a small `send_digest.py` that emails the HTML
over Gmail SMTP using an **app password** you create.
- ✅ Fully deterministic, no dependency on Claude being "up" at send time — best fit for the
  project's "as deterministic as possible" goal.
- ⚠️ Requires a Gmail App Password. **You must create it and put it in an env var yourself** —
  I will not handle credentials. (`GMAIL_USER`, `GMAIL_APP_PASSWORD`.)
- I can write `send_digest.py` (SMTP) whenever you say go.

### Option C — Hybrid
Task Scheduler produces the digest deterministically; a thin `claude -p` invocation does the
Gmail-MCP send. Same MCP-availability caveat as A. Usually not worth it over A or B.

## Recommendation
**Option B** for reliability (a job hunt digest that silently fails to send is worse than one
that's slightly less "magical"). Use **A** if you'd rather avoid an app password and are OK
with the MCP-availability caveat. Either way we should do one supervised live send first.

## Timing
Suggested: once daily at ~08:00 **Israel time**. NOTE: this machine's clock currently reports
**JST**, so schedule accordingly (08:00 Israel ≈ 14:00–15:00 JST depending on DST). Confirm the
machine's real timezone before setting the trigger.

## What's ready now
- `run_daily.ps1` — pull + produce (no send). Safe to run manually today.
- `mark_sent.py` — marks a produced digest's postings sent (run only AFTER a confirmed send).
- Still needed before go-live: your format approval, send-mechanism choice, and (for B) the
  app-password env vars + `send_digest.py`.
