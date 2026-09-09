#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 06: DESCARGA Y VERIFICACION DE MODELOS GEMMA 4
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"
source "${SCRIPT_DIR}/05_llama.sh"

download_ai_models() {
    install_llama_server false

    log_info "Comprobando y descargando modelos Gemma 4 de Hugging Face..."
    cd "${BACKEND_DIR}"

    local PYTHON_BIN="python3"
    [[ -x "${BACKEND_DIR}/.venv/bin/python" ]] && PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"

    if [[ -f "${BACKEND_DIR}/scripts/ai/download_models.py" ]]; then
        "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/ai/download_models.py" -y
        log_success "Modelos Gemma 4 listos en ${BACKEND_DIR}/ai_models/."
    else
        log_warn "Script download_models.py no encontrado en scripts/ai/."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    download_ai_models
fi
