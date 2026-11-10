"""Focused contracts for invoice reporting and quantity discounts. No real Stripe calls."""
from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select,func
from app.core.tenancy import system_scope
from app.models import Promotion,CartItem,ProductVariant
from app.models.saas import Tenant
from app.services.promotion_rules import basket_discount,promotion_issue
from app.segundo_parcial.cu03_suscripciones.cu03_facturas_modelo import SaaSInvoice
from app.segundo_parcial.cu03_suscripciones import cu03_facturas_service as invoices
from test_saas_isolation import factory,client,headers
from test_saas_customer_shopping import stocked,platform


def invoice(id,customer,currency='bob',live=False):
    return {'id':id,'customer':customer,'parent':{'subscription_details':{'subscription':'sub_'+customer}},'number':id,
        'status':'paid','currency':currency,'amount_paid':12000,'amount_due':12000,'amount_remaining':0,
        'created':int(datetime.now(timezone.utc).timestamp()),'livemode':live,'lines':{'data':[]}}


def test_platform_history_is_idempotent_filtered_and_exports_without_tenant_access(client,factory,monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings,'STRIPE_SECRET_KEY','sk_test_fixture')
    with factory() as db,system_scope(db):
        for id in (1,2):
            tenant=db.get(Tenant,id);tenant.stripe_customer_id=f'cus_{id}';tenant.admin_user_id=id
        db.commit()
    rows=[invoice('in_one','cus_1'),invoice('in_two','cus_2','usd',True),invoice('in_ignore','cus_other')]
    monkeypatch.setattr(invoices,'_stripe_request',lambda *args,**kw:{'data':rows,'has_more':False})
    root=platform(client)
    for _ in range(2):
        result=client.post('/api/v1/saas/billing/sync',headers=root,json={})
        assert result.status_code==200,result.text
    report=client.get('/api/v1/saas/billing',headers=root)
    assert report.status_code==200 and report.json()['total']==2
    assert len(report.json()['summary'])==2
    assert report.headers['cache-control']=='private, no-store'
    only=client.get('/api/v1/saas/billing?tenant_id=2&mode=live',headers=root).json()
    assert only['total']==1 and only['items'][0]['currency']=='USD'
    assert only['summary'][0]['paid_amount_minor']==12000
    assert client.get('/api/v1/saas/billing',headers=headers()).status_code==403
    assert client.post('/api/v1/saas/billing/sync',headers=headers(),json={}).status_code==403
    for fmt,magic in [('pdf',b'%PDF'),('xlsx',b'PK')]:
        file=client.get('/api/v1/saas/billing/export?format='+fmt,headers=root)
        assert file.status_code==200,file.text[:100]
        assert file.content.startswith(magic)
    with factory() as db,system_scope(db):assert db.scalar(select(func.count(SaaSInvoice.id)))==2


def test_bulk_quote_uses_real_prices_and_checkout_rechecks_quantity(client,factory,stocked):
    uid,variant,branch=stocked
    body={'codigo':'MAYOR3','tipo_descuento':'POR_CANTIDAD','valor_descuento':20,'cantidad_minima':3,'activo':True}
    created=client.post('/api/v1/admin/promotions',headers=headers(),json=body)
    assert created.status_code==201,created.text
    assert created.json()['cantidad_minima']==3
    url='/api/v1/catalog/promotions/quote'
    def quote(quantity):return client.post(url,headers=headers(uid),json={'items':[{'variante_id':variant,'cantidad':quantity}]})
    assert Decimal(quote(2).json()['descuento_calculado'])==0
    offer=quote(3).json()
    assert offer['codigo']=='MAYOR3' and Decimal(offer['descuento_calculado'])==60 and Decimal(offer['subtotal'])==300
    assert client.post(url,headers=headers(2,2,'b'),json={'items':[{'variante_id':variant,'cantidad':3}]}).status_code==409
    with factory(tenant_id=1) as db:
        item=db.scalar(select(CartItem));item.cantidad=2;db.commit()
    payload={'tipo_entrega':'RECOJO','sucursal_id':branch,'codigo_promocion':'MAYOR3','operacion_id':str(uuid4())}
    rejected=client.post('/api/v1/orders/checkout',headers=headers(uid),json=payload)
    assert rejected.status_code==409,rejected.text
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,variant).stock_total==12
        item=db.scalar(select(CartItem));item.cantidad=3;db.commit()
    sale=client.post('/api/v1/orders/checkout',headers=headers(uid),json=payload)
    assert sale.status_code==201,sale.text
    assert Decimal(sale.json()['descuento'])==60 and Decimal(sale.json()['total'])==240
    assert client.post('/api/v1/orders/checkout',headers=headers(uid),json=payload).json()['id']==sale.json()['id']
    with factory(tenant_id=1) as db:assert db.scalar(select(Promotion)).usos_actuales==1


def test_bulk_counts_only_eligible_product_units_and_rejects_invalid_configuration(client,factory,stocked):
    p=Promotion(codigo='SPECIFIC',producto_id=1,tipo_descuento='POR_CANTIDAD',valor_descuento=Decimal('15'),cantidad_minima=3,monto_minimo_compra=Decimal(0),activo=True,usos_actuales=0)
    assert basket_discount(p,[(1,1,Decimal(100)),(2,10,Decimal(100))])==0
    assert promotion_issue(p,[(1,1,Decimal(100)),(2,10,Decimal(100))])
    assert basket_discount(p,[(1,1,Decimal(100)),(1,2,Decimal(100)),(2,10,Decimal(100))])==Decimal('45')
    for changes in ({'cantidad_minima':1},{'valor_descuento':101}):
        result=client.post('/api/v1/admin/promotions',headers=headers(),json={'codigo':'INVALID','tipo_descuento':'POR_CANTIDAD','cantidad_minima':3,'valor_descuento':20,**changes})
        assert result.status_code==422
