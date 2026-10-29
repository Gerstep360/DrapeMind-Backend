from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from test_saas_incremento_ii import factory,client,stock,headers,offline_request
from app.models import User,Role,UserStatus,BranchStaff,Product,ProductVariant,BranchStock,Order,OrderItem,Payment,Reservation
from app.incrementos.incremento_ii.models import SyncOperation,SyncAudit,GarmentExchange


@pytest.fixture
def clerk(factory,stock):
    with factory(tenant_id=1) as db:
        db.add(User(id=6,nombre='Caja',email='cashier@example.com',password_hash='fixture',rol=Role.CAJERO,estado=UserStatus.ACTIVO))
        db.flush()
        db.add_all([BranchStaff(usuario_id=i,sucursal_id=1,activo=True) for i in (5,6)])
        db.commit()
    return headers(6)


def sale_body(**changes):
    body=offline_request()
    body['items']=[{'variante_id':1,'cantidad':2,'precio_unitario':'100.00'}]
    body['efectivo_recibido']='250.00'
    return {**body,**changes}


def sync(client,auth,body,kind='SALE'):
    return client.post('/api/v1/offline/operations',headers=auth,json={'tipo':kind,'payload':body})


def test_cash_sale_idempotent_and_isolated(client,clerk,factory):
    body=sale_body()
    a=sync(client,clerk,body);assert a.status_code==200,a.text
    assert a.json()['estado']=='CONFIRMED',a.text
    b=sync(client,clerk,body);assert b.json()['resultado']==a.json()['resultado']
    assert a.json()['resultado']['sale']['cambio']=='50.00'
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==8
        assert db.scalar(select(func.count(Order.id)))==1
        order=db.scalar(select(Order));assert order.usuario_id is None and order.atendido_por_id==6
        assert db.scalar(select(Payment)).monto==Decimal('200')
    assert sync(client,headers(4),sale_body()).status_code==403
    assert client.get('/api/v1/offline/operations',headers=headers(4)).json()==[]
    assert sync(client,clerk,sale_body(sucursal_id=2)).status_code==404


def test_price_conflict_is_audited_and_only_manager_can_accept_saved_price(client,clerk,factory):
    body=sale_body()
    with factory(tenant_id=1) as db:db.get(Product,1).precio=Decimal('125');db.commit()
    result=sync(client,clerk,body)
    assert result.json()['estado']=='CONFLICT',result.text
    oid=result.json()['id']
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Order.id)))==0
        assert db.get(ProductVariant,1).stock_total==10
    review={'accion':'RETRY','motivo':'Se respeta el precio cobrado en caja','aceptar_precio_guardado':True}
    url=f'/api/v1/retail/operations/{oid}/resolve'
    assert client.post(url,headers=clerk,json=review).status_code==403
    resolved=client.post(url,headers=headers(5),json=review)
    assert resolved.json()['estado']=='CONFIRMED',resolved.text
    assert sync(client,clerk,body).json()['estado']=='CONFIRMED'
    with factory(tenant_id=1) as db:
        assert db.scalar(select(Order)).total==Decimal('200')
        assert db.scalar(select(func.count(SyncAudit.id)))==2
    assert client.get('/api/v1/retail/conflicts',headers=headers(2,2,'b')).json()==[]


def test_rejection_requires_refund_confirmation_and_remains_terminal(client,clerk,factory):
    body=sale_body();body['items'][0]['cantidad']=11;body['efectivo_recibido']='1200'
    result=sync(client,clerk,body);assert result.json()['estado']=='CONFLICT',result.text
    url=f"/api/v1/retail/operations/{result.json()['id']}/resolve"
    review={'accion':'REJECT','motivo':'Se devolvió el importe al comprador'}
    assert client.post(url,headers=headers(5),json=review).status_code==422
    assert client.post(url,headers=headers(5),json={**review,'efectivo_devuelto':True}).json()['estado']=='REJECTED'
    assert sync(client,clerk,body).json()['estado']=='REJECTED'
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(Order.id)))==0


def test_attend_and_cash_pickup_consumes_reserved_units_once(client,clerk,factory):
    r=client.post('/api/v1/offline/reservations',headers=headers(4),json=offline_request())
    assert r.status_code==201,r.text
    rid=r.json()['reservation']['id']
    assert client.get('/api/v1/offline/bundle',headers=clerk).json()['reservations'][0]['id']==rid
    prepared=client.post(f'/api/v1/retail/reservations/{rid}/prepare',headers=clerk,json={'estado':'LISTA'})
    assert prepared.status_code==200,prepared.text
    body=sale_body(reserva_id=rid)
    a=sync(client,clerk,body,'PICKUP')
    assert a.json()['estado']=='CONFIRMED',a.text
    assert sync(client,clerk,body,'PICKUP').json()['resultado']==a.json()['resultado']
    assert sync(client,clerk,sale_body(reserva_id=rid),'PICKUP').json()['estado']=='CONFLICT'
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==8 and db.get(ProductVariant,1).stock_reservado==0
        order=db.scalar(select(Order));assert order.usuario_id==4 and order.reserva_id==rid
        assert db.get(Reservation,rid).estado=='CONVERTIDA'


def test_exchange_partial_return_credit_and_duplicate_protection(client,clerk,factory):
    sale=sync(client,clerk,sale_body()).json()['resultado']['sale']
    with factory(tenant_id=1) as db:
        db.add(Product(id=3,categoria_id=1,nombre='Nueva prenda',precio=Decimal('150'),imagenes=[],activo=True));db.flush()
        db.add(ProductVariant(id=3,producto_id=3,sku='NEW',talla='L',color='Azul',stock_total=5,stock_reservado=0));db.flush()
        db.add(BranchStock(sucursal_id=1,variante_id=3,stock_total=5,stock_reservado=0,activo=True));db.commit()
    original=client.get('/api/v1/retail/orders/find',headers=clerk,params={'code':sale['pedido_id']}).json()
    payload={'operacion_id':str(uuid4()),'pedido_origen_id':sale['pedido_id'],'sucursal_id':1,
        'motivo':'El cliente solicita otra talla','devoluciones':[{'item_pedido_id':original['items'][0]['id'],'cantidad':1}],
        'prendas_nuevas':[{'variante_id':3,'cantidad':1}],'efectivo_recibido':'50','efectivo_devuelto':'0'}
    result=client.post('/api/v1/retail/exchanges',headers=clerk,json=payload)
    assert result.status_code==200,result.text
    assert Decimal(result.json()['credito'])==100 and Decimal(result.json()['diferencia'])==50
    replay=client.post('/api/v1/retail/exchanges',headers=clerk,json=payload)
    assert replay.json()['id']==result.json()['id']
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==9 and db.get(ProductVariant,3).stock_total==4
        assert db.scalar(select(func.count(GarmentExchange.id)))==1
        payments=list(db.scalars(select(Payment).where(Payment.pedido_id==result.json()['pedido_nuevo_id'])))
        assert sum(p.monto for p in payments)==Decimal('150')
        assert {p.metodo for p in payments}=={'EFECTIVO','CREDITO_CAMBIO'}
    payload['operacion_id']=str(uuid4());payload['devoluciones'][0]['cantidad']=2
    assert client.post('/api/v1/retail/exchanges',headers=clerk,json=payload).status_code==409


def test_closed_branch_cash_conflict_can_be_refunded_and_audited(client,clerk,factory):
    from app.models import Branch
    with factory(tenant_id=1) as db:db.get(Branch,1).activo=False;db.commit()
    result=sync(client,clerk,sale_body())
    assert result.status_code==200 and result.json()['estado']=='CONFLICT',result.text
    url=f"/api/v1/retail/operations/{result.json()['id']}/resolve"
    resolved=client.post(url,headers=headers(5),json={'accion':'REJECT','motivo':'Se devolvió el efectivo al cliente','efectivo_devuelto':True})
    assert resolved.status_code==200 and resolved.json()['estado']=='REJECTED',resolved.text
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(Order.id)))==0


def test_exchange_refund_preserves_net_revenue(client,clerk,factory):
    from app.services.financials import net_payments,net_delivered_orders
    sale=sync(client,clerk,sale_body()).json()['resultado']['sale']
    with factory(tenant_id=1) as db:
        db.get(Product,1).precio=Decimal('80');db.commit()
    original=client.get('/api/v1/retail/orders/find',headers=clerk,params={'code':sale['pedido_id']}).json()
    payload={'operacion_id':str(uuid4()),'pedido_origen_id':sale['pedido_id'],'sucursal_id':1,
        'motivo':'Se aplica devolución de diferencia','devoluciones':[{'item_pedido_id':original['items'][0]['id'],'cantidad':1}],
        'prendas_nuevas':[{'variante_id':1,'cantidad':1}],'efectivo_recibido':'0','efectivo_devuelto':'20'}
    preview=client.post('/api/v1/retail/exchanges?preview=true',headers=clerk,json=payload)
    assert preview.status_code==200 and Decimal(preview.json()['diferencia'])==-20
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(GarmentExchange.id)))==0
    result=client.post('/api/v1/retail/exchanges',headers=clerk,json=payload);assert result.status_code==200,result.text
    with factory(tenant_id=1) as db:
        assert net_payments(db)==Decimal('180') and net_delivered_orders(db)==Decimal('180')
        assert db.get(ProductVariant,1).stock_total==8


def test_conflicted_reservation_cancel_is_visible_to_manager_and_terminal(client,clerk,factory):
    body=offline_request();body['items'][0]['cantidad']=11
    result=sync(client,headers(4),body,'RESERVATION')
    assert result.json()['estado']=='CONFLICT',result.text
    cancel=client.post(f"/api/v1/offline/operations/{body['operacion_id']}/cancel",headers=headers(4),json={})
    assert cancel.status_code==200 and cancel.json()['estado']=='REJECTED',cancel.text
    assert sync(client,headers(4),body,'RESERVATION').json()['estado']=='REJECTED'
    assert client.post(f"/api/v1/retail/operations/{result.json()['id']}/resolve",headers=headers(5),json={'accion':'RETRY','motivo':'No debe volver a crearse'}).status_code==409


def test_cash_multiple_lines_roll_back_without_partial_sale(client,clerk,factory):
    body=sale_body()
    body['items'].append({'variante_id':2,'cantidad':1,'precio_unitario':'100.00'})
    body['efectivo_recibido']='400'
    result=sync(client,clerk,body)
    assert result.json()['estado']=='CONFLICT',result.text
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Order.id)))==0
        assert db.get(ProductVariant,1).stock_total==10


def test_result_lookup_is_scoped_to_the_authenticated_owner(client,clerk):
    body=sale_body();result=sync(client,clerk,body)
    assert result.json()['estado']=='CONFIRMED'
    request={'operaciones':[body['operacion_id']]}
    assert len(client.post('/api/v1/offline/operations/results',headers=clerk,json=request).json())==1
    assert client.post('/api/v1/offline/operations/results',headers=headers(4),json=request).json()==[]
    assert client.post('/api/v1/offline/operations/results',headers=headers(2,2,'b'),json=request).json()==[]


def test_expired_reservation_releases_branch_and_global_inventory(client,clerk,factory):
    from datetime import datetime,timedelta,timezone
    result=client.post('/api/v1/offline/reservations',headers=headers(4),json=offline_request())
    assert result.status_code==201,result.text
    with factory(tenant_id=1) as db:
        reservation=db.get(Reservation,result.json()['reservation']['id'])
        reservation.fecha_reserva=datetime.now(timezone.utc)-timedelta(hours=2)
        reservation.vence_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        db.commit()
    assert client.get('/api/v1/offline/bundle',headers=clerk).status_code==200
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_reservado==0
        assert db.scalar(select(BranchStock).where(BranchStock.sucursal_id==1,BranchStock.variante_id==1)).stock_reservado==0
