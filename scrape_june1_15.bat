@echo off
cd /d "%~dp0"
echo Scraping 1.-15.6.2026...
python daily_golf_update.py 2026-06-01 2026-06-15
echo.
echo Hotovo! Stiskni libovolnou klavesu.
pause
