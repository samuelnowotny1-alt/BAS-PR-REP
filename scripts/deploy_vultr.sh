#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE_HOST="${REMOTE_HOST:-bas@155.138.193.113}"
REMOTE_DIR="${REMOTE_DIR:-/home/bas/bas-assistant}"
REMOTE_RELEASES_DIR="${REMOTE_RELEASES_DIR:-/home/bas/bas-assistant-releases}"
SERVICE_NAME="${SERVICE_NAME:-bas-assistant.service}"
RELEASE_ID="${RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
REMOTE_BACKUP_DIR="${REMOTE_RELEASES_DIR}/${RELEASE_ID}"

echo "Deploying ${PROJECT_ROOT} to ${REMOTE_HOST}:${REMOTE_DIR}"

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}' '${REMOTE_BACKUP_DIR}'"
ssh "${REMOTE_HOST}" "rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'config/bas-assistant.env' \
  --exclude 'data' --exclude 'logs' --exclude 'output' --exclude 'uploads' \
  --exclude 'ui/data' --exclude 'ui/output' \
  '${REMOTE_DIR}/' '${REMOTE_BACKUP_DIR}/'"

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.mypy_cache' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '__pycache__' \
  --exclude 'config/bas-assistant.env' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'output' \
  --exclude 'uploads' \
  --exclude 'ui/data' \
  --exclude 'ui/output' \
  "${PROJECT_ROOT}/" \
  "${REMOTE_HOST}:${REMOTE_DIR}/"

if ! ssh "${REMOTE_HOST}" "bash -s" -- "${REMOTE_DIR}" "${REMOTE_BACKUP_DIR}" "${SERVICE_NAME}" <<'REMOTE'
set -euo pipefail
remote_dir="$1"
backup_dir="$2"
service_name="$3"

cd "${remote_dir}"
mkdir -p logs data output uploads
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
fi
.venv/bin/pip install -e .
if [ -x .venv/bin/alembic ]; then
    .venv/bin/alembic upgrade head
fi

can_sudo=0
if sudo -n true 2>/dev/null; then
    can_sudo=1
    sudo install -m 0644 deploy/bas-assistant.service.example "/etc/systemd/system/${service_name}"
    sudo systemctl daemon-reload
elif ! systemctl cat "${service_name}" >/dev/null 2>&1; then
    echo "${service_name} is not installed and passwordless sudo is unavailable." >&2
    exit 1
fi

restart_service() {
    if [ "${can_sudo}" -eq 1 ]; then
        sudo systemctl enable "${service_name}" >/dev/null
        sudo systemctl restart "${service_name}"
        return
    fi
    main_pid="$(systemctl show "${service_name}" -p MainPID --value)"
    if [ -z "${main_pid}" ] || [ "${main_pid}" = "0" ]; then
        echo "${service_name} is not running and cannot be started without sudo." >&2
        return 1
    fi
    kill "${main_pid}"
}

if systemctl is-active --quiet "${service_name}"; then
    restart_service
elif [ "${can_sudo}" -eq 1 ]; then
    sudo systemctl enable --now "${service_name}"
else
    echo "${service_name} is inactive and cannot be started without sudo." >&2
    exit 1
fi

healthy=0
for _ in $(seq 1 15); do
    if curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
        healthy=1
        break
    fi
    sleep 1
done
if [ "${healthy}" -ne 1 ]; then
    rsync -a --delete \
      --exclude '.venv' --exclude 'config/bas-assistant.env' \
      --exclude 'data' --exclude 'logs' --exclude 'output' --exclude 'uploads' \
      --exclude 'ui/data' --exclude 'ui/output' \
      "${backup_dir}/" "${remote_dir}/"
    cd "${remote_dir}"
    .venv/bin/pip install -e .
    restart_service || true
    echo "Deployment failed health checks and code was rolled back from ${backup_dir}." >&2
    exit 1
fi

systemctl is-active "${service_name}"
curl -fsS http://127.0.0.1:8000/healthz
REMOTE
then
    exit 1
fi

echo
echo "Deployment ${RELEASE_ID} complete. Rollback snapshot: ${REMOTE_BACKUP_DIR}"
echo "Open http://${REMOTE_HOST#*@}/"
