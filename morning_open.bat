@echo off
cd /d "C:\Users\ERC\stock-dashboard"
git pull --rebase --autostash origin main >nul 2>&1
"C:\Program Files\Python312\python.exe" weekly_marketing.py
"C:\Program Files\Python312\python.exe" etf_check.py >nul 2>&1
"C:\Program Files\Python312\python.exe" morning_page.py
