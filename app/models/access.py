from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.saas import TenantOwned
from app.models.entities import Role, role_enum


class TenantRole(TenantOwned, Base):
    __tablename__ = 'roles_empresa'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))
    descripcion: Mapped[str | None] = mapped_column(String(300))
    base_role: Mapped[Role] = mapped_column(role_enum)
    permisos: Mapped[list] = mapped_column(JSONB, default=list)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'nombre', name='uq_role_company_name'),)


class UserAccess(TenantOwned, Base):
    __tablename__ = 'accesos_usuario'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id', ondelete='CASCADE'))
    rol_empresa_id: Mapped[int | None] = mapped_column(ForeignKey('roles_empresa.id', ondelete='RESTRICT'))
    overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[int] = mapped_column(ForeignKey('usuarios.id', ondelete='RESTRICT'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint('tenant_id', 'usuario_id', name='uq_access_company_user'),)
