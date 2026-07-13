#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCK_FILE="${PROJECT_ROOT}/logs/checkpoint_push.lock"

mkdir -p "${PROJECT_ROOT}/logs"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "Checkpoint push already running. Skipping."
    exit 0
fi

exec "${SCRIPT_DIR}/push_checkpoint.sh" --message "Automated checkpoint $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
