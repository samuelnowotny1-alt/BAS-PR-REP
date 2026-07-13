#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
CRON_LINE="*/30 * * * * cd ${PROJECT_ROOT} && ${PROJECT_ROOT}/scripts/push_checkpoint_safe.sh >> ${LOG_DIR}/checkpoint_cron.log 2>&1"
BEGIN_MARKER="# BAS Assistant checkpoint automation"

mkdir -p "${LOG_DIR}"

EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"

FILTERED_CRONTAB="$(printf '%s\n' "${EXISTING_CRONTAB}" | awk -v marker="${BEGIN_MARKER}" -v line="${CRON_LINE}" '
    $0 == marker {skip=1; next}
    skip == 1 && $0 == line {skip=0; next}
    {print}
')"

{
    if [[ -n "${FILTERED_CRONTAB}" ]]; then
        printf '%s\n' "${FILTERED_CRONTAB}"
    fi
    printf '%s\n' "${BEGIN_MARKER}"
    printf '%s\n' "${CRON_LINE}"
} | crontab -

echo "Installed BAS Assistant checkpoint cron job:"
echo "${CRON_LINE}"
