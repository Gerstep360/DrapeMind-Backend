"""CU-11: Procesar y confirmar pago electrónico.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Order, Payment, Role, User
from app.schemas.api import PaymentCreate, PaymentOut, PaymentWebhook
from app.services.realtime import event_hub
from app.services.store import confirm_payment, create_payment, staff_can_access_branch

logger = logging.getLogger(__name__)

from app.api.v1.endpoints.stripe_payments import router as stripe_router

router = APIRouter()
router.include_router(stripe_router)


def _can_read_payment(user: User, order: Order, db: Session) -> bool:
    return order.usuario_id == user.id or (user.rol in {
        Role.ADMIN,
        Role.VENDEDOR,
        Role.ENCARGADO,
        Role.CAJERO,
    } and staff_can_access_branch(db, user, order.sucursal_id))


@router.post(
    "",
    response_model=PaymentOut,
    status_code=201,
    summary="CU-11: Iniciar pago",
    description="CU-11. El monto se toma del pedido; el cliente nunca decide el importe.",
)
def initiate(
    payload: PaymentCreate,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=100
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    order = db.scalar(
        select(Order).where(
            Order.id == payload.pedido_id, Order.usuario_id == current_user.id
        )
    )
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    return create_payment(db, order, payload.metodo, idempotency_key)


@router.get(
    "/order/{order_id}",
    response_model=list[PaymentOut],
    summary="CU-11: Consultar pagos de un pedido",
)
def payments_for_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Payment]:
    order = db.get(Order, order_id)
    if not order or not _can_read_payment(current_user, order, db):
        raise HTTPException(404, "Pedido no encontrado")
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.pedido_id == order_id)
            .order_by(Payment.created_at.desc())
        )
    )




@router.post("/{payment_id}/mock-confirm", response_model=PaymentOut, summary="CU-11: Confirmar pago mock")
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
        .where(Payment.id == payment_id, Order.usuario_id == current_user.id, Payment.proveedor == "MOCK")
    )
    if not payment:
        raise HTTPException(404, "Pago no encontrado")
    payment = confirm_payment(db, payment.referencia_externa, "APROBADO")
    event_payload = {
        "type": "payment_updated",
        "payment_id": payment.id,
        "order_id": payment.pedido_id,
        "status": payment.estado,
    }
    background_tasks.add_task(event_hub.publish, event_payload, current_user.id)
    return payment


@router.get(
    "/{payment_id}",
    response_model=PaymentOut,
    summary="CU-11: Consultar estado de pago",
)
def get_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Pago no encontrado")
    order = db.get(Order, payment.pedido_id)
    if not order or not _can_read_payment(current_user, order, db):
        raise HTTPException(404, "Pago no encontrado")
    return payment


@router.post("/webhook", summary="CU-11: Webhook HMAC de pasarela de pago")
async def payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    x_signature = x_signature or request.headers.get("x-webhook-signature")
    if not x_signature:
        raise HTTPException(401, "Falta la firma HMAC")
    expected = hmac.new(
        settings.PAYMENT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Firma HMAC inválida")
    try:
        data = PaymentWebhook.model_validate(json.loads(raw_body.decode()))
    except ValueError as exc:
        raise HTTPException(422, "Payload de webhook inválido") from exc
    payment = db.scalar(
        select(Payment)
        .where(Payment.referencia_externa == data.referencia_externa)
        .with_for_update()
    )
    if not payment:
        raise HTTPException(404, "Transacción no encontrada")
    if payment.proveedor == "STRIPE":
        raise HTTPException(409, "Este pago requiere el webhook firmado de Stripe")
    if data.estado == "APROBADO":
        payment = confirm_payment(db, payment.referencia_externa, "APROBADO")
        order = db.get(Order, payment.pedido_id)
        if order:
            event = {
                "type": "payment_approved",
                "order_id": order.id,
                "payment_id": payment.id,
                "status": order.estado,
            }
            background_tasks.add_task(event_hub.publish, event, order.usuario_id)
            background_tasks.add_task(
                event_hub.publish, event, None, {"ADMIN", "VENDEDOR"}
            )
    return {"status": "ok", "payment_id": payment.id}


@router.post(
    "/simulate-qr-scan",
    summary="CU-11: Simular pago de QR (Solo desarrollo y demostración)",
)
def simulate_qr_payment(
    qr_data: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if settings.PAYMENT_PROVIDER != "mock" or settings.ENVIRONMENT == "production":
        raise HTTPException(404, "Endpoint no disponible")
    payment = db.scalar(
        select(Payment).join(Order, Order.id == Payment.pedido_id)
        .where(Payment.qr_payload == qr_data, Order.usuario_id == current_user.id, Payment.proveedor == "MOCK").with_for_update()
    )
    if not payment:
        raise HTTPException(404, "QR no encontrado")
    if payment.estado == "APROBADO":
        return {"status": "already_approved", "payment_id": payment.id}
    payment = confirm_payment(db, payment.referencia_externa, "APROBADO")
    order = db.get(Order, payment.pedido_id)
    if order:
        event = {
            "type": "payment_approved",
            "order_id": order.id,
            "payment_id": payment.id,
            "status": order.estado,
        }
        background_tasks.add_task(event_hub.publish, event, order.usuario_id)
        background_tasks.add_task(
            event_hub.publish, event, None, {"ADMIN", "VENDEDOR"}
        )
    return {"status": "approved", "order_id": payment.pedido_id, "payment_id": payment.id}
