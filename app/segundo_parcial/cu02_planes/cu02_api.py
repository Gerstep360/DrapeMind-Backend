from fastapi import APIRouter
from typing import Literal
from app.segundo_parcial.compartido.saas import (
    Depends,
    FEATURES,
    HTTPException,
    IntegrityError,
    PlanInput,
    PriceInput,
    SaaSPlan,
    SaaSPrice,
    Session,
    Tenant,
    TenantSubscription,
    User,
    get_current_user,
    get_db,
    plan_payload,
    platform_admin,
    price_details,
    select,
    validate_downgrade,
)

router = APIRouter(prefix="/saas", tags=["CU-02 · planes"])


@router.get("/plans")
def plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        plan_payload(p, private=user.is_platform_admin)
        for p in db.scalars(select(SaaSPlan).order_by(SaaSPlan.id))
    ]


@router.get("/plans/{plan_id}/price")
def price(
    plan_id: int,
    interval: Literal["month", "year"] = "month",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = db.get(SaaSPlan, plan_id)
    if not plan or not plan.active:
        raise HTTPException(404, "Plan no encontrado")
    details = price_details(plan, interval)
    return {
        "amount_minor": details["unit_amount"],
        "currency": details["currency"],
        "interval": interval,
    }


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    payload: PlanInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    plan = db.get(SaaSPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan no encontrado")
    if set(payload.features) != set(FEATURES):
        raise HTTPException(
            422, "Debes configurar exactamente las funcionalidades admitidas"
        )
    if payload.stripe_price_id and payload.stripe_price_id != plan.stripe_price_id:
        from types import SimpleNamespace

        details = price_details(
            SimpleNamespace(stripe_price_id=payload.stripe_price_id)
        )
        registered = db.get(SaaSPrice, payload.stripe_price_id)
        if registered and registered.plan_id != plan.id:
            raise HTTPException(409, "Este precio pertenece a otro plan")
        if not registered:
            db.add(SaaSPrice(id=payload.stripe_price_id, plan_id=plan.id))
        if plan.stripe_annual_price_id and details["currency"] != plan.currency:
            raise HTTPException(
                409, "Los precios mensual y anual deben usar la misma moneda"
            )
        plan.stripe_product_id = details["product"]
        plan.monthly_amount_minor, plan.currency = (
            details["unit_amount"],
            details["currency"],
        )
    for subscription in db.scalars(
        select(TenantSubscription).where(TenantSubscription.plan_id == plan.id)
    ):
        db.scalar(
            select(Tenant).where(Tenant.id == subscription.tenant_id).with_for_update()
        )
        validate_downgrade(db, subscription.tenant_id, payload)
    plan.name, plan.max_branches, plan.active, plan.stripe_price_id = (
        payload.name,
        payload.max_branches,
        payload.active,
        payload.stripe_price_id,
    )
    for key, value in payload.features.items():
        setattr(plan, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ese precio Stripe ya está asignado a otro plan")
    return plan_payload(plan, private=True)


@router.post("/plans/{plan_id}/stripe-price")
def create_stripe_price(
    plan_id: int,
    payload: PriceInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    from app.services.saas_billing import configure_plan_price

    plan = db.scalar(select(SaaSPlan).where(SaaSPlan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, "Plan no encontrado")
    configure_plan_price(
        db, plan, payload.billing_interval, payload.amount_minor, payload.currency
    )
    return plan_payload(plan, private=True)
