#!/usr/bin/env bash
# =====================================================================
# DRAPEMIND - MODULO 01: SINCRONIZACION Y ACTUALIZACION DEL .ENV
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

sync_env_production() {
    local ENV_FILE="${BACKEND_DIR}/.env"
    log_info "Sincronizando archivo de configuración (.env) para producción..."

    # Si no existe .env, inicializar desde plantilla
    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${BACKEND_DIR}/.env.production.example" ]]; then
            cp "${BACKEND_DIR}/.env.production.example" "${ENV_FILE}"
            log_info "Archivo .env inicializado desde .env.production.example."
        elif [[ -f "${BACKEND_DIR}/.env.example" ]]; then
            cp "${BACKEND_DIR}/.env.example" "${ENV_FILE}"
            log_info "Archivo .env inicializado desde .env.example."
        else
            touch "${ENV_FILE}"
        fi
    fi

    # Configuración general y de red
    set_or_update_var "ENVIRONMENT" "\"production\"" "${ENV_FILE}"
    set_or_update_var "DEBUG" "false" "${ENV_FILE}"
    set_or_update_var "ROOT_PATH" "\"/DrapeMind\"" "${ENV_FILE}"
    set_or_update_var "PORT" "${BACKEND_PORT}" "${ENV_FILE}"
    set_or_update_var "AI_SERVER_PORT" "${AI_SERVER_PORT}" "${ENV_FILE}"
    set_or_update_var "AI_BASE_URL" "\"http://127.0.0.1:${AI_SERVER_PORT}/v1\"" "${ENV_FILE}"
    set_or_update_var "AR_ASSET_BASE_URL" "\"http://${SERVER_IP}/DrapeMind/static/ar\"" "${ENV_FILE}"

    # Generar secretos criptográficos seguros si son valores por defecto
    if grep -q "change-me" "${ENV_FILE}" || grep -q "CAMBIAR" "${ENV_FILE}"; then
        local PYTHON_BIN="python3"
        [[ -x "${BACKEND_DIR}/.venv/bin/python" ]] && PYTHON_BIN="${BACKEND_DIR}/.venv/bin/python"
        
        local NEW_SECRET
        NEW_SECRET=$("${PYTHON_BIN}" -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -hex 32)
        local NEW_WEBHOOK
        NEW_WEBHOOK=$("${PYTHON_BIN}" -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -hex 24)

        if grep -E '^SECRET_KEY=.*(change-me|CAMBIAR)' "${ENV_FILE}"; then
            sed -i "s|^SECRET_KEY=.*|SECRET_KEY=\"${NEW_SECRET}\"|" "${ENV_FILE}"
            log_success "Nueva SECRET_KEY criptográfica generada y guardada."
        fi
        if grep -E '^PAYMENT_WEBHOOK_SECRET=.*(change-me|CAMBIAR)' "${ENV_FILE}"; then
            sed -i "s|^PAYMENT_WEBHOOK_SECRET=.*|PAYMENT_WEBHOOK_SECRET=\"${NEW_WEBHOOK}\"|" "${ENV_FILE}"
            log_success "Nueva PAYMENT_WEBHOOK_SECRET generada y guardada."
        fi
    fi

    # Rutas del motor de inferencia local
    set_or_update_var "LLAMA_SERVER_PATH" "\"/usr/local/bin/llama-server\"" "${ENV_FILE}"

    # =====================================================================
    # PARAMETROS DE IA ALTAIR (OPTIMIZADOS PARA CPU VPS Y STREAMING)
    # =====================================================================
    log_info "Actualizando parámetros de inferencia y streaming de Altair..."
    set_or_update_var "AI_CONTEXT_SIZE" "4096" "${ENV_FILE}"
    set_or_update_var "AI_PARALLEL_SLOTS" "1" "${ENV_FILE}"
    set_or_update_var "AI_THREADS" "3" "${ENV_FILE}"
    set_or_update_var "AI_GPU_LAYERS" "\"0\"" "${ENV_FILE}"
    set_or_update_var "AI_MAX_AGENT_STEPS" "4" "${ENV_FILE}"
    set_or_update_var "AI_TIMEOUT_SECONDS" "90" "${ENV_FILE}"
    set_or_update_var "AI_MAX_TOKENS" "1024" "${ENV_FILE}"
    set_or_update_var "AI_AGENT_MAX_TOKENS" "768" "${ENV_FILE}"
    set_or_update_var "AI_AGENT_DEADLINE_SECONDS" "180" "${ENV_FILE}"
    set_or_update_var "AI_REASONING_MODE" "auto" "${ENV_FILE}"
    set_or_update_var "AI_REASONING_BUDGET" "64" "${ENV_FILE}"
    set_or_update_var "AI_FIRST_TOKEN_TIMEOUT_SECONDS" "120" "${ENV_FILE}"
    set_or_update_var "AI_TEMPERATURE" "0.35" "${ENV_FILE}"

    # Actualizar credenciales de PostgreSQL si fueron provistas por el instalador
    if [[ -n "${CONFIGURED_DB_USER}" ]]; then
        set_or_update_var "POSTGRES_USER" "\"${CONFIGURED_DB_USER}\"" "${ENV_FILE}"
    fi
    if [[ -n "${CONFIGURED_DB_PASS}" ]]; then
        set_or_update_var "POSTGRES_PASSWORD" "\"${CONFIGURED_DB_PASS}\"" "${ENV_FILE}"
    fi
    if [[ -n "${CONFIGURED_DB_NAME}" ]]; then
        set_or_update_var "POSTGRES_DB" "\"${CONFIGURED_DB_NAME}\"" "${ENV_FILE}"
    fi

    # Carpetas estáticas requeridas
    mkdir -p "${BACKEND_DIR}/app/static/products"
    chmod -R 755 "${BACKEND_DIR}/app/static" 2>/dev/null || true

    log_success "Archivo .env sincronizado exitosamente con los parámetros de producción."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    sync_env_production
fi
