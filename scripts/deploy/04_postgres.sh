#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

setup_postgresql() {
    check_root
    if ! command -v psql >/dev/null 2>&1; then
        apt-get install -y -qq postgresql postgresql-contrib
    fi
    systemctl enable --now postgresql
    cd "${BACKEND_DIR}"
    # Use the configured URL and role; never replace existing database credentials.
    "${BACKEND_DIR}/.venv/bin/python" -m scripts.local_tasks create-db
}

run_migrations_only() {
    cd "${BACKEND_DIR}"
    "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head
}

run_seeder_only() {
    cd "${BACKEND_DIR}"
    "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data "$@"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ "${1:-}" == '--seed' ]]; then
        shift
        run_seeder_only "$@"
    else
        setup_postgresql
        run_migrations_only
    fi
fi
