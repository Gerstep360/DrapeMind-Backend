"""CU-35: Registrar movimientos, recepción y ajustes de inventario.
Paquete: Sucursales, inventario y proveedores (PK-07).
Actores: Admin / Encargado.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import (
    Branch, BranchStaff, BranchStock, InventoryMovement, Product,
    ProductVariant, Role, User,
)
from app.schemas.api import InventoryAdjustment
from app.services.store import staff_can_access_branch

router = APIRouter()


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


@router.post(
    "/inventory/adjustments",
    status_code=status.HTTP_201_CREATED,
    summary="CU-35: Registrar movimientos, recepción y ajustes de inventario",
    description="CU-35. Permite a ADMIN y ENCARGADO registrar recepción (ENTRADA) o corrección física (AJUSTE) con trazabilidad en Kardex.",
)
def ajustar_inventario(
    payload: InventoryAdjustment,
    staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.scalar(
        select(ProductVariant)
        .where(ProductVariant.id == payload.variante_id)
        .with_for_update()
    )
    if not variant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variante no encontrada")

    target_branch_id = payload.sucursal_id
    if target_branch_id is None and staff.rol == Role.ENCARGADO:
        # Inferir la sucursal asignada del encargado
        target_branch_id = db.scalar(
            select(BranchStaff.sucursal_id).where(
                BranchStaff.usuario_id == staff.id,
                BranchStaff.activo.is_(True),
            )
        )
        if not target_branch_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "El encargado no tiene una sucursal asignada activa",
            )

    if target_branch_id is not None:
        if not staff_can_access_branch(db, staff, target_branch_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "No está asignado a esta sucursal",
            )
        branch = db.get(Branch, target_branch_id)
        if not branch:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Sucursal no encontrada")

        branch_stock = db.scalar(
            select(BranchStock)
            .where(
                BranchStock.sucursal_id == target_branch_id,
                BranchStock.variante_id == variant.id,
            )
            .with_for_update()
        )
        if branch_stock and payload.nuevo_stock_total < branch_stock.stock_reservado:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El nuevo stock total no puede ser menor al reservado en la sucursal",
            )

        previous_total = branch_stock.stock_total if branch_stock else 0
        previous_reserved = branch_stock.stock_reservado if branch_stock else 0

        if not branch_stock:
            branch_stock = BranchStock(
                sucursal_id=target_branch_id,
                variante_id=variant.id,
                stock_total=payload.nuevo_stock_total,
                stock_reservado=0,
                stock_minimo=1,
                activo=True,
            )
            db.add(branch_stock)
        else:
            branch_stock.stock_total = payload.nuevo_stock_total

        db.flush()
        _sync_variant_totals(db, variant.id)
    else:
        # Ajuste global directo por ADMIN
        if payload.nuevo_stock_total < variant.stock_reservado:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El nuevo total es menor que el stock reservado global",
            )
        previous_total = variant.stock_total
        previous_reserved = variant.stock_reservado
        variant.stock_total = payload.nuevo_stock_total
        db.flush()

    # Clasificación formal del movimiento: ENTRADA (Recepción) vs AJUSTE (Conteo/Merma)
    if payload.tipo in {"ENTRADA", "AJUSTE"}:
        tipo_movimiento = payload.tipo
    elif payload.nuevo_stock_total > previous_total:
        tipo_movimiento = "ENTRADA"
    else:
        tipo_movimiento = "AJUSTE"

    difference = payload.nuevo_stock_total - previous_total
    cantidad = abs(difference)

    if difference != 0:
        db.add(
            InventoryMovement(
                variante_id=variant.id,
                sucursal_id=target_branch_id,
                tipo=tipo_movimiento,
                cantidad=cantidad,
                stock_total_anterior=previous_total,
                stock_total_nuevo=payload.nuevo_stock_total,
                stock_reservado_anterior=previous_reserved,
                stock_reservado_nuevo=previous_reserved,
                referencia_tipo="RECEPCION" if tipo_movimiento == "ENTRADA" else "AJUSTE",
                referencia_id=target_branch_id,
                usuario_id=staff.id,
                observacion=payload.observacion,
            )
        )

    db.commit()
    db.refresh(variant)

    return {
        "variante_id": variant.id,
        "sucursal_id": target_branch_id,
        "tipo": tipo_movimiento,
        "cantidad": cantidad,
        "stock_anterior": previous_total,
        "stock_nuevo": payload.nuevo_stock_total,
        "observacion": payload.observacion,
    }


@router.get(
    "/inventory/movements",
    summary="CU-35: Consultar kardex de movimientos de inventario",
    description="CU-35. Historial auditable de recepciones, entradas, salidas y ajustes de inventario.",
)
def listar_movimientos_inventario(
    tipo: str | None = Query(default=None, description="Filtrar por ENTRADA, AJUSTE, VENTA, etc."),
    sucursal_id: int | None = Query(default=None, description="Filtrar por ID de sucursal"),
    variante_id: int | None = Query(default=None, description="Filtrar por ID de variante"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(InventoryMovement, ProductVariant, Product, Branch)
        .outerjoin(ProductVariant, ProductVariant.id == InventoryMovement.variante_id)
        .outerjoin(Product, Product.id == ProductVariant.producto_id)
        .outerjoin(Branch, Branch.id == InventoryMovement.sucursal_id)
    )

    # Restricción de visibilidad para personal que no sea ADMIN
    if staff.rol != Role.ADMIN:
        assigned_branch_ids = select(BranchStaff.sucursal_id).where(
            BranchStaff.usuario_id == staff.id,
            BranchStaff.activo.is_(True),
        )
        stmt = stmt.where(InventoryMovement.sucursal_id.in_(assigned_branch_ids))

    if tipo:
        stmt = stmt.where(InventoryMovement.tipo == tipo.upper())
    if sucursal_id:
        if staff.rol != Role.ADMIN and not staff_can_access_branch(db, staff, sucursal_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No está asignado a esta sucursal")
        stmt = stmt.where(InventoryMovement.sucursal_id == sucursal_id)
    if variante_id:
        stmt = stmt.where(InventoryMovement.variante_id == variante_id)

    stmt = stmt.order_by(InventoryMovement.id.desc()).offset(offset).limit(limit)
    results = db.execute(stmt).all()

    return [
        {
            "id": m.id,
            "variante_id": m.variante_id,
            "sku": variant.sku if variant else None,
            "producto": product.nombre if product else None,
            "color": variant.color if variant else None,
            "talla": variant.talla if variant else None,
            "sucursal_id": m.sucursal_id,
            "sucursal": branch.nombre if branch else None,
            "tipo": m.tipo,
            "cantidad": m.cantidad,
            "stock_total_anterior": m.stock_total_anterior,
            "stock_total_nuevo": m.stock_total_nuevo,
            "stock_anterior": m.stock_total_anterior,
            "stock_nuevo": m.stock_total_nuevo,
            "usuario_id": m.usuario_id,
            "observacion": m.observacion,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, variant, product, branch in results
    ]
