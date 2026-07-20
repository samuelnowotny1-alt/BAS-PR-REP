#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-bas@155.138.193.113}"
REMOTE_DIR="${REMOTE_DIR:-/home/bas/bas-assistant}"

echo "Deploying BAS Assistant to ${REMOTE_HOST}:${REMOTE_DIR}"

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}'"

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.mypy_cache' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '__pycache__' \
  --exclude 'config/bas-assistant.env' \
  --exclude 'data' \
  --exclude 'output' \
  --exclude 'uploads' \
  --exclude 'ui/data' \
  --exclude 'ui/output' \
  /home/oem/.openclaw/workspace/bas-assistant/ \
  "${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "${REMOTE_HOST}" "bash -lc '
  set -euo pipefail
  cd \"${REMOTE_DIR}\"
  mkdir -p logs data output uploads
  if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e .
  fi
  pid=\$(ss -ltnp | sed -n \"s/.*127.0.0.1:8000.*pid=\\([0-9]\\+\\).*/\\1/p\" | head -n1)
  if [ -n \"\${pid:-}\" ]; then
    kill \"\$pid\" || true
    sleep 2
  fi
  nohup ./scripts/start_production.sh > logs/remote-start.out 2>&1 < /dev/null &
  sleep 5
  ss -ltnp | grep 127.0.0.1:8000
  curl http://127.0.0.1:8000/healthz
'"

echo "Deployment complete. Open http://${REMOTE_HOST#*@}/"
