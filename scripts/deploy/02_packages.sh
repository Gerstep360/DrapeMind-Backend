#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 02: INSTALACION DE PAQUETES DEL SISTEMA
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

detect_python() {
    log_info "Detectando versión de Python disponible..."
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_EXEC="python3.11"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_EXEC="python3"
    else
        log_warn "Python 3 no detectado aún en el PATH. Se instalará automáticamente."
        PYTHON_EXEC="python3"
    fi
    log_success "Intérprete Python objetivo: $($PYTHON_EXEC --version 2>/dev/null || echo 'Pendiente de instalación')"
}

install_system_packages() {
    check_root
    log_info "Instalando paquetes base del sistema para FastAPI y librerías C++..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq

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
        apt-get install -y -qq python3 python3-venv python3-pip python3-dev
    fi

    detect_python
    log_success "Paquetes base del sistema instalados exitosamente."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_system_packages
fi
