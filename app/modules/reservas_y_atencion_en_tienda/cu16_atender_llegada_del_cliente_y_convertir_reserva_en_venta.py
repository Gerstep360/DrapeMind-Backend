from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Reservation, Role, User
from app.schemas.api import OrderOut, QRValidationRequest, ReservationOut
from app.services.realtime import event_hub
from app.services.store import (
    convert_reservation_to_order, expire_due_reservations, staff_can_access_branch,
)

router = APIRouter()


@router.post(
    "/validate-qr",
    response_model=ReservationOut,
    summary="CU-16: Validar QR en tienda",
    description="CU-16. Verifica token, vencimiento y que el personal pertenezca a la sucursal.",
)
def validate_qr(
    payload: QRValidationRequest,
    background_tasks: BackgroundTasks,
    staff: User = Depends(
        require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)
    ),
    db: Session = Depends(get_db),
) -> Reservation:
    expire_due_reservations(db)
    reservation = db.scalar(
        select(Reservation)
        .where(Reservation.qr_token == payload.qr_token)
        .with_for_update()
    )
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
    "/{reservation_id}/convert-to-order",
    response_model=OrderOut,
    summary="CU-16: Convertir reserva en compra",
    description="CU-16. Consume stock reservado de la sede y crea un pedido de venta presencial.",
)
def convert(
    reservation_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(
        require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)
    ),
    db: Session = Depends(get_db),
) -> OrderOut:
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

