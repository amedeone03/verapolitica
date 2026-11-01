@echo off
rem VeraPolitica: load every region, province and municipality from ISTAT and
rem propose the parties of the current Chamber, party logos and coats of arms from Wikidata/Wikimedia Commons.
rem Needs internet. Logos arrive in the redazione queue: they go public only
rem after a redazione member approves them (/redazione/#/coda).
rem Usage from the repository root:  scripts\sync_reference_data.cmd
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "VERAPOLITICA_DATABASE_URL=sqlite:///./data/demo/verapolitica_demo.db"
set "VERAPOLITICA_RAW_STORAGE_PATH=./data/demo/raw"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\run_demo.cmd once first: it creates the Python environment.
  pause
  exit /b 1
)
echo === ISTAT: regions, provinces and municipalities ===
".venv\Scripts\python.exe" -m scripts.run_territorial_ingestion territories --live
if errorlevel 1 (
  echo ISTAT download failed. Check the internet connection and retry.
  pause
  exit /b 1
)
echo === Wikidata / Commons: logos and coats of arms (proposals for the redazione) ===
".venv\Scripts\python.exe" -m scripts.sync_symbols --parties
pause
