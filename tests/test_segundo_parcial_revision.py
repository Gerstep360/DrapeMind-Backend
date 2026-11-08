import base64, io, json, wave
from datetime import date
from sqlalchemy import select, func
from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from app.models import User, Order, Payment
from app.segundo_parcial.cu28_machine_learning.cu28_entrenamiento import (
    train,
    persisted_forecast,
    predict_week,
)
from app.segundo_parcial.cu28_machine_learning.cu28_modelos import DemandModel


def recording():
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 16000)
    return base64.b64encode(data.getvalue()).decode()


def test_voice_checks_audio_permission_and_purpose_before_nvidia(
    client, stocked, monkeypatch
):
    from app.segundo_parcial.compartido import voz
    from app.core.config import settings

    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-fixture")
    calls = []
    monkeypatch.setattr(
        voz,
        "recognize",
        lambda audio: calls.append(len(audio)) or "Consulta las ventas de este mes",
    )
    auth = headers(stocked[0])
    data = {"audio_wav": recording(), "proposito": "ALTAIR"}
    response = client.post("/api/v1/voice/transcribe", headers=auth, json=data)
    assert response.status_code == 200 and response.json()["requiere_revision"]
    assert response.headers["cache-control"] == "no-store" and calls == [32000]
    assert (
        client.post(
            "/api/v1/voice/transcribe",
            headers=auth,
            json={**data, "proposito": "REPORTE"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/voice/transcribe",
            headers=auth,
            json={**data, "audio_wav": "x" * 80},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/voice/transcribe", headers=auth, json={**data, "tenant_id": 2}
        ).status_code
        == 422
    )
    assert calls == [32000]


def test_forest_is_trained_without_future_data_and_survives_json_roundtrip():
    values = [1 if i % 7 < 5 else 15 for i in range(112)]
    start = date(2026, 1, 5)
    result, artifact = train(values, start)
    assert (
        "Random Forest" in result["modelos_evaluados"]
        and len(artifact["arboles"]) == 96
    )
    assert result["validacion"]["mae_random_forest"] < result["validacion"]["mae_base"]
    restored = json.loads(json.dumps(artifact))
    assert predict_week(restored, values, start) == predict_week(
        artifact, values, start
    )
    assert len(result["predicciones"]) == 7 and result["modelo"] == "Random Forest"


def test_training_is_persisted_reused_and_isolated_by_company(factory):
    values = [1 if i % 7 < 5 else 15 for i in range(70)]
    with factory(tenant_id=1) as db:
        user = db.get(User, 1)
        first = persisted_forecast(db, user, None, values, date(2026, 1, 5))
        assert (
            first["entrenamiento"]["persistido"]
            and not first["entrenamiento"]["reutilizado"]
        )
    with factory(tenant_id=1) as db:
        result = persisted_forecast(db, db.get(User, 1), None, values, date(2026, 1, 5))
        assert (
            result["entrenamiento"]["id"] == first["entrenamiento"]["id"]
            and result["entrenamiento"]["reutilizado"]
        )
        assert db.scalar(select(func.count(DemandModel.id))) == 1
    with factory(tenant_id=2) as db:
        assert db.scalar(select(func.count(DemandModel.id))) == 0
    with factory(tenant_id=1) as db:
        result = persisted_forecast(
            db, db.get(User, 1), None, values + [2], date(2026, 1, 5)
        )
        assert not result["entrenamiento"]["reutilizado"]
        assert (
            result["entrenamiento"]["huella_datos"]
            != first["entrenamiento"]["huella_datos"]
        )


def test_checkout_previews_real_branch_stock_without_mutating_order(
    client, factory, stocked
):
    response = client.get(
        "/api/v1/orders/checkout-options", headers=headers(stocked[0])
    )
    assert response.status_code == 200, response.text
    options = response.json()
    assert options["sucursales"] and options["sucursales"][-1]["disponible"]
    assert not options["vacio"] and options["compra_pendiente"] is None
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Order.id))) == 0


def test_cash_desk_card_is_pending_until_stripe_and_qr_is_not_accepted(
    client, factory, stocked
):
    payload = {
        "sucursal_id": stocked[2],
        "items": [
            {"variante_id": stocked[1], "cantidad": 1, "precio_unitario": "100.00"}
        ],
        "metodo_pago": "QR",
    }
    # Route for an authorized employee; all catalog and branch data are test fixtures.
    assert (
        client.post(
            "/api/v1/admin/sales/pos", headers=headers(), json=payload
        ).status_code
        == 422
    )
    response = client.post(
        "/api/v1/admin/sales/pos",
        headers=headers(),
        json={**payload, "metodo_pago": "TARJETA"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["pago_estado"] == "PENDIENTE"
    with factory(tenant_id=1) as db:
        order = db.get(Order, response.json()["pedido_id"])
        assert order.paid_at is None and order.estado == "PENDIENTE_PAGO"
        assert db.scalar(select(func.count(Payment.id))) == 0
