@echo off
rem 자정 쿼터 리셋 후 katSale 재스크래핑 재개 -> 패널 재구축 -> 140조합 CV 재튜닝
rem (2026-08-08 세션이 등록한 일회성 작업. schtasks /TN crop_resume_scrape)
cd /d "%~dp0src"
..\.venv\Scripts\python.exe -X utf8 scrape_jeonbuk_all_crops.py > ..\outputs\scrape_allcrops_run5.log 2>&1
if errorlevel 1 (
  echo scrape failed, aborting chain >> ..\outputs\scrape_allcrops_run5.log
  exit /b 1
)
..\.venv\Scripts\python.exe -X utf8 build_dataset.py > ..\outputs\build_run9.log 2>&1
..\.venv\Scripts\python.exe -X utf8 crop_county_cv.py > ..\outputs\crop_county_cv_run3.log 2>&1
echo CHAIN_DONE >> ..\outputs\scrape_allcrops_run5.log
