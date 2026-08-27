from datetime import datetime, timezone
from io import BytesIO

import qrcode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Reservation, Role, User
from app.schemas.api import OrderOut, QRValidationRequest, ReservationCreate, ReservationOut
from app.services.store import (
    cancel_reservation,
    convert_reservation_to_order,
    create_reservation_from_cart,
    expire_due_reservations,
)
from app.services.realtime import event_hub

router = APIRouter()


def _own_reservation(db: Session, reservation_id: int, user_id: int) -> Reservation:
    reservation = db.scalar(select(Reservation).where(Reservation.id == reservation_id, Reservation.usuario_id == user_id))
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    return reservation


@router.post(
    "", response_model=ReservationOut, status_code=201, summary="Reservar carrito",
    description="CU-18. Bloquea filas de variantes, verifica stock y aumenta stock_reservado en una transaccion.",
)
def reserve(
    payload: ReservationCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = create_reservation_from_cart(db, current_user.id, payload.observacion)
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "reservation_created",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        None,
        {"ADMIN", "VENDEDOR"},
    )
    return reservation


@router.get("", response_model=list[ReservationOut], summary="Listar mis reservas")
def my_reservations(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Reservation]:
    expire_due_reservations(db)
    return list(db.scalars(select(Reservation).where(Reservation.usuario_id == current_user.id).order_by(Reservation.created_at.desc())))


@router.get("/{reservation_id}", response_model=ReservationOut, summary="Consultar reserva")
def get_reservation(
    reservation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Reservation:
    return _own_reservation(db, reservation_id, current_user.id)


@router.get(
    "/{reservation_id}/qr", responses={200: {"content": {"image/png": {}}}},
    response_class=Response, summary="Generar QR de reserva", description="CU-19. El QR contiene solo un token aleatorio, nunca datos personales.",
)
def reservation_qr(
    reservation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    reservation = _own_reservation(db, reservation_id, current_user.id)
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA"}:
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
        {"ADMIN", "VENDEDOR"},
    )
    return reservation


@router.post(
    "/validate-qr", response_model=ReservationOut, summary="Validar QR en tienda",
    description="CU-21. Solo VENDEDOR/ADMIN. Verifica token, estado y vencimiento.",
)
def validate_qr(
    payload: QRValidationRequest,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> Reservation:
    expire_due_reservations(db)
    reservation = db.scalar(select(Reservation).where(Reservation.qr_token == payload.qr_token).with_for_update())
    if not reservation:
        raise HTTPException(404, "QR invalido")
    if reservation.vence_at <= datetime.now(timezone.utc) or reservation.estado == "VENCIDA":
        raise HTTPException(410, "La reserva vencio")
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA"}:
        raise HTTPException(409, f"Reserva en estado {reservation.estado}")
    reservation.estado = "CONFIRMADA"
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
    "/{reservation_id}/convert-to-order", response_model=OrderOut, summary="Convertir reserva en compra",
    description="CU-22. Solo VENDEDOR/ADMIN; consume stock reservado y crea el pedido de tienda.",
)
def convert(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
):
    reservation = db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Reserva no encontrada")
    order = convert_reservation_to_order(db, reservation, staff.id)
    background_tasks.add_task(
        event_hub.publish,
        {"type": "order_created", "order_id": order.id, "status": order.estado},
        order.usuario_id,
    )
    return order
