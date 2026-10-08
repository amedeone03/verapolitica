@echo off
rem VeraPolitica local demo launcher for Windows (cmd or PowerShell).
rem Usage from the repository root:  scripts\run_demo.cmd
setlocal
cd /d "%~dp0.."
title VeraPolitica demo
set "PYTHONUTF8=1"

if not exist ".venv\Scripts\python.exe" (
  echo === Creating the Python environment ===
  py -3.13 -m venv .venv
  if errorlevel 1 (
    echo Python 3.13 was not found. Install it with: py install 3.13
    pause
    exit /b 1
  )
)

echo === Installing dependencies ===
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r backend\requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo === Rebuilding the isolated demo data ===
".venv\Scripts\python.exe" -m scripts.prepare_demo
if errorlevel 1 (
  echo Demo preparation failed.
  pause
  exit /b 1
)

set "VERAPOLITICA_DATABASE_URL=sqlite:///./data/demo/verapolitica_demo.db"
set "VERAPOLITICA_RAW_STORAGE_PATH=./data/demo/raw"
set "VERAPOLITICA_ADMIN_API_KEY=verapolitica-demo-admin"
set "VERAPOLITICA_ADMIN_REVIEWER_IDENTITY=demo-presenter"

echo.
echo Starting VeraPolitica in DEMO-ONLY mode.
echo   Citizen site:     http://127.0.0.1:8000/app/
echo   Editorial demo:   http://127.0.0.1:8000/demo/
echo   API and Swagger:  http://127.0.0.1:8000/docs
echo Close this window or press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pause
