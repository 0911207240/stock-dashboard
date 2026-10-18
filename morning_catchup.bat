@echo off
rem 登入或解鎖時補開晨報：08:00 後且今天還沒開過才執行
cd /d "C:\Users\ERC\stock-dashboard"
"C:\Program Files\Python312\python.exe" morning_page.py --needs-run
if errorlevel 3 exit /b 0
call morning_open.bat
