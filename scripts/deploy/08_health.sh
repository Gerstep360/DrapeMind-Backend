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

    local ROUTING_BADGE="${COLOR_MUTED}[ DESCONOCIDO ]${NC}"
    if echo "${AI_HEALTH}" | grep -q '"routing_mode":"scout"'; then
        ROUTING_BADGE="${COLOR_SUCCESS}${BOLD}[ scout (Orquestador Qwen) ]${NC}"
    elif echo "${AI_HEALTH}" | grep -q '"routing_mode":"legacy_gemma"'; then
        ROUTING_BADGE="${COLOR_WARNING}${BOLD}[ legacy_gemma (Directo Gemma 4) ]${NC}"
    fi

    echo ""
    echo -e "${COLOR_PRIMARY}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${COLOR_ACCENT}${ICON_SPARK} PANEL DE ESTADO — DRAPEMIND BACKEND & AGENTE ALTAIR${NC}                   ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Salud General:${NC}     ${HEALTH_BADGE}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Motor Gemma 4:${NC}     ${AI_BADGE} (Puerto ${AI_SERVER_PORT})"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}Enrutamiento IA:${NC}   ${ROUTING_BADGE}"
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
    local AUDIT_LOG_FILE="${LOG_DIR}/ai-audit.log"

    mkdir -p "${LOG_DIR}"
    touch "${LOG_FILE}" "${SCOUT_LOG_FILE}" "${AUDIT_LOG_FILE}" 2>/dev/null || true

    local GEMMA_PID
    GEMMA_PID=$(pgrep -f "port.*${AI_SERVER_PORT}" | head -n 1 || pgrep -f "llama-server" | head -n 1 || true)
    local SCOUT_PID
    SCOUT_PID=$(pgrep -f "port.*${SCOUT_SERVER_PORT}" | head -n 1 || true)

    if [[ -n "${GEMMA_PID}" ]]; then
        local GEMMA_MEM
        GEMMA_MEM=$(ps -p "${GEMMA_PID}" -o %cpu,%mem,rss --no-headers 2>/dev/null | awk '{print "CPU: "$1"% | RAM: "$2"% ("int($3/1024)" MB)"}' || echo "")
        echo -e "  ${COLOR_SUCCESS}${ICON_CHECK}${NC} ${BOLD}Gemma 4 (Síntesis):${NC}  ${COLOR_SUCCESS}${BOLD}[ ✔ ACTIVO ]${NC} (PID: ${BOLD}${GEMMA_PID}${NC} | Puerto: ${BOLD}${AI_SERVER_PORT}${NC})"
        [[ -n "${GEMMA_MEM}" ]] && echo -e "     ${COLOR_MUTED}Recursos:${NC} ${GEMMA_MEM}"
    else
        echo -e "  ${COLOR_WARNING}ℹ${NC}  ${BOLD}Gemma 4 (Síntesis):${NC}  ${COLOR_WARNING}${BOLD}[ ⏸ EN REPOSO / ON-DEMAND ]${NC} (Inicia si Scout delega síntesis)"
    fi

    if [[ -n "${SCOUT_PID}" ]]; then
        local SCOUT_MEM
        SCOUT_MEM=$(ps -p "${SCOUT_PID}" -o %cpu,%mem,rss --no-headers 2>/dev/null | awk '{print "CPU: "$1"% | RAM: "$2"% ("int($3/1024)" MB)"}' || echo "")
        echo -e "  ${COLOR_SUCCESS}${ICON_CHECK}${NC} ${BOLD}Scout Qwen (Orq.):${NC}   ${COLOR_SUCCESS}${BOLD}[ ✔ ACTIVO ]${NC} (PID: ${BOLD}${SCOUT_PID}${NC} | Puerto: ${BOLD}${SCOUT_SERVER_PORT}${NC})"
        [[ -n "${SCOUT_MEM}" ]] && echo -e "     ${COLOR_MUTED}Recursos:${NC} ${SCOUT_MEM}"
    else
        echo -e "  ${COLOR_WARNING}ℹ${NC}  ${BOLD}Scout Qwen (Orq.):${NC}   ${COLOR_WARNING}${BOLD}[ ⏸ EN REPOSO / ON-DEMAND ]${NC} (Inicia al recibir consultas)"
    fi

    echo ""
    echo -e "  ${COLOR_ACCENT}${BOLD}Guía de Marcadores en los Logs:${NC}"
    echo -e "  ${COLOR_PRIMARY}✦ [NUEVO MENSAJE]${NC}      Llegada de mensaje del usuario y modo de enrutamiento"
    echo -e "  ${COLOR_PRIMARY}✦ [SCOUT ORQUESTADOR]${NC}  Decisión de Scout, tokens consumidos y si delega o no"
    echo -e "  ${COLOR_PRIMARY}✦ [GEMMA 4 INFERENCIA]${NC} TTFT, velocidad (tokens/seg) y consumo del modelo grande"
    echo -e "  ${COLOR_PRIMARY}✦ [TURNO COMPLETADO]${NC}   Consumo total de tokens, latencia y diagnóstico de rendimiento"
    echo -e "  ${COLOR_MUTED}✦ [AI_AUDIT]{...}${NC}       Líneas JSON estructuradas para análisis automático con IA"
    echo ""
    echo -e "  ${COLOR_PRIMARY}${ICON_CHEVRON}${NC} ${BOLD}Monitoreando:${NC} ${COLOR_ACCENT}${LOG_FILE}${NC}, ${COLOR_ACCENT}${SCOUT_LOG_FILE}${NC} y ${COLOR_ACCENT}${AUDIT_LOG_FILE}${NC}"
    echo -e "  ${COLOR_MUTED}(Presiona ${BOLD}Ctrl+C${NC}${COLOR_MUTED} para detener el visor y volver al menú principal)${NC}"
    echo -e "${COLOR_PRIMARY}────────────────────────────────────────────────────────────────────────────${NC}"
    echo ""
    sleep 1

    tail -f -n 50 "${LOG_FILE}" "${SCOUT_LOG_FILE}" "${AUDIT_LOG_FILE}" 2>/dev/null || tail -f -n 50 "${LOG_FILE}" || true
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    verify_backend
fi
