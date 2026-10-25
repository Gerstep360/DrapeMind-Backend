from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_role, get_current_user_optional
from app.db.session import get_db
from app.models import Category, Product, ProductVariant, BranchStock, Role, User
from app.schemas.api import CategoryInput, CategoryOut, VariantInput, VariantOut
from app.services.store import variant_payload

router = APIRouter()


def _validate_category_parent(db, parent_id, category_id=None):
    seen={category_id} if category_id is not None else set()
    while parent_id is not None:
        if parent_id in seen:raise HTTPException(409,'La categoría no puede formar un ciclo con sus padres')
        seen.add(parent_id)
        parent=db.get(Category,parent_id)
        if parent is None:raise HTTPException(404,'Categoría padre no encontrada en esta empresa')
        parent_id=parent.parent_id


@router.get(
    "/categories",
    response_model=list[CategoryOut],
    summary="CU-30: Listar categorías del catálogo",
    description="Devuelve el árbol completo de categorías y subcategorías de ropa activas.",
)
def listar_categorias_publico(include_inactive: bool = False,user: User | None = Depends(get_current_user_optional),db: Session = Depends(get_db)) -> list[Category]:
    """CU-30: Lista de categorías activas."""
    if include_inactive and (not user or user.rol != Role.ADMIN):
        raise HTTPException(403,'Solo el administrador puede consultar categorías inactivas')
    query=select(Category)
    if not include_inactive:query=query.where(Category.activo.is_(True))
    return list(db.scalars(query.order_by(Category.nombre)))



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
    _validate_category_parent(db,payload.parent_id)
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
    _validate_category_parent(db,payload.parent_id,category.id)
    for field, value in payload.model_dump().items():
        setattr(category, field, value)
    try:db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Slug o categoría duplicada en esta empresa')
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
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    variant = ProductVariant(
        producto_id=product_id,
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
    return variant_payload(variant, product)


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
    if payload.stock_total < variant.stock_reservado:
        raise HTTPException(409,'El stock total no puede ser menor al reservado')
    if not payload.activo and variant.stock_reservado:
        raise HTTPException(409,'No se puede desactivar una variante con unidades reservadas')
    if payload.stock_total != variant.stock_total and db.scalar(select(BranchStock.id).where(BranchStock.variante_id==variant.id).limit(1)):
        raise HTTPException(409,'Modifica las existencias desde el inventario de cada sucursal')
    for field, value in payload.model_dump().items():
        setattr(variant, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "SKU duplicado") from exc
    db.refresh(variant)
    product = db.get(Product, variant.producto_id)
    return variant_payload(variant, product)


@router.delete(
    "/categories/{category_id}",
    summary="CU-30: Alternar estado o desactivar categoría",
)
def eliminar_o_desactivar_categoria(
    category_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(404, "Categoría no encontrada")
    cat.activo = not cat.activo
    db.commit()
    return {"message": f"Categoría {'activada' if cat.activo else 'desactivada'} correctamente", "activo": cat.activo}


@router.get(
    "/variants",
    response_model=list[VariantOut],
    summary="CU-30: Listar variantes administrativas",
    description="Permite consultar variantes con filtros por producto, SKU, color y estado.",
)
def listar_variantes_admin(
    producto_id: int | None = None,
    q: str | None = None,
    activo_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ProductVariant, Product).join(Product, Product.id == ProductVariant.producto_id)
    if producto_id is not None:
        stmt = stmt.where(ProductVariant.producto_id == producto_id)
    if activo_only:
        stmt = stmt.where(ProductVariant.activo.is_(True))
    if q and q.strip():
        term = f"%{q.strip()}%"
        from sqlalchemy import or_
        stmt = stmt.where(
            or_(
                ProductVariant.sku.ilike(term),
                ProductVariant.color.ilike(term),
                ProductVariant.talla.ilike(term),
                Product.nombre.ilike(term),
            )
        )
    stmt = stmt.order_by(Product.nombre.asc(), ProductVariant.sku.asc()).offset(offset).limit(limit)
    return [variant_payload(v, p) for v, p in db.execute(stmt)]


@router.delete(
    "/variants/{variant_id}",
    summary="CU-30: Alternar estado o desactivar variante",
)
def eliminar_o_desactivar_variante(
    variant_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    variant = db.get(ProductVariant, variant_id)
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    if variant.activo and variant.stock_reservado:
        raise HTTPException(409,'No se puede desactivar una variante con unidades reservadas')
    variant.activo = not variant.activo
    db.commit()
    return {"message": f"Variante {'activada' if variant.activo else 'desactivada'} correctamente", "activo": variant.activo}


