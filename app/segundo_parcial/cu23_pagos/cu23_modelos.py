"""Durable card-on-file purchases; card numbers never enter application storage."""

from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.saas import TenantOwned

PURCHASE_TERMINAL = {"PAGADA", "RECHAZADA", "CANCELADA", "VENCIDA"}


class SavedCard(TenantOwned, Base):
    __tablename__ = "tarjetas_guardadas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    stripe_payment_method: Mapped[str] = mapped_column(String(100))
    setup_intent: Mapped[str] = mapped_column(String(100))
    marca: Mapped[str] = mapped_column(String(30))
    ultimos_cuatro: Mapped[str] = mapped_column(String(4))
    mes_vencimiento: Mapped[int] = mapped_column(Integer)
    anio_vencimiento: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    consentimiento_version: Mapped[str] = mapped_column(
        String(30), default="deferred-v1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "usuario_id",
            "stripe_payment_method",
            name="uq_saved_card_owner_method",
        ),
    )


class DeferredPurchase(TenantOwned, Base):
    __tablename__ = "compras_diferidas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    operacion_id: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    tarjeta_id: Mapped[int | None] = mapped_column(
        ForeignKey("tarjetas_guardadas.id", ondelete="RESTRICT")
    )
    pedido_id: Mapped[int | None] = mapped_column(
        ForeignKey("pedidos.id", ondelete="RESTRICT")
    )
    estado: Mapped[str] = mapped_column(
        String(40), default="PENDIENTE_SINCRONIZACION", index=True
    )
    total_autorizado: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    consentimiento_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mensaje: Mapped[str | None] = mapped_column(String(500))
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    siguiente_intento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "usuario_id",
            "operacion_id",
            name="uq_deferred_purchase_owner_operation",
        ),
    )
