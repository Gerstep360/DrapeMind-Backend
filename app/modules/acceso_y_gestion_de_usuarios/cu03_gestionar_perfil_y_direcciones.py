"""CU-03: Gestionar perfil y direcciones.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Address, User
from app.schemas.api import AddressInput, AddressOut, UserOut, UserUpdate

router = APIRouter()


@router.patch(
    "/me",
    response_model=UserOut,
    summary="CU-03: Actualizar perfil de usuario",
    description="CU-03. Actualiza nombre y teléfono del cliente autenticado.",
)
def actualizar_perfil_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me/addresses", response_model=list[AddressOut], summary="CU-03: Listar direcciones")
def listar_direcciones_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Address]:
    return list(
        db.scalars(
            select(Address)
            .where(Address.usuario_id == current_user.id)
            .order_by(Address.es_principal.desc(), Address.id)
        )
    )


@router.post(
    "/me/addresses",
    response_model=AddressOut,
    status_code=201,
    summary="CU-03: Crear dirección",
    description="CU-03. Si es principal, desmarca automáticamente la dirección principal anterior.",
)
def crear_direccion_me(
    payload: AddressInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Address:
    has_address = (
        db.scalar(select(Address.id).where(Address.usuario_id == current_user.id)) is not None
    )
    data = payload.model_dump()
    if not has_address:
        data["es_principal"] = True
    if data["es_principal"]:
        db.execute(
            update(Address)
            .where(Address.usuario_id == current_user.id)
            .values(es_principal=False)
        )
    address = Address(usuario_id=current_user.id, **data)
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.put("/me/addresses/{address_id}", response_model=AddressOut, summary="CU-03: Actualizar dirección")
def actualizar_direccion_me(
    address_id: int,
    payload: AddressInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Address:
    address = db.scalar(
        select(Address).where(
            Address.id == address_id, Address.usuario_id == current_user.id
        )
    )
    if not address:
        raise HTTPException(404, "Dirección no encontrada")
    if payload.es_principal:
        db.execute(
            update(Address)
            .where(Address.usuario_id == current_user.id)
            .values(es_principal=False)
        )
    for field, value in payload.model_dump().items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/me/addresses/{address_id}", status_code=204, summary="CU-03: Eliminar dirección")
def eliminar_direccion_me(
    address_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    address = db.scalar(
        select(Address).where(
            Address.id == address_id, Address.usuario_id == current_user.id
        )
    )
    if not address:
        raise HTTPException(404, "Dirección no encontrada")
    was_primary = address.es_principal
    db.delete(address)
    db.flush()
    if was_primary:
        replacement = db.scalar(
            select(Address)
            .where(Address.usuario_id == current_user.id)
            .order_by(Address.id)
            .limit(1)
        )
        if replacement:
            replacement.es_principal = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

