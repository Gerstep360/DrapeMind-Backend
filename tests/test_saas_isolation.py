from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, update, delete, event, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, CITEXT, ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError
from app.db.base import Base
from app.db.tenant_session import TenantSession
from app.core.tenancy import system_scope, tenant_scope
from app.models import User, Role, UserStatus, Product, Category, City, Branch
from app.models.saas import Tenant, SaaSPlan, TenantSubscription
from app.services.saas import require_active_subscription, validate_downgrade
from app.services.realtime import EventHub

@compiles(BigInteger,'sqlite')
def bigint(type_, compiler, **kw): return 'INTEGER'
@compiles(JSONB,'sqlite')
def jsonb(type_,compiler,**kw): return 'JSON'
@compiles(CITEXT,'sqlite')
def citext(type_,compiler,**kw): return 'TEXT'
@compiles(ARRAY,'sqlite')
def array(type_,compiler,**kw): return 'JSON'


@pytest.fixture
def factory():
    engine = create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def foreign_keys(connection,record): connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine,class_=TenantSession,expire_on_commit=False,autoflush=False)
    now = datetime.now(timezone.utc)
    with make() as db, system_scope(db):
        db.add_all([Tenant(id=1,name='A',slug='a'),Tenant(id=2,name='B',slug='b'),SaaSPlan(id=1,code='BASIC',name='Básico',max_branches=2,ai_reports=False),SaaSPlan(id=2,code='PRO',name='Profesional',max_branches=10,ai_reports=True)])
        db.flush()
        db.add_all([TenantSubscription(tenant_id=i,plan_id=i,status='ACTIVE',source='ADMINISTRATIVE',starts_at=now,ends_at=now+timedelta(days=30)) for i in (1,2)])
        for i in (1,2):
            db.add_all([User(id=i,tenant_id=i,is_platform_admin=False,nombre=f'Admin {i}',email='same@example.com',password_hash='test',rol=Role.ADMIN,estado=UserStatus.ACTIVO),Category(id=i,tenant_id=i,nombre='Camisas',slug='camisas'),City(id=i,tenant_id=i,nombre='La Paz',departamento='La Paz')])
        db.flush()
        for i in (1,2):
            db.add(Product(id=i,tenant_id=i,categoria_id=i,nombre=f'Prenda {i}',precio=Decimal('100'),imagenes=[],activo=True))
            db.add(Branch(id=i,tenant_id=i,ciudad_id=i,nombre='Centro',codigo='CENTRO',direccion='Principal',activo=True))
        db.commit()
    yield make
    engine.dispose()


def test_reads_joins_and_identity_map_cannot_cross_companies(factory):
    with factory(tenant_id=1) as db:
        assert db.get(Product,2) is None
        assert [p.id for p in db.scalars(select(Product))] == [1]
        assert [p.id for p,c in db.execute(select(Product,Category).join(Category))] == [1]
        with system_scope(db): assert db.get(Product,2).id == 2
        assert db.get(Product,2) is None


def test_bulk_update_delete_and_foreign_key_ownership(factory):
    with factory(tenant_id=1) as db:
        with pytest.raises(HTTPException): db.execute(update(Category).where(Category.id==1).values(tenant_id=2))
        assert db.execute(update(Product).where(Product.id==2).values(nombre='Hacked')).rowcount == 0
        assert db.execute(delete(Product).where(Product.id==2)).rowcount == 0
        db.add(Product(tenant_id=1,categoria_id=2,nombre='Cross',precio=10,imagenes=[]))
        with pytest.raises(HTTPException) as error: db.flush()
        assert error.value.status_code == 404
        db.rollback()
        with pytest.raises(IntegrityError): db.execute(update(Product).where(Product.id==1).values(categoria_id=2))
        db.rollback()


def test_missing_context_fails_closed_and_writes_get_company_automatically(factory):
    with tenant_scope(None), factory() as db:
        assert list(db.scalars(select(Product))) == []
        db.add(Category(nombre='Sin dueño',slug='none'))
        with pytest.raises(HTTPException): db.flush()
    with factory(tenant_id=2) as db:
        category=Category(nombre='Nueva',slug='new');db.add(category);db.commit()
        assert category.tenant_id == 2


def test_basic_blocks_third_branch_and_ai_reports(factory):
    with factory(tenant_id=1) as db:
        db.add(Branch(ciudad_id=1,nombre='Norte',codigo='NORTE',direccion='Norte',activo=True));db.commit()
        db.add(Branch(ciudad_id=1,nombre='Tercera',codigo='TRES',direccion='Tercera',activo=True))
        with pytest.raises(HTTPException) as error: db.commit()
        assert error.value.status_code == 409
        db.rollback()
        with pytest.raises(HTTPException) as error: require_active_subscription(db,1,'ai_reports')
        assert error.value.status_code == 403


def test_pro_allows_ten_but_blocks_eleven_and_invalid_downgrade(factory):
    with factory(tenant_id=2) as db:
        for n in range(2,11): db.add(Branch(ciudad_id=2,nombre=f'Sucursal {n}',codigo=f'S{n}',direccion='Real',activo=True))
        db.commit()
        assert require_active_subscription(db,2,'ai_reports').code == 'PRO'
        with pytest.raises(HTTPException): validate_downgrade(db,2,db.get(SaaSPlan,1))
        db.add(Branch(ciudad_id=2,nombre='Once',codigo='S11',direccion='Real',activo=True))
        with pytest.raises(HTTPException): db.commit()


def test_expired_subscription_does_not_grant_access(factory):
    with factory(tenant_id=1) as db:
        subscription=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
        subscription.ends_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        with pytest.raises(HTTPException) as error: require_active_subscription(db,1)
        assert error.value.status_code == 402


@pytest.mark.asyncio
async def test_websocket_broadcast_does_not_cross_companies():
    hub=EventHub();a=AsyncMock();b=AsyncMock()
    await hub.connect(a,1,'ADMIN',tenant_id=1);await hub.connect(b,2,'ADMIN',tenant_id=2)
    with tenant_scope(1): await hub.publish({'type':'inventory_updated'},roles={'ADMIN'})
    a.send_json.assert_awaited_once();b.send_json.assert_not_awaited()


@pytest.fixture
def client(factory,monkeypatch):
    from app.main import app
    from app.db import session
    from starlette.testclient import TestClient
    monkeypatch.setattr(session,'SessionLocal',factory)
    import app.main as main_module
    monkeypatch.setattr(main_module,'engine',factory.kw['bind'])
    from app.core.security import hash_password
    with factory() as db,system_scope(db):
        db.add(User(id=3,tenant_id=None,is_platform_admin=True,nombre='Plataforma',email='platform@example.com',password_hash=hash_password('Test-platform-123!'),rol=Role.ADMIN,estado=UserStatus.ACTIVO));db.commit()
    with TestClient(app) as http: yield http


def headers(user_id=1,tenant_id=1,slug='a'):
    from app.core.security import create_access_token
    token,_=create_access_token(user_id,'ADMIN',tenant_id=tenant_id)
    return {'Authorization':'Bearer '+token,'X-Tenant':slug}


def test_http_rejects_tenant_header_override_and_cross_company_resources(client):
    assert client.get('/api/v1/catalog/products/2',headers=headers()).status_code==404
    assert client.delete('/api/v1/admin/products/2',headers=headers()).status_code==404
    assert client.get('/api/v1/catalog/products',headers=headers(slug='b')).status_code==403
    assert client.get('/api/v1/catalog/products',headers=headers(user_id=1,tenant_id=2,slug='b')).status_code==401


def test_http_plan_gate_and_expired_billing_recovery(client,factory):
    assert client.post('/api/v1/ai/reports/generate',headers=headers(),json={}).status_code==403
    assert client.get('/api/v1/saas/tenants',headers=headers()).status_code==403
    with factory(tenant_id=1) as db:
        subscription=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
        subscription.ends_at=datetime.now(timezone.utc)-timedelta(days=1);db.commit()
    assert client.get('/api/v1/catalog/products',headers=headers()).status_code==402
    assert client.get('/api/v1/saas/me',headers=headers()).status_code==200


def test_platform_session_has_no_store_scope_and_lists_independent_companies(client):
    from app.core.security import decode_access_token
    response=client.post('/api/v1/saas/platform/login',headers={'X-Tenant':'a'},json={'email':'platform@example.com','password':'Test-platform-123!'})
    assert response.status_code==200,response.text
    claims=decode_access_token(response.json()['access_token'])
    assert claims['tid'] is None and claims['platform']
    auth={'Authorization':'Bearer '+response.json()['access_token']}
    assert len(client.get('/api/v1/saas/tenants',headers=auth).json())==2
    assert client.get('/api/v1/catalog/products',headers=auth).status_code==403


def test_platform_creates_company_and_controls_license_lifecycle(client,factory):
    from app.core.security import create_access_token
    token,_=create_access_token(3,'ADMIN',platform=True)
    root={'Authorization':'Bearer '+token}
    data={'name':'Nueva empresa','slug':'nueva-empresa','admin_name':'Admin Nueva','admin_email':'same@example.com','admin_password':'Nueva-empresa-123!','plan_id':1}
    created=client.post('/api/v1/saas/tenants',headers=root,json=data)
    assert created.status_code==201,created.text
    company=created.json();assert company['access_active'] is False and company['subscription']['status']=='PENDING'
    login=client.post('/api/v1/auth/login',headers={'X-Tenant':data['slug']},json={'email':data['admin_email'],'password':data['admin_password']})
    assert login.status_code==200
    auth={'Authorization':'Bearer '+login.json()['access_token'],'X-Tenant':data['slug']}
    assert client.get('/api/v1/catalog/products',headers=auth).status_code==402
    now=datetime.now(timezone.utc)
    license={'plan_id':2,'status':'ACTIVE','starts_at':(now-timedelta(minutes=1)).isoformat(),'ends_at':(now+timedelta(days=30)).isoformat()}
    activated=client.put(f"/api/v1/saas/tenants/{company['tenant']['id']}/subscription",headers=root,json=license)
    assert activated.status_code==200 and activated.json()['access_active']
    assert client.get('/api/v1/catalog/products',headers=auth).status_code==200
    assert client.post('/api/v1/ai/reports/generate',headers=auth,json={'periodo':'INVALID'}).status_code==422 # Passed the Professional gate; invalid enum prevents an AI request.
    license['status']='SUSPENDED'
    assert client.put(f"/api/v1/saas/tenants/{company['tenant']['id']}/subscription",headers=root,json=license).status_code==200
    assert client.get('/api/v1/catalog/products',headers=auth).status_code==402
    assert client.get('/api/v1/saas/me',headers=auth).status_code==200
