"""CU-39: Gestionar pedidos, ventas y entregas.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import BranchStaff, Order, Role, User
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
    _staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> list[Order]:
    stmt = select(Order)
    if _staff.rol != Role.ADMIN:
        stmt = stmt.where(Order.sucursal_id.in_(select(BranchStaff.sucursal_id).where(
            BranchStaff.usuario_id == _staff.id, BranchStaff.activo.is_(True),
        )))
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
    background_tasks: BackgroundTasks,
    _staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> Order:
    from .cu12_consultar_pedidos_e_historial_de_compras import update_status
    return update_status(order_id, payload, background_tasks, _staff, db)
