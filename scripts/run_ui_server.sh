#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

export BAS_DATA_DIR="${BAS_DATA_DIR:-${PROJECT_ROOT}/ui/data}"
export BAS_OUTPUT_DIR="${BAS_OUTPUT_DIR:-${PROJECT_ROOT}/ui/output}"

exec ./.venv/bin/python -m uvicorn ui.api.main:app --host 127.0.0.1 --port 8000
