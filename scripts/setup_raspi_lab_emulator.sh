#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo bash setup_raspi_lab_emulator.sh --repo /opt/bas-assistant --project-json examples/sample-hvac-project.json

Options:
  --repo PATH            Repo location on the Raspberry Pi
  --project-json PATH    Project JSON path, relative to repo or absolute
  --service-name NAME    systemd service name (default: bas-lab-emulator)
  --user NAME            Linux user that should own/run the service (default: pi)
  --host HOST            Bind host for emulator API (default: 0.0.0.0)
  --port PORT            Bind port for emulator API (default: 8787)
  --skip-apt             Skip apt package install
  --help                 Show this help

Behavior:
  - installs Python venv dependencies
  - installs BAS Assistant into the venv
  - generates emulator manifest files
  - generates fake station CSV runtime data
  - creates and enables a systemd service
EOF
}

REPO_DIR=""
PROJECT_JSON=""
SERVICE_NAME="bas-lab-emulator"
APP_USER="pi"
HOST="0.0.0.0"
PORT="8787"
SKIP_APT="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_DIR="$2"
      shift 2
      ;;
    --project-json)
      PROJECT_JSON="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --user)
      APP_USER="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --skip-apt)
      SKIP_APT="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${REPO_DIR}" || -z "${PROJECT_JSON}" ]]; then
  usage
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo so it can install packages and register the service."
  exit 1
fi

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  echo "User '${APP_USER}' does not exist."
  exit 1
fi

REPO_DIR="$(readlink -f "${REPO_DIR}")"
if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Repo directory not found: ${REPO_DIR}"
  exit 1
fi

if [[ "${PROJECT_JSON}" = /* ]]; then
  PROJECT_JSON_ABS="${PROJECT_JSON}"
else
  PROJECT_JSON_ABS="${REPO_DIR}/${PROJECT_JSON}"
fi
PROJECT_JSON_ABS="$(readlink -f "${PROJECT_JSON_ABS}")"
if [[ ! -f "${PROJECT_JSON_ABS}" ]]; then
  echo "Project JSON not found: ${PROJECT_JSON_ABS}"
  exit 1
fi

VENV_DIR="${REPO_DIR}/.venv"
EMULATION_DIR="${REPO_DIR}/emulation"
FAKE_STATION_DIR="${REPO_DIR}/examples/fake_station"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${SKIP_APT}" != "true" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv python3-pip
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
fi

sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" -m pip install -e "${REPO_DIR}"

mkdir -p "${EMULATION_DIR}" "${FAKE_STATION_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${EMULATION_DIR}" "${FAKE_STATION_DIR}" "${VENV_DIR}"

sudo -u "${APP_USER}" env PYTHONPATH="${REPO_DIR}/src:${REPO_DIR}" \
  "${VENV_DIR}/bin/python" -m bas_assistant.cli emulate \
  "${PROJECT_JSON_ABS}" \
  -o "${EMULATION_DIR}"

sudo -u "${APP_USER}" env PYTHONPATH="${REPO_DIR}/src:${REPO_DIR}" \
  "${VENV_DIR}/bin/python" - <<'PY' "${PROJECT_JSON_ABS}" "${FAKE_STATION_DIR}"
from pathlib import Path
import sys

from examples.generate_fake_station_data import generate

project_json = Path(sys.argv[1]).resolve()
output_dir = Path(sys.argv[2]).resolve()
generate(project_json, output_dir)
print(f"Generated fake station data in {output_dir}")
PY

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=BAS Lab Emulator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${REPO_DIR}
Environment=PYTHONPATH=${REPO_DIR}/src:${REPO_DIR}
ExecStart=${VENV_DIR}/bin/python -m bas_assistant.cli emulate ${PROJECT_JSON_ABS} -o ${EMULATION_DIR} --serve --host ${HOST} --port ${PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo
echo "Raspberry Pi lab emulator installed."
echo "Service: ${SERVICE_NAME}.service"
echo "Project: ${PROJECT_JSON_ABS}"
echo "Manifest: ${EMULATION_DIR}/lab_manifest.json"
echo "Snapshot: ${EMULATION_DIR}/runtime_snapshot.json"
echo "Fake station CSVs: ${FAKE_STATION_DIR}"
echo "API: http://${HOST}:${PORT}"
echo
systemctl --no-pager --status=short status "${SERVICE_NAME}.service" || true
