@echo off
cd /d "%~dp0"
"venv\Scripts\python.exe" run_hourly.py >> logs\run_hourly.log 2>&1
