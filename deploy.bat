@echo off
cd /d "%~dp0"

echo [DEPLOY] Nahravam na GitHub...

git add index.html
git diff --cached --quiet && (
    echo [DEPLOY] Zadna zmena, neni co nahrat.
    goto :end
)

:: Datum + cas jako commit message
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set DATUM=%%c-%%b-%%a
for /f "tokens=1 delims=: " %%a in ('time /t') do set CAS=%%a
git commit -m "Aktualizace dat %DATUM% %CAS%"
git push origin main

echo [DEPLOY] Hotovo! Stranka se obnovi za ~30 sekund.

:end
