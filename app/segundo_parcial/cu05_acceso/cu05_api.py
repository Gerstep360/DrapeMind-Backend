from fastapi import APIRouter
from app.segundo_parcial.compartido.saas import (
    Depends,
    HTTPException,
    LoginRequest,
    SaaSPlan,
    Session,
    Tenant,
    TenantSubscription,
    TokenResponse,
    User,
    UserStatus,
    create_access_token,
    datetime,
    func,
    get_db,
    select,
    system_scope,
    timezone,
    verify_password,
)

router = APIRouter(prefix="/saas", tags=["CU-05 · acceso"])


@router.post("/platform/login", response_model=TokenResponse, deprecated=True)
def login_platform(payload: LoginRequest, db: Session = Depends(get_db)):
    with system_scope(db):
        user = db.scalar(
            select(User).where(
                User.is_platform_admin.is_(True),
                User.tenant_id.is_(None),
                func.lower(User.email) == str(payload.email).lower(),
            )
        )
        if (
            not user
            or user.estado != UserStatus.ACTIVO
            or not verify_password(payload.password, user.password_hash)
        ):
            raise HTTPException(401, "Credenciales de plataforma incorrectas")
        token, expires = create_access_token(user.id, user.rol.value, platform=True)
        return {"access_token": token, "token_type": "bearer", "expires_in": expires}


@router.get("/companies")
def companies(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    query = (
        select(Tenant)
        .join(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
        .join(SaaSPlan, SaaSPlan.id == TenantSubscription.plan_id)
        .where(
            Tenant.active.is_(True),
            SaaSPlan.active.is_(True),
            TenantSubscription.status.in_(("ACTIVE", "TRIALING")),
            TenantSubscription.starts_at <= now,
            TenantSubscription.ends_at > now,
        )
        .order_by(Tenant.name)
        .limit(200)
    )
    return [{"slug": t.slug, "name": t.name} for t in db.scalars(query)]


@router.get("/companies/{slug}")
def company_entry(slug: str, db: Session = Depends(get_db)):
    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))
    )
    if not tenant:
        raise HTTPException(404, "Esta tienda no está disponible")
    return {
        "slug": tenant.slug,
        "name": tenant.name,
        "login_path": "/tienda/" + tenant.slug,
    }
