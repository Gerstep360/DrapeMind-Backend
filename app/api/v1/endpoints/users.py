from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Address, User
from app.schemas.api import AddressInput, AddressOut, UserOut, UserUpdate

router = APIRouter()


@router.patch(
    "/me", response_model=UserOut, summary="Actualizar perfil",
    description="CU-03. Actualiza nombre y telefono del cliente autenticado.",
)
def update_me(
    payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me/addresses", response_model=list[AddressOut], summary="Listar direcciones")
def list_addresses(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Address]:
    return list(db.scalars(select(Address).where(Address.usuario_id == current_user.id).order_by(Address.es_principal.desc(), Address.id)))


@router.post(
    "/me/addresses", response_model=AddressOut, status_code=201, summary="Crear direccion",
    description="CU-03. Si es principal, desmarca atomically la direccion principal anterior.",
)
def create_address(
    payload: AddressInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Address:
    if payload.es_principal:
        db.execute(update(Address).where(Address.usuario_id == current_user.id).values(es_principal=False))
    address = Address(usuario_id=current_user.id, **payload.model_dump())
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.put("/me/addresses/{address_id}", response_model=AddressOut, summary="Actualizar direccion")
def update_address(
    address_id: int, payload: AddressInput, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Address:
    address = db.scalar(select(Address).where(Address.id == address_id, Address.usuario_id == current_user.id))
    if not address:
        raise HTTPException(404, "Direccion no encontrada")
    if payload.es_principal:
        db.execute(update(Address).where(Address.usuario_id == current_user.id).values(es_principal=False))
    for field, value in payload.model_dump().items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/me/addresses/{address_id}", status_code=204, summary="Eliminar direccion")
def delete_address(
    address_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    address = db.scalar(select(Address).where(Address.id == address_id, Address.usuario_id == current_user.id))
    if not address:
        raise HTTPException(404, "Direccion no encontrada")
    db.delete(address)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
