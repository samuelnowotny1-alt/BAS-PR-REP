#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_TEST_CMD="${PROJECT_ROOT}/.venv/bin/pytest ${PROJECT_ROOT}/tests/test_auth_and_database.py ${PROJECT_ROOT}/tests/test_ui_workflow.py ${PROJECT_ROOT}/tests/test_runtime_infrastructure.py"

SKIP_TESTS=0
COMMIT_MESSAGE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
        --message)
            COMMIT_MESSAGE="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

cd "${PROJECT_ROOT}"
mkdir -p "${PROJECT_ROOT}/logs"

if [[ -z "$(git status --short)" ]]; then
    echo "No local changes to checkpoint."
    exit 0
fi

if [[ "${SKIP_TESTS}" -ne 1 ]]; then
    TEST_CMD="${BAS_CHECKPOINT_TEST_CMD:-${DEFAULT_TEST_CMD}}"
    echo "Running checkpoint test gate..."
    # shellcheck disable=SC2086
    eval ${TEST_CMD}
fi

git add -A

if git diff --cached --quiet; then
    echo "No staged changes after git add."
    exit 0
fi

if [[ -z "${COMMIT_MESSAGE}" ]]; then
    COMMIT_MESSAGE="Checkpoint $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
fi

CURRENT_BRANCH="$(git branch --show-current)"
if [[ -z "${CURRENT_BRANCH}" ]]; then
    echo "Unable to determine current git branch." >&2
    exit 1
fi

git commit -m "${COMMIT_MESSAGE}"
git push -u origin "${CURRENT_BRANCH}"

echo "Checkpoint pushed on ${CURRENT_BRANCH}."
