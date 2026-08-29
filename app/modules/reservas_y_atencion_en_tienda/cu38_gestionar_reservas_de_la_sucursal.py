from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Reservation, Role, User
from app.schemas.api import ReservationOut
from app.services.store import expire_due_reservations

router = APIRouter()


@router.get(
    "/reservations",
    response_model=list[ReservationOut],
    summary="CU-38: Gestionar reservas de la sucursal",
)
def all_reservations(
    state: str | None = None,
    sucursal_id: int | None = None,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[Reservation]:
    stmt = select(Reservation)
    if state:
        stmt = stmt.where(Reservation.estado == state)
    if sucursal_id:
        stmt = stmt.where(Reservation.sucursal_id == sucursal_id)
    return list(db.scalars(stmt.order_by(Reservation.created_at.desc()).limit(200)))


@router.post("/reservations/expire-due", summary="CU-38: Liberar reservas vencidas")
def expire_reservations(
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
) -> dict:
    return {"expired": expire_due_reservations(db, limit=500)}

