@echo off
rem Starter content-agenten (bruges af Windows Opgavestyring)
cd /d "%~dp0"
git pull -q 2>nul
python agent.py
echo.
pause
