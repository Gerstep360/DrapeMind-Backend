import logging
from datetime import datetime
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Notification, UserDevice
from app.services.realtime import event_hub

logger = logging.getLogger("drapemind.push")


async def send_fcm_message(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, Any],
    silent: bool = False,
) -> dict[str, Any]:
    """
    Despacha notificaciones push a traves del servicio intermediario FCM.
    Soporta envio a multiples tokens concurrentemente.
    Maneja invalidacion automatica cuando el proveedor reporta tokens obsoletos.
    """
    if not tokens:
        return {"sent": 0, "failed": 0, "invalid_tokens": []}

    fcm_server_key = getattr(settings, "FCM_SERVER_KEY", None)
    invalid_tokens: list[str] = []

    # Si no hay credencial de servidor FCM configurada en entorno local,
    # registrar el despacho estructurado para simulacion y pruebas.
    if not fcm_server_key:
        logger.info(
            "[FCM Push Dispatch] Simulado para %d dispositivos vinculados (titulo='%s', silent=%s). Para activar push en background configure FCM_SERVER_KEY o Firebase Service Account.",
            len(tokens),
            title,
            silent,
        )
        return {"sent": len(tokens), "failed": 0, "invalid_tokens": []}

    sent = 0
    failed = 0

    # FCM Legacy HTTP API o v1
    url = "https://fcm.googleapis.com/fcm/send"
    headers = {
        "Authorization": f"key={fcm_server_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Enviar en lotes o individualmente para aislar errores por token
        for token in tokens:
            payload: dict[str, Any] = {
                "to": token,
                "data": {**data, "click_action": "FLUTTER_NOTIFICATION_CLICK"},
                "priority": "high",
            }
            if not silent:
                payload["notification"] = {
                    "title": title,
                    "body": body,
                    "sound": "default",
                    "badge": 1,
                    "android_channel_id": "drapemind_alerts",
                    "channel_id": "drapemind_alerts",
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                }
            else:
                payload["content_available"] = True

            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    res_data = response.json()
                    results = res_data.get("results", [])
                    if results and "error" in results[0]:
                        err = results[0]["error"]
                        if err in ("NotRegistered", "InvalidRegistration"):
                            invalid_tokens.append(token)
                        failed += 1
                    else:
                        sent += 1
                elif response.status_code in (400, 404):
                    invalid_tokens.append(token)
                    failed += 1
                else:
                    failed += 1
            except Exception as ex:
                logger.warning("[FCM Push] Error enviando a token %s: %s", token[:15], ex)
                failed += 1

    return {"sent": sent, "failed": failed, "invalid_tokens": invalid_tokens}


async def dispatch_notification(
    db: Session,
    user_id: int | None = None,
    titulo: str = "",
    mensaje: str = "",
    tipo: str = "GENERAL",
    payload: dict[str, Any] | None = None,
    silent: bool = False,
    exclude_token: str | None = None,
) -> Notification | None:
    """
    Flujo centralizado de notificaciones multi-dispositivo (1:N):
    1. Registra la notificacion persistente en base de datos.
    2. Consulta todos los tokens activos asociados al user_id.
    3. Envia el payload a traves de FCM a todos los terminales vinculados.
    4. Emite el evento en tiempo real por WebSockets para terminales conectados.
    5. Invalida automaticamente tokens que hayan sido reportados como dados de baja.
    """
    payload_data = payload or {}
    notification: Notification | None = None

    if not silent:
        try:
            notification = Notification(
                usuario_id=user_id,
                titulo=titulo,
                mensaje=mensaje,
                tipo=tipo,
                data_payload=payload_data,
                leido=False,
            )
            db.add(notification)
            db.commit()
            db.refresh(notification)
        except Exception as _db_err:
            db.rollback()
            logger.warning("No se pudo persistir la notificacion en BD: %s", _db_err)
            notification = None

    # 1. Enviar evento en tiempo real a traves de WebSockets
    ws_event = {
        "type": "notification",
        "id": notification.id if notification else None,
        "notification_type": tipo,
        "title": titulo,
        "body": mensaje,
        "data": payload_data,
        "created_at": notification.created_at.isoformat() if notification else datetime.now().isoformat(),
        "silent": silent,
    }
    await event_hub.publish(ws_event, user_id=user_id)

    # 2. Consultar tokens activos en tabla de dispositivos (1:N)
    stmt = select(UserDevice).where(UserDevice.activo == True)  # noqa: E712
    if user_id is not None:
        stmt = stmt.where(UserDevice.usuario_id == user_id)
    if exclude_token:
        stmt = stmt.where(UserDevice.token != exclude_token)

    devices = db.scalars(stmt).all()
    tokens = [dev.token for dev in devices if dev.token]

    if tokens:
        data_to_send = {
            "notification_id": str(notification.id) if notification else "",
            "type": tipo,
            "title": titulo,
            "body": mensaje,
            **{str(k): str(v) for k, v in payload_data.items()},
        }
        res = await send_fcm_message(tokens, titulo, mensaje, data_to_send, silent=silent)

        # Invalidacion automatica de tokens expirados
        if res.get("invalid_tokens"):
            for inv_token in res["invalid_tokens"]:
                for dev in devices:
                    if dev.token == inv_token:
                        dev.activo = False
            db.commit()

    return notification


async def sync_silent_dismissal(
    db: Session,
    user_id: int,
    notification_id: int,
    originating_token: str | None = None,
) -> None:
    """
    Silenciamiento tras lectura:
    Al interactuar con la notificacion en un dispositivo, se envia un payload silencioso
    a los otros dispositivos vinculados al mismo usuario para descartar la alerta en su barra de estado.
    """
    # 1. Notificar via WebSocket a todas las sesiones activas
    await event_hub.publish(
        {
            "type": "notification_dismissed",
            "notification_id": notification_id,
            "user_id": user_id,
        },
        user_id=user_id,
    )

    # 2. Notificar via Push Silencioso a los demas dispositivos
    await dispatch_notification(
        db=db,
        user_id=user_id,
        titulo="",
        mensaje="",
        tipo="SILENT_DISMISS",
        payload={"action": "DISMISS_NOTIFICATION", "notification_id": str(notification_id)},
        silent=True,
        exclude_token=originating_token,
    )
