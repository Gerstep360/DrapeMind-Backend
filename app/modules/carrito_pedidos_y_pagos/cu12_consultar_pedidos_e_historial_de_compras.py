from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Order, Role, User
from app.schemas.api import OrderOut, OrderStatusUpdate
from app.services.realtime import event_hub
from app.services.store import cancel_unpaid_order

router = APIRouter()


@router.get("", response_model=list[OrderOut], summary="CU-12: Historial de pedidos")
def list_orders(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Order]:
    if current_user.rol in (Role.ADMIN, Role.VENDEDOR):
        return list(db.scalars(select(Order).order_by(Order.created_at.desc())))
    return list(
        db.scalars(
            select(Order)
            .where(Order.usuario_id == current_user.id)
            .order_by(Order.created_at.desc())
        )
    )


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    summary="CU-12: Consultar estado del pedido",
)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Order:
    if current_user.rol in (Role.ADMIN, Role.VENDEDOR):
        order = db.get(Order, order_id)
    else:
        order = db.scalar(
            select(Order).where(
                Order.id == order_id, Order.usuario_id == current_user.id
            )
        )
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    return order


@router.patch(
    "/{order_id}/status",
    response_model=OrderOut,
    summary="CU-12: Actualizar estado del pedido",
)
def update_status(
    order_id: int,
    payload: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    allowed = {
        "PENDIENTE_PAGO": {"PAGADO", "CANCELADO"},
        "PAGADO": {"PREPARANDO"},
        "PREPARANDO": {"LISTO", "CANCELADO"},
        "LISTO": {"ENVIADO", "ENTREGADO"},
        "ENVIADO": {"ENTREGADO"},
        "ENTREGADO": set(),
        "CANCELADO": set(),
    }
    if payload.estado not in allowed[order.estado]:
        raise HTTPException(
            409, f"Transicion {order.estado} -> {payload.estado} no permitida"
        )
    if payload.estado == "CANCELADO":
        order = cancel_unpaid_order(db, order, staff.id)
        background_tasks.add_task(
            event_hub.publish,
            {"type": "order_updated", "order_id": order.id, "status": order.estado},
            order.usuario_id,
        )
        return order
    order.estado = payload.estado
    if payload.estado == "ENTREGADO":
        order.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    event = {"type": "order_updated", "order_id": order.id, "status": order.estado}
    background_tasks.add_task(event_hub.publish, event, order.usuario_id)
    background_tasks.add_task(
        event_hub.publish, event, None, {"ADMIN", "VENDEDOR"}
    )
    return order


@router.post(
    "/{order_id}/cancel",
    response_model=OrderOut,
    summary="CU-12: Cancelar pedido pendiente",
)
def cancel_order(
    order_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Order:
    order = db.scalar(
        select(Order).where(
            Order.id == order_id, Order.usuario_id == current_user.id
        )
    )
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, "Solo se pueden cancelar pedidos pendientes de pago")
    order = cancel_unpaid_order(db, order, current_user.id)
    background_tasks.add_task(
        event_hub.publish,
        {"type": "order_cancelled", "order_id": order.id},
        order.usuario_id,
    )
    return order

