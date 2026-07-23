#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo install -m 0644 "${PROJECT_ROOT}/deploy/bas-assistant-backup.service.example" \
    /etc/systemd/system/bas-assistant-backup.service
sudo install -m 0644 "${PROJECT_ROOT}/deploy/bas-assistant-backup.timer.example" \
    /etc/systemd/system/bas-assistant-backup.timer
sudo install -m 0644 "${PROJECT_ROOT}/deploy/bas-assistant-health.service.example" \
    /etc/systemd/system/bas-assistant-health.service
sudo install -m 0644 "${PROJECT_ROOT}/deploy/bas-assistant-health.timer.example" \
    /etc/systemd/system/bas-assistant-health.timer

sudo systemctl daemon-reload
sudo systemctl enable --now \
    bas-assistant.service \
    bas-assistant-backup.timer \
    bas-assistant-health.timer

sudo systemctl is-enabled \
    bas-assistant.service \
    bas-assistant-backup.timer \
    bas-assistant-health.timer
