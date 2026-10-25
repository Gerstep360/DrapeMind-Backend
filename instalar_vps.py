#!/usr/bin/env python3
"""Arranque sin dependencias: descarga los repositorios y abre el gestor Bash nativo."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time
from urllib.parse import urlsplit

BACKEND_REPO = 'https://github.com/Gerstep360/DrapeMind-Backend.git'
WEB_REPO = 'https://github.com/Gerstep360/DrapeMind-web.git'
DEFAULT_DIR = '/root/app/DrapeMind'
DEFAULT_ORIGIN = 'https://167.86.106.105'


def validate_origin(value):
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.path not in ('', '/') or url.username or url.password or url.query or url.fragment:
        raise ValueError('Usa un origen HTTPS sin ruta ni credenciales.')
    if url.port not in (None, 443):
        raise ValueError('El origen público debe utilizar el puerto 443.')
    try:
        ipaddress.IPv4Address(url.hostname)
    except ValueError:
        import re
        if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', url.hostname):
            raise ValueError('Host inválido; usa IPv4 o un dominio.') from None
    return 'https://' + url.hostname.lower()


def validate_repo(value):
    import re
    if re.fullmatch(r'https://[\w.-]+/[\w./-]+(?:\.git)?', value) or re.fullmatch(r'git@[\w.-]+:[\w./-]+', value):
        return value
    raise ValueError('Usa una URL Git HTTPS sin token o una URL SSH git@host:organización/repositorio.git.')


def validate_branch(value):
    import re
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/-]*', value) or '..' in value or value.endswith('/'):
        raise ValueError('Nombre de rama inválido.')
    return value


def card(title, description=''):
    width = max(16, min(shutil.get_terminal_size((80, 24)).columns - 2, 92))
    color = sys.stdout.isatty() and not os.environ.get('NO_COLOR')
    print(('\033[1;36m' if color else '') + '─' * width)
    for line in textwrap.wrap(title, width):
        print(line)
    print(('\033[0m' if color else '') + '─' * width)
    if description:
        print(textwrap.fill(description, width))


def run(command, label):
    print(f'→ {label}', flush=True)
    # Git necesita acceso al TTY para SSH o su gestor de credenciales.
    subprocess.run(command, check=True)
    print(f'✓ {label}', flush=True)


def clone_or_reuse(url, branch, target):
    if target.exists():
        if not (target / '.git').exists():
            raise ValueError(f'{target} existe y no es un repositorio. No se sobrescribe.')
        actual = subprocess.check_output(['git', '-C', str(target), 'remote', 'get-url', 'origin'], text=True).strip()
        if actual.rstrip('/') != url.rstrip('/'):
            raise ValueError(f'El origen de {target.name} no coincide con el configurado.')
        print(f'✓ Se conserva el checkout existente: {target.name}')
        return
    run(['git', 'clone', '--branch', branch, '--single-branch', '--', url, str(target)], f'Descargar {target.name}')


def synchronize_bootstrap(paths, config):
    """Recuperar el gestor ausente sin descartar cambios ni actualizar una sola mitad."""
    repositories = []
    for component in ('backend', 'web'):
        target, branch = paths[component], config[component + '_branch']
        status = subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain'], text=True)
        if status.strip():
            raise ValueError(f'{target.name} tiene cambios locales. Se conservan; guarda un commit o stash antes de preparar el gestor.')
        current = subprocess.check_output(['git', '-C', str(target), 'branch', '--show-current'], text=True).strip()
        if current != branch:
            raise ValueError(f'{target.name} está en {current or "HEAD separado"}; deploy.json solicita {branch}. Cambia al checkout correspondiente antes de continuar.')
        repositories.append((target, branch, 'refs/remotes/origin/' + branch))
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes')
    for target, branch, remote in repositories:
        run_command = ['git', '-C', str(target), 'fetch', '--no-tags', 'origin', f'refs/heads/{branch}:{remote}']
        print(f'→ Comprobar la rama remota {branch}: {target.name}', flush=True)
        subprocess.run(run_command, check=True, env=env)
        result = subprocess.run(['git', '-C', str(target), 'merge-base', '--is-ancestor', 'HEAD', remote])
        if result.returncode:
            raise ValueError(f'{target.name} diverge de origin/{branch}. No se descartan commits ni se restablece el repositorio.')
    backend, branch, remote = repositories[0]
    if subprocess.run(['git', '-C', str(backend), 'cat-file', '-e', remote + ':scripts/deploy/platform.sh'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError(f'La rama remota origin/{branch} del backend no contiene el gestor. Comprueba la rama publicada; los checkouts no se han sustituido.')
    if shutil.which('systemctl') and subprocess.run(['systemctl','is-active','--quiet','drapemind-backend'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        python = backend / '.venv/bin/python'
        if not python.exists():
            raise ValueError('El backend está activo y falta su entorno para respaldar la base antes de actualizar el gestor.')
        subprocess.run([str(python), '-m', 'scripts.saas_setup', 'backup'], cwd=backend, check=True)
    for target, branch, remote in repositories:
        run(['git', '-C', str(target), 'merge', '--ff-only', remote], f'Sincronizar {target.name} con origin/{branch}')


def validate_manager_bundle(paths):
    required = [('backend','scripts/deploy/platform.sh'), ('backend','scripts/deploy/platform_ui.sh'),
                ('backend','scripts/deploy/platform_config.py'), ('web','install.sh')]
    for component, relative in required:
        if not (paths[component] / relative).is_file():
            raise ValueError(f'Instalación incompleta: falta {component}/{relative} en la rama seleccionada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', default=DEFAULT_DIR)
    parser.add_argument('--origin', default=DEFAULT_ORIGIN)
    parser.add_argument('--backend-repo', default=BACKEND_REPO)
    parser.add_argument('--web-repo', default=WEB_REPO)
    parser.add_argument('--backend-branch', default=None, help='Rama del backend; Main en una instalación nueva')
    parser.add_argument('--web-branch', default=None, help='Rama web; Main en una instalación nueva')
    parser.add_argument('--prefix', default='/DrapeMind')
    parser.add_argument('--action', choices=['menu', 'install', 'update', 'check'], default='menu')
    parser.add_argument('--prepare-only', action='store_true', help='Descargar y configurar, sin instalar servicios')
    parser.add_argument('--yes', action='store_true', help='Usar los valores indicados sin preguntas')
    parser.add_argument('--accept-acme-tos', action='store_true', help='Aceptar términos de Let’s Encrypt para un certificado nuevo')
    parser.add_argument('--email', default='', help='Correo de contacto para Let’s Encrypt')
    args = parser.parse_args(argv)
    origin = validate_origin(args.origin)
    validate_repo(args.backend_repo); validate_repo(args.web_repo)
    validate_branch(args.backend_branch or 'Main'); validate_branch(args.web_branch or 'Main')
    import re
    if not re.fullmatch(r'/[a-zA-Z0-9_-]+', args.prefix):
        raise ValueError('El prefijo debe ser una ruta como /DrapeMind.')
    app = Path(args.app_dir).expanduser().resolve()
    if app == Path('/') or app.name.lower() != 'drapemind' or any(c.isspace() for c in str(app)):
        raise ValueError('Selecciona un directorio DrapeMind dedicado y sin espacios.')
    card('DRAPEMIND · Instalación y mantenimiento', f'Destino: {app} | Web y API: {origin}{args.prefix}/')
    if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise ValueError('Ejecuta este archivo con python3 como root en Ubuntu/Debian del VPS.')
    if not args.yes and sys.stdin.isatty() and args.action == 'menu':
        print('1. Preparar repositorios y abrir el menú\n2. Instalar desde cero\n3. Actualizar instalación\n4. Revisar estado\n0. Salir')
        choice = input('Elige [1]: ').strip() or '1'
        if choice == '0':
            return 0
        if choice not in ('1', '2', '3', '4'):
            raise ValueError('Opción inválida.')
        args.action = {'1': 'menu', '2': 'install', '3': 'update', '4': 'check'}[choice]
    if not shutil.which('git'):
        run(['apt-get', 'update', '-qq'], 'Preparar lista de paquetes')
        run(['apt-get', 'install', '-y', 'git', 'ca-certificates'], 'Instalar Git')
    app.mkdir(parents=True, exist_ok=True)
    config_path = app / 'deploy.json'
    if config_path.exists():
        config = json.loads(config_path.read_text())
        # La configuración existente manda; no se restablecen ramas/rutas al reabrir el menú.
        origin = validate_origin(config['origin'])
    else:
        config = dict(origin=origin, prefix=args.prefix, backend_dir='backend', web_dir='web',
                      backend_repo=args.backend_repo, web_repo=args.web_repo,
                      backend_branch=args.backend_branch or 'Main', web_branch=args.web_branch or 'Main',
                      port=8045, acme_email=args.email, acme_agree_tos=args.accept_acme_tos)
        # Reconoce instalaciones anteriores sin renombrarlas ni duplicar datos.
        for key, candidates in [('backend_dir', ['backend', 'DrapeMind-Backend']), ('web_dir', ['web', 'DrapeMind-web', 'DrapeMind-Web', 'frontend'])]:
            config[key] = next((name for name in candidates if (app / name / '.git').exists()), config[key])
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        config_path.chmod(0o600)
    if args.backend_branch or args.web_branch:
        for component in ('backend','web'):
            supplied = getattr(args,component+'_branch')
            if supplied:
                config[component+'_branch'] = validate_branch(supplied)
        config_path.write_text(json.dumps(config,indent=2)+'\n')
    if args.accept_acme_tos or args.email:
        config.update(acme_agree_tos=args.accept_acme_tos or config.get('acme_agree_tos', False), acme_email=args.email or config.get('acme_email', ''))
        config_path.write_text(json.dumps(config, indent=2) + '\n')
    paths = {}
    for key in ('backend', 'web'):
        target = (app / config[key + '_dir']).resolve()
        if target.parent != app:
            raise ValueError('Los repositorios deben estar directamente dentro de DrapeMind.')
        clone_or_reuse(validate_repo(config[key + '_repo']), validate_branch(config[key + '_branch']), target)
        paths[key] = target
    manager = paths['backend'] / 'scripts/deploy/platform.sh'
    if not manager.exists():
        print('El checkout no tiene todavía el gestor; se consultarán las ramas remotas antes de continuar.',flush=True)
        synchronize_bootstrap(paths,config)
    validate_manager_bundle(paths)
    launcher = '#!/usr/bin/env bash\nset -euo pipefail\nAPP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\nexport DRAPEMIND_APP_DIR="$APP_DIR"\nexec bash ' + __import__('shlex').quote(str(manager)) + ' "$@"\n'
    for name in ('install.sh', 'config.sh'):
        if (app / name).exists() and (app / name).read_text() != launcher:
            archive = app / '.deploy/bootstrap-backups' / time.strftime('%Y%m%dT%H%M%S')
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(app / name, archive / name)
        (app / name).write_text(launcher)
        (app / name).chmod(0o700)
    destination = app / 'instalar_vps.py'
    if destination.resolve() != Path(__file__).resolve():
        shutil.copy2(__file__, destination)
    print(f'✓ Gestor preparado: bash {app}/install.sh')
    if args.prepare_only:
        return 0
    action = {'menu': [], 'install': ['--all'], 'update': ['--update'], 'check': ['--check']}[args.action]
    return subprocess.call(['bash', str(app / 'install.sh'), *action], env=dict(os.environ, DRAPEMIND_APP_DIR=str(app)))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # No se imprimen comandos que pudieran contener credenciales de Git.
        print(f'No se completó la preparación: {exc if isinstance(exc, ValueError) else type(exc).__name__}', file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('\nOperación interrumpida. Puedes volver a abrir el gestor.')
        raise SystemExit(130)
