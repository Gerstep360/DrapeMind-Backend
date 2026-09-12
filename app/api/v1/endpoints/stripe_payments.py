from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Order, User
from app.services.stripe_payments import confirm_sandbox_payment, create_intent, process_event, verify_event
from app.services.realtime import event_hub

router = APIRouter()

@router.get("/config")
def payment_config():
    return {"provider": settings.PAYMENT_PROVIDER}

class StripeIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: int = Field(gt=0)

class StripeSandboxConfirmRequest(BaseModel):
    payment_id: int = Field(gt=0)

@router.post("/stripe-intent")
def stripe_intent(payload: StripeIntentRequest, response: Response,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return create_intent(db, payload.order_id, user.id)

@router.post("/stripe-sandbox-confirm")
async def stripe_sandbox_confirm(payload: StripeSandboxConfirmRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payment = confirm_sandbox_payment(db, payload.payment_id, user.id)
    order = db.get(Order, payment.pedido_id)
    await event_hub.publish({"type": "payment_updated", "payment_id": payment.id,
        "order_id": payment.pedido_id, "status": payment.estado}, order.usuario_id)
    return {
        "id": payment.id, "pedido_id": payment.pedido_id, "estado": payment.estado,
        "monto": float(payment.monto), "metodo": payment.metodo,
        "proveedor": payment.proveedor, "referencia_externa": payment.referencia_externa
    }

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    event = verify_event(await request.body(), request.headers.get("stripe-signature"), settings.STRIPE_WEBHOOK_SECRET)
    payment = await run_in_threadpool(process_event, db, event)
    if payment:
        order = db.get(Order, payment.pedido_id)
        await event_hub.publish({"type": "payment_updated", "payment_id": payment.id,
            "order_id": payment.pedido_id, "status": payment.estado}, order.usuario_id)
    return {"received": True}
