from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Order, OrderItem, Payment, Role, User
from app.schemas.api import CheckoutRequest, OrderOut, OrderStatusUpdate
from app.services.store import cancel_unpaid_order, checkout_cart, staff_can_access_branch
from app.services.realtime import event_hub

router = APIRouter()


@router.get("/{order_id}/receipt", response_class=PlainTextResponse, summary="Descargar comprobante de compra (no fiscal)")
def receipt(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or (order.usuario_id != current_user.id and not staff_can_access_branch(db, current_user, order.sucursal_id)):
        raise HTTPException(404, "Pedido no encontrado")
    payments = list(db.scalars(select(Payment).where(Payment.pedido_id == order_id, Payment.estado == "APROBADO")))
    if not payments or order.estado == "CANCELADO":
        raise HTTPException(409, "El pedido todavía no tiene un pago aprobado")
    items = list(db.scalars(select(OrderItem).where(OrderItem.pedido_id == order_id).order_by(OrderItem.id)))
    lines = ["DRAPEMIND — COMPROBANTE DE COMPRA", "Comprobante interno, no es una factura fiscal.",
             f"Pedido: {order.codigo_publico}", f"Sucursal: {order.sucursal_id or 'Venta online'}", ""]
    lines += [f"{item.cantidad} x {item.nombre_snapshot} | {item.color_snapshot} | {item.talla_snapshot} | Bs {item.subtotal:.2f}" for item in items]
    lines += ["", f"Total: Bs {order.total:.2f}", f"Estado: {order.estado}",
              "Pago: " + ", ".join(p.metodo for p in payments)]
    return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": f'attachment; filename="comprobante-{order_id}.txt"'})


@router.post(
    "/checkout", response_model=OrderOut, status_code=201, summary="Checkout del carrito",
    description="CU-23/CU-24. Toma precios del servidor, crea snapshots, bloquea stock y convierte el carrito.",
)
def checkout(
    payload: CheckoutRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Order:
    order = checkout_cart(
        db, current_user, payload.tipo_entrega, payload.direccion_id,
        payload.costo_envio, payload.observacion,
    )
    background_tasks.add_task(
        event_hub.publish,
        {"type": "order_created", "order_id": order.id, "status": order.estado},
        None,
        {"ADMIN", "VENDEDOR"},
    )
    return order


@router.get("", response_model=list[OrderOut], summary="Historial de pedidos")
def list_orders(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Order]:
    if current_user.rol in (Role.ADMIN, Role.VENDEDOR):
        return list(db.scalars(select(Order).order_by(Order.created_at.desc())))
    return list(db.scalars(select(Order).where(Order.usuario_id == current_user.id).order_by(Order.created_at.desc())))


@router.get("/{order_id}", response_model=OrderOut, summary="Consultar estado del pedido")
def get_order(
    order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Order:
    if current_user.rol in (Role.ADMIN, Role.VENDEDOR):
        order = db.get(Order, order_id)
    else:
        order = db.scalar(select(Order).where(Order.id == order_id, Order.usuario_id == current_user.id))
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    return order


@router.patch("/{order_id}/status", response_model=OrderOut, summary="Actualizar estado del pedido")
def update_status(
    order_id: int,
    payload: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    allowed = {
        "PENDIENTE_PAGO": {"CANCELADO"}, "PAGADO": {"PREPARANDO"},
        "PREPARANDO": {"LISTO", "CANCELADO"}, "LISTO": {"ENVIADO", "ENTREGADO"},
        "ENVIADO": {"ENTREGADO"}, "ENTREGADO": set(), "CANCELADO": set(),
    }
    if not staff_can_access_branch(db, staff, order.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal del pedido")
    if payload.estado not in allowed[order.estado]:
        raise HTTPException(409, f"Transicion {order.estado} -> {payload.estado} no permitida")
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


@router.post("/{order_id}/cash-confirm", response_model=OrderOut, summary="Confirmar y registrar cobro en efectivo por vendedor")
def confirm_order_cash_payment(
    order_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, f"El pedido ya esta en estado {order.estado}")
    if not staff_can_access_branch(db, staff, order.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal del pedido")

    from app.models import Payment
    from app.services.store import confirm_payment, create_payment

    payment = db.scalar(select(Payment).where(Payment.pedido_id == order.id, Payment.metodo == "EFECTIVO"))
    if not payment:
        payment = create_payment(db, order, "EFECTIVO")
    confirm_payment(db, payment.referencia_externa, "APROBADO")
    db.refresh(order)

    event = {"type": "order_updated", "order_id": order.id, "status": order.estado}
    background_tasks.add_task(event_hub.publish, event, order.usuario_id)
    background_tasks.add_task(event_hub.publish, event, None, {"ADMIN", "VENDEDOR"})
    return order
