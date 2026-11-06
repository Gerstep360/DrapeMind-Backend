from datetime import datetime,timezone,timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock
import json
import pytest
from sqlalchemy import select,func
from test_saas_isolation import factory,client,headers
from test_saas_customer_shopping import stocked
from app.models import Order,Payment,ProductVariant,BranchStock,BranchStaff,User,Role
from app.models.saas import SaaSPlan
from app.services.store import create_payment,confirm_payment
from app.incrementos.incremento_iii.models import CheckoutConfirmation,BusinessReport
from app.incrementos.incremento_iii.pdf import document

def checkout(client,stocked,operation=None,**extra):
    uid,vid,branch=stocked
    payload={'tipo_entrega':'RECOJO','sucursal_id':branch,'operacion_id':operation or str(uuid4()),**extra}
    return client.post('/api/v1/orders/checkout',headers=headers(uid),json=payload),payload

def paid(factory,order_id):
    with factory(tenant_id=1) as db:
        p=create_payment(db,db.get(Order,order_id),'EFECTIVO')
        confirm_payment(db,p.referencia_externa,'APROBADO')

def test_checkout_reply_loss_recovers_same_order_and_never_reduces_stock_twice(client,factory,stocked):
    response,payload=checkout(client,stocked)
    assert response.status_code==201,response.text
    order=response.json();uid,vid,_=stocked
    repeat=client.post('/api/v1/orders/checkout',headers=headers(uid),json=payload)
    assert repeat.status_code==201 and repeat.json()['id']==order['id']
    recovered=client.get('/api/v1/orders/checkout-operations/'+payload['operacion_id'],headers=headers(uid))
    assert recovered.status_code==200 and recovered.json()['id']==order['id']
    assert client.get('/api/v1/orders/checkout-operations/'+payload['operacion_id'],headers=headers(2,2,'b')).status_code==404
    assert client.post('/api/v1/orders/checkout',headers=headers(uid),json={**payload,'observacion':'Otro cuerpo'}).status_code==409
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Order.id)))==1
        assert db.get(ProductVariant,vid).stock_total==9
        assert db.scalar(select(func.count(CheckoutConfirmation.id)))==1

def test_receipt_pdf_requires_payment_owner_or_assigned_branch(client,factory,stocked):
    response,_=checkout(client,stocked);oid=response.json()['id'];uid,vid,branch=stocked
    url=f'/api/v1/orders/{oid}/receipt.pdf'
    assert client.get(url,headers=headers(uid)).status_code==409
    paid(factory,oid)
    pdf=client.get(url,headers=headers(uid))
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-1.4')
    assert pdf.headers['content-type']=='application/pdf'
    assert b'Comprobante de venta' in pdf.content and b'Bs 300.00' in pdf.content
    assert client.get(url,headers=headers(2,2,'b')).status_code==404
    with factory(tenant_id=1) as db:
        user=User(nombre='Caja',email='receipt-cashier@example.com',password_hash='fixture',rol=Role.CAJERO)
        db.add(user);db.commit();staff_id=user.id
    assert client.get(url,headers=headers(staff_id)).status_code==404
    with factory(tenant_id=1) as db:db.add(BranchStaff(usuario_id=staff_id,sucursal_id=branch,activo=True));db.commit()
    assert client.get(url,headers=headers(staff_id)).status_code==200
    assert [r['id'] for r in client.get('/api/v1/orders',headers=headers(staff_id)).json()]==[oid]
    assert client.get(f'/api/v1/orders/{oid}',headers=headers(staff_id)).status_code==200

def test_customer_can_cancel_pending_checkout_and_stock_returns_once(client,factory,stocked):
    response,_=checkout(client,stocked);oid=response.json()['id'];uid,vid,_=stocked
    assert client.post(f'/api/v1/orders/{oid}/cancel',headers=headers(uid)).status_code==200
    assert client.post(f'/api/v1/orders/{oid}/cancel',headers=headers(uid)).status_code==409
    with factory(tenant_id=1) as db:assert db.get(ProductVariant,vid).stock_total==12

def test_receipt_pdf_paginates_and_escapes_content():
    pdf=document('Tienda (prueba)',[f'Prenda {n} \\ talla (M)' for n in range(130)])
    assert b'/Count 3' in pdf and b'\\(prueba\\)' in pdf
    assert pdf.endswith(b'%%EOF\n')

def test_report_plan_role_scope_and_input_validation(client,stocked):
    valid={'consulta':'Revisa las ventas de este mes'}
    assert client.post('/api/v1/business-reports',headers=headers(),json=valid).status_code==403
    assert client.post('/api/v1/business-reports',headers=headers(stocked[0]),json=valid).status_code==403
    assert client.post('/api/v1/business-reports',headers=headers(2,2,'b'),json={**valid,'tenant_id':1}).status_code==422
    assert client.post('/api/v1/business-reports',headers=headers(2,2,'b'),json={**valid,'desde':'2026-10-30','hasta':'2026-10-01'}).status_code==422

@pytest.fixture
def professional(factory):
    with factory(tenant_id=1) as db:db.get(SaaSPlan,1).ai_reports=True;db.commit()

def test_report_natural_language_is_grounded_saved_and_tenant_scoped(client,factory,stocked,professional,monkeypatch):
    response,_=checkout(client,stocked);paid(factory,response.json()['id'])
    ai=AsyncMock(return_value=(json.dumps({'titulo':'Balance de la tienda','analisis':'Las métricas reflejan cobros confirmados y existencias actuales.','recomendaciones':['Revisar las tallas de mayor salida.']}),{}))
    monkeypatch.setattr('app.incrementos.incremento_iii.router.call_nvidia',ai)
    r=client.post('/api/v1/business-reports',headers=headers(),json={'consulta':'Revisa ventas de hoy e inventario','entrada':'VOZ'})
    assert r.status_code==201,r.text
    data=r.json();assert data['datos']['ingreso_neto_cobrado']=='300.00' and data['datos']['pedidos_pagados']==1
    assert data['entrada']=='VOZ' and data['datos']['desde']==str(datetime.now(timezone.utc).date())
    prompt=json.loads(ai.call_args.kwargs['user'])
    from app.models.saas import Tenant
    with factory(tenant_id=1) as db:company=db.get(Tenant,1).name
    assert prompt['datos_verificados']['empresa']==company and 'client@example.com' not in ai.call_args.kwargs['user']
    assert client.get('/api/v1/business-reports',headers=headers()).json()[0]['id']==data['id']
    assert client.get('/api/v1/business-reports',headers=headers(2,2,'b')).json()==[]
    assert client.get(f"/api/v1/business-reports/{data['id']}/pdf",headers=headers()).content.startswith(b'%PDF')
    assert client.get(f"/api/v1/business-reports/{data['id']}/pdf",headers=headers(2,2,'b')).status_code==404

def test_nvidia_unavailable_creates_no_fabricated_report(client,factory,professional,monkeypatch):
    monkeypatch.setattr('app.incrementos.incremento_iii.router.call_nvidia',AsyncMock(side_effect=RuntimeError('Unavailable')))
    r=client.post('/api/v1/business-reports',headers=headers(),json={'consulta':'Revisa inventario actual'})
    assert r.status_code==503
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(BusinessReport.id)))==0

def test_delivery_price_comes_from_server_not_client(client,factory,stocked):
    from app.models import Address
    with factory(tenant_id=1) as db:
        a=Address(usuario_id=stocked[0],alias='Casa',departamento='La Paz',ciudad='La Paz',direccion='Calle 10',es_principal=True)
        db.add(a);db.commit();aid=a.id
    response,_=checkout(client,stocked,tipo_entrega='DELIVERY',direccion_id=aid,costo_envio='0.01')
    assert response.status_code==201,response.text
    config=client.get('/api/v1/commerce/config',headers=headers(stocked[0])).json()
    assert Decimal(str(response.json()['costo_envio']))==Decimal(config['costo_delivery'])
    assert Decimal(str(response.json()['total']))==Decimal('300')+Decimal(config['costo_delivery'])
