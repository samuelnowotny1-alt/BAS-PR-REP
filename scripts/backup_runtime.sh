#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${BAS_PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKUP_DIR="${BAS_BACKUP_DIR:-/home/bas/bas-assistant-backups}"
RETENTION_DAYS="${BAS_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_DIR}/bas-assistant-runtime-${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"
umask 0077

tar -czf "${ARCHIVE}" \
    -C "${PROJECT_ROOT}" \
    config/bas-assistant.env \
    data \
    uploads \
    output

find "${BACKUP_DIR}" \
    -maxdepth 1 \
    -type f \
    -name 'bas-assistant-runtime-*.tar.gz' \
    -mtime "+${RETENTION_DAYS}" \
    -delete

echo "${ARCHIVE}"
