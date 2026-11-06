from datetime import datetime
from sqlalchemy import BigInteger,DateTime,ForeignKey,String,Text,UniqueConstraint,func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from app.db.base import Base
from app.models.saas import TenantOwned

class CheckoutConfirmation(TenantOwned,Base):
    __tablename__='checkout_confirmaciones'
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    usuario_id:Mapped[int]=mapped_column(ForeignKey('usuarios.id'))
    operacion_id:Mapped[str]=mapped_column(String(36))
    payload_hash:Mapped[str]=mapped_column(String(64))
    pedido_id:Mapped[int]=mapped_column(ForeignKey('pedidos.id'))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    __table_args__=(UniqueConstraint('tenant_id','usuario_id','operacion_id',name='uq_checkout_owner_operation'),)

class BusinessReport(TenantOwned,Base):
    __tablename__='reportes_empresariales'
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    usuario_id:Mapped[int]=mapped_column(ForeignKey('usuarios.id'))
    consulta:Mapped[str]=mapped_column(Text)
    entrada:Mapped[str]=mapped_column(String(10))
    filtros:Mapped[dict]=mapped_column(JSONB)
    resultado:Mapped[dict]=mapped_column(JSONB)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
