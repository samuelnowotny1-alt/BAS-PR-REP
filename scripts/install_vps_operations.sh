#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---system}"
UNITS=(
    bas-assistant.service
    bas-assistant-backup.service
    bas-assistant-backup.timer
    bas-assistant-health.service
    bas-assistant-health.timer
)

if [ "${MODE}" = "--user" ]; then
    unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
    mkdir -p "${unit_dir}"
    loginctl enable-linger "$(id -un)"

    for unit in "${UNITS[@]}"; do
        source="${PROJECT_ROOT}/deploy/${unit}.example"
        sed \
            -e '/^User=/d' \
            -e '/^Group=/d' \
            -e 's/^WantedBy=multi-user.target$/WantedBy=default.target/' \
            "${source}" > "${unit_dir}/${unit}"
        chmod 0644 "${unit_dir}/${unit}"
    done

    systemctl --user daemon-reload
    systemctl --user disable bas-assistant.service >/dev/null 2>&1 || true
    systemctl --user enable bas-assistant.service
    if ! systemctl is-active --quiet bas-assistant.service; then
        systemctl --user start bas-assistant.service
    fi
    systemctl --user enable --now \
        bas-assistant-backup.timer \
        bas-assistant-health.timer
    systemctl --user is-enabled \
        bas-assistant.service \
        bas-assistant-backup.timer \
        bas-assistant-health.timer
elif [ "${MODE}" = "--system" ]; then
    for unit in "${UNITS[@]}"; do
        sudo install -m 0644 "${PROJECT_ROOT}/deploy/${unit}.example" \
            "/etc/systemd/system/${unit}"
    done

    sudo systemctl daemon-reload
    sudo systemctl enable --now \
        bas-assistant.service \
        bas-assistant-backup.timer \
        bas-assistant-health.timer
    sudo systemctl is-enabled \
        bas-assistant.service \
        bas-assistant-backup.timer \
        bas-assistant-health.timer
else
    echo "Usage: $0 [--system|--user]" >&2
    exit 2
fi
