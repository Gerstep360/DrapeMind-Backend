"""CU-06: Consultar detalle, talla, color y variante.
Paquete: Catálogo y comercialización (PK-02).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import ProductDetail
from app.services.store import get_product_detail

router = APIRouter()


@router.get(
    "/products/{product_id}",
    response_model=ProductDetail,
    summary="CU-06: Detalle y stock del producto",
    description="CU-06. Incluye variantes reales, talla, color y stock disponible calculado.",
)
def consultar_detalle_prenda(product_id: int, db: Session = Depends(get_db)) -> dict:
    return get_product_detail(db, product_id)

