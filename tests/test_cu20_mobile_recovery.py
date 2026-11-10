"""Provider doubles only: no real card charges or refunds."""
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.core.config import settings
from app.models import Payment, Order, ProductVariant
from app.segundo_parcial.compartido.offline_modelos import GarmentExchange
from app.services import stripe_payments
from test_saas_incremento_ii import client, factory, stock, headers
from test_saas_incremento_ii_retail import clerk, sale_body, sync


def request_return(client, clerk, factory):
    sale = sync(client, clerk, sale_body()).json()['resultado']['sale']
    with factory(tenant_id=1) as db:
        payment = db.scalar(select(Payment).where(Payment.pedido_id == sale['pedido_id']))
        payment.metodo='TARJETA'; payment.proveedor='STRIPE'; payment.referencia_externa='pi_fixture_original'
        db.commit()
    original=client.get('/api/v1/retail/orders/find', headers=clerk, params={'code':sale['pedido_id']}).json()
    return {'operacion_id':str(uuid4()), 'pedido_origen_id':sale['pedido_id'], 'sucursal_id':1,
            'motivo':'Devolver una de las dos prendas', 'metodo_pago':'STRIPE',
            'devoluciones':[{'item_pedido_id':original['items'][0]['id'], 'cantidad':1}], 'prendas_nuevas':[]}


def provider(monkeypatch, status='succeeded', fail=False):
    monkeypatch.setattr(settings, 'STRIPE_SECRET_KEY','sk_test_fixture')
    monkeypatch.setattr(settings, 'PAYMENT_PROVIDER','stripe')
    calls=[]
    def request(method, path, *, data=None, key=None):
        calls.append((method,path,key,data))
        if method=='GET': return {'data':[], 'has_more':False}
        if fail: raise HTTPException(502,'Proveedor temporalmente inaccesible')
        return {'id':'re_fixture_'+str(len(calls)), 'status':status, 'amount':10000, 'currency':'bob', 'metadata':{'drapemind_operation':key}}
    monkeypatch.setattr(stripe_payments,'_stripe_request',request)
    return calls


def test_stripe_failure_does_not_fabricate_cash_or_change_inventory(client,clerk,factory,monkeypatch):
    body=request_return(client,clerk,factory)
    calls=provider(monkeypatch,fail=True)
    response=client.post('/api/v1/retail/exchanges', headers=clerk,json=body)
    assert response.status_code==502
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==8
        assert db.scalar(select(func.count(GarmentExchange.id)))==0
        assert db.scalar(select(func.count(Payment.id)).where(Payment.estado=='REEMBOLSADO'))==0
    provider_key=calls[-1][2]
    calls=provider(monkeypatch)
    result=client.post('/api/v1/retail/exchanges',headers=clerk,json=body)
    assert result.status_code==200,result.text
    assert calls[-1][2]==provider_key
    assert result.json()['stripe_refund']['estado']=='REEMBOLSADO'
    replay=client.post('/api/v1/retail/exchanges',headers=clerk,json=body)
    assert replay.json()['id']==result.json()['id'] and len(calls)==2


def test_pending_refund_is_truthful_and_webhook_reconciles_current_state(client,clerk,factory,monkeypatch):
    from app.services.financials import net_payments
    body=request_return(client,clerk,factory)
    calls=provider(monkeypatch,status='pending')
    response=client.post('/api/v1/retail/exchanges',headers=clerk,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['stripe_refund']['estado']=='REEMBOLSO_PENDIENTE'
    with factory(tenant_id=1) as db:
        assert net_payments(db)==Decimal('200')
        assert db.get(Order,body['pedido_origen_id']).estado=='ENTREGADO'
    key=calls[-1][2]
    monkeypatch.setattr(stripe_payments,'_stripe_request',lambda *a,**kw:{'id':result['stripe_refund']['id'],'status':'succeeded','amount':10000,'currency':'bob','metadata':{'drapemind_operation':key}})
    with factory(tenant_id=1) as db:
        stripe_payments.process_event(db,{'type':'refund.updated','data':{'object':{'id':result['stripe_refund']['id'],'status':'pending'}}})
        assert net_payments(db)==Decimal('100')
    recovered=client.get('/api/v1/retail/exchanges/operations/'+body['operacion_id'],headers=clerk).json()
    assert recovered['stripe_refund']['estado']=='REEMBOLSADO'


def test_missing_stripe_configuration_cannot_approve_refund(client,clerk,factory,monkeypatch):
    body=request_return(client,clerk,factory)
    monkeypatch.setattr(settings,'STRIPE_SECRET_KEY','')
    monkeypatch.setattr(settings,'PAYMENT_PROVIDER','stripe')
    response=client.post('/api/v1/retail/exchanges',headers=clerk,json=body)
    assert response.status_code==503
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(GarmentExchange.id)))==0


@pytest.mark.parametrize('state',['failed','canceled','unrecognized'])
def test_failed_or_unknown_refund_is_not_success(client,clerk,factory,monkeypatch,state):
    body=request_return(client,clerk,factory)
    provider(monkeypatch,status=state)
    assert client.post('/api/v1/retail/exchanges',headers=clerk,json=body).status_code==502
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(GarmentExchange.id)))==0


def test_provider_history_recovers_refund_after_key_retention(monkeypatch):
    monkeypatch.setattr(settings,'STRIPE_SECRET_KEY','sk_test_fixture')
    paths=[]
    def request(method,path,**kw):
        assert method=='GET'  # An already accepted refund must never be posted again.
        paths.append(path)
        if len(paths)==1: return {'data':[{'id':'re_other','metadata':{}}], 'has_more':True}
        return {'data':[{'id':'re_saved','amount':10000,'currency':'bob','status':'pending','metadata':{'drapemind_operation':'exchange-refund-1-operation'}}], 'has_more':False}
    monkeypatch.setattr(stripe_payments,'_stripe_request',request)
    result=stripe_payments.create_stripe_refund(None,'pi_fixture',Decimal('100'),operation_key='exchange-refund-1-operation')
    assert result['id']=='re_saved' and 'starting_after=re_other' in paths[-1]


def test_refund_result_is_bound_to_specific_exchange(client,clerk,factory,monkeypatch):
    body=request_return(client,clerk,factory)
    provider(monkeypatch)
    first=client.post('/api/v1/retail/exchanges',headers=clerk,json=body)
    assert first.status_code==200,first.text
    second_body={**body,'operacion_id':str(uuid4())}
    provider(monkeypatch,status='pending')
    # Different Stripe IDs for the second refund; its state must not overwrite the first result.
    original_request=stripe_payments._stripe_request
    def second_request(*a,**kw):
        data=original_request(*a,**kw)
        if data.get('id'): data['id']='re_second'
        return data
    monkeypatch.setattr(stripe_payments,'_stripe_request',second_request)
    second=client.post('/api/v1/retail/exchanges',headers=clerk,json=second_body)
    assert second.status_code==200,second.text
    assert second.json()['stripe_refund']['estado']=='REEMBOLSO_PENDIENTE'
    original=client.get('/api/v1/retail/exchanges/operations/'+body['operacion_id'],headers=clerk).json()
    assert original['stripe_refund']['id']==first.json()['stripe_refund']['id']
    assert original['stripe_refund']['estado']=='REEMBOLSADO'
