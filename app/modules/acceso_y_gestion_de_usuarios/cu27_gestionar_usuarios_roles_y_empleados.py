"""CU-27: Gestionar usuarios, roles y empleados.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel, EmailStr, Field
from app.api.deps import require_role
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.schemas.api import UserOut

router = APIRouter()


class AdminUserCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    telefono: str | None = None
    rol: Role = Role.CLIENTE
    estado: UserStatus = UserStatus.ACTIVO


class AdminUserUpdate(BaseModel):
    nombre: str | None = None
    telefono: str | None = None
    rol: Role | None = None
    estado: UserStatus | None = None



@router.get(
    "/users",
    response_model=list[UserOut],
    summary="CU-27: Listar todos los usuarios y empleados",
    description="Permite al administrador auditar la lista completa de usuarios, empleados y roles.",
)
def listar_usuarios(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    rol: Role | None = None,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[User]:
    """CU-27: Consulta administrativa de usuarios del sistema."""
    query = select(User)
    if rol:
        query = query.where(User.rol == rol)
    query = query.order_by(User.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-27: Crear usuario o empleado",
    description="Permite al administrador crear cuentas con roles específicos (ADMIN, VENDEDOR, CLIENTE).",
)
def crear_usuario_administrativo(
    payload: AdminUserCreate,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    """CU-27: Alta administrativa de usuario o empleado."""
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(409, "El email ya está registrado")

    user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        nombre=payload.nombre,
        telefono=payload.telefono,
        rol=payload.rol,
        estado=payload.estado,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="CU-27: Actualizar rol o estado de usuario",
    description="Permite al administrador modificar roles y suspender o activar cuentas.",
)
def actualizar_usuario_administrativo(
    user_id: int,
    payload: AdminUserUpdate,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    """CU-27: Modificación de roles y estado de cuenta."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if payload.rol is not None:
        user.rol = payload.rol
    if payload.estado is not None:
        user.estado = payload.estado
    if payload.nombre is not None:
        user.nombre = payload.nombre
    if payload.telefono is not None:
        user.telefono = payload.telefono

    db.commit()
    db.refresh(user)
    return user
