from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Branch, City, Role, User
from app.schemas.api import BranchInput, BranchOut, CityInput, CityOut

router = APIRouter()


def _branch_payload(branch: Branch, city: City | None = None) -> dict:
    return {
        "id": branch.id,
        "ciudad_id": branch.ciudad_id,
        "codigo": branch.codigo,
        "nombre": branch.nombre,
        "direccion": branch.direccion,
        "telefono": branch.telefono,
        "latitud": branch.latitud,
        "longitud": branch.longitud,
        "activo": branch.activo,
        "ciudad": city.nombre if city else None,
        "departamento": city.departamento if city else None,
    }


@router.get("/cities", response_model=list[CityOut], summary="CU-28: Listar ciudades con sucursales")
def listar_ciudades(include_inactive: bool = False, db: Session = Depends(get_db)) -> list[City]:
    stmt = select(City)
    if not include_inactive:
        stmt = stmt.where(City.activo.is_(True))
    return list(db.scalars(stmt.order_by(City.nombre)))


@router.post("/cities", response_model=CityOut, status_code=status.HTTP_201_CREATED, summary="CU-28: Crear ciudad")
def crear_ciudad(
    payload: CityInput,
    admin: User = Depends(require_role(Role.ADMIN)),
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


@router.put("/cities/{city_id}", response_model=CityOut, summary="CU-28: Actualizar ciudad")
def actualizar_ciudad(
    city_id: int,
    payload: CityInput,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> City:
    city = db.get(City, city_id)
    if not city:
        raise HTTPException(404, "Ciudad no encontrada")
    for field, val in payload.model_dump().items():
        setattr(city, field, val)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Error de integridad al actualizar ciudad") from exc
    db.refresh(city)
    return city


@router.delete("/cities/{city_id}", summary="CU-28: Alternar estado o eliminar ciudad")
def eliminar_o_desactivar_ciudad(
    city_id: int,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    city = db.get(City, city_id)
    if not city:
        raise HTTPException(404, "Ciudad no encontrada")
    city.activo = not city.activo
    db.commit()
    return {"message": f"Ciudad {'activada' if city.activo else 'desactivada'} correctamente", "activo": city.activo}


@router.get("", response_model=list[BranchOut], summary="CU-28: Listar sucursales")
def listar_sucursales(ciudad_id: int | None = None, include_inactive: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(Branch, City)
        .join(City, City.id == Branch.ciudad_id)
        .order_by(City.nombre, Branch.nombre)
    )
    if not include_inactive:
        stmt = stmt.where(Branch.activo.is_(True), City.activo.is_(True))
    if ciudad_id is not None:
        stmt = stmt.where(Branch.ciudad_id == ciudad_id)
    return [_branch_payload(branch, city) for branch, city in db.execute(stmt)]


@router.get("/{branch_id}", response_model=BranchOut, summary="CU-28: Consultar sucursal")
def obtener_sucursal(branch_id: int, db: Session = Depends(get_db)) -> dict:
    result = db.execute(
        select(Branch, City).join(City, City.id == Branch.ciudad_id).where(Branch.id == branch_id)
    ).first()
    if not result:
        raise HTTPException(404, "Sucursal no encontrada")
    return _branch_payload(*result)


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED, summary="CU-28: Crear sucursal")
def crear_sucursal(
    payload: BranchInput,
    admin: User = Depends(require_role(Role.ADMIN)),
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


@router.put("/{branch_id}", response_model=BranchOut, summary="CU-28: Actualizar sucursal")
def actualizar_sucursal(
    branch_id: int,
    payload: BranchInput,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    city = db.get(City, payload.ciudad_id)
    if not city:
        raise HTTPException(404, "Ciudad asignada no encontrada")

    for field, val in payload.model_dump().items():
        setattr(branch, field, val)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Código de sucursal duplicado u otro conflicto") from exc

    db.refresh(branch)
    return _branch_payload(branch, city)


@router.delete("/{branch_id}", summary="CU-28: Alternar estado o dar de baja sucursal")
def eliminar_o_desactivar_sucursal(
    branch_id: int,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(404, "Sucursal no encontrada")
    branch.activo = not branch.activo
    db.commit()
    return {"message": f"Sucursal {'activada' if branch.activo else 'desactivada'} correctamente", "activo": branch.activo}


