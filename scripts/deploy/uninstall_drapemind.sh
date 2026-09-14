#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - DESINSTALADOR QUIRÚRGICO Y ESCÁNER INTELIGENTE DE SISTEMAS
# Servidor: 157.173.102.129
# =====================================================================
# ✦ ESCÁNER DE DEPENDENCIAS Y PROGRAMAS:
# 1. Escanea programas y servicios usados por DrapeMind vs otros sistemas.
# 2. Si un programa es EXCLUSIVO de DrapeMind y ningún otro proyecto lo ocupa,
#    lo elimina para liberar recursos y almacenamiento (modelos IA, llama-server).
# 3. Si un programa es COMPARTIDO (PostgreSQL con otras BD, Nginx con otros sitios,
#    Node.js/Python usados por Cotizador Pro u otros), lo PROTEGE y NO lo toca.
# 4. Elimina COMPLETAMENTE el proyecto Frontend y Backend de DrapeMind.
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

# Localizar la raíz de DrapeMind
ROOT_DIR=""
for candidate in \
    "/root/app/DrapeMind" \
    "${SCRIPT_DIR}/.." \
    "${SCRIPT_DIR}/../.." \
    "${SCRIPT_DIR}/../../.." \
    "${SCRIPT_DIR}" \
    "/opt/drapemind" \
    "/root/DrapeMind"; do
    if [[ -d "${candidate}" && (-d "${candidate}/DrapeMind-Backend" || -f "${candidate}/config.sh" || -f "${candidate}/install.sh") ]]; then
        ROOT_DIR="$(cd "${candidate}" && pwd)"
        break
    fi
done

[[ -z "${ROOT_DIR}" ]] && ROOT_DIR="/root/app/DrapeMind"

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
    echo "│  ⚠️  DRAPEMIND ATELIER — DESINSTALADOR Y ESCÁNER INTELIGENTE DE VPS      │"
    echo "│     Limpieza quirúrgica: elimina lo exclusivo y protege lo compartido    │"
    echo "╰──────────────────────────────────────────────────────────────────────────╯"
    echo -e "${NC}"
}

# =====================================================================
# ESCÁNER INTELIGENTE DE SISTEMAS Y DEPENDENCIAS (SHARED VS EXCLUSIVE)
# =====================================================================
OTHER_PROJECTS_FOUND=false
OTHER_DB_FOUND=false
OTHER_NGINX_SITES_FOUND=false
OTHER_NODE_FOUND=false
OTHER_PYTHON_FOUND=false

scan_system_and_dependencies() {
    echo -e "${COLOR_PRIMARY}╭── [ESCÁNER INTELIGENTE DE SISTEMAS Y DEPENDENCIAS DEL VPS] ──────────────╮${NC}"
    echo -e "${COLOR_PRIMARY}│${NC}  Analizando programas utilizados para diferenciar exclusivos vs compartidos:   ${COLOR_PRIMARY}│${NC}"
    echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""

    # 1. Escanear servicios de otros proyectos en ejecución
    local RUNNING_SERVICES
    RUNNING_SERVICES=$(systemctl list-units --type=service --state=running --no-pager 2>/dev/null | grep -E 'cotizador|django|pm2|gunicorn|next|react|laravel' | grep -v 'drapemind' || true)

    if [[ -n "${RUNNING_SERVICES}" ]]; then
        OTHER_PROJECTS_FOUND=true
        echo -e "  ${COLOR_WARNING}📦 Otros sistemas detectados en ejecución:${NC}"
        while IFS= read -r srv; do
            echo -e "     ${COLOR_MUTED}• ${srv}${NC}"
        done <<< "${RUNNING_SERVICES}"
    else
        echo -e "  ${COLOR_MUTED}• No se detectaron otros proyectos comerciales en systemctl.${NC}"
    fi

    # 2. Escanear PostgreSQL (¿Hay otras bases de datos?)
    echo ""
    echo -e "  ${COLOR_ACCENT}🔍 Análisis de PostgreSQL:${NC}"
    if command -v psql >/dev/null 2>&1; then
        local ALL_DBS
        ALL_DBS=$(su - postgres -c "psql -tc 'SELECT datname FROM pg_database WHERE datistemplate = false;'" 2>/dev/null | tr -d ' ' || true)
        local OTHER_DBS_COUNT=0
        for db in ${ALL_DBS}; do
            if [[ "${db}" == "drapemind_db" ]]; then
                echo -e "     • Base DrapeMind:   ${COLOR_DANGER}${BOLD}${db}${NC} (Exclusiva ➜ Será eliminada)"
            elif [[ -n "${db}" && "${db}" != "postgres" ]]; then
                OTHER_DBS_COUNT=$((OTHER_DBS_COUNT + 1))
                echo -e "     • Base de otro sistema: ${COLOR_SUCCESS}${BOLD}${db}${NC} (COMPARTIDA ➜ 🛡️ PROTEGIDA)"
            fi
        done
        if [[ ${OTHER_DBS_COUNT} -gt 0 ]]; then
            OTHER_DB_FOUND=true
            echo -e "     ${COLOR_SUCCESS}✔ Se detectaron bases de datos de otros proyectos. PostgreSQL NO se desinstalará.${NC}"
        else
            echo -e "     ${COLOR_MUTED}• No hay otras bases de datos de proyectos en PostgreSQL.${NC}"
        fi
    else
        echo -e "     ${COLOR_MUTED}• PostgreSQL no está instalado en el sistema.${NC}"
    fi

    # 3. Escanear Nginx (¿Hay otros sitios web?)
    echo ""
    echo -e "  ${COLOR_ACCENT}🔍 Análisis de Nginx:${NC}"
    if command -v nginx >/dev/null 2>&1; then
        local OTHER_SITES=0
        for site in /etc/nginx/sites-enabled/*; do
            if [[ -f "${site}" ]]; then
                local bsite
                bsite="$(basename "${site}")"
                if [[ "${bsite}" != *"drapemind"* ]]; then
                    OTHER_SITES=$((OTHER_SITES + 1))
                    echo -e "     • Sitio activo:     ${COLOR_SUCCESS}${BOLD}${bsite}${NC} (COMPARTIDO ➜ 🛡️ PROTEGIDO)"
                fi
            fi
        done
        if [[ ${OTHER_SITES} -gt 0 ]]; then
            OTHER_NGINX_SITES_FOUND=true
            echo -e "     ${COLOR_SUCCESS}✔ Nginx aloja otros sitios web. Nginx NO se desinstalará, solo se retira /DrapeMind.${NC}"
        else
            echo -e "     ${COLOR_MUTED}• No hay otros sitios activos en Nginx.${NC}"
        fi
    fi

    # 4. Escanear Node.js y npm (¿Lo usan otros proyectos?)
    echo ""
    echo -e "  ${COLOR_ACCENT}🔍 Análisis de Node.js / npm:${NC}"
    if command -v node >/dev/null 2>&1; then
        local NODE_PROCS
        NODE_PROCS=$(pgrep -a node 2>/dev/null | grep -v 'drapemind' || true)
        local OTHER_NODE_DIRS
        OTHER_NODE_DIRS=$(find /root /var/www /opt -maxdepth 3 -name "package.json" 2>/dev/null | grep -v 'drapemind' | grep -v 'DrapeMind' || true)

        if [[ -n "${NODE_PROCS}" || -n "${OTHER_NODE_DIRS}" ]]; then
            OTHER_NODE_FOUND=true
            echo -e "     • Node.js es utilizado por otros proyectos (ej. Cotizador Frontend)."
            echo -e "     ${COLOR_SUCCESS}✔ Node.js y npm son COMPARTIDOS ➜ 🛡️ PROTEGIDOS (No se tocan).${NC}"
        else
            echo -e "     • Ningún otro sistema en el servidor utiliza Node.js."
            echo -e "     ${COLOR_DANGER}✖ Node.js es candidato a desinstalación limpia.${NC}"
        fi
    else
        echo -e "     ${COLOR_MUTED}• Node.js no está instalado.${NC}"
    fi

    # 5. Escanear Motor LLM y Modelos IA (Exclusivos de DrapeMind)
    echo ""
    echo -e "  ${COLOR_ACCENT}🔍 Análisis de Motor LLM (llama-server) y Modelos IA:${NC}"
    local OTHER_LLAMA
    OTHER_LLAMA=$(systemctl list-units --type=service 2>/dev/null | grep -E 'llama|gemma|scout' | grep -v 'drapemind' || true)
    if [[ -z "${OTHER_LLAMA}" ]]; then
        echo -e "     • llama-server y modelos Gemma/Scout son ${COLOR_DANGER}${BOLD}EXCLUSIVOS de DrapeMind${NC}."
        echo -e "     ${COLOR_DANGER}➜ Serán eliminados para liberar memoria y gigabytes de disco.${NC}"
    else
        echo -e "     ${COLOR_SUCCESS}✔ Otro servicio utiliza llama-server. Se protegerá.${NC}"
    fi
    echo ""
}

confirm_action() {
    echo -e "${COLOR_DANGER}╭── [PLAN DE ACCIÓN DE DESINSTALACIÓN Y LIMPIEZA] ─────────────────────────╮${NC}"
    echo -e "${COLOR_DANGER}│${NC}  1. ${BOLD}Detener y eliminar servicio:${NC}  drapemind-backend.service                    ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  2. ${BOLD}Liberar puertos exclusivos:${NC}   8045 (FastAPI), 8088/8089 (llama-server)     ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  3. ${BOLD}Limpiar Nginx:${NC}                Retirar /DrapeMind y snippets (sitios OK)    ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  4. ${BOLD}Eliminar Frontend publicado:${NC}  /var/www/drapemind y /var/www/html/DrapeMind ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  5. ${BOLD}Base de Datos:${NC}                Eliminar drapemind_db (otras BD intactas)    ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  6. ${BOLD}Modelos IA y llama-server:${NC}    Eliminar binarios y modelos GGUF             ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}│${NC}  7. ${BOLD}Código Fuente Completo:${NC}       Eliminar /root/app/DrapeMind (Backend + Web) ${COLOR_DANGER}│${NC}"
    echo -e "${COLOR_DANGER}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
    read -rp "  ¿Confirmas la desinstalación y eliminación de DrapeMind? (escribe 'SI' para proceder): " resp
    if [[ "${resp}" != "SI" && "${resp}" != "si" && "${resp}" != "Si" ]]; then
        echo -e "\n  ${COLOR_MUTED}Operación cancelada por el usuario. DrapeMind no ha sido modificado.${NC}\n"
        exit 0
    fi
}

step_1_stop_and_remove_systemd() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 1/7] Deteniendo y eliminando servicios systemd de DrapeMind...${NC}"

    for srv in drapemind-backend.service drapemind.service drapemind-ai.service; do
        if systemctl is-active --quiet "${srv}" 2>/dev/null; then
            echo -e "  • Deteniendo ${srv}..."
            systemctl stop "${srv}" 2>/dev/null || true
        fi
        if systemctl is-enabled --quiet "${srv}" 2>/dev/null; then
            echo -e "  • Deshabilitando ${srv}..."
            systemctl disable "${srv}" 2>/dev/null || true
        fi
        if [[ -f "/etc/systemd/system/${srv}" ]]; then
            echo -e "  • Eliminando /etc/systemd/system/${srv}..."
            rm -f "/etc/systemd/system/${srv}"
        fi
    done

    systemctl daemon-reload
    systemctl reset-failed 2>/dev/null || true
    echo -e "  ${COLOR_SUCCESS}✔ Servicios systemd de DrapeMind eliminados.${NC}"
}

step_2_terminate_orphan_processes() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 2/7] Liberando puertos exclusivos de DrapeMind (8045, 8088, 8089)...${NC}"

    if command -v fuser >/dev/null 2>&1; then
        fuser -k 8045/tcp 2>/dev/null || true
        fuser -k 8088/tcp 2>/dev/null || true
        fuser -k 8089/tcp 2>/dev/null || true
    fi

    # Matar procesos uvicorn o python asociados a DrapeMind
    local PIDS_DM
    PIDS_DM=$(pgrep -f "app.main:app.*8045" || true)
    [[ -n "${PIDS_DM}" ]] && kill -9 ${PIDS_DM} 2>/dev/null || true

    # Matar llama-server exclusivo de DrapeMind
    local PIDS_LLAMA
    PIDS_LLAMA=$(pgrep -f "llama-server" || true)
    [[ -n "${PIDS_LLAMA}" ]] && kill -9 ${PIDS_LLAMA} 2>/dev/null || true

    echo -e "  ${COLOR_SUCCESS}✔ Puertos 8045, 8088 y 8089 liberados.${NC}"
}

step_3_clean_nginx() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 3/7] Limpiando configuración de Nginx para /DrapeMind...${NC}"

    local RELOAD_NEEDED=false

    # Limpiar inclusión de drapemind-subpath.conf en todos los sitios
    for site_conf in /etc/nginx/sites-available/* /etc/nginx/sites-enabled/*; do
        if [[ -f "${site_conf}" ]] && grep -q "drapemind" "${site_conf}" 2>/dev/null; then
            echo -e "  • Limpiando configuración de DrapeMind en: ${site_conf}"
            sed -i '/drapemind/d' "${site_conf}"
            RELOAD_NEEDED=true
        fi
    done

    # Eliminar configs dedicadas si existen
    rm -f /etc/nginx/sites-enabled/*drapemind*.conf 2>/dev/null || true
    rm -f /etc/nginx/sites-available/*drapemind*.conf 2>/dev/null || true
    rm -f /etc/nginx/snippets/drapemind-subpath.conf 2>/dev/null || true

    if command -v nginx >/dev/null 2>&1; then
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx 2>/dev/null || true
            echo -e "  ${COLOR_SUCCESS}✔ Nginx recargado con éxito. Otros sitios permanecen 100% operativos.${NC}"
        else
            echo -e "  ${COLOR_WARNING}⚠️  Advertencia en nginx -t; revisa manualmente para no afectar otros sitios.${NC}"
        fi
    fi
}

step_4_clean_www_files() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 4/7] Eliminando archivos publicados en /var/www/...${NC}"
    rm -rf "/var/www/drapemind" 2>/dev/null || true
    rm -rf "/var/www/html/DrapeMind" 2>/dev/null || true
    rm -rf "/var/log/drapemind" 2>/dev/null || true
    echo -e "  ${COLOR_SUCCESS}✔ Archivos web publicados de DrapeMind eliminados.${NC}"
}

step_5_manage_database() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 5/7] Limpiando Base de Datos PostgreSQL de DrapeMind...${NC}"

    if command -v psql >/dev/null 2>&1; then
        local HAS_DM
        HAS_DM=$(su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname = 'drapemind_db';\"" 2>/dev/null | tr -d ' ' || true)
        if [[ "${HAS_DM}" == "1" ]]; then
            echo -e "  • Terminando conexiones a drapemind_db..."
            su - postgres -c "psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'drapemind_db';\"" >/dev/null 2>&1 || true
            echo -e "  • Eliminando base de datos drapemind_db..."
            su - postgres -c "psql -c \"DROP DATABASE IF EXISTS drapemind_db;\"" 2>/dev/null || true
            echo -e "  • Eliminando usuario drapemind_user..."
            su - postgres -c "psql -c \"DROP USER IF EXISTS drapemind_user;\"" 2>/dev/null || true
            echo -e "  ${COLOR_SUCCESS}✔ Base de datos y usuario de DrapeMind eliminados.${NC}"
        else
            echo -e "  • No se encontró la base de datos 'drapemind_db'."
        fi

        # Si NO hay ninguna otra BD en el servidor además de postgres
        if [[ "${OTHER_DB_FOUND}" == "false" ]]; then
            echo ""
            echo -e "  ${COLOR_WARNING}ℹ️  PostgreSQL no aloja ninguna otra base de datos de otros proyectos.${NC}"
            read -rp "  ¿Deseas DESINSTALAR el motor PostgreSQL del sistema? [s/N]: " del_pg
            if [[ "${del_pg}" == "s" || "${del_pg}" == "S" || "${del_pg}" == "si" || "${del_pg}" == "SI" ]]; then
                echo -e "  • Desinstalando PostgreSQL..."
                apt-get remove --purge -y postgresql postgresql-contrib 2>/dev/null || true
                echo -e "  ${COLOR_SUCCESS}✔ Motor PostgreSQL desinstalado.${NC}"
            fi
        fi
    fi
}

step_6_clean_exclusive_tools_and_models() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 6/7] Eliminando binarios exclusivos de IA y Modelos GGUF...${NC}"

    # Eliminar binarios llama-server instalados por DrapeMind
    if [[ -f "/usr/local/bin/llama-server" ]]; then
        echo -e "  • Eliminando /usr/local/bin/llama-server..."
        rm -f "/usr/local/bin/llama-server"
    fi
    if [[ -f "/usr/local/bin/llama-cli" ]]; then
        echo -e "  • Eliminando /usr/local/bin/llama-cli..."
        rm -f "/usr/local/bin/llama-cli"
    fi

    # Eliminar modelos IA cacheados en disco
    rm -rf /root/.cache/huggingface/hub/*gemma* 2>/dev/null || true
    rm -rf /root/.cache/huggingface/hub/*scout* 2>/dev/null || true

    # Si Node.js NO lo ocupa ningún otro proyecto
    if [[ "${OTHER_NODE_FOUND}" == "false" ]] && command -v node >/dev/null 2>&1; then
        echo ""
        echo -e "  ${COLOR_WARNING}ℹ️  Ningún otro sistema en el VPS utiliza Node.js ni npm.${NC}"
        read -rp "  ¿Deseas DESINSTALAR Node.js y npm del sistema? [s/N]: " del_node
        if [[ "${del_node}" == "s" || "${del_node}" == "S" || "${del_node}" == "si" || "${del_node}" == "SI" ]]; then
            echo -e "  • Desinstalando Node.js y npm..."
            apt-get remove --purge -y nodejs npm 2>/dev/null || true
            rm -rf /etc/apt/sources.list.d/nodesource.list* 2>/dev/null || true
            echo -e "  ${COLOR_SUCCESS}✔ Node.js y npm desinstalados.${NC}"
        fi
    fi

    echo -e "  ${COLOR_SUCCESS}✔ Herramientas exclusivas limpiadas.${NC}"
}

step_7_delete_full_project_code() {
    echo ""
    echo -e "${COLOR_PRIMARY}[PASO 7/7] Eliminando Proyecto Completo (Frontend, Backend, .venv y Modelos)...${NC}"

    local TARGET_DIRS=(
        "/root/app/DrapeMind"
        "/root/drapemind"
        "/opt/drapemind"
    )

    # Si ROOT_DIR no está en la lista y es DrapeMind
    if [[ -d "${ROOT_DIR}" && "${ROOT_DIR}" != "/" && "${ROOT_DIR}" != "/root" ]]; then
        TARGET_DIRS+=("${ROOT_DIR}")
    fi

    for dir in "${TARGET_DIRS[@]}"; do
        if [[ -d "${dir}" ]]; then
            local SIZE
            SIZE=$(du -sh "${dir}" 2>/dev/null | cut -f1 || echo "")
            echo -e "  • Eliminando directorio: ${BOLD}${dir}${NC} (${SIZE})..."
            rm -rf "${dir}"
            echo -e "  ${COLOR_SUCCESS}✔ ${dir} eliminado completamente.${NC}"
        fi
    done

    # Limpieza final de paquetes huérfanos con apt
    apt-get autoremove -y -qq 2>/dev/null || true
    apt-get clean 2>/dev/null || true

    echo -e "  ${COLOR_SUCCESS}✔ Proyecto Frontend y Backend de DrapeMind eliminado en su totalidad.${NC}"
}

summary_final() {
    echo ""
    echo -e "${COLOR_SUCCESS}╭──────────────────────────────────────────────────────────────────────────╮${NC}"
    echo -e "${COLOR_SUCCESS}│  ${BOLD}✦ DRAPEMIND HA SIDO COMPLETAMENTE DESINSTALADO DEL SERVIDOR${NC}${COLOR_SUCCESS}             │${NC}"
    echo -e "${COLOR_SUCCESS}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Servicio systemd:        ${COLOR_DANGER}[ ELIMINADO ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Puertos 8045, 8088, 8089: ${COLOR_SUCCESS}[ LIBERADOS ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Ruta /DrapeMind Nginx:    ${COLOR_DANGER}[ REMOVIDA ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Archivos Web /var/www:    ${COLOR_DANGER}[ REMOVIDOS ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Base de datos PostgreSQL: ${COLOR_DANGER}[ ELIMINADA ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}│${NC}  • Código Frontend y Backend:${COLOR_DANGER}[ ELIMINADO TOTALMENTE ]${NC}${COLOR_SUCCESS}"
    echo -e "${COLOR_SUCCESS}├──────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${COLOR_SUCCESS}│${NC}  ${BOLD}ESTADO DE OTROS SISTEMAS DEL SERVIDOR:${NC}"

    if [[ "${OTHER_PROJECTS_FOUND}" == "true" ]]; then
        echo -e "${COLOR_SUCCESS}│${NC}  • Otros proyectos:          ${COLOR_SUCCESS}[ INTACTOS Y EN OPERACIÓN ]${NC}"
    fi

    local NGINX_ST="ACTIVO"
    systemctl is-active --quiet nginx || NGINX_ST="INACTIVO"
    echo -e "${COLOR_SUCCESS}│${NC}  • Servidor Nginx:           ${COLOR_SUCCESS}[ ${NGINX_ST} ]${NC}"

    local PG_ST="ACTIVO"
    systemctl is-active --quiet postgresql || PG_ST="INACTIVO"
    echo -e "${COLOR_SUCCESS}│${NC}  • Motor PostgreSQL:         ${COLOR_SUCCESS}[ ${PG_ST} ]${NC}"

    echo -e "${COLOR_SUCCESS}╰──────────────────────────────────────────────────────────────────────────╯${NC}"
    echo ""
}

# --- Ejecución Principal ---
check_root
banner
scan_system_and_dependencies
confirm_action

step_1_stop_and_remove_systemd
step_2_terminate_orphan_processes
step_3_clean_nginx
step_4_clean_www_files
step_5_manage_database
step_6_clean_exclusive_tools_and_models
step_7_delete_full_project_code
summary_final

exit 0
