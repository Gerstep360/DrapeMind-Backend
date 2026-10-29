"""Cambios parciales, crédito aplicado y diferencia de efectivo con trazabilidad."""
from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid4,UUID
from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,func,cast,String,or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Order,OrderItem,Payment,ProductVariant,Product,BranchStock,Role,User
from app.services.saas import require_active_subscription
from .models import GarmentExchange,ExchangeReturn
from .schemas import ExchangeCreate
from .common import digest
from .retail_service import branch_access,variant_stock,movement,order_line,ticket,fail,CENT

router=APIRouter(prefix='/retail',tags=['Incremento II · CU-20 Cambios de prendas'])
staff=require_roles(Role.ADMIN,Role.ENCARGADO,Role.CAJERO)


def merchandise_factor(order):
    return max(Decimal('0'),(order.subtotal-order.descuento)/order.subtotal) if order.subtotal else Decimal('0')


def exchange_payload(db,exchange):
    new_order=db.get(Order,exchange.pedido_nuevo_id)
    return {'id':exchange.id,'operacion_id':exchange.operacion_id,'pedido_origen_id':exchange.pedido_origen_id,
        'pedido_nuevo_id':exchange.pedido_nuevo_id,'sucursal_id':exchange.sucursal_id,
        'credito':str(exchange.credito),'total_nuevo':str(exchange.total_nuevo),'diferencia':str(exchange.diferencia),
        'efectivo_recibido':str(exchange.efectivo_recibido),'efectivo_devuelto':str(exchange.efectivo_devuelto),
        'motivo':exchange.motivo,'actor_id':exchange.actor_id,'created_at':exchange.created_at,
        'sale':ticket(new_order)}


@router.get('/orders/find')
def find_order(code:str=Query(min_length=1,max_length=40),user:User=Depends(staff),db:Session=Depends(get_db)):
    value=code.strip()
    if value.isdecimal():
        condition=Order.id==int(value)
    elif len(value)>=8:
        condition=cast(Order.codigo_publico,String).ilike(value.replace('%','').replace('_','')+'%')
    else:fail('INVALID_CODE','Introduce el número de pedido o al menos ocho caracteres del comprobante',422)
    orders=list(db.scalars(select(Order).where(condition).limit(2)))
    if len(orders)!=1:fail('NOT_FOUND','No se encontró un comprobante único con ese código',404)
    order=orders[0]
    branch_access(db,user,order.sucursal_id)
    returned=dict(db.execute(select(ExchangeReturn.item_pedido_id,func.sum(ExchangeReturn.cantidad)).group_by(ExchangeReturn.item_pedido_id)).all())
    return {**ticket(order),'cliente_id':order.usuario_id,'items':[{'id':i.id,'variante_id':i.variante_id,'nombre':i.nombre_snapshot,
        'talla':i.talla_snapshot,'color':i.color_snapshot,'cantidad':i.cantidad,'precio_unitario':str(i.precio_unitario),
        'credito_unitario':str((i.subtotal*merchandise_factor(order)/i.cantidad).quantize(CENT)),
        'disponible_cambio':i.cantidad-int(returned.get(i.id,0))} for i in db.scalars(select(OrderItem).where(OrderItem.pedido_id==order.id))]}


@router.get('/exchanges')
def exchanges(sucursal_id:int,user:User=Depends(staff),db:Session=Depends(get_db)):
    branch_access(db,user,sucursal_id)
    return [exchange_payload(db,e) for e in db.scalars(select(GarmentExchange).where(GarmentExchange.sucursal_id==sucursal_id).order_by(GarmentExchange.id.desc()).limit(100))]


@router.post('/exchanges')
def create_exchange(payload:ExchangeCreate,preview:bool=False,user:User=Depends(staff),db:Session=Depends(get_db)):
    try:
        return apply_exchange(payload,preview,user,db)
    except IntegrityError:
        db.rollback()
        fail('EXCHANGE_CONFLICT','El comprobante cambió o esta operación ya fue registrada. Comprueba el resultado antes de repetirla.')


def apply_exchange(payload,preview,user,db):
    require_active_subscription(db,user.tenant_id,'products_sales')
    branch_access(db,user,payload.sucursal_id)
    # Serialize all returns of the source ticket, including requests from different cashiers.
    source=db.scalar(select(Order).where(Order.id==payload.pedido_origen_id).with_for_update())
    if not source:fail('NOT_FOUND','Comprobante de origen no encontrado',404)
    branch_access(db,user,source.sucursal_id,require_active=False)
    fingerprint=digest(payload.model_dump(mode='json'))
    previous=db.scalar(select(GarmentExchange).where(GarmentExchange.operacion_id==str(payload.operacion_id)))
    if previous:
        if previous.payload_hash!=fingerprint:fail('OPERATION_REUSED','Ese cambio ya se registró con otros datos')
        return exchange_payload(db,previous)
    if source.estado!='ENTREGADO' or source.paid_at is None:
        fail('ORDER_UNPAID','Solo puedes cambiar prendas de una venta pagada y entregada')
    originals={i.id:i for i in db.scalars(select(OrderItem).where(OrderItem.pedido_id==source.id))}
    past=db.execute(select(ExchangeReturn.item_pedido_id,func.sum(ExchangeReturn.cantidad),func.sum(ExchangeReturn.credito)).where(
        ExchangeReturn.item_pedido_id.in_(originals)).group_by(ExchangeReturn.item_pedido_id)).all()
    returned={row[0]:row[1] for row in past}
    used_credit={row[0]:row[2] for row in past}
    credit=Decimal('0.00');line_credits={}
    for row in payload.devoluciones:
        item=originals.get(row.item_pedido_id)
        if not item or not item.variante_id or row.cantidad>item.cantidad-int(returned.get(item.id,0)):
            fail('ALREADY_RETURNED','La cantidad supera las prendas que aún puedes cambiar de este comprobante')
        original_credit=(item.subtotal*merchandise_factor(source)).quantize(CENT)
        remaining=item.cantidad-int(returned.get(item.id,0))
        amount=(original_credit-used_credit.get(item.id,Decimal('0'))) if row.cantidad==remaining else (original_credit*row.cantidad/item.cantidad).quantize(CENT)
        line_credits[item.id]=amount
        credit+=amount
    all_ids=sorted({originals[i.item_pedido_id].variante_id for i in payload.devoluciones}|{i.variante_id for i in payload.prendas_nuevas})
    locked={}
    for variant_id in all_ids:
        v=db.scalar(select(ProductVariant).where(ProductVariant.id==variant_id).with_for_update())
        if not v:fail('PRODUCT_UNAVAILABLE','Una variante del comprobante ya no existe')
        s=db.scalar(select(BranchStock).where(BranchStock.variante_id==variant_id,BranchStock.sucursal_id==payload.sucursal_id).with_for_update())
        if s and not s.activo:
            fail('STOCK_DISABLED','Reactiva el inventario de esta talla en la sucursal antes de registrar el cambio')
        locked[variant_id]=(v,s)
    returned_qty={}
    for row in payload.devoluciones:
        vid=originals[row.item_pedido_id].variante_id
        returned_qty[vid]=returned_qty.get(vid,0)+row.cantidad
    total=Decimal('0.00');new_rows=[]
    for row in payload.prendas_nuevas:
        v,s=locked[row.variante_id];p=db.get(Product,v.producto_id)
        if not v.activo or not p or not p.activo:fail('PRODUCT_UNAVAILABLE','Una prenda nueva ya no está a la venta')
        available=(s.stock_total-s.stock_reservado if s and s.activo else 0)+returned_qty.get(v.id,0)
        if available<row.cantidad:fail('STOCK_CHANGED','No hay stock suficiente de la prenda nueva en esta sucursal')
        total+=p.precio*row.cantidad;new_rows.append((row,v,p))
    difference=total-credit
    if total>Decimal('99999999.99'):
        fail('AMOUNT_TOO_LARGE','El importe supera el límite admitido por un comprobante',422)
    if preview:
        return {'credito':str(credit),'total_nuevo':str(total),'diferencia':str(difference)}
    if payload.efectivo_recibido-payload.efectivo_devuelto!=difference:
        fail('CASH_DIFFERENCE','Revisa el efectivo recibido y devuelto: deben coincidir con la diferencia del cambio',422)
    now=datetime.now(timezone.utc)
    order=Order(codigo_publico=uuid4(),usuario_id=source.usuario_id,atendido_por_id=user.id,
        comprador_registrado=source.comprador_registrado,sucursal_id=payload.sucursal_id,
        estado='ENTREGADO',canal='TIENDA',tipo_entrega='TIENDA',subtotal=total,descuento=0,costo_envio=0,
        total=total,paid_at=now,completed_at=now,observacion=f'Cambio de prendas del pedido {source.id}')
    db.add(order);db.flush()
    exchange=GarmentExchange(operacion_id=str(payload.operacion_id),payload_hash=fingerprint,
        pedido_origen_id=source.id,pedido_nuevo_id=order.id,sucursal_id=payload.sucursal_id,actor_id=user.id,
        motivo=payload.motivo,credito=credit,total_nuevo=total,diferencia=difference,
        efectivo_recibido=payload.efectivo_recibido,efectivo_devuelto=payload.efectivo_devuelto)
    db.add(exchange);db.flush()
    for row in payload.devoluciones:
        item=originals[row.item_pedido_id];v,s=locked[item.variante_id]
        if not s:
            s=BranchStock(variante_id=v.id,sucursal_id=payload.sucursal_id,stock_total=0,stock_reservado=0,activo=True)
            db.add(s);db.flush();locked[v.id]=(v,s)
        s.activo=True
        movement(db,v,s,row.cantidad,user.id,'CAMBIO',exchange.id)
        db.add(ExchangeReturn(cambio_id=exchange.id,item_pedido_id=item.id,cantidad=row.cantidad,credito=line_credits[item.id]))
    for row,v,p in new_rows:
        s=locked[v.id][1]
        movement(db,v,s,-row.cantidad,user.id,'CAMBIO',exchange.id)
        order_line(db,order,v,p,row.cantidad,p.precio)
    applied=min(credit,total)
    if applied:
        db.add(Payment(pedido_id=order.id,metodo='CREDITO_CAMBIO',proveedor='CAMBIO_PRENDAS',monto=applied,
            moneda='BOB',estado='APROBADO',referencia_externa=f'CAMBIO-{exchange.id}-CREDITO',paid_at=now))
    if difference>0:
        db.add(Payment(pedido_id=order.id,metodo='EFECTIVO',proveedor='CAMBIO_PRENDAS',monto=difference,
            moneda='BOB',estado='APROBADO',referencia_externa=f'CAMBIO-{exchange.id}-EFECTIVO',paid_at=now))
    if difference<0:
        db.add(Payment(pedido_id=source.id,metodo='EFECTIVO',proveedor='CAMBIO_DEVOLUCION',monto=-difference,
            moneda='BOB',estado='REEMBOLSADO',referencia_externa=f'CAMBIO-{exchange.id}-DEVOLUCION',paid_at=now))
    db.commit()
    return exchange_payload(db,exchange)
