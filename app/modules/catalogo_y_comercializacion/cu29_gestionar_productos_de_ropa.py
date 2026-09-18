import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Category, Gender, Product, ProductVariant, Role, User
from app.schemas.api import ProductDetail, ProductInput, ProductOut
from app.services.store import get_product_detail

router = APIRouter()
STATIC_PRODUCTS_DIR = Path(__file__).resolve().parents[2] / "static" / "products"
STATIC_PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)


@router.get(
    "/products",
    response_model=list[ProductOut],
    summary="CU-29: Listar productos administrativamente",
    description="Permite al administrador auditar todos los productos del catálogo con stock y filtros.",
)
def listar_productos_admin(
    q: str | None = None,
    categoria_id: int | None = None,
    genero: str | None = None,
    activo: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stock = func.coalesce(func.sum(ProductVariant.stock_total - ProductVariant.stock_reservado), 0)
    stmt = (
        select(Product, stock.label("stock_disponible"))
        .join(ProductVariant, ProductVariant.producto_id == Product.id, isouter=True)
        .group_by(Product.id)
        .order_by(Product.id.desc())
    )
    if activo is not None:
        stmt = stmt.where(Product.activo == activo)
    if categoria_id is not None:
        stmt = stmt.where(Product.categoria_id == categoria_id)
    if genero and genero.upper() != "TODOS":
        try:
            target_gender = Gender[genero.upper()]
            stmt = stmt.where(Product.genero_objetivo == target_gender)
        except KeyError:
            pass
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Product.nombre.ilike(term),
                Product.marca.ilike(term),
                Product.material.ilike(term),
            )
        )

    stmt = stmt.offset(offset).limit(limit)
    rows = db.execute(stmt).all()
    results = []
    for prod, stock_disp in rows:
        d = {c.name: getattr(prod, c.name) for c in prod.__table__.columns}
        d["stock_disponible"] = int(stock_disp or 0)
        results.append(d)
    return results


@router.get(
    "/products/{product_id}",
    response_model=ProductDetail,
    summary="CU-29: Consultar detalle administrativo de prenda",
)
def obtener_detalle_producto_admin(
    product_id: int,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> dict:
    detail = get_product_detail(db, product_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return detail


@router.post(
    "/products/upload-image",
    summary="CU-29: Subir imagen de prenda para catálogo",
    description="Sube una fotografía de prenda y devuelve la URL estática para asignarla al producto.",
)
async def subir_imagen_producto(
    file: UploadFile = File(...),
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
) -> dict:
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".svg"}
    suffix = Path(file.filename or "upload.jpg").suffix.lower()
    if suffix not in allowed_extensions:
        suffix = ".jpg"

    unique_filename = f"{uuid.uuid4().hex}{suffix}"
    dest_path = STATIC_PRODUCTS_DIR / unique_filename

    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)

    public_url = f"/static/products/{unique_filename}"
    return {
        "url": public_url,
        "filename": unique_filename,
        "content_type": file.content_type,
        "size_bytes": len(contents),
    }


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-29: Registrar nuevo producto de ropa",
    description="Crea una prenda base en el catálogo especificando categoría, material, precio base y calidad.",
)
def crear_producto(
    payload: ProductInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Product:
    """CU-29: Alta de producto por el administrador."""
    if not db.get(Category, payload.categoria_id):
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="CU-29: Actualizar información de producto",
    description="Actualiza precio, categoría, nivel de calidad, material y estado de la prenda.",
)
def actualizar_producto(
    product_id: int,
    payload: ProductInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Product:
    """CU-29: Modificación de producto existente."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if not db.get(Category, payload.categoria_id):
        raise HTTPException(status_code=404, detail="Categoría no encontrada")

    for field, value in payload.model_dump().items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.delete(
    "/products/{product_id}",
    summary="CU-29: Desactivar o alternar estado de producto del catálogo",
    description="Desactiva o reactiva una prenda para el catálogo público.",
)
def desactivar_producto(
    product_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-29: Desactiva o reactiva producto del catálogo."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    product.activo = not product.activo
    db.commit()
    return {"message": f"Producto {'activado' if product.activo else 'desactivado'} correctamente", "activo": product.activo}

