from datetime import datetime
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entities import Notification, User, UserDevice
from app.services.push_notifications import dispatch_notification, sync_silent_dismissal
from app.services.realtime import event_hub

router = APIRouter()


class DeviceRegisterRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=500, description="FCM registration token")
    dispositivo_id: str | None = Field(None, max_length=120, description="Identificador fisico del dispositivo")
    plataforma: str = Field("android", max_length=30, description="android, ios o web")
    modelo: str | None = Field(None, max_length=100, description="Modelo del terminal, ej: Pixel 7")


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
    description="Vincula el token FCM del dispositivo al usuario actual. Permite multiples dispositivos por cuenta (1:N).",
)
def register_device(
    payload: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    existing = db.scalar(select(UserDevice).where(UserDevice.token == payload.token))
    if existing:
        existing.usuario_id = current_user.id
        if payload.dispositivo_id:
            existing.dispositivo_id = payload.dispositivo_id
        existing.plataforma = payload.plataforma
        if payload.modelo:
            existing.modelo = payload.modelo
        existing.activo = True
        existing.ultimo_uso = func.now()
    else:
        new_dev = UserDevice(
            usuario_id=current_user.id,
            token=payload.token,
            dispositivo_id=payload.dispositivo_id,
            plataforma=payload.plataforma,
            modelo=payload.modelo,
            activo=True,
        )
        db.add(new_dev)

    db.commit()

    active_count = db.scalar(
        select(func.count(UserDevice.id)).where(
            UserDevice.usuario_id == current_user.id,
            UserDevice.activo == True,  # noqa: E712
        )
    ) or 1

    return {
        "status": "success",
        "message": "Dispositivo registrado exitosamente",
        "active_devices_for_user": active_count,
    }


@router.post(
    "/devices/unregister",
    status_code=status.HTTP_200_OK,
    summary="Desregistrar dispositivo",
    description="Invalida el token al cerrar sesion en este equipo, conservando las sesiones de los otros dispositivos.",
)
def unregister_device(
    payload: DeviceUnregisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    dev = db.scalar(
        select(UserDevice).where(
            UserDevice.token == payload.token,
            UserDevice.usuario_id == current_user.id,
        )
    )
    if dev:
        dev.activo = False
        db.commit()

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
    originating_token: str | None = Query(None, description="Token del terminal que leyo la notificacion"),
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
    originating_token: str | None = Query(None),
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
        "status": "sent",
        "notification_id": notif.id if notif else None,
        "message": "Notificacion despachada a todos los dispositivos vinculados.",
    }


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
) -> dict[str, str]:
    await event_hub.publish(payload.event, user_id=payload.user_id)
    return {"status": "broadcasted"}
