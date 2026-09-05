#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - INSTALADOR INDEPENDIENTE DE BACKEND (FASTAPI + IA)
# Servidor IP: 157.173.102.129
# Puerto API: 8045 (evita colision con 8000)
# Puerto Gemma 4: 8088 (evita colision con 8080)
# Prefijo Proxy: /DrapeMind/api/
# =====================================================================

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SERVER_IP="157.173.102.129"
BACKEND_PORT=8045
AI_SERVER_PORT=8088
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info() { echo -e "${CYAN}${BOLD}[BACKEND INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}${BOLD}[BACKEND OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}${BOLD}[BACKEND AVISO]${NC} $1"; }
log_error() { echo -e "${RED}${BOLD}[BACKEND ERROR]${NC} $1" >&2; }

banner() {
    clear 2>/dev/null || true
    echo -e "${CYAN}${BOLD}"
    echo "======================================================================"
    echo "       DRAPEMIND ATELIER - INSTALADOR INDEPENDIENTE DE BACKEND"
    echo "======================================================================"
    echo -e "${NC}"
    echo -e " Directorio Backend: ${BOLD}${BACKEND_DIR}${NC}"
    echo -e " Puerto FastAPI:     ${BOLD}127.0.0.1:${BACKEND_PORT}${NC} (8000 queda libre)"
    echo -e " Puerto Gemma 4:     ${BOLD}127.0.0.1:${AI_SERVER_PORT}${NC} (8080 queda libre)"
    echo -e " Prefijo API:        ${BOLD}/DrapeMind/api/${NC}"
    echo "======================================================================"
    echo ""
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Se requieren privilegios de administrador (sudo)."
        echo "Ejecuta: sudo bash install.sh"
        exit 1
    fi
}

detect_python() {
    log_info "Detectando versión de Python..."
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_EXEC="python3.11"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_EXEC="python3"
    else
        log_warn "Python 3 no detectado. Se instalará automáticamente."
        PYTHON_EXEC="python3"
    fi
    log_success "Intérprete detectado: $($PYTHON_EXEC --version 2>/dev/null || echo 'Pendiente de instalación')"
}

install_system_packages() {
    log_info "Instalando paquetes base del sistema para el backend..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq

    apt-get install -y -qq \
        curl \
        wget \
        git \
        build-essential \
        libpq-dev \
        software-properties-common

    if ! command -v python3 >/dev/null 2>&1 || ! dpkg -s python3-venv >/dev/null 2>&1; then
        apt-get install -y -qq python3 python3-venv python3-pip python3-dev
    fi
    log_success "Paquetes del sistema instalados."
}

setup_postgresql() {
    log_info "Comprobando estado de PostgreSQL..."
    local PG_INSTALLED=false

    if command -v psql >/dev/null 2>&1 || systemctl is-active --quiet postgresql 2>/dev/null; then
        PG_INSTALLED=true
        log_success "PostgreSQL ya está instalado en el servidor (no se sobreescribirá)."
    else
        log_info "Instalando PostgreSQL..."
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

    log_info "Configurando usuario '${DB_USER}' y base de datos '${DB_NAME}'..."
    
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" | grep -q 1 || \
        su - postgres -c "psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

    su - postgres -c "psql -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\""

    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1 || \
        su - postgres -c "psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\""

    su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\""
    su - postgres -c "psql -d ${DB_NAME} -c \"GRANT ALL ON SCHEMA public TO ${DB_USER};\"" >/dev/null 2>&1 || true

    log_success "Base de datos y usuario de PostgreSQL configurados exitosamente."

    CONFIGURED_DB_USER="${DB_USER}"
    CONFIGURED_DB_PASS="${DB_PASS}"
    CONFIGURED_DB_NAME="${DB_NAME}"
}

setup_python_venv() {
    log_info "Configurando entorno virtual backend/.venv..."
    cd "${BACKEND_DIR}"

    if [[ ! -d ".venv" ]]; then
        ${PYTHON_EXEC} -m venv .venv
    fi

    log_info "Instalando requerimientos de Python en el entorno virtual..."
    "${BACKEND_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
    "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r requirements.txt

    # Preparar archivo .env
    if [[ ! -f ".env" ]]; then
        if [[ -f ".env.production.example" ]]; then
            cp .env.production.example .env
        elif [[ -f ".env.example" ]]; then
            cp .env.example .env
        fi
    fi

    local SECRET_KEY
    SECRET_KEY=$("${BACKEND_DIR}/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
    local WEBHOOK_SECRET
    WEBHOOK_SECRET=$("${BACKEND_DIR}/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))")

    sed -i "s|^ENVIRONMENT=.*|ENVIRONMENT=\"production\"|" .env
    sed -i "s|^DEBUG=.*|DEBUG=false|" .env
    sed -i "s|^ROOT_PATH=.*|ROOT_PATH=\"/DrapeMind\"|" .env
    sed -i "s|^PORT=.*|PORT=${BACKEND_PORT}|" .env
    sed -i "s|^AI_SERVER_PORT=.*|AI_SERVER_PORT=${AI_SERVER_PORT}|" .env
    sed -i "s|^AI_BASE_URL=.*|AI_BASE_URL=\"http://127.0.0.1:${AI_SERVER_PORT}/v1\"|" .env
    sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=\"${CONFIGURED_DB_USER:-drapemind_user}\"|" .env
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=\"${CONFIGURED_DB_PASS:-postgres}\"|" .env
    sed -i "s|^POSTGRES_DB=.*|POSTGRES_DB=\"${CONFIGURED_DB_NAME:-drapemind_db}\"|" .env
    sed -i "s|^AR_ASSET_BASE_URL=.*|AR_ASSET_BASE_URL=\"http://${SERVER_IP}/DrapeMind/static/ar\"|" .env

    if grep -q "change-me" .env || grep -q "CAMBIAR" .env; then
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=\"${SECRET_KEY}\"|" .env
        sed -i "s|^PAYMENT_WEBHOOK_SECRET=.*|PAYMENT_WEBHOOK_SECRET=\"${WEBHOOK_SECRET}\"|" .env
    fi

    if grep -q "^LLAMA_SERVER_PATH=" .env; then
        sed -i 's|^LLAMA_SERVER_PATH=.*|LLAMA_SERVER_PATH="/usr/local/bin/llama-server"|' .env
    else
        echo 'LLAMA_SERVER_PATH="/usr/local/bin/llama-server"' >> .env
    fi

    ensure_env_defaults

    log_info "Aplicando migraciones Alembic a PostgreSQL..."
    "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head

    log_info "Sembrando catálogo inicial de productos y usuarios..."
    "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data || log_warn "El sembrado finalizó o ya contenía datos."

    log_success "Entorno Python y base de datos configurados."
}

ensure_env_defaults() {
    local ENV_FILE="${BACKEND_DIR}/.env"
    if [[ ! -f "${ENV_FILE}" ]]; then
        return 0
    fi
    log_info "Saneando configuración de IA para CPU VPS..."
    if grep -q "^AI_GPU_LAYERS=" "${ENV_FILE}"; then
        sed -i 's|^AI_GPU_LAYERS=.*|AI_GPU_LAYERS="0"|' "${ENV_FILE}"
    else
        echo 'AI_GPU_LAYERS="0"' >> "${ENV_FILE}"
    fi
    if grep -q "^AI_CONTEXT_SIZE=" "${ENV_FILE}"; then
        sed -i 's|^AI_CONTEXT_SIZE=.*|AI_CONTEXT_SIZE=4096|' "${ENV_FILE}"
    else
        echo 'AI_CONTEXT_SIZE=4096' >> "${ENV_FILE}"
    fi
    if grep -q "^AI_PARALLEL_SLOTS=" "${ENV_FILE}"; then
        sed -i 's|^AI_PARALLEL_SLOTS=.*|AI_PARALLEL_SLOTS=1|' "${ENV_FILE}"
    else
        echo 'AI_PARALLEL_SLOTS=1' >> "${ENV_FILE}"
    fi
    if grep -q "^AI_SERVER_PORT=" "${ENV_FILE}"; then
        sed -i "s|^AI_SERVER_PORT=.*|AI_SERVER_PORT=${AI_SERVER_PORT}|" "${ENV_FILE}"
    else
        echo "AI_SERVER_PORT=${AI_SERVER_PORT}" >> "${ENV_FILE}"
    fi
    if grep -q "^AI_BASE_URL=" "${ENV_FILE}"; then
        sed -i "s|^AI_BASE_URL=.*|AI_BASE_URL=\"http://127.0.0.1:${AI_SERVER_PORT}/v1\"|" "${ENV_FILE}"
    else
        echo "AI_BASE_URL=\"http://127.0.0.1:${AI_SERVER_PORT}/v1\"" >> "${ENV_FILE}"
    fi

    mkdir -p "${BACKEND_DIR}/app/static/products"
    chmod -R 755 "${BACKEND_DIR}/app/static" 2>/dev/null || true
}

install_llama_server() {
    log_info "Verificando binario llama-server para Gemma 4..."
    if command -v llama-server >/dev/null 2>&1 || [[ -x "/usr/local/bin/llama-server" ]] || [[ -x "/opt/llama.cpp/build/bin/llama-server" ]]; then
        log_success "llama-server ya está presente en el servidor."
        return 0
    fi

    log_info "Instalando paquetes de compilación y descarga para llama-server..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl wget unzip git build-essential cmake

    local ARCH
    ARCH=$(uname -m)
    local INSTALLED=false

    if [[ "${ARCH}" == "x86_64" ]]; then
        log_info "Intentando descargar release precompilado oficial de llama.cpp (Ubuntu x64)..."
        local TMP_ZIP="/tmp/llama-bin.zip"
        local TMP_DIR="/tmp/llama-extract"
        rm -rf "${TMP_ZIP}" "${TMP_DIR}"
        mkdir -p "${TMP_DIR}"

        local DOWNLOAD_URL
        DOWNLOAD_URL=$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest 2>/dev/null | grep "browser_download_url.*bin-ubuntu-x64.zip" | head -n 1 | cut -d '"' -f 4 || true)
        if [[ -z "${DOWNLOAD_URL}" ]]; then
            DOWNLOAD_URL="https://github.com/ggml-org/llama.cpp/releases/download/b4610/llama-b4610-bin-ubuntu-x64.zip"
        fi

        log_info "Descargando: ${DOWNLOAD_URL}..."
        if curl -fsSL "${DOWNLOAD_URL}" -o "${TMP_ZIP}" 2>/dev/null && unzip -q "${TMP_ZIP}" -d "${TMP_DIR}" 2>/dev/null; then
            local SERVER_BIN
            SERVER_BIN=$(find "${TMP_DIR}" -type f -name "llama-server" | head -n 1)
            if [[ -n "${SERVER_BIN}" && -f "${SERVER_BIN}" ]]; then
                cp "${SERVER_BIN}" /usr/local/bin/llama-server
                chmod +x /usr/local/bin/llama-server
                find "${TMP_DIR}" -type f -name "*.so*" -exec cp {} /usr/local/lib/ \; 2>/dev/null || true
                ldconfig 2>/dev/null || true
                INSTALLED=true
                log_success "llama-server instalado exitosamente desde release precompilado."
            fi
        fi
        rm -rf "${TMP_ZIP}" "${TMP_DIR}"
    fi

    if [[ "${INSTALLED}" != true ]]; then
        log_info "Compilando llama-server desde código fuente con CMake (esto puede tomar unos minutos)..."
        mkdir -p /opt
        rm -rf /opt/llama.cpp
        git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
        cmake -B /opt/llama.cpp/build /opt/llama.cpp -DGGML_OPENMP=ON
        cmake --build /opt/llama.cpp/build --config Release -j$(nproc) --target llama-server
        cp /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
        chmod +x /usr/local/bin/llama-server
        log_success "llama-server compilado e instalado en /usr/local/bin/llama-server."
    fi

    if [[ -f "${BACKEND_DIR}/.env" ]]; then
        if grep -q "^LLAMA_SERVER_PATH=" "${BACKEND_DIR}/.env"; then
            sed -i 's|^LLAMA_SERVER_PATH=.*|LLAMA_SERVER_PATH="/usr/local/bin/llama-server"|' "${BACKEND_DIR}/.env"
        else
            echo 'LLAMA_SERVER_PATH="/usr/local/bin/llama-server"' >> "${BACKEND_DIR}/.env"
        fi
    fi

    if command -v llama-server >/dev/null 2>&1 || [[ -x "/usr/local/bin/llama-server" ]]; then
        log_success "Binario llama-server listo en /usr/local/bin/llama-server."
    fi
}

download_ai_models() {
    install_llama_server

    log_info "Comprobando y descargando modelos de Hugging Face (Gemma 4)..."
    cd "${BACKEND_DIR}"

    if [[ -f "${BACKEND_DIR}/scripts/ai/download_models.py" ]]; then
        "${BACKEND_DIR}/.venv/bin/python" "${BACKEND_DIR}/scripts/ai/download_models.py" -y
    fi
}

setup_systemd() {
    log_info "Configurando servicio systemd (drapemind-backend.service)..."

    local SERVICE_USER="drapemind"
    local SERVICE_GROUP="drapemind"

    # Si el proyecto se encuentra dentro de /root, el servicio debe ejecutarse como root
    # porque los usuarios estandar no tienen permisos para acceder o atravesar /root
    if [[ "${BACKEND_DIR}" == /root* ]]; then
        log_warn "El proyecto está dentro de /root. Se ejecutará con usuario root para evitar errores de permisos (CHDIR)."
        SERVICE_USER="root"
        SERVICE_GROUP="root"
    else
        if ! id -u drapemind >/dev/null 2>&1; then
            useradd -r -s /bin/false -d "${BACKEND_DIR}" drapemind || true
        fi
        chown -R drapemind:drapemind "${BACKEND_DIR}/logs" "${BACKEND_DIR}/ai_models" 2>/dev/null || true
    fi

    mkdir -p "${BACKEND_DIR}/logs" "${BACKEND_DIR}/ai_models"
    chmod -R 775 "${BACKEND_DIR}/logs" 2>/dev/null || true

    local SERVICE_DEST="/etc/systemd/system/drapemind-backend.service"

    cat <<EOF > "${SERVICE_DEST}"
[Unit]
Description=DrapeMind FastAPI Backend and Managed Gemma AI Runtime
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${BACKEND_DIR}
EnvironmentFile=${BACKEND_DIR}/.env
Environment="PATH=/usr/local/bin:/usr/bin:/bin:${BACKEND_DIR}/.venv/bin"
Environment="LLAMA_SERVER_PATH=/usr/local/bin/llama-server"
ExecStart=${BACKEND_DIR}/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT} --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable drapemind-backend.service
    systemctl restart drapemind-backend.service

    sleep 3
    if systemctl is-active --quiet drapemind-backend.service; then
        log_success "Servicio drapemind-backend activo en puerto ${BACKEND_PORT}."
    else
        log_error "El servicio no pudo iniciar. Mostrando últimos logs:"
        journalctl -u drapemind-backend -n 25 --no-pager || true
    fi
}

update_backend_code() {
    log_info "Actualizando backend con los cambios más recientes..."
    cd "${BACKEND_DIR}"
    git pull || log_warn "Git pull no se pudo completar automáticamente (revisa si hay cambios sin commitear)."

    log_info "Instalando paquetes actualizados..."
    "${BACKEND_DIR}/.venv/bin/pip" install --quiet -r requirements.txt || true

    log_info "Aplicando migraciones de base de datos..."
    "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head || true

    ensure_env_defaults
    install_llama_server

    log_info "Reiniciando servicio backend..."
    setup_systemd
    verify_backend
}

view_logs() {
    echo "Mostrando logs en tiempo real (Presiona Ctrl+C para salir)..."
    sleep 1
    journalctl -u drapemind-backend -f -n 40
}

verify_backend() {
    echo ""
    log_info "Verificando salud del backend..."
    sleep 2

    local HEALTH
    HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ready" || echo '{"status":"error"}')
    local AI_HEALTH
    AI_HEALTH=$(curl -s "http://127.0.0.1:${BACKEND_PORT}/health/ai" || echo '{"healthy":false}')
    local AI_DESC="En reposo (inicia automáticamente al consultar a Altair)"
    if echo "${AI_HEALTH}" | grep -q '"healthy":true'; then
        AI_DESC="${GREEN}ACTIVO Y RESPONDIENDO${NC}"
    fi

    echo ""
    echo "======================================================================"
    echo -e " ${GREEN}${BOLD}✓ BACKEND DE DRAPEMIND INSTALADO Y CORRIENDO${NC}"
    echo "======================================================================"
    echo -e " • Escucha interna:     ${CYAN}${BOLD}http://127.0.0.1:${BACKEND_PORT}${NC}"
    echo -e " • Ruta con Nginx:      ${CYAN}${BOLD}http://${SERVER_IP}/DrapeMind/api/v1/catalog/products${NC}"
    echo -e " • Swagger Docs:        ${CYAN}${BOLD}http://${SERVER_IP}/DrapeMind/docs${NC}"
    echo -e " • Puerto FastAPI:      ${BOLD}${BACKEND_PORT}${NC} (8000 libre)"
    echo -e " • Puerto Gemma 4:      ${BOLD}${AI_SERVER_PORT}${NC} (8080 libre)"
    echo -e " • Estado Gemma 4:      ${AI_DESC}"
    echo -e " • PostgreSQL BD:       ${BOLD}${CONFIGURED_DB_NAME:-drapemind_db}${NC}"
    echo -e " • PostgreSQL Usuario:  ${BOLD}${CONFIGURED_DB_USER:-drapemind_user}${NC}"
    echo -e " • Ver servicio:        systemctl status drapemind-backend"
    echo "======================================================================"
    echo ""
}

show_help() {
    echo "Uso: sudo bash install.sh [OPCION]"
    echo ""
    echo "Opciones disponibles:"
    echo "  --all         Instalación completa (Paquetes, PostgreSQL, venv, modelos y servicio)"
    echo "  --db          Solo configura PostgreSQL, migraciones y catálogo"
    echo "  --models      Solo descarga modelos Gemma 4 de Hugging Face"
    echo "  --service     Solo actualiza y reinicia el servicio systemd"
    echo "  --check       Verifica estado del servicio y PostgreSQL"
    echo "  --help        Muestra esta ayuda"
    echo ""
}

# --- Ejecución ---
check_root
detect_python

case "${1:-}" in
    --all)
        banner
        install_system_packages
        setup_postgresql
        setup_python_venv
        download_ai_models
        setup_systemd
        verify_backend
        ;;
    --db)
        setup_postgresql
        cd "${BACKEND_DIR}"
        "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head
        "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data
        ;;
    --models)
        download_ai_models
        ;;
    --llama)
        install_llama_server
        ;;
    --service)
        setup_systemd
        ;;
    --update)
        update_backend_code
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
        echo "  3) Actualizar Backend con cambios recientes de Git (Pull + Restart)"
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
                install_system_packages
                setup_postgresql
                setup_python_venv
                install_llama_server
                download_ai_models
                setup_systemd
                verify_backend
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
                cd "${BACKEND_DIR}"
                "${BACKEND_DIR}/.venv/bin/python" -m alembic upgrade head
                "${BACKEND_DIR}/.venv/bin/python" -m scripts.db.seed_data
                ;;
            6)
                install_llama_server
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
