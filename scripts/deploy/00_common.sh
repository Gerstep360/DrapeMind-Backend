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

# Glifos e Iconografía TUI
ICON_ROCKET="🚀"
ICON_BRAIN="🧠"
ICON_SHIELD="🛡️ "
ICON_CHECK="✔"
ICON_CROSS="✖"
ICON_GEAR="⚙️ "
ICON_SPARK="✦"
ICON_CHEVRON="➜"
ICON_DOT="●"
ICON_PACKAGE="📦"
ICON_DATABASE="🗄️ "

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
log_warn()    { echo -e "  ${COLOR_WARNING}⚠${NC} ${YELLOW}$1${NC}"; }
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

# Indicador de Progreso Visual por Pasos (Stepper con Barra de Progreso)
tui_step() {
    local current="$1"
    local total="$2"
    local title="$3"

    local percent=$(( current * 100 / total ))
    local bar_width=24
    local filled_len=$(( percent * bar_width / 100 ))
    local empty_len=$(( bar_width - filled_len ))

    local bar=""
    for ((i=0; i<filled_len; i++)); do bar+="█"; done
    for ((i=0; i<empty_len; i++)); do bar+="░"; done

    echo ""
    echo -e "${COLOR_ACCENT}╭── [PASO ${current}/${total}] ──────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_ACCENT}│${NC}  ${COLOR_PRIMARY}[${bar}] ${percent}%${NC}  ${BOLD}${title}${NC}"
    echo -e "${COLOR_ACCENT}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

# Spinner de Animación para Comandos en Terminal
tui_spin_cmd() {
    local label="$1"
    shift
    local log_file="/tmp/drapemind-task-$$.log"

    # Si no hay terminal interactiva, ejecutar directamente
    if [[ ! -t 1 ]]; then
        log_info "${label}..."
        "$@"
        return $?
    fi

    # Ejecutar comando en segundo plano redirigiendo salida
    "$@" > "${log_file}" 2>&1 &
    local pid=$!

    local spin_chars=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0
    local start_time
    start_time=$(date +%s)

    # Ocultar cursor
    tput civis 2>/dev/null || printf "\033[?25l"

    while kill -0 "${pid}" 2>/dev/null; do
        local now
        now=$(date +%s)
        local elapsed=$(( now - start_time ))
        local char="${spin_chars[i % 10]}"
        printf "\r  ${COLOR_PRIMARY}${char}${NC} ${BOLD}%s${NC} ${COLOR_MUTED}(%ds)${NC} \033[K" "${label}" "${elapsed}"
        i=$((i + 1))
        sleep 0.08
    done

    # Restaurar cursor
    tput cnorm 2>/dev/null || printf "\033[?25h"

    wait "${pid}"
    local exit_code=$?
    local total_time=$(( $(date +%s) - start_time ))

    if [[ ${exit_code} -eq 0 ]]; then
        printf "\r  ${COLOR_SUCCESS}${ICON_CHECK}${NC} ${BOLD}%s${NC} ${COLOR_MUTED}(completado en %ds)${NC}\033[K\n" "${label}" "${total_time}"
        rm -f "${log_file}"
        return 0
    else
        printf "\r  ${COLOR_DANGER}${ICON_CROSS}${NC} ${BOLD}%s${NC} ${COLOR_DANGER}(falló tras %ds)${NC}\033[K\n" "${label}" "${total_time}"
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
