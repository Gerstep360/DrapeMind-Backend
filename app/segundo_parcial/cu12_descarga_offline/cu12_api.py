from fastapi import APIRouter
from app.segundo_parcial.compartido.catalogo_offline import (
    Branch,
    BranchStaff,
    BranchStock,
    Category,
    City,
    Depends,
    Product,
    ProductVariant,
    Response,
    Role,
    Session,
    User,
    aware,
    datetime,
    digest,
    expire_due_reservations,
    get_db,
    offline_user,
    require_active_subscription,
    select,
    subscription_state,
    timedelta,
    timezone,
)

router = APIRouter(prefix="/offline", tags=["CU-12 · descarga_offline"])


@router.get("/status")
def status(
    response: Response,
    user: User = Depends(offline_user),
    db: Session = Depends(get_db),
):
    require_active_subscription(db, user.tenant_id, "offline")
    response.headers["Cache-Control"] = "no-store"
    return {"owner": f"{user.tenant_id}:{user.id}", "available": True}


@router.get("/bundle")
def download(
    response: Response,
    user: User = Depends(offline_user),
    db: Session = Depends(get_db),
):
    require_active_subscription(db, user.tenant_id, "offline")
    expire_due_reservations(db)
    tenant, sub, _, _ = subscription_state(db, user.tenant_id)
    branches = list(
        db.scalars(select(Branch).where(Branch.activo.is_(True)).order_by(Branch.id))
    )
    if user.rol not in (Role.ADMIN, Role.CLIENTE):
        allowed = set(
            db.scalars(
                select(BranchStaff.sucursal_id).where(
                    BranchStaff.usuario_id == user.id, BranchStaff.activo.is_(True)
                )
            )
        )
        branches = [b for b in branches if b.id in allowed]
    branch_ids = [b.id for b in branches]
    products = list(
        db.scalars(select(Product).where(Product.activo.is_(True)).order_by(Product.id))
    )
    product_ids = [p.id for p in products]
    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(
                ProductVariant.activo.is_(True),
                ProductVariant.producto_id.in_(product_ids),
            )
            .order_by(ProductVariant.id)
        )
    )
    variant_ids = [v.id for v in variants]
    categories = list(db.scalars(select(Category).where(Category.activo.is_(True))))
    cities = {c.id: c.nombre for c in db.scalars(select(City))}
    data = {
        "products": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "descripcion": p.descripcion,
                "categoria_id": p.categoria_id,
                "marca": p.marca,
                "material": p.material,
                "genero_objetivo": p.genero_objetivo.value,
                "precio": str(p.precio),
                "imagenes": p.imagenes or [],
            }
            for p in products
        ],
        "variants": [
            {
                "id": v.id,
                "producto_id": v.producto_id,
                "sku": v.sku,
                "talla": v.talla,
                "color": v.color,
                "imagen": v.imagen,
            }
            for v in variants
        ],
        "categories": [{"id": c.id, "nombre": c.nombre} for c in categories],
        "branches": [
            {
                "id": b.id,
                "nombre": b.nombre,
                "direccion": b.direccion,
                "ciudad": cities.get(b.ciudad_id, ""),
            }
            for b in branches
        ],
        "stock": [
            {
                "sucursal_id": s.sucursal_id,
                "variante_id": s.variante_id,
                "disponible": max(0, s.stock_total - s.stock_reservado),
            }
            for s in db.scalars(
                select(BranchStock).where(
                    BranchStock.activo.is_(True),
                    BranchStock.sucursal_id.in_(branch_ids),
                    BranchStock.variante_id.in_(variant_ids),
                )
            )
        ],
    }
    if user.rol in (Role.ADMIN, Role.ENCARGADO, Role.CAJERO):
        from app.segundo_parcial.compartido.sincronizacion import attending_snapshots

        data["reservations"] = attending_snapshots(db, user)
    else:
        data["reservations"] = []
    now = datetime.now(timezone.utc)
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": 1,
        "owner": f"{user.tenant_id}:{user.id}",
        "tenant_id": user.tenant_id,
        "user_id": user.id,
        "tenant_name": tenant.name,
        "version": digest(data),
        "downloaded_at": now,
        "valid_until": min(now + timedelta(hours=24), aware(sub.ends_at)),
        **data,
    }
