"""Subscription invoices, separate from garment sale payments."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SaaSInvoice(Base):
    __tablename__='saas_invoices'
    id: Mapped[str]=mapped_column(String(120),primary_key=True)
    tenant_id: Mapped[int]=mapped_column(ForeignKey('saas_tenants.id',ondelete='RESTRICT'),index=True)
    subscription_id: Mapped[str]=mapped_column(String(120))
    number: Mapped[str | None]=mapped_column(String(120))
    plan_name: Mapped[str | None]=mapped_column(String(160))
    status: Mapped[str]=mapped_column(String(25))
    currency: Mapped[str]=mapped_column(String(3))
    amount_due_minor: Mapped[int]=mapped_column(BigInteger,default=0)
    amount_paid_minor: Mapped[int]=mapped_column(BigInteger,default=0)
    amount_remaining_minor: Mapped[int]=mapped_column(BigInteger,default=0)
    attempt_count: Mapped[int]=mapped_column(Integer,default=0)
    livemode: Mapped[bool]=mapped_column(Boolean,default=False)
    hosted_url: Mapped[str | None]=mapped_column(String(1500))
    pdf_url: Mapped[str | None]=mapped_column(String(1500))
    issued_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    paid_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
    __table_args__=(CheckConstraint('amount_due_minor >= 0 AND amount_paid_minor >= 0 AND amount_remaining_minor >= 0',name='ck_saas_invoice_amounts'),)
