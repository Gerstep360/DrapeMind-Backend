
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Category, InventoryMovement, Order, Product, ProductVariant, Reservation, Role, User,
)
from app.schemas.api import (
    AssistedProductRequest, CategoryInput, CategoryOut, InventoryAdjustment,
    OrderOut, ProductInput, ProductOut, ReservationOut, VariantInput, VariantOut,
)
from app.services.ai import call_gemma
from app.services.model_runtime import ModelRuntimeError, model_runtime
from app.services.store import variant_payload
from app.services.store import expire_due_reservations

router = APIRouter()
logger = logging.getLogger("drapemind.ai")


@router.get("/ai/runtime", summary="Estado del runtime Gemma")
async def ai_runtime_status(
    admin: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    return await model_runtime.status()


@router.post("/ai/runtime/start", summary="Encender Gemma")
async def start_ai_runtime(
    admin: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    try:
        await model_runtime.ensure_started()
    except ModelRuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("No se pudo iniciar el runtime administrado de Gemma")
        reason = (
            f"{type(exc).__name__}: {exc}"
            if settings.ENVIRONMENT == "development"
            else "Revise el log del servicio."
        )
        raise HTTPException(503, f"No se pudo iniciar Gemma. {reason}") from exc
    return await model_runtime.status()


@router.post("/ai/runtime/stop", summary="Apagar Gemma")
async def stop_ai_runtime(
    admin: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    await model_runtime.stop()
    return await model_runtime.status()


@router.post("/categories", response_model=CategoryOut, status_code=201, summary="Crear categoria")
def create_category(
    payload: CategoryInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Category:
    category = Category(**payload.model_dump())
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Slug o categoria duplicada") from exc
    db.refresh(category)
    return category


@router.put("/categories/{category_id}", response_model=CategoryOut, summary="Actualizar categoria")
def update_category(
    category_id: int, payload: CategoryInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Category:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Categoria no encontrada")
    for field, value in payload.model_dump().items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.post("/products", response_model=ProductOut, status_code=201, summary="Crear producto")
def create_product(
    payload: ProductInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Product:
    if not db.get(Category, payload.categoria_id):
        raise HTTPException(404, "Categoria no encontrada")
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=ProductOut, summary="Actualizar producto")
def update_product(
    product_id: int, payload: ProductInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    for field, value in payload.model_dump().items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201, summary="Crear variante")
def create_variant(
    product_id: int, payload: VariantInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    variant = ProductVariant(producto_id=product_id, stock_reservado=0, **payload.model_dump())
    db.add(variant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "SKU, codigo de barras o combinacion color/talla duplicada") from exc
    db.refresh(variant)
    return variant_payload(variant, product)


@router.put("/variants/{variant_id}", response_model=VariantOut, summary="Actualizar variante")
def update_variant(
    variant_id: int, payload: VariantInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.get(ProductVariant, variant_id)
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    if payload.stock_total < variant.stock_reservado:
        raise HTTPException(409, "El stock total no puede quedar por debajo del reservado")
    for field, value in payload.model_dump().items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    return variant_payload(variant, db.get(Product, variant.producto_id))


@router.post(
    "/inventory/adjustments", status_code=201, summary="Ajustar inventario",
    description="CU-30. Bloquea la variante y registra antes/despues en movimientos_inventario.",
)
def adjust_inventory(
    payload: InventoryAdjustment, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.scalar(select(ProductVariant).where(ProductVariant.id == payload.variante_id).with_for_update())
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    if payload.nuevo_stock_total < variant.stock_reservado:
        raise HTTPException(409, "El nuevo total es menor que el stock reservado")
    previous = variant.stock_total
    difference = payload.nuevo_stock_total - previous
    variant.stock_total = payload.nuevo_stock_total
    db.add(InventoryMovement(
        variante_id=variant.id, tipo="AJUSTE", cantidad=difference,
        stock_total_anterior=previous, stock_total_nuevo=variant.stock_total,
        stock_reservado_anterior=variant.stock_reservado,
        stock_reservado_nuevo=variant.stock_reservado, usuario_id=admin.id,
        observacion=payload.observacion,
    ))
    db.commit()
    return {"variante_id": variant.id, "stock_anterior": previous, "stock_nuevo": variant.stock_total}


@router.post(
    "/products/ai-draft", summary="Generar borrador de producto con IA",
    description="CU-31. Gemma propone metadatos, pero no escribe en productos: un ADMIN debe validar y usar POST /products.",
)
async def assisted_product(
    payload: AssistedProductRequest, admin: User = Depends(require_roles(Role.ADMIN))
) -> dict:
    answer, usage = await call_gemma(
        "Eres catalogador de ropa. Devuelve JSON con descripcion, material_probable, tags y genero_objetivo. No incluyas precio ni stock.",
        f"Nombre: {payload.nombre_provisional}\nObservacion visual: {payload.descripcion_imagen}",
    )
    return {"borrador": answer, "modelo": settings.AI_MODEL, "requiere_validacion_humana": True, "usage": usage}


@router.get("/reservations", response_model=list[ReservationOut], summary="Gestionar reservas")
def all_reservations(
    state: str | None = None, staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[Reservation]:
    stmt = select(Reservation)
    if state:
        stmt = stmt.where(Reservation.estado == state)
    return list(db.scalars(stmt.order_by(Reservation.created_at.desc()).limit(200)))


@router.post("/reservations/expire-due", summary="Liberar reservas vencidas")
def expire_reservations(
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
) -> dict:
    return {"expired": expire_due_reservations(db, limit=500)}


@router.get("/orders", response_model=list[OrderOut], summary="Gestionar pedidos")
def all_orders(
    state: str | None = None, staff: User = Depends(require_roles(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[Order]:
    stmt = select(Order)
    if state:
        stmt = stmt.where(Order.estado == state)
    return list(db.scalars(stmt.order_by(Order.created_at.desc()).limit(200)))


@router.get("/sales/history", summary="Historial de ventas")
def sales_history(
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(text("SELECT * FROM vw_historial_ventas ORDER BY completed_at DESC NULLS LAST LIMIT :limit"), {"limit": limit})
    return [dict(row._mapping) for row in rows]


@router.get("/metrics/sales-inventory", summary="Metricas de ventas e inventario")
def sales_inventory_metrics(
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
) -> dict:
    sales = db.execute(text(
        "SELECT COUNT(*) AS pedidos_entregados, COALESCE(SUM(total),0) AS ingresos "
        "FROM pedidos WHERE estado='ENTREGADO'"
    )).mappings().one()
    inventory = db.execute(text(
        "SELECT COUNT(*) AS variantes, COALESCE(SUM(stock_total-stock_reservado),0) AS unidades_disponibles, "
        "COUNT(*) FILTER (WHERE stock_total-stock_reservado <= 3) AS stock_bajo FROM variantes_producto WHERE activo"
    )).mappings().one()
    return {"ventas": dict(sales), "inventario": dict(inventory)}


@router.get("/metrics/ai", summary="Metricas de uso de IA")
def ai_metrics(
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)
) -> list[dict]:
    return [dict(row._mapping) for row in db.execute(text("SELECT * FROM vw_resumen_ai ORDER BY tipo"))]
