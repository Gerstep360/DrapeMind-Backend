from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.core.tenancy import system_scope
from app.db.session import get_db
from app.db.tenant_session import apply_database_scope
from app.models import User, Role, UserStatus
from app.models.saas import Tenant, SaaSPlan, SaaSPrice, TenantSubscription
from app.schemas.api import LoginRequest, TokenResponse
from app.services.saas import FEATURES, tenant_summary, plan_payload, validate_downgrade, aware
from app.services.saas_billing import checkout, portal, price_details, process_billing_event
from app.services.stripe_payments import verify_event

router = APIRouter()


def platform_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_platform_admin or user.tenant_id is not None:
        raise HTTPException(403, 'Solo el administrador de la plataforma puede gestionar empresas y planes')
    db.info['saas_system'] = True
    apply_database_scope(db)
    return user


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TenantInput(StrictInput):
    name: str = Field(min_length=2,max_length=150)
    slug: str = Field(min_length=2,max_length=80,pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    admin_name: str = Field(min_length=2,max_length=120)
    admin_email: EmailStr
    admin_password: str = Field(min_length=12,max_length=72)
    plan_id: int = Field(gt=0)


class TenantStateInput(StrictInput):
    active: bool


class PlanInput(StrictInput):
    name: str = Field(min_length=2,max_length=80)
    max_branches: int = Field(ge=1,le=10000)
    features: dict[str,bool]
    stripe_price_id: str | None = Field(default=None,pattern=r'^price_[A-Za-z0-9]+$')
    active: bool = True


class LicenseInput(StrictInput):
    plan_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    status: Literal['ACTIVE','TRIALING','SUSPENDED','CANCELED','EXPIRED']
    @model_validator(mode='after')
    def dates(self):
        if aware(self.ends_at) <= aware(self.starts_at): raise ValueError('El vencimiento debe ser posterior al inicio')
        return self


class CheckoutInput(StrictInput):
    plan_id: int = Field(gt=0)
    billing_interval: Literal['month','year'] = 'month'


class PriceInput(StrictInput):
    amount_minor: int = Field(gt=0,le=100000000)
    currency: Literal['bob','usd'] = 'bob'
    billing_interval: Literal['month','year']


@router.post('/platform/login',response_model=TokenResponse)
def login_platform(payload: LoginRequest, db: Session = Depends(get_db)):
    with system_scope(db):
        user = db.scalar(select(User).where(User.is_platform_admin.is_(True),User.tenant_id.is_(None),func.lower(User.email)==str(payload.email).lower()))
        if not user or user.estado != UserStatus.ACTIVO or not verify_password(payload.password,user.password_hash):
            raise HTTPException(401,'Credenciales de plataforma incorrectas')
        token, expires = create_access_token(user.id,user.rol.value,platform=True)
        return {'access_token':token,'token_type':'bearer','expires_in':expires}


@router.get('/companies')
def companies(db: Session = Depends(get_db)):
    return [{'slug':t.slug,'name':t.name} for t in db.scalars(select(Tenant).where(Tenant.active.is_(True)).order_by(Tenant.name).limit(200))]


@router.get('/me')
def my_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.tenant_id: raise HTTPException(403,'El administrador SaaS no tiene una suscripción empresarial propia')
    result = tenant_summary(db,user.tenant_id)
    tenant = db.get(Tenant,user.tenant_id)
    result['portal_available'] = bool(tenant.stripe_customer_id and result['subscription'] and result['subscription']['source']=='STRIPE')
    return result


@router.get('/plans')
def plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [plan_payload(p,private=user.is_platform_admin) for p in db.scalars(select(SaaSPlan).order_by(SaaSPlan.id))]


@router.get('/plans/{plan_id}/price')
def price(plan_id: int, interval: Literal['month','year'] = 'month', user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = db.get(SaaSPlan,plan_id)
    if not plan or not plan.active: raise HTTPException(404,'Plan no encontrado')
    details = price_details(plan,interval)
    return {'amount_minor':details['unit_amount'],'currency':details['currency'],'interval':interval}


@router.post('/checkout')
def start_checkout(payload: CheckoutInput, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    return checkout(db,user,payload.plan_id,payload.billing_interval)


@router.post('/portal')
def customer_portal(user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    return portal(db,user)


@router.post('/sync')
def sync_subscription(user: User = Depends(require_roles(Role.ADMIN)),db: Session = Depends(get_db)):
    from app.services.saas_billing import reconcile
    reconcile(db,user)
    return my_subscription(user,db)


@router.post('/stripe-webhook')
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    event = verify_event(await request.body(),request.headers.get('stripe-signature'),settings.STRIPE_SAAS_WEBHOOK_SECRET or settings.STRIPE_WEBHOOK_SECRET)
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(process_billing_event,db,event)
    return {'received':True}


@router.get('/tenants')
def list_tenants(admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    return [tenant_summary(db,t.id) for t in db.scalars(select(Tenant).order_by(Tenant.id))]


@router.post('/tenants',status_code=201)
def create_tenant(payload: TenantInput, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    if db.scalar(select(Tenant.id).where(Tenant.slug==payload.slug)): raise HTTPException(409,'El identificador de empresa ya está registrado')
    plan = db.get(SaaSPlan,payload.plan_id)
    if not plan or not plan.active: raise HTTPException(404,'Plan no encontrado')
    try:
        tenant = Tenant(name=payload.name,slug=payload.slug,active=True)
        db.add(tenant); db.flush()
        owner = User(tenant_id=tenant.id,is_platform_admin=False,nombre=payload.admin_name,email=str(payload.admin_email).lower(),password_hash=hash_password(payload.admin_password),rol=Role.ADMIN,estado=UserStatus.ACTIVO)
        db.add(owner); db.flush()
        tenant.admin_user_id = owner.id
        db.add(TenantSubscription(tenant_id=tenant.id,plan_id=plan.id,status='PENDING',source='STRIPE'))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'La empresa o su administrador ya están registrados')
    except Exception:
        db.rollback()
        raise
    return tenant_summary(db,tenant.id)


@router.patch('/tenants/{tenant_id}')
def tenant_state(tenant_id: int, payload: TenantStateInput, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant,tenant_id)
    if not tenant: raise HTTPException(404,'Empresa no encontrada')
    tenant.active = payload.active; db.commit()
    return tenant_summary(db,tenant_id)


@router.put('/plans/{plan_id}')
def update_plan(plan_id: int,payload: PlanInput,admin: User = Depends(platform_admin),db: Session = Depends(get_db)):
    plan = db.get(SaaSPlan,plan_id)
    if not plan: raise HTTPException(404,'Plan no encontrado')
    if set(payload.features) != set(FEATURES): raise HTTPException(422,'Debes configurar exactamente las funcionalidades admitidas')
    if payload.stripe_price_id and payload.stripe_price_id != plan.stripe_price_id:
        from types import SimpleNamespace
        details = price_details(SimpleNamespace(stripe_price_id=payload.stripe_price_id))
        registered = db.get(SaaSPrice,payload.stripe_price_id)
        if registered and registered.plan_id != plan.id: raise HTTPException(409,'Este precio pertenece a otro plan')
        if not registered: db.add(SaaSPrice(id=payload.stripe_price_id,plan_id=plan.id))
        if plan.stripe_annual_price_id and details['currency'] != plan.currency:
            raise HTTPException(409,'Los precios mensual y anual deben usar la misma moneda')
        plan.stripe_product_id = details['product']
        plan.monthly_amount_minor,plan.currency = details['unit_amount'],details['currency']
    for subscription in db.scalars(select(TenantSubscription).where(TenantSubscription.plan_id==plan.id)):
        db.scalar(select(Tenant).where(Tenant.id==subscription.tenant_id).with_for_update())
        validate_downgrade(db,subscription.tenant_id,payload)
    plan.name,plan.max_branches,plan.active,plan.stripe_price_id = payload.name,payload.max_branches,payload.active,payload.stripe_price_id
    for key,value in payload.features.items(): setattr(plan,key,value)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,'Ese precio Stripe ya está asignado a otro plan')
    return plan_payload(plan,private=True)


@router.post('/plans/{plan_id}/stripe-price')
def create_stripe_price(plan_id: int,payload: PriceInput,admin: User = Depends(platform_admin),db: Session = Depends(get_db)):
    from app.services.saas_billing import configure_plan_price
    plan=db.scalar(select(SaaSPlan).where(SaaSPlan.id==plan_id).with_for_update())
    if not plan: raise HTTPException(404,'Plan no encontrado')
    configure_plan_price(db,plan,payload.billing_interval,payload.amount_minor,payload.currency)
    return plan_payload(plan,private=True)


@router.put('/tenants/{tenant_id}/subscription')
def administrative_license(tenant_id: int,payload: LicenseInput,admin: User = Depends(platform_admin),db: Session = Depends(get_db)):
    tenant = db.scalar(select(Tenant).where(Tenant.id==tenant_id).with_for_update())
    if not tenant: raise HTTPException(404,'Empresa no encontrada')
    plan = db.get(SaaSPlan,payload.plan_id)
    if not plan or not plan.active: raise HTTPException(404,'Plan no encontrado')
    validate_downgrade(db,tenant_id,plan)
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id==tenant_id).with_for_update())
    if subscription and subscription.stripe_subscription_id: raise HTTPException(409,'Gestiona esta suscripción con Stripe para mantener cobros y acceso sincronizados')
    if not subscription: subscription = TenantSubscription(tenant_id=tenant_id,plan_id=plan.id);db.add(subscription)
    subscription.plan_id,subscription.status = plan.id,payload.status
    subscription.starts_at,subscription.ends_at,subscription.source = payload.starts_at,payload.ends_at,'ADMINISTRATIVE'
    db.commit()
    return tenant_summary(db,tenant_id)
