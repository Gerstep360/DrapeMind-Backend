from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Reservation, Role, User
from app.schemas.api import ReservationOut
from app.services.realtime import event_hub
from app.services.store import expire_due_reservations, staff_can_access_branch

router = APIRouter()


@router.post(
    "/{reservation_id}/prepare",
    response_model=ReservationOut,
    summary="CU-15: Recibir y preparar reserva",
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
        {
            "type": "reservation_updated",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        reservation.usuario_id,
    )
    return reservation


@router.post(
    "/{reservation_id}/ready",
    response_model=ReservationOut,
    summary="CU-15: Marcar reserva lista para recojo",
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
        {
            "type": "reservation_updated",
            "reservation_id": reservation.id,
            "status": reservation.estado,
        },
        reservation.usuario_id,
    )
    return reservation

