#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - INSTALADOR PRINCIPAL MODULAR Y TUI (FASTAPI + ALTAIR AI)
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
    echo "ERROR CRÍTICO: Directorio de módulos ${DEPLOY_DIR} no encontrado." >&2
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
    export INSTALL_FLOW=true
    tui_banner
    echo -e "${COLOR_PRIMARY}╭── [PROCESO DE INSTALACIÓN INTEGRAL] ──────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_ROCKET} Despliegue completo: Paquetes, BD, Python, .env, Gemma 4 y Systemd... ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    tui_step 1 8 "Instalación de Paquetes Base del Sistema (Ubuntu Linux)"
    install_system_packages

    tui_step 2 8 "Configuración y Protección de Variables de Entorno (.env)"
    sync_env_production

    tui_step 3 8 "Configuración Aislada de Base de Datos PostgreSQL"
    setup_postgresql

    tui_step 4 8 "Configuración de Entorno Virtual Python y Dependencias"
    setup_python_venv

    tui_step 5 8 "Aplicación de Migraciones Alembic y Sembrado Inicial"
    run_migrations_and_seed

    tui_step 6 8 "Instalación de Motor de Inferencia llama-server (Gemma 4)"
    install_llama_server false

    tui_step 7 8 "Descarga y Validación de Modelos Gemma 4 en Hugging Face"
    download_ai_models

    tui_step 8 8 "Configuración e Inicio del Servicio Systemd"
    setup_systemd

    sync_parent_config
    verify_backend
}

update_backend_code() {
    export INSTALL_FLOW=true
    tui_banner
    echo -e "${COLOR_PRIMARY}╭── [ACTUALIZACIÓN SEGURA DE DRAPEMIND BACKEND] ────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}🔄 Sincronizando repositorio, dependencias, entorno, BD y servicios...   ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    tui_step 1 5 "Sincronizando Código Fuente desde el Repositorio Git"
    _sync_git_repo() {
        cd "${BACKEND_DIR}"
        if ! git diff --quiet || ! git diff --cached --quiet 2>/dev/null; then
            git stash push -u -m "autostash_deploy_$(date +%s)" >/dev/null 2>&1 || true
        fi
        git fetch origin Main --quiet 2>&1
        if ! git pull origin Main --quiet 2>&1; then
            git reset --hard origin/Main >/dev/null 2>&1
        fi
        chmod +x "${BACKEND_DIR}"/*.sh "${BACKEND_DIR}"/scripts/deploy/*.sh 2>/dev/null || true
    }
    tui_spin_cmd "Descargando commits recientes desde origin/Main" _sync_git_repo

    tui_step 2 5 "Verificando Entorno Virtual y Nuevas Dependencias PIP"
    setup_python_venv

    tui_step 3 5 "Sincronizando Nuevas Variables en .env (Preservando Secretos)"
    sync_env_production

    tui_step 4 5 "Aplicando Migraciones de Base de Datos Alembic"
    run_migrations_and_seed

    tui_step 5 5 "Reiniciando Servicio Systemd drapemind-backend"
    restart_service

    sync_parent_config
    verify_backend
}

show_menu() {
    tui_banner
    echo -e "${COLOR_PRIMARY}╭── [MENÚ DE ADMINISTRACIÓN Y DESPLIEGUE] ──────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Selecciona una acción para gestionar el Backend de DrapeMind:           ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├────┬──────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  1 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_ROCKET} ${BOLD}Instalación Completa${NC} (Paquetes, BD, Python, .env, Gemma 4, Systemd)${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  2 ${NC}${COLOR_PRIMARY}│${NC}  🔄 ${BOLD}Actualizar desde Git${NC} (Pull + Migrar .env + Restart)                ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  3 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_SHIELD} ${BOLD}Sincronizar y Proteger .env${NC} (Agregar nuevas variables sin daño)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  4 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_GEAR} ${BOLD}Iniciar / Reiniciar Servicio${NC} (drapemind-backend en puerto 8045)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  5 ${NC}${COLOR_PRIMARY}│${NC}  📜 ${BOLD}Ver Logs del Backend${NC} (Journalctl FastAPI / Uvicorn)            ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  6 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_BRAIN} ${BOLD}Ver Logs de Llama / IA${NC} (Tokens, Velocidad y Generación en vivo)  ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  7 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_DATABASE} ${BOLD}Configurar PostgreSQL${NC} (Usuario, base de datos y migraciones)        ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  8 ${NC}${COLOR_PRIMARY}│${NC}  ⚡ ${BOLD}Instalar llama-server${NC} (Binarios GGML con soporte Gemma 4)           ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  9 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_BRAIN} ${BOLD}Descargar Modelos Gemma 4${NC} (Pesos E2B desde Hugging Face)            ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD} 10 ${NC}${COLOR_PRIMARY}│${NC}  🩺 ${BOLD}Verificar Diagnóstico y Salud${NC} (/health/ready y /health/ai)          ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  0 ${NC}${COLOR_PRIMARY}│${NC}  🚪 ${BOLD}Salir del Instalador${NC}                                                ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰────┴──────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

show_help() {
    tui_banner
    echo "Uso: sudo bash install.sh [OPCION]"
    echo ""
    echo "Opciones disponibles por línea de comando:"
    echo "  --all         Instalación completa (Paquetes, BD, Python, .env, llama-server, modelos, systemd)"
    echo "  --update      Actualiza código de Git, sincroniza .env con nuevas variables, migra BD y reinicia"
    echo "  --env         Sincroniza y actualiza únicamente las variables de entorno en .env"
    echo "  --db          Solo configura PostgreSQL, migraciones Alembic y sembrado inicial"
    echo "  --llama       Descarga o compila el binario llama-server con librerías GGML"
    echo "  --models      Descarga modelos Gemma 4 de Hugging Face"
    echo "  --service     Reconfigura y reinicia el servicio systemd"
    echo "  --restart     Solo reinicia el servicio systemd actual"
    echo "  --logs        Muestra logs de journalctl del backend en tiempo real"
    echo "  --logs-llama  Muestra logs de llama-server en tiempo real (tokens, velocidad y generación)"
    echo "  --check       Verifica endpoints de salud (/health/ready y /health/ai)"
    echo "  --help        Muestra esta ayuda"
    echo ""
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    show_help
    exit 0
fi

# Verificación de privilegios
check_root

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
    --restart)
        restart_service
        verify_backend
        ;;
    --logs|--logs-backend)
        view_logs
        ;;
    --logs-llama|--llama-logs|--ai-logs)
        view_llama_logs
        ;;
    --check)
        verify_backend
        ;;
    --help|-h)
        show_help
        ;;
    *)
        show_menu
        read -rp "  ${COLOR_ACCENT}${ICON_CHEVRON}${NC} ${BOLD}Selecciona una opción [0-10]:${NC} " opt
        case $opt in
            1)
                install_full
                ;;
            2)
                update_backend_code
                ;;
            3)
                sync_env_production
                ;;
            4)
                restart_service
                verify_backend
                ;;
            5)
                view_logs
                ;;
            6)
                view_llama_logs
                ;;
            7)
                setup_postgresql
                sync_env_production
                run_migrations_and_seed
                ;;
            8)
                install_llama_server true
                ;;
            9)
                download_ai_models
                ;;
            10)
                verify_backend
                ;;
            0)
                echo -e "  ${COLOR_MUTED}Saliendo del instalador...${NC}"
                exit 0
                ;;
            *)
                log_error "Opción no válida."
                exit 1
                ;;
        esac
        ;;
esac
