#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 04: BASE DE DATOS POSTGRESQL Y MIGRACIONES
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_postgresql() {
    check_root

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo -e "${COLOR_PRIMARY}╭── [BASE DE DATOS] ────────────────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_DATABASE} Configuración de PostgreSQL Aislada para DrapeMind${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    if command -v psql >/dev/null 2>&1 || systemctl is-active --quiet postgresql 2>/dev/null; then
        log_success "Servicio PostgreSQL activo y disponible en el servidor."
    else
        tui_spin_cmd "Instalando servicio PostgreSQL y módulos contrib" apt-get install -y -qq postgresql postgresql-contrib
        systemctl enable --now postgresql >/dev/null 2>&1 || true
        log_success "PostgreSQL instalado e iniciado como servicio."
    fi

    local DB_NAME="drapemind_db"
    local DB_USER="drapemind_user"
    local DB_PASS=""

    # 1. Intentar leer contraseña existente de .env
    if [[ -f "${BACKEND_DIR}/.env" ]]; then
        DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${BACKEND_DIR}/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    fi

    # 2. Si no hay contraseña en .env, buscar en .env_produccion para no romper la base de datos real
    if [[ -z "${DB_PASS}" || "${DB_PASS}" == *"CAMBIAR"* ]]; then
        if [[ -f "${BACKEND_DIR}/.env_produccion" ]]; then
            DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${BACKEND_DIR}/.env_produccion" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
        elif [[ -f "${BACKEND_DIR}/../.env_produccion" ]]; then
            DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${BACKEND_DIR}/../.env_produccion" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
        fi
    fi

    # 3. Solo si es una instalación totalmente virgen, generar clave aleatoria
    if [[ -z "${DB_PASS}" || "${DB_PASS}" == "postgres" || "${DB_PASS}" == *"CAMBIAR"* ]]; then
        DB_PASS=$(openssl rand -hex 12)
    fi

    _configure_pg_roles() {
        su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1 || \
            su - postgres -c "psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

        su - postgres -c "psql -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

        su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1 || \
            su - postgres -c "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\""

        su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\""
        su - postgres -c "psql -d ${DB_NAME} -c \"GRANT ALL ON SCHEMA public TO ${DB_USER};\"" >/dev/null 2>&1 || true
    }

    tui_spin_cmd "Configurando usuario '${DB_USER}' y base de datos '${DB_NAME}'" _configure_pg_roles

    export CONFIGURED_DB_USER="${DB_USER}"
    export CONFIGURED_DB_PASS="${DB_PASS}"
    export CONFIGURED_DB_NAME="${DB_NAME}"
    log_success "Base de datos y permisos de PostgreSQL listos."
}

run_migrations_and_seed() {
    cd "${BACKEND_DIR}"

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo -e "${COLOR_PRIMARY}╭── [MIGRACIONES Y DATOS] ──────────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_DATABASE} Aplicando Esquemas de Base de Datos y Catálogo Inicial${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    if [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
        tui_spin_cmd "Ejecutando migraciones de base de datos Alembic (upgrade head)" \
            "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head

        tui_spin_cmd "Sembrando catálogo inicial de productos, trajes y usuarios de prueba" \
            "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data || log_warn "El sembrado ya existía o finalizó con avisos menores."

        log_success "Migraciones y datos de prueba sincronizados correctamente."
    else
        log_warn "Entorno virtual .venv no encontrado; omite migraciones hasta crear el entorno."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_postgresql
    run_migrations_and_seed
fi
