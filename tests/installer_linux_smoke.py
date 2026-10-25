"""Prueba opt-in en Linux: Nginx aislado, web por versiones y base PostgreSQL temporal.

Ejecutar como root solo en una copia de pruebas dentro de /tmp/.../DrapeMind/backend.
No modifica /etc/nginx, systemd ni las bases de aplicaciones existentes.
"""
from pathlib import Path
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('deployment',ROOT/'scripts/deploy/platform_config.py')
deployment=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployment)


def nginx_smoke(folder):
    class Echo(BaseHTTPRequestHandler):
        def do_GET(self):
            body=json.dumps(dict(path=self.path,upgrade=self.headers.get('Upgrade'),prefix=self.headers.get('X-Forwarded-Prefix'))).encode()
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Echo)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    public=folder/'public';public.mkdir();public.chmod(0o755)
    (public/'index.html').write_text('DRAPEMIND_SPA')
    (public/'config.json').write_text('{"apiPrefix":"/DrapeMind/api/v1"}')
    snippet=deployment.locations(dict(prefix='/DrapeMind',port=upstream.server_port,enforce_https=False)).replace('/var/www/drapemind/current',str(public))
    config=folder/'nginx.conf'
    config.write_text(f'''pid {folder}/nginx.pid;
error_log {folder}/nginx-error.log;
events {{}}
http {{
 access_log off;
 map $http_upgrade $drapemind_connection_upgrade {{ default upgrade; '' close; }}
 server {{ listen 127.0.0.1:{port}; server_name localhost;
 {snippet}
 }}
}}
''')
    process=subprocess.Popen(['nginx','-p',str(folder),'-c',str(config),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    base=f'http://127.0.0.1:{port}'
    try:
        for attempt in range(30):
            try:
                with urlopen(base+'/DrapeMind/config.json',timeout=1) as response:
                    assert json.load(response)['apiPrefix']=='/DrapeMind/api/v1'
                    assert response.headers['Cache-Control']=='no-store'
                break
            except OSError:
                time.sleep(.1)
        else: raise AssertionError('Nginx aislado no inició')
        with urlopen(base+'/DrapeMind/catalog/example',timeout=2) as response:
            assert response.read()==b'DRAPEMIND_SPA'
        request=Request(base+'/DrapeMind/api/v1/ping',headers={'Upgrade':'websocket','Connection':'upgrade'})
        with urlopen(request,timeout=2) as response:
            data=json.load(response)
            assert data==dict(path='/api/v1/ping',upgrade='websocket',prefix='/DrapeMind')
        with urlopen(base+'/DrapeMind/health/ready',timeout=2) as response:
            assert json.load(response)['path']=='/health/ready'
        secured=deployment.locations(dict(prefix='/DrapeMind',port=upstream.server_port)).replace('/var/www/drapemind/current',str(public))
        config.write_text(config.read_text().replace(snippet,secured))
        subprocess.run(['nginx','-p',str(folder),'-c',str(config),'-t'],check=True,capture_output=True)
        import signal,http.client
        process.send_signal(signal.SIGHUP)
        for attempt in range(20):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            connection.request('GET','/DrapeMind/config.json')
            response=connection.getresponse()
            status,location=response.status,response.getheader('Location')
            response.read();connection.close()
            if status==308:
                assert location.startswith('https://') and location.endswith('/DrapeMind/config.json')
                break
            time.sleep(.1)
        else: raise AssertionError('Falta redirección HTTPS')
        print('PASS: SPA, config sin caché, API y cabeceras WebSocket en Nginx aislado',flush=True)
        print('PASS: redirección HTTPS limitada al prefijo de DrapeMind',flush=True)
    finally:
        process.terminate();process.wait(timeout=5);upstream.shutdown()


def publication_smoke(folder):
    project=folder/'web';project.mkdir();(project/'dist/web/browser').mkdir(parents=True)
    (project/'dist/web/browser/index.html').write_text('release-two')
    shutil.copy2(ROOT.parent/'web/install.sh',project/'install.sh')
    bin_dir=folder/'bin';bin_dir.mkdir()
    for name,body in [('node','exit 0'),('npm','exit "${FAKE_NPM_EXIT:-0}"')]:
        f=bin_dir/name;f.write_text('#!/bin/sh\n'+body+'\n');f.chmod(0o755)
    target=folder/'drapemind';(target/'releases/first').mkdir(parents=True)
    (target/'current').symlink_to(target/'releases/first')
    env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],DRAPEMIND_WEB_ROOT=str(target),FAKE_NPM_EXIT='7')
    result=subprocess.run(['bash',str(project/'install.sh'),'--build'],env=env,capture_output=True)
    assert result.returncode==7
    assert (target/'current').resolve()==target/'releases/first'
    env['FAKE_NPM_EXIT']='0'
    subprocess.run(['bash',str(project/'install.sh'),'--build'],env=env,check=True,capture_output=True)
    assert (target/'current/index.html').read_text()=='release-two'
    assert (target/'previous').resolve()==target/'releases/first'
    assert json.loads((target/'current/config.json').read_text())['apiPrefix']=='/DrapeMind/api/v1'
    print('PASS: build fallido conserva web; publicación válida cambia symlink y conserva versión anterior',flush=True)


def database_smoke():
    app=ROOT.parent
    config=deployment.load_config(app)
    deployment.prepare_env(app,config)
    suffix=str(int(time.time()))
    db='drapemind_check_'+suffix
    owner='drapemind_check_owner_'+suffix
    runtime='drapemind_check_runtime_'+suffix
    password=secrets.token_urlsafe(30)
    from sqlalchemy.engine import URL
    admin_url=URL.create('postgresql+psycopg',username=owner,password=password,host='127.0.0.1',port=5432,database=db)
    runtime_url=admin_url.set(username=runtime,password=secrets.token_urlsafe(30))
    deployment.update_env(ROOT/'.env',dict(DATABASE_URL=admin_url.render_as_string(hide_password=False),RUNTIME_DATABASE_URL=runtime_url.render_as_string(hide_password=False)))
    log=app/'smoke-private.log'
    with log.open('w') as output:
        log.chmod(0o600)
        try:
            deployment.provision_database()
            for command in ([sys.executable,'-m','scripts.saas_setup','backup'],[sys.executable,'-m','alembic','upgrade','head']):
                subprocess.run(command,cwd=ROOT,check=True,stdout=output,stderr=subprocess.STDOUT)
            deployment.grant_runtime();deployment.ensure_admin(app)
            from sqlalchemy import create_engine,text
            with create_engine(runtime_url).connect() as connection:
                assert connection.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()==(False,False)
                assert connection.scalar(text('SELECT COUNT(*) FROM pg_tables WHERE schemaname=\'public\''))>30
            command='''from fastapi.testclient import TestClient
from app.main import app
import json
from pathlib import Path
credentials=json.loads((Path.cwd().parent/'.deploy/admin-access.json').read_text())
with TestClient(app) as client:
 assert client.get('/health/ready').status_code==200
 result=client.post('/api/v1/saas/platform/login',json=credentials)
 assert result.status_code==200, result.status_code
print('API health and initial platform login passed')
'''
            subprocess.run([sys.executable,'-c',command],cwd=ROOT,check=True,stdout=output,stderr=subprocess.STDOUT)
            print('PASS: PostgreSQL vacío, migraciones completas, runtime sin bypass, salud API y login de administrador',flush=True)
        finally:
            assert re.fullmatch(r'drapemind_check_\d+',db)
            assert all(re.fullmatch(r'drapemind_check_(owner|runtime)_\d+',role) for role in (owner,runtime))
            # Solo los nombres temporales generados por esta ejecución.
            deployment.psql(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);',admin_url)
            for role in (runtime,owner):
                deployment.psql(f'DROP ROLE IF EXISTS "{role}";',admin_url)


if __name__=='__main__':
    assert sys.platform=='linux' and os.geteuid()==0
    assert str(ROOT).startswith('/tmp/drapemind-installer-check-') and ROOT.parent.name=='DrapeMind'
    os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory(prefix='drapemind-smoke-') as temporary:
            folder=Path(temporary);folder.chmod(0o755)
            nginx_smoke(folder)
            publication_smoke(folder)
        database_smoke()
    except Exception as exc:
        print('FAIL:',type(exc).__name__,'; detalles privados en',ROOT.parent/'smoke-private.log',flush=True)
        raise SystemExit(1)
