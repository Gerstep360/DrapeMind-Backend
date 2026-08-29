"""CU-04: Consultar catálogo de prendas.
Paquete: Catálogo y comercialización (PK-02).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import ProductOut
from app.services.store import search_products

router = APIRouter()


@router.get(
    "/products",
    response_model=list[ProductOut],
    summary="CU-04/CU-05: Buscar y filtrar productos",
    description="CU-04/CU-05. Filtros combinables; por defecto solo devuelve productos con stock.",
)
def consultar_catalogo(
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
    return search_products(
        db,
        q,
        categoria_id,
        precio_min,
        precio_max,
        genero,
        color,
        talla,
        con_stock,
        offset,
        limit,
    )
