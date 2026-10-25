from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Role, User, UserStatus

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales invalidas o expiradas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
    except (ValueError, TypeError):
        raise credentials_error
    from app.core.tenancy import system_scope
    if claims.get('platform') is True:
        with system_scope(db): user = db.get(User, user_id)
    else:
        user = db.get(User, user_id)
    if not user:
        raise credentials_error
    if user.tenant_id != claims.get('tid') or bool(user.is_platform_admin) != (claims.get('platform') is True):
        raise credentials_error
    if user.estado != UserStatus.ACTIVO:
        raise HTTPException(status_code=403, detail="La cuenta no esta activa")
    if user.customer_account_id:
        from app.models.saas import CustomerAccount
        identity=db.get(CustomerAccount,user.customer_account_id)
        if not identity or not identity.active or user.rol!=Role.CLIENTE:
            raise HTTPException(403,'La cuenta personal no está disponible')
    return user


def require_roles(*roles: Role) -> Callable:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.is_platform_admin or current_user.tenant_id is None:
            raise HTTPException(403, 'Esta operación requiere un administrador de la empresa')
        if current_user.rol not in roles:
            raise HTTPException(status_code=403, detail="No tiene permisos para esta operacion")
        return current_user

    return dependency


require_role = require_roles



oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/token", auto_error=False
)


def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional), db: Session = Depends(get_db)
) -> User | None:
    if not token:
        return None
    try:
        user_id = int(decode_access_token(token)["sub"])
        user = db.get(User, user_id)
        if user and user.estado == UserStatus.ACTIVO:
            return user
    except Exception:
        return None
    return None


CurrentUser = Depends(get_current_user)
CurrentUserOptional = Depends(get_current_user_optional)
AdminUser = Depends(require_roles(Role.ADMIN))
StaffUser = Depends(require_roles(Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO, Role.CAJERO))
