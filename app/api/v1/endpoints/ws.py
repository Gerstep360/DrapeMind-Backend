import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User, UserStatus
from app.services.ai import run_agent_socket, sanitize_for_json
from app.services.model_runtime import ModelRuntimeError
from app.services.realtime import event_hub, websocket_origin_allowed

router = APIRouter()


async def _authenticate(socket: WebSocket) -> dict:
    if not websocket_origin_allowed(socket.headers.get("origin")):
        await socket.close(code=1008, reason="Origin no permitido")
        raise WebSocketDisconnect(code=1008)
    await socket.accept()
    try:
        message = await asyncio.wait_for(socket.receive_json(), timeout=10)
        if message.get("type") != "auth":
            raise ValueError("El primer mensaje debe ser auth")
        return decode_access_token(str(message.get("token", "")))
    except (asyncio.TimeoutError, ValueError, TypeError, HTTPException, Exception):
        await socket.close(code=1008, reason="Autenticacion invalida")
        raise WebSocketDisconnect(code=1008)


@router.websocket("/ai")
async def ai_socket(socket: WebSocket) -> None:
    try:
        payload = await _authenticate(socket)
    except WebSocketDisconnect:
        return
    with SessionLocal() as db:
        user = db.get(User, int(payload["sub"]))
        if not user or user.estado != UserStatus.ACTIVO:
            await socket.close(code=1008, reason="Usuario inactivo")
            return

        async def safe_send(msg: dict) -> None:
            try:
                await socket.send_json(sanitize_for_json(msg))
            except (WebSocketDisconnect, RuntimeError):
                pass

        await safe_send({"type": "connected", "channel": "ai"})
        try:
            while True:
                try:
                    data = await socket.receive_json()
                except (WebSocketDisconnect, RuntimeError):
                    break
                message_type = data.get("type")
                if message_type == "ping":
                    await safe_send({"type": "pong"})
                    continue
                if message_type != "chat":
                    await safe_send({"type": "error", "message": "Evento no soportado"})
                    continue
                message = str(data.get("message", "")).strip()
                if not 2 <= len(message) <= 2000:
                    await safe_send(
                        {"type": "error", "message": "El mensaje debe tener 2 a 2000 caracteres"}
                    )
                    continue
                try:
                    await run_agent_socket(
                        db,
                        user,
                        message,
                        data.get("session_id"),
                        safe_send,
                    )
                except (ModelRuntimeError, HTTPException) as exc:
                    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    await safe_send({"type": "error", "message": detail})
                except Exception as exc:
                    import logging
                    logging.getLogger("drapemind.ws").exception("Error procesando mensaje de IA en WebSocket")
                    await safe_send(
                        {
                            "type": "error",
                            "message": f"No se pudo completar la consulta: {str(exc)}",
                        }
                    )
        except (WebSocketDisconnect, RuntimeError):
            return


@router.websocket("/events")
async def events_socket(socket: WebSocket) -> None:
    try:
        payload = await _authenticate(socket)
    except WebSocketDisconnect:
        return
    with SessionLocal() as db:
        user = db.get(User, int(payload["sub"]))
        if not user or user.estado != UserStatus.ACTIVO:
            await socket.close(code=1008, reason="Usuario inactivo")
            return
        await event_hub.connect(socket, user.id, user.rol.value)
        await socket.send_json({"type": "connected", "channel": "events"})
        try:
            while True:
                message = await socket.receive_json()
                if message.get("type") == "ping":
                    await socket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            await event_hub.disconnect(socket)
