#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(dirname -- "$SCRIPT_DIR")
ENV_FILE="$REPOSITORY_ROOT/.env.production"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  echo "Copy .env.production.example to .env.production and fill local/VPS values." >&2
  echo "See docs/production_deployment.md" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  set -- up --build
fi

cd "$REPOSITORY_ROOT"
exec docker compose --env-file "$ENV_FILE" "$@"
