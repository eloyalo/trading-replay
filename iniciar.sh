#!/usr/bin/env bash
# Arranca trading-replay en http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

uv sync --quiet
exec uv run uvicorn trading_replay.app:app --host 127.0.0.1 --port 8000 "$@"
