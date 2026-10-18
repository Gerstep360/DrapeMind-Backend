"""Verify customer HTTP routes and authenticated sockets directly and through Angular."""

import asyncio
import json
import secrets
from uuid import uuid4

import httpx
import websockets
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import User


async def main():
    user_id = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/api/v1", timeout=15
    ) as api:
        try:
            credentials = {
                "email": f"qa-routes-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
            }
            registered = await api.post(
                "/auth/register",
                json={**credentials, "nombre": "Verificación de rutas"},
            )
            registered.raise_for_status()
            user_id = registered.json()["id"]
            login = await api.post("/auth/login", json=credentials)
            login.raise_for_status()
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            saved = await api.post(
                "/users/me/style-profile",
                headers=headers,
                json={
                    "genero": "UNISEX",
                    "talla_superior": "M",
                    "infer_style": False,
                    "infer_outfit": False,
                },
            )
            saved.raise_for_status()
            paths = (
                "/catalog/promotions?activo=true",
                "/notifications?limit=50",
                "/users/me/addresses",
                "/catalog/favorites",
                "/users/me/style-profile",
            )
            for origin in ("http://127.0.0.1:8000", "http://localhost:4200"):
                async with httpx.AsyncClient(
                    base_url=origin + "/api/v1", headers=headers, timeout=15
                ) as client:
                    for path in paths:
                        response = await client.get(path)
                        response.raise_for_status()
                        print(
                            origin, path.split("?")[0], response.status_code, flush=True
                        )
                for channel in ("ai", "events"):
                    async with websockets.connect(
                        origin.replace("http://", "ws://") + f"/api/v1/ws/{channel}",
                        origin="http://localhost:4200",
                        open_timeout=15,
                    ) as socket:
                        await socket.send(json.dumps({"type": "auth", "token": token}))
                        assert (
                            json.loads(await asyncio.wait_for(socket.recv(), 10))[
                                "type"
                            ]
                            == "connected"
                        )
                        await socket.send(json.dumps({"type": "ping"}))
                        assert (
                            json.loads(await asyncio.wait_for(socket.recv(), 10))[
                                "type"
                            ]
                            == "pong"
                        )
                        print(
                            origin,
                            "WebSocket",
                            channel,
                            "auth + ping/pong OK",
                            flush=True,
                        )
        finally:
            if user_id is not None:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id == user_id))
                    db.commit()
                print("Cuenta temporal eliminada.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
