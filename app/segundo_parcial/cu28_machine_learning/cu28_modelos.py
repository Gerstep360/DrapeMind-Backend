from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.saas import TenantOwned


class DemandModel(TenantOwned, Base):
    __tablename__ = "modelos_demanda"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alcance: Mapped[str] = mapped_column(String(80))
    sucursal_id: Mapped[int | None] = mapped_column(
        ForeignKey("sucursales.id", ondelete="RESTRICT")
    )
    entrenado_por: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    datos_hash: Mapped[str] = mapped_column(String(64))
    modelo: Mapped[str] = mapped_column(String(80))
    artefacto: Mapped[dict] = mapped_column(JSONB)
    resultado: Mapped[dict] = mapped_column(JSONB)
    entrenado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("tenant_id", "alcance", name="uq_modelo_demanda_alcance"),
    )
