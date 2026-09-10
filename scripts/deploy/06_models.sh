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
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_BRAIN} Comprobación y Descarga de Modelos IA (Gemma 4 E2B + Scout Qwen 0.6B)${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    local PYTHON_BIN="python3"
    [[ -x "${BACKEND_DIR}/.venv/bin/python" ]] && PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"

    if [[ -f "${BACKEND_DIR}/scripts/ai/download_models.py" ]]; then
        tui_spin_cmd "Descargando / verificando pesos de IA (Gemma 4 + Scout) desde Hugging Face" \
            "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/ai/download_models.py" -y

        # Si el modelo Scout Qwen se descargó y existe, activar Scout automáticamente en .env
        local SCOUT_FILE="${BACKEND_DIR}/ai_models/qwen3-0.6B/Qwen3-0.6B-Q8_0.gguf"
        if [[ -f "${SCOUT_FILE}" ]]; then
            log_success "Modelo Scout Qwen 0.6B verificado en ${SCOUT_FILE}."
            if [[ -f "${BACKEND_DIR}/.env" ]]; then
                if grep -q "^SCOUT_ENABLED=" "${BACKEND_DIR}/.env"; then
                    sed -i 's|^SCOUT_ENABLED=.*|SCOUT_ENABLED=true|' "${BACKEND_DIR}/.env"
                else
                    echo "SCOUT_ENABLED=true" >> "${BACKEND_DIR}/.env"
                fi
                log_success "SCOUT_ENABLED=true activado en .env (Orquestador Scout listo)."
            fi
        else
            log_warn "Modelo Scout no presente. SCOUT_ENABLED permanecerá false hasta su descarga."
        fi

        log_success "Pesos de inferencia listos en ${DIM}${BACKEND_DIR}/ai_models/${NC}"
    else
        log_warn "Script download_models.py no encontrado en scripts/ai/."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    download_ai_models
fi
