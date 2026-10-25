"""Real middleware, persisted memberships and branch inventory transactions."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from app.core.tenancy import system_scope
from app.models import User,Role,UserStatus,ProductVariant,BranchStock,Cart,CartItem,Branch,Order,InventoryMovement,UserStyleProfile
from app.models.saas import Tenant,CustomerAccount
from app.core.security import create_access_token
from app.services.store import checkout_cart,cancel_unpaid_order
from test_saas_isolation import factory,client,headers

def platform(client):
    response=client.post('/api/v1/auth/login',json={'email':'platform@example.com','password':'Test-platform-123!'})
    assert response.status_code==200
    return {'Authorization':'Bearer '+response.json()['access_token']}

def test_platform_creates_ready_company_without_technical_slug(client,factory):
    response=client.post('/api/v1/saas/tenants',headers=platform(client),json={'name':'Moda Nueva','admin_name':'Ana Moda','admin_email':'ana@example.com','admin_password':'Company-owner-123!','plan_id':1,'activation':'ADMINISTRATIVE','ends_at':(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),'address':'Calle 12','phone':'70000000'})
    assert response.status_code==201,response.text
    row=response.json()
    assert row['tenant']['slug']=='moda-nueva' and row['access_active']
    assert row['tenant']['address']=='Calle 12'
    updated=client.put('/api/v1/saas/tenants/'+str(row['tenant']['id'])+'/details',headers=platform(client),json={'name':'Moda Nueva','address':'Calle 20','phone':'70000001','contact_email':'tienda@example.com'})
    assert updated.status_code==200 and updated.json()['tenant']['address']=='Calle 20'
    login=client.post('/api/v1/auth/login',json={'email':'ana@example.com','password':'Company-owner-123!'})
    assert login.status_code==200 and login.json()['redirect_path']=='/dashboard'
    assert client.get('/api/v1/saas/tenants',headers={'Authorization':'Bearer '+login.json()['access_token']}).status_code==403
    assert client.put('/api/v1/saas/tenants/'+str(row['tenant']['id'])+'/details',headers={'Authorization':'Bearer '+login.json()['access_token']},json={'name':'Otra tienda'}).status_code==403

def test_pending_stripe_company_can_get_administrative_license(client):
    response=client.post('/api/v1/saas/tenants',headers=platform(client),json={'name':'Pendiente','admin_name':'Ana','admin_email':'ana@example.com','admin_password':'Company-owner-123!','plan_id':1})
    assert response.status_code==201,response.text
    row=response.json();assert not row['subscription']['managed_by_stripe'] and not row['access_active']
    response=client.put('/api/v1/saas/tenants/'+str(row['tenant']['id'])+'/subscription',headers=platform(client),json={'plan_id':1,'status':'ACTIVE','starts_at':datetime.now(timezone.utc).isoformat(),'ends_at':(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()})
    assert response.status_code==200 and response.json()['access_active']

def test_one_customer_registration_visits_two_stores_with_preferences(client,factory):
    payload={'nombre':'Cliente Personal','email':'shopper@example.com','password':'Customer-password-123!'}
    response=client.post('/api/v1/auth/register',headers={'X-Tenant':'a'},json=payload)
    assert response.status_code==201,response.text
    login=client.post('/api/v1/auth/login',json={'email':payload['email'],'password':payload['password'],'tenant_slug':'a'})
    data=login.json();assert data['user']['is_universal_customer']
    first_id=data['user']['id'];auth={'Authorization':'Bearer '+data['access_token']}
    with factory(tenant_id=1) as db:
        profile=UserStyleProfile(usuario_id=first_id,talla_superior='M',estilos_preferidos=['casual'],presupuesto_habitual=Decimal('250'))
        db.add(profile);db.flush()
        from app.services.customer_identity import remember_personal_data
        remember_personal_data(db,db.get(User,first_id));db.commit()
        cart=Cart(usuario_id=first_id);db.add(cart);db.commit();cart_id=cart.id
    response=client.post('/api/v1/users/me/addresses',headers=auth,json={'alias':'Casa','departamento':'La Paz','ciudad':'La Paz','direccion':'Calle personal 12','es_principal':True})
    assert response.status_code==201,response.text
    switched=client.post('/api/v1/auth/store',headers=auth,json={'slug':'b'})
    assert switched.status_code==200,switched.text
    second=switched.json();assert second['user']['email']==payload['email'] and second['user']['tenant_id']==2
    assert second['user']['id']!=first_id and second['user']['rol']=='CLIENTE' and second['user']['has_style_profile']
    second_auth={'Authorization':'Bearer '+second['access_token']}
    assert client.get('/api/v1/users/me/style-profile',headers=second_auth).json()['talla_superior']=='M'
    address=client.get('/api/v1/users/me/addresses',headers=second_auth).json()[0]
    assert address['direccion']=='Calle personal 12'
    assert client.get('/api/v1/catalog/products/1',headers=second_auth).status_code==404
    assert client.get('/api/v1/saas/tenants',headers=second_auth).status_code==403
    assert client.post('/api/v1/auth/store',headers=second_auth,json={'slug':'a','is_platform_admin':True}).status_code==422
    with factory() as db,system_scope(db):
        assert db.scalar(select(func.count(CustomerAccount.id)))==1
        assert db.get(Cart,cart_id).tenant_id==1
    again=client.post('/api/v1/auth/login',json={'email':payload['email'],'password':payload['password'],'tenant_slug':'b'})
    assert again.status_code==200 and again.json()['user']['id']==second['user']['id']
    assert client.get('/api/v1/users/me/addresses',headers=second_auth).json()[0]['id']==address['id']
    assert client.post('/api/v1/auth/register',headers={'X-Tenant':'b'},json=payload).status_code==409

def test_employees_cannot_change_store_or_gain_platform_permissions(client):
    assert client.post('/api/v1/auth/store',headers=headers(),json={'slug':'b'}).status_code==403

def test_unavailable_store_sends_customer_to_shopping_directory(client,factory):
    payload={'nombre':'Cliente','email':'customer@example.com','password':'Customer-password-123!'}
    assert client.post('/api/v1/auth/register',headers={'X-Tenant':'a'},json=payload).status_code==201
    from app.models.saas import TenantSubscription
    with factory() as db,system_scope(db):
        subscription=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
        subscription.ends_at=datetime.now(timezone.utc)-timedelta(days=1);db.commit()
    response=client.post('/api/v1/auth/login',json={'email':payload['email'],'password':payload['password'],'tenant_slug':'a'})
    assert response.status_code==200 and response.json()['redirect_path']=='/tiendas'
    assert [row['slug'] for row in client.get('/api/v1/saas/companies').json()]==['b']

@pytest.fixture
def stocked(factory):
    with factory.kw['bind'].connect() as connection:
        connection.connection.driver_connection.create_function('gen_random_uuid',0,lambda:uuid4().hex)
    with factory(tenant_id=1) as db:
        user=User(nombre='Comprador',email='buyer@example.com',password_hash='test',rol=Role.CLIENTE,estado=UserStatus.ACTIVO)
        db.add(user);db.flush()
        variant=ProductVariant(producto_id=1,sku='SHIRT-M',color='Negro',talla='M',stock_total=12,stock_reservado=0,activo=True)
        db.add(variant);db.flush()
        db.add(Branch(ciudad_id=1,codigo='NORTE',nombre='Norte',direccion='Norte',activo=True));db.flush()
        north=db.scalar(select(Branch).where(Branch.codigo=='NORTE'))
        db.add_all([BranchStock(sucursal_id=1,variante_id=variant.id,stock_total=2,stock_reservado=0,activo=True),BranchStock(sucursal_id=north.id,variante_id=variant.id,stock_total=10,stock_reservado=0,activo=True)])
        cart=Cart(usuario_id=user.id);db.add(cart);db.flush()
        db.add(CartItem(carrito_id=cart.id,variante_id=variant.id,cantidad=3,precio_referencia=Decimal('1')));db.commit()
        return user.id,variant.id,north.id

def test_pickup_validates_branch_stock_atomically_and_original_prices(factory,stocked):
    uid,vid,north=stocked
    with factory(tenant_id=1) as db:
        user=db.get(User,uid)
        with pytest.raises(HTTPException) as error: checkout_cart(db,user,'RECOJO',None,Decimal(0),None,branch_id=1)
        assert error.value.status_code==409
        db.rollback()
        assert db.get(ProductVariant,vid).stock_total==12
        assert db.scalar(select(func.count(Order.id)))==0
        order=checkout_cart(db,user,'RECOJO',None,Decimal(0),None,branch_id=north)
        assert order.sucursal_id==north and order.total==Decimal('300')
        assert db.scalar(select(BranchStock.stock_total).where(BranchStock.sucursal_id==north))==7
        assert db.get(ProductVariant,vid).stock_total==9
        assert db.scalar(select(InventoryMovement.sucursal_id))==north
        cancel_unpaid_order(db,order,uid)
        assert db.scalar(select(BranchStock.stock_total).where(BranchStock.sucursal_id==north))==10
        assert db.get(ProductVariant,vid).stock_total==12

def test_pickup_rejects_missing_or_other_company_branch(factory,stocked):
    uid,vid,north=stocked
    with factory(tenant_id=1) as db:
        for branch_id,code in [(None,422),(2,404)]:
            with pytest.raises(HTTPException) as error: checkout_cart(db,db.get(User,uid),'RECOJO',None,Decimal(0),None,branch_id=branch_id)
            assert error.value.status_code==code
            db.rollback()

def test_pos_keeps_anonymous_buyer_separate_from_attendant(factory,stocked):
    from app.modules.carrito_pedidos_y_pagos.cu37_registrar_venta_presencial_pago_y_comprobante import registrar_venta_pos,PosSaleRequest
    from app.services.merchant_identity import receipt_identity
    uid,vid,north=stocked
    with factory(tenant_id=1) as db:
        result=registrar_venta_pos(PosSaleRequest(sucursal_id=north,items=[{'variante_id':vid,'cantidad':1,'precio_unitario':100}]),db.get(User,1),db)
        order=db.get(Order,result['pedido_id'])
        assert order.usuario_id is None and order.atendido_por_id==1 and not order.comprador_registrado
        identity=receipt_identity(db,order)
        assert identity['empresa']['nombre']=='A' and identity['sucursal']['nombre']=='Norte'
        assert identity['atendido_por']['id']==1 and not identity['comprador_registrado']
