"""CU-33: Registrar productos y disponibilidad como proveedor.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Role, Supplier, SupplierProduct, User, UserStatus
from app.schemas.api import (
    Message,
    SupplierAccountCreate,
    SupplierOut,
    SupplierProductInput,
    SupplierProductOut,
)

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
    "/suppliers/me/profile",
    response_model=SupplierOut,
    summary="CU-33: Obtener perfil del proveedor autenticado",
)
def obtener_mi_perfil_proveedor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = db.query(Supplier).filter(Supplier.usuario_id == current_user.id).first()
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontro una empresa proveedora vinculada a este usuario.",
        )
    return supplier


@router.get(
    "/suppliers/me/products",
    response_model=list[SupplierProductOut],
    summary="CU-33: Listar suministros y prendas del proveedor autenticado",
)
def listar_mis_suministros(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SupplierProduct]:
    supplier = db.query(Supplier).filter(Supplier.usuario_id == current_user.id).first()
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontro una empresa proveedora vinculada a este usuario.",
        )
    return (
        db.query(SupplierProduct)
        .filter(SupplierProduct.proveedor_id == supplier.id)
        .order_by(SupplierProduct.created_at.desc())
        .all()
    )


@router.post(
    "/suppliers/me/products",
    response_model=SupplierProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-33: Registrar suministro o prenda por el proveedor autenticado",
)
def registrar_mi_suministro(
    payload: SupplierProductInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SupplierProduct:
    supplier = db.query(Supplier).filter(Supplier.usuario_id == current_user.id).first()
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontro una empresa proveedora vinculada a este usuario.",
        )
    supply = SupplierProduct(
        proveedor_id=supplier.id,
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
    "/suppliers/me/products/{product_id}",
    response_model=SupplierProductOut,
    summary="CU-33: Actualizar suministro o prenda por el proveedor autenticado",
)
def actualizar_mi_suministro(
    product_id: int,
    payload: SupplierProductInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SupplierProduct:
    supplier = db.query(Supplier).filter(Supplier.usuario_id == current_user.id).first()
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontro una empresa proveedora vinculada a este usuario.",
        )
    supply = (
        db.query(SupplierProduct)
        .filter(
            SupplierProduct.id == product_id,
            SupplierProduct.proveedor_id == supplier.id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suministro no encontrado en su catalogo.",
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
    "/suppliers/me/products/{product_id}",
    response_model=Message,
    summary="CU-33: Eliminar suministro o prenda por el proveedor autenticado",
)
def eliminar_mi_suministro(
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    supplier = db.query(Supplier).filter(Supplier.usuario_id == current_user.id).first()
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontro una empresa proveedora vinculada a este usuario.",
        )
    supply = (
        db.query(SupplierProduct)
        .filter(
            SupplierProduct.id == product_id,
            SupplierProduct.proveedor_id == supplier.id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suministro no encontrado en su catalogo.",
        )

    db.delete(supply)
    db.commit()
    return Message(message="Suministro eliminado de su catalogo exitosamente.")


@router.post(
    "/suppliers/{supplier_id}/account",
    response_model=SupplierOut,
    summary="CU-33: Crear o vincular cuenta de usuario para proveedor",
    description="Crea una cuenta de usuario con rol PROVEEDOR o vincula una existente a la empresa proveedora.",
)
def crear_cuenta_proveedor(
    supplier_id: int,
    payload: SupplierAccountCreate,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )

    target_email = str(payload.email).strip().lower()
    existing_user = db.query(User).filter(User.email == target_email).first()

    if existing_user:
        if existing_user.rol != Role.PROVEEDOR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El correo {target_email} ya pertenece a un usuario con rol {existing_user.rol.value}.",
            )
        existing_user.password_hash = hash_password(payload.password)
        if payload.nombre:
            existing_user.nombre = payload.nombre.strip()
        user = existing_user
    else:
        user_name = (
            payload.nombre.strip()
            if payload.nombre
            else (supplier.contacto_nombre or supplier.nombre_empresa)
        )
        user = User(
            nombre=user_name,
            email=target_email,
            password_hash=hash_password(payload.password),
            telefono=supplier.telefono,
            rol=Role.PROVEEDOR,
            estado=UserStatus.ACTIVO,
        )
        db.add(user)
        db.flush()

    supplier.usuario_id = user.id
    if not supplier.email:
        supplier.email = target_email

    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete(
    "/suppliers/{supplier_id}/account",
    response_model=SupplierOut,
    summary="CU-33: Desvincular cuenta de usuario de proveedor",
)
def desvincular_cuenta_proveedor(
    supplier_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proveedor no encontrado.",
        )
    supplier.usuario_id = None
    db.commit()
    db.refresh(supplier)
    return supplier


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
