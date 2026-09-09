#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - INSTALADOR PRINCIPAL MODULAR DE BACKEND (FASTAPI + IA)
# Servidor IP: 157.173.102.129
# Puerto API: 8045 (8000 libre)
# Puerto Gemma 4: 8088 (8080 libre)
# Prefijo Proxy: /DrapeMind/api/
# =====================================================================

set -eo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${BACKEND_DIR}/scripts/deploy"

# Cargar módulos de despliegue
if [[ ! -d "${DEPLOY_DIR}" ]]; then
    echo "ERROR: Directorio de módulos ${DEPLOY_DIR} no encontrado." >&2
    exit 1
fi

source "${DEPLOY_DIR}/00_common.sh"
source "${DEPLOY_DIR}/01_env.sh"
source "${DEPLOY_DIR}/02_packages.sh"
source "${DEPLOY_DIR}/03_python.sh"
source "${DEPLOY_DIR}/04_postgres.sh"
source "${DEPLOY_DIR}/05_llama.sh"
source "${DEPLOY_DIR}/06_models.sh"
source "${DEPLOY_DIR}/07_systemd.sh"
source "${DEPLOY_DIR}/08_health.sh"

install_full() {
    banner
    install_system_packages
    setup_postgresql
    setup_python_venv
    sync_env_production
    run_migrations_and_seed
    install_llama_server false
    download_ai_models
    setup_systemd
    verify_backend
}

update_backend_code() {
    log_info "Actualizando backend con los cambios más recientes de Git..."
    cd "${BACKEND_DIR}"
    git pull || log_warn "Git pull no se pudo completar automáticamente (revisa si hay cambios locales sin confirmar)."

    setup_python_venv
    sync_env_production
    run_migrations_and_seed
    install_llama_server false
    setup_systemd
    verify_backend
}

show_help() {
    echo "Uso: sudo bash install.sh [OPCION]"
    echo ""
    echo "Opciones disponibles:"
    echo "  --all         Instalación completa modular (Paquetes, BD, Python, .env, llama-server, modelos, systemd)"
    echo "  --update      Actualiza código de Git, sincroniza .env con nuevas variables, migra BD y reinicia"
    echo "  --env         Sincroniza y actualiza únicamente las variables de entorno en .env"
    echo "  --db          Solo configura PostgreSQL, migraciones Alembic y sembrado inicial"
    echo "  --llama       Descarga o compila el binario llama-server con librerías GGML"
    echo "  --models      Descarga modelos Gemma 4 de Hugging Face"
    echo "  --service     Reconfigura y reinicia el servicio systemd"
    echo "  --logs        Muestra logs de journalctl en tiempo real"
    echo "  --check       Verifica endpoints de salud (/health/ready y /health/ai)"
    echo "  --help        Muestra esta ayuda"
    echo ""
}

# --- Ejecución ---
check_root
detect_python

case "${1:-}" in
    --all)
        install_full
        ;;
    --update)
        update_backend_code
        ;;
    --env)
        sync_env_production
        ;;
    --db)
        setup_postgresql
        sync_env_production
        run_migrations_and_seed
        ;;
    --llama)
        install_llama_server true
        ;;
    --models)
        download_ai_models
        ;;
    --service)
        setup_systemd
        verify_backend
        ;;
    --logs)
        view_logs
        ;;
    --check)
        verify_backend
        ;;
    --help|-h)
        show_help
        ;;
    *)
        banner
        echo "Selecciona una opción para el Backend:"
        echo "  1) Instalación completa de Backend (Recomendado con Gemma 4)"
        echo "  2) Iniciar / Reiniciar Servicio Systemd (Puerto 8045)"
        echo "  3) Actualizar Backend con cambios recientes de Git (Pull + Sincronizar .env + Restart)"
        echo "  4) Ver logs en vivo del Backend (Journalctl)"
        echo "  5) Solo configurar Base de Datos PostgreSQL"
        echo "  6) Solo descargar e instalar binario llama-server (Gemma 4)"
        echo "  7) Solo descargar Modelos Gemma 4 desde Hugging Face"
        echo "  8) Verificar estado de salud del Backend"
        echo "  9) Salir"
        echo ""
        read -rp "Opción [1-9]: " opt
        case $opt in
            1)
                install_full
                ;;
            2)
                setup_systemd
                verify_backend
                ;;
            3)
                update_backend_code
                ;;
            4)
                view_logs
                ;;
            5)
                setup_postgresql
                sync_env_production
                run_migrations_and_seed
                ;;
            6)
                install_llama_server true
                ;;
            7)
                download_ai_models
                ;;
            8)
                verify_backend
                ;;
            9)
                exit 0
                ;;
            *)
                log_error "Opción no válida."
                exit 1
                ;;
        esac
        ;;
esac
