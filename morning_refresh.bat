@echo off
rem refresh the morning page (no popup) once the cloud briefing for today is out
cd /d "C:\Users\ERC\stock-dashboard"
"C:\Program Files\Python312\python.exe" morning_page.py --stale-page
if errorlevel 3 exit /b 0
git pull --rebase --autostash origin main >nul 2>&1
"C:\Program Files\Python312\python.exe" morning_page.py --refresh
exit /b 0
