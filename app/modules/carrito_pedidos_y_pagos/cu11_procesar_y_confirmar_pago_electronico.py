"""CU-11: Procesar y confirmar pago electrónico.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
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
from app.services.realtime import event_hub
from app.services.store import confirm_payment, create_payment

router = APIRouter()


def _can_read_payment(user: User, order: Order) -> bool:
    return order.usuario_id == user.id or user.rol in {
        Role.ADMIN,
        Role.VENDEDOR,
        Role.ENCARGADO,
        Role.CAJERO,
    }


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
    if not order or not _can_read_payment(current_user, order):
        raise HTTPException(404, "Pedido no encontrado")
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.pedido_id == order_id)
            .order_by(Payment.created_at.desc())
        )
    )


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
    if not order or not _can_read_payment(current_user, order):
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
    if settings.ENVIRONMENT != "development":
        if not x_signature:
            raise HTTPException(401, "Falta la firma HMAC")
        expected = hmac.new(
            settings.WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_signature):
            raise HTTPException(401, "Firma HMAC inválida")
    data = PaymentWebhook.model_validate(json.loads(raw_body.decode()))
    payment = db.scalar(
        select(Payment)
        .where(Payment.transaccion_externa_id == data.transaccion_externa_id)
        .with_for_update()
    )
    if not payment:
        raise HTTPException(404, "Transacción no encontrada")
    if data.estado == "APROBADO":
        order = confirm_payment(
            db, payment, data.transaccion_externa_id, data.payload
        )
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
    db: Session = Depends(get_db),
) -> dict:
    payment = db.scalar(
        select(Payment).where(Payment.qr_data == qr_data).with_for_update()
    )
    if not payment:
        raise HTTPException(404, "QR no encontrado")
    if payment.estado == "APROBADO":
        return {"status": "already_approved", "payment_id": payment.id}
    order = confirm_payment(
        db,
        payment,
        f"SIM-{payment.id}",
        {"simulated": True, "method": "QR_SIMPLE"},
    )
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
    return {"status": "approved", "order_id": order.id, "payment_id": payment.id}
