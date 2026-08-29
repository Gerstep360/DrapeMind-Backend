"""CU-02: Iniciar sesión y mantener sesión segura.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.schemas.api import LoginRequest, TokenResponse, UserOut

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="CU-02: Iniciar sesión con JWT",
    description="Autenticación con email y contraseña, emitiendo un Bearer JWT de acceso seguro.",
)
def iniciar_sesion(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """CU-02: Autentica credenciales y emite token JWT."""
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.estado != UserStatus.ACTIVO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo o bloqueado",
        )

    token, expires_in = create_access_token(user.id, user.rol.value)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }


@router.get(
    "/me",
    response_model=UserOut,
    summary="CU-02: Consultar usuario autenticado",
    description="Retorna el perfil del usuario activo en la sesión actual.",
)
def obtener_usuario_actual(user: User = Depends(get_current_user)) -> User:
    """CU-02: Valida y devuelve el usuario de la sesión actual."""
    return user


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="CU-02: Renovar token de sesión",
    description="Extiende la vigencia del token JWT para sesiones activas.",
)
def refrescar_sesion(user: User = Depends(get_current_user)) -> dict:
    """CU-02: Renueva el token de acceso JWT del usuario activo."""
    token, expires_in = create_access_token(user.id, user.rol.value)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }
