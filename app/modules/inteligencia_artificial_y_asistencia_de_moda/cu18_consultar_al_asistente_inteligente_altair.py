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
from app.services.ai import run_ai_action
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


@router.get(
    "/onboarding-greeting",
    summary="CU-18: Saludo inicial de onboarding con Altair",
    description="Genera un saludo interactivo y personalizado de Altair para guiar al usuario nuevo en el atelier.",
)
async def onboarding_greeting(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    nombre = user.nombre.split()[0] if user.nombre else "amante de la moda"
    prompt = (
        f"Genera un saludo breve, cálido y elegante para dar la bienvenida a {nombre} al atelier DrapeMind. "
        f"Preséntate como Altair, su Personal Stylist con IA conectado al inventario físico en Bolivia. "
        f"Invítalo a calibrar su perfil de estilo y tallas en este breve recorrido para recomendarle su primer outfit exclusivo. "
        f"Respuesta directa en español, en 2 o 3 oraciones memorables, sin markdown técnico ni comillas."
    )

    t0 = asyncio.get_event_loop().time()
    from fastapi import HTTPException
    from app.core.config import settings
    try:
        from app.services.ai import call_nvidia
        async with asyncio.timeout(45):
            greeting_text, _ = await call_nvidia(
                'Da una bienvenida breve. No afirmes haber consultado inventario ni analizado preferencias todavía.',
                prompt, max_tokens=192,
            )
    except Exception as exc:
        raise HTTPException(503, 'Altair no pudo generar la bienvenida. Puedes continuar con el formulario.') from exc

    latency_ms = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
    return {
        "greeting": greeting_text,
        "stylist_name": "Altair",
        "model": settings.llm_model,
        "user_name": nombre,
        "latency_ms": latency_ms,
        "tips": [
            "Consultamos stock real en Bolivianos (Bs) antes de recomendarte cualquier prenda.",
            "Tus tallas y gustos quedarán registrados para tus futuras sesiones de asesoría.",
            "Podrás reservar tus looks favoritos directamente en el showroom."
        ]
    }


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
        claims = decode_access_token(token)
        if not isinstance(claims.get('tid'),int) or claims.get('platform'):
            raise ValueError('El chat requiere una empresa autorizada')
        from app.core.tenancy import tenant_context
        tenant_context.set(claims['tid'])
        with SessionLocal() as db:
            user = db.get(User,int(claims['sub']))
            if not user or user.tenant_id != claims['tid'] or user.estado != UserStatus.ACTIVO:
                raise ValueError('Usuario sin empresa autorizada')
            from app.services.saas import require_active_subscription
            from app.db.tenant_session import TenantSession
            if isinstance(db, TenantSession):
                require_active_subscription(db,user.tenant_id)
        return claims
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
    from app.services.concurrent_chat import serve_nvidia_socket
    await serve_nvidia_socket(socket, int(payload["sub"]), SessionLocal)


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
