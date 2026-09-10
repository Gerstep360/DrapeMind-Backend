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
    echo -e "${COLOR_PRIMARY}╭── [MONITOR DE LOGS EN VIVO — FASTAPI / UVICORN] ──────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_GEAR} Conectando a journalctl drapemind-backend (Presiona Ctrl+C para salir)...${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
    sleep 1
    journalctl -u drapemind-backend -f -n 50 || true
}

view_llama_logs() {
    echo ""
    echo -e "${COLOR_PRIMARY}╭── [MONITOR DE INFERENCIA IA — LLAMA-SERVER EN TIEMPO REAL] ──────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_BRAIN} Flujo de Generación de Tokens, Métricas y Slots en Vivo...            ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""

    local LOG_DIR="${BACKEND_DIR}/logs"
    local LOG_FILE="${LOG_DIR}/llama-server.log"
    local SCOUT_LOG_FILE="${LOG_DIR}/llama-scout.log"

    mkdir -p "${LOG_DIR}"
    touch "${LOG_FILE}"

    local LLAMA_PID
    LLAMA_PID=$(pgrep -f "llama-server" | head -n 1 || true)

    if [[ -n "${LLAMA_PID}" ]]; then
        local MEM_INFO
        MEM_INFO=$(ps -p "${LLAMA_PID}" -o %cpu,%mem,rss --no-headers 2>/dev/null | awk '{print "CPU: "$1"% | RAM: "$2"% ("int($3/1024)" MB)"}' || echo "")
        echo -e "  ${COLOR_SUCCESS}${ICON_CHECK}${NC} ${BOLD}Estado llama-server:${NC} ${COLOR_SUCCESS}${BOLD}[ ✔ ACTIVO ]${NC} (PID: ${BOLD}${LLAMA_PID}${NC} | Puerto: ${BOLD}${AI_SERVER_PORT}${NC})"
        if [[ -n "${MEM_INFO}" ]]; then
            echo -e "  ${COLOR_PRIMARY}${ICON_CHEVRON}${NC} ${BOLD}Uso de Recursos:${NC}    ${MEM_INFO}"
        fi
    else
        echo -e "  ${COLOR_WARNING}ℹ${NC}  ${BOLD}Estado llama-server:${NC} ${COLOR_WARNING}${BOLD}[ ⏸ EN REPOSO / ON-DEMAND ]${NC}"
        echo -e "  ${COLOR_MUTED}• El motor arranca automáticamente al recibir una consulta del Agente Altair / Web.${NC}"
        echo -e "  ${COLOR_MUTED}• En cuanto inicie la inferencia, verás aquí tokens/seg, prompt eval y streaming.${NC}"
    fi

    echo ""
    echo -e "  ${COLOR_PRIMARY}${ICON_CHEVRON}${NC} ${BOLD}Archivo de logs:${NC}     ${COLOR_ACCENT}${LOG_FILE}${NC}"
    echo -e "  ${COLOR_MUTED}(Presiona ${BOLD}Ctrl+C${NC}${COLOR_MUTED} para detener el visor y volver al menú principal)${NC}"
    echo -e "${COLOR_PRIMARY}────────────────────────────────────────────────────────────────────────────${NC}"
    echo ""
    sleep 1

    if [[ -f "${SCOUT_LOG_FILE}" ]]; then
        tail -f -n 50 "${LOG_FILE}" "${SCOUT_LOG_FILE}" || true
    else
        tail -f -n 50 "${LOG_FILE}" || true
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    verify_backend
fi
