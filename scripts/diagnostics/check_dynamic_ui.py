"""Real NVIDIA chat verification for server-owned prefabricated UI; temporary QA user."""

import asyncio
import json
import secrets
from uuid import uuid4
from decimal import Decimal

import httpx
import websockets
from sqlalchemy import delete, select
from app.db.session import SessionLocal
from app.models import Product, ProductVariant, User


async def ask(socket, message, identity, session=None):
    await socket.send(
        json.dumps(
            {
                "type": "chat",
                "request_id": identity,
                "message": message,
                "session_id": session,
            }
        )
    )
    async with asyncio.timeout(135):
        while True:
            event = json.loads(await socket.recv())
            if event.get("request_id") != identity:
                continue
            if event["type"] == "error":
                raise RuntimeError(event.get("message"))
            if event["type"] == "done":
                return event


async def main():
    with SessionLocal() as db:
        products = list(
            db.scalars(
                select(Product)
                .where(Product.activo.is_(True))
                .order_by(Product.id)
                .limit(2)
            )
        )
        assert len(products) == 2, (
            "Se necesitan dos productos reales; no se insertan productos de prueba."
        )
        ids = [p.id for p in products]
        prices = {p.nombre: f"Bs {Decimal(str(p.precio)):,.2f}" for p in products}
        variant = db.scalar(
            select(ProductVariant)
            .where(
                ProductVariant.producto_id == ids[0], ProductVariant.activo.is_(True)
            )
            .limit(1)
        )
        variant_id = variant.id if variant else None
    user_id = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/api/v1", timeout=20
    ) as client:
        try:
            credentials = {
                "email": f"qa-genui-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
            }
            response = await client.post(
                "/auth/register",
                json={**credentials, "nombre": "Verificación de componentes"},
            )
            response.raise_for_status()
            user_id = response.json()["id"]
            response = await client.post("/auth/login", json=credentials)
            response.raise_for_status()
            async with websockets.connect(
                "ws://127.0.0.1:8000/api/v1/ws/ai", origin="http://localhost:4200"
            ) as socket:
                await socket.send(
                    json.dumps(
                        {"type": "auth", "token": response.json()["access_token"]}
                    )
                )
                assert json.loads(await socket.recv())["type"] == "connected"
                comparison = await ask(
                    socket,
                    f"Compara las prendas con ID {ids[0]} e ID {ids[1]}. Consulta compare_products y muestra un componente de comparación, sin tabla ASCII.",
                    "compare",
                )
                table = next(
                    b
                    for b in comparison["ui_blocks"]
                    if b["type"] == "data_table"
                    and b["source_tool"] == "compare_products"
                )
                assert len(table["rows"]) == 2
                assert all(prices[row["name"]] == row["price"] for row in table["rows"])
                print(
                    "Comparación NVIDIA real: tabla prefabricada con nombres y precios de PostgreSQL.",
                    flush=True,
                )
                if variant_id:
                    budget = await ask(
                        socket,
                        f"Calcula el presupuesto para una unidad de la variante ID {variant_id} con límite de 500 Bs usando calculate_selection_budget. Muéstralo con el componente de presupuesto.",
                        "budget",
                        comparison["session_id"],
                    )
                    metrics = next(
                        b for b in budget["ui_blocks"] if b["type"] == "metrics"
                    )
                    assert metrics["source_tool"] == "calculate_selection_budget"
                    print(
                        "Presupuesto NVIDIA real: resumen visual con cálculos del servidor.",
                        flush=True,
                    )
        finally:
            if user_id is not None:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id == user_id))
                    db.commit()
                print("Cuenta temporal eliminada; catálogo conservado.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
