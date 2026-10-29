"""Reglas comunes CU-15/17/19/20: caja, stock por sucursal y comprobantes."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from app.models import (Branch, BranchStock, Product, ProductVariant, Order, OrderItem,
                        Payment, Reservation, ReservationItem, Role, User, UserStatus, InventoryMovement)
from app.services.saas import aware
from app.services.store import staff_can_access_branch, _sync_variant_inventory

CENT = Decimal('0.01')


def fail(code, message, status=409):
    raise HTTPException(status, {'code':code,'message':message})


def branch_access(db, user, branch_id, *, require_active=True):
    branch = db.get(Branch, branch_id)
    if not branch or (require_active and not branch.activo):
        fail('BRANCH_UNAVAILABLE','La sucursal ya no está disponible',404)
    if user.rol != Role.CLIENTE and not staff_can_access_branch(db,user,branch_id):
        fail('BRANCH_FORBIDDEN','No estás asignado a esta sucursal',403)
    return branch


def variant_stock(db, variant_id, branch_id):
    variant = db.scalar(select(ProductVariant).where(ProductVariant.id==variant_id).with_for_update())
    product = db.get(Product,variant.producto_id) if variant else None
    if not variant or not variant.activo or not product or not product.activo:
        fail('PRODUCT_UNAVAILABLE','Una de las prendas ya no está disponible')
    stock = db.scalar(select(BranchStock).where(BranchStock.variante_id==variant_id,
        BranchStock.sucursal_id==branch_id,BranchStock.activo.is_(True)).with_for_update())
    if not stock:
        fail('STOCK_CHANGED','No hay existencias de esa talla en la sucursal')
    return variant,product,stock


def movement(db, variant, stock, quantity, actor_id, ref_type, ref_id, *, reserved_delta=0):
    before_total,before_reserved=variant.stock_total,variant.stock_reservado
    stock.stock_total+=quantity
    stock.stock_reservado+=reserved_delta
    if stock.stock_total < stock.stock_reservado or stock.stock_reservado < 0:
        fail('STOCK_CHANGED','El inventario de la sucursal cambió; revisa la operación')
    db.flush()
    _sync_variant_inventory(db,variant)
    db.add(InventoryMovement(variante_id=variant.id,sucursal_id=stock.sucursal_id,
        tipo='VENTA' if quantity<0 else 'DEVOLUCION',cantidad=quantity,
        stock_total_anterior=before_total,stock_total_nuevo=variant.stock_total,
        stock_reservado_anterior=before_reserved,stock_reservado_nuevo=variant.stock_reservado,
        usuario_id=actor_id,referencia_tipo=ref_type,referencia_id=ref_id))


def order_line(db,order,variant,product,quantity,price):
    db.add(OrderItem(pedido_id=order.id,producto_id=product.id,variante_id=variant.id,
        nombre_snapshot=product.nombre,sku_snapshot=variant.sku,color_snapshot=variant.color,
        talla_snapshot=variant.talla,cantidad=quantity,precio_unitario=price,descuento=0,subtotal=price*quantity))


def ticket(order, received=None):
    result={'pedido_id':order.id,'codigo_publico':str(order.codigo_publico),'sucursal_id':order.sucursal_id,
            'total':str(order.total),'estado':order.estado,'pago_estado':'APROBADO' if order.paid_at else 'PENDIENTE'}
    if received is not None:
        result.update(efectivo_recibido=str(received),cambio=str(received-order.total))
    return result


def apply_cash_sale(db,user,payload,*,pickup=False,accept_saved_price=False):
    branch_access(db,user,payload.sucursal_id)
    if payload.creado_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        fail('CLOCK_INVALID','Revisa la fecha y hora del dispositivo',422)
    reservation=None
    if pickup:
        reservation=db.scalar(select(Reservation).where(Reservation.id==payload.reserva_id).with_for_update())
        if not reservation or reservation.sucursal_id!=payload.sucursal_id:
            fail('RESERVATION_UNAVAILABLE','No se encontró esa reserva en la sucursal',404)
        if reservation.estado=='CONVERTIDA' or db.scalar(select(Order.id).where(Order.reserva_id==reservation.id)):
            fail('ALREADY_SOLD','La reserva ya tiene una venta. No vuelvas a cobrarla.')
        if aware(reservation.vence_at)<=datetime.now(timezone.utc) or reservation.estado not in ('PENDIENTE','CONFIRMADA','EN_PREPARACION','LISTA','RETIRADA'):
            fail('RESERVATION_EXPIRED','La reserva venció o ya no puede retirarse')
        held={i.variante_id:i for i in db.scalars(select(ReservationItem).where(ReservationItem.reserva_id==reservation.id))}
        if {i.variante_id:i.cantidad for i in payload.items}!={k:i.cantidad for k,i in held.items()}:
            fail('RESERVATION_CHANGED','La selección ya no coincide con las prendas reservadas')
    customer_id=reservation.usuario_id if reservation else payload.cliente_id
    if customer_id:
        customer=db.get(User,customer_id)
        if not customer or customer.rol!=Role.CLIENTE or customer.estado!=UserStatus.ACTIVO:
            fail('CUSTOMER_UNAVAILABLE','No se encontró al cliente en esta tienda',404)
    checked=[]
    for line in sorted(payload.items,key=lambda i:i.variante_id):
        variant,product,stock=variant_stock(db,line.variante_id,payload.sucursal_id)
        price=held[variant.id].precio_referencia if pickup else product.precio
        if line.precio_unitario!=price and not accept_saved_price:
            fail('PRICE_CHANGED','El precio cambió. Un encargado debe revisar el importe cobrado.')
        if (stock.stock_reservado if pickup else stock.stock_total-stock.stock_reservado)<line.cantidad or stock.stock_total<line.cantidad:
            fail('STOCK_CHANGED','No hay unidades suficientes en la sucursal para registrar esta venta')
        checked.append((line,variant,product,stock))
    total=sum((line.precio_unitario*line.cantidad for line in payload.items),Decimal('0.00'))
    if total>Decimal('99999999.99'):
        fail('AMOUNT_TOO_LARGE','El importe supera el límite admitido por un comprobante',422)
    if payload.efectivo_recibido<total:
        fail('CASH_INSUFFICIENT','El efectivo recibido no cubre el total',422)
    now=datetime.now(timezone.utc)
    order=Order(codigo_publico=uuid4(),usuario_id=customer_id,atendido_por_id=user.id,
        comprador_registrado=customer_id is not None,reserva_id=reservation.id if reservation else None,
        sucursal_id=payload.sucursal_id,estado='ENTREGADO',canal='TIENDA',tipo_entrega='TIENDA',
        subtotal=total,descuento=0,costo_envio=0,total=total,paid_at=now,completed_at=now,
        observacion=payload.observacion or 'Venta de contado sincronizada')
    db.add(order);db.flush()
    for line,variant,product,stock in checked:
        movement(db,variant,stock,-line.cantidad,user.id,'PEDIDO',order.id,reserved_delta=-line.cantidad if pickup else 0)
        order_line(db,order,variant,product,line.cantidad,line.precio_unitario)
    db.add(Payment(pedido_id=order.id,metodo='EFECTIVO',proveedor='CAJA_OFFLINE',monto=total,
        moneda='BOB',estado='APROBADO',referencia_externa=f'OFFLINE-{user.tenant_id}-{user.id}-{payload.operacion_id}',paid_at=now))
    if reservation:
        reservation.estado='CONVERTIDA';reservation.atendido_por_id=user.id;reservation.atendido_at=now
    db.flush()
    return ticket(order,payload.efectivo_recibido)
