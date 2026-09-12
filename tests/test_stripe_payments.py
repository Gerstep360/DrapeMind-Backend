import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from pydantic import ValidationError
from app.main import app
from app.services import stripe_payments as service
from app.api.v1.endpoints.stripe_payments import StripeIntentRequest

class StripePaymentTests(TestCase):
    def event(self):
        return {"type": "payment_intent.succeeded", "data": {"object": {
            "id": "pi_test_fixture", "amount": 17900, "amount_received": 17900,
            "currency": "bob", "status": "succeeded", "metadata": {"payment_id": "8", "order_id": "5"}}}}

    def payment(self):
        return SimpleNamespace(id=8, pedido_id=5, monto=Decimal("179.00"), moneda="BOB",
            proveedor="STRIPE", estado="PENDIENTE", referencia_externa="pi_test_fixture",
            idempotency_key="stripe-order-5")

    def signed(self, raw, timestamp=None):
        timestamp = str(timestamp or int(time.time()))
        signature = hmac.new(b"whsec_test_fixture", timestamp.encode()+b"."+raw, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_signature_requires_configuration_and_header(self):
        for secret, header in [("", None), ("change-me", "x"), ("whsec_test_fixture", None)]:
            with self.assertRaises(HTTPException): service.verify_event(b"{}", header, secret)

    def test_raw_body_signature_and_replay_tolerance(self):
        raw = json.dumps(self.event()).encode()
        self.assertEqual(service.verify_event(raw, self.signed(raw), "whsec_test_fixture"), self.event())
        for body, signature in [(raw+b" ", self.signed(raw)), (raw, self.signed(raw, int(time.time())-301))]:
            with self.assertRaises(HTTPException): service.verify_event(body, signature, "whsec_test_fixture")

    def test_signature_supports_rotation(self):
        raw = json.dumps(self.event()).encode()
        self.assertEqual(service.verify_event(raw, self.signed(raw)+",v1=invalid", "whsec_test_fixture"), self.event())

    def test_client_cannot_supply_price(self):
        with self.assertRaises(ValidationError): StripeIntentRequest(order_id=5, amount=1)

    def test_minor_units_do_not_round_away_money(self):
        self.assertEqual(service.minor_units(Decimal("179.01")), 17901)
        for value in ["0", "-1", "1.001", "NaN"]:
            with self.assertRaises(HTTPException): service.minor_units(Decimal(value))

    def test_exact_payment_not_metadata_fallback(self):
        db = MagicMock(); db.scalar.return_value = None
        with patch.object(service, "confirm_payment") as confirm:
            self.assertIsNone(service.process_event(db, self.event()))
            confirm.assert_not_called()
        self.assertEqual(db.scalar.call_count, 1)

    def test_approval_delegates_existing_state_machine(self):
        db = MagicMock(); db.scalar.return_value = self.payment()
        with patch.object(service, "confirm_payment") as confirm:
            service.process_event(db, self.event())
            confirm.assert_called_once_with(db, "pi_test_fixture", "APROBADO")

    def test_amount_currency_and_metadata_must_match(self):
        db = MagicMock(); db.scalar.return_value = self.payment()
        for field, value in [("amount", 1), ("amount_received", 1), ("currency", "usd"), ("metadata", {"order_id": "9"})]:
            event = self.event(); event["data"]["object"][field] = value
            with patch.object(service, "confirm_payment") as confirm, self.assertRaises(HTTPException):
                service.process_event(db, event)
            confirm.assert_not_called()

    def test_card_failure_is_not_terminal(self):
        db = MagicMock(); event = self.event(); event['type'] = 'payment_intent.payment_failed'
        self.assertIsNone(service.process_event(db, event)); db.scalar.assert_not_called()

    def test_existing_intent_is_retrieved_not_created_again(self):
        db = MagicMock()
        db.scalar.side_effect = [SimpleNamespace(id=5, estado="PENDIENTE_PAGO", total=Decimal("179")), self.payment()]
        intent = self.event()["data"]["object"] | {"client_secret": "test-fixture"}
        with patch.object(service.settings, "PAYMENT_PROVIDER", "stripe"), \
             patch.object(service.settings, "STRIPE_SECRET_KEY", "sk_test_fixture"), \
             patch.object(service.settings, "STRIPE_PUBLISHABLE_KEY", "pk_test_fixture"), \
             patch.object(service.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test_fixture"), \
             patch.object(service, "_stripe_request", return_value=intent) as request:
            result = service.create_intent(db, 5, 2)
        request.assert_called_once_with("GET", "payment_intents/pi_test_fixture")
        self.assertEqual(result["amount"], 17900)

    def test_routes_registered_once(self):
        paths = [route.path for route in app.routes]
        self.assertEqual(paths.count('/api/v1/payments/stripe-intent'), 1)
        self.assertEqual(paths.count('/api/v1/payments/stripe-webhook'), 1)
