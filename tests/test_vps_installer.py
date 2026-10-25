"""Pruebas herméticas del instalador; no acceden al VPS ni a PostgreSQL real."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from instalar_vps import validate_origin, validate_repo, validate_branch, clone_or_reuse, synchronize_bootstrap, validate_manager_bundle

spec = importlib.util.spec_from_file_location('platform_config', ROOT/'scripts/deploy/platform_config.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.fixture
def project(tmp_path, monkeypatch):
    app = tmp_path/'DrapeMind'
    backend = app/'backend'; backend.mkdir(parents=True)
    (app/'web').mkdir()
    monkeypatch.setattr(deploy,'BACKEND',backend)
    config = deploy.load_config(app)
    return app, backend, config


@pytest.mark.parametrize('value',['http://167.86.106.105','https://user:secret@example.com','https://example.com/path','https://example.com?x=y','https://example.com:8443'])
def test_public_origin_rejects_credentials_http_and_embedded_routes(value):
    with pytest.raises(ValueError):
        validate_origin(value)


def test_git_parameters_are_not_shell_fragments():
    assert validate_origin('https://167.86.106.105/') == 'https://167.86.106.105'
    assert validate_branch('feature/installer') == 'feature/installer'
    for value in ('--upload-pack=evil','Main;echo owned','../Main'):
        with pytest.raises(ValueError):
            validate_branch(value)
    with pytest.raises(ValueError):
        validate_repo('https://token:secret@github.com/org/project.git')


def test_config_rejects_checkout_escape(project):
    app,backend,config = project
    config['web_dir']='../another-app'
    (app/'deploy.json').write_text(json.dumps(config))
    with pytest.raises(ValueError):
        deploy.load_config(app)


def test_production_env_preserves_secrets_and_sets_same_origin(project):
    app,backend,config = project
    env=backend/'.env'
    deploy.update_env(env,dict(SECRET_KEY='existing-jwt-key-should-not-be-rotated-1234',
       PAYMENT_WEBHOOK_SECRET='existing-payment-key-do-not-change', NVIDIA_API_KEY='private-nvidia',
       STRIPE_SECRET_KEY='private-stripe', DATABASE_URL='postgresql+psycopg://owner:private@localhost/app',
       RUNTIME_DATABASE_URL='postgresql+psycopg://runtime:private@localhost/app'))
    before=deploy.read_env(env)
    deploy.prepare_env(app,config)
    after=deploy.read_env(env)
    for key,value in before.items():
        assert after[key]==value
    assert after['ROOT_PATH']=='/DrapeMind'
    assert after['SAAS_WEB_URL']=='https://167.86.106.105/DrapeMind'
    assert json.loads(after['CORS_ORIGINS'])==['https://167.86.106.105']
    assert after['ENVIRONMENT']=='production'


def test_fresh_env_generates_distinct_private_credentials(project, capsys):
    app,backend,config=project
    deploy.prepare_env(app,config)
    env=deploy.read_env(backend/'.env')
    assert len(env['SECRET_KEY'])>=32
    assert env['SECRET_KEY']!=env['PAYMENT_WEBHOOK_SECRET']
    assert env['POSTGRES_USER']=='drapemind_owner'
    assert env['POSTGRES_PASSWORD'] not in capsys.readouterr().out


def test_private_import_keeps_provider_keys_and_isolates_pc_database(project,capsys):
    app,backend,config=project
    private=app/'.private/env';private.mkdir(parents=True)
    raw='ENVIRONMENT="development"\nDATABASE_URL="postgresql+psycopg://pc:pc-secret@localhost/pc_db"\nNVIDIA_API_KEY="private-ai"\nNVIDIA_SECONDARY_KEY="private-ai-two"\nnvidia_api="legacy-private-alias"\nSTRIPE_SECRET_KEY="private-stripe"\nSTRIPE_LOCAL_WEBHOOK_SECRET="whsec_cli_only"\nSTRIPE_SAAS_WEBHOOK_SECRET="whsec_cli_only"\n'
    (private/'backend.env').write_text(raw)
    (private/'web.env').write_text('PRIVATE_WEB_VALUE="private-web"\n')
    deploy.prepare_env(app,config)
    result=deploy.read_env(backend/'.env')
    assert result['NVIDIA_API_KEY']=='private-ai'
    assert result['NVIDIA_SECONDARY_KEY']=='private-ai-two'
    assert result['STRIPE_SECRET_KEY']=='private-stripe'
    assert result['STRIPE_SAAS_WEBHOOK_SECRET']==''
    assert result['POSTGRES_USER']=='drapemind_owner'
    assert 'pc-secret' not in result['DATABASE_URL']
    assert 'nvidia_api="legacy-private-alias"' in (backend/'.env').read_text()
    assert (private/'backend.env').read_text()==raw
    assert (app/'web/.env').read_text()=='PRIVATE_WEB_VALUE="private-web"\n'
    output=capsys.readouterr().out
    assert all(value not in output for value in ('private-ai','private-stripe','private-web'))


def test_private_refresh_preserves_vps_database_and_session_secrets(project):
    app,backend,config=project
    deploy.prepare_env(app,config)
    before=deploy.read_env(backend/'.env')
    deploy.update_env(backend/'.env',dict(RUNTIME_DATABASE_URL='postgresql+psycopg://runtime:vps-password@127.0.0.1/drapemind_db'))
    private=app/'.private/env';private.mkdir(parents=True)
    (private/'backend.env').write_text('DATABASE_URL="postgresql+psycopg://pc:pc-password@localhost/pc"\nSECRET_KEY="pc-session-secret"\nNVIDIA_API_KEY="refreshed-key"\n')
    deploy.import_private_envs(app);deploy.prepare_env(app,config)
    after=deploy.read_env(backend/'.env')
    assert after['DATABASE_URL']==before['DATABASE_URL']
    assert after['SECRET_KEY']==before['SECRET_KEY']
    assert 'vps-password' in after['RUNTIME_DATABASE_URL']
    assert after['NVIDIA_API_KEY']=='refreshed-key'
    assert len(list((app/'.deploy/env-backups').glob('*/backend.env')))==1


def nginx_fixture(app):
    etc=app/'nginx'
    for folder in ('sites-enabled','sites-available','snippets','conf.d'):
        (etc/folder).mkdir(parents=True)
    target=etc/'sites-available/taji-web'
    original='''# server { ignored }
server {
 listen 80;
 listen 443 ssl;
 server_name 167.86.106.105;
 ssl_certificate /existing/fullchain.pem;
 location /taji/ { proxy_pass http://127.0.0.1:8000; }
 location / { return 200 "literal { braces }"; }
 include /etc/nginx/snippets/codelingo.conf;
}
server { listen 80; server_name another.example.com; location / { return 200; } }
'''
    target.write_text(original)
    (etc/'sites-enabled/taji-web').symlink_to(target)
    return etc,target,original


@pytest.mark.skipif(sys.platform=='win32', reason='symlinks de Nginx se verifican también en Linux')
def test_nginx_shared_site_preserves_other_applications_and_is_idempotent(project,monkeypatch):
    app,backend,config=project
    etc,target,original=nginx_fixture(app)
    calls=[]
    monkeypatch.setattr(deploy.subprocess,'run',lambda command,**kw:calls.append(command))
    deploy.configure_nginx(app,config,etc)
    first=target.read_text()
    assert '/taji/' in first and 'codelingo.conf' in first and '/existing/fullchain.pem' in first
    assert first.count('drapemind.locations.conf')==1
    assert original.split('server { listen 80;')[1] == first.split('server { listen 80;')[1]
    deploy.configure_nginx(app,config,etc)
    assert target.read_text()==first
    snippet=(etc/'snippets/drapemind.locations.conf').read_text()
    assert 'proxy_buffering off;' in snippet
    assert '$drapemind_connection_upgrade' in snippet
    assert 'http://127.0.0.1:8045/api/' in snippet
    assert '/DrapeMind/index.html' in snippet


@pytest.mark.skipif(sys.platform=='win32', reason='symlinks de Nginx se verifican también en Linux')
def test_nginx_failed_validation_restores_exact_files(project,monkeypatch):
    app,backend,config=project
    etc,target,original=nginx_fixture(app)
    count=0
    def run(command,**kwargs):
        nonlocal count
        count+=1
        if count==2:
            raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(deploy.subprocess,'run',run)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.configure_nginx(app,config,etc)
    assert target.read_text()==original
    assert not (etc/'snippets/drapemind.locations.conf').exists()
    assert not (etc/'conf.d/drapemind-websocket.conf').exists()
    assert (etc/'sites-enabled/taji-web').is_symlink()


def test_nginx_rejects_duplicate_old_routes_before_mutating(project,monkeypatch):
    app,backend,config=project
    etc=app/'nginx'
    (etc/'sites-enabled').mkdir(parents=True)
    target=etc/'sites-enabled/existing.conf'
    original='server { listen 80; server_name 167.86.106.105; location /DrapeMind/ { root /old; } }'
    target.write_text(original)
    monkeypatch.setattr(deploy.subprocess,'run',lambda *a,**kw:None)
    with pytest.raises(ValueError,match='antiguas'):
        deploy.configure_nginx(app,config,etc)
    assert target.read_text()==original
    assert not (etc/'snippets/drapemind.locations.conf').exists()


def test_existing_checkout_mismatch_never_overwrites(project,monkeypatch):
    app,backend,config=project
    (backend/'.git').mkdir()
    marker=backend/'important.txt'; marker.write_text('keep me')
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:'https://github.com/other/repo.git\n')
    with pytest.raises(ValueError,match='no coincide'):
        clone_or_reuse('https://github.com/Gerstep360/DrapeMind-Backend.git','Main',backend)
    assert marker.read_text()=='keep me'


@pytest.fixture
def published_repositories(tmp_path,monkeypatch):
    import instalar_vps
    # La regresión usa repositorios Git reales y remotos locales, sin SSH ni servicios.
    monkeypatch.setattr(instalar_vps.shutil,'which',lambda name:None)
    def git(repo,*args):
        return subprocess.run(['git','-c','user.name=Installer test','-c','user.email=installer@example.com','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
    paths={};producers={};before={}
    for component in ('backend','web'):
        remote=tmp_path/(component+'-remote.git')
        subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
        producer=tmp_path/(component+'-publisher');producer.mkdir()
        git(producer,'init','-b','Main')
        git(producer,'remote','add','origin',str(remote))
        (producer/'README.md').write_text('old version')
        git(producer,'add','.');git(producer,'commit','-m','old Main')
        git(producer,'push','origin','Main')
        consumer=tmp_path/'DrapeMind'/component
        consumer.parent.mkdir(exist_ok=True)
        subprocess.run(['git','clone','--branch','Main',str(remote),str(consumer)],check=True,capture_output=True)
        paths[component]=consumer;producers[component]=producer;before[component]=git(consumer,'rev-parse','HEAD')
        files=['scripts/deploy/platform.sh','scripts/deploy/platform_ui.sh','scripts/deploy/platform_config.py'] if component=='backend' else ['install.sh']
        for name in files:
            target=producer/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('# published installer\n')
        git(producer,'add','.');git(producer,'commit','-m','publish installer on Main');git(producer,'push','origin','Main')
    return paths,producers,before,git,dict(backend_branch='Main',web_branch='Main')


def test_missing_manager_recovers_already_published_main(published_repositories):
    paths,producers,before,git,config=published_repositories
    assert not (paths['backend']/'scripts/deploy/platform.sh').exists()
    synchronize_bootstrap(paths,config)
    validate_manager_bundle(paths)
    for component in paths:
        assert git(paths[component],'branch','--show-current')=='Main'
        assert git(paths[component],'rev-parse','HEAD')==git(producers[component],'rev-parse','HEAD')


def test_bootstrap_preserves_dirty_checkout_before_updating_either_repo(published_repositories):
    paths,producers,before,git,config=published_repositories
    (paths['web']/'README.md').write_text('local work to preserve')
    with pytest.raises(ValueError,match='cambios locales'):
        synchronize_bootstrap(paths,config)
    assert (paths['web']/'README.md').read_text()=='local work to preserve'
    assert all(git(paths[c],'rev-parse','HEAD')==before[c] for c in paths)


def test_bootstrap_preserves_local_commits_when_main_diverges(published_repositories):
    paths,producers,before,git,config=published_repositories
    (paths['web']/'local.txt').write_text('committed local work')
    git(paths['web'],'add','.');git(paths['web'],'commit','-m','keep local commit')
    local_head=git(paths['web'],'rev-parse','HEAD')
    with pytest.raises(ValueError,match='diverge'):
        synchronize_bootstrap(paths,config)
    assert git(paths['backend'],'rev-parse','HEAD')==before['backend']
    assert git(paths['web'],'rev-parse','HEAD')==local_head
