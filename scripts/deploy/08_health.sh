#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 08: VERIFICACION DE SALUD Y LOGS EN VIVO
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

verify_backend() {
    echo ""
    log_info "Verificando salud del backend en puerto ${BACKEND_PORT}..."
    sleep 2

    local HEALTH
    HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ready" || echo '{"status":"error"}')
    local AI_HEALTH
    AI_HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ai" || echo '{"healthy":false}')
    local AI_DESC="En reposo (inicia automáticamente bajo demanda al consultar a Altair)"

    if echo "${AI_HEALTH}" | grep -q '"healthy":true'; then
        AI_DESC="${GREEN}Activo y respondiendo${NC}"
    fi

    echo ""
    echo "======================================================================"
    echo -e " ${GREEN}${BOLD}✓ ESTADO DEL SERVICIO BACKEND DRAPEMIND${NC}"
    echo "======================================================================"
    echo -e " • Endpoint Salud:   http://127.0.0.1:${BACKEND_PORT}/health/ready"
    echo -e " • Respuesta Salud:  ${HEALTH}"
    echo -e " • Motor Gemma 4:    127.0.0.1:${AI_SERVER_PORT} (${AI_DESC})"
    echo -e " • API Pública:      http://${SERVER_IP}/DrapeMind/api/v1/catalog/products"
    echo -e " • Swagger Docs:     http://${SERVER_IP}/DrapeMind/docs"
    echo -e " • WebSocket AI:     ws://${SERVER_IP}/DrapeMind/api/v1/ws/ai"
    echo -e " • Systemd Service:  systemctl status drapemind-backend"
    echo "======================================================================"
    echo ""
}

view_logs() {
    echo "Mostrando logs en tiempo real (Presiona Ctrl+C para salir)..."
    sleep 1
    journalctl -u drapemind-backend -f -n 40
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    verify_backend
fi
