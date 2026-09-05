"""CU-18: Consultar al asistente inteligente Altair.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import decode_access_token
from app.db.session import SessionLocal, get_db
from app.models import User, UserStatus
from app.schemas.api import AIRequest, AIResponse
from app.services.ai import run_agent_socket, run_ai_action
from app.services.realtime import websocket_origin_allowed

router = APIRouter()
ws_router = APIRouter()
logger = logging.getLogger("drapemind.ws")


@router.post(
    "/chat",
    response_model=AIResponse,
    summary="CU-18: Asistente conversacional Altair (HTTP)",
    description="CU-18 / CU-08. Endpoint HTTP para consultas de moda con contexto de catálogo y carrito.",
)
async def chat_http(
    payload: AIRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-18: Consulta conversacional vía HTTP."""
    return await run_ai_action(db, user, "chat", payload.mensaje, payload.sesion_id)


async def _authenticate(socket: WebSocket) -> dict:
    origin = socket.headers.get("origin")
    if not websocket_origin_allowed(origin):
        logger.warning("WS handshake rejected: Origin '%s' no permitido", origin)
        await socket.close(code=4403, reason="Origin no permitido")
        raise WebSocketDisconnect(code=4403)
    await socket.accept()
    try:
        message = await asyncio.wait_for(socket.receive_json(), timeout=10)
        if message.get("type") != "auth":
            logger.warning("WS handshake rejected: Primer mensaje no es auth")
            raise ValueError("El primer mensaje debe ser auth")
        token = str(message.get("token", "")).strip()
        if not token:
            logger.warning("WS handshake rejected: Token vacío")
            raise ValueError("Token vacío")
        return decode_access_token(token)
    except Exception as exc:
        logger.info("WS auth rejected: %s", exc)
        try:
            await socket.send_json(
                {
                    "type": "error",
                    "code": "AUTH_INVALID",
                    "message": "Sesión inválida o expirada. Por favor vuelve a iniciar sesión.",
                }
            )
        except Exception:
            pass
        await socket.close(code=4401, reason="Autenticacion invalida")
        raise WebSocketDisconnect(code=4401)


@ws_router.websocket("/ai")
async def ai_socket(socket: WebSocket) -> None:
    try:
        payload = await _authenticate(socket)
    except WebSocketDisconnect:
        return
    with SessionLocal() as db:
        user = db.get(User, int(payload["sub"]))
        if not user or user.estado != UserStatus.ACTIVO:
            try:
                await socket.send_json(
                    {
                        "type": "error",
                        "code": "AUTH_INVALID",
                        "message": "Usuario inactivo o no encontrado. Por favor inicia sesión nuevamente.",
                    }
                )
            except Exception:
                pass
            await socket.close(code=4401, reason="Usuario inactivo")
            return

        async def safe_send(msg: dict) -> None:
            try:
                from app.services.ai import sanitize_for_json
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
                    from app.services.model_runtime import ModelRuntimeError
                    from fastapi import HTTPException
                    await run_agent_socket(
                        db,
                        user,
                        message,
                        data.get("session_id"),
                        safe_send,
                    )
                except Exception as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "message": f"No se pudo completar la consulta: {str(exc)}",
                        }
                    )
        except (WebSocketDisconnect, RuntimeError):
            return


@ws_router.websocket("/events")
async def events_socket(socket: WebSocket) -> None:
    try:
        payload = await _authenticate(socket)
    except WebSocketDisconnect:
        return
    with SessionLocal() as db:
        user = db.get(User, int(payload["sub"]))
        if not user or user.estado != UserStatus.ACTIVO:
            await socket.close(code=4401, reason="Usuario inactivo")
            return
        user_id = user.id
        user_role = user.rol.value

    from app.services.realtime import event_hub
    await event_hub.connect(socket, user_id, user_role)
    try:
        await socket.send_json({"type": "connected", "channel": "events"})
        while True:
            data = await socket.receive_json()
            if data.get("type") == "ping":
                await socket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await event_hub.disconnect(socket)


