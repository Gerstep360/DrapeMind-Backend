import glob
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings, BACKEND_DIR
from app.models.entities import Notification, UserDevice
from app.services.realtime import event_hub

logger = logging.getLogger("drapemind.push")

# Cache global para el token OAuth2 de Google FCM HTTP v1
_cached_oauth_token: str | None = None
_cached_oauth_expiry: float = 0.0


def _find_firebase_service_account_path() -> str | None:
    """
    Busca automaticamente el archivo de credenciales de la Cuenta de Servicio
    de Firebase en las ubicaciones habituales del proyecto y sistema.
    """
    candidates = []

    # 1. Configuracion explicita en settings / .env
    if getattr(settings, "FIREBASE_CREDENTIALS_PATH", None):
        candidates.append(str(settings.FIREBASE_CREDENTIALS_PATH))

    # 2. Variables de entorno estandar de Google
    for env_var in ["GOOGLE_APPLICATION_CREDENTIALS", "FIREBASE_SERVICE_ACCOUNT_PATH"]:
        env_val = os.environ.get(env_var)
        if env_val:
            candidates.append(env_val)

    # 3. Directorio de Backend
    candidates.append(str(BACKEND_DIR / "firebase_service_account.json"))
    candidates.append(str(BACKEND_DIR / "service_account.json"))
    candidates.append(str(BACKEND_DIR / "credentials.json"))

    # 4. Busqueda por patron en backend y directorio superior
    for pattern in ["*firebase-adminsdk*.json", "*service_account*.json"]:
        candidates.extend(glob.glob(str(BACKEND_DIR / pattern)))
        candidates.extend(glob.glob(str(BACKEND_DIR.parent / pattern)))

    # 5. Directorios de produccion en VPS
    vps_paths = [
        "/root/app/DrapeMind/DrapeMind-Backend/firebase_service_account.json",
        "/root/app/DrapeMind/firebase_service_account.json",
        "/root/firebase_service_account.json",
    ]
    candidates.extend(vps_paths)

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("type") == "service_account" and "private_key" in data:
                    return path
            except Exception:
                continue

    return None


def _get_project_id() -> str:
    """Extrae el project_id desde google-services.json o settings."""
    candidates = [
        str(BACKEND_DIR / "google-services.json"),
        str(BACKEND_DIR.parent / "mobile" / "google-services.json"),
        str(BACKEND_DIR.parent / "mobile" / "android" / "app" / "google-services.json"),
        "/root/app/DrapeMind/mobile/google-services.json",
        "/root/app/DrapeMind/DrapeMind-Backend/google-services.json",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pid = data.get("project_info", {}).get("project_id")
                if pid:
                    return pid
            except Exception:
                continue
    return getattr(settings, "FIREBASE_PROJECT_ID", "drapemind-5bd6e")


async def _get_google_oauth2_token() -> tuple[str | None, str]:
    """
    Obtiene un Bearer token OAuth2 para autenticar ante FCM HTTP v1.
    Retorna (access_token, project_id).
    Cachea el token para reutilizarlo durante su periodo de validez (~50 min).
    """
    global _cached_oauth_token, _cached_oauth_expiry

    project_id = _get_project_id()

    # Si hay token en cache con al menos 60 segundos de margen, reutilizar
    now = time.time()
    if _cached_oauth_token and now < (_cached_oauth_expiry - 60):
        return _cached_oauth_token, project_id

    sa_path = _find_firebase_service_account_path()
    if not sa_path:
        return None, project_id

    try:
        # Intentar obtener credenciales via google.oauth2
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleAuthRequest

            scopes = ["https://www.googleapis.com/auth/firebase.messaging"]
            credentials = service_account.Credentials.from_service_account_file(
                sa_path,
                scopes=scopes,
            )
            credentials.refresh(GoogleAuthRequest())
            if credentials.token:
                _cached_oauth_token = credentials.token
                _cached_oauth_expiry = (
                    credentials.expiry.timestamp()
                    if credentials.expiry
                    else now + 3000
                )
                if credentials.project_id:
                    project_id = credentials.project_id
                return _cached_oauth_token, project_id
        except ImportError:
            pass

        # Fallback nativo con cryptography y request directo a Google OAuth2
        with open(sa_path, "r", encoding="utf-8") as f:
            sa_info = json.load(f)

        client_email = sa_info["client_email"]
        private_key_pem = sa_info["private_key"].encode("utf-8")
        token_uri = sa_info.get("token_uri", "https://oauth2.googleapis.com/token")
        if "project_id" in sa_info:
            project_id = sa_info["project_id"]

        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        header = {"alg": "RS256", "typ": "JWT"}
        iat = int(now)
        exp = iat + 3600
        claim = {
            "iss": client_email,
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": token_uri,
            "exp": exp,
            "iat": iat,
        }

        def b64url(val: bytes) -> str:
            return base64.urlsafe_b64encode(val).decode("utf-8").rstrip("=")

        signing_input = (
            f"{b64url(json.dumps(header).encode('utf-8'))}."
            f"{b64url(json.dumps(claim).encode('utf-8'))}"
        )

        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
        )
        sig = private_key.sign(
            signing_input.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signed_jwt = f"{signing_input}.{b64url(sig)}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                _cached_oauth_token = token
                _cached_oauth_expiry = now + expires_in
                return token, project_id
            else:
                logger.warning(
                    "[FCM OAuth2] Error solicitando access_token: HTTP %d: %s",
                    resp.status_code,
                    resp.text,
                )
    except Exception as ex:
        logger.warning("[FCM OAuth2] Error cargando credenciales de cuenta de servicio: %s", ex)

    return None, project_id


async def send_fcm_message(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, Any],
    silent: bool = False,
) -> dict[str, Any]:
    """
    Despacha notificaciones push a traves de Google Firebase Cloud Messaging HTTP v1.
    Soporta envio a multiples tokens concurrentemente con prioridad alta y canal Android.
    Maneja invalidacion automatica cuando Google reporta tokens obsoletos o dados de baja.
    """
    if not tokens:
        return {"sent": 0, "failed": 0, "invalid_tokens": []}

    access_token, project_id = await _get_google_oauth2_token()
    invalid_tokens: list[str] = []

    if not access_token:
        logger.info(
            "[FCM Push v1] Simulado para %d dispositivos vinculados (titulo='%s', silent=%s). "
            "Para activar notificaciones push en segundo plano en Android, descargue la clave privada "
            "desde Firebase Console (Configuracion del proyecto > Cuentas de servicio > Generar nueva clave privada) "
            "y guardela como 'firebase_service_account.json' en el backend.",
            len(tokens),
            title,
            silent,
        )
        return {
            "sent": 0,
            "failed": len(tokens),
            "simulated": True,
            "invalid_tokens": [],
            "reason": "NO_SERVICE_ACCOUNT_FILE",
        }

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Serializar datos a string para compatibilidad estricta con FCM HTTP v1 data map
    string_data: dict[str, str] = {
        "click_action": "FLUTTER_NOTIFICATION_CLICK",
        **{str(k): str(v) for k, v in data.items()},
    }

    sent = 0
    failed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for token in tokens:
            message_obj: dict[str, Any] = {
                "token": token,
                "data": string_data,
            }

            if not silent:
                message_obj["notification"] = {
                    "title": title,
                    "body": body,
                }
                message_obj["android"] = {
                    "priority": "HIGH",
                    "notification": {
                        "channel_id": "drapemind_alerts",
                        "sound": "default",
                        "click_action": "FLUTTER_NOTIFICATION_CLICK",
                    },
                }
            else:
                message_obj["android"] = {
                    "priority": "NORMAL",
                }

            payload = {"message": message_obj}

            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    sent += 1
                elif response.status_code in (400, 404):
                    res_body = response.text
                    # Google devuelve UNREGISTERED o INVALID_ARGUMENT para tokens dados de baja
                    if "UNREGISTERED" in res_body or "NOT_FOUND" in res_body or response.status_code == 404:
                        invalid_tokens.append(token)
                    failed += 1
                    logger.warning("[FCM Push v1] Token invalido o no registrado: %s (%s)", token[:16], res_body)
                elif response.status_code == 403 and "PERMISSION_DENIED" in response.text:
                    failed += 1
                    logger.warning(
                        "[FCM Push v1] Permiso 'cloudmessaging.messages.create' denegado. "
                        "Para activar el permiso en Google Cloud, visite: "
                        "https://console.cloud.google.com/apis/library/fcm.googleapis.com?project=%s",
                        project_id,
                    )
                else:
                    failed += 1
                    logger.warning(
                        "[FCM Push v1] Error enviando a token %s (HTTP %d): %s",
                        token[:16],
                        response.status_code,
                        response.text,
                    )
            except Exception as ex:
                logger.warning("[FCM Push v1] Excepcion de red con token %s: %s", token[:16], ex)
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
    Flujo centralizado de notificaciones multi-dispositivo y multi-plataforma:
    1. Registra la notificacion persistente en base de datos PostgreSQL.
    2. Emite el evento en tiempo real por WebSockets para Web y Mobile conectados.
    3. Consulta todos los tokens activos asociados al usuario.
    4. Envia push background a traves de Google Firebase Cloud Messaging HTTP v1.
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

    # 1. Enviar evento en tiempo real a traves de WebSockets para Web y Mobile activo
    ws_event = {
        "type": "notification",
        "id": notification.id if notification else None,
        "notification_type": tipo,
        "title": titulo,
        "body": mensaje,
        "data": payload_data,
        "created_at": notification.created_at.isoformat() if notification else datetime.now(timezone.utc).isoformat(),
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

        # Invalidacion automatica de tokens expirados o desinstalados
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
