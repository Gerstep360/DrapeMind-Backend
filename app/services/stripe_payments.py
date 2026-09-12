"""Stripe transport and validation. Never accept amount or success from a client."""
import hashlib
import hmac
import json
import time
from decimal import Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Order, Payment
from app.services.store import confirm_payment


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
    if (settings.PAYMENT_PROVIDER != "stripe" or not settings.STRIPE_SECRET_KEY.startswith("sk_")
        or not settings.STRIPE_PUBLISHABLE_KEY.startswith("pk_") or not settings.STRIPE_WEBHOOK_SECRET.startswith("whsec_")):
        raise HTTPException(503, "Pago con Stripe no configurado")
    order = db.scalar(select(Order).where(Order.id == order_id, Order.usuario_id == user_id).with_for_update())
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, "El pedido no está pendiente de pago")
    amount = minor_units(order.total)
    payment = db.scalar(select(Payment).where(Payment.idempotency_key == f"stripe-order-{order.id}"))
    if payment is None:
        payment = Payment(pedido_id=order.id, metodo="TARJETA", proveedor="STRIPE",
            monto=order.total, moneda="BOB", estado="PENDIENTE", idempotency_key=f"stripe-order-{order.id}")
        db.add(payment)
    if (payment.proveedor != "STRIPE" or payment.pedido_id != order.id or payment.moneda != "BOB"
        or payment.estado != "PENDIENTE" or minor_units(payment.monto) != amount):
        raise HTTPException(409, "El pago requiere conciliación antes de volver a cobrar")
    # Persist the draft BEFORE HTTP: retries use the same metadata and idempotency key,
    # even after a network timeout/process restart. Never hold DB locks during HTTP.
    db.commit()
    db.refresh(payment)
    if payment.referencia_externa:
        intent = _stripe_request("GET", f"payment_intents/{payment.referencia_externa}")
    else:
        intent = _stripe_request("POST", "payment_intents", key=payment.idempotency_key, data={
            "amount": str(amount), "currency": "bob", "payment_method_types[]": "card",
            "metadata[order_id]": str(order_id), "metadata[payment_id]": str(payment.id),
        })
    if intent.get("amount") != amount or intent.get("currency") != "bob" or not str(intent.get("id", "")).startswith("pi_"):
        raise HTTPException(502, "Stripe devolvió un intento incompatible con el pedido")
    payment.referencia_externa = intent["id"]
    db.commit()
    return {"payment_id": payment.id, "provider": "stripe", "payment_intent_id": intent["id"],
        "client_secret": intent.get("client_secret"), "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        "amount": amount, "currency": "bob", "status": payment.estado}


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
