from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
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


class SyncOperation(TenantOwned, Base):
    __tablename__ = 'offline_operaciones'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey('sucursales.id'))
    operacion_id: Mapped[str] = mapped_column(String(36))
    tipo: Mapped[str] = mapped_column(String(20))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    estado: Mapped[str] = mapped_column(String(20), default='PENDING')
    resultado: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('tenant_id', 'usuario_id', 'operacion_id', name='uq_offline_operation_owner'),
        CheckConstraint("tipo IN ('RESERVATION','SALE','PICKUP')", name='ck_sync_type'),
        CheckConstraint("estado IN ('PENDING','CONFIRMED','CONFLICT','REJECTED')", name='ck_sync_state'),
    )


class SyncAudit(TenantOwned, Base):
    __tablename__ = 'offline_operaciones_auditoria'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operacion_id: Mapped[int] = mapped_column(ForeignKey('offline_operaciones.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    accion: Mapped[str] = mapped_column(String(30))
    detalle: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GarmentExchange(TenantOwned, Base):
    __tablename__ = 'cambios_prendas'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operacion_id: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    pedido_origen_id: Mapped[int] = mapped_column(ForeignKey('pedidos.id'))
    pedido_nuevo_id: Mapped[int] = mapped_column(ForeignKey('pedidos.id'), unique=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey('sucursales.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    motivo: Mapped[str] = mapped_column(String(300))
    credito: Mapped[Decimal] = mapped_column(Numeric(12,2))
    total_nuevo: Mapped[Decimal] = mapped_column(Numeric(12,2))
    diferencia: Mapped[Decimal] = mapped_column(Numeric(12,2))
    efectivo_recibido: Mapped[Decimal] = mapped_column(Numeric(12,2))
    efectivo_devuelto: Mapped[Decimal] = mapped_column(Numeric(12,2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('tenant_id','operacion_id',name='uq_exchange_operation'),
                     CheckConstraint('credito >= 0 AND total_nuevo >= 0 AND efectivo_recibido >= 0 AND efectivo_devuelto >= 0',name='ck_exchange_amounts'))


class ExchangeReturn(TenantOwned, Base):
    __tablename__ = 'cambios_prendas_devoluciones'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cambio_id: Mapped[int] = mapped_column(ForeignKey('cambios_prendas.id'))
    item_pedido_id: Mapped[int] = mapped_column(ForeignKey('items_pedido.id'))
    cantidad: Mapped[int] = mapped_column(Integer)
    credito: Mapped[Decimal] = mapped_column(Numeric(12,2))
    __table_args__ = (CheckConstraint('cantidad > 0',name='ck_exchange_return_qty'),)
