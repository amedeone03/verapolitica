#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(dirname -- "$SCRIPT_DIR")
PYTHON="$REPOSITORY_ROOT/.venv/bin/python"
ENV_FILE="$REPOSITORY_ROOT/.env.unified-demo"

if [ ! -x "$PYTHON" ]; then
  echo "Unified demo startup failed: create the repository .venv first." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

cd "$REPOSITORY_ROOT"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if [ ! -f "$REPOSITORY_ROOT/data/unified_demo/verapolitica.db" ]; then
  echo "Unified demo database is missing. Build it once with:" >&2
  echo "  $PYTHON -m scripts.prepare_unified_demo --seed-from-ceo" >&2
  exit 1
fi

echo "Starting VeraPolitica unified demo on http://127.0.0.1:8000"
echo "Citizen app:     http://127.0.0.1:8000/app/"
echo "AI editorial:    http://127.0.0.1:8000/demo/ai-upload"
echo "Press Ctrl+C to stop. This launcher does not rebuild data."

exec "$PYTHON" -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
