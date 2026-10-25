"""CU-01: Registrar cliente.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.schemas.api import RegisterRequest, UserOut
from app.models.saas import CustomerAccount

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
    if db.scalar(select(CustomerAccount.id).where(CustomerAccount.email==str(payload.email).lower())):
        raise HTTPException(409,'Ya tienes una cuenta DrapeMind. Inicia sesión para comprar en esta tienda.')
    try:
        account=CustomerAccount(email=str(payload.email).lower(),password_hash=get_password_hash(payload.password),name=payload.nombre,phone=payload.telefono)
        db.add(account);db.flush()
        user = User(email=str(payload.email).lower(),password_hash=account.password_hash,nombre=payload.nombre,telefono=payload.telefono,rol=Role.CLIENTE,estado=UserStatus.ACTIVO,customer_account_id=account.id)
        db.add(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Ya existe una cuenta con este correo. Inicia sesión.')
    db.refresh(user)
    return user
