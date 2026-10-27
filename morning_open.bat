@echo off
cd /d "C:\Users\ERC\stock-dashboard"
git pull --rebase --autostash origin main >nul 2>&1
rem weekly_marketing takes ~25 min via claude -p; run hidden in background so the page opens first
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -WindowStyle Hidden -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'weekly_marketing.py' -WorkingDirectory 'C:\Users\ERC\stock-dashboard'"
"C:\Program Files\Python312\python.exe" etf_check.py >nul 2>&1
"C:\Program Files\Python312\python.exe" morning_page.py
