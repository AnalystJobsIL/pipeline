# run_daily.ps1 — daily pipeline wrapper (PRODUCE ONLY; does NOT send email).
#
# This is the deterministic core of the daily job. It:
#   1. pulls the latest companies.csv from GitHub (so remote edits are picked up)
#   2. runs the pipeline to produce out/digest-<date>.{html,txt,json}
# It deliberately STOPS before sending. The send step is intentionally separate and is
# NOT wired up yet — that is gated on the user approving the digest format (see PROGRESS.md
# step 6) and choosing a send mechanism (see SCHEDULING.md).
#
# Usage (manual test):   powershell -File run_daily.ps1
# Later (scheduled):     register with Task Scheduler once the send step is agreed.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo

$log = Join-Path $repo ("state\run-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
New-Item -ItemType Directory -Force -Path (Join-Path $repo "state") | Out-Null

"[{0}] daily run start" -f (Get-Date -Format s) | Tee-Object -FilePath $log -Append

# 1. refresh companies.csv from the repo (fast-forward only; never clobber local work)
try {
    git pull --ff-only 2>&1 | Tee-Object -FilePath $log -Append
} catch {
    "git pull failed (continuing with local companies.csv): $_" | Tee-Object -FilePath $log -Append
}

# 2. produce the digest (uses claude -p for ambiguous titles; never sends)
python -m pipeline.run 2>&1 | Tee-Object -FilePath $log -Append

"[{0}] daily run done — digest produced in .\out (NOT sent)" -f (Get-Date -Format s) |
    Tee-Object -FilePath $log -Append
