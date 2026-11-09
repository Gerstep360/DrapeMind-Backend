from sqlalchemy import select
from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from app.core.tenancy import system_scope
from app.models import UserDevice
from types import SimpleNamespace


def test_device_registration_is_automatic_but_requires_verified_identity(client, factory, stocked):
    payload={'token':'fixture-fcm-not-a-real-device-token','dispositivo_id':'test-device-identity','plataforma':'android'}
    assert client.post('/api/v1/devices/register',headers={'X-Tenant':'a'},json=payload).status_code==401
    response=client.post('/api/v1/devices/register',headers=headers(stocked[0]),json={**payload,'usuario_id':2,'email':'another@example.com'})
    assert response.status_code==200,response.text
    with factory() as db,system_scope(db):
        devices=db.scalars(select(UserDevice).where(UserDevice.token==payload['token'],UserDevice.activo.is_(True))).all()
        assert [(r.usuario_id,r.tenant_id) for r in devices]==[(stocked[0],1)]
    assert client.post('/api/v1/devices/unregister',headers={'X-Tenant':'a'},json={'token':payload['token']}).status_code==401


def test_store_notice_schema_preserves_target_and_company(client,factory,stocked,monkeypatch):
    calls=[]
    async def fake_dispatch(db,user_id,*args,**kwargs):
        calls.append(user_id)
        return SimpleNamespace(id=17)
    monkeypatch.setattr('app.api.v1.endpoints.notifications.dispatch_notification',fake_dispatch)
    body={'usuario_id':stocked[0],'titulo':'Tu pedido','mensaje':'Ya puedes recogerlo','screen':'/orders'}
    response=client.post('/api/v1/notifications/send',headers=headers(),json=body)
    assert response.status_code==201,response.text
    assert calls==[stocked[0]]
    assert client.post('/api/v1/notifications/send',headers=headers(),json={**body,'usuario_id':2}).status_code==404
    assert client.post('/api/v1/notifications/send',headers=headers(),json={**body,'tenant_id':2}).status_code==422
    assert len(calls)==1
