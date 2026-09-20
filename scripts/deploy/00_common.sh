#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 00: CONFIGURACION COMUN, TUI Y MOTOR DE ANIMACIONES
# =====================================================================

set -eo pipefail

# Paleta de Colores ANSI 256 / 16
COLOR_PRIMARY='\033[38;5;39m'     # Deep Sky Blue
COLOR_ACCENT='\033[38;5;141m'     # Lavender / Purple
COLOR_SUCCESS='\033[38;5;48m'     # Emerald Green
COLOR_WARNING='\033[38;5;214m'    # Amber / Gold
COLOR_DANGER='\033[38;5;196m'     # Coral Red
COLOR_MUTED='\033[38;5;244m'      # Slate Gray
COLOR_CARD='\033[48;5;236m'       # Dark Card Background
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Compatibilidad con scripts existentes
RED="${COLOR_DANGER}"
GREEN="${COLOR_SUCCESS}"
YELLOW="${COLOR_WARNING}"
CYAN="${COLOR_PRIMARY}"

# Glifos e Iconografia TUI (Cero emojis)
ICON_ROCKET="[DEPLOY]"
ICON_BRAIN="[IA]"
ICON_SHIELD="[SEC]"
ICON_CHECK="[OK]"
ICON_CROSS="[FAIL]"
ICON_GEAR="[*]"
ICON_SPARK="[+]"
ICON_CHEVRON="->"
ICON_DOT="*"
ICON_PACKAGE="[PKG]"
ICON_DATABASE="[DB]"

SERVER_IP="157.173.102.129"
BACKEND_PORT=8045
AI_SERVER_PORT=8088
SCOUT_SERVER_PORT=8089

# Resolver directorio raíz del backend
if [[ -z "${BACKEND_DIR}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

log_info()    { echo -e "  ${COLOR_PRIMARY}${ICON_CHEVRON}${NC} ${BOLD}$1${NC}"; }
log_success() { echo -e "  ${COLOR_SUCCESS}${ICON_CHECK}${NC} ${BOLD}$1${NC}"; }
log_warn()    { echo -e "  ${COLOR_WARNING}[WARN]${NC} ${YELLOW}$1${NC}"; }
log_error()   { echo -e "  ${COLOR_DANGER}${ICON_CROSS}${NC} ${RED}${BOLD}$1${NC}" >&2; }

# Limpieza segura del cursor al salir
cleanup_cursor() {
    tput cnorm 2>/dev/null || printf "\033[?25h"
}
trap cleanup_cursor EXIT INT TERM

# Banner de Cabecera Estilo GUI/TUI
tui_banner() {
    clear 2>/dev/null || true
    echo -e "${COLOR_PRIMARY}"
    echo "╭──────────────────────────────────────────────────────────────────────────╮"
    echo -e "│  ${BOLD}${COLOR_ACCENT}${ICON_SPARK} DRAPEMIND ATELIER${COLOR_PRIMARY} — BACKEND ENTERPRISE & ALTAIR AI ENGINE        │"
    echo -e "│  ${DIM}Entorno de Producción VPS Linux  •  FastAPI + Local Gemma 4 Runtime${NC}${COLOR_PRIMARY}      │"
    echo "├──────────────────────────────────────────────────────────────────────────┤"
    echo -e "│  ${COLOR_MUTED}IP Servidor:${NC}   ${BOLD}${SERVER_IP}${NC}${COLOR_PRIMARY}                                        │"
    echo -e "│  ${COLOR_MUTED}Directorio:${NC}    ${BOLD}${BACKEND_DIR}${NC}${COLOR_PRIMARY}"
    echo -e "│  ${COLOR_MUTED}FastAPI API:${NC}   ${COLOR_SUCCESS}http://127.0.0.1:${BACKEND_PORT}${NC}${COLOR_PRIMARY} (Prefijo: ${BOLD}/DrapeMind/api/${NC}${COLOR_PRIMARY})     │"
    echo -e "│  ${COLOR_MUTED}Gemma 4 AI:${NC}    ${COLOR_ACCENT}http://127.0.0.1:${AI_SERVER_PORT}${NC}${COLOR_PRIMARY} (llama-server local CPU)         │"
    echo "╰──────────────────────────────────────────────────────────────────────────╯"
    echo -e "${NC}"
}

banner() {
    tui_banner
}

# Indicador de Progreso Visual Limpio por Pasos
tui_step() {
    local current="$1"
    local total="$2"
    local title="$3"

    echo ""
    echo -e "  ${COLOR_PRIMARY}${BOLD}▶ [Paso ${current}/${total}]${NC} ${BOLD}${title}${NC}"
}

# Sincroniza automáticamente config.sh hacia el directorio padre app/DrapeMind
sync_parent_config() {
    local SRC_CONFIG="${BACKEND_DIR}/config.sh"
    if [[ ! -f "${SRC_CONFIG}" ]]; then
        return 0
    fi

    local CANDIDATE_DIRS=(
        "${BACKEND_DIR}/.."
        "/root/app/DrapeMind"
        "/root/DrapeMind"
        "${ROOT_DIR:-}"
    )

    for dir in "${CANDIDATE_DIRS[@]}"; do
        if [[ -n "${dir}" && -d "${dir}" && "${dir}" != "${BACKEND_DIR}" ]]; then
            local dest="${dir}/config.sh"
            if [[ -f "${dest}" || "${dir}" == *"/DrapeMind" || "${dir}" == *"/app/DrapeMind" ]]; then
                cp -f "${SRC_CONFIG}" "${dest}" 2>/dev/null || true
                chmod +x "${dest}" 2>/dev/null || true
                log_success "Archivo config.sh sincronizado en ${dest}"
            fi
        fi
    done
}

# Ejecutor Limpio de Comandos para Instalacion y Actualizacion
tui_spin_cmd() {
    local label="$1"
    shift
    local log_file="/tmp/drapemind-task-$$.log"

    log_info "${label}..."
    local start_time
    start_time=$(date +%s)

    # Ejecutar comando redirigiendo salida a log temporal
    if "$@" > "${log_file}" 2>&1; then
        local total_time=$(( $(date +%s) - start_time ))
        log_success "${label} (completado en ${total_time}s)"
        rm -f "${log_file}"
        return 0
    else
        local exit_code=$?
        local total_time=$(( $(date +%s) - start_time ))
        log_error "${label} (falló tras ${total_time}s - código ${exit_code})"
        if [[ -f "${log_file}" ]]; then
            echo -e "${COLOR_MUTED}  ┌── Detalle del error: ─────────────────────────────────────────────┐${NC}"
            while IFS= read -r line; do
                echo -e "${COLOR_MUTED}  │${NC} ${COLOR_DANGER}${line}${NC}"
            done < <(tail -n 12 "${log_file}")
            echo -e "${COLOR_MUTED}  └───────────────────────────────────────────────────────────────────┘${NC}"
            rm -f "${log_file}"
        fi
        return ${exit_code}
    fi
}

# Animación rápida de pausa con pulsación
tui_pulse_delay() {
    local text="$1"
    local seconds="${2:-1}"
    local steps=$(( seconds * 10 ))
    local dots=('·' '•' '●' '•')

    tput civis 2>/dev/null || printf "\033[?25l"
    for ((s=0; s<steps; s++)); do
        local dot="${dots[s % 4]}"
        printf "\r  ${COLOR_ACCENT}%s${NC} ${text} \033[K" "${dot}"
        sleep 0.1
    done
    tput cnorm 2>/dev/null || printf "\033[?25h"
    printf "\r\033[K"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo ""
        echo -e "${COLOR_DANGER}╭──────────────────────────────────────────────────────────────────────────╮"
        echo -e "│  ${BOLD}ERROR: PRIVILEGIOS DE ADMINISTRADOR REQUERIDOS                          ${NC}${COLOR_DANGER}│"
        echo -e "│  ${NC}Este instalador gestiona servicios systemd, dependencias y PostgreSQL.  ${COLOR_DANGER}│"
        echo -e "│  ${BOLD}Por favor ejecuta:${NC} ${COLOR_SUCCESS}sudo bash install.sh${NC}${COLOR_DANGER}                                  │"
        echo -e "╰──────────────────────────────────────────────────────────────────────────╯${NC}"
        echo ""
        exit 1
    fi
}
