from io import BytesIO

import qrcode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Reservation, ReservationItem, User
from app.schemas.api import ReservationDetail, ReservationOut
from app.services.realtime import event_hub
from app.services.store import cancel_reservation, expire_due_reservations

router = APIRouter()


def _own_reservation(db: Session, reservation_id: int, user_id: int) -> Reservation:
    reservation = db.scalar(
        select(Reservation).where(
            Reservation.id == reservation_id, Reservation.usuario_id == user_id
        )
    )
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


@router.get("", response_model=list[ReservationOut], summary="CU-14: Listar mis reservas")
def my_reservations(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Reservation]:
    expire_due_reservations(db)
    return list(
        db.scalars(
            select(Reservation)
            .where(Reservation.usuario_id == current_user.id)
            .order_by(Reservation.created_at.desc())
        )
    )


@router.get(
    "/{reservation_id}",
    response_model=ReservationDetail,
    summary="CU-14: Consultar reserva y prendas",
)
def get_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _detail(db, _own_reservation(db, reservation_id, current_user.id))


@router.get(
    "/{reservation_id}/qr",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
    summary="CU-14: Generar QR de reserva",
    description="CU-14. El QR contiene solo un token aleatorio, nunca datos personales.",
)
def reservation_qr(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    reservation = _own_reservation(db, reservation_id, current_user.id)
    if reservation.estado not in {
        "PENDIENTE",
        "CONFIRMADA",
        "EN_PREPARACION",
        "LISTA",
    }:
        raise HTTPException(409, "La reserva no tiene un QR activo")
    image = qrcode.make(str(reservation.qr_token))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.post(
    "/{reservation_id}/cancel",
    response_model=ReservationOut,
    summary="CU-14: Cancelar reserva",
)
def cancel(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Reservation:
    reservation = cancel_reservation(
        db,
        _own_reservation(db, reservation_id, current_user.id),
        current_user.id,
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

