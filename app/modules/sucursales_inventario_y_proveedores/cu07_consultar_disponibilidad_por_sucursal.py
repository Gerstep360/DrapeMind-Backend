"""CU-07: Consultar disponibilidad por sucursal.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Branch, BranchStock, City, Product, ProductVariant
from app.schemas.api import BranchStockOut

router = APIRouter()


def _stock_payload(row: BranchStock, variant: ProductVariant, product: Product) -> dict:
    return {
        "sucursal_id": row.sucursal_id,
        "variante_id": row.variante_id,
        "producto_id": product.id,
        "producto": product.nombre,
        "sku": variant.sku,
        "color": variant.color,
        "talla": variant.talla,
        "stock_total": row.stock_total,
        "stock_reservado": row.stock_reservado,
        "stock_disponible": row.stock_total - row.stock_reservado,
        "activo": row.activo and variant.activo and product.activo,
    }


@router.get(
    "/products/{product_id}/availability",
    response_model=list[BranchStockOut],
    summary="CU-07: Disponibilidad de un producto por sucursal",
    description="CU-07. Devuelve stock físico disponible separado por sede, talla y color.",
)
def disponibilidad_producto_por_sucursal(
    product_id: int, db: Session = Depends(get_db)
) -> list[dict]:
    if not db.scalar(select(Product.id).where(Product.id == product_id, Product.activo.is_(True))):
        raise HTTPException(404, "Producto no encontrado")
    stmt = (
        select(BranchStock, ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == BranchStock.variante_id)
        .join(Product, Product.id == ProductVariant.producto_id)
        .join(Branch, Branch.id == BranchStock.sucursal_id)
        .where(
            Product.id == product_id,
            Branch.activo.is_(True),
            BranchStock.activo.is_(True),
            BranchStock.stock_total > BranchStock.stock_reservado,
        )
        .order_by(BranchStock.sucursal_id, ProductVariant.color, ProductVariant.talla)
    )
    return [_stock_payload(row, variant, product) for row, variant, product in db.execute(stmt)]


@router.get(
    "/{branch_id}/availability",
    response_model=list[BranchStockOut],
    summary="CU-07: Consultar inventario disponible de una sucursal",
    description="CU-07. Permite filtrar por producto, variante, talla y color.",
)
def disponibilidad_inventario_sucursal(
    branch_id: int,
    producto_id: int | None = None,
    variante_id: int | None = None,
    talla: str | None = Query(default=None, max_length=20),
    color: str | None = Query(default=None, max_length=60),
    con_stock: bool = True,
    db: Session = Depends(get_db),
) -> list[dict]:
    if not db.scalar(select(Branch.id).where(Branch.id == branch_id, Branch.activo.is_(True))):
        raise HTTPException(404, "Sucursal no encontrada")
    stmt = (
        select(BranchStock, ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == BranchStock.variante_id)
        .join(Product, Product.id == ProductVariant.producto_id)
        .where(BranchStock.sucursal_id == branch_id, BranchStock.activo.is_(True))
        .order_by(Product.nombre, ProductVariant.color, ProductVariant.talla)
    )
    if producto_id is not None:
        stmt = stmt.where(Product.id == producto_id)
    if variante_id is not None:
        stmt = stmt.where(ProductVariant.id == variante_id)
    if talla:
        stmt = stmt.where(func.lower(ProductVariant.talla) == talla.lower())
    if color:
        stmt = stmt.where(ProductVariant.color.ilike(f"%{color}%"))
    if con_stock:
        stmt = stmt.where(BranchStock.stock_total > BranchStock.stock_reservado)
    return [_stock_payload(row, variant, product) for row, variant, product in db.execute(stmt)]

