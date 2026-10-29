from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.saas import TenantOwned


class SupplyOrder(TenantOwned, Base):
    __tablename__ = 'abastecimiento_pedidos'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    proveedor_id: Mapped[int] = mapped_column(ForeignKey('proveedores.id'))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey('sucursales.id'))
    creado_por_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    recibido_por_id: Mapped[int | None] = mapped_column(ForeignKey('usuarios.id'))
    estado: Mapped[str] = mapped_column(String(20), default='SOLICITADO')
    observacion: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recibido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint('tenant_id', 'request_id', name='uq_supply_request'),
        CheckConstraint("estado IN ('SOLICITADO','CONFIRMADO','RECIBIDO','CANCELADO')", name='ck_supply_state'),
        CheckConstraint('total >= 0', name='ck_supply_total'),
    )


class SupplyOrderItem(TenantOwned, Base):
    __tablename__ = 'abastecimiento_items'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey('abastecimiento_pedidos.id', ondelete='CASCADE'))
    suministro_id: Mapped[int] = mapped_column(ForeignKey('proveedor_suministros.id'))
    variante_id: Mapped[int | None] = mapped_column(ForeignKey('variantes_producto.id'))
    nombre: Mapped[str] = mapped_column(String(150))
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    __table_args__ = (CheckConstraint('cantidad > 0', name='ck_supply_quantity'),)


class OfflineReservationReceipt(TenantOwned, Base):
    __tablename__ = 'offline_reservas_recibidas'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    operacion_id: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    reserva_id: Mapped[int] = mapped_column(ForeignKey('reservas.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('tenant_id', 'usuario_id', 'operacion_id', name='uq_offline_reservation_operation'),)
