#!/usr/bin/env bash
# Compatibilidad: el gestor nativo mantiene una sola lógica de despliegue.
set -euo pipefail
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
action="${1:---menu}"; shift || true
case "$action" in
 --all|--update|--db) action=--backend;;
 --check-ai) cd "$BACKEND_DIR"; exec "$BACKEND_DIR/.venv/bin/python" -m scripts.local_tasks check-ai "$@";;
 --logs-backend) action=--logs;;
esac
exec bash "$BACKEND_DIR/scripts/deploy/platform.sh" "$action" "$@"
