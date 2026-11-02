@echo off
rem VeraPolitica: prepare the demo for the presentation to the redazione.
rem Party of each member of the Government (Wikidata), latest Senate bills,
rem news items from scripts\presentazione_notizie.json. Each item is approved by
rem a second member. A copy of the database is saved first. Needs internet.
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "VERAPOLITICA_DATABASE_URL=sqlite:///./data/demo/verapolitica_demo.db"
set "VERAPOLITICA_RAW_STORAGE_PATH=./data/demo/raw"
".venv\Scripts\python.exe" -m scripts.prepara_presentazione
echo.
echo Fatto. Ricarica la demo nel browser (ctrl+shift+r).
pause
