#!/bin/sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
project_root="$(dirname -- "${script_dir}")"

cd -- "${project_root}"

if [ ! -f "app.py" ]; then
    printf 'ERROR: application entrypoint not found: %s/app.py\n' "${project_root}" >&2
    exit 1
fi

exec python -u app.py
