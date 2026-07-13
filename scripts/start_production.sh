#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/config/bas-assistant.env"

cd "${PROJECT_ROOT}"

if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

mkdir -p "${BAS_LOG_DIR:-${PROJECT_ROOT}/logs}" "${BAS_DATA_DIR:-${PROJECT_ROOT}/data}" "${BAS_OUTPUT_DIR:-${PROJECT_ROOT}/output}"
mkdir -p "${BAS_UPLOADS_DIR:-${PROJECT_ROOT}/uploads}"

export BAS_DATABASE_URL="${BAS_DATABASE_URL:-sqlite:///${PROJECT_ROOT}/data/bas_assistant.db}"
export BAS_SESSION_SECRET="${BAS_SESSION_SECRET:-replace-in-production}"

exec "${PROJECT_ROOT}/.venv/bin/python" -m uvicorn ui.api.main:app \
    --host "${BAS_HOST:-127.0.0.1}" \
    --port "${BAS_PORT:-8000}" \
    --proxy-headers
