#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 08: PANEL DE SALUD TUI Y LOGS EN VIVO
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

verify_backend() {
    echo ""
    echo -e "${COLOR_PRIMARY}╭── [DIAGNÓSTICO Y SALUD DEL SISTEMA] ──────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_SHIELD} Comprobando conectividad HTTP, base de datos y motor de IA...${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    tui_pulse_delay "Consultando endpoints de salud en 127.0.0.1:${BACKEND_PORT}..." 1

    local HEALTH
    HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ready" 2>/dev/null || echo '{"status":"error"}')
    local AI_HEALTH
    AI_HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ai" 2>/dev/null || echo '{"healthy":false}')

    local HEALTH_BADGE="${COLOR_DANGER}[ ERROR ]${NC}"
    if echo "${HEALTH}" | grep -q '"status":"ready"'; then
        HEALTH_BADGE="${COLOR_SUCCESS}${BOLD}[ ✔ OPERATIVO ]${NC}"
    fi

    local AI_BADGE="${COLOR_WARNING}[ ⏸ REPOSO (DEMANDA) ]${NC}"
    if echo "${AI_HEALTH}" | grep -q '"healthy":true'; then
        AI_BADGE="${COLOR_SUCCESS}${BOLD}[ ✔ ACTIVO ]${NC}"
    fi

    echo ""
    echo -e "${COLOR_PRIMARY}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${COLOR_ACCENT}${ICON_SPARK} PANEL DE ESTADO — DRAPEMIND BACKEND & AGENTE ALTAIR${NC}                   ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Salud General:${NC}     ${HEALTH_BADGE}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Motor Gemma 4:${NC}     ${AI_BADGE} (Puerto ${AI_SERVER_PORT})"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}API Interna:${NC}       http://127.0.0.1:${BACKEND_PORT}/health/ready"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}API Pública:${NC}       http://${SERVER_IP}/DrapeMind/api/v1/catalog/products"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Documentación:${NC}     http://${SERVER_IP}/DrapeMind/docs"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}WebSocket Altair:${NC}  ws://${SERVER_IP}/DrapeMind/api/v1/ws/ai"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Servicio Systemd:${NC}  systemctl status drapemind-backend"
    echo -e "${COLOR_PRIMARY}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

view_logs() {
    echo ""
    echo -e "${COLOR_PRIMARY}╭── [MONITOR DE LOGS EN VIVO] ──────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_GEAR} Conectando a journalctl drapemind-backend (Presiona Ctrl+C para salir)...${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
    sleep 1
    journalctl -u drapemind-backend -f -n 50
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    verify_backend
fi
