from fastapi import APIRouter
from app.segundo_parcial.compartido.catalogo_offline import (
    Branch,
    BranchStock,
    Depends,
    HTTPException,
    OfflineReservation,
    OfflineReservationReceipt,
    Product,
    ProductVariant,
    Reservation,
    ReservationItem,
    Response,
    Role,
    Session,
    User,
    _movement,
    _sync_variant_inventory,
    datetime,
    digest,
    expire_due_reservations,
    get_db,
    offline_user,
    require_active_subscription,
    select,
    settings,
    staff_can_access_branch,
    timedelta,
    timezone,
    uuid4,
)

router = APIRouter(prefix="/offline", tags=["CU-14 · reservas_offline"])


@router.post("/reservations")
def synchronize(
    payload: OfflineReservation,
    response: Response,
    user: User = Depends(offline_user),
    db: Session = Depends(get_db),
):
    return apply_reservation(payload, response, user, db)


def apply_reservation(payload, response, user, db, *, commit_changes=True):
    require_active_subscription(db, user.tenant_id, "offline")
    require_active_subscription(db, user.tenant_id, "reservations")
    if commit_changes:
        expire_due_reservations(db)
    # Serialize retries by authenticated owner; receipt and stock commit together.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    fingerprint = digest(payload.model_dump(mode="json"))
    previous = db.scalar(
        select(OfflineReservationReceipt).where(
            OfflineReservationReceipt.usuario_id == user.id,
            OfflineReservationReceipt.operacion_id == str(payload.operacion_id),
        )
    )
    if previous:
        if previous.payload_hash != fingerprint:
            raise HTTPException(
                409,
                {
                    "code": "OPERATION_REUSED",
                    "message": "Esta operación ya se confirmó con otras prendas. Crea una nueva solicitud.",
                },
            )
        return receipt_payload(
            db.get(Reservation, previous.reserva_id), str(payload.operacion_id), True
        )
    branch = db.scalar(
        select(Branch).where(Branch.id == payload.sucursal_id, Branch.activo.is_(True))
    )
    if not branch:
        raise HTTPException(404, "La sucursal ya no está disponible")
    if user.rol != Role.CLIENTE and not staff_can_access_branch(db, user, branch.id):
        raise HTTPException(
            403, "No tienes autorización para reservar en esta sucursal"
        )
    now = datetime.now(timezone.utc)
    if payload.creado_at > now + timedelta(minutes=5):
        raise HTTPException(
            422,
            "La fecha de la solicitud está en el futuro. Revisa la hora del dispositivo.",
        )
    checked = []
    for item in sorted(payload.items, key=lambda i: i.variante_id):
        variant = db.scalar(
            select(ProductVariant)
            .where(ProductVariant.id == item.variante_id)
            .with_for_update()
        )
        product = db.get(Product, variant.producto_id) if variant else None
        if not variant or not variant.activo or not product or not product.activo:
            raise HTTPException(
                409,
                {
                    "code": "PRODUCT_UNAVAILABLE",
                    "message": "Una de las prendas ya no está disponible. Actualiza tu selección.",
                },
            )
        stock = db.scalar(
            select(BranchStock)
            .where(
                BranchStock.variante_id == variant.id,
                BranchStock.sucursal_id == branch.id,
                BranchStock.activo.is_(True),
            )
            .with_for_update()
        )
        available = max(0, stock.stock_total - stock.stock_reservado) if stock else 0
        if available < item.cantidad:
            raise HTTPException(
                409,
                {
                    "code": "STOCK_CHANGED",
                    "message": f"La talla {variant.talla} en color {variant.color} tiene {available} unidades disponibles.",
                    "variante_id": variant.id,
                    "disponible": available,
                },
            )
        checked.append((item, variant, product, stock))
    reservation = Reservation(
        usuario_id=user.id,
        sucursal_id=branch.id,
        codigo_publico=uuid4(),
        qr_token=uuid4(),
        vence_at=now + timedelta(minutes=settings.RESERVATION_TTL_MINUTES),
        observacion=payload.observacion,
    )
    try:
        db.add(reservation)
        db.flush()
        for item, variant, product, stock in checked:
            before = variant.stock_reservado
            stock.stock_reservado += item.cantidad
            db.flush()
            _sync_variant_inventory(db, variant)
            movement = _movement(
                variant, "RESERVA", item.cantidad, user.id, "RESERVA", reservation.id
            )
            movement.sucursal_id, movement.stock_reservado_anterior = branch.id, before
            movement.observacion = "Reserva creada al sincronizar una solicitud offline"
            db.add_all(
                [
                    movement,
                    ReservationItem(
                        reserva_id=reservation.id,
                        variante_id=variant.id,
                        cantidad=item.cantidad,
                        precio_referencia=product.precio,
                    ),
                ]
            )
        db.add(
            OfflineReservationReceipt(
                usuario_id=user.id,
                operacion_id=str(payload.operacion_id),
                payload_hash=fingerprint,
                reserva_id=reservation.id,
            )
        )
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
    return {
        "operacion_id": operation_id,
        "status": "CONFIRMED",
        "replayed": replayed,
        "reservation": {
            "id": reservation.id,
            "codigo_publico": str(reservation.codigo_publico),
            "sucursal_id": reservation.sucursal_id,
            "estado": reservation.estado,
            "vence_at": reservation.vence_at,
        },
    }
