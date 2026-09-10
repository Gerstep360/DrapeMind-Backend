#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 05: MOTOR DE INFERENCIA LOCAL LLAMA-SERVER (GEMMA 4)
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

install_llama_server() {
    check_root
    local FORCE="${1:-false}"

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo -e "${COLOR_PRIMARY}╭── [MOTOR DE INFERENCIA IA] ───────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_BRAIN} Verificación y Despliegue de llama-server con soporte Gemma 4${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    local NEED_INSTALL=false

    # Si las librerías existen en /usr/local/lib, asegurar que también estén en /usr/local/bin/
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
            log_warn "llama-server instalado es antiguo y no reconoce la arquitectura 'gemma4' (${VER}). Actualizando..."
            NEED_INSTALL=true
        elif [[ ! -f "/usr/local/bin/libggml-cpu-x64.so" && ! -f "/usr/local/lib/libggml-cpu-x64.so" ]]; then
            log_warn "Faltan las librerías dinámicas de backend CPU (libggml-cpu-x64.so). Reinstalando..."
            NEED_INSTALL=true
        else
            log_success "llama-server y backend GGML para CPU de Gemma 4 verificados (${VER})."
        fi
    fi

    if [[ "${NEED_INSTALL}" == false ]]; then
        return 0
    fi

    export DEBIAN_FRONTEND=noninteractive
    tui_spin_cmd "Instalando paquetes para compilación y descarga de llama.cpp" \
        apt-get install -y -qq curl wget tar gzip git build-essential cmake

    local ARCH
    ARCH=$(uname -m)
    local INSTALLED=false

    if [[ "${ARCH}" == "x86_64" ]]; then
        local TMP_ARCHIVE="/tmp/llama-bin.tar.gz"
        local TMP_DIR="/tmp/llama-extract"
        rm -rf "${TMP_ARCHIVE}" "${TMP_DIR}"
        mkdir -p "${TMP_DIR}"

        local DOWNLOAD_URL
        DOWNLOAD_URL=$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases 2>/dev/null | grep -o 'https://github.com/ggml-org/llama.cpp/releases/download/[^"]*bin-ubuntu-x64\.tar\.gz' | head -n 1 || true)
        if [[ -z "${DOWNLOAD_URL}" ]]; then
            DOWNLOAD_URL="https://github.com/ggml-org/llama.cpp/releases/download/b10819/llama-b10819-bin-ubuntu-x64.tar.gz"
        fi

        _download_and_extract_llama() {
            curl -fsSL "${DOWNLOAD_URL}" -o "${TMP_ARCHIVE}" && tar -xzf "${TMP_ARCHIVE}" -C "${TMP_DIR}"
            local SERVER_BIN
            SERVER_BIN=$(find "${TMP_DIR}" -type f -name "llama-server" | head -n 1)
            if [[ -n "${SERVER_BIN}" && -f "${SERVER_BIN}" ]]; then
                local EXTRACTED_DIR
                EXTRACTED_DIR=$(dirname "${SERVER_BIN}")
                cp -a "${EXTRACTED_DIR}"/* /usr/local/bin/
                chmod +x /usr/local/bin/llama-* 2>/dev/null || true
                cp -a "${EXTRACTED_DIR}"/*.so* /usr/local/lib/ 2>/dev/null || true
                echo "/usr/local/lib" > /etc/ld.so.conf.d/llama.conf
                echo "/usr/local/bin" >> /etc/ld.so.conf.d/llama.conf
                ldconfig 2>/dev/null || true
                mkdir -p /opt/llama.cpp
                cp -a "${EXTRACTED_DIR}"/* /opt/llama.cpp/
            else
                return 1
            fi
        }

        if tui_spin_cmd "Descargando e instalando binarios oficiales de llama.cpp (release x86_64)" _download_and_extract_llama; then
            INSTALLED=true
        fi
        rm -rf "${TMP_ARCHIVE}" "${TMP_DIR}"
    fi

    if [[ "${INSTALLED}" != true ]]; then
        _compile_llama_from_source() {
            mkdir -p /opt
            rm -rf /opt/llama.cpp
            git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
            cmake -B /opt/llama.cpp/build /opt/llama.cpp -DGGML_OPENMP=ON
            cmake --build /opt/llama.cpp/build --config Release -j"$(nproc)" --target llama-server
            cp -a /opt/llama.cpp/build/bin/* /usr/local/bin/
            chmod +x /usr/local/bin/llama-*
        }

        tui_spin_cmd "Compilando llama-server desde código fuente con CMake y OpenMP" _compile_llama_from_source
    fi

    if [[ -f "${BACKEND_DIR}/.env" ]]; then
        if grep -q "^LLAMA_SERVER_PATH=" "${BACKEND_DIR}/.env"; then
            sed -i 's|^LLAMA_SERVER_PATH=.*|LLAMA_SERVER_PATH="/usr/local/bin/llama-server"|' "${BACKEND_DIR}/.env"
        else
            echo 'LLAMA_SERVER_PATH="/usr/local/bin/llama-server"' >> "${BACKEND_DIR}/.env"
        fi
    fi

    log_success "Binario llama-server listo en /usr/local/bin/llama-server."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_llama_server "${1:-false}"
fi
