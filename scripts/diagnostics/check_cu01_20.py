"""Prueba integral del alcance CU-01..CU-20 contra PostgreSQL.

Requiere una base migrada y sembrada. No inicia Gemma ni necesita Docker.
"""

from starlette.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models import Reservation


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def run() -> None:
    client = TestClient(app)
    customer = _login(client, "cliente@drapemind.com", "Cliente12345!")
    manager = _login(client, "encargado@drapemind.com", "Encargado12345!")
    cashier = _login(client, "cajero@drapemind.com", "Cajero12345!")

    branches = client.get("/api/v1/branches").json()
    central = next(branch for branch in branches if branch["codigo"] == "SCZ-CENTRAL")
    stock = client.get(f"/api/v1/branches/{central['id']}/availability?con_stock=true").json()
    assert len(stock) >= 2

    reservation_response = client.post(
        "/api/v1/reservations",
        headers=customer,
        json={
            "sucursal_id": central["id"],
            "items": [
                {"variante_id": stock[0]["variante_id"], "cantidad": 1},
                {"variante_id": stock[1]["variante_id"], "cantidad": 1},
            ],
            "observacion": "Prueba integral automatizada",
        },
    )
    reservation_response.raise_for_status()
    reservation = reservation_response.json()
    reservation_id = reservation["id"]

    detail = client.get(f"/api/v1/reservations/{reservation_id}", headers=customer)
    detail.raise_for_status()
    assert len(detail.json()["items"]) == 2
    qr_image = client.get(f"/api/v1/reservations/{reservation_id}/qr", headers=customer)
    qr_image.raise_for_status()
    assert qr_image.headers["content-type"] == "image/png"

    prepared = client.post(f"/api/v1/reservations/{reservation_id}/prepare", headers=manager)
    prepared.raise_for_status()
    assert prepared.json()["estado"] == "EN_PREPARACION"
    ready = client.post(f"/api/v1/reservations/{reservation_id}/ready", headers=manager)
    ready.raise_for_status()
    assert ready.json()["estado"] == "LISTA"

    with SessionLocal() as db:
        qr_token = str(db.get(Reservation, reservation_id).qr_token)
    checked_in = client.post(
        "/api/v1/reservations/validate-qr",
        headers=cashier,
        json={"qr_token": qr_token},
    )
    checked_in.raise_for_status()
    assert checked_in.json()["estado"] == "RETIRADA"

    converted = client.post(
        f"/api/v1/reservations/{reservation_id}/convert-to-order",
        headers=cashier,
    )
    converted.raise_for_status()
    order = converted.json()
    assert order["sucursal_id"] == central["id"]

    payment_headers = {**customer, "Idempotency-Key": f"cu20-order-{order['id']}"}
    first_payment = client.post(
        "/api/v1/payments",
        headers=payment_headers,
        json={"pedido_id": order["id"], "metodo": "QR"},
    )
    first_payment.raise_for_status()
    repeated_payment = client.post(
        "/api/v1/payments",
        headers=payment_headers,
        json={"pedido_id": order["id"], "metodo": "QR"},
    )
    repeated_payment.raise_for_status()
    assert first_payment.json()["id"] == repeated_payment.json()["id"]

    confirmed = client.post(
        f"/api/v1/payments/{first_payment.json()['id']}/mock-confirm",
        headers=customer,
    )
    confirmed.raise_for_status()
    assert confirmed.json()["estado"] == "APROBADO"

    ar_config = client.get(f"/api/v1/ar/products/{stock[0]['producto_id']}/try-on-config")
    ar_config.raise_for_status()
    assert ar_config.json()["available_variants"]
    print(
        "CU-01..CU-20 OK:",
        f"reserva={reservation_id}",
        f"pedido={order['id']}",
        f"pago={first_payment.json()['id']}",
    )


if __name__ == "__main__":
    run()
