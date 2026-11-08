from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from test_saas_isolation import factory, client, headers
from app.models import User, Role, UserDevice, Notification
from app.models.saas import CustomerAccount
from app.models.access import UserAccess, TenantRole
from app.core.tenancy import system_scope
from app.services.device_memberships import register, unregister


@pytest.fixture
def staff(factory):
    with factory(tenant_id=1) as db:
        row = User(nombre='Caja',email='staff@example.com',password_hash='fixture',rol=Role.CAJERO)
        db.add(row);db.commit();return row.id


def test_admin_creates_reusable_role_and_denies_are_enforced_with_existing_jwt(client, factory, staff):
    payload={'nombre':'Caja sin catálogo','base_role':'CAJERO','permisos':['offline.use','sales.manage']}
    response=client.post('/api/v1/team/roles',headers=headers(),json=payload)
    assert response.status_code==201,response.text
    rid=response.json()['id']
    assert client.put(f'/api/v1/team/users/{staff}/access',headers=headers(),json={'rol_empresa_id':rid}).status_code==200
    assert client.get('/api/v1/team/me',headers=headers(staff)).json()['permissions']==['offline.use','sales.manage']
    assert client.get('/api/v1/admin/products',headers=headers(staff)).status_code==403
    assert client.get('/api/v1/team/roles',headers=headers(staff)).status_code==403
    assert client.put(f'/api/v1/team/users/{staff}/access',headers=headers(),json={'permisos':{'catalog.manage':True,'sales.manage':False}}).status_code==200
    assert client.get('/api/v1/admin/products',headers=headers(staff)).status_code==200
    assert client.post('/api/v1/admin/sales/pos',headers=headers(staff),json={}).status_code==403
    assert client.put(f'/api/v1/team/users/{staff}/access',headers=headers(),json={'permisos':{'orders.manage':False,'reservations.manage':False}}).status_code==200
    assert client.get('/api/v1/orders',headers=headers(staff)).status_code==403
    assert client.get('/api/v1/reservations',headers=headers(staff)).status_code==403
    assert client.put(f'/api/v1/team/users/{staff}/access',headers=headers(),json={'permisos':{'catalog.manage':True,'sales.manage':False}}).status_code==200
    # A catalog grant never grants branch administration.
    assert client.post('/api/v1/branches',headers=headers(staff),json={}).status_code==403
    # Main user DTO exposes the same capabilities, refreshed from DB.
    assert 'sales.manage' not in client.get('/api/v1/auth/me',headers=headers(staff)).json()['permisos']


def test_profiles_are_tenant_private_and_cannot_escalate_customer_or_remove_admin(client, factory, staff):
    check=client.get('/api/v1/team/roles',headers=headers(2,2,'b'))
    assert check.status_code==200,check.text
    row=client.post('/api/v1/team/roles',headers=headers(),json={'nombre':'Stock','base_role':'ENCARGADO','permisos':['inventory.manage']}).json()
    response=client.put(f"/api/v1/team/roles/{row['id']}",headers=headers(2,2,'b'),json={'nombre':'Hack','base_role':'ENCARGADO','permisos':[]})
    assert response.status_code==404,response.text
    assert client.put('/api/v1/team/users/1/access',headers=headers(),json={'permisos':{}}).status_code==409
    assert client.put('/api/v1/team/users/2/access',headers=headers(),json={'permisos':{}}).status_code==404
    assert client.post('/api/v1/team/roles',headers=headers(),json={'nombre':'Escalada','base_role':'CAJERO','permisos':['team.manage']}).status_code==422
    with factory(tenant_id=1) as db:
        identity=CustomerAccount(name='Cliente',email='universal@example.com',password_hash='fixture');db.add(identity);db.flush()
        customer=User(nombre='Cliente',email=identity.email,password_hash='fixture',rol=Role.CLIENTE,customer_account_id=identity.id);db.add(customer);db.commit();uid=customer.id
    assert client.put(f'/api/v1/team/users/{uid}/access',headers=headers(),json={'rol_empresa_id':row['id']}).status_code==409
    assert client.get('/api/v1/team/roles',headers=headers(2,2,'b')).json()==[]


def test_inactive_role_revokes_overrides_and_legacy_role_change_resets_profile(client, factory, staff):
    role=client.post('/api/v1/team/roles',headers=headers(),json={'nombre':'Colección','base_role':'VENDEDOR','permisos':['catalog.manage']}).json()
    assert client.put(f'/api/v1/team/users/{staff}/access',headers=headers(),json={'rol_empresa_id':role['id'],'permisos':{'inventory.manage':True}}).status_code==200
    assert client.put(f"/api/v1/team/roles/{role['id']}",headers=headers(),json={**{k:v for k,v in role.items() if k!='id'},'activo':False}).status_code==200
    assert client.get('/api/v1/team/me',headers=headers(staff)).json()['permissions']==[]
    assert client.patch(f'/api/v1/admin/users/{staff}',headers=headers(),json={'rol':'CAJERO'}).status_code==200
    assert 'sales.manage' in client.get('/api/v1/team/me',headers=headers(staff)).json()['permissions']


def test_device_same_identity_all_memberships_and_logout(factory):
    with factory() as db, system_scope(db):
        account=CustomerAccount(name='Cliente',email='push@example.com',password_hash='fixture');db.add(account);db.flush()
        owners=[]
        for tid in (1,2):
            user=User(tenant_id=tid,nombre='Cliente',email=account.email,password_hash='fixture',rol=Role.CLIENTE,customer_account_id=account.id);db.add(user);owners.append(user)
        db.commit();ids=[x.id for x in owners]
    payload=SimpleNamespace(token='a-real-provider-token',dispositivo_id='phone-unique',plataforma='android',modelo='Test')
    with factory(tenant_id=1) as db:
        assert register(db,db.get(User,ids[0]),payload)==2
        assert len(list(db.scalars(select(UserDevice))))==1
    with factory(tenant_id=2) as db:
        assert db.scalar(select(UserDevice)).usuario_id==ids[1]
        unregister(db,db.get(User,ids[1]),payload.token)
    with factory() as db, system_scope(db):
        assert all(not row.activo for row in db.scalars(select(UserDevice)))
    with factory(tenant_id=1) as db:
        register(db,db.get(User,1),payload)
    with factory() as db, system_scope(db):
        active=list(db.scalars(select(UserDevice).where(UserDevice.activo.is_(True))))
        assert [x.usuario_id for x in active]==[1]


@pytest.mark.asyncio
async def test_push_origin_is_server_owned_and_foreign_recipient_rejected(factory, monkeypatch):
    import app.services.push_notifications as push
    sender=AsyncMock(return_value={'sent':1,'failed':0,'invalid_tokens':[]});monkeypatch.setattr(push,'send_fcm_message',sender)
    monkeypatch.setattr(push.event_hub,'publish',AsyncMock())
    with factory(tenant_id=1) as db:
        db.add(UserDevice(usuario_id=1,token='real-provider-token',plataforma='android'));db.commit()
        notification=await push.dispatch_notification(db,1,'Pedido listo','Recógelo','PEDIDO',{'tenant_id':2,'tenant_slug':'b','tenant_name':'Otra'})
        assert notification.data_payload['tenant_id']==1
        assert sender.call_args.args[1]==notification.data_payload['tenant_name']+' · Pedido listo'
        assert sender.call_args.args[3]['tenant_slug']=='a'
        with pytest.raises(Exception) as error:await push.dispatch_notification(db,2,'No','No')
        assert error.value.status_code==404


def test_browser_subscription_rejects_ssrf(client):
    response=client.post('/api/v1/devices/web-register',headers=headers(),json={'dispositivo_id':'browser-001','subscription':{'endpoint':'https://127.0.0.1/private','keys':{}}})
    assert response.status_code==422
