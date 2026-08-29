import hashlib
import hmac
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Order, Payment, Role, User
from app.schemas.api import PaymentCreate, PaymentOut, PaymentWebhook
from app.services.store import confirm_payment, create_payment
from app.services.realtime import event_hub

router = APIRouter()


def _can_read_payment(user: User, order: Order) -> bool:
    return order.usuario_id == user.id or user.rol in {
        Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO,
    }


@router.post(
    "", response_model=PaymentOut, status_code=201, summary="Iniciar pago",
    description="CU-25. El monto se toma del pedido; el cliente nunca decide el importe.",
)
def initiate(
    payload: PaymentCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    order = db.scalar(select(Order).where(Order.id == payload.pedido_id, Order.usuario_id == current_user.id))
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    return create_payment(db, order, payload.metodo, idempotency_key)


@router.get("/order/{order_id}", response_model=list[PaymentOut], summary="Consultar pagos de un pedido")
def payments_for_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Payment]:
    order = db.get(Order, order_id)
    if not order or not _can_read_payment(current_user, order):
        raise HTTPException(404, "Pedido no encontrado")
    return list(
        db.scalars(select(Payment).where(Payment.pedido_id == order_id).order_by(Payment.created_at.desc()))
    )


@router.get("/{payment_id}", response_model=PaymentOut, summary="Consultar estado de pago")
def get_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    payment = db.get(Payment, payment_id)
    order = db.get(Order, payment.pedido_id) if payment else None
    if not payment or not order or not _can_read_payment(current_user, order):
        raise HTTPException(404, "Pago no encontrado")
    return payment


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
