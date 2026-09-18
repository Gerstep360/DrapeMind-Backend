"""CU-32: Gestionar proveedores.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, Supplier, User
from app.schemas.api import Message, SupplierInput, SupplierOut

router = APIRouter()


@router.get(
    "/suppliers",
    response_model=list[SupplierOut],
    summary="CU-32: Listar proveedores del atelier",
    description="Devuelve el directorio de empresas proveedoras textiles y confección con filtros de búsqueda.",
)
def listar_proveedores(
    q: str | None = Query(None, description="Término de búsqueda por nombre, nit o contacto"),
    ciudad: str | None = Query(None, description="Filtrar por ciudad"),
    activo: bool | None = Query(None, description="Filtrar por estado activo/inactivo"),
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> list[Supplier]:
    """CU-32: Directorio de proveedores."""
    query = db.query(Supplier)

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Supplier.nombre_empresa.ilike(term),
                Supplier.nit.ilike(term),
                Supplier.contacto_nombre.ilike(term),
                Supplier.email.ilike(term),
            )
        )

    if ciudad:
        query = query.filter(Supplier.ciudad.ilike(f"%{ciudad.strip()}%"))

    if activo is not None:
        query = query.filter(Supplier.activo == activo)

    return query.order_by(Supplier.nombre_empresa.asc()).all()


@router.get(
    "/suppliers/{supplier_id}",
    response_model=SupplierOut,
    summary="CU-32: Obtener detalle de un proveedor",
)
def obtener_proveedor(
    supplier_id: int,
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )
    return supplier


@router.post(
    "/suppliers",
    response_model=SupplierOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-32: Registrar nuevo proveedor",
    description="Permite dar de alta un nuevo fabricante textil o proveedor de insumos.",
)
def crear_proveedor(
    payload: SupplierInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Supplier:
    """CU-32: Alta de proveedor."""
    supplier = Supplier(
        nombre_empresa=payload.nombre_empresa.strip(),
        nit=payload.nit.strip() if payload.nit else None,
        contacto_nombre=payload.contacto_nombre.strip() if payload.contacto_nombre else None,
        telefono=payload.telefono.strip() if payload.telefono else None,
        email=payload.email.strip() if payload.email else None,
        ciudad=payload.ciudad.strip(),
        direccion=payload.direccion.strip() if payload.direccion else None,
        categoria_suministro=payload.categoria_suministro.strip(),
        activo=payload.activo,
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.put(
    "/suppliers/{supplier_id}",
    response_model=SupplierOut,
    summary="CU-32: Modificar datos de proveedor",
    description="Actualiza la información de contacto o suministro de un proveedor existente.",
)
def actualizar_proveedor(
    supplier_id: int,
    payload: SupplierInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )

    supplier.nombre_empresa = payload.nombre_empresa.strip()
    supplier.nit = payload.nit.strip() if payload.nit else None
    supplier.contacto_nombre = payload.contacto_nombre.strip() if payload.contacto_nombre else None
    supplier.telefono = payload.telefono.strip() if payload.telefono else None
    supplier.email = payload.email.strip() if payload.email else None
    supplier.ciudad = payload.ciudad.strip()
    supplier.direccion = payload.direccion.strip() if payload.direccion else None
    supplier.categoria_suministro = payload.categoria_suministro.strip()
    supplier.activo = payload.activo

    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete(
    "/suppliers/{supplier_id}",
    response_model=Message,
    summary="CU-32: Dar de baja proveedor",
    description="Elimina o desactiva un proveedor del directorio.",
)
def eliminar_proveedor(
    supplier_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Message:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )

    db.delete(supplier)
    db.commit()
    return Message(message="Proveedor eliminado correctamente.")
