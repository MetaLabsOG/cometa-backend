#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly STACK_DIR="${COMETA_STACK_DIR:-${PROJECT_ROOT}/..}"
readonly STACK_FILE="${STACK_DIR}/docker-compose.yml"
readonly BACKEND_SERVICE="${COMETA_BACKEND_SERVICE:-backend}"
readonly HEALTH_URL="${COMETA_HEALTH_URL:-https://api.cometa.farm/contracts}"
readonly HEALTH_ATTEMPTS="${COMETA_HEALTH_ATTEMPTS:-12}"
readonly HEALTH_DELAY_SECONDS="${COMETA_HEALTH_DELAY_SECONDS:-5}"

trap 'printf "ERROR: redeploy failed at line %s\n" "$LINENO" >&2' ERR

if [[ ! "${HEALTH_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: COMETA_HEALTH_ATTEMPTS must be a positive integer\n' >&2
    exit 2
fi

if [[ ! "${HEALTH_DELAY_SECONDS}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    printf 'ERROR: COMETA_HEALTH_DELAY_SECONDS must be a non-negative number\n' >&2
    exit 2
fi

if [[ ! -f "${STACK_FILE}" ]]; then
    printf 'ERROR: production Compose file not found: %s\n' "${STACK_FILE}" >&2
    exit 2
fi

service_found=false
while IFS= read -r service; do
    if [[ "${service}" == "${BACKEND_SERVICE}" ]]; then
        service_found=true
        break
    fi
done < <(docker compose --project-directory "${STACK_DIR}" --file "${STACK_FILE}" config --services)

if [[ "${service_found}" != true ]]; then
    printf 'ERROR: Compose service %s is not defined in %s\n' "${BACKEND_SERVICE}" "${STACK_FILE}" >&2
    exit 2
fi

git -C "${PROJECT_ROOT}" pull --ff-only
docker compose \
    --project-directory "${STACK_DIR}" \
    --file "${STACK_FILE}" \
    up --detach --build --remove-orphans "$@" "${BACKEND_SERVICE}"

for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --max-time 10 "${HEALTH_URL}" >/dev/null; then
        printf 'Deploy OK: %s is ready\n' "${HEALTH_URL}"
        exit 0
    fi

    if ((attempt < HEALTH_ATTEMPTS)); then
        printf 'Waiting for service health (%d/%d)...\n' "${attempt}" "${HEALTH_ATTEMPTS}" >&2
        sleep "${HEALTH_DELAY_SECONDS}"
    fi
done

printf 'ERROR: service did not become healthy: %s\n' "${HEALTH_URL}" >&2
exit 1
