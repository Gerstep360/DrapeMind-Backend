#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 03: ENTORNO VIRTUAL PYTHON Y DEPENDENCIAS PIP
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_python_venv() {
    cd "${BACKEND_DIR}"

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo -e "${COLOR_PRIMARY}╭── [ENTORNO PYTHON] ───────────────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_GEAR} Configuración de Entorno Virtual y Paquetes de Backend (.venv)${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    local PYTHON_BIN="python3"
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_BIN="python3.11"
    fi

    if [[ ! -d ".venv" ]]; then
        tui_spin_cmd "Creando entorno virtual Python con ${PYTHON_BIN}" ${PYTHON_BIN} -m venv .venv
    else
        log_info "Entorno virtual existente detectado en ${DIM}${BACKEND_DIR}/.venv${NC}"
    fi

    tui_spin_cmd "Actualizando gestor de paquetes pip" \
        "${BACKEND_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip

    tui_spin_cmd "Instalando dependencias de requirements.txt (FastAPI, Uvicorn, SQLAlchemy)" \
        "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r "${BACKEND_DIR}/requirements.txt"

    log_success "Entorno virtual y dependencias de FastAPI configuradas correctamente."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_python_venv
fi
