#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(dirname -- "$SCRIPT_DIR")
PYTHON="$REPOSITORY_ROOT/.venv/bin/python"
UVICORN="$REPOSITORY_ROOT/.venv/bin/uvicorn"

if [ ! -x "$PYTHON" ] || [ ! -x "$UVICORN" ]; then
  echo "Demo startup failed: create the repository .venv and install requirements first." >&2
  exit 1
fi

cd "$REPOSITORY_ROOT"

echo "Preparing the isolated VeraPolitica demo dataset..."
"$PYTHON" -m scripts.prepare_demo

export VERAPOLITICA_DATABASE_URL="sqlite:///./data/demo/verapolitica_demo.db"
export VERAPOLITICA_RAW_STORAGE_PATH="./data/demo/raw"
export VERAPOLITICA_ADMIN_API_KEY="verapolitica-demo-admin"
export VERAPOLITICA_ADMIN_REVIEWER_IDENTITY="demo-presenter"

echo
echo "Starting VeraPolitica in DEMO-ONLY mode."
echo "Citizen interface:  http://127.0.0.1:8000/app/"
echo "Editorial demo:     http://127.0.0.1:8000/demo/"
echo "Swagger fallback:   http://127.0.0.1:8000/docs"
echo "Press Ctrl+C to stop. Run this script again to reset the demo."

exec "$UVICORN" backend.app.main:app --host 127.0.0.1 --port 8000
