from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Category, Favorite, Product, User
from app.schemas.api import CategoryOut, ProductDetail, ProductOut
from app.services.store import get_product_detail, search_products

router = APIRouter()


@router.get("/categories", response_model=list[CategoryOut], summary="Listar categorias")
def categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.scalars(select(Category).where(Category.activo.is_(True)).order_by(Category.nombre)))


@router.get(
    "/products", response_model=list[ProductOut], summary="Buscar y filtrar productos",
    description="CU-04/CU-05. Filtros combinables; por defecto solo devuelve productos con stock.",
)
def products(
    q: str | None = Query(default=None, max_length=150),
    categoria_id: int | None = None,
    precio_min: Decimal | None = Query(default=None, ge=0),
    precio_max: Decimal | None = Query(default=None, ge=0),
    genero: str | None = None,
    color: str | None = None,
    talla: str | None = None,
    con_stock: bool = True,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict]:
    return search_products(db, q, categoria_id, precio_min, precio_max, genero, color, talla, con_stock, offset, limit)


@router.get(
    "/products/{product_id}", response_model=ProductDetail, summary="Detalle y stock del producto",
    description="CU-06. Incluye variantes reales, talla, color y stock disponible calculado.",
)
def product_detail(product_id: int, db: Session = Depends(get_db)) -> dict:
    return get_product_detail(db, product_id)


@router.get("/favorites", response_model=list[ProductOut], summary="Listar favoritos")
def list_favorites(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Product]:
    return list(db.scalars(
        select(Product).join(Favorite, Favorite.producto_id == Product.id)
        .where(Favorite.usuario_id == current_user.id, Product.activo.is_(True))
        .order_by(Favorite.created_at.desc())
    ))


@router.post("/favorites/{product_id}", status_code=201, summary="Agregar favorito")
def add_favorite(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not db.get(Product, product_id):
        raise HTTPException(404, "Producto no encontrado")
    db.add(Favorite(usuario_id=current_user.id, producto_id=product_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"message": "Producto agregado a favoritos"}


@router.delete("/favorites/{product_id}", status_code=204, summary="Eliminar favorito")
def remove_favorite(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    favorite = db.scalar(select(Favorite).where(Favorite.usuario_id == current_user.id, Favorite.producto_id == product_id))
    if favorite:
        db.delete(favorite)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
