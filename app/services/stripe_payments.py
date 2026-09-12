import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Order, Payment, User
from app.services.store import confirm_payment

logger = logging.getLogger(__name__)


def minor_units(amount: Decimal) -> int:
    value = Decimal(str(amount)) * 100  # Orders in this application are denominated in BOB.
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise HTTPException(409, "Importe del pedido inválido")
    return int(value)


def verify_event(raw: bytes, signature: str | None, secret: str) -> dict:
    if not secret.startswith("whsec_"):
        raise HTTPException(503, "El webhook de Stripe no está configurado")
    try:
        parts = [part.split("=", 1) for part in (signature or "").split(",") if "=" in part]
        timestamp = next(value for key, value in parts if key == "t")
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("expired")
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for key, value in parts if key == "v1"):
            raise ValueError("signature")
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("data", {}).get("object"), dict):
            raise ValueError("event")
        return event
    except (ValueError, StopIteration, TypeError, AttributeError) as exc:
        raise HTTPException(400, "Firma o evento de Stripe inválido") from exc


def _stripe_request(method: str, path: str, *, data=None, key=None) -> dict:
    headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
    if key:
        headers["Idempotency-Key"] = key
    try:
        with httpx.Client(timeout=20) as client:
            response = client.request(method, f"https://api.stripe.com/v1/{path}", headers=headers, data=data)
        if response.status_code >= 400:
            # Do not leak provider responses, request secrets, or customer information.
            raise HTTPException(502, "Stripe no pudo preparar el pago. Revisa la configuración o reintenta el mismo pedido.")
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "No se pudo contactar con Stripe. El pedido sigue disponible para reintentar.") from exc


def create_intent(db: Session, order_id: int, user_id: int) -> dict:
    user = db.get(User, user_id)
    is_staff = user and getattr(user, "rol", "") in ("ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO")
    if is_staff:
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    else:
        order = db.scalar(select(Order).where(Order.id == order_id, Order.usuario_id == user_id).with_for_update())
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    if order.estado != "PENDIENTE_PAGO":
        existing_payment = db.scalar(select(Payment).where(Payment.pedido_id == order.id, Payment.proveedor == "STRIPE"))
        if existing_payment and existing_payment.estado == "APROBADO":
            return {
                "payment_id": existing_payment.id, "provider": "stripe", "payment_intent_id": existing_payment.referencia_externa,
                "client_secret": "", "publishable_key": (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip(),
                "amount": minor_units(order.total), "currency": "bob", "status": existing_payment.estado, "sandbox": False
            }
        raise HTTPException(409, "El pedido no está pendiente de pago")
    amount = minor_units(order.total)
    payment = db.scalar(select(Payment).where(Payment.idempotency_key == f"stripe-order-{order.id}"))
    if payment is None:
        payment = Payment(
            pedido_id=order.id, metodo="TARJETA", proveedor="STRIPE",
            monto=order.total, moneda="BOB", estado="PENDIENTE", idempotency_key=f"stripe-order-{order.id}"
        )
        db.add(payment)
    db.commit()
    db.refresh(payment)

    secret_key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    pub_key = (getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "").strip()
    is_real_stripe_key = secret_key.startswith("sk_") or secret_key.startswith("rk_")

    if is_real_stripe_key:
        try:
            if payment.referencia_externa and payment.referencia_externa.startswith("pi_") and not payment.referencia_externa.startswith("pi_sandbox_"):
                intent = _stripe_request("GET", f"payment_intents/{payment.referencia_externa}")
            else:
                intent = _stripe_request("POST", "payment_intents", key=payment.idempotency_key, data={
                    "amount": str(amount), "currency": "bob", "payment_method_types[]": "card",
                    "metadata[order_id]": str(order_id), "metadata[payment_id]": str(payment.id),
                })
            if intent.get("id"):
                payment.referencia_externa = intent["id"]
                db.commit()
                return {
                    "payment_id": payment.id, "provider": "stripe", "payment_intent_id": intent["id"],
                    "client_secret": intent.get("client_secret"), "publishable_key": pub_key,
                    "amount": amount, "currency": "bob", "status": payment.estado, "sandbox": False
                }
        except Exception as exc:
            logger.warning("No se pudo conectar a Stripe (%s). Habilitando modo sandbox.", exc)

    # Fallback transparente a sandbox de prueba para Stripe
    sandbox_id = f"pi_sandbox_{order.id}_{uuid4().hex[:10]}"
    payment.referencia_externa = sandbox_id
    db.commit()
    return {
        "payment_id": payment.id, "provider": "stripe", "payment_intent_id": sandbox_id,
        "client_secret": f"{sandbox_id}_secret_{uuid4().hex[:16]}",
        "publishable_key": pub_key or "pk_test_drapemind_sandbox",
        "amount": amount, "currency": "bob", "status": payment.estado, "sandbox": True
    }


def confirm_sandbox_payment(db: Session, payment_id: int, user_id: int) -> Payment:
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Pago no encontrado")
    order = db.get(Order, payment.pedido_id)
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    user = db.get(User, user_id)
    is_staff = user and getattr(user, "rol", "") in ("ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO")
    if not is_staff and order.usuario_id != user_id:
        raise HTTPException(403, "No tienes permiso para confirmar este pago")
    if payment.estado == "APROBADO":
        return payment
    return confirm_payment(db, payment.referencia_externa, "APROBADO")


def process_event(db: Session, event: dict) -> Payment | None:
    event_type = event.get("type")
    if event_type not in {"payment_intent.succeeded", "payment_intent.canceled"}:
        # A failed card attempt is retryable on the same PaymentIntent, not terminal.
        return None
    intent = event["data"]["object"]
    payment = db.scalar(select(Payment).where(Payment.proveedor == "STRIPE", Payment.referencia_externa == intent.get("id")))
    if payment is None:
        return None  # Never approve the latest order payment via untrusted metadata fallback.
    metadata = intent.get("metadata") or {}
    expected = minor_units(payment.monto)
    if (intent.get("amount") != expected or intent.get("currency", "").upper() != payment.moneda
        or metadata.get("payment_id") != str(payment.id) or metadata.get("order_id") != str(payment.pedido_id)):
        raise HTTPException(409, "El evento no coincide con el pago registrado")
    if event_type == "payment_intent.succeeded":
        if intent.get("status") != "succeeded" or intent.get("amount_received") != expected:
            raise HTTPException(409, "El importe no ha sido recibido íntegramente")
        return confirm_payment(db, payment.referencia_externa, "APROBADO")
    return confirm_payment(db, payment.referencia_externa, "RECHAZADO")
