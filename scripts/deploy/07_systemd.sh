#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 07: SERVICIO SYSTEMD (FASTAPI + IA ADMINISTRADA)
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_systemd() {
    check_root

    echo -e "${COLOR_PRIMARY}╭── [SERVICIO DEL SISTEMA SYSTEMD] ─────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_GEAR} Registro y Configuración de drapemind-backend.service${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    local SERVICE_USER="drapemind"
    local SERVICE_GROUP="drapemind"

    # Si el proyecto se encuentra dentro de /root, el servicio debe ejecutarse como root
    # para evitar errores de permisos al cambiar de directorio (CHDIR)
    if [[ "${BACKEND_DIR}" == /root* ]]; then
        log_warn "El backend está en /root. Se ejecutará con usuario root para evitar errores de acceso."
        SERVICE_USER="root"
        SERVICE_GROUP="root"
    else
        if ! id -u drapemind >/dev/null 2>&1; then
            useradd -r -s /bin/false -d "${BACKEND_DIR}" drapemind || true
        fi
        chown -R drapemind:drapemind "${BACKEND_DIR}/logs" "${BACKEND_DIR}/ai_models" 2>/dev/null || true
    fi

    mkdir -p "${BACKEND_DIR}/logs" "${BACKEND_DIR}/ai_models"
    chmod -R 775 "${BACKEND_DIR}/logs" 2>/dev/null || true

    local SERVICE_DEST="/etc/systemd/system/drapemind-backend.service"

    cat <<EOF > "${SERVICE_DEST}"
[Unit]
Description=DrapeMind FastAPI Backend and Managed Gemma AI Runtime
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${BACKEND_DIR}
EnvironmentFile=${BACKEND_DIR}/.env
Environment="PATH=/usr/local/bin:/usr/bin:/bin:${BACKEND_DIR}/.venv/bin"
Environment="LLAMA_SERVER_PATH=/usr/local/bin/llama-server"
Environment="LD_LIBRARY_PATH=/usr/local/bin:/usr/local/lib"
Environment="GGML_BACKEND_PATH=/usr/local/bin"
ExecStart=${BACKEND_DIR}/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT} --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1 --ws-ping-interval 60 --ws-ping-timeout 300 --timeout-keep-alive 60
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    _reload_and_start_systemd() {
        systemctl daemon-reload
        systemctl enable drapemind-backend.service
        systemctl restart drapemind-backend.service
    }

    tui_spin_cmd "Habilitando e iniciando servicio drapemind-backend en systemd" _reload_and_start_systemd

    sleep 3
    if systemctl is-active --quiet drapemind-backend.service; then
        log_success "Servicio drapemind-backend activo y corriendo en el puerto ${BACKEND_PORT}."
    else
        log_error "El servicio no pudo iniciar. Mostrando últimos logs del journal:"
        journalctl -u drapemind-backend -n 25 --no-pager || true
        return 1
    fi
}

restart_service() {
    check_root

    echo -e "${COLOR_PRIMARY}╭── [REINICIAR SERVICIO] ───────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_GEAR} Reiniciando servicio drapemind-backend${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    tui_spin_cmd "Reiniciando proceso drapemind-backend en systemd" systemctl restart drapemind-backend.service

    sleep 2
    if systemctl is-active --quiet drapemind-backend.service; then
        log_success "Servicio reiniciado y respondiendo en el puerto ${BACKEND_PORT}."
    else
        log_error "Error al reiniciar el servicio drapemind-backend."
        journalctl -u drapemind-backend -n 25 --no-pager || true
        return 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_systemd
fi
