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
def listar_ciudades(db: Session = Depends(get_db)) -> list[City]:
    return list(db.scalars(select(City).where(City.activo.is_(True)).order_by(City.nombre)))


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


@router.get("", response_model=list[BranchOut], summary="CU-28: Listar sucursales")
def listar_sucursales(ciudad_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(Branch, City)
        .join(City, City.id == Branch.ciudad_id)
        .where(Branch.activo.is_(True), City.activo.is_(True))
        .order_by(City.nombre, Branch.nombre)
    )
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

