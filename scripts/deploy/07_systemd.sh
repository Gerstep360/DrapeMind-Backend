#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 07: SERVICIO SYSTEMD (FASTAPI + IA ADMINISTRADA)
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_systemd() {
    check_root
    log_info "Configurando servicio systemd (drapemind-backend.service)..."

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

    systemctl daemon-reload
    systemctl enable drapemind-backend.service
    systemctl restart drapemind-backend.service

    sleep 3
    if systemctl is-active --quiet drapemind-backend.service; then
        log_success "Servicio drapemind-backend activo en puerto ${BACKEND_PORT}."
    else
        log_error "El servicio no pudo iniciar. Mostrando últimos logs:"
        journalctl -u drapemind-backend -n 25 --no-pager || true
    fi
}

restart_service() {
    check_root
    log_info "Reiniciando servicio drapemind-backend..."
    systemctl restart drapemind-backend.service
    sleep 2
    if systemctl is-active --quiet drapemind-backend.service; then
        log_success "Servicio drapemind-backend reiniciado correctamente."
    else
        log_error "Error al reiniciar drapemind-backend."
        journalctl -u drapemind-backend -n 25 --no-pager || true
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_systemd
fi
