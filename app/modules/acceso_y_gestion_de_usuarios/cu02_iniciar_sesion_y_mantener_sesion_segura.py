"""CU-02: Iniciar sesión y mantener sesión segura.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import User
from app.schemas.api import ForgotPasswordRequest, LoginRequest, Message, TokenResponse, UserOut
from app.services.sign_in import sign_in, user_profile

router = APIRouter()


@router.post(
    "/forgot-password",
    response_model=Message,
    summary="CU-02: Restablecer contraseña",
    description="Permite a un usuario restablecer su contraseña indicando su email registrado.",
)
def restablecer_contrasena(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> Message:
    raise HTTPException(409, 'La recuperaci?n requiere validaci?n del administrador de tu empresa; no se cambia una contrase?a solo con un correo.')


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="CU-02: Iniciar sesión con JWT",
    description="Autenticación con email y contraseña, emitiendo un Bearer JWT de acceso seguro.",
)
def iniciar_sesion(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    return sign_in(db,str(payload.email),payload.password,payload.tenant_slug)


@router.get(
    "/me",
    response_model=UserOut,
    summary="CU-02: Consultar usuario autenticado",
    description="Retorna el perfil del usuario activo en la sesión actual.",
)
def obtener_usuario_actual(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserOut:
    """CU-02: Valida y devuelve el usuario de la sesión actual."""
    return user_profile(db,user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="CU-02: Renovar token de sesión",
    description="Extiende la vigencia del token JWT para sesiones activas.",
)
def refrescar_sesion(user: User = Depends(get_current_user)) -> dict:
    """CU-02: Renueva el token de acceso JWT del usuario activo."""
    token, expires_in = create_access_token(user.id, user.rol.value, tenant_id=user.tenant_id, platform=bool(user.is_platform_admin))
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }
