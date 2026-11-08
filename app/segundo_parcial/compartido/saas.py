from datetime import datetime, timezone
import re
import unicodedata
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.core.tenancy import system_scope
from app.db.session import get_db
from app.db.tenant_session import apply_database_scope
from app.models import User, Role, UserStatus
from app.models.saas import Tenant, SaaSPlan, SaaSPrice, TenantSubscription
from app.schemas.api import LoginRequest, TokenResponse
from app.services.saas import (
    FEATURES,
    tenant_summary,
    plan_payload,
    validate_downgrade,
    aware,
)
from app.services.saas_billing import (
    checkout,
    portal,
    price_details,
    process_billing_event,
)
from app.services.stripe_payments import verify_event


def platform_admin(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not user.is_platform_admin or user.tenant_id is not None:
        raise HTTPException(
            403,
            "Solo el administrador de la plataforma puede gestionar empresas y planes",
        )
    db.info["saas_system"] = True
    apply_database_scope(db)
    return user


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantInput(StrictInput):
    name: str = Field(min_length=2, max_length=150)
    slug: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    admin_name: str = Field(min_length=2, max_length=120)
    admin_email: EmailStr
    admin_password: str = Field(min_length=12, max_length=72)
    plan_id: int = Field(gt=0)
    address: str | None = Field(default=None, max_length=250)
    phone: str | None = Field(default=None, max_length=30)
    contact_email: EmailStr | None = None
    activation: Literal["CHECKOUT", "ADMINISTRATIVE"] = "CHECKOUT"
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def valid_activation(self):
        if not self.name.strip() or not self.admin_name.strip():
            raise ValueError("Completa el nombre de empresa y administrador")
        if self.activation == "ADMINISTRATIVE" and (
            not self.ends_at or aware(self.ends_at) <= datetime.now(timezone.utc)
        ):
            raise ValueError(
                "Elige una fecha de vencimiento futura para activar la licencia"
            )
        return self


class TenantStateInput(StrictInput):
    active: bool


class MerchantDetailsInput(StrictInput):
    name: str = Field(min_length=2, max_length=150)
    address: str | None = Field(default=None, max_length=250)
    phone: str | None = Field(default=None, max_length=30)
    contact_email: EmailStr | None = None


class PlanInput(StrictInput):
    name: str = Field(min_length=2, max_length=80)
    max_branches: int = Field(ge=1, le=10000)
    features: dict[str, bool]
    stripe_price_id: str | None = Field(default=None, pattern=r"^price_[A-Za-z0-9]+$")
    active: bool = True


class LicenseInput(StrictInput):
    plan_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    status: Literal["ACTIVE", "TRIALING", "SUSPENDED", "CANCELED", "EXPIRED"]

    @model_validator(mode="after")
    def dates(self):
        if aware(self.ends_at) <= aware(self.starts_at):
            raise ValueError("El vencimiento debe ser posterior al inicio")
        return self


class CheckoutInput(StrictInput):
    plan_id: int = Field(gt=0)
    billing_interval: Literal["month", "year"] = "month"


class PriceInput(StrictInput):
    amount_minor: int = Field(gt=0, le=100000000)
    currency: Literal["bob", "usd"] = "bob"
    billing_interval: Literal["month", "year"]
