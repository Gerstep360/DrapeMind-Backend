"""CU-01: Registrar cliente.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.schemas.api import RegisterRequest, UserOut

router = APIRouter()


@router.post(
    "/register",
    response_model=UserOut,
    status_code=201,
    summary="CU-01: Registrar cliente",
    description="Registra un nuevo cliente con contraseña encriptada por Argon2id y rol predeterminado CLIENTE.",
)
def registrar_cliente(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """CU-01: Registra cliente nuevo con email único y contraseña segura."""
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(409, "El email ya esta registrado")

    user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        nombre=payload.nombre,
        telefono=payload.telefono,
        rol=Role.CLIENTE,
        estado=UserStatus.ACTIVO,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
