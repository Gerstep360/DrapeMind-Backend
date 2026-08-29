from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Category, Product, ProductVariant, Role, User
from app.schemas.api import CategoryInput, CategoryOut, VariantInput, VariantOut
from app.services.store import variant_payload

router = APIRouter()


@router.get(
    "/categories",
    response_model=list[CategoryOut],
    summary="CU-30: Listar categorías del catálogo",
    description="Devuelve el árbol completo de categorías y subcategorías de ropa activas.",
)
def listar_categorias_publico(db: Session = Depends(get_db)) -> list[Category]:
    """CU-30: Lista de categorías activas."""
    return list(
        db.scalars(
            select(Category).where(Category.activo.is_(True)).order_by(Category.nombre)
        )
    )



@router.post(
    "/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-30: Crear categoría de ropa",
    description="Permite al administrador dar de alta nuevas familias y líneas de prendas.",
)
def crear_categoria(
    payload: CategoryInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Category:
    """CU-30: Registro de nueva categoría."""
    category = Category(**payload.model_dump())
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Slug o categoría duplicada") from exc
    db.refresh(category)
    return category


@router.put(
    "/categories/{category_id}",
    response_model=CategoryOut,
    summary="CU-30: Actualizar categoría",
)
def actualizar_categoria(
    category_id: int,
    payload: CategoryInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Category:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Categoría no encontrada")
    for field, value in payload.model_dump().items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-30: Registrar variante de talla y color",
    description="Añade una variante física (SKU, talla, color y stock inicial) a un producto base.",
)
def crear_variante(
    product_id: int,
    payload: VariantInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-30: Creación de variante con SKU único."""
    if not db.get(Product, product_id):
        raise HTTPException(404, "Producto no encontrado")
    variant = ProductVariant(
        producto_id=product_id,
        stock_disponible=payload.stock_total,
        stock_reservado=0,
        **payload.model_dump(),
    )
    db.add(variant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "SKU duplicado") from exc
    db.refresh(variant)
    return variant_payload(variant)


@router.put(
    "/variants/{variant_id}",
    response_model=VariantOut,
    summary="CU-30: Actualizar variante",
)
def actualizar_variante(
    variant_id: int,
    payload: VariantInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.get(ProductVariant, variant_id)
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    for field, value in payload.model_dump().items():
        setattr(variant, field, value)
    variant.stock_disponible = max(0, variant.stock_total - (variant.stock_reservado or 0))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "SKU duplicado") from exc
    db.refresh(variant)
    return variant_payload(variant)

