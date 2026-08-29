from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Branch, BranchStaff, BranchStock, Product, ProductVariant, Role, User
from app.schemas.api import BranchStockInput, BranchStockOut, StaffAssignmentInput

router = APIRouter()


def _stock_payload(row: BranchStock, variant: ProductVariant, product: Product) -> dict:
    return {
        "sucursal_id": row.sucursal_id,
        "variante_id": row.variante_id,
        "producto_id": product.id,
        "producto": product.nombre,
        "sku": variant.sku,
        "color": variant.color,
        "talla": variant.talla,
        "stock_total": row.stock_total,
        "stock_reservado": row.stock_reservado,
        "stock_disponible": row.stock_total - row.stock_reservado,
        "activo": row.activo and variant.activo and product.activo,
    }


def _sync_variant_totals(db: Session, variant_id: int) -> None:
    variant = db.get(ProductVariant, variant_id)
    if not variant:
        return
    totals = db.execute(
        select(
            func.coalesce(func.sum(BranchStock.stock_total), 0),
            func.coalesce(func.sum(BranchStock.stock_reservado), 0),
        ).where(BranchStock.variante_id == variant_id, BranchStock.activo.is_(True))
    ).one()
    variant.stock_total = int(totals[0])
    variant.stock_reservado = int(totals[1])


@router.put(
    "/{branch_id}/stock",
    response_model=BranchStockOut,
    summary="CU-34: Ajustar stock en sucursal",
)
def set_branch_stock(
    branch_id: int,
    payload: BranchStockInput,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    variant = db.scalar(
        select(ProductVariant)
        .where(ProductVariant.id == payload.variante_id)
        .with_for_update()
    )
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    row = db.scalar(
        select(BranchStock)
        .where(
            BranchStock.sucursal_id == branch_id,
            BranchStock.variante_id == variant.id,
        )
        .with_for_update()
    )
    if row and payload.stock_total < row.stock_reservado:
        raise HTTPException(409, "El stock total no puede ser menor al reservado")
    if not row:
        row = BranchStock(
            sucursal_id=branch_id,
            variante_id=variant.id,
            stock_reservado=0,
            **payload.model_dump(exclude={"variante_id"}),
        )
        db.add(row)
        db.flush()
    else:
        row.stock_total = payload.stock_total
        row.stock_minimo = payload.stock_minimo
        row.activo = payload.activo
    _sync_variant_totals(db, variant.id)
    db.commit()
    db.refresh(row)
    return _stock_payload(row, variant, db.get(Product, variant.producto_id))


@router.post(
    "/{branch_id}/staff",
    status_code=status.HTTP_201_CREATED,
    summary="CU-34: Asignar personal a sucursal",
)
def assign_staff(
    branch_id: int,
    payload: StaffAssignmentInput,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    user = db.get(User, payload.usuario_id)
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    if not user or user.rol not in {Role.ENCARGADO, Role.CAJERO, Role.VENDEDOR}:
        raise HTTPException(409, "El usuario debe ser ENCARGADO, CAJERO o VENDEDOR")
    assignment = db.scalar(
        select(BranchStaff).where(
            BranchStaff.sucursal_id == branch_id,
            BranchStaff.usuario_id == user.id,
        )
    )
    if assignment:
        assignment.activo = True
    else:
        db.add(BranchStaff(sucursal_id=branch_id, usuario_id=user.id, activo=True))
    db.commit()
    return {"sucursal_id": branch_id, "usuario_id": user.id, "activo": True}

