@echo off
rem Fake claude for rehearsals. FAKE_CLAUDE = json | unknown | prose | fail | sleep
set MODE=%FAKE_CLAUDE%
if "%MODE%"=="" set MODE=json
echo %date% %time% mode=%MODE% args=%* >> "%FAKE_CLAUDE_LOG%"
if "%MODE%"=="fail" ( echo Not logged in . Please run /login & exit /b 1 )
if "%MODE%"=="sleep" ( ping -n 400 127.0.0.1 >nul & exit /b 0 )
if "%MODE%"=="unknown" (
  echo %*| findstr /C:"allowedTools" >nul && ( echo {"unknown": true} ) || ( echo UNKNOWN )
  exit /b 0 )
if "%MODE%"=="prose" ( echo I'm not sure which company you mean, but {something} might match. & exit /b 0 )
echo %*| findstr /C:"allowedTools" >nul && (
  echo {"sector": "fintech", "sub_sector": "fake niche", "stage": "growth-private", "stage_note": "fake", "size_band": "S", "employees_global": 42, "founded": 2015, "business_model": "fake SaaS subscriptions", "customer_type": "SMBs", "il_center": "Tel Aviv (HQ)"}
) || (
  echo FakeCo builds fake things for fake customers. It makes money from fake subscriptions.
)
exit /b 0
