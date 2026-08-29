"""CU-39: Gestionar pedidos, ventas y entregas.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Order, Role, User
from app.schemas.api import OrderOut, OrderStatusUpdate

router = APIRouter()


@router.get(
    "/orders",
    response_model=list[OrderOut],
    summary="CU-39: Listar todos los pedidos de la plataforma",
    description="Permite al personal y administración consultar órdenes de todos los clientes con filtros por estado.",
)
def listar_pedidos_admin(
    state: str | None = None,
    sucursal_id: int | None = None,
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[Order]:
    stmt = select(Order)
    if state:
        stmt = stmt.where(Order.estado == state)
    if sucursal_id:
        stmt = stmt.where(Order.sucursal_id == sucursal_id)
    return list(db.scalars(stmt.order_by(Order.created_at.desc()).limit(200)))


@router.patch(
    "/orders/{order_id}/status",
    response_model=OrderOut,
    summary="CU-39: Actualizar estado de despacho o entrega",
    description="Avanza el estado del pedido (PENDIENTE, PAGADO, PREPARANDO, ENVIADO, ENTREGADO, CANCELADO).",
)
def actualizar_estado_pedido(
    order_id: int,
    payload: OrderStatusUpdate,
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    order.estado = payload.estado
    db.commit()
    db.refresh(order)
    return order
