#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-bas@155.138.193.113}"
REMOTE_DIR="${REMOTE_DIR:-/home/bas/bas-assistant}"
REMOTE_RELEASES_DIR="${REMOTE_RELEASES_DIR:-/home/bas/bas-assistant-releases}"
SERVICE_NAME="${SERVICE_NAME:-bas-assistant.service}"
RELEASE_ID="${1:-}"

if [ -z "${RELEASE_ID}" ]; then
    echo "Usage: $0 <release-id>" >&2
    echo "Available releases:" >&2
    ssh "${REMOTE_HOST}" "find '${REMOTE_RELEASES_DIR}' -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r"
    exit 2
fi

REMOTE_BACKUP_DIR="${REMOTE_RELEASES_DIR}/${RELEASE_ID}"
ssh "${REMOTE_HOST}" "test -d '${REMOTE_BACKUP_DIR}'"
ssh "${REMOTE_HOST}" "bash -s" -- "${REMOTE_DIR}" "${REMOTE_BACKUP_DIR}" "${SERVICE_NAME}" <<'REMOTE'
set -euo pipefail
remote_dir="$1"
backup_dir="$2"
service_name="$3"

rsync -a --delete \
  --exclude '.venv' --exclude 'config/bas-assistant.env' \
  --exclude 'data' --exclude 'logs' --exclude 'output' --exclude 'uploads' \
  --exclude 'ui/data' --exclude 'ui/output' \
  "${backup_dir}/" "${remote_dir}/"
cd "${remote_dir}"
.venv/bin/pip install -e .
if sudo -n true 2>/dev/null; then
    sudo systemctl restart "${service_name}"
else
    main_pid="$(systemctl show "${service_name}" -p MainPID --value)"
    if [ -z "${main_pid}" ] || [ "${main_pid}" = "0" ]; then
        echo "${service_name} is not running and cannot be restarted without sudo." >&2
        exit 1
    fi
    kill "${main_pid}"
fi
for _ in $(seq 1 15); do
    if curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
        echo "Rollback to ${backup_dir} completed."
        exit 0
    fi
    sleep 1
done
echo "Rollback completed but health verification failed." >&2
exit 1
REMOTE
