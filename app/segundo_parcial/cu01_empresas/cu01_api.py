from fastapi import APIRouter
from app.segundo_parcial.compartido.saas import (
    Depends,
    HTTPException,
    IntegrityError,
    MerchantDetailsInput,
    Role,
    SaaSPlan,
    Session,
    Tenant,
    TenantInput,
    TenantStateInput,
    TenantSubscription,
    User,
    UserStatus,
    datetime,
    get_db,
    hash_password,
    platform_admin,
    re,
    select,
    tenant_summary,
    timezone,
    unicodedata,
)

router = APIRouter(prefix="/saas", tags=["CU-01 · empresas"])


@router.get("/tenants")
def list_tenants(admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    return [
        tenant_summary(db, t.id) for t in db.scalars(select(Tenant).order_by(Tenant.id))
    ]


@router.post("/tenants", status_code=201)
def create_tenant(
    payload: TenantInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    slug = payload.slug
    if not slug:
        base = (
            re.sub(
                r"[^a-z0-9]+",
                "-",
                unicodedata.normalize("NFKD", payload.name)
                .encode("ascii", "ignore")
                .decode()
                .lower(),
            ).strip("-")[:65]
            or "tienda"
        )
        if len(base) < 2:
            base = "tienda-" + base
        slug = base
        number = 2
        while db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
            slug = f"{base}-{number}"
            number += 1
    if db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        raise HTTPException(
            409,
            "Este enlace ya pertenece a otra tienda. Elige otro nombre para el enlace.",
        )
    plan = db.get(SaaSPlan, payload.plan_id)
    if not plan or not plan.active:
        raise HTTPException(404, "Plan no encontrado")
    try:
        tenant = Tenant(
            name=payload.name.strip(),
            slug=slug,
            active=True,
            address=payload.address,
            phone=payload.phone,
            contact_email=str(payload.contact_email) if payload.contact_email else None,
        )
        db.add(tenant)
        db.flush()
        owner = User(
            tenant_id=tenant.id,
            is_platform_admin=False,
            nombre=payload.admin_name,
            email=str(payload.admin_email).lower(),
            password_hash=hash_password(payload.admin_password),
            rol=Role.ADMIN,
            estado=UserStatus.ACTIVO,
        )
        db.add(owner)
        db.flush()
        tenant.admin_user_id = owner.id
        direct = payload.activation == "ADMINISTRATIVE"
        db.add(
            TenantSubscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status="ACTIVE" if direct else "PENDING",
                source="ADMINISTRATIVE" if direct else "STRIPE",
                starts_at=datetime.now(timezone.utc) if direct else None,
                ends_at=payload.ends_at if direct else None,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "La empresa o su administrador ya están registrados")
    except Exception:
        db.rollback()
        raise
    return tenant_summary(db, tenant.id)


@router.patch("/tenants/{tenant_id}")
def tenant_state(
    tenant_id: int,
    payload: TenantStateInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Empresa no encontrada")
    tenant.active = payload.active
    db.commit()
    return tenant_summary(db, tenant_id)


@router.put("/tenants/{tenant_id}/details")
def merchant_details(
    tenant_id: int,
    payload: MerchantDetailsInput,
    admin: User = Depends(platform_admin),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Empresa no encontrada")
    if not payload.name.strip():
        raise HTTPException(422, "Escribe el nombre comercial")
    for key, value in payload.model_dump().items():
        setattr(tenant, key, str(value).strip() if value is not None else None)
    db.commit()
    return tenant_summary(db, tenant_id)
