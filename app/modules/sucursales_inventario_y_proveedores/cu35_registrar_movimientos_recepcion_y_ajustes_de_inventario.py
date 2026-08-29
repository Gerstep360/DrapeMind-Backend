from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import InventoryMovement, ProductVariant, Role, User
from app.schemas.api import InventoryAdjustment

router = APIRouter()


@router.post(
    "/inventory/adjustments",
    status_code=201,
    summary="CU-35: Ajustar inventario",
    description="CU-35. Bloquea la variante y registra antes/después en movimientos_inventario.",
)
def ajustar_inventario(
    payload: InventoryAdjustment,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.scalar(
        select(ProductVariant)
        .where(ProductVariant.id == payload.variante_id)
        .with_for_update()
    )
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    if payload.nuevo_stock_total < variant.stock_reservado:
        raise HTTPException(409, "El nuevo total es menor que el stock reservado")
    previous = variant.stock_total
    difference = payload.nuevo_stock_total - previous
    variant.stock_total = payload.nuevo_stock_total
    db.add(
        InventoryMovement(
            variante_id=variant.id,
            tipo="AJUSTE",
            cantidad=difference,
            stock_total_anterior=previous,
            stock_total_nuevo=variant.stock_total,
            stock_reservado_anterior=variant.stock_reservado,
            stock_reservado_nuevo=variant.stock_reservado,
            usuario_id=admin.id,
            observacion=payload.observacion,
        )
    )
    db.commit()
    return {
        "variante_id": variant.id,
        "stock_anterior": previous,
        "stock_nuevo": variant.stock_total,
    }


@router.get(
    "/inventory/movements",
    summary="CU-35: Consultar kardex de movimientos de inventario",
    description="Historial de entradas, salidas y ajustes de stock.",
)
def listar_movimientos_inventario(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[dict]:
    movements = list(
        db.scalars(
            select(InventoryMovement)
            .order_by(InventoryMovement.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return [
        {
            "id": m.id,
            "variante_id": m.variante_id,
            "tipo": m.tipo,
            "cantidad": m.cantidad,
            "stock_anterior": m.stock_total_anterior,
            "stock_nuevo": m.stock_total_nuevo,
            "observacion": m.observacion,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in movements
    ]

