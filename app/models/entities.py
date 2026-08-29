import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Role(str, enum.Enum):
    CLIENTE = "CLIENTE"
    ADMIN = "ADMIN"
    VENDEDOR = "VENDEDOR"
    ENCARGADO = "ENCARGADO"
    CAJERO = "CAJERO"


class UserStatus(str, enum.Enum):
    ACTIVO = "ACTIVO"
    BLOQUEADO = "BLOQUEADO"
    INACTIVO = "INACTIVO"


class Gender(str, enum.Enum):
    HOMBRE = "HOMBRE"
    MUJER = "MUJER"
    UNISEX = "UNISEX"
    OTRO = "OTRO"


role_enum = Enum(Role, name="rol_usuario")
user_status_enum = Enum(UserStatus, name="estado_usuario")
gender_enum = Enum(Gender, name="genero_objetivo")
cart_status_enum = Enum("ACTIVO", "CONVERTIDO", "ABANDONADO", name="estado_carrito")
reservation_status_enum = Enum(
    "PENDIENTE", "CONFIRMADA", "EN_PREPARACION", "LISTA", "RETIRADA",
    "VENCIDA", "CANCELADA", "CONVERTIDA", name="estado_reserva",
)
order_status_enum = Enum("PENDIENTE_PAGO", "PAGADO", "PREPARANDO", "LISTO", "ENVIADO", "ENTREGADO", "CANCELADO", name="estado_pedido")
order_channel_enum = Enum("MOBILE", "WEB", "TIENDA", name="canal_pedido")
delivery_type_enum = Enum("DELIVERY", "RECOJO", "TIENDA", name="tipo_entrega")
payment_method_enum = Enum("QR", "TARJETA", "EFECTIVO", "TRANSFERENCIA", name="metodo_pago")
payment_status_enum = Enum("PENDIENTE", "PROCESANDO", "APROBADO", "RECHAZADO", "REEMBOLSADO", name="estado_pago")
movement_type_enum = Enum("ENTRADA", "VENTA", "RESERVA", "LIBERACION_RESERVA", "DEVOLUCION", "AJUSTE", name="tipo_movimiento_inventario")
ai_session_status_enum = Enum("ACTIVA", "CERRADA", "EXPIRADA", name="estado_ai_sesion")
ai_interaction_type_enum = Enum("CHAT", "PRODUCT_SEARCH", "GENERATE_OUTFIT", "COMPLETE_OUTFIT", "STYLE_CHECK", "VALUE_CHECK", name="tipo_ai_interaccion")
ai_interaction_status_enum = Enum("OK", "ERROR", "CANCELADO", name="estado_ai_interaccion")
ai_recommendation_type_enum = Enum("OUTFIT", "REEMPLAZO_ESTILO", "REEMPLAZO_AHORRO", "REEMPLAZO_VALOR", "COMPLETAR_OUTFIT", name="tipo_ai_recomendacion")
outfit_role_enum = Enum("TOP", "BOTTOM", "SHOES", "OUTERWEAR", "ACCESSORY", "OTHER", name="rol_prenda_outfit")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(CITEXT, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    telefono: Mapped[str | None] = mapped_column(String(30))
    rol: Mapped[Role] = mapped_column(role_enum, default=Role.CLIENTE)
    estado: Mapped[UserStatus] = mapped_column(user_status_enum, default=UserStatus.ACTIVO)


class Address(TimestampMixin, Base):
    __tablename__ = "direcciones"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(50), default="Casa")
    departamento: Mapped[str] = mapped_column(String(80))
    ciudad: Mapped[str] = mapped_column(String(80))
    zona: Mapped[str | None] = mapped_column(String(100))
    direccion: Mapped[str] = mapped_column(String(250))
    referencia: Mapped[str | None] = mapped_column(String(250))
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    telefono_contacto: Mapped[str | None] = mapped_column(String(30))
    es_principal: Mapped[bool] = mapped_column(Boolean, default=False)


class City(TimestampMixin, Base):
    __tablename__ = "ciudades"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    departamento: Mapped[str] = mapped_column(String(100))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("nombre", "departamento", name="uq_ciudad_nombre_departamento"),)


class Branch(TimestampMixin, Base):
    __tablename__ = "sucursales"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id", ondelete="RESTRICT"))
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    direccion: Mapped[str] = mapped_column(String(250))
    telefono: Mapped[str | None] = mapped_column(String(30))
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class BranchStaff(Base):
    __tablename__ = "personal_sucursal"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("usuario_id", "sucursal_id", name="uq_personal_usuario_sucursal"),)


class Category(TimestampMixin, Base):
    __tablename__ = "categorias"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(250))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id", ondelete="SET NULL"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(TimestampMixin, Base):
    __tablename__ = "productos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id", ondelete="RESTRICT"))
    nombre: Mapped[str] = mapped_column(String(150))
    descripcion: Mapped[str | None] = mapped_column(Text)
    marca: Mapped[str | None] = mapped_column(String(100))
    material: Mapped[str | None] = mapped_column(String(150))
    precio: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    costo_referencia: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    calidad_nivel: Mapped[int] = mapped_column(SmallInteger, default=3)
    genero_objetivo: Mapped[Gender] = mapped_column(gender_enum, default=Gender.UNISEX)
    descripcion_ai: Mapped[str | None] = mapped_column(Text)
    tags_ai: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    imagenes: Mapped[list] = mapped_column(JSONB, default=list)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductVariant(TimestampMixin, Base):
    __tablename__ = "variantes_producto"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="RESTRICT"))
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    color: Mapped[str] = mapped_column(String(60))
    codigo_color: Mapped[str | None] = mapped_column(String(15))
    talla: Mapped[str] = mapped_column(String(20))
    stock_total: Mapped[int] = mapped_column(Integer, default=0)
    stock_reservado: Mapped[int] = mapped_column(Integer, default=0)
    codigo_barras: Mapped[str | None] = mapped_column(String(100), unique=True)
    imagen: Mapped[str | None] = mapped_column(String(500))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class BranchStock(TimestampMixin, Base):
    __tablename__ = "stock_sucursal"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id", ondelete="CASCADE"))
    variante_id: Mapped[int] = mapped_column(ForeignKey("variantes_producto.id", ondelete="RESTRICT"))
    stock_total: Mapped[int] = mapped_column(Integer, default=0)
    stock_reservado: Mapped[int] = mapped_column(Integer, default=0)
    stock_minimo: Mapped[int] = mapped_column(Integer, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("sucursal_id", "variante_id", name="uq_stock_sucursal_variante"),)


class Favorite(Base):
    __tablename__ = "favoritos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Cart(TimestampMixin, Base):
    __tablename__ = "carritos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    estado: Mapped[str] = mapped_column(cart_status_enum, default="ACTIVO")


class CartItem(TimestampMixin, Base):
    __tablename__ = "items_carrito"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    carrito_id: Mapped[int] = mapped_column(ForeignKey("carritos.id", ondelete="CASCADE"))
    variante_id: Mapped[int] = mapped_column(ForeignKey("variantes_producto.id", ondelete="RESTRICT"))
    cantidad: Mapped[int] = mapped_column(Integer, default=1)
    precio_referencia: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class Reservation(TimestampMixin, Base):
    __tablename__ = "reservas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_publico: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), server_default=func.gen_random_uuid())
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id", ondelete="RESTRICT"))
    estado: Mapped[str] = mapped_column(reservation_status_enum, default="PENDIENTE")
    fecha_reserva: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    qr_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), server_default=func.gen_random_uuid())
    observacion: Mapped[str | None] = mapped_column(String(300))
    preparado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    preparado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atendido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    atendido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReservationItem(Base):
    __tablename__ = "items_reserva"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id", ondelete="CASCADE"))
    variante_id: Mapped[int] = mapped_column(ForeignKey("variantes_producto.id", ondelete="RESTRICT"))
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_referencia: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(TimestampMixin, Base):
    __tablename__ = "pedidos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_publico: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), server_default=func.gen_random_uuid())
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="RESTRICT"))
    reserva_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id", ondelete="SET NULL"), unique=True)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id", ondelete="SET NULL"))
    estado: Mapped[str] = mapped_column(order_status_enum, default="PENDIENTE_PAGO")
    canal: Mapped[str] = mapped_column(order_channel_enum)
    tipo_entrega: Mapped[str] = mapped_column(delivery_type_enum)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    descuento: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    costo_envio: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    direccion_entrega_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    observacion: Mapped[str | None] = mapped_column(String(300))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base):
    __tablename__ = "items_pedido"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="RESTRICT"))
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id", ondelete="SET NULL"))
    variante_id: Mapped[int | None] = mapped_column(ForeignKey("variantes_producto.id", ondelete="SET NULL"))
    nombre_snapshot: Mapped[str] = mapped_column(String(150))
    sku_snapshot: Mapped[str] = mapped_column(String(80))
    color_snapshot: Mapped[str] = mapped_column(String(60))
    talla_snapshot: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "pagos"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="RESTRICT"))
    metodo: Mapped[str] = mapped_column(payment_method_enum)
    proveedor: Mapped[str | None] = mapped_column(String(80))
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    moneda: Mapped[str] = mapped_column(String(3), default="BOB")
    estado: Mapped[str] = mapped_column(payment_status_enum, default="PENDIENTE")
    referencia_externa: Mapped[str | None] = mapped_column(String(200), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    qr_payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryMovement(Base):
    __tablename__ = "movimientos_inventario"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    variante_id: Mapped[int] = mapped_column(ForeignKey("variantes_producto.id", ondelete="RESTRICT"))
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id", ondelete="SET NULL"))
    tipo: Mapped[str] = mapped_column(movement_type_enum)
    cantidad: Mapped[int] = mapped_column(Integer)
    stock_total_anterior: Mapped[int] = mapped_column(Integer)
    stock_total_nuevo: Mapped[int] = mapped_column(Integer)
    stock_reservado_anterior: Mapped[int] = mapped_column(Integer)
    stock_reservado_nuevo: Mapped[int] = mapped_column(Integer)
    referencia_tipo: Mapped[str | None] = mapped_column(String(30))
    referencia_id: Mapped[int | None] = mapped_column(BigInteger)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    observacion: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AISession(Base):
    __tablename__ = "ai_sesiones"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    estado: Mapped[str] = mapped_column(ai_session_status_enum, default="ACTIVA")
    resumen_contexto: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIInteraction(Base):
    __tablename__ = "ai_interacciones"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sesion_id: Mapped[int] = mapped_column(ForeignKey("ai_sesiones.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(ai_interaction_type_enum)
    intent: Mapped[str | None] = mapped_column(String(40))
    mensaje_usuario: Mapped[str | None] = mapped_column(Text)
    respuesta: Mapped[str | None] = mapped_column(Text)
    tool_principal: Mapped[str | None] = mapped_column(String(60))
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_entrada: Mapped[int | None] = mapped_column(Integer)
    tokens_salida: Mapped[int | None] = mapped_column(Integer)
    modelo: Mapped[str] = mapped_column(String(80))
    estado: Mapped[str] = mapped_column(ai_interaction_status_enum, default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIRecommendation(Base):
    __tablename__ = "ai_recomendaciones"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    interaccion_id: Mapped[int] = mapped_column(ForeignKey("ai_interacciones.id", ondelete="CASCADE"))
    grupo_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), server_default=func.gen_random_uuid())
    tipo: Mapped[str] = mapped_column(ai_recommendation_type_enum)
    rol: Mapped[str | None] = mapped_column(outfit_role_enum)
    producto_origen_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id", ondelete="SET NULL"))
    variante_origen_id: Mapped[int | None] = mapped_column(ForeignKey("variantes_producto.id", ondelete="SET NULL"))
    producto_recomendado_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="RESTRICT"))
    variante_recomendada_id: Mapped[int | None] = mapped_column(ForeignKey("variantes_producto.id", ondelete="SET NULL"))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    ahorro: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    motivo_corto: Mapped[str | None] = mapped_column(String(300))
    aceptada: Mapped[bool | None] = mapped_column(Boolean)
    aplicada: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
