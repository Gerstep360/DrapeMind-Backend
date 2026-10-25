"""CU-27: Gestionar usuarios, roles y empleados.
Paquete: Acceso y gestión de usuarios (PK-01).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.api.deps import require_role, require_roles
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.models.saas import Tenant
from app.schemas.api import UserOut

router = APIRouter()


def _ensure_active_admin(db: Session, user: User, next_role: Role, next_status: UserStatus) -> None:
    if user.rol == Role.ADMIN and user.estado == UserStatus.ACTIVO and (next_role != Role.ADMIN or next_status != UserStatus.ACTIVO):
        admins = db.scalar(select(func.count(User.id)).where(User.rol == Role.ADMIN, User.estado == UserStatus.ACTIVO)) or 0
        if admins <= 1:
            raise HTTPException(409, 'La empresa debe conservar al menos un administrador activo')


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    telefono: str | None = None
    rol: Role = Role.CLIENTE
    estado: UserStatus = UserStatus.ACTIVO


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nombre: str | None = None
    telefono: str | None = None
    rol: Role | None = None
    estado: UserStatus | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)


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
    q: str | None = None,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[User]:
    """CU-27: Consulta administrativa de usuarios del sistema."""
    from sqlalchemy import or_
    query = select(User)
    if rol:
        query = query.where(User.rol == rol)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            or_(
                User.nombre.ilike(term),
                User.email.ilike(term),
                User.telefono.ilike(term),
            )
        )
    query = query.order_by(User.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@router.get(
    "/customers/search",
    response_model=list[UserOut],
    summary="CU-27: Buscar clientes para Punto de Venta POS",
    description="Permite a vendedores y cajeros buscar clientes por nombre, teléfono o correo.",
)
def buscar_clientes_pos(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=15, ge=1, le=50),
    _staff: User = Depends(require_roles(Role.ADMIN, Role.ENCARGADO, Role.VENDEDOR, Role.CAJERO)),
    db: Session = Depends(get_db),
) -> list[User]:
    from sqlalchemy import or_
    query = select(User).where(User.rol == Role.CLIENTE)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            or_(
                User.nombre.ilike(term),
                User.email.ilike(term),
                User.telefono.ilike(term),
            )
        )
    query = query.order_by(User.nombre.asc()).limit(limit)
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
    email = str(payload.email).strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing:
        raise HTTPException(409, "El email ya está registrado")

    user = User(
        email=email,
        password_hash=get_password_hash(payload.password),
        nombre=payload.nombre,
        telefono=payload.telefono,
        rol=payload.rol,
        estado=payload.estado,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'El email ya está registrado en esta empresa')
    db.refresh(user)
    return user


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="CU-27: Actualizar rol o estado de usuario",
    description="Permite al administrador modificar roles, contraseñas y suspender o activar cuentas.",
)
def actualizar_usuario_administrativo(
    user_id: int,
    payload: AdminUserUpdate,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    """CU-27: Modificación de roles, credenciales y estado de cuenta."""
    # Serializes concurrent changes so two administrators cannot both remove the last role.
    db.scalar(select(Tenant).where(Tenant.id == _admin.tenant_id).with_for_update())
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    next_role = payload.rol if payload.rol is not None else user.rol
    if user.customer_account_id and (next_role!=Role.CLIENTE or payload.password):
        raise HTTPException(409,'Esta es una cuenta personal del cliente. Su contraseña se gestiona fuera de la tienda y no puede convertirse en una cuenta de empleado.')
    next_status = payload.estado if payload.estado is not None else user.estado
    _ensure_active_admin(db,user,next_role,next_status)

    if payload.rol is not None:
        user.rol = payload.rol
    if payload.estado is not None:
        user.estado = payload.estado
    if payload.nombre is not None:
        user.nombre = payload.nombre
    if payload.telefono is not None:
        user.telefono = payload.telefono
    if payload.password is not None and payload.password.strip():
        user.password_hash = get_password_hash(payload.password)

    db.commit()
    db.refresh(user)
    return user


@router.delete(
    "/users/{user_id}",
    summary="CU-27: Alternar estado o suspender usuario",
)
def eliminar_o_suspender_usuario(
    user_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    db.scalar(select(Tenant).where(Tenant.id == _admin.tenant_id).with_for_update())
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == _admin.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta administradora")

    next_status = UserStatus.BLOQUEADO if user.estado == UserStatus.ACTIVO else UserStatus.ACTIVO
    _ensure_active_admin(db,user,user.rol,next_status)

    if user.estado == UserStatus.ACTIVO:
        user.estado = UserStatus.BLOQUEADO
    else:
        user.estado = UserStatus.ACTIVO

    db.commit()
    return {"message": f"Usuario {user.nombre} ahora está {user.estado.value}", "estado": user.estado.value}

