@echo off
rem catch-up: open the morning page at logon/unlock if after 08:00 and not opened today
cd /d "C:\Users\ERC\stock-dashboard"
"C:\Program Files\Python312\python.exe" morning_page.py --needs-run
if errorlevel 3 exit /b 0
call morning_open.bat
