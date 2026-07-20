#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy_raspi_lab_emulator.sh \
    --pi-host 192.168.1.50 \
    --pi-user pi \
    --local-repo /home/oem/.openclaw/workspace/bas-assistant \
    --remote-repo /opt/bas-assistant \
    --project-json examples/sample-hvac-project.json

This helper:
  1. copies the Raspberry Pi installer script to the Pi
  2. prints the exact repo sync command to run
  3. runs the installer over SSH

Options:
  --pi-host HOST         Raspberry Pi hostname or IP
  --pi-user USER         Raspberry Pi SSH user
  --local-repo PATH      Local BAS Assistant repo path
  --remote-repo PATH     Target repo path on the Pi
  --project-json PATH    Project JSON path relative to remote repo or absolute on the Pi
  --service-name NAME    systemd service name (default: bas-lab-emulator)
  --host HOST            Emulator bind host (default: 0.0.0.0)
  --port PORT            Emulator port (default: 8787)
  --remote-user USER     Linux user that should run the emulator service (default: pi)
  --help                 Show this help
EOF
}

PI_HOST=""
PI_USER=""
LOCAL_REPO=""
REMOTE_REPO=""
PROJECT_JSON=""
SERVICE_NAME="bas-lab-emulator"
BIND_HOST="0.0.0.0"
PORT="8787"
REMOTE_USER="pi"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pi-host)
      PI_HOST="$2"
      shift 2
      ;;
    --pi-user)
      PI_USER="$2"
      shift 2
      ;;
    --local-repo)
      LOCAL_REPO="$2"
      shift 2
      ;;
    --remote-repo)
      REMOTE_REPO="$2"
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
    --host)
      BIND_HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --remote-user)
      REMOTE_USER="$2"
      shift 2
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

if [[ -z "${PI_HOST}" || -z "${PI_USER}" || -z "${LOCAL_REPO}" || -z "${REMOTE_REPO}" || -z "${PROJECT_JSON}" ]]; then
  usage
  exit 1
fi

LOCAL_REPO="$(readlink -f "${LOCAL_REPO}")"
INSTALLER_LOCAL="${LOCAL_REPO}/scripts/setup_raspi_lab_emulator.sh"

if [[ ! -f "${INSTALLER_LOCAL}" ]]; then
  echo "Installer script not found: ${INSTALLER_LOCAL}"
  exit 1
fi

REMOTE_TMP="/tmp/setup_raspi_lab_emulator.sh"

echo "Copying installer to ${PI_USER}@${PI_HOST}:${REMOTE_TMP}"
scp "${INSTALLER_LOCAL}" "${PI_USER}@${PI_HOST}:${REMOTE_TMP}"

cat <<EOF

Recommended repo sync command for the Pi:

  rsync -av --delete \\
    --exclude '.venv' \\
    --exclude '__pycache__' \\
    --exclude '.pytest_cache' \\
    --exclude 'ui/output' \\
    --exclude 'output' \\
    --exclude 'logs' \\
    ${LOCAL_REPO}/ ${PI_USER}@${PI_HOST}:${REMOTE_REPO}/

If the repo is not on the Pi yet, run that command first.
EOF

echo
echo "Running Raspberry Pi installer over SSH"
ssh "${PI_USER}@${PI_HOST}" \
  "sudo bash ${REMOTE_TMP} --repo ${REMOTE_REPO} --project-json ${PROJECT_JSON} --service-name ${SERVICE_NAME} --user ${REMOTE_USER} --host ${BIND_HOST} --port ${PORT}"

echo
echo "Done. To inspect the service on the Pi:"
echo "  ssh ${PI_USER}@${PI_HOST} 'systemctl status ${SERVICE_NAME}.service --no-pager'"
