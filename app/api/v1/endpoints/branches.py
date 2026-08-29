from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import Branch, BranchStaff, BranchStock, City, Product, ProductVariant, Role, User
from app.schemas.api import (
    BranchInput, BranchOut, BranchStockInput, BranchStockOut, CityInput, CityOut,
    StaffAssignmentInput,
)

router = APIRouter()


def _branch_payload(branch: Branch, city: City | None = None) -> dict:
    return {
        "id": branch.id, "ciudad_id": branch.ciudad_id, "codigo": branch.codigo,
        "nombre": branch.nombre, "direccion": branch.direccion, "telefono": branch.telefono,
        "latitud": branch.latitud, "longitud": branch.longitud, "activo": branch.activo,
        "ciudad": city.nombre if city else None,
        "departamento": city.departamento if city else None,
    }


def _stock_payload(row: BranchStock, variant: ProductVariant, product: Product) -> dict:
    return {
        "sucursal_id": row.sucursal_id, "variante_id": row.variante_id,
        "producto_id": product.id, "producto": product.nombre, "sku": variant.sku,
        "color": variant.color, "talla": variant.talla, "stock_total": row.stock_total,
        "stock_reservado": row.stock_reservado,
        "stock_disponible": row.stock_total - row.stock_reservado,
        "activo": row.activo and variant.activo and product.activo,
    }


def _sync_variant_totals(db: Session, variant_id: int) -> None:
    variant = db.get(ProductVariant, variant_id)
    if not variant:
        return
    totals = db.execute(
        select(
            func.coalesce(func.sum(BranchStock.stock_total), 0),
            func.coalesce(func.sum(BranchStock.stock_reservado), 0),
        ).where(BranchStock.variante_id == variant_id, BranchStock.activo.is_(True))
    ).one()
    variant.stock_total = int(totals[0])
    variant.stock_reservado = int(totals[1])


@router.get("/cities", response_model=list[CityOut], summary="Listar ciudades con sucursales")
def list_cities(db: Session = Depends(get_db)) -> list[City]:
    return list(db.scalars(select(City).where(City.activo.is_(True)).order_by(City.nombre)))


@router.get("", response_model=list[BranchOut], summary="Listar sucursales")
def list_branches(ciudad_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(Branch, City).join(City, City.id == Branch.ciudad_id)
        .where(Branch.activo.is_(True), City.activo.is_(True))
        .order_by(City.nombre, Branch.nombre)
    )
    if ciudad_id is not None:
        stmt = stmt.where(Branch.ciudad_id == ciudad_id)
    return [_branch_payload(branch, city) for branch, city in db.execute(stmt)]


@router.get(
    "/products/{product_id}/availability", response_model=list[BranchStockOut],
    summary="Disponibilidad de un producto por sucursal",
    description="CU-07. Devuelve stock físico disponible separado por sede, talla y color.",
)
def product_availability(product_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if not db.scalar(select(Product.id).where(Product.id == product_id, Product.activo.is_(True))):
        raise HTTPException(404, "Producto no encontrado")
    stmt = (
        select(BranchStock, ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == BranchStock.variante_id)
        .join(Product, Product.id == ProductVariant.producto_id)
        .join(Branch, Branch.id == BranchStock.sucursal_id)
        .where(
            Product.id == product_id, Branch.activo.is_(True), BranchStock.activo.is_(True),
            BranchStock.stock_total > BranchStock.stock_reservado,
        )
        .order_by(BranchStock.sucursal_id, ProductVariant.color, ProductVariant.talla)
    )
    return [_stock_payload(row, variant, product) for row, variant, product in db.execute(stmt)]


@router.get("/{branch_id}", response_model=BranchOut, summary="Consultar sucursal")
def get_branch(branch_id: int, db: Session = Depends(get_db)) -> dict:
    result = db.execute(
        select(Branch, City).join(City, City.id == Branch.ciudad_id).where(Branch.id == branch_id)
    ).first()
    if not result:
        raise HTTPException(404, "Sucursal no encontrada")
    return _branch_payload(*result)


@router.get(
    "/{branch_id}/availability", response_model=list[BranchStockOut],
    summary="Consultar inventario disponible de una sucursal",
    description="CU-07. Permite filtrar por producto, variante, talla y color.",
)
def branch_availability(
    branch_id: int, producto_id: int | None = None, variante_id: int | None = None,
    talla: str | None = Query(default=None, max_length=20),
    color: str | None = Query(default=None, max_length=60), con_stock: bool = True,
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


@router.post("/cities", response_model=CityOut, status_code=status.HTTP_201_CREATED, summary="Crear ciudad")
def create_city(
    payload: CityInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> City:
    city = City(**payload.model_dump())
    db.add(city)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "La ciudad ya existe") from exc
    db.refresh(city)
    return city


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED, summary="Crear sucursal")
def create_branch(
    payload: BranchInput, admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    city = db.get(City, payload.ciudad_id)
    if not city:
        raise HTTPException(404, "Ciudad no encontrada")
    branch = Branch(**payload.model_dump())
    db.add(branch)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El código de sucursal ya existe") from exc
    db.refresh(branch)
    return _branch_payload(branch, city)


@router.put("/{branch_id}/stock", response_model=BranchStockOut, summary="Ajustar stock en sucursal")
def set_branch_stock(
    branch_id: int, payload: BranchStockInput,
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    variant = db.scalar(select(ProductVariant).where(ProductVariant.id == payload.variante_id).with_for_update())
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    if not variant:
        raise HTTPException(404, "Variante no encontrada")
    row = db.scalar(
        select(BranchStock).where(
            BranchStock.sucursal_id == branch_id, BranchStock.variante_id == variant.id,
        ).with_for_update()
    )
    if row and payload.stock_total < row.stock_reservado:
        raise HTTPException(409, "El stock total no puede ser menor al reservado")
    if not row:
        row = BranchStock(
            sucursal_id=branch_id, variante_id=variant.id, stock_reservado=0,
            **payload.model_dump(exclude={"variante_id"}),
        )
        db.add(row)
        db.flush()
    else:
        row.stock_total = payload.stock_total
        row.stock_minimo = payload.stock_minimo
        row.activo = payload.activo
    _sync_variant_totals(db, variant.id)
    db.commit()
    db.refresh(row)
    return _stock_payload(row, variant, db.get(Product, variant.producto_id))


@router.post("/{branch_id}/staff", status_code=status.HTTP_201_CREATED, summary="Asignar personal a sucursal")
def assign_staff(
    branch_id: int, payload: StaffAssignmentInput,
    admin: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    user = db.get(User, payload.usuario_id)
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    if not user or user.rol not in {Role.ENCARGADO, Role.CAJERO, Role.VENDEDOR}:
        raise HTTPException(409, "El usuario debe ser ENCARGADO, CAJERO o VENDEDOR")
    assignment = db.scalar(
        select(BranchStaff).where(
            BranchStaff.sucursal_id == branch_id, BranchStaff.usuario_id == user.id,
        )
    )
    if assignment:
        assignment.activo = True
    else:
        db.add(BranchStaff(sucursal_id=branch_id, usuario_id=user.id, activo=True))
    db.commit()
    return {"sucursal_id": branch_id, "usuario_id": user.id, "activo": True}
