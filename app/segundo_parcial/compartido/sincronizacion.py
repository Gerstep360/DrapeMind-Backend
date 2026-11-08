"""Incremento II: registro durable, conciliación, conflictos y atención de reservas."""

from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.db.session import get_db
from app.models import (
    User,
    UserStatus,
    Role,
    Branch,
    BranchStaff,
    Reservation,
    ReservationItem,
    ProductVariant,
    Product,
)
from app.services.saas import require_active_subscription, aware
from app.services.store import expire_due_reservations
from app.segundo_parcial.compartido.offline_modelos import SyncOperation, SyncAudit
from app.segundo_parcial.compartido.offline_contratos import (
    Input,
    SyncEnvelope,
    OfflineReservation,
    CashSale,
    ReservationPickup,
    ConflictResolution,
    ReservationPreparation,
    OperationLookup,
)
from app.segundo_parcial.compartido.operaciones import digest
from app.segundo_parcial.cu15_ventas_contado.cu15_ventas_service import (
    branch_access,
    apply_cash_sale,
    fail,
)
from app.segundo_parcial.cu14_reservas_offline.cu14_api import apply_reservation

authorized = require_roles(
    Role.ADMIN, Role.ENCARGADO, Role.CAJERO, Role.CLIENTE, Role.VENDEDOR
)
staff = require_roles(Role.ADMIN, Role.ENCARGADO, Role.CAJERO)
manager = require_roles(Role.ADMIN, Role.ENCARGADO)
CASH_ROLES = (Role.ADMIN, Role.ENCARGADO, Role.CAJERO)


def operation_payload(op):
    return {
        "id": op.id,
        "operacion_id": op.operacion_id,
        "tipo": op.tipo,
        "usuario_id": op.usuario_id,
        "sucursal_id": op.sucursal_id,
        "estado": op.estado,
        "payload": op.payload,
        "resultado": op.resultado,
        "error": op.error,
        "intentos": op.intentos,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
    }


def role_for_kind(user, kind):
    required = (
        "offline.use"
        if kind == "RESERVATION"
        else "reservations.manage"
        if kind == "PICKUP"
        else "sales.manage"
    )
    if required not in user.permisos:
        fail(
            "PERMISSION_REQUIRED",
            "Tu administrador no habilitó esta operación para tu cuenta",
            403,
        )
    if kind != "RESERVATION" and user.rol not in CASH_ROLES:
        fail(
            "ROLE_FORBIDDEN",
            "Solo el personal de caja autorizado puede registrar una venta",
            403,
        )


def branch_ids(db, user):
    return select(BranchStaff.sucursal_id).where(
        BranchStaff.usuario_id == user.id, BranchStaff.activo.is_(True)
    )


def attempt(db, op, owner, actor, *, accept_saved_price=False, reason=None):
    op.intentos += 1
    op.updated_at = datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            if owner.estado != UserStatus.ACTIVO:
                fail(
                    "USER_INACTIVE",
                    "El usuario que creó la operación ya no está autorizado",
                    403,
                )
            role_for_kind(owner, op.tipo)
            require_active_subscription(db, owner.tenant_id, "offline")
            require_active_subscription(
                db,
                owner.tenant_id,
                "reservations" if op.tipo == "RESERVATION" else "products_sales",
            )
            branch_access(db, owner, op.sucursal_id)
            if op.tipo == "RESERVATION":
                result = apply_reservation(
                    OfflineReservation.model_validate(op.payload),
                    Response(),
                    owner,
                    db,
                    commit_changes=False,
                )
            else:
                model = ReservationPickup if op.tipo == "PICKUP" else CashSale
                result = {
                    "sale": apply_cash_sale(
                        db,
                        owner,
                        model.model_validate(op.payload),
                        pickup=op.tipo == "PICKUP",
                        accept_saved_price=accept_saved_price,
                    )
                }
            op.resultado = jsonable_encoder(result)
            op.error = None
            op.estado = "CONFIRMED"
    except HTTPException as error:
        detail = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "OPERATION_CONFLICT", "message": error.detail}
        )
        op.estado = "CONFLICT"
        op.error = jsonable_encoder(detail)
        op.resultado = None
    db.add(
        SyncAudit(
            operacion_id=op.id,
            actor_id=actor.id,
            accion="MANAGER_RETRY" if reason else "SYNC",
            detalle={
                "estado": op.estado,
                "error": op.error,
                "motivo": reason,
                "aceptar_precio_guardado": accept_saved_price,
            },
        )
    )
    db.flush()
    return op


def reservation_snapshot(db, reservation):
    return {
        "id": reservation.id,
        "codigo_publico": str(reservation.codigo_publico),
        "sucursal_id": reservation.sucursal_id,
        "estado": reservation.estado,
        "vence_at": aware(reservation.vence_at).isoformat(),
        "usuario_id": reservation.usuario_id,
        "items": [
            {
                "variante_id": i.variante_id,
                "cantidad": i.cantidad,
                "precio_unitario": str(i.precio_referencia),
            }
            for i in db.scalars(
                select(ReservationItem).where(
                    ReservationItem.reserva_id == reservation.id
                )
            )
        ],
    }


def attending_snapshots(db, user):
    stmt = select(Reservation).where(
        Reservation.estado.in_(
            ["PENDIENTE", "CONFIRMADA", "EN_PREPARACION", "LISTA", "RETIRADA"]
        )
    )
    if user.rol != Role.ADMIN:
        stmt = stmt.where(Reservation.sucursal_id.in_(branch_ids(db, user)))
    return [
        reservation_snapshot(db, r)
        for r in db.scalars(stmt.order_by(Reservation.id.desc()).limit(200))
    ]
