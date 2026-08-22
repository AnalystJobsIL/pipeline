@echo off
rem Full firmographics maintenance chain: profile missing -> LinkedIn employee fill ->
rem web verify/fill -> export. Idempotent; safe to run any time. Logs itself.
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
set LOG=state\firmo_chain.log
set PYTHONIOENCODING=utf-8
echo ==== chain start %date% %time% ==== >> %LOG%
rem CI's latest matched table is obtained by research_firmographics.py itself via
rem `git fetch` + blob extract (state\cloud_seen_fetch.db) — a worktree pull is NEVER
rem attempted: a dirty companies.csv (routine here) blocks --ff-only forever, silently.
"%PY%" -u research_firmographics.py --workers 3 >> %LOG% 2>&1
"%PY%" -u bd_employees.py >> %LOG% 2>&1
"%PY%" -u fill_employees_llm.py --workers 3 >> %LOG% 2>&1
"%PY%" -u research_firmographics.py --export >> %LOG% 2>&1
echo ==== chain done %date% %time% ==== >> %LOG%
