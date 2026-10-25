"""Acceso unificado con middleware SaaS real: identidad y permisos del servidor."""
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.core.security import decode_access_token,hash_password
from app.core.tenancy import system_scope
from app.models import User,UserStatus,Role,UserStyleProfile
from app.models.saas import Tenant,TenantSubscription
from test_saas_isolation import factory,client,headers


@pytest.fixture
def accounts(factory):
    with factory() as db,system_scope(db):
        a=db.get(User,1);a.email='owner-a@example.com';a.password_hash=hash_password('Owner-A-12345!')
        b=db.get(User,2);b.email='owner-b@example.com';b.password_hash=hash_password('Owner-B-12345!')
        db.commit()


def login(client,email,password,**body):
    return client.post('/api/v1/auth/login',json=dict(email=email,password=password,**body))


def test_email_discovers_company_and_returns_only_safe_profile(client,accounts):
    response=login(client,'OWNER-B@example.com','Owner-B-12345!')
    assert response.status_code==200,response.text
    body=response.json();claims=decode_access_token(body['access_token'])
    assert claims['tid']==2 and claims['platform'] is False
    assert body['tenant']==dict(id=2,slug='b',name='B')
    assert body['user']['tenant_slug']=='b' and 'password_hash' not in body['user']
    assert body['redirect_path']=='/dashboard'
    assert client.get('/api/v1/catalog/products/1',headers={'Authorization':'Bearer '+body['access_token']}).status_code==404


def test_platform_uses_same_login_without_privilege_selector(client):
    response=login(client,'platform@example.com','Test-platform-123!')
    assert response.status_code==200,response.text
    body=response.json();claims=decode_access_token(body['access_token'])
    assert claims['platform'] is True and claims['tid'] is None
    assert body['redirect_path']=='/saas-platform' and body['tenant'] is None
    assert body['user']['is_platform_admin'] is True


def test_saved_headers_never_choose_the_login_account(client,accounts):
    response=client.post('/api/v1/auth/login',headers={'X-Tenant':'stale-store','Authorization':'Bearer expired-token'},json={'email':'owner-a@example.com','password':'Owner-A-12345!'})
    assert response.status_code==200 and response.json()['tenant']['id']==1


@pytest.mark.parametrize('injected',[{'is_platform_admin':True},{'platform':True},{'rol':'ADMIN'},{'tenant_id':1}])
def test_login_rejects_client_supplied_privileges(client,accounts,injected):
    assert login(client,'owner-b@example.com','Owner-B-12345!',**injected).status_code==422


def test_same_email_different_password_resolves_without_asking_company(client,accounts,factory):
    with factory() as db,system_scope(db):
        db.get(User,2).email='owner-a@example.com';db.commit()
    response=login(client,'owner-a@example.com','Owner-B-12345!')
    assert response.status_code==200 and response.json()['tenant']['id']==2


def test_ambiguous_credentials_use_store_link_without_disclosing_companies(client,accounts,factory):
    with factory() as db,system_scope(db):
        b=db.get(User,2);b.email='owner-a@example.com';b.password_hash=hash_password('Owner-A-12345!');db.commit()
    response=login(client,'owner-a@example.com','Owner-A-12345!')
    assert response.status_code==409
    assert response.json()['detail']['code']=='STORE_LINK_REQUIRED'
    assert 'companies' not in response.json()['detail']
    assert 'access_token' not in response.json()
    response=login(client,'owner-a@example.com','Owner-A-12345!',tenant_slug='b')
    assert response.status_code==200 and response.json()['tenant']['id']==2


def test_wrong_store_link_never_authenticates_another_company(client,accounts):
    assert login(client,'owner-a@example.com','Owner-A-12345!',tenant_slug='b').status_code==401


def test_blocked_account_and_inactive_company_are_rejected(client,accounts,factory):
    with factory() as db,system_scope(db):
        db.get(User,1).estado=UserStatus.BLOQUEADO;db.get(Tenant,2).active=False;db.commit()
    assert login(client,'owner-a@example.com','Owner-A-12345!').status_code==403
    assert login(client,'owner-b@example.com','Owner-B-12345!').status_code==403


def test_expired_company_signs_in_to_billing_only(client,accounts,factory):
    with factory() as db,system_scope(db):
        subscription=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
        subscription.ends_at=datetime.now(timezone.utc)-timedelta(days=1);db.commit()
    response=login(client,'owner-a@example.com','Owner-A-12345!')
    assert response.status_code==200 and response.json()['redirect_path']=='/subscription'
    assert client.get('/api/v1/catalog/products',headers={'Authorization':'Bearer '+response.json()['access_token']}).status_code==402


def test_customer_and_cashier_destinations_come_from_saved_role(client,accounts,factory):
    with factory() as db,system_scope(db):
        db.get(User,1).rol=Role.CAJERO;db.get(User,2).rol=Role.CLIENTE;db.commit()
    assert login(client,'owner-a@example.com','Owner-A-12345!').json()['redirect_path']=='/pos'
    assert login(client,'owner-b@example.com','Owner-B-12345!').json()['redirect_path']=='/onboarding'
    with factory(tenant_id=2) as db:
        db.add(UserStyleProfile(usuario_id=2));db.commit()
    assert login(client,'owner-b@example.com','Owner-B-12345!').json()['redirect_path']=='/catalog'


def test_unknown_email_and_wrong_password_share_error(client,accounts):
    a=login(client,'unknown@example.com','Owner-A-12345!')
    b=login(client,'owner-a@example.com','incorrect-password')
    assert a.status_code==b.status_code==401 and a.json()==b.json()


def test_company_entry_is_public_and_has_no_admin_or_billing_details(client):
    response=client.get('/api/v1/saas/companies/a')
    assert response.status_code==200
    assert response.json()==dict(slug='a',name='A',login_path='/tienda/a')
