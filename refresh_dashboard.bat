@echo off
cd /d "%~dp0"
"venv\Scripts\python.exe" refresh_dashboard.py >> logs\refresh_dashboard.log 2>&1
