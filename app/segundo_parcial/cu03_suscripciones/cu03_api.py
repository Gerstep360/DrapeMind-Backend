from fastapi import APIRouter
from app.segundo_parcial.compartido.saas import (
    Depends,
    HTTPException,
    LicenseInput,
    SaaSPlan,
    Session,
    Tenant,
    TenantSubscription,
    User,
    get_db,
    platform_admin,
    select,
    tenant_summary,
    validate_downgrade,
)

router = APIRouter(prefix="/saas", tags=["CU-03 · suscripciones"])


@router.put("/tenants/{tenant_id}/subscription")
def administrative_license(
    tenant_id: int,
    payload: LicenseInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if not tenant:
        raise HTTPException(404, "Empresa no encontrada")
    plan = db.get(SaaSPlan, payload.plan_id)
    if not plan or not plan.active:
        raise HTTPException(404, "Plan no encontrado")
    validate_downgrade(db, tenant_id, plan)
    subscription = db.scalar(
        select(TenantSubscription)
        .where(TenantSubscription.tenant_id == tenant_id)
        .with_for_update()
    )
    if subscription and subscription.stripe_subscription_id:
        raise HTTPException(
            409,
            "Gestiona esta suscripción con Stripe para mantener cobros y acceso sincronizados",
        )
    if not subscription:
        subscription = TenantSubscription(tenant_id=tenant_id, plan_id=plan.id)
        db.add(subscription)
    subscription.plan_id, subscription.status = plan.id, payload.status
    subscription.starts_at, subscription.ends_at, subscription.source = (
        payload.starts_at,
        payload.ends_at,
        "ADMINISTRATIVE",
    )
    db.commit()
    return tenant_summary(db, tenant_id)
