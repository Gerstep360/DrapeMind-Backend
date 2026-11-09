from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.models.saas import TenantOwned
from app.models.entities import TimestampMixin

class ProductReview(TenantOwned, TimestampMixin, Base):
    __tablename__ = "resenas_prendas"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    calificacion: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 a 5
    titulo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    comentario: Mapped[str] = mapped_column(Text, nullable=False)
    compra_verificada: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    producto: Mapped["Product"] = relationship("Product", foreign_keys=[producto_id])
    usuario: Mapped["User"] = relationship("User", foreign_keys=[usuario_id])

    __table_args__ = (
        UniqueConstraint("tenant_id", "producto_id", "usuario_id", name="uq_resena_tenant_producto_usuario"),
        CheckConstraint("calificacion BETWEEN 1 AND 5", name="ck_resena_calificacion"),
        CheckConstraint("length(trim(comentario)) BETWEEN 3 AND 1000", name="ck_resena_comentario"),
        Index("ix_resena_tenant_producto_activo", "tenant_id", "producto_id", "activo"),
        Index("ix_resena_producto_calificacion", "producto_id", "calificacion"),
    )
