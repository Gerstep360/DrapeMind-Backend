from fastapi import APIRouter
from app.segundo_parcial.compartido.sincronizacion import (
    Branch,
    ConflictResolution,
    Depends,
    Product,
    ProductVariant,
    Role,
    Session,
    SyncAudit,
    SyncOperation,
    User,
    attempt,
    branch_access,
    branch_ids,
    datetime,
    fail,
    get_db,
    manager,
    operation_payload,
    select,
    timezone,
)

router = APIRouter(prefix="", tags=["CU-18 · conflictos"])


@router.get("/retail/conflicts")
def conflicts(
    before_id: int | None = None,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
):
    stmt = select(SyncOperation).where(
        SyncOperation.estado.in_(["CONFLICT", "REJECTED"])
    )
    if user.rol != Role.ADMIN:
        stmt = stmt.where(SyncOperation.sucursal_id.in_(branch_ids(db, user)))
    if before_id:
        stmt = stmt.where(SyncOperation.id < before_id)
    rows = list(db.scalars(stmt.order_by(SyncOperation.id.desc()).limit(200)))
    users = dict(
        db.execute(
            select(User.id, User.nombre).where(
                User.id.in_([o.usuario_id for o in rows])
            )
        ).all()
    )
    branches = dict(
        db.execute(
            select(Branch.id, Branch.nombre).where(
                Branch.id.in_([o.sucursal_id for o in rows])
            )
        ).all()
    )
    ids = {i["variante_id"] for o in rows for i in o.payload["items"]}
    variants = {
        v.id: (v, p)
        for v, p in db.execute(
            select(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.producto_id)
            .where(ProductVariant.id.in_(ids))
        )
    }
    result = []
    for op in rows:
        lines = []
        for item in op.payload["items"]:
            v, p = variants.get(item["variante_id"], (None, None))
            lines.append(
                {
                    **item,
                    "nombre": f"{p.nombre} · {v.talla} · {v.color}"
                    if p
                    else "Prenda no disponible",
                    "precio_actual": str(p.precio) if p else None,
                }
            )
        result.append(
            {
                **operation_payload(op),
                "usuario_nombre": users.get(op.usuario_id, "Usuario de la tienda"),
                "sucursal_nombre": branches.get(
                    op.sucursal_id, "Sucursal de la tienda"
                ),
                "detalle_prendas": lines,
            }
        )
    return result


@router.get("/retail/operations/{operation_id}/audit")
def audit(
    operation_id: int, user: User = Depends(manager), db: Session = Depends(get_db)
):
    op = db.get(SyncOperation, operation_id)
    if not op:
        fail("NOT_FOUND", "Operación no encontrada", 404)
    branch_access(db, user, op.sucursal_id, require_active=False)
    return [
        {
            "id": a.id,
            "actor_id": a.actor_id,
            "accion": a.accion,
            "detalle": a.detalle,
            "created_at": a.created_at,
        }
        for a in db.scalars(
            select(SyncAudit)
            .where(SyncAudit.operacion_id == operation_id)
            .order_by(SyncAudit.id)
        )
    ]


@router.post("/retail/operations/{operation_id}/resolve")
def resolve(
    operation_id: int,
    payload: ConflictResolution,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
):
    op = db.get(SyncOperation, operation_id)
    if not op:
        fail("NOT_FOUND", "Operación no encontrada", 404)
    branch_access(db, user, op.sucursal_id, require_active=False)
    owner = db.scalar(select(User).where(User.id == op.usuario_id).with_for_update())
    op = db.scalar(
        select(SyncOperation)
        .where(SyncOperation.id == operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if op.estado != "CONFLICT":
        fail("ALREADY_RESOLVED", "La operación ya fue resuelta. Actualiza la lista.")
    if payload.accion == "REJECT":
        if op.tipo != "RESERVATION" and not payload.efectivo_devuelto:
            fail(
                "REFUND_REQUIRED",
                "Confirma la devolución del efectivo antes de anular esta venta",
                422,
            )
        op.estado = "REJECTED"
        op.updated_at = datetime.now(timezone.utc)
        op.error = {"code": "MANAGER_REJECTED", "message": payload.motivo}
        db.add(
            SyncAudit(
                operacion_id=op.id,
                actor_id=user.id,
                accion="REJECT",
                detalle={
                    "motivo": payload.motivo,
                    "efectivo_devuelto": payload.efectivo_devuelto,
                },
            )
        )
    else:
        attempt(
            db,
            op,
            owner,
            user,
            accept_saved_price=payload.aceptar_precio_guardado,
            reason=payload.motivo,
        )
    db.commit()
    return operation_payload(op)
