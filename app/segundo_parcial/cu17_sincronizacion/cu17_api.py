from fastapi import APIRouter
from app.segundo_parcial.compartido.sincronizacion import (
    Branch,
    Depends,
    Session,
    SyncEnvelope,
    SyncOperation,
    User,
    attempt,
    authorized,
    digest,
    expire_due_reservations,
    fail,
    get_db,
    operation_payload,
    require_active_subscription,
    role_for_kind,
    select,
)

router = APIRouter(prefix="", tags=["CU-17 · sincronizacion"])


@router.post("/offline/operations")
def synchronize(
    payload: SyncEnvelope,
    user: User = Depends(authorized),
    db: Session = Depends(get_db),
):
    role_for_kind(user, payload.tipo)
    require_active_subscription(db, user.tenant_id, "offline")
    if not db.get(Branch, payload.payload["sucursal_id"]):
        fail("BRANCH_UNAVAILABLE", "La sucursal no pertenece a esta empresa", 404)
    expire_due_reservations(db)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    operation_id = payload.payload["operacion_id"]
    fingerprint = digest(payload.model_dump(mode="json"))
    op = db.scalar(
        select(SyncOperation)
        .where(
            SyncOperation.usuario_id == user.id,
            SyncOperation.operacion_id == operation_id,
        )
        .with_for_update()
    )
    if op:
        if op.payload_hash != fingerprint:
            fail("OPERATION_REUSED", "Esta operación ya fue recibida con otros datos")
        if op.estado in ("CONFIRMED", "REJECTED"):
            return operation_payload(op)
    else:
        op = SyncOperation(
            usuario_id=user.id,
            sucursal_id=payload.payload["sucursal_id"],
            operacion_id=operation_id,
            tipo=payload.tipo,
            payload=payload.payload,
            payload_hash=fingerprint,
        )
        db.add(op)
        db.flush()
    attempt(db, op, user, user)
    db.commit()
    return operation_payload(op)
