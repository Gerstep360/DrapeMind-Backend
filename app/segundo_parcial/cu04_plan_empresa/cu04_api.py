from fastapi import APIRouter
from app.segundo_parcial.compartido.saas import (
    CheckoutInput,
    Depends,
    HTTPException,
    Request,
    Role,
    Session,
    Tenant,
    User,
    checkout,
    get_current_user,
    get_db,
    portal,
    process_billing_event,
    require_roles,
    settings,
    tenant_summary,
    verify_event,
)

router = APIRouter(prefix="/saas", tags=["CU-04 · plan_empresa"])


@router.get("/me")
def my_subscription(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not user.tenant_id:
        raise HTTPException(
            403, "El administrador SaaS no tiene una suscripción empresarial propia"
        )
    result = tenant_summary(db, user.tenant_id)
    tenant = db.get(Tenant, user.tenant_id)
    result["portal_available"] = bool(
        tenant.stripe_customer_id
        and result["subscription"]
        and result["subscription"]["source"] == "STRIPE"
    )
    return result


@router.post("/checkout")
def start_checkout(
    payload: CheckoutInput,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return checkout(db, user, payload.plan_id, payload.billing_interval)


@router.post("/portal")
def customer_portal(
    user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
):
    return portal(db, user)


@router.post("/sync")
def sync_subscription(
    user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
):
    from app.services.saas_billing import reconcile

    reconcile(db, user)
    return my_subscription(user, db)


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    event = verify_event(
        await request.body(),
        request.headers.get("stripe-signature"),
        settings.STRIPE_SAAS_WEBHOOK_SECRET or settings.STRIPE_WEBHOOK_SECRET,
    )
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(process_billing_event, db, event)
    return {"received": True}
