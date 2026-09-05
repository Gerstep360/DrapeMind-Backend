from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.entities import Gender, Role, UserStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class RegisterRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    telefono: str | None = Field(default=None, max_length=30)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: int
    nombre: str
    email: EmailStr
    telefono: str | None
    rol: Role
    estado: UserStatus
    created_at: datetime


class UserUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    telefono: str | None = Field(default=None, max_length=30)


class AddressInput(BaseModel):
    alias: str = Field(default="Casa", max_length=50)
    departamento: str = Field(min_length=2, max_length=80)
    ciudad: str = Field(min_length=2, max_length=80)
    zona: str | None = Field(default=None, max_length=100)
    direccion: str = Field(min_length=5, max_length=250)
    referencia: str | None = Field(default=None, max_length=250)
    latitud: Decimal | None = Field(default=None, ge=-90, le=90)
    longitud: Decimal | None = Field(default=None, ge=-180, le=180)
    telefono_contacto: str | None = Field(default=None, max_length=30)
    es_principal: bool = False


class AddressOut(AddressInput, ORMModel):
    id: int
    usuario_id: int
    created_at: datetime


class CityInput(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    departamento: str = Field(min_length=2, max_length=100)
    activo: bool = True


class CityOut(CityInput, ORMModel):
    id: int


class BranchInput(BaseModel):
    ciudad_id: int
    codigo: str = Field(pattern=r"^[A-Z0-9-]+$", min_length=2, max_length=30)
    nombre: str = Field(min_length=2, max_length=120)
    direccion: str = Field(min_length=5, max_length=250)
    telefono: str | None = Field(default=None, max_length=30)
    latitud: Decimal | None = Field(default=None, ge=-90, le=90)
    longitud: Decimal | None = Field(default=None, ge=-180, le=180)
    activo: bool = True


class BranchOut(BranchInput, ORMModel):
    id: int
    ciudad: str | None = None
    departamento: str | None = None


class BranchStockInput(BaseModel):
    variante_id: int
    stock_total: int = Field(ge=0)
    stock_minimo: int = Field(default=0, ge=0)
    activo: bool = True


class BranchStockOut(ORMModel):
    sucursal_id: int
    variante_id: int
    producto_id: int
    producto: str
    sku: str
    color: str
    talla: str
    stock_total: int
    stock_reservado: int
    stock_disponible: int
    activo: bool


class StaffAssignmentInput(BaseModel):
    usuario_id: int


class CategoryInput(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    descripcion: str | None = Field(default=None, max_length=250)
    parent_id: int | None = None
    activo: bool = True


class CategoryOut(CategoryInput, ORMModel):
    id: int


class VariantInput(BaseModel):
    sku: str = Field(min_length=2, max_length=80)
    color: str = Field(min_length=2, max_length=60)
    codigo_color: str | None = Field(default=None, max_length=15)
    talla: str = Field(min_length=1, max_length=20)
    stock_total: int = Field(default=0, ge=0)
    codigo_barras: str | None = Field(default=None, max_length=100)
    imagen: str | None = Field(default=None, max_length=500)
    activo: bool = True


class VariantOut(ORMModel):
    id: int
    producto_id: int
    sku: str
    color: str
    codigo_color: str | None
    talla: str
    stock_total: int
    stock_reservado: int
    stock_disponible: int
    imagen: str | None
    activo: bool


class ProductInput(BaseModel):
    categoria_id: int
    nombre: str = Field(min_length=2, max_length=150)
    descripcion: str | None = None
    marca: str | None = Field(default=None, max_length=100)
    material: str | None = Field(default=None, max_length=150)
    precio: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    costo_referencia: Decimal | None = Field(default=None, ge=0)
    calidad_nivel: int = Field(default=3, ge=1, le=5)
    genero_objetivo: Gender = Gender.UNISEX
    descripcion_ai: str | None = None
    tags_ai: list[str] | None = None
    imagenes: list[Any] = Field(default_factory=list)
    activo: bool = True


class ProductOut(ProductInput, ORMModel):
    id: int
    created_at: datetime
    stock_disponible: int | None = None


class ProductDetail(ProductOut):
    variantes: list[VariantOut] = Field(default_factory=list)


class CartItemInput(BaseModel):
    variante_id: int
    cantidad: int = Field(default=1, ge=1, le=20)


class CartBatchInput(BaseModel):
    items: list[CartItemInput] = Field(min_length=1, max_length=8)


class CartItemUpdate(BaseModel):
    cantidad: int = Field(ge=1, le=20)


class CartReplaceInput(BaseModel):
    item_id: int
    nueva_variante_id: int


class CartItemOut(BaseModel):
    id: int
    variante_id: int
    producto_id: int
    nombre: str
    sku: str
    color: str
    talla: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    stock_disponible: int
    imagen: str | None = None


class CartOut(BaseModel):
    id: int
    estado: str
    items: list[CartItemOut]
    total_items: int
    subtotal: Decimal


class ReservationItemInput(BaseModel):
    variante_id: int
    cantidad: int = Field(default=1, ge=1, le=20)


class ReservationCreate(BaseModel):
    sucursal_id: int | None = None
    items: list[ReservationItemInput] | None = Field(default=None, min_length=1, max_length=20)
    observacion: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def unique_variants(self) -> "ReservationCreate":
        if self.items:
            ids = [item.variante_id for item in self.items]
            if len(ids) != len(set(ids)):
                raise ValueError("No repita variantes; use cantidad")
        return self


class ReservationOut(ORMModel):
    id: int
    codigo_publico: UUID
    sucursal_id: int | None
    estado: str
    fecha_reserva: datetime
    vence_at: datetime
    observacion: str | None
    preparado_por_id: int | None = None
    preparado_at: datetime | None = None
    atendido_por_id: int | None = None
    atendido_at: datetime | None = None


class ReservationItemOut(ORMModel):
    variante_id: int
    cantidad: int
    precio_referencia: Decimal


class ReservationDetail(ReservationOut):
    items: list[ReservationItemOut] = Field(default_factory=list)


class QRValidationRequest(BaseModel):
    qr_token: UUID


class CheckoutRequest(BaseModel):
    tipo_entrega: Literal["DELIVERY", "RECOJO"]
    direccion_id: int | None = None
    costo_envio: Decimal = Field(default=0, ge=0)
    observacion: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def require_address_for_delivery(self) -> "CheckoutRequest":
        if self.tipo_entrega == "DELIVERY" and self.direccion_id is None:
            raise ValueError("direccion_id es obligatorio para DELIVERY")
        return self


class OrderOut(ORMModel):
    id: int
    codigo_publico: UUID
    usuario_id: int | None = None
    sucursal_id: int | None = None
    estado: str
    canal: str
    tipo_entrega: str
    subtotal: Decimal
    descuento: Decimal
    costo_envio: Decimal
    total: Decimal
    observacion: str | None = None
    created_at: datetime
    paid_at: datetime | None = None
    completed_at: datetime | None = None


class OrderStatusUpdate(BaseModel):
    estado: Literal["PAGADO", "PREPARANDO", "LISTO", "ENVIADO", "ENTREGADO", "CANCELADO"]


class PaymentCreate(BaseModel):
    pedido_id: int
    metodo: Literal["QR", "TARJETA", "EFECTIVO", "TRANSFERENCIA"]


class PaymentOut(ORMModel):
    id: int
    pedido_id: int
    metodo: str
    proveedor: str | None
    monto: Decimal
    moneda: str
    estado: str
    referencia_externa: str | None
    qr_payload: str | None
    created_at: datetime
    paid_at: datetime | None = None


class PaymentWebhook(BaseModel):
    referencia_externa: str
    estado: Literal["APROBADO", "RECHAZADO"]


class InventoryAdjustment(BaseModel):
    variante_id: int
    nuevo_stock_total: int = Field(ge=0)
    observacion: str = Field(min_length=3, max_length=300)


class AIRequest(BaseModel):
    mensaje: str = Field(min_length=2, max_length=2000)
    sesion_id: int | None = None


class NaturalSearchRequest(BaseModel):
    consulta: str = Field(min_length=2, max_length=500)
    sesion_id: int | None = None


class OutfitRequest(BaseModel):
    ocasion: str = Field(min_length=2, max_length=200)
    presupuesto_max: Decimal | None = Field(default=None, gt=0)
    preferencias: str | None = Field(default=None, max_length=500)
    producto_base_id: int | None = None
    sesion_id: int | None = None


class CartAnalysisRequest(BaseModel):
    objetivo: Literal["estilo", "ahorro", "calidad_precio"] = "estilo"
    sesion_id: int | None = None


class RecommendationApply(BaseModel):
    recomendacion_id: int


class AIResponse(BaseModel):
    sesion_id: int
    interaccion_id: int
    respuesta: str
    productos: list[dict[str, Any]] = Field(default_factory=list)
    recomendaciones: list[dict[str, Any]] = Field(default_factory=list)
    modelo: str


class AssistedProductRequest(BaseModel):
    nombre_provisional: str = Field(min_length=2, max_length=150)
    descripcion_imagen: str = Field(min_length=3, max_length=2000)


class ARConfig(BaseModel):
    producto_id: int
    supported: bool
    mode: Literal["2d-overlay", "external-provider"]
    asset_url: str | None
    instructions: str
    size_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    fabric_elasticity: float = 0.05
    fit_category: str = "regular"
    available_sizes: list[str] = Field(default_factory=list)
    recommended_size: str | None = None
    material: str | None = None
    available_variants: list[dict[str, Any]] = Field(default_factory=list)
    tracking: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
