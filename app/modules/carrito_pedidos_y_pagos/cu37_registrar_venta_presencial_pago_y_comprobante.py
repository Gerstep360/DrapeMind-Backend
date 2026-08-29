"""CU-37: Registrar venta presencial, pago y comprobante.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Order, OrderItem, Payment, ProductVariant, Role, User

router = APIRouter()


class PosSaleItem(BaseModel):
    variante_id: int
    cantidad: int = Field(ge=1)
    precio_unitario: Decimal = Field(ge=0)


class PosSaleRequest(BaseModel):
    sucursal_id: int
    cliente_id: int | None = None
    items: list[PosSaleItem] = Field(min_length=1)
    metodo_pago: str = Field(default="EFECTIVO")
    numero_factura: str | None = None


@router.post(
    "/sales/pos",
    status_code=status.HTTP_201_CREATED,
    summary="CU-37: Registrar venta presencial en caja",
    description="Permite a vendedores registrar una venta en tienda física, descontando inventario y emitiendo comprobante.",
)
def registrar_venta_pos(
    payload: PosSaleRequest,
    vendedor: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-37: Venta en mostrador / POS."""
    total = sum(item.precio_unitario * item.cantidad for item in payload.items)

    order = Order(
        usuario_id=payload.cliente_id or vendedor.id,
        sucursal_id=payload.sucursal_id,
        total=total,
        estado="ENTREGADO",
        metodo_entrega="RECOJO_SUCURSAL",
        notas=f"Venta en mostrador por {vendedor.nombre}",
    )
    db.add(order)
    db.flush()

    for item_data in payload.items:
        variant = db.get(ProductVariant, item_data.variante_id)
        if not variant or (variant.stock_disponible or 0) < item_data.cantidad:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente para la variante ID {item_data.variante_id}",
            )
        variant.stock_disponible = max(0, variant.stock_disponible - item_data.cantidad)
        variant.stock_total = max(0, variant.stock_total - item_data.cantidad)

        order_item = OrderItem(
            pedido_id=order.id,
            variante_id=variant.id,
            cantidad=item_data.cantidad,
            precio_unitario=item_data.precio_unitario,
            subtotal=item_data.precio_unitario * item_data.cantidad,
        )
        db.add(order_item)

    payment = Payment(
        pedido_id=order.id,
        monto=total,
        metodo=payload.metodo_pago,
        estado="APROBADO",
        transaccion_externa_id=payload.numero_factura or f"POS-{order.id}",
    )
    db.add(payment)
    db.commit()

    return {
        "pedido_id": order.id,
        "total": float(total),
        "estado": "ENTREGADO",
        "pago_estado": "APROBADO",
        "mensaje": "Venta presencial registrada y comprobante emitido exitosamente.",
    }
