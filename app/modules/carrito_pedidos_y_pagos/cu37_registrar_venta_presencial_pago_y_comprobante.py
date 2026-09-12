"""CU-37: Registrar venta presencial, pago y comprobante.
Paquete: Carrito, pedidos y pagos (PK-03).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Branch, BranchStock, Order, OrderItem, Payment, Product, ProductVariant, Role, User
from app.services.store import staff_can_access_branch

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
    description="Permite al personal registrar una venta en tienda física, descontando inventario y emitiendo comprobante.",
)
def registrar_venta_pos(
    payload: PosSaleRequest,
    vendedor: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-37: Venta en mostrador / POS."""
    if not staff_can_access_branch(db, vendedor, payload.sucursal_id):
        raise HTTPException(403, 'No está asignado a la sucursal de venta')
    branch = db.get(Branch, payload.sucursal_id)
    if not branch or not branch.activo:
        raise HTTPException(404, 'Sucursal no disponible')
    if payload.cliente_id and not db.get(User, payload.cliente_id):
        raise HTTPException(404, 'Cliente no encontrado')
    if payload.metodo_pago.upper() not in {'EFECTIVO', 'QR', 'TARJETA', 'TRANSFERENCIA'}:
        raise HTTPException(422, 'Método de pago no válido')
    ids = [item.variante_id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Agrupa la cantidad de cada variante en una sola línea')
    # Lock in stable order and validate the entire sale before writing any order.
    for line in sorted(payload.items, key=lambda item: item.variante_id):
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == line.variante_id).with_for_update())
        product = db.get(Product, variant.producto_id) if variant else None
        stock = db.scalar(select(BranchStock).where(
            BranchStock.sucursal_id == payload.sucursal_id,
            BranchStock.variante_id == line.variante_id,
        ).with_for_update())
        if not variant or not variant.activo or not product or not product.activo:
            raise HTTPException(404, 'Prenda no disponible')
        if line.precio_unitario != product.precio:
            raise HTTPException(409, 'El precio cambió. Actualiza la selección antes de cobrar')
        if not stock or min(stock.stock_total - stock.stock_reservado,
                            variant.stock_total - variant.stock_reservado) < line.cantidad:
            raise HTTPException(409, 'Stock insuficiente en la sucursal seleccionada')
    total = sum((item.precio_unitario * item.cantidad for item in payload.items), Decimal("0.00"))

    order = Order(
        usuario_id=payload.cliente_id or vendedor.id,
        sucursal_id=payload.sucursal_id,
        estado="ENTREGADO",
        canal="TIENDA",
        tipo_entrega="TIENDA",
        subtotal=total,
        descuento=Decimal("0.00"),
        costo_envio=Decimal("0.00"),
        total=total,
        observacion=f"Venta en mostrador / POS por {vendedor.nombre}",
        paid_at=func.now(),
        completed_at=func.now(),
    )
    db.add(order)
    db.flush()

    for item_data in payload.items:
        variant = db.get(ProductVariant, item_data.variante_id)
        if not variant:
            raise HTTPException(
                status_code=404,
                detail=f"Variante ID {item_data.variante_id} no encontrada",
            )

        product = db.get(Product, variant.producto_id)
        branch_stock = db.scalar(
            select(BranchStock).where(
                BranchStock.sucursal_id == payload.sucursal_id,
                BranchStock.variante_id == variant.id,
            )
        )

        stock_disponible = (
            (branch_stock.stock_total - branch_stock.stock_reservado)
            if branch_stock
            else (variant.stock_total - variant.stock_reservado)
        )
        if stock_disponible < item_data.cantidad:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente para la variante '{variant.sku}' (Disponible: {stock_disponible})",
            )

        # Descontar de sucursal e inventario global
        if branch_stock:
            branch_stock.stock_total = max(0, branch_stock.stock_total - item_data.cantidad)
        variant.stock_total = max(0, variant.stock_total - item_data.cantidad)

        order_item = OrderItem(
            pedido_id=order.id,
            producto_id=product.id if product else variant.producto_id,
            variante_id=variant.id,
            nombre_snapshot=product.nombre if product else (variant.sku or "Prenda"),
            sku_snapshot=variant.sku,
            color_snapshot=variant.color or "Único",
            talla_snapshot=variant.talla or "U",
            cantidad=item_data.cantidad,
            precio_unitario=item_data.precio_unitario,
            descuento=Decimal("0.00"),
            subtotal=item_data.precio_unitario * item_data.cantidad,
        )
        db.add(order_item)

    payment_method = payload.metodo_pago.upper()
    if payment_method not in {"EFECTIVO", "QR", "TARJETA", "TRANSFERENCIA"}:
        payment_method = "EFECTIVO"

    import uuid
    ref = payload.numero_factura.strip() if payload.numero_factura else None
    if ref:
        existing_pay = db.scalar(select(Payment).where(Payment.referencia_externa == ref))
        if existing_pay:
            ref = f"{ref}-{order.id}"
    else:
        ref = f"POS-{order.id}-{uuid.uuid4().hex[:6]}"

    payment = Payment(
        pedido_id=order.id,
        monto=total,
        metodo=payment_method,
        proveedor="CAJA_POS",
        moneda="BOB",
        estado="APROBADO",
        referencia_externa=ref,
    )
    db.add(payment)
    db.commit()
    db.refresh(order)

    return {
        "pedido_id": order.id,
        "total": float(total),
        "estado": "ENTREGADO",
        "pago_estado": "APROBADO",
        "mensaje": "Venta presencial registrada y comprobante emitido exitosamente.",
    }
