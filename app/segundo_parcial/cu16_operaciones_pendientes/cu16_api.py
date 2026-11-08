from fastapi import APIRouter
from app.segundo_parcial.compartido.sincronizacion import (
    Depends,
    OperationLookup,
    Query,
    Session,
    SyncAudit,
    SyncOperation,
    UUID,
    User,
    authorized,
    datetime,
    fail,
    get_db,
    operation_payload,
    select,
    timezone,
)

router = APIRouter(prefix="", tags=["CU-16 · operaciones_pendientes"])


@router.get("/offline/operations")
def my_operations(
    before_id: int | None = None,
    limit: int = Query(200, ge=1, le=200),
    user: User = Depends(authorized),
    db: Session = Depends(get_db),
):
    stmt = select(SyncOperation).where(SyncOperation.usuario_id == user.id)
    if before_id:
        stmt = stmt.where(SyncOperation.id < before_id)
    return [
        operation_payload(o)
        for o in db.scalars(stmt.order_by(SyncOperation.id.desc()).limit(limit))
    ]


@router.post("/offline/operations/results")
def operation_results(
    payload: OperationLookup,
    user: User = Depends(authorized),
    db: Session = Depends(get_db),
):
    return [
        operation_payload(o)
        for o in db.scalars(
            select(SyncOperation).where(
                SyncOperation.usuario_id == user.id,
                SyncOperation.operacion_id.in_([str(i) for i in payload.operaciones]),
            )
        )
    ]


@router.post("/offline/operations/{operation_uuid}/cancel")
def cancel_pending(
    operation_uuid: UUID,
    user: User = Depends(authorized),
    db: Session = Depends(get_db),
):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    op = db.scalar(
        select(SyncOperation)
        .where(
            SyncOperation.usuario_id == user.id,
            SyncOperation.operacion_id == str(operation_uuid),
        )
        .with_for_update()
    )
    if not op:
        fail("NOT_FOUND", "La operación no se recibió en el servidor", 404)
    if op.tipo != "RESERVATION" or op.estado not in ("CONFLICT", "REJECTED"):
        fail(
            "ALREADY_PROCESSED",
            "Esta operación no se puede cancelar. Comprueba su resultado.",
        )
    if op.estado != "REJECTED":
        op.estado = "REJECTED"
        op.updated_at = datetime.now(timezone.utc)
        op.error = {
            "code": "OWNER_CANCELLED",
            "message": "La solicitud fue cancelada por su titular.",
        }
        db.add(
            SyncAudit(
                operacion_id=op.id,
                actor_id=user.id,
                accion="OWNER_CANCEL",
                detalle={"estado": "REJECTED"},
            )
        )
        db.commit()
    return operation_payload(op)
