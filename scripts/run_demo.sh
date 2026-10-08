#!/usr/bin/env bash
# VeraPolitica local demo launcher for macOS and Linux.
# Usage from the repository root:  ./scripts/run_demo.sh            (official data)
#                                  ./scripts/run_demo.sh synthetic  (synthetic fixtures)
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1

if [ ! -x .venv/bin/python ]; then
  echo "=== Creating the Python environment ==="
  PY=$(command -v python3.13 || command -v python3 || true)
  if [ -z "$PY" ]; then
    echo "Python 3.13 was not found. Install it with: brew install python@3.13"
    exit 1
  fi
  "$PY" -m venv .venv
fi

echo "=== Installing dependencies ==="
.venv/bin/python -m pip install --disable-pip-version-check -q -r backend/requirements.txt

if [ "${1:-}" = "synthetic" ]; then
  echo "=== Rebuilding the synthetic demo data ==="
  .venv/bin/python -m scripts.prepare_demo
else
  echo "=== Rebuilding the demo from official governo.it data ==="
  .venv/bin/python -m scripts.prepare_real_demo
fi

export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"
export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"
export VERAPOLITICA_ADMIN_API_KEY="verapolitica-demo-admin"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="demo-presenter"
export VERAPOLITICA_PORTRAITS_PATH="./data/demo/portraits.json"

echo
echo "Starting VeraPolitica in DEMO-ONLY mode."
echo "  Citizen site:     http://127.0.0.1:8000/app/"
echo "  Editorial demo:   http://127.0.0.1:8000/demo/"
echo "  API and Swagger:  http://127.0.0.1:8000/docs"
echo "Press Ctrl+C to stop."
echo
exec .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
