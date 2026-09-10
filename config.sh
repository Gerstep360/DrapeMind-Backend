#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - PANEL DE CONTROL Y ORQUESTADOR GENERAL (CONFIG & DEPLOY)
# Acceso centralizado a los instaladores de Backend y Frontend / Web
# =====================================================================

set -eo pipefail

# Colores y Estilos ANSI
COLOR_PRIMARY='\033[38;5;39m'     # Cyan / Deep Sky Blue
COLOR_ACCENT='\033[38;5;141m'     # Lavender / Purple
COLOR_SUCCESS='\033[38;5;48m'     # Emerald Green
COLOR_WARNING='\033[38;5;214m'    # Amber / Gold
COLOR_DANGER='\033[38;5;196m'     # Coral Red
COLOR_MUTED='\033[38;5;244m'      # Slate Gray
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

SERVER_IP="157.173.102.129"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Si el script se ejecuta desde dentro de backend o DrapeMind-Backend, resolver la raíz en el padre
if [[ "$(basename "${SCRIPT_DIR}")" =~ ^(backend|Backend|DrapeMind-Backend|drapemind-backend)$ ]]; then
    ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    ROOT_DIR="${SCRIPT_DIR}"
fi

# Detección inteligente de directorios (VPS y local)
BACKEND_DIR=""
for candidate in \
    "${ROOT_DIR}/DrapeMind-Backend" \
    "${ROOT_DIR}/backend" \
    "${ROOT_DIR}/Backend" \
    "${ROOT_DIR}/drapemind-backend" \
    "${SCRIPT_DIR}"; do
    if [[ -d "${candidate}" && -f "${candidate}/install.sh" ]]; then
        BACKEND_DIR="${candidate}"
        break
    fi
done

WEB_DIR=""
for candidate in \
    "${ROOT_DIR}/DrapeMind-web" \
    "${ROOT_DIR}/DrapeMind-Web" \
    "${ROOT_DIR}/web" \
    "${ROOT_DIR}/Frontend" \
    "${ROOT_DIR}/frontend" \
    "${ROOT_DIR}/drapemind-web" \
    "${ROOT_DIR}/drapemind-frontend"; do
    if [[ -d "${candidate}" && -f "${candidate}/install.sh" ]]; then
        WEB_DIR="${candidate}"
        break
    fi
done

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo ""
        echo -e "${COLOR_DANGER}╭──────────────────────────────────────────────────────────────────────────╮"
        echo -e "│  ${BOLD}ERROR: SE REQUIEREN PRIVILEGIOS DE ADMINISTRADOR (SUDO)                  ${NC}${COLOR_DANGER}│"
        echo -e "│  ${NC}Para administrar systemd, Nginx, PostgreSQL y librerías de producción:  ${COLOR_DANGER}│"
        echo -e "│  ${BOLD}Ejecuta:${NC} ${COLOR_SUCCESS}sudo bash config.sh${NC}${COLOR_DANGER}                                            │"
        echo -e "╰──────────────────────────────────────────────────────────────────────────╯${NC}"
        echo ""
        exit 1
    fi
}

banner() {
    clear 2>/dev/null || true
    echo -e "${COLOR_PRIMARY}"
    echo "╭──────────────────────────────────────────────────────────────────────────╮"
    echo -e "│  ${BOLD}${COLOR_ACCENT}✦ DRAPEMIND ATELIER${COLOR_PRIMARY} — PANEL CENTRAL DE CONFIGURACIÓN Y DESPLIEGUE  │"
    echo -e "│  ${DIM}Gestor unificado de instalación, actualización y diagnóstico (VPS)       ${NC}${COLOR_PRIMARY}│"
    echo "├──────────────────────────────────────────────────────────────────────────┤"
    echo -e "│  ${COLOR_MUTED}Directorio Raíz:${NC}   ${BOLD}${ROOT_DIR}${NC}${COLOR_PRIMARY}"

    if [[ -n "${BACKEND_DIR}" ]]; then
        echo -e "│  ${COLOR_MUTED}Backend:${NC}           ${COLOR_SUCCESS}✔ Encontrado${NC} (${BOLD}$(basename "${BACKEND_DIR}")${NC})${COLOR_PRIMARY}"
    else
        echo -e "│  ${COLOR_MUTED}Backend:${NC}           ${COLOR_DANGER}✖ No detectado (revisa DrapeMind-Backend/)${NC}${COLOR_PRIMARY}"
    fi

    if [[ -n "${WEB_DIR}" ]]; then
        echo -e "│  ${COLOR_MUTED}Frontend Web:${NC}      ${COLOR_SUCCESS}✔ Encontrado${NC} (${BOLD}$(basename "${WEB_DIR}")${NC})${COLOR_PRIMARY}"
    else
        echo -e "│  ${COLOR_MUTED}Frontend Web:${NC}      ${COLOR_DANGER}✖ No detectado (revisa DrapeMind-web/)${NC}${COLOR_PRIMARY}"
    fi

    echo -e "│  ${COLOR_MUTED}IP Servidor:${NC}       ${BOLD}${SERVER_IP}${NC}${COLOR_PRIMARY}  •  URL: ${COLOR_ACCENT}http://${SERVER_IP}/DrapeMind/${NC}${COLOR_PRIMARY}     │"
    echo "╰──────────────────────────────────────────────────────────────────────────╯"
    echo -e "${NC}"
}

run_backend() {
    if [[ -z "${BACKEND_DIR}" || ! -f "${BACKEND_DIR}/install.sh" ]]; then
        echo -e "${COLOR_DANGER}ERROR: No se encontró install.sh en el directorio de Backend.${NC}"
        read -rp "Presiona Enter para continuar..."
        return 1
    fi
    chmod +x "${BACKEND_DIR}/install.sh"
    (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" "$@")
    echo ""
    echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
    read -r
}

run_web() {
    if [[ -z "${WEB_DIR}" || ! -f "${WEB_DIR}/install.sh" ]]; then
        echo -e "${COLOR_DANGER}ERROR: No se encontró install.sh en el directorio de Frontend / Web.${NC}"
        read -rp "Presiona Enter para continuar..."
        return 1
    fi
    chmod +x "${WEB_DIR}/install.sh"
    (cd "${WEB_DIR}" && bash "${WEB_DIR}/install.sh" "$@")
    echo ""
    echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
    read -r
}

run_install_all() {
    banner
    echo -e "${COLOR_PRIMARY}Iniciando instalación completa secuencial de Backend y Frontend...${NC}"
    echo ""

    if [[ -n "${BACKEND_DIR}" ]]; then
        echo -e "${COLOR_ACCENT}=== 1/2: INSTALANDO BACKEND (FastAPI + PostgreSQL + Gemma 4) ===${NC}"
        chmod +x "${BACKEND_DIR}/install.sh"
        (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --all)
    fi

    if [[ -n "${WEB_DIR}" ]]; then
        echo ""
        echo -e "${COLOR_ACCENT}=== 2/2: INSTALANDO FRONTEND (Angular + Nginx) ===${NC}"
        chmod +x "${WEB_DIR}/install.sh"
        (cd "${WEB_DIR}" && bash "${WEB_DIR}/install.sh" --all)
    fi

    verify_all
    echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
    read -r
}

run_update_all() {
    banner
    echo -e "${COLOR_PRIMARY}Actualizando repositorios y reiniciando servicios...${NC}"
    echo ""

    if [[ -n "${BACKEND_DIR}" ]]; then
        echo -e "${COLOR_ACCENT}=== Sincronizando Backend con Git y actualizando .env ===${NC}"
        (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --update)
    fi

    if [[ -n "${WEB_DIR}" ]]; then
        echo ""
        echo -e "${COLOR_ACCENT}=== Sincronizando Frontend con Git y recompilando Angular ===${NC}"
        (cd "${WEB_DIR}" && bash "${WEB_DIR}/install.sh" --update)
    fi

    verify_all
    echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
    read -r
}

verify_all() {
    echo ""
    echo -e "${COLOR_PRIMARY}╭── [ESTADO INTEGRAL DEL SISTEMA DRAPEMIND] ────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Comprobando conectividad HTTP, Nginx, FastAPI y motor de IA...          ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    local CODE_FE CODE_BE AI_HEALTH
    CODE_FE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1/DrapeMind/" 2>/dev/null || echo "000")
    CODE_BE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8045/health/ready" 2>/dev/null || echo "000")
    AI_HEALTH=$(curl -s "http://127.0.0.1:8045/health/ai" 2>/dev/null || echo '{"healthy":false}')

    local STATUS_FE="${COLOR_DANGER}[ ERROR ${CODE_FE} ]${NC}"
    [[ "${CODE_FE}" == "200" ]] && STATUS_FE="${COLOR_SUCCESS}${BOLD}[ ✔ OPERATIVO (HTTP 200) ]${NC}"

    local STATUS_BE="${COLOR_DANGER}[ ERROR ${CODE_BE} ]${NC}"
    [[ "${CODE_BE}" == "200" ]] && STATUS_BE="${COLOR_SUCCESS}${BOLD}[ ✔ OPERATIVO (HTTP 200) ]${NC}"

    local STATUS_AI="${COLOR_WARNING}[ ⏸ EN REPOSO (DEMANDA) ]${NC}"
    if echo "${AI_HEALTH}" | grep -q '"healthy":true'; then
        STATUS_AI="${COLOR_SUCCESS}${BOLD}[ ✔ ACTIVO ]${NC}"
    fi

    echo ""
    echo -e "${COLOR_PRIMARY}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${COLOR_ACCENT}✦ DIAGNÓSTICO DE PRODUCCIÓN EN ${SERVER_IP}${NC}                        ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Frontend Angular / Nginx:  ${STATUS_FE}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Backend FastAPI:           ${STATUS_BE}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Motor Gemma 4 (Altair):    ${STATUS_AI}"
    echo -e "${COLOR_PRIMARY}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Web Pública:        ${BOLD}http://${SERVER_IP}/DrapeMind/${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • API Catalog:        ${BOLD}http://${SERVER_IP}/DrapeMind/api/v1/catalog/products${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Swagger Docs:       ${BOLD}http://${SERVER_IP}/DrapeMind/docs${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • WebSocket Altair:   ${BOLD}ws://${SERVER_IP}/DrapeMind/api/v1/ws/ai${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  • Nginx Service:      systemctl status nginx"
    echo -e "${COLOR_PRIMARY}│${NC}  • Backend Service:    systemctl status drapemind-backend"
    echo -e "${COLOR_PRIMARY}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

show_menu() {
    banner
    echo -e "${COLOR_PRIMARY}╭── [MENÚ PRINCIPAL DE GESTIÓN] ───────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Accede a los instaladores independientes sin tener que cambiar de carpeta:${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}├────┬─────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  1 ${NC}${COLOR_PRIMARY}│${NC}  🚀  ${BOLD}Instalador de Backend${NC} (Python, PostgreSQL, Gemma 4, .env)     ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  2 ${NC}${COLOR_PRIMARY}│${NC}  🌐  ${BOLD}Instalador de Frontend / Web${NC} (Angular, Node.js, Nginx Proxy)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  3 ${NC}${COLOR_PRIMARY}│${NC}  ⚡  ${BOLD}Instalación Completa${NC} (Desplegar Backend + Frontend de una vez)  ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  4 ${NC}${COLOR_PRIMARY}│${NC}  🔄  ${BOLD}Actualizar Todo desde Git${NC} (Git pull en ambos + Build + Restart)  ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  5 ${NC}${COLOR_PRIMARY}│${NC}  🩺  ${BOLD}Diagnóstico Integral de Salud${NC} (Verificar HTTP y WebSockets)    ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  6 ${NC}${COLOR_PRIMARY}│${NC}  📜  ${BOLD}Ver Logs en Vivo de Backend${NC} (Journalctl drapemind-backend)       ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  7 ${NC}${COLOR_PRIMARY}│${NC}  🧠  ${BOLD}Ver Logs de Llama / IA en Vivo${NC} (Tokens y Generación en vivo)     ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  8 ${NC}${COLOR_PRIMARY}│${NC}  🛡️   ${BOLD}Sincronizar y Proteger .env${NC} (Actualizar variables de IA)         ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}│${BOLD}  0 ${NC}${COLOR_PRIMARY}│${NC}  🚪  ${BOLD}Salir${NC}                                                               ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰────┴─────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

# --- Ejecución ---
check_root

case "${1:-}" in
    --backend|-b)
        shift
        run_backend "$@"
        ;;
    --web|--frontend|-w)
        shift
        run_web "$@"
        ;;
    --all|-a)
        run_install_all
        ;;
    --update|-u)
        run_update_all
        ;;
    --check|-c)
        verify_all
        ;;
    --logs|-l)
        if [[ -n "${BACKEND_DIR}" ]]; then
            (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --logs)
        else
            journalctl -u drapemind-backend -f -n 50
        fi
        ;;
    --logs-llama|--llama-logs|-ll)
        if [[ -n "${BACKEND_DIR}" ]]; then
            (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --logs-llama)
        else
            tail -f -n 50 /root/drapemind/backend/logs/llama-server.log 2>/dev/null || true
        fi
        ;;
    --help|-h)
        banner
        echo "Uso: sudo bash config.sh [OPCION]"
        echo ""
        echo "Opciones disponibles:"
        echo "  --backend,  -b    Ejecuta el menú o tarea de Backend (DrapeMind-Backend/install.sh)"
        echo "  --web,      -w    Ejecuta el menú o tarea de Frontend (DrapeMind-web/install.sh)"
        echo "  --all,      -a    Instalación completa de Backend y Frontend"
        echo "  --update,   -u    Actualiza ambos con Git, migra .env, compila y reinicia"
        echo "  --check,    -c    Diagnóstico de salud y puertos del servidor"
        echo "  --logs,     -l    Muestra logs en tiempo real del backend"
        echo "  --logs-llama, -ll Muestra logs en tiempo real de llama-server (tokens y generación)"
        echo "  --help,     -h    Muestra esta ayuda"
        echo ""
        exit 0
        ;;
    *)
        while true; do
            show_menu
            read -rp "  ${COLOR_ACCENT}➜${NC} ${BOLD}Selecciona una opción [0-8]:${NC} " opt
            case $opt in
                1)
                    run_backend
                    ;;
                2)
                    run_web
                    ;;
                3)
                    run_install_all
                    ;;
                4)
                    run_update_all
                    ;;
                5)
                    banner
                    verify_all
                    echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
                    read -r
                    ;;
                6)
                    if [[ -n "${BACKEND_DIR}" ]]; then
                        (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --logs)
                    else
                        journalctl -u drapemind-backend -f -n 50
                    fi
                    ;;
                7)
                    if [[ -n "${BACKEND_DIR}" ]]; then
                        (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --logs-llama)
                    else
                        tail -f -n 50 /root/drapemind/backend/logs/llama-server.log 2>/dev/null || true
                    fi
                    ;;
                8)
                    if [[ -n "${BACKEND_DIR}" ]]; then
                        (cd "${BACKEND_DIR}" && bash "${BACKEND_DIR}/install.sh" --env)
                        echo -e "${COLOR_MUTED}Presiona Enter para regresar al menú principal...${NC}"
                        read -r
                    fi
                    ;;
                0)
                    echo -e "  ${COLOR_MUTED}Saliendo...${NC}"
                    exit 0
                    ;;
                *)
                    echo -e "  ${COLOR_DANGER}Opción no válida.${NC}"
                    sleep 1
                    ;;
            esac
        done
        ;;
esac
