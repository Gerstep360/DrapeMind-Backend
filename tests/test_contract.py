from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.main import app


def test_cors_parser_and_normalization():
    settings = Settings(
        CORS_ORIGINS='["http://localhost:4200/","http://localhost:4200"]',
        _env_file=None,
    )
    assert settings.CORS_ORIGINS == ["http://localhost:4200"]


def test_jwt_roundtrip():
    token, expires_in = create_access_token(7, "CLIENTE")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "CLIENTE"
    assert expires_in > 0


def test_expired_jwt_is_rejected():
    expired = jwt.encode(
        {
            "sub": "7",
            "role": "CLIENTE",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(minutes=2),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(ValueError, match="expirado"):
        decode_access_token(expired)


def test_websocket_reports_invalid_auth_without_retryable_payload():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws/ai") as socket:
        socket.send_json({"type": "auth", "token": "expired-or-corrupt"})
        event = socket.receive_json()
        assert event["type"] == "error"
        assert event["code"] == "AUTH_INVALID"
        assert "iniciar sesión" in event["message"]


def test_openapi_exposes_main_use_cases():
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/auth/register",
        "/api/v1/auth/forgot-password",
        "/api/v1/catalog/products",
        "/api/v1/branches",
        "/api/v1/branches/{branch_id}/availability",
        "/api/v1/branches/products/{product_id}/availability",
        "/api/v1/cart/items",
        "/api/v1/cart/items/batch",
        "/api/v1/reservations",
        "/api/v1/orders/checkout",
        "/api/v1/payments/webhook",
        "/api/v1/payments/order/{order_id}",
        "/api/v1/ai/outfits/generate",
        "/api/v1/ai/cart/value-check",
        "/api/v1/ar/products/{product_id}/try-on-config",
        "/api/v1/ar/capabilities",
        "/api/v1/admin/metrics/ai",
    }
    assert expected.issubset(paths)


def test_no_public_role_escalation_field():
    register_schema = app.openapi()["components"]["schemas"]["RegisterRequest"]
    assert "rol" not in register_schema["properties"]


def test_ar_config_schema_exposes_fit_metrics():
    ar_schema = app.openapi()["components"]["schemas"]["ARConfig"]
    assert "size_metrics" in ar_schema["properties"]
    assert "fabric_elasticity" in ar_schema["properties"]
    assert "recommended_size" in ar_schema["properties"]
    assert "fit_category" in ar_schema["properties"]
    assert "available_variants" in ar_schema["properties"]
    assert "tracking" in ar_schema["properties"]


def test_reservation_contract_supports_branch_and_multiple_items():
    schema = app.openapi()
    reservation_create = schema["components"]["schemas"]["ReservationCreate"]["properties"]
    assert "sucursal_id" in reservation_create
    assert "items" in reservation_create
    assert "/api/v1/reservations/{reservation_id}/prepare" in schema["paths"]
    assert "/api/v1/reservations/{reservation_id}/ready" in schema["paths"]
    assert "/api/v1/reservations/{reservation_id}/convert-to-order" in schema["paths"]


def test_operational_roles_are_part_of_authenticated_user_contract():
    role_schema = app.openapi()["components"]["schemas"]["Role"]
    assert {"CLIENTE", "ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO"}.issubset(
        set(role_schema["enum"])
    )


def test_payment_creation_accepts_idempotency_key():
    operation = app.openapi()["paths"]["/api/v1/payments"]["post"]
    header_names = {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }
    assert "Idempotency-Key" in header_names


def test_forgot_password_contract():
    client = TestClient(app)
    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "inexistente@drapemind.com", "new_password": "NewPassword123!"},
    )
    assert res.status_code == 404
    assert "No existe una cuenta" in res.json()["detail"]
