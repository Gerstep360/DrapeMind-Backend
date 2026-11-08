from datetime import datetime,timedelta,timezone
from uuid import uuid4
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select,func
import pytest
from test_saas_isolation import factory,client,headers
from test_saas_customer_shopping import stocked
from app.models import User,Order,Payment,Product,ProductVariant,Cart,CartItem
from app.incrementos.incremento_iii.deferred_models import SavedCard,DeferredPurchase


class StripeFixture:
    def __init__(self):self.intent=None;self.mode='success';self.charges=0;self.creates=0;self.confirmations=0;self.unavailable=False;self.created_keys=set()
    def __call__(self,method,path,*,data=None,key=None):
        if self.unavailable:raise HTTPException(502,'Proveedor sin respuesta')
        if path=='payment_intents' and method=='POST':
            if key in self.created_keys:return dict(self.intent)
            self.created_keys.add(key)
            self.creates+=1
            self.intent={'id':'pi_fixture','status':'requires_payment_method','amount':int(data['amount']),'currency':'bob','amount_received':0,
                'metadata':{k[9:-1]:v for k,v in data.items() if k.startswith('metadata[')},'client_secret':'fixture_secret'}
        elif path=='payment_intents/pi_fixture/confirm':
            self.confirmations+=1
            if data.get('off_session')!='true' and self.mode=='auth':self.intent['status']='requires_action'
            elif self.mode=='decline':self.intent.update(status='requires_payment_method',last_payment_error={'code':'card_declined'});raise HTTPException(502,'Rechazo')
            elif self.mode=='auth':self.intent.update(status='requires_action');return dict(self.intent)
            elif self.intent['status']!='succeeded':self.charges+=1;self.intent.update(status='succeeded',amount_received=self.intent['amount'])
            if self.mode=='lost_response':raise HTTPException(502,'Respuesta perdida después del cobro')
        elif path=='payment_intents/pi_fixture/cancel':
            if self.intent['status']=='succeeded':raise HTTPException(502,'No se puede cancelar')
            self.intent['status']='canceled'
        elif path=='payment_intents/pi_fixture' and method=='POST':self.intent.update(data)
        elif path!='payment_intents/pi_fixture':raise AssertionError((method,path))
        return dict(self.intent)


@pytest.fixture
def provider(monkeypatch,factory,stocked):
    from app.core.config import settings
    from app.services import stripe_payments
    from app.incrementos.incremento_iii import deferred_checkout
    monkeypatch.setattr(settings,'PAYMENT_PROVIDER','stripe');monkeypatch.setattr(settings,'STRIPE_SECRET_KEY','sk_test_fixture');monkeypatch.setattr(settings,'STRIPE_PUBLISHABLE_KEY','pk_test_fixture')
    gateway=StripeFixture();monkeypatch.setattr(stripe_payments,'_stripe_request',gateway);monkeypatch.setattr(deferred_checkout,'_stripe_request',gateway)
    uid,vid,branch=stocked
    with factory(tenant_id=1) as db:
        db.get(User,uid).stripe_customer_id='cus_fixture'
        card=SavedCard(usuario_id=uid,stripe_payment_method='pm_fixture',setup_intent='seti_fixture',marca='visa',ultimos_cuatro='4242',mes_vencimiento=12,anio_vencimiento=2032)
        db.add(card);db.commit();gateway.card=card.id
    return gateway


def body(stocked,provider,**extra):
    return {'operacion_id':str(uuid4()),'items':[{'variante_id':stocked[1],'cantidad':3}],'tipo_entrega':'RECOJO','sucursal_id':stocked[2],
        'tarjeta_id':provider.card,'autorizar_cobro_automatico':True,'total_autorizado':'300.00','creado_en_dispositivo':datetime.now(timezone.utc).isoformat(),**extra}


def submit(client,stocked,payload):return client.post('/api/v1/payments/deferred',headers=headers(stocked[0]),json=payload)


@pytest.mark.parametrize('mode',['success','lost_response'])
def test_saved_card_purchase_is_paid_once_after_lost_reply(client,factory,stocked,provider,mode):
    provider.mode=mode;payload=body(stocked,provider)
    first=submit(client,stocked,payload)
    assert first.status_code==201,first.text
    assert first.json()['estado']=='PAGADA',first.text
    again=submit(client,stocked,payload)
    assert again.json()['pedido_id']==first.json()['pedido_id'] and provider.charges==1 and provider.creates==1
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,stocked[1]).stock_total==9
        assert db.scalar(select(func.count(Order.id)))==1
        assert db.scalar(select(Cart).where(Cart.usuario_id==stocked[0])).estado=='CONVERTIDO'
    assert submit(client,stocked,{**payload,'total_autorizado':'299.00'}).status_code==409


def test_decline_cancels_and_restores_branch_stock_once(client,factory,stocked,provider):
    provider.mode='decline';payload=body(stocked,provider)
    response=submit(client,stocked,payload)
    assert response.status_code==201,response.text
    assert response.json()['estado']=='RECHAZADA',response.text
    assert submit(client,stocked,payload).json()['estado']=='RECHAZADA'
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,stocked[1]).stock_total==12
        assert db.get(Order,response.json()['pedido_id']).estado=='CANCELADO'
        assert db.scalar(select(Cart).where(Cart.usuario_id==stocked[0])).estado=='ACTIVO'
    assert provider.charges==0


def test_no_card_waits_without_order_or_charge_and_requires_explicit_authorization(client,factory,stocked,provider):
    payload=body(stocked,provider,tarjeta_id=None,autorizar_cobro_automatico=False)
    result=submit(client,stocked,payload).json();assert result['estado']=='REQUIERE_METODO' and result['pedido_id'] is None
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(Order.id)))==0
    url='/api/v1/payments/deferred/'+payload['operacion_id']+'/method'
    assert client.post(url,headers=headers(stocked[0]),json={'tarjeta_id':provider.card,'autorizar_cobro_automatico':False}).status_code==422
    assert client.post(url,headers=headers(stocked[0]),json={'tarjeta_id':provider.card,'autorizar_cobro_automatico':True}).json()['estado']=='PAGADA'


def test_changed_price_no_stock_and_expired_snapshot_never_charge(client,factory,stocked,provider):
    response=submit(client,stocked,body(stocked,provider,total_autorizado='299.00'))
    assert response.json()['estado']=='RECHAZADA',response.text
    response=submit(client,stocked,body(stocked,provider,items=[{'variante_id':stocked[1],'cantidad':99}],total_autorizado='9900.00'))
    assert response.json()['estado']=='RECHAZADA'
    response=submit(client,stocked,body(stocked,provider,creado_en_dispositivo=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))
    assert response.json()['estado']=='VENCIDA'
    assert provider.creates==provider.charges==0
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,stocked[1]).stock_total==12
        assert db.scalar(select(func.count(Order.id)))==0


def test_3ds_waits_and_cancel_verifies_stripe_before_releasing_stock(client,factory,stocked,provider):
    provider.mode='auth';payload=body(stocked,provider)
    result=submit(client,stocked,payload).json();assert result['estado']=='REQUIERE_AUTENTICACION',result
    assert client.post('/api/v1/orders/'+str(result['pedido_id'])+'/cancel',headers=headers(stocked[0])).status_code==409
    assert client.post('/api/v1/orders/'+str(result['pedido_id'])+'/cash-confirm',headers=headers()).status_code==409
    url='/api/v1/payments/deferred/'+payload['operacion_id']+'/cancel'
    provider.unavailable=True
    result=client.post(url,headers=headers(stocked[0])).json();assert result['estado']=='PENDIENTE_RESULTADO'
    with factory(tenant_id=1) as db:assert db.get(ProductVariant,stocked[1]).stock_total==9
    provider.unavailable=False
    result=client.post(url,headers=headers(stocked[0])).json();assert result['estado']=='CANCELADA'
    client.post(url,headers=headers(stocked[0]))
    with factory(tenant_id=1) as db:assert db.get(ProductVariant,stocked[1]).stock_total==12


def test_card_and_purchase_are_private_to_user_and_tenant(client,factory,stocked,provider):
    payload=body(stocked,provider,tarjeta_id=None,autorizar_cobro_automatico=False)
    submit(client,stocked,payload)
    assert client.get('/api/v1/payments/cards',headers=headers()).status_code==403
    with factory(tenant_id=1) as db:
        row=User(nombre='Otro',email='other-card@example.com',password_hash='test',rol='CLIENTE');db.add(row);db.commit();other=row.id
    assert client.get('/api/v1/payments/deferred/'+payload['operacion_id'],headers=headers(other)).status_code==404
    assert submit(client,stocked,{**body(stocked,provider),'card_number':'4242424242424242','cvc':'123'}).status_code==422
    assert client.get('/api/v1/payments/cards',headers=headers(stocked[0])).json()==[{'id':provider.card,'marca':'visa','ultimos_cuatro':'4242','mes_vencimiento':12,'anio_vencimiento':2032}]


def test_cancel_before_lost_submission_cannot_be_charged_on_replay(client,factory,stocked,provider):
    payload=body(stocked,provider)
    response=client.post('/api/v1/payments/deferred/cancel-pending',headers=headers(stocked[0]),json=payload)
    assert response.json()['estado']=='CANCELADA',response.text
    assert submit(client,stocked,payload).json()['estado']=='CANCELADA'
    assert provider.creates==provider.charges==0
    with factory(tenant_id=1) as db:assert db.get(ProductVariant,stocked[1]).stock_total==12


def test_another_identifier_cannot_duplicate_an_unfinished_purchase(client,stocked,provider):
    provider.mode='auth';payload=body(stocked,provider)
    assert submit(client,stocked,payload).json()['estado']=='REQUIERE_AUTENTICACION'
    second={**payload,'operacion_id':str(uuid4())}
    assert submit(client,stocked,second).json()['estado']=='RECHAZADA'
    response=client.post('/api/v1/orders/checkout',headers=headers(stocked[0]),json={'tipo_entrega':'RECOJO','sucursal_id':stocked[2],'operacion_id':str(uuid4())})
    assert response.status_code==409
    assert provider.confirmations==1 and provider.charges==0


def test_setup_checks_stripe_owner_status_and_returns_only_masked_card(client,factory,stocked,provider,monkeypatch):
    from app.incrementos.incremento_iii import deferred_checkout as service
    uid=stocked[0];good=True
    def setup_call(method,path,**kwargs):
        if path=='setup_intents':return {'id':'seti_saved','client_secret':'setup_fixture'}
        if path=='setup_intents/seti_saved':return {'id':'seti_saved','customer':'cus_fixture' if good else 'cus_foreign','status':'succeeded','usage':'off_session','payment_method':'pm_second','metadata':{'tenant_id':'1','user_id':str(uid),'consent':'deferred-v1'}}
        if path=='payment_methods/pm_second':return {'id':'pm_second','type':'card','customer':'cus_fixture','card':{'brand':'visa','last4':'1881','exp_month':12,'exp_year':2032}}
        raise AssertionError(path)
    monkeypatch.setattr(service,'_stripe_request',setup_call)
    payload={'operacion_id':str(uuid4()),'aceptar_guardado_y_cobros_diferidos':False}
    assert client.post('/api/v1/payments/cards/setup',headers=headers(uid),json=payload).status_code==422
    assert client.post('/api/v1/payments/cards/setup',headers=headers(uid),json={**payload,'aceptar_guardado_y_cobros_diferidos':True}).status_code==200
    confirmation={'setup_intent_id':'seti_saved','aceptar_guardado_y_cobros_diferidos':True}
    good=False
    assert client.post('/api/v1/payments/cards/confirm',headers=headers(uid),json=confirmation).status_code==404
    good=True
    for _ in range(2):
        response=client.post('/api/v1/payments/cards/confirm',headers=headers(uid),json=confirmation)
        assert response.status_code==201 and response.json()['ultimos_cuatro']=='1881',response.text
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(SavedCard.id)))==2


@pytest.mark.parametrize('outcome',['retry','expire'])
def test_worker_reconciles_persisted_purchase_without_client(client,factory,stocked,provider,monkeypatch,outcome):
    from app.db import session
    from app.incrementos.incremento_iii.deferred_worker import tick
    monkeypatch.setattr(session,'SessionLocal',factory)
    provider.unavailable=outcome=='retry'
    provider.mode='auth' if outcome=='expire' else 'success'
    response=submit(client,stocked,body(stocked,provider))
    assert response.status_code==201
    assert response.json()['estado']==('PENDIENTE_RESULTADO' if outcome=='retry' else 'REQUIERE_AUTENTICACION')
    provider.unavailable=False
    with factory(tenant_id=1) as db:
        row=db.scalar(select(DeferredPurchase))
        row.siguiente_intento=datetime.now(timezone.utc)-timedelta(seconds=1)
        if outcome=='expire':row.vence_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        db.commit()
    tick();tick()
    with factory(tenant_id=1) as db:
        assert db.scalar(select(DeferredPurchase)).estado==('PAGADA' if outcome=='retry' else 'VENCIDA')
        assert db.get(ProductVariant,stocked[1]).stock_total==(9 if outcome=='retry' else 12)
    assert provider.charges==(1 if outcome=='retry' else 0)
