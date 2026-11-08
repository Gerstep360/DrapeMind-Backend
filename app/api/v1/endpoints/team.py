from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User, Role
from app.models.saas import Tenant
from app.models.access import TenantRole, UserAccess
from app.services.access_control import PERMISSIONS, CLIENT, DEFAULTS, effective_access

router = APIRouter(prefix='/team', tags=['Equipo, roles y permisos'])
admin = require_roles(Role.ADMIN)


class RoleWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    nombre: str = Field(min_length=2, max_length=80)
    descripcion: str | None = Field(None, max_length=300)
    base_role: Role
    permisos: list[str] = Field(default_factory=list, max_length=30)
    activo: bool = True

    @model_validator(mode='after')
    def validate_permissions(self):
        if self.base_role == Role.ADMIN:
            raise ValueError('Los administradores conservan el acceso completo a su empresa')
        if set(self.permisos) - PERMISSIONS.keys() or 'team.manage' in self.permisos:
            raise ValueError('Permisos no configurables para este rol')
        if self.base_role == Role.CLIENTE and set(self.permisos) - CLIENT:
            raise ValueError('Un cliente no puede recibir permisos de empleado')
        return self


class AccessWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rol_empresa_id: int | None = Field(None, gt=0)
    permisos: dict[str, bool] = Field(default_factory=dict)


def role_out(role):
    return {key: getattr(role, key) for key in ('id', 'nombre', 'descripcion', 'base_role', 'permisos', 'activo')}


@router.get('/catalog')
def catalog(user: User = Depends(admin)):
    return {'permissions': [{'key': key, 'group': group, 'label': label, 'delegable': key != 'team.manage'} for key, (group, label) in PERMISSIONS.items()],
            'defaults': {role.value: sorted(perms) for role, perms in DEFAULTS.items()}}


@router.get('/me')
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return effective_access(db, user)


@router.get('/roles')
def roles(user: User = Depends(admin), db: Session = Depends(get_db)):
    return [role_out(row) for row in db.scalars(select(TenantRole).order_by(TenantRole.nombre))]


def save_role(db, row, payload):
    for key, value in payload.model_dump().items():
        setattr(row, key, list(dict.fromkeys(value)) if key == 'permisos' else value)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Ya existe un rol con ese nombre en tu empresa')
    db.refresh(row)
    db.info.pop('effective_access', None)
    return role_out(row)


@router.post('/roles', status_code=201)
def create_role(payload: RoleWrite, user: User = Depends(admin), db: Session = Depends(get_db)):
    return save_role(db, TenantRole(), payload)


@router.put('/roles/{role_id}')
def update_role(role_id: int, payload: RoleWrite, user: User = Depends(admin), db: Session = Depends(get_db)):
    db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    row = db.get(TenantRole, role_id)
    if not row:
        raise HTTPException(404, 'Rol no encontrado en tu empresa')
    assigned = db.scalar(select(func.count(UserAccess.id)).where(UserAccess.rol_empresa_id == row.id)) or 0
    if assigned and payload.base_role != row.base_role:
        raise HTTPException(409, 'Este rol ya tiene usuarios. Crea otro rol para cambiar su función de trabajo.')
    return save_role(db, row, payload)


@router.get('/users/{user_id}/access')
def get_access(user_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'Usuario no encontrado en tu empresa')
    return {'usuario_id': target.id, 'base_role': target.rol, **effective_access(db, target)}


@router.put('/users/{user_id}/access')
def set_access(user_id: int, payload: AccessWrite, user: User = Depends(admin), db: Session = Depends(get_db)):
    db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'Usuario no encontrado en tu empresa')
    if target.rol == Role.ADMIN:
        raise HTTPException(409, 'Los administradores conservan todos los permisos. Cambia primero su función si necesitas limitar su acceso.')
    if set(payload.permisos) - PERMISSIONS.keys() or 'team.manage' in payload.permisos:
        raise HTTPException(422, 'Hay permisos no configurables en la solicitud')
    profile = db.get(TenantRole, payload.rol_empresa_id) if payload.rol_empresa_id else None
    if payload.rol_empresa_id and not profile:
        raise HTTPException(404, 'Rol no encontrado en tu empresa')
    base = profile.base_role if profile else target.rol
    if target.customer_account_id and (base != Role.CLIENTE or any(key not in CLIENT and value for key, value in payload.permisos.items())):
        raise HTTPException(409, 'La cuenta personal del cliente no se puede convertir en una cuenta de empleado')
    if base == Role.CLIENTE and any(key not in CLIENT and value for key, value in payload.permisos.items()):
        raise HTTPException(422, 'Un cliente no puede recibir permisos de empleado')
    row = db.scalar(select(UserAccess).where(UserAccess.usuario_id == target.id))
    if row is None:
        row = UserAccess(usuario_id=target.id)
        db.add(row)
    row.rol_empresa_id = profile.id if profile else None
    row.overrides = payload.permisos
    row.updated_by = user.id
    target.rol = base
    db.commit()
    db.info.pop('effective_access', None)
    return {'usuario_id': target.id, 'base_role': target.rol, **effective_access(db, target)}
