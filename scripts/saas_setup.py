"""Local SaaS maintenance. Never logs secrets or connection strings."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.core.config import settings, BACKEND_DIR


def update_env(key, value):
    target = BACKEND_DIR / '.env'
    lines = target.read_text(encoding='utf-8').splitlines() if target.exists() else []
    lines = [line for line in lines if not line.startswith(key+'=')]
    lines.append(key+'='+json.dumps(value))
    target.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def backup():
    url = make_url(settings.database_uri)
    executable = shutil.which('pg_dump')
    if not executable:
        candidates = sorted(Path('C:/Program Files/PostgreSQL').glob('*/bin/pg_dump.exe'), reverse=True)
        executable = str(candidates[0]) if candidates else None
    if not executable: raise RuntimeError('Instala pg_dump antes de migrar')
    folder = BACKEND_DIR / 'backups'; folder.mkdir(exist_ok=True)
    target = folder / ('pre_saas_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.dump')
    env = dict(os.environ, PGPASSWORD=url.password or '')
    result = subprocess.run([executable,'-h',url.host or 'localhost','-p',str(url.port or 5432),'-U',url.username or 'postgres','-d',url.database,'-Fc','-f',str(target)],env=env,capture_output=True)
    if result.returncode: raise RuntimeError('No se pudo crear el respaldo PostgreSQL')
    print('Respaldo PostgreSQL creado en backend/backups/'+target.name)


def runtime_role():
    """Admin URL is kept for Alembic; HTTP uses a separate non-owner, non-bypass login."""
    url = make_url(settings.database_uri)
    engine = create_engine(url, echo=False)
    runtime = make_url(settings.RUNTIME_DATABASE_URL) if settings.RUNTIME_DATABASE_URL else None
    role = 'drapemind_runtime'
    password = runtime.password if runtime and runtime.username == role else secrets.token_urlsafe(36)
    with engine.begin() as conn:
        exists = conn.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:name'),{'name':role})
        # Identifiers and password are generated here, never supplied by a client.
        statement = ('ALTER' if exists else 'CREATE')+' ROLE drapemind_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '+"'"+password.replace("'","''")+"'"
        conn.exec_driver_sql(statement)
        database = conn.dialect.identifier_preparer.quote_identifier(url.database)
        conn.exec_driver_sql(f'GRANT CONNECT ON DATABASE {database} TO drapemind_runtime')
        conn.exec_driver_sql('GRANT USAGE ON SCHEMA public TO drapemind_runtime')
        conn.exec_driver_sql('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO drapemind_runtime')
        conn.exec_driver_sql('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO drapemind_runtime')
        conn.exec_driver_sql('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO drapemind_runtime')
        conn.exec_driver_sql('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO drapemind_runtime')
    update_env('RUNTIME_DATABASE_URL',url.set(username=role,password=password).render_as_string(hide_password=False))
    if not runtime: update_env('SECRET_KEY',secrets.token_urlsafe(48))
    print('Conexión de ejecución restringida configurada; Alembic conserva su conexión administrativa.')


def demo():
    if settings.ENVIRONMENT == 'production': raise RuntimeError('Las demostraciones solo se generan en local o pruebas')
    from app.models import User, Role, UserStatus, City, Branch, Category, Product, ProductVariant, BranchStock
    from app.models.saas import Tenant, SaaSPlan, TenantSubscription
    from app.core.security import hash_password
    from app.db.tenant_session import TenantSession
    from app.core.tenancy import system_scope
    engine = create_engine(settings.database_uri,echo=False)
    factory = sessionmaker(bind=engine,class_=TenantSession,expire_on_commit=False)
    credentials_path=BACKEND_DIR/'.saas-demo-credentials.json'
    credentials=json.loads(credentials_path.read_text(encoding='utf-8')) if credentials_path.exists() else {'platform':{},'companies':[]}
    with factory() as db, system_scope(db):
        root=db.scalar(select(User).where(User.is_platform_admin.is_(True),User.tenant_id.is_(None)))
        if not root:
            password=secrets.token_urlsafe(18)
            root=User(tenant_id=None,is_platform_admin=True,nombre='Administrador SaaS',email='saas-admin@example.com',password_hash=hash_password(password),rol=Role.ADMIN,estado=UserStatus.ACTIVO)
            db.add(root);db.flush()
            credentials['platform']={'email':root.email,'password':password,'url':'http://localhost:4200/saas-platform'}
        for slug,name,code,amount in [('moda-oriente','Moda Oriente (demo)','BASIC','80.00'),('urban-fit','Urban Fit (demo)','PRO','150.00')]:
            tenant=db.scalar(select(Tenant).where(Tenant.slug==slug))
            if tenant: continue
            tenant=Tenant(name=name,slug=slug,is_demo=True);db.add(tenant);db.flush()
            password=secrets.token_urlsafe(18)
            owner=User(tenant_id=tenant.id,is_platform_admin=False,nombre='Administrador '+name,email='admin@example.com',password_hash=hash_password(password),rol=Role.ADMIN,estado=UserStatus.ACTIVO)
            db.add(owner);db.flush();tenant.admin_user_id=owner.id
            plan=db.scalar(select(SaaSPlan).where(SaaSPlan.code==code))
            db.add(TenantSubscription(tenant_id=tenant.id,plan_id=plan.id,status='ACTIVE',starts_at=datetime.now(timezone.utc)-timedelta(minutes=1),ends_at=datetime.now(timezone.utc)+timedelta(days=365),source='ADMINISTRATIVE'))
            db.flush()
            city=City(tenant_id=tenant.id,nombre='Santa Cruz' if code=='PRO' else 'La Paz',departamento='Santa Cruz' if code=='PRO' else 'La Paz')
            category=Category(tenant_id=tenant.id,nombre='Camisetas',slug='camisetas')
            db.add_all([city,category]);db.flush()
            branches=[]
            for index in range(2 if code=='BASIC' else 3):
                branch=Branch(tenant_id=tenant.id,ciudad_id=city.id,codigo=f'SEDE-{index+1}',nombre=f'{name} · Sede {index+1}',direccion='Dirección de demostración',activo=True)
                db.add(branch);db.flush();branches.append(branch)
            product=Product(tenant_id=tenant.id,categoria_id=category.id,nombre='Camiseta de algodón (demo '+name+')',descripcion='Prenda de demostración de aislamiento empresarial',precio=Decimal(amount),imagenes=[],tags_ai=['demo'])
            db.add(product);db.flush()
            variant=ProductVariant(tenant_id=tenant.id,producto_id=product.id,sku='DEMO-CAMISETA-M',color='Negro',talla='M',stock_total=10*len(branches))
            db.add(variant);db.flush()
            for branch in branches: db.add(BranchStock(tenant_id=tenant.id,sucursal_id=branch.id,variante_id=variant.id,stock_total=10))
            db.flush()
            credentials['companies'].append({'company':slug,'email':owner.email,'password':password,'plan':code})
        db.commit()
    credentials_path.write_text(json.dumps(credentials,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Empresas demo y administrador disponibles. Credenciales locales: backend/.saas-demo-credentials.json (no se publican).')


def prices():
    from app.db.session import SessionLocal
    from app.models.saas import SaaSPlan
    from app.services.saas_billing import configure_plan_price
    if not settings.STRIPE_SECRET_KEY:
        print('Stripe pendiente: configura STRIPE_SECRET_KEY para publicar los precios.');return
    with SessionLocal() as db:
        for plan in db.scalars(select(SaaSPlan).order_by(SaaSPlan.id)):
            for interval in ('month','year'):
                configure_plan_price(db,plan,interval)
    print('Precios mensuales y anuales publicados en Stripe. No se cobró a ningún cliente.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','runtime-role','demo','stripe-prices'])
    args=parser.parse_args()
    try: {'backup':backup,'runtime-role':runtime_role,'demo':demo,'stripe-prices':prices}[args.action]()
    except Exception as exc:
        # Driver/provider exceptions may contain secrets: report only the exception class.
        print('No se completó la operación SaaS ('+type(exc).__name__+'). Revisa la configuración local.')
        raise SystemExit(1)

if __name__=='__main__': main()
