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

    tui_step 7 8 "Descarga y Validación de Modelos IA (Gemma 4 y Scout Qwen)"
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
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}[ACTUALIZAR] Sincronizando repositorio, dependencias, BD y servicios...   ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    tui_step 1 5 "Sincronizando Código Fuente desde el Repositorio Git"
    _sync_git_repo() {
        cd "${BACKEND_DIR}"
        git fetch origin Main --quiet 2>&1 || git fetch --all --quiet 2>&1
        git reset --hard origin/Main >/dev/null 2>&1 || git reset --hard origin/main >/dev/null 2>&1 || git reset --hard HEAD >/dev/null 2>&1
        git clean -fd >/dev/null 2>&1 || true
        chmod +x "${BACKEND_DIR}"/*.sh "${BACKEND_DIR}"/scripts/deploy/*.sh 2>/dev/null || true
    }
    tui_spin_cmd "Descargando commits recientes desde origin/Main" _sync_git_repo

    tui_step 2 5 "Verificando Entorno Virtual y Nuevas Dependencias PIP"
    setup_python_venv

    tui_step 3 5 "Sincronizando Nuevas Variables en .env (Preservando Secretos)"
    sync_env_production

    tui_step 4 5 "Aplicando Migraciones de Base de Datos Alembic (Sin Sembrado)"
    run_migrations_only

    tui_step 5 5 "Reiniciando Servicio Systemd drapemind-backend"
    restart_service

    sync_parent_config
    verify_backend
}

prompt_and_run_seeder() {
    echo ""
    echo -e "${COLOR_PRIMARY}╭── [CONFIGURACIÓN DE POBLACIÓN DE BASE DE DATOS] ──────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Selecciona la escala de catálogo para optimizar rendimiento y login:      ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├───────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  1) Modo Ligero (40 prendas, 2 sucursales) - RECOMENDADO para evitar lag  ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  2) Modo Estándar (120 prendas, 3 sucursales) - Balance catálogo y memoria ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  3) Modo Completo (887 prendas, 5 sucursales) - Carga masiva total         ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  4) Personalizado (Indicar cantidad de ropa, sucursales y reset limpio)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    read -rp "  Selecciona perfil [1-4, por defecto 1]: " s_choice
    case "$s_choice" in
        2)
            run_seeder_only --standard --reset
            ;;
        3)
            run_seeder_only --full --reset
            ;;
        4)
            read -rp "  ¿Cuántas prendas de ropa deseas sembrar? [ej. 60]: " p_num
            p_val="${p_num:-60}"
            read -rp "  ¿Cuántas sucursales deseas activar? (1 a 5) [ej. 2]: " b_num
            b_val="${b_num:-2}"
            read -rp "  ¿Deseas limpiar tablas antes de sembrar (reset limpio)? [S/n]: " r_ans
            r_flag="--reset"
            if [[ "$r_ans" =~ ^[nN] ]]; then r_flag=""; fi
            run_seeder_only --products "$p_val" --branches "$b_val" $r_flag
            ;;
        *)
            run_seeder_only --quick --reset
            ;;
    esac
}

show_menu() {
    tui_banner
    echo -e "${COLOR_PRIMARY}╭── [MENÚ DE ADMINISTRACIÓN Y DESPLIEGUE] ──────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Selecciona una acción para gestionar el Backend de DrapeMind:           ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├────┬──────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  1 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_ROCKET} ${BOLD}Instalación Completa${NC} (Paquetes, BD, Python, .env, Gemma 4, Systemd)${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  2 ${NC}${COLOR_PRIMARY}│${NC}  [ACTUALIZAR] ${BOLD}Actualizar desde Git${NC} (Pull + Migrar .env + Restart)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  3 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_SHIELD} ${BOLD}Sincronizar y Proteger .env${NC} (Agregar nuevas variables sin daño)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  4 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_GEAR} ${BOLD}Iniciar / Reiniciar Servicio${NC} (drapemind-backend en puerto 8045)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  5 ${NC}${COLOR_PRIMARY}│${NC}  [LOGS] ${BOLD}Ver Logs del Backend${NC} (Journalctl FastAPI / Uvicorn)        ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  6 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_BRAIN} ${BOLD}Ver Logs de Llama / IA${NC} (Tokens, Velocidad y Generación en vivo)  ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  7 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_DATABASE} ${BOLD}Configurar PostgreSQL${NC} (Usuario, base de datos y migraciones)        ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  8 ${NC}${COLOR_PRIMARY}│${NC}  [LLAMA] ${BOLD}Instalar llama-server${NC} (Binarios GGML con soporte Gemma 4)      ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  9 ${NC}${COLOR_PRIMARY}│${NC}  ${ICON_BRAIN} ${BOLD}Descargar Modelos IA${NC} (Gemma 4 + Scout Qwen 0.6B)                 ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD} 10 ${NC}${COLOR_PRIMARY}│${NC}  [CHECK] ${BOLD}Verificar Diagnóstico y Salud${NC} (/health/ready y /health/ai)      ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD} 11 ${NC}${COLOR_PRIMARY}│${NC}  [SEEDER] ${BOLD}Sembrar Catálogo y Pruebas${NC} (Personalizable, sedes, stock)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  0 ${NC}${COLOR_PRIMARY}│${NC}  [SALIR] ${BOLD}Salir del Instalador${NC}                                            ${COLOR_PRIMARY}│${NC}"
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
    echo "  --seed        Ejecuta el seeder completo (catálogo población, usuarios por rol, inventario y pruebas)"
    echo "  --llama       Descarga o compila el binario llama-server con librerías GGML"
    echo "  --models      Descarga modelos IA (Gemma 4 y Scout Qwen 0.6B) de Hugging Face"
    echo "  --service     Reconfigura y reinicia el servicio systemd"
    echo "  --restart     Solo reinicia el servicio systemd actual"
    echo "  --logs        Muestra logs de journalctl del backend en tiempo real"
    echo "  --logs-llama  Muestra logs de llama-server en tiempo real (tokens, velocidad y generación)"
    echo "  --check       Verifica endpoints de salud (/health/ready y /health/ai)"
    echo "  --uninstall   Desinstala y elimina DrapeMind de forma quirúrgica"
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
        run_migrations_only
        ;;
    --seed)
        shift
        run_seeder_only "$@"
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
    --uninstall|--remove)
        for cand in \
            "${SCRIPT_DIR}/scripts/deploy/uninstall_drapemind.sh" \
            "${SCRIPT_DIR}/../scripts/uninstall_drapemind.sh" \
            "/root/app/DrapeMind/DrapeMind-Backend/scripts/deploy/uninstall_drapemind.sh" \
            "/root/app/DrapeMind/scripts/uninstall_drapemind.sh"; do
            if [[ -f "${cand}" ]]; then
                chmod +x "${cand}"
                exec bash "${cand}"
            fi
        done
        echo "ERROR: No se encontró uninstall_drapemind.sh."
        exit 1
        ;;
    --help|-h)
        show_help
        exit 0
        ;;
    *)
        show_menu
        read -rp "  ${COLOR_ACCENT}${ICON_CHEVRON}${NC} ${BOLD}Selecciona una opción [0-11]:${NC} " opt
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
                run_migrations_only
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
            11)
                prompt_and_run_seeder
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
