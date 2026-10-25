#!/usr/bin/env bash
# Gestor nativo único. No restablece Git ni sustituye sitios de otras aplicaciones.
set -euo pipefail
umask 077
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$DEPLOY_DIR/../.." && pwd)"
DRAPE_APP_DIR="${DRAPEMIND_APP_DIR:-$(dirname "$BACKEND_DIR")}"
CONFIG_TOOL="$DEPLOY_DIR/platform_config.py"
source "$DEPLOY_DIR/platform_ui.sh"
action="${1:---menu}"; shift || true
if [[ "$action" == --help || "$action" == -h ]]; then
    printf '%s\n' 'DrapeMind · gestor VPS Ubuntu/Debian' \
      '--all          Instalar dependencias, DB, migraciones, web, HTTPS y servicio' \
      '--update       Respaldo, avance Git seguro, dependencias, migraciones y publicación' \
      '--backend      Preparar/actualizar backend del checkout actual' \
      '--frontend     Compilar y publicar el frontend del checkout actual' \
      '--env          Configurar NVIDIA/Stripe sin mostrar claves' \
      '--import-env   Importar las copias privadas enviadas por SFTP' \
      '--migrate      Respaldo + migraciones + permisos runtime + reinicio' \
      '--seed [args]  Seeder por empresa, sin reset global' \
      '--backup       Respaldo PostgreSQL' \
      '--nginx        Integrar solo /DrapeMind en el servidor existente' \
      '--tls          Reutilizar HTTPS o emitir y renovar certificado' \
      '--restart      Reiniciar backend' '--check        Salud real de backend, web y HTTPS' \
      '--logs         Seguir journal del backend' '--notify       Herramienta de notificaciones existente' \
      '--admin        Crear administrador inicial si no existe' \
      '--menu         Abrir menú (predeterminado)' \
      'DRAPEMIND_NO_ANIMATION=1 desactiva movimiento; NO_COLOR=1 desactiva color.'
    exit 0
fi
[[ $EUID -eq 0 ]] || { ui_text '1;31' 'Ejecuta como root o con sudo.'; exit 1; }
[[ -f /etc/debian_version ]] || { ui_text '1;31' 'Se requiere Ubuntu o Debian con systemd.'; exit 1; }
config_exports=$(python3 "$CONFIG_TOOL" shell --app-dir "$DRAPE_APP_DIR")
eval "$config_exports"
export DRAPEMIND_APP_DIR="$DRAPE_APP_DIR"
export PATH="/opt/drapemind/node/current/bin:$PATH"
PY="$BACKEND_DIR/.venv/bin/python"
mkdir -p "$DRAPE_APP_DIR/.deploy" /var/log/drapemind
DRAPE_LOG_DIR="/var/log/drapemind/$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -m 700 "$DRAPE_LOG_DIR"
python3 "$CONFIG_TOOL" save --app-dir "$DRAPE_APP_DIR"
lock_deploy() { exec 9>/var/lock/drapemind-deploy.lock; flock -n 9 || { ui_text '1;31' 'Ya hay una operación DrapeMind en ejecución.'; return 1; }; }
cfg() { "$PY" "$CONFIG_TOOL" "$1" --app-dir "$DRAPE_APP_DIR"; }
prepare_env() { python3 "$CONFIG_TOOL" env --app-dir "$DRAPE_APP_DIR"; }
packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl git openssl xz-utils build-essential libpq-dev python3 python3-venv python3-dev postgresql postgresql-contrib nginx nano acl
    systemctl enable --now postgresql nginx
}
python_env() {
    python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ requerido"'
    [[ -x "$PY" ]] || python3 -m venv "$BACKEND_DIR/.venv"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r "$BACKEND_DIR/requirements.txt"
}
node_env() {
    # Node privado del proyecto: no cambia el Node de taji u otros servicios.
    local arch tmp name checksum
    case "$(uname -m)" in x86_64) arch=x64;; aarch64|arm64) arch=arm64;; *) return 1;; esac
    tmp=$(mktemp -d)
    curl --fail --silent --show-error --retry 3 https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt -o "$tmp/sums"
    read -r checksum name < <(awk -v arch="$arch" '$2 ~ "^node-v24\\.[0-9]+\\.[0-9]+-linux-"arch"\\.tar\\.xz$" {print $1, $2; exit}' "$tmp/sums")
    [[ "$checksum" =~ ^[a-f0-9]{64}$ && "$name" =~ ^node-v24\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] || return 1
    curl --fail --silent --show-error --retry 3 "https://nodejs.org/dist/latest-v24.x/$name" -o "$tmp/$name"
    (cd "$tmp"; printf '%s  %s\n' "$checksum" "$name" | sha256sum -c -)
    mkdir -p /opt/drapemind/node
    [[ -d "/opt/drapemind/node/${name%.tar.xz}" ]] || tar -xJf "$tmp/$name" -C /opt/drapemind/node
    ln -sfn "/opt/drapemind/node/${name%.tar.xz}" /opt/drapemind/node/current
    # tmp es una ruta literal de mktemp validada antes de su eliminación.
    [[ "$tmp" == /tmp/tmp.* ]] && rm -rf -- "$tmp"
    node --version; npm --version
}
backup() { (cd "$BACKEND_DIR"; "$PY" -m scripts.saas_setup backup); }
migrate() {
    (cd "$BACKEND_DIR"; "$PY" -m alembic upgrade head)
    cfg grants
}
service() {
    # Cuenta dedicada incluso con el checkout en /root. ACL de travesía, sin abrir /root globalmente.
    id -u drapemind >/dev/null 2>&1 || useradd --system --home-dir "$BACKEND_DIR" --shell /usr/sbin/nologin drapemind
    local parent="$BACKEND_DIR"
    while [[ "$parent" != / ]]; do setfacl -m u:drapemind:--x "$parent"; parent=$(dirname "$parent"); done
    setfacl -R -m u:drapemind:rX "$BACKEND_DIR"
    setfacl -m u:drapemind:r-- "$BACKEND_DIR/.env"
    mkdir -p "$BACKEND_DIR/logs" "$BACKEND_DIR/app/static/products"
    setfacl -R -m u:drapemind:rwX "$BACKEND_DIR/logs" "$BACKEND_DIR/app/static"
    setfacl -d -m u:drapemind:rwX "$BACKEND_DIR/logs" "$BACKEND_DIR/app/static" "$BACKEND_DIR/app/static/products"
    cat > /etc/systemd/system/drapemind-backend.service <<EOF
[Unit]
Description=DrapeMind FastAPI / NVIDIA API
After=network-online.target postgresql.service
Wants=network-online.target postgresql.service
[Service]
Type=simple
User=drapemind
Group=drapemind
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$PY -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1 --timeout-keep-alive 60 --ws-ping-interval 60 --ws-ping-timeout 300
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
UMask=0027
LimitNOFILE=65535
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable drapemind-backend
    systemctl restart drapemind-backend
}
web_build() { bash "$WEB_DIR/install.sh" --build; }
wait_backend() {
    local attempt
    for attempt in {1..40}; do
        if curl --fail --silent --max-time 3 "http://127.0.0.1:$BACKEND_PORT/health/ready" >/dev/null; then return 0; fi
        sleep 1
    done
    printf 'Backend no disponible; consulta journalctl -u drapemind-backend\n' >&2; return 1
}
check() {
    local rc=0
    if systemctl is-active --quiet drapemind-backend && curl --fail --silent --max-time 5 "http://127.0.0.1:$BACKEND_PORT/health/ready" >/dev/null; then ui_text '32' 'OK · Backend y PostgreSQL'; else ui_text '31' 'ERROR · Backend/PostgreSQL'; rc=1; fi
    if curl --fail --silent --max-time 10 --resolve "$SERVER_IP:443:127.0.0.1" "$DRAPE_ORIGIN$DRAPE_PREFIX/config.json" | python3 -c 'import sys,json; v=json.load(sys.stdin); assert v["apiPrefix"].endswith("/api/v1")'; then ui_text '32' 'OK · Web y certificado HTTPS'; else ui_text '31' 'ERROR · Web/HTTPS'; rc=1; fi
    if curl --fail --silent --max-time 10 --resolve "$SERVER_IP:443:127.0.0.1" "$DRAPE_ORIGIN$DRAPE_PREFIX/health/ready" >/dev/null; then ui_text '32' 'OK · Proxy API HTTPS'; else ui_text '31' 'ERROR · Proxy API'; rc=1; fi
    printf 'Web: %s%s/\nAPI: %s%s/api/v1\nLogs de esta operación: %s\n' "$DRAPE_ORIGIN" "$DRAPE_PREFIX" "$DRAPE_ORIGIN" "$DRAPE_PREFIX" "$DRAPE_LOG_DIR"
    return "$rc"
}
git_preflight() {
    local repo="$1" branch="$2"
    [[ -z "$(git -C "$repo" status --porcelain)" ]] || { printf 'Hay cambios locales en %s. Se conservan; guarda un commit o stash antes de actualizar.\n' "$repo"; return 1; }
    [[ "$(git -C "$repo" branch --show-current)" == "$branch" ]] || { printf 'La rama de %s no coincide con %s.\n' "$repo" "$branch"; return 1; }
}
git_fetch_all() {
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}"
    git_preflight "$BACKEND_DIR" "$DRAPE_BACKEND_BRANCH"; git_preflight "$WEB_DIR" "$DRAPE_WEB_BRANCH"
    git -C "$BACKEND_DIR" fetch origin "$DRAPE_BACKEND_BRANCH"
    git -C "$WEB_DIR" fetch origin "$DRAPE_WEB_BRANCH"
    git -C "$BACKEND_DIR" merge-base --is-ancestor HEAD FETCH_HEAD
    git -C "$WEB_DIR" merge-base --is-ancestor HEAD FETCH_HEAD
    printf 'Ambos repositorios admiten avance directo.\n'
}
git_advance() {
    git -C "$BACKEND_DIR" merge --ff-only FETCH_HEAD
    git -C "$WEB_DIR" merge --ff-only FETCH_HEAD
    # Reabre el gestor actualizado para evitar funciones antiguas cargadas en memoria.
}
tls_ready() { curl --silent --show-error --max-time 8 --resolve "$SERVER_IP:443:127.0.0.1" "$DRAPE_ORIGIN/" --output /dev/null; }
tls() {
    if tls_ready; then printf 'Se reutiliza HTTPS válido del servidor existente.\n'; return 0; fi
    local email certbot=/opt/drapemind/certbot/bin/certbot
    # Solicitar términos/contacto con el TTY, antes del paso animado.
    email=$(python3 "$CONFIG_TOOL" tls-config --app-dir "$DRAPE_APP_DIR")
    python3 -m venv /opt/drapemind/certbot
    /opt/drapemind/certbot/bin/pip install --quiet 'certbot>=5.4,<6'
    # Un sitio nuevo creado por el gestor ya expone este webroot en HTTP.
    # Si había un sitio sin HTTPS, no se altera su ACME: requiere integrarlo explícitamente.
    [[ -L /etc/nginx/sites-enabled/drapemind.conf ]] || { printf 'Integra /.well-known/acme-challenge/ en tu servidor HTTP antes de emitir el certificado.\n' >&2; return 1; }
    install -d -m 755 /var/lib/drapemind /var/lib/drapemind/acme
    local nameflag=--domain
    [[ "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && nameflag=--ip-address
    (umask 022; "$certbot" certonly --non-interactive --agree-tos --email "$email" --preferred-profile shortlived --webroot -w /var/lib/drapemind/acme "$nameflag" "$SERVER_IP" --cert-name "drapemind-$SERVER_IP" --deploy-hook 'nginx -t && systemctl reload nginx')
    local site=/etc/nginx/sites-available/drapemind.conf
    cp "$site" "$DRAPE_APP_DIR/.deploy/nginx-before-tls.conf"
    sed -i "/listen 80;/a\ listen 443 ssl;\n ssl_certificate /etc/letsencrypt/live/drapemind-$SERVER_IP/fullchain.pem;\n ssl_certificate_key /etc/letsencrypt/live/drapemind-$SERVER_IP/privkey.pem;\n ssl_protocols TLSv1.2 TLSv1.3;" "$site"
    if ! nginx -t; then cp "$DRAPE_APP_DIR/.deploy/nginx-before-tls.conf" "$site"; return 1; fi
    systemctl reload nginx
    cat > /etc/systemd/system/drapemind-certbot-renew.service <<EOF
[Unit]
Description=Renovar certificado HTTPS de DrapeMind
[Service]
Type=oneshot
UMask=0022
ExecStart=$certbot renew --quiet --cert-name drapemind-$SERVER_IP
EOF
    cat > /etc/systemd/system/drapemind-certbot-renew.timer <<'EOF'
[Unit]
Description=Revisar renovación de HTTPS cada 12 horas
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload; systemctl enable --now drapemind-certbot-renew.timer
    tls_ready
}
install_backend() {
    TOTAL=8; STEP=0
    run_step 'Dependencias Linux y PostgreSQL' packages
    run_step 'Configuración privada de producción' prepare_env
    run_step 'Entorno Python y dependencias' python_env
    run_step 'Base y roles PostgreSQL' cfg db
    run_step 'Respaldo antes de migrar' backup
    run_step 'Migraciones y permisos de ejecución' migrate
    run_step 'Administrador inicial' cfg admin
    run_step 'Servicio nativo y permisos' service
    wait_backend
}
install_all() {
    install_backend
    TOTAL=3; STEP=0
    run_step 'Node privado del proyecto' node_env
    run_step 'Compilar y publicar Angular' web_build
    run_step 'Integrar proxy y WebSockets' cfg nginx
    tls
    check
    printf 'Acceso inicial (solo si fue creado): %s/.deploy/admin-access.json\n' "$DRAPE_APP_DIR"
}
update() {
    TOTAL=3; STEP=0
    run_step 'Comprobar ambos repositorios y descargar cambios' git_fetch_all
    run_step 'Respaldo PostgreSQL antes de actualizar' backup
    run_step 'Avanzar ambos repositorios sin descartar cambios' git_advance
    exec bash "$DEPLOY_DIR/platform.sh" --apply-update
}
apply_update() {
    TOTAL=8; STEP=0
    run_step 'Revisar configuración de producción' prepare_env
    run_step 'Actualizar dependencias Python' python_env
    run_step 'Migraciones y permisos runtime' migrate
    run_step 'Preparar Node del proyecto' node_env
    run_step 'Compilar y publicar Angular' web_build
    run_step 'Actualizar permisos y reiniciar backend' service
    run_step 'Validar e integrar Nginx' cfg nginx
    run_step 'Esperar disponibilidad del backend' wait_backend
    tls; check
}
menu() {
    [[ -t 0 ]] || { printf 'Selecciona una acción explícita; consulta --help.\n'; return 2; }
    while true; do
        ui_header
        ui_item 1 'Instalar desde cero · backend + web + PostgreSQL + HTTPS'
        ui_item 2 'Actualizar todo · respaldo + Git + migraciones + publicación'
        ui_item 3 'Configurar IA NVIDIA y pagos Stripe'
        ui_item 4 'Migraciones y permisos runtime'
        ui_item 5 'Seeder por empresa (sin borrar datos)'
        ui_item 6 'Crear respaldo PostgreSQL'
        ui_item 7 'Estado, web, API y certificado HTTPS'
        ui_item 8 'Reiniciar backend'
        ui_item 9 'Ver logs en vivo'
        ui_item 10 'Compilar y publicar solo la web'
        ui_item 11 'Integrar Nginx y WebSockets'
        ui_item 12 'Configurar o verificar HTTPS'
        ui_item 13 'Importar .env privados subidos desde vps_terminal'
        ui_item 0 'Salir'
        read -rp 'Elige una opción: ' choice
        case "$choice" in
          1) next=(--all);;
          2) next=(--update);;
          3) next=(--env);;
          4) next=(--migrate);;
          5) read -rp 'Identificador de empresa [drapemind]: ' tenant; next=(--seed --quick --tenant "${tenant:-drapemind}");;
          6) next=(--backup);;
          7) next=(--check);;
          8) next=(--restart);;
          9) next=(--logs);;
          10) next=(--frontend);;
          11) next=(--nginx);;
          12) next=(--tls);;
          13) next=(--import-env);;
          0) return;; *) ui_text '33' 'Elige una opción de la lista.'; continue;;
        esac
        if bash "$DEPLOY_DIR/platform.sh" "${next[@]}"; then ui_text '32' 'Operación completada.'; else ui_text '31' 'Operación detenida. Revisa el mensaje o el registro privado.'; fi
        read -rp 'Enter para volver al menú… ' _
    done
}
case "$action" in
 --menu) menu;;
 --help|-h) :;;
 --check|-c) check;;
 --logs|--ai-logs) exec journalctl -u drapemind-backend -f;;
 *)
    lock_deploy
    case "$action" in
      --all|-a) install_all;;
      --backend|-b) install_backend;;
      --update|-u) update;;
      --apply-update) apply_update;;
      --frontend|--web|-w) TOTAL=2; run_step 'Preparar Node' node_env; run_step 'Publicar Angular' web_build;;
      --env) python3 "$CONFIG_TOOL" env-wizard --app-dir "$DRAPE_APP_DIR"; if systemctl is-active --quiet drapemind-backend; then setfacl -m u:drapemind:r-- "$BACKEND_DIR/.env"; systemctl restart drapemind-backend; wait_backend; fi;;
      --import-env) python3 "$CONFIG_TOOL" import-env --app-dir "$DRAPE_APP_DIR"; if systemctl is-active --quiet drapemind-backend; then setfacl -m u:drapemind:r-- "$BACKEND_DIR/.env"; systemctl restart drapemind-backend; wait_backend; fi;;
      --migrate) TOTAL=3; run_step 'Respaldar DB' backup; run_step 'Migrar y renovar permisos' migrate; run_step 'Reiniciar servicio' service; wait_backend;;
      --backup) TOTAL=1; run_step 'Respaldar PostgreSQL' backup;;
      --nginx) TOTAL=1; run_step 'Integrar y validar Nginx' cfg nginx;;
      --tls) tls;;
      --restart) systemctl restart drapemind-backend; wait_backend;;
      --service) service; wait_backend;;
      --uninstall|--remove) bash "$DEPLOY_DIR/uninstall_drapemind.sh";;
      --admin) cfg admin;;
      --seed) for argument in "$@"; do [[ "$argument" != --reset && "$argument" != --reset=* ]] || { ui_text '31' 'El reset global está deshabilitado en SaaS.'; exit 2; }; done; (cd "$BACKEND_DIR"; "$PY" -m scripts.db.seed_data "$@");;
      --notify|--notification|-n) (cd "$BACKEND_DIR"; "$PY" scripts/send_custom_notification.py "$@");;
      *) printf 'Opción no reconocida. Consulta --help.\n' >&2; exit 2;;
    esac;;
esac
