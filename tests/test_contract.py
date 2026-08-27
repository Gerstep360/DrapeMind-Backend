from app.core.config import Settings
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


def test_openapi_exposes_main_use_cases():
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/auth/register",
        "/api/v1/catalog/products",
        "/api/v1/cart/items",
        "/api/v1/cart/items/batch",
        "/api/v1/reservations",
        "/api/v1/orders/checkout",
        "/api/v1/payments/webhook",
        "/api/v1/ai/outfits/generate",
        "/api/v1/ai/cart/value-check",
        "/api/v1/ar/products/{product_id}/try-on-config",
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

