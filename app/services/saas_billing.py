"""Stripe is authoritative. Redirects and client parameters never grant entitlements."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.models.saas import Tenant, SaaSPlan, SaaSPrice, TenantSubscription, BillingEvent, CheckoutAttempt
from app.services.stripe_payments import _stripe_request
from app.services.saas import validate_downgrade, aware


def stripe_ready():
    if not settings.STRIPE_SECRET_KEY.startswith(('sk_', 'rk_')):
        raise HTTPException(503, 'Configura Stripe en el backend para cobrar suscripciones. No se simula un pago real.')


def price_details(plan, interval='month'):
    stripe_ready()
    price_id = plan.stripe_price_id if interval == 'month' else plan.stripe_annual_price_id
    if not price_id:
        raise HTTPException(409, 'El administrador SaaS debe configurar el Price ID de Stripe de este plan.')
    price = _stripe_request('GET', f'prices/{price_id}')
    if not price.get('active') or price.get('recurring', {}).get('interval') != interval or price.get('recurring', {}).get('interval_count') != 1 or price.get('unit_amount') is None or price.get('currency') not in ('bob','usd'):
        raise HTTPException(409, 'El precio debe estar activo, ser mensual o anual según la modalidad, y estar en BOB o USD.')
    return price


def synchronize_checkout(db, tenant, session):
    """Recover a missed webhook using a server-fetched Checkout and subscription."""
    if session.get('customer') != tenant.stripe_customer_id or (session.get('metadata') or {}).get('tenant_id') != str(tenant.id) or session.get('client_reference_id') != str(tenant.id):
        raise HTTPException(409,'El checkout no corresponde a esta empresa')
    if session.get('status') != 'complete' or not session.get('subscription'):
        return False
    remote=_stripe_request('GET',f"subscriptions/{session['subscription']}?expand[]=latest_invoice")
    if remote.get('customer') != tenant.stripe_customer_id:
        raise HTTPException(409,'La suscripción no corresponde a esta empresa')
    synchronize(db,remote)
    db.commit()
    return True


def reconcile(db, user):
    """No charges: current Stripe state, restricted to the authenticated company."""
    stripe_ready()
    tenant=db.scalar(select(Tenant).where(Tenant.id==user.tenant_id).with_for_update())
    subscription=db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==tenant.id))
    if subscription and subscription.stripe_subscription_id:
        remote=_stripe_request('GET',f'subscriptions/{subscription.stripe_subscription_id}?expand[]=latest_invoice')
        if remote.get('customer') != tenant.stripe_customer_id:
            raise HTTPException(409,'La suscripción no corresponde a esta empresa')
        synchronize(db,remote);db.commit()
        return
    attempt=db.scalar(select(CheckoutAttempt).where(CheckoutAttempt.tenant_id==tenant.id,CheckoutAttempt.stripe_session_id.is_not(None)).order_by(CheckoutAttempt.created_at.desc()).limit(1))
    if attempt:
        session=_stripe_request('GET',f'checkout/sessions/{attempt.stripe_session_id}')
        synchronize_checkout(db,tenant,session)


def checkout(db, user, plan_id, interval='month'):
    stripe_ready()
    tenant = db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    plan = db.get(SaaSPlan, plan_id)
    if not plan or not plan.active: raise HTTPException(404, 'Plan no encontrado')
    validate_downgrade(db, tenant.id, plan)
    price = price_details(plan,interval)
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id))
    terminal_subscription_id = None
    if subscription and subscription.stripe_subscription_id:
        current = _stripe_request('GET', f'subscriptions/{subscription.stripe_subscription_id}')
        if current.get('status') not in ('canceled','incomplete_expired'):
            raise HTTPException(409, 'La empresa ya tiene una suscripción Stripe. Usa Gestionar con Stripe para cambiar o renovar sin duplicar cobros.')
        terminal_subscription_id = subscription.stripe_subscription_id
    if not tenant.stripe_customer_id:
        customer = _stripe_request('POST', 'customers', key=f'saas-customer-{tenant.id}', data={'name':tenant.name,'email':user.email,'metadata[tenant_id]':str(tenant.id)})
        tenant.stripe_customer_id = customer['id']
        db.commit()
        tenant = db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    attempt = db.scalar(select(CheckoutAttempt).where(CheckoutAttempt.tenant_id == tenant.id, CheckoutAttempt.created_at > datetime.now(timezone.utc)-timedelta(hours=23)).order_by(CheckoutAttempt.created_at.desc()).limit(1))
    if attempt and not attempt.stripe_session_id and (attempt.plan_id != plan.id or attempt.billing_interval != interval):
        raise HTTPException(409,'Hay una contratación en preparación. Reintenta la misma modalidad antes de cambiarla.')
    if attempt and attempt.stripe_session_id:
        prior = _stripe_request('GET', f'checkout/sessions/{attempt.stripe_session_id}')
        if prior.get('status') == 'complete':
            if terminal_subscription_id and prior.get('subscription') == terminal_subscription_id:
                attempt = None
            elif synchronize_checkout(db,tenant,prior):
                return {'synchronized':True,'message':'Stripe confirmó el checkout. El estado de la suscripción está actualizado.'}
            else:
                raise HTTPException(409,'Stripe todavía está confirmando la suscripción. Usa Actualizar estado para volver a consultarla.')
        if prior.get('status') == 'open':
            if attempt.plan_id == plan.id and attempt.billing_interval == interval:
                db.commit()
                return {'url':prior['url']}
            _stripe_request('POST', f"checkout/sessions/{attempt.stripe_session_id}/expire", key=f'saas-expire-{attempt.id}', data={})
        attempt = None
    if not attempt:
        attempt = CheckoutAttempt(id=str(uuid4()),tenant_id=tenant.id,plan_id=plan.id,billing_interval=interval)
        db.add(attempt)
        db.commit()
    response = _stripe_request('POST','checkout/sessions',key=f'saas-checkout-{attempt.id}',data={
        'mode':'subscription','customer':tenant.stripe_customer_id,
        'line_items[0][price]':price['id'],'line_items[0][quantity]':'1',
        'client_reference_id':str(tenant.id),'metadata[tenant_id]':str(tenant.id),
        'subscription_data[metadata][tenant_id]':str(tenant.id),
        'success_url':settings.SAAS_WEB_URL.rstrip('/')+'/subscription?checkout=returned',
        'cancel_url':settings.SAAS_WEB_URL.rstrip('/')+'/subscription?checkout=canceled'})
    attempt.stripe_session_id = response['id']
    db.commit()
    return {'url':response['url']}


def portal(db, user):
    stripe_ready()
    tenant = db.get(Tenant,user.tenant_id)
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id))
    if not tenant.stripe_customer_id or not subscription or not subscription.stripe_subscription_id:
        raise HTTPException(409, 'Esta empresa todavía no tiene una suscripción Stripe para gestionar.')
    eligible = []
    for plan in db.scalars(select(SaaSPlan).where(SaaSPlan.active.is_(True), SaaSPlan.stripe_price_id.is_not(None))):
        try: validate_downgrade(db,tenant.id,plan)
        except HTTPException: continue
        for interval in ('month','year'):
            selected = plan.stripe_price_id if interval=='month' else plan.stripe_annual_price_id
            if selected: eligible.append((plan,price_details(plan,interval)))
    config = {'business_profile[headline]':'Suscripción DrapeMind',
        'features[payment_method_update][enabled]':'true','features[invoice_history][enabled]':'true',
        'features[subscription_cancel][enabled]':'true','features[subscription_cancel][mode]':'at_period_end',
        'features[subscription_update][enabled]':'true' if eligible else 'false'}
    if eligible:
        config.update({'features[subscription_update][default_allowed_updates][0]':'price','features[subscription_update][proration_behavior]':'always_invoice'})
        groups = {}
        for plan,price in eligible: groups.setdefault(price['product'],[]).append(price['id'])
        for index,(product,prices) in enumerate(groups.items()):
            config[f'features[subscription_update][products][{index}][product]'] = product
            for position,price in enumerate(prices): config[f'features[subscription_update][products][{index}][prices][{position}]'] = price
    fingerprint = hashlib.sha256(str(sorted(config.items())).encode()).hexdigest()[:24]
    configuration = _stripe_request('POST','billing_portal/configurations',key=f'saas-portal-config-{fingerprint}',data=config)
    session = _stripe_request('POST','billing_portal/sessions',data={'customer':tenant.stripe_customer_id,'configuration':configuration['id'],'return_url':settings.SAAS_WEB_URL.rstrip('/')+'/subscription'})
    return {'url':session['url']}


def synchronize(db, remote):
    customer = remote.get('customer')
    tenant = db.scalar(select(Tenant).where(Tenant.stripe_customer_id == customer).with_for_update())
    if not tenant: return None
    from app.db.tenant_session import bind_tenant
    bind_tenant(db,tenant.id)
    if (remote.get('metadata') or {}).get('tenant_id') != str(tenant.id):
        raise HTTPException(409, 'La suscripción Stripe no coincide con la empresa registrada')
    items = remote.get('items',{}).get('data',[])
    if len(items) != 1 or items[0].get('quantity',1) != 1:
        raise HTTPException(409, 'La suscripción no corresponde a un único plan empresarial')
    price_id = items[0].get('price',{}).get('id')
    registered_price = db.get(SaaSPrice,price_id)
    plan = db.get(SaaSPlan,registered_price.plan_id) if registered_price else db.scalar(select(SaaSPlan).where(SaaSPlan.stripe_price_id == price_id))
    if not plan: raise HTTPException(409,'El precio Stripe no está asociado a un plan de esta plataforma')
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id).with_for_update())
    if subscription and subscription.stripe_subscription_id not in (None,remote['id']):
        if remote.get('status') in ('canceled','incomplete_expired'):
            return tenant.id # A late event cannot revoke the replacement contract.
        previous=_stripe_request('GET',f'subscriptions/{subscription.stripe_subscription_id}')
        if previous.get('status') not in ('canceled','incomplete_expired'):
            raise HTTPException(409,'Existe otra suscripción activa; no se sustituye automáticamente')
    if not subscription:
        subscription = TenantSubscription(tenant_id=tenant.id,plan_id=plan.id)
        db.add(subscription)
    status = remote.get('status')
    invoice = remote.get('latest_invoice')
    paid = isinstance(invoice,dict) and (invoice.get('paid') is True or invoice.get('status') == 'paid')
    # A pending plan invoice must not grant an upgrade or revoke an already paid period.
    if status == 'active' and not paid:
        if subscription.status in ('ACTIVE','TRIALING') and subscription.ends_at and aware(subscription.ends_at) > datetime.now(timezone.utc):
            subscription.stripe_subscription_id = remote['id']
            subscription.source = 'STRIPE'
            return tenant.id
        mapped = 'PENDING'
    else:
        mapped = {'active':'ACTIVE','trialing':'TRIALING','past_due':'PAST_DUE','unpaid':'UNPAID','canceled':'CANCELED','paused':'SUSPENDED','incomplete':'PENDING','incomplete_expired':'EXPIRED'}.get(status,'PENDING')
    try: validate_downgrade(db,tenant.id,plan)
    except HTTPException: mapped = 'LIMIT_EXCEEDED'
    subscription.plan_id = plan.id
    subscription.stripe_subscription_id = remote['id']
    subscription.source,subscription.status = 'STRIPE',mapped
    start = items[0].get('current_period_start') or remote.get('current_period_start')
    end = items[0].get('current_period_end') or remote.get('current_period_end')
    subscription.starts_at = datetime.fromtimestamp(start,timezone.utc) if start else None
    subscription.ends_at = datetime.fromtimestamp(end,timezone.utc) if end else None
    subscription.cancel_at_period_end = bool(remote.get('cancel_at_period_end'))
    return tenant.id


def process_billing_event(db,event):
    kind = event.get('type','')
    if kind not in {'checkout.session.completed','customer.subscription.created','customer.subscription.updated','customer.subscription.deleted','customer.subscription.paused','customer.subscription.resumed','invoice.paid','invoice.payment_failed'}:
        return False
    if not isinstance(event.get('id'),str) or not event['id']:
        raise HTTPException(422,'El evento Stripe no tiene un identificador válido')
    if db.get(BillingEvent,event.get('id')): return True
    obj = event['data']['object']
    sub_id = obj.get('id') if kind.startswith('customer.subscription.') else obj.get('subscription') or (obj.get('parent') or {}).get('subscription_details',{}).get('subscription')
    if not sub_id: return False
    stripe_ready()
    remote = _stripe_request('GET',f'subscriptions/{sub_id}?expand[]=latest_invoice')
    tenant_id = synchronize(db,remote)
    if tenant_id:
        db.add(BillingEvent(id=event['id'],event_type=kind,tenant_id=tenant_id))
        try: db.commit()
        except IntegrityError: db.rollback()  # Concurrent delivery of the same signed event.
    return True


def configure_plan_price(db, plan, interval, amount_minor=None, currency=None):
    """Create immutable Stripe prices; previous prices stay mapped for existing subscribers."""
    stripe_ready()
    amount_minor = amount_minor if amount_minor is not None else (plan.monthly_amount_minor if interval=='month' else plan.annual_amount_minor)
    currency = currency or plan.currency
    other = plan.stripe_annual_price_id if interval=='month' else plan.stripe_price_id
    if other and currency != plan.currency:
        raise HTTPException(409,'Los precios mensual y anual deben usar la misma moneda')
    if not plan.stripe_product_id:
        product = _stripe_request('POST','products',key=f'saas-product-{plan.id}',data={'name':f'DrapeMind {plan.name}','metadata[saas_plan_id]':str(plan.id)})
        plan.stripe_product_id = product['id'];db.commit()
    response = _stripe_request('POST','prices',key=f'saas-price-{plan.id}-{interval}-{currency}-{amount_minor}',data={'product':plan.stripe_product_id,'unit_amount':str(amount_minor),'currency':currency,'recurring[interval]':interval,'metadata[saas_plan_id]':str(plan.id)})
    record = db.get(SaaSPrice,response['id'])
    if not record: db.add(SaaSPrice(id=response['id'],plan_id=plan.id))
    if interval=='month': plan.stripe_price_id=response['id'];plan.monthly_amount_minor=amount_minor
    else: plan.stripe_annual_price_id=response['id'];plan.annual_amount_minor=amount_minor
    plan.currency=currency;db.commit()
    return response
