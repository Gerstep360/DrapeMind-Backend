"""CU-11: directorio, ofertas propias y abastecimiento con recepción por sede."""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Supplier, SupplierProduct, User, UserStatus, Role, Branch, ProductVariant, Product, BranchStock, InventoryMovement
from app.schemas.api import SupplierOut, SupplierProductOut
from app.services.saas import require_active_subscription
from app.services.store import _sync_variant_inventory
from app.incrementos.incremento_ii.models import SupplyOrder, SupplyOrderItem
from app.incrementos.incremento_ii.schemas import SupplierWrite, OfferWrite, SupplierAccount, SupplyCreate
from app.incrementos.incremento_ii.common import digest

router = APIRouter(prefix='/supply', tags=['Incremento II · CU-11 Proveedores y abastecimiento'])
operator = require_roles(Role.ADMIN, Role.PROVEEDOR)
administrator = require_roles(Role.ADMIN)


@router.get('/destinations')
def destinations(user: User = Depends(administrator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    return {'branches': [{'id': b.id, 'nombre': b.nombre} for b in db.scalars(select(Branch).where(Branch.activo.is_(True)))],
            'variants': [{'id': v.id, 'nombre': f'{p.nombre} · {v.talla} · {v.color}'} for v, p in db.execute(
                select(ProductVariant, Product).join(Product, Product.id == ProductVariant.producto_id).where(
                    ProductVariant.activo.is_(True), Product.activo.is_(True)))]}


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Los datos ya están registrados o una relación dejó de estar disponible.')


def supplier_for(db, user, supplier_id, *, lock=False):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    stmt = select(Supplier).where(Supplier.id == supplier_id)
    if lock:
        # Supplier.usuario is joined eagerly; exclude that outer join from locks.
        stmt = stmt.with_for_update(of=Supplier)
    supplier = db.scalar(stmt)
    if not supplier or (user.rol == Role.PROVEEDOR and (supplier.usuario_id != user.id or not supplier.activo)):
        raise HTTPException(404, 'Proveedor no encontrado en tu empresa')
    return supplier


@router.get('/suppliers', response_model=list[SupplierOut])
def suppliers(user: User = Depends(operator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    stmt = select(Supplier).order_by(Supplier.nombre_empresa)
    if user.rol == Role.PROVEEDOR:
        stmt = stmt.where(Supplier.usuario_id == user.id, Supplier.activo.is_(True))
    return list(db.scalars(stmt))


@router.post('/suppliers', response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierWrite, user: User = Depends(administrator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    if payload.nit and db.scalar(select(Supplier.id).where(Supplier.nit == payload.nit)):
        raise HTTPException(409, 'Ya existe un proveedor con ese NIT')
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    commit(db)
    db.refresh(supplier)
    return supplier


@router.put('/suppliers/{supplier_id}', response_model=SupplierOut)
def update_supplier(supplier_id: int, payload: SupplierWrite, user: User = Depends(administrator), db: Session = Depends(get_db)):
    supplier = supplier_for(db, user, supplier_id, lock=True)
    if payload.nit and db.scalar(select(Supplier.id).where(Supplier.nit == payload.nit, Supplier.id != supplier_id)):
        raise HTTPException(409, 'Ya existe otro proveedor con ese NIT')
    for name, value in payload.model_dump().items():
        setattr(supplier, name, value)
    commit(db)
    return supplier


@router.post('/suppliers/{supplier_id}/account', response_model=SupplierOut)
def account(supplier_id: int, payload: SupplierAccount, user: User = Depends(administrator), db: Session = Depends(get_db)):
    supplier = supplier_for(db, user, supplier_id, lock=True)
    if supplier.usuario_id:
        raise HTTPException(409, 'El proveedor ya tiene una cuenta vinculada; gestiona su acceso desde Usuarios.')
    email = payload.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, 'Ese correo ya tiene una cuenta en esta empresa. Usa otro correo para el proveedor.')
    account = User(nombre=payload.nombre, email=email, password_hash=hash_password(payload.password),
                   rol=Role.PROVEEDOR, estado=UserStatus.ACTIVO, is_platform_admin=False)
    db.add(account)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Ese correo ya tiene una cuenta en esta empresa')
    supplier.usuario_id = account.id
    commit(db)
    db.refresh(supplier)
    return supplier


@router.get('/suppliers/{supplier_id}/offers', response_model=list[SupplierProductOut])
def offers(supplier_id: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    supplier_for(db, user, supplier_id)
    return list(db.scalars(select(SupplierProduct).where(SupplierProduct.proveedor_id == supplier_id).order_by(SupplierProduct.id)))


@router.post('/suppliers/{supplier_id}/offers', response_model=SupplierProductOut, status_code=201)
def create_offer(supplier_id: int, payload: OfferWrite, user: User = Depends(operator), db: Session = Depends(get_db)):
    supplier = supplier_for(db, user, supplier_id, lock=True)
    if not supplier.activo:
        raise HTTPException(409, 'Activa el proveedor antes de registrar ofertas')
    if payload.sku_proveedor and db.scalar(select(SupplierProduct.id).where(SupplierProduct.proveedor_id == supplier_id, SupplierProduct.sku_proveedor == payload.sku_proveedor)):
        raise HTTPException(409, 'Este proveedor ya tiene una oferta con ese código')
    offer = SupplierProduct(proveedor_id=supplier_id, **payload.model_dump())
    db.add(offer)
    commit(db)
    return offer


@router.put('/suppliers/{supplier_id}/offers/{offer_id}', response_model=SupplierProductOut)
def update_offer(supplier_id: int, offer_id: int, payload: OfferWrite, user: User = Depends(operator), db: Session = Depends(get_db)):
    supplier_for(db, user, supplier_id)
    offer = db.scalar(select(SupplierProduct).where(SupplierProduct.id == offer_id, SupplierProduct.proveedor_id == supplier_id).with_for_update())
    if not offer:
        raise HTTPException(404, 'Oferta no encontrada')
    if payload.sku_proveedor and db.scalar(select(SupplierProduct.id).where(SupplierProduct.proveedor_id == supplier_id, SupplierProduct.id != offer_id, SupplierProduct.sku_proveedor == payload.sku_proveedor)):
        raise HTTPException(409, 'Este proveedor ya utiliza ese código')
    for name, value in payload.model_dump().items():
        setattr(offer, name, value)
    commit(db)
    return offer


def order_payload(db, order):
    supplier = db.get(Supplier, order.proveedor_id)
    branch = db.get(Branch, order.sucursal_id)
    return {'id': order.id, 'request_id': order.request_id, 'proveedor_id': order.proveedor_id,
            'proveedor': supplier.nombre_empresa, 'sucursal_id': order.sucursal_id, 'sucursal': branch.nombre,
            'estado': order.estado, 'total': str(order.total), 'observacion': order.observacion,
            'created_at': order.created_at, 'recibido_at': order.recibido_at,
            'items': [{'id': i.id, 'suministro_id': i.suministro_id, 'variante_id': i.variante_id,
                       'nombre': i.nombre, 'cantidad': i.cantidad, 'precio_unitario': str(i.precio_unitario)}
                      for i in db.scalars(select(SupplyOrderItem).where(SupplyOrderItem.pedido_id == order.id).order_by(SupplyOrderItem.id))]}


@router.get('/orders')
def orders(user: User = Depends(operator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    stmt = select(SupplyOrder).order_by(SupplyOrder.id.desc())
    if user.rol == Role.PROVEEDOR:
        stmt = stmt.where(SupplyOrder.proveedor_id.in_(select(Supplier.id).where(Supplier.usuario_id == user.id, Supplier.activo.is_(True))))
    return [order_payload(db, o) for o in db.scalars(stmt)]


@router.post('/orders', status_code=201)
def create_order(payload: SupplyCreate, user: User = Depends(administrator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    # One creator lock makes retry + order creation atomic across server workers.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    fingerprint = digest(payload.model_dump(mode='json'))
    previous = db.scalar(select(SupplyOrder).where(SupplyOrder.request_id == str(payload.request_id)))
    if previous:
        if previous.payload_hash != fingerprint or previous.creado_por_id != user.id:
            raise HTTPException(409, 'La solicitud ya existe con otros datos')
        return order_payload(db, previous)
    supplier = supplier_for(db, user, payload.proveedor_id)
    branch = db.scalar(select(Branch).where(Branch.id == payload.sucursal_id, Branch.activo.is_(True)))
    if not supplier.activo or not branch:
        raise HTTPException(404, 'El proveedor o la sucursal no están disponibles')
    rows, total = [], Decimal('0.00')
    for item in payload.items:
        offer = db.get(SupplierProduct, item.suministro_id)
        if not offer or offer.proveedor_id != supplier.id or not offer.activo or offer.estado == 'AGOTADO':
            raise HTTPException(404, 'Uno de los suministros no está disponible con este proveedor')
        if item.cantidad > offer.cantidad_disponible:
            raise HTTPException(409, 'La cantidad solicitada supera la oferta del proveedor')
        if item.variante_id:
            variant = db.get(ProductVariant, item.variante_id)
            product = db.get(Product, variant.producto_id) if variant else None
            if not variant or not variant.activo or not product or not product.activo:
                raise HTTPException(404, 'Variante de destino no disponible')
        total += offer.costo_unitario * item.cantidad
        rows.append((item, offer))
    order = SupplyOrder(request_id=str(payload.request_id), payload_hash=fingerprint, proveedor_id=supplier.id,
                        sucursal_id=branch.id, creado_por_id=user.id, total=total, observacion=payload.observacion)
    db.add(order)
    db.flush()
    for item, offer in rows:
        db.add(SupplyOrderItem(pedido_id=order.id, suministro_id=offer.id, variante_id=item.variante_id,
                              nombre=offer.nombre_suministro, cantidad=item.cantidad, precio_unitario=offer.costo_unitario))
    commit(db)
    return order_payload(db, order)


@router.post('/orders/{order_id}/{action}')
def transition(order_id: int, action: str, user: User = Depends(operator), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'products_sales')
    if action not in ('confirm', 'receive', 'cancel'):
        raise HTTPException(404, 'Acción no encontrada')
    order = db.scalar(select(SupplyOrder).where(SupplyOrder.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, 'Pedido de abastecimiento no encontrado')
    supplier_for(db, user, order.proveedor_id)
    if action == 'receive' and user.rol != Role.ADMIN:
        raise HTTPException(403, 'Solo la administración de la empresa puede registrar la recepción')
    target = {'confirm': 'CONFIRMADO', 'receive': 'RECIBIDO', 'cancel': 'CANCELADO'}[action]
    if order.estado == target:
        return order_payload(db, order)
    if order.estado in ('RECIBIDO', 'CANCELADO') or (action == 'receive' and order.estado != 'CONFIRMADO'):
        raise HTTPException(409, 'El estado actual del pedido no permite esta acción')
    items = list(db.scalars(select(SupplyOrderItem).where(SupplyOrderItem.pedido_id == order.id).order_by(SupplyOrderItem.suministro_id)))
    if action == 'confirm' or (action == 'cancel' and order.estado == 'CONFIRMADO'):
        for item in items:
            offer = db.scalar(select(SupplierProduct).where(SupplierProduct.id == item.suministro_id).with_for_update())
            if action == 'confirm':
                if not offer.activo or offer.estado == 'AGOTADO' or offer.cantidad_disponible < item.cantidad:
                    raise HTTPException(409, f'La oferta de {item.nombre} ya no tiene suficientes unidades')
                offer.cantidad_disponible -= item.cantidad
            else:
                offer.cantidad_disponible += item.cantidad
    if action == 'receive':
        branch = db.get(Branch, order.sucursal_id)
        if not branch or not branch.activo:
            raise HTTPException(409, 'Activa la sucursal antes de registrar la recepción')
        for item in sorted(items, key=lambda i: i.variante_id or 0):
            if not item.variante_id:
                continue
            variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
            if not variant or not variant.activo:
                raise HTTPException(409, f'La variante de {item.nombre} no está activa')
            stock = db.scalar(select(BranchStock).where(BranchStock.variante_id == variant.id, BranchStock.sucursal_id == order.sucursal_id).with_for_update())
            before_total, before_reserved = variant.stock_total, variant.stock_reservado
            if not stock:
                stock = BranchStock(variante_id=variant.id, sucursal_id=order.sucursal_id, stock_total=0, stock_reservado=0, activo=True)
                db.add(stock)
            stock.activo = True
            stock.stock_total += item.cantidad
            db.flush()
            _sync_variant_inventory(db, variant)
            db.add(InventoryMovement(variante_id=variant.id, sucursal_id=order.sucursal_id, tipo='ENTRADA', cantidad=item.cantidad,
                    stock_total_anterior=before_total, stock_total_nuevo=variant.stock_total,
                    stock_reservado_anterior=before_reserved, stock_reservado_nuevo=variant.stock_reservado,
                    usuario_id=user.id, referencia_tipo='ABASTECIMIENTO', referencia_id=order.id,
                    observacion=f'Recepción del pedido de abastecimiento {order.id}'))
        order.recibido_por_id, order.recibido_at = user.id, datetime.now(timezone.utc)
    order.estado = target
    commit(db)
    return order_payload(db, order)
