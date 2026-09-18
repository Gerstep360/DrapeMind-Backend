"""CU-33: Registrar productos y disponibilidad como proveedor.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, Supplier, SupplierProduct, User
from app.schemas.api import Message, SupplierProductInput, SupplierProductOut

router = APIRouter()


@router.get(
    "/suppliers/products/all",
    response_model=list[SupplierProductOut],
    summary="CU-33: Catálogo global de suministros de proveedores",
    description="Devuelve todos los insumos, telas y prendas disponibles de proveedores registrados.",
)
def listar_todos_suministros(
    q: str | None = Query(None, description="Buscar por nombre de material o SKU"),
    categoria: str | None = Query(None, description="Filtrar por categoría"),
    proveedor_id: int | None = Query(None, description="Filtrar por proveedor específico"),
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[SupplierProduct]:
    query = db.query(SupplierProduct)

    if proveedor_id:
        query = query.filter(SupplierProduct.proveedor_id == proveedor_id)

    if categoria:
        query = query.filter(SupplierProduct.categoria.ilike(f"%{categoria.strip()}%"))

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SupplierProduct.nombre_suministro.ilike(term),
                SupplierProduct.sku_proveedor.ilike(term),
            )
        )

    return query.order_by(SupplierProduct.created_at.desc()).all()


@router.get(
    "/suppliers/{supplier_id}/products",
    response_model=list[SupplierProductOut],
    summary="CU-33: Consultar catálogo de insumos de un proveedor",
    description="Obtiene las telas, avíos o lotes que provee una empresa textil específica.",
)
def listar_suministros_proveedor(
    supplier_id: int,
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[SupplierProduct]:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )
    return (
        db.query(SupplierProduct)
        .filter(SupplierProduct.proveedor_id == supplier_id)
        .order_by(SupplierProduct.created_at.desc())
        .all()
    )


@router.post(
    "/suppliers/{supplier_id}/products",
    response_model=SupplierProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-33: Registrar disponibilidad de lote de proveedor",
    description="Permite registrar un lote de prendas o tejidos disponibles desde la fábrica proveedora.",
)
def registrar_disponibilidad_proveedor(
    supplier_id: int,
    payload: SupplierProductInput,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> SupplierProduct:
    """CU-33: Ingreso de oferta mayorista de proveedor."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado para vincular el suministro.",
        )

    supply = SupplierProduct(
        proveedor_id=supplier_id,
        nombre_suministro=payload.nombre_suministro.strip(),
        sku_proveedor=payload.sku_proveedor.strip() if payload.sku_proveedor else None,
        categoria=payload.categoria.strip(),
        unidad_medida=payload.unidad_medida.strip(),
        costo_unitario=payload.costo_unitario,
        cantidad_disponible=payload.cantidad_disponible,
        tiempo_entrega_dias=payload.tiempo_entrega_dias,
        estado=payload.estado,
        activo=payload.activo,
    )
    db.add(supply)
    db.commit()
    db.refresh(supply)
    return supply


@router.put(
    "/suppliers/{supplier_id}/products/{product_id}",
    response_model=SupplierProductOut,
    summary="CU-33: Actualizar lote o suministro de proveedor",
)
def actualizar_suministro_proveedor(
    supplier_id: int,
    product_id: int,
    payload: SupplierProductInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> SupplierProduct:
    supply = (
        db.query(SupplierProduct)
        .filter(
            SupplierProduct.id == product_id,
            SupplierProduct.proveedor_id == supplier_id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suministro de proveedor no encontrado.",
        )

    supply.nombre_suministro = payload.nombre_suministro.strip()
    supply.sku_proveedor = payload.sku_proveedor.strip() if payload.sku_proveedor else None
    supply.categoria = payload.categoria.strip()
    supply.unidad_medida = payload.unidad_medida.strip()
    supply.costo_unitario = payload.costo_unitario
    supply.cantidad_disponible = payload.cantidad_disponible
    supply.tiempo_entrega_dias = payload.tiempo_entrega_dias
    supply.estado = payload.estado
    supply.activo = payload.activo

    db.commit()
    db.refresh(supply)
    return supply


@router.delete(
    "/suppliers/{supplier_id}/products/{product_id}",
    response_model=Message,
    summary="CU-33: Eliminar suministro de proveedor",
)
def eliminar_suministro_proveedor(
    supplier_id: int,
    product_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Message:
    supply = (
        db.query(SupplierProduct)
        .filter(
            SupplierProduct.id == product_id,
            SupplierProduct.proveedor_id == supplier_id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suministro de proveedor no encontrado.",
        )

    db.delete(supply)
    db.commit()
    return Message(message="Suministro eliminado del catálogo del proveedor.")
