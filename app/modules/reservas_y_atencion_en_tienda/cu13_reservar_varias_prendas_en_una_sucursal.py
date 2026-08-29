from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Reservation, User
from app.schemas.api import ReservationCreate, ReservationOut
from app.services.realtime import event_hub
from app.services.store import create_reservation_from_cart

router = APIRouter()


@router.post(
    "",
    response_model=ReservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-13: Reservar carrito o prendas en sucursal",
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
        [(item.variante_id, item.cantidad) for item in payload.items]
        if payload.items
        else None,
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

