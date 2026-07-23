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

rsync -a --delete --no-owner --no-group --omit-dir-times \
  --exclude '.git' --exclude '.venv' --exclude 'config/bas-assistant.env' \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'data' --exclude 'logs' --exclude 'output' --exclude 'uploads' \
  --exclude 'ui/data' --exclude 'ui/output' \
  "${backup_dir}/" "${remote_dir}/"
cd "${remote_dir}"
.venv/bin/pip install -e .
old_pid="$(systemctl show "${service_name}" -p MainPID --value 2>/dev/null || true)"
old_pid="${old_pid:-0}"
if sudo -n true 2>/dev/null; then
    sudo systemctl restart "${service_name}"
elif [ "${old_pid}" != "0" ]; then
    kill "${old_pid}" 2>/dev/null || true
fi
for _ in $(seq 1 30); do
    main_pid="$(systemctl show "${service_name}" -p MainPID --value 2>/dev/null || true)"
    main_pid="${main_pid:-0}"
    listener_pid="$(
        ss -H -ltnp '( sport = :8000 )' 2>/dev/null \
          | sed -n 's/.*pid=\([0-9]*\).*/\1/p' \
          | head -n 1
    )"
    if [ "${main_pid}" != "0" ] && [ "${main_pid}" != "${old_pid}" ] \
      && [ "${listener_pid}" = "${main_pid}" ] \
      && systemctl is-active --quiet "${service_name}" \
      && curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
        echo "Rollback to ${backup_dir} completed."
        exit 0
    fi
    sleep 1
done
echo "Rollback completed but health verification failed." >&2
exit 1
REMOTE
