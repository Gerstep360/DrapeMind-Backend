"""CU-34: Gestionar inventario por sucursal.
Paquete: Sucursales, inventario y proveedores (PK-07).
Actores: Admin / Encargado.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import (
    Branch, BranchStaff, BranchStock, City, InventoryMovement,
    Product, ProductVariant, Role, User,
)
from app.schemas.api import (
    BranchOut, BranchStockInput, BranchStockOut, StaffAssignmentInput,
)
from app.services.store import staff_can_access_branch

router = APIRouter()


def _branch_payload(branch: Branch, city: City | None = None) -> dict:
    return {
        "id": branch.id,
        "ciudad_id": branch.ciudad_id,
        "codigo": branch.codigo,
        "nombre": branch.nombre,
        "direccion": branch.direccion,
        "telefono": branch.telefono,
        "latitud": branch.latitud,
        "longitud": branch.longitud,
        "activo": branch.activo,
        "ciudad": city.nombre if city else None,
        "departamento": city.departamento if city else None,
    }


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


@router.get(
    "/staff/assigned",
    response_model=list[BranchOut],
    summary="CU-34: Mis sucursales de trabajo asignadas",
    description="Devuelve las sucursales asignadas al empleado (o todas las activas si es ADMIN).",
)
def assigned_branches(
    staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.CAJERO, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(Branch, City)
        .join(City, City.id == Branch.ciudad_id)
        .where(Branch.activo.is_(True))
    )
    if staff.rol != Role.ADMIN:
        stmt = stmt.where(
            Branch.id.in_(
                select(BranchStaff.sucursal_id).where(
                    BranchStaff.usuario_id == staff.id,
                    BranchStaff.activo.is_(True),
                )
            )
        )
    return [_branch_payload(branch, city) for branch, city in db.execute(stmt.order_by(Branch.nombre))]


@router.put(
    "/{branch_id}/stock",
    response_model=BranchStockOut,
    summary="CU-34: Ajustar stock en sucursal",
    description="CU-34. Permite a ADMIN o ENCARGADO ajustar existencias físicas con registro obligatorio en Kardex.",
)
def set_branch_stock(
    branch_id: int,
    payload: BranchStockInput,
    admin: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO)),
    db: Session = Depends(get_db),
    observacion: str = Query(default="Ajuste de existencias", min_length=5, max_length=300),
) -> dict:
    if not staff_can_access_branch(db, admin, branch_id):
        raise HTTPException(403, "No está asignado a esta sucursal")
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
    if row and row.stock_reservado and not payload.activo:
        raise HTTPException(409, "No se puede desactivar stock con reservas activas")

    previous_total = row.stock_total if row else 0
    previous_reserved = row.stock_reservado if row else 0

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

    db.flush()
    _sync_variant_totals(db, variant.id)

    if previous_total != payload.stock_total:
        db.add(
            InventoryMovement(
                variante_id=variant.id,
                sucursal_id=branch_id,
                tipo="ENTRADA" if payload.stock_total > previous_total else "AJUSTE",
                cantidad=abs(payload.stock_total - previous_total),
                stock_total_anterior=previous_total,
                stock_total_nuevo=payload.stock_total,
                stock_reservado_anterior=previous_reserved,
                stock_reservado_nuevo=previous_reserved,
                usuario_id=admin.id,
                observacion=observacion,
                referencia_tipo="SUCURSAL",
                referencia_id=branch_id,
            )
        )

    db.commit()
    db.refresh(row)
    return _stock_payload(row, variant, db.get(Product, variant.producto_id))


@router.get(
    "/{branch_id}/movements",
    summary="CU-34: Historial de movimientos de inventario de la sucursal",
    description="Devuelve el registro auditable de entradas y ajustes en la sucursal.",
)
def branch_movements(
    branch_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[dict]:
    if not staff_can_access_branch(db, staff, branch_id):
        raise HTTPException(403, "No está asignado a esta sucursal")
    rows = db.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.sucursal_id == branch_id)
        .order_by(InventoryMovement.id.desc())
        .limit(limit)
    )
    return [
        {
            key: getattr(row, key)
            for key in (
                "id", "variante_id", "sucursal_id", "tipo", "cantidad",
                "stock_total_anterior", "stock_total_nuevo", "usuario_id",
                "observacion", "created_at",
            )
        }
        for row in rows
    ]


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
