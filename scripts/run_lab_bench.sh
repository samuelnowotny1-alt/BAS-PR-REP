#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <project-json> [--serve] [--host HOST] [--port PORT]"
  exit 1
fi

PROJECT_JSON="$1"
shift

if [[ ! -f "${PROJECT_JSON}" ]]; then
  echo "Project file not found: ${PROJECT_JSON}"
  exit 1
fi

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtualenv not found at ${PYTHON_BIN}"
  exit 1
fi

export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}"

EMULATION_DIR="${PROJECT_ROOT}/emulation"
FAKE_STATION_DIR="${PROJECT_ROOT}/examples/fake_station"

mkdir -p "${EMULATION_DIR}" "${FAKE_STATION_DIR}"

echo "Generating emulator manifest from ${PROJECT_JSON}"
"${PYTHON_BIN}" -m bas_assistant.cli emulate "${PROJECT_JSON}" -o "${EMULATION_DIR}"

echo "Generating fake station runtime CSVs in ${FAKE_STATION_DIR}"
"${PYTHON_BIN}" - <<'PY' "${PROJECT_JSON}" "${FAKE_STATION_DIR}"
from pathlib import Path
import sys

from examples.generate_fake_station_data import generate

project_json = Path(sys.argv[1]).resolve()
output_dir = Path(sys.argv[2]).resolve()
generate(project_json, output_dir)
print(f"Generated fake station data from {project_json} into {output_dir}")
PY

if [[ $# -gt 0 ]]; then
  echo "Starting emulator server"
  "${PYTHON_BIN}" -m bas_assistant.cli emulate "${PROJECT_JSON}" -o "${EMULATION_DIR}" "$@"
fi
