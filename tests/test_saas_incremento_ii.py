"""CU-11..14: real HTTP/DB transactions with two independent tenants."""
from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from test_saas_isolation import factory, client, headers
from app.core.tenancy import system_scope
from app.models import User, Role, UserStatus, ProductVariant, BranchStock, Reservation, InventoryMovement
from app.models.saas import SaaSPlan
from app.incrementos.incremento_ii.models import OfflineReservationReceipt, SupplyOrder


@pytest.fixture
def stock(factory):
    with factory() as db, system_scope(db):
        db.add_all([User(id=4, tenant_id=1, nombre='Cliente', email='client@example.com', password_hash='fixture', rol=Role.CLIENTE, estado=UserStatus.ACTIVO),
                    User(id=5, tenant_id=1, nombre='Encargado', email='manager@example.com', password_hash='fixture', rol=Role.ENCARGADO, estado=UserStatus.ACTIVO)])
        for i in (1, 2):
            db.add(ProductVariant(id=i, tenant_id=i, producto_id=i, sku='SKU', color='Negro', talla='M', stock_total=10, stock_reservado=0))
        db.flush()
        for i in (1, 2):
            db.add(BranchStock(tenant_id=i, sucursal_id=i, variante_id=i, stock_total=10, stock_reservado=0, activo=True))
        db.commit()


def offline_request(**changes):
    return dict(operacion_id=str(uuid4()), sucursal_id=1, snapshot_version='catalog-version',
                creado_at=datetime.now(timezone.utc).isoformat(), items=[{'variante_id':1,'cantidad':2}], **changes)


def test_cu12_bundle_is_owned_complete_and_without_private_costs(client, stock):
    r=client.get('/api/v1/offline/bundle',headers=headers(4));assert r.status_code==200,r.text
    b=r.json();assert b['owner']=='1:4' and b['products'][0]['id']==1 and len(b['products'])==1
    assert b['variants'][0]['id']==1 and b['stock'][0]['disponible']==10
    assert 'costo_referencia' not in b['products'][0] and b['valid_until']>b['downloaded_at']
    assert r.headers['cache-control']=='no-store'
    r=client.get('/api/v1/offline/bundle',headers=headers(5));assert r.status_code==200 and r.json()['branches']==[]


def test_cu12_plan_and_role_are_checked(client,stock,factory):
    with factory(tenant_id=1) as db:
        db.get(User,5).rol=Role.PROVEEDOR;db.commit()
    assert client.get('/api/v1/offline/bundle',headers=headers(5)).status_code==403
    with factory() as db,system_scope(db):db.get(SaaSPlan,1).offline=False;db.commit()
    assert client.get('/api/v1/offline/bundle',headers=headers(4)).status_code==403


def test_cu14_confirmation_is_atomic_and_idempotent(client,stock,factory):
    payload=offline_request()
    first=client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    assert first.status_code==201,first.text
    second=client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    assert second.status_code==200 and second.json()['replayed']
    assert first.json()['reservation']['id']==second.json()['reservation']['id']
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_reservado==2
        assert db.scalar(select(func.count(Reservation.id)))==1
        assert db.scalar(select(func.count(OfflineReservationReceipt.id)))==1
    changed={**payload,'items':[{'variante_id':1,'cantidad':3}]}
    assert client.post('/api/v1/offline/reservations',headers=headers(4),json=changed).status_code==409


def test_cu14_stock_conflict_keeps_server_unchanged_and_can_retry(client,stock,factory):
    payload=offline_request();payload['items'][0]['cantidad']=11
    r=client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    assert r.status_code==409 and r.json()['detail']['code']=='STOCK_CHANGED'
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Reservation.id)))==0
        assert db.get(ProductVariant,1).stock_reservado==0
    payload['items'][0]['cantidad']=1
    assert client.post('/api/v1/offline/reservations',headers=headers(4),json=payload).status_code==201


def test_cu14_rechecks_branch_ownership_and_rejects_injected_price(client,stock):
    payload=offline_request()
    assert client.post('/api/v1/offline/reservations',headers=headers(5),json=payload).status_code==403
    assert client.post('/api/v1/offline/reservations',headers=headers(4),json={**payload,'sucursal_id':2}).status_code==404
    assert client.post('/api/v1/offline/reservations',headers=headers(4),json={**payload,'tenant_id':2}).status_code==422
    payload['items'][0]['precio']=1
    assert client.post('/api/v1/offline/reservations',headers=headers(4),json=payload).status_code==422


def test_cu14_multiple_lines_do_not_leave_partial_reservations(client,stock,factory):
    payload=offline_request()
    payload['items'].append({'variante_id':2,'cantidad':1})
    result=client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    assert result.status_code==409
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_reservado==0
        assert db.scalar(select(func.count(Reservation.id)))==0
        assert db.scalar(select(func.count(InventoryMovement.id)))==0
        assert db.scalar(select(func.count(OfflineReservationReceipt.id)))==0


def test_cu14_uses_current_database_price_after_download(client,stock,factory):
    from app.models import Product, ReservationItem
    snapshot=client.get('/api/v1/offline/bundle',headers=headers(4)).json()
    with factory(tenant_id=1) as db:
        db.get(Product,1).precio=Decimal('245.50')
        db.commit()
    payload=offline_request()
    payload['snapshot_version']=snapshot['version']
    result=client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    assert result.status_code==201,result.text
    with factory(tenant_id=1) as db:
        assert db.scalar(select(ReservationItem)).precio_referencia==Decimal('245.50')


def test_cu11_supplier_portal_and_receiving_updates_inventory_once(client,stock,factory):
    root=headers()
    check=client.get('/api/v1/auth/me',headers=headers(2,2,'b'))
    assert check.status_code==200,check.text
    r=client.post('/api/v1/supply/suppliers',headers=root,json={'nombre_empresa':'Fábrica local','ciudad':'La Paz'})
    assert r.status_code==201,r.text
    supplier=r.json()['id']
    r=client.post(f'/api/v1/supply/suppliers/{supplier}/account',headers=root,json={'nombre':'Proveedor','email':'supplier@example.com','password':'Test-supplier-123!'})
    assert r.status_code==200,r.text
    provider=headers(r.json()['usuario_id'])
    r=client.post(f'/api/v1/supply/suppliers/{supplier}/offers',headers=provider,json={'nombre_suministro':'Camisas M','costo_unitario':'20','cantidad_disponible':20,'unidad_medida':'Unidades'})
    assert r.status_code==201,r.text
    offer=r.json()['id']
    request={'request_id':str(uuid4()),'proveedor_id':supplier,'sucursal_id':1,'items':[{'suministro_id':offer,'variante_id':1,'cantidad':5}]}
    r=client.post('/api/v1/supply/orders',headers=root,json=request);assert r.status_code==201,r.text
    order=r.json()['id'];assert Decimal(r.json()['total'])==Decimal('100')
    assert client.post('/api/v1/supply/orders',headers=root,json=request).json()['id']==order
    assert client.post(f'/api/v1/supply/orders/{order}/receive',headers=provider).status_code==403
    assert client.post(f'/api/v1/supply/orders/{order}/confirm',headers=provider).status_code==200
    for _ in range(2):
        r=client.post(f'/api/v1/supply/orders/{order}/receive',headers=root);assert r.status_code==200,r.text
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==15
        assert db.scalar(select(func.count(InventoryMovement.id)))==1
    assert client.post(f'/api/v1/supply/orders/{order}/cancel',headers=root).status_code==409
    check=client.get('/api/v1/supply/orders',headers=headers(2,2,'b'))
    assert check.status_code==200,check.text
    assert check.json()==[]
    assert client.put(f'/api/v1/supply/suppliers/{supplier}',headers=headers(2,2,'b'),json={'nombre_empresa':'Otra','ciudad':'La Paz'}).status_code==404
    assert client.get('/api/v1/supply/suppliers',headers=headers(4)).status_code==403


def test_cu11_cancel_confirmed_restores_offer_without_entering_stock(client,stock):
    root=headers()
    supplier=client.post('/api/v1/supply/suppliers',headers=root,json={'nombre_empresa':'Fábrica','ciudad':'La Paz'}).json()['id']
    offer=client.post(f'/api/v1/supply/suppliers/{supplier}/offers',headers=root,json={'nombre_suministro':'Lote','costo_unitario':'10','cantidad_disponible':8}).json()['id']
    r=client.post('/api/v1/supply/orders',headers=root,json={'request_id':str(uuid4()),'proveedor_id':supplier,'sucursal_id':1,'items':[{'suministro_id':offer,'cantidad':5}]})
    assert r.status_code==201,r.text
    oid=r.json()['id']
    assert client.post(f'/api/v1/supply/orders/{oid}/confirm',headers=root).status_code==200
    assert client.get(f'/api/v1/supply/suppliers/{supplier}/offers',headers=root).json()[0]['cantidad_disponible']==3
    for _ in range(2):assert client.post(f'/api/v1/supply/orders/{oid}/cancel',headers=root).status_code==200
    assert client.get(f'/api/v1/supply/suppliers/{supplier}/offers',headers=root).json()[0]['cantidad_disponible']==8
