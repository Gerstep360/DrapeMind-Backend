"""Shared-database SaaS control plane and tenant ownership contract."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, declared_attr
from app.db.base import Base


class TenantOwned:
    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        return mapped_column(BigInteger, ForeignKey('saas_tenants.id', ondelete='RESTRICT'), nullable=False, index=True)


class Tenant(Base):
    __tablename__ = 'saas_tenants'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('usuarios.id', use_alter=True, name='fk_saas_admin_user'))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SaaSPlan(Base):
    __tablename__ = 'saas_plans'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    max_branches: Mapped[int] = mapped_column(Integer)
    products_sales: Mapped[bool] = mapped_column(Boolean, default=True)
    reservations: Mapped[bool] = mapped_column(Boolean, default=True)
    offline: Mapped[bool] = mapped_column(Boolean, default=True)
    reports: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_reports: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    stripe_product_id: Mapped[str | None] = mapped_column(String(100))
    stripe_annual_price_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    monthly_amount_minor: Mapped[int] = mapped_column(Integer, default=9900)
    annual_amount_minor: Mapped[int] = mapped_column(Integer, default=99000)
    currency: Mapped[str] = mapped_column(String(3), default='bob')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint('max_branches > 0', name='ck_plan_branch_limit'),)


class TenantSubscription(Base):
    __tablename__ = 'saas_subscriptions'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('saas_tenants.id', ondelete='RESTRICT'), unique=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('saas_plans.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(30), default='PENDING')
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(30), default='STRIPE')
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("status IN ('PENDING','ACTIVE','TRIALING','PAST_DUE','CANCELED','UNPAID','SUSPENDED','EXPIRED','LIMIT_EXCEEDED')", name='ck_subscription_state'),)


class BillingEvent(Base):
    __tablename__ = 'saas_billing_events'
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey('saas_tenants.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SaaSPrice(Base):
    __tablename__ = 'saas_prices'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('saas_plans.id', ondelete='RESTRICT'))


class CheckoutAttempt(Base):
    __tablename__ = 'saas_checkout_attempts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('saas_tenants.id', ondelete='RESTRICT'))
    plan_id: Mapped[int] = mapped_column(ForeignKey('saas_plans.id', ondelete='RESTRICT'))
    billing_interval: Mapped[str] = mapped_column(String(10), default='month')
    stripe_session_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def tenant_metadata_constraints(metadata):
    """The database rejects cross-company relationships, including bulk SQL writes."""
    owned = {mapper.local_table.name for mapper in Base.registry.mappers if issubclass(mapper.class_, TenantOwned)}
    from sqlalchemy import ForeignKeyConstraint
    for name in owned:
        table = metadata.tables[name]
        table.append_constraint(UniqueConstraint('id', 'tenant_id', name=f'uq_{name}_id_tenant'))
        for constraint in list(table.foreign_key_constraints):
            if len(constraint.elements) != 1:
                continue
            fk = constraint.elements[0]
            if fk.column.table.name not in owned:
                continue
            target_table, target_column, parent_column = fk.column.table.name, fk.column.name, fk.parent.name
            ondelete = constraint.ondelete if constraint.ondelete != 'SET NULL' else None
            table.constraints.discard(constraint)
            table.foreign_keys.discard(fk)
            fk.parent.foreign_keys.discard(fk)
            table.append_constraint(ForeignKeyConstraint([parent_column, 'tenant_id'], [f'{target_table}.{target_column}', f'{target_table}.tenant_id'], name=f'fk_{name}_{parent_column}_tenant', ondelete=ondelete))
