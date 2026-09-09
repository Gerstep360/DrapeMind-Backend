#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 00: CONFIGURACION COMUN Y UTILIDADES
# =====================================================================

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SERVER_IP="157.173.102.129"
BACKEND_PORT=8045
AI_SERVER_PORT=8088

# Resolver directorio raíz del backend
if [[ -z "${BACKEND_DIR}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

log_info() { echo -e "${CYAN}${BOLD}[BACKEND INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}${BOLD}[BACKEND OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}${BOLD}[BACKEND AVISO]${NC} $1"; }
log_error() { echo -e "${RED}${BOLD}[BACKEND ERROR]${NC} $1" >&2; }

banner() {
    clear 2>/dev/null || true
    echo -e "${CYAN}${BOLD}"
    echo "======================================================================"
    echo "       DRAPEMIND ATELIER - INSTALADOR INDEPENDIENTE DE BACKEND"
    echo "======================================================================"
    echo -e "${NC}"
    echo -e " Directorio Backend: ${BOLD}${BACKEND_DIR}${NC}"
    echo -e " Puerto FastAPI:     ${BOLD}127.0.0.1:${BACKEND_PORT}${NC} (8000 queda libre)"
    echo -e " Puerto Gemma 4:     ${BOLD}127.0.0.1:${AI_SERVER_PORT}${NC} (8080 queda libre)"
    echo -e " Prefijo API:        ${BOLD}/DrapeMind/api/${NC}"
    echo "======================================================================"
    echo ""
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Se requieren privilegios de administrador (sudo)."
        echo "Ejecuta: sudo bash install.sh"
        exit 1
    fi
}
