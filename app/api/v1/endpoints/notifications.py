from datetime import datetime
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Header, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.entities import Notification, User, UserDevice, Role
from app.services.push_notifications import dispatch_notification, sync_silent_dismissal
from app.services.realtime import event_hub

router = APIRouter()

class DeviceRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str = Field(..., min_length=10, max_length=500, description="FCM registration token")
    dispositivo_id: str | None = Field(None, max_length=120, description="Identificador fisico del dispositivo")
    plataforma: str = Field("android", max_length=30, description="android, ios o web")
    modelo: str | None = Field(None, max_length=100, description="Modelo del terminal, ej: Pixel 7")


class BrowserRegisterRequest(BaseModel):
    subscription: dict[str, Any]
    dispositivo_id: str = Field(min_length=8, max_length=120)


@router.get('/notifications/push-config')
def push_config(user: User = Depends(get_current_user)):
    from app.services.browser_push import public_key
    return {'public_key': public_key()}


@router.post('/devices/web-register')
def register_browser(payload: BrowserRegisterRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import hashlib
    from types import SimpleNamespace
    from app.services.browser_push import validate_subscription
    from app.services.device_memberships import register
    try:
        subscription = validate_subscription(payload.subscription)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'La suscripción de notificaciones del navegador no es válida')
    token = 'webpush_' + hashlib.sha256(subscription['endpoint'].encode()).hexdigest()
    count = register(db, user, SimpleNamespace(token=token, dispositivo_id=payload.dispositivo_id,
        plataforma='web', modelo='Navegador', web_subscription=subscription))
    return {'token': token, 'subscribed_stores': count}


class DeviceUnregisterRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=500)


class NotificationOut(BaseModel):
    id: int
    usuario_id: int | None
    titulo: str
    mensaje: str
    tipo: str
    data_payload: dict[str, Any] | None
    leido: bool
    leido_en: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationsListResponse(BaseModel):
    unread_count: int
    total: int
    items: list[NotificationOut]


class TestNotificationRequest(BaseModel):
    titulo: str = "Notificacion de Prueba"
    mensaje: str = "Este es un mensaje de prueba para verificar recepcion multi-dispositivo."
    tipo: str = "GENERAL"
    screen: str = "/orders"


@router.post(
    "/devices/register",
    status_code=status.HTTP_200_OK,
    summary="Registrar dispositivo para push",
    description="Vincula automáticamente el dispositivo a las tiendas de la identidad autenticada.",
)
def register_device(
    payload: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.device_memberships import register
    memberships = register(db, current_user, payload)

    active_count = db.scalar(select(func.count(UserDevice.id)).where(
        UserDevice.usuario_id==current_user.id,UserDevice.activo.is_(True))) or 1

    return {
        "status": "success",
        "message": "Dispositivo registrado exitosamente",
        "active_devices_for_user": active_count,
        "subscribed_stores": memberships,
    }


@router.post(
    "/devices/unregister",
    status_code=status.HTTP_200_OK,
    summary="Desregistrar dispositivo",
    description="Invalida el token al cerrar sesion en este equipo.",
)
def unregister_device(
    payload: DeviceUnregisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.device_memberships import unregister
    unregister(db, current_user, payload.token)

    return {"status": "success", "message": "Dispositivo desregistrado correctamente"}


@router.get(
    "/notifications",
    response_model=NotificationsListResponse,
    summary="Listar notificaciones del usuario",
    description="Devuelve las notificaciones dirigidas al usuario o globales del atelier.",
)
def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = (
        select(Notification)
        .where(
            or_(
                Notification.usuario_id == current_user.id,
                Notification.usuario_id.is_(None),
            )
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    items = db.scalars(stmt).all()

    unread_stmt = select(func.count(Notification.id)).where(
        or_(
            Notification.usuario_id == current_user.id,
            Notification.usuario_id.is_(None),
        ),
        Notification.leido == False,  # noqa: E712
    )
    unread_count = db.scalar(unread_stmt) or 0

    return {
        "unread_count": unread_count,
        "total": len(items),
        "items": items,
    }


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationOut,
    summary="Marcar notificacion como leida",
    description="Marca como leida y despacha silenciamiento en segundo plano a los demas dispositivos vinculados.",
)
async def mark_as_read(
    notification_id: int,
    originating_token: str | None = Header(None, alias='X-Device-Token'),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    notif = db.get(Notification, notification_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada")

    if notif.usuario_id is not None and notif.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para modificar esta notificacion")

    notif.leido = True
    notif.leido_en = func.now()
    db.commit()
    db.refresh(notif)

    # Silenciamiento tras lectura a terminales hermanos
    await sync_silent_dismissal(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
        originating_token=originating_token,
    )

    return notif


@router.post(
    "/notifications/read-all",
    summary="Marcar todas las notificaciones como leidas",
)
def mark_all_as_read(
    background_tasks: BackgroundTasks,
    originating_token: str | None = Header(None, alias='X-Device-Token'),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = (
        select(Notification)
        .where(
            or_(
                Notification.usuario_id == current_user.id,
                Notification.usuario_id.is_(None),
            ),
            Notification.leido == False,  # noqa: E712
        )
    )
    unread_items = db.scalars(stmt).all()
    for item in unread_items:
        item.leido = True
        item.leido_en = func.now()

    db.commit()

    return {"status": "success", "marked_read_count": len(unread_items)}


@router.post(
    "/notifications/test",
    summary="Enviar notificacion de prueba al usuario actual",
)
async def send_test_notification(
    payload: TestNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    notif = await dispatch_notification(
        db=db,
        user_id=current_user.id,
        titulo=payload.titulo,
        mensaje=payload.mensaje,
        tipo=payload.tipo,
        payload={"screen": payload.screen},
    )
    return {
        "status": "stored",
        "notification_id": notif.id if notif else None,
        "message": "Aviso guardado. Consulta el resultado de entrega a dispositivos.",
        "delivery": db.info.get('last_push_result', {}),
    }


class StoreNotice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    usuario_id: int = Field(gt=0)
    titulo: str = Field(min_length=2, max_length=150)
    mensaje: str = Field(min_length=2, max_length=1500)
    screen: str = '/catalog'


@router.post('/notifications/send', status_code=201)
async def send_store_notice(payload: StoreNotice, admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    target = db.get(User, payload.usuario_id)
    if not target or target.estado.value != 'ACTIVO':
        raise HTTPException(404, 'El destinatario no está activo en tu tienda')
    if payload.screen not in ('/catalog', '/orders', '/reservations', '/chat', '/notifications'):
        raise HTTPException(422, 'Selecciona un destino válido dentro de la tienda')
    notice = await dispatch_notification(db, target.id, payload.titulo, payload.mensaje,
        'GENERAL', {'screen': payload.screen})
    if notice is None:
        raise HTTPException(409, 'La cuenta del destinatario no está disponible para recibir avisos')
    return {'id': notice.id, 'delivery': db.info.get('last_push_result', {}),
            'message': 'Aviso guardado en la bandeja de la tienda.'}


class BroadcastPayload(BaseModel):
    event: dict[str, Any]
    user_id: int | None = None


@router.post(
    "/notifications/broadcast",
    summary="Difusion de eventos WebSocket para Web y terminales conectados",
    description="Permite que procesos auxiliares y tareas en segundo plano emitan eventos en tiempo real.",
)
async def broadcast_notification_event(
    payload: BroadcastPayload,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if payload.user_id is not None and db.get(User,payload.user_id) is None:
        raise HTTPException(404,'Usuario no encontrado')
    await event_hub.publish(payload.event, user_id=payload.user_id, tenant_id=admin.tenant_id)
    return {"status": "broadcasted"}
