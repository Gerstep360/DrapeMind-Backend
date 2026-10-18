#!/usr/bin/env bash
# Retira sólo el servicio de la aplicación; conserva código y bases de datos.
set -euo pipefail
[[ "${EUID}" -eq 0 ]] || { echo 'Ejecuta con sudo.' >&2; exit 1; }
systemctl disable --now drapemind-backend.service || true
if [[ -f /etc/systemd/system/drapemind-backend.service ]]; then
    rm -- /etc/systemd/system/drapemind-backend.service
fi
systemctl daemon-reload
echo 'Servicio retirado. Los archivos y PostgreSQL se conservaron.'
