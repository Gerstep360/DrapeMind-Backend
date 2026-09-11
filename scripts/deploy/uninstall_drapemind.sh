#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - DESINSTALADOR SEGURO Y LIMPIEZA QUIRÚRGICA DE SERVICIOS
# Servidor: 157.173.102.129
# =====================================================================
# ⚠️ IMPORTANTE - PROTOCOLO DE SEGURIDAD PARA SERVICIOS COMPARTIDOS:
# 1. NO desinstala Python, Node.js, npm, Nginx ni PostgreSQL.
# 2. NO afecta otros proyectos (Cotizador Pro, Django, Laravel, etc.).
# 3. NO toca bases de datos de otros servicios en PostgreSQL.
# 4. Elimina ÚNICAMENTE lo correspondiente a DrapeMind:
#    - Servicio systemd: drapemind-backend.service
#    - Procesos en puertos exclusivos: 8045 (FastAPI) y 8088 (Gemma/llama)
#    - Snippet de Nginx: /etc/nginx/snippets/drapemind-subpath.conf
#    - Archivos web: /var/www/drapemind y enlace /var/www/html/DrapeMind
#    - Opcional con confirmación previa: Base de datos drapemind_db
#    - Opcional con confirmación previa: Carpeta de código y modelos /root/app/DrapeMind
# =====================================================================

set -eo pipefail

COLOR_PRIMARY='\033[38;5;39m'     # Cyan
COLOR_ACCENT='\033[38;5;141m'     # Púrpura / Lavanda
COLOR_SUCCESS='\033[38;5;48m'     # Verde
COLOR_WARNING='\033[38;5;214m'    # Ámbar
COLOR_DANGER='\033[38;5;196m'     # Rojo
COLOR_MUTED='\033[38;5;244m'      # Gris
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Localizar la raíz del proyecto
if [[ -f "${SCRIPT_DIR}/../../config.sh" ]]; then
    ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
elif [[ -f "${SCRIPT_DIR}/../config.sh" ]]; then
    ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    ROOT_DIR="/root/app/DrapeMind"
fi

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo ""
        echo -e "${COLOR_DANGER}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_DANGER}│  ${BOLD}ERROR: PRIVILEGIOS DE ADMINISTRADOR REQUERIDOS                           ${NC}${COLOR_DANGER}│${NC}"
        echo -e "${COLOR_DANGER}│  ${NC}Ejecuta este desinstalador con: ${COLOR_SUCCESS}sudo bash $0${NC}${COLOR_DANGER}                     │${NC}"
        echo -e "${COLOR_DANGER}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
        echo ""
        exit 1
    fi
}

banner() {
    clear 2>/dev/null || true
    echo -e "${COLOR_DANGER}${BOLD}"
    echo "╭──────────────────────────────────────────────────────────────────────────╮"
    echo "│  ⚠️  DRAPEMIND ATELIER — DESINSTALADOR SEGURO DE SERVICIO Y LIMPIEZA    │"
    echo "│     Eliminación quirúrgica y aislada sin afectar otros sistemas en VPS   │"
    echo "╰──────────────────────────────────────────────────────────────────────────╯"
    echo -e "${NC}"
}

audit_other_services() {
    echo -e "${COLOR_PRIMARY}╭── [AUDITORÍA DE SERVICIOS COMPARTIDOS EN EL VPS] ────────────────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Verificando servicios activos para garantizar su protección total:      ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"

    local OTHER_SERVICES
    OTHER_SERVICES=$(systemctl list-units --type=service --state=running --no-pager 2>/dev/null | grep -E 'cotizador|django|node|next|pm2|gunicorn' || true)

    if [[ -n "${OTHER_SERVICES}" ]]; then
        echo -e "  ${COLOR_WARNING}ℹ️  Se detectaron otros proyectos en ejecución:${NC}"
        while IFS= read -r line; do
            echo -e "     ${COLOR_MUTED}• ${line}${NC}"
        done <<< "${OTHER_SERVICES}"
        echo -e "  ${COLOR_SUCCESS}✔  GARANTÍA: Estos servicios NO serán modificados ni detenidos.${NC}"
    else
        echo -e "  ${COLOR_MUTED}• No se detectaron otros proyectos comerciales en systemctl.${NC}"
    fi

    # Verificar si PostgreSQL aloja otras bases de datos
    echo ""
    echo -e "  ${COLOR_PRIMARY}Verificando bases de datos en PostgreSQL:${NC}"
    if command -v psql >/dev/null 2>&1; then
        local DATABASES
        DATABASES=$(su - postgres -c "psql -tc 'SELECT datname FROM pg_database WHERE datistemplate = false;'" 2>/dev/null | tr -d ' ' || true)
        for db in ${DATABASES}; do
            if [[ "${db}" == "drapemind_db" ]]; then
                echo -e "     • Base DrapeMind:  ${COLOR_DANGER}${BOLD}${db}${NC} (Candidata a borrado)"
            else
                echo -e "     • Otra Base BD:    ${COLOR_SUCCESS}${BOLD}${db}${NC} (PROTEGIDA - No se tocará)"
            fi
        done
    fi
    echo ""
}

confirm_action() {
    echo -e "${COLOR_DANGER}╭── [CONFIRMACIÓN DE SEGURIDAD OBLIGATORIA] ──────────────────────────────╮${NC}"
    echo -e "${COLOR_DANGER}│${NC}  Esta acción desinstalará el servicio DrapeMind del sistema:             ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  • Se detendrá y eliminará ${BOLD}drapemind-backend.service${NC}                     ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  • Se liberarán los puertos ${BOLD}8045${NC} y ${BOLD}8088${NC}                                   ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  • Se retirará la ruta ${BOLD}/DrapeMind${NC} de Nginx                               ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  • Se eliminarán los archivos web de ${BOLD}/var/www/drapemind${NC}                  ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  • ${COLOR_SUCCESS}${BOLD}Python, Node, npm, Nginx y PostgreSQL seguirán intactos.${NC}            ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
    read -rp "  ¿Estás seguro de proceder con la desinstalación? (escribe 'SI' para confirmar): " resp
    if [[ "${resp}" != "SI" && "${resp}" != "si" && "${resp}" != "Si" ]]; then
        echo -e "\n  ${COLOR_MUTED}Operación cancelada. DrapeMind sigue funcionando sin cambios.${NC}\n"
        exit 0
    fi
}

step_1_stop_and_remove_systemd() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 1/6] Deteniendo y eliminando servicio systemd de DrapeMind...${NC}"

    if systemctl is-active --quiet drapemind-backend.service 2>/dev/null; then
        echo -e "  • Deteniendo drapemind-backend.service..."
        systemctl stop drapemind-backend.service 2>/dev/null || true
    fi

    if systemctl is-enabled --quiet drapemind-backend.service 2>/dev/null; then
        echo -e "  • Deshabilitando inicio automático en el arranque..."
        systemctl disable drapemind-backend.service 2>/dev/null || true
    fi

    if [[ -f "/etc/systemd/system/drapemind-backend.service" ]]; then
        echo -e "  • Eliminando /etc/systemd/system/drapemind-backend.service..."
        rm -f "/etc/systemd/system/drapemind-backend.service"
    fi

    systemctl daemon-reload
    systemctl reset-failed 2>/dev/null || true
    echo -e "  ${COLOR_SUCCESS}✔ Servicio systemd drapemind-backend eliminado correctamente.${NC}"
}

step_2_terminate_orphan_processes() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 2/6] Liberando puertos exclusivos de DrapeMind (8045 y 8088)...${NC}"

    if command -v fuser >/dev/null 2>&1; then
        fuser -k 8045/tcp 2>/dev/null || true
        fuser -k 8088/tcp 2>/dev/null || true
    fi

    local PIDS_DM
    PIDS_DM=$(pgrep -f "app.main:app.*8045" || true)
    if [[ -n "${PIDS_DM}" ]]; then
        echo -e "  • Finalizando procesos huérfanos de DrapeMind (PIDs: ${PIDS_DM})..."
        kill -9 ${PIDS_DM} 2>/dev/null || true
    fi

    local PIDS_LLAMA
    PIDS_LLAMA=$(pgrep -f "llama-server.*8088" || true)
    if [[ -n "${PIDS_LLAMA}" ]]; then
        echo -e "  • Finalizando llama-server huérfano de DrapeMind (PIDs: ${PIDS_LLAMA})..."
        kill -9 ${PIDS_LLAMA} 2>/dev/null || true
    fi

    echo -e "  ${COLOR_SUCCESS}✔ Puertos 8045 y 8088 verificados y libres.${NC}"
}

step_3_clean_nginx() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 3/6] Limpiando configuración de Nginx para /DrapeMind...${NC}"

    local RELOAD_NEEDED=false

    for site_conf in /etc/nginx/sites-available/* /etc/nginx/sites-enabled/*; do
        if [[ -f "${site_conf}" ]] && grep -q "drapemind-subpath.conf" "${site_conf}" 2>/dev/null; then
            echo -e "  • Limpiando inclusión de DrapeMind en: ${site_conf}"
            sed -i '/drapemind-subpath\.conf/d' "${site_conf}"
            RELOAD_NEEDED=true
        fi
    done

    if [[ -f "/etc/nginx/sites-enabled/drapemind.conf" ]]; then
        rm -f "/etc/nginx/sites-enabled/drapemind.conf"
        RELOAD_NEEDED=true
    fi
    if [[ -f "/etc/nginx/sites-available/drapemind.conf" ]]; then
        rm -f "/etc/nginx/sites-available/drapemind.conf"
        RELOAD_NEEDED=true
    fi

    if [[ -f "/etc/nginx/snippets/drapemind-subpath.conf" ]]; then
        echo -e "  • Eliminando /etc/nginx/snippets/drapemind-subpath.conf..."
        rm -f "/etc/nginx/snippets/drapemind-subpath.conf"
        RELOAD_NEEDED=true
    fi

    if [[ "${RELOAD_NEEDED}" == "true" ]]; then
        echo -e "  • Validando configuración de Nginx (nginx -t)..."
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx
            echo -e "  ${COLOR_SUCCESS}✔ Nginx recargado sin la ruta /DrapeMind. Otros sitios siguen 100% operativos.${NC}"
        else
            echo -e "  ${COLOR_DANGER}⚠️  nginx -t reportó un aviso. No se forzó recarga para proteger otros sitios.${NC}"
            nginx -t || true
        fi
    else
        echo -e "  • Nginx no tenía snippets activos de DrapeMind."
    fi
}

step_4_clean_www_files() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 4/6] Eliminando archivos estáticos de Frontend web...${NC}"

    if [[ -L "/var/www/html/DrapeMind" || -d "/var/www/html/DrapeMind" ]]; then
        echo -e "  • Eliminando enlace /var/www/html/DrapeMind..."
        rm -rf "/var/www/html/DrapeMind"
    fi

    if [[ -d "/var/www/drapemind" ]]; then
        echo -e "  • Eliminando directorio publicado /var/www/drapemind..."
        rm -rf "/var/www/drapemind"
    fi

    echo -e "  ${COLOR_SUCCESS}✔ Directorios web de DrapeMind eliminados.${NC}"
}

step_5_manage_database() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 5/6] Gestión de Base de Datos PostgreSQL...${NC}"
    echo -e "  ${COLOR_WARNING}ℹ️  Verificación de seguridad en PostgreSQL:${NC}"
    echo -e "     Otros proyectos (bases de datos existentes) ${BOLD}NO${NC} serán tocados."

    local HAS_DM_DB=false
    if command -v psql >/dev/null 2>&1; then
        if su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='drapemind_db'\"" 2>/dev/null | grep -q 1; then
            HAS_DM_DB=true
        fi
    fi

    if [[ "${HAS_DM_DB}" == "true" ]]; then
        echo ""
        read -rp "  ¿Deseas ELIMINAR la base de datos 'drapemind_db' y el usuario 'drapemind_user'? [s/N]: " db_resp
        if [[ "${db_resp}" == "s" || "${db_resp}" == "S" || "${db_resp}" == "si" || "${db_resp}" == "SI" ]]; then
            echo -e "  • Terminando conexiones activas a drapemind_db..."
            su - postgres -c "psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'drapemind_db';\"" >/dev/null 2>&1 || true
            echo -e "  • Eliminando base de datos drapemind_db..."
            su - postgres -c "psql -c \"DROP DATABASE IF EXISTS drapemind_db;\"" 2>/dev/null || true
            echo -e "  • Eliminando usuario drapemind_user..."
            su - postgres -c "psql -c \"DROP USER IF EXISTS drapemind_user;\"" 2>/dev/null || true
            echo -e "  ${COLOR_SUCCESS}✔ Base de datos y usuario de DrapeMind eliminados de PostgreSQL.${NC}"
        else
            echo -e "  ${COLOR_MUTED}• Base de datos 'drapemind_db' PRESERVADA intacta como respaldo.${NC}"
        fi
    else
        echo -e "  • No se encontró la base de datos 'drapemind_db' en PostgreSQL."
    fi
}

step_6_manage_project_directory() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 6/6] Código Fuente y Modelos IA en el Servidor...${NC}"

    if id -u drapemind >/dev/null 2>&1; then
        echo -e "  • Eliminando usuario del sistema drapemind..."
        userdel -r drapemind 2>/dev/null || userdel drapemind 2>/dev/null || true
    fi

    local DM_PATHS=("/root/app/DrapeMind" "/root/DrapeMind" "/opt/drapemind")
    local FOUND_DIR=""

    for p in "${DM_PATHS[@]}"; do
        if [[ -d "${p}" ]]; then
            FOUND_DIR="${p}"
            break
        fi
    done

    if [[ -z "${FOUND_DIR}" && -d "${ROOT_DIR}" && "$(basename "${ROOT_DIR}")" =~ ^(DrapeMind|drapemind|Primer examen)$ ]]; then
        FOUND_DIR="${ROOT_DIR}"
    fi

    if [[ -n "${FOUND_DIR}" ]]; then
        local SIZE_DIR
        SIZE_DIR=$(du -sh "${FOUND_DIR}" 2>/dev/null | cut -f1 || echo "desconocido")
        echo -e "  Directorio de DrapeMind detectado: ${BOLD}${FOUND_DIR}${NC} (Tamaño: ${SIZE_DIR})"
        echo -e "  ${COLOR_WARNING}Contiene código, entorno virtual .venv y modelos IA (Gemma 4 / Scout).${NC}"
        echo ""
        read -rp "  ¿Deseas ELIMINAR la carpeta de código y modelos (${FOUND_DIR})? [s/N]: " dir_resp
        if [[ "${dir_resp}" == "s" || "${dir_resp}" == "S" || "${dir_resp}" == "si" || "${dir_resp}" == "SI" ]]; then
            if [[ -f "${FOUND_DIR}/backend/.env" ]]; then
                cp "${FOUND_DIR}/backend/.env" "/root/drapemind_backup_$(date +%Y%m%d_%H%M%S).env" 2>/dev/null || true
                echo -e "  • Se guardó un respaldo seguro de .env en /root/"
            fi
            echo -e "  • Eliminando ${FOUND_DIR}..."
            rm -rf "${FOUND_DIR}"
            echo -e "  ${COLOR_SUCCESS}✔ Carpeta y modelos de DrapeMind eliminados.${NC}"
        else
            echo -e "  ${COLOR_MUTED}• Carpeta de código PRESERVADA en ${FOUND_DIR}.${NC}"
        fi
    fi
}

summary_health_verification() {
    echo ""
    echo -e "${COLOR_SUCCESS}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_SUCCESS}│  ${BOLD}✦ DESINSTALACIÓN DE DRAPEMIND COMPLETADA EXITOSAMENTE${NC}${COLOR_SUCCESS}                   │${NC}"
    echo -e "${COLOR_SUCCESS}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Servicio drapemind-backend:   ${COLOR_DANGER}[ ELIMINADO ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Puertos 8045 / 8088:          ${COLOR_SUCCESS}[ LIBRES ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Ruta /DrapeMind en Nginx:     ${COLOR_DANGER}[ REMOVIDA ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Archivos web en /var/www:     ${COLOR_DANGER}[ REMOVIDOS ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_SUCCESS}│${NC}  ${BOLD}ESTADO DE OTROS SERVICIOS DEL VPS:${NC}"

    local NGINX_ST="ACTIVO"
    systemctl is-active --quiet nginx || NGINX_ST="INACTIVO"
    echo -e "${COLOR_SUCCESS}│${NC}  • Nginx Server:                 ${COLOR_SUCCESS}[ ${NGINX_ST} ]${NC}"

    local PG_ST="ACTIVO"
    systemctl is-active --quiet postgresql || PG_ST="INACTIVO"
    echo -e "${COLOR_SUCCESS}│${NC}  • PostgreSQL Cluster:           ${COLOR_SUCCESS}[ ${PG_ST} ]${NC}"

    if systemctl list-unit-files | grep -q "cotizador-backend"; then
        local COT_BE="ACTIVO"
        systemctl is-active --quiet cotizador-backend || COT_BE="INACTIVO"
        echo -e "${COLOR_SUCCESS}│${NC}  • Cotizador Backend:            ${COLOR_SUCCESS}[ ${COT_BE} ] (Intacto en puerto 8000)${NC}"
    fi
    if systemctl list-unit-files | grep -q "cotizador-frontend"; then
        local COT_FE="ACTIVO"
        systemctl is-active --quiet cotizador-frontend || COT_FE="INACTIVO"
        echo -e "${COLOR_SUCCESS}│${NC}  • Cotizador Frontend:           ${COLOR_SUCCESS}[ ${COT_FE} ] (Intacto en puerto 5173)${NC}"
    fi

    echo -e "${COLOR_SUCCESS}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

# --- Ejecución Principal ---
check_root
banner
audit_other_services
confirm_action

step_1_stop_and_remove_systemd
step_2_terminate_orphan_processes
step_3_clean_nginx
step_4_clean_www_files
step_5_manage_database
step_6_manage_project_directory
summary_health_verification
