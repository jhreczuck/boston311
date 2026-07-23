@echo off
cd /d "%~dp0"
"venv\Scripts\python.exe" refresh_stg_boston_311.py >> logs\refresh_stg.log 2>&1
