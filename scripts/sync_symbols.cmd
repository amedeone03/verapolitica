@echo off
rem VeraPolitica: propose the parties of the current Chamber and the free-licence
rem logos and coats of arms from Wikidata/Commons. Needs internet. Everything
rem waits in the redazione queue (/redazione/#/coda) until a member approves it.
rem Run it again after approving new parties to fetch their logos.
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "VERAPOLITICA_DATABASE_URL=sqlite:///./data/demo/verapolitica_demo.db"
set "VERAPOLITICA_RAW_STORAGE_PATH=./data/demo/raw"
".venv\Scripts\python.exe" -m scripts.sync_symbols --parties
pause
