from datetime import datetime, timezone
from io import BytesIO

import qrcode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Reservation, ReservationItem, Role, User
from app.schemas.api import (
    OrderOut, QRValidationRequest, ReservationCreate, ReservationDetail,
    ReservationOut,
)
from app.services.store import (
    cancel_reservation,
    convert_reservation_to_order,
    create_reservation_from_cart,
    expire_due_reservations,
    staff_can_access_branch,
)
from app.services.realtime import event_hub

router = APIRouter()


def _own_reservation(db: Session, reservation_id: int, user_id: int) -> Reservation:
    reservation = db.scalar(select(Reservation).where(Reservation.id == reservation_id, Reservation.usuario_id == user_id))
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    return reservation


def _detail(db: Session, reservation: Reservation) -> dict:
    data = ReservationOut.model_validate(reservation).model_dump()
    data["items"] = list(
        db.scalars(
            select(ReservationItem)
            .where(ReservationItem.reserva_id == reservation.id)
            .order_by(ReservationItem.id)
        )
    )
    return data


@router.post(
    "", response_model=ReservationOut, status_code=201, summary="Reservar carrito",
    description="CU-13. Reserva varias variantes en una sucursal. Si items se omite, usa el carrito actual.",
)
def reserve(
    payload: ReservationCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = create_reservation_from_cart(
        db,
        current_user.id,
        payload.observacion,
        payload.sucursal_id,
        [(item.variante_id, item.cantidad) for item in payload.items] if payload.items else None,
    )
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "reservation_created",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        None,
        {"ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO"},
    )
    return reservation


@router.get("", response_model=list[ReservationOut], summary="Listar mis reservas")
def my_reservations(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Reservation]:
    expire_due_reservations(db)
    return list(db.scalars(select(Reservation).where(Reservation.usuario_id == current_user.id).order_by(Reservation.created_at.desc())))


@router.get("/{reservation_id}", response_model=ReservationDetail, summary="Consultar reserva y prendas")
def get_reservation(
    reservation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return _detail(db, _own_reservation(db, reservation_id, current_user.id))


@router.get(
    "/{reservation_id}/qr", responses={200: {"content": {"image/png": {}}}},
    response_class=Response, summary="Generar QR de reserva", description="CU-19. El QR contiene solo un token aleatorio, nunca datos personales.",
)
def reservation_qr(
    reservation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    reservation = _own_reservation(db, reservation_id, current_user.id)
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA", "EN_PREPARACION", "LISTA"}:
        raise HTTPException(409, "La reserva no tiene un QR activo")
    image = qrcode.make(str(reservation.qr_token))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.post("/{reservation_id}/cancel", response_model=ReservationOut, summary="Cancelar reserva")
def cancel(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = cancel_reservation(
        db, _own_reservation(db, reservation_id, current_user.id), current_user.id
    )
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "reservation_updated",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        None,
        {"ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO"},
    )
    return reservation


@router.post(
    "/validate-qr", response_model=ReservationOut, summary="Validar QR en tienda",
    description="CU-16. Verifica token, vencimiento y que el personal pertenezca a la sucursal.",
)
def validate_qr(
    payload: QRValidationRequest,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> Reservation:
    expire_due_reservations(db)
    reservation = db.scalar(select(Reservation).where(Reservation.qr_token == payload.qr_token).with_for_update())
    if not reservation:
        raise HTTPException(404, "QR invalido")
    if reservation.vence_at <= datetime.now(timezone.utc) or reservation.estado == "VENCIDA":
        raise HTTPException(410, "La reserva vencio")
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA", "LISTA"}:
        raise HTTPException(409, f"Reserva en estado {reservation.estado}")
    if not staff_can_access_branch(db, staff, reservation.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal de esta reserva")
    reservation.estado = "RETIRADA" if reservation.estado == "LISTA" else "CONFIRMADA"
    db.commit()
    db.refresh(reservation)
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "reservation_updated",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        reservation.usuario_id,
    )
    return reservation


@router.post(
    "/{reservation_id}/prepare",
    response_model=ReservationOut,
    summary="Recibir y preparar reserva",
    description="CU-15. Inicia la preparación en la sucursal asignada y registra al responsable.",
)
def prepare(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = db.scalar(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    if not staff_can_access_branch(db, staff, reservation.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal de esta reserva")
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA"}:
        raise HTTPException(409, f"No se puede preparar una reserva {reservation.estado}")
    if reservation.vence_at <= datetime.now(timezone.utc):
        expire_due_reservations(db)
        raise HTTPException(410, "La reserva venció")
    reservation.estado = "EN_PREPARACION"
    reservation.preparado_por_id = staff.id
    reservation.preparado_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    background_tasks.add_task(
        event_hub.publish,
        {"type": "reservation_updated", "reservation_id": reservation.id, "status": reservation.estado},
        reservation.usuario_id,
    )
    return reservation


@router.post(
    "/{reservation_id}/ready",
    response_model=ReservationOut,
    summary="Marcar reserva lista para recojo",
    description="CU-15. Finaliza la preparación y avisa al cliente por WebSocket.",
)
def mark_ready(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = db.scalar(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    if not staff_can_access_branch(db, staff, reservation.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal de esta reserva")
    if reservation.estado != "EN_PREPARACION":
        raise HTTPException(409, "La reserva debe estar EN_PREPARACION")
    reservation.estado = "LISTA"
    db.commit()
    db.refresh(reservation)
    background_tasks.add_task(
        event_hub.publish,
        {"type": "reservation_updated", "reservation_id": reservation.id, "status": reservation.estado},
        reservation.usuario_id,
    )
    return reservation


@router.post(
    "/{reservation_id}/convert-to-order", response_model=OrderOut, summary="Convertir reserva en compra",
    description="CU-16. Consume stock reservado de la sede y crea un pedido de venta presencial.",
)
def convert(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)),
    db: Session = Depends(get_db),
):
    reservation = db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    if not staff_can_access_branch(db, staff, reservation.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal de esta reserva")
    order = convert_reservation_to_order(db, reservation, staff.id)
    background_tasks.add_task(
        event_hub.publish,
        {"type": "order_created", "order_id": order.id, "status": order.estado},
        order.usuario_id,
    )
    return order
