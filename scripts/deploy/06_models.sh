#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 06: MODELOS GEMMA 4 Y PROYECTOR MULTIMODAL
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"
source "${SCRIPT_DIR}/05_llama.sh"

download_ai_models() {
    install_llama_server false
    cd "${BACKEND_DIR}"

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo -e "${COLOR_PRIMARY}╭── [MODELOS DE INTELIGENCIA ARTIFICIAL] ───────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_BRAIN} Comprobación y Descarga de Gemma 4 E2B + Proyector Multimodal${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    local PYTHON_BIN="python3"
    [[ -x "${BACKEND_DIR}/.venv/bin/python" ]] && PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"

    if [[ -f "${BACKEND_DIR}/scripts/ai/download_models.py" ]]; then
        tui_spin_cmd "Descargando / verificando pesos de Gemma 4 desde Hugging Face" \
            "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/ai/download_models.py" -y

        log_success "Pesos de inferencia listos en ${DIM}${BACKEND_DIR}/ai_models/${NC}"
    else
        log_warn "Script download_models.py no encontrado en scripts/ai/."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    download_ai_models
fi
