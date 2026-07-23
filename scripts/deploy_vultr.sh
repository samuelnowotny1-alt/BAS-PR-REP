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
ssh "${REMOTE_HOST}" "rsync -a --delete --no-owner --no-group --omit-dir-times \
  --exclude '.git' --exclude '.venv' --exclude 'config/bas-assistant.env' \
  --exclude '__pycache__' --exclude '*.pyc' \
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
if [ -f config/bas-assistant.env ]; then
    set -a
    # shellcheck disable=SC1091
    source config/bas-assistant.env
    set +a
fi
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
fi
.venv/bin/pip install -e .
if [ -x .venv/bin/alembic ]; then
    current_revision="$(.venv/bin/alembic current 2>/dev/null)"
    table_count="$(
        .venv/bin/python -c \
          'from sqlalchemy import create_engine, inspect; from bas_assistant.config import get_settings; tables=set(inspect(create_engine(get_settings().database_url)).get_table_names())-{"alembic_version"}; print(len(tables))'
    )"
    if [ -z "${current_revision}" ] && [ "${table_count}" -gt 0 ]; then
        .venv/bin/alembic stamp head
    else
        .venv/bin/alembic upgrade head
    fi
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
    old_pid="$(systemctl show "${service_name}" -p MainPID --value 2>/dev/null || true)"
    old_pid="${old_pid:-0}"
    if [ "${can_sudo}" -eq 1 ]; then
        sudo systemctl enable "${service_name}" >/dev/null
        sudo systemctl restart "${service_name}"
    elif [ "${old_pid}" != "0" ]; then
        kill "${old_pid}" 2>/dev/null || true
    fi

    # Restart=always may leave the unit briefly inactive before a replacement
    # process appears. Require a new PID so a stale listener cannot pass health.
    for _ in $(seq 1 30); do
        main_pid="$(systemctl show "${service_name}" -p MainPID --value 2>/dev/null || true)"
        main_pid="${main_pid:-0}"
        if [ "${main_pid}" != "0" ] && [ "${main_pid}" != "${old_pid}" ] \
          && systemctl is-active --quiet "${service_name}" \
          && curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "${service_name} did not produce a healthy replacement process." >&2
    return 1
}

if ! restart_service; then
    rsync -a --delete --no-owner --no-group --omit-dir-times \
      --exclude '.git' --exclude '.venv' --exclude 'config/bas-assistant.env' \
      --exclude '__pycache__' --exclude '*.pyc' \
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
    echo "Remote deployment stage failed; restoring ${REMOTE_BACKUP_DIR}." >&2
    "${SCRIPT_DIR}/rollback_vultr.sh" "${RELEASE_ID}" || {
        echo "Automatic rollback also failed; inspect ${REMOTE_HOST} immediately." >&2
        exit 2
    }
    exit 1
fi

echo
echo "Deployment ${RELEASE_ID} complete. Rollback snapshot: ${REMOTE_BACKUP_DIR}"
echo "Open http://${REMOTE_HOST#*@}/"
