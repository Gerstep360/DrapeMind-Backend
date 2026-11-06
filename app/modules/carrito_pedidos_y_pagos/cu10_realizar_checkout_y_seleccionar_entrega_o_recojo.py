from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Order, User
from app.schemas.api import CheckoutRequest, OrderOut
from app.services.realtime import event_hub
from app.services.store import checkout_cart
from app.incrementos.incremento_ii.common import digest

router = APIRouter()


@router.post(
    "/checkout",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-10: Checkout del carrito y selección de entrega",
    description="CU-10. Toma precios del servidor, crea snapshots, bloquea stock y convierte el carrito en pedido.",
)
def realizar_checkout(
    payload: CheckoutRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Order:
    order = checkout_cart(
        db,
        current_user,
        payload.tipo_entrega,
        payload.direccion_id,
        payload.costo_envio,
        payload.observacion,
        payload.codigo_promocion,
        payload.sucursal_id,
        payload.canal,
        str(payload.operacion_id) if payload.operacion_id else None,
        digest(payload.model_dump(mode='json')),
    )
    if db.info.get('checkout_replayed'):return order
    background_tasks.add_task(
        event_hub.publish,
        {"type": "order_created", "order_id": order.id, "status": order.estado},
        None,
        {"ADMIN", "VENDEDOR"},
    )
    from app.incrementos.incremento_iii.notifications import notify
    background_tasks.add_task(
        notify,
        order.tenant_id,
        order.usuario_id,
        "Compra Registrada",
        f"Tu pedido #{order.id} ha sido registrado exitosamente por Bs. {float(order.total):,.2f}.",
        "COMPRA",
        {"screen": "/orders", "order_id": order.id},
    )
    return order


