@echo off
rem ===========================================================================
rem  Lettuce daily scrape - auto resume after katSale quota reset (midnight KST)
rem
rem  NOTE: keep this file ASCII-only. cmd.exe reads .bat in the OEM codepage
rem  (cp949 here), so UTF-8 Korean comments get parsed as commands and the
rem  script breaks. Korean documentation lives in src/scrape_lettuce_daily.py.
rem
rem  Register:  schtasks /Query /TN lettuce_daily_resume
rem  Remove:    schtasks /Delete /TN lettuce_daily_resume /F
rem
rem  Why daily: katSale daily cap measured at ~1,900 requests. The remaining
rem  66 months x 23 markets needs ~2,131, so it cannot finish in one night.
rem  scrape_lettuce_daily.py records finished months in
rem  data\raw\lettuce_daily_state.json and stops itself on quota exhaustion,
rem  so running it daily resumes only the months still missing.
rem  Once everything is collected it prints "already complete" and exits.
rem ===========================================================================
setlocal
cd /d "%~dp0src" || exit /b 1
set "PY=..\.venv\Scripts\python.exe"
set "LOG=..\outputs\scrape_lettuce_daily_run1.log"

echo. >> "%LOG%"
echo ======== scheduled run start %date% %time% ======== >> "%LOG%"

rem -X utf8 so Korean print() does not die with UnicodeEncodeError on a cp949 console
"%PY%" -X utf8 scrape_lettuce_daily.py --start 2018-01 >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [sched] scraper exited with error - chain aborted >> "%LOG%"
  exit /b 1
)

rem Decide completion from the state file, not by grepping the log:
rem the log is append-mode, so an old "incomplete" line would match forever.
"%PY%" -X utf8 scrape_lettuce_daily.py --check-complete >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [sched] still incomplete - audit deferred to next run >> "%LOG%"
  exit /b 0
)

echo ======== complete - running audit ======== >> "%LOG%"
"%PY%" -X utf8 audit_lettuce_daily.py > ..\outputs\audit_lettuce_daily.log 2>&1
"%PY%" -X utf8 analyze_sampling_error.py > ..\outputs\sampling_error.log 2>&1
echo CHAIN_DONE >> "%LOG%"
endlocal
