#!/usr/bin/env bash
# FastAPI + PostgreSQL; inferencia exclusivamente mediante NVIDIA API.
set -euo pipefail
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${BACKEND_DIR}/scripts/deploy"
source "${DEPLOY_DIR}/00_common.sh"
source "${DEPLOY_DIR}/01_env.sh"
source "${DEPLOY_DIR}/02_packages.sh"
source "${DEPLOY_DIR}/03_python.sh"
source "${DEPLOY_DIR}/04_postgres.sh"
source "${DEPLOY_DIR}/07_systemd.sh"
source "${DEPLOY_DIR}/08_health.sh"
cd "${BACKEND_DIR}"
action="${1:---help}"
shift || true
case "${action}" in
  --all)
    export INSTALL_FLOW=true
    install_system_packages
    sync_env_production
    setup_python_venv
    setup_postgresql
    run_migrations_only
    setup_systemd
    verify_backend
    echo 'Para cargar datos de ejemplo: bash install.sh --seed --quick'
    ;;
  --update)
    setup_python_venv
    sync_env_production
    run_migrations_only
    restart_service
    verify_backend
    ;;
  --env) sync_env_production ;;
  --db) setup_postgresql; run_migrations_only ;;
  --migrate) run_migrations_only ;;
  --seed) run_seeder_only "$@" ;;
  --service) setup_systemd ;;
  --restart) restart_service ;;
  --logs|--logs-backend|--ai-logs) journalctl -u drapemind-backend -f ;;
  --check) verify_backend ;;
  --check-ai) "${BACKEND_DIR}/.venv/bin/python" -m scripts.local_tasks check-ai ;;
  --uninstall|--remove) bash "${DEPLOY_DIR}/uninstall_drapemind.sh" ;;
  --help|-h)
    echo 'DrapeMind · FastAPI / PostgreSQL / NVIDIA API'
    echo '--all          Preparar sistema, entorno, DB, migraciones y servicio'
    echo '--update       Dependencias, migraciones y reinicio del checkout actual'
    echo '--env          Crear .env si falta; conserva credenciales existentes'
    echo '--db           Preparar PostgreSQL y migraciones'
    echo '--migrate      alembic upgrade head'
    echo '--seed [args]  Datos de ejemplo: --quick, --standard o --full'
    echo '--service      Instalar servicio systemd'
    echo '--restart      Reiniciar FastAPI'
    echo '--check        Comprobar salud de API y conexión NVIDIA'
    echo '--check-ai     Verificar streaming y herramientas con la cuenta NVIDIA'
    echo '--logs         Journal del backend'
    echo 'Local Windows: python iniciar_local.py'
    ;;
  *) echo "Opción desconocida: ${action}" >&2; exit 2 ;;
esac
