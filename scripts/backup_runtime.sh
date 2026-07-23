#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${BAS_PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKUP_DIR="${BAS_BACKUP_DIR:-/home/bas/bas-assistant-backups}"
RETENTION_DAYS="${BAS_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_DIR}/bas-assistant-runtime-${TIMESTAMP}.tar.gz"
ARCHIVE_TMP="${ARCHIVE}.tmp"

mkdir -p "${BACKUP_DIR}"
umask 0077
STAGING_ROOT="$(mktemp -d "${BACKUP_DIR}/.bas-assistant-runtime-${TIMESTAMP}.XXXXXX")"
trap 'rm -rf "${STAGING_ROOT}" "${ARCHIVE_TMP}"' EXIT

mkdir -p "${STAGING_ROOT}/project"
rsync -a --relative \
    --exclude '*.db' \
    --exclude '*.sqlite' \
    --exclude '*.sqlite3' \
    "${PROJECT_ROOT}/./config/bas-assistant.env" \
    "${PROJECT_ROOT}/./data" \
    "${PROJECT_ROOT}/./uploads" \
    "${PROJECT_ROOT}/./output" \
    "${STAGING_ROOT}/project/"

# SQLite's backup API includes committed WAL data without stopping the service.
while IFS= read -r -d '' database; do
    relative_path="${database#"${PROJECT_ROOT}/"}"
    destination="${STAGING_ROOT}/project/${relative_path}"
    mkdir -p "$(dirname "${destination}")"
    python3 - "${database}" "${destination}" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
done < <(
    find "${PROJECT_ROOT}/data" -type f \
        \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) \
        -print0
)

tar -czf "${ARCHIVE_TMP}" \
    -C "${STAGING_ROOT}/project" \
    config \
    data \
    uploads \
    output
chmod 0600 "${ARCHIVE_TMP}"
mv "${ARCHIVE_TMP}" "${ARCHIVE}"

find "${BACKUP_DIR}" \
    -maxdepth 1 \
    -type f \
    -name 'bas-assistant-runtime-*.tar.gz' \
    -mtime "+${RETENTION_DAYS}" \
    -delete

echo "${ARCHIVE}"
