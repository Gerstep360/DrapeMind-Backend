#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 04: BASE DE DATOS POSTGRESQL Y MIGRACIONES
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_postgresql() {
    check_root
    log_info "Comprobando estado del servicio PostgreSQL..."
    local PG_INSTALLED=false

    if command -v psql >/dev/null 2>&1 || systemctl is-active --quiet postgresql 2>/dev/null; then
        PG_INSTALLED=true
        log_success "PostgreSQL ya se encuentra disponible en el servidor (no se alterará)."
    else
        log_info "Instalando PostgreSQL y módulos contrib..."
        apt-get install -y -qq postgresql postgresql-contrib
        systemctl enable --now postgresql
        log_success "PostgreSQL instalado e iniciado."
    fi

    local DB_NAME="drapemind_db"
    local DB_USER="drapemind_user"
    local DB_PASS=""

    if [[ -f "${BACKEND_DIR}/.env" ]]; then
        DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${BACKEND_DIR}/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    fi

    if [[ -z "${DB_PASS}" ]] || [[ "${DB_PASS}" == "postgres" ]] || [[ "${DB_PASS}" == *"CAMBIAR"* ]]; then
        DB_PASS=$(openssl rand -hex 12)
    fi

    log_info "Configurando rol de base de datos '${DB_USER}' y esquema '${DB_NAME}'..."

    su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1 || \
        su - postgres -c "psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

    su - postgres -c "psql -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1 || \
        su - postgres -c "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\""

    su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\""
    su - postgres -c "psql -d ${DB_NAME} -c \"GRANT ALL ON SCHEMA public TO ${DB_USER};\"" >/dev/null 2>&1 || true

    log_success "Base de datos y usuario de PostgreSQL configurados exitosamente."

    export CONFIGURED_DB_USER="${DB_USER}"
    export CONFIGURED_DB_PASS="${DB_PASS}"
    export CONFIGURED_DB_NAME="${DB_NAME}"
}

run_migrations_and_seed() {
    log_info "Aplicando migraciones Alembic en PostgreSQL..."
    cd "${BACKEND_DIR}"

    if [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
        "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head
        log_info "Sembrando catálogo inicial de productos y usuarios..."
        "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data || log_warn "El sembrado finalizó o ya contenía datos."
        log_success "Migraciones y datos iniciales aplicados correctamente."
    else
        log_warn "Entorno virtual no encontrado; omite migraciones hasta crear .venv."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    setup_postgresql
    run_migrations_and_seed
fi
