#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@155.138.193.113}"
REMOTE_DIR="${REMOTE_DIR:-/opt/bas-assistant}"

echo "Deploying BAS Assistant to ${REMOTE_HOST}:${REMOTE_DIR}"

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}'"

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.mypy_cache' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '__pycache__' \
  --exclude 'data' \
  --exclude 'output' \
  --exclude 'ui/data' \
  --exclude 'ui/output' \
  /home/oem/.openclaw/workspace/bas-assistant/ \
  "${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "${REMOTE_HOST}" "bash -lc '
  set -euo pipefail
  if ! command -v docker >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable\" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  cd \"${REMOTE_DIR}\"
  docker compose -f docker-compose.yml -f docker-compose.vultr.yml up -d --build
  docker compose -f docker-compose.yml -f docker-compose.vultr.yml ps
'"

echo "Deployment complete. Open http://${REMOTE_HOST#*@}/"
