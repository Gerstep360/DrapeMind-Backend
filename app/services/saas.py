from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, func, inspect
from app.models import Branch
from app.models.saas import Tenant, SaaSPlan, TenantSubscription

FEATURES = ('products_sales', 'reservations', 'offline', 'reports', 'ai_reports')


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def subscription_state(db, tenant_id, *, lock=False):
    tenant = db.get(Tenant, tenant_id)
    stmt = select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
    if lock: stmt = stmt.with_for_update()
    subscription = db.scalar(stmt)
    plan = db.get(SaaSPlan, subscription.plan_id) if subscription else None
    now = datetime.now(timezone.utc)
    usable = bool(tenant and tenant.active and subscription and plan and plan.active and subscription.status in ('ACTIVE','TRIALING') and aware(subscription.starts_at) and aware(subscription.starts_at) <= now and aware(subscription.ends_at) and aware(subscription.ends_at) > now)
    return tenant, subscription, plan, usable


def require_active_subscription(db, tenant_id, feature=None):
    tenant, subscription, plan, usable = subscription_state(db, tenant_id)
    if not usable:
        raise HTTPException(402, {'code':'SUBSCRIPTION_REQUIRED','message':'La suscripción de la empresa no está activa. El administrador puede renovarla desde Mi suscripción.'})
    if feature and (feature not in FEATURES or not getattr(plan, feature)):
        raise HTTPException(403, {'code':'PLAN_FEATURE_REQUIRED','message':'Esta función no está incluida en el plan contratado.', 'feature':feature})
    return plan


def enforce_pending_branch_limit(db, objects):
    changes = [obj for obj in objects if isinstance(obj, Branch)]
    if not changes: return
    tenant_id = db.info.get('tenant_id')
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    plan = require_active_subscription(db, tenant_id)
    count = db.scalar(select(func.count(Branch.id)).where(Branch.activo.is_(True))) or 0
    delta = 0
    for branch in changes:
        active = branch.activo is not False
        if branch in db.new: delta += int(active)
        elif branch in db.deleted: delta -= int(active)
        else:
            history = inspect(branch).attrs.activo.history
            if history.has_changes(): delta += int(active) - int(bool(history.deleted[0]) if history.deleted else not active)
    if count + delta > plan.max_branches:
        raise HTTPException(409, {'code':'BRANCH_LIMIT','message':f'El plan {plan.name} permite {plan.max_branches} sucursales activas. Desactiva otra sucursal o cambia de plan.'})


def validate_downgrade(db, tenant_id, plan):
    count = db.scalar(select(func.count(Branch.id)).where(Branch.tenant_id == tenant_id, Branch.activo.is_(True))) or 0
    if count > plan.max_branches:
        raise HTTPException(409, f'La empresa tiene {count} sucursales activas; desactiva las necesarias antes de pasar al límite de {plan.max_branches}.')


def tenant_summary(db, tenant_id):
    tenant, subscription, plan, usable = subscription_state(db, tenant_id)
    if not tenant: raise HTTPException(404, 'Empresa no encontrada')
    count = db.scalar(select(func.count(Branch.id)).where(Branch.tenant_id == tenant_id, Branch.activo.is_(True))) or 0
    return {'tenant': {'id':tenant.id,'name':tenant.name,'slug':tenant.slug,'active':tenant.active,'is_demo':tenant.is_demo},
            'subscription': None if not subscription else {'id':subscription.id,'status':subscription.status,'starts_at':subscription.starts_at,'ends_at':subscription.ends_at,'source':subscription.source,'cancel_at_period_end':subscription.cancel_at_period_end},
            'plan': None if not plan else plan_payload(plan), 'access_active':usable,'active_branches':count}


def plan_payload(plan, private=False):
    result = {'id':plan.id,'code':plan.code,'name':plan.name,'max_branches':plan.max_branches,'features':{key:getattr(plan,key) for key in FEATURES},'active':plan.active,'checkout_available':bool(plan.stripe_price_id),'annual_checkout_available':bool(plan.stripe_annual_price_id),'monthly_amount_minor':plan.monthly_amount_minor,'annual_amount_minor':plan.annual_amount_minor,'currency':plan.currency}
    if private: result.update(stripe_price_id=plan.stripe_price_id,stripe_annual_price_id=plan.stripe_annual_price_id)
    return result
