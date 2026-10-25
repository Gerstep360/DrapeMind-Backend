"""Configuración privada, PostgreSQL y proxy compartido del instalador nativo.

La lectura y generación de configuración no importa la aplicación ni necesita pip.
Las acciones de base de datos se ejecutan después de preparar el entorno virtual.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
from instalar_vps import validate_origin, validate_branch, validate_repo


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
        output.write(text)
    temporary.replace(path)
    path.chmod(0o600)


def load_config(app):
    app = app.resolve()
    if app.name.lower() != 'drapemind' or any(c.isspace() for c in str(app)):
        raise ValueError('El destino debe ser un directorio DrapeMind dedicado, sin espacios.')
    path = app / 'deploy.json'
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    else:
        web = next((p.name for p in (app/'web', app/'DrapeMind-web', app/'DrapeMind-Web', app/'frontend') if (p/'package.json').exists()), 'web')
        data = dict(origin='https://167.86.106.105', prefix='/DrapeMind', backend_dir=BACKEND.name,
                    web_dir=web, port=8045, backend_branch='Main', web_branch='Main',
                    backend_repo='https://github.com/Gerstep360/DrapeMind-Backend.git',
                    web_repo='https://github.com/Gerstep360/DrapeMind-web.git', acme_email='', acme_agree_tos=False)
    data['origin'] = validate_origin(data['origin'])
    if not re.fullmatch(r'/[a-zA-Z0-9_-]+', data['prefix']):
        raise ValueError('Prefijo inválido.')
    if type(data['port']) is not int or not 1024 <= data['port'] <= 65535:
        raise ValueError('Puerto interno inválido.')
    for key in ('backend', 'web'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', data[key+'_dir']):
            raise ValueError('Nombre de carpeta inválido.')
        validate_branch(data[key+'_branch']); validate_repo(data[key+'_repo'])
        target = (app / data[key+'_dir']).resolve()
        if target.parent != app:
            raise ValueError('Los repositorios deben permanecer dentro de DrapeMind.')
    if (app / data['backend_dir']).resolve() != BACKEND:
        raise ValueError('El backend ejecutado no coincide con deploy.json.')
    return data


def read_env(path):
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        key = key.strip().removeprefix('export ')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            continue
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        result[key] = str(value)
    return result


def update_env(path, values):
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    lines = [line for line in old.splitlines() if line.partition('=')[0].strip().removeprefix('export ') not in values]
    lines.extend(key + '=' + json.dumps(str(value), ensure_ascii=False) for key, value in values.items())
    private_write(path, '\n'.join(lines) + '\n')


def import_private_envs(app):
    """Importar copias íntegras SFTP; mantener las conexiones propias del VPS."""
    source = app/'.private/env/backend.env'
    target = BACKEND/'.env'
    if source.is_file():
        previous = read_env(target)
        if target.exists():
            archive=app/'.deploy/env-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')/'backend.env'
            private_write(archive,target.read_text(encoding='utf-8'))
        private_write(target, source.read_text(encoding='utf-8-sig'))
        connection_keys = ['DATABASE_URL','RUNTIME_DATABASE_URL','POSTGRES_HOST','POSTGRES_PORT','POSTGRES_USER','POSTGRES_PASSWORD','POSTGRES_DB']
        if previous and previous.get('ENVIRONMENT') == 'production':
            keep = {key:previous[key] for key in connection_keys+['SECRET_KEY','PAYMENT_WEBHOOK_SECRET'] if key in previous}
            incoming=read_env(source)
            for key in ('STRIPE_SAAS_WEBHOOK_SECRET','STRIPE_WEBHOOK_SECRET'):
                if incoming.get('STRIPE_LOCAL_WEBHOOK_SECRET') and incoming.get(key)==incoming['STRIPE_LOCAL_WEBHOOK_SECRET']:
                    if previous.get(key) and previous[key]!=previous.get('STRIPE_LOCAL_WEBHOOK_SECRET'):
                        keep[key]=previous[key]
        else:
            # El .env del PC puede contener postgres, puertos o contraseñas de otra máquina.
            # La copia íntegra se conserva en .private; esta instancia usa su propia base.
            from urllib.parse import quote
            password = secrets.token_urlsafe(36)
            keep = dict(DATABASE_URL=f'postgresql+psycopg://drapemind_owner:{quote(password)}@127.0.0.1:5432/drapemind_db',
                        RUNTIME_DATABASE_URL='',POSTGRES_HOST='127.0.0.1',POSTGRES_PORT='5432',
                        POSTGRES_USER='drapemind_owner',POSTGRES_PASSWORD=password,POSTGRES_DB='drapemind_db')
        update_env(target,keep)
        print('Backend: entorno privado importado; conexión de esta instancia conservada o preparada.')
    web_source=app/'.private/env/web.env'
    if web_source.is_file():
        private_write(app/load_config(app)['web_dir']/'.env',web_source.read_text(encoding='utf-8-sig'))
        print('Web: .env privado copiado; sus valores no se incorporan a config.json ni al build.')
    if not source.is_file() and not web_source.is_file():
        raise ValueError('No hay copias SFTP en .private/env. Usa «Subir .env de forma privada» en vps_terminal.py.')


def prepare_env(app, config, wizard=False):
    path = BACKEND / '.env'
    if not path.exists() and any((app/'.private/env'/name).is_file() for name in ('backend.env','web.env')):
        import_private_envs(app)
    old = read_env(path)
    from urllib.parse import quote
    changes = dict(ENVIRONMENT='production', DEBUG='false', PORT=str(config['port']),
                   ROOT_PATH=config['prefix'], SAAS_WEB_URL=config['origin']+config['prefix'],
                   CORS_ORIGINS=json.dumps([config['origin']]), CORS_ORIGIN_REGEX='',
                   CORS_ALLOW_CREDENTIALS='true', DB_ECHO='false')
    for key in ('SECRET_KEY', 'PAYMENT_WEBHOOK_SECRET'):
        if not old.get(key) or old[key].lower().startswith(('change-me', 'cambiar_')):
            changes[key] = secrets.token_urlsafe(48)
    if old.get('POSTGRES_PASSWORD','').lower().startswith(('cambiar_', 'change-me')):
        changes['POSTGRES_PASSWORD'] = secrets.token_urlsafe(36)
    if not old:
        password = secrets.token_urlsafe(36)
        changes.update(ACCESS_TOKEN_EXPIRE_MINUTES='60', POSTGRES_HOST='127.0.0.1', POSTGRES_PORT='5432', POSTGRES_USER='drapemind_owner',
                       POSTGRES_PASSWORD=password, POSTGRES_DB='drapemind_db',
                       DATABASE_URL=f'postgresql+psycopg://drapemind_owner:{quote(password)}@127.0.0.1:5432/drapemind_db')
    if not old.get('NVIDIA_MODEL'):
        changes.update(NVIDIA_MODEL='nvidia/nemotron-3-super-120b-a12b', NVIDIA_BASE_URL='https://integrate.api.nvidia.com/v1')
    for key in ('STRIPE_SAAS_WEBHOOK_SECRET','STRIPE_WEBHOOK_SECRET'):
        if old.get('STRIPE_LOCAL_WEBHOOK_SECRET') and old.get(key)==old['STRIPE_LOCAL_WEBHOOK_SECRET']:
            changes[key]=''
            print(key+': firma de Stripe CLI detectada; configura la firma publicada del Dashboard.')
    # Variables existentes de NVIDIA, Stripe, correo y Firebase se conservan.
    if wizard:
        if not sys.stdin.isatty():
            raise ValueError('La configuración guiada requiere una terminal interactiva.')
        print('Enter conserva el valor. Las claves no se muestran ni se guardan en deploy.json.')
        for key, label in [('NVIDIA_API_KEY','NVIDIA API key'), ('STRIPE_SECRET_KEY','Stripe secret key'),
                           ('STRIPE_PUBLISHABLE_KEY','Stripe publishable key'),
                           ('STRIPE_SAAS_WEBHOOK_SECRET','Firma del webhook SaaS publicado'),
                           ('STRIPE_WEBHOOK_SECRET','Firma del webhook de compras publicado')]:
            value = getpass.getpass(label + ' [' + ('configurada' if old.get(key) else 'pendiente') + ']: ')
            if value:
                changes[key] = value
    update_env(path, changes)
    print('.env de producción preparado; credenciales existentes conservadas.')
    env = read_env(path)
    for key, label in [('NVIDIA_API_KEY', 'IA NVIDIA'), ('STRIPE_SECRET_KEY', 'Cobros Stripe'), ('STRIPE_SAAS_WEBHOOK_SECRET', 'Webhook SaaS')]:
        print(label + ': ' + ('configurado' if env.get(key) else 'pendiente de configurar con --env'))


def database_urls():
    from sqlalchemy.engine import make_url, URL
    env = read_env(BACKEND / '.env')
    admin = make_url(env['DATABASE_URL']) if env.get('DATABASE_URL') else URL.create('postgresql+psycopg',
          username=env.get('POSTGRES_USER','postgres'), password=env.get('POSTGRES_PASSWORD'),
          host=env.get('POSTGRES_HOST','127.0.0.1'), port=int(env.get('POSTGRES_PORT','5432')), database=env.get('POSTGRES_DB','drapemind_db'))
    if admin.get_backend_name() != 'postgresql' or not admin.database:
        raise ValueError('La instalación nativa requiere PostgreSQL.')
    runtime = make_url(env['RUNTIME_DATABASE_URL']) if env.get('RUNTIME_DATABASE_URL') else admin.set(username='drapemind_runtime', password=secrets.token_urlsafe(36))
    if runtime.database != admin.database or runtime.host != admin.host or runtime.port != admin.port or runtime.username == admin.username:
        raise ValueError('La conexión HTTP debe usar un rol distinto en la misma base.')
    if admin.host not in ('localhost', '127.0.0.1', None):
        raise ValueError('El aprovisionamiento automático es local; prepara la base remota y sus roles por separado.')
    return admin, runtime


def identifier(value):
    if not value or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', value):
        raise ValueError('Nombre de base o rol inválido para aprovisionamiento automático.')
    return '"' + value + '"'


def psql(sql, admin, database='postgres'):
    command = ['runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-p', str(admin.port or 5432), '-d', database, '-At']
    result = subprocess.run(command, input=sql, text=True, capture_output=True, cwd='/tmp')
    if result.returncode:
        raise ValueError('PostgreSQL no completó el aprovisionamiento. Revisa permisos y credenciales locales; no se modifican otras bases.')
    return result.stdout.strip()


def provision_database():
    admin, runtime = database_urls()
    # Persistir antes de crear el rol permite reintentar sin perder su contraseña.
    update_env(BACKEND/'.env', {'RUNTIME_DATABASE_URL':runtime.render_as_string(hide_password=False)})
    for url in (admin, runtime):
        role = identifier(url.username)
        exists = psql("SELECT 1 FROM pg_roles WHERE rolname='"+url.username+"';", admin)
        if not exists:
            if not url.password:
                raise ValueError('Configura una contraseña para el nuevo rol.')
            password = url.password.replace("'", "''")
            psql(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{password}';", admin)
        elif url.username == runtime.username:
            flags = psql("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='"+url.username+"';", admin)
            if flags != 'f':
                raise ValueError('El rol runtime existente omite RLS. No se cambia un rol compartido automáticamente.')
    name = identifier(admin.database)
    if not psql("SELECT 1 FROM pg_database WHERE datname='"+admin.database+"';", admin):
        psql(f'CREATE DATABASE {name} OWNER {identifier(admin.username)};', admin)
    # No se rotan passwords de roles existentes. Una incompatibilidad detiene la instalación.
    from sqlalchemy import create_engine, text
    for url in (admin, runtime):
        with create_engine(url, connect_args={'connect_timeout':5}).connect() as connection:
            connection.execute(text('SELECT 1'))
    update_env(BACKEND/'.env', {'RUNTIME_DATABASE_URL':runtime.render_as_string(hide_password=False)})
    print('Base y roles disponibles; no se han borrado datos ni modificado contraseñas existentes.')


def grant_runtime():
    admin, runtime = database_urls()
    role = identifier(runtime.username)
    owner = identifier(admin.username)
    psql(f'''GRANT CONNECT ON DATABASE {identifier(admin.database)} TO {role};
GRANT USAGE ON SCHEMA public TO {role};
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role};
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {role};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {role};''', admin, admin.database)
    print('Permisos de ejecución renovados tras las migraciones.')


def ensure_admin(app):
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings
    from app.core.security import hash_password
    from app.core.tenancy import system_scope
    from app.db.tenant_session import TenantSession
    from app.models import User, Role, UserStatus
    engine = create_engine(settings.database_uri)
    email = 'adminsaas@drapemind.com'
    with sessionmaker(bind=engine, class_=TenantSession)() as db, system_scope(db):
        if db.get_bind().dialect.name=='postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(60102501)'))
        existing = db.scalar(select(User).where(User.is_platform_admin.is_(True), User.tenant_id.is_(None),User.email==email))
        if existing:
            print('Se conserva la cuenta SaaS genérica existente, sin cambiar su contraseña.')
            return
        password = secrets.token_urlsafe(24)
        db.add(User(tenant_id=None, is_platform_admin=True, nombre='Administrador de plataforma', email=email,
                    password_hash=hash_password(password), rol=Role.ADMIN, estado=UserStatus.ACTIVO))
        # Credenciales antes de commit: no se pierde la contraseña si falla escribir el archivo.
        target = app/'.deploy/admin-access.json'
        if target.exists():
            private_write(app/'.deploy/admin-access.previous.json',target.read_text(encoding='utf-8'))
        private_write(target, json.dumps(dict(email=email, password=password), indent=2)+'\n')
        db.commit()
    print('Administrador inicial creado. Acceso privado: '+str(target))


def nginx_tokens(text):
    # Comentarios y cadenas citadas no cuentan como llaves de bloques.
    expression = r'''\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};"'\#]+'''
    return [(m.group(), m.start(), m.end()) for m in re.finditer(expression, text) if not m.group().startswith('#')]


def server_blocks(text):
    tokens = nginx_tokens(text)
    blocks = []
    for i, (word, start, end) in enumerate(tokens[:-1]):
        if word != 'server' or tokens[i+1][0] != '{':
            continue
        depth, j, directive, directives = 1, i+2, [], []
        while j < len(tokens) and depth:
            value, begin, finish = tokens[j]
            if value == '{':
                depth += 1; directive = []
            elif value == '}':
                depth -= 1; directive = []
            elif depth == 1:
                if value == ';':
                    directives.append(directive); directive = []
                else:
                    directive.append(value.strip('"\''))
            j += 1
        if depth:
            raise ValueError('Bloque Nginx incompleto; corrige la configuración existente.')
        blocks.append(dict(start=start, opening=tokens[i+1][2], end=tokens[j-1][2], directives=directives))
    return blocks


def locations(config):
    prefix, port = config['prefix'], config['port']
    proxy = '''proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;'''
    result = f'''# Gestionado por DrapeMind: solo su prefijo público.
location = {prefix} {{ return 308 {prefix}/; }}
location ^~ {prefix}/api/ {{
    proxy_pass http://127.0.0.1:{port}/api/;
    {proxy}
    proxy_set_header X-Forwarded-Prefix {prefix};
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $drapemind_connection_upgrade;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;
    client_max_body_size 64M;
}}
'''
    for public, upstream in [('static/','static/'), ('health/','health/'), ('docs','docs'), ('redoc','redoc'), ('openapi.json','api/v1/openapi.json')]:
        result += f'''location {'^~' if public.endswith('/') else '='} {prefix}/{public} {{
    proxy_pass http://127.0.0.1:{port}/{upstream};
    {proxy}
}}
'''
    for name in ('config.json','index.html'):
        result += f'''location = {prefix}/{name} {{
    alias /var/www/drapemind/current/{name};
    add_header Cache-Control "no-store" always;
}}
'''
    result += f'''location ^~ {prefix}/ {{
    alias /var/www/drapemind/current/;
    index index.html;
    try_files $uri $uri/ {prefix}/index.html;
}}
'''
    if config.get('enforce_https', True):
        # Solo redirecciones con return, dentro de las rutas DrapeMind.
        result = re.sub(r'(location[^\n]+\{)', r'\1\n    if ($scheme = http) { return 308 https://$host$request_uri; }', result)
    return result


def matching_sites(host, etc):
    result = []
    candidates = list((etc/'sites-enabled').glob('*')) + list((etc/'conf.d').glob('*.conf'))
    visited = set()
    for path in candidates:
        path = path.resolve()
        if path in visited or not path.is_file():
            continue
        visited.add(path)
        text = path.read_text()
        matching = [b for b in server_blocks(text) if any(d and d[0]=='server_name' and host in d[1:] for d in b['directives'])]
        if matching:
            result.append((path, text, matching))
    return result


def configure_nginx(app, config, etc=Path('/etc/nginx')):
    subprocess.run(['nginx','-t'], check=True, capture_output=True)
    host = urlsplit(config['origin']).hostname
    snippet = etc/'snippets/drapemind.locations.conf'
    include = f'include {snippet};'
    changes = {snippet:locations(config), etc/'conf.d/drapemind-websocket.conf':
               "map $http_upgrade $drapemind_connection_upgrade { default upgrade; '' close; }\n"}
    matches = matching_sites(host, etc)
    if not matches:
        site = etc/'sites-available/drapemind.conf'
        if site.exists():
            raise ValueError('Ya existe drapemind.conf sin un servidor compatible; revísalo antes de continuar.')
        changes[site] = f'server {{\n listen 80;\n server_name {host};\n {include}\n location ^~ /.well-known/acme-challenge/ {{ root /var/lib/drapemind/acme; }}\n}}\n'
    else:
        for path, text, blocks in matches:
            for block in reversed(blocks):
                body = text[block['opening']:block['end']-1]
                if include in body:
                    continue
                # No se superponen rutas de una instalación anterior ni se borran para recuperarse.
                if re.search(r'location\s+(?:[=~^*]+\s+)?'+re.escape(config['prefix'])+r'(?:[/\s{])', body) or 'drapemind-subpath.conf' in body:
                    raise ValueError('El servidor ya tiene rutas DrapeMind antiguas. Retira únicamente ese snippet antes de instalar el nuevo.')
                pos = block['opening']
                text = text[:pos]+'\n    '+include+'\n'+text[pos:]
            changes[path] = text
    backup = app/'.deploy/nginx-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    backup.mkdir(parents=True, exist_ok=True); backup.chmod(0o700)
    originals = {path:path.read_bytes() if path.exists() else None for path in changes}
    link = etc/'sites-enabled/drapemind.conf'
    created_link = not matches
    link_added = False
    try:
        for i, (path, content) in enumerate(changes.items()):
            path.parent.mkdir(parents=True, exist_ok=True)
            if originals[path] is not None:
                private_write(backup/f'{i}_{path.name}', originals[path].decode())
            path.write_text(content)
        if created_link:
            if link.exists() or link.is_symlink():
                raise ValueError('El enlace drapemind.conf ya existe.')
            link.symlink_to(etc/'sites-available/drapemind.conf')
            link_added = True
        subprocess.run(['nginx','-t'], check=True, capture_output=True)
        subprocess.run(['systemctl','reload','nginx'], check=True)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        if link_added and link.is_symlink():
            link.unlink()
        raise
    print('Nginx validado y recargado; respaldo de configuración: '+str(backup))


def shell_config(app, config):
    values = dict(DRAPE_APP_DIR=str(app.resolve()), BACKEND_DIR=str(BACKEND),
        WEB_DIR=str(app/config['web_dir']), SERVER_IP=urlsplit(config['origin']).hostname,
        DRAPE_ORIGIN=config['origin'], DRAPE_PREFIX=config['prefix'], BACKEND_PORT=config['port'],
        DRAPE_BACKEND_BRANCH=config['backend_branch'], DRAPE_WEB_BRANCH=config['web_branch'])
    for key, value in values.items():
        print('export '+key+'='+shlex.quote(str(value)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['shell','save','env','env-wizard','import-env','db','grants','admin','nginx','tls-config'])
    parser.add_argument('--app-dir', type=Path, required=True)
    args = parser.parse_args()
    app = args.app_dir.resolve()
    config = load_config(app)
    if args.action == 'shell':
        shell_config(app,config)
    elif args.action == 'save':
        private_write(app/'deploy.json', json.dumps(config, indent=2)+'\n')
    elif args.action in ('env','env-wizard'):
        prepare_env(app,config,args.action=='env-wizard')
    elif args.action == 'import-env':
        import_private_envs(app)
        prepare_env(app,config)
    elif args.action == 'db':
        provision_database()
    elif args.action == 'grants':
        grant_runtime()
    elif args.action == 'admin':
        ensure_admin(app)
    elif args.action == 'nginx':
        configure_nginx(app,config)
    elif args.action == 'tls-config':
        # La aceptación de términos se solicita antes de emitir un certificado nuevo.
        if not config.get('acme_agree_tos'):
            if not sys.stdin.isatty():
                raise ValueError('Para emitir HTTPS nuevo usa instalar_vps.py --accept-acme-tos --email correo@dominio.')
            print('¿Aceptas https://letsencrypt.org/repository/ para solicitar HTTPS? [s/N]: ',end='',file=sys.stderr,flush=True)
            if input().strip().lower() != 's':
                raise ValueError('HTTPS pendiente; la configuración HTTP permanece disponible.')
            config['acme_agree_tos'] = True
        if not config.get('acme_email'):
            if not sys.stdin.isatty():
                raise ValueError('Falta correo de contacto ACME.')
            print('Correo para avisos del certificado: ',end='',file=sys.stderr,flush=True)
            config['acme_email'] = input().strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', config['acme_email']):
            raise ValueError('Correo ACME inválido.')
        private_write(app/'deploy.json',json.dumps(config,indent=2)+'\n')
        print(config['acme_email'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Las excepciones SQL/HTTP pueden incluir DSN; no se envían a la terminal.
        print(str(exc) if isinstance(exc,ValueError) else 'Operación no completada ('+type(exc).__name__+'). Revisa la configuración privada.',file=sys.stderr)
        raise SystemExit(1)
