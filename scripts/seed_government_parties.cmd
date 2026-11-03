@echo off
rem VeraPolitica: put Government and main opposition parties in the list, with
rem their logos (free-licence files from Wikimedia Commons). Needs internet.
rem The redazione can change name, abbreviation, website and logo at any time
rem from /redazione/#/simboli.
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "VERAPOLITICA_DATABASE_URL=sqlite:///./data/demo/verapolitica_demo.db"
set "VERAPOLITICA_RAW_STORAGE_PATH=./data/demo/raw"
".venv\Scripts\python.exe" -m scripts.seed_government_parties --approver "Direzione VeraPolitica"
pause
