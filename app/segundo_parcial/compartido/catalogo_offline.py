"""Paquete CU-12/13/14: copia autorizada y confirmación idempotente de reservas."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Branch,
    BranchStaff,
    BranchStock,
    Category,
    City,
    Product,
    ProductVariant,
    Reservation,
    ReservationItem,
    Role,
    User,
)
from app.services.saas import require_active_subscription, subscription_state, aware
from app.services.store import (
    _sync_variant_inventory,
    _movement,
    staff_can_access_branch,
    expire_due_reservations,
)
from app.segundo_parcial.compartido.offline_modelos import OfflineReservationReceipt
from app.segundo_parcial.compartido.offline_contratos import OfflineReservation
from app.segundo_parcial.compartido.operaciones import digest

offline_user = require_roles(
    Role.ADMIN, Role.CLIENTE, Role.ENCARGADO, Role.CAJERO, Role.VENDEDOR
)
