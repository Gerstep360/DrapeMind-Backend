from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Branch, Order, OrderItem, Payment, Role, User
from app.schemas.api import OrderOut, OrderStatusUpdate
from app.services.realtime import event_hub
from app.services.store import (
    cancel_unpaid_order,
    confirm_payment,
    create_payment,
    staff_can_access_branch,
)

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


@router.post(
    "/{order_id}/cash-confirm",
    response_model=OrderOut,
    summary="CU-37: Confirmar y registrar cobro en efectivo por vendedor",
)
def confirm_order_cash_payment(
    order_id: int,
    background_tasks: BackgroundTasks,
    staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido no encontrado")
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, f"El pedido ya esta en estado {order.estado}")
    if staff.rol != Role.ADMIN and not staff_can_access_branch(db, staff, order.sucursal_id):
        raise HTTPException(403, "No está asignado a la sucursal del pedido")

    payment = db.scalar(
        select(Payment).where(Payment.pedido_id == order.id, Payment.metodo == "EFECTIVO")
    )
    if not payment:
        payment = create_payment(db, order, "EFECTIVO")
    confirm_payment(db, payment.referencia_externa, "APROBADO")
    db.refresh(order)

    event = {"type": "order_updated", "order_id": order.id, "status": order.estado}
    background_tasks.add_task(event_hub.publish, event, order.usuario_id)
    background_tasks.add_task(
        event_hub.publish, event, None, {"ADMIN", "VENDEDOR", "ENCARGADO", "CAJERO"}
    )
    return order


@router.get(
    "/{order_id}/receipt",
    summary="CU-12: Descargar comprobante de compra (no fiscal)",
)
def download_receipt(
    order_id: int,
    format: str = "json",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if not order or (
        order.usuario_id != current_user.id
        and current_user.rol not in (Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO)
    ):
        raise HTTPException(404, "Pedido no encontrado")

    if order.estado not in {"PAGADO", "PREPARANDO", "LISTO", "ENVIADO", "ENTREGADO"}:
        payments = list(
            db.scalars(
                select(Payment).where(
                    Payment.pedido_id == order_id, Payment.estado == "APROBADO"
                )
            )
        )
        if not payments:
            raise HTTPException(409, "El pedido todavía no tiene un pago aprobado o confirmado")

    payments = list(
        db.scalars(
            select(Payment).where(Payment.pedido_id == order_id).order_by(Payment.id)
        )
    )
    items = list(
        db.scalars(
            select(OrderItem).where(OrderItem.pedido_id == order_id).order_by(OrderItem.id)
        )
    )
    cliente = db.get(User, order.usuario_id)
    sucursal = db.get(Branch, order.sucursal_id) if order.sucursal_id else None

    if format == "json":
        return {
            "order": {
                "id": order.id,
                "codigo_publico": order.codigo_publico,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "estado": order.estado,
                "canal": order.canal,
                "tipo_entrega": order.tipo_entrega,
                "subtotal": float(order.subtotal),
                "descuento": float(order.descuento),
                "costo_envio": float(order.costo_envio),
                "total": float(order.total),
                "observacion": order.observacion,
            },
            "sucursal": {
                "id": sucursal.id if sucursal else 1,
                "nombre": sucursal.nombre if sucursal else "Showroom Central DrapeMind",
                "ciudad": "Santa Cruz",
                "direccion": sucursal.direccion if sucursal else "Av. Las Américas #780, Equipetrol",
                "telefono": sucursal.telefono if sucursal else "63014529",
            },
            "cliente": {
                "id": cliente.id if cliente else None,
                "nombre": cliente.nombre if cliente else "Cliente DrapeMind",
                "email": cliente.email if cliente else "",
                "telefono": cliente.telefono if cliente else "",
            },
            "items": [
                {
                    "id": item.id,
                    "nombre": item.nombre_snapshot,
                    "sku": item.sku_snapshot,
                    "color": item.color_snapshot,
                    "talla": item.talla_snapshot,
                    "cantidad": item.cantidad,
                    "precio_unitario": float(item.precio_unitario),
                    "subtotal": float(item.subtotal),
                }
                for item in items
            ],
            "payments": [
                {
                    "id": p.id,
                    "metodo": p.metodo,
                    "monto": float(p.monto),
                    "estado": p.estado,
                    "referencia": p.referencia_externa,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in payments
            ],
        }

    # Fallback texto plano
    lines = [
        "==================================================",
        "              DRAPEMIND ATELIER MODA              ",
        "         Comprobante de Venta y Entrega           ",
        "==================================================",
        "",
        f"Código de Pedido : {order.codigo_publico}",
        f"Fecha y Hora     : {order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else ''}",
        f"Sucursal         : {sucursal.nombre if sucursal else 'Showroom Central'}",
        f"Modalidad        : {order.tipo_entrega}",
        f"Estado del Pedido: {order.estado}",
        "",
        "--------------------------------------------------",
        "DETALLE DE PRENDAS:",
        "--------------------------------------------------",
    ]
    for item in items:
        lines.append(
            f"{item.cantidad}x {item.nombre_snapshot} ({item.color_snapshot}, Talla {item.talla_snapshot})"
        )
        lines.append(
            f"   SKU: {item.sku_snapshot} | Precio: Bs {item.precio_unitario:.2f} | Subtotal: Bs {item.subtotal:.2f}"
        )

    lines.extend([
        "--------------------------------------------------",
        f"Subtotal Prendas : Bs {sum((i.subtotal for i in items), Decimal('0')):.2f}",
        f"Costo de Envío   : Bs {order.costo_envio:.2f}",
        f"TOTAL PAGADO     : Bs {order.total:.2f} BOB",
        "--------------------------------------------------",
        f"Método de Pago   : {', '.join(p.metodo for p in payments) if payments else 'PAGO EN TIENDA / EFECTIVO'}",
        "",
        "¡Gracias por confiar en el estilo y confección DrapeMind!",
        "Documento interno informativo y comprobante de entrega.",
        "==================================================",
    ])

    return PlainTextResponse(
        "\n".join(lines),
        headers={
            "Content-Disposition": f'attachment; filename="comprobante-pedido-{order_id}.txt"'
        },
    )



