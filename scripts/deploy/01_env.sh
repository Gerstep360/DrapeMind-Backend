#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"
sync_env_production() {
    local env_file="${BACKEND_DIR}/.env"
    if [[ ! -f "${env_file}" ]]; then
        cp "${BACKEND_DIR}/.env.production.example" "${env_file}"
        chmod 600 "${env_file}"
        log_info 'Creado .env. Configura DB, secretos y NVIDIA_API_KEY antes de iniciar.'
        return 1
    else
        log_info 'Se conserva .env y sus credenciales existentes.'
    fi
}
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then sync_env_production; fi
