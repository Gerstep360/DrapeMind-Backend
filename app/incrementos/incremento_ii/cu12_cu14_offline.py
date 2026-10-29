"""Paquete CU-12/13/14: copia autorizada y confirmación idempotente de reservas."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import (Branch, BranchStaff, BranchStock, Category, City, Product, ProductVariant,
                        Reservation, ReservationItem, Role, User)
from app.services.saas import require_active_subscription, subscription_state, aware
from app.services.store import _sync_variant_inventory, _movement, staff_can_access_branch, expire_due_reservations
from app.incrementos.incremento_ii.models import OfflineReservationReceipt
from app.incrementos.incremento_ii.schemas import OfflineReservation
from app.incrementos.incremento_ii.common import digest

router = APIRouter(prefix='/offline', tags=['Incremento II · CU-12 a CU-14'])
offline_user = require_roles(Role.ADMIN, Role.CLIENTE, Role.ENCARGADO, Role.CAJERO, Role.VENDEDOR)


@router.get('/status')
def status(response: Response, user: User = Depends(offline_user), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'offline')
    response.headers['Cache-Control'] = 'no-store'
    return {'owner': f'{user.tenant_id}:{user.id}', 'available': True}


@router.get('/bundle')
def download(response: Response, user: User = Depends(offline_user), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'offline')
    expire_due_reservations(db)
    tenant, sub, _, _ = subscription_state(db, user.tenant_id)
    branches = list(db.scalars(select(Branch).where(Branch.activo.is_(True)).order_by(Branch.id)))
    if user.rol not in (Role.ADMIN, Role.CLIENTE):
        allowed = set(db.scalars(select(BranchStaff.sucursal_id).where(BranchStaff.usuario_id == user.id, BranchStaff.activo.is_(True))))
        branches = [b for b in branches if b.id in allowed]
    branch_ids = [b.id for b in branches]
    products = list(db.scalars(select(Product).where(Product.activo.is_(True)).order_by(Product.id)))
    product_ids = [p.id for p in products]
    variants = list(db.scalars(select(ProductVariant).where(ProductVariant.activo.is_(True), ProductVariant.producto_id.in_(product_ids)).order_by(ProductVariant.id)))
    variant_ids = [v.id for v in variants]
    categories = list(db.scalars(select(Category).where(Category.activo.is_(True))))
    cities = {c.id: c.nombre for c in db.scalars(select(City))}
    data = {
        'products': [{'id': p.id, 'nombre': p.nombre, 'descripcion': p.descripcion, 'categoria_id': p.categoria_id,
                      'marca': p.marca, 'material': p.material, 'genero_objetivo': p.genero_objetivo.value,
                      'precio': str(p.precio), 'imagenes': p.imagenes or []} for p in products],
        'variants': [{'id': v.id, 'producto_id': v.producto_id, 'sku': v.sku, 'talla': v.talla, 'color': v.color,
                      'imagen': v.imagen} for v in variants],
        'categories': [{'id': c.id, 'nombre': c.nombre} for c in categories],
        'branches': [{'id': b.id, 'nombre': b.nombre, 'direccion': b.direccion, 'ciudad': cities.get(b.ciudad_id, '')} for b in branches],
        'stock': [{'sucursal_id': s.sucursal_id, 'variante_id': s.variante_id,
                   'disponible': max(0, s.stock_total - s.stock_reservado)} for s in db.scalars(
            select(BranchStock).where(BranchStock.activo.is_(True), BranchStock.sucursal_id.in_(branch_ids), BranchStock.variante_id.in_(variant_ids)))],
    }
    if user.rol in (Role.ADMIN,Role.ENCARGADO,Role.CAJERO):
        from .cu15_cu19_operaciones import attending_snapshots
        data['reservations']=attending_snapshots(db,user)
    else:
        data['reservations']=[]
    now = datetime.now(timezone.utc)
    response.headers['Cache-Control'] = 'no-store'
    return {'schema_version': 1, 'owner': f'{user.tenant_id}:{user.id}', 'tenant_id': user.tenant_id,
            'user_id': user.id, 'tenant_name': tenant.name, 'version': digest(data), 'downloaded_at': now,
            'valid_until': min(now + timedelta(hours=24), aware(sub.ends_at)), **data}


@router.post('/reservations')
def synchronize(payload: OfflineReservation, response: Response, user: User = Depends(offline_user), db: Session = Depends(get_db)):
    return apply_reservation(payload, response, user, db)


def apply_reservation(payload, response, user, db, *, commit_changes=True):
    require_active_subscription(db, user.tenant_id, 'offline')
    require_active_subscription(db, user.tenant_id, 'reservations')
    if commit_changes:
        expire_due_reservations(db)
    # Serialize retries by authenticated owner; receipt and stock commit together.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    fingerprint = digest(payload.model_dump(mode='json'))
    previous = db.scalar(select(OfflineReservationReceipt).where(
        OfflineReservationReceipt.usuario_id == user.id, OfflineReservationReceipt.operacion_id == str(payload.operacion_id)))
    if previous:
        if previous.payload_hash != fingerprint:
            raise HTTPException(409, {'code': 'OPERATION_REUSED', 'message': 'Esta operación ya se confirmó con otras prendas. Crea una nueva solicitud.'})
        return receipt_payload(db.get(Reservation, previous.reserva_id), str(payload.operacion_id), True)
    branch = db.scalar(select(Branch).where(Branch.id == payload.sucursal_id, Branch.activo.is_(True)))
    if not branch:
        raise HTTPException(404, 'La sucursal ya no está disponible')
    if user.rol != Role.CLIENTE and not staff_can_access_branch(db, user, branch.id):
        raise HTTPException(403, 'No tienes autorización para reservar en esta sucursal')
    now = datetime.now(timezone.utc)
    if payload.creado_at > now + timedelta(minutes=5):
        raise HTTPException(422, 'La fecha de la solicitud está en el futuro. Revisa la hora del dispositivo.')
    checked = []
    for item in sorted(payload.items, key=lambda i: i.variante_id):
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
        product = db.get(Product, variant.producto_id) if variant else None
        if not variant or not variant.activo or not product or not product.activo:
            raise HTTPException(409, {'code': 'PRODUCT_UNAVAILABLE', 'message': 'Una de las prendas ya no está disponible. Actualiza tu selección.'})
        stock = db.scalar(select(BranchStock).where(BranchStock.variante_id == variant.id, BranchStock.sucursal_id == branch.id,
                                                   BranchStock.activo.is_(True)).with_for_update())
        available = max(0, stock.stock_total - stock.stock_reservado) if stock else 0
        if available < item.cantidad:
            raise HTTPException(409, {'code': 'STOCK_CHANGED', 'message': f'La talla {variant.talla} en color {variant.color} tiene {available} unidades disponibles.',
                                      'variante_id': variant.id, 'disponible': available})
        checked.append((item, variant, product, stock))
    reservation = Reservation(usuario_id=user.id, sucursal_id=branch.id, codigo_publico=uuid4(), qr_token=uuid4(),
                              vence_at=now + timedelta(minutes=settings.RESERVATION_TTL_MINUTES), observacion=payload.observacion)
    try:
        db.add(reservation)
        db.flush()
        for item, variant, product, stock in checked:
            before = variant.stock_reservado
            stock.stock_reservado += item.cantidad
            db.flush()
            _sync_variant_inventory(db, variant)
            movement = _movement(variant, 'RESERVA', item.cantidad, user.id, 'RESERVA', reservation.id)
            movement.sucursal_id, movement.stock_reservado_anterior = branch.id, before
            movement.observacion = 'Reserva creada al sincronizar una solicitud offline'
            db.add_all([movement, ReservationItem(reserva_id=reservation.id, variante_id=variant.id,
                                                  cantidad=item.cantidad, precio_referencia=product.precio)])
        db.add(OfflineReservationReceipt(usuario_id=user.id, operacion_id=str(payload.operacion_id),
                                        payload_hash=fingerprint, reserva_id=reservation.id))
        if commit_changes:
            db.commit()
        else:
            db.flush()
    except Exception:
        if commit_changes:
            db.rollback()
        raise
    response.status_code = 201
    return receipt_payload(reservation, str(payload.operacion_id), False)


def receipt_payload(reservation, operation_id, replayed):
    return {'operacion_id': operation_id, 'status': 'CONFIRMED', 'replayed': replayed,
            'reservation': {'id': reservation.id, 'codigo_publico': str(reservation.codigo_publico),
                            'sucursal_id': reservation.sucursal_id, 'estado': reservation.estado,
                            'vence_at': reservation.vence_at}}
