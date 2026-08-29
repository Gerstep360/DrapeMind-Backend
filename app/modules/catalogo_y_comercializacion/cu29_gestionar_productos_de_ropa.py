"""CU-29: Gestionar productos de ropa.
Paquete: Catálogo y comercialización (PK-02).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Category, Product, Role, User
from app.schemas.api import ProductInput, ProductOut
from app.services.store import get_product_detail

router = APIRouter()


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
    summary="CU-29: Desactivar producto del catálogo",
    description="Desactiva (soft-delete) una prenda para ocultarla del catálogo público.",
)
def desactivar_producto(
    product_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-29: Desactiva producto del catálogo."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    product.activo = False
    db.commit()
    return {"message": "Producto desactivado correctamente"}
