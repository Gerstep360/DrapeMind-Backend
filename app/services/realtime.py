import asyncio
import re
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.core.config import settings


def websocket_origin_allowed(origin: str | None) -> bool:
    if not origin or settings.ENVIRONMENT == "development":
        return True
    normalized = origin.rstrip("/")
    if normalized in settings.CORS_ORIGINS:
        return True
    return bool(
        settings.CORS_ORIGIN_REGEX
        and re.fullmatch(settings.CORS_ORIGIN_REGEX, normalized)
    )



@dataclass
class EventConnection:
    socket: WebSocket
    user_id: int
    role: str


class EventHub:
    """Single-process event hub. Use one API worker or replace with Redis for horizontal scale."""

    def __init__(self) -> None:
        self.connections: list[EventConnection] = []
        self.lock = asyncio.Lock()

    async def connect(self, socket: WebSocket, user_id: int, role: str) -> None:
        async with self.lock:
            self.connections.append(EventConnection(socket, user_id, role))

    async def register(self, socket: WebSocket, user_id: int, roles: Any = None) -> None:
        role = "CLIENTE"
        if isinstance(roles, (set, list, tuple)) and roles:
            role = str(next(iter(roles)))
        elif isinstance(roles, str):
            role = roles
        await self.connect(socket, user_id, role)

    async def disconnect(self, socket: WebSocket) -> None:
        async with self.lock:
            self.connections = [
                connection
                for connection in self.connections
                if connection.socket is not socket
            ]

    async def publish(
        self,
        event: dict,
        user_id: int | None = None,
        roles: set[str] | None = None,
    ) -> None:
        async with self.lock:
            targets = [
                connection
                for connection in self.connections
                if (user_id is None or connection.user_id == user_id)
                and (roles is None or connection.role in roles)
            ]
        stale: list[WebSocket] = []
        for connection in targets:
            try:
                await connection.socket.send_json(event)
            except Exception:
                stale.append(connection.socket)
        for socket in stale:
            await self.disconnect(socket)


event_hub = EventHub()
