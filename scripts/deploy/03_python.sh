#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 03: ENTORNO VIRTUAL PYTHON Y DEPENDENCIAS PIP
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_python_venv() {
    log_info "Configurando entorno virtual Python en ${BACKEND_DIR}/.venv..."
    cd "${BACKEND_DIR}"

    local PYTHON_BIN="python3"
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_BIN="python3.11"
    fi

    if [[ ! -d ".venv" ]]; then
        log_info "Creando nuevo entorno virtual con ${PYTHON_BIN}..."
        ${PYTHON_BIN} -m venv .venv
    fi

    log_info "Actualizando pip e instalando dependencias de requirements.txt..."
    "${BACKEND_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
    "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r requirements.txt

    log_success "Entorno virtual de Python configurado exitosamente."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_python_venv
fi
