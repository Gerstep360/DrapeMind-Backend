#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 05: INSTALACION Y VERIFICACION DE LLAMA-SERVER
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

install_llama_server() {
    check_root
    local FORCE="${1:-false}"
    log_info "Verificando compatibilidad y librerías GGML de llama-server para Gemma 4..."
    local NEED_INSTALL=false

    # Si las librerías ya existen en /usr/local/lib, asegurar que también estén en /usr/local/bin/
    if [[ -d "/usr/local/lib" ]]; then
        cp -a /usr/local/lib/libggml* /usr/local/bin/ 2>/dev/null || true
        cp -a /usr/local/lib/libllama* /usr/local/bin/ 2>/dev/null || true
        cp -a /usr/local/lib/libmtmd* /usr/local/bin/ 2>/dev/null || true
    fi

    if [[ "${FORCE}" == "true" ]]; then
        NEED_INSTALL=true
    elif ! command -v llama-server >/dev/null 2>&1 && [[ ! -x "/usr/local/bin/llama-server" ]]; then
        NEED_INSTALL=true
    else
        local CURRENT_BIN
        CURRENT_BIN=$(command -v llama-server || echo "/usr/local/bin/llama-server")
        local VER
        VER=$("${CURRENT_BIN}" --version 2>&1 || true)
        if ! echo "${VER}" | grep -qE "b108|b109|b11|v0\.[4-9]"; then
            log_warn "llama-server instalado es antiguo y no reconoce arquitectura 'gemma4' (${VER}). Actualizando..."
            NEED_INSTALL=true
        elif [[ ! -f "/usr/local/bin/libggml-cpu-x64.so" && ! -f "/usr/local/lib/libggml-cpu-x64.so" ]]; then
            log_warn "Faltan las librerías dinámicas de backend CPU (libggml-cpu-x64.so). Reinstalando..."
            NEED_INSTALL=true
        else
            log_success "llama-server y backend CPU de Gemma 4 verificados (${VER})."
        fi
    fi

    if [[ "${NEED_INSTALL}" == false ]]; then
        return 0
    fi

    log_info "Instalando paquetes de compilación y descarga para llama-server..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl wget tar gzip git build-essential cmake

    local ARCH
    ARCH=$(uname -m)
    local INSTALLED=false

    if [[ "${ARCH}" == "x86_64" ]]; then
        log_info "Descargando release oficial de llama.cpp con soporte Gemma 4..."
        local TMP_ARCHIVE="/tmp/llama-bin.tar.gz"
        local TMP_DIR="/tmp/llama-extract"
        rm -rf "${TMP_ARCHIVE}" "${TMP_DIR}"
        mkdir -p "${TMP_DIR}"

        local DOWNLOAD_URL
        DOWNLOAD_URL=$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases 2>/dev/null | grep -o 'https://github.com/ggml-org/llama.cpp/releases/download/[^"]*bin-ubuntu-x64\.tar\.gz' | head -n 1 || true)
        if [[ -z "${DOWNLOAD_URL}" ]]; then
            DOWNLOAD_URL="https://github.com/ggml-org/llama.cpp/releases/download/b10819/llama-b10819-bin-ubuntu-x64.tar.gz"
        fi

        log_info "Descargando binarios precompilados: ${DOWNLOAD_URL}..."
        if curl -fsSL "${DOWNLOAD_URL}" -o "${TMP_ARCHIVE}" 2>/dev/null && tar -xzf "${TMP_ARCHIVE}" -C "${TMP_DIR}" 2>/dev/null; then
            local SERVER_BIN
            SERVER_BIN=$(find "${TMP_DIR}" -type f -name "llama-server" | head -n 1)
            if [[ -n "${SERVER_BIN}" && -f "${SERVER_BIN}" ]]; then
                local EXTRACTED_DIR
                EXTRACTED_DIR=$(dirname "${SERVER_BIN}")
                log_info "Instalando binario llama-server y librerías dinámicas desde ${EXTRACTED_DIR}..."

                cp -a "${EXTRACTED_DIR}"/* /usr/local/bin/
                chmod +x /usr/local/bin/llama-* 2>/dev/null || true

                cp -a "${EXTRACTED_DIR}"/*.so* /usr/local/lib/ 2>/dev/null || true
                echo "/usr/local/lib" > /etc/ld.so.conf.d/llama.conf
                echo "/usr/local/bin" >> /etc/ld.so.conf.d/llama.conf
                ldconfig 2>/dev/null || true

                mkdir -p /opt/llama.cpp
                cp -a "${EXTRACTED_DIR}"/* /opt/llama.cpp/

                INSTALLED=true
                log_success "llama-server y librerías GGML instaladas exitosamente."
            fi
        fi
        rm -rf "${TMP_ARCHIVE}" "${TMP_DIR}"
    fi

    if [[ "${INSTALLED}" != true ]]; then
        log_info "Compilando llama-server desde código fuente actual con CMake..."
        mkdir -p /opt
        rm -rf /opt/llama.cpp
        git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
        cmake -B /opt/llama.cpp/build /opt/llama.cpp -DGGML_OPENMP=ON
        cmake --build /opt/llama.cpp/build --config Release -j$(nproc) --target llama-server
        cp -a /opt/llama.cpp/build/bin/* /usr/local/bin/
        chmod +x /usr/local/bin/llama-*
        log_success "llama-server compilado e instalado en /usr/local/bin/llama-server."
    fi

    if [[ -f "${BACKEND_DIR}/.env" ]]; then
        if grep -q "^LLAMA_SERVER_PATH=" "${BACKEND_DIR}/.env"; then
            sed -i 's|^LLAMA_SERVER_PATH=.*|LLAMA_SERVER_PATH="/usr/local/bin/llama-server"|' "${BACKEND_DIR}/.env"
        else
            echo 'LLAMA_SERVER_PATH="/usr/local/bin/llama-server"' >> "${BACKEND_DIR}/.env"
        fi
    fi

    if command -v llama-server >/dev/null 2>&1 || [[ -x "/usr/local/bin/llama-server" ]]; then
        log_success "Binario llama-server listo en /usr/local/bin/llama-server."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_llama_server "${1:-false}"
fi
