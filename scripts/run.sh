#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

cd -- "${PROJECT_ROOT}"

if [[ ! -f "app.py" ]]; then
    printf 'ERROR: application entrypoint not found: %s/app.py\n' "${PROJECT_ROOT}" >&2
    exit 1
fi

exec python -u app.py
