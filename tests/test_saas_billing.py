from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_saas_isolation import factory
from app.models import User, Branch
from app.models.saas import SaaSPlan, SaaSPrice, Tenant, TenantSubscription, BillingEvent, CheckoutAttempt
from app.services import saas_billing as billing
from app.core.config import settings


@pytest.fixture
def billing_db(factory,monkeypatch):
    monkeypatch.setattr(settings,'STRIPE_SECRET_KEY','sk_test_fixture')
    with factory(tenant_id=1) as db:
        tenant=db.get(Tenant,1);tenant.stripe_customer_id='cus_A'
        for id in (1,2):
            plan=db.get(SaaSPlan,id);plan.stripe_price_id=f'price_month{id}';plan.stripe_annual_price_id=f'price_year{id}'
            db.add_all([SaaSPrice(id=plan.stripe_price_id,plan_id=id),SaaSPrice(id=plan.stripe_annual_price_id,plan_id=id)])
        db.commit()
        yield db


def remote(**changes):
    now=datetime.now(timezone.utc)
    value={'id':'sub_A','customer':'cus_A','metadata':{'tenant_id':'1'},'status':'active','cancel_at_period_end':False,'latest_invoice':{'paid':True,'status':'paid'},'items':{'data':[{'quantity':1,'price':{'id':'price_year2'},'current_period_start':int(now.timestamp()),'current_period_end':int((now+timedelta(days=365)).timestamp())}]}}
    value.update(changes);return value


def test_paid_annual_license_uses_stripe_period_and_deduplicates(billing_db,monkeypatch):
    db=billing_db
    api=Mock(return_value=remote());monkeypatch.setattr(billing,'_stripe_request',api)
    event={'id':'evt_paid','type':'invoice.paid','data':{'object':{'subscription':'sub_A'}}}
    assert billing.process_billing_event(db,event)
    sub=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    assert sub.status=='ACTIVE' and sub.plan_id==2 and sub.source=='STRIPE'
    assert sub.ends_at-sub.starts_at==timedelta(days=365)
    assert db.get(BillingEvent,'evt_paid')
    assert billing.process_billing_event(db,event)
    assert api.call_count==1


def test_unpaid_upgrade_preserves_existing_plan_but_tracks_subscription(billing_db):
    db=billing_db
    before=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    end=before.ends_at
    billing.synchronize(db,remote(latest_invoice={'paid':False,'status':'open'}));db.commit()
    assert before.plan_id==1 and before.status=='ACTIVE' and before.ends_at==end
    assert before.stripe_subscription_id=='sub_A'


def test_out_of_order_old_invoice_retrieves_current_cancellation(billing_db,monkeypatch):
    api=Mock(return_value=remote(status='canceled'));monkeypatch.setattr(billing,'_stripe_request',api)
    assert billing.process_billing_event(billing_db,{'id':'evt_old','type':'invoice.paid','data':{'object':{'parent':{'subscription_details':{'subscription':'sub_A'}}}}})
    sub=billing_db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    assert sub.status=='CANCELED'
    assert api.call_args.args[1]=='subscriptions/sub_A?expand[]=latest_invoice'


def test_cross_company_metadata_and_multiple_items_are_rejected(billing_db):
    for payload in [remote(metadata={'tenant_id':'2'}),remote(items={'data':[]}),remote(customer='cus_A',items={'data':[{'quantity':2,'price':{'id':'price_year2'}}]})]:
        with pytest.raises(HTTPException) as error:billing.synchronize(billing_db,payload)
        assert error.value.status_code==409
        billing_db.rollback()


def test_interval_mismatch_and_unregistered_price_are_rejected(billing_db,monkeypatch):
    monkeypatch.setattr(billing,'_stripe_request',Mock(return_value={'active':True,'unit_amount':9900,'currency':'bob','recurring':{'interval':'month','interval_count':1}}))
    with pytest.raises(HTTPException):billing.price_details(billing_db.get(SaaSPlan,1),'year')
    value=remote();value['items']['data'][0]['price']['id']='price_unknown'
    with pytest.raises(HTTPException):billing.synchronize(billing_db,value)


def test_existing_subscription_cannot_create_duplicate_checkout(billing_db,monkeypatch):
    sub=billing_db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1));sub.stripe_subscription_id='sub_A';billing_db.commit()
    api=Mock(side_effect=[{'id':'price_month1','active':True,'unit_amount':9900,'currency':'bob','recurring':{'interval':'month','interval_count':1}},{'status':'active'}]);monkeypatch.setattr(billing,'_stripe_request',api)
    with pytest.raises(HTTPException) as error:billing.checkout(billing_db,billing_db.get(User,1),1)
    assert error.value.status_code==409
    assert all(call.args[0]=='GET' for call in api.call_args_list)


def test_new_immutable_price_keeps_old_mapping(billing_db,monkeypatch):
    plan=billing_db.get(SaaSPlan,1);plan.stripe_product_id='prod_A'
    api=Mock(return_value={'id':'price_new'});monkeypatch.setattr(billing,'_stripe_request',api)
    billing.configure_plan_price(billing_db,plan,'month',10900,'bob')
    assert plan.stripe_price_id=='price_new' and plan.monthly_amount_minor==10900
    assert billing_db.get(SaaSPrice,'price_month1').plan_id==1
    assert billing_db.get(SaaSPrice,'price_new').plan_id==1
    assert api.call_args.kwargs['data']['recurring[interval]']=='month'


def test_signed_event_without_id_cannot_be_acknowledged_as_processed(billing_db):
    with pytest.raises(HTTPException) as error:billing.process_billing_event(billing_db,{'type':'invoice.paid'})
    assert error.value.status_code==422


def test_completed_paid_checkout_recovers_without_waiting_for_missing_webhook(billing_db,monkeypatch):
    db=billing_db
    db.add(CheckoutAttempt(id='completed',tenant_id=1,plan_id=2,billing_interval='year',stripe_session_id='cs_done'));db.commit()
    session={'id':'cs_done','status':'complete','payment_status':'paid','customer':'cus_A','client_reference_id':'1','metadata':{'tenant_id':'1'},'subscription':'sub_A'}
    price={'id':'price_year2','active':True,'unit_amount':249000,'currency':'bob','recurring':{'interval':'year','interval_count':1}}
    snapshot=remote(latest_invoice={'status':'paid','amount_paid':249000}) # Current Stripe versions omit the legacy paid boolean.
    api=Mock(side_effect=[price,session,snapshot]);monkeypatch.setattr(billing,'_stripe_request',api)
    result=billing.checkout(db,db.get(User,1),2,'year')
    assert result['synchronized'] is True and 'url' not in result
    sub=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    assert sub.source=='STRIPE' and sub.status=='ACTIVE' and sub.plan_id==2
    assert all(call.args[0]=='GET' for call in api.call_args_list) # Recovery never creates another charge or checkout.


def test_reconciliation_rejects_another_customer_even_with_stored_checkout(billing_db,monkeypatch):
    db=billing_db;db.add(CheckoutAttempt(id='wrong',tenant_id=1,plan_id=1,stripe_session_id='cs_wrong'));db.commit()
    monkeypatch.setattr(billing,'_stripe_request',Mock(return_value={'status':'complete','customer':'cus_B','subscription':'sub_B','client_reference_id':'1','metadata':{'tenant_id':'1'}}))
    with pytest.raises(HTTPException):billing.reconcile(db,db.get(User,1))
    sub=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    assert sub.stripe_subscription_id is None


def test_canceled_contract_can_be_replaced_and_late_old_event_cannot_revoke_it(billing_db,monkeypatch):
    db=billing_db;sub=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1))
    sub.stripe_subscription_id='sub_old';sub.status='CANCELED';db.commit()
    api=Mock(return_value={'status':'canceled'});monkeypatch.setattr(billing,'_stripe_request',api)
    billing.synchronize(db,remote());db.commit()
    assert sub.stripe_subscription_id=='sub_A' and sub.status=='ACTIVE'
    billing.synchronize(db,remote(id='sub_old',status='canceled'));db.commit()
    assert sub.stripe_subscription_id=='sub_A' and sub.status=='ACTIVE'
    assert api.call_count==1


def test_canceled_checkout_does_not_prevent_starting_a_new_contract(billing_db,monkeypatch):
    db=billing_db;sub=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==1));sub.stripe_subscription_id='sub_old';sub.status='CANCELED'
    db.add(CheckoutAttempt(id='old',tenant_id=1,plan_id=1,stripe_session_id='cs_old'));db.commit()
    price={'id':'price_month1','active':True,'unit_amount':9900,'currency':'bob','recurring':{'interval':'month','interval_count':1}}
    api=Mock(side_effect=[price,{'status':'canceled'},{'status':'complete','subscription':'sub_old'},{'id':'cs_new','url':'https://checkout.stripe.com/new'}]);monkeypatch.setattr(billing,'_stripe_request',api)
    assert billing.checkout(db,db.get(User,1),1)['url']=='https://checkout.stripe.com/new'
    assert api.call_args.args==('POST','checkout/sessions')
