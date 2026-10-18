"""Real NVIDIA + local DB regression, using an automatically removed QA account."""

import asyncio
import json
import secrets
from decimal import Decimal
from uuid import uuid4

import httpx
import websockets
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import User
from app.services.store import get_product_detail


async def turn(socket, message, request_id, session_id=None):
    await socket.send(
        json.dumps(
            {
                "type": "chat",
                "request_id": request_id,
                "message": message,
                "session_id": session_id,
            }
        )
    )
    tools, snapshots = [], []
    async with asyncio.timeout(135):
        while True:
            event = json.loads(await socket.recv())
            if event.get("request_id") != request_id:
                continue
            if event["type"] == "error":
                raise RuntimeError(event.get("message"))
            if event["type"] == "tool_start":
                tools.append(event["name"])
                print("Herramienta real:", event["name"], flush=True)
            if event["type"] == "answer_snapshot":
                snapshots.append(event["content"])
            if event["type"] == "done":
                return event, tools, snapshots


async def main():
    user_id = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/api/v1", timeout=120
    ) as client:
        try:
            credentials = {
                "email": f"qa-grounding-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
            }
            registration = await client.post(
                "/auth/register",
                json={**credentials, "nombre": "Verificación de catálogo"},
            )
            registration.raise_for_status()
            user_id = registration.json()["id"]
            login = await client.post("/auth/login", json=credentials)
            login.raise_for_status()
            async with websockets.connect(
                "ws://127.0.0.1:8000/api/v1/ws/ai", origin="http://localhost:4200"
            ) as socket:
                await socket.send(
                    json.dumps({"type": "auth", "token": login.json()["access_token"]})
                )
                assert json.loads(await socket.recv())["type"] == "connected"
                browse, tools, snapshots = await turn(
                    socket,
                    "Muéstrame dos prendas disponibles del catálogo real para elegir. Quiero ver las prendas, no solo novedades.",
                    "browse",
                )
                cards = browse["action_items"]
                assert cards and any(
                    t in tools for t in ("search_products", "discover_for_me")
                )
                with SessionLocal() as db:
                    for card in cards:
                        detail = get_product_detail(db, card["id"], fresh=True)
                        assert detail["nombre"] == card["nombre"]
                        assert Decimal(str(detail["precio"])) == Decimal(
                            str(card["precio"])
                        )
                print(
                    "Explorar: herramientas reales,",
                    len(cards),
                    "fichas; nombres y precios coinciden con PostgreSQL.",
                )
                identity = cards[0]["id"]
                price, tools, snapshots = await turn(
                    socket,
                    f"¿Cuál es el precio actual de la prenda con ID {identity}? Solo necesito el precio en texto, sin fotos ni tarjetas.",
                    "price",
                    browse["session_id"],
                )
                assert not price["action_items"] and "get_product_detail" in tools
                with SessionLocal() as db:
                    detail = get_product_detail(db, identity, fresh=True)
                    expected = f"Bs {Decimal(str(detail['precio'])):,.2f}"
                assert any(expected in text for text in snapshots)
                assert all(
                    "$usd" not in text.lower()
                    and "showroom principal" not in text.lower()
                    for text in snapshots
                )
                print(
                    "Precio: consulta nueva a la DB; importe original en Bs; cero tarjetas."
                )
                general, tools, snapshots = await turn(
                    socket,
                    "Explícame brevemente qué es el algodón, sin recomendar productos.",
                    "general",
                    browse["session_id"],
                )
                assert not general["action_items"] and not tools
                print(
                    "Conversación general: respuesta sin consultas innecesarias ni fichas."
                )
        finally:
            if user_id is not None:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id == user_id))
                    db.commit()
                print("Cuenta temporal eliminada; catálogo existente conservado.")


if __name__ == "__main__":
    asyncio.run(main())
