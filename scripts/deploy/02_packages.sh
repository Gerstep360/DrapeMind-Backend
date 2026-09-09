#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 02: INSTALACION DE PAQUETES DEL SISTEMA (APT)
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

detect_python() {
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_EXEC="python3.11"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_EXEC="python3"
    else
        PYTHON_EXEC="python3"
    fi
}

install_system_packages() {
    check_root
    detect_python

    echo -e "${COLOR_PRIMARY}╭── [PAQUETES DEL SISTEMA] ─────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_PACKAGE} Preparando dependencias del sistema operativo (Ubuntu Linux)${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    export DEBIAN_FRONTEND=noninteractive

    tui_spin_cmd "Actualizando repositorios APT del sistema" apt-get update -qq

    tui_spin_cmd "Instalando herramientas base (curl, wget, git, build-essential, cmake, libpq)" \
        apt-get install -y -qq \
        curl \
        wget \
        git \
        tar \
        gzip \
        build-essential \
        cmake \
        libpq-dev \
        software-properties-common

    if ! command -v python3 >/dev/null 2>&1 || ! dpkg -s python3-venv >/dev/null 2>&1; then
        tui_spin_cmd "Instalando entorno base de Python 3 (venv, pip, dev)" \
            apt-get install -y -qq python3 python3-venv python3-pip python3-dev
    fi

    detect_python
    local PY_VER
    PY_VER=$($PYTHON_EXEC --version 2>/dev/null || echo "Python 3")
    log_success "Paquetes base del sistema y ${BOLD}${PY_VER}${NC} listos."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_system_packages
fi
