import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Order, Payment, User
from app.schemas.api import PaymentCreate, PaymentOut, PaymentWebhook
from app.services.store import confirm_payment, create_payment
from app.services.realtime import event_hub

router = APIRouter()


@router.post(
    "", response_model=PaymentOut, status_code=201, summary="Iniciar pago",
    description="CU-25. El monto se toma del pedido; el cliente nunca decide el importe.",
)
def initiate(
    payload: PaymentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Payment:
    order = db.scalar(select(Order).where(Order.id == payload.pedido_id, Order.usuario_id == current_user.id))
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    return create_payment(db, order, payload.metodo)


@router.post(
    "/webhook", response_model=PaymentOut, include_in_schema=True, summary="Webhook de confirmacion",
    description="CU-26. Endpoint de pasarela; valida HMAC SHA-256 sobre el body crudo y es idempotente.",
)
async def webhook(
    request: Request, x_webhook_signature: str = Header(alias="X-Webhook-Signature"),
    db: Session = Depends(get_db),
) -> Payment:
    body = await request.body()
    expected = hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_webhook_signature):
        raise HTTPException(401, "Firma de webhook invalida")
    try:
        payload = PaymentWebhook.model_validate(json.loads(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Payload de webhook invalido") from exc
    payment = confirm_payment(db, payload.referencia_externa, payload.estado)
    order = db.get(Order, payment.pedido_id)
    await event_hub.publish(
        {
            "type": "payment_updated",
            "payment_id": payment.id,
            "order_id": order.id,
            "status": payment.estado,
        },
        order.usuario_id,
    )
    return payment


@router.post("/{payment_id}/mock-confirm", response_model=PaymentOut, summary="Confirmar pago mock")
def mock_confirm(
    payment_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    if settings.PAYMENT_PROVIDER != "mock" or settings.ENVIRONMENT == "production":
        raise HTTPException(404, "Endpoint no disponible")
    payment = db.scalar(
        select(Payment).join(Order, Order.id == Payment.pedido_id)
        .where(Payment.id == payment_id, Order.usuario_id == current_user.id)
    )
    if not payment:
        raise HTTPException(404, "Pago no encontrado")
    payment = confirm_payment(db, payment.referencia_externa, "APROBADO")
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "payment_updated",
            "payment_id": payment.id,
            "order_id": payment.pedido_id,
            "status": payment.estado,
        },
        current_user.id,
    )
    return payment
