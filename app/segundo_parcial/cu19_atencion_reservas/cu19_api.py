from fastapi import APIRouter
from app.segundo_parcial.compartido.sincronizacion import (
    Depends,
    Reservation,
    ReservationPreparation,
    Session,
    User,
    attending_snapshots,
    branch_access,
    datetime,
    expire_due_reservations,
    fail,
    get_db,
    reservation_snapshot,
    select,
    staff,
    timezone,
)

router = APIRouter(prefix="", tags=["CU-19 · atencion_reservas"])


@router.get("/retail/reservations")
def attending(user: User = Depends(staff), db: Session = Depends(get_db)):
    expire_due_reservations(db)
    return attending_snapshots(db, user)


@router.post("/retail/reservations/{reservation_id}/prepare")
def prepare(
    reservation_id: int,
    payload: ReservationPreparation,
    user: User = Depends(staff),
    db: Session = Depends(get_db),
):
    expire_due_reservations(db)
    r = db.scalar(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    if not r:
        fail("NOT_FOUND", "Reserva no encontrada", 404)
    branch_access(db, user, r.sucursal_id)
    allowed = {
        "PENDIENTE": ("CONFIRMADA", "EN_PREPARACION", "LISTA"),
        "CONFIRMADA": ("EN_PREPARACION", "LISTA"),
        "EN_PREPARACION": ("LISTA",),
        "LISTA": (),
    }
    if r.estado != payload.estado and payload.estado not in allowed.get(r.estado, ()):
        fail("INVALID_STATE", "La reserva no permite ese cambio de estado")
    r.estado = payload.estado
    r.preparado_por_id = user.id
    r.preparado_at = datetime.now(timezone.utc)
    db.commit()
    return reservation_snapshot(db, r)
