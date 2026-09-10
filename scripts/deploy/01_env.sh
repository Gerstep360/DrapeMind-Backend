#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 01: SINCRONIZACION Y PROTECCION DEL ENTORNO (.ENV)
# =====================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"

set_or_update_var() {
    local key="$1"
    local val="$2"
    local file="${3:-${BACKEND_DIR}/.env}"

    if grep -q "^${key}=" "${file}"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "${file}"
    else
        echo "${key}=${val}" >> "${file}"
    fi
}

set_default_var() {
    local key="$1" val="$2" file="$3"
    if ! grep -q "^${key}=" "${file}"; then
        set_or_update_var "${key}" "${val}" "${file}"
    fi
}

sync_env_production() {
    local ENV_FILE="${BACKEND_DIR}/.env"
    local PROD_REF_FILE="${BACKEND_DIR}/.env_produccion"
    [[ ! -f "${PROD_REF_FILE}" && -f "${BACKEND_DIR}/../.env_produccion" ]] && PROD_REF_FILE="${BACKEND_DIR}/../.env_produccion"

    if [[ "${INSTALL_FLOW:-false}" != "true" ]]; then
        echo ""
        echo -e "${COLOR_PRIMARY}╭── [CONFIGURACIÓN DE ENTORNO] ─────────────────────────────────────────────╮${NC}"
        echo -e "${COLOR_PRIMARY}│${NC}  ${BOLD}${ICON_SHIELD} Sincronización y Protección de Variables de Producción (.env)${NC}"
        echo -e "${COLOR_PRIMARY}╰───────────────────────────────────────────────────────────────────────────╯${NC}"
    fi

    # Paso 1: Si ya existe un .env en producción, crear copia de seguridad inmediata
    if [[ -f "${ENV_FILE}" ]]; then
        local BACKUP_FILE="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
        cp "${ENV_FILE}" "${BACKUP_FILE}"
        log_success "Copia de seguridad de seguridad creada en: ${DIM}${BACKUP_FILE}${NC}"
    else
        # Si no existe .env, intentar restaurar desde el estado real .env_produccion
        if [[ -f "${PROD_REF_FILE}" ]]; then
            cp "${PROD_REF_FILE}" "${ENV_FILE}"
            log_success "Archivo .env inicializado desde la referencia de producción (.env_produccion)."
        elif [[ -f "${BACKEND_DIR}/.env.production.example" ]]; then
            cp "${BACKEND_DIR}/.env.production.example" "${ENV_FILE}"
            log_info "Archivo .env inicializado desde .env.production.example."
        elif [[ -f "${BACKEND_DIR}/.env.example" ]]; then
            cp "${BACKEND_DIR}/.env.example" "${ENV_FILE}"
            log_info "Archivo .env inicializado desde .env.example."
        else
            touch "${ENV_FILE}"
        fi
    fi

    # Paso 2: Preservar credenciales existentes (NUNCA sobreescribir secretos reales)
    local EXISTING_SECRET
    EXISTING_SECRET=$(grep -E '^SECRET_KEY=' "${ENV_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    local EXISTING_PG_PASS
    EXISTING_PG_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${ENV_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    local EXISTING_WEBHOOK
    EXISTING_WEBHOOK=$(grep -E '^PAYMENT_WEBHOOK_SECRET=' "${ENV_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)

    # Si faltaban en .env pero existen en .env_produccion, recuperarlos
    if [[ -z "${EXISTING_SECRET}" || "${EXISTING_SECRET}" == *"CAMBIAR"* ]] && [[ -f "${PROD_REF_FILE}" ]]; then
        EXISTING_SECRET=$(grep -E '^SECRET_KEY=' "${PROD_REF_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    fi
    if [[ -z "${EXISTING_PG_PASS}" || "${EXISTING_PG_PASS}" == *"CAMBIAR"* ]] && [[ -f "${PROD_REF_FILE}" ]]; then
        EXISTING_PG_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${PROD_REF_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    fi
    if [[ -z "${EXISTING_WEBHOOK}" || "${EXISTING_WEBHOOK}" == *"CAMBIAR"* ]] && [[ -f "${PROD_REF_FILE}" ]]; then
        EXISTING_WEBHOOK=$(grep -E '^PAYMENT_WEBHOOK_SECRET=' "${PROD_REF_FILE}" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    fi

    # Generar secretos criptográficos seguros SOLO si nunca se han configurado
    local PYTHON_BIN="python3"
    [[ -x "${BACKEND_DIR}/.venv/bin/python" ]] && PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"

    if [[ -z "${EXISTING_SECRET}" || "${EXISTING_SECRET}" == *"CAMBIAR"* || "${EXISTING_SECRET}" == *"change-me"* ]]; then
        EXISTING_SECRET=$("${PYTHON_BIN}" -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -hex 32)
        log_warn "Generando nueva SECRET_KEY criptográfica segura..."
    fi

    if [[ -z "${EXISTING_WEBHOOK}" || "${EXISTING_WEBHOOK}" == *"CAMBIAR"* || "${EXISTING_WEBHOOK}" == *"change-me"* ]]; then
        EXISTING_WEBHOOK=$("${PYTHON_BIN}" -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -hex 24)
        log_warn "Generando nuevo PAYMENT_WEBHOOK_SECRET..."
    fi

    set_or_update_var "SECRET_KEY" "\"${EXISTING_SECRET}\"" "${ENV_FILE}"
    set_or_update_var "PAYMENT_WEBHOOK_SECRET" "\"${EXISTING_WEBHOOK}\"" "${ENV_FILE}"

    # Paso 3: Configuración general y de red de producción
    set_or_update_var "APP_NAME" "\"DrapeMind API\"" "${ENV_FILE}"
    set_or_update_var "APP_VERSION" "\"1.0.0\"" "${ENV_FILE}"
    set_or_update_var "ENVIRONMENT" "\"production\"" "${ENV_FILE}"
    set_or_update_var "DEBUG" "false" "${ENV_FILE}"
    set_or_update_var "ROOT_PATH" "\"/DrapeMind\"" "${ENV_FILE}"
    set_or_update_var "API_V1_PREFIX" "\"/api/v1\"" "${ENV_FILE}"
    set_or_update_var "DOCS_ENABLED" "true" "${ENV_FILE}"
    set_or_update_var "PORT" "${BACKEND_PORT}" "${ENV_FILE}"

    set_or_update_var "JWT_ALGORITHM" "\"HS256\"" "${ENV_FILE}"
    set_or_update_var "ACCESS_TOKEN_EXPIRE_MINUTES" "60" "${ENV_FILE}"

    # Base de datos PostgreSQL
    set_or_update_var "POSTGRES_HOST" "\"localhost\"" "${ENV_FILE}"
    set_or_update_var "POSTGRES_PORT" "5432" "${ENV_FILE}"
    set_or_update_var "POSTGRES_USER" "\"${CONFIGURED_DB_USER:-drapemind_user}\"" "${ENV_FILE}"
    if [[ -n "${CONFIGURED_DB_PASS}" ]]; then
        set_or_update_var "POSTGRES_PASSWORD" "\"${CONFIGURED_DB_PASS}\"" "${ENV_FILE}"
    elif [[ -n "${EXISTING_PG_PASS}" && "${EXISTING_PG_PASS}" != *"CAMBIAR"* ]]; then
        set_or_update_var "POSTGRES_PASSWORD" "\"${EXISTING_PG_PASS}\"" "${ENV_FILE}"
    fi
    set_or_update_var "POSTGRES_DB" "\"${CONFIGURED_DB_NAME:-drapemind_db}\"" "${ENV_FILE}"
    set_or_update_var "DB_POOL_SIZE" "10" "${ENV_FILE}"
    set_or_update_var "DB_MAX_OVERFLOW" "20" "${ENV_FILE}"
    set_or_update_var "DB_ECHO" "false" "${ENV_FILE}"

    # CORS seguro para el frontend en producción y local
    set_or_update_var "CORS_ORIGINS" "'[\"http://${SERVER_IP}\",\"http://${SERVER_IP}:80\",\"http://localhost\",\"http://127.0.0.1\"]'" "${ENV_FILE}"
    set_or_update_var "CORS_ORIGIN_REGEX" "" "${ENV_FILE}"
    set_or_update_var "CORS_ALLOW_CREDENTIALS" "true" "${ENV_FILE}"

    # Paso 4: Parámetros del motor Gemma 4 y agente Altair
    set_default_var "AI_BASE_URL" "\"http://127.0.0.1:${AI_SERVER_PORT}/v1\"" "${ENV_FILE}"
    set_default_var "AI_API_KEY" "\"local-no-key\"" "${ENV_FILE}"
    set_default_var "AI_MODEL" "\"google/gemma-4-E2B-it-qat-q4_0-gguf\"" "${ENV_FILE}"
    set_default_var "AI_MANAGED_SERVER" "true" "${ENV_FILE}"
    set_default_var "AI_SERVER_HOST" "\"127.0.0.1\"" "${ENV_FILE}"
    set_default_var "AI_SERVER_PORT" "${AI_SERVER_PORT}" "${ENV_FILE}"
    set_default_var "AI_MODEL_PATH" "\"ai_models/gemma-4-e2b/gemma-4-E2B_q4_0-it.gguf\"" "${ENV_FILE}"
    set_default_var "AI_MMPROJ_PATH" "\"ai_models/gemma-4-e2b/gemma-4-E2B-it-mmproj.gguf\"" "${ENV_FILE}"
    set_default_var "LLAMA_SERVER_PATH" "\"/usr/local/bin/llama-server\"" "${ENV_FILE}"
    set_default_var "AI_IDLE_TIMEOUT_SECONDS" "600" "${ENV_FILE}"
    set_default_var "AI_STARTUP_TIMEOUT_SECONDS" "240" "${ENV_FILE}"
    set_default_var "AI_CONTEXT_SIZE" "4096" "${ENV_FILE}"
    set_default_var "AI_PARALLEL_SLOTS" "1" "${ENV_FILE}"
    set_default_var "AI_THREADS" "3" "${ENV_FILE}"
    set_default_var "AI_GPU_LAYERS" "\"0\"" "${ENV_FILE}"
    set_default_var "AI_SERVER_EXTRA_ARGS" "\"\"" "${ENV_FILE}"

    # =====================================================================
    # NUEVAS VARIABLES DE IA Y STREAMING ALTAIR SOLICITADAS
    # =====================================================================
    set_default_var "AI_MAX_AGENT_STEPS" "4" "${ENV_FILE}"
    set_default_var "AI_TURN_TIMEOUT_SECONDS" "150" "${ENV_FILE}"
    set_default_var "AI_TIMEOUT_SECONDS" "90" "${ENV_FILE}"
    set_default_var "AI_MAX_TOKENS" "1024" "${ENV_FILE}"
    set_default_var "AI_AGENT_MAX_TOKENS" "768" "${ENV_FILE}"
    set_default_var "AI_AGENT_DEADLINE_SECONDS" "180" "${ENV_FILE}"
    set_default_var "AI_REASONING_MODE" "auto" "${ENV_FILE}"
    set_default_var "AI_REASONING_BUDGET" "64" "${ENV_FILE}"
    set_default_var "AI_FIRST_TOKEN_TIMEOUT_SECONDS" "120" "${ENV_FILE}"
    set_default_var "AI_TEMPERATURE" "0.35" "${ENV_FILE}"

    local SCOUT_FILE="${BACKEND_DIR}/ai_models/qwen3-0.6B/Qwen3-0.6B-Q8_0.gguf"
    if [[ -f "${SCOUT_FILE}" ]]; then
        set_default_var "SCOUT_ENABLED" "true" "${ENV_FILE}"
    else
        set_default_var "SCOUT_ENABLED" "false" "${ENV_FILE}"
    fi
    set_default_var "SCOUT_MODEL" "\"ai_models/qwen3-0.6B/Qwen3-0.6B-Q8_0.gguf\"" "${ENV_FILE}"
    set_default_var "SCOUT_MODEL_PATH" "\"ai_models/qwen3-0.6B/Qwen3-0.6B-Q8_0.gguf\"" "${ENV_FILE}"
    set_default_var "SCOUT_BASE_URL" "\"http://127.0.0.1:${SCOUT_SERVER_PORT:-8089}/v1\"" "${ENV_FILE}"
    set_default_var "SCOUT_API_KEY" "\"local-no-key\"" "${ENV_FILE}"
    set_default_var "SCOUT_MANAGED_SERVER" "true" "${ENV_FILE}"
    set_default_var "SCOUT_SERVER_PORT" "${SCOUT_SERVER_PORT:-8089}" "${ENV_FILE}"
    set_default_var "SCOUT_THREADS" "1" "${ENV_FILE}"
    set_default_var "SCOUT_CONTEXT_SIZE" "4096" "${ENV_FILE}"
    set_default_var "SCOUT_MAX_TOKENS" "256" "${ENV_FILE}"
    set_default_var "SCOUT_DIRECT_CONFIDENCE" "0.85" "${ENV_FILE}"
    set_default_var "AI_RESPONSE_SHORT_TOKENS" "128" "${ENV_FILE}"
    set_default_var "AI_RESPONSE_NORMAL_TOKENS" "256" "${ENV_FILE}"
    set_default_var "AI_RESPONSE_DEEP_TOKENS" "512" "${ENV_FILE}"
    set_default_var "SCOUT_MAX_STEPS" "6" "${ENV_FILE}"
    set_default_var "SCOUT_TIMEOUT_SECONDS" "60" "${ENV_FILE}"
    set_default_var "SCOUT_TURN_TIMEOUT_SECONDS" "240" "${ENV_FILE}"
    set_default_var "SCOUT_IDLE_TIMEOUT_SECONDS" "300" "${ENV_FILE}"
    set_default_var "AI_CONTEXT_TOKEN_METRICS" "false" "${ENV_FILE}"

    # Dominio y Pagos
    set_or_update_var "RESERVATION_TTL_MINUTES" "2880" "${ENV_FILE}"
    set_or_update_var "PAYMENT_PROVIDER" "\"mock\"" "${ENV_FILE}"
    set_or_update_var "AR_ASSET_BASE_URL" "\"http://${SERVER_IP}/DrapeMind/static/ar\"" "${ENV_FILE}"

    # Directorios estáticos necesarios
    mkdir -p "${BACKEND_DIR}/app/static/products" "${BACKEND_DIR}/app/static/ar"
    chmod -R 755 "${BACKEND_DIR}/app/static" 2>/dev/null || true

    # Mantener sincronizado el archivo dorado .env_produccion como respaldo maestro
    if [[ -f "${PROD_REF_FILE}" ]]; then
        cp "${ENV_FILE}" "${PROD_REF_FILE}"
    fi
    cp "${ENV_FILE}" "${BACKEND_DIR}/.env_produccion" 2>/dev/null || true

    # Tarjeta de estado en terminal
    echo -e "${COLOR_SUCCESS}  ┌── Resumen de Configuración (.env) ──────────────────────────────┐${NC}"
    echo -e "${COLOR_SUCCESS}  │${NC} • Estado:           ${COLOR_SUCCESS}${BOLD}Protegido y Sincronizado${NC}"
    echo -e "${COLOR_SUCCESS}  │${NC} • Base de Datos:    ${BOLD}PostgreSQL (${CONFIGURED_DB_USER:-drapemind_user}@localhost:5432)${NC}"
    echo -e "${COLOR_SUCCESS}  │${NC} • Streaming IA:     ${BOLD}Configuración existente preservada en .env${NC}"
    echo -e "${COLOR_SUCCESS}  │${NC} • Razonamiento:     ${BOLD}Se conserva el valor configurado${NC}"
    echo -e "${COLOR_SUCCESS}  │${NC} • Arquitectura IA:  ${BOLD}Ver SCOUT_ENABLED en .env y AI_ROUTING en logs${NC}"
    log_info "Scout no se activa automáticamente: si estaba false, configure modelo y SCOUT_ENABLED=true antes de reiniciar."
    echo -e "${COLOR_SUCCESS}  │${NC} • Secretos:         ${COLOR_SUCCESS}${BOLD}Protegidos sin sobreescritura destructiva${NC}"
    echo -e "${COLOR_SUCCESS}  └───────────────────────────────────────────────────────────────────┘${NC}"
    log_success "Archivo de variables de entorno (.env) actualizado satisfactoriamente."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    sync_env_production
fi
